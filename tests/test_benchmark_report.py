from __future__ import annotations

import importlib.util
import json
import pathlib


REPO_DPATH = pathlib.Path(__file__).resolve().parents[1]
REPORT_PATH = REPO_DPATH / 'dev' / 'benchmarks' / 'benchmark_report.py'


def _load_report_module():
    spec = importlib.util.spec_from_file_location('kwconf_benchmark_report_test', REPORT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_explains_skipped_benchmarks(tmp_path):
    module = _load_report_module()
    (tmp_path / 'campaign.json').write_text('{"profile": "review"}')
    (tmp_path / 'environment.json').write_text('{"python": "3.13.13"}')
    (tmp_path / 'feature_matrix.json').write_text('{"rows": []}')
    reason = 'review profile skips repeated sampling after a required gate failure'
    labels = [
        'realistic-cli-benchmark',
        'real-cli-startup',
        'python-pyo3-benchmark',
        'completion-benchmark',
        'modal-benchmark',
        'help-color-benchmark',
    ]
    rows = [
        {
            'label': label,
            'status': 'SKIP',
            'reason': reason,
        }
        for label in labels
    ]
    (tmp_path / 'commands.json').write_text(json.dumps(rows))

    rendered = module.render(tmp_path)

    assert reason in rendered
    assert 'No startup results.' not in rendered
    assert 'Exact native output parity</span><strong>true' not in rendered
    assert 'Exact output parity</span><strong>false' not in rendered
