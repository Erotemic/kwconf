"""
Proposed generic Value: these are all *correct* and should type-check CLEAN
(zero errors).
"""

from __future__ import annotations

from value_proposed import Config, Value


class Good(Config):
    a: int | None = Value(None)  # None is a valid int|None
    b: int = Value(10)  # int default for int field
    c: str = Value('hello')  # str default for str field
    d: list[int] = Value(
        default_factory=list
    )  # factory return assignable to list[int]
    e: int = Value(required=True)  # required, no default; type from annotation
    f: float = Value(1.5, coerce=str)  # explicit coerce override is allowed


# correct constructor kwargs
g1 = Good(a=5, b=2, c='y', e=1)
g2 = Good(a=None, b=0, c='z', e=7, d=[1, 2, 3])
