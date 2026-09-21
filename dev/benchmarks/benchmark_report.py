#!/usr/bin/env python3
"""Render a self-contained HTML report from a kwconf Rust evidence directory."""

from __future__ import annotations

import argparse
import csv
import html
import json
import statistics
from pathlib import Path
from typing import Any

REPO_DPATH = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_DPATH / 'examples' / '09_argparse_comparison.py'


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline='') as file:
        return list(csv.DictReader(file))


def _command_skip_reason(evidence: Path, label: str) -> str | None:
    rows = _read_json(evidence / 'commands.json', [])
    for row in rows:
        if row.get('label') == label and row.get('status') == 'SKIP':
            return row.get('reason') or 'the campaign skipped this measurement'
    return None


def _missing_message(evidence: Path, label: str, fallback: str) -> str:
    reason = _command_skip_reason(evidence, label)
    if reason:
        return f'Not collected: {html.escape(str(reason))}.'
    return fallback


def _extract_snippet(text: str, name: str) -> str:
    start = f'# REPORT_SNIPPET_{name}_START'
    end = f'# REPORT_SNIPPET_{name}_END'
    return text.split(start, 1)[1].split(end, 1)[0].strip('\n')


def _ms(ns: float) -> str:
    return f'{ns / 1e6:.2f} ms'


def _us(seconds: float) -> str:
    return f'{seconds * 1e6:.1f} µs'


def _duration_ns(ns: float) -> str:
    if ns >= 1e6:
        return f'{ns / 1e6:.2f} ms'
    if ns >= 1e3:
        return f'{ns / 1e3:.1f} µs'
    return f'{ns:.0f} ns'


def _ratio(value: float) -> str:
    return f'{value:.3f}×'


def _ratio_class(value: float) -> str:
    if value < 0.95:
        return 'win'
    if value <= 1.05:
        return 'near'
    return 'loss'


def _bar(label: str, value: float, max_value: float, suffix: str) -> str:
    width = 4 if max_value <= 0 else max(4.0, 100.0 * value / max_value)
    return (
        '<div class="bar-row">'
        f'<div class="bar-label">{html.escape(label)}</div>'
        '<div class="bar-track">'
        f'<div class="bar-fill" style="width:{width:.2f}%"></div>'
        '</div>'
        f'<div class="bar-value">{value:.2f}{html.escape(suffix)}</div>'
        '</div>'
    )


def _cold_case(
    data: dict[str, Any], profile: str, preferred_size: int = 64
) -> dict[str, Any] | None:
    profile_data = data.get('profiles', {}).get(profile, {})
    cases = profile_data.get('cases', [])
    if not cases:
        return None
    return min(cases, key=lambda case: abs(int(case['schema_size']) - preferred_size))


def _metric_median(method: dict[str, Any], key: str) -> float:
    return float(method[key]['median_ns'])


def _render_cold_breakdown(evidence: Path) -> str:
    data = _read_json(evidence / 'cold_breakdown' / 'summary.json', {})
    default_case = _cold_case(data, 'default')
    if default_case is None:
        message = _missing_message(
            evidence,
            'cold-start-breakdown',
            'No fresh-process decomposition results were found.',
        )
        return (
            '<section id="cold-decomposition">'
            '<h2>Fresh-process cost breakdown</h2>'
            f'<p>{message}</p></section>'
        )

    size = int(default_case['schema_size'])
    methods = default_case['methods']
    baseline_method = methods.get('python_baseline')
    baseline_total = (
        _metric_median(baseline_method, 'total_ns')
        if baseline_method is not None
        else 0.0
    )
    labels = [
        ('python_baseline', 'Python baseline'),
        ('argparse', 'argparse'),
        ('kwconf_python', 'kwconf Python'),
        ('kwconf_rust', 'kwconf Rust'),
    ]
    cards = []
    rows = []
    for key, label in labels:
        method = methods.get(key)
        if method is None:
            continue
        total = _metric_median(method, 'total_ns')
        card_note = (
            'bare fresh process'
            if key == 'python_baseline'
            else 'fresh process median'
        )
        cards.append(
            f'<div class="metric"><span>{html.escape(label)}</span>'
            f'<strong>{_duration_ns(total)}</strong>'
            f'<small>{html.escape(card_note)}</small></div>'
        )
        delta = total - baseline_total if key != 'python_baseline' else 0.0
        body = _metric_median(method, 'body_ns')
        imported = _metric_median(method, 'import_ns')
        cli_after_import = max(0.0, body - imported)
        rows.append(
            '<tr>'
            f'<td>{html.escape(label)}</td>'
            f'<td><strong>{_duration_ns(total)}</strong></td>'
            f'<td>{"—" if key == "python_baseline" else _duration_ns(delta)}</td>'
            f'<td>{_duration_ns(_metric_median(method, "process_envelope_ns"))}</td>'
            f'<td>{_duration_ns(imported)}</td>'
            f'<td>{_duration_ns(cli_after_import)}</td>'
            '</tr>'
        )
    return f'''<section id="cold-decomposition" class="hero">
<h2>What a user pays on a cold start</h2>
<p>Fresh Python process, {size}-field CLI, and one supplied option. Each observation launches a new process. The process envelope includes interpreter initialization, script loading, output, and teardown. The detailed backend section below separates schema definition, backend construction, token parsing, and Config lifecycle work; this headline table deliberately avoids calling all lazy first-use work “parse”.</p>
<div class="metric-grid">{''.join(cards)}</div>
<table><thead><tr><th>Implementation</th><th>Total wall clock</th><th>Extra over bare Python</th><th>Process envelope</th><th>Library import</th><th>CLI body after import</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</section>'''


