#!/usr/bin/env python3
"""Benchmark the realistic side-by-side CLI in examples/09_argparse_comparison.py."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_DPATH / 'examples' / '09_argparse_comparison.py'


def _run_child(backend: str, extra: list[str], env: dict[str, str]) -> tuple[int, str]:
    child_env = env.copy()
    if backend == 'kwconf':
        # Benchmark the normal shipping policy regardless of a developer's
        # ambient override.  auto uses Rust when the proven fast path applies.
        child_env['KWCONF_CLI_BACKEND'] = 'auto'
    else:
        child_env.pop('KWCONF_CLI_BACKEND', None)
    start = time.perf_counter_ns()
    proc = subprocess.run(
        [sys.executable, str(EXAMPLE), backend, *extra],
        cwd=REPO_DPATH,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    elapsed = time.perf_counter_ns() - start
    if proc.returncode != 0:
        raise RuntimeError(f'{backend} child failed:\n{proc.stdout}')
    return elapsed, proc.stdout


def _median(values: list[int]) -> float:
    return float(statistics.median(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=20)
    parser.add_argument('--warm-loops', type=int, default=20000)
    parser.add_argument(
        '--cold-only',
        action='store_true',
        help='skip repeated in-process parsing; retain only fresh-process evidence',
    )
    parser.add_argument('--output-json', type=Path)
    args = parser.parse_args()
    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_DPATH) + os.pathsep + env.get('PYTHONPATH', '')

    cold: dict[str, list[int]] = {'argparse': [], 'kwconf': []}
    # Interleave to reduce drift.
    for _ in range(args.trials):
        for backend in ('argparse', 'kwconf'):
            elapsed, _ = _run_child(backend, ['--_quiet'], env)
            cold[backend].append(elapsed)

    results = {}
    warm = {}
    if args.cold_only:
        # Preserve semantic parity evidence without spending the review campaign
        # on a large repeated warm loop.
        for backend in ('argparse', 'kwconf'):
            _, stdout = _run_child(backend, ['--_json'], env)
            payload = json.loads(stdout.strip().splitlines()[-1])
            results[backend] = payload['result']
    else:
        for backend in ('argparse', 'kwconf'):
            _, stdout = _run_child(
                backend,
                [f'--_repeat={args.warm_loops}', '--_json'],
                env,
            )
            payload = json.loads(stdout.strip().splitlines()[-1])
            warm[backend] = float(payload['per_parse_ns'])
            results[backend] = payload['result']

    if results['argparse'] != results['kwconf']:
        raise AssertionError('argparse and kwconf example outputs differ')

    cold_med = {key: _median(value) for key, value in cold.items()}
    data = {
        'python': sys.executable,
        'trials': args.trials,
        'warm_loops': 0 if args.cold_only else args.warm_loops,
        'cold_only': bool(args.cold_only),
        'kwconf_backend': 'auto',
        'cold': {
            key: {
                'median_ns': cold_med[key],
                'mean_ns': statistics.fmean(values),
                'min_ns': min(values),
            }
            for key, values in cold.items()
        },
        'ratios': {
            'cold_kwconf_vs_argparse': cold_med['kwconf'] / cold_med['argparse'],
        },
        'output_parity': True,
    }
    if warm:
        data['warm_parse'] = {key: {'mean_ns': value} for key, value in warm.items()}
        data['ratios']['warm_kwconf_vs_argparse'] = warm['kwconf'] / warm['argparse']
    text = json.dumps(data, indent=2) + '\n'
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
