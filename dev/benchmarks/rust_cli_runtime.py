#!/usr/bin/env python3
"""Measure the experimental Rust CLI backend against argparse and kwconf.

This benchmark is intentionally separate from ``cli_runtime.py`` while the
backend is experimental.  It measures both hot/warm costs and one-shot process
startup so an extension cannot appear attractive by hiding its import cost.

CommandLine:
    python dev/rust_backend/build_backend.py --release
    python dev/benchmarks/rust_cli_runtime.py --quick

Use the same Python executable for the build and benchmark. In particular, do
not run this file as a PEP 723 ``uv run`` script: that would benchmark an
isolated environment that does not contain the wheel just installed by the
build helper.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

REPO_DPATH = Path(__file__).resolve().parents[2]
if str(REPO_DPATH) not in sys.path:
    sys.path.insert(0, str(REPO_DPATH))

import kwconf
from kwconf import _rust


def _parse_int_list(text: str) -> list[int]:
    values = [int(part) for part in text.split(',') if part.strip()]
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError('expected positive comma-separated ints')
    return values


def _kwconf_class(num_options: int, backend: str) -> type[kwconf.Config]:
    namespace: dict[str, object] = {
        '__default__': {
            f'option_{idx}': kwconf.Value(None, parser=str)
            for idx in range(num_options)
        },
        '__cli_backend__': backend,
    }
    return type(f'RustBenchConfig{num_options}{backend}', (kwconf.Config,), namespace)


def _kwconf_typed_class(num_options: int, backend: str) -> type[kwconf.Config]:
    names = [f'option_{idx}' for idx in range(num_options)]
    namespace: dict[str, object] = {
        '__annotations__': {name: str for name in names},
        '__cli_backend__': backend,
    }
    namespace.update({name: '' for name in names})
    return type(
        f'RustTypedBenchConfig{num_options}{backend}',
        (kwconf.Config,),
        namespace,
    )


def _argparse_parser(num_options: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    for idx in range(num_options):
        parser.add_argument(
            f'--option_{idx}',
            f'--option-{idx}',
            dest=f'option_{idx}',
            default=None,
            type=str,
        )
    return parser


def _measure(
    func: Callable[[], object], *, bestof: int, min_duration: float
) -> tuple[float, float, int]:
    """Measure per-call latency with a stdlib-only adaptive harness.

    ``timerit`` is intentionally not used here. This benchmark must execute in
    the exact interpreter where the locally built extension was installed, and
    a PEP 723 dependency block would make ``uv run`` create an isolated Python
    environment that cannot see that extension.
    """
    func()

    target_sample = max(0.002, min_duration / max(bestof, 1))
    number = 1
    while True:
        start = time.perf_counter()
        for _ in range(number):
            func()
        elapsed = time.perf_counter() - start
        if elapsed >= target_sample or number >= (1 << 24):
            break
        if elapsed <= 0:
            number *= 10
        else:
            scale = max(2, min(10, int(target_sample / elapsed)))
            number *= scale

    samples: list[float] = []
    for _ in range(bestof):
        start = time.perf_counter()
        for _ in range(number):
            func()
        elapsed = time.perf_counter() - start
        samples.append(elapsed / number)
    return min(samples), statistics.fmean(samples), number * bestof


def _run_process(args: list[str]) -> None:
    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = (
        str(REPO_DPATH)
        if not old_pythonpath
        else str(REPO_DPATH) + os.pathsep + old_pythonpath
    )
    subprocess.run(
        args,
        cwd=REPO_DPATH,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _record(
    rows: list[dict[str, object]],
    family: str,
    method: str,
    schema_size: int,
    func: Callable[[], object],
    *,
    bestof: int,
    min_duration: float,
) -> None:
    minimum, mean, loops = _measure(
        func, bestof=bestof, min_duration=min_duration
    )
    rows.append(
        {
            'family': family,
            'method': method,
            'schema_size': schema_size,
            'min_s': minimum,
            'mean_s': mean,
            'loops': loops,
        }
    )


def _warm_cases(
    rows: list[dict[str, object]],
    schema_sizes: list[int],
    *,
    bestof: int,
    min_duration: float,
) -> None:
    for size in schema_sizes:
        argv = ['--option_0=value']
        argparse_parser = _argparse_parser(size)
        py_cls = _kwconf_class(size, 'python')
        rust_cls = _kwconf_class(size, 'rust')
        auto_cls = _kwconf_class(size, 'auto')
        py_config = py_cls()
        rust_config = rust_cls()
        typed_py_cls = _kwconf_typed_class(size, 'python')
        typed_rust_cls = _kwconf_typed_class(size, 'rust')
        typed_auto_cls = _kwconf_typed_class(size, 'auto')
        kw_parser = py_config.argparse()

        _rust.clear_cache()
        compiled = _rust.compile_config(rust_config)
        completion_index = _rust.compile_completion_index(rust_config)

        _record(
            rows,
            'hot_parse',
            'argparse',
            size,
            lambda p=argparse_parser, a=argv: p.parse_args(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'hot_parse',
            'kwconf_argparse',
            size,
            lambda p=kw_parser, a=argv: p.parse_args(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'hot_parse',
            'rust_pyo3_parse',
            size,
            lambda c=compiled, a=argv: c.parser.parse(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'hot_parse',
            'rust_bridge',
            size,
            lambda c=rust_config, p=compiled, a=argv: _rust.parse_compiled(
                c, p, a, strict=True
            ),
            bestof=bestof,
            min_duration=min_duration,
        )

        _record(
            rows,
            'completion_hot',
            'rust_pyo3_options',
            size,
            lambda i=completion_index: i.complete([], '--option-'),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'completion_build',
            'rust_pyo3_index',
            size,
            lambda c=rust_config: _rust.compile_completion_index(c),
            bestof=bestof,
            min_duration=min_duration,
        )

        _record(
            rows,
            'config_construct',
            'kwconf_python',
            size,
            py_cls,
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'config_construct',
            'kwconf_rust',
            size,
            rust_cls,
            bestof=bestof,
            min_duration=min_duration,
        )

        _record(
            rows,
            'schema_build',
            'argparse',
            size,
            lambda n=size: _argparse_parser(n),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'schema_build',
            'kwconf_argparse',
            size,
            py_config.argparse,
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'schema_build',
            'rust_uncached',
            size,
            lambda c=rust_config: _rust.compile_config(c, cache=False),
            bestof=bestof,
            min_duration=min_duration,
        )

        # Declarative class construction is paid once during application
        # import and is therefore invisible to the warm Config.cli() rows.
        # Measure it separately because it is part of the cold CLI budget.
        _record(
            rows,
            'declaration_build',
            'argparse',
            size,
            lambda n=size: _argparse_parser(n),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'declaration_build',
            'kwconf_values',
            size,
            lambda n=size: _kwconf_class(n, 'auto'),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'declaration_build',
            'kwconf_typed',
            size,
            lambda n=size: _kwconf_typed_class(n, 'auto'),
            bestof=bestof,
            min_duration=min_duration,
        )

        # Fair in-process one-shot comparison: both sides pay schema
        # declaration/construction and parse once. Imports are already warm;
        # fresh-process costs are measured separately below.
        _record(
            rows,
            'one_shot_end_to_end',
            'argparse',
            size,
            lambda n=size, a=argv: _argparse_parser(n).parse_args(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'one_shot_end_to_end',
            'kwconf_python',
            size,
            lambda n=size, a=argv: _kwconf_typed_class(n, 'python').cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'one_shot_end_to_end',
            'kwconf_rust',
            size,
            lambda n=size, a=argv: _kwconf_typed_class(n, 'rust').cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'one_shot_end_to_end',
            'kwconf_auto',
            size,
            lambda n=size, a=argv: _kwconf_typed_class(n, 'auto').cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )

        # Warm the Rust cache before timing the normal application pattern.
        # Here argparse construction remains inside the timed function while a
        # module-scope kwconf class is already declared; use one_shot_end_to_end
        # above for a lifecycle-symmetric in-process comparison.
        _rust.clear_cache()
        rust_cls.cli(
            argv=argv,
            autocomplete=False,
            special_options=False,
        )
        auto_cls.cli(
            argv=argv,
            autocomplete=False,
            special_options=False,
        )
        _record(
            rows,
            'warm_end_to_end',
            'argparse',
            size,
            lambda n=size, a=argv: _argparse_parser(n).parse_args(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'warm_end_to_end',
            'kwconf_python',
            size,
            lambda c=py_cls, a=argv: c.cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'warm_end_to_end',
            'kwconf_rust',
            size,
            lambda c=rust_cls, a=argv: c.cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'warm_end_to_end',
            'kwconf_auto',
            size,
            lambda c=auto_cls, a=argv: c.cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )


        # Repeat the end-to-end comparison with kwconf's preferred annotated
        # declaration syntax. The low-level family above intentionally uses
        # parser=str to isolate bridge costs; this family catches regressions
        # in annotation normalization and default auto coercion.
        typed_rust_cls.cli(
            argv=argv,
            autocomplete=False,
            special_options=False,
        )
        typed_auto_cls.cli(
            argv=argv,
            autocomplete=False,
            special_options=False,
        )
        _record(
            rows,
            'typed_warm_end_to_end',
            'argparse',
            size,
            lambda n=size, a=argv: _argparse_parser(n).parse_args(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'typed_warm_end_to_end',
            'kwconf_python',
            size,
            lambda c=typed_py_cls, a=argv: c.cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'typed_warm_end_to_end',
            'kwconf_rust',
            size,
            lambda c=typed_rust_cls, a=argv: c.cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'typed_warm_end_to_end',
            'kwconf_auto',
            size,
            lambda c=typed_auto_cls, a=argv: c.cli(
                argv=a, autocomplete=False, special_options=False
            ),
            bestof=bestof,
            min_duration=min_duration,
        )


def _argv_scaling_cases(
    rows: list[dict[str, object]],
    argv_sizes: list[int],
    *,
    schema_size: int,
    bestof: int,
    min_duration: float,
) -> None:
    """Measure PyO3/result-conversion scaling as supplied argv grows."""
    if max(argv_sizes, default=0) > schema_size:
        raise ValueError('argv size cannot exceed argv schema size')
    parser = _argparse_parser(schema_size)
    cls = _kwconf_typed_class(schema_size, 'rust')
    config = cls()
    compiled = _rust.compile_config(config, cache=False)
    for argv_size in argv_sizes:
        argv = [f'--option_{idx}=value{idx}' for idx in range(argv_size)]
        _record(
            rows,
            'argv_scaling',
            'argparse',
            argv_size,
            lambda p=parser, a=argv: p.parse_args(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'argv_scaling',
            'rust_pyo3_parse',
            argv_size,
            lambda p=compiled.parser, a=argv: p.parse(a),
            bestof=bestof,
            min_duration=min_duration,
        )
        _record(
            rows,
            'argv_scaling',
            'rust_bridge',
            argv_size,
            lambda c=config, p=compiled, a=argv: _rust.parse_compiled(
                c, p, a, strict=True
            ),
            bestof=bestof,
            min_duration=min_duration,
        )


def _cold_cases(
    rows: list[dict[str, object]],
    schema_sizes: list[int],
    *,
    bestof: int,
    min_duration: float,
) -> None:
    python = sys.executable
    imports = {
        'python': [python, '-c', 'pass'],
        'argparse': [python, '-c', 'import argparse'],
        'kwconf': [python, '-c', 'import kwconf'],
        'kwconf_core': [
            python, '-c', 'import kwconf; kwconf.Config; kwconf.Value'
        ],
        'rust_extension': [python, '-c', 'import _kwconf_rust'],
        'kwconf_plus_rust': [
            python,
            '-c',
            (
                'import kwconf; kwconf.Config; kwconf.Value; '
                'from kwconf import _rust; assert _rust.extension_available()'
            ),
        ],
    }
    for method, command in imports.items():
        _record(
            rows,
            'cold_import',
            method,
            0,
            lambda cmd=command: _run_process(cmd),
            bestof=bestof,
            min_duration=min_duration,
        )

    helper = REPO_DPATH / 'dev' / 'benchmarks' / '_rust_cold_case.py'
    for size in schema_sizes:
        for method in ['argparse', 'kwconf_python', 'kwconf_rust', 'kwconf_auto']:
            command = [python, str(helper), method, str(size)]
            _record(
                rows,
                'cold_end_to_end',
                method,
                size,
                lambda cmd=command: _run_process(cmd),
                bestof=bestof,
                min_duration=min_duration,
            )


    for size in schema_sizes:
        for method in [
            'argparse_typed',
            'kwconf_python_typed',
            'kwconf_rust_typed',
            'kwconf_auto_typed',
        ]:
            command = [python, str(helper), method, str(size)]
            _record(
                rows,
                'typed_cold_end_to_end',
                method.removesuffix('_typed'),
                size,
                lambda cmd=command: _run_process(cmd),
                bestof=bestof,
                min_duration=min_duration,
            )


def _add_ratios(rows: list[dict[str, object]]) -> None:
    baselines = {
        'hot_parse': 'argparse',
        'completion_hot': 'rust_pyo3_options',
        'completion_build': 'rust_pyo3_index',
        'config_construct': 'kwconf_python',
        'schema_build': 'argparse',
        'declaration_build': 'argparse',
        'one_shot_end_to_end': 'argparse',
        'argv_scaling': 'argparse',
        'warm_end_to_end': 'argparse',
        'typed_warm_end_to_end': 'argparse',
        'cold_import': 'python',
        'cold_end_to_end': 'argparse',
        'typed_cold_end_to_end': 'argparse',
    }
    index = {
        (str(row['family']), int(row['schema_size']), str(row['method'])): row
        for row in rows
    }
    for row in rows:
        baseline_method = baselines[str(row['family'])]
        baseline = index[
            (str(row['family']), int(row['schema_size']), baseline_method)
        ]
        row['ratio_vs_baseline'] = float(row['min_s']) / float(
            baseline['min_s']
        )
        row['delta_vs_baseline_s'] = float(row['min_s']) - float(
            baseline['min_s']
        )


def _write_csv(rows: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _print(rows: list[dict[str, object]]) -> None:
    families = [
        'hot_parse',
        'completion_hot',
        'completion_build',
        'config_construct',
        'schema_build',
        'declaration_build',
        'one_shot_end_to_end',
        'argv_scaling',
        'warm_end_to_end',
        'typed_warm_end_to_end',
        'cold_import',
        'cold_end_to_end',
        'typed_cold_end_to_end',
    ]
    for family in families:
        print(f'\n{family}:')
        for row in rows:
            if row['family'] != family:
                continue
            micros = float(row['min_s']) * 1e6
            delta_micros = float(row['delta_vs_baseline_s']) * 1e6
            print(
                f"  n={int(row['schema_size']):4d} "
                f"{str(row['method']):18s} {micros:10.2f} us  "
                f"{float(row['ratio_vs_baseline']):7.3f}x  "
                f"delta={delta_micros:+9.2f} us"
            )


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--quick', action='store_true')
    parser.add_argument(
        '--schema-sizes', type=_parse_int_list, default=[1, 16, 64, 256]
    )
    parser.add_argument('--bestof', type=int, default=5)
    parser.add_argument(
        '--argv-sizes', type=_parse_int_list, default=[1, 16, 64, 256]
    )
    parser.add_argument('--argv-schema-size', type=int, default=256)
    parser.add_argument('--min-duration', type=float, default=0.08)
    parser.add_argument(
        '--output',
        type=Path,
        default=REPO_DPATH / 'dev' / 'benchmarks' / '_results' / 'rust_cli_runtime.csv',
    )
    return parser


def main() -> None:
    args = _make_cli().parse_args()
    if not _rust.extension_available():
        raise SystemExit(
            'Rust extension is not importable from the benchmark Python:\n'
            f'  {sys.executable}\n'
            'The build helper installs into the Python that runs it. Use the '
            'same interpreter for both commands, for example:\n'
            f'  {sys.executable} dev/rust_backend/build_backend.py --release\n'
            f'  {sys.executable} dev/benchmarks/rust_cli_runtime.py --quick'
        )
    import _kwconf_rust

    print(f'benchmark python: {sys.executable}')
    print(f'rust extension:   {_kwconf_rust.__file__}')
    if args.quick:
        args.schema_sizes = [1, 16, 64, 256]
        args.min_duration = min(args.min_duration, 0.02)
        args.bestof = min(args.bestof, 3)

    rows: list[dict[str, object]] = []
    common = {'bestof': args.bestof, 'min_duration': args.min_duration}
    _warm_cases(rows, args.schema_sizes, **common)
    _argv_scaling_cases(
        rows,
        args.argv_sizes,
        schema_size=args.argv_schema_size,
        **common,
    )
    _cold_cases(rows, args.schema_sizes, **common)
    _add_ratios(rows)
    _write_csv(rows, args.output)
    _print(rows)
    print(f'\nwrote: {args.output}')


if __name__ == '__main__':
    main()
