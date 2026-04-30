"""
Compatibility layer for the older `DataConfig` name.

New `kwconf` code should generally prefer :class:`kwconf.DataConfig`, which now
supports the same typed class-variable schema style. `DataConfig` remains as a
transition-friendly subclass and compatibility surface.

Similar to the old-style Config objects, you simply declare a class that
inherits from :class:`kwconf.DataConfig` (or is wrapped by
:func:`kwconf.datconf`) and declare the class variables as the config
attributes much like you would write a dataclass.


Creating an instance of a ``DataConfig`` class works just like a regular
dataclass, and nothing special happens. You can create the argument parser by
using the :func:``DataConfig.cli`` classmethod, which works similarly to the
old-style :class:`kwconf.DataConfig` constructor.

The following is the same top-level example as in :mod:`kwconf.config`,
but using ``DataConfig`` instead. It works as a drop-in replacement.


Example:
    >>> import kwconf
    >>> # In its simplest incarnation, the config class specifies default values.
    >>> # For each configuration parameter.
    >>> class ExampleConfig(kwconf.DataConfig):
    >>>      num = 1
    >>>      mode = 'bar'
    >>>      ignore = ['baz', 'biz']
    >>> # Creating an instance, starts using the defaults
    >>> config = ExampleConfig()
    >>> # Typically you will want to update default from a dict or file.  By
    >>> # specifying cmdline=True you denote that it is ok for the contents of
    >>> # `sys.argv` to override config values. Here we pass a dict to `load`.
    >>> kwargs = {'num': 2}
    >>> config.load(kwargs, cmdline=False)
    >>> assert config['num'] == 2
    >>> # The `load` method can also be passed a json/yaml file/path.
    >>> import tempfile
    >>> config_fpath = tempfile.mktemp()
    >>> open(config_fpath, 'w').write('{"num": 3}')
    >>> config.load(config_fpath, cmdline=False)
    >>> assert config['num'] == 3
    >>> # It is possible to load only from CLI by setting cmdline=True
    >>> # or by setting it to a custom sys.argv
    >>> config.load(cmdline=['--num=4', '--mode' ,'fiz'])
    >>> assert config['num'] == 4
    >>> assert config['mode'] == 'fiz'
    >>> # You can also just use the command line string itself
    >>> config.load(cmdline='--num=4 --mode fiz')
    >>> assert config['num'] == 4
    >>> assert config['mode'] == 'fiz'
    >>> # Note that using `config.load(cmdline=True)` will just use the
    >>> # contents of sys.argv

Notes:
    https://docs.python.org/3/library/dataclasses.html
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Type, cast
import inspect

from kwconf.config import Config, MetaConfig
from kwconf.value import Value
import ubelt as ub
from kwconf import diagnostics
from kwconf.subconfig import SubConfig
from collections.abc import Sequence

__all__ = ['dataconf', 'DataConfig', 'MetaDataConfig', 'SubConfig']


def dataconf(cls: Type[Any]) -> Type[Any]:
    """
    A dataclass-style decorator.

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
        >>> self = cls()
        >>> assert self['time_dim'] == 3

    Example:
        >>> from kwconf.dataconfig import *  # NOQA
        >>> import kwconf
        >>> @dataconf
        >>> class PathologicalConfig:
        >>>     default0 = kwconf.Value((256, 256), help='chip size')
        >>>     keys = [1, 2, 3]
        >>>     __default__ = {
        >>>         'argparse': 3.3,
        >>>         'keys': [4, 5],
        >>>     }
        >>>     time_sampling = kwconf.Value('soft2')
        >>>     def foobar(self):
        >>>         ...
        >>> self = PathologicalConfig(1)
        >>> assert self['default0'] == 1
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
        if callable(v) and not (inspect.isclass(v) and issubclass(v, Config)):
            namespace[k] = v
            continue
        namespace[k] = v
    if '__default__' in vars(cls):
        namespace['__default__'] = vars(cls)['__default__']

    return MetaDataConfig(cls.__name__, (DataConfig,), namespace)


class MetaDataConfig(MetaConfig):
    """
    This metaclass allows us to call `dataconf` when a new subclass is defined
    without the extra boilerplate.

    All shared schema work (class-attr collection, ``Value``/``SubConfig``
    normalization, ``__default__`` inheritance, ``__class__`` reservation, and
    trailing-comma warning) is performed by :class:`MetaConfig`. This subclass
    just sets the marker attribute used by :func:`dataconf` and rewrites the
    autogenerated ``__init__`` docstring.
    """

    @staticmethod
    def __new__(mcls: type,
                name: str,
                bases: Tuple[type, ...],
                namespace: Dict[str, Any],
                *args: Any,
                **kwargs: Any) -> type:
        if diagnostics.DEBUG_META_DATA_CONFIG:
            print(f'MetaDataConfig.__new__ called: {mcls=} {name=} {bases=} {namespace=} {args=} {kwargs=}')

        is_root = (
            namespace.get('__module__') == 'kwconf.dataconfig' and name == 'DataConfig'
        )
        if not is_root:
            namespace['__did_dataconfig_init__'] = True

        cls = super().__new__(mcls, name, bases, namespace, *args, **kwargs)  # type: ignore

        if cls.__init__.__doc__ == '__autogenerateme__':
            valid_keys = list(cls.__default__.keys())
            cls.__init__.__doc__ = ub.codeblock(
                f'''
                Valid options: {valid_keys}

                Args:
                    *args: positional arguments for this data config
                    **kwargs: keyword arguments for this data config
                ''')
        return cls


