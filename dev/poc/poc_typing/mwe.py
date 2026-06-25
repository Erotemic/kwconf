"""Minimal repro: does the checker synthesize a *checking* __init__ from a
hand-rolled dataclass_transform metaclass?

Expected (per PEP 681): line 27 and line 28 should both error.
"""

from __future__ import annotations

from typing import Any, TypeVar, dataclass_transform, overload

T = TypeVar('T')


@overload
def Value(*, default: T) -> T: ...
@overload
def Value(*, required: bool) -> Any: ...
def Value(*, default=None, required=False):  # type: ignore[no-untyped-def]
    return default


@dataclass_transform(field_specifiers=(Value,), kw_only_default=True)
class Meta(type):
    def __new__(mcls, name, bases, ns, **kw):  # type: ignore[no-untyped-def]
        return super().__new__(mcls, name, bases, ns)


class Config(metaclass=Meta):
    def __init__(self, **kwargs: Any) -> None: ...  # permissive runtime base


class C(Config):
    x: int = Value(default=1)


C(x='bad')  # EXPECT error: str is not assignable to int
C(nope=1)  # EXPECT error: unknown keyword argument
