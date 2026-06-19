"""
POC: the *proposed* Value, typed so the checker validates a field's default
(and constructor kwargs) against its annotation.

The key trick (same one attrs ``field()`` and pydantic ``Field()`` use): the
field specifier is *typed* to return ``T`` -- the value type -- even though at
runtime it returns a ``Value`` wrapper object. That lie is what makes the
class-body assignment ``x: int = Value(10)`` type-check as ``int = int``,
while ``x: int = Value(None)`` becomes ``int = None`` -> error.

Combined with ``dataclass_transform(field_specifiers=(Value, Flag))`` on the
metaclass, the checker also synthesizes ``__init__(*, x: int, ...)`` so
``MyConfig(x='3')`` is a static error -- which is the "drop runtime coercion
at the Python boundary, let the type checker catch it" decision, enforced
statically.
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

T = TypeVar("T")


class _Value:
    """Runtime wrapper. Isinstance/`.value` checks use this; the typed
    ``Value`` factory below hides it behind a ``-> T`` signature."""

    def __init__(self, default: Any = None, *, default_factory: Any = None,
                 coerce: Any = None, help: Any = None, required: bool = False) -> None:
        self.value = default_factory() if default_factory is not None else default
        self.coerce = coerce
        self.required = required


# 1. explicit default -> field type is the default's type (T)
@overload
def Value(
    default: T,
    *,
    coerce: Callable[[str], Any] | str | None = ...,
    help: str | None = ...,
    required: bool = ...,
    default_factory: None = ...,
) -> T: ...


# 2. factory -> field type is the factory's return (T)
@overload
def Value(
    *,
    default_factory: Callable[[], T],
    coerce: Callable[[str], Any] | str | None = ...,
    help: str | None = ...,
    required: bool = ...,
) -> T: ...


# 3. required + no default -> no T to infer; type comes from the annotation.
#    Return Any so it is assignable to any declared field type, and (because
#    neither `default` nor `default_factory` is passed) the synthesized
#    __init__ makes the field a *required* parameter.
@overload
def Value(
    *,
    required: Literal[True],
    coerce: Callable[[str], Any] | str | None = ...,
    help: str | None = ...,
) -> Any: ...


def Value(default=None, *, default_factory=None, coerce=None, help=None,  # type: ignore[no-untyped-def]
          required=False):
    return _Value(default, default_factory=default_factory, coerce=coerce,
                  help=help, required=required)


def Flag(default: bool = False, *, help: str | None = ...) -> bool:  # type: ignore[no-untyped-def]
    return default


@dataclass_transform(field_specifiers=(Value, Flag), kw_only_default=True)
class MetaConfig(type):
    def __new__(mcls, name, bases, ns, **kw):  # type: ignore[no-untyped-def]
        return super().__new__(mcls, name, bases, ns)


class Config(metaclass=MetaConfig):
    pass
