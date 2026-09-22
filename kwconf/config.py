"""
Write simple configs and update from CLI, kwargs, json, and yaml.

``kwconf`` provides a simple way to make configurable scripts that combine
config files, command-line arguments, and Python keyword arguments. A
config is defined by subclassing :class:`Config` and declaring fields
as typed class variables. The instance behaves like a dict (it supports
``config['x']``) and like a namespace (``config.x``).

The future-facing schema style uses typed class variables. Use
:class:`kwconf.Value` to attach CLI metadata (help text, aliases, choices,
``isflag``, ``nargs``, positional, etc) when needed.

Example:
    >>> import kwconf as kw
    >>> # The simplest config: typed fields with raw defaults.
    >>> class ExampleConfig(kw.Config):
    ...     num: int = 1
    ...     mode: str = 'bar'
    ...     tags: list = kw.Value(default_factory=list, help='free-form tags')
    >>> # Creating an instance starts from the declared defaults.
    >>> config = ExampleConfig()
    >>> assert config['num'] == 1
    >>> # Programmatic updates via load(data=...).
    >>> config.load({'num': 2})
    >>> assert config['num'] == 2
    >>> # The `load` method can also accept a path to a json or yaml file,
    >>> # or a raw json / yaml string.
    >>> import tempfile, os
    >>> path = tempfile.mktemp(suffix='.json')
    >>> _ = open(path, 'w').write('{"num": 3}')
    >>> config.load(path)
    >>> assert config['num'] == 3
    >>> os.unlink(path)
    >>> # CLI parsing is available through the cli classmethod (preferred).
    >>> config = ExampleConfig.cli(argv=['--num=4', '--mode', 'fiz'])
    >>> assert config['num'] == 4 and config['mode'] == 'fiz'
    >>> # ``argv`` accepts a list, a shell-like string, True (read sys.argv),
    >>> # or False (skip CLI parsing entirely).
    >>> config = ExampleConfig.cli(argv='--num=4 --mode fiz')
    >>> assert config['num'] == 4 and config['mode'] == 'fiz'

Note:
    kwconf intentionally departs from scriptconfig: a CLI string with
    commas like ``--items=a,b,c`` stays the literal string ``"a,b,c"``
    rather than being silently split into a list. For CLI list input use
    ``nargs='+'`` (space-separated tokens). If you really want
    comma-separated parsing, do the split in ``__post_init__``. See
    ``docs/source/manual/migration_from_scriptconfig.md`` for the full
    list of breaks.

Example:
    >>> # Comma strings stay strings; lists are explicit.
    >>> import kwconf as kw
    >>> class ListConfig(kw.Config):
    ...     plain: str = ''
    ...     tags: list = kw.Value(default_factory=list, nargs='+')
    >>> config = ListConfig.cli(argv=['--plain=a,b,c', '--tags', 'x', 'y'])
    >>> # Plain strings are preserved literally:
    >>> assert config['plain'] == 'a,b,c'
    >>> # Lists are gathered from space-separated tokens via nargs:
    >>> assert config['tags'] == ['x', 'y']

Note:
    The ``__default__`` dict form remains supported on ``Config`` for
    compatibility with existing code, but new code should prefer typed
    class variables.
"""

from __future__ import annotations

import os
import sys
from abc import ABCMeta as _ABCMeta
from collections.abc import Mapping, Sequence
from collections.abc import Mapping as _ABCMapping

from kwconf._typing_runtime import (
    IO,
    Any,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    cast,
)
from kwconf.annotations import _is_any as _annotation_is_any
from kwconf.annotations import (
    choices_from_annotation as _choices_from_annotation,
)
from kwconf.annotations import (
    format_annotation as _format_annotation,
)
from kwconf.annotations import (
    get_class_namespace_annotations as _get_class_namespace_annotations,
)
from kwconf.annotations import is_classvar_annotation as _is_classvar_annotation
from kwconf.annotations import (
    runtime_type_from_annotation as _runtime_type_from_annotation,
)
from kwconf.annotations import (
    value_matches_annotation as _value_matches_annotation,
)
from kwconf.util.util_misc import NoParam, copy_value, iterable
from kwconf.util.util_repr import NiceRepr
from kwconf.value import _Value as Value
from kwconf.value import _resolve_alias

_DIAGNOSTIC_TRUE = frozenset({'true', 'on', 'yes', '1'})
_DEBUG_DEFAULT = os.environ.get('KWCONF_DEBUG', '').lower() in _DIAGNOSTIC_TRUE
_DIAGNOSTIC_DEFAULTS = {
    'DEBUG_CONFIG': _DEBUG_DEFAULT
    or os.environ.get('KWCONF_DEBUG_CONFIG', '').lower() in _DIAGNOSTIC_TRUE,
    'DEBUG_META_CONFIG': _DEBUG_DEFAULT
    or os.environ.get('KWCONF_DEBUG_META_CONFIG', '').lower()
    in _DIAGNOSTIC_TRUE,
}


def _diagnostic_enabled(name: str) -> bool:
    """Read diagnostic flags without importing :mod:`kwconf.diagnostics`."""
    module = sys.modules.get('kwconf.diagnostics')
    if module is not None:
        return bool(getattr(module, name, False))
    return _DIAGNOSTIC_DEFAULTS.get(name, _DEBUG_DEFAULT)


def _codeblock(text: str) -> str:
    from kwconf.util.util_text import codeblock

    return codeblock(text)


def _indent(text: str, prefix: str = '    ') -> str:
    from kwconf.util.util_text import indent

    return indent(text, prefix)


def _paragraph(text: str) -> str:
    from kwconf.util.util_text import paragraph

    return paragraph(text)


def _warn_user(message: str, category=UserWarning) -> None:
    """Emit a warning at the first frame outside kwconf.

    Hot and cold helper paths traverse different internal modules. A fixed
    ``stacklevel`` can therefore leak internal filenames into otherwise
    identical warnings. Resolve the first external frame dynamically so
    diagnostics stay user-facing.
    This helper is only called on warning paths, so the frame walk is not part
    of normal CLI startup.
    """
    import warnings

    frame = sys._getframe(1)
    stacklevel = 2  # warnings.warn -> _warn_user -> caller
    while frame is not None:
        module_name = frame.f_globals.get('__name__', '')
        if not (module_name == 'kwconf' or module_name.startswith('kwconf.')):
            break
        frame = frame.f_back
        stacklevel += 1
    warnings.warn(message, category, stacklevel=stacklevel)


class _LazyConfigFunction:
    """Function-like descriptor that resolves a cold implementation."""

    __slots__ = ('name', '_resolved')

    def __init__(self, name: str) -> None:
        self.name = name
        self._resolved = None

    def _resolve(self):
        func = self._resolved
        if func is None:
            module = __import__('kwconf._config_cold', fromlist=[self.name])
            func = getattr(module, self.name)
            self._resolved = func
        return func

    def __get__(self, instance, owner=None):
        return self._resolve().__get__(instance, owner)

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)


class _LazyConfigClassMethod(classmethod):
    """``classmethod``-compatible lazy descriptor for introspection parity."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._resolved = None
        super().__init__(lambda cls, *args, **kwargs: None)

    def _resolve(self):
        descriptor = self._resolved
        if descriptor is None:
            module = __import__('kwconf._config_cold', fromlist=[self.name])
            descriptor = classmethod(getattr(module, self.name))
            self._resolved = descriptor
        return descriptor

    def __get__(self, instance, owner=None):
        return self._resolve().__get__(instance, owner)


class _LazyConfigProperty(property):
    """``property``-compatible lazy descriptor for introspection parity."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._resolved = None
        super().__init__(fget=None)

    def _resolve(self):
        descriptor = self._resolved
        if descriptor is None:
            module = __import__('kwconf._config_cold', fromlist=[self.name])
            descriptor = property(getattr(module, self.name))
            self._resolved = descriptor
        return descriptor

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return self._resolve().__get__(instance, owner)


