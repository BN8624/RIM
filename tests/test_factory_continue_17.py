# Phase 1.7 Continuation Delta Loop 테스트: 분류·repair plan·frozen 보호·transient retry·green 승격·정직 verdict (§20).
import json
from pathlib import Path

import pytest

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_continue import (
    classify_failures,
    build_repair_plan,
    decide_promotion,
    load_continuation_base,
    run_continuation,
    _apply_continuation_files,
    _patch_with_retry,
)
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_core_schemas import PatchOutput
from repo_idea_miner.factory_desks import DeskError
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})

_BAD_LAYER = {"files": [{"path": "product/viewer/index.html",
                         "content": "<!-- replay viewer --><div>demo state</div>"}],
              "product_report": "replay 문자열만 있고 실제 소비 없음"}


def _make_base(tmp_path, overrides):
    llm = MockLLMClient(overrides={**mock_core_factory_overrides(), **overrides},
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


# ---------------------------------------------------------------- Failure Classifier 유닛 (§20-5,6,7,15,19)

def test_classify_golden_extra_field_requires_spec_repair():
    """§20-5,15: runner에 golden에 없는 키 → RUNNER_OUTPUT_EXTRA_FIELD + SPEC_REPAIR_REQUIRED."""
    golden_diff = {"status": "FAIL", "diffs": [
        {"scenario_id": "scenario_001", "diffs": ["final_state.edges: golden에 없는 키"]},
    ]}
    fs = classify_failures({}, golden_diff, {}, {}, {}, {}, product_layer_problems=[])
    types = {f["type"] for f in fs}
    assert "RUNNER_OUTPUT_EXTRA_FIELD" in types
    assert "GOLDEN_SCHEMA_MISMATCH" in types
    assert "SPEC_REPAIR_REQUIRED" in types  # golden frozen → spec repair 필요
    extra = next(f for f in fs if f["type"] == "RUNNER_OUTPUT_EXTRA_FIELD")
    assert extra["requires_spec_repair"] is True


def test_classify_invariant_not_exposed():
    """§20-6,19: not_exposed invariant → STATE_INVARIANT_NOT_EXPOSED (spec repair 불필요)."""
    inv = {"status": "FAIL", "not_exposed": [
        {"scenario_id": "s1", "invariant": "input_values.length >= 0",
         "message": "invariant 대상 필드 없음: input_values.length"}], "failed": []}
    fs = classify_failures({}, {}, inv, {}, {}, {}, product_layer_problems=[])
    t = next(f for f in fs if f["type"] == "STATE_INVARIANT_NOT_EXPOSED")
    assert t["repairable"] is True and t["requires_spec_repair"] is False


def test_classify_product_layer_not_consuming():
    """§20-7: product layer replay 미소비 → PRODUCT_LAYER_NOT_CONSUMING_REPLAY."""
    fs = classify_failures({}, {}, {}, {}, {}, {},
                           product_layer_problems=["product layer가 replay/ 산출물을 실제로 읽지 않음"])
    assert any(f["type"] == "PRODUCT_LAYER_NOT_CONSUMING_REPLAY" for f in fs)


def test_repair_plan_reflects_frozen_and_targets():
    """§20-8,9: repair_plan이 frozen_files를 반영하고 patchable failure만 step으로."""
    failures = [
        {"type": "PRODUCT_LAYER_NOT_CONSUMING_REPLAY", "evidence": "x",
         "repairable": True, "requires_spec_repair": False},
        {"type": "RUNNER_OUTPUT_EXTRA_FIELD", "evidence": "y",
         "repairable": True, "requires_spec_repair": True},
    ]
    plan = build_repair_plan(failures, ["src/", "product/"], ["golden/", "fixtures/"])
    assert plan["frozen_files"] == ["golden/", "fixtures/"]
    step_types = {s["failure_type"] for s in plan["steps"]}
    assert "PRODUCT_LAYER_NOT_CONSUMING_REPLAY" in step_types
    assert "RUNNER_OUTPUT_EXTRA_FIELD" not in step_types  # spec repair는 patch step 아님
    assert plan["requires_spec_repair"] is True


# ---------------------------------------------------------------- frozen/allowed patch (§20-10,11)

def test_apply_rejects_frozen_and_outside(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    entries = [
        {"path": "product/viewer/app.js", "content": "ok"},      # 허용
        {"path": "golden/expected_001.json", "content": "{}"},   # frozen
        {"path": "fixtures/scenario_001.json", "content": "{}"},  # frozen
        {"path": "core_contract.json", "content": "{}"},          # frozen
        {"path": "config/secret.txt", "content": "x"},            # 허용 밖
    ]
    written, rejected = _apply_continuation_files(ws, entries, ["src/", "product/"],
                                                  ["golden/", "fixtures/"], [])
    assert written == ["product/viewer/app.js"]
    assert set(rejected) == {"golden/expected_001.json", "fixtures/scenario_001.json",
                             "core_contract.json", "config/secret.txt"}
    assert not (ws / "golden").exists() and not (ws / "core_contract.json").exists()


# ---------------------------------------------------------------- transient retry (§20-12,13,14)

class _FakeExecutor:
    """continuation_patch 호출에서 지정 횟수만큼 transient 실패 후 성공/실패하는 가짜 executor."""

    def __init__(self, fail_n, succeed=True):
        self.fail_n = fail_n
        self.succeed = succeed
        self.calls = 0

    def call(self, schema_name, prompt, model_cls):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise DeskError("patch_repair: LLM 호출 실패 (transient): boom", kind="transient")
        if not self.succeed:
            raise DeskError("patch_repair: LLM 호출 실패 (transient): boom", kind="transient")
        return PatchOutput(files=[{"path": "product/v.js", "content": "ok"}],
                           patch_report="fixed"), "MOCK"


def test_patch_transient_retry_then_success():
    """§20-12,13: transient 1~2회 후 성공하면 patch 반환."""
    ex = _FakeExecutor(fail_n=2, succeed=True)
    patch, transient, err = _patch_with_retry(ex, "packet", "fail", {}, ["product/"], ["golden/"],
                                              1, 2, max_transient=2, sleep_fn=lambda s: None,
                                              log_fn=lambda r: None)
    assert patch is not None and err is None
    assert transient == 2 and ex.calls == 3


def test_patch_transient_final_failure_returns_none():
    """§20-14: 재시도 후에도 transient면 patch=None (→ NEEDS_MORE_GEMMA_LOOP 유지)."""
    ex = _FakeExecutor(fail_n=99, succeed=False)
    patch, transient, err = _patch_with_retry(ex, "packet", "fail", {}, ["product/"], ["golden/"],
                                              1, 2, max_transient=2, sleep_fn=lambda s: None,
                                              log_fn=lambda r: None)
    assert patch is None and err is not None
    assert transient == 2


# ---------------------------------------------------------------- decide_promotion (§20-24,25)

def _all_pass():
    return {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                              "state_invariant", "determinism", "anti_hardcode")}


def test_decide_promotion_green_when_all_pass_and_consumes():
    promo = decide_promotion(_all_pass(), product_consumes=True, hardcode_risk="low",
                             oracle_risk="low", failures=[], next_goal="g")
    assert promo["promoted_to_green_base"] is True and promo["new_verdict"] == "REVIEW_READY"


def test_decide_promotion_spec_repair_when_frozen_needed():
    gates = {**_all_pass(), "golden_output": False}
    failures = [{"type": "RUNNER_OUTPUT_EXTRA_FIELD", "requires_spec_repair": True}]
    promo = decide_promotion(gates, product_consumes=True, hardcode_risk="low",
                             oracle_risk="low", failures=failures, next_goal="g")
    assert promo["promoted_to_green_base"] is False
    assert promo["new_verdict"] == "SPEC_REPAIR_REQUIRED"


def test_decide_promotion_needs_more_when_patchable():
    gates = {**_all_pass(), "golden_output": False}
    failures = [{"type": "GOLDEN_SCHEMA_MISMATCH", "requires_spec_repair": False}]
    promo = decide_promotion(gates, product_consumes=True, hardcode_risk="low",
                             oracle_risk="low", failures=failures, next_goal="g")
    assert promo["new_verdict"] == "NEEDS_MORE_GEMMA_LOOP"


# ---------------------------------------------------------------- load / CANNOT_CONTINUE (§20-1,2,3)

def test_cannot_continue_without_base(tmp_path):
    """§20-2: continuation_base가 없으면 CANNOT_CONTINUE."""
    empty = tmp_path / "empty"
    empty.mkdir()
    res = run_continuation(base_run_dir=empty, mode="mock", output_dir=tmp_path / "runs",
                           settings=SETTINGS, factory_settings=FSET)
    assert res["status"] == "CANNOT_CONTINUE"
    assert "continuation_base 없음" in res["error"]


def test_cannot_continue_when_hardcode_high(tmp_path):
    """§20-3: hardcode risk high면 continuation 거부."""
    base = _make_base(tmp_path, {"product_layer": _BAD_LAYER, "product_layer_repair": _BAD_LAYER})
    ws = Path(base["run_dir"]) / "workspace"
    anti = json.loads((ws / "anti_hardcode_summary.json").read_text(encoding="utf-8"))
    anti["hardcode_risk"] = "high"
    (ws / "anti_hardcode_summary.json").write_text(json.dumps(anti), encoding="utf-8")
    base_info = load_continuation_base(Path(base["run_dir"]))
    assert not base_info["ok"] and "hardcode risk high" in base_info["problems"]


# ---------------------------------------------------------------- --run-dir 모드 식별자 backfill

def test_find_run_id_by_run_dir(tmp_path):
    """run 디렉터리 이름으로 product_runs 역조회 (--run-dir backfill용)."""
    from repo_idea_miner.factory_db import find_product_run_id_by_run_dir, open_factory_db, create_product_run

    db = open_factory_db(tmp_path / "t.db")
    try:
        create_product_run(db, 54, r"runs\factory_20260710_011833\workspace", "standard")
        rid2 = create_product_run(db, 54, "runs/factory_20260710_011833/workspace", "standard")
        assert find_product_run_id_by_run_dir(db, "runs/factory_20260710_011833") == rid2  # 최신 우선
        assert find_product_run_id_by_run_dir(db, Path("runs") / "factory_20260710_011833") == rid2
        assert find_product_run_id_by_run_dir(db, "runs/factory_none") is None
    finally:
        db.close()


def test_run_dir_mode_backfills_identifiers(tmp_path):
    """--run-dir 모드에서 base_run_id/challenge_id를 DB·산출물에서 역조회해 채운다."""
    from repo_idea_miner.factory_db import open_factory_db, create_product_run

    base = _make_base(tmp_path, {"product_layer": _BAD_LAYER, "product_layer_repair": _BAD_LAYER})
    base_dir = Path(base["run_dir"])
    db = open_factory_db(tmp_path / "t.db")
    try:
        base_id = create_product_run(db, 77, str(base_dir / "workspace"), "standard")
        res = run_continuation(base_run_dir=base_dir, mode="mock",
                               output_dir=tmp_path / "runs2", settings=SETTINGS,
                               factory_settings=FSET, db_conn=db)
        assert res["base_run_id"] == base_id
        assert res["challenge_id"] == 77
        summary = json.loads((Path(res["continuation_run_dir"])
                              / "continuation_run_summary.json").read_text(encoding="utf-8"))
        assert summary["base_run_id"] == base_id
        assert summary["challenge_id"] == 77
        promo = json.loads((Path(res["continuation_run_dir"])
                            / "green_base_promotion.json").read_text(encoding="utf-8"))
        assert promo["base_run_id"] == base_id
        assert promo["base_run_dir"]
    finally:
        db.close()


def test_run_dir_mode_without_db_keeps_dir_identifier(tmp_path):
    """DB 없이 --run-dir만 줘도 base_run_dir 식별자로 validate가 통과한다."""
    from repo_idea_miner.factory_validate import validate_continuation_run_dir

    base = _make_base(tmp_path, {"product_layer": _BAD_LAYER, "product_layer_repair": _BAD_LAYER})
    res = run_continuation(base_run_dir=base["run_dir"], mode="mock",
                           output_dir=tmp_path / "runs2", settings=SETTINGS, factory_settings=FSET)
    _ok, problems, _info = validate_continuation_run_dir(Path(res["continuation_run_dir"]), [])
    assert not any("base_run_id/base_run_dir" in p for p in problems)
    assert not any("base run 표시 없음" in p for p in problems)


# ---------------------------------------------------------------- E2E: product layer 수정 → green 승격 (§20-1,4,8,16,17,21~24,26,27)

@pytest.fixture(scope="module")
def pl_run(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("cont_pl")
    base = _make_base(tmp_path, {"product_layer": _BAD_LAYER, "product_layer_repair": _BAD_LAYER})
    assert base["continuation_base_path"], "product layer 실패 base가 continuation_base여야 함"
    res = run_continuation(base_run_dir=base["run_dir"], mode="mock",
                           output_dir=tmp_path / "runs", settings=SETTINGS, factory_settings=FSET)
    return base, res


def test_e2e_classifies_and_generates_artifacts(pl_run):
    """§20-4,8,26,27: failure/repair/green_promotion/phase17_dashboard 산출물 생성."""
    _, res = pl_run
    cd = Path(res["continuation_run_dir"])
    for name in ("failure_classification.json", "repair_plan.json", "gate_rerun_summary.json",
                 "product_layer_recheck.json", "green_base_promotion.json",
                 "phase17_dashboard_summary.json", "continuation_run_summary.json"):
        assert (cd / name).is_file(), name
    assert "PRODUCT_LAYER_NOT_CONSUMING_REPLAY" in res["failure_types"]


def test_e2e_product_layer_resolved_and_promoted(pl_run):
    """§20-1,16,17,23,24: product layer가 replay 소비하도록 고쳐지고 green_base로 승격."""
    _, res = pl_run
    assert res["resolved"].get("PRODUCT_LAYER_NOT_CONSUMING_REPLAY") is True
    assert res["patch_attempts"] == 1
    assert res["promoted_to_green_base"] is True
    assert res["verdict"] == "REVIEW_READY"
    assert res["green_base_path"] and Path(res["green_base_path"]).is_dir()
    recheck = json.loads((Path(res["continuation_run_dir"]) / "product_layer_recheck.json").read_text(encoding="utf-8"))
    assert recheck["consumes_replay_output"] is True


def test_e2e_gate_rerun_and_build_review(pl_run):
    """§20-21,22: patch 후 core gates 재실행 + build review 재계산."""
    _, res = pl_run
    cd = Path(res["continuation_run_dir"])
    gr = json.loads((cd / "gate_rerun_summary.json").read_text(encoding="utf-8"))
    assert gr["gates_passed"] == gr["gates_total"]
    assert (cd / "build_review.json").is_file()


def test_e2e_dashboard_summary_continuation_fields(pl_run):
    """§20-27: phase17_dashboard_summary에 continuation 표시 필드."""
    _, res = pl_run
    d = json.loads((Path(res["continuation_run_dir"]) / "phase17_dashboard_summary.json").read_text(encoding="utf-8"))
    assert d["is_continuation"] is True
    assert d["green_base"] is True
    assert d["continuation_resolved"].get("PRODUCT_LAYER_NOT_CONSUMING_REPLAY") is True


def test_e2e_secret_scan_clean(pl_run, fake_env):
    """§20-33: continuation 산출물에 secret 없음."""
    _, res = pl_run
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in Path(res["continuation_run_dir"]).rglob("*") if p.is_file())
    for secret in fake_env.values():
        assert secret not in blob


# ---------------------------------------------------------------- E2E: golden 실패 base → 정직 verdict 유지 (§20-25)

def test_e2e_golden_failure_stays_honest(tmp_path):
    """§20-25, §14.15: golden이 실패하는 base는 자동 patch로 못 고치면 정직하게 미승격."""
    from repo_idea_miner.factory_core_prompts import mock_broken_core_build_output

    broken = mock_broken_core_build_output()
    broken_patch = {"files": [f for f in broken["files"] if f["path"] == "src/core/engine.py"],
                    "patch_report": "여전히 깨진 patch"}
    base = _make_base(tmp_path, {"core_build": broken, "patch_repair": broken_patch})
    assert base["continuation_base_path"]
    res = run_continuation(base_run_dir=base["run_dir"], mode="mock",
                           output_dir=tmp_path / "runs", settings=SETTINGS, factory_settings=FSET)
    assert res["promoted_to_green_base"] is False
    assert res["verdict"] in ("NEEDS_MORE_GEMMA_LOOP", "SPEC_REPAIR_REQUIRED", "RUNS_BUT_WEAK")
    assert not (Path(res["continuation_run_dir"]) / "green_base.json").is_file()
