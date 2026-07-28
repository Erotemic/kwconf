"""
The RECOMMENDED recipe distilled from the probes:

  * Value/Flag are typed as field-specifier *functions returning T* (the
    attrs/pydantic trick) -> field-default validation works on ty AND pyright.
  * dataclass_transform is applied to the BASE CLASS -> pyright synthesizes a
    typed __init__ (constructor-kwarg checking). ty ignores it for now but
    degrades gracefully (no false positives on construction... see note).
  * Defaults are passed by KEYWORD (default=/default_factory=). pyright treats
    a *positional* default (Value(10)) as a REQUIRED field, so keyword form is
    required for ergonomic `MyConfig()` construction under pyright.

Expected checker results:
  pyright: only the 3 lines marked `# ERR` should error.
  ty:      only the 2 default-validation lines (`# ERR default`) error;
           ty does not synthesize __init__, so the constructor-kwarg lines
           are not checked.
"""

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
    *,
    default: T,
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
    *,
    default=None,
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


class Train(Config):
    epochs: int = Value(default=100)
    lr: float = Value(default=1e-3, help='learning rate')
    name: str | None = Value(default=None)
    tags: list[str] = Value(default_factory=list)
    out_dir: str = Value(required=True)


# correct usage -- clean on both checkers
good = Train(epochs=10, lr=0.1, name='run1', tags=['a'], out_dir='/tmp/x')
defaulted = Train(out_dir='/tmp/y')  # everything else has a default


class BadDefaults(Config):
    a: int = Value(default=None)  # ERR default: None -> int
    b: list[int] = Value(
        default_factory=lambda: ['x']
    )  # ERR default: list[str] -> list[int]


bad = Train(
    epochs='not-int', out_dir='/tmp/z'
)  # ERR (pyright only): str -> int
