"""Cold argparse / code-generation helpers for :mod:`kwconf.value`."""

from __future__ import annotations

from collections.abc import MutableMapping

from kwconf import value as _value_mod
from kwconf._typing_runtime import Any, Callable, Optional, Union, cast
from kwconf.util.util_misc import NoParam
from kwconf.value import _resolve_alias, _Value, normalize_option_str

# This cold module is imported only after kwconf.value is fully initialized.


def _value_to_value_kw(self) -> MutableMapping[str, Any]:
    """
    Used in port-to-config and port-to-argparse
    """

    value = self
    orig_help = cast(Optional[str], self.parsekw['help'])
    orig_type = cast(Optional[Union[str, type]], self.parsekw['type'])
    value_kw: MutableMapping[str, Any] = {
        k: v
        for k, v in self.__dict__.items()
        # Private attributes (_annotation, _parser_spec, _value, ...) are
        # runtime metadata. The concrete default or factory recipe is
        # exposed explicitly below.
        if v and not k.startswith('_') and k != 'default_factory'
    }
    value_kw.pop('parsekw', None)
    value_kw.update(value.parsekw)
    if value.bare is not NoParam:
        # ``bare`` may intentionally be falsy (None / False / 0), so it
        # cannot rely on the truthiness filter above.
        value_kw['bare'] = value.bare
    if orig_help is None:
        # Do not emit a redundant help=None kwarg.
        value_kw.pop('help', None)
    else:
        value_kw['help'] = CodeRepr(repr(orig_help))
    value_kw['nargs'] = CodeRepr(repr(value.parsekw['nargs']))
    if orig_type is not None:
        if isinstance(orig_type, str):
            value_kw['type'] = repr(orig_type)
        else:
            value_kw['type'] = CodeRepr(orig_type.__name__)

    # Move the "known" keys to the front (keeping their existing relative
    # order), then any extra keys after -- matching the prior udict dance.
    _order_keys = {
        'value',
        'nargs',
        'bare',
        'type',
        'isflag',
        'position',
        'required',
        'choices',
        'alias',
        'short_alias',
        'group',
        'mutex_group',
        'help',
    }
    order = {k: v for k, v in value_kw.items() if k in _order_keys}
    rest = {k: v for k, v in value_kw.items() if k not in _order_keys}
    value_kw = {**order, **rest}
    if value_kw.get('nargs', None) in {None, 'None'}:
        value_kw.pop('nargs', None)

    # help stays a plain repr string literal (set above) so emitted code is
    # dependency-free; we no longer wrap it in a ``ub.paragraph(...)`` call.
    if value.default_factory is not None:
        value_kw['default_factory'] = _callable_code_repr(value.default_factory)
    else:
        value_kw['default'] = value.value
    value_kw.pop('value', None)
    return value_kw


def _value_from_action(
    cls, action, actionid_to_groupkey, actionid_to_mgroupkey, pos_counter
):
    """
    Used in port_argparse

    Example:
        import argparse
        from kwconf.value import *  # NOQA
        action = argparse._StoreAction('foo', 'bar', default=3)
        value = _Value._from_action(action, {}, {}, 0)

        action = argparse._CountAction('foo', 'bar')
        value = _Value._from_action(action, {}, {}, 0)
    """
    import argparse

    key = action.dest

    long_option_strings = [
        s
        for s in action.option_strings
        if s.startswith('--') and len(s) > 2 and s[2] != '-'
    ]
    short_option_strings = [
        s
        for s in action.option_strings
        if s.startswith('-')
        and not s.startswith('--')
        and len(s) > 1
        and s[1] != '-'
    ]

    alias_seen = list(
        dict.fromkeys(normalize_option_str(s) for s in long_option_strings)
    )
    alias: list[str] = [a for a in alias_seen if a != key]

    short_alias_seen = list(
        dict.fromkeys(normalize_option_str(s) for s in short_option_strings)
    )
    short_alias: list[str] = [a for a in short_alias_seen if a != key]

    action_type = action.type
    if isinstance(action_type, _SmartValueCoercer):
        # A live kwconf parser uses an internal coercer as argparse's
        # ``type`` callable so all text-boundary conversion still routes
        # through the originating Value.  That implementation detail is
        # not part of the parser's portable configuration surface.  When
        # porting the parser back to a Value, recover the original
        # argparse-facing type instead of serializing the internal
        # coercer object.
        template = action_type.template
        action_type = None if template is None else template.parsekw.get('type')

    real_value_kw = {
        'default': action.default,
        'type': action_type,
        'alias': alias,
        'short_alias': short_alias,
        'required': action.required,
        'choices': action.choices,
        'help': action.help,
    }
    if action.nargs == 0 and action.const is True:
        # This is a boolean flag
        real_value_kw['isflag'] = True
    elif isinstance(action, argparse._CountAction):
        real_value_kw['isflag'] = 'counter'
    else:
        real_value_kw.pop('isflag', None)
        if action.option_strings and action.nargs == '?':
            # Argparse expresses an option with a meaningful bare form as
            # ``nargs='?'`` plus ``const=...``. Port that pair into
            # kwconf's semantic spelling instead of preserving the lower-
            # level argparse representation. ``const=None`` is meaningful
            # and therefore intentionally becomes ``bare=None``.
            real_value_kw['bare'] = action.const
        elif action.nargs is not None:
            real_value_kw['nargs'] = action.nargs
    action_id = id(action)
    if action_id in actionid_to_groupkey:
        real_value_kw['group'] = repr(actionid_to_groupkey[action_id])
    if action_id in actionid_to_mgroupkey:
        real_value_kw['mutex_group'] = repr(actionid_to_mgroupkey[action_id])
    if len(action.option_strings) == 0:
        real_value_kw['position'] = next(pos_counter)
    value = _Value(**real_value_kw)  # type: ignore
    return value


