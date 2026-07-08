# runs/<timestamp>/ 산출물을 모바일 우선 정적 viewer.html로 렌더링하는 모듈.
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from repo_idea_miner.config import load_settings
from repo_idea_miner.redaction import redact_text

# 정렬/필터가 참조하는 verdict 우선순위 (KEEP → MAYBE → DROP → ERROR)
_VERDICT_RANK = {"KEEP": 0, "MAYBE": 1, "DROP": 2, "ERROR": 3}

_FINAL_JSON = "debug/worker_outputs/critic_judge_final.json"


def detect_run_kind(run_dir: Path) -> str:
    if (run_dir / "top_ideas.md").exists() or (run_dir / "candidates.json").exists():
        return "search"
    return "single"


# ---------------------------------------------------------------------------
# run_report.md / idea_card.md 파싱 헬퍼
# ---------------------------------------------------------------------------
def _kv_block(text: str, header: str) -> dict[str, str]:
    """`## header` 아래의 `- key: value` 줄을 dict로 반환한다."""
    out: dict[str, str] = {}
    section = text.split(f"## {header}", 1)
    if len(section) < 2:
        return out
    for line in section[1].splitlines()[1:]:
        line = line.strip()
        if line.startswith("## "):
            break
        m = re.match(r"-\s*([^:]+):\s*(.*)", line)
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def _section_value(text: str, header: str) -> str | None:
    """`## header` 바로 다음 첫 비어있지 않은 줄을 반환한다 (단일 값 섹션용)."""
    section = text.split(f"## {header}", 1)
    if len(section) < 2:
        return None
    for line in section[1].splitlines()[1:]:
        if line.strip():
            return line.strip()
    return None


