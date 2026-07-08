# mock 모드 단일 Challenge 파이프라인 통합 테스트: 산출물/DB/validate까지 네트워크 없이 검증.
import json
from pathlib import Path

from repo_idea_miner.challenge_db import open_db
from repo_idea_miner.challenge_pipeline import SINGLE_CHALLENGE_FILES, run_challenge
from repo_idea_miner.challenge_validate import validate_challenge_run_dir
from repo_idea_miner.config import Settings
from tests.test_pipeline_mock import FakeGitHub


def _run(tmp_path, db_conn=None, **kwargs):
    settings = Settings(google_keys={1: "AQ.fake_key_for_test_aaaaaaaaaa"})
    return run_challenge(
        "https://github.com/owner/repo",
        mode="mock",
        output_dir=tmp_path,
        settings=settings,
        gh=FakeGitHub(),
        db_conn=db_conn,
        **kwargs,
    )


def test_mock_challenge_produces_all_artifacts(tmp_path):
    result = _run(tmp_path)
    assert result["ok"], result
    run_dir = Path(result["run_dir"])
    for name in SINGLE_CHALLENGE_FILES:
        assert (run_dir / name).exists(), name
    assert (run_dir / "viewer.html").exists()

    report = json.loads((run_dir / "validation_report.json").read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert report["schema_validation"] == "PASS"
    assert report["secret_scan"] == "PASS"

    assert result["final_label"] == "GOOD_CHALLENGE"
    assert isinstance(result["score_total"], int)


def test_mock_challenge_validates(tmp_path):
    result = _run(tmp_path)
    ok, problems = validate_challenge_run_dir(result["run_dir"], [])
    assert ok, problems


def test_implementation_prompt_reflects_forbidden_and_anchors(tmp_path):
    result = _run(tmp_path)
    run_dir = Path(result["run_dir"])
    impl = (run_dir / "implementation_prompt.md").read_text(encoding="utf-8")
    card = json.loads((run_dir / "challenge_card.json").read_text(encoding="utf-8"))
    for anchor in card["difficulty_anchors"]:
        assert anchor in impl
    for forbidden in card["forbidden_simplifications"]:
        assert forbidden in impl
    assert card["implementation_prompt"].strip() in impl


def test_viewer_has_required_elements_and_no_secret(tmp_path):
    result = _run(tmp_path)
    viewer = (Path(result["run_dir"]) / "viewer.html").read_text(encoding="utf-8")
    assert 'name="viewport"' in viewer
    assert 'class="card"' in viewer
    assert 'class="badge' in viewer
    assert "AQ.fake_key_for_test" not in viewer


def test_mock_challenge_saves_to_db(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        result = _run(tmp_path, db_conn=conn)
        assert result["challenge_id"] is not None
        repos = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
        challenges = conn.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
        review = conn.execute(
            "SELECT owner_status FROM owner_reviews WHERE challenge_id=?", (result["challenge_id"],)
        ).fetchone()
        assert repos == 1
        assert challenges == 1
        assert review["owner_status"] == "unseen"
        events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert events >= 1
    finally:
        conn.close()


def test_invalid_llm_output_fails_safe(tmp_path):
    from repo_idea_miner.challenge_prompts import mock_challenge_package
    from repo_idea_miner.llm_client import MockLLMClient

    bad = mock_challenge_package("owner/repo")
    bad["challenge_card"]["difficulty_anchors"] = []  # schema 위반
    llm = MockLLMClient(overrides={"challenge_package": bad})
    settings = Settings(google_keys={})
    result = run_challenge(
        "https://github.com/owner/repo",
        mode="mock",
        output_dir=tmp_path,
        settings=settings,
        gh=FakeGitHub(),
        llm=llm,
    )
    assert not result["ok"]
    assert "VALIDATION_FAIL" in (result["error"] or "")
    run_dir = Path(result["run_dir"])
    report = json.loads((run_dir / "validation_report.json").read_text(encoding="utf-8"))
    assert report["schema_validation"] == "FAIL"
    assert not (run_dir / "challenge_card.json").exists()
