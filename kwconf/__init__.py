"""
kwconf
======

`kwconf` is an experimental successor to `scriptconfig` that keeps the
high-value CLI and config-file features while moving toward a simpler typed
configuration model.

Preferred usage:

.. code:: python

    import kwconf as kw


    class MyConfig(kw.Config):
        x: int = 1
        y: str = 'foo'
        tags: list[str] = kw.Value(default_factory=list)


    config = MyConfig.cli(argv=['--x=3'])
    assert config.x == 3

`Value(...)` remains the place for CLI metadata such as help text, aliases,
choices, flags, and positional behavior.
"""

__autogen__ = """
Ignore:
    mkinit ~/code/kwconf/kwconf/__init__.py --nomods --relative --diff
    mkinit ~/code/kwconf/kwconf/__init__.py --nomods --relative -w
"""

__version__ = '0.9.2'

__submodules__ = {
    'modal': None,
    'config': None,
    'value': None,
    'cli': None,
    'dataconfig': None,
    'annotations': None,
}

from typing import Any, TypeVar, overload

from . import diagnostics  # NOQA
from .modal import (ModalCLI, ModalValue)
from .config import (Config, define,)
from .value import Value as ValueClass, Flag as FlagClass
from .dataconfig import (dataconf,)
from .subconfig import (SubConfig,)

_T = TypeVar('_T')


# The runtime field-metadata wrappers live in ``kwconf.value`` as classes. The
# PUBLIC ``kwconf.Value`` / ``kwconf.Flag`` are thin factory *functions* typed to
# return the field's value type ``T`` (the attrs ``field()`` pattern), so that
# ``x: int = Value(None)`` is a static type error and ``cfg.x`` reads as ``int``.
# Internals keep using the classes directly via ``from kwconf.value import
# Value`` (isinstance / attribute access unaffected); ``kwconf.value.Value`` (or
# ``kwconf.ValueClass``) remains the class for anyone who needs it.
# When a default is given positionally, the field is typed as that value's
# type ``T`` (so ``x: int = Value(None)`` is an error). Any other call shape
# (keyword-only metadata, ``default_factory=``, ``required=``) types as ``Any``.
@overload
def Value(default: _T, /, *args: Any, **kwargs: Any) -> _T: ...
@overload
def Value(**kwargs: Any) -> Any: ...
def Value(*args: Any, **kwargs: Any) -> Any:
    """
    Declare a config field with metadata (help, aliases, choices, ``coerce``,
    flags, positional behavior). Returns a :class:`kwconf.value.Value` instance
    at runtime, but is typed as the field's value type so that a positional
    default is checked against the field annotation. See
    :class:`kwconf.value.Value` for the full set of accepted arguments.
    """
    return ValueClass(*args, **kwargs)


@overload
def Flag(default: bool, /, *args: Any, **kwargs: Any) -> bool: ...
@overload
def Flag(**kwargs: Any) -> Any: ...
def Flag(*args: Any, **kwargs: Any) -> Any:
    """Boolean flag field; like :func:`Value` but with flag semantics."""
    return FlagClass(*args, **kwargs)

__all__ = ['Config', 'Value', 'Flag',
           'dataconf', 'define', 'ModalCLI', 'ModalValue', 'SubConfig']
