#!/usr/bin/env python3
"""Attribute cold lifecycle costs for the production-style comparison CLI.

Unlike :mod:`realistic_cli_runtime`, which measures the exact user-facing wall
clock of launching ``examples/09_argparse_comparison.py``, this benchmark
isolates the backend lifecycle for that *same* 24-option schema and sample argv.
Each observation still runs in a fresh Python process.
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

REPO_DPATH = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_DPATH / 'examples' / '09_argparse_comparison.py'
MARKER = 'KWCONF_REALISTIC_PHASES'
PHASES = (
    'body_ns',
    'import_ns',
    'api_ns',
    'definition_ns',
    'instance_ns',
    'backend_ns',
    'rust_bridge_ns',
    'extension_ns',
    'schema_ns',
    'parser_build_ns',
    'parse_ns',
    'reset_ns',
    'reparse_ns',
    'apply_ns',
)
METHODS = ('argparse', 'kwconf_python', 'kwconf_rust')


def _example_sample_argv() -> list[str]:
    spec = importlib.util.spec_from_file_location('_kwconf_realistic_example_parent', EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.SAMPLE_ARGV)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _summarize(values: list[int]) -> dict[str, float]:
    vals = [float(v) for v in values]
    return {
        'median_ns': statistics.median(vals),
        'mean_ns': statistics.fmean(vals),
        'p10_ns': _percentile(vals, 0.10),
        'p90_ns': _percentile(vals, 0.90),
        'min_ns': min(vals),
    }


def _script_text(method: str) -> str:
    if method not in METHODS:
        raise KeyError(method)
    lines = [
        'import importlib.util as _ilu',
        'import json as _json',
        'import sys as _sys',
        'from time import perf_counter_ns as _clock',
        f"_spec = _ilu.spec_from_file_location('_kwconf_realistic_example', {str(EXAMPLE)!r})",
        'assert _spec is not None and _spec.loader is not None',
        '_example = _ilu.module_from_spec(_spec)',
        '_spec.loader.exec_module(_example)',
        '_argv = list(_example.SAMPLE_ARGV)',
        '_body_start = _clock()',
    ]
    if method == 'argparse':
        lines.extend(
            [
                '_import_start = _clock()',
                'import argparse as _argparse',
                '_import_end = _clock()',
                '_api_start = _api_end = _import_end',
                '_definition_start = _clock()',
                '_parser = _example._get_argparse_parser()',
                '_definition_end = _clock()',
                '_instance_start = _instance_end = _definition_end',
                '_backend_start = _backend_end = _definition_end',
                '_rust_bridge_start = _rust_bridge_end = _definition_end',
                '_extension_start = _extension_end = _definition_end',
                '_schema_start = _schema_end = _definition_end',
                '_parser_build_start = _parser_build_end = _definition_end',
                '_reset_start = _reset_end = _definition_end',
                '_parse_start = _clock()',
                '_ns = _parser.parse_args(_argv)',
                '_parse_end = _clock()',
                '_reparse_start = _reparse_end = _parse_end',
                '_apply_start = _clock()',
                '_result = vars(_ns)',
                '_apply_end = _clock()',
            ]
        )
    else:
        backend = {'kwconf_python': 'python', 'kwconf_rust': 'rust'}[method]
        lines.extend(
            [
                '_import_start = _clock()',
                'import kwconf',
                '_import_end = _clock()',
                '_api_start = _clock()',
                '_Config = kwconf.Config',
                '_Value = kwconf.Value',
                '_Flag = kwconf.Flag',
                '_api_end = _clock()',
                '_definition_start = _clock()',
                '_CLI = _example._get_kwconf_config()',
                f"_CLI.__cli_backend__ = '{backend}'",
                '_definition_end = _clock()',
                '_instance_start = _clock()',
                '_cfg = _CLI(_dont_call_post_init=True)',
                '_instance_end = _clock()',
            ]
        )
        if method == 'kwconf_python':
            lines.extend(
                [
                    '_reset_start = _clock()',
                    '_cfg._reset_data_from_defaults(_dont_call_post_init=True)',
                    '_reset_end = _clock()',
                    '_backend_start = _clock()',
                    '_parser = _cfg._argparse(special_options=False)',
                    '_backend_end = _clock()',
                    '_rust_bridge_start = _rust_bridge_end = _backend_end',
                    '_extension_start = _extension_end = _backend_end',
                    '_schema_start = _schema_end = _backend_end',
                    '_parser_build_start = _parser_build_end = _backend_end',
                    '_parse_start = _clock()',
                    'from kwconf import argparse_ext as _argparse_ext',
                    '_parsed = _argparse_ext.parse_result(_parser, _argv)',
                    '_parse_end = _clock()',
                    '_reparse_start = _reparse_end = _parse_end',
                    '_apply_start = _clock()',
                    '_explicit = set(_parsed.explicit_keys)',
                    'for _key in _explicit:',
                    '    _cfg._setitem(_key, _parsed.values[_key], validation_mode=None)',
                    '_provided = frozenset(_explicit)',
                    '_cfg._explicit_argv_keys = _provided',
                    '_cfg._provided_keys = _provided',
                    '_cfg._validate_required_fields()',
                    '_cfg.__post_init__()',
                    '_result = _cfg.to_dict()',
                    '_apply_end = _clock()',
                ]
            )
        else:
            lines.extend(
                [
                    '_normalized_argv = kwconf.config._coerce_argv_common(_argv, expand_vars=True)',
                    '_backend_start = _clock()',
                    '_rust_bridge_start = _rust_bridge_end = _clock()',
                    'from kwconf import config as _config_mod',
                    '_extension_start = _clock()',
                    '_extension = _config_mod._load_direct_rust_extension(required=True)',
                    '_extension_end = _clock()',
                    '_schema_start = _clock()',
                    '_description = _config_mod._direct_rust_schema_description(_cfg)',
                    'assert _description is not None',
                    '_specs, _metadata = _description',
                    '_schema_end = _clock()',
                    '_parser_build_start = _clock()',
                    '_compiled = _config_mod._direct_rust_build_compiled(',
                    '    _extension, _specs, _metadata',
                    ')',
                    'assert _compiled is not None',
                    '_parser_build_end = _clock()',
                    '_backend_end = _clock()',
                    '_parse_start = _clock()',
                    '_parsed = _config_mod._direct_rust_parse(',
                    '    _cfg, _compiled, _normalized_argv, strict=True',
                    ')',
                    'assert _parsed is not None',
                    '_parse_end = _clock()',
                    '_reset_start = _clock()',
                    '_cfg._reset_data_from_defaults(_dont_call_post_init=True)',
                    '_reset_end = _clock()',
                    '_reparse_start = _clock()',
                    '_parsed = _config_mod._direct_rust_parse(',
                    '    _cfg, _compiled, _normalized_argv, strict=True',
                    ')',
                    'assert _parsed is not None',
                    '_reparse_end = _clock()',
                    '_apply_start = _clock()',
                    '_values, _explicit, _unknown = _parsed',
                    'assert not _unknown',
                    '_explicit = set(_explicit)',
                    'for _key in _explicit:',
                    '    _cfg._setitem(_key, _values[_key], validation_mode=None)',
                    '_provided = frozenset(_explicit)',
                    '_cfg._explicit_argv_keys = _provided',
                    '_cfg._provided_keys = _provided',
                    '_cfg._validate_required_fields()',
                    '_cfg.__post_init__()',
                    '_result = _cfg.to_dict()',
                    '_apply_end = _clock()',
                ]
            )
    lines.extend(
        [
            '_body_end = _clock()',
            '_payload = {',
            "    'timings': {",
            "        'body_ns': _body_end - _body_start,",
            "        'import_ns': _import_end - _import_start,",
            "        'api_ns': _api_end - _api_start,",
            "        'definition_ns': _definition_end - _definition_start,",
            "        'instance_ns': _instance_end - _instance_start,",
            "        'backend_ns': _backend_end - _backend_start,",
            "        'rust_bridge_ns': _rust_bridge_end - _rust_bridge_start,",
            "        'extension_ns': _extension_end - _extension_start,",
            "        'schema_ns': _schema_end - _schema_start,",
            "        'parser_build_ns': _parser_build_end - _parser_build_start,",
            "        'parse_ns': _parse_end - _parse_start,",
            "        'reset_ns': _reset_end - _reset_start,",
            "        'reparse_ns': _reparse_end - _reparse_start,",
            "        'apply_ns': _apply_end - _apply_start,",
            '    },',
            "    'result': _result,",
            '}',
            f"print('{MARKER}|' + _json.dumps(_payload, sort_keys=True))",
        ]
    )
    return '\n'.join(lines) + '\n'


def _run(command: list[str], env: dict[str, str]) -> tuple[dict[str, int], dict[str, object]]:
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
            'realistic phase child failed:\n'
            f'  command: {command!r}\n'
            f'  stdout:\n{proc.stdout}\n'
            f'  stderr:\n{proc.stderr}'
        )
    marker = next(
        (line for line in reversed(proc.stdout.splitlines()) if line.startswith(MARKER + '|')),
        None,
    )
    if marker is None:
        raise RuntimeError(f'child did not emit {MARKER!r}:\n{proc.stdout}')
    payload = json.loads(marker.split('|', 1)[1])
    timings = {key: int(value) for key, value in payload['timings'].items()}
    timings['total_ns'] = total_ns
    phase_sum = sum(timings[key] for key in PHASES if key != 'body_ns')
    timings['other_body_ns'] = max(0, timings['body_ns'] - phase_sum)
    timings['process_envelope_ns'] = max(0, total_ns - timings['body_ns'])
    return timings, payload['result']


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=15)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--output-json', type=Path)
    parser.add_argument('--raw-output', type=Path)
    parser.add_argument('--script-dir', type=Path)
    args = parser.parse_args()
    if args.trials < 2:
        raise SystemExit('--trials must be at least 2')

    env = os.environ.copy()
    env['PYTHONPATH'] = str(REPO_DPATH) + os.pathsep + env.get('PYTHONPATH', '')

    if args.script_dir is None:
        temp_context = tempfile.TemporaryDirectory(prefix='kwconf-realistic-phases-')
        directory = Path(temp_context.name)
    else:
        temp_context = None
        directory = args.script_dir
        directory.mkdir(parents=True, exist_ok=True)

    scripts = {}
    for method in METHODS:
        path = directory / f'case_{method}.py'
        path.write_text(_script_text(method))
        scripts[method] = path

    try:
        for method in METHODS:
            for _ in range(args.warmups):
                _run([sys.executable, str(scripts[method])], env)

        rows: list[dict[str, object]] = []
        results: dict[str, dict[str, object]] = {}
        rng = random.Random(args.seed)
        for trial in range(args.trials):
            order = list(METHODS)
            rng.shuffle(order)
            for order_index, method in enumerate(order):
                timings, result = _run([sys.executable, str(scripts[method])], env)
                rows.append(
                    {
                        'trial': trial,
                        'order_index': order_index,
                        'method': method,
                        **timings,
                    }
                )
                results.setdefault(method, result)
                if results[method] != result:
                    raise AssertionError(f'{method} result changed across trials')
    finally:
        if temp_context is not None:
            temp_context.cleanup()

    if not (results['argparse'] == results['kwconf_python'] == results['kwconf_rust']):
        raise AssertionError('instrumented realistic CLI outputs differ')

    metric_names = ['total_ns', *PHASES, 'other_body_ns', 'process_envelope_ns']
    methods = {}
    for method in METHODS:
        matching = [row for row in rows if row['method'] == method]
        methods[method] = {
            metric: _summarize([int(row[metric]) for row in matching])
            for metric in metric_names
        }

    summary = {
        'python': sys.executable,
        'trials': args.trials,
        'argv': _example_sample_argv(),
        'output_parity': True,
        'methods': methods,
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
