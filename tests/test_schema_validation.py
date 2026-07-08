# JSON validation 테스트 (§34.9): Pydantic 구조 검증.
import pytest
from pydantic import ValidationError

from repo_idea_miner.schemas import JudgeOutput


def test_mock_judge_passes(judge_json):
    out = JudgeOutput.model_validate(judge_json)
    assert out.verdict == "MAYBE"


def test_bad_verdict_fails(judge_json):
    judge_json["verdict"] = "SUPER_KEEP"
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)


def test_score_11_fails(judge_json):
    judge_json["score"] = 11
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)


def test_missing_required_field_fails(judge_json):
    del judge_json["next_action"]
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)


def test_list_type_error_fails(judge_json):
    judge_json["user_pain"] = "문자열이면 안 됨"
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)


def test_object_type_error_fails(judge_json):
    judge_json["one_day_mvp"] = "문자열이면 안 됨"
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)


def test_empty_why_it_fails_fails(judge_json):
    judge_json["why_it_fails"] = []
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)


def test_empty_next_action_fails(judge_json):
    judge_json["next_action"] = ""
    with pytest.raises(ValidationError):
        JudgeOutput.model_validate(judge_json)
