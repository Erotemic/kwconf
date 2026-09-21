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


def _extract_snippet(text: str, name: str) -> str:
    start = f'# REPORT_SNIPPET_{name}_START'
    end = f'# REPORT_SNIPPET_{name}_END'
    return text.split(start, 1)[1].split(end, 1)[0].strip('\n')


def _ms(ns: float) -> str:
    return f'{ns / 1e6:.2f} ms'


def _us(seconds: float) -> str:
    return f'{seconds * 1e6:.1f} µs'


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


def _render_realistic(evidence: Path) -> str:
    data = _read_json(evidence / 'realistic' / 'summary.json')
    snapshot_example = evidence / 'source_snapshot' / 'examples' / EXAMPLE.name
    source_path = snapshot_example if snapshot_example.exists() else EXAMPLE
    source = source_path.read_text() if source_path.exists() else ''
    snippets = ''
    if source:
        a = html.escape(_extract_snippet(source, 'ARGPARSE'))
        k = html.escape(_extract_snippet(source, 'KWCONF'))
        snippets = f'''<div class="code-grid">
<section><h3>argparse</h3><pre><code>{a}</code></pre></section>
<section><h3>kwconf</h3><pre><code>{k}</code></pre></section>
</div>'''
    if not data:
        return f'''<section id="realistic"><h2>Realistic CLI comparison</h2>
<p>The report generator supports the normal-sized CLI benchmark in
<code>examples/09_argparse_comparison.py</code>. This evidence bundle predates
that benchmark, so no measured realistic-CLI row is available yet.</p>{snippets}</section>'''

    cold_a = float(data['cold']['argparse']['median_ns'])
    cold_k = float(data['cold']['kwconf']['median_ns'])
    warm_a = float(data['warm_parse']['argparse']['mean_ns'])
    warm_k = float(data['warm_parse']['kwconf']['mean_ns'])
    cold_r = float(data['ratios']['cold_kwconf_vs_argparse'])
    warm_r = float(data['ratios']['warm_kwconf_vs_argparse'])
    cold_max = max(cold_a, cold_k) / 1e6
    warm_max = max(warm_a, warm_k) / 1e3
    return f'''<section id="realistic"><h2>Realistic CLI comparison</h2>
<p>A 24-option production-style CLI implemented both ways. Output parity:
<strong>{str(bool(data.get('output_parity'))).lower()}</strong>.</p>
<div class="metric-grid">
<div class="metric"><span>Cold process</span><strong class="{_ratio_class(cold_r)}">{_ratio(cold_r)}</strong><small>kwconf / argparse</small></div>
<div class="metric"><span>Warm parse</span><strong class="{_ratio_class(warm_r)}">{_ratio(warm_r)}</strong><small>kwconf / argparse</small></div>
</div>
<div class="chart"><h3>Cold process median</h3>
{_bar('argparse', cold_a / 1e6, cold_max, ' ms')}
{_bar('kwconf', cold_k / 1e6, cold_max, ' ms')}</div>
<div class="chart"><h3>Warm parse per call</h3>
{_bar('argparse', warm_a / 1e3, warm_max, ' µs')}
{_bar('kwconf', warm_k / 1e3, warm_max, ' µs')}</div>
{snippets}</section>'''


def _render_startup(evidence: Path) -> str:
    rows = _read_csv(evidence / 'startup' / 'summary.csv')
    if not rows:
        return '<section><h2>Cold startup</h2><p>No startup results.</p></section>'
    by_size: dict[int, dict[str, dict[str, str]]] = {}
    for row in rows:
        by_size.setdefault(int(row['schema_size']), {})[row['method']] = row
    body = []
    for size in sorted(by_size):
        methods = by_size[size]
        a = float(methods['argparse']['median_ns'])
        auto = methods.get('kwconf_auto')
        rust = methods.get('kwconf_rust')
        body.append('<tr>')
        body.append(f'<td>{size}</td><td>{_ms(a)}</td>')
        for row in (auto, rust):
            if row is None:
                body.append('<td>—</td><td>—</td>')
            else:
                med = float(row['median_ns'])
                ratio = med / a
                body.append(f'<td>{_ms(med)}</td><td class="{_ratio_class(ratio)}">{_ratio(ratio)}</td>')
        body.append('</tr>')
    return f'''<section id="startup"><h2>Cold process startup</h2>
<p>Fresh interpreter + imports + schema declaration + one parse. Ratios below 1 are faster.</p>
<table><thead><tr><th>Fields</th><th>argparse</th><th>kwconf auto</th><th>auto ratio</th><th>kwconf rust</th><th>rust ratio</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></section>'''


