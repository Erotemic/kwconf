"""
Dataclass-style decorator support for ``kwconf``.

The primary public base class is :class:`kwconf.Config`. This module keeps the
:func:`dataconf` decorator and also re-exports ``Config`` for callers that
import through ``kwconf.dataconfig``. It deliberately does not expose a
``DataConfig`` name.

Example:
    >>> import kwconf
    >>> class ExampleConfig(kwconf.Config):
    >>>      num = 1
    >>>      mode = 'bar'
    >>>      ignore = ['baz', 'biz']
    >>> config = ExampleConfig()
    >>> kwargs = {'num': 2}
    >>> config.load(kwargs, argv=False)
    >>> assert config['num'] == 2
    >>> # CLI parsing is available through the cli classmethod.
    >>> config = ExampleConfig.cli(argv=['--num=4', '--mode', 'fiz'])
    >>> assert config['num'] == 4 and config['mode'] == 'fiz'

Notes:
    https://docs.python.org/3/library/dataclasses.html
"""

from __future__ import annotations

import dataclasses
import inspect
import typing
from typing import Any, Dict, Type

from kwconf.annotations import get_class_namespace_annotations
from kwconf.config import (
    _MAPPING_API_NAMES,
    Config,
    MetaConfig,
    _ConfigFieldProxy,
)
from kwconf.subconfig import SubConfig
from kwconf.value import _Value as Value

__all__ = ['dataconf', 'Config', 'MetaConfig', 'SubConfig']


def _is_field_candidate(value: Any) -> bool:
    """Return whether a plain-class attribute denotes a config field."""
    if isinstance(value, (classmethod, staticmethod, property)):
        return False
    if hasattr(value, '__get__') and not isinstance(value, Value):
        if not (inspect.isclass(value) and issubclass(value, Config)):
            return False
    if callable(value) and not (
        inspect.isclass(value) and issubclass(value, Config)
    ):
        return False
    return True


