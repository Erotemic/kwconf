"""
POC: a minimal stand-in for kwconf's *current* Value + Config typing.

The point of this file is to reproduce, in isolation, what the real package
does today:

  * ``MetaConfig`` is decorated with ``dataclass_transform(field_specifiers=...)``
  * ``Value.__init__`` accepts ``default: Any``

With ``default: Any`` the type checker has nothing to validate the default
against, so mistakes like ``x: int = Value(None)`` are silently accepted.
See ``check_current_gap.py``.
"""
from __future__ import annotations

from typing import Any, Callable, dataclass_transform


class Value:
    # Mirrors kwconf/value.py today: default is untyped.
    def __init__(
        self,
        default: Any = None,
        type: Any = None,
        help: str | None = None,
        *,
        default_factory: Callable[[], Any] | None = None,
        required: bool = False,
    ) -> None:
        self.value = default


class Flag(Value):
    def __init__(self, default: Any = False, **kwargs: Any) -> None:
        super().__init__(default=default, **kwargs)


@dataclass_transform(field_specifiers=(Value, Flag))
class MetaConfig(type):
    def __new__(mcls, name, bases, ns, **kw):  # type: ignore[no-untyped-def]
        return super().__new__(mcls, name, bases, ns)


class Config(metaclass=MetaConfig):
    pass