class DataConfig(Config, metaclass=MetaDataConfig):
    """
    Base class for dataconfig-style configs.
    Overwrite this docstr with a description.

    To use, create a class (e.g. MyConfig) that inherits from DataConfig.  The
    configuration keys and their default values are specified by class level
    attributes. Metadata for keys can be given by specifying the default values
    as a :class:`kwconf.Value`.

    An instance can be created programmatically with keyword arguments
    specifying updates to default values.

    The :func:`DataConfig.cli` classmethod can be used to create an instance
    where the values are optionally populated from command line arguments in
    ``sys.argv`` or a custom ``argv``.

    Usage of the config is flexible.  It can be used as a dictionary or as a
    namespace. That is, you can either use ``config['key']`` or ``config.key``
    to access values for ``key``. The only incompatibility between this and a
    normal dictionary is that this does not allow new keys to be added,
    otherwise it can be treated exactly as a dictionary.

    Example:
        >>> import kwconf
        >>> class MyConfig(kwconf.DataConfig):
        >>>     key1 = 'default-value1'
        >>>     key2 = 'default-value2'
        >>>     key3 = kwconf.Value('default-value3', help='extra metadata!')
        >>> # Create a programmatic instance
        >>> config = MyConfig()
        >>> print(f'config={config}')
        config=<MyConfig({'key1': 'default-value1', 'key2': 'default-value2', 'key3': 'default-value3'})>
        >>> # Create an instance via command line args
        >>> # (note the default "smartcasting")
        >>> config = MyConfig.cli(argv=['--key1', '123', '--key2=345', '--key3=abc'])
        >>> print(f'config={config}')
        config=<MyConfig({'key1': 123, 'key2': 345, 'key3': 'abc'})>

    For fine-grained control overwrite the following attributes:

        * ``__epilog__`` (str):  documentation for the epilog of the argparse help string

        * ``__post_init__`` (callable): function that normalizes values on instance creation.

        * ``__default__`` (Dict[str, Any]): an alternate way to specify key/default-values based on an existing dictionary. Specifying an item in this dictionary has the same effect as specifying a class-attribute.

    SeeAlso:
        :class:`kwconf.DataConfig`
    """
    # Not sure if having a docstring for this will break user-configs.
    # No docstring, because user-specified docstring will define the default
    # __description__.
    # Note: class attributes may be raw literals; the metaclass normalizes
    # them into Value/SubConfig instances after class creation.
    __default__: Dict[str, Any] = {}
    __description__: Optional[str] = None
    __epilog__: Optional[str] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        "__autogenerateme__"
        # Private internal hack to prevent __post_init__ from being called
        # if we are immediately going to load and call it again.
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

    def __getattr__(self, key: str) -> Any:
        # Note: attributes that mirror the public API will be suppressed
        # It is generally better to use the dictionary interface instead
        # But we want this to be data-classy, so...
        if key.startswith('_'):
            # config vars must not start with '_'. That is only for us
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
        else:
            can_setattr = (getattr(self, '__allow_newattr__', False))  # case where user can add new keys on the fly
            can_setattr |= (getattr(self, '_enable_setattr', False) and key in self)  # internal usage for initialization
            if can_setattr:
                # After object initialization allow the user to use setattr on any
                # value in the underlying dictionary. Everything else uses the
                # normal mechanism.
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
        Mimics argparse.ArgumentParser.parse_args
        """
        if namespace is not None:
            raise NotImplementedError(
                'namespaces are not handled in kwconf')
        return cast("DataConfig", cls.cli(argv=args, strict=True))

    @classmethod
    def parse_known_args(cls,
                         args: Sequence[str] | None = None,
                         namespace: Any = None) -> "DataConfig":
        """
        Mimics argparse.ArgumentParser.parse_known_args
        """
        if namespace is not None:
            raise NotImplementedError(
                'namespaces are not handled in kwconf')
        return cast("DataConfig", cls.cli(argv=args, strict=False))

    @classmethod
    def _register_main(cls, func):
        """
        Register a function as the main method for this dataconfig CLI
        """
        cls.main = func
        return func