def _collect_plain_fields(cls: type) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Collect inherited annotations/defaults with subclass precedence."""
    annotations: Dict[str, Any] = {}
    defaults: Dict[str, Any] = {}
    for klass in reversed(inspect.getmro(cls)):
        if klass is object:
            continue
        klass_annotations = get_class_namespace_annotations(vars(klass))
        annotations.update(klass_annotations)
        for name, value in vars(klass).items():
            if name.startswith('_') or name == 'default':
                continue
            if (
                typing.get_origin(klass_annotations.get(name))
                is typing.ClassVar
            ):
                defaults.pop(name, None)
                continue
            if _is_field_candidate(value):
                defaults[name] = value
    return annotations, defaults


def _collect_dataclass_fields(cls: type) -> Dict[str, Any]:
    """Translate stdlib dataclass defaults into kwconf declarations."""
    defaults: Dict[str, Any] = {}
    for field in dataclasses.fields(typing.cast(Any, cls)):
        if field.default_factory is not dataclasses.MISSING:
            defaults[field.name] = Value(
                default_factory=field.default_factory  # type: ignore[arg-type]
            )
        elif field.default is not dataclasses.MISSING:
            defaults[field.name] = field.default
        else:
            defaults[field.name] = Value(required=True)
    return defaults


def dataconf(cls: Type[Any]) -> Type[Any]:
    """Convert a plain class or stdlib dataclass into a ``Config`` subclass.

    The generated type inherits from the original class, rather than copying
    its methods into an unrelated replacement. This preserves Python method
    semantics such as zero-argument ``super()`` and descriptor ``__set_name__``
    state. ``Config`` remains first in the generated MRO so its construction and
    object protocols cannot be replaced by a dataclass-generated ``__init__``.

    Inheriting from :class:`Config` directly remains the preferred style; this
    decorator is primarily a compatibility bridge.

    Example:
        >>> from kwconf.dataconfig import *  # NOQA
        >>> import kwconf
        >>> @dataconf
        >>> class ExampleConfig2:
        >>>     chip_dims = kwconf.Value((256, 256), help='chip size')
        >>>     time_dim = kwconf.Value(3, help='number of time steps')
        >>>     channels = kwconf.Value('*:(red|green|blue)', help='sensor / channel code')
        >>>     time_sampling = kwconf.Value('soft2')
        >>> cls = ExampleConfig2
        >>> print(f'cls={cls}')
        >>> self = cls()
        >>> print(f'self={self}')

    Example:
        >>> from kwconf.dataconfig import *  # NOQA
        >>> import kwconf
        >>> @dataconf
        >>> class PathologicalConfig:
        >>>     default0 = kwconf.Value((256, 256), help='chip size')
        >>>     default = kwconf.Value((256, 256), help='chip size')
        >>>     keys = [1, 2, 3]
        >>>     __default__ = {
        >>>         'argparse': 3.3,
        >>>         'keys': [4, 5],
        >>>     }
        >>>     default = None
        >>>     time_sampling = kwconf.Value('soft2')
        >>>     def foobar(self):
        >>>         ...
        >>> self = PathologicalConfig(1, 2, 3)
        >>> print(f'self={self}')

    # FIXME: xdoctest problem. Need to be able to simulate a module global scope
    # Example:
    #     >>> # Using inheritance and the decorator lets you pickle the object
    #     >>> from kwconf.dataconfig import *  # NOQA
    #     >>> import kwconf
    #     >>> @dataconf
    #     >>> class PathologicalConfig2(kwconf.Config):
    #     >>>     default0 = kwconf.Value((256, 256), help='chip size')
    #     >>>     default2 = kwconf.Value((256, 256), help='chip size')
    #     >>>     #keys = [1, 2, 3] : Too much
    #     >>>     __default__3 = {
    #     >>>         'argparse': 3.3,
    #     >>>         'keys2': [4, 5],
    #     >>>     }
    #     >>>     default2 = None
    #     >>>     time_sampling = kwconf.Value('soft2')
    #     >>> config = PathologicalConfig2()
    #     >>> import pickle
    #     >>> serial = pickle.dumps(config)
    #     >>> recon = pickle.loads(serial)
    #     >>> assert 'locals' not in str(PathologicalConfig2)
    """
    if inspect.isclass(cls) and issubclass(cls, Config):
        return cls

    annotations, plain_defaults = _collect_plain_fields(cls)
    if dataclasses.is_dataclass(cls):
        defaults = _collect_dataclass_fields(cls)
        defaults.update(
            {
                name: value
                for name, value in plain_defaults.items()
                if name not in defaults
            }
        )
    else:
        defaults = plain_defaults

    explicit_defaults = getattr(cls, '__default__', None)
    if explicit_defaults:
        defaults.update(explicit_defaults)

    namespace: Dict[str, Any] = {
        '__doc__': getattr(cls, '__doc__', None),
        '__qualname__': cls.__qualname__,
        '__module__': cls.__module__,
        '__annotations__': annotations,
        '__default__': defaults,
    }

    # These declarative hooks must override Config's implementations. Ordinary
    # methods and descriptors are inherited from ``cls``; non-dunder helpers are
    # copied only when Config would otherwise shadow them.
    preserved_dunders = {
        '__allow_newattr__',
        '__command__',
        '__description__',
        '__epilog__',
        '__fuzzy_hyphens__',
        '__post_init__',
        '__prog__',
        '__special_options__',
        '__validate__',
        '__version__',
    }
    for klass in reversed(inspect.getmro(cls)):
        if klass is object:
            continue
        for name, value in vars(klass).items():
            if name in preserved_dunders:
                namespace[name] = value
            elif (
                not name.startswith('__')
                and not _is_field_candidate(value)
                and hasattr(Config, name)
            ):
                namespace[name] = value

    # The original class still owns its field class attributes. Data
    # descriptors on the generated subclass route instance reads/writes through
    # Config's mapping state. Mapping methods stay method-first; all other
    # inherited APIs may be shadowed by a field on instances.
    for name in defaults:
        if not name.startswith('_') and name not in _MAPPING_API_NAMES:
            namespace[name] = _ConfigFieldProxy(name)

    return MetaConfig(cls.__name__, (Config, cls), namespace)


def __example__() -> None:
    """
    Doctests are broken for Configs, so putting them here.
    """
    import kwconf

    dataclasses_module: Any
    try:
        import dataclasses as dataclasses_module
    except ImportError:
        dataclasses_module = None  # type: ignore

    if dataclasses_module is None:
        return

    @dataclasses_module.dataclass
    class ExampleConfig0:
        x: int = 0
        y: str = '3'

    # Different variants of the same basic configuration (varying amounts of
    # metadata).
    class ExampleConfig1:
        chip_dims = (256, 256)
        time_dim = 5
        channels = 'red|green|blue'
        time_sampling = 'soft2'

    ExampleConfig1d = dataclasses_module.dataclass(ExampleConfig1)

    @dataclasses_module.dataclass
    class ExampleConfig2:
        chip_dims = kwconf.Value((256, 256), help='chip size')
        time_dim = kwconf.Value(3, help='number of time steps')
        channels = kwconf.Value(
            '*:(red|green|blue)', help='sensor / channel code'
        )
        time_sampling = kwconf.Value('soft2')

    @dataclasses_module.dataclass
    class ExampleConfig2d:
        chip_dims = kwconf.Value((256, 256), help='chip size')
        time_dim: Any = kwconf.Value(3, help='number of time steps')
        channels: Any = kwconf.Value(
            '*:(red|green|blue)', help='sensor / channel code'
        )
        time_sampling: Any = kwconf.Value('soft2')

    class ExampleConfig3:
        __default__ = {
            'chip_dims': kwconf.Value((256, 256), help='chip size'),
            'time_dim': kwconf.Value(
                3, type=int, help='number of time steps'
            ),
            'channels': kwconf.Value(
                '*:(red|green|blue)',
                type=str,
                help='sensor / channel code',
            ),
            'time_sampling': kwconf.Value('soft2', type=str),
        }

    classes = [
        ExampleConfig0,
        ExampleConfig1,
        ExampleConfig1d,
        ExampleConfig2,
        ExampleConfig2d,
        ExampleConfig3,
    ]
    for cls in classes:
        dcls = dataconf(cls)
        self = dcls()
        print(f'self={self}')

    # cls = ExampleConfig2
    # cls.__annotations__['channels'].__dict__
    # cls.__annotations__['set_cover_algo'].__dict__
    # # @kwconf.dataconfig
