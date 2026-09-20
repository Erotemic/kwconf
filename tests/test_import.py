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
    """The flat Config/Rust path must not eagerly load fallback-only stacks."""
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



def test_accelerated_flat_cli_does_not_load_cold_fallback_modules(tmp_path):
    """Exercise the direct lifecycle with a tiny protocol-compatible fake."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_dpath = Path(__file__).resolve().parents[1]
    package = tmp_path / '_kwconf_rust'
    package.mkdir()
    (package / '__init__.py').write_text(
        """
def backend_info():
    return ('kwconf-cli-core', 3)

class FlatParser:
    def __init__(self, specs):
        self.lookup = {}
        for index, (_key, spellings, _kind) in enumerate(specs):
            for spelling in spellings:
                self.lookup[spelling] = index

    def parse(self, argv):
        assignments = []
        unknown = []
        index = 0
        while index < len(argv):
            token = argv[index]
            if '=' in token:
                spelling, value = token.split('=', 1)
                field_index = self.lookup.get(spelling)
                if field_index is None:
                    unknown.append(token)
                else:
                    assignments.append((field_index, 0, (value, 0)))
                index += 1
                continue
            field_index = self.lookup.get(token)
            if field_index is None or index + 1 >= len(argv):
                unknown.append(token)
                index += 1
                continue
            assignments.append((field_index, 0, (argv[index + 1], 0)))
            index += 2
        return assignments, unknown, None
"""
    )
    code = r"""
import sys
import kwconf

class Demo(kwconf.Config):
    value: int = 0

result = Demo.cli(
    argv=['--value=7'], autocomplete=False, special_options=False
)
assert result.value == 7
unexpected = {
    name for name in [
        'argparse',
        'kwconf._config_cold',
        'kwconf._value_cold',
        'kwconf.argparse_ext',
        'kwconf.coerce',
        'kwconf.subconfig',
        'kwconf.util.util_text',
        'kwconf.util.util_yaml',
    ]
    if name in sys.modules
}
assert not unexpected, unexpected
"""
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join([str(tmp_path), str(repo_dpath)])
    proc = subprocess.run(
        [sys.executable, '-S', '-c', code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_accelerated_nested_cli_avoids_argparse_import(tmp_path):
    """Fixed realized SubConfig leaves stay off argparse on the Rust path."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo_dpath = Path(__file__).resolve().parents[1]
    package = tmp_path / '_kwconf_rust'
    package.mkdir()
    (package / '__init__.py').write_text(
        r'''
def backend_info():
    return ('kwconf-cli-core', 3)

class FlatParser:
    def __init__(self, specs):
        self.lookup = {}
        for index, (_key, spellings, _kind) in enumerate(specs):
            for spelling in spellings:
                self.lookup[spelling] = index

    def parse(self, argv):
        assignments = []
        unknown = []
        index = 0
        while index < len(argv):
            token = argv[index]
            if '=' in token:
                spelling, value = token.split('=', 1)
                field_index = self.lookup.get(spelling)
                if field_index is None:
                    unknown.append(token)
                else:
                    assignments.append((field_index, 0, (value, 0)))
                index += 1
                continue
            field_index = self.lookup.get(token)
            if field_index is None or index + 1 >= len(argv):
                unknown.append(token)
                index += 1
                continue
            assignments.append((field_index, 0, (argv[index + 1], 0)))
            index += 2
        return assignments, unknown, None
'''
    )
    code = r'''
import sys
import kwconf

class Inner(kwconf.Config):
    depth: int = 1

class Outer(kwconf.Config):
    inner = kwconf.SubConfig(Inner)

assert 'argparse' not in sys.modules
result = Outer.cli(
    argv=['--inner.depth=7'], autocomplete=False, special_options=False
)
assert result.inner.depth == 7
assert 'argparse' not in sys.modules, sorted(
    name for name in sys.modules if name == 'argparse' or name.startswith('argparse.')
)
'''
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join([str(tmp_path), str(repo_dpath)])
    proc = subprocess.run(
        [sys.executable, '-S', '-c', code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