def _render_backend_phases(evidence: Path) -> str:
    data = _read_json(evidence / 'cold_backend' / 'summary.json', {})
    profile = data.get('profiles', {}).get('default', {})
    methods = profile.get('methods', {})
    if not methods:
        message = _missing_message(
            evidence,
            'cold-backend-phases',
            'No cold backend phase results were found.',
        )
        return (
            '<section id="backend-phases"><h2>Where the CLI work goes</h2>'
            f'<p>{message}</p></section>'
        )

    size = int(data.get('schema_size', 64))
    labels = [
        ('argparse', 'argparse'),
        ('kwconf_python', 'kwconf Python'),
        ('kwconf_rust', 'kwconf Rust'),
    ]
    rows = []
    for key, label in labels:
        method = methods.get(key)
        if method is None:
            continue
        rows.append(
            '<tr>'
            f'<td>{html.escape(label)}</td>'
            f'<td>{_duration_ns(_metric_median(method, "api_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "definition_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "instance_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "backend_ns"))}</td>'
            f'<td><strong>{_duration_ns(_metric_median(method, "parse_ns"))}</strong></td>'
            f'<td>{_duration_ns(_metric_median(method, "reset_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "reparse_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "apply_ns"))}</td>'
            '</tr>'
        )

    py_method = methods.get('kwconf_python')
    rust_method = methods.get('kwconf_rust')
    cards = []
    if py_method and rust_method:
        py_backend = _metric_median(py_method, 'backend_ns')
        rust_backend = _metric_median(rust_method, 'backend_ns')
        if py_backend:
            cards.append(
                '<div class="metric"><span>Backend materialization</span>'
                f'<strong>{_ratio(rust_backend / py_backend)}</strong>'
                '<small>Rust / kwconf Python; lower is faster</small></div>'
            )
        rust_bridge = _metric_median(rust_method, 'rust_bridge_ns')
        rust_extension = _metric_median(rust_method, 'extension_ns')
        rust_schema = _metric_median(rust_method, 'schema_ns')
        rust_parser_build = _metric_median(rust_method, 'parser_build_ns')
        cards.append(
            '<div class="metric"><span>Rust compiler core</span>'
            f'<strong>{_duration_ns(rust_schema + rust_parser_build)}</strong>'
            '<small>schema extraction + <code>FlatParser</code> construction</small></div>'
        )
        cards.append(
            '<div class="metric"><span>Rust load overhead</span>'
            f'<strong>{_duration_ns(rust_bridge + rust_extension)}</strong>'
            '<small>direct hot core + extension/protocol load</small></div>'
        )
        rust_parse = _metric_median(rust_method, 'parse_ns')
        cards.append(
            '<div class="metric"><span>Rust token parse</span>'
            f'<strong>{_duration_ns(rust_parse)}</strong>'
            '<small><code>FlatParser.parse()</code>, not setup</small></div>'
        )
        rust_reparse = _metric_median(rust_method, 'reparse_ns')
        cards.append(
            '<div class="metric"><span>Compatibility reparse</span>'
            f'<strong>{_duration_ns(rust_reparse)}</strong>'
            '<small>second parse after canonical reset</small></div>'
        )

    rust_detail_rows = []
    if rust_method:
        for label, metric_name in [
            ('Import common Rust bridge (0 when resident in <code>config.py</code>)', 'rust_bridge_ns'),
            ('Import/check <code>_kwconf_rust</code> extension', 'extension_ns'),
            ('Extract normalized kwconf schema', 'schema_ns'),
            ('Construct/cache <code>FlatParser</code>', 'parser_build_ns'),
        ]:
            rust_detail_rows.append(
                '<tr>'
                f'<td>{label}</td>'
                f'<td>{_duration_ns(_metric_median(rust_method, metric_name))}</td>'
                '</tr>'
            )

    return f'''<section id="backend-phases">
<h2>Where the CLI work goes</h2>
<p>Fresh-process attribution for a representative {size}-field CLI. The kwconf rows now separate first realization of the lazy <code>kwconf.Config</code> API from actual Config subclass construction; this prevents module-loading work from being mislabeled as schema-definition cost. argparse's normal <code>ArgumentParser()</code> + <code>add_argument()</code> definition already materializes its backend, so its separate backend-build column is zero.</p>
<div class="metric-grid">{''.join(cards)}</div>
<table><thead><tr><th>Implementation</th><th>kwconf API realization</th><th>Schema/parser definition</th><th>Config instance</th><th>Backend materialization</th><th>Parser engine</th><th>Canonical reset</th><th>Compatibility reparse</th><th>Apply/finalize</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="note">For kwconf Python, backend materialization constructs the real <code>ExtendedArgumentParser</code>. For the common kwconf Rust path, the tiny bridge is already resident in <code>config.py</code>; backend materialization therefore imports only the extension and compiles <code>FlatParser</code>. Richer shapes still delegate to the full <code>kwconf._rust</code> bridge. It never constructs argparse on the successful native fast path. The public <code>.argparse()</code> API remains available and intentionally constructs a Python parser when explicitly requested.</p>
<details><summary>Show Rust backend materialization breakdown</summary><table><thead><tr><th>Phase</th><th>Median</th></tr></thead><tbody>{''.join(rust_detail_rows)}</tbody></table></details>
</section>'''

