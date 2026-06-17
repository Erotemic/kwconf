"""Probe: which call shapes does pyright recognize as 'has a default'?
C() should be legal iff every field is treated as optional."""
from __future__ import annotations

from value_proposed import Config, Value


class C(Config):
    p: int = Value(5)                      # positional default
    q: int = Value(default=5)              # keyword default
    r: int = Value(5, coerce=str)          # positional default + extra kwarg
    s: int = Value(default_factory=lambda: 5)  # factory


c = C()  # if any field is seen as required, pyright reports it missing here
