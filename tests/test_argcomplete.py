import builtins
import importlib
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import types

import pytest

import kwconf


REPO_DPATH = Path(__file__).resolve().parents[1]


class _AutocompleteIntercept(RuntimeError):
    """Raised by fake completion hooks before normal CLI parsing runs."""


def _option_strings(parser):
    return {
        option
        for action in parser._actions
        for option in getattr(action, 'option_strings', ())
    }


def _subcommand_names(parser):
    names = set()
    for action in parser._actions:
        choices = getattr(action, 'choices', None)
        if isinstance(choices, dict):
            names.update(choices)
    return names


def _block_argcomplete_import(monkeypatch):
    """Make argcomplete unavailable even when it is installed in the test env."""
    real_import = builtins.__import__
    real_import_module = importlib.import_module

    def guarded_import(name, *args, **kwargs):
        if name == 'argcomplete':
            raise ImportError('argcomplete intentionally unavailable for test')
        return real_import(name, *args, **kwargs)

    def guarded_import_module(name, *args, **kwargs):
        if name == 'argcomplete':
            raise ImportError('argcomplete intentionally unavailable for test')
        return real_import_module(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, 'argcomplete', raising=False)
    monkeypatch.setattr(builtins, '__import__', guarded_import)
    monkeypatch.setattr(importlib, 'import_module', guarded_import_module)


def _run_real_argcomplete_subprocess(tmp_path, command, source):
    """Exercise argcomplete's shell protocol without touching pytest's FDs."""
    pytest.importorskip('argcomplete')

    output_fpath = tmp_path / 'argcomplete-output.txt'
    env = os.environ.copy()
    env.update(
        {
            '_ARGCOMPLETE': '1',
            '_ARGCOMPLETE_IFS': '\v',
            '_ARGCOMPLETE_STDOUT_FILENAME': os.fspath(output_fpath),
            'COMP_LINE': command,
            'COMP_POINT': str(len(command)),
        }
    )
    # Debug mode uses argcomplete's fd-9 stream and is intentionally unrelated
    # to the completion result being tested here.
    env.pop('_ARC_DEBUG', None)
    env.pop('_ARGCOMPLETE_DFS', None)

    proc = subprocess.run(
        [sys.executable, '-c', textwrap.dedent(source)],
        cwd=REPO_DPATH,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f'completion subprocess failed\nstdout={proc.stdout!r}\n'
        f'stderr={proc.stderr!r}'
    )
    assert output_fpath.exists(), (
        'argcomplete did not create its completion output file\n'
        f'stdout={proc.stdout!r}\nstderr={proc.stderr!r}'
    )
    return [item for item in output_fpath.read_text().split('\v') if item]


def test_config_cli_invokes_argcomplete_with_realized_parser(monkeypatch):
    """Config.cli must hand argcomplete the actual parser before parsing argv."""
    seen = {}

    def autocomplete(parser):
        seen['options'] = _option_strings(parser)
        mode_action = next(
            action
            for action in parser._actions
            if '--mode' in getattr(action, 'option_strings', ())
        )
        seen['mode_choices'] = tuple(mode_action.choices)
        raise _AutocompleteIntercept

    fake_argcomplete = types.SimpleNamespace(autocomplete=autocomplete)
    monkeypatch.setitem(sys.modules, 'argcomplete', fake_argcomplete)

    class DemoConfig(kwconf.Config):
        count: int = 0
        mode = kwconf.Value('fast', choices=['fast', 'safe'])
        verbose = kwconf.Flag(False)

    with pytest.raises(_AutocompleteIntercept):
        DemoConfig.cli(
            argv=['--this-would-normally-error'],
            autocomplete=True,
            special_options=False,
        )

    assert '--count' in seen['options']
    assert '--mode' in seen['options']
    assert '--verbose' in seen['options']
    assert seen['mode_choices'] == ('fast', 'safe')


