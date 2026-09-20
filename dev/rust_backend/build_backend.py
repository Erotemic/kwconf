#!/usr/bin/env python3
"""Build/install the experimental Rust extension for the active Python."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
MANIFEST = REPO_DPATH / 'rust' / 'kwconf_accel' / 'Cargo.toml'
CRATE_DPATH = REPO_DPATH / 'rust' / 'kwconf_accel'
WHEEL_DPATH = CRATE_DPATH / 'dist'


def _maturin_command() -> list[str]:
    maturin = shutil.which('maturin')
    if maturin is not None:
        return [maturin]
    uv = shutil.which('uv')
    if uv is not None:
        return [uv, 'tool', 'run', '--from', 'maturin', 'maturin']
    raise SystemExit(
        'maturin is not installed and uv is unavailable. Install maturin in '
        'the active environment, then rerun this command.'
    )


def _assert_abi3_wheel(wheel: Path) -> None:
    """Refuse accidentally version-specific accelerator wheels.

    The optional binary is intentionally built against CPython's Stable ABI
    with a Python 3.10 floor. Compatibility is part of the accelerator's
    product contract, so a faster cp313-only artifact is a benchmark variant,
    not a releasable kwconf accelerator wheel.
    """
    tags = wheel.stem.split('-')
    if 'abi3' not in tags:
        raise SystemExit(
            'Refusing non-abi3 accelerator wheel: '
            f'{wheel.name}. Expected a Stable-ABI wheel such as '
            'cp310-abi3-<platform>.whl.'
        )


def _assert_abi3_extension_layout() -> None:
    """Validate the installed Stable-ABI extension layout.

    Maturin's normal *pure Rust project* wheel layout is a tiny package
    ``_kwconf_rust/__init__.py`` which re-exports a native child module.  A
    top-level extension module is also valid if a future packaging setup emits
    one directly.  What matters for the release contract is that the imported
    public module resolves to a real abi3 native extension, not whether maturin
    uses its generated one-line wrapper.
    """
    import importlib
    import importlib.machinery
    import importlib.util

    spec = importlib.util.find_spec('_kwconf_rust')
    if spec is None or spec.origin is None:
        raise SystemExit('installed _kwconf_rust module could not be located')

    origin = Path(spec.origin)
    extension_suffixes = tuple(importlib.machinery.EXTENSION_SUFFIXES)

    def is_native(path: Path) -> bool:
        return any(path.name.endswith(suffix) for suffix in extension_suffixes)

    if is_native(origin):
        native_origin = origin
        wrapper_origin = None
    elif origin.name == '__init__.py':
        # Importing the public package is part of the real user-facing cost and
        # ensures find_spec can resolve the generated native child reliably.
        importlib.import_module('_kwconf_rust')
        child_spec = importlib.util.find_spec('_kwconf_rust._kwconf_rust')
        if child_spec is None or child_spec.origin is None:
            raise SystemExit(
                'maturin wrapper was installed but native child '
                '_kwconf_rust._kwconf_rust could not be located'
            )
        native_origin = Path(child_spec.origin)
        wrapper_origin = origin
        if not is_native(native_origin):
            raise SystemExit(
                'expected maturin wrapper to resolve to a native extension, '
                f'got {native_origin!s}'
            )
    else:
        raise SystemExit(
            'installed _kwconf_rust has an unexpected import layout: '
            f'{origin!s}'
        )

    # Stable-ABI compatibility is asserted from the wheel tag above.  Do not
    # infer it from the installed shared-library filename: Windows stable-ABI
    # extension filenames need not contain the literal string ``abi3``.
    if wrapper_origin is not None:
        print('extension wrapper origin:', wrapper_origin)
    print('native extension origin:', native_origin)


def _install_wheel(wheel: Path) -> None:
    uv = shutil.which('uv')
    if uv is not None:
        command = [
            uv,
            'pip',
            'install',
            '--python',
            sys.executable,
            '--force-reinstall',
            '--no-deps',
            str(wheel),
        ]
    else:
        command = [
            sys.executable,
            '-m',
            'pip',
            'install',
            '--force-reinstall',
            '--no-deps',
            str(wheel),
        ]
    print('+', ' '.join(command))
    subprocess.run(command, cwd=CRATE_DPATH, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--release', action='store_true')
    mode.add_argument(
        '--profile',
        help='build with a named Cargo profile (for example: profiling)',
    )
    parser.add_argument(
        '--benchmark',
        action='store_true',
        help='run the quick Python/PyO3 benchmark after install/check',
    )
    parser.add_argument(
        '--benchmark-native',
        action='store_true',
        help='run native Criterion parser benchmarks after install/check',
    )
    parser.add_argument(
        '--benchmark-startup',
        action='store_true',
        help='run interleaved fresh-process CLI startup trials',
    )
    parser.add_argument(
        '--benchmark-all',
        action='store_true',
        help='run component, native, startup, completion, modal, and help/color benchmarks',
    )
    parser.add_argument(
        '--wheel',
        action='store_true',
        help='build the wheel but do not install/check it',
    )
    parser.add_argument('--verbose', '-v', action='count', default=0)
    args = parser.parse_args()
    any_benchmark = (
        args.benchmark
        or args.benchmark_native
        or args.benchmark_startup
        or args.benchmark_all
    )
    if args.wheel and any_benchmark:
        parser.error('--wheel cannot be combined with benchmark options')

    if shutil.which('cargo') is None:
        raise SystemExit('cargo was not found on PATH; install a Rust toolchain first')

    WHEEL_DPATH.mkdir(parents=True, exist_ok=True)
    before = set(WHEEL_DPATH.glob('*.whl'))
    command = [
        *_maturin_command(),
        'build',
        '--manifest-path',
        str(MANIFEST),
        '--interpreter',
        sys.executable,
        '--out',
        str(WHEEL_DPATH),
    ]
    if args.release:
        command.append('--release')
    elif args.profile:
        command.extend(['--profile', args.profile])
    if args.verbose:
        command.extend(['-' + ('v' * min(args.verbose, 2))])

    print('+', ' '.join(command))
    subprocess.run(command, cwd=CRATE_DPATH, check=True)

    after = set(WHEEL_DPATH.glob('*.whl'))
    candidates = sorted(after - before, key=lambda p: p.stat().st_mtime)
    if not candidates:
        candidates = sorted(after, key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise SystemExit(f'maturin produced no wheel under {WHEEL_DPATH}')
    wheel = candidates[-1]
    print('wheel:', wheel)
    _assert_abi3_wheel(wheel)

    if args.wheel:
        return

    _install_wheel(wheel)
    _assert_abi3_extension_layout()
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    check = [sys.executable, 'dev/rust_backend/check_backend.py']
    print('+', ' '.join(check))
    subprocess.run(check, cwd=REPO_DPATH, env=env, check=True)

    python_benchmark = [
        sys.executable,
        'dev/benchmarks/rust_cli_runtime.py',
        '--quick',
    ]
    startup_benchmark = [
        sys.executable,
        'dev/benchmarks/cli_startup.py',
        '--quick',
    ]
    native_benchmark = [
        sys.executable,
        'dev/rust_backend/profile_backend.py',
        'criterion',
    ]
    completion_benchmark = [
        sys.executable,
        'dev/benchmarks/completion_runtime.py',
        '--quick',
    ]
    modal_benchmark = [
        sys.executable,
        'dev/benchmarks/modal_runtime.py',
        '--quick',
    ]
    help_benchmark = [
        sys.executable,
        'dev/benchmarks/help_runtime.py',
        '--quick',
    ]
    run_python = args.benchmark or args.benchmark_all
    run_native = args.benchmark_native or args.benchmark_all
    run_startup = args.benchmark_startup or args.benchmark_all
    for enabled, command in [
        (run_python, python_benchmark),
        (run_native, native_benchmark),
        (run_startup, startup_benchmark),
        (args.benchmark_all, completion_benchmark),
        (args.benchmark_all, modal_benchmark),
        (args.benchmark_all, help_benchmark),
    ]:
        if enabled:
            print('+', ' '.join(command))
            subprocess.run(command, cwd=REPO_DPATH, env=env, check=True)
    if not (run_python or run_native or run_startup):
        print('benchmark with the same Python:')
        print('  ' + ' '.join(python_benchmark))
        print('  ' + ' '.join(startup_benchmark))
        print('native Rust benchmark:')
        print('  ' + ' '.join(native_benchmark))
        print('full evidence bundle:')
        print(f'  {sys.executable} dev/rust_backend/evidence_bundle.py')


if __name__ == '__main__':
    main()
