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
from typing import Any, Dict, Type

from kwconf.config import Config, MetaConfig
from kwconf.subconfig import SubConfig
from kwconf.value import _Value as Value

__all__ = ['dataconf', 'Config', 'MetaConfig', 'SubConfig']


class _ConfigFieldProxy:
    """Shadow a plain base-class field so instance access reaches Config data."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, instance: Config | None, owner: type | None = None) -> Any:
        if instance is None:
            if owner is None:
                raise AttributeError(self.name)
            return owner.__default__[self.name]
        return instance[self.name]

    def __set__(self, instance: Config, value: Any) -> None:
        instance[self.name] = value


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
        annotations.update(getattr(klass, '__annotations__', {}) or {})
        for name, value in vars(klass).items():
            if name.startswith('_') or name == 'default':
                continue
            if _is_field_candidate(value):
                defaults[name] = value
    return annotations, defaults


def _collect_dataclass_fields(cls: type) -> Dict[str, Any]:
    """Translate stdlib dataclass defaults into kwconf declarations."""
    defaults: Dict[str, Any] = {}
    for field in dataclasses.fields(cls):
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
    # descriptors on the generated subclass shadow those attributes and route
    # instance reads/writes through Config's mapping state.
    for name in defaults:
        # Keep Config's mapping/API methods authoritative for historical field
        # names such as ``keys``. Non-conflicting inherited class defaults need
        # a data descriptor so instance attribute access reaches ``_data``.
        if not hasattr(Config, name):
            namespace[name] = _ConfigFieldProxy(name)

    return MetaConfig(cls.__name__, (Config, cls), namespace)
