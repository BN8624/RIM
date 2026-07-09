# challenge.db를 읽어 Challenge 목록/상세/판정(SAVE·MAYBE·DROP·BUILD NEXT)을 제공하는 로컬 대시보드.
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from repo_idea_miner.challenge_db import is_paused, queue_counts, set_owner_review
from repo_idea_miner.challenge_schemas import CHALLENGE_LABELS, LABEL_PRIORITY, OWNER_STATUSES
from repo_idea_miner.factory_db import (
    add_product_review,
    get_product_run,
    latest_review,
    latest_reviews_map,
    list_product_runs,
    log_product_event,
    open_factory_db as open_db,  # challenge 스키마 + factory 스키마 보장 (기존 라우트 동작은 동일)
)
from repo_idea_miner.factory_schemas import (
    PRODUCT_OWNER_DECISIONS,
    PRODUCT_VERDICT_LABELS,
    VERDICT_TO_RECOMMENDED_ACTION,
)
from repo_idea_miner.factory_summary import (
    GATE_KEYS,
    gate_pass_count,
    head_lines,
    load_gate_summary,
    load_product_summary,
    load_qa_summary,
)
from repo_idea_miner.redaction import redact_text

# 상세 화면에서 artifact_dir 내 이 파일들만 읽는다 (임의 경로 접근 금지)
_DETAIL_FILES = {
    "owner_brief": "owner_brief.md",
    "screen_story": "screen_story.md",
    "challenge_card": "challenge_card.md",
    "implementation_prompt": "implementation_prompt.md",
    "validation_report": "validation_report.json",
}

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

# Report Preview 탭 화이트리스트 (§23). 사용자는 key만 고르므로 임의 경로 접근이 불가능하다.
# ("final"=final_artifact_dir, "run"=run 디렉터리) 순서가 곧 탭 순서다.
_PRODUCT_REPORT_TABS = [
    ("readme", ("final", "README.md", "README.md")),
    ("run_instructions", ("final", "run_instructions.md", "run_instructions.md")),
    ("product_verdict", ("final", "product_verdict.md", "product_verdict.md")),
    ("qa_report", ("final", "reports/qa_report.md", "qa_report.md")),
    ("contract_report", ("final", "reports/contract_report.md", "contract_report.md")),
    ("syntax_report", ("final", "reports/syntax_report.md", "syntax_report.md")),
    ("smoke_report", ("final", "reports/smoke_report.md", "smoke_report.md")),
    ("manifest", ("final", "manifest.json", "manifest.json")),
    ("contract", ("final", "contract.json", "contract.json")),
    ("events", ("run", "events.jsonl", "events.jsonl")),
    ("debug_history", ("run", "debug_history.jsonl", "debug_history.jsonl")),
    ("product_summary", ("final", "product_summary.json", "product_summary.json")),
    ("gate_summary", ("final", "gate_summary.json", "gate_summary.json")),
    ("qa_summary", ("final", "qa_summary.json", "qa_summary.json")),
]
_PRODUCT_REPORT_TABS_MAP = dict(_PRODUCT_REPORT_TABS)

# 허용된 Source Preview 범위 (§22). final_artifact 안에서만, 이 루트/파일만 읽는다.
_SOURCE_PREVIEW_FILES = {"README.md", "run_instructions.md", "manifest.json", "contract.json"}
_SOURCE_PREVIEW_PREFIXES = ("src/", "reports/")

# preview 길이 제한 (§30 large file truncate)
_PREVIEW_MAX_BYTES = 60000

# run status / gate·qa status 화면용 한글/배지
_STATUS_KO = {"pending": "대기", "running": "진행 중", "done": "완료", "error": "에러"}
_GATE_STATUS_KO = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP", "UNKNOWN": "UNKNOWN"}

_VERDICT_KO = {
    "PROMOTE_TO_CODEX": "Codex 승격 후보",
    "KEEP_CANDIDATE": "보관 후보",
    "NEEDS_MORE_GEMMA_LOOP": "루프 더 필요",
    "TOO_WEAK": "너무 약함",
    "DROP": "버림",
}

