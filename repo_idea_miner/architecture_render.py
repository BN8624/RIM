# Architecture Atlas 정적 HTML renderer — 외부 의존 0, 모바일 우선, 다크모드, 결정론적 출력.
from __future__ import annotations

import html
import json

_CSS = """
:root { color-scheme: light dark;
  --bg:#f4f5f7; --card:#fff; --fg:#1c1c1e; --muted:#6b7280; --line:#d1d5db;
  --accent:#2563eb; --ok:#15803d; --warn:#b45309; --bad:#b91c1c; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#000; --card:#1c1c1e; --fg:#f2f2f7; --muted:#98989f; --line:#3a3a3c; } }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  font-size:16px; line-height:1.55; background:var(--bg); color:var(--fg); -webkit-text-size-adjust:100%; }
.wrap { max-width:860px; margin:0 auto; padding:14px 12px 80px; }
h1 { font-size:1.2rem; margin:6px 0 4px; }
.sub { color:var(--muted); font-size:.8rem; word-break:break-all; margin:0 0 12px; }
.tabs { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; }
.tabs button { font-size:.86rem; padding:9px 12px; border-radius:999px; border:1px solid var(--line);
  background:var(--card); color:var(--fg); min-height:40px; cursor:pointer; }
.tabs button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px; margin-bottom:12px; }
.card h2 { font-size:.95rem; margin:0 0 8px; }
.muted { color:var(--muted); }
.pill { display:inline-block; font-size:.76rem; font-weight:700; padding:3px 10px; border-radius:999px;
  border:1px solid var(--line); margin:2px 4px 2px 0; }
.pill.ok { background:var(--ok); border-color:var(--ok); color:#fff; }
.pill.warn { background:var(--warn); border-color:var(--warn); color:#fff; }
.pill.bad { background:var(--bad); border-color:var(--bad); color:#fff; }
.flow { display:flex; flex-direction:column; gap:6px; }
.flow .node { border:1px solid var(--line); border-radius:12px; padding:10px 12px; background:var(--card); }
.flow .node b { display:block; }
.flow .node .mods { font-size:.8rem; color:var(--muted); word-break:break-all; }
.flow .arrow { text-align:center; color:var(--muted); font-size:.85rem; }
input[type=search], select { font-size:1rem; padding:10px 12px; border-radius:12px;
  border:1px solid var(--line); background:var(--card); color:var(--fg); min-height:44px; width:100%; }
.controls { display:grid; grid-template-columns:1fr; gap:8px; margin-bottom:10px; }
@media (min-width:560px) { .controls { grid-template-columns:2fr 1fr; } }
.modrow { border:1px solid var(--line); border-radius:12px; padding:10px 12px; margin-bottom:8px;
  background:var(--card); cursor:pointer; }
.modrow b { word-break:break-all; }
.modrow .meta { font-size:.78rem; color:var(--muted); }
.drawer { position:fixed; inset:auto 0 0 0; max-height:78vh; overflow:auto; background:var(--card);
  border-top:2px solid var(--accent); border-radius:16px 16px 0 0; padding:16px 14px 40px;
  box-shadow:0 -6px 24px rgba(0,0,0,.25); display:none; z-index:9; }
.drawer.open { display:block; }
.drawer h3 { margin:0 0 6px; word-break:break-all; }
.drawer .close { position:absolute; top:10px; right:12px; font-size:1rem; border:1px solid var(--line);
  background:var(--card); color:var(--fg); border-radius:10px; padding:6px 12px; cursor:pointer; }
.kv { font-family:ui-monospace,Menlo,monospace; font-size:.8rem; word-break:break-all; }
ul.plain { margin:4px 0; padding-left:18px; font-size:.86rem; }
details > summary { cursor:pointer; font-weight:700; font-size:.9rem; margin:6px 0; }
table { border-collapse:collapse; width:100%; font-size:.82rem; }
th, td { text-align:left; padding:5px 6px; border-bottom:1px solid var(--line); word-break:break-all; }
.section { display:none; }
.section.on { display:block; }
.stat { display:inline-block; min-width:110px; margin:4px 10px 4px 0; }
.stat .n { font-size:1.2rem; font-weight:700; display:block; }
.stat .k { font-size:.75rem; color:var(--muted); }
"""

