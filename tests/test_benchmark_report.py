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
        'cold-backend-phases',
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
            'preloaded_modules_stable': True,
            'preloaded_modules': ['re'],
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
        'preload_probe_modules': ['argparse', 're', 'kwconf'],
        'profiles': {
            'default': {'cases': [{'schema_size': 64, 'methods': default_methods}]},
            'no_site': {'cases': [{'schema_size': 64, 'methods': no_site_methods}]},
        }
    }
    (cold / 'summary.json').write_text(json.dumps(payload))

    cold_backend = tmp_path / 'cold_backend'
    cold_backend.mkdir()

    def phase_method(
        definition,
        instance,
        backend,
        parse,
        reset=0,
        reparse=0,
        apply=0,
        api=0,
        rust_bridge=0,
        extension=0,
        schema=0,
        parser_build=0,
    ):
        return {
            'api_ns': metric(api),
            'definition_ns': metric(definition),
            'instance_ns': metric(instance),
            'backend_ns': metric(backend),
            'rust_bridge_ns': metric(rust_bridge),
            'extension_ns': metric(extension),
            'schema_ns': metric(schema),
            'parser_build_ns': metric(parser_build),
            'parse_ns': metric(parse),
            'reset_ns': metric(reset),
            'reparse_ns': metric(reparse),
            'apply_ns': metric(apply),
        }

    phase_payload = {
        'schema_size': 64,
        'profiles': {
            'default': {
                'methods': {
                    'argparse': phase_method(700_000, 0, 0, 100_000),
                    'kwconf_python': phase_method(300_000, 80_000, 4_000_000, 150_000, 30_000, 0, 30_000, api=1_200_000),
                    'kwconf_rust': phase_method(300_000, 80_000, 800_000, 12_000, 30_000, 7_000, 30_000, api=1_200_000, rust_bridge=250_000, extension=350_000, schema=80_000, parser_build=120_000),
                }
            }
        },
    }
    (cold_backend / 'summary.json').write_text(json.dumps(phase_payload))

    rendered = module.render(tmp_path)

    assert rendered.index('What a user pays on a cold start') < rendered.index(
        'Implementation diagnostics'
    )
    assert 'Python baseline' in rendered
    assert 'kwconf Python' in rendered
    assert 'kwconf Rust' in rendered
    assert 'Where the CLI work goes' in rendered
    assert 'Backend materialization' in rendered
    assert 'kwconf API realization' in rendered
    assert 'Rust compiler core' in rendered
    assert 'Rust load overhead' in rendered
    assert 'Show Rust backend materialization breakdown' in rendered
    assert 'Parser engine' in rendered
    assert 'FlatParser.parse()' in rendered
    assert 'If Python startup were cheaper' in rendered
    assert 'python -S' in rendered
    assert 'Warm parse' not in rendered
    assert 'Show modules already loaded before CLI timing' in rendered


