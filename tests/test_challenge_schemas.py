# Challenge Mode 스키마 검증과 §9 자동 판정 규칙 테스트.
import pytest
from pydantic import ValidationError

from repo_idea_miner.challenge_prompts import mock_challenge_package
from repo_idea_miner.challenge_schemas import (
    ChallengeCard,
    ChallengeIndex,
    ChallengePackage,
    OwnerBrief,
    ScreenStory,
    apply_auto_label_rules,
)


def test_mock_package_passes_all_schemas():
    pkg = mock_challenge_package("owner/repo")
    validated = ChallengePackage.model_validate(pkg)
    assert validated.challenge_card.final_label == "GOOD_CHALLENGE"
    OwnerBrief.model_validate(pkg["owner_brief"])
    ScreenStory.model_validate(pkg["screen_story"])
    ChallengeCard.model_validate(pkg["challenge_card"])


def test_empty_difficulty_anchors_fails():
    pkg = mock_challenge_package()
    pkg["challenge_card"]["difficulty_anchors"] = []
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)


def test_empty_forbidden_simplifications_fails():
    pkg = mock_challenge_package()
    pkg["challenge_card"]["forbidden_simplifications"] = []
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)


def test_empty_pass_or_failure_criteria_fails():
    pkg = mock_challenge_package()
    pkg["challenge_card"]["pass_criteria"] = []
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)
    pkg = mock_challenge_package()
    pkg["challenge_card"]["failure_criteria"] = []
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)


@pytest.mark.parametrize("score", [0, 6, -1])
def test_owner_clarity_score_out_of_range_fails(score):
    pkg = mock_challenge_package()
    pkg["owner_brief"]["owner_clarity_score"] = score
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)


def test_scores_out_of_range_fails():
    pkg = mock_challenge_package()
    pkg["challenge_card"]["scores"]["not_too_easy"] = 0
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)


def test_invalid_final_label_fails():
    pkg = mock_challenge_package()
    pkg["challenge_card"]["final_label"] = "KEEP"
    with pytest.raises(ValidationError):
        ChallengePackage.model_validate(pkg)


# ---------------------------------------------------------------- 자동 판정 규칙 (§9)

def _package(**overrides) -> ChallengePackage:
    pkg = mock_challenge_package()
    for key, value in overrides.items():
        if key == "owner_clarity_score":
            pkg["owner_brief"][key] = value
            pkg["challenge_card"]["scores"]["owner_clarity"] = value
        else:
            pkg["challenge_card"]["scores"][key] = value
    return ChallengePackage.model_validate(pkg)


def test_low_owner_clarity_forces_unclear():
    p = _package(owner_clarity_score=2)
    applied = apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "UNCLEAR_TO_OWNER"
    assert applied


def test_weak_anchor_forces_too_easy():
    p = _package(difficulty_anchor_alive=2)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "TOO_EASY"


def test_not_too_easy_low_forces_too_easy():
    p = _package(not_too_easy=1)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "TOO_EASY"


def test_not_buildable_forces_too_big():
    p = _package(buildable_in_one_day=1)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "TOO_BIG"


def test_low_demo_value_forces_drop():
    p = _package(immediate_demo_value=2)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "DROP"


def test_good_challenge_stays_when_scores_ok():
    p = _package()
    applied = apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "GOOD_CHALLENGE"
    assert applied == []


def test_challenge_index_schema():
    idx = ChallengeIndex.model_validate(
        {
            "query": "stars:>1000",
            "mode": "mock",
            "total_candidates": 5,
            "generated_count": 1,
            "items": [
                {
                    "source_repo": "a/b",
                    "repo_url": "https://github.com/a/b",
                    "challenge_title": "t",
                    "one_line_challenge": "o",
                    "final_label": "GOOD_CHALLENGE",
                    "owner_clarity_score": 4,
                    "score_total": 32,
                    "difficulty_anchors": ["x"],
                    "short_reason": "r",
                    "artifact_dir": "runs/x/repos/a__b",
                }
            ],
        }
    )
    assert idx.generated_count == 1
