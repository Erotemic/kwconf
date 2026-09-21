#!/usr/bin/env python3
"""Measure complete fresh-process CLI latency with raw interleaved trials.

This is the headline benchmark for the Rust-backed kwconf campaign. Unlike the
microbenchmark harness, every observation launches a new Python process and
runs a complete parser/config declaration + parse + immediate exit workload.
The methods are shuffled within each trial round so slow machine drift is less
likely to systematically favor one implementation.

Example:
    python dev/benchmarks/cli_startup.py --quick
    python dev/benchmarks/cli_startup.py --trials 100 --cpu 4
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as datetime_mod
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
RESULT_DPATH = REPO_DPATH / 'dev' / 'benchmarks' / '_results'


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


def _git(command: list[str]) -> str:
    try:
        result = subprocess.run(
            ['git', *command],
            cwd=REPO_DPATH,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ''
    return result.stdout.strip()


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


def _append_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    exists = path.exists() and path.stat().st_size > 0
    with path.open('a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def _script_text(method: str, size: int, style: str) -> str:
    if method == 'argparse':
        lines = [
            'import argparse',
            '',
            'def main():',
            '    parser = argparse.ArgumentParser(add_help=False)',
        ]
        for idx in range(size):
            lines.append(
                f"    parser.add_argument('--option_{idx}', '--option-{idx}', "
                f"dest='option_{idx}', default='', type=str)"
            )
        lines.extend(
            [
                '    result = parser.parse_args()',
                "    if hasattr(result, 'option_0') and result.option_0:",
                "        assert result.option_0 == 'value0'",
                '',
                "if __name__ == '__main__':",
                '    main()',
            ]
        )
        return '\n'.join(lines) + '\n'

    backend = {
        'kwconf_python': 'python',
        'kwconf_rust': 'rust',
        'kwconf_auto': 'auto',
    }[method]
    lines = ['import kwconf', '', 'class CLI(kwconf.Config):']
    lines.append(f"    __cli_backend__ = '{backend}'")
    if style == 'typed':
        for idx in range(size):
            lines.append(f"    option_{idx}: str = ''")
    else:
        lines.append('    __default__ = {')
        for idx in range(size):
            lines.append(
                f"        'option_{idx}': kwconf.Value(None, parser=str),"
            )
        lines.append('    }')
    lines.extend(
        [
            '',
            'def main():',
            '    result = CLI.cli(',
            '        autocomplete=False, special_options=False,',
            '    )',
            "    if result['option_0']:",
            "        assert result['option_0'] == 'value0'",
            '',
            "if __name__ == '__main__':",
            '    main()',
        ]
    )
    return '\n'.join(lines) + '\n'


def _write_scripts(
    directory: Path, methods: list[str], sizes: list[int], style: str
) -> dict[tuple[str, int], Path]:
    scripts = {}
    for size in sizes:
        for method in methods:
            path = directory / f'{method}-{style}-{size}.py'
            path.write_text(_script_text(method, size, style))
            scripts[(method, size)] = path
    return scripts


def _command(script: Path, argv_size: int) -> list[str]:
    argv = [f'--option_{idx}=value{idx}' for idx in range(argv_size)]
    return [sys.executable, str(script), *argv]


def _run(command: list[str], env: dict[str, str]) -> int:
    start = time.perf_counter_ns()
    try:
        subprocess.run(
            command,
            cwd=REPO_DPATH,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as ex:
        stderr = (ex.stderr or b'').decode(errors='replace')
        raise SystemExit(
            'benchmark child failed:\n'
            f'  command: {command!r}\n'
            f'  stderr:\n{stderr}'
        ) from ex
    return time.perf_counter_ns() - start


def _cpu_model() -> str:
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors='replace').splitlines():
            if line.startswith('model name') and ':' in line:
                return line.split(':', 1)[1].strip()
    return platform.processor()


def _affinity_text() -> str:
    if hasattr(os, 'sched_getaffinity'):
        return ','.join(map(str, sorted(os.sched_getaffinity(0))))
    return ''


def _set_affinity(cpu: int | None) -> set[int] | None:
    if cpu is None:
        return None
    if not hasattr(os, 'sched_getaffinity') or not hasattr(os, 'sched_setaffinity'):
        raise SystemExit('--cpu requires Linux sched_setaffinity support')
    original = set(os.sched_getaffinity(0))
    if cpu not in original:
        raise SystemExit(
            f'CPU {cpu} is not in this process affinity mask: {sorted(original)}'
        )
    os.sched_setaffinity(0, {cpu})
    return original


def _restore_affinity(original: set[int] | None) -> None:
    if original is not None:
        os.sched_setaffinity(0, original)


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--trials', type=int, default=50)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--cpu', type=int)
    parser.add_argument(
        '--schema-sizes',
        type=_int_list,
        default=[1, 16, 64, 256],
    )
    parser.add_argument(
        '--methods',
        type=_csv_list,
        default=['argparse', 'kwconf_python', 'kwconf_rust', 'kwconf_auto'],
    )
    parser.add_argument('--style', choices=['typed', 'value'], default='typed')
    parser.add_argument(
        '--argv-size',
        type=int,
        default=1,
        help='number of supplied option=value tokens per child invocation',
    )
    parser.add_argument(
        '--raw-output',
        type=Path,
        default=RESULT_DPATH / 'cli_startup_trials.csv',
    )
    parser.add_argument(
        '--summary-output',
        type=Path,
        default=RESULT_DPATH / 'cli_startup_summary.csv',
    )
    parser.add_argument(
        '--no-append',
        action='store_true',
        help='overwrite output files instead of appending a run to history',
    )
    parser.add_argument(
        '--script-dir',
        type=Path,
        help='keep generated benchmark programs here for inspection',
    )
    return parser


def main() -> None:
    args = _make_cli().parse_args()
    if args.quick:
        args.trials = min(args.trials, 12)
        args.warmups = min(args.warmups, 1)
    if args.trials < 2:
        raise SystemExit('--trials must be at least 2')
    if 'argparse' not in args.methods:
        raise SystemExit('--methods must include argparse as the baseline')

    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )

    run_id = datetime_mod.datetime.now(datetime_mod.timezone.utc).strftime(
        '%Y%m%dT%H%M%SZ'
    ) + '-' + uuid.uuid4().hex[:8]
    metadata = {
        'run_id': run_id,
        'timestamp_utc': datetime_mod.datetime.now(
            datetime_mod.timezone.utc
        ).isoformat(),
        'python': sys.version.split()[0],
        'python_executable': sys.executable,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'cpu_model': _cpu_model(),
        'affinity': _affinity_text(),
        'git_revision': _git(['rev-parse', '--short=12', 'HEAD']),
        'git_dirty': bool(_git(['status', '--porcelain'])),
        'style': args.style,
        'argv_size': args.argv_size,
        'cpu': '' if args.cpu is None else args.cpu,
        'seed': args.seed,
        'source_shape': 'generated-real-cli',
    }

    if args.script_dir is None:
        script_context = tempfile.TemporaryDirectory(prefix='kwconf-startup-')
    else:
        args.script_dir.mkdir(parents=True, exist_ok=True)
        script_context = contextlib.nullcontext(str(args.script_dir))

    original_affinity = _set_affinity(args.cpu)
    try:
        with script_context as temp:
            scripts = _write_scripts(
                Path(temp), args.methods, args.schema_sizes, args.style
            )
            # Warm filesystem/import caches without contributing observations.
            for size in args.schema_sizes:
                for method in args.methods:
                    if args.argv_size > size:
                        continue
                    command = _command(scripts[(method, size)], args.argv_size)
                    for _ in range(args.warmups):
                        _run(command, env)

            rng = random.Random(args.seed)
            rows: list[dict[str, object]] = []
            for size in args.schema_sizes:
                if args.argv_size > size:
                    continue
                for trial in range(args.trials):
                    order = list(args.methods)
                    rng.shuffle(order)
                    for order_index, method in enumerate(order):
                        elapsed_ns = _run(
                            _command(scripts[(method, size)], args.argv_size),
                            env,
                        )
                        rows.append(
                            {
                                **metadata,
                                'schema_size': size,
                                'trial': trial,
                                'order_index': order_index,
                                'method': method,
                                'elapsed_ns': elapsed_ns,
                            }
                        )
    finally:
        _restore_affinity(original_affinity)

    summary_rows: list[dict[str, object]] = []
    for size in args.schema_sizes:
        if args.argv_size > size:
            continue
        by_method: dict[str, list[float]] = {}
        by_trial: dict[str, dict[int, float]] = {}
        for method in args.methods:
            values = [
                float(row['elapsed_ns'])
                for row in rows
                if row['schema_size'] == size and row['method'] == method
            ]
            by_method[method] = values
            by_trial[method] = {
                int(row['trial']): float(row['elapsed_ns'])
                for row in rows
                if row['schema_size'] == size and row['method'] == method
            }
        baseline = by_method['argparse']
        baseline_median = statistics.median(baseline)
        for method in args.methods:
            values = by_method[method]
            paired = [
                by_trial[method][trial] - by_trial['argparse'][trial]
                for trial in sorted(by_trial['argparse'])
            ]
            median = statistics.median(values)
            summary_rows.append(
                {
                    **metadata,
                    'schema_size': size,
                    'method': method,
                    'trials': len(values),
                    'min_ns': min(values),
                    'p10_ns': _percentile(values, 0.10),
                    'median_ns': median,
                    'mean_ns': statistics.fmean(values),
                    'p90_ns': _percentile(values, 0.90),
                    'stdev_ns': statistics.stdev(values),
                    'ratio_vs_argparse_median': median / baseline_median,
                    'paired_delta_median_ns': statistics.median(paired),
                    'paired_delta_p10_ns': _percentile(paired, 0.10),
                    'paired_delta_p90_ns': _percentile(paired, 0.90),
                }
            )

    if args.no_append:
        for path in [args.raw_output, args.summary_output]:
            if path.exists():
                path.unlink()
    _append_csv(args.raw_output, rows)
    _append_csv(args.summary_output, summary_rows)

    print(f'run_id: {run_id}')
    print(f'python: {sys.executable}')
    print(f'style: {args.style}; trials per case: {args.trials}')
    if args.script_dir is not None:
        print(f'generated scripts: {args.script_dir}')
    if args.cpu is not None:
        print(f'CPU affinity: {args.cpu}')
    for size in args.schema_sizes:
        if args.argv_size > size:
            continue
        print(f'\nschema_size={size}, argv_size={args.argv_size}')
        for row in summary_rows:
            if row['schema_size'] != size:
                continue
            median_ms = float(row['median_ns']) / 1e6
            delta_ms = float(row['paired_delta_median_ns']) / 1e6
            ratio = float(row['ratio_vs_argparse_median'])
            print(
                f"  {str(row['method']):16s} median={median_ms:8.3f} ms  "
                f"ratio={ratio:6.3f}x  paired_delta={delta_ms:+7.3f} ms"
            )
    print(f'\nraw trials: {args.raw_output}')
    print(f'summary:    {args.summary_output}')


if __name__ == '__main__':
    main()