def _render_no_site(evidence: Path) -> str:
    data = _read_json(evidence / 'cold_breakdown' / 'summary.json', {})
    default_case = _cold_case(data, 'default')
    no_site_case = _cold_case(data, 'no_site')
    if default_case is None or no_site_case is None:
        return ''

    size = int(default_case['schema_size'])
    normal_methods = default_case['methods']
    stripped_methods = no_site_case['methods']
    normal_base = _metric_median(normal_methods['python_baseline'], 'total_ns')
    stripped_base = _metric_median(stripped_methods['python_baseline'], 'total_ns')
    saved = normal_base - stripped_base
    saved_pct = 100.0 * saved / normal_base if normal_base else 0.0
    rows = []
    for key, label in [
        ('argparse', 'argparse'),
        ('kwconf_python', 'kwconf Python'),
        ('kwconf_rust', 'kwconf Rust'),
    ]:
        normal = normal_methods.get(key)
        stripped = stripped_methods.get(key)
        if normal is None or stripped is None:
            continue
        normal_total = _metric_median(normal, 'total_ns')
        stripped_total = _metric_median(stripped, 'total_ns')
        import_ns = _metric_median(stripped, 'import_ns')
        body_ns = _metric_median(stripped, 'body_ns')
        cli_after_import = max(0.0, body_ns - import_ns)
        cli_share = 100.0 * cli_after_import / stripped_total if stripped_total else 0.0
        rows.append(
            '<tr>'
            f'<td>{html.escape(label)}</td>'
            f'<td>{_duration_ns(normal_total)}</td>'
            f'<td><strong>{_duration_ns(stripped_total)}</strong></td>'
            f'<td>{_duration_ns(normal_total - stripped_total)}</td>'
            f'<td>{_duration_ns(import_ns)}</td>'
            f'<td>{_duration_ns(cli_after_import)}</td>'
            f'<td>{cli_share:.1f}%</td>'
            '</tr>'
        )

    probe_modules = data.get('preload_probe_modules', [])
    preload_rows = []
    normal_probe = normal_methods.get('python_baseline', {})
    stripped_probe = stripped_methods.get('python_baseline', {})
    normal_loaded = set(normal_probe.get('preloaded_modules', []))
    stripped_loaded = set(stripped_probe.get('preloaded_modules', []))
    for name in probe_modules:
        preload_rows.append(
            '<tr>'
            f'<td><code>{html.escape(str(name))}</code></td>'
            f'<td>{"loaded" if name in normal_loaded else "—"}</td>'
            f'<td>{"loaded" if name in stripped_loaded else "—"}</td>'
            '</tr>'
        )
    preload_block = ''
    if preload_rows:
        preload_block = (
            '<details><summary>Show modules already loaded before CLI timing</summary>'
            '<p class="note">The probe runs after importing only <code>sys</code> and '
            '<code>time.perf_counter_ns</code>, and before the timed CLI-library import. '
            'Differences here explain work that <code>-S</code> shifts into later phases.</p>'
            '<table><thead><tr><th>Module</th><th>Normal Python</th>'
            '<th><code>python -S</code></th></tr></thead>'
            f'<tbody>{"".join(preload_rows)}</tbody></table></details>'
        )

    return f'''<section id="no-site">
<h2>If Python startup were cheaper</h2>
<p>This is a diagnostic, not the normal execution mode. It launches the same {size}-field programs with <code>python -S</code>, while explicitly restoring the parent environment's site-packages paths so kwconf and the Rust extension remain importable. This asks how much ordinary <code>site</code> initialization masks CLI work.</p>
<div class="metric-grid">
<div class="metric"><span>Normal Python baseline</span><strong>{_duration_ns(normal_base)}</strong><small>fresh process</small></div>
<div class="metric"><span><code>python -S</code> baseline</span><strong>{_duration_ns(stripped_base)}</strong><small>same dependency paths injected explicitly</small></div>
<div class="metric"><span>Startup removed</span><strong>{_duration_ns(saved)}</strong><small>{saved_pct:.1f}% of the normal baseline</small></div>
</div>
<table><thead><tr><th>Implementation</th><th>Normal total</th><th><code>-S</code> total</th><th>Saved</th><th>Import</th><th>CLI body after import</th><th>CLI-body share</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
{preload_block}
</section>'''