def _LazyConfigMethod(name: str, *, kind: str = 'method'):
    if kind == 'classmethod':
        return _LazyConfigClassMethod(name)
    if kind == 'property':
        return _LazyConfigProperty(name)
    return _LazyConfigFunction(name)


class ConfigValidationError(TypeError):
    """Raised when strict runtime validation rejects supplied configuration.

    This includes annotation mismatches and opt-in structural input checks,
    such as contradictory SubConfig selector spellings. It subclasses
    :class:`TypeError` so existing ``except TypeError`` handlers keep working,
    while callers can catch this specific type and render a clean diagnostic.
    """


__all__ = ['Config', 'ConfigValidationError', 'define']


ConfigData = Mapping[str, Any] | str | os.PathLike[str] | IO[Any] | None


def _normalize_validation_mode(mode: bool | str | None) -> bool | str | None:
    """Normalize the public runtime-validation policy."""
    if mode is True:
        return 'error'
    if mode is None or mode is False:
        return mode
    if isinstance(mode, str) and mode in {'warn', 'error'}:
        return mode
    raise ValueError(
        f"validate must be None, False, 'warn', 'error', or True; got {mode!r}"
    )


def _structural_validation_mode(
    cfg: 'Config', override: bool | str | None
) -> bool | str:
    """Resolve whether opt-in structural input checks should run.

    The default class policy is ``'warn'`` for inexpensive per-assignment type
    checks. It intentionally does *not* activate structural source scans. Such
    scans run when ``validate=`` is explicitly supplied, or when a class opts
    into the fully strict ``__validate__ = 'error'`` policy.
    """
    if override is not None:
        mode = _normalize_validation_mode(override)
        return False if mode is None else mode
    class_mode = _normalize_validation_mode(
        getattr(cfg, '__validate__', 'warn')
    )
    return 'error' if class_mode == 'error' else False


def define(default: Mapping[str, Any] = {}, name: Optional[str] = None) -> type:
    """
    Alternate method for defining a custom :class:`Config` type from a
    dict of defaults.

    Example:
        >>> from kwconf.config import define, Value
        >>> cls = define({'k1': Value('v1'), 'k2': 'v2'}, 'MyConfig')
        >>> instance = cls()
        >>> assert instance.to_dict() == {'k1': 'v1', 'k2': 'v2'}
        >>> print(instance)
        <MyConfig({'k1': 'v1', 'k2': 'v2'})>
    """
    import uuid
    from textwrap import dedent

    if name is None:
        hashid = str(uuid.uuid4()).replace('-', '_')
        name = 'Config_{}'.format(hashid)
    vals: Dict[str, Any] = {'default': default}
    code = dedent(
        """
        import kwconf
        class {name}(kwconf.Config):
            __default__ = default
        """.strip('\n').format(name=name)
    )
    exec(code, vals)
    cls = vals[name]
    return cast(Type['Config'], cls)


def _maybe_apply_annotation_to_value(key, value, annotations):
    """
    Enrich a class-attribute default with information derived from its type
    annotation (if any).

    Recognized annotation forms:

      * plain types (``int``, ``str``, ...): become ``Value.type``.
      * generic origins (``list[int]``, ``dict[str, int]``): the origin
        becomes ``Value.type``.
      * ``Optional[T]`` / ``T | None``: behaves like ``T``.
      * ``Literal['a', 'b', 'c']``: populates ``Value.choices`` and infers
        the underlying type from the literal members.

    Explicit metadata on a user-supplied :class:`Value` always wins over
    annotation-derived values.
    """
    annotation = annotations.get(key, None)
    # Plain runtime classes dominate typed Config declarations. Avoid two
    # generic annotation-dispatch calls for that case; unions/Literal/generics
    # still go through the centralized annotation helpers below.
    runtime_type = _runtime_type_from_annotation(annotation)
    if (
        runtime_type is annotation
        and isinstance(annotation, type)
        and not _annotation_is_any(annotation)
    ):
        # Ordinary classes dominate typed Config declarations.  The identity
        # check is important on Python 3.10 where ``list[int]`` can also satisfy
        # ``isinstance(annotation, type)`` but normalizes to runtime type list.
        choices = None
        has_annotation = True
    else:
        choices = _choices_from_annotation(annotation)
        # A string annotation could not be resolved; there is nothing usable
        # to stash (validation handles richer forms from real objects).
        has_annotation = annotation is not None and not isinstance(
            annotation, str
        )

    if isinstance(value, Value):
        if not has_annotation:
            return value
        # Value templates are shared with base classes and sibling configs
        # (subclass __default__ merging reuses the same objects), so never
        # mutate the original: copy once, then enrich the copy.
        value = value.copy()
        value.parsekw = dict(value.parsekw)
        value._annotation = annotation
        # Explicit metadata on a user-supplied Value wins over
        # annotation-derived values.
        if choices is not None and not value.parsekw.get('choices'):
            value.parsekw['choices'] = list(choices)
        if runtime_type is not None and value.type is None:
            value.type = runtime_type
            value.parsekw['type'] = runtime_type
        return value

    if not has_annotation:
        return value

    # Wrap a plain default into a Value so we have somewhere to stash the
    # annotation (and any derived choices) for later validation, even when
    # no runtime type could be inferred (e.g. ``int | None``).
    if choices is not None:
        new_value = Value(
            value, choices=list(choices), isflag=isinstance(value, bool)
        )
    else:
        new_value = Value(value, isflag=isinstance(value, bool))
    if runtime_type is not None:
        # Set the annotation-derived runtime type as an attribute rather than
        # passing ``type=`` to the constructor, so the Value is NOT marked as
        # "user gave type=" (which would route coercion through the legacy
        # smartcast path instead of the annotation-gated 'auto' default).
        new_value.type = runtime_type
        new_value.parsekw = dict(new_value.parsekw)
        new_value.parsekw['type'] = runtime_type
    new_value._annotation = annotation
    return new_value


def _collect_declared_config_attrs(
    namespace: Dict[str, Any], annotations: Mapping[str, Any] | None = None
) -> Dict[str, Any]:
    annotations = annotations or {}
    attr_default = {}
    for k, v in namespace.items():
        if k.startswith('_') or k == 'default':
            continue
        annotation = annotations.get(k)
        if (
            annotation is not None
            and not isinstance(annotation, type)
            and _is_classvar_annotation(annotation)
        ):
            continue
        if isinstance(v, classmethod) or isinstance(v, staticmethod):
            continue
        # Descriptors define class/instance behavior; they are not declarative
        # field defaults unless explicitly wrapped in Value/SubConfig metadata.
        if hasattr(v, '__get__') and not isinstance(v, Value):
            if not (isinstance(v, type) and issubclass(v, Config)):
                continue
        if callable(v) and not (isinstance(v, type) and issubclass(v, Config)):
            continue
        # Annotation enrichment is applied once after class attributes and
        # ``__default__`` have been merged. Doing it here as well used to copy
        # every annotated Value twice during metaclass construction.
        attr_default[k] = v
    return attr_default


def _materialize_default_items(defaults: Mapping[str, Any]) -> Dict[str, Any]:
    realized = {}
    for key, value in defaults.items():
        if isinstance(value, Value):
            realized[key] = value.clone_default(
                context=f'default for field {key!r}'
            )
        else:
            realized[key] = copy_value(
                value, context=f'default for field {key!r}'
            )
    return realized