def _value_argument_invocations(
    value: Any,
    template: Optional[_Value],
    key: str,
    fuzzy_hyphens: int | bool = False,
    portable: bool = False,
) -> dict[str, tuple[str, tuple[str, ...], dict[str, Any]]]:
    """Build the canonical argparse calls for one field.

    Both live parser construction and ``port_to_argparse`` consume this single
    representation, preventing their coercion / flag / alias semantics from
    drifting.
    """
    from kwconf import argparse_ext

    name = key
    argkw: dict[str, Any] = {'help': ''}
    positional: Optional[int] = None
    isflag: bool | str = False
    required = False
    if template is not None:
        argkw.update(template.parsekw)
        required = template.required
        isflag = template.isflag
        positional = template.position

    argkw['help'] = argkw.get('help') or ''
    argkw['default'] = value
    argkw['action'] = _get_smart_parse_action()
    if not portable and not isflag:
        argkw['_kwconf_template'] = template

    if not isflag and not portable:
        # ParseAction routes conversion through Value.coerce, so argparse's
        # independent type converter must not run as a second parser.
        argkw.pop('type', None)

    invocations: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {}
    if positional:
        invocations['positional'] = (
            'add_argument',
            (name,),
            argkw.copy(),
        )
        # Positional and key/value variants need independent kwargs because
        # the option path mutates its dictionary below.
        option_kw = argkw.copy()
    else:
        # The common non-positional case owns this kwargs dictionary already.
        option_kw = argkw
    option_kw['dest'] = name
    option_strings = tuple(_resolve_alias(name, template, fuzzy_hyphens))

    if isflag:
        option_kw.pop('type', None)
        option_kw.pop('choices', None)
        option_kw.pop('action', None)
        option_kw.pop('nargs', None)
        if isflag == 'counter':
            option_kw['action'] = argparse_ext.CounterOrKeyValAction
        else:
            option_kw['action'] = argparse_ext.BooleanFlagOrKeyValAction
    elif template is not None and template.bare is not NoParam:
        # ``bare`` is the public semantic abstraction over argparse's
        # ``nargs='?'`` + ``const=...`` pair.
        option_kw['nargs'] = '?'
        option_kw['const'] = template.bare

    if option_kw.get('nargs') is not None and option_kw.get('type') in {
        list,
        tuple,
        set,
        frozenset,
    }:
        option_kw.pop('type', None)

    if isinstance(option_kw.get('type'), str):
        raise TypeError(
            'Value type must be a callable or None at parser-build time, '
            f'got the string {option_kw["type"]!r}. Named-type sentinels '
            'are resolved in Value.__init__; if you reached this branch the '
            'string was set after construction.'
        )

    option_kw['required'] = required
    invocations['key_value'] = ('add_argument', option_strings, option_kw)
    return invocations


