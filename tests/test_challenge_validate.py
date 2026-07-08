# Challenge 산출물 검증(challenge_validate) 테스트: 정상/훼손 케이스와 CLI validate 라우팅.
import json
from pathlib import Path

from repo_idea_miner.challenge_pipeline import run_challenge
from repo_idea_miner.challenge_validate import (
    check_challenge_artifacts,
    detect_challenge_run,
    validate_challenge_run_dir,
)
from repo_idea_miner.config import Settings
from tests.test_pipeline_mock import FakeGitHub


def _make_run(tmp_path) -> Path:
    result = run_challenge(
        "https://github.com/owner/repo",
        mode="mock",
        output_dir=tmp_path,
        settings=Settings(google_keys={}),
        gh=FakeGitHub(),
    )
    assert result["ok"]
    return Path(result["run_dir"])


def test_detect_challenge_run(tmp_path):
    run_dir = _make_run(tmp_path)
    assert detect_challenge_run(run_dir) == "single"
    assert detect_challenge_run(tmp_path) is None


def test_validate_pass(tmp_path):
    run_dir = _make_run(tmp_path)
    ok, problems = validate_challenge_run_dir(run_dir, [])
    assert ok, problems


def test_validate_fails_on_missing_file(tmp_path):
    run_dir = _make_run(tmp_path)
    (run_dir / "implementation_prompt.md").unlink()
    ok, problems = validate_challenge_run_dir(run_dir, [])
    assert not ok
    assert any("implementation_prompt.md" in p for p in problems)


def test_validate_fails_on_anchor_not_reflected(tmp_path):
    run_dir = _make_run(tmp_path)
    card = json.loads((run_dir / "challenge_card.json").read_text(encoding="utf-8"))
    card["difficulty_anchors"].append("md에 없는 새 앵커")
    (run_dir / "challenge_card.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    problems = check_challenge_artifacts(run_dir)
    assert any("Difficulty Anchor 미반영" in p for p in problems)


def test_validate_fails_on_broken_schema(tmp_path):
    run_dir = _make_run(tmp_path)
    brief = json.loads((run_dir / "owner_brief.json").read_text(encoding="utf-8"))
    brief["owner_clarity_score"] = 99
    (run_dir / "owner_brief.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ok, problems = validate_challenge_run_dir(run_dir, [])
    assert not ok
    assert any("owner_brief.json 스키마 위반" in p for p in problems)


def test_validate_fails_on_secret_in_artifact(tmp_path):
    run_dir = _make_run(tmp_path)
    (run_dir / "owner_brief.md").write_text(
        (run_dir / "owner_brief.md").read_text(encoding="utf-8")
        + "\nAIzaSyFAKEFAKEFAKEFAKEFAKE123456",
        encoding="utf-8",
    )
    ok, problems = validate_challenge_run_dir(run_dir, [])
    assert not ok
    assert any("secret 노출" in p for p in problems)


def test_cli_validate_routes_challenge_run(tmp_path, capsys):
    from repo_idea_miner.cli import main

    run_dir = _make_run(tmp_path)
    assert main(["validate", str(run_dir)]) == 0
    assert "VALIDATION PASS" in capsys.readouterr().out
