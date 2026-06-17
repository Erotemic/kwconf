from __future__ import annotations
from typing import Any, TypeVar, dataclass_transform

T = TypeVar("T")
def Value(*, default: T = ..., help: str | None = ...) -> T: ...  # type: ignore

@dataclass_transform(field_specifiers=(Value,), kw_only_default=True)
class Config:
    # kwconf defines this explicitly (config.py:485). Does it suppress
    # the transform-synthesized __init__?
    def __init__(self, *args: Any, **kwargs: Any) -> None: ...

class Train(Config):
    epochs: int = Value(default=10)

bad = Train(epochs="not-int")   # if synthesis is suppressed, NO error here