def _render_startup(evidence: Path) -> str:
    data = _read_json(evidence / 'cold_breakdown' / 'summary.json', {})
    profile = data.get('profiles', {}).get('default', {})
    cases = profile.get('cases', [])
    if not cases:
        message = _missing_message(
            evidence,
            'cold-start-breakdown',
            'No cold-start scaling results were found.',
        )
        return f'<section><h2>Cold-start scaling</h2><p>{message}</p></section>'
    body = []
    for case in sorted(cases, key=lambda item: int(item['schema_size'])):
        size = int(case['schema_size'])
        methods = case['methods']
        argparse_method = methods.get('argparse')
        if argparse_method is None:
            continue
        baseline = _metric_median(argparse_method, 'total_ns')
        body.append('<tr>')
        body.append(f'<td>{size}</td><td><strong>{_duration_ns(baseline)}</strong></td>')
        for name in ('kwconf_python', 'kwconf_rust'):
            method = methods.get(name)
            if method is None:
                body.append('<td>—</td><td>—</td>')
            else:
                total = _metric_median(method, 'total_ns')
                ratio = total / baseline
                body.append(
                    f'<td>{_duration_ns(total)}</td>'
                    f'<td class="{_ratio_class(ratio)}">{_ratio(ratio)}</td>'
                )
        body.append('</tr>')
    return f'''<section id="startup"><h2>Cold-start scaling</h2>
<p>Fresh interpreter + imports + CLI definition + one first parse. These are user-facing end-to-end timings, not warm loops.</p>
<table><thead><tr><th>Fields</th><th>argparse</th><th>kwconf Python</th><th>Python ratio</th><th>kwconf Rust</th><th>Rust ratio</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></section>'''



def _render_realistic_phases(evidence: Path) -> str:
    data = _read_json(evidence / 'realistic_phases' / 'summary.json', {})
    methods = data.get('methods', {})
    if not methods:
        message = _missing_message(
            evidence,
            'realistic-cli-phases',
            'No production-style lifecycle attribution was collected.',
        )
        return (
            '<div class="subcard"><h3>Production-style lifecycle attribution</h3>'
            f'<p>{message}</p></div>'
        )

    labels = [
        ('argparse', 'argparse'),
        ('kwconf_python', 'kwconf Python'),
        ('kwconf_rust', 'kwconf Rust'),
    ]
    rows = []
    for key, label in labels:
        method = methods.get(key)
        if method is None:
            continue
        rows.append(
            '<tr>'
            f'<td>{html.escape(label)}</td>'
            f'<td>{_duration_ns(_metric_median(method, "api_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "definition_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "instance_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "backend_ns"))}</td>'
            f'<td><strong>{_duration_ns(_metric_median(method, "parse_ns"))}</strong></td>'
            f'<td>{_duration_ns(_metric_median(method, "reset_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "reparse_ns"))}</td>'
            f'<td>{_duration_ns(_metric_median(method, "apply_ns"))}</td>'
            '</tr>'
        )

    rust = methods.get('kwconf_rust')
    py_method = methods.get('kwconf_python')
    cards = []
    detail = ''
    if rust is not None:
        rust_schema = _metric_median(rust, 'schema_ns')
        rust_build = _metric_median(rust, 'parser_build_ns')
        rust_extension = _metric_median(rust, 'extension_ns')
        rust_parse = _metric_median(rust, 'parse_ns')
        cards.extend([
            '<div class="metric"><span>Rust backend materialization</span>'
            f'<strong>{_duration_ns(_metric_median(rust, "backend_ns"))}</strong>'
            '<small>extension + schema + FlatParser</small></div>',
            '<div class="metric"><span>Rust compiler core</span>'
            f'<strong>{_duration_ns(rust_schema + rust_build)}</strong>'
            '<small>schema extraction + FlatParser construction</small></div>',
            '<div class="metric"><span>Rust token parse</span>'
            f'<strong>{_duration_ns(rust_parse)}</strong>'
            '<small>production-style sample argv</small></div>',
        ])
        if py_method is not None:
            py_backend = _metric_median(py_method, 'backend_ns')
            rust_backend = _metric_median(rust, 'backend_ns')
            if py_backend:
                cards.append(
                    '<div class="metric"><span>Backend ratio</span>'
                    f'<strong>{_ratio(rust_backend / py_backend)}</strong>'
                    '<small>Rust / kwconf Python</small></div>'
                )
        detail = (
            '<details><summary>Show production-style Rust backend breakdown</summary>'
            '<table><thead><tr><th>Phase</th><th>Median</th></tr></thead><tbody>'
            '<tr><td>Import common Rust bridge</td>'
            f'<td>{_duration_ns(_metric_median(rust, "rust_bridge_ns"))}</td></tr>'
            '<tr><td>Import/check <code>_kwconf_rust</code></td>'
            f'<td>{_duration_ns(rust_extension)}</td></tr>'
            '<tr><td>Extract normalized production schema</td>'
            f'<td>{_duration_ns(rust_schema)}</td></tr>'
            '<tr><td>Construct/cache <code>FlatParser</code></td>'
            f'<td>{_duration_ns(rust_build)}</td></tr>'
            '</tbody></table></details>'
        )

    return (
        '<div class="subcard"><h3>Why the production-style CLI costs what it costs</h3>'
        '<p>This repeats the lifecycle attribution using the exact schema and sample argv from '
        '<code>examples/09_argparse_comparison.py</code>, rather than the synthetic all-string schema. '
        'The separate cold-process medians above remain the user-facing result.</p>'
        f'<div class="metric-grid">{"".join(cards)}</div>'
        '<table><thead><tr><th>Implementation</th><th>kwconf API realization</th>'
        '<th>Schema/parser definition</th><th>Config instance</th><th>Backend materialization</th>'
        '<th>Parser engine</th><th>Canonical reset</th><th>Compatibility reparse</th>'
        '<th>Apply/finalize</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>{detail}</div>'
    )