def _render_components(evidence: Path) -> str:
    rows = _read_csv(evidence / 'components' / 'rust_cli_runtime.csv')
    if not rows:
        return '<section><h2>In-process runtime</h2><p>No component results.</p></section>'
    wanted = ['hot_parse', 'warm_end_to_end', 'one_shot_end_to_end', 'schema_build']
    blocks = []
    for family in wanted:
        fam = [r for r in rows if r['family'] == family]
        if not fam:
            continue
        # Keep the report readable: show a normal small/medium/large spread.
        sizes = sorted({int(r['schema_size']) for r in fam})
        selected = [x for x in (16, 64, 256) if x in sizes] or sizes[:3]
        trs = []
        for size in selected:
            candidates = [r for r in fam if int(r['schema_size']) == size]
            base = next((r for r in candidates if r['method'] == 'argparse'), None)
            if base is None:
                continue
            target = next(
                (
                    r
                    for name in ('kwconf_rust', 'rust_bridge', 'rust_uncached', 'rust_pyo3_parse')
                    for r in candidates
                    if r['method'] == name
                ),
                None,
            )
            if target is None:
                continue
            base_s = float(base['mean_s'])
            target_s = float(target['mean_s'])
            ratio = target_s / base_s
            trs.append(
                f'<tr><td>{size}</td><td>{html.escape(target["method"])}</td>'
                f'<td>{_us(base_s)}</td><td>{_us(target_s)}</td>'
                f'<td class="{_ratio_class(ratio)}">{_ratio(ratio)}</td></tr>'
            )
        if trs:
            title = family.replace('_', ' ').title()
            blocks.append(
                f'<div class="subcard"><h3>{title}</h3><table><thead><tr><th>Fields</th><th>Rust path</th><th>argparse</th><th>kwconf/Rust</th><th>ratio</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>'
            )
    return '<section id="components"><h2>In-process runtime</h2><p>These isolate work after interpreter startup, where the Rust acceleration is most visible.</p>' + ''.join(blocks) + '</section>'


def _render_completion(evidence: Path) -> str:
    data = _read_json(evidence / 'completion' / 'summary.json', {})
    cases = data.get('cases', [])
    native = [c for c in cases if c.get('expected_ownership') == 'native']
    delegated = [c for c in cases if c.get('expected_ownership') == 'delegated']
    ratios = []
    parity = True
    for case in native:
        method = case.get('methods', {}).get('kwconf_rust', {})
        if 'ratio' in method:
            ratios.append(float(method['ratio']))
        parity = parity and bool(method.get('exact_output_parity', False))
    med = statistics.median(ratios) if ratios else float('nan')
    return f'''<section id="completion"><h2>Completion</h2>
<div class="metric-grid"><div class="metric"><span>Native cases</span><strong>{len(native)}</strong><small>static Rust-owned paths</small></div>
<div class="metric"><span>Delegated cases</span><strong>{len(delegated)}</strong><small>canonical argcomplete paths</small></div>
<div class="metric"><span>Native median ratio</span><strong class="{_ratio_class(med) if ratios else 'near'}">{_ratio(med) if ratios else '—'}</strong><small>kwconf rust / argparse+argcomplete</small></div>
<div class="metric"><span>Exact native output parity</span><strong>{str(parity).lower()}</strong><small>wire output, not just candidate sets</small></div></div></section>'''


def _render_modal_help(evidence: Path) -> str:
    modal = _read_json(evidence / 'modal' / 'summary.json', {})
    help_data = _read_json(evidence / 'help' / 'summary.json', {})
    trs = []
    for case in modal.get('cases', []):
        m = case['methods'].get('kwconf_rust')
        if m:
            ratio = float(m['ratio'])
            trs.append(f'<tr><td>{case["commands"]}</td><td>{m["median_ms"]:.2f} ms</td><td class="{_ratio_class(ratio)}">{_ratio(ratio)}</td></tr>')
    help_cases = help_data.get('cases', [])
    help_parity = all(bool(c.get('exact_output_parity')) for c in help_cases) if help_cases else False
    return f'''<section id="surface"><h2>Modal routing and help/color</h2>
<div class="two-col"><div><h3>ModalCLI cold routing</h3><table><thead><tr><th>Commands</th><th>Rust median</th><th>vs argparse</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div>
<div><h3>Presentation parity</h3><div class="metric"><span>Help/color cases</span><strong>{len(help_cases)}</strong><small>stdlib, Rich, forced color, NO_COLOR</small></div><div class="metric"><span>Exact output parity</span><strong>{str(help_parity).lower()}</strong><small>canonical formatter output</small></div></div></div></section>'''