def _materialize_initial_state(
    defaults: Mapping[str, Any], *, _dont_call_post_init: bool = False
) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Clone schema baselines and seed runtime values in one pass.

    Construction used to clone every class template and then immediately walk
    the cloned mapping a second time to create ``_data``.  Large declarative
    CLIs spend a meaningful fraction of their startup budget in those two
    Python loops.  This helper preserves the ownership boundary while doing
    both operations together.

    Mutable concrete values are still copied twice by design: once from the
    class template into the instance reset baseline, and once from that
    baseline into the live runtime value.  Factories remain recipes and
    SubConfigs retain their normal instantiation semantics.
    """
    instance_defaults: Dict[str, Any] = {}
    data: Dict[str, Any] = {}
    subconfigs: Dict[str, Any] = {}

    for key, class_template in defaults.items():
        template_context = f'default for field {key!r}'
        runtime_context = f'reset baseline for field {key!r}'

        # SubConfig is a Value subclass but owns selector/instantiation
        # semantics, so it must stay on its specialized clone path.
        if getattr(class_template, '_kwconf_is_subconfig', False):
            template = class_template.clone_default(context=template_context)
            instance_defaults[key] = template
            subconfigs[key] = template
            data[key] = template.instantiate(
                _dont_call_post_init=_dont_call_post_init
            )
            continue

        if isinstance(class_template, Value):
            template, runtime_value = class_template._materialize_instance_pair(
                template_context=template_context,
                runtime_context=runtime_context,
            )
            instance_defaults[key] = template
            data[key] = runtime_value
            continue

        template = copy_value(class_template, context=template_context)
        instance_defaults[key] = template
        data[key] = copy_value(template, context=runtime_context)

    return instance_defaults, data, subconfigs


def _coerce_data_to_dict(
    data: Any, mode: Optional[str] = None
) -> Dict[str, Any]:
    """Compatibility wrapper around the shared ingestion boundary.

    ``None`` and a plain ``dict`` cover the hot CLI path and can be handled
    without importing the file/YAML/JSON ingestion stack. More general inputs
    stay centralized in :mod:`kwconf._ingest`.
    """
    if data is None:
        return {}
    if type(data) is dict:
        return dict(data)
    from kwconf._ingest import coerce_mapping_source

    return coerce_mapping_source(data, mode=mode)


def _coerce_argv_common(argv: Any, *, expand_vars: bool = False) -> list[str]:
    """Normalize the common argv forms without importing ``_ingest``.

    Lists/tuples and ``sys.argv`` account for normal CLI execution. String
    command lines and arbitrary iterables retain the canonical shared helper.
    """
    if argv is False or argv is None:
        return []
    if argv is True:
        return list(sys.argv[1:])
    if isinstance(argv, (list, tuple)):
        return [
            os.fspath(item) if isinstance(item, os.PathLike) else item
            for item in argv
        ]
    from kwconf._ingest import coerce_argv

    return coerce_argv(argv, expand_vars=expand_vars)


def _validate_class_aliases(
    class_name: str, defaults: Mapping[str, Any], fuzzy_hyphens: bool
) -> None:
    """Reject ambiguous option and mapping names during schema validation.

    Canonical field names and ``Value.alias`` spellings share one long-name
    lookup namespace. When fuzzy hyphens are enabled, each underscore spelling
    also claims its generated hyphen spelling. ``Value.short_alias`` spellings
    share a separate short-option namespace. Any spelling claimed by two fields
    would otherwise be resolved inconsistently by constructor/data lookup and
    argparse.

    This check is intentionally opt-in through :meth:`Config.validate` so
    production CLI startup does not repeatedly scan schemas that projects have
    already validated in their test suite or CI.
    """
    spelling_owner: Dict[str, str] = {}
    spelling_source: Dict[str, str] = {}
    short_owner: Dict[str, str] = {}

    for key, value in defaults.items():
        aliases = getattr(value, 'alias', None)
        if aliases is None:
            aliases = []
        elif isinstance(aliases, str):
            aliases = [aliases]

        declared_names = [(key, 'canonical field')] + [
            (alias, 'alias') for alias in aliases
        ]
        for declared_name, source_kind in declared_names:
            accepted_names = [declared_name]
            if fuzzy_hyphens:
                fuzzy_name = declared_name.replace('_', '-')
                if fuzzy_name != declared_name:
                    accepted_names.append(fuzzy_name)

            for accepted_name in accepted_names:
                owner = spelling_owner.get(accepted_name)
                if owner is not None and owner != key:
                    prior_source = spelling_source[accepted_name]
                    raise ValueError(
                        f'Alias collision in {class_name}: spelling '
                        f'{accepted_name!r} is claimed by fields {owner!r} '
                        f'({prior_source}) and {key!r} ({source_kind}). '
                        'Canonical names, aliases, and generated fuzzy-hyphen '
                        'spellings must be unique.'
                    )
                spelling_owner[accepted_name] = key
                spelling_source[accepted_name] = source_kind

        short_aliases = getattr(value, 'short_alias', None)
        if short_aliases is None:
            short_aliases = []
        elif isinstance(short_aliases, str):
            short_aliases = [short_aliases]
        for short_name in short_aliases:
            owner = short_owner.get(short_name)
            if owner is not None and owner != key:
                raise ValueError(
                    f'Alias collision in {class_name}: short option '
                    f'{("-" + short_name)!r} is claimed by fields '
                    f'{owner!r} and {key!r}. Short aliases must be unique.'
                )
            short_owner[short_name] = key


_MAPPING_API_NAMES = frozenset(
    {
        'clear',
        'copy',
        'get',
        'items',
        'keys',
        'pop',
        'popitem',
        'update',
        'values',
    }
)


class _ConfigFieldProxy:
    """Route an instance attribute to config data without hiding class APIs.

    Config item access is the authoritative field protocol. Attribute access is
    convenience syntax, so mapping methods remain method-first. Other public
    APIs may be used as field names: the field wins on an instance, while class
    access still resolves the inherited method, classmethod, or property.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(
        self, instance: 'Config | None', owner: type | None = None
    ) -> Any:
        if instance is not None:
            return instance[self.name]
        if owner is None:
            raise AttributeError(self.name)

        config_type = globals().get('Config')
        if config_type is not None:
            sentinel = object()
            for base in owner.__mro__[1:]:
                if not issubclass(base, config_type):
                    continue
                candidate = vars(base).get(self.name, sentinel)
                if candidate is sentinel or isinstance(
                    candidate, _ConfigFieldProxy
                ):
                    continue
                descriptor_get = getattr(candidate, '__get__', None)
                if descriptor_get is not None:
                    return descriptor_get(None, owner)
                return candidate

        default = getattr(owner, '__default__')
        return default[self.name]

    def __set__(self, instance: 'Config', value: Any) -> None:
        instance[self.name] = value


_CONFIG_API_NAMES: frozenset[str] | None = None


def _config_api_defines_attribute(name: str) -> bool:
    """Return whether the root Config API defines public ``name``.

    The root API is immutable for ordinary kwconf use, while this predicate is
    evaluated twice per declared field during metaclass construction. Cache the
    union once instead of walking ``Config.__mro__`` and materializing ``vars``
    mappings for every field in wide schemas.
    """
    global _CONFIG_API_NAMES
    api_names = _CONFIG_API_NAMES
    if api_names is None:
        config_type = globals().get('Config')
        if config_type is None:
            return False
        api_names = frozenset(
            attr for ancestor in config_type.__mro__ for attr in vars(ancestor)
        )
        _CONFIG_API_NAMES = api_names
    return name in api_names


_PLAIN_DEFAULT_TYPES = (type(None), bool, int, float, complex, str, bytes)


