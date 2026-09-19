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


def _git_metadata() -> tuple[str, bool | None]:
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
    except (OSError, subprocess.CalledProcessError):
        return 'unknown', None
    else:
        return revision_proc.stdout.strip(), bool(status_proc.stdout.strip())


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


def _write_csv(rows: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    git_revision, git_dirty = _git_metadata()
    metadata = {
        'python': platform.python_version(),
        'platform': platform.platform(),
        'kwconf_version': kwconf.__version__,
        'timerit_version': timerit.__version__,
        'git_revision': git_revision,
        'git_dirty': git_dirty,
        'timestamp_utc': datetime_mod.datetime.now(
            datetime_mod.timezone.utc
        ).isoformat(),
    }
    for row in rows:
        row.update(metadata)
    fieldnames = list(rows[0]) if rows else []
    with output.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
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
        ax.set_title(f'kwconf CLI benchmark: {family}')
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
    _write_csv(rows, args.output)
    print(f'wrote results: {args.output}')
    if not args.no_plot:
        plot_dpath = args.plot_dir
        if plot_dpath is None:
            plot_dpath = args.output.parent / (args.output.stem + '_plots')
        outputs = _plot_rows(rows, plot_dpath)
        for output in outputs:
            print(f'wrote plot: {output}')


if __name__ == '__main__':
    main()
