#!/usr/bin/env python3
"""Decompose fresh-process CLI latency into user-visible cold-start phases.

Each observation launches a new Python process. The parent measures true wall
clock latency while the generated child program independently times the work
that happens after the interpreter starts executing the script:

* CLI-library import
* CLI/schema definition
* first parse

The remaining wall-clock time is reported as the process envelope. It includes
interpreter initialization, script loading/compilation, the timer import, output,
and process teardown. A baseline child with no CLI work is measured alongside
the three parser implementations.

The ``no_site`` profile launches Python with ``-S`` but explicitly restores the
parent environment's site-packages paths through ``PYTHONPATH``. This is an
engineering diagnostic for the question "what if site initialization were not
part of startup?"; it is not the normal Python execution mode.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
MARKER = 'KWCONF_COLD_PHASES'


def _csv_list(text: str) -> list[str]:
    values = [item.strip() for item in text.split(',') if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError('expected a non-empty comma-separated list')
    return values


def _int_list(text: str) -> list[int]:
    try:
        values = [int(item) for item in _csv_list(text)]
    except ValueError as ex:
        raise argparse.ArgumentTypeError(str(ex)) from ex
    if any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError('schema sizes must be positive')
    return values


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float('nan')
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _site_package_paths() -> list[str]:
    """Return import roots needed to make ``python -S`` comparable."""
    candidates: list[str] = []
    paths = sysconfig.get_paths()
    for key in ('purelib', 'platlib'):
        value = paths.get(key)
        if value:
            candidates.append(value)
    for value in sys.path:
        if value and ('site-packages' in value or 'dist-packages' in value):
            candidates.append(value)
    return list(dict.fromkeys(candidates))


def _child_env(profile: str) -> dict[str, str]:
    env = os.environ.copy()
    roots = [str(REPO_DPATH)]
    if profile == 'no_site':
        roots.extend(_site_package_paths())
    existing = env.get('PYTHONPATH')
    if existing:
        roots.extend(item for item in existing.split(os.pathsep) if item)
    env['PYTHONPATH'] = os.pathsep.join(dict.fromkeys(roots))
    return env


def _baseline_script() -> str:
    return f'''from time import perf_counter_ns as _clock\n_body_start = _clock()\n_body_end = _clock()\nprint("{MARKER}|{{}}|0|0|0".format(_body_end - _body_start))\n'''


def _script_text(method: str, size: int) -> str:
    if method == 'argparse':
        lines = [
            'from time import perf_counter_ns as _clock',
            '_body_start = _clock()',
            '_import_start = _clock()',
            'import argparse',
            '_import_end = _clock()',
            '_definition_start = _clock()',
            'parser = argparse.ArgumentParser(add_help=False)',
        ]
        for idx in range(size):
            lines.append(
                f"parser.add_argument('--option_{idx}', '--option-{idx}', "
                f"dest='option_{idx}', default='', type=str)"
            )
        lines.extend(
            [
                '_definition_end = _clock()',
                '_parse_start = _clock()',
                'result = parser.parse_args()',
                '_parse_end = _clock()',
                "if result.option_0:",
                "    assert result.option_0 == 'value0'",
            ]
        )
    else:
        backend = {
            'kwconf_python': 'python',
            'kwconf_rust': 'rust',
        }[method]
        lines = [
            'from time import perf_counter_ns as _clock',
            '_body_start = _clock()',
            '_import_start = _clock()',
            'import kwconf',
            '_import_end = _clock()',
            '_definition_start = _clock()',
            'class CLI(kwconf.Config):',
            f"    __cli_backend__ = '{backend}'",
        ]
        for idx in range(size):
            lines.append(f"    option_{idx}: str = ''")
        lines.extend(
            [
                '_definition_end = _clock()',
                '_parse_start = _clock()',
                'result = CLI.cli(autocomplete=False, special_options=False)',
                '_parse_end = _clock()',
                "if result['option_0']:",
                "    assert result['option_0'] == 'value0'",
            ]
        )
    lines.extend(
        [
            '_body_end = _clock()',
            'print(',
            f"    '{MARKER}|{{}}|{{}}|{{}}|{{}}'.format(",
            '        _body_end - _body_start,',
            '        _import_end - _import_start,',
            '        _definition_end - _definition_start,',
            '        _parse_end - _parse_start,',
            '    )',
            ')',
        ]
    )
    return '\n'.join(lines) + '\n'


def _write_scripts(directory: Path, methods: list[str], sizes: list[int]) -> dict[tuple[str, int], Path]:
    scripts: dict[tuple[str, int], Path] = {}
    baseline = directory / 'python_baseline.py'
    baseline.write_text(_baseline_script())
    for size in sizes:
        scripts[('python_baseline', size)] = baseline
        for method in methods:
            path = directory / f'{method}-{size}.py'
            path.write_text(_script_text(method, size))
            scripts[(method, size)] = path
    return scripts


def _command(profile: str, script: Path, argv_size: int, method: str) -> list[str]:
    argv = [] if method == 'python_baseline' else [
        f'--option_{idx}=value{idx}' for idx in range(argv_size)
    ]
    flags = ['-S'] if profile == 'no_site' else []
    return [sys.executable, *flags, str(script), *argv]


def _run(command: list[str], env: dict[str, str]) -> dict[str, int]:
    start = time.perf_counter_ns()
    proc = subprocess.run(
        command,
        cwd=REPO_DPATH,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    total_ns = time.perf_counter_ns() - start
    if proc.returncode != 0:
        raise RuntimeError(
            'cold-start child failed:\n'
            f'  command: {command!r}\n'
            f'  stdout:\n{proc.stdout}\n'
            f'  stderr:\n{proc.stderr}'
        )
    marker_line = next(
        (line for line in reversed(proc.stdout.splitlines()) if line.startswith(MARKER + '|')),
        None,
    )
    if marker_line is None:
        raise RuntimeError(f'child did not emit {MARKER!r}:\n{proc.stdout}')
    fields = marker_line.split('|')
    if len(fields) != 5:
        raise RuntimeError(f'unexpected timing marker: {marker_line!r}')
    body_ns, import_ns, definition_ns, parse_ns = map(int, fields[1:])
    phase_ns = import_ns + definition_ns + parse_ns
    other_body_ns = max(0, body_ns - phase_ns)
    process_envelope_ns = max(0, total_ns - body_ns)
    return {
        'total_ns': total_ns,
        'body_ns': body_ns,
        'process_envelope_ns': process_envelope_ns,
        'import_ns': import_ns,
        'definition_ns': definition_ns,
        'parse_ns': parse_ns,
        'other_body_ns': other_body_ns,
    }


def _summarize(values: list[int]) -> dict[str, float]:
    vals = [float(v) for v in values]
    return {
        'median_ns': statistics.median(vals),
        'mean_ns': statistics.fmean(vals),
        'p10_ns': _percentile(vals, 0.10),
        'p90_ns': _percentile(vals, 0.90),
        'min_ns': min(vals),
    }


def _set_affinity(cpu: int | None) -> set[int] | None:
    if cpu is None:
        return None
    if not hasattr(os, 'sched_getaffinity') or not hasattr(os, 'sched_setaffinity'):
        raise SystemExit('--cpu requires Linux sched_setaffinity support')
    original = set(os.sched_getaffinity(0))
    if cpu not in original:
        raise SystemExit(f'CPU {cpu} is not available: {sorted(original)}')
    os.sched_setaffinity(0, {cpu})
    return original


def _restore_affinity(original: set[int] | None) -> None:
    if original is not None:
        os.sched_setaffinity(0, original)


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=30)
    parser.add_argument('--no-site-trials', type=int, default=10)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--schema-sizes', type=_int_list, default=[16, 64, 256])
    parser.add_argument(
        '--methods',
        type=_csv_list,
        default=['argparse', 'kwconf_python', 'kwconf_rust'],
    )
    parser.add_argument('--profiles', type=_csv_list, default=['default', 'no_site'])
    parser.add_argument('--argv-size', type=int, default=1)
    parser.add_argument('--output-json', type=Path)
    parser.add_argument('--raw-output', type=Path)
    parser.add_argument('--script-dir', type=Path)
    return parser


def main() -> None:
    args = _make_cli().parse_args()
    valid_methods = {'argparse', 'kwconf_python', 'kwconf_rust'}
    valid_profiles = {'default', 'no_site'}
    unknown_methods = set(args.methods) - valid_methods
    unknown_profiles = set(args.profiles) - valid_profiles
    if unknown_methods:
        raise SystemExit(f'unknown methods: {sorted(unknown_methods)}')
    if unknown_profiles:
        raise SystemExit(f'unknown profiles: {sorted(unknown_profiles)}')
    if args.trials < 2:
        raise SystemExit('--trials must be at least 2')
    if args.no_site_trials < 2:
        raise SystemExit('--no-site-trials must be at least 2')
    if args.argv_size < 0:
        raise SystemExit('--argv-size must be non-negative')

    env_by_profile = {profile: _child_env(profile) for profile in args.profiles}
    if args.script_dir is None:
        temp_context = tempfile.TemporaryDirectory(prefix='kwconf-cold-breakdown-')
    else:
        args.script_dir.mkdir(parents=True, exist_ok=True)
        temp_context = None

    original_affinity = _set_affinity(args.cpu)
    try:
        directory = Path(temp_context.name) if temp_context is not None else args.script_dir
        assert directory is not None
        scripts = _write_scripts(directory, args.methods, args.schema_sizes)
        methods = ['python_baseline', *args.methods]

        # Warm the filesystem page cache, not the Python interpreter: every
        # measured observation below still launches a fresh child process.
        for profile in args.profiles:
            for size in args.schema_sizes:
                if args.argv_size > size:
                    continue
                for method in methods:
                    command = _command(profile, scripts[(method, size)], args.argv_size, method)
                    for _ in range(args.warmups):
                        _run(command, env_by_profile[profile])

        rng = random.Random(args.seed)
        rows: list[dict[str, object]] = []
        for profile in args.profiles:
            for size in args.schema_sizes:
                if args.argv_size > size:
                    continue
                profile_trials = (
                    args.no_site_trials if profile == 'no_site' else args.trials
                )
                for trial in range(profile_trials):
                    order = methods.copy()
                    rng.shuffle(order)
                    for order_index, method in enumerate(order):
                        result = _run(
                            _command(profile, scripts[(method, size)], args.argv_size, method),
                            env_by_profile[profile],
                        )
                        rows.append(
                            {
                                'profile': profile,
                                'schema_size': size,
                                'trial': trial,
                                'order_index': order_index,
                                'method': method,
                                **result,
                            }
                        )
    finally:
        _restore_affinity(original_affinity)
        if temp_context is not None:
            temp_context.cleanup()

    summary: dict[str, object] = {
        'python': sys.executable,
        'python_version': sys.version.split()[0],
        'platform': platform.platform(),
        'trials': args.trials,
        'no_site_trials': args.no_site_trials,
        'warmups': args.warmups,
        'argv_size': args.argv_size,
        'site_paths_injected_for_no_site': _site_package_paths(),
        'profiles': {},
    }
    metrics = [
        'total_ns',
        'body_ns',
        'process_envelope_ns',
        'import_ns',
        'definition_ns',
        'parse_ns',
        'other_body_ns',
    ]
    for profile in args.profiles:
        profile_cases = []
        for size in args.schema_sizes:
            if args.argv_size > size:
                continue
            method_data = {}
            for method in methods:
                matching = [
                    row
                    for row in rows
                    if row['profile'] == profile
                    and row['schema_size'] == size
                    and row['method'] == method
                ]
                method_data[method] = {
                    metric: _summarize([int(row[metric]) for row in matching])
                    for metric in metrics
                }
            baseline_ns = method_data['python_baseline']['total_ns']['median_ns']
            for method, data in method_data.items():
                data['delta_vs_python_baseline_ns'] = (
                    data['total_ns']['median_ns'] - baseline_ns
                )
            profile_cases.append({'schema_size': size, 'methods': method_data})
        summary['profiles'][profile] = {
            'python_args': [] if profile == 'default' else ['-S'],
            'description': (
                'normal Python startup'
                if profile == 'default'
                else 'python -S with parent site-packages restored through PYTHONPATH'
            ),
            'cases': profile_cases,
        }

    if args.raw_output is not None:
        args.raw_output.parent.mkdir(parents=True, exist_ok=True)
        with args.raw_output.open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    text = json.dumps(summary, indent=2) + '\n'
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
