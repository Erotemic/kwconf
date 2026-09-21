#!/usr/bin/env python3
"""Build one self-contained Rust-backend evidence tarball.

The bundle is designed to answer the next review without asking the user to
rerun individual commands.  It captures source state, build/wheel metadata,
feature/parity checks, Python/Rust benchmarks, completion/help measurements,
import profiles, optional native profiles, generated benchmark programs, and
all command stdout/stderr (including failures).

Campaign profiles:
    default   Review-quality release gates plus representative benchmarks.
    --quick   Minimal smoke/diagnostic bundle for the edit-test loop.
    --deep    Historical exhaustive sampling plus Criterion/cProfile/perf.

Examples:
    python dev/rust_backend/evidence_bundle.py
    python dev/rust_backend/evidence_bundle.py --quick
    python dev/rust_backend/evidence_bundle.py --deep
    python dev/rust_backend/evidence_bundle.py --cpu 4
"""

from __future__ import annotations

import argparse
import datetime as datetime_mod
import hashlib
import importlib.metadata
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

REPO_DPATH = Path(__file__).resolve().parents[2]
DEFAULT_RESULT_DPATH = REPO_DPATH / 'dev' / 'benchmarks' / '_results'


def _now_id() -> str:
    stamp = datetime_mod.datetime.now(datetime_mod.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return stamp + '-' + uuid.uuid4().hex[:8]


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _jsonable_env() -> dict[str, Any]:
    packages = [
        'kwconf',
        'argcomplete',
        'rich',
        'rich-argparse',
        'maturin',
        'pytest',
        'ruff',
        'ubelt',
    ]
    info: dict[str, Any] = {
        'timestamp_utc': datetime_mod.datetime.now(datetime_mod.timezone.utc).isoformat(),
        'python': sys.version,
        'python_executable': sys.executable,
        'platform': platform.platform(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'implementation': platform.python_implementation(),
        'packages': {name: _version(name) for name in packages},
        'tools': {
            name: shutil.which(name)
            for name in [
                'cargo',
                'rustc',
                'maturin',
                'uv',
                'perf',
                'valgrind',
                'ruff',
                'git',
            ]
        },
        'affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
    }
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


class Collector:
    def __init__(self, root: Path, env: dict[str, str]):
        self.root = root
        self.env = env
        self.commands = root / 'commands'
        self.commands.mkdir(parents=True, exist_ok=True)
        self.rows: list[dict[str, Any]] = []
        self.counter = 0

    def run(
        self,
        label: str,
        command: list[str],
        *,
        required: bool = False,
        cwd: Path = REPO_DPATH,
        env: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> int:
        self.counter += 1
        slug = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in label).strip('-')
        log = self.commands / f'{self.counter:02d}-{slug}.log'
        active_env = self.env if env is None else env
        header = '$ ' + shlex.join([str(x) for x in command]) + '\n'
        print(header.rstrip(), flush=True)
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                env=active_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
            output = proc.stdout
            code = proc.returncode
        except subprocess.TimeoutExpired as ex:
            output = (ex.stdout or '') + '\n[TIMEOUT]\n' + (ex.stderr or '')
            code = 124
        except FileNotFoundError as ex:
            output = f'{type(ex).__name__}: {ex}\n'
            code = 127
        elapsed = time.perf_counter() - start
        log.write_text(header + output)
        row = {
            'label': label,
            'required': required,
            'returncode': code,
            'elapsed_seconds': elapsed,
            'log': str(log.relative_to(self.root)),
            'command': command,
        }
        self.rows.append(row)
        print(
            f'  -> {code} in {elapsed:.2f}s: {log.relative_to(self.root)}',
            flush=True,
        )
        return code

    def skip(self, label: str, reason: str, *, required: bool = False) -> None:
        self.counter += 1
        slug = ''.join(ch if ch.isalnum() or ch in '-_' else '-' for ch in label).strip('-')
        log = self.commands / f'{self.counter:02d}-{slug}.log'
        log.write_text(f'[SKIP] {reason}\n')
        self.rows.append(
            {
                'label': label,
                'required': required,
                'returncode': None,
                'status': 'SKIP',
                'elapsed_seconds': 0.0,
                'log': str(log.relative_to(self.root)),
                'command': [],
                'reason': reason,
            }
        )
        print(f'  -> SKIP: {label}: {reason}', flush=True)

    def has_required_failures(self) -> bool:
        return any(
            row['required']
            and row.get('status') != 'SKIP'
            and row['returncode'] != 0
            for row in self.rows
        )

    def write_summary(self, *, profile: str | None = None) -> None:
        lines = [
            '# kwconf Rust backend evidence bundle',
            '',
        ]
        if profile is not None:
            lines.extend([f'Campaign profile: **{profile}**', ''])
        lines.extend([
            '| status | required | elapsed | command | log |',
            '| --- | --- | ---: | --- | --- |',
        ])
        for row in self.rows:
            if row.get('status') == 'SKIP':
                status = 'SKIP'
            else:
                status = 'PASS' if row['returncode'] == 0 else f"FAIL({row['returncode']})"
            elapsed = row.get('elapsed_seconds', 0.0)
            lines.append(
                f"| {status} | {row['required']} | {elapsed:.2f}s | "
                f"`{row['label']}` | `{row['log']}` |"
            )
        required_failures = [
            row
            for row in self.rows
            if row['required'] and row.get('status') != 'SKIP' and row['returncode'] != 0
        ]
        total_elapsed = sum(row.get('elapsed_seconds', 0.0) for row in self.rows)
        lines.extend(
            [
                '',
                f'Required failures: **{len(required_failures)}**',
                f'Collected subprocess time: **{total_elapsed:.2f}s**',
                '',
                'Native-vs-delegated feature ownership is in `feature_matrix.json`.',
                'Real CLI startup data is in `startup/`; completion data is in `completion/`.',
                'Every subprocess log is retained even when a command fails.',
            ]
        )
        (self.root / 'SUMMARY.md').write_text('\n'.join(lines) + '\n')
        (self.root / 'commands.json').write_text(json.dumps(self.rows, indent=2, default=str) + '\n')


def _capture_repo_state(bundle: Path, collector: Collector) -> None:
    for label, command in [
        ('git-status', ['git', '-c', f'safe.directory={REPO_DPATH}', 'status', '--short']),
        ('git-revision', ['git', '-c', f'safe.directory={REPO_DPATH}', 'rev-parse', 'HEAD']),
        ('git-diff-stat', ['git', '-c', f'safe.directory={REPO_DPATH}', 'diff', 'HEAD', '--stat']),
        ('git-diff-check', ['git', '-c', f'safe.directory={REPO_DPATH}', 'diff', 'HEAD', '--check']),
    ]:
        collector.run(label, command, required=(label == 'git-diff-check'))
    patch = bundle / 'repo.diff'
    try:
        proc = subprocess.run(
            ['git', '-c', f'safe.directory={REPO_DPATH}', 'diff', 'HEAD', '--binary'],
            cwd=REPO_DPATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        patch.write_bytes(proc.stdout)
    except FileNotFoundError:
        patch.write_text('git unavailable\n')


def _capture_source_snapshot(bundle: Path) -> None:
    """Copy the exact tracked + untracked working source into the bundle.

    Use Git as the source of truth so staged and untracked files that actually
    participated in the campaign are preserved as well. Generated benchmark
    outputs and build products remain excluded through normal .gitignore rules.
    """
    destination = bundle / 'source_snapshot'
    destination.mkdir()
    command = [
        'git',
        '-c',
        f'safe.directory={REPO_DPATH}',
        'ls-files',
        '--cached',
        '--others',
        '--exclude-standard',
        '-z',
    ]
    try:
        proc = subprocess.run(
            command,
            cwd=REPO_DPATH,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return
    for raw in proc.stdout.split(b'\0'):
        if not raw:
            continue
        rel = Path(os.fsdecode(raw))
        src = REPO_DPATH / rel
        if not src.is_file():
            continue
        dst = destination / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _capture_wheel(bundle: Path) -> None:
    wheels = sorted(
        (REPO_DPATH / 'packages' / 'kwconf-rust' / 'dist').glob('*.whl'),
        key=lambda p: p.stat().st_mtime,
    )
    data: dict[str, Any] = {'wheels': []}
    wheel_dir = bundle / 'wheels'
    wheel_dir.mkdir(exist_ok=True)
    selected = wheels[-3:]
    for wheel in selected:
        record: dict[str, Any] = {
            'name': wheel.name,
            'size': wheel.stat().st_size,
            'sha256': _sha256(wheel),
        }
        try:
            with zipfile.ZipFile(wheel) as archive:
                record['members'] = archive.namelist()
        except zipfile.BadZipFile as ex:
            record['error'] = str(ex)
        copied = wheel_dir / wheel.name
        shutil.copy2(wheel, copied)
        record['bundle_path'] = str(copied.relative_to(bundle))
        data['wheels'].append(record)
    (bundle / 'wheel_metadata.json').write_text(json.dumps(data, indent=2) + '\n')


def _run_cargo_gates(collector: Collector, args: argparse.Namespace) -> None:
    """Run required Rust checks before repeated performance sampling."""
    if not shutil.which('cargo'):
        return
    collector.run(
        'cargo-check-extension',
        ['cargo', 'check', '--manifest-path', 'packages/kwconf-rust/Cargo.toml'],
        required=True,
        timeout=300,
    )
    collector.run(
        'cargo-test-core',
        ['cargo', 'test', '--manifest-path', 'rust/kwconf_accel_core/Cargo.toml'],
        required=True,
        timeout=300,
    )
    if not args.quick:
        collector.run(
            'cargo-fmt-check',
            [
                'cargo',
                'fmt',
                '--manifest-path',
                'packages/kwconf-rust/Cargo.toml',
                '--',
                '--check',
            ],
            required=True,
            timeout=120,
        )
        collector.run(
            'cargo-clippy',
            [
                'cargo',
                'clippy',
                '--manifest-path',
                'packages/kwconf-rust/Cargo.toml',
                '--all-targets',
                '--all-features',
                '--',
                '-D',
                'warnings',
            ],
            required=True,
            timeout=600,
        )
        collector.run(
            'cargo-fmt-core-check',
            [
                'cargo',
                'fmt',
                '--manifest-path',
                'rust/kwconf_accel_core/Cargo.toml',
                '--',
                '--check',
            ],
            required=True,
            timeout=120,
        )
        collector.run(
            'cargo-clippy-core',
            [
                'cargo',
                'clippy',
                '--manifest-path',
                'rust/kwconf_accel_core/Cargo.toml',
                '--all-targets',
                '--',
                '-D',
                'warnings',
            ],
            required=True,
            timeout=600,
        )


def _discover_kwconf_rs(explicit: str | None) -> Path | None:
    """Resolve an optional native kwconf-rs checkout for convergence evidence."""
    if explicit and explicit.lower() not in {'auto', 'none', 'off'}:
        return Path(explicit).expanduser().resolve()
    if explicit and explicit.lower() in {'none', 'off'}:
        return None
    candidates = [
        Path.home() / 'code' / 'kwconf-rs',
        Path.home() / 'code' / 'kwconf_rs',
    ]
    for candidate in candidates:
        if (candidate / 'Cargo.toml').exists():
            return candidate.resolve()
    return None


def _make_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    profile = parser.add_mutually_exclusive_group()
    profile.add_argument(
        '--quick',
        action='store_true',
        help='minimal smoke/diagnostic bundle',
    )
    profile.add_argument(
        '--deep',
        action='store_true',
        help='exhaustive release-performance and profiling campaign',
    )
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--startup-trials', type=int)
    parser.add_argument('--completion-trials', type=int)
    parser.add_argument('--delegated-completion-trials', type=int)
    parser.add_argument('--modal-trials', type=int)
    parser.add_argument('--help-trials', type=int)
    parser.add_argument('--realistic-trials', type=int)
    parser.add_argument('--realistic-warm-loops', type=int)
    parser.add_argument(
        '--kwconf-rs',
        default='auto',
        help=(
            "native kwconf-rs checkout to inspect, 'auto' to look under "
            "~/code/kwconf-rs, or 'none' to disable"
        ),
    )
    parser.add_argument('--output', type=Path)
    return parser


def _configure_profile(args: argparse.Namespace) -> str:
    """Resolve campaign defaults while preserving explicit trial overrides."""
    if args.quick:
        profile = 'quick'
        defaults = {
            'startup_trials': 2,
            'completion_trials': 2,
            'delegated_completion_trials': 2,
            'modal_trials': 2,
            'help_trials': 1,
            'realistic_trials': 2,
            'realistic_warm_loops': 1000,
        }
    elif args.deep:
        # These match the historical full campaign. Keep this mode available
        # for release characterization and deep performance investigations.
        profile = 'deep'
        defaults = {
            'startup_trials': 100,
            'completion_trials': 50,
            'delegated_completion_trials': 50,
            'modal_trials': 50,
            'help_trials': 30,
            'realistic_trials': 50,
            'realistic_warm_loops': 30000,
        }
    else:
        # Review mode keeps every correctness/parity dimension but spends
        # repeated process launches where they add statistical information.
        profile = 'review'
        defaults = {
            'startup_trials': 30,
            'completion_trials': 15,
            'delegated_completion_trials': 2,
            'modal_trials': 15,
            'help_trials': 3,
            'realistic_trials': 15,
            'realistic_warm_loops': 10000,
        }
    for name, value in defaults.items():
        if getattr(args, name) is None:
            setattr(args, name, value)
        if getattr(args, name) < 1:
            raise SystemExit(f'--{name.replace("_", "-")} must be at least 1')
    return profile


def main() -> None:
    args = _make_cli().parse_args()
    profile = _configure_profile(args)
    kwconf_rs = _discover_kwconf_rs(args.kwconf_rs)
    run_id = _now_id()

    final_output = args.output
    if final_output is None:
        DEFAULT_RESULT_DPATH.mkdir(parents=True, exist_ok=True)
        final_output = DEFAULT_RESULT_DPATH / f'kwconf-rust-evidence-{run_id}.tar.gz'
    final_output = final_output.resolve()
    final_output.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    old_pythonpath = env.get('PYTHONPATH')
    env['PYTHONPATH'] = str(REPO_DPATH) if not old_pythonpath else str(REPO_DPATH) + os.pathsep + old_pythonpath

    with tempfile.TemporaryDirectory(prefix='kwconf-rust-evidence-') as temp:
        bundle = Path(temp) / f'kwconf-rust-evidence-{run_id}'
        bundle.mkdir()
        (bundle / 'environment.json').write_text(json.dumps(_jsonable_env(), indent=2, default=str) + '\n')
        campaign = {
            'profile': profile,
            'quick': args.quick,
            'deep': args.deep,
            'startup_trials': args.startup_trials,
            'completion_trials': args.completion_trials,
            'delegated_completion_trials': args.delegated_completion_trials,
            'modal_trials': args.modal_trials,
            'help_trials': args.help_trials,
            'realistic_trials': args.realistic_trials,
            'realistic_warm_loops': args.realistic_warm_loops,
        }
        (bundle / 'campaign.json').write_text(json.dumps(campaign, indent=2) + '\n')
        print('campaign profile:', profile, campaign, flush=True)
        collector = Collector(bundle, env)
        _capture_repo_state(bundle, collector)
        _capture_source_snapshot(bundle)
        collector.run(
            'python-package-freeze',
            [sys.executable, '-m', 'pip', 'freeze'],
            required=False,
        )

        if not args.skip_build:
            collector.run(
                'build-install-abi3',
                [sys.executable, 'dev/rust_backend/build_backend.py', '--release'],
                required=True,
                timeout=300,
            )

        collector.run(
            'backend-parity',
            [sys.executable, 'dev/rust_backend/check_backend.py'],
            required=True,
        )
        collector.run(
            'feature-matrix',
            [
                sys.executable,
                'dev/rust_backend/feature_matrix.py',
                '--json-output',
                str(bundle / 'feature_matrix.json'),
            ],
            required=True,
        )
        focused_pytest = [
            sys.executable,
            '-m',
            'pytest',
            '-q',
            '-o',
            'addopts=',
            'tests/test_rust_backend.py',
            'tests/test_rust_completion.py',
            'tests/test_rust_optional_ecosystem.py',
            'tests/test_ubelt_repr.py',
            'tests/test_import.py',
            'tests/test_subconfig_behavior.py',
        ]
        if args.quick:
            collector.run(
                'focused-pytest',
                focused_pytest,
                required=True,
                timeout=180,
            )
        else:
            full_pytest_code = collector.run(
                'full-pytest',
                [sys.executable, '-m', 'pytest', '-q', '-o', 'addopts=', 'tests'],
                required=True,
                timeout=300,
            )
            if args.deep or full_pytest_code != 0:
                collector.run(
                    'focused-pytest',
                    focused_pytest,
                    required=args.deep,
                    timeout=180,
                )
            else:
                collector.skip(
                    'focused-pytest',
                    'full pytest passed; focused suite would duplicate covered tests',
                )
        collector.run(
            'compileall',
            [sys.executable, '-m', 'compileall', '-q', 'kwconf'],
            required=True,
        )
        if not args.quick:
            collector.run(
                'ruff-check',
                [
                    'ruff',
                    'check',
                    'kwconf',
                    'tests',
                    'dev/rust_backend',
                    'dev/benchmarks',
                ],
                required=True,
            )

        _run_cargo_gates(collector, args)

        run_benchmarks = (
            args.quick or args.deep or not collector.has_required_failures()
        )
        if not run_benchmarks:
            reason = (
                'review profile skips repeated performance sampling after a required '
                'gate failure; pass --deep to collect it anyway'
            )
            for label in [
                'realistic-cli-benchmark',
                'real-cli-startup',
                'python-pyo3-benchmark',
                'completion-benchmark',
                'modal-benchmark',
                'help-color-benchmark',
            ]:
                collector.skip(label, reason, required=True)

        if run_benchmarks:
            realistic = bundle / 'realistic'
            realistic.mkdir()
            collector.run(
                'realistic-cli-benchmark',
                [
                    sys.executable,
                    'dev/benchmarks/realistic_cli_runtime.py',
                    '--trials',
                    str(args.realistic_trials),
                    '--warm-loops',
                    str(args.realistic_warm_loops),
                    '--output-json',
                    str(realistic / 'summary.json'),
                ],
                required=True,
                timeout=180,
            )

            startup = bundle / 'startup'
            startup.mkdir()
            startup_cmd = [
                sys.executable,
                'dev/benchmarks/cli_startup.py',
                '--trials',
                str(args.startup_trials),
                '--no-append',
                '--raw-output',
                str(startup / 'trials.csv'),
                '--summary-output',
                str(startup / 'summary.csv'),
                '--script-dir',
                str(startup / 'scripts'),
            ]
            if args.cpu is not None:
                startup_cmd += ['--cpu', str(args.cpu)]
            if args.quick:
                startup_cmd += ['--schema-sizes', '1']
            collector.run('real-cli-startup', startup_cmd, required=True, timeout=300)

            component_dir = bundle / 'components'
            component_dir.mkdir()
            collector.run(
                'python-pyo3-benchmark',
                [
                    sys.executable,
                    'dev/benchmarks/rust_cli_runtime.py',
                    '--quick',
                    '--output',
                    str(component_dir / 'rust_cli_runtime.csv'),
                ],
                required=True,
                timeout=180,
            )

            completion = bundle / 'completion'
            completion.mkdir()
            collector.run(
                'completion-benchmark',
                [
                    sys.executable,
                    'dev/benchmarks/completion_runtime.py',
                    '--trials',
                    str(args.completion_trials),
                    '--delegated-trials',
                    str(args.delegated_completion_trials),
                    '--output-json',
                    str(completion / 'summary.json'),
                    '--script-dir',
                    str(completion / 'scripts'),
                    *(['--schema-sizes', '1'] if args.quick else []),
                ],
                required=True,
                timeout=300,
            )

            modal_dir = bundle / 'modal'
            modal_dir.mkdir()
            collector.run(
                'modal-benchmark',
                [
                    sys.executable,
                    'dev/benchmarks/modal_runtime.py',
                    '--trials',
                    str(args.modal_trials),
                    '--output-json',
                    str(modal_dir / 'summary.json'),
                    '--script-dir',
                    str(modal_dir / 'scripts'),
                    *(['--schema-sizes', '1'] if args.quick else []),
                ],
                required=True,
                timeout=300,
            )

            help_dir = bundle / 'help'
            help_dir.mkdir()
            collector.run(
                'help-color-benchmark',
                [
                    sys.executable,
                    'dev/benchmarks/help_runtime.py',
                    '--trials',
                    str(args.help_trials),
                    '--output-json',
                    str(help_dir / 'summary.json'),
                    '--script-dir',
                    str(help_dir / 'scripts'),
                    *(['--schema-sizes', '1'] if args.quick else []),
                ],
                required=True,
                timeout=300,
            )

        collector.run(
            'benchmark-report',
            [
                sys.executable,
                'dev/benchmarks/benchmark_report.py',
                str(bundle),
                '--output',
                str(bundle / 'benchmark_report.html'),
            ],
            required=True,
            timeout=60,
        )

        import_dir = bundle / 'importtime'
        import_dir.mkdir()
        collector.run(
            'importtime-kwconf-core',
            [sys.executable, '-X', 'importtime', '-c', 'import kwconf; from kwconf import Config, Value'],
        )
        collector.run(
            'importtime-rust-extension',
            [sys.executable, '-X', 'importtime', '-c', 'import _kwconf_rust; print(_kwconf_rust.__file__)'],
        )
        collector.run(
            'importtime-modal',
            [sys.executable, '-X', 'importtime', '-c', 'import kwconf.modal'],
        )
        collector.run(
            'importtime-completion',
            [sys.executable, '-X', 'importtime', '-c', 'import kwconf._completion'],
        )

        if args.deep and shutil.which('cargo'):
            collector.run(
                'criterion',
                [sys.executable, 'dev/rust_backend/profile_backend.py', 'criterion'],
                required=False,
                timeout=600,
            )
        elif not args.deep:
            collector.skip('criterion', 'deep-only profiling; pass --deep to enable')
        if shutil.which('perf') and args.deep:
            perf_probe = subprocess.run(
                [shutil.which('perf'), 'stat', '-e', 'task-clock', '--', 'true'],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            if perf_probe.returncode != 0:
                reason_lines = perf_probe.stdout.strip().splitlines()
                reason = (
                    reason_lines[0]
                    if reason_lines
                    else f'perf probe returned {perf_probe.returncode}'
                )
                for label in [
                    'perf-stat-native',
                    'perf-python-rust-bridge',
                    'perf-stat-native-completion',
                    'perf-python-completion',
                ]:
                    collector.skip(label, f'perf unavailable: {reason}')
            else:
                collector.run(
                    'perf-stat-native',
                    [
                        sys.executable,
                        'dev/rust_backend/profile_backend.py',
                        'perf-stat',
                        '--workload',
                        'parse-mixed',
                        '--schema-size',
                        '256',
                        '--repeat',
                        '3',
                    ],
                    required=False,
                    timeout=300,
                )
                collector.run(
                    'perf-python-rust-bridge',
                    [
                        sys.executable,
                        'dev/rust_backend/profile_backend.py',
                        'perf-python',
                        '--workload',
                        'rust-bridge',
                        '--schema-size',
                        '256',
                        '--iterations',
                        '200000',
                        '--output',
                        str(bundle / 'perf-python-rust-bridge.data'),
                    ],
                    required=False,
                    timeout=300,
                )
                collector.run(
                    'perf-stat-native-completion',
                    [
                        sys.executable,
                        'dev/rust_backend/profile_backend.py',
                        'perf-stat',
                        '--workload',
                        'complete-options',
                        '--schema-size',
                        '256',
                        '--repeat',
                        '3',
                    ],
                    required=False,
                    timeout=300,
                )
                collector.run(
                    'perf-python-completion',
                    [
                        sys.executable,
                        'dev/rust_backend/profile_backend.py',
                        'perf-python',
                        '--workload',
                        'completion-pyo3',
                        '--schema-size',
                        '256',
                        '--iterations',
                        '100000',
                        '--output',
                        str(bundle / 'perf-python-completion.data'),
                    ],
                    required=False,
                    timeout=300,
                )
        run_cprofile = args.deep or (not args.quick and run_benchmarks)
        if run_cprofile:
            cprofile_iterations = 20000 if args.deep else 5000
            collector.run(
                'python-cprofile-rust-bridge',
                [
                    sys.executable,
                    'dev/rust_backend/profile_backend.py',
                    'python-cprofile',
                    '--workload',
                    'rust-bridge',
                    '--schema-size',
                    '256',
                    '--iterations',
                    str(cprofile_iterations),
                    '--output',
                    str(bundle / 'python-rust-bridge.prof'),
                ],
                required=False,
                timeout=300,
            )
            collector.run(
                'python-cprofile-completion',
                [
                    sys.executable,
                    'dev/rust_backend/profile_backend.py',
                    'python-cprofile',
                    '--workload',
                    'completion-pyo3',
                    '--schema-size',
                    '256',
                    '--iterations',
                    str(cprofile_iterations),
                    '--output',
                    str(bundle / 'python-completion.prof'),
                ],
                required=False,
                timeout=300,
            )
        else:
            reason = (
                'quick profile omits cProfile'
                if args.quick
                else 'required gate failure blocked review performance profiling'
            )
            collector.skip('python-cprofile-rust-bridge', reason)
            collector.skip('python-cprofile-completion', reason)

        if not args.deep and shutil.which('perf'):
            for label in [
                'perf-stat-native',
                'perf-python-rust-bridge',
                'perf-stat-native-completion',
                'perf-python-completion',
            ]:
                collector.skip(label, 'deep-only profiling; pass --deep to enable')

        if kwconf_rs is not None:
            rs = kwconf_rs
            (bundle / 'kwconf-rs-path.txt').write_text(str(rs) + '\n')
            if rs.exists():
                reference = bundle / 'kwconf-rs-reference'
                for rel in [
                    'Cargo.toml',
                    'crates/kwconf/Cargo.toml',
                    'crates/kwconf/src/spec.rs',
                    'crates/kwconf/src/cli.rs',
                    'crates/kwconf/src/command.rs',
                    'docs/contract.md',
                    'docs/roadmap.md',
                ]:
                    src = rs / rel
                    if src.exists():
                        dst = reference / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dst)
                collector.run(
                    'kwconf-rs-git-status',
                    ['git', '-c', f'safe.directory={rs}', 'status', '--short'],
                    cwd=rs,
                    required=False,
                )
                collector.run(
                    'kwconf-rs-git-revision',
                    ['git', '-c', f'safe.directory={rs}', 'rev-parse', 'HEAD'],
                    cwd=rs,
                    required=False,
                )
            if rs.exists() and shutil.which('cargo'):
                if args.deep:
                    collector.run(
                        'kwconf-rs-tests',
                        ['cargo', 'test'],
                        cwd=rs,
                        required=False,
                        timeout=600,
                    )
                else:
                    collector.skip(
                        'kwconf-rs-tests',
                        'deep-only cross-repository test run; pass --deep to enable',
                    )
                collector.run(
                    'kwconf-rs-metadata',
                    ['cargo', 'metadata', '--no-deps', '--format-version', '1'],
                    cwd=rs,
                    required=False,
                    timeout=120,
                )

        # Installed extension details are useful even when an earlier check failed.
        inspect_code = textwrap.dedent(
            '''
            import importlib.util, json
            data = {}
            spec = importlib.util.find_spec('_kwconf_rust')
            data['spec_origin'] = None if spec is None else spec.origin
            try:
                import _kwconf_rust as m
                data['file'] = m.__file__
                data['backend_info'] = m.backend_info()
                data['capabilities'] = m.backend_capabilities()
            except Exception as ex:
                data['error'] = repr(ex)
            print(json.dumps(data, indent=2))
            '''
        )
        collector.run('inspect-installed-extension', [sys.executable, '-c', inspect_code])
        _capture_wheel(bundle)

        collector.write_summary(profile=profile)
        required_failed = any(row['required'] and row['returncode'] for row in collector.rows)

        with tarfile.open(final_output, 'w:gz') as archive:
            archive.add(bundle, arcname=bundle.name)
        print('evidence bundle:', final_output, flush=True)
        print('sha256:', _sha256(final_output), flush=True)
        if required_failed:
            raise SystemExit('evidence bundle created, but one or more required checks failed')


if __name__ == '__main__':
    main()
