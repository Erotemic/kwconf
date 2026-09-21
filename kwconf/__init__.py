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

__version__ = '0.12.1'

__submodules__ = {
    'modal': ['ModalCLI', 'ModalValue'],
    'config': ['Config', 'ConfigValidationError', 'define'],
    'value': ['Value', 'Flag'],
    'dataconfig': ['dataconf'],
    'subconfig': ['SubConfig'],
    'coerce': ['register_parser'],
}

# Keep the package import cheap.  CLI programs almost always need Config and
# Value, but they should not pay to import modal/dataconfig/subconfig/coerce
# merely because those names are part of kwconf's top-level API.  PEP 562
# module __getattr__ preserves the public spelling while importing each owner
# only on first access.
_LAZY_ATTRS = {
    'Config': ('config', 'Config'),
    'ConfigValidationError': ('config', 'ConfigValidationError'),
    'define': ('config', 'define'),
    'Value': ('value', 'Value'),
    'Flag': ('value', 'Flag'),
    'ModalCLI': ('modal', 'ModalCLI'),
    'ModalValue': ('modal', 'ModalValue'),
    'dataconf': ('dataconfig', 'dataconf'),
    'SubConfig': ('subconfig', 'SubConfig'),
    'register_parser': ('coerce', 'register_parser'),
}

# Submodules that callers historically get as attributes after importing the
# package are also resolved lazily.  This matters for internal imports such as
# ``from kwconf import diagnostics`` and preserves ``kwconf.modal`` style use.
_LAZY_MODULES = {
    'annotations',
    'argparse_ext',
    'coerce',
    'config',
    'dataconfig',
    'diagnostics',
    'modal',
    'subconfig',
    'value',
    '_ingest',
    '_rust',
    '_ubelt_repr_extension',
}


def __getattr__(name):
    if name in _LAZY_ATTRS:
        module_name, attr_name = _LAZY_ATTRS[name]
        module = __import__(
            f'{__name__}.{module_name}', fromlist=[attr_name]
        )
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    if name in _LAZY_MODULES:
        module = __import__(f'{__name__}.{name}', fromlist=[name])
        globals()[name] = module
        return module
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def __dir__():
    return sorted(set(globals()) | set(__all__) | _LAZY_MODULES)


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
