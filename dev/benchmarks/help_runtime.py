#!/usr/bin/env python3
"""Benchmark help/color startup while enforcing backend output parity."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_DPATH = Path(__file__).resolve().parents[2]


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _kwconf_script(backend: str, size: int) -> str:
    lines = ['import kwconf', '', 'class CLI(kwconf.Config):', f"    __cli_backend__ = {backend!r}"]
    for idx in range(size):
        lines.append(f"    option_{idx}: str = kwconf.Value('', help='option {idx} help')")
    lines += ['', "CLI.cli(argv=['--help'], autocomplete=False, special_options=False)"]
    return '\n'.join(lines) + '\n'


def _run(path: Path, env: dict[str, str]) -> tuple[float, bytes, bytes, int]:
    start = time.perf_counter_ns()
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=REPO_DPATH,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = (time.perf_counter_ns() - start) / 1e6
    return elapsed, proc.stdout, proc.stderr, proc.returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--trials', type=int, default=30)
    parser.add_argument('--schema-sizes', default='1,16,64,256')
    parser.add_argument('--script-dir', type=Path)
    parser.add_argument('--output-json', type=Path)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args()
    if args.quick:
        args.trials = min(args.trials, 8)
    sizes = [int(x) for x in args.schema_sizes.split(',') if x]
    rng = random.Random(args.seed)
    env_base = os.environ.copy()
    old = env_base.get('PYTHONPATH')
    env_base['PYTHONPATH'] = str(REPO_DPATH) if not old else str(REPO_DPATH) + os.pathsep + old

    report: dict[str, Any] = {
        'python': sys.executable,
        'trials': args.trials,
        'rich_argparse_version': _version('rich-argparse'),
        'cases': [],
    }

    if args.script_dir is None:
        context = tempfile.TemporaryDirectory(prefix='kwconf-help-')
        directory = None
    else:
        args.script_dir.mkdir(parents=True, exist_ok=True)
        context = None
        directory = args.script_dir
    try:
        if directory is None:
            directory = Path(context.__enter__())  # type: ignore[union-attr]
        for size in sizes:
            paths = {}
            for backend in ('python', 'rust', 'auto'):
                path = directory / f'{backend}-{size}.py'
                path.write_text(_kwconf_script(backend, size))
                paths[backend] = path

            for color_mode in ('stdlib', 'rich-auto', 'force-color', 'no-color'):
                env = dict(env_base)
                if color_mode == 'force-color':
                    env['FORCE_COLOR'] = '1'
                    env['TERM'] = 'xterm-256color'
                    env.pop('KWCONF_NORICH', None)
                    env.pop('NO_COLOR', None)
                elif color_mode == 'no-color':
                    env['NO_COLOR'] = '1'
                    env.pop('FORCE_COLOR', None)
                    env.pop('KWCONF_NORICH', None)
                elif color_mode == 'rich-auto':
                    env.pop('FORCE_COLOR', None)
                    env.pop('NO_COLOR', None)
                    env.pop('KWCONF_NORICH', None)
                else:
                    env['KWCONF_NORICH'] = '1'
                    env.pop('FORCE_COLOR', None)
                    env.pop('NO_COLOR', None)
                samples = {k: [] for k in paths}
                outputs: dict[str, bytes] = {}
                for _ in range(args.trials):
                    order = list(paths)
                    rng.shuffle(order)
                    for backend in order:
                        elapsed, stdout, stderr, code = _run(paths[backend], env)
                        if code != 0:
                            raise RuntimeError(
                                f'{backend} help failed: {stderr.decode(errors="replace")}'
                            )
                        samples[backend].append(elapsed)
                        outputs[backend] = stdout
                exact = outputs['python'] == outputs['rust'] == outputs['auto']
                if not exact:
                    raise AssertionError(
                        f'Rust/auto help output diverged in {color_mode} mode'
                    )
                has_ansi = b'\x1b[' in outputs['python']
                print(f'\nschema_size={size}, color_mode={color_mode}, ansi={has_ansi}')
                base = statistics.median(samples['python'])
                methods = {}
                for backend in ('python', 'rust', 'auto'):
                    med = statistics.median(samples[backend])
                    print(
                        f'  kwconf_{backend:6s} median={med:8.3f} ms '
                        f'ratio={med/base:6.3f}x'
                    )
                    methods[backend] = {'median_ms': med, 'ratio': med / base}
                report['cases'].append(
                    {
                        'schema_size': size,
                        'color_mode': color_mode,
                        'ansi_present': has_ansi,
                        'exact_output_parity': exact,
                        'methods': methods,
                    }
                )
    finally:
        if context is not None:
            context.__exit__(None, None, None)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print('wrote:', args.output_json)


if __name__ == '__main__':
    main()
