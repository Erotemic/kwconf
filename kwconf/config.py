"""
Write simple configs and update from CLI, kwargs, json, and yaml.

``kwconf`` provides a simple way to make configurable scripts that combine
config files, command-line arguments, and Python keyword arguments. A
config is defined by subclassing :class:`DataConfig` and declaring fields
as typed class variables. The instance behaves like a dict (it supports
``config['x']``) and like a namespace (``config.x``).

The future-facing schema style uses typed class variables. Use
:class:`kwconf.Value` to attach CLI metadata (help text, aliases, choices,
``isflag``, ``nargs``, positional, etc) when needed.

Example:
    >>> import kwconf as kw
    >>> # The simplest config: typed fields with raw defaults.
    >>> class ExampleConfig(kw.DataConfig):
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
    >>> class ListConfig(kw.DataConfig):
    ...     plain: str = ''
    ...     tags: list = kw.Value(default_factory=list, nargs='+')
    >>> config = ListConfig.cli(argv=['--plain=a,b,c', '--tags', 'x', 'y'])
    >>> # Plain strings are preserved literally:
    >>> assert config['plain'] == 'a,b,c'
    >>> # Lists are gathered from space-separated tokens via nargs:
    >>> assert config['tags'] == ['x', 'y']

Note:
    The ``__default__`` dict form remains supported on ``DataConfig`` for
    compatibility with existing code, but new code should prefer typed
    class variables.
"""
from __future__ import annotations

import copy
import inspect
import os
import warnings
import ubelt as ub
import itertools as it
import argparse as argparse_mod
import types
from typing import IO, Dict, Iterable, List, Optional, Tuple, Type, Union, cast
from kwconf import _ubelt_repr_extension
from kwconf.dict_like import DictLike
from kwconf.file_like import FileLike
from kwconf.value import Value
from kwconf import diagnostics
import typing

from collections.abc import Mapping, Sequence
from typing import Any
# from kwconf.util.util_class import class_or_instancemethod

__all__ = ['DataConfig', 'define']


