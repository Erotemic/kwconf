"""Optional integration parity for argcomplete and rich-argparse.

These tests skip cleanly when the optional ecosystem packages or compiled
accelerator are absent.  The evidence-bundle runner builds the accelerator
first, so a developer/release machine with those extras installed exercises
them end to end.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_DPATH = Path(__file__).resolve().parents[1]


def _have(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _extension_available() -> bool:
    return importlib.util.find_spec('_kwconf_rust') is not None


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    old = env.get('PYTHONPATH')
    env['PYTHONPATH'] = str(REPO_DPATH) if not old else str(REPO_DPATH) + os.pathsep + old
    return env


def _completion_output(
    tmp_path: Path,
    backend: str,
    line: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> bytes:
    (tmp_path / 'completion-fixture.txt').write_text('fixture\n')
    output = tmp_path.parent / f'{tmp_path.name}-completion-{backend}.txt'
    output.unlink(missing_ok=True)
    code = f'''\
import kwconf
class CLI(kwconf.Config):
    __cli_backend__ = {backend!r}
    mode = kwconf.Value('a', choices=['a', 'b'], help='run mode')
    path: str = ''
CLI.cli(autocomplete='auto', special_options=False)
'''
    env = _base_env()
    env.update(
        {
            '_ARGCOMPLETE': '1',
            'COMP_LINE': line,
            'COMP_POINT': str(len(line)),
            '_ARGCOMPLETE_STDOUT_FILENAME': str(output),
        }
    )
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors='replace')
    return output.read_bytes()


def _modal_completion_output(
    tmp_path: Path,
    backend: str,
    line: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> bytes:
    output = tmp_path.parent / f'{tmp_path.name}-modal-completion-{backend}.txt'
    output.unlink(missing_ok=True)
    code = f'''\
import kwconf
class Train(kwconf.Config):
    __command__ = 'train_model'
    __cli_backend__ = {backend!r}
    lr = kwconf.Value(0.1, choices=[0.1, 0.2], help='learning rate')
    @classmethod
    def main(cls, argv=None, **kwargs):
        return 0
class Evaluate(kwconf.Config):
    __command__ = 'evaluate'
    __cli_backend__ = {backend!r}
    @classmethod
    def main(cls, argv=None, **kwargs):
        return 0
class Root(kwconf.ModalCLI):
    __cli_backend__ = {backend!r}
    __subconfigs__ = [Train, Evaluate]
Root.main(autocomplete='auto')
'''
    env = _base_env()
    env.update(
        {
            '_ARGCOMPLETE': '1',
            'COMP_LINE': line,
            'COMP_POINT': str(len(line)),
            '_ARGCOMPLETE_STDOUT_FILENAME': str(output),
        }
    )
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors='replace')
    return output.read_bytes()


@pytest.mark.skipif(not _have('argcomplete'), reason='argcomplete is optional')
@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
@pytest.mark.parametrize(
    'line',
    [
        'prog --mo',
        'prog --mode b',
        # '=' is a shell word break. The Rust protocol layer deliberately
        # delegates it so argcomplete remains byte-for-byte authoritative.
        'prog --mode=b',
        # No finite choices: the Rust completion layer must delegate this value
        # position to canonical argcomplete (normally filesystem completion).
        'prog --path completion-fi',
    ],
)
def test_argcomplete_exact_output_parity(tmp_path, line):
    python = _completion_output(tmp_path, 'python', line)
    rust = _completion_output(tmp_path, 'rust', line)
    auto = _completion_output(tmp_path, 'auto', line)
    assert rust == python
    assert auto == python


@pytest.mark.skipif(not _have('argcomplete'), reason='argcomplete is optional')
@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
def test_argcomplete_suppress_space_exact_output_parity(tmp_path):
    extra = {'_ARGCOMPLETE_SUPPRESS_SPACE': '1'}
    python = _completion_output(tmp_path, 'python', 'prog --mo', extra_env=extra)
    rust = _completion_output(tmp_path, 'rust', 'prog --mo', extra_env=extra)
    auto = _completion_output(tmp_path, 'auto', 'prog --mo', extra_env=extra)
    assert rust == python
    assert auto == python


@pytest.mark.skipif(not _have('argcomplete'), reason='argcomplete is optional')
@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
@pytest.mark.parametrize(
    'line',
    [
        'prog tr',
        'prog train-model --l',
        'prog train-model --lr 0',
    ],
)
def test_modal_argcomplete_exact_output_parity(tmp_path, line):
    python = _modal_completion_output(tmp_path, 'python', line)
    rust = _modal_completion_output(tmp_path, 'rust', line)
    auto = _modal_completion_output(tmp_path, 'auto', line)
    assert rust == python
    assert auto == python


@pytest.mark.skipif(not _have('argcomplete'), reason='argcomplete is optional')
@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
@pytest.mark.parametrize(
    'extra_env',
    [
        {'_ARGCOMPLETE_SHELL': 'zsh'},
        {'_ARGCOMPLETE_SHELL': 'fish'},
        {
            '_ARGCOMPLETE_SHELL': 'powershell',
            '_ARGCOMPLETE_IFS': '\n',
            '_ARGCOMPLETE_SUPPRESS_SPACE': '0',
        },
        {'_ARGCOMPLETE_DFS': ':'},
    ],
)
def test_descriptive_argcomplete_protocol_exact_output_parity(tmp_path, extra_env):
    python = _completion_output(
        tmp_path,
        'python',
        'prog --mo',
        extra_env=extra_env,
    )
    rust = _completion_output(
        tmp_path,
        'rust',
        'prog --mo',
        extra_env=extra_env,
    )
    auto = _completion_output(
        tmp_path,
        'auto',
        'prog --mo',
        extra_env=extra_env,
    )
    assert rust == python
    assert auto == python


def _help_output(
    backend: str,
    *,
    force_color: bool,
    use_rich: bool = False,
) -> bytes:
    code = f'''\
import kwconf
class CLI(kwconf.Config):
    __cli_backend__ = {backend!r}
    count: int = kwconf.Value(1, help='number of items')
    mode = kwconf.Value('a', choices=['a', 'b'], help='run mode')
CLI.cli(argv=['--help'], autocomplete=False, special_options=False)
'''
    env = _base_env()
    if force_color:
        env['FORCE_COLOR'] = '1'
        env['TERM'] = 'xterm-256color'
        env.pop('KWCONF_NORICH', None)
    elif use_rich:
        env.pop('KWCONF_NORICH', None)
        env.pop('FORCE_COLOR', None)
    else:
        env['KWCONF_NORICH'] = '1'
        env.pop('FORCE_COLOR', None)
    proc = subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_DPATH,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors='replace')
    return proc.stdout


@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
def test_plain_help_exact_backend_parity():
    python = _help_output('python', force_color=False)
    assert _help_output('rust', force_color=False) == python
    assert _help_output('auto', force_color=False) == python


@pytest.mark.skipif(not _have('rich_argparse'), reason='rich-argparse is optional')
@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
def test_rich_help_color_exact_backend_parity():
    python = _help_output('python', force_color=True)
    assert _help_output('rust', force_color=True) == python
    assert _help_output('auto', force_color=True) == python
    assert b'\x1b[' in python


@pytest.mark.skipif(not _have('rich_argparse'), reason='rich-argparse is optional')
@pytest.mark.skipif(not _extension_available(), reason='Rust extension is not installed')
def test_rich_help_no_color_exact_backend_parity(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    python = _help_output('python', force_color=False, use_rich=True)
    assert _help_output('rust', force_color=False, use_rich=True) == python
    assert _help_output('auto', force_color=False, use_rich=True) == python
