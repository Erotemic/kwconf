"""Variant: apply dataclass_transform to the BASE CLASS instead of a metaclass,
to see whether ty synthesizes __init__ in this form (it did for pydantic)."""

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
def Value(
    default: T,
    *,
    coerce: Any = ...,
    help: str | None = ...,
    required: bool = ...,
    default_factory: None = ...,
) -> T: ...
@overload
def Value(
    *,
    default_factory: Callable[[], T],
    coerce: Any = ...,
    help: str | None = ...,
    required: bool = ...,
) -> T: ...
@overload
def Value(
    *, required: Literal[True], coerce: Any = ..., help: str | None = ...
) -> Any: ...
def Value(
    default=None,
    *,
    default_factory=None,
    coerce=None,
    help=None,
    required=False,
):  # type: ignore
    return _Value()


@dataclass_transform(field_specifiers=(Value,), kw_only_default=True)
class Config:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)


class MyConfig(Config):
    epochs: int = Value(default=10)  # keyword default (pyright-reliable)
    name: str = Value(default='hi')


ok = MyConfig(epochs=3, name='x')  # correct
bad1 = MyConfig(epochs='3', name='x')  # E: str -> int
bad2 = MyConfig(nope=1)  # E: unknown field
