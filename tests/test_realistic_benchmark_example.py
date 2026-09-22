from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_DPATH = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_DPATH / 'examples' / '09_argparse_comparison.py'
BENCHMARK = REPO_DPATH / 'dev' / 'benchmarks' / 'realistic_cli_runtime.py'


def _load_example_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        '_kwconf_realistic_example_test', EXAMPLE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_realistic_example_default_invocation_parses_once(monkeypatch):
    module = _load_example_module()
    calls = []

    def fake_parse(argv):
        calls.append(list(argv))
        return {'ok': True}

    monkeypatch.setattr(module, 'parse_argparse', fake_parse)
    assert module.main(['argparse', '--_quiet']) == 0
    assert len(calls) == 1


def test_realistic_example_repeated_mode_keeps_one_warmup(monkeypatch):
    module = _load_example_module()
    calls = []

    def fake_parse(argv):
        calls.append(list(argv))
        return {'ok': True}

    monkeypatch.setattr(module, 'parse_argparse', fake_parse)
    assert module.main(['argparse', '--_repeat=3', '--_quiet']) == 0
    assert len(calls) == 4


def _run(backend: str):
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE), backend, '--_json'],
        cwd=REPO_DPATH,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_argparse_kwconf_realistic_example_output_parity():
    argparse_result = _run('argparse')['result']
    kwconf_result = _run('kwconf')['result']
    assert argparse_result == kwconf_result


def test_realistic_benchmark_cold_only(tmp_path):
    output = tmp_path / 'summary.json'
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    subprocess.run(
        [
            sys.executable,
            str(BENCHMARK),
            '--trials',
            '2',
            '--cold-only',
            '--output-json',
            str(output),
        ],
        cwd=REPO_DPATH,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    data = json.loads(output.read_text())
    assert data['cold_only'] is True
    assert data['cold_parses_per_process'] == 1
    assert data['output_parity'] is True
    assert 'warm_parse' not in data
    assert 'warm_kwconf_vs_argparse' not in data['ratios']
