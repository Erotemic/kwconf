"""
Misc small helpers vendored to keep kwconf dependency-free at runtime.
"""

from __future__ import annotations

import copy
from typing import Any


class _NoParamType:
    """
    Singleton sentinel for "no parameter given", distinct from ``None``.

    Reproduces ``ubelt.NoParam``: identity-comparable, falsy, and stable across
    copy/deepcopy/pickle so it survives Config cloning.
    """

    _instance = None

    def __new__(cls) -> '_NoParamType':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return 'NoParam'

    def __str__(self) -> str:
        return 'NoParam'

    def __bool__(self) -> bool:
        return False

    def __reduce__(self):
        return (_NoParamType, ())

    def __copy__(self) -> '_NoParamType':
        return self

    def __deepcopy__(self, memo) -> '_NoParamType':
        return self


NoParam = _NoParamType()


def copy_value(value: Any, *, context: str = 'configuration default') -> Any:
    """Deep-copy a concrete reset baseline or raise an actionable error.

    kwconf promises that concrete defaults and current runtime values do not
    alias. Silently falling back to a shallow copy (or identity) breaks that
    invariant for mutable objects, so concrete baselines must support
    :func:`copy.deepcopy`.

    ``default_factory`` outputs do not use this helper: their recipe is invoked
    afresh instead, matching :mod:`dataclasses` and supporting arbitrary
    non-copyable runtime objects.
    """
    try:
        return copy.deepcopy(value)
    except Exception as ex:
        raise TypeError(
            f'{context} must support copy.deepcopy() so reset state remains '
            'independent. Use Value(default_factory=...) for values that must '
            'be constructed afresh instead of copied.'
        ) from ex


def iterable(obj: Any, strok: bool = False) -> bool:
    """
    True if ``obj`` is iterable. Strings are NOT considered iterable unless
    ``strok=True``. Reproduces ``ubelt.iterable``.
    """
    try:
        iter(obj)
    except Exception:
        return False
    return strok or not isinstance(obj, str)


def import_ubelt(feature: str = 'this feature') -> Any:
    """
    Import the optional ``ubelt`` dependency, raising an actionable error if it
    is not installed. Used by the few features that still need ubelt
    (``port_to_argparse`` codegen, ``Config.__json__``).
    """
    try:
        import ubelt as ub
    except ImportError as exc:
        raise RuntimeError(
            f'{feature} requires the optional ubelt dependency. '
            f'Install it with `pip install kwconf[ubelt]`.'
        ) from exc
    return ub
