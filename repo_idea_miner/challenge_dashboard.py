# challenge.db를 읽어 Challenge 목록/상세/판정(SAVE·MAYBE·DROP·BUILD NEXT)을 제공하는 로컬 대시보드.
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from repo_idea_miner.challenge_db import is_paused, open_db, queue_counts, set_owner_review
from repo_idea_miner.challenge_schemas import CHALLENGE_LABELS, LABEL_PRIORITY, OWNER_STATUSES
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
.ostatus { font-size: .8rem; font-weight: 700; padding: 4px 12px; border-radius: 999px;
  background: #e5e7eb; color: #374151; white-space: nowrap; }
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
  .ostatus { background: #2c2c2e; color: #d1d5db; }
  .repo, .repo a, .meta, .muted, .count, form.filters label { color: #98989f; }
  .back a { color: #6ea8fe; }
  .tabs a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
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
    body = summary + filter_form + count_line + (
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
