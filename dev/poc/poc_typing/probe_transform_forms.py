from __future__ import annotations
import dataclasses
from typing import Any, dataclass_transform


# Control 1: stdlib dataclass (ty definitely supports this)
@dataclasses.dataclass
class D:
    x: int = 5


d = D(x='bad')  # EXPECT error: str -> int


# Form: decorator-function flavored dataclass_transform
@dataclass_transform()
def model(cls):
    return cls


@model
class E:
    y: int = 5


e = E(y='bad')  # EXPECT error if generic dataclass_transform supported
