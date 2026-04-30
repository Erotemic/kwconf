"""
Backwards-compatible imports for ``kwconf.dataconfig``.

The actual ``DataConfig`` class and ``MetaConfig`` metaclass now live in
:mod:`kwconf.config`. This module is kept so that code written against
``from kwconf.dataconfig import DataConfig`` continues to work, and to
host the :func:`dataconf` decorator.

Example:
    >>> import kwconf
    >>> class ExampleConfig(kwconf.DataConfig):
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

import inspect
from typing import Any, Dict, Type

from kwconf.config import DataConfig, MetaConfig
from kwconf.subconfig import SubConfig

# ``MetaDataConfig`` is the older name for the shared metaclass. Keep the
# alias so user code that referenced it directly still imports cleanly.
MetaDataConfig = MetaConfig

__all__ = ['dataconf', 'DataConfig', 'MetaDataConfig', 'SubConfig']


def dataconf(cls: Type[Any]) -> Type[Any]:
    """
    A dataclass-style decorator for kwconf configs.

    For classes that already inherit from :class:`DataConfig` the metaclass
    has already done all the work and the decorator is a no-op. For classes
    that do not, the decorator builds an equivalent ``DataConfig`` subclass
    with the same name and module so the result behaves like a normal
    DataConfig (including pickleability when the class lives at module
    scope).

    Note:
        Inheriting from :class:`DataConfig` directly is the preferred
        pattern. The decorator is kept primarily for compatibility.

    Example:
        >>> from kwconf.dataconfig import *  # NOQA
        >>> import kwconf
        >>> @dataconf
        >>> class ExampleDataConfig2:
        >>>     chip_dims = kwconf.Value((256, 256), help='chip size')
        >>>     time_dim = kwconf.Value(3, help='number of time steps')
        >>>     channels = kwconf.Value('*:(red|green|blue)', help='sensor / channel code')
        >>>     time_sampling = kwconf.Value('soft2')
        >>> cls = ExampleDataConfig2
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
    #     >>> class PathologicalConfig2(kwconf.DataConfig):
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
    if getattr(cls, '__did_dataconfig_init__', False):
        # Already a DataConfig subclass; the metaclass handled everything.
        return cls

    namespace: Dict[str, Any] = {
        '__doc__': getattr(cls, '__doc__', None),
        '__qualname__': cls.__qualname__,
        '__module__': cls.__module__,
        '__description__': getattr(cls, '__description__', None),
        '__epilog__': getattr(cls, '__epilog__', None),
        '__annotations__': dict(getattr(cls, '__annotations__', {}) or {}),
    }
    # Carry over the class-level fields. The metaclass turns them into
    # ``__default__`` entries during class construction.
    for k, v in vars(cls).items():
        if k.startswith('_'):
            continue
        if isinstance(v, (classmethod, staticmethod)):
            namespace[k] = v
            continue
        if callable(v) and not (inspect.isclass(v) and issubclass(v, DataConfig)):
            namespace[k] = v
            continue
        namespace[k] = v
    if '__default__' in vars(cls):
        namespace['__default__'] = vars(cls)['__default__']

    return MetaConfig(cls.__name__, (DataConfig,), namespace)


def __example__() -> None:
    """
    Doctests are broken for DataConfigs, so putting them here.
    """
    import kwconf
    dataclasses: Any
    try:
        import dataclasses
    except ImportError:
        dataclasses = None  # type: ignore

    if dataclasses is None:
        return

    @dataclasses.dataclass
    class ExampleDataConfig0:
        x: int = 0
        y: str = '3'

    ### Different variants of the same basic configuration (varying amounts of metadata)
    class ExampleDataConfig1:
        chip_dims = (256, 256)
        time_dim = 5
        channels = 'red|green|blue'
        time_sampling = 'soft2'

    ExampleDataConfig1d = dataclasses.dataclass(ExampleDataConfig1)

    @dataclasses.dataclass
    class ExampleDataConfig2:
        chip_dims = kwconf.Value((256, 256), help='chip size')
        time_dim = kwconf.Value(3, help='number of time steps')
        channels = kwconf.Value('*:(red|green|blue)', help='sensor / channel code')
        time_sampling = kwconf.Value('soft2')

    @dataclasses.dataclass
    class ExampleDataConfig2d:
        chip_dims = kwconf.Value((256, 256), help='chip size')
        time_dim: Any = kwconf.Value(3, help='number of time steps')
        channels: Any = kwconf.Value('*:(red|green|blue)', help='sensor / channel code')
        time_sampling: Any = kwconf.Value('soft2')

    class ExampleDataConfig3:
        __default__ = {
            'chip_dims': kwconf.Value((256, 256), help='chip size'),
            'time_dim': kwconf.Value(3, type=int, help='number of time steps'),
            'channels': kwconf.Value('*:(red|green|blue)', type=str, help='sensor / channel code'),
            'time_sampling': kwconf.Value('soft2', type=str),
        }

    classes = [ExampleDataConfig0, ExampleDataConfig1, ExampleDataConfig1d,
               ExampleDataConfig2, ExampleDataConfig2d, ExampleDataConfig3]
    for cls in classes:
        dcls = dataconf(cls)
        self = dcls()
        print(f'self={self}')

    # cls = ExampleDataConfig2
    # cls.__annotations__['channels'].__dict__
    # cls.__annotations__['set_cover_algo'].__dict__
    # # @kwconf.dataconfig
