#!/usr/bin/env python3
"""Benchmark real fresh-process static modal dispatch.

The argparse baseline constructs an equivalent subparser tree. Rust-backed
kwconf may route a static command tree in Rust and then parse the selected leaf
Config with the normal accelerated Config path. Help/errors remain canonical.
"""

from __future__ import annotations

import argparse
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


def _argparse_script(size: int) -> str:
    lines = [
        'import argparse',
        'parser = argparse.ArgumentParser()',
        "subs = parser.add_subparsers(dest='command', required=True)",
    ]
    for idx in range(size):
        lines += [
            f"p = subs.add_parser('command_{idx}', aliases=['command-{idx}'])",
            "p.add_argument('--value', type=int, default=0)",
        ]
    lines += [
        'ns = parser.parse_args()',
        "assert ns.value == 3",
    ]
    return '\n'.join(lines) + '\n'


def _kwconf_script(backend: str, size: int) -> str:
    lines = ['import kwconf', '']
    names = []
    for idx in range(size):
        name = f'Command{idx}'
        names.append(name)
        lines += [
            f'class {name}(kwconf.Config):',
            f"    __command__ = 'command_{idx}'",
            f"    __cli_backend__ = {backend!r}",
            '    value: int = 0',
            '    @classmethod',
            '    def main(cls, argv=None, **kwargs):',
            '        cfg = cls.cli(argv=argv, data=kwargs, autocomplete=False, special_options=False)',
            '        assert cfg.value == 3',
            '        return 0',
            '',
        ]
    lines += [
        'class Root(kwconf.ModalCLI):',
        f"    __cli_backend__ = {backend!r}",
        f"    __subconfigs__ = [{', '.join(names)}]",
        '',
        "raise SystemExit(Root.main(autocomplete=False))",
    ]
    return '\n'.join(lines) + '\n'


def _run(path: Path, command: str, env: dict[str, str]) -> float:
    start = time.perf_counter_ns()
    proc = subprocess.run(
        [sys.executable, str(path), command, '--value=3'],
        cwd=REPO_DPATH,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    elapsed = (time.perf_counter_ns() - start) / 1e6
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors='replace'))
    return elapsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--trials', type=int, default=50)
    parser.add_argument('--schema-sizes', default='1,16,64,256')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--script-dir', type=Path)
    parser.add_argument('--output-json', type=Path)
    args = parser.parse_args()
    if args.quick:
        args.trials = min(args.trials, 12)
    sizes = [int(x) for x in args.schema_sizes.split(',') if x]
    methods = ['argparse', 'kwconf_python', 'kwconf_rust', 'kwconf_auto']
    rng = random.Random(args.seed)
    env = os.environ.copy()
    old = env.get('PYTHONPATH')
    env['PYTHONPATH'] = str(REPO_DPATH) if not old else str(REPO_DPATH) + os.pathsep + old
    report: dict[str, Any] = {'python': sys.executable, 'trials': args.trials, 'cases': []}

    context = None
    if args.script_dir is None:
        context = tempfile.TemporaryDirectory(prefix='kwconf-modal-')
        directory = Path(context.__enter__())
    else:
        directory = args.script_dir
        directory.mkdir(parents=True, exist_ok=True)
    try:
        for size in sizes:
            scripts = {
                'argparse': directory / f'argparse-{size}.py',
                'kwconf_python': directory / f'kwconf-python-{size}.py',
                'kwconf_rust': directory / f'kwconf-rust-{size}.py',
                'kwconf_auto': directory / f'kwconf-auto-{size}.py',
            }
            scripts['argparse'].write_text(_argparse_script(size))
            scripts['kwconf_python'].write_text(_kwconf_script('python', size))
            scripts['kwconf_rust'].write_text(_kwconf_script('rust', size))
            scripts['kwconf_auto'].write_text(_kwconf_script('auto', size))
            observations = {method: [] for method in methods}
            command = f'command-{size - 1}'
            for _ in range(args.trials):
                order = list(methods)
                rng.shuffle(order)
                for method in order:
                    observations[method].append(_run(scripts[method], command, env))
            base = statistics.median(observations['argparse'])
            print(f'\ncommands={size}, selected={command!r}')
            row = {'commands': size, 'selected': command, 'methods': {}}
            for method in methods:
                med = statistics.median(observations[method])
                print(f'  {method:14s} median={med:8.3f} ms ratio={med/base:6.3f}x')
                row['methods'][method] = {'median_ms': med, 'ratio': med / base}
            report['cases'].append(row)
    finally:
        if context is not None:
            context.__exit__(None, None, None)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print('wrote:', args.output_json)


if __name__ == '__main__':
    main()
