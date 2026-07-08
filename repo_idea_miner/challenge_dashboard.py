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
    ("saved", "SAVE"),
    ("maybe", "MAYBE"),
    ("dropped", "DROP"),
    ("build_next", "BUILD NEXT"),
    ("built", "MARK BUILT"),
]

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 16px; line-height: 1.5; background: #f4f5f7; color: #1c1c1e; }
.wrap { max-width: 860px; margin: 0 auto; padding: 16px 14px 64px; }
h1 { font-size: 1.3rem; margin: 4px 0 14px; }
h1 a { color: inherit; text-decoration: none; }
.summary, .card, .panel { background: #fff; border-radius: 14px; padding: 14px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.sgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px 12px; }
.sitem { display: flex; flex-direction: column; }
.sitem .k { font-size: .72rem; color: #6b7280; }
.sitem .val { font-weight: 700; }
form.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
form.filters select, form.filters input, form.filters button {
  font-size: .9rem; padding: 8px 10px; border-radius: 10px; border: 1px solid #d1d5db; background: #fff; color: inherit; }
.badge { font-size: .72rem; font-weight: 700; padding: 3px 10px; border-radius: 999px; color: #fff; }
.l-GOOD_CHALLENGE { background: #16a34a; } .l-STEAL_ONLY { background: #7c3aed; }
.l-NOT_MY_TASTE { background: #d97706; } .l-TOO_BIG { background: #0891b2; }
.l-UNCLEAR_TO_OWNER { background: #db2777; } .l-TOO_EASY { background: #6b7280; }
.l-DROP { background: #374151; }
.ostatus { font-size: .72rem; font-weight: 700; padding: 3px 10px; border-radius: 999px;
  background: #e5e7eb; color: #374151; }
.chead { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.repo { font-weight: 700; word-break: break-all; flex: 1 1 auto; }
.repo a { color: #2563eb; text-decoration: none; }
.title { font-weight: 700; margin: 6px 0 2px; }
.muted { color: #6b7280; font-size: .85rem; }
.score { font-size: .8rem; font-weight: 600; background: #eef2ff; color: #374151; padding: 3px 9px; border-radius: 999px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.actions button { font-size: .85rem; padding: 8px 12px; border-radius: 10px; border: 1px solid #d1d5db;
  background: #fff; color: inherit; cursor: pointer; }
.actions button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
pre { white-space: pre-wrap; word-break: break-word; background: #f3f4f6; border-radius: 10px;
  padding: 12px; font-size: .85rem; overflow-x: auto; }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
.tabs a { font-size: .85rem; padding: 7px 12px; border-radius: 999px; border: 1px solid #d1d5db;
  text-decoration: none; color: inherit; }
.tabs a.active { background: #2563eb; color: #fff; border-color: #2563eb; }
textarea { width: 100%; border-radius: 10px; border: 1px solid #d1d5db; padding: 8px; font: inherit; }
@media (prefers-color-scheme: dark) {
  body { background: #000; color: #f2f2f7; }
  .summary, .card, .panel { background: #1c1c1e; box-shadow: none; border: 1px solid #2c2c2e; }
  form.filters select, form.filters input, form.filters button, .actions button
    { background: #1c1c1e; border-color: #3a3a3c; color: #f2f2f7; }
  .actions button.primary { background: #2563eb; border-color: #2563eb; }
  pre { background: #2c2c2e; }
  .ostatus { background: #2c2c2e; color: #d1d5db; }
  .repo a { color: #6ea8fe; }
  .tabs a { border-color: #3a3a3c; }
}
"""

_COPY_JS = """
function copyText(id, btn) {
  var el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(function () {
    var old = btn.textContent; btn.textContent = 'COPIED';
    setTimeout(function () { btn.textContent = old; }, 1200);
  });
}
"""


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def _label_badge(label: str | None) -> str:
    lab = label or "DROP"
    return f'<span class="badge l-{_e(lab)}">{_e(lab)}</span>'


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
<h1><a href="/">RIM Challenge Dashboard</a></h1>
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
    key_line = ", ".join(f"{k['key_id']}:{k['status']}" for k in s["keys"]) or "(등록된 key 없음)"
    summary = f"""
<section class="summary">
  <div class="sgrid">
    <div class="sitem"><span class="k">오늘 생성</span><span class="val">{s['today_total']}</span></div>
    <div class="sitem"><span class="k">GOOD_CHALLENGE</span><span class="val">{labels.get('GOOD_CHALLENGE', 0)}</span></div>
    <div class="sitem"><span class="k">STEAL_ONLY</span><span class="val">{labels.get('STEAL_ONLY', 0)}</span></div>
    <div class="sitem"><span class="k">TOO_EASY</span><span class="val">{labels.get('TOO_EASY', 0)}</span></div>
    <div class="sitem"><span class="k">DROP</span><span class="val">{labels.get('DROP', 0)}</span></div>
    <div class="sitem"><span class="k">에러</span><span class="val">{s['errors']}</span></div>
    <div class="sitem"><span class="k">처리 중</span><span class="val">{s['queue']['in_progress']}</span></div>
    <div class="sitem"><span class="k">대기 중</span><span class="val">{s['queue']['queued']}</span></div>
    <div class="sitem"><span class="k">miner</span><span class="val">{'PAUSED' if s['paused'] else 'RUNNING'}</span></div>
  </div>
  <p class="muted">keys: {_e(key_line)}</p>
</section>"""

    label_opts = '<option value="">final_label</option>' + "".join(
        f'<option value="{lab}"{" selected" if filters.get("final_label") == lab else ""}>{lab}</option>'
        for lab in CHALLENGE_LABELS
    )
    status_opts = '<option value="">owner_status</option>' + "".join(
        f'<option value="{st}"{" selected" if filters.get("owner_status") == st else ""}>{st}</option>'
        for st in OWNER_STATUSES
    )
    filter_form = f"""
<form class="filters" method="get" action="/">
  <select name="final_label">{label_opts}</select>
  <select name="owner_status">{status_opts}</select>
  <input name="language" placeholder="language" value="{_e(filters.get('language') or '')}">
  <input name="created_date" placeholder="YYYY-MM-DD" value="{_e(filters.get('created_date') or '')}">
  <input name="score_min" placeholder="score ≥" size="6" value="{_e(filters.get('score_min') or '')}">
  <input name="score_max" placeholder="score ≤" size="6" value="{_e(filters.get('score_max') or '')}">
  <button type="submit">필터</button>
  <a href="/?owner_status=build_next" style="align-self:center">BUILD NEXT만</a>
</form>"""

    rows = query_challenges(conn, filters)
    cards = []
    for c in rows:
        cards.append(
            f"""  <article class="card">
    <div class="chead">
      <span class="repo"><a href="/challenge/{c['id']}">{_e(_repo_name(c))}</a></span>
      {_label_badge(c['final_label'])}
      <span class="ostatus">{_e(c['owner_status'])}</span>
      <span class="score">clarity {_e(c['owner_clarity_score'])} · score {_e(c['score_total'])}</span>
    </div>
    <p class="title">{_e(c['challenge_title'])}</p>
    <p>{_e(c['one_line_challenge'])}</p>
    <p class="muted">{_e(c.get('language') or '')} · {_e((c.get('created_at') or '')[:10])}</p>
  </article>"""
        )
    body = summary + filter_form + (
        "\n".join(cards) if cards else '<p class="muted">표시할 challenge가 없습니다.</p>'
    )
    return _page("RIM Challenge Dashboard", body)


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
        for key, label in [
            ("owner_brief", "Owner Brief"),
            ("screen_story", "Screen Story"),
            ("challenge_card", "Challenge Card"),
            ("implementation_prompt", "Implementation Prompt"),
            ("validation_report", "Validation Report"),
        ]
    )

    action_buttons = "".join(
        f"""<form method="post" action="/challenge/{challenge_id}/review" style="display:inline">
<input type="hidden" name="owner_status" value="{st}">
<button type="submit" class="{'primary' if st == 'build_next' else ''}">{label}</button></form>"""
        for st, label in _STATUS_ACTIONS
    )

    # 복사 버튼용 원문 (implementation prompt / challenge card md)
    copy_sources = ""
    copy_buttons = ""
    for key, btn_label in (("implementation_prompt", "COPY IMPLEMENTATION PROMPT"), ("challenge_card", "COPY CHALLENGE CARD")):
        p = artifact_dir / _DETAIL_FILES[key]
        if artifact_dir.is_dir() and p.is_file():
            raw = redact_text(p.read_text(encoding="utf-8", errors="replace"), secrets)
            copy_sources += f'<pre id="copy-{key}" style="display:none">{_e(raw)}</pre>'
            copy_buttons += f'<button type="button" onclick="copyText(\'copy-{key}\', this)">{btn_label}</button>'

    body = f"""
<section class="summary">
  <div class="chead">
    <span class="repo"><a href="{_e(c.get('repo_url'))}" target="_blank" rel="noopener">{_e(_repo_name(c))}</a></span>
    {_label_badge(c['final_label'])}
    <span class="ostatus">{_e(c['owner_status'])}</span>
    <span class="score">clarity {_e(c['owner_clarity_score'])} · score {_e(c['score_total'])}</span>
  </div>
  <p class="title">{_e(c['challenge_title'])}</p>
  <p>{_e(c['one_line_challenge'])}</p>
</section>
<section class="panel">
  <div class="actions">{action_buttons}{copy_buttons}</div>
  <form method="post" action="/challenge/{challenge_id}/review" style="margin-top:10px">
    <input type="hidden" name="owner_status" value="{_e(c['owner_status'])}">
    <textarea name="note" rows="2" placeholder="note">{_e(c.get('owner_note') or '')}</textarea>
    <div class="actions"><button type="submit">노트 저장</button></div>
  </form>
</section>
<div class="tabs">{tabs}</div>
<section class="panel"><pre>{_e(content)}</pre></section>
{copy_sources}
"""
    return _page(f"Challenge #{challenge_id}", body)


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
