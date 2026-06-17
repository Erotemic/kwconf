"""
String coercion for kwconf -- the eventual successor to :mod:`kwconf.smartcast`.

This module is the home of the ``coerce`` mechanism described in
``dev/planning/design.md``. The key entry points are:

* :func:`auto` -- the default ``'auto'`` parser. Given a single string token and
  a type annotation, it infers a value using a fixed, documented precedence
  *intersected with the annotation*. The annotation's union members are the only
  candidate types it may produce.
* :func:`coerce` -- dispatch over the ``coerce=`` spec on a :class:`kwconf.Value`
  (a callable, or a string key into the parser registry such as ``'auto'``,
  ``'yaml'``, ``'csv'``). Coercion only ever runs on *strings*; real Python
  objects pass through untouched.

Deliberate departures from scriptconfig / smartcast (see the design doc):

* **No comma-splitting.** ``"1,2,3"`` stays the literal string under every
  annotation. Use ``coerce='csv'`` / ``coerce='yaml'`` or ``nargs`` for lists.
* **Strict bool.** The ``'auto'`` parser accepts only ``0/1/true/false`` for a
  bool (never arbitrary ints like ``"123"``). Users wanting laxer behavior set
  an explicit ``coerce``.
* **Warn, never raise, on no-match.** If nothing in the candidate set matches and
  ``str`` is not allowed, ``auto`` warns and falls back to the original string.
  Annotations are statically binding but runtime-advisory.

This module is intentionally additive: it is not yet wired into the Value /
Config hot path. That integration (and the removal of ``smartcast``) happens in
a later step.
"""
from __future__ import annotations

import types
import typing
import warnings
from typing import Any, Callable

__all__ = ['auto', 'coerce', 'register_parser', 'CannotCoerce']

NoneType = type(None)

# Fixed, documented global precedence. ``str`` is always the final catch-all.
# ``int`` precedes ``bool`` so a bare ``"1"`` becomes ``int`` 1 when int is an
# allowed candidate; ``bool`` only claims ``"1"``/``"0"`` when int is absent.
_PRECEDENCE: list[type] = [NoneType, int, float, complex, bool, str]


def _parse_none(token: str) -> None:
    if token.strip().lower() in {'none', 'null'}:
        return None
    raise ValueError(token)


def _parse_bool(token: str) -> bool:
    """Strict boolean: only ``true``/``false``/``1``/``0`` (case-insensitive)."""
    low = token.strip().lower()
    if low in {'true', '1'}:
        return True
    if low in {'false', '0'}:
        return False
    raise ValueError(token)


def _identity(token: str) -> str:
    return token


_PARSERS: dict[type, Callable[[str], Any]] = {
    NoneType: _parse_none,
    int: int,
    float: float,
    complex: complex,
    bool: _parse_bool,
    str: _identity,  # catch-all; never fails
}


class CannotCoerce(Exception):
    """The annotation is a shape ``auto`` cannot build from a single token
    (e.g. ``list[int]``). Callers should use ``coerce='csv'``/``'yaml'`` or
    ``nargs``."""


def _candidate_types(annotation: Any) -> list[type]:
    """
    Ordered candidate types the ``auto`` parser may produce for ``annotation``.

    Examples:
        >>> from kwconf.coerce import _candidate_types, NoneType
        >>> _candidate_types(int)
        [<class 'int'>]
        >>> _candidate_types(int | None) == [NoneType, int]
        True
        >>> _candidate_types(str | int | None) == [NoneType, int, str]
        True
    """
    if annotation is None or annotation is Any:
        return list(_PRECEDENCE)  # full auto

    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        member_types = {type(arg) for arg in typing.get_args(annotation)}
        return [t for t in _PRECEDENCE if t in member_types]
    if origin in {typing.Union, types.UnionType}:
        members = set(typing.get_args(annotation))
        ordered = [t for t in _PRECEDENCE if t in members]
        if not ordered:
            # e.g. ``Path | None`` with no scalar members we understand
            raise CannotCoerce(annotation)
        return ordered
    if origin is not None:
        # Parameterized generic (list[int], dict[...], etc.)
        raise CannotCoerce(annotation)
    if isinstance(annotation, type):
        if annotation in _PRECEDENCE:
            return [annotation]
        raise CannotCoerce(annotation)
    # Unresolved string / forward ref / anything else -> behave like Any.
    return list(_PRECEDENCE)


