#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "matplotlib>=3.7",
#   "timerit>=1.1.0",
# ]
# ///
"""Benchmark kwconf CLI overhead against stdlib argparse.

This benchmark intentionally separates parser construction from parser reuse.
That distinction matters for command-line programs: a parser is commonly built
once and parsed once, while libraries and tests may reuse a parser many times.

The benchmark families are:

* ``build``: parser construction as schema size grows.
* ``schema_parse``: parsing one exact long option with a prebuilt parser as
  schema size grows.
* ``argv_parse``: parsing more exact long options with a fixed-size schema.
* ``short_cluster``: parsing increasingly long ``-vvvv`` counter clusters.
* ``fuzzy``: exact versus underscore/hyphen-normalized long options as schema
  size grows.
* ``end_to_end``: construct and parse, including Config initialization for
  kwconf.

Results are written in long-form CSV so they can be compared across revisions
or analyzed with other tools. Plotting creates one figure per benchmark family;
there are intentionally no subplots so each scaling axis remains legible.

CommandLine:
    uv run dev/benchmarks/cli_runtime.py --quick
    uv run dev/benchmarks/cli_runtime.py --output /tmp/kwconf-cli-bench.csv
    uv run dev/benchmarks/cli_runtime.py --families build,schema_parse
    uv run dev/benchmarks/cli_runtime.py --profile kwconf_cli
"""

from __future__ import annotations

import argparse
import cProfile
import csv
import datetime as datetime_mod
import hashlib
import math
import platform
import pstats
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Callable

REPO_DPATH = Path(__file__).resolve().parents[2]
if str(REPO_DPATH) not in sys.path:
    sys.path.insert(0, str(REPO_DPATH))

import timerit

import kwconf
from kwconf import argparse_ext

ALL_FAMILIES = (
    'build',
    'schema_parse',
    'argv_parse',
    'short_cluster',
    'fuzzy',
    'end_to_end',
)

REFERENCE_FAMILY = 'reference'
REFERENCE_METHOD = 'python_startup'


