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

import argparse as argparse_mod
import inspect
import itertools as it
import os
import pprint
import sys
import typing
import warnings
from abc import ABCMeta as _ABCMeta
from collections import Counter
from collections.abc import Mapping, Sequence
from collections.abc import Mapping as _ABCMapping
from typing import (
    IO,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    cast,
)

from kwconf import _ubelt_repr_extension, diagnostics
from kwconf.annotations import (
    choices_from_annotation as _choices_from_annotation,
)
from kwconf.annotations import (
    format_annotation as _format_annotation,
)
from kwconf.annotations import (
    get_class_namespace_annotations as _get_class_namespace_annotations,
)
from kwconf.annotations import (
    runtime_type_from_annotation as _runtime_type_from_annotation,
)
from kwconf.annotations import (
    value_matches_annotation as _value_matches_annotation,
)
from kwconf.util.util_misc import copy_value, import_ubelt, iterable
from kwconf.util.util_repr import NiceRepr
from kwconf.util.util_text import codeblock, indent, paragraph
from kwconf.util.util_yaml import import_yaml
from kwconf.value import _Value as Value

# from kwconf.util.util_class import class_or_instancemethod


class ConfigValidationError(TypeError):
    """Raised when strict runtime validation rejects supplied configuration.

    This includes annotation mismatches and opt-in structural input checks,
    such as contradictory SubConfig selector spellings. It subclasses
    :class:`TypeError` so existing ``except TypeError`` handlers keep working,
    while callers can catch this specific type and render a clean diagnostic.
    """


__all__ = ['Config', 'ConfigValidationError', 'define']


ConfigData = (
    Mapping[str, Any]
    | str
    | os.PathLike[str]
    | IO[Any]
    | None
)


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
    runtime_type = _runtime_type_from_annotation(annotation)
    choices = _choices_from_annotation(annotation)

    # A string annotation could not be resolved; there is nothing usable to
    # stash (validation handles unions/Literal natively from real objects).
    has_annotation = annotation is not None and not isinstance(annotation, str)

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
        if typing.get_origin(annotations.get(k)) is typing.ClassVar:
            continue
        if isinstance(v, classmethod) or isinstance(v, staticmethod):
            continue
        # Descriptors define class/instance behavior; they are not declarative
        # field defaults unless explicitly wrapped in Value/SubConfig metadata.
        if hasattr(v, '__get__') and not isinstance(v, Value):
            if not (inspect.isclass(v) and issubclass(v, Config)):
                continue
        if callable(v) and not (inspect.isclass(v) and issubclass(v, Config)):
            continue
        attr_default[k] = _maybe_apply_annotation_to_value(k, v, annotations)
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


def _coerce_data_to_dict(
    data: Any, mode: Optional[str] = None
) -> Dict[str, Any]:
    """Compatibility wrapper around the shared ingestion boundary."""
    from kwconf._ingest import coerce_mapping_source

    return coerce_mapping_source(data, mode=mode)


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


