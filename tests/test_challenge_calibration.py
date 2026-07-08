# Challenge Mode 라벨 캘리브레이션 테스트: 쉬운 후보가 GOOD_CHALLENGE로 과대평가되지 않는지 검증.
from repo_idea_miner.challenge_prompts import (
    EASY_CALIBRATION_CASES,
    mock_challenge_package,
    mock_easy_challenge_package,
)
from repo_idea_miner.challenge_schemas import (
    ChallengePackage,
    apply_auto_label_rules,
    is_generic_list,
)


def _label_after_rules(pkg_dict: dict) -> str:
    pkg = ChallengePackage.model_validate(pkg_dict)
    apply_auto_label_rules(pkg)
    return pkg.challenge_card.final_label


def _package(**overrides) -> ChallengePackage:
    pkg = mock_challenge_package()
    for key, value in overrides.items():
        if key == "owner_clarity_score":
            pkg["owner_brief"][key] = value
            pkg["challenge_card"]["scores"]["owner_clarity"] = value
        elif key in ("difficulty_anchors", "forbidden_simplifications"):
            pkg["challenge_card"][key] = value
        else:
            pkg["challenge_card"]["scores"][key] = value
    return ChallengePackage.model_validate(pkg)


# ------------------------------------------------ is_generic_list 휴리스틱 단위 검증

def test_generic_anchors_detected():
    assert is_generic_list(["좋은 UX", "자동화", "데이터 관리", "대시보드", "사용자 친화성"])


def test_generic_forbidden_detected():
    assert is_generic_list(["단순하게 만들지 말 것", "기능을 줄이지 말 것"])


def test_concrete_anchors_not_generic():
    assert not is_generic_list(
        [
            "사용자가 명령을 검색하고 즉시 실행한다",
            "결과 카드에서 다음 후속 액션을 선택할 수 있다",
        ]
    )


def test_concrete_forbidden_not_generic():
    assert not is_generic_list(
        [
            "결과 카드 없이 검색창만 만들지 말 것",
            "상태 변화 없이 정적 목록만 보여주지 말 것",
        ]
    )


def test_good_mock_lists_are_not_generic():
    # GOOD 기준 mock의 anchors/forbidden은 일반론으로 오탐되면 안 된다.
    card = mock_challenge_package()["challenge_card"]
    assert not is_generic_list(card["difficulty_anchors"])
    assert not is_generic_list(card["forbidden_simplifications"])


# ------------------------------------------------ 필수 캘리브레이션 테스트 (지시문 1~5)

def test_easy_calibration_set_yields_too_easy_or_drop():
    """1. easy calibration sample에서 TOO_EASY 또는 DROP이 최소 1개 이상 나와야 한다."""
    labels = []
    for i, (seed, variant) in enumerate(EASY_CALIBRATION_CASES):
        pkg = mock_easy_challenge_package(f"easy/{i}", seed=seed, variant=variant)
        labels.append(_label_after_rules(pkg))
    # 쉬운 후보 중 어느 것도 GOOD_CHALLENGE가 되면 안 된다.
    assert "GOOD_CHALLENGE" not in labels, labels
    # TOO_EASY 또는 DROP이 최소 1개 이상.
    assert any(label in ("TOO_EASY", "DROP") for label in labels), labels


def test_todo_crud_mock_never_good():
    """2. 단순 TODO/CRUD류 mock은 GOOD_CHALLENGE가 되면 안 된다."""
    pkg = mock_easy_challenge_package("easy/todo", seed="todo app", variant="too_easy")
    assert _label_after_rules(pkg) != "GOOD_CHALLENGE"


def test_generic_anchors_block_good():
    """3. difficulty_anchors가 일반론뿐이면 GOOD_CHALLENGE가 되면 안 된다."""
    p = _package(difficulty_anchors=["좋은 UX", "자동화", "데이터 관리"])
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label != "GOOD_CHALLENGE"
    assert p.challenge_card.final_label == "TOO_EASY"


def test_generic_forbidden_block_good():
    """4. forbidden_simplifications가 일반론뿐이면 GOOD_CHALLENGE가 되면 안 된다."""
    p = _package(forbidden_simplifications=["단순하게 만들지 말 것", "기능을 줄이지 말 것"])
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label != "GOOD_CHALLENGE"
    assert p.challenge_card.final_label == "TOO_EASY"


def test_high_clarity_but_low_not_too_easy_blocks_good():
    """5. owner_clarity가 높아도 not_too_easy가 낮으면 GOOD_CHALLENGE가 되면 안 된다."""
    p = _package(owner_clarity_score=5, not_too_easy=2)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "TOO_EASY"


# ------------------------------------------------ 강화된 임계값 경계 검증

def test_anchor_alive_3_now_too_easy():
    # 기존에는 3이면 GOOD 유지였으나, 캘리브레이션 후 4 미만은 TOO_EASY.
    p = _package(difficulty_anchor_alive=3)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "TOO_EASY"


def test_not_too_easy_3_now_too_easy():
    p = _package(not_too_easy=3)
    apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "TOO_EASY"


def test_good_mock_still_good():
    # 좋은 seed(기본 mock)는 강화 후에도 GOOD_CHALLENGE로 남아야 한다.
    p = _package()
    applied = apply_auto_label_rules(p)
    assert p.challenge_card.final_label == "GOOD_CHALLENGE"
    assert applied == []
