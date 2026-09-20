"""Compatibility tests for the lazy optional ubelt repr integration."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_DPATH = Path(__file__).resolve().parents[1]


def _run_fresh(code: str) -> None:
    ubelt = pytest.importorskip('ubelt')
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    # ``-S`` intentionally skips site initialization, so explicitly expose
    # the site-packages root that contains the already-importable ubelt.  This
    # preserves the clean-interpreter property without making installed
    # optional dependencies disappear inside the child process.
    ubelt_site = Path(ubelt.__file__).resolve().parent.parent
    pythonpath_parts = [str(REPO_DPATH), str(ubelt_site)]
    if old_pythonpath:
        pythonpath_parts.append(old_pythonpath)
    env['PYTHONPATH'] = os.pathsep.join(pythonpath_parts)
    proc = subprocess.run(
        [sys.executable, '-S', '-c', code],
        cwd=REPO_DPATH,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_ubelt_is_not_imported_by_flat_core_but_late_urepr_still_works():
    _run_fresh(
        r'''
import sys
import kwconf

class Demo(kwconf.Config):
    value: int = 1

cfg = Demo()
plain = repr(cfg)
assert 'ubelt' not in sys.modules
assert 'kwconf._ubelt_repr_extension' not in sys.modules

import ubelt as ub
first = ub.urepr(cfg, nl=0)
second = ub.urepr(cfg, nl=0)
assert first == "Demo(**{'value': 1})", first
assert second == first
assert repr(cfg) == plain
'''
    )


def test_ubelt_first_import_order_and_unrelated_config_typename_are_safe():
    _run_fresh(
        r'''
import ubelt as ub
import kwconf

class Demo(kwconf.Config):
    value: int = 1

assert ub.urepr(Demo(), nl=0) == "Demo(**{'value': 1})"

class Config:
    def __repr__(self):
        return 'UNRELATED_CONFIG'

# kwconf must not claim ubelt's global typename registry entry for every class
# named Config.
assert ub.urepr(Config()) == 'UNRELATED_CONFIG'
'''
    )