def _render_realistic(evidence: Path) -> str:
    data = _read_json(evidence / 'realistic' / 'summary.json')
    snapshot_example = evidence / 'source_snapshot' / 'examples' / EXAMPLE.name
    source_path = snapshot_example if snapshot_example.exists() else EXAMPLE
    source = source_path.read_text() if source_path.exists() else ''
    snippets = ''
    if source:
        argparse_code = html.escape(_extract_snippet(source, 'ARGPARSE'))
        kwconf_code = html.escape(_extract_snippet(source, 'KWCONF'))
        snippets = f'''<details><summary>Show equivalent argparse and kwconf source</summary><div class="code-grid">
<section><h3>argparse</h3><pre><code>{argparse_code}</code></pre></section>
<section><h3>kwconf</h3><pre><code>{kwconf_code}</code></pre></section>
</div></details>'''
    if not data:
        fallback = (
            'No measured realistic-CLI row was found in this evidence bundle.'
            if source
            else 'This evidence bundle predates the realistic-CLI benchmark.'
        )
        message = _missing_message(evidence, 'realistic-cli-benchmark', fallback)
        return f'''<section id="realistic"><h2>Production-style cold check</h2>
<p>{message}</p>{snippets}</section>'''

    cold_argparse = float(data['cold']['argparse']['median_ns'])
    cold_kwconf = float(data['cold']['kwconf']['median_ns'])
    cold_ratio = float(data['ratios']['cold_kwconf_vs_argparse'])
    cold_max = max(cold_argparse, cold_kwconf) / 1e6
    phase_html = _render_realistic_phases(evidence)
    return f'''<section id="realistic"><h2>Production-style cold check</h2>
<p>A 24-option CLI implemented both ways, launched in a fresh process. Output parity: <strong>{str(bool(data.get('output_parity'))).lower()}</strong>.</p>
<div class="metric-grid">
<div class="metric"><span>argparse</span><strong>{_duration_ns(cold_argparse)}</strong><small>cold process median</small></div>
<div class="metric"><span>kwconf auto</span><strong>{_duration_ns(cold_kwconf)}</strong><small>cold process median</small></div>
<div class="metric"><span>kwconf / argparse</span><strong class="{_ratio_class(cold_ratio)}">{_ratio(cold_ratio)}</strong><small>lower is faster</small></div>
</div>
<div class="chart"><h3>Cold process median</h3>
{_bar('argparse', cold_argparse / 1e6, cold_max, ' ms')}
{_bar('kwconf', cold_kwconf / 1e6, cold_max, ' ms')}</div>
{phase_html}
{snippets}</section>'''