def _config_api_defines_attribute(name: str) -> bool:
    """Return whether the root Config API defines public ``name``."""
    config_type = globals().get('Config')
    return config_type is not None and any(
        name in vars(ancestor) for ancestor in inspect.getmro(config_type)
    )


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
    from kwconf.subconfig import SubConfig

    for key, value in defaults.items():
        normalized_value: Any
        if isinstance(value, SubConfig):
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
            if isinstance(inner, SubConfig):
                if value.help and not inner.help:
                    inner.parsekw['help'] = value.help
                normalized_value = inner
            elif isinstance(inner, Config) or (
                inspect.isclass(inner) and issubclass(inner, Config)
            ):
                normalized_value = SubConfig(inner, help=value.help)
            else:
                normalized_value = value
        elif isinstance(value, Config) or (
            inspect.isclass(value) and issubclass(value, Config)
        ):
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
        if diagnostics.DEBUG_META_CONFIG:
            print(
                f'MetaConfig.__new__ called: {mcls=} {name=} {bases=} {namespace=} {args=} {kwargs=}'
            )

        # Skip class-attr collection on Config itself (the root); all
        # subclasses (user classes) participate.
        is_root_config = (
            name == 'Config' and namespace.get('__module__') == __name__
        )

        annotations = _get_class_namespace_annotations(namespace)

        if not is_root_config:
            attr_default = _collect_declared_config_attrs(
                namespace, annotations
            )
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
                    warnings.warn(
                        paragraph(
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

        if diagnostics.DEBUG_META_CONFIG:
            print(
                'FINAL namespace = {}'.format(pprint.pformat(vars(namespace)))
            )
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
            cls.__init__.__doc__ = codeblock(
                f"""
                Valid options: {valid_keys}

                Args:
                    *args: positional arguments mapped onto declared fields.
                    **kwargs: keyword arguments for any declared field.
                """
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
        new_values = dict(zip(it.islice(self._default, num_args), args))
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
            self._default.update(_materialize_default_items(cls_default))
        self._reset_data_from_defaults(
            _dont_call_post_init=_dont_call_post_init
        )

    def _set_default_value(self, key: str, value: Any) -> None:
        """Replace one instance baseline while preserving field metadata."""
        template = self._default[key]
        if isinstance(value, Value):
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
        """Index SubConfig metadata without mutating default templates."""
        from kwconf.subconfig import SubConfig

        self._subconfig_meta = {
            key: template
            for key, template in self._default.items()
            if isinstance(template, SubConfig)
        }
        self._has_subconfigs = bool(self._subconfig_meta)

    def _reset_data_from_defaults(
        self, *, _dont_call_post_init: bool = False
    ) -> None:
        """Reset current values from the independent instance baseline."""
        from kwconf.subconfig import SubConfig

        self._index_subconfigs()
        values: Dict[str, Any] = {}
        for key, template in self._default.items():
            if isinstance(template, SubConfig):
                values[key] = template.instantiate(
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
        if diagnostics.DEBUG_CONFIG:
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
                print('config = ' + pprint.pformat(dict(self)))
            else:
                rich.print('config = ' + escape(pprint.pformat(dict(self))))
        if diagnostics.DEBUG_CONFIG:
            print(f'[kwconf] Return {cls.__name__}.cli')
        return self

    @classmethod
    def demo(cls) -> 'Config':
        """
        Create an example config class for test cases

        CommandLine:
            xdoctest -m kwconf.config Config.demo
            xdoctest -m kwconf.config Config.demo --cli --option1 fo

        Example:
            >>> from kwconf.config import *
            >>> self = Config.demo()
            >>> print('self = {}'.format(self))
            self = <DemoConfig({...'option1': ...}...)...>...
            >>> self.argparse().print_help()
            >>> # xdoc: +REQUIRES(--cli)
            >>> self.load(argv=True)
            >>> # xdoctest: +REQUIRES(module:ubelt)
            >>> import ubelt as ub
            >>> print(ub.urepr(self, nl=1))
        """
        import kwconf

        class DemoConfig(kwconf.Config):
            """
            This was generated by kwconf.Config.demo
            """

            __default__ = {
                'option1': kwconf.Value('bar', help='an option'),
                'option2': kwconf.Value(
                    (1, 2, 3), tuple, help='another option'
                ),
                'option3': None,
                'option4': 'foo',
                'discrete': kwconf.Value(None, choices=['a', 'b', 'c']),
                'apath': kwconf.Value(None, type=str, help='a path'),
            }

        self = DemoConfig()
        return self

    def __json__(self) -> Dict[str, Any]:
        """
        Creates a JSON serializable representation of this config object.

        Raises:
            TypeError: if any non-builtin python objects without a __json__
                method are encountered.

        Returns:
            dict

        Example:
            >>> self = Config.demo()
            >>> self.__json__()
            >>> self['option1'] = {1, 2, 3}
            >>> self['option2'] = {1: 'one', 'two': 2}
            >>> import json
            >>> json.dumps(self.__json__())
            >>> self['option2'] = {(1, 2): 'fds'}
            >>> import pytest
            >>> with pytest.raises(TypeError):
            >>>     self.__json__()
        """
        numpy: Any
        try:
            import numpy as _numpy
        except ImportError:
            numpy = None
        else:
            numpy = _numpy
        data = self._asdict()

        BUILTIN_SCALAR_TYPES = (str, int, float)
        BUILTIN_VECTOR_TYPES = (set, frozenset, list, tuple)

        # The walker method should be more efficient.
        ub = import_ubelt('Config.__json__')
        walker = ub.IndexableWalker(data, list_cls=BUILTIN_VECTOR_TYPES)
        for path, item in walker:
            if item is None or isinstance(item, BUILTIN_SCALAR_TYPES):
                ...
            elif isinstance(item, list):
                ...
            elif isinstance(item, (set, tuple)):
                walker[path] = list(item)
            elif numpy is not None and isinstance(item, numpy.ndarray):
                walker[path] = item.tolist()
            elif isinstance(item, dict):
                # Preserve insertion order. Sorting is not JSON semantics and
                # fails for otherwise valid mixed scalar keys such as 1 and
                # "one" on Python 3.
                ...
            else:
                if hasattr(item, '__json__'):
                    walker[path] = item.__json__()
                else:
                    raise TypeError(
                        'Unknown JSON serialization for type {!r}'.format(
                            type(item)
                        )
                    )

        # Validate the complete transformed object. In particular, JSON has no
        # representation for complex numbers or tuple-valued mapping keys.
        import json

        json.dumps(data)
        return data

    def __nice__(self) -> str:
        data = self._asdict()
        if isinstance(data, dict):
            data = dict(data)
        return str(data)

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
            warnings.warn(msg, UserWarning, stacklevel=3)
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

    def load(
        self,
        data: ConfigData = None,
        argv: bool | Sequence[str] | str = False,
        mode: str | None = None,
        default: Mapping[str, Any] | None = None,
        strict: bool = False,
        autocomplete: bool | str = False,
        _dont_call_post_init: bool = False,
        special_options: bool | None = None,
        allow_import: bool = True,
        allow_subconfig_overrides: bool = True,
        localns: Mapping[str, Any] | None = None,
        stacklevel: int | None = 0,
        _reset: bool = True,
        validate: bool | str | None = None,
    ) -> Config:
        """
        Updates the configuration from a given data source.

        Any option can be overwritten via the command line if ``argv`` is
        truthy.

        Args:
            data (PathLike | dict):
                Either a path to a yaml / json file or a config dict

            argv (bool | List[str] | str):
                If False, then no command line information is used.
                If True, then sys.argv is parsed and used.
                If a list of strings, that is used instead of sys.argv.
                If a string, then that is parsed using shlex and used instead
                of sys.argv.
                Defaults to False.

            mode (str | None):
                Either json or yaml.

            default (dict | None):
                updated defaults. Note: anything passed to default will be deep
                copied and can be updated by argv or data if it is specified.
                Generally prefer to pass directly to data instead.

            strict (bool):
                if True an error will be raised if the command line
                contains unknown arguments.

            validate (bool | str | None):
                Per-load runtime-validation override. The policy matches
                :meth:`cli`: ``None`` preserves field/class value validation;
                ``False`` disables it for this load; ``'warn'`` enables
                structural diagnostics; and ``'error'`` / ``True`` raises
                :class:`ConfigValidationError` on value or structural failures.

            autocomplete (bool):
                if True, attempts to use the autocomplete package if it is
                available if reading from sys.argv. Defaults to False.

            special_options (bool | None, default=None):
                adds special kwconf options, namely: --config, --dumps,
                and --dump. If None, uses the class attribute __special_options__
                if present, otherwise defaults to False. Opt in by setting
                ``__special_options__ = True`` on the class or by passing
                ``special_options=True`` explicitly.

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

        Note:
            if argv=True, this will create an argument parser.

        Example:
            >>> # Test load works correctly in argv True and False mode
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __default__ = {
            >>>         'src': kwconf.Value(None, help=('some help msg')),
            >>>     }
            >>> data = {'src': 'hi'}
            >>> self = MyConfig.cli(data=data, argv=False)
            >>> assert self['src'] == 'hi'
            >>> self = MyConfig.cli(default=data, argv=[])
            >>> assert self['src'] == 'hi'
            >>> # In 0.5.8 and previous src fails to populate!
            >>> # This is because argv=True overwrites data with defaults
            >>> self = MyConfig.cli(data=data, argv=False)
            >>> assert self['src'] == 'hi', f'Got: {self}'

        Example:
            >>> # Test load works correctly with alias
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __default__ = {
            >>>         'opt1': kwconf.Value(None),
            >>>         'opt2': kwconf.Value(None, alias=['arg2']),
            >>>     }
            >>> config1 = MyConfig(**{'opt2': 'foo'})
            >>> assert config1['opt2'] == 'foo'
            >>> config2 = MyConfig(**{'arg2': 'bar'})
            >>> assert config2['opt2'] == 'bar'
            >>> assert 'arg2' not in config2
        """
        if diagnostics.DEBUG_CONFIG:
            print(
                f'[kwconf.config.Config] Call {self.__class__.__name__}.load',
                f'argv={argv}, strict={strict}, special_options={special_options}',
            )

        validate = _normalize_validation_mode(validate)
        structural_validation = _structural_validation_mode(self, validate)

        if special_options is None:
            special_options = getattr(self, '__special_options__', False)

        if default:
            self._update_defaults(default)

        user_config = _coerce_data_to_dict(data, mode=mode)

        from kwconf import subconfig as _subcfg_mod

        has_subconfigs = getattr(self, '_has_subconfigs', False)
        if not has_subconfigs:
            # Normalize in source order and reject canonical/alias duplicates.
            # The previous set-based pass made the winner hash-seed dependent.
            user_config = self._normalize_alias_dict(user_config)

        # Check unknown values deterministically without destroying aliases or
        # nested mapping shape before the SubConfig boundary sees them.
        unknown_keys = []
        alias_map = self._build_alias_map()
        for raw_key in list(user_config):
            if raw_key in self._default or raw_key in alias_map:
                continue
            if raw_key.startswith('.') or (
                raw_key.startswith('__') and raw_key.endswith('__')
            ):
                user_config.pop(raw_key, None)
            elif has_subconfigs and '.' in raw_key:
                continue
            else:
                unknown_keys.append(raw_key)
        if unknown_keys:
            if strict:
                if diagnostics.DEBUG_CONFIG:
                    print(f'[kwconf.config.Config] Error: data={data}')
                raise KeyError(f'Unknown data options {unknown_keys}')
            for key in unknown_keys:
                user_config.pop(key, None)

        localns = _subcfg_mod.resolve_localns(localns, stacklevel)  # type: ignore
        if _reset:
            self._reset_data_from_defaults(
                _dont_call_post_init=_dont_call_post_init
            )
        # Provenance is scoped to this load call. Clear both snapshots even
        # when argv=False so reusing a Config cannot satisfy required fields
        # with stale history from a prior parse.
        _subcfg_mod.distribute_explicit_argv_keys(self, set())
        _subcfg_mod.distribute_provided_keys(self, set())
        provided_keys: set[str] = set()
        pending_updates = None
        if has_subconfigs:
            if argv:
                # Preserve the original mapping shape until the canonical
                # SubConfig update boundary. Pre-flattening here discards the
                # provenance needed to diagnose nested-vs-dotted conflicts.
                pending_updates = user_config
            else:
                _subcfg_mod.apply_dot_updates(
                    self,
                    user_config,
                    allow_import=allow_import,
                    localns=localns,
                    stacklevel=None,
                    validation_mode=validate,
                    structural_validation=structural_validation,
                    provided_keys=provided_keys,
                )
        else:
            if validate is None:
                self._update(user_config)
            else:
                for key, value in user_config.items():
                    self._setitem(key, value, validation_mode=validate)
            provided_keys.update(user_config)

        if argv or iterable(argv):
            from kwconf._ingest import coerce_argv

            argv = coerce_argv(argv, expand_vars=True)
            next_stacklevel = None if stacklevel is None else stacklevel + 1
            read_argv_kwargs: Dict[str, Any] = {
                'special_options': special_options,
                'strict': strict,
                'autocomplete': autocomplete,
                'argv': None,
                'allow_import': allow_import,
                'allow_subconfig_overrides': allow_subconfig_overrides,
                'pending_updates': pending_updates,
                'localns': localns,
                'stacklevel': next_stacklevel,
                'validation_mode': validate,
                'structural_validation': structural_validation,
            }
            read_argv_kwargs['argv'] = argv
            provided_keys.update(self._read_argv(**read_argv_kwargs))

        _subcfg_mod.distribute_provided_keys(self, provided_keys)

        if not _dont_call_post_init:
            self._validate_required_fields()
            if has_subconfigs:
                _subcfg_mod.finalize_post_init(self)
            else:
                self.__post_init__()
        return self

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

    def _read_argv(
        self,
        argv=None,
        special_options=None,
        strict=False,
        autocomplete=False,
        allow_import=True,
        allow_subconfig_overrides=True,
        pending_updates=None,
        localns=None,
        stacklevel=0,
        validation_mode=None,
        structural_validation=False,
    ):
        """
        Example:
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     'my CLI description'
            >>>     __default__ = {
            >>>         'src':  kwconf.Value(['foo'], position=1, nargs='+'),
            >>>         'dry':  kwconf.Value(False),
            >>>         'approx':  kwconf.Value(False, isflag=True, alias=['a1', 'a2']),
            >>>     }
            >>> self = MyConfig()
            >>> self._read_argv(argv='')
            >>> print('self = {}'.format(self))
            >>> self = MyConfig()
            >>> # nargs='+' makes argparse build a list from each space-separated
            >>> # token. kwconf does not split commas inside an individual token.
            >>> self._read_argv(argv='--src a b')
            >>> print('self = {}'.format(self))
            >>> self = MyConfig()
            >>> self._read_argv(argv='--src a b --a1')
            >>> print('self = {}'.format(self))
            self = <MyConfig({'src': ['foo'], 'dry': False, 'approx': False})>
            self = <MyConfig({'src': ['a', 'b'], 'dry': False, 'approx': False})>
            self = <MyConfig({'src': ['a', 'b'], 'dry': False, 'approx': True})>

            >>> self = MyConfig()
            >>> self._read_argv(argv='p1 p2 p3')
            >>> print('self = {}'.format(self))
            >>> self = MyConfig()
            >>> # ``--src=p4,p5,p6!`` is a single token: kwconf does NOT split it.
            >>> self._read_argv(argv='--src=p4,p5,p6!')
            >>> print('self = {}'.format(self))
            >>> self = MyConfig()
            >>> self._read_argv(argv='p1 p2 p3 --src=p4,p5,p6!')
            >>> print('self = {}'.format(self))
            self = <MyConfig({'src': ['p1', 'p2', 'p3'], 'dry': False, 'approx': False})>
            self = <MyConfig({'src': ['p4,p5,p6!'], 'dry': False, 'approx': False})>
            self = <MyConfig({'src': ['p4,p5,p6!'], 'dry': False, 'approx': False})>

            >>> self = MyConfig()
            >>> self._read_argv(argv='p1')
            >>> print('self = {}'.format(self))
            >>> self = MyConfig()
            >>> self._read_argv(argv='--src=p4')
            >>> print('self = {}'.format(self))
            >>> self = MyConfig()
            >>> self._read_argv(argv='p1 --src=p4')
            >>> print('self = {}'.format(self))
            self = <MyConfig({'src': ['p1'], 'dry': False, 'approx': False})>
            self = <MyConfig({'src': ['p4'], 'dry': False, 'approx': False})>
            self = <MyConfig({'src': ['p4'], 'dry': False, 'approx': False})>

            >>> special_options = False
            >>> parser = self.argparse(special_options=special_options)
            >>> parser.print_help()
            >>> x = parser.parse_known_args()

        Example:
            >>> import kwconf
            >>> import pytest
            >>> class EmptyConfig(kwconf.Config):
            >>>     ...
            >>> self = EmptyConfig()
            >>> with pytest.raises(Exception) as ex:
            >>>     self._read_argv(argv=32132)

        Ignore:
            >>> # Weird cases
            >>> self = MyConfig()
            >>> self._read_argv(argv='--src=[p4,p5,p6!] f of')
            >>> print('self = {}'.format(self))

            >>> self = MyConfig()
            >>> self._read_argv(argv='--src=p4,')
            >>> print('self = {}'.format(self))

            >>> self = MyConfig()
            >>> self._read_argv(argv='a b --src p4 p5 p6!')
            >>> print('self = {}'.format(self))

            >>> self = MyConfig()
            >>> self._read_argv(argv='--src=p4 p5 p6!')
            >>> print('self = {}'.format(self))

            >>> self = MyConfig()
            >>> self._read_argv(argv='p1 p2 p3!')
            >>> print('self = {}'.format(self))

        Example:
            >>> # SubConfig case: staged parsing + dotted overrides
            >>> import kwconf
            >>> import pytest
            >>> class Adam(kwconf.Config):
            ...     __default__ = {'lr': 1e-3}
            >>> class Sgd(kwconf.Config):
            ...     __default__ = {'momentum': 0.9}
            >>> class TrainCfg(kwconf.Config):
            ...     __default__ = {
            ...         'optim': kwconf.SubConfig(Adam, choices={'adam': Adam, 'sgd': Sgd}),
            ...     }
            >>> cfg = TrainCfg()
            >>> cfg._read_argv(argv='--optim=sgd --optim.momentum=0.8')
            >>> assert isinstance(cfg['optim'], Sgd) and cfg['optim']['momentum'] == 0.8
            >>> print('Test error case:')
            >>> with pytest.raises(SystemExit) as ex:
            ...     cfg._read_argv(argv='--optim.unknown=1', strict=True)
            >>> print(f'Got expected error: {ex}')
            >>> print('Test success case:')
            >>> cfg._read_argv(argv='--optim=sgd --optim.momentum=0.8')
            >>> # xdoctest: +REQUIRES(module:yaml)
            >>> print(cfg.dumps())
            >>> assert isinstance(cfg['optim'], Sgd) and cfg['optim']['momentum'] == 0.8
        """
        if special_options is None:
            special_options = getattr(self, '__special_options__', False)

        if argv is not None:
            from kwconf._ingest import coerce_argv

            argv = coerce_argv(argv)

        provided_keys: set[str] = set()

        # TODO: warn about any unused flags
        has_subconfigs = getattr(self, '_has_subconfigs', False)
        if has_subconfigs:
            # Start from a bare root parser. The multipass helper realizes the
            # selected tree and extends this exact parser once; pre-populating it
            # with the default variant would create duplicate/stale arguments.
            from kwconf import subconfig as _subcfg_mod

            parser = self._new_argparse_parser()
            localns = _subcfg_mod.resolve_localns(localns, stacklevel)
            parser, argv = _subcfg_mod.expand_multipass_parser(
                self,
                parser=parser,
                argv=argv,
                special_options=special_options,
                allow_import=allow_import,
                allow_subconfig_overrides=allow_subconfig_overrides,
                pending_updates=pending_updates,
                localns=localns,
                stacklevel=None,
                validation_mode=validation_mode,
                structural_validation=structural_validation,
                provided_keys=provided_keys,
            )
        else:
            parser = self._argparse(special_options=special_options)

        if autocomplete:
            try:
                import argcomplete as argcomplete_mod
            except ImportError:
                if autocomplete != 'auto':
                    raise
            else:
                argcomplete_mod.autocomplete(parser)

        try:
            from kwconf import argparse_ext

            if strict:
                parse_result = argparse_ext.parse_result(parser, argv)
            else:
                parse_result = argparse_ext.parse_known_result(parser, argv)
            ns = parse_result.values
            explicit_keys = set(parse_result.explicit_keys)
        except (ValueError, TypeError, KeyError) as ex:
            # For errors (like ValueError) where its probably a programmer
            # error and not a user error, give the debugger some information
            # about the kwconf object.
            from kwconf.util import util_exception

            # TODO: figure out argv that triggers a value error so we can add a test
            note = codeblock(
                f"""
                Error while attempting to parse arguments in _read_argv

                Context:
                    argv = {argv!r}
                    special_options = {special_options!r}
                    strict = {strict!r}
                    autocomplete = {autocomplete!r}
                    self = {self!r}
                """
            )
            print(note)
            ex = util_exception.add_exception_note(ex, note)
            raise ex

        special_ns_keys = ['config', 'dump', 'dumps']
        if special_options:
            special_ns = {k: ns.pop(k, None) for k in special_ns_keys}
        else:
            special_ns = {}

        if has_subconfigs:
            # Selector options were already applied while realizing the parser
            # schema. The final parse only needs to remove them from the leaf
            # value update set; applying them again would reconstruct the same
            # SubConfig and erase lower-precedence data/config values.
            from kwconf import subconfig as _subcfg_mod

            subconfig_paths = set(_subcfg_mod.find_subconfig_paths(self))
            if explicit_keys:
                selector_keys = {
                    k
                    for k in explicit_keys
                    if k.endswith('.__class__') or k in subconfig_paths
                }
                if selector_keys:
                    for key in selector_keys:
                        ns.pop(key, None)
                    explicit_keys = explicit_keys - selector_keys
            if subconfig_paths:
                for key in subconfig_paths:
                    ns.pop(key, None)
                explicit_keys = {
                    key for key in explicit_keys if key not in subconfig_paths
                }
        # Then load config file defaults. Merge (not reset): a full load()
        # would first restore every key to its default, wiping data= values
        # for keys the file never mentions.
        if special_options:
            config_fpath = special_ns['config']
            if config_fpath is not None and not has_subconfigs:
                # Nested configs apply --config during parser realization so
                # selector-dependent arguments exist before the final parse.
                # Flat configs still load the file here.
                self._load(
                    config_fpath,
                    argv=False,
                    _dont_call_post_init=True,
                    _reset=False,
                    validate=(False if has_subconfigs else validation_mode),
                )
                provided_keys.update(self._provided_keys)

        # Finally load explicit CLI values. The parser action has already
        # coerced the raw token; we just need to store it.
        for key in explicit_keys:
            if key not in special_ns:
                self._setitem(key, ns[key], validation_mode=validation_mode)

        # Record argv provenance once values (and any subconfig class swaps)
        # are finalized. Use the raw ParseResult set so the snapshot faithfully
        # reflects what argv supplied -- including ``.__class__`` selectors --
        # then distribute the dotted keys to the realized subconfig children.
        # Only the special-options destinations (config/dump/dumps) are
        # dropped, since those are CLI plumbing rather than config fields.
        from kwconf import subconfig as _subcfg_mod

        recorded_keys = {
            key
            for key in parse_result.explicit_keys
            if key not in special_ns_keys
        }
        _subcfg_mod.distribute_explicit_argv_keys(self, recorded_keys)
        provided_keys.update(recorded_keys)

        if special_options:
            dump_fpath = special_ns['dump']
            do_dumps = special_ns['dumps']
            if dump_fpath or do_dumps:
                if dump_fpath:
                    # Infer config format from the extension (yaml default).
                    if dump_fpath.lower().endswith('.json'):
                        mode = 'json'
                    else:
                        mode = 'yaml'
                    text = self._dumps(mode=mode)
                    with open(dump_fpath, 'w') as file:
                        file.write(text)

                if do_dumps:
                    # Always use yaml to dump to stdout
                    text = self._dumps(mode='yaml')
                    print(text)

                # A successful dump is a success: exit 0 so shell pipelines
                # like ``tool --dumps > config.yaml`` do not report failure.
                sys.exit(0)
        return provided_keys

    def __post_init__(self) -> None:
        """overloadable function called after each load"""
        ...

    def dump(
        self, stream: Optional[IO[str]] = None, mode: Optional[str] = None
    ):
        """
        Write configuration file to a file or stream

        Args:
            stream (IO[str] | None): the writable stream to write to
            mode (str | None): can be 'yaml' or 'json' (defaults to 'yaml')
        """
        if mode is None:
            mode = 'yaml'
        if getattr(self, '_has_subconfigs', False):
            from kwconf.subconfig import config_to_nested_dict

            payload = config_to_nested_dict(self, include_class=True)
        else:
            payload = dict(self._items())
        if mode == 'yaml':
            yaml = import_yaml("dump(mode='yaml')")

            # Use a local Dumper subclass; registering the representer on the
            # shared yaml.SafeDumper would change the behavior of every other
            # safe_dump call in the process. (The ignore is because PyYAML is
            # imported lazily, so the base is a local name to a checker.)
            class _OrderedDumper(yaml.SafeDumper):  # type: ignore[name-defined]
                ...

            def order_rep(dumper, data):
                return dumper.represent_mapping(
                    'tag:yaml.org,2002:map', data.items(), flow_style=False
                )

            _OrderedDumper.add_representer(dict, order_rep)
            yaml.dump(payload, stream, Dumper=_OrderedDumper)  # type: ignore
        elif mode == 'json':
            import json

            json.dump(payload, stream, indent=4)  # type: ignore
        else:
            raise KeyError(mode)

    def dumps(self, mode: Optional[str] = None) -> str:
        """
        Write the configuration to a text object and return it

        Args:
            mode (str | None): can be 'yaml' or 'json' (defaults to 'yaml')

        Returns:
            str - the configuration as a string
        """
        import io

        stream = io.StringIO()
        self._dump(stream=stream, mode=mode)
        return stream.getvalue()

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

    @classmethod
    def parse_args(
        cls, args: Optional[List[str]] = None, namespace: Optional[Any] = None
    ) -> 'Config':
        """
        Mimics :meth:`argparse.ArgumentParser.parse_args`.
        """
        if namespace is not None:
            raise NotImplementedError('namespaces are not handled in kwconf')
        return cls._cli(argv=args, strict=True)

    @classmethod
    def parse_known_args(
        cls, args: Sequence[str] | None = None, namespace: Any = None
    ) -> 'Config':
        """
        Mimics :meth:`argparse.ArgumentParser.parse_known_args`.
        """
        if namespace is not None:
            raise NotImplementedError('namespaces are not handled in kwconf')
        return cls._cli(argv=args, strict=False)

    @classmethod
    def _register_main(cls, func):
        """
        Register a function as the main method for this config CLI.
        """
        cls.main = func  # type: ignore[attr-defined]
        return func

    @property
    def _description(self) -> Optional[str]:
        """
        The argparse ``description`` for this config's CLI -- the prose
        block printed near the top of ``--help`` between the usage line
        and the argument table.

        Resolved in order: the class attribute ``__description__`` if set,
        otherwise the class docstring, otherwise a diagnostic
        ``no description for <module>.<qualname>`` fallback. The result is run
        through :func:`ubelt.codeblock` so that triple-quoted indented strings
        render cleanly.
        """
        description = getattr(self, '__description__', None)
        if description is None:
            description = self.__class__.__doc__
        if description is None:
            # Diagnostic fallback: name the class that is missing a description
            # by its fully-qualified ``module.qualname`` so the author can see
            # exactly where it comes from. Deterministic (no version string).
            cls = self.__class__
            description = (
                f'no description for {cls.__module__}.{cls.__qualname__}'
            )
        if description is not None:
            description = codeblock(description)
        return description

    @property
    def _epilog(self) -> Optional[str]:
        """
        The argparse ``epilog`` for this config's CLI -- the prose block
        printed at the bottom of ``--help``, after the argument table.
        Typically used for examples or "see also" notes.

        Pulled from the class attribute ``__epilog__`` if set, otherwise
        ``None`` (argparse omits the epilog entirely). The result is run
        through :func:`ubelt.codeblock` so that triple-quoted indented
        strings render cleanly.
        """
        epilog = getattr(self, '__epilog__', None)
        if epilog is not None:
            epilog = codeblock(epilog)
        return epilog

    @property
    def _prog(self) -> Optional[str]:
        """
        The argparse ``prog`` for this config's CLI -- the program name
        shown in the usage line (e.g. ``usage: <prog> [-h] ...``).

        Pulled from the class attribute ``__prog__`` if set, otherwise the
        config class's own name. Note that argparse will fall back to
        ``sys.argv[0]`` if ``prog`` is ``None``; we explicitly use the
        class name so help output is stable regardless of how the script
        was invoked.
        """
        prog = getattr(self, '__prog__', None)
        if prog is None:
            prog = self.__class__.__name__
        return prog

    def _parserkw(self) -> dict:
        """
        Generate the kwargs for making a new argparse.ArgumentParser
        """
        from kwconf import argparse_ext

        parserkw = dict(
            prog=self._prog,
            description=self._description,
            epilog=self._epilog,
            # formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            # formatter_class=argparse.RawDescriptionHelpFormatter,
            formatter_class=argparse_ext.RawDescriptionDefaultsHelpFormatter,
            # exit_on_error=False,
        )
        if hasattr(self, '__allow_abbrev__'):
            parserkw['allow_abbrev'] = self.__allow_abbrev__
        return parserkw

    def port_to_config(self, style: str = 'config') -> str:
        """
        Helper that writes kwconf source code for this config.

        CommandLine:
            xdoctest -m kwconf.config Config.port_to_config

        Example:
            >>> import kwconf
            >>> self = kwconf.Config.demo()
            >>> print(self.port_to_config())
        """
        entries = []
        for key, value in self.__default__.items():
            if not isinstance(value, Value):
                value_kw = Value(value)._to_value_kw()
            else:
                value_kw = value._to_value_kw()
            entries.append((key, value_kw))
        description = self._description
        name = self.__class__.__name__
        text = self._write_code(entries, name, style, description)
        return text

    @classmethod
    def _write_code(
        self,
        entries: Iterable[tuple[str, Mapping[str, Any]]],
        name: str = 'MyConfig',
        style: str = 'config',
        description: Optional[str] = None,
    ) -> str:

        if style == 'config':
            pad = ' ' * 4
        else:
            pad = ' ' * 8

        if style == 'orig':
            raise NotImplementedError("style='orig' is no longer supported")
        elif style == 'config':
            recon_str = [
                'import kwconf',
                '',
                'class ' + name + '(kwconf.Config):',
                '    """',
                indent(description or ''),
                '    """',
            ]
        else:
            raise KeyError(style)

        for key, value_kw in entries:
            _value_kw = dict(value_kw)

            value_args = []
            if 'default' in _value_kw:
                default = _value_kw.pop('default')
                value_args.append(repr(default))
            value_args.extend(
                [
                    '{}={}'.format(k, repr(v))
                    for k, v in _value_kw.items()
                    if v is not None
                ]
            )
            val_body = ', '.join(value_args)

            if style == 'orig':
                recon_str.append(
                    "{}'{}': kwconf.Value({}),".format(pad, key, val_body)
                )
            elif style == 'config':
                recon_str.append(
                    '{}{} = kwconf.Value({})'.format(pad, key, val_body)
                )
            else:
                raise KeyError(style)

        if style == 'orig':
            recon_str.append('    }')
        elif style == 'config':
            ...
        else:
            raise KeyError(style)
        text = '\n'.join(recon_str)
        return text

    @classmethod
    def port_from_click(cls, click_main, name=None, style='config') -> str:
        """
        Prints kwconf code that roughly implements some click CLI.

        Args:
            click_main (click.core.Command): command to port

            name (str | None): the name of the new class, if None then
               uses the name of the CLI command.

            style (str): either 'config' or 'orig'

        Returns:
            str : The code that roughly implements the config class.

        CommandLine:
            xdoctest -m kwconf.config Config.port_from_click

        Example:
            >>> # xdoctest: +REQUIRES(module:click)
            >>> from kwconf.config import *  # NOQA
            >>> import click
            >>> import kwconf
            >>> @click.command()
            >>> @click.option('--dataset', required=True, type=click.Path(exists=True), help='input dataset')
            >>> @click.option('--deployed', required=True, type=click.Path(exists=True), help='weights file')
            >>> @click.option('--key1', default=123,  help='some key')
            >>> @click.option('--key2', default='456', help='another key')
            >>> def click_main(dataset, deployed, key1, key2):
            >>>     ...
            >>> text = kwconf.Config.port_from_click(click_main)
            >>> print(text)
            import kwconf
            ...
            class click_main(kwconf.Config):
                ...
                no description for builtins.click_main
                ...
                dataset = kwconf.Value(None, required=True, help='input dataset')
                deployed = kwconf.Value(None, required=True, help='weights file')
                key1 = kwconf.Value(123, help='some key')
                key2 = kwconf.Value('456', help='another key')
        """
        import click

        ctx = click.Context(click.Command(''))
        info_dict = click_main.to_info_dict(ctx)  # NOQA
        default = {}
        blocklist = {'help'}
        for param in info_dict['params']:
            if param['name'] in blocklist:
                continue
            default[param['name']] = Value(
                param['default'],
                required=param['required'],
                isflag=param['is_flag'],
                help=param['help'],
            )
        if name is None:
            name = info_dict['name'].replace('-', '_')
        config_cls = define(default, name)
        instance = config_cls(_dont_call_post_init=True)
        return instance._port_to_config(style=style)

    @classmethod
    def port_from_argparse(
        cls,
        parser: 'argparse_mod.ArgumentParser',
        name: str = 'MyConfig',
        style: str = 'config',
    ) -> str:
        """
        Generate the corresponding kwconf code from an existing argparse
        instance.

        Args:
            parser (argparse.ArgumentParser):
                existing argparse parser we want to port
            name (str): the name of the config class
            style (str): either 'orig' or 'config'

        Returns:
            str :
                code to create a kwconf object that should work similarly
                to the existing argparse object.

        Note:
            The correctness of this function is not guaranteed.  This only
            works perfectly in simple cases, but in complex cases it may not
            produce 1-to-1 results, however it will provide a useful starting
            point.

        TODO:
            - [X] Handle "store_true".
            - [ ] Argument groups.
            - [ ] Handle mutually exclusive groups

        Example:
            >>> import kwconf
            >>> import argparse
            >>> parser = argparse.ArgumentParser(description='my argparse')
            >>> parser.add_argument('pos_arg1')
            >>> parser.add_argument('pos_arg2', nargs='*')
            >>> parser.add_argument('-t', '--true_dataset', '--test_dataset', help='path to the groundtruth dataset', required=True)
            >>> parser.add_argument('-p', '--pred_dataset', help='path to the predicted dataset', required=True)
            >>> parser.add_argument('--eval_dpath', help='path to dump results')
            >>> parser.add_argument('--draw_curves', default='auto', help='flag to draw curves or not')
            >>> parser.add_argument('--score_space', default='video', help='can score in image or video space')
            >>> parser.add_argument('--workers', default='auto', help='number of parallel scoring workers')
            >>> parser.add_argument('--draw_workers', default='auto', help='number of parallel drawing workers')
            >>> group1 = parser.add_argument_group('mygroup1')
            >>> group1.add_argument('--group1_opt1', action='store_true')
            >>> group1.add_argument('--group1_opt2')
            >>> group2 = parser.add_argument_group()
            >>> group2.add_argument('--group2_opt1', action='store_true')
            >>> group2.add_argument('--group2_opt2')
            >>> mutex_group3 = parser.add_mutually_exclusive_group()
            >>> mutex_group3.add_argument('--mgroup3_opt1')
            >>> mutex_group3.add_argument('--mgroup3_opt2')
            >>> text = kwconf.Config.port_from_argparse(parser, name='PortedConfig', style='config')
            >>> print(text)
            >>> # Make an instance of the ported class
            >>> vals = {}
            >>> exec(text, vals)
            >>> cls = vals['PortedConfig']
            >>> self = cls(**{'true_dataset': 1, 'pred_dataset': 1})
            >>> recon = self.argparse()
            >>> # xdoctest: +REQUIRES(module:ubelt)
            >>> import ubelt as ub
            >>> print('recon._actions = {}'.format(ub.urepr(recon._actions, nl=1)))
        """
        entries = cls._values_from_argparse(parser)
        description = parser.description
        text = cls._write_code(entries, name, style, description)
        return text

    @classmethod
    def cls_from_argparse(cls, parser, name=None, description=None) -> type:
        """
        Create a full configuration class from an existing argparse parser.

        Args:
            parser (argparse.ArgumentParser):
                The parser we will use to dynamically create a kwconf class

            name (str): the name of the new class.
                If unspecified, the name will be ``"Dynamic" + cls.__name__``

            description (None | str):
                if specified override the description from the parser.

        Returns:
            Config: a subclass of the Config class.

        SeeAlso:
            :func:`Config.port_from_argparse` - like this function, but returns
                the text that could be executed to define the new class
                statically.  In constrat this creates the clas dynamically.

        CommandLine:
            xdoctest -m kwconf.config Config.cls_from_argparse

        Example:
            >>> import kwconf
            >>> import argparse
            >>> parser = argparse.ArgumentParser(description='my argparse')
            >>> parser.add_argument('pos_arg1')
            >>> parser.add_argument('pos_arg2', nargs='*')
            >>> parser.add_argument('-t', '--true_dataset', '--test_dataset', help='path to the groundtruth dataset', required=True)
            >>> parser.add_argument('-p', '--pred_dataset', help='path to the predicted dataset', required=True)
            >>> parser.add_argument('--eval_dpath', help='path to dump results')
            >>> parser.add_argument('--draw_curves', default='auto', help='flag to draw curves or not')
            >>> parser.add_argument('--score_space', default='video', help='can score in image or video space')
            >>> parser.add_argument('--workers', default='auto', help='number of parallel scoring workers')
            >>> parser.add_argument('--draw_workers', default='auto', help='number of parallel drawing workers')
            >>> group1 = parser.add_argument_group('mygroup1')
            >>> group1.add_argument('--group1_opt1', action='store_true')
            >>> group1.add_argument('--group1_opt2')
            >>> group2 = parser.add_argument_group()
            >>> group2.add_argument('--group2_opt1', action='store_true')
            >>> group2.add_argument('--group2_opt2')
            >>> mutex_group3 = parser.add_mutually_exclusive_group()
            >>> mutex_group3.add_argument('--mgroup3_opt1')
            >>> mutex_group3.add_argument('--mgroup3_opt2')
            >>> DynamicClass = kwconf.Config.cls_from_argparse(parser)
            >>> # xdoctest: +REQUIRES(module:ubelt)
            >>> import ubelt as ub
            >>> print(f'DynamicClass.__default__ = {ub.urepr(DynamicClass.__default__, nl=1)}')
            >>> self = DynamicClass()
            >>> print(f'self = {ub.urepr(self, nl=1)}')
            >>> # Check to see if ithis roundtrips nicelyprint(self.port_to_argparse())
            >>> print(self.port_to_argparse())
            >>> parser = self.argparse()
        """

        if name is None:
            name = 'Dynamic' + cls.__name__

        # Extract the appropriate values from the parser
        values = cls._values_from_argparse(parser, for_text=False)

        bases = (cls,)  # Base classes, object is the default base class
        attributes = {
            '__doc__': description or parser.description,
            '__default__': dict(values),
        }

        # Dynamically create the class (
        # note, cls.__class__ should be MetaConfig)
        DynamicClass = cls.__class__(name, bases, attributes)  # type: ignore[call-overload]
        return DynamicClass

    @classmethod
    def _values_from_argparse(cls, parser, for_text=True) -> list:
        """
        Port argparse options to a list of key / values.
        """
        # This logic should be able to be used statically or dynamically
        # to transition argparse back to kwconf config classes.
        pos_counter = it.count(1)

        # Determine if the parser has groups / mutex groups. Build mappings so
        # we can lookup which action is associated with which group later.
        group_counter = it.count(1)
        mgroup_counter = it.count(1)
        annon_groupid_to_key = {}
        annon_mgroupid_to_key = {}
        default_groups = {'positional arguments', 'options', 'required'}
        actionid_to_groupkey = {}
        actionid_to_mgroupkey = {}
        # Build group lookups table
        for group in parser._action_groups:
            if group.title not in default_groups:
                if group.title is not None:
                    group_key = group.title
                else:
                    group_id = id(group)
                    if group_id not in annon_groupid_to_key:
                        annon_groupid_to_key[group_id] = next(group_counter)
                    group_key = annon_groupid_to_key[group_id]
                for action in group._group_actions:
                    action_id = id(action)
                    actionid_to_groupkey[action_id] = group_key
        # Build mutex group lookups table
        for mutex_group in parser._mutually_exclusive_groups:
            mgroup_id = id(mutex_group)
            if mgroup_id not in annon_mgroupid_to_key:
                annon_mgroupid_to_key[mgroup_id] = next(mgroup_counter)
            mgroup_key = annon_mgroupid_to_key[mgroup_id]
            for action in mutex_group._group_actions:
                action_id = id(action)
                actionid_to_mgroupkey[action_id] = mgroup_key

        # Iterate over all of the actions and build the appropriate value to be
        # placed in the kwconf class.
        entries = []
        for action in parser._actions:
            key = action.dest
            if key == 'help':
                # kwconf takes care of help for us
                continue
            value = Value._from_action(
                action, actionid_to_groupkey, actionid_to_mgroupkey, pos_counter
            )
            if for_text:
                # Use for the text reconstruction of the argparser, this is
                # very hacky.
                value_kw = value._to_value_kw()
                entries.append((key, value_kw))
            else:
                entries.append((key, value))
        return entries

    def port_to_argparse(
        self,
        fuzzy_hyphens: bool = False,
        flag_value_mode: bool = False,
        kwconf_primatives: bool = False,
    ) -> str:
        """
        Attempt to make code for a nearly-equivalent argparse object.

        This code only handles basic cases. Some of the kwconf magic is
        dropped by default so we dont need to rely on custom actions.

        By default this emits plain argparse-compatible code. Opt in to closer
        behavior with:

        * ``fuzzy_hyphens=True`` to emit underscore / hyphen long-option
          variants (e.g., ``--my_opt`` and ``--my-opt``).
        * ``flag_value_mode=True`` to preserve kwconf boolean / counter
          flag actions, which support both ``--flag`` and ``--flag=value``.

        The idea is that sometimes we can't depend on kwconf, so it would
        be nice to be able to translate an existing kwconf class to the
        nearly equivalent argparse code.

        Args:
            fuzzy_hyphens (bool):
                If True, emit both underscore and hyphen long-option variants
                for keys / aliases that contain underscores.

            flag_value_mode (bool):
                If True, preserve kwconf-like flexible flag parsing in
                generated code using local argparse actions (supports
                ``--flag`` and ``--flag=value`` forms for boolean / counter
                flags).

            kwconf_primatives (bool):
                If True, emit the 1-to-1 experience that *depends on kwconf*:
                the generated code imports ``kwconf.argparse_ext`` and
                ``kwconf.coerce`` and wires each argument with the real
                argparse_ext actions and our annotation-gated coerce as
                ``type=``. This reproduces kwconf's CLI behavior exactly at the
                cost of a small kwconf dependency, bypassing the vendored
                lightweight reconstructions. When False (default), the generated
                code is plain argparse with lightweight approximations (opt into
                individual QoL features via ``flag_value_mode`` etc.).

        SeeAlso:
            :meth:`Config.argparse` - creates a real argparse object

        Returns:
            str: code to construct a similar argparse object

        CommandLine:
            xdoctest -m kwconf.config Config.port_to_argparse

        Example:
            >>> import kwconf
            >>> class DemoCLI(kwconf.Config):
            >>>     my_opt = kwconf.Value('v1', help='demo option')
            >>>     flag = kwconf.Value(False, isflag=True, help='demo flag')
            >>> text = DemoCLI().port_to_argparse(
            >>>     fuzzy_hyphens=True, flag_value_mode=True)
            >>> print(text)
            >>> assert 'parser = argparse.ArgumentParser(' in text
            >>> assert '--my_opt' in text and '--my-opt' in text
            >>> assert '_PortedBooleanFlagOrKeyValAction' in text
            >>> assert 'from kwconf' not in text

        Example:
            >>> import kwconf
            >>> class SimpleCLI(kwconf.Config):
            >>>     data = kwconf.Value(None, help='input data', position=1)
            >>> self = SimpleCLI()
            >>> text = self.port_to_argparse()
            >>> print(text)
            >>> assert "parser.add_argument('data'" in text
            >>> assert "nargs='?'" in text
            >>> assert "default=argparse.SUPPRESS" in text
            >>> # Test that the generated code is executable
            >>> ns = {}
            >>> exec(text, ns, ns)
            >>> parser = ns['parser']
            >>> args1 = parser.parse_args(['foobar'])
            >>> assert args1.data == 'foobar'
            >>> args2 = parser.parse_args(['--data=blag'])
            >>> assert args2.data == 'blag'
            >>> args3 = parser.parse_args(['foo', '--data=bar'])
            >>> assert args3.data == 'bar'
            >>> # Demonstrate roundtrip behavior for representative argv cases
            >>> orig = self.argparse(special_options=False)
            >>> for argv in [['foobar'], ['--data=blag'], ['foo', '--data=bar']]:
            >>>     got_orig = vars(orig.parse_args(argv))
            >>>     got_port = vars(parser.parse_args(argv))
            >>>     assert got_orig == got_port
        """
        ub = import_ubelt('port_to_argparse')
        parserkw = self._parserkw()
        to_pop = {k for k, v in parserkw.items() if v is None}
        parserkw = {k: v for k, v in parserkw.items() if k not in to_pop}
        parserkw.pop('formatter_class', None)

        constructor_body = indent(ub.urepr(parserkw, explicit=True, nobr=1))  # type: ignore

        def _annotation_to_code(ann: Any) -> str:
            # Render an annotation as code for the emitted coerce partial.
            # Builtins/types use their name; typing / PEP 604 forms repr cleanly
            # (``str | int | None``, ``list[int]``, ``typing.Optional[int]``).
            if ann is None:
                return 'None'
            if isinstance(ann, type):
                return ann.__name__
            return repr(ann)

        lines = []
        if kwconf_primatives:
            lines.append(
                codeblock(
                    """
                import functools
                import typing  # noqa: F401  (used by emitted annotations)
                from kwconf import argparse_ext
                from kwconf import coerce as _kwconf_coerce
                """
                )
            )
        lines.append(
            codeblock(
                """
            import argparse
            parser = argparse.ArgumentParser(
            {constructor_body}
                formatter_class=argparse.RawDescriptionHelpFormatter,
            )
            """
            ).format(
                constructor_body=constructor_body,
            )
        )

        from kwconf import value as value_mod

        need_ported_bool_action = False
        need_ported_counter_action = False
        for key, _value in self._data.items():
            if isinstance(_value, value_mod._Value):
                value = _value.value
            else:
                value = _value
                _value = self._default[key]
                if not isinstance(_value, value_mod._Value):
                    # hack
                    _value = value_mod._Value(_value)

            invocations = value_mod._value_add_argument_kw(
                value, _value, self, key, fuzzy_hyphens=fuzzy_hyphens
            )
            has_key_value_variant = 'key_value' in invocations
            for arg_type, t in invocations.items():
                meth, args, kwargs = t
                if arg_type == 'positional' and has_key_value_variant:
                    # kwconf positional arguments can usually be supplied
                    # either positionally or via --key=value. Make the
                    # generated positional optional to allow key/value-only use.
                    if kwargs.get('nargs', None) is None:
                        kwargs['nargs'] = '?'
                    # Avoid overriding values set by the --key form when the
                    # positional argument is omitted.
                    kwargs['default'] = value_mod.CodeRepr('argparse.SUPPRESS')
                action = kwargs.get('action')
                action_name = (
                    getattr(action, '__name__', '')
                    if not isinstance(action, str)
                    else ''
                )
                is_flag_action = action_name in (
                    'BooleanFlagOrKeyValAction',
                    'CounterOrKeyValAction',
                )
                if not isinstance(action, str):
                    if kwconf_primatives and is_flag_action:
                        # Use the real argparse_ext actions (1-to-1; depends on kwconf).
                        kwargs['action'] = value_mod.CodeRepr(
                            f'argparse_ext.{action_name}'
                        )
                    elif (
                        flag_value_mode
                        and action_name == 'BooleanFlagOrKeyValAction'
                    ):
                        kwargs['action'] = value_mod.CodeRepr(
                            '_PortedBooleanFlagOrKeyValAction'
                        )
                        need_ported_bool_action = True
                    elif (
                        flag_value_mode
                        and action_name == 'CounterOrKeyValAction'
                    ):
                        kwargs['action'] = value_mod.CodeRepr(
                            '_PortedCounterOrKeyValAction'
                        )
                        need_ported_counter_action = True
                        need_ported_bool_action = True
                    else:
                        kwargs.pop('action', None)
                if kwconf_primatives and not is_flag_action:
                    # Emit our annotation-gated coerce as the type= converter,
                    # matching the live kwconf CLI behavior.
                    ann = getattr(_value, '_annotation', None)
                    base_ann = ann if ann is not None else kwargs.get('type')
                    if kwargs.get('nargs', None) is not None:
                        from kwconf import coerce as _cm

                        base_ann = _cm.element_annotation(base_ann)
                    kwargs['type'] = value_mod.CodeRepr(
                        'functools.partial(_kwconf_coerce.auto, '
                        f'annotation={_annotation_to_code(base_ann)})'
                    )
                elif kwargs.get('type', None) is not None:
                    kwargs['type'] = value_mod.CodeRepr(kwargs['type'].__name__)
                to_pop = {k for k, v in kwargs.items() if v is None}
                kwargs = {k: v for k, v in kwargs.items() if k not in to_pop}
                args_body = (
                    ub.urepr(args, explicit=1, nobr=1, trailsep=0)
                    .strip()
                    .strip(',')
                )  # type: ignore
                kwargs_body = ub.urepr(
                    kwargs, explicit=1, nobr=1, trailsep=0, nl=0
                ).strip(',')  # type: ignore
                if args_body and kwargs_body:
                    args_body += ', '
                lines.append(f'parser.{meth}({args_body}{kwargs_body})')

        ported_action_blocks = []
        if need_ported_bool_action:
            ported_action_blocks.append(
                codeblock(
                    """
                def _ported_smartcast(value):
                    if not isinstance(value, str):
                        return value
                    lower = value.lower()
                    if lower == 'true':
                        return True
                    if lower == 'false':
                        return False
                    try:
                        return int(value)
                    except Exception:
                        pass
                    try:
                        return float(value)
                    except Exception:
                        pass
                    return value


                class _PortedBooleanFlagOrKeyValAction(argparse.Action):
                    def __init__(self, option_strings, dest, default=None, required=False, help=None, type=None):
                        _option_strings = []
                        for option_string in option_strings:
                            _option_strings.append(option_string)
                            if option_string.startswith('--'):
                                _option_strings.append('--no-' + option_string[2:])
                        kwargs = dict(
                            option_strings=_option_strings,
                            dest=dest,
                            default=default,
                            type=type,
                            choices=None,
                            required=required,
                            help=help,
                            metavar=None,
                            nargs='?'
                        )
                        super().__init__(**kwargs)

                    def __call__(self, parser, namespace, values, option_string=None):
                        if option_string is None:
                            raise ValueError('Boolean flag action requires an option string')
                        key_is_negative = option_string.startswith('--no-')
                        if values is None:
                            value = not key_is_negative
                        else:
                            value = values if self.type is not None else _ported_smartcast(values)
                            if key_is_negative:
                                value = not value
                        setattr(namespace, self.dest, value)
                """
                )
            )

        if need_ported_counter_action:
            ported_action_blocks.append(
                codeblock(
                    """
                class _PortedCounterOrKeyValAction(_PortedBooleanFlagOrKeyValAction):
                    def __call__(self, parser, namespace, values, option_string=None):
                        if option_string is None:
                            raise ValueError('Counter flag action requires an option string')
                        key_is_negative = option_string.startswith('--no-')
                        key_default = not key_is_negative
                        current = getattr(namespace, self.dest, self.default)
                        if current is None:
                            current = 0

                        if values is None:
                            value = current + key_default
                        else:
                            value = values if self.type is not None else _ported_smartcast(values)
                            if key_is_negative:
                                value = not value
                        setattr(namespace, self.dest, value)
                """
                )
            )
        if ported_action_blocks:
            lines[1:1] = ported_action_blocks

        text = '\n'.join(lines)
        return text

    # @classmethod
    # def _construct_config_text(cls):
    #     ...

    @property
    def namespace(self) -> argparse_mod.Namespace:
        """
        Access a namespace like object for compatibility with argparse

        Returns:
            argparse.Namespace
        """
        return argparse_mod.Namespace(**dict(self))

    def _new_argparse_parser(self) -> argparse_mod.ArgumentParser:
        """Create the canonical parser shell for this config."""
        from kwconf import argparse_ext

        return argparse_ext.ExtendedArgumentParser(**self._parserkw())

    def _argument_key_order(self) -> list[str]:
        """Return declaration order with explicit positions first."""
        positions = {
            key: template.position
            for key, template in self._default.items()
            if isinstance(template, Value) and template.position is not None
        }
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
        if not positions:
            return list(self._data)
        ordered = sorted(positions, key=positions.__getitem__)
        seen = set(ordered)
        ordered.extend(key for key in self._data if key not in seen)
        return ordered

    def _add_special_options(self, parser: argparse_mod.ArgumentParser) -> None:
        """Add kwconf's opt-in config/dump control options."""
        from kwconf import argparse_ext

        special_group = parser.add_argument_group('kwconf options')
        special_group.add_argument(
            '--config',
            default=None,
            help=codeblock(
                """
                special kwconf option that accepts the path to an on-disk
                configuration file and loads it into this {!r} object.
                """
            ).format(self.__class__.__name__),
        )
        special_group.add_argument(
            '--dump',
            default=None,
            help='If specified, dump this config to disk.',
        )
        special_group.add_argument(
            '--dumps',
            action=argparse_ext.BooleanFlagOrKeyValAction,
            help='If specified, dump this config to stdout.',
        )

    def _populate_argparse_parser(
        self,
        parser: argparse_mod.ArgumentParser,
        *,
        special_options: bool = False,
        fuzzy_hyphens: Optional[int] = None,
    ) -> argparse_mod.ArgumentParser:
        """Populate a parser from the current values and instance schema."""
        own_fuzzy = getattr(self, '__fuzzy_hyphens__', 1)
        effective_fuzzy = (
            own_fuzzy if (fuzzy_hyphens is None or fuzzy_hyphens) else 0
        )
        setattr(parser, '_kwconf_fuzzy_hyphens', bool(effective_fuzzy))

        from kwconf import value as value_mod

        for key in self._argument_key_order():
            value_mod._value_add_argument_to_parser(
                self._data[key],
                self._default[key],
                self,
                parser,
                key,
                fuzzy_hyphens=effective_fuzzy,
            )
        if special_options:
            self._add_special_options(parser)
        return parser

    def argparse(
        self,
        parser: Optional[argparse_mod.ArgumentParser] = None,
        special_options: bool = False,
        allow_subconfig_overrides: bool = False,
        fuzzy_hyphens: Optional[int] = None,
    ) -> argparse_mod.ArgumentParser:
        """
        construct or update an argparse.ArgumentParser CLI parser

        Args:
            parser (None | argparse.ArgumentParser): if specified this
                parser is updated with options from this config.

            special_options (bool):
                adds special kwconf options, namely: --config, --dumps,
                and --dump. Defaults to False.

            allow_subconfig_overrides (bool):
                If True, allow SubConfig selector overrides. SubConfig
                selection requires multipass parsing; use ``cli`` instead.

        Returns:
            argparse.ArgumentParser : a new or updated argument parser

        CommandLine:
            xdoctest -m kwconf.config Config.argparse:0
            xdoctest -m kwconf.config Config.argparse:1

        TODO:
            A good CLI spec for lists might be

            # In the case where ``key`` ends with and ``=``, assume the list is
            # given as a comma separated string with optional square brackets at
            # each end.

            --key=[f]

            # In the case where ``key`` does not end with equals and we know
            # the value is supposd to be a list, then we consume arguments
            # until we hit the next one that starts with '--' (which means
            # that list items cannot start with -- but they can contains
            # commas)

        FIXME:

            * In the case where we have an nargs='+' action, and we specify
              the option with an `=`, and then we give position args after it
              there is no way to modify behavior of the action to just look at
              the data in the string without modifying the ArgumentParser
              itself. The action object has no control over it. For example
              `--foo=bar baz biz` will parse as `[baz, biz]` which is really
              not what we want. We may be able to overload ArgumentParser to
              fix this.

        Example:
            >>> # You can now make instances of this class
            >>> import kwconf
            >>> self = kwconf.Config.demo()
            >>> parser = self.argparse()
            >>> parser.print_help()
            >>> # xdoctest: +REQUIRES(PY3)
            >>> # Python2 argparse does a hard sys.exit instead of raise
            >>> ns, extra = parser.parse_known_args()

        Example:
            >>> # You can now make instances of this class
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __description__ = 'my CLI description'
            >>>     __default__ = {
            >>>         'path1':  kwconf.Value(None, position=1, alias='src'),
            >>>         'path2':  kwconf.Value(None, position=2, alias='dst'),
            >>>         'dry':  kwconf.Value(False, isflag=True),
            >>>         'approx':  kwconf.Value(False, isflag=False, alias=['a1', 'a2']),
            >>>     }
            >>> self = MyConfig()
            >>> special_options = True
            >>> parser = None
            >>> parser = self.argparse(special_options=special_options)
            >>> parser.print_help()
            >>> self._read_argv(argv=['objection', '42', '--path1=overruled!'])
            >>> print('self = {!r}'.format(self))

        Example:
            >>> # Test required option
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __description__ = 'my CLI description'
            >>>     __default__ = {
            >>>         'path1':  kwconf.Value(None, position=1, alias='src'),
            >>>         'path2':  kwconf.Value(None, position=2, alias='dst'),
            >>>         'dry':  kwconf.Value(False, isflag=True),
            >>>         'important':  kwconf.Value(False, required=True),
            >>>         'approx':  kwconf.Value(False, isflag=False, alias=['a1', 'a2']),
            >>>     }
            >>> self = MyConfig(**{'important': 1})
            >>> special_options = True
            >>> parser = None
            >>> parser = self.argparse(special_options=special_options)
            >>> parser.print_help()
            >>> self._read_argv(argv=['objection', '42', '--path1=overruled!', '--important=1'])
            >>> print('self = {!r}'.format(self))

        Ignore:
            >>> self._read_argv(argv=['hi','--path1=foobar'])
            >>> self._read_argv(argv=['hi', 'hello', '--path1=foobar'])
            >>> self._read_argv(argv=['hi', 'hello', '--path1=foobar', '--help'])
            >>> self._read_argv(argv=['--path1=foobar', '--path1=baz'])
            >>> print('self = {!r}'.format(self))

        Example:
            >>> # Is it possible to the CLI as a key/val pair or an exist bool flag?
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __default__ = {
            >>>         'path1':  kwconf.Value(None, position=1, alias='src'),
            >>>         'path2':  kwconf.Value(None, position=2, alias='dst'),
            >>>         'flag':  kwconf.Value(None, isflag=True),
            >>>     }
            >>> self = MyConfig()
            >>> special_options = True
            >>> parser = None
            >>> parser = self.argparse(special_options=special_options)
            >>> parser.print_help()
            >>> print(self._read_argv(argv=[], strict=True))
            >>> # Test that we can specify the flag as a pure flag
            >>> print(self._read_argv(argv=['--flag']))
            >>> print(self._read_argv(argv=['--no-flag']))
            >>> # Test that we can specify the flag with a key/val pair
            >>> print(self._read_argv(argv=['--flag', 'TRUE']))
            >>> print(self._read_argv(argv=['--flag=1']))
            >>> print(self._read_argv(argv=['--flag=0']))
            >>> # Test flag and positional
            >>> self = MyConfig()
            >>> print(self._read_argv(argv=['--flag', 'TRUE', 'SUFFIX']))
            >>> self = MyConfig()
            >>> print(self._read_argv(argv=['PREFIX', '--flag', 'TRUE']))
            >>> self = MyConfig()
            >>> print(self._read_argv(argv=['--path2=PREFIX', '--flag', 'TRUE']))

        Example:
            >>> # Test groups
            >>> import kwconf
            >>> class MyConfig(kwconf.Config):
            >>>     __description__ = 'my CLI description'
            >>>     __default__ = {
            >>>         'arg1':  kwconf.Value(None, group='a'),
            >>>         'arg2':  kwconf.Value(None, group='a', alias='a2'),
            >>>         'arg3':  kwconf.Value(None, group='b'),
            >>>         'arg4':  kwconf.Value(None, group='b', alias='a4'),
            >>>         'arg5':  kwconf.Value(None, mutex_group='b', isflag=True),
            >>>         'arg6':  kwconf.Value(None, mutex_group='b', alias='a6'),
            >>>     }
            >>> self = MyConfig()
            >>> parser = self.argparse()
            >>> parser.print_help()
            >>> print(self.port_from_argparse(parser))
            >>> import pytest
            >>> import argparse
            >>> with pytest.raises(SystemExit):
            >>>     self._read_argv(argv=['--arg6', '42', '--arg5', '32'])
            >>> # self._read_argv(argv=['--arg6', '42', '--arg5']) # Strange, this does not cause an mutex error
            >>> self._read_argv(argv=['--arg6', '42'])
            >>> self._read_argv(argv=['--arg5'])
            >>> self._read_argv(argv=[])
        """
        if getattr(self, '_has_subconfigs', False):
            if allow_subconfig_overrides:
                raise RuntimeError(
                    'SubConfig selection overrides require multipass parsing; use cli()'
                )
            from kwconf import subconfig as _subcfg_mod

            flat_helper = _subcfg_mod.flat_config_from_tree(
                self, include_class_options=False
            )
            parser = flat_helper._argparse(
                parser=parser, special_options=special_options
            )
            _subcfg_mod.add_forbidden_selector_args(parser, self)
            return parser

        if parser is None:
            parser = self._new_argparse_parser()
        return self._populate_argparse_parser(
            parser,
            special_options=special_options,
            fuzzy_hyphens=fuzzy_hyphens,
        )

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

_ubelt_repr_extension._register_ubelt_repr_extensions()
