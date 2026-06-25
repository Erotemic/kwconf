"""Faithful test of GPT's recommended shape: metaclass transform, keyword-only
Value defaults, explicit permissive base __init__. Settles whether ty 0.0.49
synthesizes a checking __init__ here."""

from __future__ import annotations

from typing import (
    Any,
    Callable,
    Literal,
    TypeVar,
    dataclass_transform,
    overload,
)

T = TypeVar('T')


class _Value:
    def __init__(self, *a: Any, **k: Any) -> None: ...


@overload
def Value(*, default: T, coerce: Any = ..., help: str | None = ...) -> T: ...
@overload
def Value(*, default_factory: Callable[[], T], coerce: Any = ...) -> T: ...
@overload
def Value(*, required: Literal[True], coerce: Any = ...) -> Any: ...
def Value(
    *,
    default=...,
    default_factory=...,
    required=False,
    coerce='auto',
    help=None,
):  # type: ignore
    return _Value()


@dataclass_transform(field_specifiers=(Value,), kw_only_default=True)
class ConfigMeta(type):
    def __new__(mcls, name, bases, ns, **kw):  # type: ignore[no-untyped-def]
        return super().__new__(mcls, name, bases, ns)


class Config(metaclass=ConfigMeta):
    def __init__(self, **kwargs: Any) -> None: ...


class Train(Config):
    epochs: int = 100  # bare default
    lr: float = Value(default=0.01)
    names: list[str] = Value(default_factory=list)
    seed: int = Value(required=True)


class Bad(Config):
    a: int = Value(default=None)  # E: None -> int (default check)


good = Train(
    seed=0
)  # OK: bare + keyword-defaults optional, seed required given
e1 = Train(seed=0, lr='x')  # E: str -> float (ctor type check)
e2 = Train(seed=0, nope=1)  # E: unknown field
e3 = Train(lr=0.1)  # E: missing required 'seed'