def _render_components(evidence: Path) -> str:
    rows = _read_csv(evidence / 'components' / 'rust_cli_runtime.csv')
    if not rows:
        message = _missing_message(
            evidence,
            'python-pyo3-benchmark',
            'No in-process component results were found.',
        )
        return (
            '<section><h2>Implementation diagnostics</h2>'
            f'<p>{message}</p></section>'
        )
    wanted = [
        'declaration_build',
        'schema_build',
        'one_shot_end_to_end',
        'hot_parse',
    ]
    blocks = []
    for family in wanted:
        family_rows = [row for row in rows if row['family'] == family]
        if not family_rows:
            continue
        sizes = sorted({int(row['schema_size']) for row in family_rows})
        selected = [size for size in (16, 64, 256) if size in sizes] or sizes[:3]
        table_rows = []
        for size in selected:
            candidates = [
                row for row in family_rows if int(row['schema_size']) == size
            ]
            baseline = next(
                (row for row in candidates if row['method'] == 'argparse'), None
            )
            if baseline is None:
                continue
            target = next(
                (
                    row
                    for name in (
                        'kwconf_rust',
                        'rust_bridge',
                        'rust_uncached',
                        'rust_pyo3_parse',
                        'kwconf_typed',
                    )
                    for row in candidates
                    if row['method'] == name
                ),
                None,
            )
            if target is None:
                continue
            baseline_s = float(baseline['mean_s'])
            target_s = float(target['mean_s'])
            ratio = target_s / baseline_s
            table_rows.append(
                f'<tr><td>{size}</td><td>{html.escape(target["method"])}</td>'
                f'<td>{_us(baseline_s)}</td><td>{_us(target_s)}</td>'
                f'<td class="{_ratio_class(ratio)}">{_ratio(ratio)}</td></tr>'
            )
        if table_rows:
            title = family.replace('_', ' ').title()
            blocks.append(
                f'<div class="subcard"><h3>{title}</h3>'
                '<table><thead><tr><th>Fields</th><th>Rust path</th>'
                '<th>argparse</th><th>kwconf/Rust</th><th>ratio</th></tr></thead>'
                f'<tbody>{"".join(table_rows)}</tbody></table></div>'
            )
    return (
        '<section id="components"><h2>Implementation diagnostics</h2>'
        '<p>These in-process microbenchmarks explain where time goes, but they '
        'are not cold-start user timings. Repeated warm-loop throughput is '
        'intentionally omitted from the main report.</p>'
        '<details><summary>Show in-process attribution benchmarks</summary>'
        + ''.join(blocks)
        + '</details></section>'
    )


