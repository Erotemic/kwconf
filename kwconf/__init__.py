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


    config = MyConfig.cli(argv=False, data={'x': 3})
    assert config.x == 3

`Value(...)` remains the place for CLI metadata such as help text, aliases,
choices, flags, and positional behavior. `DataConfig` is still available during
the transition, but `Config` is the future-facing entry point.
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
}

from . import diagnostics  # NOQA
from .modal import (ModalCLI, ModalValue)
from .config import (Config, LegacyConfig, define,)
from .value import (Path, PathList, Value, Flag)
from .cli import (quick_cli,)
from .dataconfig import (DataConfig, dataconf,)
from .subconfig import (SubConfig,)

__all__ = ['Config', 'LegacyConfig', 'DataConfig', 'Path', 'PathList',
           'Value', 'dataconf', 'define', 'quick_cli', 'Flag', 'ModalCLI',
           'ModalValue', 'SubConfig']