def auto(token: str, annotation: Any = Any) -> Any:
    """
    The default ``'auto'`` parser. Parse a CLI/env string token, gated by
    ``annotation``.

    Examples:
        >>> from kwconf.coerce import auto
        >>> auto('123')
        123
        >>> auto('1.5')
        1.5
        >>> auto('True')
        True
        >>> auto('None') is None
        True
        >>> auto('foo123')
        'foo123'
        >>> auto('1,2,3')                 # no comma-splitting
        '1,2,3'
        >>> auto('123', str)              # str annotation pins to string
        '123'
        >>> auto('123', int | None)
        123
        >>> auto('1', int | bool)         # int beats bool for "1"
        1
        >>> auto('1', bool | None)        # no int -> bool claims "1"
        True
    """
    if not isinstance(token, str):
        return token

    try:
        candidates = _candidate_types(annotation)
    except CannotCoerce:
        warnings.warn(
            f'auto parser cannot build {annotation!r} from the single token '
            f'{token!r}; use coerce=\'csv\'/\'yaml\' or nargs. Keeping string.',
            stacklevel=2,
        )
        return token

    for cand in candidates:
        try:
            return _PARSERS[cand](token)
        except (ValueError, TypeError):
            continue

    # Nothing matched and ``str`` was not an allowed candidate. Per the design
    # we warn and keep the string rather than raising.
    warnings.warn(
        f'could not parse {token!r} into any of {annotation!r}; keeping string',
        stacklevel=2,
    )
    return token


def _parse_yaml(token: str) -> Any:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "coerce='yaml' requires PyYAML. Install with `pip install pyyaml`."
        ) from exc
    return yaml.safe_load(token)


def _parse_csv(token: str) -> list[Any]:
    """Split on commas and ``auto``-parse each (scalar) element.

    Examples:
        >>> from kwconf.coerce import _parse_csv
        >>> _parse_csv('1,2,3')
        [1, 2, 3]
        >>> _parse_csv('a,b,c')
        ['a', 'b', 'c']
        >>> _parse_csv('')
        []
    """
    parts = [p.strip() for p in token.split(',')]
    return [auto(p) for p in parts if p]


# Registry of named string parsers usable as ``coerce='<name>'``.
_REGISTRY: dict[str, Callable[..., Any]] = {
    'auto': auto,
    'yaml': _parse_yaml,
    'csv': _parse_csv,
}


def register_parser(name: str, parser: Callable[[str], Any]) -> None:
    """Register a named parser usable as ``coerce='<name>'``."""
    _REGISTRY[name] = parser


def coerce(value: Any, annotation: Any = Any, spec: Any = 'auto') -> Any:
    """
    Coerce ``value`` according to a ``coerce=`` ``spec``.

    Coercion runs **only on strings**; any non-string ``value`` is returned
    unchanged (the "parse iff string" rule). ``spec`` may be:

    * a callable ``str -> value`` (called directly), or
    * a string key into the parser registry (``'auto'``, ``'yaml'``, ``'csv'``).

    Only ``'auto'`` consults ``annotation``; other named parsers ignore it.

    Examples:
        >>> from kwconf.coerce import coerce
        >>> coerce('123')                 # default 'auto'
        123
        >>> coerce(123)                   # non-string passes through
        123
        >>> coerce('1,2,3', spec='csv')
        [1, 2, 3]
        >>> coerce('123', spec=str)       # explicit callable escape hatch
        '123'
    """
    if not isinstance(value, str):
        return value
    if callable(spec):
        return spec(value)
    if isinstance(spec, str):
        try:
            parser = _REGISTRY[spec]
        except KeyError as exc:
            raise TypeError(
                f'unknown coerce spec {spec!r}; '
                f'known names: {sorted(_REGISTRY)} (or pass a callable).'
            ) from exc
        if parser is auto:
            return auto(value, annotation)
        return parser(value)
    raise TypeError(f'coerce spec must be a callable or str, got {type(spec)!r}')
