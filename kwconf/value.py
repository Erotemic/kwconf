from __future__ import annotations

from collections.abc import Sequence

from kwconf._typing_runtime import (
    Any,
    Callable,
    Optional,
    TypeVar,
    Union,
    cast,
    overload,
)
from kwconf.util.util_misc import NoParam, copy_value
from kwconf.util.util_repr import NiceRepr


class _LazyValueMethod:
    """Descriptor for cold _Value conversion helpers."""

    __slots__ = ('name', 'kind', '_resolved')

    def __init__(self, name: str, *, kind: str = 'method') -> None:
        self.name = name
        self.kind = kind
        self._resolved = None

    def _resolve(self):
        resolved = self._resolved
        if resolved is None:
            module = __import__('kwconf._value_cold', fromlist=[self.name])
            func = getattr(module, self.name)
            resolved = classmethod(func) if self.kind == 'classmethod' else func
            self._resolved = resolved
        return resolved

    def __get__(self, instance, owner=None):
        return self._resolve().__get__(instance, owner)


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

    _instance: 'Optional[_FactoryUnset]' = None

    def __new__(cls) -> '_FactoryUnset':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return '<FACTORY_UNSET>'

    def __bool__(self) -> bool:
        return False

    def __copy__(self) -> '_FactoryUnset':
        return self

    def __deepcopy__(self, memo: Any) -> '_FactoryUnset':
        return self

    def __reduce__(self) -> Any:
        return (_FactoryUnset, ())


_FACTORY_UNSET = _FactoryUnset()


def normalize_option_str(s: str) -> str:
    return s.lstrip('-').replace('-', '_')


def _yaml_safe_load(value: str) -> Any:
    """Parse a string as YAML, used as the callable for ``type='yaml'``."""
    from kwconf.util.util_yaml import import_yaml

    yaml = import_yaml("type='yaml'")
    return yaml.safe_load(value)


# Registry of named string types accepted as ``Value(type=<name>)``.
# Each parser takes a string and returns the parsed value. The same callable
# is set as the argparse ``type`` so CLI tokens parse the same way.
_NAMED_TYPE_PARSERS: dict[str, Callable[[str], Any]] = {
    'yaml': _yaml_safe_load,
}
_NAMED_TYPE_PARSER_SET: set[Callable[[str], Any]] = set(
    _NAMED_TYPE_PARSERS.values()
)


def _fast_bool_coerce(token: str) -> bool:
    low = token.strip().lower()
    if low in {'true', '1'}:
        return True
    if low in {'false', '0'}:
        return False
    raise ValueError(token)


_FAST_SCALAR_COERCERS = {
    str: str,
    int: int,
    float: float,
    complex: complex,
    bool: _fast_bool_coerce,
}


def _fast_scalar_coerce(token: str, annotation: Any) -> tuple[bool, Any]:
    """Coerce the common builtin annotation without loading coerce.py.

    ``kwconf.coerce.auto`` deliberately keeps the original string when its
    sole candidate cannot parse it; validation is the layer that reports a
    mismatch. Mirror exactly that behavior here.
    """
    parser = _FAST_SCALAR_COERCERS.get(annotation)
    if parser is None:
        return False, token
    try:
        return True, parser(token)
    except (TypeError, ValueError, OverflowError):
        return True, token


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


