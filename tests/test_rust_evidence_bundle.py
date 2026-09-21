from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


REPO_DPATH = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = REPO_DPATH / 'dev' / 'rust_backend' / 'evidence_bundle.py'


def _load_evidence_module():
    spec = importlib.util.spec_from_file_location('kwconf_evidence_bundle_test', EVIDENCE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evidence_campaign_profiles():
    module = _load_evidence_module()
    parser = module._make_cli()

    review = parser.parse_args([])
    assert module._configure_profile(review) == 'review'
    assert review.startup_trials == 30
    assert review.completion_trials == 15
    assert review.delegated_completion_trials == 2
    assert review.modal_trials == 15
    assert review.help_trials == 3
    assert review.realistic_trials == 15
    assert review.realistic_warm_loops == 10000

    quick = parser.parse_args(['--quick'])
    assert module._configure_profile(quick) == 'quick'
    assert quick.startup_trials == 2
    assert quick.completion_trials == 2
    assert quick.delegated_completion_trials == 2
    assert quick.modal_trials == 2
    assert quick.help_trials == 1
    assert quick.realistic_trials == 2
    assert quick.realistic_warm_loops == 1000

    deep = parser.parse_args(['--deep'])
    assert module._configure_profile(deep) == 'deep'
    assert deep.startup_trials == 100
    assert deep.completion_trials == 50
    assert deep.delegated_completion_trials == 50
    assert deep.modal_trials == 50
    assert deep.help_trials == 30
    assert deep.realistic_trials == 50
    assert deep.realistic_warm_loops == 30000


def test_evidence_profile_explicit_trials_win():
    module = _load_evidence_module()
    args = module._make_cli().parse_args(
        [
            '--startup-trials',
            '7',
            '--completion-trials',
            '8',
            '--delegated-completion-trials',
            '4',
            '--modal-trials',
            '9',
            '--help-trials',
            '5',
            '--realistic-trials',
            '6',
            '--realistic-warm-loops',
            '7000',
        ]
    )
    assert module._configure_profile(args) == 'review'
    assert args.startup_trials == 7
    assert args.completion_trials == 8
    assert args.delegated_completion_trials == 4
    assert args.modal_trials == 9
    assert args.help_trials == 5
    assert args.realistic_trials == 6
    assert args.realistic_warm_loops == 7000


def test_evidence_html_output_option(tmp_path):
    module = _load_evidence_module()
    expected = tmp_path / 'benchmark-report.html'
    args = module._make_cli().parse_args(['--html-output', str(expected)])
    assert args.html_output == expected


def test_copy_html_report(tmp_path):
    module = _load_evidence_module()
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    source = bundle / 'benchmark_report.html'
    source.write_text('<html>report</html>')
    target = tmp_path / 'standalone' / 'report.html'

    result = module._copy_html_report(bundle, target)

    assert result == target.resolve()
    assert target.read_text() == source.read_text()


def test_evidence_profiles_are_mutually_exclusive():
    module = _load_evidence_module()
    with pytest.raises(SystemExit):
        module._make_cli().parse_args(['--quick', '--deep'])


def test_collector_records_elapsed_time(tmp_path):
    module = _load_evidence_module()
    collector = module.Collector(tmp_path, os.environ.copy())
    code = collector.run(
        'noop',
        [sys.executable, '-c', 'pass'],
        cwd=REPO_DPATH,
        required=True,
    )
    assert code == 0
    assert collector.rows[0]['elapsed_seconds'] >= 0
    assert not collector.has_required_failures()

    collector.skip('not-needed', 'test skip')
    collector.write_summary()
    summary = (tmp_path / 'SUMMARY.md').read_text()
    assert '| status | required | elapsed | command | log |' in summary
    assert 'Collected subprocess time:' in summary
    rows = json.loads((tmp_path / 'commands.json').read_text())
    assert rows[-1]['reason'] == 'test skip'


def test_benchmark_gate_is_independent_from_repo_policy_failures(tmp_path):
    module = _load_evidence_module()
    collector = module.Collector(tmp_path, os.environ.copy())

    # A required repository-policy failure still makes the evidence campaign
    # non-green, but it must not invalidate otherwise meaningful benchmarks.
    collector.rows.append(
        {
            'label': 'ruff-check',
            'required': True,
            'returncode': 1,
            'elapsed_seconds': 0.0,
            'log': 'commands/ruff.log',
            'command': ['ruff', 'check'],
        }
    )
    assert collector.has_required_failures()
    assert collector.failed_labels(module.BENCHMARK_PREREQUISITE_LABELS) == []

    # Backend parity is a benchmark-validity prerequisite, so this one does block.
    collector.rows.append(
        {
            'label': 'backend-parity',
            'required': True,
            'returncode': 1,
            'elapsed_seconds': 0.0,
            'log': 'commands/backend-parity.log',
            'command': ['python', 'check_backend.py'],
        }
    )
    assert collector.failed_labels(module.BENCHMARK_PREREQUISITE_LABELS) == [
        'backend-parity'
    ]
