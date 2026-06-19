"""Probe: does positional-default detection work WITHOUT @overload?"""
from __future__ import annotations

from typing import Any, Callable, TypeVar, dataclass_transform

T = TypeVar("T")


# Single (non-overloaded) field specifier. `default` is the first positional.
def V(default: T = ..., *, coerce: Any = ..., help: str | None = ...) -> T:  # type: ignore
    return default


@dataclass_transform(field_specifiers=(V,), kw_only_default=True)
class Meta(type):
    def __new__(mcls, name, bases, ns, **kw):  # type: ignore[no-untyped-def]
        return super().__new__(mcls, name, bases, ns)


class Conf(metaclass=Meta):
    pass


class C(Conf):
    p: int = V(5)              # positional default
    q: int = V(default=5)      # keyword default
    r: int = V(5, coerce=str)  # positional default + extra kwarg


c = C()  # legal iff p, q, r are all treated as optional
bad = C(p="nope")  # E: str not assignable to int
