from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_DPATH = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_DPATH / 'examples' / '09_argparse_comparison.py'


def _run(backend: str):
    env = os.environ.copy()
    env['KWCONF_CLI_BACKEND'] = 'python'
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
