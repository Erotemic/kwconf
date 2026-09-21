from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_DPATH = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = REPO_DPATH / 'dev' / 'benchmarks' / 'cold_start_breakdown.py'


def _load_module():
    spec = importlib.util.spec_from_file_location(
        'kwconf_cold_start_breakdown_test', BENCHMARK_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_scripts_measure_definition_and_parse():
    module = _load_module()
    argparse_text = module._script_text('argparse', 2)
    python_text = module._script_text('kwconf_python', 2)
    rust_text = module._script_text('kwconf_rust', 2)

    assert '_definition_start = _clock()' in argparse_text
    assert 'parser.parse_args()' in argparse_text
    assert "__cli_backend__ = 'python'" in python_text
    assert "__cli_backend__ = 'rust'" in rust_text
    assert module.MARKER in rust_text


def test_argparse_cold_breakdown_smoke(tmp_path):
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
            '--schema-sizes',
            '1',
            '--methods',
            'argparse',
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
    assert set(data['profiles']) == {'default', 'no_site'}
    for profile in data['profiles'].values():
        case = profile['cases'][0]
        assert case['schema_size'] == 1
        assert 'python_baseline' in case['methods']
        assert 'argparse' in case['methods']
        row = case['methods']['argparse']
        assert row['total_ns']['median_ns'] > 0
        assert row['definition_ns']['median_ns'] > 0
        assert row['parse_ns']['median_ns'] > 0
    assert raw.exists()
