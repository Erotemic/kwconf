from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import kwconf

REPO_DPATH = Path(__file__).resolve().parents[1]


def test_python_backend_does_not_import_rust_extension():
    code = r'''
import sys
import kwconf
class C(kwconf.Config):
    __cli_backend__ = 'python'
    value: int = 0
assert '_kwconf_rust' not in sys.modules
result = C.cli(argv=['--value=3'], autocomplete=False, special_options=False)
assert result['value'] == 3
assert '_kwconf_rust' not in sys.modules
'''
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_DPATH,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_auto_backend_falls_back_when_extension_is_missing(monkeypatch):
    from kwconf import config as config_mod

    monkeypatch.setattr(config_mod, '_RUST_EXTENSION_PROBE', False)
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION', None)
    monkeypatch.setattr(
        config_mod, '_RUST_EXTENSION_ERROR', 'test: extension unavailable'
    )

    class C(kwconf.Config):
        __cli_backend__ = 'auto'
        value: int = 0

    result = C.cli(
        argv=['--value=3'], autocomplete=False, special_options=False
    )
    assert result['value'] == 3


def test_default_backend_is_auto_and_falls_back_when_missing(monkeypatch):
    from kwconf import config as config_mod

    monkeypatch.setattr(config_mod, '_RUST_EXTENSION_PROBE', False)

    class C(kwconf.Config):
        value: int = 0

    assert C.__cli_backend__ == 'auto'
    result = C.cli(
        argv=['--value=4'], autocomplete=False, special_options=False
    )
    assert result['value'] == 4


def test_invalid_backend_name_is_rejected():
    class C(kwconf.Config):
        __cli_backend__ = 'wat'
        value: int = 0

    with pytest.raises(ValueError, match='__cli_backend__'):
        C.cli(argv=['--value=3'], autocomplete=False, special_options=False)


def _require_extension():
    return pytest.importorskip('_kwconf_rust')


def test_rust_backend_matches_common_flat_cli_cases():
    _require_extension()

    class C(kwconf.Config):
        number: int = 0
        label: str = ''
        flag = kwconf.Value(
            False, isflag=True, alias=['enabled'], short_alias=['f']
        )
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
        maybe = kwconf.Value('default', bare='BARE', short_alias=['m'])

    cases = [
        [],
        ['--number=3'],
        ['--number', '3', '--label=hello'],
        ['--flag'],
        ['--no-flag'],
        ['--flag=0'],
        ['--no-flag=0'],
        ['--enabled'],
        ['-f'],
        ['-vvv'],
        ['-vvv=5'],
        ['--verbose=3', '--verbose', '--verbose'],
        ['--maybe'],
        ['--maybe=value'],
        ['-m=value'],
        ['--number=1', '--number=2'],
    ]
    for argv in cases:
        C.__cli_backend__ = 'python'
        want = dict(
            C.cli(argv=argv, autocomplete=False, special_options=False)
        )
        C.__cli_backend__ = 'rust'
        got = dict(C.cli(argv=argv, autocomplete=False, special_options=False))
        assert got == want, argv


def test_rust_backend_falls_back_for_abbreviation_and_nargs():
    _require_extension()

    class Abbrev(kwconf.Config):
        number: int = 0

    Abbrev.__cli_backend__ = 'rust'
    result = Abbrev.cli(
        argv=['--num=4'], autocomplete=False, special_options=False
    )
    assert result['number'] == 4

    class Multi(kwconf.Config):
        values = kwconf.Value([], nargs='+')

    Multi.__cli_backend__ = 'rust'
    result = Multi.cli(
        argv=['--values', 'a', 'b'], autocomplete=False, special_options=False
    )
    assert result['values'] == ['a', 'b']


def test_rust_backend_falls_back_when_short_clusters_are_disabled():
    _require_extension()

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        __short_alias_clusters__ = False
        force = kwconf.Flag(False, short_alias=['f'])
        verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])

    # Native argparse semantics treat the remainder as -f's optional value.
    result = C.cli(
        argv=['-fv'], autocomplete=False, special_options=False
    )
    assert result.force == 'v'
    assert result.verbose == 0


