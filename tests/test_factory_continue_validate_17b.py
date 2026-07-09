# Phase 1.7b: factory-validate가 continuation run을 별도 run type으로 감지·검증하는지 테스트 (§8).
import json
from pathlib import Path

import pytest

from repo_idea_miner.factory_validate import (
    RUN_TYPE_CONTINUATION,
    RUN_TYPE_CORE,
    RUN_TYPE_LEGACY,
    RUN_TYPE_UNKNOWN,
    detect_run_type,
    validate_continuation_run_dir,
    validate_product_run_dir,
)


# ---------------------------------------------------------------- 정상 continuation run fixture

def _valid_continuation(run_dir: Path) -> Path:
    """모든 필수 산출물이 정합적인 continuation run(SPEC_REPAIR_REQUIRED) fixture를 만든다."""
    run_dir.mkdir(parents=True, exist_ok=True)

    def w(name, data):
        (run_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    w("continuation_run_summary.json", {
        "base_run_id": 5, "base_run_dir": "runs/factory_x", "challenge_id": 47,
        "mode": "live", "verdict": "SPEC_REPAIR_REQUIRED", "promoted_to_green_base": False,
        "failure_types": ["GOLDEN_SCHEMA_MISMATCH", "STATE_INVARIANT_NOT_EXPOSED", "SPEC_REPAIR_REQUIRED"],
        "resolved": {}, "patch_attempts": 2, "transient_retries": 2, "rejected_patches": [],
        "requires_spec_repair": True,
    })
    w("failure_classification.json", {
        "base_run_id": 5, "challenge_id": 47,
        "failure_types": [
            {"type": "GOLDEN_SCHEMA_MISMATCH", "evidence": "golden behind runner",
             "repairable": True, "requires_spec_repair": True},
            {"type": "STATE_INVARIANT_NOT_EXPOSED", "evidence": "invariants not exposed",
             "repairable": True, "requires_spec_repair": False},
            {"type": "SPEC_REPAIR_REQUIRED", "evidence": "golden update needed",
             "repairable": False, "requires_spec_repair": True},
        ],
    })
    w("repair_plan.json", {
        "base_run_id": 5, "repair_scope": "delta_patch",
        "allowed_touch_files": ["src/", "product/", "run_instructions.md", "README.md"],
        "frozen_files": ["core_contract.json", "runner_contract.json", "fixtures/", "golden/"],
        "steps": [{"target": "src/", "reason": "expose invariant", "failure_type": "STATE_INVARIANT_NOT_EXPOSED"}],
        "requires_spec_repair": True,
    })
    w("green_base_promotion.json", {
        "base_run_id": 5, "continuation_run_id": 8, "promoted_to_green_base": False,
        "new_verdict": "SPEC_REPAIR_REQUIRED",
        "remaining_failures": ["GOLDEN_SCHEMA_MISMATCH", "STATE_INVARIANT_NOT_EXPOSED"],
        "next_goal": "resolve schema mismatch",
    })
    w("gate_rerun_summary.json", {
        "gates": {"core_contract": True, "runner": True, "scenario_replay": True,
                  "golden_output": False, "state_invariant": False, "determinism": True,
                  "anti_hardcode": True},
        "gates_passed": 5, "gates_total": 7, "failed_scenarios": ["scenario_001"],
        "product_layer_consumes_core": True, "build_review_status": "NEEDS_PATCH",
    })
    w("phase17_dashboard_summary.json", {
        "is_continuation": True, "base_run_id": 5, "verdict": "SPEC_REPAIR_REQUIRED",
        "headline": "스펙 수정 필요", "green_base": False, "continuation_base": True,
        "remaining_failures": ["GOLDEN_SCHEMA_MISMATCH", "STATE_INVARIANT_NOT_EXPOSED"],
    })
    w("product_layer_recheck.json", {"consumes_replay_output": True, "problems": []})
    return run_dir


def _load(run_dir, name):
    return json.loads((run_dir / name).read_text(encoding="utf-8"))


def _dump(run_dir, name, data):
    (run_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 1~3: 감지 + PASS

def test_detect_continuation_run(tmp_path):
    """§8-1: continuation_run_summary.json을 보고 CONTINUATION_RUN으로 감지."""
    run = _valid_continuation(tmp_path / "cont")
    assert detect_run_type(run) == RUN_TYPE_CONTINUATION


def test_continuation_not_routed_to_legacy(tmp_path):
    """§8-2: continuation run이 legacy final_artifact 경로로 라우팅되지 않는다."""
    run = _valid_continuation(tmp_path / "cont")
    ok, problems = validate_product_run_dir(run, [])
    assert ok, problems
    # legacy 검증이 냈을 법한 문제(manifest/final_artifact)가 없어야 한다
    assert not any("final_artifact" in p or "manifest" in p for p in problems)


def test_valid_continuation_passes(tmp_path):
    """§8-3: 필수 continuation 파일이 모두 있으면 PASS (SPEC_REPAIR_REQUIRED도 정직하면 PASS)."""
    run = _valid_continuation(tmp_path / "cont")
    ok, problems, info = validate_continuation_run_dir(run, [])
    assert ok, problems
    assert info["verdict"] == "SPEC_REPAIR_REQUIRED"
    assert info["base_run_id"] == 5


# ---------------------------------------------------------------- 4~7: 필수 파일 누락

@pytest.mark.parametrize("missing", [
    "continuation_run_summary.json",
    "failure_classification.json",
    "repair_plan.json",
    "green_base_promotion.json",
])
def test_missing_required_file_fails(tmp_path, missing):
    """§8-4,5,6,7: 필수 continuation 산출물 누락 시 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    (run / missing).unlink()
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any(missing in p for p in problems)


# ---------------------------------------------------------------- 8: unknown failure type

def test_unknown_failure_type_fails(tmp_path):
    """§8-8: 알 수 없는 failure type인데 unknown 표기가 없으면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    fc = _load(run, "failure_classification.json")
    fc["failure_types"].append({"type": "WEIRD_UNKNOWN_TYPE", "evidence": "x",
                                "repairable": True, "requires_spec_repair": False})
    _dump(run, "failure_classification.json", fc)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("알 수 없는 failure type" in p for p in problems)


def test_unknown_marked_type_passes(tmp_path):
    """§8-8 보완: unknown으로 표기하면 통과한다."""
    run = _valid_continuation(tmp_path / "cont")
    fc = _load(run, "failure_classification.json")
    fc["failure_types"].append({"type": "unknown", "evidence": "미분류",
                                "repairable": False, "requires_spec_repair": False})
    _dump(run, "failure_classification.json", fc)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert ok, problems


# ---------------------------------------------------------------- 9~12: frozen/allowed 정합성

def test_no_frozen_files_fails(tmp_path):
    """§8-9: frozen_files 없으면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    plan = _load(run, "repair_plan.json")
    plan["frozen_files"] = []
    _dump(run, "repair_plan.json", plan)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("frozen_files 없음" in p for p in problems)


def test_no_allowed_touch_files_fails(tmp_path):
    """§8-10: allowed_touch_files 없으면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    plan = _load(run, "repair_plan.json")
    plan["allowed_touch_files"] = []
    _dump(run, "repair_plan.json", plan)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("allowed_touch_files 없음" in p for p in problems)


def test_frozen_in_allowed_fails(tmp_path):
    """§8-11: golden/fixtures/contract가 allowed_touch_files에 들어가면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    plan = _load(run, "repair_plan.json")
    plan["allowed_touch_files"] = ["src/", "golden/"]
    _dump(run, "repair_plan.json", plan)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("allowed_touch_files에 포함됨" in p for p in problems)


def test_patch_modifies_frozen_fails(tmp_path):
    """§8-12: patch가 frozen file을 수정한 기록(patch_diff_summary)이 있으면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    _dump(run, "patch_diff_summary.json", {
        "patch_attempts": 1, "modified_files": ["golden/expected_001.json"], "rejected_patches": [],
    })
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("frozen 파일 수정됨" in p for p in problems)


# ---------------------------------------------------------------- 13: transient 기록은 PASS 가능

def test_patch_transient_recorded_passes(tmp_path):
    """§8-13: patch transient 실패가 기록되어 있으면(정직) PASS 가능."""
    run = _valid_continuation(tmp_path / "cont")
    fc = _load(run, "failure_classification.json")
    fc["failure_types"].append({"type": "PATCH_TRANSIENT_FAILURE", "evidence": "model call failed",
                                "repairable": True, "requires_spec_repair": False})
    _dump(run, "failure_classification.json", fc)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert ok, problems


# ---------------------------------------------------------------- 14~16,19,20: verdict consistency

def test_gate_fail_with_review_ready_fails(tmp_path):
    """§8-14: gate fail + REVIEW_READY = FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    for name in ("continuation_run_summary.json", "green_base_promotion.json", "phase17_dashboard_summary.json"):
        d = _load(run, name)
        if "verdict" in d:
            d["verdict"] = "REVIEW_READY"
        if "new_verdict" in d:
            d["new_verdict"] = "REVIEW_READY"
        _dump(run, name, d)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("verdict consistency" in p for p in problems)


def test_gate_fail_with_promote_fails(tmp_path):
    """§8-15: gate fail + PROMOTE_TO_CODEX = FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    for name in ("continuation_run_summary.json", "green_base_promotion.json", "phase17_dashboard_summary.json"):
        d = _load(run, name)
        if "verdict" in d:
            d["verdict"] = "PROMOTE_TO_CODEX"
        if "new_verdict" in d:
            d["new_verdict"] = "PROMOTE_TO_CODEX"
        _dump(run, name, d)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("verdict consistency" in p for p in problems)


def test_gate_fail_with_spec_repair_passes(tmp_path):
    """§8-16: gate fail + SPEC_REPAIR_REQUIRED = PASS (정직하게 멈춘 실패)."""
    run = _valid_continuation(tmp_path / "cont")  # 이미 SPEC_REPAIR_REQUIRED
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert ok, problems


def test_spec_repair_with_review_ready_fails(tmp_path):
    """§8-20: requires_spec_repair=true + REVIEW_READY = FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    # 모든 gate를 통과시켜 gate consistency는 넘기되 requires_spec_repair는 유지
    gr = _load(run, "gate_rerun_summary.json")
    gr["gates"] = {k: True for k in gr["gates"]}
    _dump(run, "gate_rerun_summary.json", gr)
    for name in ("continuation_run_summary.json", "green_base_promotion.json", "phase17_dashboard_summary.json"):
        d = _load(run, name)
        if "verdict" in d:
            d["verdict"] = "REVIEW_READY"
        if "new_verdict" in d:
            d["new_verdict"] = "REVIEW_READY"
        _dump(run, name, d)
    # promoted=false + REVIEW_READY 모순을 피하려면 promoted도 손대야 하지만, 여기선 requires_spec 규칙만 확인
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("requires_spec_repair인데" in p for p in problems)


def test_spec_repair_with_spec_verdict_passes(tmp_path):
    """§8-19: requires_spec_repair=true + SPEC_REPAIR_REQUIRED = PASS."""
    run = _valid_continuation(tmp_path / "cont")
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert ok, problems


# ---------------------------------------------------------------- 17,18: green promotion 모순

def test_promoted_true_with_gate_fail_fails(tmp_path):
    """§8-17: promoted_to_green_base=true인데 gate fail이면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    promo = _load(run, "green_base_promotion.json")
    promo["promoted_to_green_base"] = True
    promo["new_verdict"] = "REVIEW_READY"
    _dump(run, "green_base_promotion.json", promo)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("promoted=true인데 gate fail" in p for p in problems)


def test_promoted_false_without_remaining_fails(tmp_path):
    """§8-18: promoted_to_green_base=false인데 remaining_failures 없으면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    promo = _load(run, "green_base_promotion.json")
    promo["remaining_failures"] = []
    _dump(run, "green_base_promotion.json", promo)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("remaining_failures 없음" in p for p in problems)


# ---------------------------------------------------------------- 21: dashboard base run 표시

def test_dashboard_missing_base_run_fails(tmp_path):
    """§8-21: phase17_dashboard_summary.json이 base run id를 표시하지 않으면 FAIL."""
    run = _valid_continuation(tmp_path / "cont")
    d = _load(run, "phase17_dashboard_summary.json")
    d.pop("base_run_id")
    _dump(run, "phase17_dashboard_summary.json", d)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("base run id 표시 없음" in p for p in problems)


# ---------------------------------------------------------------- 22,23: 기존 run type 유지

def test_core_run_still_detected(tmp_path):
    """§8-22: harness_summary.json 있는 core run은 CORE_FACTORY_RUN으로 유지."""
    run = tmp_path / "core"
    run.mkdir()
    (run / "harness_summary.json").write_text("{}", encoding="utf-8")
    assert detect_run_type(run) == RUN_TYPE_CORE


def test_legacy_run_still_detected(tmp_path):
    """§8-23: manifest 기반 legacy run은 LEGACY_FACTORY_RUN으로 유지."""
    run = tmp_path / "legacy"
    final = run / "final_artifact"
    final.mkdir(parents=True)
    (final / "manifest.json").write_text("{}", encoding="utf-8")
    assert detect_run_type(run) == RUN_TYPE_LEGACY


def test_unknown_run_detected(tmp_path):
    """빈 디렉터리는 UNKNOWN_RUN."""
    run = tmp_path / "empty"
    run.mkdir()
    assert detect_run_type(run) == RUN_TYPE_UNKNOWN
