#!/usr/bin/env python3
"""Parity smoke checks for the experimental Rust backend, no pytest required."""

from __future__ import annotations

import itertools
import os
import subprocess
import sys
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
if str(REPO_DPATH) not in sys.path:
    sys.path.insert(0, str(REPO_DPATH))

import kwconf


class Demo(kwconf.Config):
    number: int = 0
    label: str = ''
    flag = kwconf.Value(False, isflag=True, alias=['enabled'], short_alias=['f'])
    verbose = kwconf.Value(0, isflag='counter', short_alias=['v'])
    maybe = kwconf.Value('default', bare='BARE', short_alias=['m'])
    choice = kwconf.Value('a', choices=['a', 'b'])


class TypedDemo(kwconf.Config):
    number: int = 0
    label: str = ''
    ratio: float = 1.0
    enabled: bool = False


def _run_cls(
    cls: type[kwconf.Config],
    backend: str,
    argv: list[str],
    *,
    strict: bool = True,
) -> dict:
    old = getattr(cls, '__cli_backend__', None)
    cls.__cli_backend__ = backend
    try:
        result = cls.cli(
            argv=argv,
            strict=strict,
            autocomplete=False,
            special_options=False,
        )
    finally:
        if old is None:
            del cls.__cli_backend__
        else:
            cls.__cli_backend__ = old
    return dict(result)


def _run(backend: str, argv: list[str], *, strict: bool = True) -> dict:
    return _run_cls(Demo, backend, argv, strict=strict)