def define(default: Mapping[str, Any] = {}, name: Optional[str] = None) -> type:
    """
    Alternate method for defining a custom :class:`DataConfig` type from a
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
        name = 'DataConfig_{}'.format(hashid)
    vals: Dict[str, Any] = {'default': default}
    code = dedent(
        '''
        import kwconf
        class {name}(kwconf.DataConfig):
            __default__ = default
        '''.strip('\n').format(name=name))
    exec(code, vals)
    cls = vals[name]
    return cast(Type["DataConfig"], cls)


def _runtime_type_from_annotation(annotation: Any) -> type | None:
    if annotation is None or annotation is Any or isinstance(annotation, str):
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        # ``Literal['a', 'b']`` -> infer the type of the choices.
        choice_types = {type(arg) for arg in typing.get_args(annotation)}
        if len(choice_types) == 1:
            (only_type,) = choice_types
            return only_type
        return None
    if origin in {Union, types.UnionType}:
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        for arg in args:
            runtime_type = _runtime_type_from_annotation(arg)
            if runtime_type is not None:
                return runtime_type
        return None
    if origin is not None:
        return cast(type | None, origin)
    if isinstance(annotation, type):
        return annotation
    return None


def _choices_from_annotation(annotation: Any) -> tuple | None:
    """
    Return the choices implied by ``annotation`` if it is (or wraps via
    ``Optional``/``Union``) a :data:`typing.Literal`, otherwise None.
    """
    if annotation is None or isinstance(annotation, str):
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return typing.get_args(annotation)
    if origin in {Union, types.UnionType}:
        for arg in typing.get_args(annotation):
            if arg is type(None):
                continue
            ch = _choices_from_annotation(arg)
            if ch is not None:
                return ch
    return None


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

    if runtime_type is None and choices is None:
        return value

    # Apply choices from Literal[...] when the user hasn't already set them.
    if choices is not None:
        if isinstance(value, Value):
            if not value.parsekw.get('choices'):
                value = value.copy()
                value.parsekw = dict(value.parsekw)
                value.parsekw['choices'] = list(choices)
        else:
            value = Value(value, choices=list(choices),
                          isflag=isinstance(value, bool))

    if runtime_type is None:
        return value

    if isinstance(value, Value):
        if value.type is not None:
            return value
        value = value.copy()
        value.type = runtime_type
        value.parsekw = dict(value.parsekw)
        value.parsekw['type'] = runtime_type
        return value
    return Value(value, type=runtime_type, isflag=isinstance(value, bool))


def _collect_declared_config_attrs(namespace: Dict[str, Any]) -> Dict[str, Any]:
    annotations = namespace.get('__annotations__', {})
    attr_default = {}
    for k, v in namespace.items():
        if k.startswith('_') or k == 'default':
            continue
        if isinstance(v, classmethod) or isinstance(v, staticmethod):
            continue
        if callable(v) and not (inspect.isclass(v) and issubclass(v, DataConfig)):
            continue
        attr_default[k] = _maybe_apply_annotation_to_value(k, v, annotations)
    return attr_default


def _materialize_default_items(defaults: Mapping[str, Any]) -> Dict[str, Any]:
    realized = {}
    for key, value in defaults.items():
        if isinstance(value, Value):
            realized[key] = value.clone_default()
        else:
            realized[key] = copy.deepcopy(value)
    return realized


def _coerce_data_to_dict(data: Any, mode: Optional[str] = None) -> Dict[str, Any]:
    """
    Normalize a ``data`` argument (None, dict, DataConfig, file/path/string) into
    a plain dict ready for DataConfig.load.

    Supports:

      * ``None`` -> ``{}``
      * a :class:`DataConfig` instance -> ``data.asdict()``
      * a :class:`dict` -> returned as-is
      * a file path (str / os.PathLike) or readable file -> parsed by
        ``mode`` (auto-detected from file extension; defaults to yaml).
      * a raw json or yaml string -> parsed in-memory.
    """
    if data is None:
        return {}
    if isinstance(data, DataConfig):
        return data.asdict()
    if isinstance(data, dict):
        return data
    if isinstance(data, (str, os.PathLike)) or hasattr(data, 'readable'):
        if isinstance(data, str) and ('\n' in data or not os.path.exists(data)):
            import json
            try:
                return json.loads(data)
            except Exception:
                import yaml  # type: ignore[import-untyped]
                import io
                return yaml.load(io.StringIO(data), Loader=yaml.SafeLoader)
        if mode is None:
            if isinstance(data, str) and data.lower().endswith('.json'):
                mode = 'json'
            elif isinstance(data, os.PathLike) and os.fspath(data).lower().endswith('.json'):
                mode = 'json'
            else:
                mode = 'yaml'
        with FileLike(cast(Union[str, os.PathLike, IO[Any]], data), 'r') as file:
            if mode == 'yaml':
                import yaml  # type: ignore[import-untyped]
                return yaml.load(file, Loader=yaml.SafeLoader)
            if mode == 'json':
                import json
                return json.load(file)
            raise KeyError(mode)
    raise TypeError(f'Expected path, dict, or DataConfig; got {type(data)!r}')


def _normalize_class_defaults(defaults, annotations=None):
    """
    Normalize class-level defaults to ensure Value/SubConfig metadata is present.

    Example:
        >>> import kwconf
        >>> class Inner(kwconf.DataConfig):
        ...     __default__ = {'x': 1}
        >>> class Outer(kwconf.DataConfig):
        ...     __default__ = {'inner': Inner, 'flag': False, 'leaf': 3}
        >>> norms = _normalize_class_defaults(Outer.__default__)
        >>> assert isinstance(norms['inner'], kwconf.SubConfig)
        >>> assert isinstance(norms['flag'], kwconf.Value) and norms['flag'].isflag is True
        >>> assert isinstance(norms['leaf'], kwconf.Value)
    """
    normalized = {}
    if defaults is None:
        defaults = {}
    annotations = annotations or {}
    from kwconf.subconfig import SubConfig
    for key, value in defaults.items():
        if isinstance(value, SubConfig):
            normalized_value = value
        elif isinstance(value, Value):
            value = _maybe_apply_annotation_to_value(key, value, annotations)
            inner = value.value
            if isinstance(inner, SubConfig):
                if value.help and not inner.help:
                    inner.parsekw['help'] = value.help
                normalized_value = inner
            elif isinstance(inner, DataConfig) or (
                inspect.isclass(inner) and issubclass(inner, DataConfig)
            ):
                normalized_value = SubConfig(inner, help=value.help)
            else:
                normalized_value = value
        elif isinstance(value, DataConfig) or (
            inspect.isclass(value) and issubclass(value, DataConfig)
        ):
            normalized_value = SubConfig(value)
        else:
            normalized_value = _maybe_apply_annotation_to_value(
                key, value, annotations)
            if normalized_value is value:
                if isinstance(value, bool):
                    normalized_value = Value(value, isflag=True)
                else:
                    normalized_value = Value(value)
        normalized[key] = normalized_value
    return normalized


class MetaConfig(type):
    """
    A metaclass for Config to help make usage between Config and DataConfig
    consistent.

    Ensures that class attributes are mirrored:
        * __default__ mirrors default
        * __post_init__ mirrors normalize

    Also reserves the ``__class__`` key for SubConfig selector metadata and
    warns on the common ``key = Value(...),`` trailing-comma typo. These
    checks were previously only applied by :class:`MetaDataConfig` and now
    apply uniformly to all kwconf config classes.
    """

    @staticmethod
    def __new__(mcls: type,
                name: str,
                bases: Tuple[type, ...],
                namespace: Dict[str, Any],
                *args: Any,
                **kwargs: Any) -> type:
        if diagnostics.DEBUG_META_CONFIG:
            print(f'MetaConfig.__new__ called: {mcls=} {name=} {bases=} {namespace=} {args=} {kwargs=}')

        # Skip class-attr collection on DataConfig itself (the root); all
        # subclasses (user classes) participate.
        is_root_config = (
            name == 'DataConfig' and namespace.get('__module__') == __name__
        )

        if not is_root_config:
            attr_default = _collect_declared_config_attrs(namespace)
            if attr_default:
                for key in attr_default:
                    namespace.pop(key, None)
                cls_default = namespace.get('__default__', None) or {}
                namespace['__default__'] = {**attr_default, **cls_default}

        HANDLE_INHERITENCE = 1
        if HANDLE_INHERITENCE:
            # Handle inheritance, add in defaults from base classes
            this_default = namespace.get('__default__', {})
            if this_default is None:
                this_default = {}
            this_default = ub.udict(this_default)

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
                        'The name "__class__" is reserved for nested DataConfig meta keys'
                    )

                # Warn on the common ``key = Value(...),`` trailing-comma typo.
                for k, v in this_default.items():
                    if isinstance(v, tuple) and len(v) == 1 and isinstance(v[0], Value):
                        warnings.warn(ub.paragraph(
                            f'''
                            It looks like you have a trailing comma in your
                            {name} DataConfig.  The variable {k!r} has a value of
                            {v!r}, which is a Tuple[Value]. Typically it should be
                            a Value.
                            '''), UserWarning)

                this_default = _normalize_class_defaults(
                    this_default, namespace.get('__annotations__', {}))
            namespace['__default__'] = this_default

        if diagnostics.DEBUG_META_CONFIG:
            print('FINAL namespace = {}'.format(ub.urepr(namespace, nl=2)))
        cls = super().__new__(mcls, name, bases, namespace, *args, **kwargs)  # type: ignore

        # Modify the __init__ docstring to surface the valid keys to help().
        if getattr(cls, '__init__', None) is not None and cls.__init__.__doc__ == '__autogenerateme__':
            valid_keys = list(cls.__default__.keys())
            cls.__init__.__doc__ = ub.codeblock(
                f'''
                Valid options: {valid_keys}

                Args:
                    *args: positional arguments mapped onto declared fields.
                    **kwargs: keyword arguments for any declared field.
                ''')
        return cls


class DataConfig(ub.NiceRepr, DictLike, metaclass=MetaConfig):
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
    namespace (``config.key``). New keys cannot be added by default; opt in
    with ``__allow_newattr__ = True`` on the class.

    Key methods:

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
        >>> class MyConfig(kw.DataConfig):
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
    # __allow_newattr__ = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        "__autogenerateme__"
        # Internal flag used by the cli/load lifecycle to defer __post_init__.
        _dont_call_post_init = kwargs.pop('_dont_call_post_init', False)

        # Shared per-instance state setup (builds _default, seeds _data,
        # and instantiates SubConfig nodes).
        self._init_state(_dont_call_post_init=_dont_call_post_init)

        argkeys = list(self._default.keys())[0:len(args)]
        new_values = ub.dzip(argkeys, args)
        kwargs = self._normalize_alias_dict(kwargs)
        new_values.update(kwargs)
        unknown_args: Dict[str, Any] = ub.dict_diff(new_values, self._default)  # type: ignore[arg-type]
        if unknown_args:
            raise ValueError((
                "Unknown Arguments: {}. Expected arguments are: {}"
            ).format(unknown_args, list(self._default)))
        for key, value in new_values.items():
            template = self._default.get(key)
            if isinstance(template, Value) and not isinstance(value, Value):
                new_template = template.copy()
                new_template.value = value
                self._default[key] = new_template
            else:
                self._default[key] = value
            self[key] = value

        self._enable_setattr = True
        if not _dont_call_post_init:
            self.__post_init__()
            self._kwconf_post_init_done = True

    def _init_state(self, _dont_call_post_init: bool = False) -> None:
        """
        Initialize per-instance attribute storage from the class-level defaults.

        Shared between :class:`DataConfig` and :class:`DataConfig` constructors.
        Builds ``self._default`` (a fresh per-instance copy), populates
        ``self._data`` with raw values, and instantiates any SubConfig nodes.
        """
        self._data: Dict[str, Any] = {}
        self._default: Dict[str, Value] = {}
        self._subconfig_meta: Dict[str, Any] = {}
        self._has_subconfigs = False
        self._kwconf_post_init_done = False
        self._alias_map = None
        cls_default = getattr(self, '__default__', getattr(self, 'default', None))
        if cls_default:
            self._default.update(_materialize_default_items(cls_default))
        # Seed _data with raw values; wrap_subconfig_defaults may overwrite
        # entries for SubConfig nodes with realized config instances.
        self._data = {
            key: (value.value if isinstance(value, Value) else value)
            for key, value in self._default.items()
        }
        from kwconf.subconfig import wrap_subconfig_defaults
        wrap_subconfig_defaults(self, _dont_call_post_init=_dont_call_post_init)

    @classmethod
    def cli(
        cls,
        data: Mapping[str, Any] | str | None = None,
        default: Mapping[str, Any] | None = None,
        argv: Sequence[str] | str | bool | None = None,
        strict: bool = True,
        autocomplete: bool | str = "auto",
        special_options: bool | None = None,
        verbose: bool | str = False,
        allow_import: bool = True,
        allow_subconfig_overrides: bool = True,
        localns: Mapping[str, Any] | None = None,
        stacklevel: int | None = 0,
    ) -> DataConfig:
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
                If True, allow module path selectors like
                ``pkg.mod.ClassName``
                for SubConfig selection. Defaults to True.

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
            >>> class MyConfig(kwconf.DataConfig):
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
        # Note: hack to avoid calling __post_init__ twice
        self = cls(_dont_call_post_init=True)
        next_stacklevel = None if stacklevel is None else stacklevel + 1
        self.load(data, argv=argv, default=default, strict=strict,
                  autocomplete=autocomplete, special_options=special_options,
                  allow_import=allow_import,
                  allow_subconfig_overrides=allow_subconfig_overrides,
                  localns=localns, stacklevel=next_stacklevel)

        if isinstance(verbose, str) and verbose == 'auto':
            verbose = self.get('verbose', verbose)
            verbose = not self.get('quiet', not verbose)
            verbose = not self.get('silent', not verbose)

        if verbose:
            try:
                import rich
                from rich.markup import escape
            except ImportError:
                print('config = ' + ub.urepr(self, nl=1))  # type: ignore
            else:
                rich.print('config = ' + escape(ub.urepr(self, nl=1)))  # type: ignore
        if diagnostics.DEBUG_CONFIG:
            print(f'[kwconf] Return {cls.__name__}.cli')
        return self

    @classmethod
    def demo(cls) -> "DataConfig":
        """
        Create an example config class for test cases

        CommandLine:
            xdoctest -m kwconf.config DataConfig.demo
            xdoctest -m kwconf.config DataConfig.demo --cli --option1 fo

        Example:
            >>> from kwconf.config import *
            >>> self = DataConfig.demo()
            >>> print('self = {}'.format(self))
            self = <DemoConfig({...'option1': ...}...)...>...
            >>> self.argparse().print_help()
            >>> # xdoc: +REQUIRES(--cli)
            >>> self.load(argv=True)
            >>> print(ub.urepr(self, nl=1))
        """
        import kwconf
        class DemoConfig(kwconf.DataConfig):
            """
            This was generated by kwconf.DataConfig.demo
            """
            __default__ = {
                'option1': kwconf.Value('bar', help='an option'),
                'option2': kwconf.Value((1, 2, 3), tuple, help='another option'),
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
            >>> self = DataConfig.demo()
            >>> self.__json__()
            >>> self['option1'] = {1, 2, 3}
            >>> self['option2'] = {(1, 2): 'fds'}
            >>> self.__json__()
        """
        numpy: Any
        try:
            import numpy
        except ImportError:
            numpy = None  # type: ignore
        data = self.asdict()

        BUILTIN_SCALAR_TYPES = (str, int, float, complex)
        BUILTIN_VECTOR_TYPES = (set, frozenset, list, tuple)

        # The walker method should be more efficient.
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
                walker[path] = dict(sorted(item.items()))
            else:
                if hasattr(item, '__json__'):
                    return item.__json__()
                else:
                    raise TypeError(
                        'Unknown JSON serialization for type {!r}'.format(type(item)))
        return data

    def __nice__(self) -> str:
        data = self.asdict()
        if isinstance(data, dict):
            data = dict(data)
        return str(data)

    def asdict(self) -> Dict[str, Any]:
        if getattr(self, '_has_subconfigs', False):
            from kwconf.subconfig import config_to_nested_dict
            return config_to_nested_dict(self, include_class=False)
        return super().asdict()

    def to_dict(self) -> Dict[str, Any]:
        return self.asdict()

    def getitem(self, key: str) -> Any:
        """
        Dictionary-like method to get the value of a key.

        Args:
            key (str): the key

        Returns:
            Any : the associated value
        """
        if isinstance(key, str) and '.' in key and getattr(self, '_has_subconfigs', False):
            parts = key.split('.')
            node: Any = self
            for part in parts:
                if not isinstance(node, DataConfig):
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

    def setitem(self, key: str, value: Any) -> None:
        """
        Dictionary-like method to set the value of a key.

        Args:
            key (str): the key
            value (Any): the new value
        """
        if isinstance(key, str) and '.' in key and getattr(self, '_has_subconfigs', False):
            parts = key.split('.')
            parent_key, leaf = parts[:-1], parts[-1]
            from kwconf.subconfig import _ensure_parent_node
            parent = _ensure_parent_node(self, parent_key)
            parent[leaf] = value
            return
        if key not in self._data:
            key = self._normalize_alias_key(key)
            if key not in self._data:
                if not getattr(self, '__allow_newattr__', False):
                    raise Exception(
                        'Cannot add keys to kwconf.DataConfig objects unless '
                        'self.__allow_newattr__ is True'
                    )
        if isinstance(value, Value):
            # If the new item is a Value object simply overwrite the old one
            self._data[key] = value
        else:
            template = self.__default__.get(key, None)
            if template is not None and isinstance(template, Value):
                # If the new value is raw data, and we have a underlying Value
                # object update it.
                self._data[key] = template.coerce(value)
            else:
                # If we don't have an underlying Value object simply set the
                # raw data.
                self._data[key] = value

    def delitem(self, key: str) -> None:
        raise Exception('cannot delete items from a config')

    def keys(self) -> Iterable[str]:
        """
        Dictionary-like keys method

        Yields:
            str:
        """
        return self._data.keys()

    def update_defaults(self, default: Mapping[str, Any]) -> None:
        """
        Update the instance-level default values

        Args:
            default (dict): new defaults
        """
        import copy
        default = self._normalize_alias_dict(default)

        # The user might pass raw values in which case we should keep the
        # metadata from the existing wrapped Values and just update the .value
        # attribute.
        for k, v in default.items():
            old_default = self._default[k]
            if isinstance(old_default, Value) and not isinstance(v, Value):
                new_default = copy.deepcopy(old_default)
                new_default.value = v
                default[k] = new_default

        self._default.update(default)
        self._alias_map = None
        from kwconf.subconfig import wrap_subconfig_defaults
        wrap_subconfig_defaults(self, _dont_call_post_init=True)

    def load(
        self,
        data: Mapping[str, Any] | str | None = None,
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
    ) -> DataConfig:
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
                If True, allow module path selectors like
                ``pkg.mod.ClassName``
                for SubConfig selection. Defaults to True.

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
            >>> class MyConfig(kwconf.DataConfig):
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
            >>> class MyConfig(kwconf.DataConfig):
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
            print(f'[kwconf.config.DataConfig] Call {self.__class__.__name__}.load',
                  f'argv={argv}, strict={strict}, special_options={special_options}')

        if special_options is None:
            special_options = getattr(self, '__special_options__', False)

        if default:
            self.update_defaults(default)

        _default = copy.deepcopy(self._default)
        user_config = _coerce_data_to_dict(data, mode=mode)

        # check for unknown values
        indirect_keys = set(user_config) - set(_default)
        if indirect_keys:
            # Check if unknown keys are aliases
            unknown_keys = []
            _alias_map = self._build_alias_map()
            for a in indirect_keys:
                if a in _alias_map:
                    k = _alias_map[a]
                    user_config[k] = user_config.pop(a)  # type: ignore
                else:
                    # Ignore any unknown dunder keys or allow dotted keys when
                    # subconfigs are enabled (they may be nested updates).
                    if a.startswith('.') or a.startswith('__') and a.endswith('__'):
                        user_config.pop(a, None)
                    elif getattr(self, '_has_subconfigs', False) and '.' in a:
                        continue
                    else:
                        unknown_keys.append(a)
            if unknown_keys:
                if strict:
                    if diagnostics.DEBUG_CONFIG:
                        print(f'[kwconf.config.DataConfig] Error: data={data}')

                    raise KeyError(f'Unknown data options {unknown_keys}')
                else:
                    for k in unknown_keys:
                        user_config.pop(k, None)

        from kwconf import subconfig as _subcfg_mod
        localns = _subcfg_mod.resolve_localns(localns, stacklevel)  # type: ignore
        self._data = {key: value.value for key, value in _default.items()}
        pending_updates = None
        if getattr(self, '_has_subconfigs', False):
            _subcfg_mod.ensure_subconfigs_instantiated(self, _dont_call_post_init=_dont_call_post_init)
            if argv:
                pending_updates = _subcfg_mod.coerce_data_updates(user_config)
            else:
                _subcfg_mod.apply_dot_updates(
                    self,
                    user_config,
                    allow_import=allow_import,
                    localns=localns,
                    stacklevel=None,
                )
        else:
            self.update(user_config)

        if isinstance(argv, str):
            # allow specification using the actual command line arg string
            import shlex
            argv = shlex.split(os.path.expandvars(argv))

        if argv or ub.iterable(argv):
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
            }
            if ub.iterable(argv):
                read_argv_kwargs['argv'] = argv
            self._read_argv(**read_argv_kwargs)

        if not _dont_call_post_init:
            if 1:
                # Check that all required variables are not the same as defaults
                # Probably a way to make this check nicer
                for k, v in self._default.items():
                    if isinstance(v, Value):
                        if v.required:
                            if self[k] == v.value:
                                raise Exception('Required variable {!r} still has default value'.format(k))
            if getattr(self, '_has_subconfigs', False):
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
        norm = {self._alias_map.get(k, k): v for k, v in data.items()}  # type: ignore
        return norm

    def _build_alias_map(self):
        _alias_map = {}
        for k, v in self._default.items():
            alias = getattr(v, 'alias', None)
            if alias:
                if not ub.iterable(alias):
                    alias = [alias]
                for a in alias:
                    _alias_map[a] = k
        return _alias_map

    def _read_argv(self, argv=None, special_options=None, strict=False, autocomplete=False,
                   allow_import=True, allow_subconfig_overrides=True, pending_updates=None,
                   localns=None, stacklevel=0):
        """
        Example:
            >>> import kwconf
            >>> class MyConfig(kwconf.DataConfig):
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
            >>> class EmptyConfig(kwconf.DataConfig):
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
            >>> class Adam(kwconf.DataConfig):
            ...     __default__ = {'lr': 1e-3}
            >>> class Sgd(kwconf.DataConfig):
            ...     __default__ = {'momentum': 0.9}
            >>> class TrainCfg(kwconf.DataConfig):
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
            >>> print(cfg.dumps())
            >>> assert isinstance(cfg['optim'], Sgd) and cfg['optim']['momentum'] == 0.8
        """
        if special_options is None:
            special_options = getattr(self, '__special_options__', False)

        if isinstance(argv, str):
            import shlex
            argv = shlex.split(argv)

        # TODO: warn about any unused flags
        parser = self.argparse(special_options=special_options)
        has_subconfigs = getattr(self, '_has_subconfigs', False)
        if has_subconfigs:
            # Subconfig argv parsing is staged: realize selector overrides first,
            # then rebuild a parser for the realized tree before parsing values.
            from kwconf import subconfig as _subcfg_mod
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
            )

        if autocomplete:
            try:
                import argcomplete as argcomplete_mod
            except ImportError:
                if autocomplete != 'auto':
                    raise
            else:
                argcomplete_mod.autocomplete(parser)

        try:
            if strict:
                ns = parser.parse_args(argv).__dict__
            else:
                ns = parser.parse_known_args(argv)[0].__dict__
        except (ValueError, TypeError, KeyError) as ex:
            # For errors (like ValueError) where its probably a programmer
            # error and not a user error, give the debugger some information
            # about the kwconf object.
            from kwconf.util import util_exception
            # TODO: figure out argv that triggers a value error so we can add a test
            note = ub.codeblock(
                f'''
                Error while attempting to parse arguments in _read_argv

                Context:
                    argv = {argv!r}
                    special_options = {special_options!r}
                    strict = {strict!r}
                    autocomplete = {autocomplete!r}
                    self = {self!r}
                ''')
            print(note)
            ex = util_exception.add_exception_note(ex, note)
            raise ex

        special_ns_keys = ['config', 'dump', 'dumps']
        if special_options:
            special_ns = {k: ns.pop(k, None) for k in special_ns_keys}
        else:
            special_ns = {}

        if has_subconfigs:
            # Subconfig selectors need special handling, but regular values
            # can use the standard DataConfig setitem logic.
            from kwconf import subconfig as _subcfg_mod
            explicit = getattr(parser, '_explicitly_given', set())
            subconfig_paths = set(_subcfg_mod.find_subconfig_paths(self))
            if explicit:
                selector_keys = {
                    k for k in explicit
                    if k.endswith('.__class__') or k in subconfig_paths
                }
                if selector_keys:
                    selector_updates = {k: ns[k] for k in selector_keys if k in ns}
                    _subcfg_mod.apply_dot_updates(
                        self,
                        selector_updates,
                        allow_import=allow_import,
                        localns=localns,
                        stacklevel=None,
                    )
                    for key in selector_keys:
                        ns.pop(key, None)
                    parser._explicitly_given = explicit - selector_keys  # type: ignore
            if subconfig_paths:
                for key in subconfig_paths:
                    ns.pop(key, None)
                parser._explicitly_given = {  # type: ignore
                    key for key in parser._explicitly_given  # type: ignore
                    if key not in subconfig_paths
                }
        # First load argparse defaults in first
        _not_given = set(ns.keys()) - parser._explicitly_given  # type: ignore
        # print('_not_given = {!r}'.format(_not_given))
        # print('parser._explicitly_given = {!r}'.format(parser._explicitly_given))
        for key in _not_given:
            value = ns[key]
            if key not in self.__default__:
                # Skip dotted selector keys or unknown argparse entries.
                continue
            # NOTE: this implementation is messy and needs refactor.
            # Currently the .__default__ .default, ._default, and ._data
            # attributes can all be Value objects, but this gets messy when the
            # "default" constructor argument is used. We should refactor so
            # _data and _default only store the raw current values,
            # post-casting. Until then we trust the parser action to have
            # already coerced the value.
            default_value = self.__default__[key].value
            # Preserve any data/default overrides that were already applied
            # before argparse defaults are merged in.
            if self._data.get(key, default_value) != default_value:
                continue
            self[key] = value

        # Then load config file defaults
        if special_options:
            config_fpath = special_ns['config']
            if config_fpath is not None:
                self.load(config_fpath, argv=False,
                          _dont_call_post_init=True)

        # Finally load explicit CLI values. The parser action has already
        # coerced the raw token; we just need to store it.
        for key in parser._explicitly_given:  # type: ignore
            if key not in special_ns:
                self[key] = ns[key]

        if special_options:
            import sys
            dump_fpath = special_ns['dump']
            do_dumps = special_ns['dumps']
            if dump_fpath or do_dumps:
                if dump_fpath:
                    # Infer config format from the extension
                    if dump_fpath.lower().endswith('.json'):
                        mode = 'json'
                    elif dump_fpath.lower().endswith('.yaml'):
                        mode = 'yaml'
                    else:
                        mode = 'yaml'
                    text = self.dumps(mode=mode)
                    with open(dump_fpath, 'w') as file:
                        file.write(text)

                if do_dumps:
                    # Always use yaml to dump to stdout
                    text = self.dumps(mode='yaml')
                    print(text)

                sys.exit(1)
        return self

    def __post_init__(self) -> None:
        """ overloadable function called after each load """
        ...

    def dump(self, stream: Optional[Union[FileLike, IO[str]]] = None, mode: Optional[str] = None):
        """
        Write configuration file to a file or stream

        Args:
            stream (FileLike | None): the stream to write to
            mode (str | None): can be 'yaml' or 'json' (defaults to 'yaml')
        """
        if mode is None:
            mode = 'yaml'
        if getattr(self, '_has_subconfigs', False):
            from kwconf.subconfig import config_to_nested_dict
            payload = config_to_nested_dict(self, include_class=True)
        else:
            payload = dict(self.items())
        if mode == 'yaml':
            import yaml  # type: ignore
            def order_rep(dumper, data):
                return dumper.represent_mapping('tag:yaml.org,2002:map', data.items(), flow_style=False)
            yaml.add_representer(dict, order_rep, Dumper=yaml.SafeDumper)
            yaml.safe_dump(payload, stream)  # type: ignore
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
        self.dump(stream=stream, mode=mode)
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
        return initial + list(self.keys())

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
        can_setattr |= (getattr(self, '_enable_setattr', False) and key in self)
        if can_setattr:
            try:
                self[key] = value
            except KeyError:
                raise AttributeError(key)
        else:
            self.__dict__[key] = value

    @classmethod
    def parse_args(cls,
                   args: Optional[List[str]] = None,
                   namespace: Optional[Any] = None) -> "DataConfig":
        """
        Mimics :meth:`argparse.ArgumentParser.parse_args`.
        """
        if namespace is not None:
            raise NotImplementedError('namespaces are not handled in kwconf')
        return cast("DataConfig", cls.cli(argv=args, strict=True))

    @classmethod
    def parse_known_args(cls,
                         args: Sequence[str] | None = None,
                         namespace: Any = None) -> "DataConfig":
        """
        Mimics :meth:`argparse.ArgumentParser.parse_known_args`.
        """
        if namespace is not None:
            raise NotImplementedError('namespaces are not handled in kwconf')
        return cast("DataConfig", cls.cli(argv=args, strict=False))

    @classmethod
    def _register_main(cls, func):
        """
        Register a function as the main method for this config CLI.
        """
        cls.main = func
        return func

    @property
    def _description(self) -> Optional[str]:
        description = getattr(self, '__description__', None)
        if description is None:
            description = self.__class__.__doc__
        if description is None:
            import kwconf
            description = f'argparse CLI generated by kwconf {kwconf.__version__}'
        if description is not None:
            description = ub.codeblock(description)
        return description

    @property
    def _epilog(self) -> Optional[str]:
        epilog = getattr(self, '__epilog__', None)
        if epilog is not None:
            epilog = ub.codeblock(epilog)
        return epilog

    @property
    def _prog(self) -> Optional[str]:
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

    def port_to_dataconf(self, style: str = 'dataconf') -> str:
        """
        Helper that writes kwconf source code for this config.

        TODO: In the future perhaps rename to something that indicates we can
        write a code representation of this object in either config or data
            config style?

        CommandLine:
            xdoctest -m kwconf.config DataConfig.port_to_dataconf

        Example:
            >>> import kwconf
            >>> self = kwconf.DataConfig.demo()
            >>> print(self.port_to_dataconf())
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
    def _write_code(self,
                    entries: Iterable[tuple[str, Dict[str, Any]]],
                    name: str = 'MyConfig',
                    style: str = 'dataconf',
                    description: Optional[str] = None) -> str:

        if style == 'dataconf':
            indent = ' ' * 4
        else:
            indent = ' ' * 8

        if style == 'orig':
            raise Exception('no longer supported')
        elif style == 'dataconf':
            recon_str = [
                'import ubelt as ub',
                'import kwconf',
                '',
                'class ' + name + '(kwconf.DataConfig):',
                '    """',
                ub.indent(description or ''),
                '    """',
            ]
        else:
            raise KeyError(style)

        for (key, value_kw) in entries:
            _value_kw = value_kw.copy()

            default = _value_kw.pop('default')
            value_args = [
                repr(default),
            ]
            value_args.extend(['{}={}'.format(k, repr(v)) for k, v in _value_kw.items() if v is not None])
            val_body = ', '.join(value_args)

            if style == 'orig':
                recon_str.append("{}'{}': kwconf.Value({}),".format(indent, key, val_body))
            elif style ==  'dataconf':
                recon_str.append("{}{} = kwconf.Value({})".format(indent, key, val_body))
            else:
                raise KeyError(style)

        if style == 'orig':
            recon_str.append('    }')
        elif style ==  'dataconf':
            ...
        else:
            raise KeyError(style)
        text = '\n'.join(recon_str)
        if 0:
            try:
                import black
                text = black.format_str(
                    text, mode=black.Mode(string_normalization=True)
                )
            except Exception:
                pass
        return text

    @classmethod
    def port_from_click(cls, click_main, name=None, style='dataconf') -> str:
        """
        Prints kwconf code that roughly implements some click CLI.

        Args:
            click_main (click.core.Command): command to port

            name (str | None): the name of the new class, if None then
               uses the name of the CLI command.

            style (str): either dataconf or orig

        Returns:
            str : The code that roughly implements the config class.

        CommandLine:
            xdoctest -m kwconf.config DataConfig.port_from_click

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
            >>> text = kwconf.DataConfig.port_from_click(click_main)
            >>> print(text)
            import ubelt as ub
            import kwconf
            ...
            class click_main(kwconf.DataConfig):
                ...
                argparse CLI generated by kwconf ...
                ...
                dataset = kwconf.Value(None, required=True, help='input dataset')
                deployed = kwconf.Value(None, required=True, help='weights file')
                key1 = kwconf.Value(123, help='some key')
                key2 = kwconf.Value(456, help='another key')
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
                isflag=param['is_flag'], help=param['help'])
        if name is None:
            name = info_dict['name'].replace('-', '_')
        config_cls = define(default, name)
        instance = config_cls(_dont_call_post_init=True)
        return instance.port_to_dataconf(style=style)

    @classmethod
    def port_from_argparse(cls,
                           parser: "argparse_mod.ArgumentParser",
                           name: str = 'MyConfig',
                           style: str = 'dataconf') -> str:
        """
        Generate the corresponding kwconf code from an existing argparse
        instance.

        Args:
            parser (argparse.ArgumentParser):
                existing argparse parser we want to port
            name (str): the name of the config class
            style (str): either 'orig' or 'dataconf'

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
            >>> text = kwconf.DataConfig.port_from_argparse(parser, name='PortedConfig', style='dataconf')
            >>> print(text)
            >>> # Make an instance of the ported class
            >>> vals = {}
            >>> exec(text, vals)
            >>> cls = vals['PortedConfig']
            >>> self = cls(**{'true_dataset': 1, 'pred_dataset': 1})
            >>> recon = self.argparse()
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
            Config: a subclass of the Config or DataConfig class.

        SeeAlso:
            :func:`DataConfig.port_from_argparse` - like this function, but returns
                the text that could be executed to define the new class
                statically.  In constrat this creates the clas dynamically.

        CommandLine:
            xdoctest -m kwconf.config DataConfig.cls_from_argparse

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
            >>> DynamicClass = kwconf.DataConfig.cls_from_argparse(parser)
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
        DynamicClass = cast(type, cls.__class__(name, bases, attributes))  # type: ignore[call-overload]
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
                action, actionid_to_groupkey, actionid_to_mgroupkey, pos_counter)
            if for_text:
                # Use for the text reconstruction of the argparser, this is
                # very hacky.
                value_kw = value._to_value_kw()
                entries.append((key, value_kw))
            else:
                entries.append((key, value))
        return entries

    # Backwards compatibility, deprecate and remove
    port_argparse = port_from_argparse

    def port_to_argparse(self,
                         fuzzy_hyphens: bool = False,
                         flag_value_mode: bool = False) -> str:
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

        SeeAlso:
            :meth:`DataConfig.argparse` - creates a real argparse object

        Returns:
            str: code to construct a similar argparse object

        CommandLine:
            xdoctest -m kwconf.config DataConfig.port_to_argparse

        Example:
            >>> import kwconf
            >>> class DemoCLI(kwconf.DataConfig):
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
            >>> class SimpleCLI(kwconf.DataConfig):
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
        parserkw = self._parserkw()
        to_pop = {k for k, v in parserkw.items() if v is None}
        parserkw = ub.udict(parserkw) - to_pop  # type: ignore
        parserkw.pop('formatter_class', None)

        constructor_body = ub.indent(ub.urepr(parserkw, explicit=True, nobr=1))  # type: ignore

        lines = []
        lines.append(ub.codeblock(
            '''
            import argparse
            parser = argparse.ArgumentParser(
            {constructor_body}
                formatter_class=argparse.RawDescriptionHelpFormatter,
            )
            ''').format(
                constructor_body=constructor_body,
            ))

        from kwconf import value as value_mod
        need_ported_bool_action = False
        need_ported_counter_action = False
        for key, _value in self._data.items():
            if isinstance(_value, value_mod.Value):
                value = _value.value
            else:
                value = _value
                _value = self._default[key]
                if not isinstance(_value, value_mod.Value):
                    # hack
                    _value = value_mod.Value(_value)

            invocations = value_mod._value_add_argument_kw(
                value, _value, self, key, fuzzy_hyphens=fuzzy_hyphens)
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
                if not isinstance(action, str):
                    action_name = getattr(action, '__name__', '')
                    if flag_value_mode and action_name == 'BooleanFlagOrKeyValAction':
                        kwargs['action'] = value_mod.CodeRepr(
                            '_PortedBooleanFlagOrKeyValAction')
                        need_ported_bool_action = True
                    elif flag_value_mode and action_name == 'CounterOrKeyValAction':
                        kwargs['action'] = value_mod.CodeRepr(
                            '_PortedCounterOrKeyValAction')
                        need_ported_counter_action = True
                        need_ported_bool_action = True
                    else:
                        kwargs.pop('action', None)
                if kwargs.get('type', None) is not None:
                    kwargs['type'] = value_mod.CodeRepr(kwargs['type'].__name__)
                to_pop = {k for k, v in kwargs.items() if v is None}
                kwargs = ub.udict(kwargs) - to_pop  # type: ignore
                args_body = ub.urepr(args, explicit=1, nobr=1, trailsep=0).strip().strip(',')  # type: ignore
                kwargs_body = ub.urepr(kwargs, explicit=1, nobr=1, trailsep=0, nl=0).strip(',')  # type: ignore
                if args_body and kwargs_body:
                    args_body += ', '
                lines.append(f'parser.{meth}({args_body}{kwargs_body})')

        ported_action_blocks = []
        if need_ported_bool_action:
            ported_action_blocks.append(ub.codeblock(
                '''
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
                '''))

        if need_ported_counter_action:
            ported_action_blocks.append(ub.codeblock(
                '''
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
                '''))
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

    def argparse(self,
                 parser: Optional[argparse_mod.ArgumentParser] = None,
                 special_options: bool = False,
                 allow_subconfig_overrides: bool = False) -> argparse_mod.ArgumentParser:
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
            xdoctest -m kwconf.config DataConfig.argparse:0
            xdoctest -m kwconf.config DataConfig.argparse:1

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
            >>> self = kwconf.DataConfig.demo()
            >>> parser = self.argparse()
            >>> parser.print_help()
            >>> # xdoctest: +REQUIRES(PY3)
            >>> # Python2 argparse does a hard sys.exit instead of raise
            >>> ns, extra = parser.parse_known_args()

        Example:
            >>> # You can now make instances of this class
            >>> import kwconf
            >>> class MyConfig(kwconf.DataConfig):
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
            >>> class MyConfig(kwconf.DataConfig):
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
            >>> class MyConfig(kwconf.DataConfig):
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
            >>> class MyConfig(kwconf.DataConfig):
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
            >>> print(self.port_argparse(parser))
            >>> import pytest
            >>> import argparse
            >>> with pytest.raises(SystemExit):
            >>>     self._read_argv(argv=['--arg6', '42', '--arg5', '32'])
            >>> # self._read_argv(argv=['--arg6', '42', '--arg5']) # Strange, this does not cause an mutex error
            >>> self._read_argv(argv=['--arg6', '42'])
            >>> self._read_argv(argv=['--arg5'])
            >>> self._read_argv(argv=[])
        """
        from kwconf import argparse_ext
        if getattr(self, '_has_subconfigs', False):
            if allow_subconfig_overrides:
                raise RuntimeError(
                    'SubConfig selection overrides require multipass parsing; use cli()'
                )
            from kwconf import subconfig as _subcfg_mod
            flat_helper = _subcfg_mod.flat_config_from_tree(self, include_class_options=False)
            parser = flat_helper.argparse(parser=parser, special_options=special_options)
            _subcfg_mod.add_forbidden_selector_args(parser, self)
            return parser

        if parser is None:
            parserkw = self._parserkw()
            # parser = argparse.ArgumentParser(**parserkw)
            parser = argparse_ext.ExtendedArgumentParser(**parserkw)

        # Use custom action used to mark which values were explicitly set on
        # the commandline
        parser._explicitly_given = set()  # type: ignore

        _positions = {k: v.position for k, v in self._default.items()
                      if v.position is not None}
        if _positions:
            if ub.find_duplicates(_positions.values()):
                # TODO: make this a warning in 3.7+ and ensure there is a good
                # API for just indicating that a value is supposed to be
                # positional, and using its order in the dictionary as that
                # position. Need to account for inheritance though.
                raise Exception('two values have the same position')
            _keyorder = ub.oset(ub.argsort(cast(Any, _positions)))
            _keyorder |= (ub.oset(self._default) - _keyorder)
        else:
            _keyorder = ub.oset(self._default.keys())

        FUZZY_HYPHENS = getattr(self, '__fuzzy_hyphens__', 1)

        # Need to clean this up, metadata probably isn't necessary.
        for key, value in self._data.items():
            # Use the metadata in the Value class to enhance argparse
            _value = self._default[key]
            from kwconf import value as value_mod
            value_mod._value_add_argument_to_parser(
                value, _value, self, parser, key, fuzzy_hyphens=FUZZY_HYPHENS)

        if special_options:
            special_group = parser.add_argument_group(
                'kwconf options')
            special_group.add_argument('--config', default=None, help=ub.codeblock(
                '''
                special kwconf option that accepts the path to a on-disk
                configuration file, and loads that into this {!r} object.
                ''').format(self.__class__.__name__))

            special_group.add_argument('--dump', default=None, help=ub.codeblock(
                '''
                If specified, dump this config to disk.
                ''').format(self.__class__.__name__))

            special_group.add_argument(
                '--dumps', action=argparse_ext.BooleanFlagOrKeyValAction,
                help=ub.codeblock(
                    '''
                    If specified, dump this config stdout
                    ''').format(self.__class__.__name__))

        return parser


__notes__ = """
export _ARC_DEBUG=1
pip install argcomplete
activate-global-python-argcomplete --dest=$HOME/.bash_completion.d --user
eval "$(register-python-argcomplete xdev)"
complete -r xdev
"""

_ubelt_repr_extension._register_ubelt_repr_extensions()