_DECISION_KO = {
    "keep": "KEEP",
    "drop": "DROP",
    "productize": "PRODUCTIZE",
    "retry": "RETRY",
    "archive": "ARCHIVE",
}

# §15 verdict → 추천 버튼 강조용
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


# ---------------------------------------------------------------- 데이터 조회

_ORDER_SQL = (
    "ORDER BY CASE c.final_label "
    + " ".join(f"WHEN '{lab}' THEN {pri}" for lab, pri in LABEL_PRIORITY.items())
    + " ELSE 99 END, c.owner_clarity_score DESC, c.score_total DESC, c.created_at DESC"
)


def query_challenges(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    sql = (
        "SELECT c.*, COALESCE(r.owner_status, 'unseen') AS owner_status, r.note AS owner_note, "
        "repos.language AS language "
        "FROM challenges c "
        "LEFT JOIN owner_reviews r ON r.challenge_id = c.id "
        "LEFT JOIN repos ON repos.repo_url = c.repo_url WHERE 1=1"
    )
    args: list = []
    if filters.get("final_label"):
        sql += " AND c.final_label = ?"
        args.append(filters["final_label"])
    if filters.get("owner_status"):
        sql += " AND COALESCE(r.owner_status, 'unseen') = ?"
        args.append(filters["owner_status"])
    if filters.get("language"):
        sql += " AND repos.language = ?"
        args.append(filters["language"])
    if filters.get("created_date"):
        sql += " AND c.created_at LIKE ?"
        args.append(filters["created_date"] + "%")
    if filters.get("score_min"):
        sql += " AND c.score_total >= ?"
        args.append(int(filters["score_min"]))
    if filters.get("score_max"):
        sql += " AND c.score_total <= ?"
        args.append(int(filters["score_max"]))
    sql += f" {_ORDER_SQL} LIMIT 200"
    return [dict(r) for r in conn.execute(sql, args)]


def today_summary(conn: sqlite3.Connection) -> dict:
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = local_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    labels = {
        row["final_label"]: row["n"]
        for row in conn.execute(
            "SELECT final_label, COUNT(*) AS n FROM challenges WHERE created_at >= ? GROUP BY final_label",
            (since,),
        )
    }
    total = conn.execute("SELECT COUNT(*) FROM challenges WHERE created_at >= ?", (since,)).fetchone()[0]
    errors = conn.execute(
        "SELECT COUNT(*) FROM events WHERE timestamp >= ? AND event_type IN ('repo_error','llm_error','seed_error','validation_error')",
        (since,),
    ).fetchone()[0]
    counts = queue_counts(conn)
    keys = [dict(r) for r in conn.execute("SELECT * FROM api_keys ORDER BY key_id")]
    return {
        "today_total": total,
        "labels": labels,
        "errors": errors,
        "queue": counts,
        "keys": keys,
        "paused": is_paused(conn),
    }


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
    row = conn.execute(
        "SELECT c.*, COALESCE(r.owner_status,'unseen') AS owner_status, r.note AS owner_note "
        "FROM challenges c LEFT JOIN owner_reviews r ON r.challenge_id=c.id WHERE c.id=?",
        (challenge_id,),
    ).fetchone()
    if row is None:
        return None
    c = dict(row)
    tab = tab if tab in _DETAIL_FILES else "owner_brief"

    artifact_dir = Path(c.get("artifact_dir") or "")
    content = "(artifact 파일 없음)"
    target = artifact_dir / _DETAIL_FILES[tab]
    if artifact_dir.is_dir() and target.is_file():
        text = target.read_text(encoding="utf-8", errors="replace")
        if tab == "validation_report":
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                pass
        content = redact_text(text, secrets)

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
        p = artifact_dir / _DETAIL_FILES[key]
        if artifact_dir.is_dir() and p.is_file():
            raw = redact_text(p.read_text(encoding="utf-8", errors="replace"), secrets)
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
    label = _VERDICT_KO.get(v, "진행 중" if verdict is None else v)
    return f'<span class="badge v-{_e(v)}">{_e(label)}</span>'


def _status_badge(status: str | None) -> str:
    st = status or "pending"
    cls = st if st in ("done", "error", "running", "pending") else "pending"
    text = "ERROR" if st == "error" else _STATUS_KO.get(st, st)
    return f'<span class="sb sb-{cls}">{_e(text)}</span>'


def _review_badge(action: str | None) -> str:
    if not action:
        return '<span class="rb">미검수</span>'
    return f'<span class="rb rb-on">{_e(_DECISION_KO.get(action, action))}</span>'


def _run_root(run: dict) -> Path | None:
    """workspace_dir(run_dir/workspace)에서 run 디렉터리를 얻는다."""
    ws = run.get("workspace_dir")
    if not ws:
        return None
    return Path(ws).parent


def _product_dirs(run: dict) -> tuple[Path | None, Path | None]:
    final_dir = Path(run["final_artifact_dir"]) if run.get("final_artifact_dir") else None
    return final_dir, _run_root(run)


def _product_title(run: dict, psum: dict | None) -> str:
    """Challenge 제목 fallback (§12)."""
    return (
        run.get("challenge_title")
        or (psum or {}).get("challenge_title")
        or (f"Challenge #{run['challenge_id']}" if run.get("challenge_id") else None)
        or f"run #{run['id']}"
    )


def _overall_qa_status(qa: dict) -> str:
    vals = [qa.get("anchor_status"), qa.get("forbidden_status"), qa.get("core_interaction_status")]
    if "FAIL" in vals:
        return "FAIL"
    if "PARTIAL" in vals:
        return "PARTIAL"
    if vals and all(v == "PASS" for v in vals):
        return "PASS"
    return "UNKNOWN"


def _gate_pills(gate: dict) -> str:
    labels = {"static": "Static", "contract": "Contract", "syntax": "Syntax", "smoke": "Smoke"}
    out = []
    for key in GATE_KEYS:
        status = (gate.get(key) or {}).get("status", "UNKNOWN")
        out.append(
            f'<span class="gp gp-{_e(status)}"><span class="lbl">{labels[key]}</span>{_e(status)}</span>'
        )
    return '<div class="gaterow">' + "".join(out) + "</div>"


def _match_product_filters(run: dict, rev: dict | None, filters: dict) -> bool:
    verdict = filters.get("verdict")
    status = filters.get("status")
    review = (filters.get("review") or "").lower()
    if verdict and (run.get("verdict") or "") != verdict:
        return False
    if status and (run.get("status") or "") != status:
        return False
    if review == "unreviewed" and rev is not None:
        return False
    if review == "reviewed" and rev is None:
        return False
    if review in PRODUCT_OWNER_DECISIONS and (rev or {}).get("action") != review:
        return False
    return True


def _read_capped(path: Path, secrets: list[str]) -> str:
    """화이트리스트 파일을 크기 제한 안에서 읽고 secret을 마스킹한다 (§30)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "(읽기 실패)"
    truncated = len(raw) > _PREVIEW_MAX_BYTES
    text = raw[:_PREVIEW_MAX_BYTES].decode("utf-8", errors="replace")
    text = redact_text(text, secrets)
    if truncated:
        text += "\n… (길이 제한으로 잘림)"
    return text


def _safe_source_path(final_dir: Path | None, rel: str) -> Path | None:
    """source preview 요청 경로를 화이트리스트 루트로 제한한다 (§22·§30: 절대경로/../ 차단)."""
    if not final_dir or not rel:
        return None
    p = Path(rel)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        return None
    if not (rel in _SOURCE_PREVIEW_FILES or any(rel.startswith(pre) for pre in _SOURCE_PREVIEW_PREFIXES)):
        return None
    target = final_dir / p
    try:
        resolved = target.resolve()
    except OSError:
        return None
    if not str(resolved).startswith(str(final_dir.resolve())):
        return None
    return resolved if resolved.is_file() else None


def _source_files(final_dir: Path | None) -> list[str]:
    """source preview 대상 파일 목록 (final_artifact 안, 허용 루트만)."""
    if not final_dir or not final_dir.is_dir():
        return []
    out: list[str] = []
    for name in ("README.md", "run_instructions.md", "manifest.json", "contract.json"):
        if (final_dir / name).is_file():
            out.append(name)
    for p in sorted((final_dir / "src").rglob("*")) if (final_dir / "src").is_dir() else []:
        if p.is_file():
            out.append(p.relative_to(final_dir).as_posix())
    return out


def _final_tree(final_dir: Path | None, limit: int = 200) -> str:
    if not final_dir or not final_dir.is_dir():
        return "(final_artifact 없음)"
    lines = ["final_artifact/"]
    paths = sorted(p for p in final_dir.rglob("*") if p.is_file())
    for p in paths[:limit]:
        rel = p.relative_to(final_dir).as_posix()
        indent = "  " * (rel.count("/") + 1)
        lines.append(f"{indent}{p.name}")
    if len(paths) > limit:
        lines.append(f"  … (총 {len(paths)}개 중 {limit}개 표시)")
    return "\n".join(lines)


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
    for d, label in _DECISION_ACTIONS:
        cls = ("primary" if d == recommended else "") + (" on" if d == current else "")
        extra = ""
        if d in ("retry", "productize") and next_goal:
            extra = f'<input type="hidden" name="selected_next_goal" value="{_e(next_goal)}">'
        star = " (추천)" if d == recommended else ""
        out.append(
            f'<form method="post" action="/product/{run_id}/decision" style="display:inline">'
            f'<input type="hidden" name="decision" value="{d}">{extra}'
            f'<button type="submit" class="{cls.strip()}">{label}{star}</button></form>'
        )
    return "".join(out)


def _product_filter_chips(filters: dict) -> str:
    active = filters.get("verdict"), filters.get("status"), (filters.get("review") or "").lower()
    chips = [("전체", "/products", not any(active))]
    for lab in PRODUCT_VERDICT_LABELS:
        chips.append((lab, f"/products?verdict={lab}", filters.get("verdict") == lab))
    chips.append(("status=error", "/products?status=error", filters.get("status") == "error"))
    chips.append(("미검수", "/products?review=unreviewed", active[2] == "unreviewed"))
    chips.append(("검수완료", "/products?review=reviewed", active[2] == "reviewed"))
    chips.append(("RETRY", "/products?review=retry", active[2] == "retry"))
    chips.append(("PRODUCTIZE", "/products?review=productize", active[2] == "productize"))
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
  <h2 class="sec-h">Product Runs 요약</h2>
  <div class="sgrid">
    <div class="sitem"><span class="k">전체 run</span><span class="val">{len(all_runs)}건</span></div>
    <div class="sitem"><span class="k">Codex 승격</span><span class="val">{verdict_counts.get('PROMOTE_TO_CODEX', 0)}건</span></div>
    <div class="sitem"><span class="k">루프 더 필요</span><span class="val">{verdict_counts.get('NEEDS_MORE_GEMMA_LOOP', 0)}건</span></div>
    <div class="sitem"><span class="k">에러</span><span class="val">{error_n}건</span></div>
    <div class="sitem"><span class="k">미검수</span><span class="val">{unreviewed_n}건</span></div>
  </div>
</section>"""

    runs = [r for r in all_runs if _match_product_filters(r, reviews.get(r["id"]), filters)]
    cards = []
    for r in runs:
        final_dir, run_root = _product_dirs(r)
        psum = load_product_summary(final_dir, run_root)
        gate = load_gate_summary(final_dir, run_root)
        qa = load_qa_summary(final_dir, run_root)
        rev = reviews.get(r["id"])
        title = _product_title(r, psum)
        passed, total = gate_pass_count(gate)
        issue = (psum or {}).get("issue_summary") or (qa.get("issue_summary") or "-")
        next_goal = (psum or {}).get("next_goal") or qa.get("next_goal") or "-"
        recommended = (psum or {}).get("recommended_action") or VERDICT_TO_RECOMMENDED_ACTION.get(
            r.get("verdict") or "", "-"
        ).upper()
        cards.append(
            f"""  <article class="card">
    <div class="chead">
      <span class="repo"><a href="/product/{r['id']}">run #{r['id']}</a></span>
      {_verdict_badge(r.get('verdict'))}
      {_status_badge(r.get('status'))}
      {_review_badge((rev or {}).get('action'))}
    </div>
    <p class="title"><a href="/product/{r['id']}">{_e(title)}</a></p>
    <div class="issue"><span class="k">Issue</span> {_e(issue)}</div>
    <p class="meta">Gate {passed}/{total} PASS · QA {_e(_overall_qa_status(qa))}</p>
    <div class="issue"><span class="k">Next</span> {_e(next_goal)}</div>
    <p class="meta">추천 {_e(recommended)} · <a href="/product/{r['id']}">상세 보기 →</a></p>
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
    final_dir, run_root = _product_dirs(run)
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
    ch = None
    if run.get("challenge_id"):
        row = conn.execute(
            "SELECT id, challenge_title, repo_url FROM challenges WHERE id=?", (run["challenge_id"],)
        ).fetchone()
        if row:
            ch = dict(row)

    action_buttons = _action_buttons(run_id, recommended, rev_action, next_goal)

    # 1. Verdict Hero (§14)
    hero = f"""
<section class="summary">
  <div class="chead">
    <span class="repo">run #{run_id}</span>
    {_verdict_badge(verdict)}
    {_status_badge(status)}
    {_review_badge(rev_action)}
  </div>
  <p class="title">{_e(title)}</p>
  <p class="meta">추천 Action: <b>{_e((recommended or '-').upper())}</b> · 단계 {_e(run.get('current_stage') or '-')}
    · 라인 {_e(run.get('line') or '-')} · {_e((run.get('created_at') or '')[:19].replace('T', ' '))}</p>
  <div class="issue"><span class="k">이유</span> {_e(reason)}</div>
  <div class="actions" style="margin-top:12px">{action_buttons}</div>
</section>"""

    # 3. 원본 Challenge 요약 (§15)
    if ch or psum:
        anchors = (psum or {}).get("challenge_anchors") or []
        forbidden = (psum or {}).get("challenge_forbidden") or []
        brief = (psum or {}).get("owner_brief_summary") or "-"
        link = (
            f'<a href="/challenge/{ch["id"]}">원본 Challenge 상세 →</a>'
            if ch
            else '<span class="muted">원본 Challenge 정보 없음 (삭제되었거나 샘플 run)</span>'
        )
        ch_summary = f"""
<section class="panel">
  <h2 class="sec-h">원본 Challenge 요약</h2>
  <p class="meta">Challenge ID: {_e(run.get('challenge_id') if run.get('challenge_id') else '(없음)')}</p>
  <div class="field"><span class="k">Owner Brief</span>{_e(brief)}</div>
  <div class="field"><span class="k">Difficulty Anchors</span><ul class="evi">{''.join(f'<li>{_e(a)}</li>' for a in anchors) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">Forbidden Simplifications</span><ul class="evi">{''.join(f'<li>{_e(f)}</li>' for f in forbidden) or '<li class="muted">없음</li>'}</ul></div>
  <p class="meta">{link}</p>
</section>"""
    else:
        ch_summary = '<section class="panel"><h2 class="sec-h">원본 Challenge 요약</h2><p class="muted">원본 Challenge 정보 없음</p></section>'

    # 4. Gate Summary (§16)
    gate_html = f"""
<section class="panel">
  <h2 class="sec-h">Gate Summary</h2>
  {_gate_pills(gate)}
  <p class="meta">{_e('; '.join(f"{k}: {(gate.get(k) or {}).get('summary','')}" for k in GATE_KEYS)[:600])}</p>
</section>"""

    # 5. QA Summary (§17)
    evidence = qa.get("evidence") or []
    qa_html = f"""
<section class="panel">
  <h2 class="sec-h">QA Summary</h2>
  <p class="meta">Anchor: <b>{_e(qa.get('anchor_status'))}</b> · Forbidden: <b>{_e(qa.get('forbidden_status'))}</b>
    · Core Interaction: <b>{_e(qa.get('core_interaction_status'))}</b></p>
  <div class="issue"><span class="k">핵심 결함</span> {_e(qa.get('issue_summary') or '-')}</div>
  <div class="field"><span class="k">근거</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in evidence) or '<li class="muted">없음</li>'}</ul></div>
</section>"""

    # 6. Known Issues / Next Goal (§18)
    known = (psum or {}).get("known_issues") or []
    issues_html = f"""
<section class="panel">
  <h2 class="sec-h">Known Issues / Next Goal</h2>
  <div class="field"><span class="k">Known Issues</span><ul class="evi">{''.join(f'<li>{_e(x)}</li>' for x in known) or '<li class="muted">없음</li>'}</ul></div>
  <div class="field"><span class="k">Next Goal</span>{_e(next_goal or '없음')}</div>
</section>"""

    # 7. Smoke Output Preview (§19)
    smoke_html = f"""
<section class="panel">
  <h2 class="sec-h">Smoke Output Preview</h2>
  {_smoke_preview_html(gate.get('smoke') or {}, secrets)}
</section>"""

    # 8. Artifact Paths (§20)
    codex_dir = (psum or {}).get("codex_export_dir")
    paths_html = f"""
<section class="panel">
  <h2 class="sec-h">Artifact Paths</h2>
  <div class="field"><span class="k">workspace_dir</span><span class="kv">{_e(run.get('workspace_dir') or '-')}</span></div>
  <div class="field"><span class="k">final_artifact_dir</span><span class="kv">{_e(run.get('final_artifact_dir') or '(미생성)')}</span></div>
  <div class="field"><span class="k">codex_export_dir</span><span class="kv">{_e(codex_dir or '-')}</span></div>
</section>"""

    # 9. Final Artifact File Tree (§21)
    tree_html = f"""
<section class="panel">
  <h2 class="sec-h">Final Artifact File Tree</h2>
  <div class="tree">{_e(_final_tree(final_dir))}</div>
</section>"""

    # 10. 허용된 Source Preview (§22)
    src_files = _source_files(final_dir)
    src_links = "".join(
        f'<a href="/product/{run_id}?src={_e(f)}" class="{"active" if src == f else ""}">{_e(f)}</a>'
        for f in src_files
    )
    src_content = ""
    if src:
        sp = _safe_source_path(final_dir, src)
        if sp is not None:
            src_content = f'<section class="panel"><pre>{_e(_read_capped(sp, secrets))}</pre></section>'
        else:
            src_content = '<section class="panel"><p class="muted">허용되지 않은 경로이거나 파일이 없습니다.</p></section>'
    source_html = f"""
<section class="panel">
  <h2 class="sec-h">허용된 Source Preview</h2>
  <div class="tabs">{src_links or '<span class="muted">표시할 소스 파일 없음</span>'}</div>
</section>{src_content}"""

    # 11. Report Preview Tabs (§23)
    tab = tab if tab in _PRODUCT_REPORT_TABS_MAP else "product_verdict"
    base_kind, rel, _lbl = _PRODUCT_REPORT_TABS_MAP[tab]
    base = final_dir if base_kind == "final" else run_root
    report_content = "(파일 없음)"
    if base and base.is_dir() and (base / rel).is_file():
        report_content = _read_capped(base / rel, secrets)
    tabs = "".join(
        f'<a href="/product/{run_id}?tab={key}" class="{"active" if key == tab else ""}">{label}</a>'
        for key, (_, _, label) in _PRODUCT_REPORT_TABS
    )
    report_html = f"""
<section class="panel">
  <h2 class="sec-h">Report Preview</h2>
  <div class="tabs">{tabs}</div>
  <pre>{_e(report_content)}</pre>
</section>"""

    # 12. Action Buttons (하단, §29: 상단·하단 모두 배치)
    bottom_actions = f"""
<section class="panel">
  <h2 class="sec-h">내 판정 (최종 검수)</h2>
  <div class="actions">{action_buttons}</div>
</section>"""

    body = (
        _nav("product")
        + '<p class="back"><a href="/products">← Product Runs 목록으로</a></p>'
        + hero + ch_summary + gate_html + qa_html + issues_html
        + smoke_html + paths_html + tree_html + source_html + report_html + bottom_actions
    )
    return _page(f"제품 run #{run_id}", body)


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
                exists = conn.execute("SELECT 1 FROM challenges WHERE id=?", (challenge_id,)).fetchone()
                if not exists:
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
