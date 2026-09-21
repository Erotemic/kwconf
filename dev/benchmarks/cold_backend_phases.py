#!/usr/bin/env python3
"""Measure cold CLI backend construction and parse phases in fresh processes.

This benchmark complements :mod:`cold_start_breakdown`: the latter measures the
real public ``CLI.cli()`` wall-clock path, while this script isolates the major
pieces of work that path performs.  Each observation still launches a fresh
interpreter, but the generated child program executes the lifecycle explicitly
so backend materialization and the parser engine itself can be timed separately.

The phases are intentionally API-shaped rather than forced into false symmetry:

* argparse's normal ``ArgumentParser`` + ``add_argument`` definition already
  *is* backend materialization, so ``backend_ns`` is zero for that row;
* kwconf first declares a Config class, then either materializes the canonical
  Python ``ArgumentParser`` or compiles a Rust ``FlatParser``;
* kwconf also has instance/reset/apply lifecycle work that argparse does not.

The normal end-to-end public CLI timing remains authoritative.  These numbers
exist to identify where the remaining kwconf overhead lives.
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
MARKER = 'KWCONF_COLD_BACKEND_PHASES'
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


def _csv_list(text: str) -> list[str]:
    values = [item.strip() for item in text.split(',') if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError('expected a non-empty comma-separated list')
    return values


def _site_package_paths() -> list[str]:
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


def _script_text(method: str, size: int) -> str:
    lines = [
        'import sys as _sys',
        'from time import perf_counter_ns as _clock',
        '_body_start = _clock()',
    ]
    if method == 'argparse':
        lines.extend(
            [
                '_import_start = _clock()',
                'import argparse',
                '_import_end = _clock()',
                '_api_start = _api_end = _import_end',
                '_definition_start = _clock()',
                'parser = argparse.ArgumentParser(add_help=False)',
            ]
        )
        for idx in range(size):
            lines.append(
                f"parser.add_argument('--option_{idx}', '--option-{idx}', "
                f"dest='option_{idx}', default='', type=str)"
            )
        lines.extend(
            [
                '_definition_end = _clock()',
                '_instance_start = _instance_end = _definition_end',
                '_backend_start = _backend_end = _definition_end',
                '_rust_bridge_start = _rust_bridge_end = _definition_end',
                '_extension_start = _extension_end = _definition_end',
                '_schema_start = _schema_end = _definition_end',
                '_parser_build_start = _parser_build_end = _definition_end',
                '_reset_start = _reset_end = _definition_end',
                '_parse_start = _clock()',
                'result = parser.parse_args()',
                '_parse_end = _clock()',
                '_reparse_start = _reparse_end = _parse_end',
                '_apply_start = _clock()',
                "if result.option_0:",
                "    assert result.option_0 == 'value0'",
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
                '_api_end = _clock()',
                '_definition_start = _clock()',
                'class CLI(_Config):',
                f"    __cli_backend__ = '{backend}'",
            ]
        )
        for idx in range(size):
            lines.append(f"    option_{idx}: str = ''")
        lines.extend(
            [
                '_definition_end = _clock()',
                '_argv = _sys.argv[1:]',
                '_instance_start = _clock()',
                '_cfg = CLI(_dont_call_post_init=True)',
                '_instance_end = _clock()',
            ]
        )
        if method == 'kwconf_python':
            lines.extend(
                [
                    # Canonical Config.load(_reset=True) behavior happens before
                    # the Python backend constructs argparse.
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
                    '_apply_end = _clock()',
                ]
            )
        else:
            lines.extend(
                [
                    '_normalized_argv = kwconf.config._coerce_argv_common(_argv, expand_vars=True)',
                    '_backend_start = _clock()',
                    # The common Rust CLI core now lives in config.py, which is
                    # already loaded by kwconf.Config realization. No separate
                    # Python bridge import is required on this path.
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
                    '_explicit = set(_explicit)',
                    'for _key in _explicit:',
                    '    _cfg._setitem(_key, _values[_key], validation_mode=None)',
                    '_provided = frozenset(_explicit)',
                    '_cfg._explicit_argv_keys = _provided',
                    '_cfg._provided_keys = _provided',
                    '_cfg._validate_required_fields()',
                    '_cfg.__post_init__()',
                    '_apply_end = _clock()',
                ]
            )
        lines.extend(
            [
                "if _cfg['option_0']:",
                "    assert _cfg['option_0'] == 'value0'",
            ]
        )
    lines.extend(
        [
            '_body_end = _clock()',
            'print(',
            f"    '{MARKER}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}|{{}}'.format(",
            '        _body_end - _body_start,',
            '        _import_end - _import_start,',
            '        _api_end - _api_start,',
            '        _definition_end - _definition_start,',
            '        _instance_end - _instance_start,',
            '        _backend_end - _backend_start,',
            '        _rust_bridge_end - _rust_bridge_start,',
            '        _extension_end - _extension_start,',
            '        _schema_end - _schema_start,',
            '        _parser_build_end - _parser_build_start,',
            '        _parse_end - _parse_start,',
            '        _reset_end - _reset_start,',
            '        _reparse_end - _reparse_start,',
            '        _apply_end - _apply_start,',
            '    )',
            ')',
        ]
    )
    return '\n'.join(lines) + '\n'


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
            'cold backend child failed:\n'
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
    fields = marker.split('|')
    if len(fields) != len(PHASES) + 1:
        raise RuntimeError(f'unexpected timing marker: {marker!r}')
    values = list(map(int, fields[1:]))
    result = {'total_ns': total_ns}
    result.update(dict(zip(PHASES, values)))
    phase_sum = sum(result[key] for key in PHASES if key != 'body_ns')
    result['other_body_ns'] = max(0, result['body_ns'] - phase_sum)
    result['process_envelope_ns'] = max(0, total_ns - result['body_ns'])
    return result


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument('--trials', type=int, default=15)
    parser.add_argument('--no-site-trials', type=int, default=5)
    parser.add_argument('--warmups', type=int, default=1)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--schema-size', type=int, default=64)
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
    if set(args.methods) - valid_methods:
        raise SystemExit(f'unknown methods: {sorted(set(args.methods) - valid_methods)}')
    if set(args.profiles) - valid_profiles:
        raise SystemExit(f'unknown profiles: {sorted(set(args.profiles) - valid_profiles)}')
    if args.trials < 2 or args.no_site_trials < 2:
        raise SystemExit('trial counts must be at least 2')
    if args.schema_size <= 0:
        raise SystemExit('--schema-size must be positive')
    if not 0 <= args.argv_size <= args.schema_size:
        raise SystemExit('--argv-size must satisfy 0 <= argv-size <= schema-size')

    if args.script_dir is None:
        temp_context = tempfile.TemporaryDirectory(prefix='kwconf-cold-backend-')
        directory = Path(temp_context.name)
    else:
        temp_context = None
        directory = args.script_dir
        directory.mkdir(parents=True, exist_ok=True)

    scripts = {}
    for method in args.methods:
        path = directory / f'{method}-{args.schema_size}.py'
        path.write_text(_script_text(method, args.schema_size))
        scripts[method] = path

    env_by_profile = {profile: _child_env(profile) for profile in args.profiles}
    try:
        for profile in args.profiles:
            flags = ['-S'] if profile == 'no_site' else []
            for method in args.methods:
                command = [
                    sys.executable,
                    *flags,
                    str(scripts[method]),
                    *[f'--option_{idx}=value{idx}' for idx in range(args.argv_size)],
                ]
                for _ in range(args.warmups):
                    _run(command, env_by_profile[profile])

        rows: list[dict[str, object]] = []
        rng = random.Random(args.seed)
        for profile in args.profiles:
            flags = ['-S'] if profile == 'no_site' else []
            trials = args.no_site_trials if profile == 'no_site' else args.trials
            for trial in range(trials):
                order = list(args.methods)
                rng.shuffle(order)
                for order_index, method in enumerate(order):
                    command = [
                        sys.executable,
                        *flags,
                        str(scripts[method]),
                        *[f'--option_{idx}=value{idx}' for idx in range(args.argv_size)],
                    ]
                    rows.append(
                        {
                            'profile': profile,
                            'trial': trial,
                            'order_index': order_index,
                            'method': method,
                            **_run(command, env_by_profile[profile]),
                        }
                    )
    finally:
        if temp_context is not None:
            temp_context.cleanup()

    metric_names = ['total_ns', *PHASES, 'other_body_ns', 'process_envelope_ns']
    summary: dict[str, object] = {
        'python': sys.executable,
        'python_version': sys.version.split()[0],
        'platform': platform.platform(),
        'schema_size': args.schema_size,
        'argv_size': args.argv_size,
        'trials': args.trials,
        'no_site_trials': args.no_site_trials,
        'profiles': {},
    }
    for profile in args.profiles:
        methods = {}
        for method in args.methods:
            matching = [
                row
                for row in rows
                if row['profile'] == profile and row['method'] == method
            ]
            methods[method] = {
                metric: _summarize([int(row[metric]) for row in matching])
                for metric in metric_names
            }
        summary['profiles'][profile] = {'methods': methods}

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