def test_config_cli_argcomplete_missing_auto_vs_explicit(monkeypatch):
    """'auto' is optional; explicit autocomplete=True must surface ImportError."""
    _block_argcomplete_import(monkeypatch)

    class DemoConfig(kwconf.Config):
        value: int = 0

    got = DemoConfig.cli(
        argv=['--value=3'],
        autocomplete='auto',
        special_options=False,
    )
    assert got.value == 3

    with pytest.raises(ImportError, match='intentionally unavailable'):
        DemoConfig.cli(
            argv=['--value=3'],
            autocomplete=True,
            special_options=False,
        )


def test_modal_cli_invokes_argcomplete_with_command_tree(monkeypatch):
    """ModalCLI must expose its command tree to argcomplete before dispatch."""
    seen = {}

    def autocomplete(parser):
        seen['commands'] = _subcommand_names(parser)
        raise _AutocompleteIntercept

    fake_argcomplete = types.SimpleNamespace(autocomplete=autocomplete)
    monkeypatch.setitem(sys.modules, 'argcomplete', fake_argcomplete)

    class Build(kwconf.Config):
        __command__ = 'build'
        target: str = 'all'

        @classmethod
        def main(cls, argv=None, **kwargs):
            raise AssertionError('completion must intercept before dispatch')

    class Inspect(kwconf.Config):
        __command__ = 'inspect'

        @classmethod
        def main(cls, argv=None, **kwargs):
            raise AssertionError('completion must intercept before dispatch')

    class DemoCLI(kwconf.ModalCLI):
        __subconfigs__ = [Build, Inspect]

    with pytest.raises(_AutocompleteIntercept):
        DemoCLI.main(argv=['not-a-real-command'], autocomplete=True)

    assert {'build', 'inspect'} <= seen['commands']


def test_modal_cli_argcomplete_missing_auto_vs_explicit(monkeypatch):
    """ModalCLI follows the same optional-vs-explicit import policy as Config."""
    _block_argcomplete_import(monkeypatch)

    class Command(kwconf.Config):
        __command__ = 'command'

        @classmethod
        def main(cls, argv=None, **kwargs):
            return 123

    class DemoCLI(kwconf.ModalCLI):
        __subconfigs__ = [Command]

    assert DemoCLI.main(argv=['command'], autocomplete='auto') == 123

    with pytest.raises(ImportError, match='intentionally unavailable'):
        DemoCLI.main(argv=['command'], autocomplete=True)


def test_real_argcomplete_config_options_and_choices(tmp_path):
    """Exercise the real argcomplete protocol against a kwconf Config parser."""
    source = r'''
        import kwconf

        class DemoConfig(kwconf.Config):
            output: str = 'out.txt'
            mode = kwconf.Value('fast', choices=['fast', 'safe'])

        DemoConfig.cli(argv=[], autocomplete=True, special_options=False)
    '''

    option_results = _run_real_argcomplete_subprocess(
        tmp_path,
        'prog --ou',
        source,
    )
    assert any(item.strip() == '--output' for item in option_results)

    choice_results = _run_real_argcomplete_subprocess(
        tmp_path,
        'prog --mode f',
        source,
    )
    assert any(item.strip() == 'fast' for item in choice_results)


def test_real_argcomplete_modal_commands_and_options(tmp_path):
    """Exercise the real argcomplete protocol against a ModalCLI command tree."""
    source = r'''
        import kwconf

        class Build(kwconf.Config):
            __command__ = 'build'
            target: str = 'all'

            @classmethod
            def main(cls, argv=None, **kwargs):
                raise AssertionError('completion must intercept before dispatch')

        class Inspect(kwconf.Config):
            __command__ = 'inspect'

            @classmethod
            def main(cls, argv=None, **kwargs):
                raise AssertionError('completion must intercept before dispatch')

        class DemoCLI(kwconf.ModalCLI):
            __subconfigs__ = [Build, Inspect]

        DemoCLI.main(argv=[], autocomplete=True)
    '''

    command_results = _run_real_argcomplete_subprocess(
        tmp_path,
        'prog bu',
        source,
    )
    assert any(item.strip() == 'build' for item in command_results)

    option_results = _run_real_argcomplete_subprocess(
        tmp_path,
        'prog build --ta',
        source,
    )
    assert any(item.strip() == '--target' for item in option_results)
