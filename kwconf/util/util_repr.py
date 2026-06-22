"""
A minimal ``NiceRepr`` mixin vendored to keep kwconf dependency-free.

Reproduces the subset of ``ubelt.NiceRepr`` that kwconf uses: subclasses
define ``__nice__`` and get ``__str__`` / ``__repr__`` for free.
"""

from __future__ import annotations


class NiceRepr:
    """
    Inherit from this and define ``__nice__`` to get readable ``__str__`` and
    ``__repr__`` of the form ``<ClassName(nice)>`` and
    ``<ClassName(nice) at 0x...>``.
    """

    def __nice__(self) -> str:
        raise NotImplementedError(
            'Subclasses of NiceRepr must implement __nice__'
        )

    def __repr__(self) -> str:
        try:
            nice = self.__nice__()
        except NotImplementedError:
            return object.__repr__(self)
        return f'<{self.__class__.__name__}({nice}) at {hex(id(self))}>'

    def __str__(self) -> str:
        try:
            nice = self.__nice__()
        except NotImplementedError:
            return object.__str__(self)
        return f'<{self.__class__.__name__}({nice})>'
