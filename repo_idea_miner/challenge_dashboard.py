# Challenge/Product 검수 대시보드의 HTML 렌더링과 HTTP 서버 (read model은 challenge_dashboard_data).
from __future__ import annotations

import html
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from repo_idea_miner.challenge_dashboard_data import (
    DETAIL_FILES,
    PRODUCT_REPORT_TABS,
    PRODUCT_REPORT_TABS_MAP,
    challenge_copy_text,
    challenge_detail_content,
    final_tree,
    get_challenge_brief,
    get_challenge_detail,
    load_draft_execution,
    load_phase2c0,
    load_phase2c1,
    load_phase2c2,
    load_phase2c3,
    load_phase2d0,
    load_phase2d0_details,
    load_phase2d1,
    load_phase2d1_details,
    match_product_filters,
    product_dirs,
    query_challenges,
    read_capped,
    safe_source_path,
    source_files,
    today_summary,
)
from repo_idea_miner.challenge_db import set_owner_review
from repo_idea_miner.challenge_schemas import CHALLENGE_LABELS, OWNER_STATUSES
from repo_idea_miner.factory_db import (
    add_product_review,
    get_product_run,
    latest_review,
    latest_reviews_map,
    list_product_runs,
    log_product_event,
    open_factory_db as open_db,  # challenge 스키마 + factory 스키마 보장 (기존 라우트 동작은 동일)
)
from repo_idea_miner import factory_labels as L
from repo_idea_miner.factory_schemas import (
    PRODUCT_OWNER_DECISIONS,
    PRODUCT_VERDICT_LABELS,
    VERDICT_TO_RECOMMENDED_ACTION,
)
from repo_idea_miner.factory_summary import (
    GATE_KEYS,
    gate_pass_count,
    head_lines,
    load_core_summary,
    load_dashboard_summary,
    load_gate_summary,
    load_product_summary,
    load_qa_summary,
    overall_qa_status,
)
from repo_idea_miner.redaction import redact_text

_STATUS_ACTIONS = [
    ("saved", "저장"),
    ("maybe", "보류"),
    ("dropped", "버림"),
    ("build_next", "다음 구현"),
    ("built", "구현 완료"),
]

# 라벨/상태 enum을 화면용 한글로 (색상 class는 enum 그대로 유지)
_LABEL_KO = {
    "GOOD_CHALLENGE": "좋은 과제",
    "STEAL_ONLY": "훔칠 것만",
    "NOT_MY_TASTE": "취향 아님",
    "TOO_BIG": "너무 큼",
    "UNCLEAR_TO_OWNER": "이해 어려움",
    "TOO_EASY": "너무 쉬움",
    "DROP": "버림",
}

_OSTATUS_KO = {
    "unseen": "안 봄",
    "saved": "저장",
    "maybe": "보류",
    "dropped": "버림",
    "build_next": "다음 구현",
    "built": "구현 완료",
}

_TAB_KO = [
    ("owner_brief", "쉬운 설명"),
    ("screen_story", "화면 흐름"),
    ("challenge_card", "과제 카드"),
    ("implementation_prompt", "구현 지시문"),
    ("validation_report", "검증 결과"),
]

# ---------------------------------------------------------------- Product Factory 화면 상수

