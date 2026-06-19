"""
String coercion for kwconf -- the replacement for the (now-removed) ``smartcast``
module.

This module is the home of the ``coerce`` mechanism described in
``dev/planning/design.md``. The key entry points are:

* :func:`auto` -- the default ``'auto'`` parser. Given a single string token and
  a type annotation, it infers a value using a fixed, documented precedence
  *intersected with the annotation*. The annotation's union members are the only
  candidate types it may produce.
* :func:`coerce` -- dispatch over the ``parser=`` spec on a :class:`kwconf.Value`
  (a callable, or a string key into the parser registry such as ``'auto'``,
  ``'yaml'``, ``'csv'``). Coercion only ever runs on *strings*; real Python
  objects pass through untouched.

Parsers are either *annotation-aware* or not. Aware parsers receive the field
annotation and use it to steer the produced type: ``'auto'`` gates a scalar
token by the annotation's union members, and ``'csv'`` is just ``'auto'`` mapped
over the comma-split (so ``list[str]`` keeps strings). ``'yaml'`` is unaware --
it produces its own typed structure and ignores the annotation; mismatches are
caught by the separate post-parse validation layer, not here. Custom parsers opt
in via ``register_parser(..., annotation_aware=True)``.

Deliberate departures from scriptconfig's old smartcast behavior (see the
design doc):

* **No comma-splitting.** ``"1,2,3"`` stays the literal string under every
  annotation. Use ``parser='csv'`` / ``parser='yaml'`` or ``nargs`` for lists.
* **Strict bool.** The ``'auto'`` parser accepts only ``0/1/true/false`` for a
  bool (never arbitrary ints like ``"123"``). Users wanting laxer behavior set
  an explicit ``parser``.
* **Warn, never raise, on no-match.** If nothing in the candidate set matches and
  ``str`` is not allowed, ``auto`` warns and falls back to the original string.
  Annotations are statically binding but runtime-advisory.

This is the default coercion path: ``Value.coerce()`` and ``Config.coerce()``
route here, and the deprecated ``type=`` kwarg is mapped onto it.
"""
from __future__ import annotations

import types
import typing
import warnings
from typing import Any, Callable

__all__ = ['auto', 'coerce', 'register_parser', 'CannotCoerce',
           'element_annotation']

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
    (e.g. ``list[int]``). Callers should use ``parser='csv'``/``'yaml'`` or
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


def element_annotation(annotation: Any) -> Any:
    """
    For a container annotation, return the element type; otherwise return the
    annotation unchanged.

    Used for per-token coercion of ``nargs`` CLI fields: argparse applies the
    converter to each token individually, so we coerce each token as the
    container's element type.

    Examples:
        >>> from kwconf.coerce import element_annotation
        >>> element_annotation(list[int])
        <class 'int'>
        >>> element_annotation(tuple[str, ...])
        <class 'str'>
        >>> element_annotation(int)
        <class 'int'>
        >>> element_annotation(list) is typing.Any   # bare container -> Any element
        True
    """
    origin = typing.get_origin(annotation)
    if origin in {list, set, frozenset}:
        args = typing.get_args(annotation)
        return args[0] if args else Any
    if origin is tuple:
        args = typing.get_args(annotation)
        if len(args) == 2 and args[1] is Ellipsis:
            return args[0]
        return Any  # heterogeneous tuple -> per-token Any
    if annotation in {list, set, frozenset, tuple}:
        return Any  # bare (unparameterized) container -> unknown element type
    return annotation


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
            f'{token!r}; use parser=\'csv\'/\'yaml\' or nargs. Keeping string.',
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
            "parser='yaml' requires PyYAML. Install with `pip install pyyaml`."
        ) from exc
    return yaml.safe_load(token)


def _parse_csv(token: str, annotation: Any = Any) -> list[Any]:
    """Split on commas and ``auto``-parse each element, gated by the
    container's *element* annotation.

    ``csv`` is annotation-aware: it is ``auto`` mapped over the comma-split,
    so ``list[str]`` keeps each element a string while ``list[int]`` parses
    ints. With no (or a bare-container) annotation it falls back to full
    ``auto`` per element.

    Examples:
        >>> from kwconf.coerce import _parse_csv
        >>> _parse_csv('1,2,3')                  # no annotation -> full auto
        [1, 2, 3]
        >>> _parse_csv('1,2,3o', list[str])      # element type pins to str
        ['1', '2', '3o']
        >>> _parse_csv('a,b,c')
        ['a', 'b', 'c']
        >>> _parse_csv('')
        []
    """
    elem = element_annotation(annotation)
    parts = [p.strip() for p in token.split(',')]
    return [auto(p, elem) for p in parts if p]


# ``auto`` and ``csv`` consult the field annotation; ``yaml`` does not. The
# dispatcher passes the annotation only to parsers in this set, so the public
# single-arg ``register_parser`` contract keeps working for everyone else.
_ANNOTATION_AWARE: set[Callable[..., Any]] = {auto, _parse_csv}


def _is_annotation_aware(parser: Callable[..., Any]) -> bool:
    """Whether ``parser`` accepts ``(token, annotation)`` rather than just
    ``(token)``. Opted in via ``register_parser(..., annotation_aware=True)``."""
    return parser in _ANNOTATION_AWARE


# Registry of named string parsers usable as ``parser='<name>'``.
_REGISTRY: dict[str, Callable[..., Any]] = {
    'auto': auto,
    'yaml': _parse_yaml,
    'csv': _parse_csv,
}


def register_parser(
    name: str,
    parser: Callable[..., Any],
    annotation_aware: bool = False,
) -> None:
    """
    Register a named parser usable as ``parser='<name>'``.

    Args:
        name (str): registry key.
        parser (Callable):
            the parser. By default it must accept a single string token
            (``str -> value``). If ``annotation_aware`` is True it must accept
            ``(token, annotation) -> value`` and the dispatcher will pass the
            field annotation through (use :func:`element_annotation` if you want
            the container's element type, as ``csv`` does).
        annotation_aware (bool):
            opt in to receiving the field annotation. Defaults to False so
            existing single-arg parsers keep working unchanged.
    """
    if annotation_aware:
        _ANNOTATION_AWARE.add(parser)
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
        if _is_annotation_aware(spec):
            return spec(value, annotation)
        return spec(value)
    if isinstance(spec, str):
        try:
            parser = _REGISTRY[spec]
        except KeyError as exc:
            raise TypeError(
                f'unknown coerce spec {spec!r}; '
                f'known names: {sorted(_REGISTRY)} (or pass a callable).'
            ) from exc
        if _is_annotation_aware(parser):
            return parser(value, annotation)
        return parser(value)
    raise TypeError(f'coerce spec must be a callable or str, got {type(spec)!r}')