_JS = """
const A = window.ATLAS;
function el(t, attrs, ...kids) {
  const e = document.createElement(t);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'text') e.textContent = v; else if (k.startsWith('on')) e[k] = v; else e.setAttribute(k, v);
  }
  for (const kid of kids) if (kid) e.append(kid);
  return e;
}
function show(tab) {
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('on', s.id === 'sec-' + tab));
  document.querySelectorAll('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  closeDrawer();
}
function openDrawer(mod) {
  const m = A.modules.find(x => x.module === mod);
  if (!m) return;
  const d = document.getElementById('drawer');
  d.innerHTML = '';
  d.append(el('button', {class: 'close', text: '닫기', onclick: closeDrawer}));
  d.append(el('h3', {text: m.module}));
  const comp = A.components[m.component] || {label: m.component, canon_id: '-'};
  d.append(el('p', {class: 'meta muted',
    text: comp.label + ' · ' + comp.canon_id + ' · ' + m.loc + ' LOC · ' + m.path}));
  const sec = (title, items, fmt) => {
    const det = el('details', {}, el('summary', {text: title + ' (' + items.length + ')'}));
    const ul = el('ul', {class: 'plain'});
    items.forEach(x => ul.append(el('li', {class: 'kv', text: fmt ? fmt(x) : x})));
    if (!items.length) ul.append(el('li', {class: 'muted', text: '없음'}));
    det.append(ul); d.append(det);
  };
  sec('Public API', m.public_symbols);
  sec('Imports', m.imports, i => i.from.replace('repo_idea_miner.', '') + (i.names.length ? ' ← ' + i.names.join(', ') : ''));
  sec('Imported by (변경 영향)', m.imported_by, x => x.replace('repo_idea_miner.', ''));
  sec('Artifacts', m.artifact_refs);
  sec('Tests', m.tests);
  const cli = A.cli.filter(c => c.handler && c.handler.includes(m.module.split('.').pop()));
  d.classList.add('open');
}
function closeDrawer() { document.getElementById('drawer').classList.remove('open'); }
function renderModules() {
  const q = document.getElementById('q').value.toLowerCase();
  const comp = document.getElementById('fcomp').value;
  const box = document.getElementById('modlist');
  box.innerHTML = '';
  A.modules
    .filter(m => (!comp || m.component === comp) &&
                 (!q || m.module.toLowerCase().includes(q) ||
                  m.public_symbols.some(s => s.toLowerCase().includes(q))))
    .forEach(m => {
      box.append(el('div', {class: 'modrow', onclick: () => openDrawer(m.module)},
        el('b', {text: m.module.replace('repo_idea_miner.', '')}),
        el('div', {class: 'meta',
          text: (A.components[m.component] || {label: m.component}).label + ' · ' + m.loc +
                ' LOC · imports ' + m.imports.length + ' · imported by ' + m.imported_by.length +
                ' · tests ' + m.tests.length})));
    });
  if (!box.children.length) box.append(el('p', {class: 'muted', text: '일치하는 모듈 없음'}));
}
window.addEventListener('DOMContentLoaded', () => {
  const fcomp = document.getElementById('fcomp');
  Object.entries(A.components).forEach(([cid, c]) =>
    fcomp.append(el('option', {value: cid, text: c.label})));
  document.getElementById('q').addEventListener('input', renderModules);
  fcomp.addEventListener('change', renderModules);
  renderModules();
  show('overview');
});
"""


def _e(v) -> str:
    return html.escape(str(v))


def _pill(text: str, cls: str = "") -> str:
    return f'<span class="pill {cls}">{_e(text)}</span>'


def _overview(atlas: dict) -> str:
    comps = "".join(
        f'<div class="node"><b>{_e(c["label"])}</b>'
        f'<span class="mods">{_e(c["canon_id"])} · {len(c["modules"])} modules · {_e(c["status"])}</span></div>'
        for c in atlas["components"].values()
    )
    pipe = '<div class="arrow">↓</div>'.join(
        f'<div class="node"><b>{_e(p["node"])}</b>'
        f'<span class="mods">{_e(", ".join(p["modules"]))}</span></div>'
        for p in atlas["pipeline"]
    )
    return f"""
<div class="card"><h2>A. System Overview — Components</h2><div class="flow">{comps}</div></div>
<div class="card"><h2>B. Canonical Pipeline</h2><div class="flow">{pipe}</div></div>"""


def _artifacts(atlas: dict) -> str:
    rows = "".join(
        f'<tr><td>{_e(mod.replace("repo_idea_miner.", ""))}</td>'
        f'<td>{_e(", ".join(refs[:8]))}{" …" if len(refs) > 8 else ""}</td></tr>'
        for mod, refs in sorted(atlas["artifacts"].items())
    )
    return f"""
<div class="card"><h2>D. Artifact Flow (모듈별 참조 산출물)</h2>
<p class="muted">challenge → contract → workspace → gate result → replay/golden → evidence → stage/gap/lane → child run → loop summary</p>
<div style="overflow-x:auto"><table><tr><th>module</th><th>artifacts</th></tr>{rows}</table></div></div>"""


def _gates_tests(atlas: dict) -> str:
    checks = "".join(_pill(c) for c in atlas["validators"]["checks"])
    kinds = "".join(_pill(k) for k in atlas["validators"]["run_kinds"])
    rows = "".join(
        f'<tr><td>{_e(t)}</td><td>{_e(", ".join(srcs))}</td></tr>'
        for t, srcs in sorted(atlas["tests"].items())
    )
    return f"""
<div class="card"><h2>E. Gate &amp; Validator Map</h2>
<p class="muted">run kinds</p><div>{kinds}</div>
<p class="muted">validator checks (factory_validate)</p><div>{checks}</div></div>
<div class="card"><h2>Test → Source Mapping</h2>
<div style="overflow-x:auto"><table><tr><th>test module</th><th>covers</th></tr>{rows}</table></div></div>"""


