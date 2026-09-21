from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_DPATH = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_DPATH / 'dev' / 'benchmarks' / 'cold_backend_phases.py'


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'kwconf_cold_backend_phases_test', BENCHMARK_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_backend_phase_scripts_are_explicit():
    module = _load_module()
    argparse_text = module._script_text('argparse', 2)
    python_text = module._script_text('kwconf_python', 2)
    rust_text = module._script_text('kwconf_rust', 2)

    assert 'parser = argparse.ArgumentParser' in argparse_text
    assert '_api_start = _api_end' in argparse_text
    assert '_backend_start = _backend_end' in argparse_text
    assert '_Config = kwconf.Config' in python_text
    assert 'class CLI(_Config):' in python_text
    assert '_cfg._argparse(special_options=False)' in python_text
    assert '_argparse_ext.parse_result' in python_text
    assert '_rust_mod._load_extension(required=True)' in rust_text
    assert '_rust_mod._schema_description(_cfg)' in rust_text
    assert '_extension.FlatParser(_specs)' in rust_text
    assert '_rust_mod.parse_compiled' in rust_text
    assert '_cfg._reset_data_from_defaults' in rust_text
    assert module.MARKER in rust_text


def test_cold_backend_phase_smoke_without_rust(tmp_path):
    output = tmp_path / 'summary.json'
    raw = tmp_path / 'trials.csv'
    scripts = tmp_path / 'scripts'
    subprocess.run(
        [
            sys.executable,
            str(BENCHMARK_PATH),
            '--trials',
            '2',
            '--no-site-trials',
            '2',
            '--schema-size',
            '2',
            '--methods',
            'argparse,kwconf_python',
            '--profiles',
            'default',
            '--output-json',
            str(output),
            '--raw-output',
            str(raw),
            '--script-dir',
            str(scripts),
        ],
        cwd=REPO_DPATH,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    data = json.loads(output.read_text())
    assert data['schema_size'] == 2
    methods = data['profiles']['default']['methods']
    assert methods['argparse']['definition_ns']['median_ns'] > 0
    assert methods['argparse']['parse_ns']['median_ns'] > 0
    assert methods['argparse']['backend_ns']['median_ns'] == 0
    assert methods['kwconf_python']['api_ns']['median_ns'] > 0
    assert methods['kwconf_python']['definition_ns']['median_ns'] > 0
    assert methods['kwconf_python']['instance_ns']['median_ns'] > 0
    assert methods['kwconf_python']['backend_ns']['median_ns'] > 0
    assert methods['kwconf_python']['parse_ns']['median_ns'] > 0
    assert raw.exists()
