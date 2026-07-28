"""
Proposed generic Value: every numbered line below SHOULD raise a checker
error. The comment records what we expect to be flagged.
"""

from __future__ import annotations

from value_proposed import Config, Value


class Bad(Config):
    # E1: None is not assignable to int  (this is `x: str = Value(None)` writ large)
    epochs: int = Value(None)

    # E2: int default is not assignable to str
    name: str = Value(3)

    # E3: factory returns list[str], not assignable to list[int]
    tags: list[int] = Value(default_factory=lambda: ['a', 'b'])


class Ok(Config):
    epochs: int = Value(10)
    name: str = Value('x')


# E4: str passed where the synthesized __init__ expects int
c1 = Ok(epochs='123')

# E5: unknown field
c2 = Ok(not_a_field=1)