def _value_add_argument_to_parser(
    value: Any,
    _value: Optional[_Value],
    self: Any,
    parser: Any,
    key: str,
    fuzzy_hyphens: int | bool = False,
) -> None:
    """Add one field using the canonical invocation representation."""
    group_lut: dict[str, Any] = getattr(parser, '_sc_group_lut', {})
    mutex_group_lut: dict[str, Any] = getattr(parser, '_sc_mutex_group_lut', {})
    parser._sc_group_lut = group_lut
    parser._sc_mutex_group_lut = mutex_group_lut

    parent = parser
    if _value is not None and _value.group is not None:
        if _value.group not in group_lut:
            groupkw = (
                {'title': _value.group} if isinstance(_value.group, str) else {}
            )
            group_lut[_value.group] = parser.add_argument_group(**groupkw)
        parent = group_lut[_value.group]
    if _value is not None and _value.mutex_group is not None:
        if _value.mutex_group not in mutex_group_lut:
            mutex_group_lut[_value.mutex_group] = (
                parent.add_mutually_exclusive_group()
            )
        parent = mutex_group_lut[_value.mutex_group]

    invocations = _value_argument_invocations(
        value, _value, key, fuzzy_hyphens=fuzzy_hyphens
    )
    try:
        for _kind, (method_name, args, kwargs) in invocations.items():
            getattr(parent, method_name)(*args, **kwargs)
    except Exception:
        print(
            'ERROR: Failed to add argument '
            '(in _value_add_argument_to_parser / Config.argparse)'
        )
        print(f'key = {key!r}')
        import pprint

        print(f'invocations = {pprint.pformat(invocations)}')
        raise


def _value_add_argument_kw(
    value: Any,
    _value: Optional[_Value],
    self: Any,
    key: str,
    fuzzy_hyphens: int = 0,
) -> dict[str, tuple]:
    """Return the same canonical calls used by live parser construction."""
    return _value_argument_invocations(
        value,
        _value,
        key,
        fuzzy_hyphens=fuzzy_hyphens,
        portable=True,
    )


class _SmartValueCoercer:
    """Per-field callable used by the shared argparse action.

    This deliberately does not retain a reference to the action itself.
    ``argparse.Action.__repr__`` includes the public ``type`` attribute; using
    a bound action method there makes the action recursively repr itself.
    """

    __slots__ = ('template', 'nargs')

    def __init__(self, template, nargs):
        self.template = template
        self.nargs = nargs

    def __call__(self, value):
        template = self.template
        if template is None:
            return value
        if self.nargs is not None:
            from kwconf import coerce as _coerce_mod

            # With an explicit parser, apply it per token (csv -> list, yaml ->
            # value); argparse collects the results.
            if getattr(template, '_parser_spec', None) is not None:
                return template.coerce(value)
            # Otherwise coerce each token as the container's element type
            # rather than the (container) field annotation.
            elem = _coerce_mod.element_annotation(
                getattr(template, '_annotation', None)
            )
            return _coerce_mod.auto(value, elem)
        return template.coerce(value)


def _get_smart_parse_action():
    """Materialize the argparse Action only when the Python parser is used."""
    smart_parse_action = _value_mod._SmartParseAction
    if smart_parse_action is None:
        import argparse

        class _SmartParseActionImpl(argparse.Action):
            """Shared argparse action for ordinary kwconf values."""

            def __init__(self, *args, _kwconf_template=None, **kwargs):
                self._kwconf_template = _kwconf_template
                super().__init__(*args, **kwargs)
                # Positional fields also have option spellings in kwconf, so
                # the positional action itself must not force presence.
                self.required = False

                if self.type is None:
                    self.type = _SmartValueCoercer(
                        self._kwconf_template, self.nargs
                    )

            def __call__(self, parser, namespace, values, option_string=None):
                setattr(namespace, self.dest, values)
                from kwconf.argparse_ext import mark_explicit

                mark_explicit(parser, namespace, self.dest)

        # Preserve the historical private type name for diagnostics and tests.
        _SmartParseActionImpl.__name__ = '_SmartParseAction'
        _SmartParseActionImpl.__qualname__ = '_SmartParseAction'
        smart_parse_action = _SmartParseActionImpl
        _value_mod._SmartParseAction = smart_parse_action
    return smart_parse_action


class CodeRepr(str):
    # When we want to write out the exact code that should be inserted.
    def __repr__(self):
        return self


def _callable_code_repr(func: Callable[[], Any]) -> CodeRepr:
    """Return executable source for an importable zero-argument factory."""
    import importlib

    module_name = getattr(func, '__module__', None)
    qualname = getattr(func, '__qualname__', None)
    if (
        not module_name
        or module_name == '__main__'
        or not qualname
        or '<' in qualname
    ):
        raise ValueError(
            'port_to_config cannot represent a local, lambda, or dynamically '
            f'constructed default_factory: {func!r}'
        )

    try:
        obj: Any = importlib.import_module(module_name)
        for part in qualname.split('.'):
            obj = getattr(obj, part)
    except Exception as ex:
        raise ValueError(
            f'port_to_config cannot import default_factory {func!r}'
        ) from ex
    if obj is not func:
        raise ValueError(
            'port_to_config requires default_factory to be importable by its '
            f'module and qualified name: {func!r}'
        )

    if module_name == 'builtins':
        expr = qualname
    else:
        expr = f"__import__({module_name!r}, fromlist=['*'])"
        for part in qualname.split('.'):
            expr += f'.{part}'
    return CodeRepr(expr)
