"""
POC: the proposed ``auto`` parser (replacement for ``smartcast``) plus the
"parse only at the text boundary" decision.

Two ideas under test:

1. ANNOTATION-GATED PARSING. A string token is parsed by trying a fixed,
   documented precedence of candidate types, but the candidate set is
   *intersected with the field's annotation*. Output type is always a member
   of the annotation (the one exception: warn-and-fall-back-to-string).

2. BOUNDARY DISCIPLINE. The normal constructor TRUSTS the user and never
   coerces (a string stays a string). Coercion only happens on textual
   ingestion: argv/env, or the explicit ``Config.coerce(**kw)`` alt-constructor
   (handy for tests). This is what lets the static type checker stay honest:
   ``MyConfig(x='3')`` is a type error rather than silent magic.

Run directly:  python auto_parser.py   (prints a matrix + asserts PASS)
"""
from __future__ import annotations

import types
import typing
import warnings
from typing import Any, get_type_hints

NoneType = type(None)

# Fixed, documented global precedence. `str` is always the final catch-all.
# `int` precedes `bool` so a bare "1" becomes int 1 when int is allowed; bool
# only claims "1"/"0" when int is NOT in the candidate set. `bool` always
# claims "true"/"false".
_PRECEDENCE: list[type] = [NoneType, int, float, complex, bool, str]


def _parse_none(tok: str) -> None:
    if tok.strip().lower() in {"none", "null"}:
        return None
    raise ValueError(tok)


def _parse_bool(tok: str) -> bool:
    low = tok.strip().lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    return bool(int(tok))  # "1"/"0"; raises ValueError otherwise


_PARSERS: dict[type, typing.Callable[[str], Any]] = {
    NoneType: _parse_none,
    int: int,
    float: float,
    complex: complex,
    bool: _parse_bool,
    str: lambda s: s,  # catch-all; never fails
}


class CannotAutoParse(Exception):
    """The annotation is a shape the auto parser can't satisfy from a single
    token (e.g. list[int]). Caller should use coerce='csv'|'yaml' or nargs."""


def _candidate_types(annotation: Any) -> list[type]:
    """Ordered candidate types the parser may produce for this annotation."""
    if annotation is None or annotation is Any:
        return list(_PRECEDENCE)  # full auto

    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        members = set(typing.get_args(annotation))
        ordered = [t for t in _PRECEDENCE if t in members]
        unknown = members - set(_PRECEDENCE)
        if unknown and not ordered:
            # e.g. Path | None with no scalar members we understand
            raise CannotAutoParse(annotation)
        return ordered
    if origin is not None:
        # Parameterized generic (list[int], dict[...], Literal[...], etc.)
        raise CannotAutoParse(annotation)
    if isinstance(annotation, type):
        if annotation in _PRECEDENCE:
            return [annotation]
        raise CannotAutoParse(annotation)
    # Unresolved string / forward ref / anything else -> behave like Any.
    return list(_PRECEDENCE)


def auto_parse(token: str, annotation: Any = Any) -> Any:
    """Parse a CLI/env string token, gated by ``annotation``."""
    try:
        candidates = _candidate_types(annotation)
    except CannotAutoParse:
        warnings.warn(
            f"auto parser cannot build {annotation!r} from the single token "
            f"{token!r}; use coerce='csv'|'yaml' or nargs. Keeping string.",
            stacklevel=2,
        )
        return token

    for t in candidates:
        try:
            return _PARSERS[t](token)
        except (ValueError, TypeError):
            continue

    # Nothing matched and str was not an allowed candidate. Per the design we
    # do NOT raise -- we warn and keep the string (annotations are statically
    # binding but runtime-advisory).
    warnings.warn(
        f"could not parse {token!r} into any of {annotation!r}; keeping string",
        stacklevel=2,
    )
    return token


