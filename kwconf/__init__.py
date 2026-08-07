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

__version__ = '0.11.0'

__submodules__ = {
    'modal': ['ModalCLI', 'ModalValue'],
    'config': ['Config', 'ConfigValidationError', 'define'],
    'value': ['Value', 'Flag'],
    'dataconfig': ['dataconf'],
    'subconfig': ['SubConfig'],
    'coerce': ['register_parser'],
}

from . import diagnostics  # NOQA
from .modal import ModalCLI, ModalValue
from .config import (
    Config,
    ConfigValidationError,
    define,
)

# Value / Flag are factory FUNCTIONS defined in kwconf.value (typed to
# return the field value type T).
from .value import Value, Flag
from .dataconfig import (
    dataconf,
)
from .subconfig import (
    SubConfig,
)
from .coerce import (
    register_parser,
)

__all__ = [
    'Config',
    'ConfigValidationError',
    'Value',
    'Flag',
    'dataconf',
    'define',
    'ModalCLI',
    'ModalValue',
    'SubConfig',
    'register_parser',
]