def _normalize_class_defaults(defaults, annotations=None):
    """
    Normalize class-level defaults to ensure Value/SubConfig metadata is present.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.Config):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.Config):
        ...     __default__ = {'inner': Inner, 'flag': False, 'leaf': 3}
        >>> norms = _normalize_class_defaults(Outer.__default__)
        >>> assert isinstance(norms['inner'], kwconf.SubConfig)
        >>> assert isinstance(norms['flag'], kwconf.value._Value) and norms['flag'].isflag is True
        >>> assert isinstance(norms['leaf'], kwconf.value._Value)
    """
    normalized = {}
    if defaults is None:
        defaults = {}
    annotations = annotations or {}

    for key, value in defaults.items():
        normalized_value: Any
        if getattr(value, '_kwconf_is_subconfig', False):
            normalized_value = value
        elif isinstance(value, Value):
            value = _maybe_apply_annotation_to_value(key, value, annotations)
            if value.default_factory is not None:
                # A default_factory cannot wrap a SubConfig/Config, and reading
                # ``value.value`` here would force the factory to run at
                # class-definition time. Skip the SubConfig detection so the
                # factory stays deferred until first use.
                normalized[key] = value
                continue
            inner = value.value
            if getattr(inner, '_kwconf_is_subconfig', False):
                if value.help and not inner.help:
                    inner.parsekw['help'] = value.help
                normalized_value = inner
            elif isinstance(inner, Config) or (
                isinstance(inner, type) and issubclass(inner, Config)
            ):
                from kwconf.subconfig import SubConfig

                normalized_value = SubConfig(inner, help=value.help)
            else:
                normalized_value = value
        elif type(value) in _PLAIN_DEFAULT_TYPES:
            # Common scalar defaults cannot be nested Configs; avoid the ABC
            # instance check and go directly to Value normalization.
            normalized_value = _maybe_apply_annotation_to_value(
                key, value, annotations
            )
            if normalized_value is value:
                normalized_value = Value(value, isflag=isinstance(value, bool))
        elif isinstance(value, Config) or (
            isinstance(value, type) and issubclass(value, Config)
        ):
            from kwconf.subconfig import SubConfig

            normalized_value = SubConfig(value)
        else:
            normalized_value = _maybe_apply_annotation_to_value(
                key, value, annotations
            )
            if normalized_value is value:
                if isinstance(value, bool):
                    normalized_value = Value(value, isflag=True)
                else:
                    normalized_value = Value(value)
        normalized[key] = normalized_value
    return normalized