def _git_metadata() -> tuple[str, bool | None, str]:
    """Return revision metadata plus a fingerprint of the working state."""
    try:
        git_prefix = ['git', '-c', f'safe.directory={REPO_DPATH}']
        revision_proc = subprocess.run(
            [*git_prefix, 'rev-parse', '--short=12', 'HEAD'],
            cwd=REPO_DPATH,
            check=True,
            capture_output=True,
            text=True,
        )
        status_proc = subprocess.run(
            [*git_prefix, 'status', '--porcelain'],
            cwd=REPO_DPATH,
            check=True,
            capture_output=True,
            text=True,
        )
        diff_proc = subprocess.run(
            [*git_prefix, 'diff', '--no-ext-diff', '--binary', 'HEAD'],
            cwd=REPO_DPATH,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return 'unknown', None, 'unknown'
    else:
        revision = revision_proc.stdout.strip()
        status = status_proc.stdout
        hasher = hashlib.sha256()
        hasher.update(revision.encode())
        hasher.update(b'\0')
        hasher.update(status.encode())
        hasher.update(b'\0')
        hasher.update(diff_proc.stdout)
        return revision, bool(status.strip()), hasher.hexdigest()[:16]


def _slug(text: str) -> str:
    return ''.join(c if c.isalnum() or c in '-_' else '_' for c in text)


def _parse_int_list(text: str) -> list[int]:
    values = [int(part) for part in text.split(',') if part.strip()]
    if not values:
        raise argparse.ArgumentTypeError('expected a comma-separated int list')
    if any(value < 0 for value in values):
        raise argparse.ArgumentTypeError('benchmark sizes must be non-negative')
    return values


def _parse_family_list(text: str) -> list[str]:
    if text == 'all':
        return list(ALL_FAMILIES)
    values = [part.strip() for part in text.split(',') if part.strip()]
    unknown = sorted(set(values) - set(ALL_FAMILIES))
    if unknown:
        raise argparse.ArgumentTypeError(f'unknown benchmark families: {unknown}')
    return values


def _kwconf_class(num_options: int, *, extras: bool) -> type[kwconf.Config]:
    defaults = {
        f'option_{idx}': kwconf.Value(None, parser=str)
        for idx in range(num_options)
    }
    namespace: dict[str, object] = {'__default__': defaults}
    if not extras:
        namespace['__fuzzy_hyphens__'] = False
        namespace['__short_alias_clusters__'] = False
    suffix = 'Default' if extras else 'NoExtras'
    return type(
        f'BenchConfig{num_options}{suffix}',
        (kwconf.Config,),
        namespace,
    )


def _kwconf_counter_class() -> type[kwconf.Config]:
    return type(
        'BenchCounterConfig',
        (kwconf.Config,),
        {
            '__default__': {
                'verbose': kwconf.Value(
                    0,
                    isflag='counter',
                    short_alias=['v'],
                )
            }
        },
    )


def _argparse_parser(
    num_options: int,
    *,
    aliases: bool,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    for idx in range(num_options):
        canonical = f'--option_{idx}'
        option_strings = [canonical]
        if aliases:
            option_strings.append(f'--option-{idx}')
        parser.add_argument(
            *option_strings,
            dest=f'option_{idx}',
            default=None,
            type=str,
        )
    return parser


def _argparse_counter_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count', default=0)
    return parser


def _extended_fuzzy_parser(num_options: int) -> argparse.ArgumentParser:
    parser = argparse_ext.ExtendedArgumentParser(add_help=False)
    for idx in range(num_options):
        parser.add_argument(f'--option-{idx}')
    return parser


def _argparse_fuzzy_alias_parser(num_options: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    for idx in range(num_options):
        parser.add_argument(
            f'--option-{idx}',
            f'--option_{idx}',
            dest=f'option_{idx}',
        )
    return parser


def _measure(
    func: Callable[[], object],
    *,
    label: str,
    bestof: int,
    min_duration: float,
) -> dict[str, float | int]:
    # Warm interpreter / one-time library caches outside the timed region.
    func()
    ti = timerit.Timerit(
        num=None,
        bestof=bestof,
        verbose=0,
        min_duration=min_duration,
    )
    for timer in ti.reset(label):
        with timer:
            func()
    robust = ti.robust_times()
    if not robust:
        robust = list(ti.times)
    mean = statistics.fmean(robust)
    std = statistics.pstdev(robust) if len(robust) > 1 else 0.0
    return {
        'min_s': min(robust),
        'mean_s': mean,
        'std_s': std,
        'loops': len(ti.times),
        'robust_samples': len(robust),
    }


def _base_row(
    *,
    family: str,
    method: str,
    x_name: str,
    x_value: int,
    schema_size: int,
    argv_size: int,
) -> dict[str, object]:
    return {
        'family': family,
        'method': method,
        'x_name': x_name,
        'x_value': x_value,
        'schema_size': schema_size,
        'argv_size': argv_size,
    }


def _run_case(
    rows: list[dict[str, object]],
    *,
    family: str,
    method: str,
    x_name: str,
    x_value: int,
    schema_size: int,
    argv_size: int,
    func: Callable[[], object],
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    label = f'{family}:{method}:{x_value}'
    if verbose:
        print(f'benchmark {label}')
    stats = _measure(
        func,
        label=label,
        bestof=bestof,
        min_duration=min_duration,
    )
    row = _base_row(
        family=family,
        method=method,
        x_name=x_name,
        x_value=x_value,
        schema_size=schema_size,
        argv_size=argv_size,
    )
    row.update(stats)
    row['bestof'] = bestof
    row['min_duration_s'] = min_duration
    rows.append(row)


def _bench_python_startup(
    rows: list[dict[str, object]],
    *,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    """Measure interpreter process startup once as a run-wide reference."""

    def python_startup() -> None:
        subprocess.run(
            [sys.executable, '-c', 'pass'],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    _run_case(
        rows,
        family=REFERENCE_FAMILY,
        method=REFERENCE_METHOD,
        x_name='reference',
        x_value=1,
        schema_size=0,
        argv_size=0,
        func=python_startup,
        bestof=bestof,
        min_duration=min_duration,
        verbose=verbose,
    )


def _python_startup_seconds(rows: list[dict[str, object]]) -> float | None:
    for row in rows:
        if (
            row.get('family') == REFERENCE_FAMILY
            and row.get('method') == REFERENCE_METHOD
        ):
            return float(row['min_s'])
    return None


def _bench_build(
    rows: list[dict[str, object]],
    schema_sizes: list[int],
    *,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    for num_options in schema_sizes:
        config_default = _kwconf_class(num_options, extras=True)()
        config_no_extras = _kwconf_class(num_options, extras=False)()
        methods = {
            'argparse': lambda n=num_options: _argparse_parser(
                n, aliases=False
            ),
            'argparse_aliases': lambda n=num_options: _argparse_parser(
                n, aliases=True
            ),
            'kwconf_no_extras': config_no_extras.argparse,
            'kwconf_default': config_default.argparse,
        }
        for method, func in methods.items():
            _run_case(
                rows,
                family='build',
                method=method,
                x_name='schema_size',
                x_value=num_options,
                schema_size=num_options,
                argv_size=0,
                func=func,
                bestof=bestof,
                min_duration=min_duration,
                verbose=verbose,
            )


def _bench_schema_parse(
    rows: list[dict[str, object]],
    schema_sizes: list[int],
    *,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    for num_options in schema_sizes:
        if num_options == 0:
            continue
        argv = ['--option_0=value']
        plain = _argparse_parser(num_options, aliases=False)
        aliases = _argparse_parser(num_options, aliases=True)
        config_default = _kwconf_class(num_options, extras=True)()
        config_no_extras = _kwconf_class(num_options, extras=False)()
        kw_default = config_default.argparse()
        kw_no_extras = config_no_extras.argparse()
        methods = {
            'argparse': lambda p=plain, a=argv: p.parse_args(a),
            'argparse_aliases': lambda p=aliases, a=argv: p.parse_args(a),
            'kwconf_no_extras': lambda p=kw_no_extras, a=argv: p.parse_args(a),
            'kwconf_default': lambda p=kw_default, a=argv: p.parse_args(a),
        }
        for method, func in methods.items():
            _run_case(
                rows,
                family='schema_parse',
                method=method,
                x_name='schema_size',
                x_value=num_options,
                schema_size=num_options,
                argv_size=1,
                func=func,
                bestof=bestof,
                min_duration=min_duration,
                verbose=verbose,
            )


def _bench_argv_parse(
    rows: list[dict[str, object]],
    argv_sizes: list[int],
    *,
    schema_size: int,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    schema_size = max(schema_size, max(argv_sizes, default=0))
    plain = _argparse_parser(schema_size, aliases=False)
    aliases = _argparse_parser(schema_size, aliases=True)
    config_default = _kwconf_class(schema_size, extras=True)()
    config_no_extras = _kwconf_class(schema_size, extras=False)()
    kw_default = config_default.argparse()
    kw_no_extras = config_no_extras.argparse()
    for argv_size in argv_sizes:
        argv = [
            f'--option_{idx}=value-{idx}' for idx in range(argv_size)
        ]
        methods = {
            'argparse': lambda p=plain, a=argv: p.parse_args(a),
            'argparse_aliases': lambda p=aliases, a=argv: p.parse_args(a),
            'kwconf_no_extras': lambda p=kw_no_extras, a=argv: p.parse_args(a),
            'kwconf_default': lambda p=kw_default, a=argv: p.parse_args(a),
        }
        for method, func in methods.items():
            _run_case(
                rows,
                family='argv_parse',
                method=method,
                x_name='argv_size',
                x_value=argv_size,
                schema_size=schema_size,
                argv_size=argv_size,
                func=func,
                bestof=bestof,
                min_duration=min_duration,
                verbose=verbose,
            )


def _bench_short_cluster(
    rows: list[dict[str, object]],
    cluster_lengths: list[int],
    *,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    plain = _argparse_counter_parser()
    config_cls = _kwconf_counter_class()
    kw_parser = config_cls().argparse()
    for cluster_len in cluster_lengths:
        if cluster_len <= 0:
            continue
        argv = ['-' + ('v' * cluster_len)]
        methods = {
            'argparse_count': lambda p=plain, a=argv: p.parse_args(a),
            'kwconf_counter': lambda p=kw_parser, a=argv: p.parse_args(a),
        }
        short_normalizer = getattr(
            argparse_ext, '_normalize_short_option_clusters', None
        )
        if short_normalizer is not None:
            methods['short_normalizer_only'] = (
                lambda p=kw_parser, a=argv, normalize=short_normalizer: (
                    normalize(p, a)
                )
            )
        for method, func in methods.items():
            _run_case(
                rows,
                family='short_cluster',
                method=method,
                x_name='cluster_len',
                x_value=cluster_len,
                schema_size=1,
                argv_size=1,
                func=func,
                bestof=bestof,
                min_duration=min_duration,
                verbose=verbose,
            )


def _bench_fuzzy(
    rows: list[dict[str, object]],
    schema_sizes: list[int],
    *,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    for num_options in schema_sizes:
        if num_options == 0:
            continue
        extended = _extended_fuzzy_parser(num_options)
        alias_parser = _argparse_fuzzy_alias_parser(num_options)
        exact_argv = ['--option-0=value']
        fuzzy_argv = ['--option_0=value']
        methods = {
            'argparse_alias': lambda p=alias_parser, a=fuzzy_argv: (
                p.parse_args(a)
            ),
            'extended_exact': lambda p=extended, a=exact_argv: p.parse_args(a),
            'extended_fuzzy': lambda p=extended, a=fuzzy_argv: p.parse_args(a),
            'fuzzy_normalizer_only': lambda p=extended, a=fuzzy_argv: (
                argparse_ext._normalize_fuzzy_option_tokens(p, a)
            ),
        }
        for method, func in methods.items():
            _run_case(
                rows,
                family='fuzzy',
                method=method,
                x_name='schema_size',
                x_value=num_options,
                schema_size=num_options,
                argv_size=1,
                func=func,
                bestof=bestof,
                min_duration=min_duration,
                verbose=verbose,
            )


def _bench_end_to_end(
    rows: list[dict[str, object]],
    schema_sizes: list[int],
    *,
    bestof: int,
    min_duration: float,
    verbose: int,
) -> None:
    for num_options in schema_sizes:
        if num_options:
            argv = ['--option_0=value']
        else:
            argv = []
        config_default = _kwconf_class(num_options, extras=True)
        config_no_extras = _kwconf_class(num_options, extras=False)
        methods = {
            'argparse': lambda n=num_options, a=argv: _argparse_parser(
                n, aliases=False
            ).parse_args(a),
            'argparse_aliases': lambda n=num_options, a=argv: _argparse_parser(
                n, aliases=True
            ).parse_args(a),
            'kwconf_no_extras': lambda c=config_no_extras, a=argv: c.cli(
                argv=a,
                autocomplete=False,
                special_options=False,
            ),
            'kwconf_default': lambda c=config_default, a=argv: c.cli(
                argv=a,
                autocomplete=False,
                special_options=False,
            ),
        }
        for method, func in methods.items():
            _run_case(
                rows,
                family='end_to_end',
                method=method,
                x_name='schema_size',
                x_value=num_options,
                schema_size=num_options,
                argv_size=len(argv),
                func=func,
                bestof=bestof,
                min_duration=min_duration,
                verbose=verbose,
            )


def _add_relative_ratios(rows: list[dict[str, object]]) -> None:
    python_startup_s = _python_startup_seconds(rows)
    baselines = {
        'build': 'argparse',
        'schema_parse': 'argparse',
        'argv_parse': 'argparse',
        'short_cluster': 'argparse_count',
        'fuzzy': 'argparse_alias',
        'end_to_end': 'argparse',
    }
    index: dict[tuple[str, int, str], dict[str, object]] = {}
    for row in rows:
        key = (
            str(row['family']),
            int(row['x_value']),
            str(row['method']),
        )
        index[key] = row
    for row in rows:
        baseline_method = baselines.get(str(row['family']))
        baseline = index.get(
            (str(row['family']), int(row['x_value']), str(baseline_method))
        )
        if baseline is None:
            row['ratio_vs_argparse'] = math.nan
        else:
            denom = float(baseline['min_s'])
            row['ratio_vs_argparse'] = float(row['min_s']) / denom
        if python_startup_s is None:
            row['ratio_vs_python_startup'] = math.nan
        else:
            row['ratio_vs_python_startup'] = (
                float(row['min_s']) / python_startup_s
            )


def _annotate_rows(rows: list[dict[str, object]]) -> str:
    """Attach immutable run metadata and return the run identifier."""
    git_revision, git_dirty, git_state_hash = _git_metadata()
    timestamp = datetime_mod.datetime.now(datetime_mod.timezone.utc).isoformat()
    run_id = f'{timestamp}@{git_revision}:{git_state_hash}'
    metadata = {
        'run_id': run_id,
        'python': platform.python_version(),
        'platform': platform.platform(),
        'kwconf_version': kwconf.__version__,
        'timerit_version': timerit.__version__,
        'git_revision': git_revision,
        'git_dirty': git_dirty,
        'git_state_hash': git_state_hash,
        'timestamp_utc': timestamp,
    }
    for row in rows:
        row.update(metadata)
    return run_id


def _read_csv(output: Path) -> list[dict[str, str]]:
    if not output.exists():
        return []
    with output.open(newline='') as file:
        return list(csv.DictReader(file))


def _append_csv(rows: list[dict[str, object]], output: Path) -> None:
    """Append measurements, preserving older runs in the same CSV."""
    if not rows:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0])
    if output.exists() and output.stat().st_size:
        with output.open(newline='') as file:
            reader = csv.reader(file)
            old_fieldnames = next(reader)
        if old_fieldnames != fieldnames:
            # Benchmark CSVs are intentionally long lived. If the benchmark
            # gains metadata columns, preserve old measurements while doing a
            # one-time schema widening before returning to append-only writes.
            old_rows = _read_csv(output)
            merged = list(old_fieldnames)
            merged.extend(name for name in fieldnames if name not in merged)
            if any(name not in merged for name in fieldnames):  # pragma: no cover
                raise AssertionError('failed to merge benchmark CSV schema')
            with output.open('w', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=merged)
                writer.writeheader()
                writer.writerows(old_rows)
            fieldnames = merged
        with output.open('a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writerows(rows)
    else:
        with output.open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


def _case_key(row: dict[str, object]) -> tuple[str, ...]:
    fields = (
        'family',
        'method',
        'x_name',
        'x_value',
        'schema_size',
        'argv_size',
        'bestof',
        'min_duration_s',
    )
    return tuple(str(row.get(field, '')) for field in fields)


def _run_groups(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        run_id = str(row.get('run_id') or row.get('timestamp_utc') or '')
        groups.setdefault(run_id, []).append(row)
    return groups


def _compatible_run(
    current_rows: list[dict[str, object]],
    history_rows: list[dict[str, object]],
    selector: str,
) -> tuple[str | None, list[dict[str, object]]]:
    """Resolve a baseline run with comparable environment/cases."""
    if not history_rows or selector == 'none':
        return None, []
    groups = _run_groups(history_rows)
    current = current_rows[0]
    environment = (str(current.get('python')), str(current.get('platform')))

    def compatible(rows: list[dict[str, object]]) -> bool:
        if not rows:
            return False
        candidate_env = (str(rows[0].get('python')), str(rows[0].get('platform')))
        if candidate_env != environment:
            return False
        current_keys = {_case_key(row) for row in current_rows}
        candidate_keys = {_case_key(row) for row in rows}
        return bool(current_keys & candidate_keys)

    candidates = [(run_id, rows) for run_id, rows in groups.items() if compatible(rows)]
    if selector == 'previous':
        if not candidates:
            return None, []
        return candidates[-1]

    matches = []
    for run_id, rows in candidates:
        first = rows[0]
        haystacks = (
            run_id,
            str(first.get('git_revision', '')),
            str(first.get('git_state_hash', '')),
            str(first.get('kwconf_version', '')),
            str(first.get('timestamp_utc', '')),
        )
        if any(value.startswith(selector) for value in haystacks):
            matches.append((run_id, rows))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f'no compatible benchmark run matches --compare-to={selector!r}')
    raise SystemExit(f'ambiguous --compare-to={selector!r}; matches {len(matches)} runs')


def _comparison_rows(
    baseline_rows: list[dict[str, object]],
    current_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    baseline_index = {_case_key(row): row for row in baseline_rows}
    comparisons = []
    for current in current_rows:
        baseline = baseline_index.get(_case_key(current))
        if baseline is None:
            continue
        before = float(baseline['min_s'])
        after = float(current['min_s'])
        ratio = after / before
        comparisons.append({
            'family': current['family'],
            'method': current['method'],
            'x_name': current['x_name'],
            'x_value': current['x_value'],
            'baseline_run_id': baseline.get('run_id') or baseline.get('timestamp_utc'),
            'current_run_id': current.get('run_id'),
            'baseline_git_revision': baseline.get('git_revision'),
            'current_git_revision': current.get('git_revision'),
            'baseline_git_state_hash': baseline.get('git_state_hash'),
            'current_git_state_hash': current.get('git_state_hash'),
            'baseline_min_s': before,
            'current_min_s': after,
            'ratio_current_vs_baseline': ratio,
            'percent_change': (ratio - 1.0) * 100.0,
        })
    return comparisons


def _write_comparison_csv(rows: list[dict[str, object]], output: Path) -> None:
    if not rows:
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _plot_rows(rows: list[dict[str, object]], plot_dpath: Path) -> list[Path]:
    # This benchmark only writes image files. Do not inherit a user rc file's
    # interactive backend (for example QtAgg), because the isolated PEP 723
    # environment intentionally does not depend on GUI toolkit bindings.
    import matplotlib

    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt

    plot_dpath.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    python_startup_s = _python_startup_seconds(rows)
    for family in ALL_FAMILIES:
        family_rows = [row for row in rows if row['family'] == family]
        if not family_rows:
            continue
        x_name = str(family_rows[0]['x_name'])
        methods = sorted({str(row['method']) for row in family_rows})
        fig, ax = plt.subplots()
        for method in methods:
            method_rows = sorted(
                (row for row in family_rows if row['method'] == method),
                key=lambda row: int(row['x_value']),
            )
            xs = [int(row['x_value']) for row in method_rows]
            ys = [float(row['min_s']) * 1e6 for row in method_rows]
            ax.plot(xs, ys, marker='o', label=method)
        ax.set_xlabel(x_name)
        ax.set_ylabel('minimum robust time (microseconds)')
        title = f'kwconf CLI benchmark: {family}'
        if python_startup_s is not None:
            title += (
                f'\nPython startup reference: '
                f'{python_startup_s * 1e3:.2f} ms'
            )
        ax.set_title(title)
        if all(int(row['x_value']) > 0 for row in family_rows):
            ax.set_xscale('log', base=2)
        ax.set_yscale('log')
        ax.legend()
        fig.tight_layout()
        output = plot_dpath / f'{_slug(family)}.png'
        fig.savefig(output, dpi=160)
        plt.close(fig)
        outputs.append(output)
    return outputs



def _plot_comparison_rows(
    rows: list[dict[str, object]], plot_dpath: Path
) -> list[Path]:
    if not rows:
        return []
    import matplotlib

    matplotlib.use('Agg', force=True)
    import matplotlib.pyplot as plt

    plot_dpath.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    python_startup_ratio = next(
        (
            float(row['ratio_current_vs_baseline'])
            for row in rows
            if row.get('family') == REFERENCE_FAMILY
            and row.get('method') == REFERENCE_METHOD
        ),
        None,
    )
    for family in ALL_FAMILIES:
        family_rows = [row for row in rows if row['family'] == family]
        if not family_rows:
            continue
        methods = sorted({str(row['method']) for row in family_rows})
        fig, ax = plt.subplots()
        for method in methods:
            method_rows = sorted(
                (row for row in family_rows if row['method'] == method),
                key=lambda row: int(row['x_value']),
            )
            xs = [int(row['x_value']) for row in method_rows]
            ys = [float(row['ratio_current_vs_baseline']) for row in method_rows]
            ax.plot(xs, ys, marker='o', label=method)
        ax.axhline(1.0, linewidth=1)
        ax.set_xlabel(str(family_rows[0]['x_name']))
        ax.set_ylabel('current / baseline runtime')
        title = f'kwconf CLI comparison: {family}'
        if python_startup_ratio is not None:
            title += (
                f'\nPython startup control: {python_startup_ratio:.3f}x '
                '(current / baseline)'
            )
        ax.set_title(title)
        if all(int(row['x_value']) > 0 for row in family_rows):
            ax.set_xscale('log', base=2)
        ax.legend()
        fig.tight_layout()
        output = plot_dpath / f'{_slug(family)}_comparison.png'
        fig.savefig(output, dpi=160)
        plt.close(fig)
        outputs.append(output)
    return outputs


def _format_seconds(seconds: float) -> str:
    if seconds >= 1:
        return f'{seconds:.3f} s'
    if seconds >= 1e-3:
        return f'{seconds * 1e3:.3f} ms'
    return f'{seconds * 1e6:.3f} us'


def _print_current_reference_summary(rows: list[dict[str, object]]) -> None:
    """Show the absolute current gap to the closest argparse baseline."""
    startup = _python_startup_seconds(rows)
    if startup is not None:
        print(f'python startup reference: {_format_seconds(startup)}')

    comparisons = {
        'build': ('kwconf_default', 'argparse_aliases'),
        'schema_parse': ('kwconf_default', 'argparse_aliases'),
        'argv_parse': ('kwconf_default', 'argparse_aliases'),
        'end_to_end': ('kwconf_default', 'argparse_aliases'),
        'short_cluster': ('kwconf_counter', 'argparse_count'),
        'fuzzy': ('extended_fuzzy', 'argparse_alias'),
    }
    print('current reference summary (largest measured point):')
    for family, (target_method, baseline_method) in comparisons.items():
        family_rows = [r for r in rows if str(r.get('family')) == family]
        target_rows = [r for r in family_rows if r.get('method') == target_method]
        baseline_rows = [r for r in family_rows if r.get('method') == baseline_method]
        if not target_rows or not baseline_rows:
            continue
        target_by_x = {int(r['x_value']): r for r in target_rows}
        baseline_by_x = {int(r['x_value']): r for r in baseline_rows}
        common_x = sorted(set(target_by_x) & set(baseline_by_x))
        if not common_x:
            continue
        x_value = common_x[-1]
        target_s = float(target_by_x[x_value]['min_s'])
        baseline_s = float(baseline_by_x[x_value]['min_s'])
        ratio = target_s / baseline_s
        delta = target_s - baseline_s
        startup_text = ''
        if startup:
            startup_text = f', {target_s / startup * 100:.2f}% of python startup'
        print(
            f'  {family:14s} @{x_value:<5d} '
            f'{_format_seconds(target_s):>10s} vs '
            f'{_format_seconds(baseline_s):>10s}  '
            f'{ratio:5.2f}x, delta {_format_seconds(delta)}'
            f'{startup_text}'
        )


def _print_comparison_summary(rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    print('comparison summary (current / baseline; <1 is faster):')
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (str(row['family']), str(row['method']))
        grouped.setdefault(key, []).append(float(row['ratio_current_vs_baseline']))
    for (family, method), ratios in sorted(grouped.items()):
        geometric_mean = math.exp(statistics.fmean(math.log(r) for r in ratios))
        percent = (geometric_mean - 1.0) * 100.0
        print(f'  {family:14s} {method:22s} {geometric_mean:8.3f}x ({percent:+7.2f}%)')

def _profile_target(name: str, schema_size: int, argv_size: int) -> Callable:
    schema_size = max(schema_size, argv_size)
    argv = [f'--option_{idx}=value-{idx}' for idx in range(argv_size)]
    if name == 'kwconf_cli':
        config_cls = _kwconf_class(schema_size, extras=True)
        return lambda: config_cls.cli(
            argv=argv,
            autocomplete=False,
            special_options=False,
        )
    if name == 'kwconf_build':
        config = _kwconf_class(schema_size, extras=True)()
        return config.argparse
    if name == 'kwconf_parse':
        parser = _kwconf_class(schema_size, extras=True)().argparse()
        return lambda: parser.parse_args(argv)
    if name == 'short_normalizer':
        normalize = getattr(
            argparse_ext, '_normalize_short_option_clusters', None
        )
        if normalize is None:
            raise RuntimeError(
                'this kwconf revision has no short-cluster normalizer'
            )
        parser = _kwconf_counter_class()().argparse()
        short_argv = ['-' + ('v' * max(1, argv_size))]
        return lambda: normalize(parser, short_argv)
    if name == 'fuzzy_normalizer':
        parser = _extended_fuzzy_parser(schema_size)
        fuzzy_argv = ['--option_0=value']
        return lambda: argparse_ext._normalize_fuzzy_option_tokens(
            parser, fuzzy_argv
        )
    raise KeyError(name)


def _run_profile(args: argparse.Namespace) -> None:
    func = _profile_target(
        args.profile,
        schema_size=args.profile_schema_size,
        argv_size=args.profile_argv_size,
    )
    func()
    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(args.profile_repeat):
        func()
    profiler.disable()
    stats = pstats.Stats(profiler).strip_dirs().sort_stats('cumtime')
    stats.print_stats(args.profile_top)
    if args.profile_output is not None:
        args.profile_output.parent.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(args.profile_output)
        print(f'wrote profile: {args.profile_output}')


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--families',
        type=_parse_family_list,
        default=list(ALL_FAMILIES),
        help='comma-separated benchmark families, or all',
    )
    parser.add_argument(
        '--schema-sizes',
        type=_parse_int_list,
        default=[1, 4, 16, 64, 256, 1024],
    )
    parser.add_argument(
        '--argv-sizes',
        type=_parse_int_list,
        default=[0, 1, 4, 16, 64, 256],
    )
    parser.add_argument(
        '--cluster-lengths',
        type=_parse_int_list,
        default=[1, 2, 4, 8, 16, 32, 64, 128],
    )
    parser.add_argument(
        '--argv-schema-size',
        type=int,
        default=256,
        help='fixed schema size for argv_parse',
    )
    parser.add_argument('--bestof', type=int, default=5)
    parser.add_argument('--min-duration', type=float, default=0.08)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--verbose', '-v', action='count', default=0)
    default_output = (
        REPO_DPATH / 'dev' / 'benchmarks' / '_results' / 'cli_runtime.csv'
    )
    parser.add_argument('--output', type=Path, default=default_output)
    parser.add_argument(
        '--compare-to',
        default='previous',
        help=(
            "baseline run selector: 'previous', 'none', or a prefix of a "
            "run id, git revision, git-state hash, version, or timestamp"
        ),
    )
    parser.add_argument('--plot-dir', type=Path, default=None)
    parser.add_argument('--no-plot', action='store_true')
    parser.add_argument(
        '--profile',
        choices=[
            'kwconf_cli',
            'kwconf_build',
            'kwconf_parse',
            'short_normalizer',
            'fuzzy_normalizer',
        ],
        default=None,
    )
    parser.add_argument('--profile-schema-size', type=int, default=256)
    parser.add_argument('--profile-argv-size', type=int, default=1)
    parser.add_argument('--profile-repeat', type=int, default=200)
    parser.add_argument('--profile-top', type=int, default=40)
    parser.add_argument('--profile-output', type=Path, default=None)
    return parser


def main() -> None:
    parser = _make_cli()
    args = parser.parse_args()
    if args.profile is not None:
        _run_profile(args)
        return

    if args.quick:
        args.schema_sizes = [1, 16, 64, 256]
        args.argv_sizes = [0, 1, 16, 64]
        args.cluster_lengths = [1, 4, 16, 64]
        args.min_duration = min(args.min_duration, 0.02)

    rows: list[dict[str, object]] = []
    common = {
        'bestof': args.bestof,
        'min_duration': args.min_duration,
        'verbose': args.verbose,
    }
    _bench_python_startup(rows, **common)
    for family in args.families:
        if family == 'build':
            _bench_build(rows, args.schema_sizes, **common)
        elif family == 'schema_parse':
            _bench_schema_parse(rows, args.schema_sizes, **common)
        elif family == 'argv_parse':
            _bench_argv_parse(
                rows,
                args.argv_sizes,
                schema_size=args.argv_schema_size,
                **common,
            )
        elif family == 'short_cluster':
            _bench_short_cluster(rows, args.cluster_lengths, **common)
        elif family == 'fuzzy':
            _bench_fuzzy(rows, args.schema_sizes, **common)
        elif family == 'end_to_end':
            _bench_end_to_end(rows, args.schema_sizes, **common)
        else:  # pragma: no cover
            raise AssertionError(family)

    _add_relative_ratios(rows)
    history_rows = _read_csv(args.output)
    run_id = _annotate_rows(rows)
    baseline_run_id, baseline_rows = _compatible_run(
        rows, history_rows, args.compare_to
    )
    comparisons = _comparison_rows(baseline_rows, rows)
    _append_csv(rows, args.output)
    print(f'appended run: {run_id}')
    print(f'wrote history: {args.output}')
    _print_current_reference_summary(rows)
    if baseline_run_id is not None:
        print(f'comparison baseline: {baseline_run_id}')
        comparison_output = args.output.with_name(
            args.output.stem + '_comparison.csv'
        )
        _write_comparison_csv(comparisons, comparison_output)
        print(f'wrote comparison: {comparison_output}')
        _print_comparison_summary(comparisons)
    if not args.no_plot:
        plot_dpath = args.plot_dir
        if plot_dpath is None:
            plot_dpath = args.output.parent / (args.output.stem + '_plots')
        outputs = _plot_rows(rows, plot_dpath)
        if comparisons:
            outputs += _plot_comparison_rows(
                comparisons, plot_dpath / 'comparison'
            )
        for output in outputs:
            print(f'wrote plot: {output}')


if __name__ == '__main__':
    main()