def test_environment_can_opt_in_to_rust(monkeypatch):
    _require_extension()

    class C(kwconf.Config):
        value: int = 0

    monkeypatch.setenv('KWCONF_CLI_BACKEND', 'rust')
    result = C.cli(
        argv=['--value=9'], autocomplete=False, special_options=False
    )
    assert result['value'] == 9


@pytest.mark.parametrize('backend', ['python', 'rust', 'auto'])
def test_rust_backend_preserves_required_semantics(backend):
    if backend != 'python':
        _require_extension()

    class C(kwconf.Config):
        __cli_backend__ = backend
        value = kwconf.Value('', parser=str, required=True)

    got = C.cli(
        argv=['--value=ok'], autocomplete=False, special_options=False
    )
    assert got.value == 'ok'

    # ``required`` is a kwconf provenance invariant, not argparse's
    # ``required=True`` option flag.  The canonical Python backend raises this
    # ValueError after parsing; Rust/auto must preserve that exact contract.
    with pytest.raises(ValueError, match="Required variable 'value' was not given"):
        C.cli(argv=[], autocomplete=False, special_options=False)


def test_auto_backend_avoids_argparse_on_supported_fast_path():
    _require_extension()

    code = r"""
import sys
import kwconf
class C(kwconf.Config):
    value = kwconf.Value('', parser=str)
result = C.cli(argv=['--value=ok'], autocomplete=False, special_options=False)
assert result.value == 'ok'
assert 'argparse' not in sys.modules, sorted(k for k in sys.modules if 'argparse' in k)
assert 'kwconf.argparse_ext' not in sys.modules
"""
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_DPATH,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_rust_backend_delegates_help_to_argparse(capsys):
    _require_extension()

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        value = kwconf.Value('', parser=str, help='demo value')

    with pytest.raises(SystemExit) as ex:
        C.cli(argv=['--help'], autocomplete=False, special_options=False)
    assert ex.value.code == 0
    captured = capsys.readouterr()
    assert '--value' in captured.out
    assert 'demo value' in captured.out


def test_rust_backend_delegates_end_of_options_semantics():
    _require_extension()

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        value = kwconf.Value('', parser=str)

    with pytest.raises(SystemExit):
        C.cli(
            argv=['--', '--value=not-an-option'],
            autocomplete=False,
            special_options=False,
        )


def test_active_argcomplete_session_keeps_real_argparse(monkeypatch):
    import types

    seen = []
    fake_argcomplete = types.SimpleNamespace(
        autocomplete=lambda parser: seen.append(parser)
    )
    monkeypatch.setitem(sys.modules, 'argcomplete', fake_argcomplete)
    monkeypatch.setenv('_ARGCOMPLETE', '1')

    class C(kwconf.Config):
        value = kwconf.Value('', parser=str)

    got = C.cli(argv=['--value=ok'], autocomplete='auto', special_options=False)
    assert got.value == 'ok'
    assert len(seen) == 1
    import argparse

    assert isinstance(seen[0], argparse.ArgumentParser)


def test_rust_bridge_rejects_protocol_mismatch(monkeypatch):
    import types

    from kwconf import _rust

    fake = types.SimpleNamespace(
        backend_info=lambda: ('kwconf-cli-core', 999),
    )
    monkeypatch.setitem(sys.modules, '_kwconf_rust', fake)
    monkeypatch.setattr(_rust, '_EXTENSION', None)
    monkeypatch.setattr(_rust, '_EXTENSION_TRIED', False)
    monkeypatch.setattr(_rust, '_EXTENSION_ERROR', None)

    assert _rust.extension_available() is False
    status = _rust.backend_status()
    assert status['extension_available'] is False
    assert 'protocol mismatch' in status['extension_error']

    with pytest.raises(ImportError, match='protocol mismatch'):
        _rust._load_extension(required=True)


