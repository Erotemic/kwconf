"""Tiny runtime stand-ins for names used mostly by postponed annotations.

Kwconf supports Python 3.10+ and uses ``from __future__ import annotations`` in
its implementation, so most ``typing`` names are never evaluated while modules
load. Importing :mod:`typing` solely to bind those names costs measurable time
in short-lived CLIs. This module has two modes:

* if another dependency already imported :mod:`typing`, reuse its real objects
  so runtime annotation introspection remains exact at no additional import
  cost;
* otherwise provide small runtime equivalents and let the adjacent ``.pyi``
  expose the exact typing definitions to static checkers.

``TYPE_CHECKING`` remains false in both modes so runtime-only optional imports
stay deferred.
"""

from __future__ import annotations

import sys
from collections.abc import (
    Callable as ABCCallable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
)

TYPE_CHECKING = False

_typing = sys.modules.get('typing')

if _typing is not None:
    Any = _typing.Any
    Callable = _typing.Callable
    Dict = _typing.Dict
    IO = _typing.IO
    List = _typing.List
    Optional = _typing.Optional
    Tuple = _typing.Tuple
    Type = _typing.Type
    Union = _typing.Union
    cast = _typing.cast
    overload = _typing.overload
    TypeVar = _typing.TypeVar
else:
    class _CallableRuntime:
        """Use the collections.abc generic when annotations are evaluated."""

        def __class_getitem__(cls, item):
            return ABCCallable[item]

    class _OptionalRuntime:
        """PEP 604 equivalent of ``typing.Optional`` for runtime evaluation."""

        def __class_getitem__(cls, item):
            try:
                return item | None
            except TypeError:
                return object

    class _UnionRuntime:
        """PEP 604 equivalent for the simple unions used by kwconf."""

        def __class_getitem__(cls, item):
            items = item if isinstance(item, tuple) else (item,)
            if not items:
                return object
            result = items[0]
            try:
                for part in items[1:]:
                    result = result | part
            except TypeError:
                return object
            return result

    class _IORuntime:
        """Subscriptable fallback for the legacy ``typing.IO`` spelling."""

        def __class_getitem__(cls, _item):
            return object

    Any = object
    Callable = _CallableRuntime
    Dict = dict
    IO = _IORuntime
    List = list
    Optional = _OptionalRuntime
    Tuple = tuple
    Type = type
    Union = _UnionRuntime

    def cast(_type, value):
        return value

    def overload(func):
        return func

    def TypeVar(_name, *args, **kwargs):
        return object
