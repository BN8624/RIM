# ChallengePackage JSON을 owner_brief/screen_story/challenge_card/implementation_prompt.md와 viewer.html로 렌더링하는 모듈.
from __future__ import annotations

import html

# challenge_card.md 필수 섹션 (§14) — validate에서 사용한다.
CHALLENGE_CARD_SECTIONS = [
    "## Source Repo",
    "## One-line Challenge",
    "## What Makes The Original Interesting",
    "## Surface Features",
    "## Core Interaction",
    "## Difficulty Anchors",
    "## Forbidden Simplifications",
    "## Allowed Simplifications",
    "## 30-Minute PoC",
    "## 1-Day Build",
    "## 3-Day Expansion",
    "## Pass Criteria",
    "## Failure Criteria",
    "## Taste Risk",
    "## Final Label",
]

OWNER_BRIEF_SECTIONS = [
    "## 이게 쉽게 말해 뭐냐",
    "## 사람들이 왜 좋아하냐",
    "## 우리가 훔칠 핵심은 뭐냐",
    "## 화면에서 어떻게 보이냐",
    "## 사용자는 뭘 누르냐",
    "## 이걸 만들면 뭐가 재밌거나 쓸모 있냐",
    "## 그냥 쉬운 버전과 뭐가 다르냐",
    "## 바이브코더가 이해하기 어려운 지점",
]

SCREEN_STORY_SECTIONS = [
    "## 첫 화면",
    "## 사용자 행동",
    "## 30초 데모",
    "## 성공했을 때 느낌",
    "## 실패한 화면",
]


def _bullets(items: list | None) -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return "- (없음)"
    return "\n".join(f"- {i}" for i in items)


def render_owner_brief_md(brief: dict) -> str:
    g = brief.get
    return f"""# Owner Brief

레포: {g('source_repo')}

## 이게 쉽게 말해 뭐냐
{g('what_is_this')}

## 사람들이 왜 좋아하냐
{g('why_people_like_it')}

## 우리가 훔칠 핵심은 뭐냐
{g('what_we_steal')}

## 화면에서 어떻게 보이냐
{g('what_screen_looks_like')}

## 사용자는 뭘 누르냐
{_bullets(g('what_user_does'))}

## 이걸 만들면 뭐가 재밌거나 쓸모 있냐
{g('why_it_might_be_fun_or_useful')}

## 그냥 쉬운 버전과 뭐가 다르냐
{g('how_it_differs_from_easy_version')}

## 바이브코더가 이해하기 어려운 지점
{g('owner_clarity_risk') or '(없음)'}

## Owner Clarity Score
{g('owner_clarity_score')} / 5
"""


def render_screen_story_md(story: dict) -> str:
    g = story.get
    return f"""# Screen Story

## 첫 화면
{g('first_screen')}

## 사용자 행동
{_bullets(g('user_actions'))}

## 30초 데모
{g('thirty_second_demo')}

## 성공했을 때 느낌
{g('success_feeling')}

## 실패한 화면
{g('failure_screen')}
"""


def render_challenge_card_md(card: dict) -> str:
    g = card.get
    core = g("core_interaction") or {}
    scores = g("scores") or {}
    score_lines = "\n".join(f"- {k}: {v}" for k, v in scores.items())
    return f"""# Challenge Card

## Source Repo
{g('source_repo')}

## One-line Challenge
{g('one_line_challenge')}

## Challenge Title
{g('challenge_title')}

## What Makes The Original Interesting
{g('repo_summary')}

## Surface Features
{_bullets(g('surface_features'))}

## Core Interaction
- actor: {core.get('actor')}
- trigger: {core.get('trigger')}
- loop: {core.get('loop')}
- reward: {core.get('reward')}
- state_change: {core.get('state_change')}
- hard_part: {core.get('hard_part')}

## Difficulty Anchors
{_bullets(g('difficulty_anchors'))}

## Forbidden Simplifications
{_bullets(g('forbidden_simplifications'))}

## Allowed Simplifications
{_bullets(g('allowed_simplifications'))}

## 30-Minute PoC
{g('poc_30_min')}

## 1-Day Build
{g('build_1_day')}

## 3-Day Expansion
{g('expansion_3_day')}

## Pass Criteria
{_bullets(g('pass_criteria'))}

## Failure Criteria
{_bullets(g('failure_criteria'))}

## Scores
{score_lines}

## Taste Risk
{g('taste_risk') or '(없음)'}

## Final Label
{g('final_label')}
"""