def test_backend_status_uses_class_local_cache_records(monkeypatch):
    from kwconf import _rust

    # This regression test is extension-independent. The cache was moved from
    # weak dictionaries onto Config classes; backend_status must inspect the
    # same storage rather than referring to the deleted dictionaries.
    monkeypatch.setattr(_rust, '_EXTENSION', None)
    monkeypatch.setattr(_rust, '_EXTENSION_TRIED', True)
    monkeypatch.setattr(_rust, '_EXTENSION_ERROR', 'test: extension unavailable')

    class C(kwconf.Config):
        value: int = 0

    status = _rust.backend_status(C())
    assert status['class_cached'] is False
    assert status['class_unsupported_reason'] is None
    assert status['protocol'] == ('kwconf-cli-core', 3)



def test_rust_schema_rejects_user_callback_before_extension_load(monkeypatch):
    """A fallback must not speculatively execute arbitrary user code."""
    from kwconf import _rust

    calls = []

    def custom_parser(text):
        calls.append(text)
        return text.upper()

    class C(kwconf.Config):
        value = kwconf.Value('', parser=custom_parser)

    # Schema inspection happens before the binary is needed and conservatively
    # declines the callback. This is what prevents callback replay on fallback.
    with pytest.raises(_rust.UnsupportedSchema, match='custom parser callable'):
        _rust._schema_description(C())
    assert calls == []


def test_rust_schema_rejects_nonprimitive_choices():
    from kwconf import _rust

    class Choice:
        pass

    choice = Choice()

    class C(kwconf.Config):
        value = kwconf.Value(choice, choices=[choice])

    with pytest.raises(_rust.UnsupportedSchema, match='non-primitive choices'):
        _rust._schema_description(C())


def test_rust_fallback_invokes_custom_parser_once():
    _require_extension()
    calls = []

    def custom_parser(text):
        calls.append(text)
        return text.upper()

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        value = kwconf.Value('', parser=custom_parser)

    got = C.cli(
        argv=['--value=hello'], autocomplete=False, special_options=False
    )
    assert got.value == 'HELLO'
    assert calls == ['hello']