def test_report_highlights_cold_tab_completion_three_way(tmp_path):
    module = _load_report_module()
    (tmp_path / 'campaign.json').write_text('{"profile": "review"}')
    (tmp_path / 'environment.json').write_text('{"python": "3.13.13"}')
    (tmp_path / 'feature_matrix.json').write_text('{"rows": []}')
    (tmp_path / 'commands.json').write_text('[]')
    completion = tmp_path / 'completion'
    completion.mkdir()

    def method(ms):
        return {
            'median_ms': ms,
            'mean_ms': ms,
            'p10_ms': ms,
            'p90_ms': ms,
            'min_ms': ms,
            'ratio': 1.0,
            'stable_output': True,
            'candidates': ['x'],
            'candidate_parity': True,
            'exact_output_parity': True,
        }

    cases = []
    for scenario, values in [
        ('options', (48.0, 55.0, 46.0)),
        ('choices', (47.0, 69.0, 45.0)),
    ]:
        cases.append(
            {
                'scenario': scenario,
                'schema_size': 64,
                'expected_ownership': 'native',
                'methods': {
                    'argparse_argcomplete': method(values[0]),
                    'kwconf_python': method(values[1]),
                    'kwconf_rust': method(values[2]),
                },
            }
        )
    cases.append(
        {
            'scenario': 'dynamic-value',
            'schema_size': 1,
            'expected_ownership': 'delegated',
            'methods': {'kwconf_rust': method(60.0)},
        }
    )
    payload = {
        'method_labels': {
            'argparse_argcomplete': 'argparse + argcomplete',
            'kwconf_python': 'kwconf Python + argcomplete',
            'kwconf_rust': 'kwconf Rust native fast path',
        },
        'cases': cases,
    }
    (completion / 'summary.json').write_text(json.dumps(payload))

    rendered = module.render(tmp_path)

    assert 'Cold Tab-completion latency' in rendered
    assert 'argparse + argcomplete' in rendered
    assert 'kwconf Python + argcomplete' in rendered
    assert 'kwconf Rust native fast path' in rendered
    assert 'Option-name Tab' in rendered
    assert 'Choice-value Tab' in rendered
    assert '9.00 ms saved' in rendered
    assert '24.00 ms saved' in rendered
    assert rendered.index('Cold Tab-completion latency') < rendered.index(
        'Implementation diagnostics'
    )


def test_report_renders_realistic_lifecycle_attribution(tmp_path):
    module = _load_report_module()
    (tmp_path / 'campaign.json').write_text('{"profile": "review"}')
    (tmp_path / 'environment.json').write_text('{"python": "3.13.13"}')
    (tmp_path / 'feature_matrix.json').write_text('{"rows": []}')
    (tmp_path / 'commands.json').write_text('[]')

    realistic = tmp_path / 'realistic'
    realistic.mkdir()
    (realistic / 'summary.json').write_text(
        json.dumps(
            {
                'cold': {
                    'argparse': {'median_ns': 50_000_000},
                    'kwconf': {'median_ns': 52_000_000},
                },
                'ratios': {'cold_kwconf_vs_argparse': 1.04},
                'output_parity': True,
            }
        )
    )

    realistic_phases = tmp_path / 'realistic_phases'
    realistic_phases.mkdir()

    def metric(value):
        return {
            'median_ns': value,
            'mean_ns': value,
            'p10_ns': value,
            'p90_ns': value,
            'min_ns': value,
        }

    def method(api, definition, instance, backend, parse, reset=0, reparse=0, apply=0,
               rust_bridge=0, extension=0, schema=0, parser_build=0):
        return {
            'api_ns': metric(api),
            'definition_ns': metric(definition),
            'instance_ns': metric(instance),
            'backend_ns': metric(backend),
            'parse_ns': metric(parse),
            'reset_ns': metric(reset),
            'reparse_ns': metric(reparse),
            'apply_ns': metric(apply),
            'rust_bridge_ns': metric(rust_bridge),
            'extension_ns': metric(extension),
            'schema_ns': metric(schema),
            'parser_build_ns': metric(parser_build),
        }

    (realistic_phases / 'summary.json').write_text(
        json.dumps(
            {
                'output_parity': True,
                'methods': {
                    'argparse': method(0, 700_000, 0, 0, 100_000),
                    'kwconf_python': method(
                        1_500_000, 250_000, 60_000, 4_000_000, 180_000, reset=20_000, apply=50_000
                    ),
                    'kwconf_rust': method(
                        1_500_000, 250_000, 60_000, 500_000, 20_000,
                        reset=20_000, reparse=10_000, apply=50_000,
                        extension=400_000, schema=60_000, parser_build=40_000,
                    ),
                },
            }
        )
    )

    rendered = module.render(tmp_path)
    assert 'Why the production-style CLI costs what it costs' in rendered
    assert 'production-style sample argv' in rendered
    assert 'Show production-style Rust backend breakdown' in rendered
    assert 'kwconf Python' in rendered
    assert 'kwconf Rust' in rendered