def _cli(atlas: dict) -> str:
    rows = "".join(
        f'<tr><td>{_e(c["command"])}</td><td class="kv">{_e(c["handler"])}</td>'
        f'<td>{_e(" ".join(c["options"]))}</td></tr>'
        for c in atlas["cli"]
    )
    return f"""
<div class="card"><h2>CLI Commands ({len(atlas["cli"])})</h2>
<div style="overflow-x:auto"><table><tr><th>command</th><th>handler</th><th>options</th></tr>{rows}</table></div></div>"""


def _health(atlas: dict) -> str:
    h = atlas["health"]

    def stat(k, n, bad_if_positive=False):
        cls = "bad" if bad_if_positive and n else "ok"
        return f'<span class="stat"><span class="n">{n}</span><span class="k">{_e(k)}</span></span>'

    lists = ""
    for title, items in (
        ("import cycles", [" ↔ ".join(c) for c in h["import_cycles"]]),
        ("private cross-imports (전체)", [f'{p["module"]} ← {p["from"]}:{",".join(p["names"])}'
                                          for p in h["private_cross_imports"]]),
        ("allowlist 밖 private import", [f'{p["module"]} ← {p["from"]}'
                                         for p in h["private_cross_imports_outside_allowlist"]]),
        ("orphan modules", h["orphan_modules"]),
        ("unknown component", h["unknown_component"]),
        ("500 LOC 초과", h["over_500_loc"]),
        ("800 LOC 초과", h["over_800_loc"]),
    ):
        body = "".join(f'<li class="kv">{_e(x)}</li>' for x in items) or '<li class="muted">없음</li>'
        lists += f'<details><summary>{_e(title)} ({len(items)})</summary><ul class="plain">{body}</ul></details>'
    return f"""
<div class="card"><h2>G. Architecture Health</h2>
{stat("modules", h["module_count"])}{stat("tests", h["test_count"])}
{stat("cycles", len(h["import_cycles"]), True)}{stat("private", len(h["private_cross_imports"]))}
{stat("orphans", len(h["orphan_modules"]), True)}{stat("unknown", len(h["unknown_component"]), True)}
{lists}
<p class="muted">private cross-import 3건은 Miner core 무변경 보존(§5.1)의 의도적 예외 — CANON-11.</p></div>"""


def _docs(atlas: dict) -> str:
    rows = "".join(
        f'<tr><td>{_e(name)}</td><td>{_e(role)}</td></tr>'
        for name, role in atlas["documents"].items()
    )
    return f"""
<div class="card"><h2>H. Document Governance</h2>
<div style="overflow-x:auto"><table><tr><th>document</th><th>role</th></tr>{rows}</table></div>
<p class="muted">현행 아키텍처 정본은 PROJECT_CANON.md 하나다. 이 페이지는 자동 생성물이며 직접 수정하지 않는다.</p></div>"""


def render_index(atlas: dict) -> str:
    """단일 self-contained HTML — 같은 atlas dict면 byte-identical."""
    data = json.dumps(atlas, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")
    tabs = [("overview", "개요"), ("modules", "모듈"), ("cli", "CLI"),
            ("artifacts", "산출물"), ("gates", "게이트/테스트"), ("health", "상태"), ("docs", "문서")]
    tab_btns = "".join(
        f'<button data-tab="{k}" onclick="show(\'{k}\')">{_e(label)}</button>' for k, label in tabs
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>RIM Architecture Atlas</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<h1>RIM Architecture Atlas</h1>
<p class="sub">commit {_e(atlas["commit"])} · fingerprint {_e(atlas["fingerprint"][:16])}…</p>
<div class="tabs">{tab_btns}</div>
<div id="sec-overview" class="section">{_overview(atlas)}</div>
<div id="sec-modules" class="section">
  <div class="controls">
    <input type="search" id="q" placeholder="모듈/심볼 검색">
    <select id="fcomp"><option value="">component 전체</option></select>
  </div>
  <div id="modlist"></div>
</div>
<div id="sec-cli" class="section">{_cli(atlas)}</div>
<div id="sec-artifacts" class="section">{_artifacts(atlas)}</div>
<div id="sec-gates" class="section">{_gates_tests(atlas)}</div>
<div id="sec-health" class="section">{_health(atlas)}</div>
<div id="sec-docs" class="section">{_docs(atlas)}</div>
</div>
<div id="drawer" class="drawer"></div>
<script>window.ATLAS = {data};</script>
<script>{_JS}</script>
</body>
</html>
"""