# --------------------------------------------------------------------------
# Boundary discipline: the core trusts; only .coerce() (and argv) parse.
# --------------------------------------------------------------------------
class Config:
    def __init__(self, **kwargs: Any) -> None:
        # Python boundary: store exactly what we were given. No coercion.
        hints = get_type_hints(type(self))
        data = {k: getattr(type(self), k, None) for k in hints}
        data.update(kwargs)
        self.__dict__.update(data)

    @classmethod
    def coerce(cls, **kwargs: Any) -> "Config":
        # Opt-in textual ingestion (mirrors what argv/env parsing will do).
        # Parse iff the incoming value is a string; pass real objects through.
        hints = get_type_hints(cls)
        parsed = {
            k: (auto_parse(v, hints.get(k, Any)) if isinstance(v, str) else v)
            for k, v in kwargs.items()
        }
        return cls(**parsed)


def _is(value: Any, expect_type: type) -> bool:
    return type(value) is expect_type


def _selftest() -> None:
    A = Any
    # --- full auto (untyped / Any) ------------------------------------
    assert auto_parse("True", A) is True
    assert auto_parse("None", A) is None
    assert auto_parse("123", A) == 123 and _is(auto_parse("123", A), int)
    assert auto_parse("1.5", A) == 1.5 and _is(auto_parse("1.5", A), float)
    assert auto_parse("foo123", A) == "foo123"
    assert auto_parse("1,2,3", A) == "1,2,3"          # CHANGED: no comma split

    # --- bare str annotation pins everything to string ----------------
    assert auto_parse("123", str) == "123"
    assert auto_parse("None", str) == "None"
    assert auto_parse("True", str) == "True"

    # --- str | int | None: ints pass, non-numeric stays string --------
    U = str | int | None
    assert auto_parse("123", U) == 123 and _is(auto_parse("123", U), int)
    assert auto_parse("foo", U) == "foo"
    assert auto_parse("None", U) is None

    # --- int | None, str NOT allowed: warn + fall back to string ------
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        got = auto_parse("foo", int | None)
    assert got == "foo"
    assert any("could not parse" in str(x.message) for x in w)

    # --- bool / int interplay -----------------------------------------
    assert auto_parse("1", int | bool) == 1 and _is(auto_parse("1", int | bool), int)
    assert auto_parse("1", bool | None) is True       # no int -> bool claims "1"
    assert auto_parse("true", bool | None) is True
    with warnings.catch_warnings(record=True) as w:   # "true" w/ only int -> fallback
        warnings.simplefilter("always")
        assert auto_parse("true", int | None) == "true"
    assert any("could not parse" in str(x.message) for x in w)

    # --- containers can't be built from a single token ----------------
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert auto_parse("1,2,3", list[int]) == "1,2,3"
    assert any("coerce='csv'" in str(x.message) for x in w)

    # --- boundary discipline ------------------------------------------
    class Demo(Config):
        data: Any = None
        name: str = None        # type: ignore[assignment]
        n: int | None = None

    # Python constructor trusts: string stays string even for an int field.
    assert Demo(n="123").n == "123"
    # Opt-in coerce parses, gated by the annotation.
    assert Demo.coerce(n="123").n == 123
    assert Demo.coerce(name="123").name == "123"      # str annotation pins it
    assert Demo.coerce(data="True").data is True       # Any -> full auto
    assert Demo.coerce(data="1,2,3").data == "1,2,3"   # no comma split
    # Non-string values pass through coerce untouched.
    assert Demo.coerce(n=7).n == 7

    print("auto_parser self-test: PASS")


def _matrix() -> None:
    tokens = ["True", "None", "123", "1.5", "foo123", "1,2,3", "1"]
    cols = [("Any", Any), ("str", str), ("int|None", int | None),
            ("str|int|None", str | int | None), ("bool|None", bool | None)]
    width = 14
    header = "token".ljust(10) + "".join(name.ljust(width) for name, _ in cols)
    print(header)
    print("-" * len(header))
    for tok in tokens:
        row = tok.ljust(10)
        for _, ann in cols:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                val = auto_parse(tok, ann)
            row += f"{val!r}".ljust(width)
        print(row)


if __name__ == "__main__":
    _matrix()
    print()
    _selftest()
