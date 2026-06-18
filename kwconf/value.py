from __future__ import annotations

import re
from typing import Any, Callable, cast, Optional, TypeVar, Union, overload

from collections.abc import MutableMapping, Sequence

import ubelt as ub


long_prefix_pat: re.Pattern[str] = re.compile('--[^-].*')
short_prefix_pat: re.Pattern[str] = re.compile('-[^-].*')


class _FactoryUnset:
    """
    Sentinel for a ``default_factory`` Value whose representative template
    value has not been materialized yet.

    The factory is intentionally *not* run at class-definition time (see
    ``_Value.__init__``); it is invoked lazily on the first read of
    ``Value.value`` and cached on the template. Per-instance freshness is a
    separate guarantee provided by ``clone_default``. The sentinel is a
    copy/deepcopy-safe singleton and is falsy so attribute-introspection code
    (e.g. ``_to_value_kw``) skips it.
    """
    _instance: "Optional[_FactoryUnset]" = None

    def __new__(cls) -> "_FactoryUnset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return '<FACTORY_UNSET>'

    def __bool__(self) -> bool:
        return False

    def __copy__(self) -> "_FactoryUnset":
        return self

    def __deepcopy__(self, memo: Any) -> "_FactoryUnset":
        return self

    def __reduce__(self) -> Any:
        return (_FactoryUnset, ())


_FACTORY_UNSET = _FactoryUnset()


def normalize_option_str(s: str) -> str:
    return s.lstrip('-').replace('-', '_')


def _yaml_safe_load(value: str) -> Any:
    """Parse a string as YAML, used as the callable for ``type='yaml'``."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "type='yaml' requires PyYAML. Install with `pip install pyyaml`."
        ) from exc
    return yaml.safe_load(value)


# Registry of named string types accepted as ``Value(type=<name>)``.
# Each parser takes a string and returns the parsed value. The same callable
# is set as the argparse ``type`` so CLI tokens parse the same way.
_NAMED_TYPE_PARSERS: dict[str, Callable[[str], Any]] = {
    'yaml': _yaml_safe_load,
}
_NAMED_TYPE_PARSER_SET: set[Callable[[str], Any]] = set(_NAMED_TYPE_PARSERS.values())


def _resolve_named_type(type_: Any) -> Any:
    """If ``type_`` is a known named-type sentinel string, resolve to its
    callable parser. Otherwise return ``type_`` unchanged."""
    if isinstance(type_, str):
        try:
            return _NAMED_TYPE_PARSERS[type_]
        except KeyError as exc:
            raise TypeError(
                f'Unknown named Value type {type_!r}. '
                f'Known names: {sorted(_NAMED_TYPE_PARSERS)}. '
                f'Use a callable for custom coercion.'
            ) from exc
    return type_


__note__ = """
TODO:
    After we remove 3.6 support, deprecate position and add the ispositional
    argument. Or maybe just "positional"?

    ispositional (bool):
        if True the argument will be treated as a positional argument with
        its order determined by its location in the config.