def test_rust_build_helper_requires_abi3_wheel():
    import importlib.util

    helper_fpath = REPO_DPATH / 'dev' / 'rust_backend' / 'build_backend.py'
    spec = importlib.util.spec_from_file_location(
        'kwconf_test_build_backend', helper_fpath
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    module._assert_abi3_wheel(
        Path('kwconf_rust-0.12.1-cp310-abi3-manylinux_x86_64.whl')
    )
    with pytest.raises(SystemExit, match='non-abi3'):
        module._assert_abi3_wheel(
            Path('kwconf_rust-0.12.1-cp313-cp313-manylinux_x86_64.whl')
        )


def test_direct_rust_cli_skips_generic_load(monkeypatch):
    """The common flat success path should stay inside config.py."""
    from kwconf import config as config_mod

    calls = []
    compiled = object()

    def fake_parse(config, got_compiled, argv, *, strict):
        assert got_compiled is compiled
        calls.append((tuple(argv), dict(config._data)))
        return {'value': 7}, frozenset({'value'}), ()

    def fail_load(*args, **kwargs):
        raise AssertionError('generic load path should not run')

    monkeypatch.setattr(
        config_mod, '_load_direct_rust_extension', lambda **kw: object()
    )
    monkeypatch.setattr(
        config_mod, '_direct_rust_compile', lambda *a, **kw: compiled
    )
    monkeypatch.setattr(config_mod, '_direct_rust_parse', fake_parse)
    monkeypatch.setattr(kwconf.Config, '_load', fail_load)

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        value: int = 0

    got = C.cli(
        argv=['--value=7'], autocomplete=False, special_options=False
    )
    assert got.value == 7
    # One side-effect-free eligibility parse, then one parse after the
    # canonical default reset so counter/default-factory semantics match load.
    assert len(calls) == 2
    assert got._explicit_argv_keys == frozenset({'value'})
    assert got._provided_keys == frozenset({'value'})


def test_direct_rust_cli_preserves_default_factory_reset_semantics(monkeypatch):
    from kwconf import config as config_mod

    factory_calls = []

    def factory():
        factory_calls.append(len(factory_calls))
        return []

    compiled = object()

    def fake_parse(config, got_compiled, argv, *, strict):
        assert got_compiled is compiled
        return {}, frozenset(), ()

    monkeypatch.setattr(
        config_mod, '_load_direct_rust_extension', lambda **kw: object()
    )
    monkeypatch.setattr(
        config_mod, '_direct_rust_compile', lambda *a, **kw: compiled
    )
    monkeypatch.setattr(config_mod, '_direct_rust_parse', fake_parse)

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        payload = kwconf.Value(default_factory=factory)

    got = C.cli(argv=[], autocomplete=False, special_options=False)
    # Config construction materializes once and load(_reset=True) semantics
    # materialize a second time. The accelerated path must preserve that.
    assert factory_calls == [0, 1]
    assert got.payload == []


def test_direct_rust_cli_miss_is_side_effect_free_before_fallback(monkeypatch):
    from kwconf import _rust
    from kwconf import config as config_mod

    factory_calls = []

    def factory():
        factory_calls.append(len(factory_calls))
        return []

    monkeypatch.setattr(
        config_mod, '_load_direct_rust_extension', lambda **kw: object()
    )
    monkeypatch.setattr(config_mod, '_direct_rust_compile', lambda *a, **kw: None)
    monkeypatch.setattr(_rust, 'try_compile_config', lambda *a, **kw: None)

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        payload = kwconf.Value(default_factory=factory)

    got = C.cli(argv=[], autocomplete=False, special_options=False)
    # The failed eligibility probe must not add another reset before the
    # canonical Python/argparse fallback performs its normal reset.
    assert factory_calls == [0, 1]
    assert got.payload == []


def test_common_rust_cli_does_not_import_python_bridge():
    _require_extension()

    code = r"""
import sys
import kwconf
class C(kwconf.Config):
    __cli_backend__ = 'rust'
    value: int = 0
result = C.cli(argv=['--value=3'], autocomplete=False, special_options=False)
assert result.value == 3
assert 'kwconf._rust' not in sys.modules
assert 'argparse' not in sys.modules
assert 'kwconf.argparse_ext' not in sys.modules
"""
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_DPATH,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_direct_rust_cache_clear_tracks_bridge_clear_cache():
    _require_extension()
    from kwconf import _rust
    from kwconf import config as config_mod

    class C(kwconf.Config):
        __cli_backend__ = 'rust'
        value: int = 0

    got = C.cli(argv=['--value=5'], autocomplete=False, special_options=False)
    assert got.value == 5
    assert config_mod._direct_rust_class_cached(C)

    _rust.clear_cache()
    assert not config_mod._direct_rust_class_cached(C)


def test_direct_rust_protocol_mismatch_is_safe(monkeypatch):
    import types

    from kwconf import config as config_mod

    fake = types.SimpleNamespace(backend_info=lambda: ('kwconf-cli-core', 999))
    monkeypatch.setitem(sys.modules, '_kwconf_rust', fake)
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION_PROBE', None)
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION', None)
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION_ERROR', None)

    class Auto(kwconf.Config):
        __cli_backend__ = 'auto'
        value: int = 0

    # Auto mode treats a stale accelerator like a missing optional wheel.
    got = Auto.cli(argv=['--value=6'], autocomplete=False, special_options=False)
    assert got.value == 6

    # Explicit rust mode reports the incompatibility instead of using unsafe FFI.
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION_PROBE', None)
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION', None)
    monkeypatch.setattr(config_mod, '_RUST_EXTENSION_ERROR', None)

    class Explicit(kwconf.Config):
        __cli_backend__ = 'rust'
        value: int = 0

    with pytest.raises(ImportError, match='protocol mismatch'):
        Explicit.cli(argv=['--value=6'], autocomplete=False, special_options=False)
