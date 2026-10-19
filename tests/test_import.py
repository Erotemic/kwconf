def test_import():
    import kwconf

    assert hasattr(kwconf, 'Config')
    assert not hasattr(kwconf, 'DataConfig')


def test_dataconfig_module_does_not_reexport_dataconfig():
    import kwconf.dataconfig as dataconfig

    assert hasattr(dataconfig, 'Config')
    assert not hasattr(dataconfig, 'DataConfig')


def test_public_api_exports():
    """__all__ names must exist, and the documented extension point
    register_parser must be reachable from the top level."""
    import kwconf

    for name in kwconf.__all__:
        assert hasattr(kwconf, name), name
    assert kwconf.register_parser is not None


def test_mkinit_submodules_spec_matches_reality():
    """
    The mkinit __submodules__ spec must reference real submodules and cover
    exactly the names hand-imported in __init__ (regenerating with mkinit -w
    must not change the public API).
    """
    import importlib

    import kwconf

    spec_names = set()
    for modname, names in kwconf.__submodules__.items():
        importlib.import_module(f'kwconf.{modname}')
        assert names is not None, (
            f'kwconf.{modname} must declare an explicit export list'
        )
        spec_names.update(names)
    assert spec_names == set(kwconf.__all__)


def test_flat_core_import_stays_lean_in_fresh_python():
    """The flat Config path must not eagerly load fallback-only stacks."""
    import subprocess
    import sys
    from pathlib import Path

    repo_dpath = Path(__file__).resolve().parents[1]
    code = r"""
import sys
import kwconf

assert 'kwconf.config' not in sys.modules
assert 'kwconf.modal' not in sys.modules
assert 'kwconf.subconfig' not in sys.modules
assert 'argparse' not in sys.modules

kwconf.Config
kwconf.Value

class Demo(kwconf.Config):
    __default__ = {'value': kwconf.Value(0, type=int)}

Demo()

unexpected = {
    name for name in [
        'argparse',
        'typing',
        'ubelt',
        'inspect',
        'pprint',
        'textwrap',
        'json',
        'shlex',
        'kwconf._ingest',
        'kwconf.modal',
        'kwconf.dataconfig',
        'kwconf.subconfig',
        'kwconf.coerce',
        'kwconf._ubelt_repr_extension',
        'kwconf._config_cold',
        'kwconf._value_cold',
        'kwconf.util.util_yaml',
    ]
    if name in sys.modules
}
assert not unexpected, unexpected
"""
    subprocess.run(
        [sys.executable, '-S', '-c', code],
        cwd=repo_dpath,
        check=True,
    )