def _subprocess_case(backend: str, body: str, argv: list[str]):
    code = (
        'import kwconf\n'
        + body
        + f"\nC.__cli_backend__={backend!r}\n"
        + f"C.cli(argv={argv!r}, autocomplete=False, special_options=False)\n"
    )
    env = os.environ.copy()
    old = env.get('PYTHONPATH')
    env['PYTHONPATH'] = str(REPO_DPATH) if not old else str(REPO_DPATH) + os.pathsep + old
    return subprocess.run(
        [sys.executable, '-c', code],
        cwd=REPO_DPATH,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _assert_exact_failure_parity(body: str, argv: list[str]) -> None:
    py = _subprocess_case('python', body, argv)
    rust = _subprocess_case('rust', body, argv)
    auto = _subprocess_case('auto', body, argv)
    expected = (py.returncode, py.stdout, py.stderr)
    assert (rust.returncode, rust.stdout, rust.stderr) == expected, (
        argv,
        expected,
        (rust.returncode, rust.stdout, rust.stderr),
    )
    assert (auto.returncode, auto.stdout, auto.stderr) == expected, (
        argv,
        expected,
        (auto.returncode, auto.stdout, auto.stderr),
    )


def main() -> None:
    try:
        import _kwconf_rust
    except ImportError as ex:
        raise SystemExit(
            'extension not installed; run '
            'python dev/rust_backend/build_backend.py --release first'
        ) from ex

    assert _kwconf_rust.backend_info() == ('kwconf-cli-core', 3)
    capabilities = set(_kwconf_rust.backend_capabilities())
    assert {
        'flat-parse',
        'nested-static-parse',
        'static-completion',
        'static-completion-values',
        'modal-static-completion',
        'modal-static-route',
        'abi3-py310',
    } <= capabilities

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
        ['--choice=b'],
        ['--number=1', '--number=2'],
    ]
    for argv in cases:
        want = _run('python', argv)
        got = _run('rust', argv)
        auto = _run('auto', argv)
        assert got == want, (argv, want, got)
        assert auto == want, (argv, want, auto)

    # Exercise option ordering / repetition without requiring a property-test
    # dependency in the build helper. These pairs catch stateful flag/counter
    # behavior that one-option smoke cases cannot.
    fragments = [
        ['--number=3'],
        ['--label=x'],
        ['--flag'],
        ['--no-flag'],
        ['-v'],
        ['-vv'],
        ['--maybe'],
        ['--maybe=y'],
    ]
    for parts in itertools.product(fragments, repeat=3):
        argv = [token for part in parts for token in part]
        want = _run('python', argv)
        got = _run('rust', argv)
        assert got == want, (argv, want, got)

    typed_cases = [
        [],
        ['--number=3'],
        ['--label=hello'],
        ['--ratio=2.5'],
        ['--enabled'],
        ['--enabled=false'],
        ['--number=3', '--ratio', '4.5', '--label=x'],
    ]
    for argv in typed_cases:
        want = _run_cls(TypedDemo, 'python', argv)
        got = _run_cls(TypedDemo, 'rust', argv)
        auto = _run_cls(TypedDemo, 'auto', argv)
        assert got == want, (argv, want, got)
        assert auto == want, (argv, want, auto)

    # Fallback cases: these are intentionally not implemented by the Rust core
    # but must remain behaviorally identical because Config retries argparse.
    simple_body = (
        'class C(kwconf.Config):\n'
        '    number: int = 0\n'
        "    choice = kwconf.Value('a', choices=['a','b'])\n"
    )
    for argv in [
        ['--num=4'],  # argparse abbreviation of --number
        ['--choice=not-a-choice'],
        ['--number=not-an-int'],
        ['--definitely-unknown=1'],
    ]:
        _assert_exact_failure_parity(simple_body, argv)

    required_body = (
        'class C(kwconf.Config):\n'
        "    value = kwconf.Value('', required=True)\n"
    )
    _assert_exact_failure_parity(required_body, [])

    mutex_body = (
        'class C(kwconf.Config):\n'
        "    left = kwconf.Value('', mutex_group='pair')\n"
        "    right = kwconf.Value('', mutex_group='pair')\n"
    )
    _assert_exact_failure_parity(
        mutex_body,
        ['--left=a', '--right=b'],
    )

    class RequiredDemo(kwconf.Config):
        __cli_backend__ = 'rust'
        value = kwconf.Value('', parser=str, required=True)

    assert RequiredDemo.cli(
        argv=['--value=ok'], autocomplete=False, special_options=False
    ).value == 'ok'

    # Arbitrary Python parsers are intentionally outside the speculative fast
    # path: falling back after executing one would invoke user code twice.
    callback_calls = []

    def custom_parser(text):
        callback_calls.append(text)
        return text.upper()

    class CallbackDemo(kwconf.Config):
        __cli_backend__ = 'rust'
        value = kwconf.Value('', parser=custom_parser)

    assert CallbackDemo.cli(
        argv=['--value=once'], autocomplete=False, special_options=False
    ).value == 'ONCE'
    assert callback_calls == ['once']

    from kwconf import _rust

    status = _rust.backend_status(Demo())
    assert status['extension_available'] is True
    assert status['protocol'] == ('kwconf-cli-core', 3)
    assert 'static-completion' in status['capabilities']
    assert 'modal-static-route' in status['capabilities']

    # Static completion should avoid argparse entirely for ordinary choices.
    index = _rust.compile_completion_index(Demo())
    candidates = [item[0] for item in index.complete([], '--ch')]
    assert '--choice' in candidates
    choices = [item[0] for item in index.complete([], '--choice=')]
    assert choices == ['--choice=a', '--choice=b']
    # A scalar value without finite choices deliberately returns None so the
    # canonical argcomplete default/filesystem completer can own the request.
    assert index.complete(['--label'], '') is None

    command_index = _rust.make_completion_index(
        [],
        [([], 'train_model', ['train-model'], 'train command')],
    )
    assert command_index.route(['train-model', '--number=3']) == (
        ['train_model'],
        1,
    )

    # Exercise the actual ModalCLI integration, not only the routing index.
    # The static Rust router should select the command and the selected Config
    # should then use the normal accelerated Config.cli path.
    modal_seen = {}

    class TrainCommand(kwconf.Config):
        __command__ = 'train_model'
        __cli_backend__ = 'rust'
        epochs: int = 1

        @classmethod
        def main(cls, argv=None, **kwargs):
            cfg = cls.cli(
                argv=argv,
                data=kwargs,
                autocomplete=False,
                special_options=False,
            )
            modal_seen['epochs'] = cfg.epochs
            return 9

    class ModalRoot(kwconf.ModalCLI):
        __cli_backend__ = 'rust'
        __subconfigs__ = [TrainCommand]

    assert ModalRoot.main(
        argv=['train-model', '--epochs=3'],
        autocomplete=False,
    ) == 9
    assert modal_seen == {'epochs': 3}

    # Fixed realized SubConfig leaves are accelerated. Dynamic selector tokens
    # still decline and are reparsed by the canonical multipass implementation.
    class Inner(kwconf.Config):
        count: int = 1
        mode = kwconf.Value('a', choices=['a', 'b'])

    class Outer(kwconf.Config):
        __cli_backend__ = 'rust'
        inner = kwconf.SubConfig(Inner, choices={'inner': Inner})

    nested = Outer.cli(
        argv=['--inner.count=3', '--inner.mode=b'],
        autocomplete=False,
        special_options=False,
    )
    assert nested.inner.count == 3
    assert nested.inner.mode == 'b'

    num_success = len(cases) + len(fragments) ** 3 + len(typed_cases)
    print(
        'Rust backend parity smoke checks passed '
        f'({num_success} accelerated success cases plus fallback checks)'
    )


if __name__ == '__main__':
    main()
