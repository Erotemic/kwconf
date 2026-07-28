"""
Demonstrates the GAP in today's typing: with ``default: Any`` none of these
mistakes are caught. A type checker run over this file should report
*zero* errors -- which is exactly the problem.
"""

from __future__ import annotations

from value_current import Config, Value


class Today(Config):
    epochs: int = Value(
        None
    )  # WANT error (None is not int) -- NOT caught today
    name: str = Value(3)  # WANT error (int is not str)  -- NOT caught today


# WANT error (str passed where int expected) -- NOT caught today
cfg = Today(epochs='not-an-int')