# 표시 문구는 factory_labels로 통일한다(내부값 불변). 여기서는 버튼 순서만 정의한다.
# (label은 factory_labels.format_review_label에서 렌더링)
_DECISION_ACTIONS = [
    ("keep", "KEEP"),
    ("drop", "DROP"),
    ("productize", "PRODUCTIZE"),
    ("retry", "RETRY"),
    ("archive", "ARCHIVE"),
]

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 17px; line-height: 1.6; background: #f4f5f7; color: #1c1c1e; -webkit-text-size-adjust: 100%; }
.wrap { max-width: 780px; margin: 0 auto; padding: 18px 16px 72px; }
h1 { font-size: 1.35rem; margin: 4px 0 16px; }
h1 a { color: inherit; text-decoration: none; }
.sec-h { font-size: .95rem; margin: 0 0 10px; color: #6b7280; font-weight: 700; }
.summary, .card, .panel { background: #fff; border-radius: 16px; padding: 16px; margin-bottom: 14px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.sgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px 16px; }
.sitem { display: flex; flex-direction: column; gap: 2px; }
.sitem .k { font-size: .8rem; color: #6b7280; }
.sitem .val { font-weight: 700; font-size: 1.15rem; }
form.filters { display: flex; flex-wrap: wrap; gap: 10px 12px; margin-bottom: 14px; align-items: flex-end; }
form.filters label { display: flex; flex-direction: column; gap: 4px; font-size: .78rem; color: #6b7280; }
form.filters select, form.filters input {
  font-size: 1rem; padding: 10px 12px; border-radius: 12px; border: 1px solid #d1d5db; background: #fff; color: inherit; min-height: 44px; }
form.filters button { font-size: 1rem; padding: 10px 18px; border-radius: 12px; border: 1px solid #2563eb;
  background: #2563eb; color: #fff; min-height: 44px; cursor: pointer; }
.chip-link { align-self: center; font-size: .9rem; padding: 10px 14px; border-radius: 999px;
  border: 1px solid #d1d5db; text-decoration: none; color: inherit; }
.count { color: #6b7280; font-size: .88rem; margin: 0 2px 12px; }
.badge { font-size: .82rem; font-weight: 700; padding: 4px 12px; border-radius: 999px; color: #fff; white-space: nowrap; }
.l-GOOD_CHALLENGE { background: #15803d; } .l-STEAL_ONLY { background: #6d28d9; }
.l-NOT_MY_TASTE { background: #b45309; } .l-TOO_BIG { background: #0e7490; }
.l-UNCLEAR_TO_OWNER { background: #be185d; } .l-TOO_EASY { background: #52525b; }
.l-DROP { background: #1f2937; }
.v-PROMOTE_TO_CODEX { background: #15803d; } .v-KEEP_CANDIDATE { background: #2563eb; }
.v-NEEDS_MORE_GEMMA_LOOP { background: #b45309; } .v-TOO_WEAK { background: #52525b; }
.v-DROP { background: #1f2937; } .v-PENDING { background: #6b7280; }
.ostatus { font-size: .8rem; font-weight: 700; padding: 4px 12px; border-radius: 999px;
  background: #e5e7eb; color: #374151; white-space: nowrap; }
.sb { font-size: .8rem; font-weight: 700; padding: 4px 12px; border-radius: 999px; color: #fff; white-space: nowrap; }
.sb-done { background: #15803d; } .sb-error { background: #b91c1c; }
.sb-running { background: #2563eb; } .sb-pending { background: #6b7280; }
.rb { font-size: .8rem; font-weight: 700; padding: 4px 12px; border-radius: 999px;
  background: #e5e7eb; color: #374151; white-space: nowrap; }
.rb-on { background: #0369a1; color: #fff; }
.nav { display: flex; gap: 10px; margin: 0 0 14px; }
.nav a { flex: 1 1 auto; text-align: center; font-size: .95rem; font-weight: 700; padding: 11px 10px;
  border-radius: 12px; border: 1px solid #d1d5db; text-decoration: none; color: inherit; min-height: 46px;
  display: inline-flex; align-items: center; justify-content: center; }
.nav a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.filters-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; }
.filters-chips a { font-size: .85rem; padding: 8px 12px; border-radius: 999px; border: 1px solid #d1d5db;
  text-decoration: none; color: inherit; min-height: 38px; display: inline-flex; align-items: center; }
.filters-chips a.on { background: #2563eb; color: #fff; border-color: #2563eb; }
.gaterow { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0; }
.gp { font-size: .8rem; font-weight: 700; padding: 4px 10px; border-radius: 8px; }
.gp .lbl { opacity: .7; margin-right: 4px; font-weight: 600; }
.gp-PASS { background: #dcfce7; color: #166534; } .gp-FAIL { background: #fee2e2; color: #991b1b; }
.gp-SKIP { background: #e5e7eb; color: #374151; } .gp-UNKNOWN { background: #fef9c3; color: #854d0e; }
.field { margin: 8px 0; } .field .k { font-size: .78rem; color: #6b7280; display: block; margin-bottom: 2px; }
.kv { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82rem; word-break: break-all; }
.tree { white-space: pre; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem;
  background: #f3f4f6; border-radius: 12px; padding: 12px; overflow-x: auto; line-height: 1.5; }
.smoke-meta { font-size: .85rem; color: #6b7280; margin: 2px 0; }
.issue { margin: 6px 0; } .issue .k { font-size: .78rem; color: #6b7280; }
.evi { margin: 6px 0 0; padding-left: 18px; font-size: .9rem; }
details.raw > summary { cursor: pointer; list-style: none; user-select: none; }
details.raw > summary::-webkit-details-marker { display: none; }
details.raw > summary::before { content: "▸ "; color: #6b7280; }
details.raw[open] > summary::before { content: "▾ "; }
details.raw > summary.sec-h { margin-bottom: 0; }
details.raw[open] > summary.sec-h { margin-bottom: 12px; }
.chead { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 6px; }
.repo { font-weight: 700; font-size: .92rem; word-break: break-all; flex: 1 1 auto; color: #6b7280; }
.repo a { color: #6b7280; text-decoration: none; }
.title { font-weight: 700; font-size: 1.12rem; margin: 6px 0 4px; }
.title a { color: inherit; text-decoration: none; }
.oneline { margin: 4px 0 8px; }
.meta { color: #6b7280; font-size: .85rem; margin: 6px 0 0; }
.muted { color: #6b7280; }
.back { margin: 0 0 12px; } .back a { color: #2563eb; text-decoration: none; font-size: .95rem; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.actions.copy-row { margin-top: 8px; }
.actions button { font-size: .95rem; padding: 11px 16px; border-radius: 12px; border: 1px solid #d1d5db;
  background: #fff; color: inherit; cursor: pointer; min-height: 46px; }
.actions button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.actions button.on { outline: 3px solid #93c5fd; font-weight: 700; }
.actions button.copy { border-style: dashed; color: #2563eb; }
pre { white-space: pre-wrap; word-break: break-word; background: #f3f4f6; border-radius: 12px;
  padding: 14px; font-size: .95rem; line-height: 1.65; overflow-x: auto; }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.tabs a { font-size: .92rem; padding: 9px 14px; border-radius: 999px; border: 1px solid #d1d5db;
  text-decoration: none; color: inherit; min-height: 40px; display: inline-flex; align-items: center; }
.tabs a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
textarea { width: 100%; border-radius: 12px; border: 1px solid #d1d5db; padding: 10px; font: inherit; font-size: 1rem; }
@media (prefers-color-scheme: dark) {
  body { background: #000; color: #f2f2f7; }
  .summary, .card, .panel { background: #1c1c1e; box-shadow: none; border: 1px solid #2c2c2e; }
  .sec-h { color: #98989f; }
  form.filters select, form.filters input, .actions button, .chip-link, .tabs a
    { background: #1c1c1e; border-color: #3a3a3c; color: #f2f2f7; }
  form.filters button { background: #2563eb; border-color: #2563eb; color: #fff; }
  .actions button.primary { background: #2563eb; border-color: #2563eb; color: #fff; }
  .actions button.copy { color: #6ea8fe; }
  pre { background: #2c2c2e; }
  .ostatus, .rb { background: #2c2c2e; color: #d1d5db; }
  .rb-on { background: #0369a1; color: #fff; }
  .repo, .repo a, .meta, .muted, .count, form.filters label, .field .k, .issue .k, .smoke-meta { color: #98989f; }
  .back a { color: #6ea8fe; }
  .tabs a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
  .nav a, .filters-chips a { background: #1c1c1e; border-color: #3a3a3c; color: #f2f2f7; }
  .nav a.active, .filters-chips a.on { background: #2563eb; color: #fff; border-color: #2563eb; }
  .tree { background: #2c2c2e; }
  .gp-PASS { background: #14532d; color: #bbf7d0; } .gp-FAIL { background: #7f1d1d; color: #fecaca; }
  .gp-SKIP { background: #3a3a3c; color: #d1d5db; } .gp-UNKNOWN { background: #713f12; color: #fde68a; }
}
"""

_COPY_JS = """
function copyText(id, btn) {
  var el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(function () {
    var old = btn.textContent; btn.textContent = '복사됨';
    setTimeout(function () { btn.textContent = old; }, 1200);
  });
}
"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _nav(active: str) -> str:
    """상단 네비게이션 (§7). active = 'challenge' | 'product'."""
    return (
        '<nav class="nav">'
        f'<a href="/" class="{"active" if active == "challenge" else ""}">Challenge Inbox</a>'
        f'<a href="/products" class="{"active" if active == "product" else ""}">Product Runs</a>'
        "</nav>"
    )


def _label_badge(label: str | None) -> str:
    lab = label or "DROP"
    return f'<span class="badge l-{_e(lab)}">{_e(_LABEL_KO.get(lab, lab))}</span>'


def _ostatus_badge(status: str | None) -> str:
    st = status or "unseen"
    return f'<span class="ostatus">{_e(_OSTATUS_KO.get(st, st))}</span>'


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_e(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
<h1><a href="/">RIM 챌린지 대시보드</a></h1>
{body}
</div>
<script>{_COPY_JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------- HTML 렌더링

def render_index(conn: sqlite3.Connection, filters: dict) -> str:
    s = today_summary(conn)
    labels = s["labels"]
    avail = sum(1 for k in s["keys"] if k["status"] == "available")
    summary = f"""
<section class="summary">
  <h2 class="sec-h">오늘 요약</h2>
  <div class="sgrid">
    <div class="sitem"><span class="k">오늘 생성</span><span class="val">{s['today_total']}건</span></div>
    <div class="sitem"><span class="k">좋은 과제</span><span class="val">{labels.get('GOOD_CHALLENGE', 0)}건</span></div>
    <div class="sitem"><span class="k">훔칠 것만</span><span class="val">{labels.get('STEAL_ONLY', 0)}건</span></div>
    <div class="sitem"><span class="k">너무 쉬움</span><span class="val">{labels.get('TOO_EASY', 0)}건</span></div>
    <div class="sitem"><span class="k">버림</span><span class="val">{labels.get('DROP', 0)}건</span></div>
    <div class="sitem"><span class="k">에러</span><span class="val">{s['errors']}건</span></div>
    <div class="sitem"><span class="k">처리 중 / 대기 중</span><span class="val">{s['queue']['in_progress']} / {s['queue']['queued']}</span></div>
    <div class="sitem"><span class="k">수집기 상태</span><span class="val">{'멈춤' if s['paused'] else '실행 중'}</span></div>
    <div class="sitem"><span class="k">가용 키</span><span class="val">{avail} / {len(s['keys'])}</span></div>
  </div>
</section>"""

    label_opts = '<option value="">라벨 전체</option>' + "".join(
        f'<option value="{lab}"{" selected" if filters.get("final_label") == lab else ""}>{_LABEL_KO.get(lab, lab)}</option>'
        for lab in CHALLENGE_LABELS
    )
    status_opts = '<option value="">판정 전체</option>' + "".join(
        f'<option value="{st}"{" selected" if filters.get("owner_status") == st else ""}>{_OSTATUS_KO.get(st, st)}</option>'
        for st in OWNER_STATUSES
    )
    filter_form = f"""
<form class="filters" method="get" action="/">
  <label>라벨<select name="final_label">{label_opts}</select></label>
  <label>내 판정<select name="owner_status">{status_opts}</select></label>
  <label>언어<input name="language" placeholder="예: Python" value="{_e(filters.get('language') or '')}"></label>
  <label>날짜<input name="created_date" placeholder="YYYY-MM-DD" value="{_e(filters.get('created_date') or '')}"></label>
  <label>점수 ≥<input name="score_min" inputmode="numeric" size="4" value="{_e(filters.get('score_min') or '')}"></label>
  <label>점수 ≤<input name="score_max" inputmode="numeric" size="4" value="{_e(filters.get('score_max') or '')}"></label>
  <button type="submit">필터 적용</button>
  <a class="chip-link" href="/">초기화</a>
  <a class="chip-link" href="/?owner_status=build_next">다음 구현만 보기</a>
  <a class="chip-link" href="/products">제품 공장</a>
</form>"""

    rows = query_challenges(conn, filters)
    cards = []
    for c in rows:
        cards.append(
            f"""  <article class="card">
    <div class="chead">
      <span class="repo"><a href="/challenge/{c['id']}">{_e(_repo_name(c))}</a></span>
      {_label_badge(c['final_label'])}
      {_ostatus_badge(c['owner_status'])}
    </div>
    <p class="title"><a href="/challenge/{c['id']}">{_e(c['challenge_title'])}</a></p>
    <p class="oneline">{_e(c['one_line_challenge'])}</p>
    <p class="meta">이해도 {_e(c['owner_clarity_score'])}/5 · 점수 {_e(c['score_total'])}/40 · {_e(c.get('language') or '언어 미상')} · {_e((c.get('created_at') or '')[:10])}</p>
  </article>"""
        )
    count_line = f'<p class="count">{len(rows)}건 표시</p>'
    body = _nav("challenge") + summary + filter_form + count_line + (
        "\n".join(cards) if cards else '<p class="muted">조건에 맞는 과제가 없습니다.</p>'
    )
    return _page("RIM 챌린지 대시보드", body)


def _repo_name(c: dict) -> str:
    url = c.get("repo_url") or ""
    return url.removeprefix("https://github.com/") or "(알 수 없음)"


def render_detail(conn: sqlite3.Connection, challenge_id: int, tab: str, secrets: list[str]) -> str | None:
    c = get_challenge_detail(conn, challenge_id)
    if c is None:
        return None
    tab = tab if tab in DETAIL_FILES else "owner_brief"

    artifact_dir = Path(c.get("artifact_dir") or "")
    content = challenge_detail_content(artifact_dir, tab, secrets)

    tabs = "".join(
        f'<a href="/challenge/{challenge_id}?tab={key}" class="{"active" if key == tab else ""}">{label}</a>'
        for key, label in _TAB_KO
    )

    action_buttons = "".join(
        f"""<form method="post" action="/challenge/{challenge_id}/review" style="display:inline">
<input type="hidden" name="owner_status" value="{st}">
<button type="submit" class="{'primary' if st == 'build_next' else ''}{' on' if c['owner_status'] == st else ''}">{label}</button></form>"""
        for st, label in _STATUS_ACTIONS
    )

    # 복사 버튼용 원문 (implementation prompt / challenge card md)
    copy_sources = ""
    copy_buttons = ""
    for key, btn_label in (("implementation_prompt", "구현 지시문 복사"), ("challenge_card", "과제 카드 복사")):
        raw = challenge_copy_text(artifact_dir, key, secrets)
        if raw is not None:
            copy_sources += f'<pre id="copy-{key}" style="display:none">{_e(raw)}</pre>'
            copy_buttons += f'<button type="button" class="copy" onclick="copyText(\'copy-{key}\', this)">{btn_label}</button>'

    body = f"""
<p class="back"><a href="/">← 목록으로</a></p>
<section class="summary">
  <div class="chead">
    <span class="repo"><a href="{_e(c.get('repo_url'))}" target="_blank" rel="noopener">{_e(_repo_name(c))}</a></span>
    {_label_badge(c['final_label'])}
    {_ostatus_badge(c['owner_status'])}
  </div>
  <p class="title">{_e(c['challenge_title'])}</p>
  <p class="oneline">{_e(c['one_line_challenge'])}</p>
  <p class="meta">이해도 {_e(c['owner_clarity_score'])}/5 · 점수 {_e(c['score_total'])}/40</p>
</section>
<section class="panel">
  <h2 class="sec-h">내 판정</h2>
  <div class="actions">{action_buttons}</div>
  <div class="actions copy-row">{copy_buttons}</div>
  <form method="post" action="/challenge/{challenge_id}/review" style="margin-top:12px">
    <input type="hidden" name="owner_status" value="{_e(c['owner_status'])}">
    <textarea name="note" rows="2" placeholder="메모를 남기세요">{_e(c.get('owner_note') or '')}</textarea>
    <div class="actions"><button type="submit">메모 저장</button></div>
  </form>
</section>
<div class="tabs">{tabs}</div>
<section class="panel"><pre>{_e(content)}</pre></section>
{copy_sources}
"""
    return _page(f"챌린지 #{challenge_id}", body)


# ---------------------------------------------------------------- Product Factory 화면 (§8·§13: 검수 대기함)

def _verdict_badge(verdict: str | None) -> str:
    v = verdict or "PENDING"
    return f'<span class="badge v-{_e(v)}">{_e(L.format_verdict_label(verdict))}</span>'


def _status_badge(status: str | None) -> str:
    st = status or "pending"
    cls = st if st in ("done", "error", "running", "pending") else "pending"
    return f'<span class="sb sb-{cls}">{_e(L.format_status_label(st))}</span>'


def _review_badge(action: str | None) -> str:
    if not action:
        return '<span class="rb">미검수</span>'
    return f'<span class="rb rb-on">{_e(L.format_review_label(action))}</span>'


def _product_title(run: dict, psum: dict | None) -> str:
    """Challenge 제목 fallback (§12)."""
    return (
        run.get("challenge_title")
        or (psum or {}).get("challenge_title")
        or (f"Challenge #{run['challenge_id']}" if run.get("challenge_id") else None)
        or f"run #{run['id']}"
    )


def _gate_inline(gate: dict) -> str:
    passed, total = gate_pass_count(gate)
    return f"{passed}/{total} 통과"


def _gate_pills(gate: dict) -> str:
    out = []
    for key in GATE_KEYS:
        status = (gate.get(key) or {}).get("status", "UNKNOWN")
        out.append(
            f'<span class="gp gp-{_e(status)}"><span class="lbl">{_e(L.format_gate_label(key))}</span>'
            f'{_e(L.format_gate_status(status))}</span>'
        )
    return '<div class="gaterow">' + "".join(out) + "</div>"


def _continuation_line(dsum: dict) -> str:
    """Phase 1.7 continuation 결과 표시 (§18)."""
    if not dsum.get("is_continuation"):
        return ""
    resolved = dsum.get("continuation_resolved") or {}
    done = sum(1 for v in resolved.values() if v)
    total = len(resolved)
    remaining = dsum.get("remaining_failures") or []
    items = " / ".join(
        f'{_e(k)}: {"해결" if v else "미해결"}' for k, v in resolved.items()
    ) or "(분류된 실패 없음)"
    base = dsum.get("base_run_id")
    return (
        f'<p class="meta">Continuation: '
        f'{"#" + str(base) + " " if base else ""}수정 루프 {dsum.get("patch_attempts", 0)}회'
        f' · 해결 {done}/{total}</p>'
        f'<p class="meta">수정 결과: {items}</p>'
        + (f'<p class="meta">남은 실패: {_e(", ".join(remaining))}</p>' if remaining else "")
    )


def _lane_line(p2a: dict | None, dsum: dict | None) -> str:
    """Phase 2A 추천 경로 표시: 추천 경로/이유 한 줄/상태 (주문서 §9)."""
    p2a = p2a or {}
    dsum = dsum or {}
    lane = p2a.get("lane") or p2a.get("recommended_lane") or dsum.get("recommended_lane")
    if not lane:
        return ""
    reason = p2a.get("lane_reason") or dsum.get("lane_reason") or "-"
    status = p2a.get("lane_status") or dsum.get("lane_status") or "-"
    # Phase 2B-1b는 명시 추천 경로(Anti-Hardcode Patch)를 lane 라벨보다 우선 표시한다 (§15)
    path_label = p2a.get("recommended_path") or L.format_lane_label(lane)
    return (
        f'<p class="meta">추천 경로: <b>{_e(path_label)}</b></p>'
        f'<p class="meta">이유: {_e(reason)}</p>'
        f'<p class="meta">상태: {_e(status)}</p>'
    )


def _base_line(dsum: dict) -> str:
    """Green Base / Continuation Base 구분 표시 (§6.4, §10)."""
    if dsum.get("green_base"):
        text = "성장 루프 기준점: <b>준비됨</b>"
    elif dsum.get("continuation_base"):
        text = "성장 루프 기준점: 아직 아님 · 수정 시작점: <b>있음</b>"
    else:
        text = "성장 루프 기준점: 없음 · 수정 시작점: 없음"
    return f'<p class="meta">{text}</p>'


def _core_harness_panel(dsum: dict, final_dir: Path | None, run_root: Path | None) -> str:
    """Phase 1.6 상세: 코어 시스템 검증 결과 (§11.10 상세 페이지 표시)."""
    gates = dsum.get("gates") or {}
    pills = "".join(
        f'<span class="gp gp-{"PASS" if gates.get(k) else "FAIL"}">'
        f'<span class="lbl">{_e(L.CORE_GATE_LABELS.get(k, k))}</span>'
        f'{"통과" if gates.get(k) else "실패"}</span>'
        for k in L.CORE_GATE_LABELS
    )
    failed = dsum.get("failed_scenarios") or []
    failed_html = (
        "".join(f"<li>{_e(s)}</li>" for s in failed) or '<li class="muted">없음</li>'
    )
    replay = load_core_summary("scenario_replay_summary.json", final_dir, run_root) or {}
    golden = load_core_summary("golden_diff_summary.json", final_dir, run_root) or {}
    anti = load_core_summary("anti_hardcode_summary.json", final_dir, run_root) or {}
    return f"""
<section class="panel">
  <h2 class="sec-h">코어 시스템 검증</h2>
  <p class="meta">산출물 유형: <b>{_e(dsum.get('artifact_class_ko') or '-')}</b>
    · 코어: {"있음" if dsum.get('core_present') else "없음"}
    · 검증: {dsum.get('gates_passed', 0)}/{dsum.get('gates_total', 0)} 통과</p>
  <div class="gaterow">{pills}</div>
  <p class="meta">결정성: <b>{_e(dsum.get('determinism') or '-')}</b>
    · 위험: <b>{_e(dsum.get('risk_level') or '-')}</b>
    (하드코딩 {_e(dsum.get('hardcode_risk') or '-')} / golden 신뢰 {_e(dsum.get('oracle_risk_level') or '-')})</p>
  <p class="meta">시나리오 재생: {replay.get('passed', '-')}/{replay.get('total', '-')}
    · 기대 출력 비교: 통과 {golden.get('passed', '-')} / 실패 {golden.get('failed', '-')}
    / 참고용 제외 {golden.get('review_skipped', '-')} (exact {golden.get('exact_passed', '-')}/{golden.get('exact_total', '-')})</p>
  <div class="field"><span class="k">실패 시나리오</span><ul class="evi">{failed_html}</ul></div>
  <div class="field"><span class="k">실행 명령</span><span class="kv">{_e(dsum.get('runner_command') or '-')}</span></div>
  {_base_line(dsum)}
  <p class="meta">제품 레이어: <b>{"Replay 출력 사용 확인" if dsum.get('product_layer_consumes_core') else "Replay 출력 미확인"}</b>
    {"· <b>실전 검증(Live Validation) 실행</b>" if dsum.get('is_live_validation') else ""}</p>
  {_continuation_line(dsum)}
  <p class="meta">실행 안내: 상세 리포트 탭의 run_instructions
    · 하드코딩 신호 {len((anti.get('level1_problems') or [])) + len((anti.get('level2_problems') or []))}건
    · 추천: <b>{_e(dsum.get('recommendation') or '-')}</b></p>
</section>"""


_FITNESS_KO = {
    "PRODUCT_CANDIDATE": "제품화 후보",
    "NEEDS_PRODUCT_POLISH": "제품 다듬기 필요",
    "NEEDS_CORE_PATCH": "코어 보강 필요",
    "NEEDS_SPEC_REPAIR": "사양 수리 필요",
    "ARCHIVE": "아카이브",
}


def _fitness_ko(rec: str | None) -> str:
    return _FITNESS_KO.get(rec or "", rec or "-")


def _phase2c0_card_lines(p2c: dict | None) -> str:
    """목록 카드에 추가하는 3줄: 제품성 추천 · 검수 상태 · 사용자 다음 액션 (§16)."""
    if not p2c:
        return ""
    rec = p2c.get("recommended_fitness")
    ko = p2c.get("recommended_fitness_ko") or _fitness_ko(rec)
    return (
        f'<p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or "-")})</p>'
        f'<p class="meta">검수 상태: {_e(p2c.get("review_status") or "-")}</p>'
        f'<p class="meta">사용자 다음 액션: {_e(p2c.get("user_next_action") or "-")}</p>'
    )


def _phase2c0_panel(p2c: dict | None) -> str:
    """상세 페이지 Phase 2C-0 패널 (§16 상세). 추천/검수 상태/점수/red flag 표시."""
    if not p2c:
        return ""
    rec = p2c.get("recommended_fitness")
    ko = p2c.get("recommended_fitness_ko") or _fitness_ko(rec)
    scores = p2c.get("scores") or {}
    score_line = " · ".join(f"{_e(k)} {v}" for k, v in scores.items()) or "-"
    flags = p2c.get("critical_red_flags") or []
    return f"""
<section class="panel">
  <h2 class="sec-h">Phase 2C-0 제품성 추천 (사용자 최종 결정 대기)</h2>
  <p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or '-')}) · 평균 {_e(p2c.get('average_score'))}/5</p>
  <p class="meta">검수 상태: <b>{_e(p2c.get('review_status') or '-')}</b>
    · 사용자 다음 액션: {_e(p2c.get('user_next_action') or '-')}</p>
  <p class="meta">smoke: runner {"실행 가능" if p2c.get('runner_executable') else "미확인"}
    · viewer가 replay 소비 {"확인" if p2c.get('product_viewer_reads_replay') else "미확인"}
    · runner/viewer 일치 {_e(str(p2c.get('runner_viewer_consistent')))}
    · no-code-change {_e(p2c.get('no_code_change_status') or '-')}</p>
  <div class="field"><span class="k">제품성 점수</span>{score_line}</div>
  <div class="field"><span class="k">주의 신호</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in flags) or '<li class="muted">없음</li>'}</ul></div>
  <p class="meta">상세 문서: 아래 '리포트 미리보기'에서 검수 패키지 / 제품성 리포트 / 스모크 리뷰 확인</p>
</section>"""


def _phase2c1_card_lines(p2c1: dict | None) -> str:
    """목록 카드에 추가하는 4줄: 제품성 추천 · 검수 상태 · viewer polish · 사용자 다음 액션 (§12)."""
    if not p2c1:
        return ""
    rec = p2c1.get("recommended_fitness")
    ko = _fitness_ko(rec)
    return (
        f'<p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or "-")})</p>'
        f'<p class="meta">검수 상태: {_e(p2c1.get("review_status") or "-")}</p>'
        f'<p class="meta">viewer polish: {_e(p2c1.get("viewer_polish_status") or "-")}</p>'
        f'<p class="meta">사용자 다음 액션: {_e(p2c1.get("user_next_action") or "-")}</p>'
    )


def _phase2c1_panel(p2c1: dict | None) -> str:
    """상세 페이지 Phase 2C-1 패널: edge/event/layout fix 상태 + polish 후 제품성 (§12 상세)."""
    if not p2c1:
        return ""
    rec = p2c1.get("recommended_fitness")
    ko = _fitness_ko(rec)
    scores = p2c1.get("scores") or {}
    score_line = " · ".join(f"{_e(k)} {v}" for k, v in scores.items()) or "-"
    flags = p2c1.get("critical_red_flags") or []
    remaining = p2c1.get("viewer_schema_mismatches_remaining") or []

    def _mark(v):
        return "고쳐짐" if v else "미해결"

    return f"""
<section class="panel">
  <h2 class="sec-h">Phase 2C-1 Viewer Field Mapping Polish</h2>
  <p class="meta">edge 매핑: <b>{_mark(p2c1.get('edge_mapping_fixed'))}</b>
    · event 매핑: <b>{_mark(p2c1.get('event_mapping_fixed'))}</b>
    · node layout: <b>{_mark(p2c1.get('node_layout_generated'))}</b>
    (deterministic: {_e(str(p2c1.get('layout_deterministic')))})</p>
  <p class="meta">남은 schema mismatch: {_e(", ".join(remaining) if remaining else "없음")}
    · 보호 대상 hash: {_e(p2c1.get('hash_status') or '-')}
    · runner/viewer 일치: {_e(str(p2c1.get('runner_viewer_consistent')))}</p>
  <p class="meta">polish 후 제품성 추천: <b>{_e(ko)}</b> ({_e(rec or '-')})
    · 평균 {_e(p2c1.get('average_score'))}/5 · 검수 상태: {_e(p2c1.get('review_status') or '-')}</p>
  <div class="field"><span class="k">제품성 점수</span>{score_line}</div>
  <div class="field"><span class="k">주의 신호</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in flags) or '<li class="muted">없음</li>'}</ul></div>
</section>"""


def _phase2c2_card_lines(p2c2: dict | None) -> str:
    """목록 카드에 추가하는 4줄: 제품성 추천 · 검수 상태 · editor 상태 · 사용자 다음 액션 (§23)."""
    if not p2c2:
        return ""
    rec = p2c2.get("recommended_fitness")
    ko = _fitness_ko(rec)
    cand = " · draft editor candidate" if p2c2.get("draft_editor_candidate") else ""
    return (
        f'<p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or "-")}){_e(cand)}</p>'
        f'<p class="meta">검수 상태: {_e(p2c2.get("review_status") or "-")}</p>'
        f'<p class="meta">editor 상태: {_e(p2c2.get("editor_status") or "-")}</p>'
        f'<p class="meta">사용자 다음 액션: {_e(p2c2.get("user_next_action") or "-")}</p>'
    )


def _phase2c2_panel(p2c2: dict | None) -> str:
    """상세 페이지 Phase 2C-2 패널: editor 기능/JS/DOM/handler/model/ui + draft 호환·roundtrip (§23)."""
    if not p2c2:
        return ""
    rec = p2c2.get("recommended_fitness")
    ko = _fitness_ko(rec)
    flags = p2c2.get("critical_failures") or []
    lims = p2c2.get("limitations") or []
    types = p2c2.get("supported_node_types") or []

    def _mark(v):
        return "있음" if v else "없음"

    def _pf(v):
        return "PASS" if v else "FAIL"

    return f"""
<section class="panel">
  <h2 class="sec-h">Phase 2C-2 Minimal Node Draft Editor (draft editor — runner-backed execution not included)</h2>
  <p class="meta">editor mode: <b>{_mark(p2c2.get('editor_mode_exists'))}</b>
    · supported node types({_e(p2c2.get('supported_node_types_source') or '-')}): {_e(', '.join(types) or '-')}</p>
  <p class="meta">add node: {_mark(p2c2.get('add_node_supported'))}
    · add edge: {_mark(p2c2.get('add_edge_supported'))}
    · validation: {_mark(p2c2.get('graph_validation_supported'))}
    · draft 호환: {_pf(p2c2.get('draft_schema_compatible'))}
    · roundtrip: {_pf(p2c2.get('draft_roundtrip_pass'))}</p>
  <p class="meta">JS syntax: <b>{_e(p2c2.get('js_syntax_status') or '-')}</b>
    · model_level_smoke: {_pf(p2c2.get('model_level_smoke_pass'))}
    · ui_binding_evidence: {_pf(p2c2.get('ui_binding_evidence_pass'))}
    · 보호 대상 hash: {_e(p2c2.get('hash_status') or '-')}</p>
  <p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or '-')})
    · draft editor candidate: {_e(str(p2c2.get('draft_editor_candidate')))}
    · 검수 상태: {_e(p2c2.get('review_status') or '-')}</p>
  <div class="field"><span class="k">한계</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in lims) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">critical failures</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in flags) or '<li class="muted">없음</li>'}</ul></div>
</section>"""


def _phase2c3_card_lines(p2c3: dict | None) -> str:
    """목록 카드에 추가하는 4줄: 제품성 추천 · 검수 상태 · 실행 상태 · 사용자 다음 액션."""
    if not p2c3:
        return ""
    rec = p2c3.get("recommended_fitness")
    ko = _fitness_ko(rec)
    loop = " · product loop closed" if p2c3.get("product_loop_closed") else ""
    return (
        f'<p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or "-")}){_e(loop)}</p>'
        f'<p class="meta">검수 상태: {_e(p2c3.get("review_status") or "-")}</p>'
        f'<p class="meta">실행 상태: {_e(p2c3.get("execution_status") or "-")}</p>'
        f'<p class="meta">사용자 다음 액션: {_e(p2c3.get("user_next_action") or "-")}</p>'
    )


def _phase2c3_panel(p2c3: dict | None) -> str:
    """상세 페이지 Phase 2C-3 패널: 어댑터/runner/브리지/revise 사이클 + 실행 방법."""
    if not p2c3:
        return ""
    rec = p2c3.get("recommended_fitness")
    ko = _fitness_ko(rec)
    lims = p2c3.get("limitations") or []
    flags = p2c3.get("critical_red_flags") or []

    def _pf(v):
        return "PASS" if v else "FAIL"

    return f"""
<section class="panel">
  <h2 class="sec-h">Phase 2C-3 Runner-backed Draft Execution (초안을 실제 엔진으로 실행)</h2>
  <p class="meta">실행 스모크: <b>{_pf(p2c3.get('execution_smoke_pass'))}</b>
    · 수정→재실행 반영(revise): {_pf(p2c3.get('revise_cycle_changes_result'))}
    · 실행 서버: {_pf(p2c3.get('bridge_server_ok'))}
    · 원본 replay 불변: {_pf(p2c3.get('original_replay_unchanged'))}</p>
  <p class="meta">product loop closed: <b>{_e(str(p2c3.get('product_loop_closed')))}</b>
    · runner-backed execution included: {_e(str(p2c3.get('runner_backed_execution_included')))}
    · 보호 대상 hash: {_e(p2c3.get('hash_status') or '-')}</p>
  <p class="meta">제품성 추천: <b>{_e(ko)}</b> ({_e(rec or '-')})
    · 검수 상태: {_e(p2c3.get('review_status') or '-')}</p>
  <p class="meta">실행 방법: 아티팩트 루트에서 <code>{_e(p2c3.get('bridge_command') or '-')}</code>
    실행 후 viewer에서 Execute Draft 버튼</p>
  <div class="field"><span class="k">한계</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in lims) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">red flags</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in flags) or '<li class="muted">없음</li>'}</ul></div>
</section>"""


def _draft_execution_panel(de: dict | None) -> str:
    """generic runner-backed draft execution 패널 — 실행 상태를 정직하게 표시한다 (이슈 #6 §14).

    실패/timeout/unsupported/unsafe를 completed나 empty로 감추지 않는다."""
    if not de:
        return ""
    status = de.get("execution_status") or de.get("pre_execution_status") or "-"
    problems = de.get("validation_problems") or de.get("problems") or []
    return f"""
<section class="panel">
  <h2 class="sec-h">Runner-backed Draft Execution (generic — 도메인 중립 실행 lane)</h2>
  <p class="meta">실행 상태: <b>{_e(status)}</b>
    · runner-backed execution included: {_e(str(de.get('runner_backed_execution_included')))}
    · validation: {_e('PASS' if de.get('validation_pass') else 'FAIL')}</p>
  <p class="meta">execution id: {_e(de.get('execution_id') or '-')}</p>
  <div class="field"><span class="k">문제</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in problems) or '<li class="muted">없음</li>'}</ul></div>
</section>"""


def _phase2d0_card_lines(p2d0: dict | None) -> str:
    """목록 카드에 추가하는 autopilot 줄: prior fitness/stage/next lane/status (§29)."""
    if not p2d0:
        return ""
    prior = p2d0.get("prior_fitness_label") or "-"
    qual = p2d0.get("prior_fitness_qualifier")
    return (
        f'<p class="meta">prior fitness: {_e(prior)}{_e(" / " + qual if qual else "")}</p>'
        f'<p class="meta">autopilot stage: <b>{_e(p2d0.get("autopilot_stage") or "-")}</b></p>'
        f'<p class="meta">next lane: {_e(p2d0.get("next_lane") or "-")}</p>'
        f'<p class="meta">autopilot: {_e(p2d0.get("autopilot_status") or "-")}'
        f' · auto_order quality: {_e(p2d0.get("auto_order_status") or "-")}'
        f' · repair blueprint: {_e(p2d0.get("repair_blueprint_status") or "-")}</p>'
    )


def _phase2d0_panel(p2d0: dict | None, run_root: Path | None) -> str:
    """상세 페이지 Phase 2D-0 패널: evidence/hard blocker/judge/gap/lane/order/blueprint/mock loop (§29)."""
    if not p2d0:
        return ""
    d = load_phase2d0_details(run_root)
    loop = d["evidence"].get("product_loop") or {}
    q = d["quality"]
    hard = d["hard"]
    label = d["label"]
    gap = d["gap"]
    lane = d["lane"]
    quality_rep = d["quality_report"]
    mock = d["mock"]

    def _tf(v):
        return "true" if v is True else ("false" if v is False else "-")

    loop_line = " · ".join(f"{k.replace('can_', '')}={_tf(v)}" for k, v in loop.items())
    q_line = " · ".join(f"{k}={_tf(v)}" for k, v in q.items())
    blockers = hard.get("applied") or []
    stop = p2d0.get("stop_conditions") or []
    mock_line = " · ".join(f"{k}={_tf(mock.get(k))}" for k in (
        "auto_order_read", "scope_guard_read", "repair_followed_order",
        "protected_files_unchanged", "smoke_ran", "validate_ran", "rejudge_ran")) if mock else "-"
    return f"""
<section class="panel">
  <h2 class="sec-h">Phase 2D-0 Gemma Productization Autopilot</h2>
  <p class="meta">prior fitness: {_e(p2d0.get('prior_fitness_label') or '-')}
    {_e('/ ' + p2d0.get('prior_fitness_qualifier') if p2d0.get('prior_fitness_qualifier') else '')}
    → autopilot stage: <b>{_e(p2d0.get('autopilot_stage') or '-')}</b>
    (is_product_candidate: {_tf(p2d0.get('autopilot_is_product_candidate'))})</p>
  <p class="meta">primary gap: <b>{_e(gap.get('primary_gap') or '-')}</b>
    · next lane: <b>{_e(p2d0.get('next_lane') or '-')}</b>
    · lane risk: {_e(lane.get('lane_risk') or '-')}
    · auto_execute: {_tf(lane.get('auto_execute_allowed'))}</p>
  <p class="meta">autopilot: {_e(p2d0.get('autopilot_status') or '-')}
    · auto_order quality: {_e(quality_rep.get('status') or '-')} ({_e(quality_rep.get('auto_order_quality_score'))})
    · repair blueprint: {_e(p2d0.get('repair_blueprint_status') or '-')}
    · 보호 대상 hash: {_e(p2d0.get('hash_status') or '-')}</p>
  <div class="field"><span class="k">Artifact Evidence</span><p class="meta">{_e(loop_line or '-')}</p></div>
  <div class="field"><span class="k">User-Facing Quality</span><p class="meta">{_e(q_line or '-')}</p></div>
  <div class="field"><span class="k">Hard Blockers</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in blockers) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">판정 이유</span><p class="meta">{_e(label.get('reason') or '-')}</p></div>
  <div class="field"><span class="k">Mock Loop Order Following</span><p class="meta">{_e(mock_line)}</p></div>
  <div class="field"><span class="k">Stop Conditions</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in stop) or '<li class="muted">없음</li>'}</ul></div>
</section>"""


def _phase2d1_card_lines(p2d1: dict | None) -> str:
    """목록 카드 3줄: iteration/stage, gap/lane, stop/coverage (§12 — 기술 로그는 상세로)."""
    if not p2d1:
        return ""
    cov = p2d1.get("critical_requirement_coverage")
    return (
        f'<p class="meta">closed loop: iter {_e(p2d1.get("iteration"))}/{_e(p2d1.get("max_iterations"))}'
        f' · stage: <b>{_e(p2d1.get("current_stage") or "-")}</b>'
        f' (이전: {_e(p2d1.get("previous_stage") or "-")})</p>'
        f'<p class="meta">gap: {_e(p2d1.get("primary_gap") or "-")}'
        f' · lane: {_e(p2d1.get("selected_lane") or "-")}'
        f' · mock fallback: {_e(p2d1.get("mock_fallback_count"))}'
        f' · coverage: {_e(cov if cov is not None else "-")}</p>'
        f'<p class="meta">loop status: <b>{_e(p2d1.get("status") or "-")}</b>'
        f' · stop: {_e(p2d1.get("stop_reason") or "-")}'
        f'{" · <b>사람 검수 필요</b>" if p2d1.get("hold_for_human") else ""}</p>'
    )


def _phase2d1_panel(p2d1: dict | None, run_root: Path | None) -> str:
    """상세 페이지 Phase 2D-1 패널: iteration별 stage/gap/lane/delta + lineage (§12)."""
    if not p2d1:
        return ""
    d = load_phase2d1_details(p2d1, run_root)
    summary = d["summary"]
    lineage = d["lineage"]
    hold = d["hold"]

    def _tf(v):
        return "true" if v is True else ("false" if v is False else "-")

    iter_rows = ""
    for it in summary.get("iterations") or []:
        delta = it.get("metric_delta") or {}
        delta_line = " ".join(f"{k}={v}" for k, v in delta.items()) or "-"
        iter_rows += (
            f'<tr><td>{_e(it.get("iteration"))}</td>'
            f'<td>{_e(it.get("stage_before") or "-")}'
            f'{_e(" → " + it["stage_after"] if it.get("stage_after") else "")}</td>'
            f'<td>{_e(it.get("primary_gap_before") or "-")}</td>'
            f'<td>{_e(it.get("selected_lane") or "-")}</td>'
            f'<td>{_e(it.get("lane_status") or "-")}</td>'
            f'<td>{_e(it.get("progress") or "-")}</td>'
            f'<td class="meta">{_e(delta_line)}</td></tr>')
    lineage_rows = ""
    for en in lineage.get("entries") or []:
        lineage_rows += (
            f'<tr><td>{_e(en.get("iteration"))}</td>'
            f'<td class="meta">{_e(en.get("parent_run_dir") or "-")}</td>'
            f'<td class="meta">{_e(en.get("child_run_dir") or "-")}</td>'
            f'<td>{_e(en.get("selected_lane") or "-")}</td></tr>')
    hold_html = ""
    if hold:
        hold_html = (
            f'<div class="field"><span class="k">HOLD_FOR_HUMAN</span>'
            f'<p class="meta">{_e(hold.get("why_not_automated") or "-")}</p>'
            f'<p class="meta"><b>질문: {_e(hold.get("single_question_for_human") or "-")}</b></p>'
            f'<ul class="evi">{"".join(f"<li>{_e(o)}</li>" for o in hold.get("recommended_options") or [])}</ul></div>')
    return f"""
<section class="panel">
  <h2 class="sec-h">Phase 2D-1 Closed Productization Loop</h2>
  <p class="meta">loop: {_e(p2d1.get('loop_id') or '-')}
    · iteration {_e(p2d1.get('iteration'))}/{_e(p2d1.get('max_iterations'))}
    · stage: <b>{_e(p2d1.get('current_stage') or '-')}</b> (이전: {_e(p2d1.get('previous_stage') or '-')})
    · status: <b>{_e(p2d1.get('status') or '-')}</b></p>
  <p class="meta">critical requirement coverage: {_e(p2d1.get('critical_requirement_coverage'))}
    · anchor coverage: {_e(p2d1.get('anchor_coverage'))}
    · mock fallback: {_e(p2d1.get('mock_fallback_count'))}
    · regression: {_tf(p2d1.get('regression'))}
    · base hash: {_e(p2d1.get('base_hash_status') or '-')}</p>
  <p class="meta">active candidate: {_e(p2d1.get('active_child_run') or '-')}
    · stop: {_e(p2d1.get('stop_reason') or '-')}</p>
  <div class="field"><span class="k">Iterations</span>
  <table class="tbl"><tr><th>#</th><th>stage</th><th>gap</th><th>lane</th><th>lane 결과</th><th>progress</th><th>delta</th></tr>
  {iter_rows or '<tr><td colspan="7" class="muted">없음</td></tr>'}</table></div>
  <div class="field"><span class="k">Lineage</span>
  <table class="tbl"><tr><th>#</th><th>parent</th><th>child</th><th>lane</th></tr>
  {lineage_rows or '<tr><td colspan="4" class="muted">없음</td></tr>'}</table></div>
  {hold_html}
</section>"""


def _smoke_preview_html(smoke: dict, secrets: list[str]) -> str:
    cmd = smoke.get("command")
    stdout = redact_text(head_lines(smoke.get("stdout_preview") or ""), secrets)
    stderr = redact_text(head_lines(smoke.get("stderr_preview") or ""), secrets)
    if not cmd and not stdout and not stderr:
        return '<p class="muted">Smoke 실행 출력 없음 (정적 검사이거나 structured summary 없음).</p>'
    meta = (
        f'<p class="smoke-meta">command: <span class="kv">{_e(cmd or "-")}</span></p>'
        f'<p class="smoke-meta">exit_code: {_e(smoke.get("exit_code"))} · timeout: {_e(bool(smoke.get("timeout")))}</p>'
    )
    blocks = ""
    if stdout:
        blocks += f'<div class="field"><span class="k">stdout (앞 30줄)</span><pre>{_e(stdout)}</pre></div>'
    if stderr:
        blocks += f'<div class="field"><span class="k">stderr (앞 30줄)</span><pre>{_e(stderr)}</pre></div>'
    return meta + blocks


def _action_buttons(run_id: int, recommended: str | None, current: str | None, next_goal: str) -> str:
    out = []
    for d, _en in _DECISION_ACTIONS:
        cls = ("primary" if d == recommended else "") + (" on" if d == current else "")
        extra = ""
        if d in ("retry", "productize") and next_goal:
            extra = f'<input type="hidden" name="selected_next_goal" value="{_e(next_goal)}">'
        star = " (추천)" if d == recommended else ""
        out.append(
            f'<form method="post" action="/product/{run_id}/decision" style="display:inline">'
            f'<input type="hidden" name="decision" value="{d}">{extra}'
            f'<button type="submit" class="{cls.strip()}">{_e(L.format_review_label(d))}{star}</button></form>'
        )
    return "".join(out)


def _product_filter_chips(filters: dict) -> str:
    active = filters.get("verdict"), filters.get("status"), (filters.get("review") or "").lower()
    chips = [("전체", "/products", not any(active))]
    for lab in PRODUCT_VERDICT_LABELS:
        chips.append((L.format_verdict_label(lab), f"/products?verdict={lab}", filters.get("verdict") == lab))
    chips.append(("오류", "/products?status=error", filters.get("status") == "error"))
    chips.append(("미검수", "/products?review=unreviewed", active[2] == "unreviewed"))
    chips.append(("검수완료", "/products?review=reviewed", active[2] == "reviewed"))
    chips.append(("다시 돌리기", "/products?review=retry", active[2] == "retry"))
    chips.append(("제품화", "/products?review=productize", active[2] == "productize"))
    links = "".join(
        f'<a href="{href}" class="{"on" if on else ""}">{_e(lab)}</a>' for lab, href, on in chips
    )
    return f'<div class="filters-chips">{links}</div>'


def render_products_index(conn: sqlite3.Connection, filters: dict) -> str:
    all_runs = list_product_runs(conn)
    reviews = latest_reviews_map(conn)
    verdict_counts: dict[str, int] = {}
    error_n = unreviewed_n = 0
    for r in all_runs:
        verdict_counts[r.get("verdict") or "PENDING"] = verdict_counts.get(r.get("verdict") or "PENDING", 0) + 1
        if r.get("status") == "error":
            error_n += 1
        if reviews.get(r["id"]) is None:
            unreviewed_n += 1

    summary = f"""
<section class="summary">
  <h2 class="sec-h">결과물 요약</h2>
  <div class="sgrid">
    <div class="sitem"><span class="k">전체</span><span class="val">{len(all_runs)}건</span></div>
    <div class="sitem"><span class="k">제품화 후보</span><span class="val">{verdict_counts.get('PROMOTE_TO_CODEX', 0)}건</span></div>
    <div class="sitem"><span class="k">더 돌려야 함</span><span class="val">{verdict_counts.get('NEEDS_MORE_GEMMA_LOOP', 0)}건</span></div>
    <div class="sitem"><span class="k">오류</span><span class="val">{error_n}건</span></div>
    <div class="sitem"><span class="k">미검수</span><span class="val">{unreviewed_n}건</span></div>
  </div>
</section>"""

    runs = [r for r in all_runs if match_product_filters(r, reviews.get(r["id"]), filters)]
    cards = []
    for r in runs:
        final_dir, run_root = product_dirs(r)
        psum = load_product_summary(final_dir, run_root)
        dsum = load_dashboard_summary(final_dir, run_root)
        p2a = load_core_summary("phase2b1b_dashboard_summary.json", final_dir, run_root) \
            or load_core_summary("phase2b1_dashboard_summary.json", final_dir, run_root) \
            or load_core_summary("phase2a_dashboard_summary.json", final_dir, run_root)
        rev = reviews.get(r["id"])
        title = _product_title(r, psum)
        if dsum:
            # Phase 1.6 Core Harness run: 검수용 카드 (§11.10 — 기술 로그 노출 금지)
            body_lines = (
                f'<p class="meta">산출물 유형: <b>{_e(dsum.get("artifact_class_ko") or "-")}</b>'
                f' · 코어: {"있음" if dsum.get("core_present") else "없음"}'
                f' · 검증: {dsum.get("gates_passed", 0)}/{dsum.get("gates_total", 0)} 통과</p>'
                f'<p class="meta">결정성: {_e(dsum.get("determinism") or "-")}'
                f' · 위험: {_e(dsum.get("risk_level") or "-")}'
                f' · 추천: <b>{_e(dsum.get("recommendation") or "-")}</b></p>'
                f'{_base_line(dsum)}'
                f'<p class="meta">제품 레이어: '
                f'{"Replay 출력 사용 확인" if dsum.get("product_layer_consumes_core") else "Replay 출력 미확인"}'
                f'{" · <b>실전 검증 실행</b>" if dsum.get("is_live_validation") else ""}</p>'
                f'{_continuation_line(dsum)}'
                f'{_lane_line(p2a, dsum)}'
            )
        else:
            gate = load_gate_summary(final_dir, run_root)
            qa = load_qa_summary(final_dir, run_root)
            passed, total = gate_pass_count(gate)
            issue = L.humanize_issue((psum or {}).get("issue_summary") or qa.get("issue_summary") or "-")
            recommended = L.format_recommended(r.get("verdict"), r.get("status"))
            body_lines = (
                f'<div class="issue"><span class="k">문제</span> {_e(issue)}</div>'
                f'<p class="meta">검사 {passed}/{total} 통과 · 품질 {_e(L.format_qa_status(overall_qa_status(qa)))}</p>'
                f'<p class="meta">추천 {_e(recommended)}</p>'
                f'{_lane_line(p2a, None)}'
            )
        p2c3 = load_phase2c3(run_root)
        p2c2 = load_phase2c2(run_root)
        p2c1 = load_phase2c1(run_root)
        if p2c3:
            body_lines += _phase2c3_card_lines(p2c3)
        elif p2c2:
            body_lines += _phase2c2_card_lines(p2c2)
        elif p2c1:
            body_lines += _phase2c1_card_lines(p2c1)
        else:
            body_lines += _phase2c0_card_lines(load_phase2c0(run_root))
        body_lines += _phase2d0_card_lines(load_phase2d0(run_root))
        body_lines += _phase2d1_card_lines(load_phase2d1(run_root))
        cards.append(
            f"""  <article class="card">
    <div class="chead">
      <span class="repo"><a href="/product/{r['id']}">번호 {r['id']}</a></span>
      {_verdict_badge(r.get('verdict'))}
      {_status_badge(r.get('status'))}
      {_review_badge((rev or {}).get('action'))}
    </div>
    <p class="title"><a href="/product/{r['id']}">{_e(title)}</a></p>
    {body_lines}
    <p class="meta"><a href="/product/{r['id']}">상세 보기 →</a></p>
  </article>"""
        )

    body = (
        _nav("product")
        + summary
        + _product_filter_chips(filters)
        + (
            f'<p class="count">{len(runs)}건 표시</p>' + "\n".join(cards)
            if cards
            else '<p class="muted">조건에 맞는 product run이 없습니다.</p>'
        )
    )
    return _page("RIM Product Runs", body)


def render_product_detail(
    conn: sqlite3.Connection, run_id: int, tab: str, secrets: list[str], src: str | None = None
) -> str | None:
    run = get_product_run(conn, run_id)
    if run is None:
        return None
    final_dir, run_root = product_dirs(run)
    psum = load_product_summary(final_dir, run_root)
    gate = load_gate_summary(final_dir, run_root)
    qa = load_qa_summary(final_dir, run_root)

    verdict = run.get("verdict")
    status = run.get("status")
    rev = latest_review(conn, run_id)
    rev_action = (rev or {}).get("action")
    recommended = VERDICT_TO_RECOMMENDED_ACTION.get(verdict or "", None)  # 소문자 decision key
    reason = (psum or {}).get("reason") or "판정 이유 정보 없음."
    next_goal = (psum or {}).get("next_goal") or qa.get("next_goal") or ""
    title = _product_title(run, psum)

    # 원본 challenge (§15)
    ch = get_challenge_brief(conn, run["challenge_id"]) if run.get("challenge_id") else None

    action_buttons = _action_buttons(run_id, recommended, rev_action, next_goal)
    reason_h = L.humanize_issue(reason)
    rec_ko = L.format_recommended(verdict, status)

    # 1. 판정 요약(Hero) — 한국어 검수 문장 (§11). 영어 원문은 접힘 영역에 (§13·§14)
    hero = f"""
<section class="summary">
  <div class="chead">
    <span class="repo">번호 {run_id}</span>
    {_verdict_badge(verdict)}
    {_status_badge(status)}
    {_review_badge(rev_action)}
  </div>
  <p class="title">{_e(title)}</p>
  <p class="meta">추천: <b>{_e(rec_ko)}</b> · 상태 {_e(L.format_status_label(status))}
    · {_e((run.get('created_at') or '')[:19].replace('T', ' '))}</p>
  <div class="issue"><span class="k">이유</span> {_e(reason_h)}</div>
  <p class="meta">검사: {_gate_inline(gate)} · 품질: {_e(L.format_qa_status(overall_qa_status(qa)))}</p>
  <div class="actions" style="margin-top:12px">{action_buttons}</div>
  <details class="raw"><summary>원본 상태값 보기</summary>
    <p class="kv">verdict: {_e(verdict or 'null')}</p>
    <p class="kv">status: {_e(status)}</p>
    <p class="kv">review: {_e(rev_action or 'unreviewed')}</p>
    <p class="kv">recommended: {_e(recommended or '-')}</p>
    <p class="kv">stage: {_e(run.get('current_stage') or '-')} · line: {_e(run.get('line') or '-')}</p>
  </details>
</section>"""

    # 3. 원본 아이디어 요약 (§15)
    if ch or psum:
        anchors = (psum or {}).get("challenge_anchors") or []
        forbidden = (psum or {}).get("challenge_forbidden") or []
        brief = (psum or {}).get("owner_brief_summary") or "-"
        link = (
            f'<a href="/challenge/{ch["id"]}">원본 아이디어 상세 →</a>'
            if ch
            else '<span class="muted">원본 아이디어 정보 없음 (삭제되었거나 샘플)</span>'
        )
        ch_summary = f"""
<section class="panel">
  <h2 class="sec-h">원본 아이디어 요약</h2>
  <div class="field"><span class="k">한 줄 설명</span>{_e(brief)}</div>
  <div class="field"><span class="k">핵심 조건</span><ul class="evi">{''.join(f'<li>{_e(a)}</li>' for a in anchors) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">금지된 단순화</span><ul class="evi">{''.join(f'<li>{_e(f)}</li>' for f in forbidden) or '<li class="muted">없음</li>'}</ul></div>
  <p class="meta">{link}</p>
</section>"""
    else:
        ch_summary = '<section class="panel"><h2 class="sec-h">원본 아이디어 요약</h2><p class="muted">원본 아이디어 정보 없음</p></section>'

    # 4. 검사 결과 (§6·§16) — Phase 1.6 run은 코어 시스템 검증 패널로 대체
    dsum = load_dashboard_summary(final_dir, run_root)
    # Phase 2A/2B: 추천 경로 상세 패널 (§9, 2B-1 §16, 2B-1b §15 — 상세 페이지에만 기술 정보 표시)
    p2b1b = load_core_summary("phase2b1b_dashboard_summary.json", final_dir, run_root)
    p2b1 = load_core_summary("phase2b1_dashboard_summary.json", final_dir, run_root)
    p2a = load_core_summary("phase2a_dashboard_summary.json", final_dir, run_root)
    p2a_html = ""
    if p2b1b or p2b1 or p2a:
        disp = p2b1b or p2b1 or p2a
        ftypes = ", ".join(disp.get("failure_types") or disp.get("remaining_failures") or []) or "-"
        prop = "생성됨" if (p2a or {}).get("proposal_generated") else "없음"
        rev_res = (p2a or {}).get("review_result") or ("생성됨" if (p2a or {}).get("review_generated") else "없음")
        apply_line = ""
        if p2b1b:
            g = f"{p2b1b.get('gates_passed', 0)}/{p2b1b.get('gates_total', 0)} 통과"
            apply_line += (
                f'<p class="meta">Anti-Hardcode Patch: <b>{_e(p2b1b.get("patch_status") or "-")}</b>'
                f' · summary 출처: {_e(p2b1b.get("summary_source") or "-")}'
                f' · gate 재검증 {g}'
                f' · validate {"PASS" if p2b1b.get("validate_ok") else "FAIL"}</p>'
                f'<p class="meta">green 승격: {"됨" if p2b1b.get("promoted_to_green_base") else "안 됨"}'
                f' · 남은 실패: {_e(", ".join(p2b1b.get("remaining_failures") or []) or "없음")}</p>'
            )
        if p2b1:
            gates_line = f"{p2b1.get('gates_passed', 0)}/{p2b1.get('gates_total', 0)} 통과"
            apply_line += (
                f'<p class="meta">Spec Repair Apply: <b>{_e(p2b1.get("apply_status") or "-")}</b>'
                f' · 적용 파일 {len(p2b1.get("applied_files") or [])}개'
                f' · gate 재검증 {gates_line}'
                f' · validate {"PASS" if p2b1.get("validate_ok") else "FAIL"}</p>'
                f'<p class="meta">green 승격: {"됨" if p2b1.get("promoted_to_green_base") else "안 됨"}'
                f' · 남은 실패: {_e(", ".join(p2b1.get("remaining_failures") or []) or "없음")}</p>'
            )
        p2a_html = f"""
<section class="panel">
  <h2 class="sec-h">Phase 2A/2B 추천 경로</h2>
  {_lane_line(disp, dsum)}
  <p class="meta">failure types: {_e(ftypes)}</p>
  <p class="meta">위험도: {_e(disp.get('risk_level') or '-')}
    · 차단 사유: {_e(disp.get('blocking_reason') or '-')}</p>
  <p class="meta">spec repair 제안서: {_e(prop)} · 검토: {_e(rev_res)}</p>
  {apply_line}
  <p class="meta">frozen hash: {_e(disp.get('frozen_hash_status') or '-')}
    {f"· patch 결과: {_e(disp.get('patch_result'))}" if disp.get('patch_result') else ""}</p>
</section>"""

    if dsum:
        gate_html = _core_harness_panel(dsum, final_dir, run_root)
    else:
        gate_lines = "".join(
            f'<div class="field"><span class="k">{_e(L.format_gate_label(k))}</span>{_e(L.format_gate_status((gate.get(k) or {}).get("status", "UNKNOWN")))}</div>'
            for k in GATE_KEYS
        )
        gate_html = f"""
<section class="panel">
  <h2 class="sec-h">검사 결과</h2>
  {_gate_pills(gate)}
  {gate_lines}
</section>"""

    # 5. 품질 확인 (§7·§17)
    evidence = [L.humanize_issue(x) for x in (qa.get("evidence") or [])]
    qa_html = f"""
<section class="panel">
  <h2 class="sec-h">품질 확인</h2>
  <p class="meta">핵심 조건: <b>{_e(L.format_qa_status(qa.get('anchor_status')))}</b>
    · 금지된 단순화: <b>{_e(L.format_qa_status(qa.get('forbidden_status')))}</b>
    · 핵심 조작: <b>{_e(L.format_qa_status(qa.get('core_interaction_status')))}</b></p>
  <div class="issue"><span class="k">문제</span> {_e(L.humanize_issue(qa.get('issue_summary')) or '-')}</div>
  <div class="field"><span class="k">근거</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in evidence) or '<li class="muted">없음</li>'}</ul></div>
</section>"""

    # 6. 알려진 문제 / 다음 목표 (§18)
    known = [L.humanize_issue(x) for x in ((psum or {}).get("known_issues") or [])]
    issues_html = f"""
<section class="panel">
  <h2 class="sec-h">알려진 문제 / 다음 목표</h2>
  <div class="field"><span class="k">알려진 문제</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in known) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">다음 목표</span>{_e(L.humanize_issue(next_goal) or '없음')}</div>
</section>"""

    # 7. 실행 결과 미리보기 (§19) — 기술 로그이므로 접힘 (§13)
    smoke_html = f"""
<details class="panel raw">
  <summary class="sec-h">실행 결과 미리보기</summary>
  {_smoke_preview_html(gate.get('smoke') or {}, secrets)}
</details>"""

    # 8. 생성물 경로 (§15·§20) — 접힘
    codex_dir = (psum or {}).get("codex_export_dir")
    paths_html = f"""
<details class="panel raw">
  <summary class="sec-h">생성물 경로</summary>
  <div class="field"><span class="k">작업 폴더</span><span class="kv">{_e(run.get('workspace_dir') or '-')}</span></div>
  <div class="field"><span class="k">최종 결과 폴더</span><span class="kv">{_e(run.get('final_artifact_dir') or '(미생성)')}</span></div>
  <div class="field"><span class="k">제품화 전달 폴더</span><span class="kv">{_e(codex_dir or '-')}</span></div>
</details>"""

    # 9. 생성 파일 목록 (§15·§21) — 접힘
    tree_html = f"""
<details class="panel raw">
  <summary class="sec-h">생성 파일 목록</summary>
  <div class="tree">{_e(final_tree(final_dir))}</div>
</details>"""

    # 10. 소스 미리보기 (§15·§22) — 접힘
    src_files = source_files(final_dir)
    src_links = "".join(
        f'<a href="/product/{run_id}?src={_e(f)}" class="{"active" if src == f else ""}">{_e(f)}</a>'
        for f in src_files
    )
    src_content = ""
    if src:
        sp = safe_source_path(final_dir, src)
        if sp is not None:
            src_content = f'<pre>{_e(read_capped(sp, secrets))}</pre>'
        else:
            src_content = '<p class="muted">허용되지 않은 경로이거나 파일이 없습니다.</p>'
    source_html = f"""
<details class="panel raw"{' open' if src else ''}>
  <summary class="sec-h">소스 미리보기</summary>
  <div class="tabs">{src_links or '<span class="muted">표시할 소스 파일 없음</span>'}</div>
  {src_content}
</details>"""

    # 11. 리포트 미리보기 (§15·§23) — 접힘, 영어 원문 보존 (§14)
    tab = tab if tab in PRODUCT_REPORT_TABS_MAP else "product_verdict"
    base_kind, rel, _lbl = PRODUCT_REPORT_TABS_MAP[tab]
    base = final_dir if base_kind == "final" else run_root
    report_content = "(파일 없음)"
    if base and base.is_dir() and (base / rel).is_file():
        report_content = read_capped(base / rel, secrets)
    tabs = "".join(
        f'<a href="/product/{run_id}?tab={key}" class="{"active" if key == tab else ""}">{label}</a>'
        for key, (_, _, label) in PRODUCT_REPORT_TABS
    )
    report_html = f"""
<details class="panel raw"{' open' if tab != 'product_verdict' else ''}>
  <summary class="sec-h">리포트 미리보기 (원문)</summary>
  <div class="tabs">{tabs}</div>
  <pre>{_e(report_content)}</pre>
</details>"""

    # 12. 하단 판정 버튼 (§29: 상단·하단 모두 배치)
    bottom_actions = f"""
<section class="panel">
  <h2 class="sec-h">내 판정</h2>
  <div class="actions">{action_buttons}</div>
</section>"""

    body = (
        _nav("product")
        + '<p class="back"><a href="/products">← 목록으로</a></p>'
        + hero + ch_summary + p2a_html + _phase2c0_panel(load_phase2c0(run_root))
        + _phase2c1_panel(load_phase2c1(run_root))
        + _phase2c2_panel(load_phase2c2(run_root))
        + _phase2c3_panel(load_phase2c3(run_root))
        + _draft_execution_panel(load_draft_execution(run_root))
        + _phase2d0_panel(load_phase2d0(run_root), run_root)
        + _phase2d1_panel(load_phase2d1(run_root), run_root)
        + gate_html + qa_html + issues_html
        + smoke_html + paths_html + tree_html + source_html + report_html + bottom_actions
    )
    return _page(f"제품 번호 {run_id}", body)


# ---------------------------------------------------------------- HTTP 서버

class DashboardHandler(BaseHTTPRequestHandler):
    db_path: str = "challenge.db"
    secrets: list[str] = []

    def log_message(self, fmt, *args):  # noqa: A002 - 조용히
        pass

    def _send_html(self, text: str, code: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        conn = open_db(self.db_path)
        try:
            if parts.path == "/":
                filters = {
                    k: query.get(k)
                    for k in ("final_label", "owner_status", "language", "created_date", "score_min", "score_max")
                    if query.get(k)
                }
                self._send_html(render_index(conn, filters))
                return
            if parts.path.startswith("/challenge/"):
                try:
                    challenge_id = int(parts.path.split("/")[2])
                except (IndexError, ValueError):
                    self.send_error(404)
                    return
                page = render_detail(conn, challenge_id, query.get("tab", "owner_brief"), self.secrets)
                if page is None:
                    self.send_error(404, "challenge not found")
                    return
                self._send_html(page)
                return
            if parts.path == "/products":
                filters = {
                    k: query.get(k) for k in ("verdict", "status", "review") if query.get(k)
                }
                self._send_html(render_products_index(conn, filters))
                return
            if parts.path.startswith("/product/"):
                try:
                    run_id = int(parts.path.split("/")[2])
                except (IndexError, ValueError):
                    self.send_error(404)
                    return
                page = render_product_detail(
                    conn, run_id, query.get("tab", "product_verdict"), self.secrets,
                    src=query.get("src"),
                )
                if page is None:
                    self.send_error(404, "product run not found")
                    return
                self._send_html(page)
                return
            self.send_error(404)
        finally:
            conn.close()

    def do_POST(self) -> None:  # noqa: N802
        parts = urlsplit(self.path)
        segs = parts.path.strip("/").split("/")
        if len(segs) == 3 and segs[0] == "challenge" and segs[2] == "review":
            try:
                challenge_id = int(segs[1])
            except ValueError:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = {k: v[0] for k, v in parse_qs(body).items()}
            owner_status = form.get("owner_status") or "unseen"
            if owner_status not in OWNER_STATUSES:
                self.send_error(400, "invalid owner_status")
                return
            conn = open_db(self.db_path)
            try:
                if get_challenge_brief(conn, challenge_id) is None:
                    self.send_error(404, "challenge not found")
                    return
                set_owner_review(conn, challenge_id, owner_status, form.get("note") or None)
            finally:
                conn.close()
            self._redirect(f"/challenge/{challenge_id}")
            return
        if len(segs) == 3 and segs[0] == "product" and segs[2] == "decision":
            try:
                run_id = int(segs[1])
            except ValueError:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            form = {k: v[0] for k, v in parse_qs(body).items()}
            decision = form.get("decision") or ""
            if decision not in PRODUCT_OWNER_DECISIONS:
                self.send_error(400, "invalid decision")
                return
            conn = open_db(self.db_path)
            try:
                run = get_product_run(conn, run_id)
                if run is None:
                    self.send_error(404, "product run not found")
                    return
                # append-only 검수 기록 (§26). owner_decision도 내부에서 최신값으로 갱신된다.
                add_product_review(
                    conn, run_id, decision,
                    note=form.get("note") or None,
                    selected_next_goal=form.get("selected_next_goal") or None,
                )
                log_product_event(conn, run_id, "owner_decision", f"decision={decision}")
            finally:
                conn.close()
            self._redirect(f"/product/{run_id}")
            return
        self.send_error(404)


def make_dashboard_server(
    db_path: str | Path = "challenge.db",
    host: str = "127.0.0.1",
    port: int = 8787,
    secrets: list[str] | None = None,
) -> ThreadingHTTPServer:
    handler = type(
        "BoundDashboardHandler",
        (DashboardHandler,),
        {"db_path": str(db_path), "secrets": list(secrets or [])},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve_dashboard(
    db_path: str | Path = "challenge.db", host: str = "127.0.0.1", port: int = 8787,
    secrets: list[str] | None = None,
) -> None:
    server = make_dashboard_server(db_path, host, port, secrets)
    print(f"RIM Challenge Dashboard: http://{host}:{port}/  (db: {db_path})")
    if host not in ("127.0.0.1", "localhost"):
        print("주의: 인증이 없습니다. Tailscale 등 사설망에서만 사용하세요.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