# NOTE: kwconf intentionally does NOT apply @dataclass_transform here (Option A,
# see dev/planning/design.md §6.1). With positional ``Value(...)`` defaults the
# typing spec forces the synthesized ``__init__`` to treat every wrapped field as
# *required*, producing spurious "missing field" errors under mypy/pyright. Static
# checking of field defaults is delivered instead by typing ``Value(...) -> T``.
class MetaConfig(_ABCMeta):
    """
    Metaclass that collects declarative config fields and normalizes
    compatibility metadata.

    Ensures that class attributes are mirrored:
        * __default__ mirrors default
        * __post_init__ mirrors normalize

    Also reserves the ``__class__`` key for SubConfig selector metadata and
    warns on the common ``key = Value(...),`` trailing-comma typo. These checks apply uniformly to all kwconf config classes.
    """

    @staticmethod
    def __new__(
        mcls: type,
        name: str,
        bases: Tuple[type, ...],
        namespace: Dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> type:
        if _diagnostic_enabled('DEBUG_META_CONFIG'):
            print(
                f'MetaConfig.__new__ called: {mcls=} {name=} {bases=} {namespace=} {args=} {kwargs=}'
            )

        # Skip class-attr collection on Config itself (the root); all
        # subclasses (user classes) participate.
        is_root_config = (
            name == 'Config' and namespace.get('__module__') == __name__
        )

        # The root Config class has implementation annotations that do not
        # describe user fields. Skipping them also avoids importing ``typing``
        # solely to resolve names such as Dict/Optional during package startup.
        annotations = (
            {}
            if is_root_config
            else _get_class_namespace_annotations(namespace)
        )

        if not is_root_config:
            attr_default = _collect_declared_config_attrs(
                namespace, annotations
            )

            # Keep the private operation surface aligned with ordinary
            # subclass overrides. Declared fields are handled below by field
            # proxies and deliberately do not replace the non-shadowable
            # operation alias.
            for public_name, public_value in tuple(namespace.items()):
                if (
                    public_name not in attr_default
                    and not public_name.startswith('_')
                    and _config_api_defines_attribute(public_name)
                    and (
                        isinstance(
                            public_value,
                            (classmethod, staticmethod, property),
                        )
                        or callable(public_value)
                    )
                ):
                    namespace.setdefault('_' + public_name, public_value)

            if attr_default:
                for key in attr_default:
                    namespace.pop(key, None)
                cls_default = namespace.get('__default__', None) or {}
                namespace['__default__'] = {**attr_default, **cls_default}

        # Handle inheritance, add in defaults from base classes
        this_default = namespace.get('__default__', {})
        if this_default is None:
            this_default = {}
        this_default = dict(this_default)

        inheritence_default: Dict[str, Any] = {}
        for base in reversed(bases):
            if hasattr(base, '__default__'):
                inheritence_default.update(base.__default__)  # type: ignore
        inheritence_default.update(this_default)
        this_default = inheritence_default

        if not is_root_config:
            # Reserve "__class__" for nested SubConfig selector metadata.
            if '__class__' in this_default:
                raise ValueError(
                    'The name "__class__" is reserved for nested Config meta keys'
                )

            # Warn on the common ``key = Value(...),`` trailing-comma typo.
            for k, v in this_default.items():
                if (
                    isinstance(v, tuple)
                    and len(v) == 1
                    and isinstance(v[0], Value)
                ):
                    import warnings

                    warnings.warn(
                        _paragraph(
                            f"""
                        It looks like you have a trailing comma in your
                        {name} Config.  The variable {k!r} has a value of
                        {v!r}, which is a Tuple[Value]. Typically it should be
                        a Value.
                        """
                        ),
                        UserWarning,
                    )

            this_default = _normalize_class_defaults(this_default, annotations)

            # Mapping methods remain authoritative on instances. Other public
            # inherited attributes may be shadowed by declared fields while
            # staying available on the class and through their private alias.
            for key in this_default:
                if (
                    not key.startswith('_')
                    and key not in _MAPPING_API_NAMES
                    and key not in namespace
                    and _config_api_defines_attribute(key)
                ):
                    namespace[key] = _ConfigFieldProxy(key)
        namespace['__default__'] = this_default

        if _diagnostic_enabled('DEBUG_META_CONFIG'):
            import pprint

            formatted = pprint.pformat(vars(namespace))
            print(f'FINAL namespace = {formatted}')
        cls = super().__new__(mcls, name, bases, namespace, *args, **kwargs)  # type: ignore

        # Schema validation is deliberately opt-in via ``Config.validate``.
        # Class construction is on every process startup, while a project's
        # schemas are normally static and can be checked once in tests / CI.

        # Modify the __init__ docstring to surface the valid keys to help().
        if (
            getattr(cls, '__init__', None) is not None
            and cls.__init__.__doc__ == '__autogenerateme__'
        ):
            valid_keys = list(cls.__default__.keys())
            cls.__init__.__doc__ = (
                f'Valid options: {valid_keys}\n\n'
                'Args:\n'
                '    *args: positional arguments mapped onto declared fields.\n'
                '    **kwargs: keyword arguments for any declared field.'
            )
        return cls


class Config(NiceRepr, _ABCMapping, metaclass=MetaConfig):
    """
    Primary configuration base class for kwconf.

    The preferred kwconf schema style uses typed class variables and optional
    :class:`kwconf.Value` metadata wrappers. The older ``__default__``
    dictionary style remains available for compatibility.

    You may also implement ``__post_init__`` (function that takes no args and
    has no return) to postprocess values after initialization.

    Construction is dataclass-like: positional args map onto declared fields
    in declaration order, and any field can also be passed as a keyword. To
    populate from a file, dict, or argv, use the :meth:`cli` or :meth:`load`
    methods after construction.

    An instance behaves like both a dictionary (``config['key']``) and a
    namespace (``config.key``). Declared fields form the configuration,
    mapping, CLI, and serialization contract. Assigning an undeclared Python
    attribute stores ordinary transient instance state; it is intentionally
    absent from mapping access and serialization. ``__allow_newattr__ = True``
    is an experimental escape hatch that instead promotes unknown assignments
    into dynamic configuration keys; those keys do not have declared parser,
    annotation, default, or CLI metadata.

    Key methods:

        * :meth:`validate` - check static schema invariants in tests / CI.
        * :meth:`cli` - construct a CLI-aware instance from argv.
        * :meth:`load` - update the instance from a file, dict, or argv.
        * :meth:`argparse` - build an :class:`argparse.ArgumentParser`.
        * :meth:`dump`, :meth:`dumps` - serialize to yaml/json.

    Attributes:
        _data : this protected variable holds the instance level raw state of
            the config object and is accessed by the dict-like

        _default : this protected variable maintains the instance-level default
            values for this config.

        epilog (str): A class attribute that if specified will add an epilog
            section to the help text.

    Example:
        >>> import kwconf as kw
        >>> class MyConfig(kw.Config):
        ...     option1: tuple = kw.Value((1, 2, 3))
        ...     option2: str = 'bar'
        ...     option3: list = kw.Value(default_factory=list)
        >>> config1 = MyConfig()
        >>> config2 = MyConfig(option2='baz')
        >>> assert config2.option2 == 'baz'
    """

    # Note: class definitions are allowed to use raw literals; the metaclass
    # normalizes them to Value/SubConfig instances at creation time.
    __default__: Dict[str, Any] = {}
    __description__: Optional[str] = None
    __epilog__: Optional[str] = None
    __validate__: bool | str = 'warn'
    __short_alias_clusters__: bool = True
    # __allow_newattr__ = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        "__autogenerateme__"
        # Internal flag used by the cli/load lifecycle to defer __post_init__.
        _dont_call_post_init = kwargs.pop('_dont_call_post_init', False)

        num_args = len(args)
        num_fields = len(self.__default__)
        if num_args > num_fields:
            field_word = 'argument' if num_fields == 1 else 'arguments'
            raise TypeError(
                f'{type(self).__qualname__}() accepts at most {num_fields} '
                f'positional {field_word}; got {num_args}'
            )

        # Shared per-instance state setup (builds _default, seeds _data,
        # and instantiates SubConfig nodes).
        self._init_state(_dont_call_post_init=_dont_call_post_init)

        # Bind only the supplied positional fields, then normalize keyword
        # aliases in the same pass that checks for duplicate / unknown inputs.
        # This avoids materializing the complete field-name list or making a
        # second pass over keyword arguments on the normal constructor path.
        new_values = dict(zip(self._default, args))
        unknown_args: Optional[Dict[str, Any]] = None
        alias_map = None
        for raw_key, value in kwargs.items():
            if raw_key in self._default:
                key = raw_key
            else:
                if alias_map is None:
                    alias_map = self._build_alias_map()
                    self._alias_map = alias_map
                key = alias_map.get(raw_key, raw_key)
            if key in new_values:
                raise TypeError(
                    f'{type(self).__qualname__}() got multiple values '
                    f'for argument {key!r}'
                )
            if key not in self._default:
                if unknown_args is None:
                    unknown_args = {}
                unknown_args[raw_key] = value
            else:
                new_values[key] = value
        if unknown_args is not None:
            raise ValueError(
                ('Unknown Arguments: {}. Expected arguments are: {}').format(
                    unknown_args, list(self._default)
                )
            )
        for key, value in new_values.items():
            # Constructor values define this instance's reset baseline, but
            # the baseline and current value must never alias.  Keep metadata
            # in ``_default`` and runtime values in ``_data``.
            self._set_default_value(key, value)
            self[key] = value
        if new_values:
            self._index_subconfigs()

        self._enable_setattr = True
        if not _dont_call_post_init:
            self.__post_init__()
            self._kwconf_post_init_done = True

    def _init_state(self, _dont_call_post_init: bool = False) -> None:
        """
        Initialize per-instance attribute storage from the class-level defaults.

        Shared between :class:`Config` and :class:`Config` constructors.
        Builds ``self._default`` (a fresh per-instance copy), populates
        ``self._data`` with raw values, and instantiates any SubConfig nodes.
        """
        self._data: Dict[str, Any] = {}
        self._default: Dict[str, Value] = {}
        self._subconfig_meta: Dict[str, Any] = {}
        self._has_subconfigs = False
        self._kwconf_post_init_done = False
        self._alias_map = None
        # Provenance: canonical keys that were explicitly supplied on argv
        # during the most recent :func:`_read_argv`. Empty for configs that
        # were never populated from the command line. This is intentionally
        # private and argv-scoped; it is *not* a general "was this key set by
        # any source" flag. Populated authoritatively by ``_read_argv`` (never
        # by ``__setitem__``, since that funnel also handles default/config
        # writes).
        self._explicit_argv_keys: frozenset = frozenset()
        # Canonical keys supplied by any user source during the most recent
        # load() call (data, --config, or explicit argv). Required-field
        # enforcement relies only on this provenance, never value equality.
        self._provided_keys: frozenset = frozenset()
        cls_default = getattr(self, '__default__', None)
        if cls_default:
            (
                self._default,
                self._data,
                self._subconfig_meta,
            ) = _materialize_initial_state(
                cls_default, _dont_call_post_init=_dont_call_post_init
            )
            self._has_subconfigs = bool(self._subconfig_meta)

    def _set_default_value(self, key: str, value: Any) -> None:
        """Replace one instance baseline while preserving field metadata."""
        template = self._default[key]
        if isinstance(value, Value):
            # A full Value override can change CLI metadata (aliases, parser,
            # nargs, flag mode, ...), so clone the complete field template.
            # Scalar overrides below preserve the declared metadata.
            new_template = value.clone_default(
                context=f'explicit default for field {key!r}'
            )
        elif isinstance(template, Value):
            new_template = template.copy()
            # An explicit baseline replaces the declared factory recipe.
            new_template.default_factory = None
            new_template.value = copy_value(
                value, context=f'explicit default for field {key!r}'
            )
        else:
            new_template = copy_value(
                value, context=f'explicit default for field {key!r}'
            )
        self._default[key] = new_template
        self._alias_map = None

    def _index_subconfigs(self) -> None:
        """Index SubConfig metadata without importing the nested-config stack.

        ``SubConfig`` marks itself on the class.  Looking for that marker keeps
        the overwhelmingly common flat-config construction path independent of
        ``kwconf.subconfig`` while retaining normal ``isinstance``-free behavior
        for actual SubConfig instances.
        """
        self._subconfig_meta = {
            key: template
            for key, template in self._default.items()
            if getattr(template, '_kwconf_is_subconfig', False)
        }
        self._has_subconfigs = bool(self._subconfig_meta)

    def _reset_data_from_defaults(
        self, *, _dont_call_post_init: bool = False
    ) -> None:
        """Reset current values from the independent instance baseline."""
        self._index_subconfigs()
        values: Dict[str, Any] = {}
        for key, template in self._default.items():
            if getattr(template, '_kwconf_is_subconfig', False):
                subconfig_template: Any = template
                values[key] = subconfig_template.instantiate(
                    _dont_call_post_init=_dont_call_post_init
                )
            elif isinstance(template, Value):
                if template.default_factory is not None:
                    # Treat the factory as the reset recipe, just as dataclass
                    # construction invokes default_factory for each instance.
                    values[key] = template.default_factory()
                else:
                    values[key] = copy_value(
                        template.value,
                        context=f'reset baseline for field {key!r}',
                    )
            else:
                values[key] = copy_value(
                    template, context=f'reset baseline for field {key!r}'
                )
        self._data = values

    def _clone_from_baseline(
        self, *, _dont_call_post_init: bool = False
    ) -> 'Config':
        """Clone this config's reset baseline without copying runtime values.

        A ``SubConfig(instance)`` declaration treats the instance as a baseline
        template. Concrete baseline values are deeply copied; factory-backed
        fields invoke their recipes, so non-copyable factory outputs remain
        supported and no runtime object is shared with the template instance.
        """
        clone = type(self).__new__(type(self))
        clone._data = {}
        clone._default = _materialize_default_items(self._default)
        clone._subconfig_meta = {}
        clone._has_subconfigs = False
        clone._kwconf_post_init_done = False
        clone._alias_map = None
        clone._explicit_argv_keys = frozenset()
        clone._provided_keys = frozenset()
        clone._reset_data_from_defaults(
            _dont_call_post_init=_dont_call_post_init
        )
        clone._enable_setattr = True
        if not _dont_call_post_init:
            clone.__post_init__()
            clone._kwconf_post_init_done = True
        return clone

    def _validate_required_fields(self) -> None:
        """Require explicit current-load provenance for required fields."""
        for key, template in self._default.items():
            if (
                isinstance(template, Value)
                and template.required
                and key not in self._provided_keys
            ):
                raise ValueError(f'Required variable {key!r} was not given')
        for value in self._data.values():
            if isinstance(value, Config):
                value._validate_required_fields()

    @classmethod
    def validate(cls) -> None:
        """Validate static schema invariants for this Config class.

        This method is intentionally not called during class construction or
        normal CLI invocation. Projects should call it from their test suite or
        CI so schema mistakes are caught without adding repeated startup work to
        every command invocation.

        Currently this checks that canonical field names, long aliases, short
        aliases, inherited fields, and generated fuzzy-hyphen spellings form
        unambiguous lookup namespaces. Additional static schema checks may be
        added here over time.

        Raises:
            ValueError:
                If two fields claim the same accepted spelling.

        Example:
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            ...     output_path = kwconf.Value('out.txt', alias=['output'])
            >>> MyConfig.validate()
        """
        _validate_class_aliases(
            class_name=cls.__name__,
            defaults=cls.__default__,
            fuzzy_hyphens=bool(getattr(cls, '__fuzzy_hyphens__', 1)),
        )

    @classmethod
    def coerce(cls, **kwargs: Any) -> 'Config':
        """
        Construct a config, coercing string-valued arguments through each
        field's parser (the text-boundary path).

        This is the opt-in counterpart to the plain constructor. ``cls(**kwargs)``
        is the *trusted* Python path; ``cls.coerce(**kwargs)`` is for argv/env-like
        string inputs and for tests that want CLI-style parsing without argv.
        Only string values are parsed; real Python objects pass through.

        Example:
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __default__ = {'num': kwconf.Value(0, type=int)}
            >>> cfg = MyConfig.coerce(num='42')
            >>> assert cfg['num'] == 42
        """
        defaults = getattr(cls, '__default__', {}) or {}
        alias_map: Dict[str, str] = {}
        for canonical, template in defaults.items():
            aliases = getattr(template, 'alias', None)
            if aliases:
                if not iterable(aliases):
                    aliases = [aliases]
                for alias in aliases:
                    alias_map[alias] = canonical

        coerced: Dict[str, Any] = {}
        for key, value in kwargs.items():
            canonical = alias_map.get(key, key)
            template = defaults.get(canonical)
            if isinstance(value, str) and isinstance(template, Value):
                coerced[key] = template.coerce(value)
            else:
                coerced[key] = value
        return cls(**coerced)

    @classmethod
    def from_cli(
        cls, argv: Sequence[str] | str | bool | None = None, **kwargs: Any
    ) -> 'Config':
        """Construct from command-line arguments (a named alias for :meth:`cli`)."""
        return cls._cli(argv=argv, **kwargs)

    @classmethod
    def from_yaml(cls, path: Any, **kwargs: Any) -> 'Config':
        """
        Construct from a YAML (or JSON) file path. Values keep the file
        format's own typing -- no extra string coercion is applied (a quoted
        ``"123"`` stays a string), consistent with the text-boundary rule.
        """
        return cls._cli(data=path, argv=False, **kwargs)

    @classmethod
    def from_env(cls, prefix: str = '', **kwargs: Any) -> 'Config':
        """
        Construct from environment variables.

        Each declared field ``name`` is read from
        ``os.environ[f'{prefix}{name}']`` (the suffix after ``prefix`` is matched
        case-insensitively against declared fields). Environment values are
        strings, so they pass through the text-boundary parser via
        :meth:`coerce`. Explicit ``kwargs`` override environment values.

        Example:
            >>> import os, kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __default__ = {'num': kwconf.Value(0, type=int)}
            >>> os.environ['MYAPP_NUM'] = '7'
            >>> assert MyConfig.from_env(prefix='MYAPP_')['num'] == 7
            >>> del os.environ['MYAPP_NUM']
        """
        import os

        fields = getattr(cls, '__default__', {}) or {}
        collected: Dict[str, Any] = {}
        for env_key, env_val in os.environ.items():
            if prefix and not env_key.startswith(prefix):
                continue
            field = env_key[len(prefix) :].lower()
            if field in fields:
                collected[field] = env_val
        collected.update(kwargs)
        return cls._coerce(**collected)

    @classmethod
    def cli(
        cls,
        data: ConfigData = None,
        default: Mapping[str, Any] | None = None,
        argv: Sequence[str] | str | bool | None = None,
        strict: bool = True,
        autocomplete: bool | str = 'auto',
        special_options: bool | None = None,
        verbose: bool | str = False,
        allow_import: bool = True,
        allow_subconfig_overrides: bool = True,
        localns: Mapping[str, Any] | None = None,
        stacklevel: int | None = 0,
        validate: bool | str | None = None,
    ) -> Config:
        """
        Create a command-line aware config instance.

        Args:
            data (dict | str | None):
                Values to update the configuration with. This can be a
                regular dictionary or a path to a yaml / json file.

            default (dict | None):
                Values to update the defaults with (not the actual
                configuration). Note: anything passed to default will be deep
                copied and can be updated by argv or data if it is specified.
                Generally prefer to pass directly to data instead.

            argv (list[str] | str | bool | None):
                Source of CLI arguments. ``None`` parses ``sys.argv``. A list
                or shell-like string is parsed directly. ``True`` is a synonym
                for ``None`` (parse ``sys.argv``). ``False`` skips CLI parsing
                entirely.

            strict (bool):
                if True use ``parse_args`` otherwise use ``parse_known_args``.
                Defaults to True.

            validate (bool | str | None):
                Per-invocation runtime-validation override. ``None`` preserves
                field/class value-validation policy and keeps structural input
                scans off unless ``__validate__ = 'error'``. ``False`` disables
                validation for values ingested by this call. ``'warn'`` enables
                structural checks and warns while applying deterministic safe
                precedence. ``'error'`` / ``True`` raises
                :class:`ConfigValidationError`. Parser-enforced constraints
                such as ``Literal`` choices remain hard errors regardless.

            autocomplete (bool | str):
                if True try to enable argcomplete.

            special_options (bool | None, default=None):
                adds special kwconf options, namely: --config, --dumps,
                and --dump. If None, uses the class attribute __special_options__
                if present, otherwise defaults to False. Opt in by setting
                ``__special_options__ = True`` on the class or by passing
                ``special_options=True`` explicitly.

            verbose (bool | str):
                If true, then perform a rich print of the config after it is
                parsed. If "auto", it will default to true in most cases,
                except when we can infer special behavior from the
                user-defined config via standard keys: verbose, quiet, silent.

            allow_import (bool):
                Default policy for importable selectors such as
                ``pkg.mod.Container.ClassName``. Individual ``SubConfig``
                fields may explicitly enable or disable imports; fields with
                ``allow_import=None`` inherit this value. Defaults to True.

            allow_subconfig_overrides (bool):
                If True, enable multipass CLI parsing to allow SubConfig
                selection overrides. If False, only the default realized tree
                is parsed and selector args error at parse time.

            localns (dict | None):
                Namespace used to resolve SubConfig class names. If None and
                ``stacklevel`` is not None, a namespace is derived from the
                caller's frame.

            stacklevel (int | None):
                Number of frames above the caller to use when deriving the
                namespace for SubConfig class name resolution. Use None to
                disable caller introspection.

        Example:
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __default__ = {
            >>>         'option1': kwconf.Value((1, 2, 3), tuple),
            >>>         'option2': 'bar',
            >>>         'option3': None,
            >>>         'verbose': False,
            >>>     }
            >>> # You can now make instances of this class
            >>> config = MyConfig.cli(argv=False, verbose='auto')
            >>> config = MyConfig.cli(argv=False, data=dict(verbose=1), verbose='auto')
        """
        if _diagnostic_enabled('DEBUG_CONFIG'):
            print(f'[kwconf] Call {cls.__name__}.cli argv={argv!r}')
        if argv is None:
            argv = True  # parse sys.argv by default
        if default is None:
            default = {}
        # Two-phase init: construct with __post_init__ deferred, then run it
        # exactly once at the end of load() after every source is merged
        # (otherwise it would fire on the empty instance and again post-load).
        self = cls(_dont_call_post_init=True)
        next_stacklevel = None if stacklevel is None else stacklevel + 1
        self._load(
            data,
            argv=argv,
            default=default,
            strict=strict,
            validate=validate,
            autocomplete=autocomplete,
            special_options=special_options,
            allow_import=allow_import,
            allow_subconfig_overrides=allow_subconfig_overrides,
            localns=localns,
            stacklevel=next_stacklevel,
        )

        if isinstance(verbose, str) and verbose == 'auto':
            verbose = self._get('verbose', verbose)
            verbose = not self._get('quiet', not verbose)
            verbose = not self._get('silent', not verbose)

        if verbose:
            try:
                import rich
                from rich.markup import escape
            except ImportError:
                import pprint

                print('config = ' + pprint.pformat(dict(self)))
            else:
                import pprint

                rich.print('config = ' + escape(pprint.pformat(dict(self))))
        if _diagnostic_enabled('DEBUG_CONFIG'):
            print(f'[kwconf] Return {cls.__name__}.cli')
        return self

    demo = _LazyConfigMethod('demo', kind='classmethod')

    __json__ = _LazyConfigMethod('__json__', kind='method')

    def __nice__(self) -> str:
        data = self._asdict()
        if isinstance(data, dict):
            data = dict(data)
        return str(data)

    def __repr__(self) -> str:
        # Do not import ubelt (or even kwconf's ubelt bridge) merely to build a
        # Config. If ubelt is imported later and calls urepr on this object,
        # preserve the historical formatting on that first call.
        if 'ubelt' in sys.modules:
            from kwconf import _ubelt_repr_extension

            text = _ubelt_repr_extension._late_urepr_fallback(self)
            if text is not None:
                return text
        return super().__repr__()

    def asdict(self) -> Dict[str, Any]:
        if getattr(self, '_has_subconfigs', False):
            from kwconf.subconfig import config_to_nested_dict

            return config_to_nested_dict(self, include_class=False)
        return dict(self._items())

    def to_dict(self) -> Dict[str, Any]:
        return self._asdict()

    def copy(self) -> Dict[str, Any]:
        return dict(self._items())

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __contains__(self, key: object) -> bool:
        # Check _data directly. The Mapping default uses __getitem__, which
        # triggers alias-map construction and would cache an empty map if
        # called before defaults are populated.
        return key in self._data

    def update(self, *args: Any, **kwargs: Any) -> None:
        """
        Update the config with key/value pairs from another mapping or
        from an iterable of pairs, plus keyword arguments. Mirrors
        ``dict.update``.
        """
        if len(args) > 1:
            raise TypeError(
                f'update expected at most 1 positional argument, got {len(args)}'
            )
        if args:
            other = args[0]
            if isinstance(other, _ABCMapping):
                for k in other:
                    self[k] = other[k]
            else:
                for k, v in other:
                    self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def __delitem__(self, key: str) -> None:
        raise TypeError('cannot delete items from a kwconf.Config')

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError('pop is not supported on kwconf.Config')

    def popitem(self) -> Any:
        raise TypeError('popitem is not supported on kwconf.Config')

    def clear(self) -> None:
        raise TypeError('clear is not supported on kwconf.Config')

    def __getitem__(self, key: str) -> Any:
        if (
            isinstance(key, str)
            and '.' in key
            and getattr(self, '_has_subconfigs', False)
        ):
            parts = key.split('.')
            node: Any = self
            for part in parts:
                if not isinstance(node, Config):
                    raise KeyError(key)
                try:
                    value = node._data[part]
                except KeyError:
                    part = node._normalize_alias_key(part)
                    value = node._data[part]
                node = value
            if isinstance(node, Value):
                node = node.value
            return node
        try:
            value = self._data[key]
        except KeyError:
            # Attempt alias
            key = self._normalize_alias_key(key)
            value = self._data[key]

        if isinstance(value, Value):
            value = value.value
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        self._setitem(key, value)

    def _setitem(
        self,
        key: str,
        value: Any,
        validate: bool = True,
        validation_mode: bool | str | None = None,
    ) -> None:
        """
        Core assignment. ``validate=False`` stores a *trusted* value (the
        field's own default during the argv merge) without running annotation
        validation -- defaults are the author's baseline, checked statically,
        not runtime-supplied (design.md §4).
        """
        if (
            isinstance(key, str)
            and '.' in key
            and getattr(self, '_has_subconfigs', False)
        ):
            parts = key.split('.')
            parent_key, leaf = parts[:-1], parts[-1]
            from kwconf.subconfig import _ensure_parent_node

            parent = _ensure_parent_node(self, parent_key)
            parent._setitem(
                leaf,
                value,
                validate=validate,
                validation_mode=validation_mode,
            )
            return
        if key not in self._data:
            key = self._normalize_alias_key(key)
            if key not in self._data:
                if not getattr(self, '__allow_newattr__', False):
                    raise KeyError(
                        'Cannot add keys to kwconf.Config objects unless '
                        'self.__allow_newattr__ is True'
                    )
        if isinstance(value, Value):
            # If the new item is a Value object simply overwrite the old one
            self._data[key] = value
        else:
            template = self.__default__.get(key, None)
            if template is not None and isinstance(template, Value):
                # BOUNDARY (design.md §4): the Python assignment path TRUSTS the
                # user and does NOT coerce strings. Coercion only happens at the
                # text boundary (argv pre-coerces in argparse; Config.coerce()/
                # from_cli/from_env parse explicitly). So store the value as-is.
                coerced = value
                if validate:
                    self._validate_assignment(
                        key, coerced, template, mode=validation_mode
                    )
                self._data[key] = coerced
            else:
                # If we don't have an underlying Value object simply set the
                # raw data.
                self._data[key] = value

    def _validate_assignment(
        self,
        key: str,
        value: Any,
        template: 'Value',
        mode: bool | str | None = None,
    ) -> None:
        """
        Run optional annotation-based validation on an assignment.

        An explicit ``cli(validate=...)`` / ``load(validate=...)`` mode has
        highest precedence. Without one, mode is resolved from
        ``template.validate`` first, falling back to the class-level
        ``__validate__`` attribute (default ``'warn'``).

        Modes:
          * ``'warn'`` (default) -- emit a ``UserWarning`` on mismatch.
          * ``False`` -- no validation.
          * ``'error'`` / ``True`` -- raise :class:`ConfigValidationError`
            (a ``TypeError`` subclass) on mismatch.

        This is the single place kwconf's *value-level* validation reports
        annotation mismatches; the ``coerce``/``auto`` parsers no longer warn
        on a value-level no-match (they best-effort and keep the string), so
        there is one voice for this layer. It runs on user-supplied values
        (constructor/data/assignment and parsed argv/env), but NOT on the
        field's own trusted default (design.md §4), so a WYSIWYG default like
        ``Value('512')`` never warns about itself.

        Scope: ``validate`` governs this Python/programmatic-boundary layer.
        It does NOT soften the argument parser: an annotation the parser can
        enforce directly (notably ``Literal`` -> argparse ``choices=``) is
        still hard-rejected on the ``argv``/``env`` boundary with a
        ``SystemExit`` and usage message, even in ``'warn'`` mode. So for a
        ``Literal`` field, a bad value fails hard on the CLI regardless of
        ``validate``, while ``'warn'`` only warns on the programmatic path;
        ``'error'`` makes the programmatic path hard too (both boundaries
        reject, each with the exception type appropriate to its caller).

        Validation is skipped when the template has no associated
        annotation (e.g. fields declared without a class-level type hint).
        """
        annotation = getattr(template, '_annotation', None)
        if annotation is None:
            return
        if mode is None:
            mode = template.validate
            if mode is None:
                mode = getattr(self, '__validate__', 'warn')
        mode = _normalize_validation_mode(mode)
        if not mode:
            return
        if _value_matches_annotation(value, annotation):
            return
        msg = (
            f'{type(self).__name__}.{key}: value {value!r} does not match '
            f'annotation {_format_annotation(annotation)}'
        )
        if mode == 'warn':
            _warn_user(msg, UserWarning)
        else:
            raise ConfigValidationError(msg)

    def keys(self):
        return self._data.keys()

    def update_defaults(self, default: Mapping[str, Any]) -> None:
        """
        Update the instance-level default values

        Args:
            default (dict): new defaults
        """
        default = dict(self._normalize_alias_dict(default))
        for key, value in default.items():
            if key not in self._default:
                raise KeyError(key)
            self._set_default_value(key, value)
        if default:
            self._index_subconfigs()

    load = _LazyConfigMethod('load', kind='method')

    def _normalize_alias_key(self, key):
        """
        normalizes a single aliased key
        """
        if getattr(self, '_alias_map', None) is None:
            self._alias_map = self._build_alias_map()
        return self._alias_map.get(key, key)  # type: ignore

    def _normalize_alias_dict(self, data):
        """
        Args:
            data (dict): dictionary with keys that could be aliases

        Returns:
            dict: keys are normalized to be primary keys.
        """
        if getattr(self, '_alias_map', None) is None:
            self._alias_map = self._build_alias_map()
        norm: dict[str, Any] = {}
        source: dict[str, str] = {}
        for raw_key, value in data.items():
            key = self._alias_map.get(raw_key, raw_key)  # type: ignore
            if key in norm:
                raise TypeError(
                    f'Multiple input keys {source[key]!r} and {raw_key!r} '
                    f'target configuration field {key!r}'
                )
            norm[key] = value
            source[key] = raw_key
        return norm

    def _build_alias_map(self):
        _alias_map = {}
        for k, v in self._default.items():
            alias = getattr(v, 'alias', None)
            if alias:
                if not iterable(alias):
                    alias = [alias]
                for a in alias:
                    _alias_map[a] = k
        return _alias_map

    _read_argv = _LazyConfigMethod('_read_argv', kind='method')

    def __post_init__(self) -> None:
        """overloadable function called after each load"""
        ...

    dump = _LazyConfigMethod('dump', kind='method')

    dumps = _LazyConfigMethod('dumps', kind='method')

    def __getattr__(self, key: str) -> Any:
        # Note: attributes that mirror the public API will be suppressed.
        # It is generally better to use the dictionary interface instead,
        # but we want this to be data-classy, so...
        if key.startswith('_'):
            # config vars must not start with '_'. That is only for us.
            raise AttributeError(key)
        if key in self:
            try:
                return self[key]
            except KeyError:
                raise AttributeError(key)
        raise AttributeError(key)

    def __dir__(self) -> List[str]:
        initial = cast(List[str], super().__dir__())
        return initial + list(self._keys())

    def __setattr__(self, key: str, value: Any) -> None:
        """
        Forwards setattrs in the configuration to the dictionary interface,
        otherwise passes it through.
        """
        if key.startswith('_'):
            # Currently we do not allow leading underscores to be config
            # values to give us some flexibility for API changes.
            self.__dict__[key] = value
            return
        # The user can opt into adding new keys on the fly:
        can_setattr = getattr(self, '__allow_newattr__', False)
        # Internal: after object initialization allow setattr on existing keys.
        can_setattr |= getattr(self, '_enable_setattr', False) and key in self
        if can_setattr:
            try:
                self[key] = value
            except KeyError:
                raise AttributeError(key)
        else:
            self.__dict__[key] = value

    parse_args = _LazyConfigMethod('parse_args', kind='classmethod')

    parse_known_args = _LazyConfigMethod('parse_known_args', kind='classmethod')

    _register_main = _LazyConfigMethod('_register_main', kind='classmethod')

    _description = _LazyConfigMethod('_description', kind='property')

    _epilog = _LazyConfigMethod('_epilog', kind='property')

    _prog = _LazyConfigMethod('_prog', kind='property')

    _parserkw = _LazyConfigMethod('_parserkw', kind='method')

    port_to_pydantic = _LazyConfigMethod('port_to_pydantic', kind='method')

    port_to_config = _LazyConfigMethod('port_to_config', kind='method')

    _write_code = _LazyConfigMethod('_write_code', kind='classmethod')

    port_from_click = _LazyConfigMethod('port_from_click', kind='classmethod')

    port_from_argparse = _LazyConfigMethod(
        'port_from_argparse', kind='classmethod'
    )

    cls_from_argparse = _LazyConfigMethod(
        'cls_from_argparse', kind='classmethod'
    )

    _values_from_argparse = _LazyConfigMethod(
        '_values_from_argparse', kind='classmethod'
    )

    port_to_argparse = _LazyConfigMethod('port_to_argparse', kind='method')

    # @classmethod
    # def _construct_config_text(cls):
    #     ...

    namespace = _LazyConfigMethod('namespace', kind='property')

    _new_argparse_parser = _LazyConfigMethod(
        '_new_argparse_parser', kind='method'
    )

    def _argument_key_order(self) -> list[str]:
        """Return declaration order with explicit positions first."""
        positions = {
            key: template.position
            for key, template in self._default.items()
            if isinstance(template, Value) and template.position is not None
        }
        if not positions:
            return list(self._data)
        from collections import Counter

        duplicates = [
            position
            for position, count in Counter(positions.values()).items()
            if count > 1
        ]
        if duplicates:
            conflicts = {
                position: sorted(
                    key for key, value in positions.items() if value == position
                )
                for position in duplicates
            }
            raise ValueError(
                f'Multiple fields declare the same CLI position: {conflicts}'
            )
        ordered = sorted(positions, key=positions.__getitem__)
        seen = set(ordered)
        ordered.extend(key for key in self._data if key not in seen)
        return ordered

    _add_special_options = _LazyConfigMethod(
        '_add_special_options', kind='method'
    )

    _populate_argparse_parser = _LazyConfigMethod(
        '_populate_argparse_parser', kind='method'
    )

    argparse = _LazyConfigMethod('argparse', kind='method')

    # Public Config operations are convenient spellings, but declared fields
    # may shadow them on instances. These private aliases are the stable,
    # non-shadowable implementation surface used by kwconf itself and available
    # to callers that need an operation whose public name is also a field.
    _validate = validate
    _coerce = coerce
    _from_cli = from_cli
    _from_yaml = from_yaml
    _from_env = from_env
    _cli = cli
    _demo = demo
    _asdict = asdict
    _to_dict = to_dict
    _copy = copy
    _update = update
    _pop = pop
    _popitem = popitem
    _clear = clear
    _keys = keys
    _get = _ABCMapping.get
    get = _get
    _items = _ABCMapping.items
    items = _items
    _values = _ABCMapping.values
    values = _values
    _update_defaults = update_defaults
    _load = load
    _dump = dump
    _dumps = dumps
    _parse_args = parse_args
    _parse_known_args = parse_known_args
    _port_to_pydantic = port_to_pydantic
    _port_to_config = port_to_config
    _port_from_click = port_from_click
    _port_from_argparse = port_from_argparse
    _cls_from_argparse = cls_from_argparse
    _port_to_argparse = port_to_argparse
    _namespace = namespace
    _argparse = argparse


__notes__ = """
export _ARC_DEBUG=1
pip install argcomplete
activate-global-python-argcomplete --dest=$HOME/.bash_completion.d --user
eval "$(register-python-argcomplete xdev)"
complete -r xdev
"""

# Preserve eager registration only when the caller already imported ubelt.
# The common CLI path should not import kwconf's optional repr bridge at all.
if 'ubelt' in sys.modules:
    from kwconf import _ubelt_repr_extension

    _ubelt_repr_extension._register_if_ubelt_loaded()
