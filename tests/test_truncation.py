# length truncation 테스트 (§34.11): 길이 초과는 실패가 아니라 축약.
from repo_idea_miner.truncation import apply_length_limits


def test_long_string_truncated_not_failed(judge_json):
    judge_json["one_line_conclusion"] = "가" * 500
    out, truncated = apply_length_limits(judge_json)
    assert len(out["one_line_conclusion"]) <= 160
    assert out["one_line_conclusion"].endswith("...")
    assert "one_line_conclusion" in truncated


def test_long_list_keeps_first_n(judge_json):
    judge_json["user_pain"] = [f"pain {i}" for i in range(10)]
    out, truncated = apply_length_limits(judge_json)
    assert len(out["user_pain"]) == 5
    assert out["user_pain"][0] == "pain 0"
    assert "user_pain" in truncated


def test_nested_reason_truncated(judge_json):
    judge_json["dependency_runtime_risk"]["reason"] = "리" * 400
    out, truncated = apply_length_limits(judge_json)
    assert len(out["dependency_runtime_risk"]["reason"]) <= 240
    assert "dependency_runtime_risk.reason" in truncated


def test_no_truncation_when_within_limits(judge_json):
    out, truncated = apply_length_limits(judge_json)
    assert truncated == []
    assert out["verdict"] == judge_json["verdict"]
