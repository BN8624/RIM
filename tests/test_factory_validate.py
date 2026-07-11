# factory-validate: Final Artifact 구조·단일파일 실패·manifest 불일치 검증 테스트.
import json
import shutil

import pytest

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_pipeline import FactorySettings, run_product_factory, sample_challenge
from repo_idea_miner.factory_prompts import mock_factory_overrides
from repo_idea_miner.factory_validate import validate_final_artifact, validate_product_run_dir
from repo_idea_miner.llm_client import MockLLMClient


@pytest.fixture(scope="module")
def valid_run(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("factory_validate")
    result = run_product_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        settings=Settings(google_keys={}), factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert result["ok"], result["error"]
    return result


def test_valid_run_passes(valid_run):
    ok, problems = validate_product_run_dir(valid_run["run_dir"], [])
    assert ok, problems


def test_single_file_final_artifact_fails(valid_run, tmp_path):
    """Final Artifact가 단일파일이면 실패 (§22-16)."""
    from pathlib import Path

    copy = tmp_path / "copy"
    shutil.copytree(Path(valid_run["run_dir"]) / "final_artifact", copy)
    for p in list((copy / "src").rglob("*")):
        if p.is_file() and p.name != "app.js":
            p.unlink()
    problems = validate_final_artifact(copy)
    assert any("단일파일" in p for p in problems)


def test_manifest_mismatch_fails(valid_run, tmp_path):
    """manifest와 실제 파일 불일치 시 실패 (§22-17)."""
    from pathlib import Path

    copy = tmp_path / "copy2"
    shutil.copytree(Path(valid_run["run_dir"]) / "final_artifact", copy)
    manifest = json.loads((copy / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"].append({"path": "src/ghost.js", "role": "없는 파일"})
    (copy / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    problems = validate_final_artifact(copy)
    assert any("ghost.js" in p for p in problems)


def test_missing_final_artifact_fails(tmp_path):
    empty = tmp_path / "empty_run"
    empty.mkdir()
    ok, problems = validate_product_run_dir(empty, [])
    assert not ok
    assert any("final_artifact" in p for p in problems)


def test_missing_required_report_fails(valid_run, tmp_path):
    from pathlib import Path

    copy = tmp_path / "copy3"
    shutil.copytree(Path(valid_run["run_dir"]) / "final_artifact", copy)
    (copy / "reports" / "qa_report.md").unlink()
    problems = validate_final_artifact(copy)
    assert any("qa_report.md" in p for p in problems)


def test_secret_in_artifact_fails(valid_run, tmp_path, fake_env):
    from pathlib import Path

    copy = tmp_path / "copy4"
    shutil.copytree(Path(valid_run["run_dir"]), copy)
    (copy / "final_artifact" / "README.md").write_text(
        f"key: {fake_env['GOOGLE_API_KEY_1']}", encoding="utf-8"
    )
    ok, problems = validate_product_run_dir(copy, list(fake_env.values()))
    assert not ok
    assert any("secret" in p for p in problems)


def test_marker_validator_registry_is_single_source(tmp_path):
    """§12.3: core와 continuation이 같은 registry를 쓰고, 순서·선언이 고정돼 있다."""
    from repo_idea_miner.factory_run_layout import RUN_KIND_CONTINUATION, RUN_KIND_CORE, RUN_KIND_LEGACY
    from repo_idea_miner.factory_validate import MARKER_VALIDATORS, run_marker_validators

    ids = [s.validator_id for s in MARKER_VALIDATORS]
    assert ids == ["frozen_hash_guard", "spec_repair_outputs", "spec_repair_apply",
                   "anti_hardcode_patch", "phase2c0", "phase2c1", "phase2c2", "phase2c3",
                   "interaction_ui", "draft_execution_lane", "viewer_polish_lane",
                   "ux_polish_lane", "phase2d0", "phase2d1"]
    for spec in MARKER_VALIDATORS:
        assert set(spec.run_kinds) == {RUN_KIND_CONTINUATION, RUN_KIND_CORE}, spec.validator_id
        assert spec.related_tests, spec.validator_id

    # marker 없는 빈 run: 전 validator PASS(no-op), legacy kind면 전부 SKIP
    results = run_marker_validators(tmp_path, RUN_KIND_CORE)
    assert [r.check_id for r in results] == ids
    assert all(r.status == "PASS" and not r.problems for r in results)
    assert all(r.status == "SKIP" for r in run_marker_validators(tmp_path, RUN_KIND_LEGACY))
