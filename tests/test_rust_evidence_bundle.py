from __future__ import annotations

import importlib.util
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

    quick = parser.parse_args(['--quick'])
    assert module._configure_profile(quick) == 'quick'
    assert quick.startup_trials == 2
    assert quick.completion_trials == 2
    assert quick.delegated_completion_trials == 2
    assert quick.modal_trials == 2
    assert quick.help_trials == 1

    deep = parser.parse_args(['--deep'])
    assert module._configure_profile(deep) == 'deep'
    assert deep.startup_trials == 100
    assert deep.completion_trials == 50
    assert deep.delegated_completion_trials == 50
    assert deep.modal_trials == 50
    assert deep.help_trials == 30


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
        ]
    )
    assert module._configure_profile(args) == 'review'
    assert args.startup_trials == 7
    assert args.completion_trials == 8
    assert args.delegated_completion_trials == 4
    assert args.modal_trials == 9
    assert args.help_trials == 5


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
