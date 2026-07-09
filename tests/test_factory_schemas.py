# Auto Promotion Gate(§6)와 Factory 스키마/Codex 승격 조건 테스트.
import pytest

from repo_idea_miner.challenge_prompts import mock_challenge_package
from repo_idea_miner.factory_schemas import (
    Contract,
    Manifest,
    QAOutput,
    codex_promotion_problems,
    promotion_line,
)


def _card(**overrides):
    card = mock_challenge_package("a/b")["challenge_card"]
    card.update(overrides)
    return card


def test_good_challenge_enters_standard_line():
    line, reasons = promotion_line(_card(), owner_clarity_score=4)
    assert line == "standard"
    assert any("standard" in r for r in reasons)


def test_good_challenge_rejected_when_scores_low():
    card = _card()
    card["scores"]["not_too_easy"] = 3
    line, reasons = promotion_line(card, owner_clarity_score=4)
    assert line is None
    assert any("not_too_easy" in r for r in reasons)


def test_good_challenge_rejected_when_anchors_short():
    card = _card(difficulty_anchors=["하나뿐"])
    line, _ = promotion_line(card, owner_clarity_score=4)
    assert line is None


def test_steal_only_enters_micro_line():
    card = _card(final_label="STEAL_ONLY")
    card["scores"]["difficulty_anchor_alive"] = 3
    line, reasons = promotion_line(card, owner_clarity_score=3)
    assert line == "micro"
    assert any("micro" in r for r in reasons)


def test_steal_only_rejected_when_clarity_low():
    card = _card(final_label="STEAL_ONLY")
    line, _ = promotion_line(card, owner_clarity_score=2)
    assert line is None


@pytest.mark.parametrize("label", ["TOO_EASY", "TOO_BIG", "UNCLEAR_TO_OWNER", "DROP", "NOT_MY_TASTE"])
def test_excluded_labels_do_not_enter(label):
    line, reasons = promotion_line(_card(final_label=label), owner_clarity_score=5)
    assert line is None
    assert any("자동 승격 대상이 아님" in r for r in reasons)


def test_manifest_requires_files_and_entrypoint():
    m = Manifest.model_validate(
        {
            "project_type": "static_web",
            "entrypoint": "index.html",
            "run_command": "python -m http.server",
            "files": [{"path": "index.html", "role": "화면"}],
        }
    )
    assert m.file_paths() == ["index.html"]
    with pytest.raises(Exception):
        Manifest.model_validate({"entrypoint": "", "run_command": "x", "files": []})


def test_contract_requires_anchor_requirements():
    with pytest.raises(Exception):
        Contract.model_validate(
            {
                "entrypoint": "index.html",
                "required_files": ["index.html"],
                "modules": [{"path": "src/a.js", "role": "r"}],
                "state_model": "s",
                "core_interactions": ["i"],
                "difficulty_anchor_requirements": [],
                "forbidden_simplification_rules": ["r"],
            }
        )


def _qa(alive=True, violated=False):
    return QAOutput.model_validate(
        {
            "anchors": [{"anchor": "a", "alive": alive, "evidence": "e"}],
            "forbidden": [{"rule": "r", "violated": violated, "evidence": "e"}],
            "is_degenerate": False,
            "degeneration_reason": "없음",
            "has_user_action": True,
            "has_state_change": True,
            "has_runnable_artifact": True,
            "summary": "ok",
        }
    )


def test_qa_pass_logic():
    assert _qa().qa_pass()
    assert not _qa(alive=False).qa_pass()
    assert not _qa(violated=True).qa_pass()


def test_codex_promotion_problems():
    gates = {"static": True, "contract": True, "syntax": True, "smoke": True}
    assert codex_promotion_problems(gates, _qa(), True) == []
    problems = codex_promotion_problems({**gates, "smoke": False}, _qa(), True)
    assert any("smoke" in p for p in problems)
    problems = codex_promotion_problems(gates, _qa(alive=False), True)
    assert any("Anchors" in p for p in problems)
    problems = codex_promotion_problems(gates, _qa(), False)
    assert any("debug" in p for p in problems)