def _render_completion(evidence: Path) -> str:
    data = _read_json(evidence / 'completion' / 'summary.json', {})
    cases = data.get('cases', [])
    if not cases:
        message = _missing_message(
            evidence,
            'completion-benchmark',
            'No completion benchmark results were found.',
        )
        return (
            '<section id="completion"><h2>Cold Tab-completion latency</h2>'
            f'<p>{message}</p></section>'
        )

    native = [case for case in cases if case.get('expected_ownership') == 'native']
    delegated = [
        case for case in cases if case.get('expected_ownership') == 'delegated'
    ]
    labels = {
        'argparse_argcomplete': 'argparse + argcomplete',
        'kwconf_python': 'kwconf Python + argcomplete',
        'kwconf_rust': 'kwconf Rust native fast path',
    }
    labels.update(data.get('method_labels', {}))
    method_order = ['argparse_argcomplete', 'kwconf_python', 'kwconf_rust']

    def representative(scenario: str):
        options = [
            case
            for case in native
            if case.get('scenario') == scenario
            and all(method in case.get('methods', {}) for method in method_order)
        ]
        if not options:
            return None
        return min(
            options,
            key=lambda case: (
                abs(int(case.get('schema_size', 0)) - 64),
                -int(case.get('schema_size', 0)),
            ),
        )

    option_case = representative('options')
    choice_case = representative('choices')
    representative_case = option_case or choice_case
    size = int(representative_case['schema_size']) if representative_case else None

    cards = []
    if option_case is not None:
        python_ms = float(option_case['methods']['kwconf_python']['median_ms'])
        rust_ms = float(option_case['methods']['kwconf_rust']['median_ms'])
        saved = python_ms - rust_ms
        saved_pct = 100.0 * saved / python_ms if python_ms else 0.0
        cards.append(
            '<div class="metric"><span>Option-name Tab</span>'
            f'<strong>{saved:.2f} ms saved</strong>'
            f'<small>Rust vs kwconf Python ({saved_pct:.1f}%)</small></div>'
        )
    if choice_case is not None:
        python_ms = float(choice_case['methods']['kwconf_python']['median_ms'])
        rust_ms = float(choice_case['methods']['kwconf_rust']['median_ms'])
        saved = python_ms - rust_ms
        saved_pct = 100.0 * saved / python_ms if python_ms else 0.0
        cards.append(
            '<div class="metric"><span>Choice-value Tab</span>'
            f'<strong>{saved:.2f} ms saved</strong>'
            f'<small>Rust vs kwconf Python ({saved_pct:.1f}%)</small></div>'
        )

    rust_native_methods = [
        case.get('methods', {}).get('kwconf_rust')
        for case in native
        if 'kwconf_rust' in case.get('methods', {})
    ]
    rust_delegated_methods = [
        case.get('methods', {}).get('kwconf_rust')
        for case in delegated
        if 'kwconf_rust' in case.get('methods', {})
    ]
    rust_native_parity = bool(rust_native_methods) and all(
        bool(method.get('exact_output_parity')) for method in rust_native_methods
    )
    delegated_parity = bool(rust_delegated_methods) and all(
        bool(method.get('exact_output_parity')) for method in rust_delegated_methods
    )
    cards.append(
        '<div class="metric"><span>Exact native output parity</span>'
        f'<strong>{str(rust_native_parity).lower()}</strong>'
        '<small>same argcomplete wire output</small></div>'
    )
    cards.append(
        '<div class="metric"><span>Delegated protocol cases</span>'
        f'<strong>{len(delegated)}</strong>'
        f'<small>exact parity: {str(delegated_parity).lower()}</small></div>'
    )

    representative_rows = []
    for method in method_order:
        option = option_case and option_case['methods'].get(method)
        choice = choice_case and choice_case['methods'].get(method)
        if option is None and choice is None:
            continue
        label = labels.get(method, method.replace('_', ' '))
        option_text = f'{float(option["median_ms"]):.2f} ms' if option else '—'
        choice_text = f'{float(choice["median_ms"]):.2f} ms' if choice else '—'
        representative_rows.append(
            '<tr>'
            f'<td>{html.escape(label)}</td>'
            f'<td>{option_text}</td>'
            f'<td>{choice_text}</td>'
            '</tr>'
        )

    scaling_blocks = []
    for scenario, title in [
        ('options', 'Option-name completion'),
        ('choices', 'Choice-value completion'),
    ]:
        scenario_cases = sorted(
            [
                case
                for case in native
                if case.get('scenario') == scenario
                and all(method in case.get('methods', {}) for method in method_order)
            ],
            key=lambda case: int(case['schema_size']),
        )
        rows = []
        for case in scenario_cases:
            methods = case['methods']
            raw_ms = float(methods['argparse_argcomplete']['median_ms'])
            python_ms = float(methods['kwconf_python']['median_ms'])
            rust_ms = float(methods['kwconf_rust']['median_ms'])
            rust_vs_python = rust_ms / python_ms if python_ms else float('nan')
            rows.append(
                '<tr>'
                f'<td>{int(case["schema_size"])}</td>'
                f'<td>{raw_ms:.2f} ms</td>'
                f'<td>{python_ms:.2f} ms</td>'
                f'<td><strong>{rust_ms:.2f} ms</strong></td>'
                f'<td class="{_ratio_class(rust_vs_python)}">'
                f'{_ratio(rust_vs_python)}</td>'
                '</tr>'
            )
        if rows:
            scaling_blocks.append(
                f'<div class="subcard"><h3>{title}</h3>'
                '<table><thead><tr><th>Fields</th>'
                '<th>argparse + argcomplete</th>'
                '<th>kwconf Python + argcomplete</th><th>kwconf Rust</th>'
                '<th>Rust / Python</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>'
            )

    representative_block = ''
    if representative_rows and size is not None:
        representative_block = (
            f'<h3>Representative {size}-field CLI</h3>'
            '<table><thead><tr><th>Implementation</th><th>Option name</th>'
            '<th>Choice value</th></tr></thead>'
            f'<tbody>{"".join(representative_rows)}</tbody></table>'
        )

    return f'''<section id="completion">
<h2>Cold Tab-completion latency</h2>
<p>These are fresh-process shell completion requests using argcomplete's real environment protocol: the time from launching the CLI completion process until candidates are written back to the shell. The raw baseline is stdlib argparse + argcomplete. The kwconf Python backend builds the canonical argparse parser and uses argcomplete; the Rust backend answers safe static requests through its native completion index without importing argparse/argcomplete, while dynamic and descriptive protocols still delegate.</p>
<div class="metric-grid">{''.join(cards)}</div>
{representative_block}
{''.join(scaling_blocks)}
<p class="note">All timing rows are end-to-end cold completion latency, not warmed candidate-generation loops. Exact output parity is checked independently against argparse + argcomplete.</p>
</section>'''


def _render_modal_help(evidence: Path) -> str:
    modal = _read_json(evidence / 'modal' / 'summary.json', {})
    help_data = _read_json(evidence / 'help' / 'summary.json', {})
    table_rows = []
    modal_cases = modal.get('cases', [])
    for case in modal_cases:
        method = case['methods'].get('kwconf_rust')
        if method:
            ratio = float(method['ratio'])
            table_rows.append(
                f'<tr><td>{case["commands"]}</td>'
                f'<td>{method["median_ms"]:.2f} ms</td>'
                f'<td class="{_ratio_class(ratio)}">{_ratio(ratio)}</td></tr>'
            )
    if modal_cases:
        modal_body = (
            '<table><thead><tr><th>Commands</th><th>Rust median</th>'
            '<th>vs argparse</th></tr></thead>'
            f'<tbody>{"".join(table_rows)}</tbody></table>'
        )
    else:
        modal_message = _missing_message(
            evidence,
            'modal-benchmark',
            'No ModalCLI benchmark results were found.',
        )
        modal_body = f'<p>{modal_message}</p>'

    help_cases = help_data.get('cases', [])
    if help_cases:
        help_parity = all(bool(case.get('exact_output_parity')) for case in help_cases)
        help_body = (
            '<div class="metric"><span>Help/color cases</span>'
            f'<strong>{len(help_cases)}</strong>'
            '<small>stdlib, Rich, forced color, NO_COLOR</small></div>'
            '<div class="metric"><span>Exact output parity</span>'
            f'<strong>{str(help_parity).lower()}</strong>'
            '<small>canonical formatter output</small></div>'
        )
    else:
        help_message = _missing_message(
            evidence,
            'help-color-benchmark',
            'No help/color benchmark results were found.',
        )
        help_body = f'<p>{help_message}</p>'

    return f'''<section id="surface"><h2>Modal routing and help/color</h2>
<div class="two-col"><div><h3>ModalCLI cold routing</h3>{modal_body}</div>
<div><h3>Presentation parity</h3>{help_body}</div></div></section>'''