def _render_ownership(evidence: Path) -> str:
    matrix = _read_json(evidence / 'feature_matrix.json', {})
    rows = matrix.get('rows', [])
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get('ownership', 'unknown')] = counts.get(row.get('ownership', 'unknown'), 0) + 1
    items = ''.join(f'<li><strong>{html.escape(k)}</strong>: {v}</li>' for k, v in sorted(counts.items()))
    return f'''<section id="ownership"><h2>Feature ownership</h2><p>The accelerator only claims semantics covered by its contract; complex Python extension points deliberately delegate.</p><ul class="ownership">{items}</ul></section>'''


def render(evidence: Path) -> str:
    campaign = _read_json(evidence / 'campaign.json', {})
    environment = _read_json(evidence / 'environment.json', {})
    profile = campaign.get('profile', 'unknown')
    python = environment.get('python', 'unknown').split()[0]
    css = '''
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--ink:#1d2430;--muted:#657080;--line:#d8dde5;--accent:#5a6bff;--good:#087a45;--warn:#946200;--bad:#b42318}*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}main{max-width:1180px;margin:auto;padding:40px 24px 80px}header{margin-bottom:28px}h1{font-size:42px;line-height:1.05;margin:0 0 8px}h2{margin-top:0;font-size:27px}h3{font-size:17px}p{color:var(--muted)}section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px;margin:18px 0;box-shadow:0 2px 10px #00000008}.meta{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted)}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:8px 10px;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}.metric-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.metric{border:1px solid var(--line);border-radius:10px;padding:14px;display:flex;flex-direction:column}.metric strong{font-size:25px}.metric small,.metric span{color:var(--muted)}.win{color:var(--good);font-weight:700}.near{color:var(--warn);font-weight:700}.loss{color:var(--bad);font-weight:700}.code-grid,.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}.code-grid section{padding:0;border:0;box-shadow:none;margin:0}.code-grid pre{background:#111827;color:#e5e7eb;padding:16px;border-radius:10px;overflow:auto;font-size:12px;line-height:1.4;max-height:620px}.chart{margin:18px 0}.bar-row{display:grid;grid-template-columns:95px 1fr 90px;align-items:center;gap:10px;margin:7px 0}.bar-track{height:18px;background:#dfe4ec;border-radius:999px;overflow:hidden}.bar-fill{height:100%;background:var(--accent);border-radius:999px}.bar-value{text-align:right;font-variant-numeric:tabular-nums}.subcard{margin:16px 0}.ownership{columns:2;list-style:none;padding:0}.ownership li{padding:5px 0}@media(max-width:780px){.code-grid,.two-col{grid-template-columns:1fr}.ownership{columns:1}h1{font-size:34px}}@media(prefers-color-scheme:dark){:root{--bg:#10141b;--card:#171d27;--ink:#e7ebf1;--muted:#a3adba;--line:#303947;--accent:#8c98ff}.bar-track{background:#2b3442}}
'''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>kwconf benchmark report</title><style>{css}</style></head><body><main>
<header><h1>kwconf vs argparse</h1><p>Holistic benchmark report: code size, cold startup, in-process parsing, completion, ModalCLI, and presentation parity.</p><div class="meta"><span>profile: <strong>{html.escape(str(profile))}</strong></span><span>Python: <strong>{html.escape(str(python))}</strong></span></div></header>
{_render_realistic(evidence)}
{_render_startup(evidence)}
{_render_components(evidence)}
{_render_completion(evidence)}
{_render_modal_help(evidence)}
{_render_ownership(evidence)}
<footer><p>Generated by <code>dev/benchmarks/benchmark_report.py</code>. Ratios are kwconf/Rust divided by the argparse baseline; lower is faster.</p></footer>
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
