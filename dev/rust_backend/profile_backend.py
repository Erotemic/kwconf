#!/usr/bin/env python3
"""Unified native/PyO3 profiling entry point for the kwconf accelerator.

Examples:
    python dev/rust_backend/profile_backend.py criterion
    python dev/rust_backend/profile_backend.py perf-stat --workload parse-sparse
    python dev/rust_backend/profile_backend.py perf-record --workload build
    python dev/rust_backend/profile_backend.py flamegraph --workload parse-dense
    python dev/rust_backend/profile_backend.py callgrind --workload parse-sparse
    python dev/rust_backend/profile_backend.py massif --workload build
    python dev/rust_backend/profile_backend.py python-cprofile --workload rust-bridge
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
MANIFEST = REPO_DPATH / 'rust' / 'kwconf_accel' / 'Cargo.toml'
PROFILE_DPATH = REPO_DPATH / 'dev' / 'benchmarks' / '_profiles'
TARGET_DPATH = REPO_DPATH / 'rust' / 'kwconf_accel' / 'target'
PROFILE_BIN = TARGET_DPATH / 'profiling' / 'kwconf-accel-profile'
PY_PROFILE_WORKLOAD = REPO_DPATH / 'dev' / 'rust_backend' / '_profile_python_bridge.py'


DEFAULT_ITERATIONS = {
    'build': 50_000,
    'parse-sparse': 5_000_000,
    'parse-dense': 100_000,
    'parse-mixed': 100_000,
    'short-cluster': 1_000_000,
    'fallback': 5_000_000,
    'complete-options': 200_000,
    'complete-choice': 1_000_000,
    'route-modal': 1_000_000,
    'pyo3-parse': 200_000,
    'rust-bridge': 100_000,
    'kwconf-cli': 20_000,
    'completion-pyo3': 100_000,
}


def _iterations(args: argparse.Namespace) -> int:
    if args.iterations is not None:
        return args.iterations
    value = DEFAULT_ITERATIONS[args.workload]
    if args.tool in {'callgrind', 'massif'}:
        # Instrumented execution is orders of magnitude slower than native
        # sampling; keep the default profile useful without making it huge.
        value = max(1_000, value // 50)
    return value


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print('+', ' '.join(map(str, command)))
    subprocess.run(command, cwd=REPO_DPATH, env=env, check=True)


def _require(program: str, hint: str) -> str:
    found = shutil.which(program)
    if found is None:
        raise SystemExit(f'{program!r} was not found. {hint}')
    return found


def _build_profile_binary() -> None:
    _require('cargo', 'Install a Rust toolchain and retry.')
    _run(
        [
            'cargo',
            'build',
            '--manifest-path',
            str(MANIFEST),
            '--profile',
            'profiling',
            '--no-default-features',
            '--features',
            'native-tools',
            '--bin',
            'kwconf-accel-profile',
        ]
    )
    if not PROFILE_BIN.exists():
        raise SystemExit(f'expected profiling binary at {PROFILE_BIN}')


def _native_command(args: argparse.Namespace) -> list[str]:
    return [
        str(PROFILE_BIN),
        args.workload,
        str(args.schema_size),
        str(_iterations(args)),
    ]


def _criterion(args: argparse.Namespace) -> None:
    _require('cargo', 'Install a Rust toolchain and retry.')
    command = [
        'cargo',
        'bench',
        '--manifest-path',
        str(MANIFEST),
        '--bench',
        'parser',
        '--no-default-features',
    ]
    criterion_args = []
    if args.filter:
        criterion_args.append(args.filter)
    if args.save_baseline:
        criterion_args.extend(['--save-baseline', args.save_baseline])
    if args.baseline:
        criterion_args.extend(['--baseline', args.baseline])
    if criterion_args:
        command.append('--')
        command.extend(criterion_args)
    _run(command)


def _perf_stat(args: argparse.Namespace) -> None:
    perf = _require('perf', 'Install Linux perf (often linux-tools) and retry.')
    _build_profile_binary()
    command = [
        perf,
        'stat',
        '-r',
        str(args.repeat),
        '-e',
        'task-clock,cycles,instructions,branches,branch-misses,cache-references,cache-misses',
        '--',
        *_native_command(args),
    ]
    _run(command)


def _perf_record(args: argparse.Namespace) -> None:
    perf = _require('perf', 'Install Linux perf (often linux-tools) and retry.')
    _build_profile_binary()
    PROFILE_DPATH.mkdir(parents=True, exist_ok=True)
    output = args.output or PROFILE_DPATH / f'perf-{args.workload}.data'
    report = output.with_suffix(output.suffix + '.txt')
    _run(
        [
            perf,
            'record',
            '-g',
            '--call-graph',
            'dwarf',
            '-o',
            str(output),
            '--',
            *_native_command(args),
        ]
    )
    with report.open('w') as file:
        command = [
            perf,
            'report',
            '--stdio',
            '--input',
            str(output),
            '--sort',
            'dso,symbol',
        ]
        print('+', ' '.join(command), '>', report)
        subprocess.run(command, cwd=REPO_DPATH, check=True, stdout=file)
    print(f'perf data:   {output}')
    print(f'perf report: {report}')


def _perf_python(args: argparse.Namespace) -> None:
    perf = _require('perf', 'Install Linux perf (often linux-tools) and retry.')
    PROFILE_DPATH.mkdir(parents=True, exist_ok=True)
    output = args.output or PROFILE_DPATH / f'perf-python-{args.workload}.data'
    report = output.with_suffix(output.suffix + '.txt')
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    _run(
        [
            perf,
            'record',
            '-g',
            '--call-graph',
            'dwarf',
            '-o',
            str(output),
            '--',
            sys.executable,
            str(PY_PROFILE_WORKLOAD),
            args.workload,
            str(args.schema_size),
            str(_iterations(args)),
        ],
        env=env,
    )
    with report.open('w') as file:
        command = [
            perf,
            'report',
            '--stdio',
            '--input',
            str(output),
            '--sort',
            'dso,symbol',
        ]
        print('+', ' '.join(command), '>', report)
        subprocess.run(command, cwd=REPO_DPATH, check=True, stdout=file)
    print(f'perf data:   {output}')
    print(f'perf report: {report}')
    print(
        'For useful Rust/PyO3 symbols, install a profiling wheel first with:\n'
        '  python dev/rust_backend/build_backend.py --profile profiling'
    )

def _flamegraph(args: argparse.Namespace) -> None:
    _require('cargo', 'Install a Rust toolchain and retry.')
    if shutil.which('cargo-flamegraph') is None and shutil.which('flamegraph') is None:
        raise SystemExit(
            'cargo flamegraph is not installed. Run `cargo install flamegraph` '
            'or use perf-record instead.'
        )
    PROFILE_DPATH.mkdir(parents=True, exist_ok=True)
    output = args.output or PROFILE_DPATH / f'flamegraph-{args.workload}.svg'
    command = [
        'cargo',
        'flamegraph',
        '--manifest-path',
        str(MANIFEST),
        '--profile',
        'profiling',
        '--no-default-features',
        '--features',
        'native-tools',
        '--bin',
        'kwconf-accel-profile',
        '--output',
        str(output),
        '--',
        args.workload,
        str(args.schema_size),
        str(_iterations(args)),
    ]
    _run(command)
    print(f'flamegraph: {output}')


def _callgrind(args: argparse.Namespace) -> None:
    valgrind = _require('valgrind', 'Install valgrind and retry.')
    _build_profile_binary()
    PROFILE_DPATH.mkdir(parents=True, exist_ok=True)
    output = args.output or PROFILE_DPATH / f'callgrind-{args.workload}.out'
    _run(
        [
            valgrind,
            '--tool=callgrind',
            '--collect-jumps=yes',
            f'--callgrind-out-file={output}',
            *_native_command(args),
        ]
    )
    annotate = shutil.which('callgrind_annotate')
    if annotate:
        report = output.with_suffix(output.suffix + '.txt')
        with report.open('w') as file:
            command = [annotate, '--inclusive=yes', str(output)]
            print('+', ' '.join(command), '>', report)
            subprocess.run(command, cwd=REPO_DPATH, check=True, stdout=file)
        print(f'callgrind report: {report}')
    print(f'callgrind data: {output}')


def _massif(args: argparse.Namespace) -> None:
    valgrind = _require('valgrind', 'Install valgrind and retry.')
    _build_profile_binary()
    PROFILE_DPATH.mkdir(parents=True, exist_ok=True)
    output = args.output or PROFILE_DPATH / f'massif-{args.workload}.out'
    _run(
        [
            valgrind,
            '--tool=massif',
            '--stacks=yes',
            f'--massif-out-file={output}',
            *_native_command(args),
        ]
    )
    ms_print = shutil.which('ms_print')
    if ms_print:
        report = output.with_suffix(output.suffix + '.txt')
        with report.open('w') as file:
            command = [ms_print, str(output)]
            print('+', ' '.join(command), '>', report)
            subprocess.run(command, cwd=REPO_DPATH, check=True, stdout=file)
        print(f'massif report: {report}')
    print(f'massif data: {output}')


def _python_cprofile(args: argparse.Namespace) -> None:
    PROFILE_DPATH.mkdir(parents=True, exist_ok=True)
    output = args.output or PROFILE_DPATH / f'python-{args.workload}.prof'
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    _run(
        [
            sys.executable,
            '-m',
            'cProfile',
            '-o',
            str(output),
            str(PY_PROFILE_WORKLOAD),
            args.workload,
            str(args.schema_size),
            str(_iterations(args)),
        ],
        env=env,
    )
    report = output.with_suffix(output.suffix + '.txt')
    command = [
        sys.executable,
        '-c',
        (
            'import pstats, sys; '
            "pstats.Stats(sys.argv[1]).strip_dirs().sort_stats('cumulative').print_stats(50)"
        ),
        str(output),
    ]
    print('+', ' '.join(command), '>', report)
    with report.open('w') as file:
        subprocess.run(
            command, cwd=REPO_DPATH, env=env, check=True, stdout=file
        )
    print(f'cProfile data:   {output}')
    print(f'cProfile report: {report}')


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'tool',
        choices=[
            'criterion',
            'perf-stat',
            'perf-record',
            'perf-python',
            'flamegraph',
            'callgrind',
            'massif',
            'python-cprofile',
        ],
    )
    parser.add_argument(
        '--workload',
        choices=[
            'build',
            'parse-sparse',
            'parse-dense',
            'parse-mixed',
            'short-cluster',
            'fallback',
            'complete-options',
            'complete-choice',
            'route-modal',
            'pyo3-parse',
            'rust-bridge',
            'kwconf-cli',
            'completion-pyo3',
        ],
        default='parse-sparse',
    )
    parser.add_argument('--schema-size', type=int, default=256)
    parser.add_argument(
        '--iterations',
        type=int,
        help='override workload-specific iteration count',
    )
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--filter')
    baseline = parser.add_mutually_exclusive_group()
    baseline.add_argument('--save-baseline')
    baseline.add_argument('--baseline')
    parser.add_argument('--output', type=Path)
    return parser


def main() -> None:
    args = _make_cli().parse_args()
    native = {
        'build',
        'parse-sparse',
        'parse-dense',
        'parse-mixed',
        'short-cluster',
        'fallback',
        'complete-options',
        'complete-choice',
        'route-modal',
    }
    python = {'pyo3-parse', 'rust-bridge', 'kwconf-cli', 'completion-pyo3'}
    if (
        args.tool in {'python-cprofile', 'perf-python'}
        and args.workload not in python
    ):
        raise SystemExit(
            'Python/PyO3 profiler workload must be pyo3-parse, rust-bridge, kwconf-cli, or completion-pyo3'
        )
    if (
        args.tool not in {'python-cprofile', 'perf-python', 'criterion'}
        and args.workload not in native
    ):
        raise SystemExit(
            'native profiler workload must be build, parse-sparse, parse-dense, '
            'parse-mixed, short-cluster, fallback, complete-options, '
            'complete-choice, or route-modal'
        )
    dispatch = {
        'criterion': _criterion,
        'perf-stat': _perf_stat,
        'perf-record': _perf_record,
        'perf-python': _perf_python,
        'flamegraph': _flamegraph,
        'callgrind': _callgrind,
        'massif': _massif,
        'python-cprofile': _python_cprofile,
    }
    dispatch[args.tool](args)


if __name__ == '__main__':
    main()
