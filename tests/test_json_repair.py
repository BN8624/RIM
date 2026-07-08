# JSON repair 테스트 (§34.10): syntax repair만 허용, 창작 금지.
import json

from repo_idea_miner.jsonutil import parse_json_with_repair


def test_markdown_fence_removed():
    text = '```json\n{"verdict": "DROP", "score": 2}\n```'
    obj, _ = parse_json_with_repair(text)
    assert obj == {"verdict": "DROP", "score": 2}


def test_trailing_comma_removed():
    text = '{"a": 1, "b": [1, 2,],}'
    obj, repair_used = parse_json_with_repair(text)
    assert obj == {"a": 1, "b": [1, 2]}
    assert repair_used


def test_surrounding_prose_removed():
    text = 'Here is the result:\n{"a": 1}\nHope this helps!'
    obj, _ = parse_json_with_repair(text)
    assert obj == {"a": 1}


def test_missing_field_not_invented(judge_json):
    del judge_json["why_it_fails"]
    obj, _ = parse_json_with_repair(json.dumps(judge_json, ensure_ascii=False))
    assert obj is not None
    assert "why_it_fails" not in obj  # repair가 필드를 창작하지 않음


def test_verdict_score_unchanged(judge_json):
    text = "```json\n" + json.dumps(judge_json, ensure_ascii=False) + "\n```"
    obj, _ = parse_json_with_repair(text)
    assert obj["verdict"] == judge_json["verdict"]
    assert obj["score"] == judge_json["score"]


def test_unparseable_returns_none():
    obj, repair_used = parse_json_with_repair("완전히 JSON이 아닌 텍스트")
    assert obj is None
