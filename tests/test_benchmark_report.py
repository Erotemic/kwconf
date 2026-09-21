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
        'cold-start-breakdown',
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


def test_report_leads_with_fresh_process_decomposition(tmp_path):
    module = _load_report_module()
    (tmp_path / 'campaign.json').write_text('{"profile": "review"}')
    (tmp_path / 'environment.json').write_text('{"python": "3.13.13"}')
    (tmp_path / 'feature_matrix.json').write_text('{"rows": []}')
    (tmp_path / 'commands.json').write_text('[]')
    cold = tmp_path / 'cold_breakdown'
    cold.mkdir()

    def metric(value):
        return {
            'median_ns': value,
            'mean_ns': value,
            'p10_ns': value,
            'p90_ns': value,
            'min_ns': value,
        }

    def method(total, envelope, imported, defined, parsed):
        body = imported + defined + parsed + 1000
        return {
            'total_ns': metric(total),
            'body_ns': metric(body),
            'process_envelope_ns': metric(envelope),
            'import_ns': metric(imported),
            'definition_ns': metric(defined),
            'parse_ns': metric(parsed),
            'other_body_ns': metric(1000),
            'delta_vs_python_baseline_ns': 0,
        }

    default_methods = {
        'python_baseline': method(90_000_000, 89_999_000, 0, 0, 0),
        'argparse': method(92_000_000, 89_000_000, 500_000, 2_000_000, 20_000),
        'kwconf_python': method(94_000_000, 89_000_000, 800_000, 300_000, 3_000_000),
        'kwconf_rust': method(91_000_000, 89_000_000, 800_000, 300_000, 500_000),
    }
    no_site_methods = {
        'python_baseline': method(12_000_000, 11_999_000, 0, 0, 0),
        'argparse': method(14_000_000, 11_000_000, 500_000, 2_000_000, 20_000),
        'kwconf_python': method(16_000_000, 11_000_000, 800_000, 300_000, 3_000_000),
        'kwconf_rust': method(13_000_000, 11_000_000, 800_000, 300_000, 500_000),
    }
    payload = {
        'profiles': {
            'default': {'cases': [{'schema_size': 64, 'methods': default_methods}]},
            'no_site': {'cases': [{'schema_size': 64, 'methods': no_site_methods}]},
        }
    }
    (cold / 'summary.json').write_text(json.dumps(payload))

    rendered = module.render(tmp_path)

    assert rendered.index('What a user pays on a cold start') < rendered.index(
        'Implementation diagnostics'
    )
    assert 'Python baseline' in rendered
    assert 'kwconf Python' in rendered
    assert 'kwconf Rust' in rendered
    assert 'First parse' in rendered
    assert 'If Python startup were cheaper' in rendered
    assert 'python -S' in rendered
    assert 'Warm parse' not in rendered