def parse_idea_card(text: str) -> dict:
    """idea_card.md를 카드 dict로 파싱한다 (critic_judge_final.json 부재 시 fallback)."""
    # `## 제목` 단위로 분해
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    repo_name: str | None = None
    for line in text.splitlines():
        if line.startswith("레포:"):
            repo_name = line.split(":", 1)[1].strip()
            continue
        if line.startswith("## "):
            current = line[3:].strip()
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)

    def scalar(title: str) -> str:
        for line in blocks.get(title, []):
            if line.strip():
                return line.strip()
        return ""

    def bullets(title: str) -> list[str]:
        items = []
        for line in blocks.get(title, []):
            s = line.strip()
            if s.startswith("- "):
                val = s[2:].strip()
                if val and val != "(없음)":
                    items.append(val)
        return items

    def kv(title: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in blocks.get(title, []):
            m = re.match(r"-\s*([^:]+):\s*(.*)", line.strip())
            if m:
                out[m.group(1).strip()] = m.group(2).strip()
        return out

    score_raw = scalar("점수")
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        score = None
    risk = kv("Dependency / Runtime Risk")
    mvp = kv("1일 MVP")
    poc = kv("1일 Pattern PoC")
    return {
        "repo": repo_name,
        "verdict": scalar("판정") or "ERROR",
        "score": score,
        "fast_drop": scalar("FAST DROP에 가까운가").upper() == "YES",
        "one_line_conclusion": scalar("한 줄 결론"),
        "why_people_cared": scalar("왜 사람들이 관심 가졌나"),
        "user_pain": bullets("실제 사용자 고통"),
        "feature_requests": bullets("기능 요청 신호"),
        "workflow_pain": bullets("워크플로우/자동화 신호"),
        "core_pattern": scalar("가져올 패턴"),
        "what_to_ignore": bullets("버릴 것"),
        "dependency_runtime_risk": {"level": risk.get("level"), "reason": risk.get("reason")},
        "one_day_mvp": mvp,
        "pattern_poc": poc,
        "why_it_fails": bullets("만들면 망하는 이유"),
        "why_drop_or_keep": bullets("왜 이 판정인가"),
        "next_action": scalar("다음 행동"),
    }


def _card_repo_name(card_md: Path) -> str | None:
    """idea_card.md의 `레포: owner/name` 라인에서 레포 이름을 읽는다."""
    if not card_md.exists():
        return None
    for line in card_md.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("레포:"):
            return line.split(":", 1)[1].strip()
    return None


def _run_error_reason(repo_dir: Path) -> str:
    """run_report.md의 Errors/Preflight에서 실패 사유를 추출한다."""
    report = repo_dir / "run_report.md"
    if not report.exists():
        return "산출물 없음 (분석 실패)"
    text = report.read_text(encoding="utf-8", errors="replace")
    section = text.split("## Errors", 1)
    if len(section) >= 2:
        for line in section[1].splitlines()[1:]:
            s = line.strip()
            if s.startswith("## "):
                break
            if s.startswith("- ") and s[2:].strip() not in ("", "(없음)"):
                return s[2:].strip()
    pf = _kv_block(text, "Preflight")
    return pf.get("reason") or "분석 실패"


def load_card(repo_dir: Path, repo_name: str | None = None, url: str | None = None,
              targeted_score: int | None = None) -> dict:
    """repo_dir에서 카드 dict를 만든다. 우선순위: critic_judge_final.json → idea_card.md → ERROR."""
    final = repo_dir / _FINAL_JSON
    card: dict
    if final.exists():
        try:
            card = json.loads(final.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            card = {}
        if card.get("verdict"):
            card.setdefault("repo", repo_name)
            card["url"] = url
            card["targeted_score"] = targeted_score
            return card
    card_md = repo_dir / "idea_card.md"
    if card_md.exists():
        parsed = parse_idea_card(card_md.read_text(encoding="utf-8", errors="replace"))
        parsed["repo"] = parsed.get("repo") or repo_name
        parsed["url"] = url
        parsed["targeted_score"] = targeted_score
        return parsed
    # 카드 자체가 없으면 크래시 대신 ERROR 카드
    return {
        "repo": repo_name,
        "url": url,
        "verdict": "ERROR",
        "score": None,
        "fast_drop": False,
        "one_line_conclusion": _run_error_reason(repo_dir),
        "error": _run_error_reason(repo_dir),
        "targeted_score": targeted_score,
    }


# ---------------------------------------------------------------------------
# 모델 빌더
# ---------------------------------------------------------------------------
def build_single_model(run_dir: Path) -> dict:
    report_text = ""
    report = run_dir / "run_report.md"
    if report.exists():
        report_text = report.read_text(encoding="utf-8", errors="replace")
    inp = _kv_block(report_text, "Input")
    card = load_card(run_dir)
    repo_name = card.get("repo") or _card_repo_name(run_dir / "idea_card.md") or inp.get("repo")
    card["repo"] = repo_name
    if not card.get("url") and inp.get("repo", "").startswith("http"):
        card["url"] = inp.get("repo")
    summary = {
        "repo": repo_name or "(알 수 없음)",
        "verdict": card.get("verdict"),
        "score": card.get("score"),
        "fast_drop": card.get("fast_drop"),
        "mode": inp.get("mode"),
        "input_mode": inp.get("input_mode"),
        "timestamp": inp.get("timestamp") or run_dir.name,
        "secret_scan": _section_value(report_text, "Secret Redaction"),
        "validation": _section_value(report_text, "JSON Validation"),
    }
    return {"kind": "single", "summary": summary, "cards": [card]}


def build_search_model(run_dir: Path) -> dict:
    candidates = []
    cand_path = run_dir / "candidates.json"
    if cand_path.exists():
        try:
            candidates = json.loads(cand_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            candidates = []

    from repo_idea_miner.search_pipeline import _safe_name

    cards: list[dict] = []
    for order, cand in enumerate(candidates):
        full_name = cand.get("full_name")
        safe = _safe_name(full_name or "")
        repo_dir = run_dir / "repos" / safe
        card = load_card(
            repo_dir,
            repo_name=full_name,
            url=cand.get("url"),
            targeted_score=cand.get("targeted_score"),
        )
        # repos/ 가 없거나 카드를 못 찾으면 cards/<safe>_idea_card.md 복사본으로 fallback
        if card.get("verdict") == "ERROR":
            card_copy = run_dir / "cards" / f"{safe}_idea_card.md"
            if card_copy.exists():
                parsed = parse_idea_card(card_copy.read_text(encoding="utf-8", errors="replace"))
                parsed["repo"] = parsed.get("repo") or full_name
                parsed["url"] = cand.get("url")
                parsed["targeted_score"] = cand.get("targeted_score")
                card = parsed
        card["order"] = order
        cards.append(card)

    report_text = ""
    report = run_dir / "search_report.md"
    if report.exists():
        report_text = report.read_text(encoding="utf-8", errors="replace")
    query = _section_value(report_text, "Query") or ""

    counts = {"KEEP": 0, "MAYBE": 0, "DROP": 0, "ERROR": 0}
    for c in cards:
        counts[c.get("verdict") if c.get("verdict") in counts else "ERROR"] += 1
    has_targeted = any(c.get("targeted_score") is not None for c in cards)

    summary = {
        "query": query,
        "analyzed": len(cards),
        "keep": counts["KEEP"],
        "maybe": counts["MAYBE"],
        "drop": counts["DROP"],
        "error": counts["ERROR"],
        "secret_scan": _section_value(report_text, "Secret Redaction") or _search_secret_status(run_dir),
        "validation": _search_validation_status(run_dir),
        "has_targeted": has_targeted,
    }
    return {"kind": "search", "summary": summary, "cards": cards}


def _search_secret_status(run_dir: Path) -> str | None:
    """search_report에 Secret 섹션이 없으면 per-repo run_report에서 집계한다."""
    statuses = []
    for report in (run_dir / "repos").glob("*/run_report.md"):
        v = _section_value(report.read_text(encoding="utf-8", errors="replace"), "Secret Redaction")
        if v:
            statuses.append(v)
    if not statuses:
        return None
    return "PASS" if all(s == "PASS" for s in statuses) else "FAIL"


def _search_validation_status(run_dir: Path) -> str | None:
    statuses = []
    for report in (run_dir / "repos").glob("*/run_report.md"):
        v = _section_value(report.read_text(encoding="utf-8", errors="replace"), "JSON Validation")
        if v:
            statuses.append(v)
    if not statuses:
        return None
    # 하나라도 FAIL이면 후보 분석 중 실패가 있었다는 뜻 (ERROR 카드로 표시됨)
    if any(s == "FAIL" for s in statuses):
        return "PARTIAL"
    return "PASS"


def build_model(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    if detect_run_kind(run_dir) == "search":
        return build_search_model(run_dir)
    return build_single_model(run_dir)


# ---------------------------------------------------------------------------
# HTML 렌더링
# ---------------------------------------------------------------------------
def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _bullet_list(items: list | None) -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return '<p class="muted">(없음)</p>'
    lis = "".join(f"<li>{_e(i)}</li>" for i in items)
    return f"<ul>{lis}</ul>"


def _kv_lines(d: dict | None, keys: list[tuple[str, str]]) -> str:
    d = d or {}
    rows = []
    for key, label in keys:
        val = d.get(key)
        if val in (None, "", []):
            continue
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val)
        rows.append(f"<div><span class='k'>{_e(label)}</span> {_e(val)}</div>")
    return "".join(rows) or '<p class="muted">(없음)</p>'


def _verdict_badge(verdict: str | None) -> str:
    v = (verdict or "ERROR").upper()
    return f'<span class="badge v-{_e(v)}">{_e(v)}</span>'


def _card_html(card: dict) -> str:
    verdict = (card.get("verdict") or "ERROR").upper()
    score = card.get("score")
    score_val = score if isinstance(score, int) else -1
    targeted = card.get("targeted_score")
    targeted_attr = targeted if isinstance(targeted, int) else ""
    repo = card.get("repo") or "(알 수 없음)"
    url = card.get("url")
    repo_html = f'<a href="{_e(url)}" target="_blank" rel="noopener">{_e(repo)}</a>' if url else _e(repo)

    score_chip = f'<span class="score">score {_e(score)}</span>' if isinstance(score, int) else ""
    targeted_chip = (
        f'<span class="chip">targeted {_e(targeted)}</span>' if isinstance(targeted, int) else ""
    )

    if verdict == "ERROR":
        detail = f'<p class="err">오류: {_e(card.get("error") or card.get("one_line_conclusion"))}</p>'
        expanded = ""
    else:
        detail = f'<p class="concl">{_e(card.get("one_line_conclusion"))}</p>'
        risk = card.get("dependency_runtime_risk") or {}
        expanded = f"""
    <details>
      <summary>상세 보기</summary>
      <div class="exp">
        <h4>실제 사용자 고통</h4>{_bullet_list(card.get("user_pain"))}
        <h4>기능 요청 신호</h4>{_bullet_list(card.get("feature_requests"))}
        <h4>워크플로우/자동화 신호</h4>{_bullet_list(card.get("workflow_pain"))}
        <h4>버릴 것</h4>{_bullet_list(card.get("what_to_ignore"))}
        <h4>Dependency / Runtime Risk</h4>
        {_kv_lines(risk, [("level", "level"), ("reason", "reason")])}
        <h4>1일 MVP</h4>
        {_kv_lines(card.get("one_day_mvp"), [("status", "status"), ("feature", "feature"), ("input", "input"), ("output", "output"), ("excluded_scope", "제외"), ("reason", "reason")])}
        <h4>1일 Pattern PoC</h4>
        {_kv_lines(card.get("pattern_poc"), [("status", "status"), ("idea", "idea"), ("input", "input"), ("output", "output"), ("reason", "reason")])}
        <h4>왜 실패할 수 있는가</h4>{_bullet_list(card.get("why_it_fails"))}
        <h4>왜 이 판정인가</h4>{_bullet_list(card.get("why_drop_or_keep"))}
      </div>
    </details>"""

    core = card.get("core_pattern")
    next_action = card.get("next_action")
    basic = ""
    if verdict != "ERROR":
        if core:
            basic += f'<p class="row"><span class="k">핵심 패턴</span> {_e(core)}</p>'
        if next_action:
            basic += f'<p class="row"><span class="k">다음 행동</span> {_e(next_action)}</p>'

    return f"""  <article class="card" data-verdict="{_e(verdict)}" data-score="{score_val}" data-targeted="{targeted_attr}" data-order="{card.get('order', 0)}">
    <div class="chead">
      <span class="repo">{repo_html}</span>
      {_verdict_badge(verdict)}{score_chip}{targeted_chip}
    </div>
    {detail}
    {basic}{expanded}
  </article>"""


def _single_summary_html(s: dict) -> str:
    rows = [
        ("레포", s.get("repo")),
        ("판정", s.get("verdict")),
        ("점수", s.get("score")),
        ("FAST DROP", "YES" if s.get("fast_drop") else "NO"),
        ("mode", s.get("mode")),
        ("input_mode", s.get("input_mode")),
        ("timestamp", s.get("timestamp")),
        ("secret scan", s.get("secret_scan")),
        ("validation", s.get("validation")),
    ]
    items = "".join(
        f"<div class='sitem'><span class='k'>{_e(k)}</span><span class='val'>{_e(v)}</span></div>"
        for k, v in rows
    )
    return f'<section class="summary">{_verdict_badge(s.get("verdict"))}<div class="sgrid">{items}</div></section>'


def _search_summary_html(s: dict) -> str:
    rows = [
        ("검색어", s.get("query")),
        ("분석 후보", s.get("analyzed")),
        ("KEEP", s.get("keep")),
        ("MAYBE", s.get("maybe")),
        ("DROP", s.get("drop")),
        ("ERROR", s.get("error")),
        ("secret scan", s.get("secret_scan")),
        ("validation", s.get("validation")),
    ]
    items = "".join(
        f"<div class='sitem'><span class='k'>{_e(k)}</span><span class='val'>{_e(v)}</span></div>"
        for k, v in rows
    )
    return f'<section class="summary"><div class="sgrid">{items}</div></section>'


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 17px; line-height: 1.5; background: #f4f5f7; color: #1c1c1e; -webkit-text-size-adjust: 100%; }
.wrap { max-width: 720px; margin: 0 auto; padding: 16px 14px 64px; }
h1 { font-size: 1.35rem; margin: 4px 0 14px; }
.summary { background: #fff; border-radius: 14px; padding: 14px; margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.sgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; margin-top: 8px; }
.sitem { display: flex; flex-direction: column; }
.sitem .k { font-size: .72rem; color: #6b7280; text-transform: none; }
.sitem .val { font-weight: 600; word-break: break-word; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.controls button, .controls select {
  font-size: .95rem; padding: 9px 14px; border-radius: 999px; border: 1px solid #d1d5db;
  background: #fff; color: #1c1c1e; min-height: 40px; cursor: pointer; }
.controls button.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.controls select { flex: 1 1 100%; border-radius: 12px; }
.card { background: #fff; border-radius: 14px; padding: 14px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.chead { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
.repo { font-weight: 700; font-size: 1.05rem; word-break: break-all; flex: 1 1 auto; }
.repo a { color: #2563eb; text-decoration: none; }
.badge { font-size: .78rem; font-weight: 700; padding: 3px 10px; border-radius: 999px; color: #fff; }
.v-KEEP { background: #16a34a; } .v-MAYBE { background: #d97706; }
.v-DROP { background: #6b7280; } .v-ERROR { background: #dc2626; }
.score { font-size: .8rem; font-weight: 600; color: #374151; background: #eef2ff; padding: 3px 9px; border-radius: 999px; }
.chip { font-size: .72rem; color: #6b7280; background: #f3f4f6; padding: 3px 8px; border-radius: 999px; }
.concl { margin: 6px 0; }
.err { margin: 6px 0; color: #b91c1c; }
.row { margin: 6px 0; }
.row .k, .k { font-size: .72rem; color: #6b7280; margin-right: 4px; }
details { margin-top: 8px; border-top: 1px solid #eceef1; padding-top: 8px; }
summary { cursor: pointer; font-weight: 600; color: #2563eb; padding: 6px 0; min-height: 32px; }
.exp h4 { margin: 12px 0 4px; font-size: .9rem; }
.exp ul { margin: 4px 0; padding-left: 20px; }
.exp .k { display: inline-block; min-width: 64px; }
.muted { color: #9ca3af; margin: 4px 0; }
.count { color: #6b7280; font-size: .85rem; margin: 0 0 12px; }
@media (prefers-color-scheme: dark) {
  body { background: #000; color: #f2f2f7; }
  .summary, .card { background: #1c1c1e; box-shadow: none; border: 1px solid #2c2c2e; }
  .controls button, .controls select { background: #1c1c1e; color: #f2f2f7; border-color: #3a3a3c; }
  .controls button.active { background: #2563eb; border-color: #2563eb; }
  .sitem .k, .row .k, .k { color: #98989f; }
  .score { background: #2c2c40; color: #d5d9ff; }
  .chip { background: #2c2c2e; color: #98989f; }
  .repo a { color: #6ea8fe; }
  details { border-color: #2c2c2e; }
}
"""

_JS = """
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var list = document.getElementById('cards');
  var countEl = document.getElementById('count');
  var state = { filter: 'ALL', sort: 'score' };

  function apply() {
    var shown = 0;
    cards.forEach(function (c) {
      var v = c.getAttribute('data-verdict');
      var ok = true;
      if (state.filter === 'HIDE_DROP') ok = (v !== 'DROP');
      else if (state.filter !== 'ALL') ok = (v === state.filter);
      c.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    if (countEl) countEl.textContent = shown + '개 표시';

    var rank = { KEEP: 0, MAYBE: 1, DROP: 2, ERROR: 3 };
    var sorted = cards.slice().sort(function (a, b) {
      if (state.sort === 'order')
        return (+a.getAttribute('data-order')) - (+b.getAttribute('data-order'));
      if (state.sort === 'verdict') {
        var d = rank[a.getAttribute('data-verdict')] - rank[b.getAttribute('data-verdict')];
        if (d !== 0) return d;
        return (+b.getAttribute('data-score')) - (+a.getAttribute('data-score'));
      }
      if (state.sort === 'targeted')
        return (+ (b.getAttribute('data-targeted') || -1)) - (+ (a.getAttribute('data-targeted') || -1));
      return (+b.getAttribute('data-score')) - (+a.getAttribute('data-score'));
    });
    sorted.forEach(function (c) { list.appendChild(c); });
  }

  document.querySelectorAll('[data-filter]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      state.filter = btn.getAttribute('data-filter');
      document.querySelectorAll('[data-filter]').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      apply();
    });
  });
  var sel = document.getElementById('sort');
  if (sel) sel.addEventListener('change', function () { state.sort = sel.value; apply(); });
  apply();
})();
"""


def _controls_html(has_targeted: bool) -> str:
    filters = [
        ("ALL", "전체"),
        ("KEEP", "KEEP"),
        ("MAYBE", "MAYBE"),
        ("DROP", "DROP"),
        ("ERROR", "ERROR"),
        ("HIDE_DROP", "DROP 숨기기"),
    ]
    btns = "".join(
        '<button data-filter="{f}"{cls}>{label}</button>'.format(
            f=f, cls=' class="active"' if f == "ALL" else "", label=_e(label)
        )
        for f, label in filters
    )
    sorts = [
        ("score", "점수 높은 순"),
        ("verdict", "KEEP→MAYBE→DROP 순"),
        ("order", "원래 분석 순서"),
    ]
    if has_targeted:
        sorts.append(("targeted", "targeted_score 높은 순"))
    opts = "".join(f'<option value="{v}">{_e(label)}</option>' for v, label in sorts)
    return f"""<div class="controls">{btns}</div>
<div class="controls"><select id="sort" aria-label="정렬">{opts}</select></div>
<p class="count" id="count"></p>"""


def render_viewer_html(model: dict) -> str:
    kind = model["kind"]
    summary = model["summary"]
    cards = model["cards"]
    cards_html = "\n".join(_card_html(c) for c in cards)

    if kind == "single":
        title = f"RIM · {summary.get('repo')}"
        header = _single_summary_html(summary)
        controls = ""  # 단일 카드는 필터/정렬 불필요
    else:
        title = "RIM · 검색 결과"
        header = _search_summary_html(summary)
        controls = _controls_html(summary.get("has_targeted", False))

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
<h1>{_e(title)}</h1>
{header}
{controls}
<div id="cards">
{cards_html}
</div>
</div>
<script>{_JS}</script>
</body>
</html>
"""


def generate_viewer(run_dir: str | Path) -> Path:
    """viewer.html을 생성한다. secret redaction을 거쳐 기록한다."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run 디렉터리가 아님: {run_dir}")
    model = build_model(run_dir)
    html_text = render_viewer_html(model)
    settings = load_settings()
    html_text = redact_text(html_text, settings.secret_values())
    out = run_dir / "viewer.html"
    out.write_text(html_text, encoding="utf-8")
    return out