def render_implementation_prompt_md(card: dict) -> str:
    """challenge_card.json의 implementation_prompt(원문)를 사람이 복사하기 좋게 렌더링한다.

    §7: 두 내용은 의미상 동일해야 하며, validate가 anchors/forbidden 반영 여부를 검사한다.
    """
    g = card.get
    return f"""# Implementation Prompt

레포: {g('source_repo')}
과제: {g('challenge_title')}

아래 지시문을 그대로 복사해 Claude Code / Codex / Gemma / 외주 개발자에게 넘긴다.

---

{g('implementation_prompt')}

---

## Difficulty Anchors (절대 삭제 금지)
{_bullets(g('difficulty_anchors'))}

## Forbidden Simplifications (위반 금지)
{_bullets(g('forbidden_simplifications'))}

## Allowed Simplifications
{_bullets(g('allowed_simplifications'))}

## Pass Criteria
{_bullets(g('pass_criteria'))}

## Failure Criteria
{_bullets(g('failure_criteria'))}
"""


# ---------------------------------------------------------------- viewer.html

_LABEL_CLASS = {
    "GOOD_CHALLENGE": "l-GOOD",
    "STEAL_ONLY": "l-STEAL",
    "NOT_MY_TASTE": "l-TASTE",
    "TOO_BIG": "l-BIG",
    "UNCLEAR_TO_OWNER": "l-UNCLEAR",
    "TOO_EASY": "l-EASY",
    "DROP": "l-DROP",
    "ERROR": "l-ERROR",
}

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 17px; line-height: 1.5; background: #f4f5f7; color: #1c1c1e; -webkit-text-size-adjust: 100%; }
.wrap { max-width: 720px; margin: 0 auto; padding: 16px 14px 64px; }
h1 { font-size: 1.35rem; margin: 4px 0 14px; }
.summary { background: #fff; border-radius: 14px; padding: 14px; margin-bottom: 16px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.sgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 12px; }
.sitem { display: flex; flex-direction: column; }
.sitem .k { font-size: .72rem; color: #6b7280; }
.sitem .val { font-weight: 600; word-break: break-word; }
.controls { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.controls button { font-size: .9rem; padding: 8px 13px; border-radius: 999px; border: 1px solid #d1d5db;
  background: #fff; color: #1c1c1e; min-height: 38px; cursor: pointer; }
.controls button.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.card { background: #fff; border-radius: 14px; padding: 14px; margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.chead { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
.repo { font-weight: 700; font-size: 1.05rem; word-break: break-all; flex: 1 1 auto; }
.repo a { color: #2563eb; text-decoration: none; }
.badge { font-size: .72rem; font-weight: 700; padding: 3px 10px; border-radius: 999px; color: #fff; }
.l-GOOD { background: #16a34a; } .l-STEAL { background: #7c3aed; }
.l-TASTE { background: #d97706; } .l-BIG { background: #0891b2; }
.l-UNCLEAR { background: #db2777; } .l-EASY { background: #6b7280; }
.l-DROP { background: #374151; } .l-ERROR { background: #dc2626; }
.score { font-size: .8rem; font-weight: 600; color: #374151; background: #eef2ff; padding: 3px 9px; border-radius: 999px; }
.title { font-weight: 700; margin: 6px 0 2px; }
.concl { margin: 4px 0; }
.err { margin: 6px 0; color: #b91c1c; }
h4 { margin: 12px 0 4px; font-size: .9rem; }
ul { margin: 4px 0; padding-left: 20px; }
pre { white-space: pre-wrap; word-break: break-word; background: #f3f4f6; border-radius: 10px; padding: 10px; font-size: .85rem; }
details { margin-top: 8px; border-top: 1px solid #eceef1; padding-top: 8px; }
summary { cursor: pointer; font-weight: 600; color: #2563eb; padding: 6px 0; min-height: 32px; }
.muted { color: #9ca3af; margin: 4px 0; }
.count { color: #6b7280; font-size: .85rem; margin: 0 0 12px; }
@media (prefers-color-scheme: dark) {
  body { background: #000; color: #f2f2f7; }
  .summary, .card { background: #1c1c1e; box-shadow: none; border: 1px solid #2c2c2e; }
  .controls button { background: #1c1c1e; color: #f2f2f7; border-color: #3a3a3c; }
  .controls button.active { background: #2563eb; border-color: #2563eb; }
  .sitem .k { color: #98989f; }
  .score { background: #2c2c40; color: #d5d9ff; }
  pre { background: #2c2c2e; }
  .repo a { color: #6ea8fe; }
  details { border-color: #2c2c2e; }
}
"""

_JS = """
(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var list = document.getElementById('cards');
  var countEl = document.getElementById('count');
  if (!list) return;
  var state = { filter: 'ALL' };
  function apply() {
    var shown = 0;
    cards.forEach(function (c) {
      var l = c.getAttribute('data-label');
      var ok = (state.filter === 'ALL') || (l === state.filter);
      c.style.display = ok ? '' : 'none';
      if (ok) shown++;
    });
    if (countEl) countEl.textContent = shown + '개 표시';
  }
  document.querySelectorAll('[data-filter]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      state.filter = btn.getAttribute('data-filter');
      document.querySelectorAll('[data-filter]').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      apply();
    });
  });
  apply();
})();
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _bullet_list_html(items: list | None) -> str:
    items = [i for i in (items or []) if i]
    if not items:
        return '<p class="muted">(없음)</p>'
    lis = "".join(f"<li>{_e(i)}</li>" for i in items)
    return f"<ul>{lis}</ul>"


def _label_badge(label: str | None) -> str:
    lab = (label or "ERROR").upper()
    cls = _LABEL_CLASS.get(lab, "l-ERROR")
    return f'<span class="badge {cls}">{_e(lab)}</span>'


def challenge_card_html(item: dict) -> str:
    """item: challenge 카드 dict (package 평탄화 + url/error)."""
    label = item.get("final_label") or "ERROR"
    repo = item.get("source_repo") or "(알 수 없음)"
    url = item.get("repo_url")
    repo_html = f'<a href="{_e(url)}" target="_blank" rel="noopener">{_e(repo)}</a>' if url else _e(repo)
    total = item.get("score_total")
    score_chip = f'<span class="score">score {_e(total)}</span>' if isinstance(total, int) else ""

    if label == "ERROR":
        body = f'<p class="err">오류: {_e(item.get("error"))}</p>'
        expanded = ""
    else:
        body = (
            f'<p class="title">{_e(item.get("challenge_title"))}</p>'
            f'<p class="concl">{_e(item.get("one_line_challenge"))}</p>'
        )
        brief = item.get("owner_brief") or {}
        story = item.get("screen_story") or {}
        expanded = f"""
    <details>
      <summary>상세 보기</summary>
      <h4>쉽게 말해 뭐냐</h4><p>{_e(brief.get('what_is_this'))}</p>
      <h4>우리가 훔칠 핵심</h4><p>{_e(brief.get('what_we_steal'))}</p>
      <h4>사용자 행동</h4>{_bullet_list_html(story.get('user_actions'))}
      <h4>Difficulty Anchors</h4>{_bullet_list_html(item.get('difficulty_anchors'))}
      <h4>Forbidden Simplifications</h4>{_bullet_list_html(item.get('forbidden_simplifications'))}
      <h4>Pass Criteria</h4>{_bullet_list_html(item.get('pass_criteria'))}
      <h4>Failure Criteria</h4>{_bullet_list_html(item.get('failure_criteria'))}
      <h4>Implementation Prompt</h4>
      <pre>{_e(item.get('implementation_prompt'))}</pre>
    </details>"""

    return f"""  <article class="card" data-label="{_e(label)}">
    <div class="chead">
      <span class="repo">{repo_html}</span>
      {_label_badge(label)}{score_chip}
    </div>
    {body}{expanded}
  </article>"""


def _summary_html(rows: list[tuple[str, object]]) -> str:
    items = "".join(
        f"<div class='sitem'><span class='k'>{_e(k)}</span><span class='val'>{_e(v)}</span></div>"
        for k, v in rows
    )
    return f'<section class="summary"><div class="sgrid">{items}</div></section>'


def _controls_html(labels: list[str]) -> str:
    btns = ['<button data-filter="ALL" class="active">전체</button>']
    for lab in labels:
        btns.append(f'<button data-filter="{_e(lab)}">{_e(lab)}</button>')
    return f"""<div class="controls">{''.join(btns)}</div>
<p class="count" id="count"></p>"""


def render_challenge_viewer_html(model: dict) -> str:
    """model: {"kind": "single"|"search", "summary": {...}, "cards": [...]}"""
    kind = model["kind"]
    cards = model["cards"]
    cards_html = "\n".join(challenge_card_html(c) for c in cards)

    if kind == "single":
        repo = cards[0].get("source_repo") if cards else "(없음)"
        title = f"RIM Challenge · {repo}"
        s = model.get("summary") or {}
        header = _summary_html(
            [
                ("레포", repo),
                ("final_label", s.get("final_label")),
                ("score_total", s.get("score_total")),
                ("owner_clarity", s.get("owner_clarity_score")),
                ("mode", s.get("mode")),
                ("timestamp", s.get("timestamp")),
            ]
        )
        controls = ""
    else:
        title = "RIM Challenge · 검색 결과"
        s = model.get("summary") or {}
        header = _summary_html(
            [
                ("검색어", s.get("query")),
                ("생성", s.get("generated_count")),
                ("GOOD_CHALLENGE", s.get("good_count")),
                ("STEAL_ONLY", s.get("steal_count")),
                ("TOO_EASY", s.get("too_easy_count")),
                ("DROP", s.get("drop_count")),
                ("ERROR", s.get("error_count")),
                ("mode", s.get("mode")),
            ]
        )
        present = []
        for lab in ("GOOD_CHALLENGE", "STEAL_ONLY", "NOT_MY_TASTE", "TOO_BIG", "UNCLEAR_TO_OWNER", "TOO_EASY", "DROP", "ERROR"):
            if any((c.get("final_label") or "ERROR") == lab for c in cards):
                present.append(lab)
        controls = _controls_html(present)

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