"""


class _Value(ub.NiceRepr):
    """
    You may set any item in the config's default to an instance of this class.
    Using this class allows you to declare the desired default value as well as
    the type that the value should be (Used when parsing sys.argv).

    Attributes:
        value (Any):
            A float, int, etc...

        parser (Callable | str | None):
            How to parse a *string* input into a value (the text-boundary
            parser). Either a callable ``str -> value``, or a registry key such
            as ``'auto'`` (annotation-gated; the eventual default), ``'yaml'``,
            or ``'csv'``. See :mod:`kwconf.coerce`. Preferred over ``type``;
            mutually exclusive with it.

        type (type | None):
            DEPRECATED alias kept for back-compat. Sets the argparse ``type``
            and the legacy smartcast coercion. Prefer ``parser=`` for new code;
            mutually exclusive with ``parser``.

        parsekw (dict):
            kwargs for to argparse add_argument

        position (None | int):
            if an integer, then we allow this value to be a positional argument
            in the argparse CLI. Note, that values with the same position index
            will cause conflicts. Also note: positions indexes should start
            from 1.

        isflag (bool | str): if True, args will be parsed as booleans.
            Default to False. Can also be "counter".

        alias (list[str] | None):
            other long names (that will be prefixed with '--') that will be
            accepted by the argparse CLI.

        short_alias (list[str] | None):
            other short names (that will be prefixed with '-') that will be
            accepted by the argparse CLI. e.g. ``short_alias=['n']``

        group (str | None):
            Impacts display of underlying argparse object by grouping values
            with the same type together. There is no other impact.

        mutex_group (str | None):
            Indicates that only one of the values in a group should be given on
            the command line. This has no impact on python usage.

        tags (Any):
            for external program use

        help (str | None):
            CLI help text shown for this option.

        choices (Sequence | None):
            Restrict accepted CLI values to this set (argparse ``choices``).

        nargs (int | str | None):
            argparse ``nargs`` for this option (e.g. ``'+'``, ``'*'``, ``'?'``,
            or an integer count).

        required (bool):
            If True, the CLI requires this option to be supplied.

        default_factory (Callable[[], Any] | None):
            A zero-argument callable that produces the default value; mutually
            exclusive with a positional ``default``. Use for mutable defaults
            (e.g. ``default_factory=list``).

        validate (bool | str | None):
            Opt into post-coerce annotation validation for this field. ``None``
            inherits the owning class's ``__validate__``; ``'warn'`` warns on a
            mismatch; ``'error'`` / ``True`` raises; ``False`` disables it.

    CommandLine:
        xdoctest -m kwconf.value _Value

    Example:
        >>> from kwconf.value import _Value
        >>> self = _Value(None, type=float)
        >>> print('self.value = {!r}'.format(self.value))
        self.value = None
        >>> self.update('3.3')
        >>> print('self.value = {!r}'.format(self.value))
        self.value = 3.3
    """

    def __init__(self,
                 default: Any = ub.NoParam,
                 type: Any = None,
                 help: Optional[str] = None,
                 choices: Sequence[Any] | None = None,
                 position: Optional[int] = None,
                 isflag: Union[bool, str] = False,
                 nargs: Optional[Any] = None,
                 alias: Sequence[str] | None = None,
                 required: bool = False,
                 short_alias: Sequence[str] | None = None,
                 group: Optional[str] = None,
                 mutex_group: Optional[str] = None,
                 tags: Optional[Any] = None,
                 *,
                 default_factory: Callable[[], Any] | None = None,
                 parser: Any = None,
                 validate: Optional[Union[bool, str]] = None) -> None:

        if default_factory is not None and default is not ub.NoParam:
            raise ValueError('Error: default_factory is mutually exclusive with default')

        if parser is not None and type is not None:
            raise ValueError(
                'Value: pass either `parser` (preferred) or the deprecated '
                '`type`, not both.')

        # Whether the user explicitly passed ``type=`` (deprecated). The
        # metaclass also populates ``self.type`` from a field annotation, so we
        # capture user intent here, before that happens, to decide whether
        # coerce() should use the legacy ``type`` path or the default 'auto'.
        self._user_gave_type: bool = type is not None

        type = _resolve_named_type(type)

        self.value = None
        self.type = type
        self.alias = alias
        self.position = position
        self.isflag = isflag
        self.parsekw: dict[str, Any] = {
            'help': help,
            'type': type,
            'choices': choices,
            'nargs': nargs,
        }
        self.group = group
        self.mutex_group = mutex_group
        self.required = required
        self.short_alias = short_alias
        self.tags = tags
        self.default_factory = default_factory
        # ``validate`` opts this Value into post-coerce annotation
        # validation. ``None`` means "inherit from the owning class's
        # ``__validate__`` attribute"; ``False`` disables validation
        # for this field even if the class enables it.
        self.validate: Optional[Union[bool, str]] = validate
        # Populated by the metaclass when the Value is attached to a
        # class with a matching annotation. ``None`` means no annotation
        # was associated, so validation is a no-op.
        self._annotation: Any = None
        # New-style parser spec (see kwconf.coerce). ``None`` means
        # "unset": fall back to the legacy ``type``/smartcast path. A
        # callable or registry-string (e.g. 'auto', 'yaml', 'csv') routes
        # string coercion through kwconf.coerce instead. This is the
        # forward-looking replacement for ``type=``; both coexist for now.
        self._parser_spec: Any = parser

        # default_factory is deferred, NOT run here: invoking it at
        # class-definition time would be wasteful (the result is only ever a
        # representative template value) and would prematurely trigger any
        # cost/side-effects of the factory. It is materialized lazily on the
        # first read of ``.value`` (see the ``value`` property) and, crucially,
        # re-invoked per Config instance by ``clone_default`` so mutable
        # defaults are never shared.
        if default_factory is not None:
            self._value: Any = _FACTORY_UNSET
        elif default is not ub.NoParam:
            # BOUNDARY (design.md §4): the default is a Python-boundary value and
            # is stored verbatim (WYSIWYG). It is NOT run through coerce(), so
            # ``Value('512')`` keeps the string ``'512'``. Coercion happens only
            # at the text boundary (argv/env/Config.coerce()).
            self._value = default
        else:
            self._value = None

        # if __debug__:
        #     self._check_values()

        # TODO: opposite
        # for use with flags, this indicates that there is another variable
        # that should always be the opposite of this one.
        # i.e. force / dry
        # i.e. verbose / quiet

    def _check_values(self) -> None:
        """
        We try to avoid runtime checks as much as possible, but they can be
        useful to enable in some circumstances. But we put them in a separate
        function so they are easy to enable / disable.
        """
        if self.short_alias is not None:
            short_alias: Sequence[str] = self.short_alias
            _short_alias: list[str] = cast(list[str], [short_alias] if isinstance(short_alias, str) else short_alias)
            for v in _short_alias:
                if v.startswith('-'):
                    import warnings
                    warnings.warn('Do not prefix short aliases with a -, it is implicit')

    def __nice__(self) -> str:
        # return '{!r}: {!r}'.format(self.type, self.value)
        return f'{self.value!r}'

    @property
    def value(self) -> Any:
        """
        The template's current value. For ``default_factory`` fields this
        materializes the factory lazily on first access and caches the result
        (per-instance fresh values are produced separately by
        ``clone_default``).
        """
        val = self._value
        if val is _FACTORY_UNSET:
            val = self._value = self.default_factory()  # type: ignore[misc]
        return val

    @value.setter
    def value(self, val: Any) -> None:
        self._value = val

    def update(self, value: Any) -> "_Value":
        self.value = self.coerce(value)
        return self

    def coerce(self, value: Any) -> Any:
        """
        Best-effort coercion of ``value`` toward this Value's expected runtime
        type. The name is deliberate: this is not a clean type-cast.

        Strings are parsed via :mod:`kwconf.coerce` (the ``'auto'`` parser by
        default, gated by the field annotation). kwconf intentionally departs
        from scriptconfig: comma-separated strings are NOT auto-split into lists
        -- ``"a,b"`` stays the literal string. To get a list use ``nargs`` or
        ``parser='csv'``/``'yaml'``.

        Non-strings pass through untouched. The deprecated ``type=`` kwarg is
        mapped onto the same machinery; ``type='yaml'`` routes through the
        registered yaml parser.
        """
        if isinstance(value, str):
            from kwconf import coerce as _coerce_mod
            if self._parser_spec is not None:
                # Explicit parser= spec. 'auto' is gated by the field
                # annotation; named/callable specs ignore it.
                return _coerce_mod.coerce(value, annotation=self._annotation,
                                          spec=self._parser_spec)
            if self._user_gave_type:
                # Deprecated explicit type= path, mapped onto kwconf.coerce
                # (smartcast has been retired). Named parsers (e.g. 'yaml') and
                # plain types go through the annotation-gated parser; any other
                # callable is invoked directly.
                if self.type in _NAMED_TYPE_PARSER_SET:
                    return self.type(value)
                if isinstance(self.type, type):
                    return _coerce_mod.auto(value, self.type)
                return self.type(value)
            # Default: the annotation-gated 'auto' parser.
            return _coerce_mod.auto(value, self._annotation)
        return value

    def copy(self) -> "_Value":
        import copy
        return copy.copy(self)

    def clone_default(self) -> "_Value":
        """
        Create a fresh per-instance copy of this value template.
        """
        import copy
        new = self.copy()
        if self.default_factory is not None:
            # BOUNDARY (design.md §4): factory output is a Python-boundary value
            # and is stored verbatim, consistent with __init__.
            new.value = self.default_factory()
        else:
            new.value = copy.deepcopy(self.value)
        return new

    @property
    def help(self) -> Optional[str]:
        # I'm not sure if I want to expose everything in parsekw or not.
        return cast(Optional[str], self.parsekw['help'])

    def _to_value_kw(self) -> MutableMapping[str, Any]:
        """
        Used in port-to-config and port-to-argparse
        """

        value = self
        orig_help = cast(Optional[str], self.parsekw['help'])
        orig_type = cast(Optional[Union[str, type]], self.parsekw['type'])
        value_kw: MutableMapping[str, Any] = {k: v for k, v in self.__dict__.items() if v}
        # The value is stored under the private ``_value`` attribute (it is a
        # lazily-materialized property); expose it under ``value`` so the
        # ordering/pop logic below treats it as before.
        if '_value' in value_kw:
            value_kw['value'] = value_kw.pop('_value')
        value_kw.pop('parsekw')
        value_kw.update(value.parsekw)
        value_kw['help'] = CodeRepr(repr(orig_help))
        value_kw['nargs'] = CodeRepr(repr(value.parsekw['nargs']))
        if orig_type is not None:
            if isinstance(orig_type, str):
                value_kw['type'] = repr(orig_type)
            else:
                value_kw['type'] = CodeRepr(orig_type.__name__)

        value_kw = ub.udict(value_kw)
        order = value_kw & ['value', 'nargs', 'type', 'isflag', 'position', 'required',  # type: ignore
                            'choices', 'alias', 'short_alias', 'group', 'mutex_group',
                            'help']
        value_kw = order | (value_kw - order)
        if value_kw.get('nargs', None) in {None, 'None'}:
            value_kw.pop('nargs', None)

        HACKS = 1
        if HACKS:

            if orig_help and len(orig_help) > 40:
                import textwrap
                wrapped = ub.indent('\n'.join(textwrap.wrap(orig_help, width=60)), ' ' * 4)
                block = ub.codeblock(
                    """
                    ub.paragraph(
                        '''
                    {}
                        ''')
                    """
                ).format(wrapped)
                value_kw['help'] = CodeRepr(ub.indent(block, ' ' * 8).lstrip())
                # "ub.paragraph(\n'''\n{}\n''')".format(ub.indent(value.help, ' ' * 16))
        value_kw['default'] = value.value
        value_kw.pop('value', None)
        return value_kw

    @classmethod
    def _from_action(cls, action, actionid_to_groupkey, actionid_to_mgroupkey,
                     pos_counter):
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
            s for s in action.option_strings
            if long_prefix_pat.match(s)
        ]
        short_option_strings = [
            s for s in action.option_strings
            if short_prefix_pat.match(s)
        ]

        alias_set = ub.oset(normalize_option_str(s)
                            for s in long_option_strings)
        alias: list[str] = list(alias_set - {key})

        short_alias_set = ub.oset(normalize_option_str(s)
                                  for s in short_option_strings)
        short_alias: list[str] = list(short_alias_set - {key})

        real_value_kw = {
            'default': action.default,
            'type': action.type,
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
            if action.nargs is not None:
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


class _Flag(_Value):
    """
    Exactly the same as a Value except isflag default to True
    """
    def __init__(self, default: Any = False, **kwargs: Any) -> None:
        isflag = kwargs.get('isflag', True)
        assert isflag, 'Cannot disable isflag on a Flag value'
        kwargs['isflag'] = isflag
        super().__init__(default=default, **kwargs)


_T = TypeVar('_T')


# The classes above (``_Value`` / ``_Flag``) are the runtime field-metadata
# wrappers. The PUBLIC API is these factory *functions*: they construct one of
# those classes but are typed to return the field's value type ``T`` (the attrs
# ``field()`` pattern), so ``x: int = Value(None)`` is a static type error and
# ``cfg.x`` reads as ``int``. Two overloads give precise inference: from a
# positional/keyword ``default`` (``T`` = the default's type), or from
# ``default_factory`` (``T`` = the factory's return type, even with no
# annotation). Internals keep constructing / isinstance-checking ``_Value`` /
# ``_Flag`` directly.
@overload
def Value(
    default: _T = ...,
    type: Any = ...,
    help: Optional[str] = ...,
    choices: Sequence[Any] | None = ...,
    position: Optional[int] = ...,
    isflag: Union[bool, str] = ...,
    nargs: Optional[Any] = ...,
    alias: Sequence[str] | None = ...,
    required: bool = ...,
    short_alias: Sequence[str] | None = ...,
    group: Optional[str] = ...,
    mutex_group: Optional[str] = ...,
    tags: Optional[Any] = ...,
    *,
    default_factory: None = ...,
    parser: Any = ...,
    validate: Optional[Union[bool, str]] = ...,
) -> _T: ...
@overload
def Value(
    *,
    default_factory: Callable[[], _T],
    type: Any = ...,
    help: Optional[str] = ...,
    choices: Sequence[Any] | None = ...,
    position: Optional[int] = ...,
    isflag: Union[bool, str] = ...,
    nargs: Optional[Any] = ...,
    alias: Sequence[str] | None = ...,
    required: bool = ...,
    short_alias: Sequence[str] | None = ...,
    group: Optional[str] = ...,
    mutex_group: Optional[str] = ...,
    tags: Optional[Any] = ...,
    parser: Any = ...,
    validate: Optional[Union[bool, str]] = ...,
) -> _T: ...
def Value(
    default: Any = ub.NoParam,
    type: Any = None,
    help: Optional[str] = None,
    choices: Sequence[Any] | None = None,
    position: Optional[int] = None,
    isflag: Union[bool, str] = False,
    nargs: Optional[Any] = None,
    alias: Sequence[str] | None = None,
    required: bool = False,
    short_alias: Sequence[str] | None = None,
    group: Optional[str] = None,
    mutex_group: Optional[str] = None,
    tags: Optional[Any] = None,
    *,
    default_factory: Optional[Callable[[], Any]] = None,
    parser: Any = None,
    validate: Optional[Union[bool, str]] = None,
) -> Any:
    """
    Declare a config field, attaching CLI / parsing metadata to a default value.

    Returns a :class:`_Value` wrapper at runtime, but is *typed* as the field's
    value type ``T`` so the default is checked against the field annotation
    (``x: int = Value(None)`` is a static error) and ``cfg.x`` reads as ``int``.
    Use a bare attribute (``x: int = 5``) when you need no metadata.

    Args:
        default (T):
            The default value. Omit for a required field (``required=True``) or
            when using ``default_factory``. A *string* default is parsed only at
            the text boundary, never on plain Python assignment.

        type (type | str | Callable | None):
            DEPRECATED alias for ``parser`` (kept for back-compat); mutually
            exclusive with it. Also sets the argparse ``type``.

        help (str | None):
            CLI help text for this option.

        choices (Sequence | None):
            Restrict accepted CLI values to this set (argparse ``choices``).

        position (int | None):
            Allow this field as a positional CLI argument at this 1-based index.

        isflag (bool | str):
            If True, parse as a boolean flag; ``'counter'`` for a count flag.
            Prefer :func:`Flag` for boolean flags.

        nargs (int | str | None):
            argparse ``nargs`` (e.g. ``'+'``, ``'*'``, ``'?'``, or an int). For
            container fields each token is coerced as the element type.

        alias (Sequence[str] | None):
            Additional long option names (each prefixed with ``--``).

        required (bool):
            If True, the CLI requires this option. Mutually exclusive with a
            supplied default.

        short_alias (Sequence[str] | None):
            Short option names (each prefixed with ``-``), e.g. ``['n']``.

        group (str | None):
            Display-only: group options together in CLI help.

        mutex_group (str | None):
            Mark options mutually exclusive on the command line.

        tags (Any):
            Free-form metadata for external program use.

        default_factory (Callable[[], T] | None):
            Zero-argument callable producing the default; mutually exclusive with
            ``default``. Use for mutable defaults (e.g. ``default_factory=list``).
            ``T`` is inferred from the factory's return type.

        parser (Callable | str | None):
            How to parse a *string* input into a value (the text-boundary
            parser): a callable ``str -> value`` or a registry key such as
            ``'auto'`` (annotation-gated, the default), ``'yaml'``, or ``'csv'``.
            See :mod:`kwconf.coerce`. Preferred over ``type``.

        validate (bool | str | None):
            Opt into post-coerce annotation validation. ``None`` inherits the
            class ``__validate__``; ``'warn'`` warns; ``'error'`` / ``True``
            raises; ``False`` disables.

    Returns:
        T: typed as the field value type (a ``_Value`` wrapper at runtime).

    Example:
        >>> import kwconf
        >>> class Cfg(kwconf.Config):
        >>>     epochs: int = kwconf.Value(10, help='number of epochs')
        >>>     name: str | None = kwconf.Value(None, alias=['n'])
        >>>     tags: list = kwconf.Value(default_factory=list)
        >>> assert Cfg(epochs=3)['epochs'] == 3
    """
    return _Value(
        default, type=type, help=help, choices=choices, position=position,
        isflag=isflag, nargs=nargs, alias=alias, required=required,
        short_alias=short_alias, group=group, mutex_group=mutex_group,
        tags=tags, default_factory=default_factory, parser=parser,
        validate=validate,
    )


def Flag(
    default: bool = False,
    help: Optional[str] = None,
    *,
    alias: Sequence[str] | None = None,
    short_alias: Sequence[str] | None = None,
    group: Optional[str] = None,
    mutex_group: Optional[str] = None,
    required: bool = False,
    position: Optional[int] = None,
    tags: Optional[Any] = None,
    parser: Any = None,
    validate: Optional[Union[bool, str]] = None,
) -> bool:
    """
    Declare a boolean flag field: like :func:`Value` but with flag semantics
    (supports both ``--flag`` and ``--flag=value`` on the CLI). Typed to return
    ``bool``. See :func:`Value` for the shared keyword arguments.
    """
    return cast(bool, _Flag(
        default, help=help, alias=alias, short_alias=short_alias, group=group,
        mutex_group=mutex_group, required=required, position=position,
        tags=tags, parser=parser, validate=validate,
    ))


def _value_add_argument_to_parser(value: Any, _value: Optional[_Value], self: Any, parser: Any, key: str, fuzzy_hyphens: int | bool = False) -> None:
    """
    POC for a new simplified way for a value to add itself as an argument to a
    parser.

    Args:
        value (Any): the unwrapped default value
        _value (Value): the value metadata
        self (Config): the parent kwconf object
        parser (ArgumentParser): the parser to add to
        key (str) : the name or destination
        fuzzy_hyphens (bool | int): enable fuzzy hyphens or not
    """
    # import argparse
    from kwconf import argparse_ext

    # value: Any | Value
    name: str = key
    argkw: dict[str, Any] = {}
    argkw['help'] = ''
    positional: Optional[int] = None
    isflag: bool | str = False
    required: bool = False

    group_lut: dict[str, Any] = getattr(parser, '_sc_group_lut', {})
    mutex_group_lut: dict[str, Any] = getattr(parser, '_sc_mutex_group_lut', {})
    parser._sc_mutex_group_lut = mutex_group_lut
    parser._sc_group_lut = group_lut

    parent: Any = parser
    if _value is not None:
        # Use the metadata in the Value class to enhance argparse
        # _value = _metadata[name]
        argkw.update(_value.parsekw)
        required = _value.required
        value = _value.value
        isflag = _value.isflag
        positional = _value.position

        # If the args are flagged as belonging to a group, resepct that.
        if _value.group is not None:
            if _value.group not in group_lut:
                groupkw: dict[str, Any] = {}
                if isinstance(_value.group, str):
                    groupkw['title'] = _value.group
                group_lut[_value.group] = parent.add_argument_group(**groupkw)
            parent = group_lut[_value.group]

        if _value.mutex_group is not None:
            if _value.mutex_group not in mutex_group_lut:
                mutex_group_lut[_value.mutex_group] = parent.add_mutually_exclusive_group()
            parent = mutex_group_lut[_value.mutex_group]

    if not argkw['help']:
        # argkw['help'] = '<undocumented>'
        argkw['help'] = ''

    argkw['default'] = value
    argkw['action'] = _maker_smart_parse_action(self)

    if not isflag:
        # Route CLI conversion through the field's coerce() (the annotation-
        # gated 'auto' parser / deprecated type= / coerce=), so CLI parsing
        # matches Config.coerce() and honors unions. With no argparse ``type``
        # set, the ParseAction installs a _smart_type that calls
        # template.coerce() for scalars and per-element coercion for nargs
        # fields. Flag fields keep their own (argparse_ext) handling.
        argkw.pop('type', None)

    if positional:
        parent.add_argument(name, **argkw)

    argkw['dest'] = name

    option_strings: list[str] = _resolve_alias(name, _value, fuzzy_hyphens)

    if isflag:
        # Can we support both flag and setitem methods of cli
        # parsing?
        # argkw.pop('type', None)
        argkw.pop('choices', None)
        argkw.pop('action', None)
        argkw.pop('nargs', None)
        argkw['dest'] = name

        if isflag == 'counter':
            argkw['action'] = argparse_ext.CounterOrKeyValAction
        else:
            argkw['action'] = argparse_ext.BooleanFlagOrKeyValAction

    if argkw.get('nargs', None) is not None and argkw.get('type', None) in {list, tuple, set, frozenset}:
        # argparse applies ``type`` to each token, so collection types here
        # would split strings into characters instead of preserving argv items.
        argkw.pop('type', None)

    if isinstance(argkw.get('type', None), str):
        # Named-type sentinels (e.g. 'yaml') should have been resolved to
        # callables in ``Value.__init__``. Anything still a string here is
        # either an unsupported sentinel or a value built via a code path
        # that bypasses the resolver.
        raise TypeError(
            f'Value type must be a callable or None at parser-build time, '
            f'got the string {argkw["type"]!r}. Named-type sentinels are '
            f'resolved in Value.__init__; if you reached this branch the '
            f'string was set after construction.'
        )

    try:
        parent.add_argument(*option_strings, required=required, **argkw)
    except Exception:
        print('ERROR: Failed to add argument (in _value_add_argument_to_parser / Config.argparse)')
        print('argkw = {}'.format(ub.urepr(argkw, nl=1)))
        print('required = {}'.format(ub.urepr(required, nl=1)))
        print('option_strings = {}'.format(ub.urepr(option_strings, nl=1)))
        raise


def _value_add_argument_kw(value: Any, _value: Optional[_Value], self: Any, key: str, fuzzy_hyphens: int = 0) -> dict[str, tuple]:
    """
    TODO: resolve with :func:`_value_add_argument_to_parser`. This just creates
    one or more kwargs for add_argument. (Depending on how many variants of the
    argument we want).

    Args:
        value (Any): the unwrapped default value
        _value (Value): the value metadata

    Returns:
        Dict[str, Tuple[str, Tuple, Dict]]:
            special keys to the method name, args, kwargs invocations.
    """
    # import argparse
    from kwconf import argparse_ext

    # value: Any | Value
    name: str = key
    argkw: dict[str, Any] = {}
    argkw['help'] = ''
    positional: Optional[int] = None
    isflag: bool | str = False
    required: bool = False

    # group_lut = getattr(parser, '_sc_group_lut', {})
    # mutex_group_lut = getattr(parser, '_sc_mutex_group_lut', {})
    # parser._sc_mutex_group_lut = mutex_group_lut
    # parser._sc_group_lut = group_lut

    invocations: dict[str, tuple] = {}

    # parent = parser
    if _value is not None:
        # Use the metadata in the Value class to enhance argparse
        # _value = _metadata[name]
        argkw.update(_value.parsekw)
        required = _value.required
        value = _value.value
        isflag = _value.isflag
        positional = _value.position

        # TODO: handle groups
        # If the args are flagged as belonging to a group, resepct that.
        # if _value.group is not None:
        #     if _value.group not in group_lut:
        #         groupkw = {}
        #         if isinstance(_value.group, str):
        #             groupkw['title'] = _value.group
        #         group_lut[_value.group] = parent.add_argument_group(**groupkw)
        #     parent = group_lut[_value.group]

        # if _value.mutex_group is not None:
        #     if _value.mutex_group not in mutex_group_lut:
        #         mutex_group_lut[_value.mutex_group] = parent.add_mutually_exclusive_group()
        #     parent = mutex_group_lut[_value.mutex_group]

    if not argkw['help']:
        # argkw['help'] = '<undocumented>'
        argkw['help'] = ''

    argkw['default'] = value
    argkw['action'] = _maker_smart_parse_action(self)

    if positional:
        invocations['positional'] = (
            'add_argument',
            (name,),
            argkw.copy(),
        )

    argkw['dest'] = name

    option_strings: list[str] = _resolve_alias(name, _value, fuzzy_hyphens)

    if isflag:
        # Can we support both flag and setitem methods of cli
        # parsing?
        argkw.pop('type', None)
        argkw.pop('choices', None)
        argkw.pop('action', None)
        argkw.pop('nargs', None)
        argkw['dest'] = name

        if isflag == 'counter':
            argkw['action'] = argparse_ext.CounterOrKeyValAction
        else:
            argkw['action'] = argparse_ext.BooleanFlagOrKeyValAction

    if argkw.get('nargs', None) is not None and argkw.get('type', None) in {list, tuple, set, frozenset}:
        argkw.pop('type', None)

    argkw['required'] = required
    # parent.add_argument(*option_strings, required=required, **argkw)

    invocations['key_value'] = (
        'add_argument',
        option_strings,
        argkw,
    )
    return invocations


def _resolve_alias(name: str, _value: Optional[_Value], fuzzy_hyphens: int | bool) -> list[str]:
    aliases: Optional[Sequence[str]]
    short_aliases: Optional[Sequence[str]]
    if _value is None:
        aliases = None
        short_aliases = None
    else:
        aliases = _value.alias
        short_aliases = _value.short_alias
    if isinstance(aliases, str):
        aliases = [aliases]
    if isinstance(short_aliases, str):
        short_aliases = [short_aliases]
    long_names: list[str] = [name] + list((aliases or []))
    short_names: list[str] = list(short_aliases or [])

    if fuzzy_hyphens:
        # Do we want to allow for people to use hyphens on the CLI?
        # Maybe, we can make it optional.
        unique_long_names: set[str] = set(long_names)
        modified_long_names: set[str] = {n.replace('_', '-') for n in unique_long_names}
        extra_long_names: set[str] = modified_long_names - unique_long_names
        long_names += sorted(extra_long_names)
    short_option_strings: list[str] = ['-' + n for n in short_names]
    long_option_strings: list[str] = ['--' + n for n in long_names]
    option_strings: list[str] = short_option_strings + long_option_strings
    return option_strings


def _maker_smart_parse_action(self):
    import argparse
    from itertools import chain

    kwconf_object = self

    ### TODO: be slightly less smart
    class ParseAction(argparse._StoreAction):
        def __init__(self, *args, **kwargs):
            # required/= kwargs.pop('required', False)
            super().__init__(*args, **kwargs)
            # with script config nothing should be required by default
            # (unless specified) all positional arguments should have
            # keyword arg variants Setting required=False here will prevent
            # positional args from erroring if they are not specified. I
            # dont think there are other side effects, but we should make
            # sure that is actually the case.
            self.required = False  # hack

            if self.type is None:
                # Route conversion through the field's coerce(). For nargs
                # fields argparse calls the converter per token, so coerce each
                # token as the container's element type rather than the
                # (container) field annotation.
                def _smart_type(value):
                    template = kwconf_object.__default__[self.dest]
                    if self.nargs is not None:
                        from kwconf import coerce as _coerce_mod
                        elem = _coerce_mod.element_annotation(
                            getattr(template, '_annotation', None))
                        return _coerce_mod.auto(value, elem)
                    return template.coerce(value)

                self.type = _smart_type

        def __call__(action, parser, namespace, values, option_string=None):
            # print('CALL action = {!r}'.format(action))
            # print('option_string = {!r}'.format(option_string))
            # print('values = {!r}'.format(values))

            if isinstance(values, list) and len(values):
                # We got a list of lists, which we hack into a flat list
                if isinstance(values[0], list):
                    values = list(chain(*values))

            setattr(namespace, action.dest, values)
            if not hasattr(parser, '_explicitly_given'):
                # We might be given a subparser / parent parser
                # and not the original one we created.
                parser._explicitly_given = set()
            parser._explicitly_given.add(action.dest)

    return ParseAction


class CodeRepr(str):
    # When we want to write out the exact code that should be inserted.
    def __repr__(self):
        return self
