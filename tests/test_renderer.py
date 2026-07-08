# 렌더러 테스트 (§34.13): idea_card / top_ideas 필수 섹션.
from repo_idea_miner.renderer import (
    IDEA_CARD_SECTIONS,
    render_fast_drop_card,
    render_idea_card,
    render_top_ideas,
)


def test_idea_card_has_required_sections(judge_json):
    card = render_idea_card(judge_json, "owner/repo")
    for section in IDEA_CARD_SECTIONS:
        assert section in card
    assert "MAYBE" in card


def test_idea_card_shows_verdict(judge_json):
    judge_json["verdict"] = "KEEP"
    assert "KEEP" in render_idea_card(judge_json, "o/r")
    judge_json["verdict"] = "DROP"
    assert "DROP" in render_idea_card(judge_json, "o/r")


def test_idea_card_has_pattern_poc_section(judge_json):
    card = render_idea_card(judge_json, "o/r")
    assert "## 1일 Pattern PoC" in card


def test_fast_drop_card_has_required_sections():
    card = render_fast_drop_card("o/r", "빈 레포", "preflight")
    for section in IDEA_CARD_SECTIONS:
        assert section in card
    assert "YES" in card


def test_top_ideas_rendered():
    results = [
        {"repo": "a/keep", "verdict": "KEEP", "score": 8, "one_line_conclusion": "좋음", "core_pattern": "패턴A", "fast_drop": False},
        {"repo": "b/maybe", "verdict": "MAYBE", "score": 5, "one_line_conclusion": "보통", "core_pattern": None, "fast_drop": False},
        {"repo": "c/drop", "verdict": "DROP", "score": 1, "one_line_conclusion": "별로", "fast_drop": True, "drop_reason": "빈 레포"},
    ]
    md = render_top_ideas("query x", results, top=5)
    for section in ("# Top Ideas", "## 검색어", "## 전체 요약", "## Top KEEP", "## Top MAYBE", "## 빠르게 버린 후보", "## 비교해볼 만한 패턴", "## 다음 행동"):
        assert section in md
    assert "a/keep" in md


def test_top_ideas_no_keep_marked():
    md = render_top_ideas("q", [], top=5)
    assert "KEEP 없음" in md
