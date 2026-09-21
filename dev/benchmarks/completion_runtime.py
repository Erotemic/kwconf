#!/usr/bin/env python3
"""Benchmark real shell-completion startup and candidate parity.

Generated programs exercise argcomplete's actual environment protocol. Static
kwconf requests may be answered by the Rust completion index before argparse or
argcomplete are imported; dynamic requests remain delegated to argcomplete.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
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
IFS = '\013'


def _flat_script(method: str, size: int, *, choices: bool) -> str:
    if method == 'argparse_argcomplete':
        lines = ['import argparse', 'import argcomplete', 'parser = argparse.ArgumentParser()']
        for idx in range(size):
            extra = ", choices=['a','b','c']" if choices else ''
            lines.append(
                f"parser.add_argument('--option-{idx}'{extra}, help='option {idx}')"
            )
        lines.extend(['argcomplete.autocomplete(parser)', 'parser.parse_args()'])
        return '\n'.join(lines) + '\n'

    backend = {
        'kwconf_python': 'python',
        'kwconf_rust': 'rust',
        'kwconf_auto': 'auto',
    }[method]
    lines = ['import kwconf', '', 'class CLI(kwconf.Config):', f"    __cli_backend__ = '{backend}'"]
    for idx in range(size):
        if choices:
            lines.append(
                f"    option_{idx} = kwconf.Value('a', choices=['a','b','c'], help='option {idx}')"
            )
        else:
            lines.append(f"    option_{idx}: str = kwconf.Value('', help='option {idx}')")
    lines.extend(['', "CLI.cli(autocomplete='auto', special_options=False)"])
    return '\n'.join(lines) + '\n'


def _modal_script(method: str) -> str:
    if method == 'argparse_argcomplete':
        return '''\
import argparse
import argcomplete
parser = argparse.ArgumentParser()
subs = parser.add_subparsers(dest='command')
subs.add_parser('train_model', aliases=['train-model'])
subs.add_parser('evaluate')
argcomplete.autocomplete(parser)
parser.parse_args()
'''
    backend = {
        'kwconf_python': 'python',
        'kwconf_rust': 'rust',
        'kwconf_auto': 'auto',
    }[method]
    return f'''\
import kwconf
class Train(kwconf.Config):
    __command__ = 'train_model'
    __cli_backend__ = {backend!r}
    @classmethod
    def main(cls, cmdline=1, **kwargs):
        return cls.cli(cmdline=cmdline, **kwargs)
class Evaluate(kwconf.Config):
    __command__ = 'evaluate'
    __cli_backend__ = {backend!r}
    @classmethod
    def main(cls, cmdline=1, **kwargs):
        return cls.cli(cmdline=cmdline, **kwargs)
class Root(kwconf.ModalCLI):
    __subconfigs__ = [Train, Evaluate]
Root.main(autocomplete='auto')
'''


def _available_methods() -> list[str]:
    methods = ['kwconf_rust', 'kwconf_auto']
    if importlib.util.find_spec('argcomplete') is not None:
        # Compare both kwconf backends against the ecosystem baseline whenever
        # canonical argcomplete is actually available. Without argcomplete the
        # pure-Python backend has no completion engine to invoke.
        methods = ['argparse_argcomplete', 'kwconf_python', *methods]
    return methods


def _run(
    script: Path,
    line_tail: str,
    env: dict[str, str],
    output: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> int:
    line = f'{script} {line_tail}'
    child_env = dict(env)
    child_env.update(
        {
            '_ARGCOMPLETE': '1',
            'COMP_LINE': line,
            'COMP_POINT': str(len(line)),
            '_ARGCOMPLETE_STDOUT_FILENAME': str(output),
        }
    )
    if extra_env:
        child_env.update(extra_env)
    start = time.perf_counter_ns()
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=script.parent,
        env=child_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    elapsed = time.perf_counter_ns() - start
    if proc.returncode != 0:
        raise RuntimeError(
            f'completion child failed: {script}\n'
            + proc.stderr.decode(errors='replace')
        )
    return elapsed


def _candidate_set(text: str) -> set[str]:
    return {item.split(':', 1)[0] for item in text.split(IFS) if item}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _timing_summary(values: list[float]) -> dict[str, float]:
    return {
        'median_ms': statistics.median(values),
        'mean_ms': statistics.fmean(values),
        'p10_ms': _percentile(values, 0.10),
        'p90_ms': _percentile(values, 0.90),
        'min_ms': min(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--trials', type=int, default=50)
    parser.add_argument(
        '--delegated-trials',
        type=int,
        help='trial count for delegated parity-only completion cases (default: --trials)',
    )
    parser.add_argument('--schema-sizes', default='1,16,64,256')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--script-dir', type=Path)
    parser.add_argument('--output-json', type=Path)
    parser.add_argument('--raw-output', type=Path)
    args = parser.parse_args()
    if args.quick:
        args.trials = min(args.trials, 12)
        if args.delegated_trials is None:
            args.delegated_trials = min(args.trials, 2)
    if args.delegated_trials is None:
        args.delegated_trials = args.trials
    if args.trials < 1 or args.delegated_trials < 1:
        raise SystemExit('trial counts must be at least 1')
    sizes = [int(x) for x in args.schema_sizes.split(',') if x]
    methods = _available_methods()

    env = os.environ.copy()
    old = env.get('PYTHONPATH')
    env['PYTHONPATH'] = str(REPO_DPATH) if not old else str(REPO_DPATH) + os.pathsep + old
    rng = random.Random(args.seed)
    report: dict[str, Any] = {
        'python': sys.executable,
        'trials': args.trials,
        'native_trials': args.trials,
        'delegated_trials': args.delegated_trials,
        'argcomplete_available': 'argparse_argcomplete' in methods,
        'measurement': 'fresh completion subprocess wall-clock latency',
        'method_labels': {
            'argparse_argcomplete': 'argparse + argcomplete',
            'kwconf_python': 'kwconf Python + argcomplete',
            'kwconf_rust': 'kwconf Rust native fast path',
            'kwconf_auto': 'kwconf auto',
        },
        'cases': [],
    }

    if args.script_dir is None:
        temp_context = tempfile.TemporaryDirectory(prefix='kwconf-complete-')
        directory = None
    else:
        args.script_dir.mkdir(parents=True, exist_ok=True)
        temp_context = None
        directory = args.script_dir
    try:
        if directory is None:
            directory = Path(temp_context.__enter__())  # type: ignore[union-attr]
        print('completion startup benchmark')
        print('python:', sys.executable)
        if 'argparse_argcomplete' not in methods:
            print('argcomplete: not installed; argparse+argcomplete baseline skipped')

        cases: list[tuple[str, int, str, bool, dict[str, str], str]] = []
        for size in sizes:
            cases.append(('options', size, '--option-', True, {}, 'native'))
            cases.append(('choices', size, '--option-0 b', True, {}, 'native'))
        if 'argparse_argcomplete' in methods:
            # These cursor states deliberately remain canonical argcomplete
            # territory. They are kept in the campaign to prove exact wire
            # parity rather than only fast-path candidate parity.
            cases.append(
                ('dynamic-value', 1, '--option-0 completion-fi', False, {}, 'delegated')
            )
            cases.append(
                ('inline-choice', 1, '--option-0=b', True, {}, 'delegated')
            )
            # Descriptive protocols depend on formatter/help behavior and are
            # intentionally delegated byte-for-byte to argcomplete.
            cases.append(
                (
                    'zsh-descriptions',
                    1,
                    '--option-',
                    True,
                    {'_ARGCOMPLETE_SHELL': 'zsh'},
                    'delegated',
                )
            )
            cases.append(
                (
                    'fish-protocol',
                    1,
                    '--option-',
                    True,
                    {'_ARGCOMPLETE_SHELL': 'fish'},
                    'delegated',
                )
            )
            cases.append(
                (
                    'powershell-protocol',
                    1,
                    '--option-',
                    True,
                    {
                        '_ARGCOMPLETE_SHELL': 'powershell',
                        '_ARGCOMPLETE_IFS': '\n',
                        '_ARGCOMPLETE_SUPPRESS_SPACE': '0',
                    },
                    'delegated',
                )
            )
            cases.append(
                (
                    'dfs-descriptions',
                    1,
                    '--option-',
                    True,
                    {'_ARGCOMPLETE_DFS': ':'},
                    'delegated',
                )
            )
        cases.append(
            (
                'suppress-space',
                1,
                '--option-0 b',
                True,
                {'_ARGCOMPLETE_SUPPRESS_SPACE': '1'},
                'native',
            )
        )
        cases.append(('modal', 2, 'tr', False, {}, 'native'))

        # Keep delegated filesystem completion deterministic.  Comparing raw
        # argcomplete output over a directory full of generated scripts makes
        # exact parity depend on filesystem iteration order rather than backend
        # behavior.  A unique prefix exercises the same FilesCompleter path
        # while yielding one stable canonical candidate.
        (directory / 'completion-fixture.txt').write_text('fixture\n')

        output_directory = directory / 'completion-output'
        output_directory.mkdir(exist_ok=True)
        raw_rows: list[dict[str, object]] = []

        for scenario, size, line_tail, choice_schema, extra_env, ownership in cases:
            scripts: dict[str, Path] = {}
            for method in methods:
                path = directory / f'{scenario}-{method}-{size}.py'
                if scenario == 'modal':
                    path.write_text(_modal_script(method))
                else:
                    path.write_text(_flat_script(method, size, choices=choice_schema))
                scripts[method] = path

            observations = {method: [] for method in methods}
            outputs = {method: set() for method in methods}
            case_trials = (
                args.delegated_trials if ownership == 'delegated' else args.trials
            )
            for trial in range(case_trials):
                order = list(methods)
                rng.shuffle(order)
                for order_index, method in enumerate(order):
                    out = output_directory / f'out-{scenario}-{method}-{size}-{trial}.txt'
                    elapsed = _run(
                        scripts[method],
                        line_tail,
                        env,
                        out,
                        extra_env=extra_env,
                    )
                    elapsed_ms = elapsed / 1e6
                    observations[method].append(elapsed_ms)
                    raw_rows.append(
                        {
                            'scenario': scenario,
                            'schema_size': size,
                            'ownership': ownership,
                            'trial': trial,
                            'order_index': order_index,
                            'method': method,
                            'elapsed_ns': elapsed,
                            'elapsed_ms': elapsed_ms,
                        }
                    )
                    outputs[method].add(out.read_text() if out.exists() else '')
                    if not args.script_dir:
                        out.unlink(missing_ok=True)

            baseline = 'argparse_argcomplete' if 'argparse_argcomplete' in methods else methods[0]
            base = statistics.median(observations[baseline])
            print(f'\nscenario={scenario}, schema_size={size}, line_tail={line_tail!r}')
            case_report: dict[str, Any] = {
                'scenario': scenario,
                'schema_size': size,
                'line_tail': line_tail,
                'expected_ownership': ownership,
                'trials': case_trials,
                'extra_env': extra_env,
                'methods': {},
            }
            baseline_candidates = None
            if len(outputs[baseline]) == 1:
                baseline_candidates = _candidate_set(next(iter(outputs[baseline])))
            for method in methods:
                median = statistics.median(observations[method])
                stable = len(outputs[method]) == 1
                candidates = _candidate_set(next(iter(outputs[method]))) if stable else set()
                parity = baseline_candidates is None or candidates == baseline_candidates
                exact_output = (
                    len(outputs[baseline]) == 1
                    and stable
                    and next(iter(outputs[method])) == next(iter(outputs[baseline]))
                )
                print(
                    f'  {method:22s} median={median:8.3f} ms  '
                    f'ratio={median / base:6.3f}x parity={parity} exact={exact_output}'
                )
                timing = _timing_summary(observations[method])
                case_report['methods'][method] = {
                    **timing,
                    'ratio': median / base,
                    'stable_output': stable,
                    'candidates': sorted(candidates),
                    'candidate_parity': parity,
                    'exact_output_parity': exact_output,
                }
            report['cases'].append(case_report)
    finally:
        if temp_context is not None:
            temp_context.__exit__(None, None, None)

    if args.raw_output:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        with args.raw_output.open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=list(raw_rows[0]))
            writer.writeheader()
            writer.writerows(raw_rows)
        print('wrote:', args.raw_output)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print('wrote:', args.output_json)

    if report['argcomplete_available']:
        bad = [
            (case['scenario'], method)
            for case in report['cases']
            for method, data in case['methods'].items()
            if method.startswith('kwconf_')
            and (
                not data['candidate_parity']
                or not data['exact_output_parity']
            )
        ]
        if bad:
            raise SystemExit(f'completion output parity failures: {bad!r}')


if __name__ == '__main__':
    main()