class _Value(NiceRepr):
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

        bare (Any):
            Value used when this option appears without an explicit value.
            Supplying ``bare=...`` gives the option a kwconf *bare form* and
            implies ``nargs='?'``. Explicit values remain available with
            ``--option=value`` / ``--option value`` and ``-o=value`` /
            ``-o value``. Bare-capable short options do not accept the
            undelimited ``-oVALUE`` spelling when short-alias clustering is
            enabled.

        required (bool):
            If True, the CLI requires this option to be supplied.

        default_factory (Callable[[], Any] | None):
            A zero-argument callable that produces the default value; mutually
            exclusive with a positional ``default``. Use for mutable defaults
            (e.g. ``default_factory=list``).

        validate (bool | str | None):
            Opt into post-coerce annotation validation for this field. ``None``
            inherits the owning class's ``__validate__``; ``'warn'`` warns on a
            mismatch; ``'error'`` / ``True`` raises :class:`ConfigValidationError`;
            ``False`` disables it. An explicit ``Config.cli(validate=...)`` or
            ``Config.load(validate=...)`` policy overrides both field and class
            policy for values ingested by that call. This governs the
            programmatic boundary only;
            a ``Literal`` is still hard-rejected on ``argv``/``env`` by the
            parser (argparse ``choices=``) regardless of ``validate``. See
            :meth:`Config._validate_assignment`.

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

    def __init__(
        self,
        default: Any = NoParam,
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
        bare: Any = NoParam,
        default_factory: Callable[[], Any] | None = None,
        parser: Any = None,
        validate: Optional[Union[bool, str]] = None,
    ) -> None:

        if default_factory is not None and default is not NoParam:
            raise ValueError(
                'Error: default_factory is mutually exclusive with default'
            )

        if parser is not None and type is not None:
            raise ValueError(
                'Value: pass either `parser` (preferred) or the deprecated '
                '`type`, not both.'
            )

        if bare is not NoParam:
            if isflag:
                raise ValueError(
                    'Value(bare=...) is for non-flag values; Flag and counter '
                    'fields already define their own bare behavior.'
                )
            if nargs not in {None, '?'}:
                raise ValueError(
                    "Value(bare=...) implies nargs='?' and is incompatible "
                    f'with nargs={nargs!r}'
                )

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
        self.bare = bare
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
        elif default is not NoParam:
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
            _short_alias: list[str] = cast(
                list[str],
                [short_alias] if isinstance(short_alias, str) else short_alias,
            )
            for v in _short_alias:
                if v.startswith('-'):
                    import warnings

                    warnings.warn(
                        'Do not prefix short aliases with a -, it is implicit'
                    )

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
            # Invariant: _value is _FACTORY_UNSET only when a factory was given
            # (set in __init__), so default_factory is non-None here.
            assert self.default_factory is not None
            val = self._value = self.default_factory()
        return val

    @value.setter
    def value(self, val: Any) -> None:
        self._value = val

    def update(self, value: Any) -> '_Value':
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
            if self._parser_spec is not None:
                # Explicit parser= spec. 'auto' is gated by the field
                # annotation; named/callable specs ignore it.
                if callable(self._parser_spec):
                    # The common explicit ``parser=str/int/float/...`` case
                    # needs no registry or annotation machinery at all. This
                    # avoids importing kwconf.coerce on the common CLI
                    # coercion path for the simplest schemas.
                    return self._parser_spec(value)
                from kwconf import coerce as _coerce_mod

                return _coerce_mod.coerce(
                    value, annotation=self._annotation, spec=self._parser_spec
                )
            if self._user_gave_type:
                # Deprecated explicit type= path, mapped onto kwconf.coerce
                # (smartcast has been retired). Keep the builtin scalar case
                # local so short-lived CLIs do not import the generic registry.
                if self.type in _NAMED_TYPE_PARSER_SET:
                    return self.type(value)
                handled, coerced = _fast_scalar_coerce(value, self.type)
                if handled:
                    return coerced
                if isinstance(self.type, type):
                    from kwconf import coerce as _coerce_mod

                    return _coerce_mod.auto(value, self.type)
                return self.type(value)
            # The future-facing typed syntax overwhelmingly uses builtin
            # scalar annotations. Handle those exactly without importing the
            # generic parser registry; richer annotations still delegate.
            handled, coerced = _fast_scalar_coerce(value, self._annotation)
            if handled:
                return coerced
            from kwconf import coerce as _coerce_mod

            return _coerce_mod.auto(value, self._annotation)
        return value

    def copy(self) -> '_Value':
        # _Value is an internal plain Python metadata object. copy.copy()
        # reaches the same shallow-copy result through generic reconstruction
        # machinery; cloning __dict__ directly is substantially cheaper when
        # configs contain hundreds of fields.
        cls = type(self)
        new = cls.__new__(cls)
        new.__dict__ = self.__dict__.copy()
        return new

    def clone_default(
        self, *, context: str = 'configuration default'
    ) -> '_Value':
        """
        Create a fresh per-instance copy of this value template.
        """
        new = self.copy()
        if self.default_factory is not None:
            # Retain the recipe, not a materialized result. Config reset invokes
            # the factory afresh, matching dataclasses.default_factory and
            # avoiding an undocumented deepcopy requirement on its output.
            new._value = _FACTORY_UNSET
        else:
            new.value = copy_value(self.value, context=context)
        return new

    def _materialize_instance_pair(
        self, *, template_context: str, runtime_context: str
    ) -> tuple['_Value', Any]:
        """Clone instance metadata and materialize its initial runtime value.

        Config construction needs both objects at once. Producing them here
        avoids a second Value dispatch/property walk after ``clone_default``
        while preserving the two-copy ownership rule for mutable concrete
        defaults. Factories remain recipes on the reset template and run once
        for the initial live value.
        """
        new = self.copy()
        if self.default_factory is not None:
            new._value = _FACTORY_UNSET
            runtime_value = self.default_factory()
        else:
            baseline = copy_value(self.value, context=template_context)
            new._value = baseline
            runtime_value = copy_value(baseline, context=runtime_context)
        return new, runtime_value

    @property
    def help(self) -> Optional[str]:
        # I'm not sure if I want to expose everything in parsekw or not.
        return cast(Optional[str], self.parsekw['help'])

    _to_value_kw = _LazyValueMethod('_value_to_value_kw', kind='method')

    _from_action = _LazyValueMethod('_value_from_action', kind='classmethod')


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
    bare: Any = ...,
    default_factory: None = ...,
    parser: Any = ...,
    validate: Optional[Union[bool, str]] = ...,
) -> _T: ...
@overload
def Value(  # noqa: F811
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
    bare: Any = ...,
    parser: Any = ...,
    validate: Optional[Union[bool, str]] = ...,
) -> _T: ...
def Value(  # noqa: F811
    default: Any = NoParam,
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
    bare: Any = NoParam,
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

        bare (Any):
            Define the field's CLI *bare form*. When the option appears without
            an explicit value, use this value. ``bare=...`` implies
            ``nargs='?'``. For example ``Value(None, bare='auto')`` accepts
            ``--key`` as ``'auto'`` while ``--key=file`` and ``--key file``
            remain explicit assignments.

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
            raises :class:`ConfigValidationError`; ``False`` disables. An
            explicit ``Config.cli(validate=...)`` / ``load(validate=...)``
            policy takes precedence for that ingestion. Governs the
            programmatic boundary only; a ``Literal`` is still hard-rejected
            on ``argv``/``env`` by the parser regardless of ``validate``.

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
        default,
        type=type,
        help=help,
        choices=choices,
        position=position,
        isflag=isflag,
        nargs=nargs,
        alias=alias,
        required=required,
        short_alias=short_alias,
        group=group,
        mutex_group=mutex_group,
        tags=tags,
        bare=bare,
        default_factory=default_factory,
        parser=parser,
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
    Declare a boolean flag field: like :func:`Value` but with flag semantics.

    A flag always has a *bare form*: ``--flag`` means true (and ``--no-flag``
    means false), while explicit assignment remains available as
    ``--flag=false`` / ``--flag false`` and ``-f=false`` / ``-f false``. This
    explicit-assignment property is intentional kwconf behavior, not ordinary
    ``argparse`` ``store_true`` semantics.

    Typed to return ``bool``. See :func:`Value` for the shared keyword
    arguments.
    """
    return cast(
        bool,
        _Flag(
            default,
            help=help,
            alias=alias,
            short_alias=short_alias,
            group=group,
            mutex_group=mutex_group,
            required=required,
            position=position,
            tags=tags,
            parser=parser,
            validate=validate,
        ),
    )








def _resolve_alias(
    name: str, _value: Optional[_Value], fuzzy_hyphens: int | bool
) -> list[str]:
    aliases: Optional[Sequence[str]]
    short_aliases: Optional[Sequence[str]]
    if _value is None:
        aliases = None
        short_aliases = None
    else:
        aliases = _value.alias
        short_aliases = _value.short_alias

    # Most fields have only their canonical long name. Avoid allocating the
    # general alias-normalization sets/lists for that common case.
    if not aliases and not short_aliases:
        canonical = '--' + name
        if fuzzy_hyphens and '_' in name:
            fuzzy_name = name.replace('_', '-')
            if fuzzy_name != name:
                return [canonical, '--' + fuzzy_name]
        return [canonical]

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
        modified_long_names: set[str] = {
            n.replace('_', '-') for n in unique_long_names
        }
        extra_long_names: set[str] = modified_long_names - unique_long_names
        long_names += sorted(extra_long_names)
    short_option_strings: list[str] = ['-' + n for n in short_names]
    long_option_strings: list[str] = ['--' + n for n in long_names]
    option_strings: list[str] = short_option_strings + long_option_strings
    return option_strings




_SmartParseAction: Any = None

_VALUE_COLD_ATTRS = frozenset({
    '_value_argument_invocations',
    '_value_add_argument_to_parser',
    '_value_add_argument_kw',
    '_SmartValueCoercer',
    '_get_smart_parse_action',
    'CodeRepr',
    '_callable_code_repr',
})

def __getattr__(name: str):
    if name in _VALUE_COLD_ATTRS:
        module = __import__('kwconf._value_cold', fromlist=[name])
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