def _render_ownership(evidence: Path) -> str:
    matrix = _read_json(evidence / 'feature_matrix.json', {})
    rows = matrix.get('rows', [])
    counts: dict[str, int] = {}
    for row in rows:
        ownership = row.get('ownership', 'unknown')
        counts[ownership] = counts.get(ownership, 0) + 1
    items = ''.join(
        f'<li><strong>{html.escape(key)}</strong>: {value}</li>'
        for key, value in sorted(counts.items())
    )
    return f'''<section id="ownership"><h2>Feature ownership</h2><p>The accelerator only claims semantics covered by its contract; complex Python extension points deliberately delegate.</p><ul class="ownership">{items}</ul></section>'''


def render(evidence: Path) -> str:
    campaign = _read_json(evidence / 'campaign.json', {})
    environment = _read_json(evidence / 'environment.json', {})
    profile = campaign.get('profile', 'unknown')
    python = environment.get('python', 'unknown').split()[0]
    css = '''
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--ink:#1d2430;--muted:#657080;--line:#d8dde5;--accent:#5a6bff;--good:#087a45;--warn:#946200;--bad:#b42318}*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}main{max-width:1180px;margin:auto;padding:40px 24px 80px}header{margin-bottom:28px}h1{font-size:42px;line-height:1.05;margin:0 0 8px}h2{margin-top:0;font-size:27px}h3{font-size:17px}p{color:var(--muted)}section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px;margin:18px 0;box-shadow:0 2px 10px #00000008}.hero{border-width:2px}.meta{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted)}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric{border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-direction:column}.metric strong{font-size:25px}.metric small,.metric span{color:var(--muted)}.metric code{font-size:.8em}.note{font-size:13px}.win{color:var(--good);font-weight:700}.near{color:var(--warn);font-weight:700}.loss{color:var(--bad);font-weight:700}.code-grid,.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.code-grid section{padding:0;border:0;box-shadow:none;margin:0}.code-grid pre{background:#111827;color:#e5e7eb;padding:16px;border-radius:10px;overflow:auto;font-size:12px;line-height:1.4;max-height:620px}.chart{margin:18px 0}.bar-row{display:grid;grid-template-columns:95px 1fr 90px;align-items:center;gap:10px;margin:7px 0}.bar-track{height:18px;background:#dfe4ec;border-radius:999px;overflow:hidden}.bar-fill{height:100%;background:var(--accent);border-radius:999px}.bar-value{text-align:right;font-variant-numeric:tabular-nums}.subcard{margin:16px 0}details{margin-top:16px}summary{cursor:pointer;font-weight:700;color:var(--ink)}.ownership{columns:2;list-style:none;padding:0}.ownership li{padding:5px 0}@media(max-width:780px){.code-grid,.two-col{grid-template-columns:1fr}.ownership{columns:1}h1{font-size:34px}}@media(prefers-color-scheme:dark){:root{--bg:#10141b;--card:#171d27;--ink:#e7ebf1;--muted:#a3adba;--line:#303947;--accent:#8c98ff}.bar-track{background:#2b3442}}
'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>kwconf cold-start benchmark report</title><style>{css}</style></head><body><main>
<header><h1>kwconf cold-start performance</h1><p>Fresh-process latency first: normal CLI invocation and shell Tab completion for argparse, kwconf Python, and kwconf Rust. Warm-loop throughput is diagnostic rather than headline evidence.</p><div class="meta"><span>profile: <strong>{html.escape(str(profile))}</strong></span><span>Python: <strong>{html.escape(str(python))}</strong></span></div></header>
{_render_cold_breakdown(evidence)}
{_render_backend_phases(evidence)}
{_render_no_site(evidence)}
{_render_startup(evidence)}
{_render_realistic(evidence)}
{_render_completion(evidence)}
{_render_components(evidence)}
{_render_modal_help(evidence)}
{_render_ownership(evidence)}
<footer><p>Generated by <code>dev/benchmarks/benchmark_report.py</code>. Headline timings are fresh-process measurements; in-process microbenchmarks are attribution diagnostics.</p></footer>
</main></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence_dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    evidence = args.evidence_dir.resolve()
    output = args.output or evidence / 'benchmark_report.html'
    output.write_text(render(evidence))
    print(output)


if __name__ == '__main__':
    main()
