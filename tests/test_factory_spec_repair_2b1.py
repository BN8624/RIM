# Phase 2B-1 테스트: spec repair apply 단일 케이스 — dry-run/엄격 golden 보정/snapshot·rollback/invariant DSL 최소 보강/gate 재검증/validate (주문서 §18).
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_gates import (
    check_invariant,
    run_state_invariant_gate,
)
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_db import create_product_run, open_factory_db, update_product_run
from repo_idea_miner.factory_frozen import compute_frozen_hashes, write_frozen_hash_guard
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_continue import build_spec_repair_proposal, build_spec_repair_review
from repo_idea_miner.factory_spec_repair import (
    check_apply_preconditions,
    derive_scenario_decision,
    plan_scenario_repair,
    resolve_apply_target,
    run_spec_repair_apply,
)
from repo_idea_miner.factory_validate import _check_spec_repair_apply, validate_product_run_dir
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- §18-26~33: invariant DSL 최소 보강

def test_length_resolution_on_list_and_dict():
    """§18-27,28,29: <field>.length가 list/dict에서 해석된다."""
    state = {"nodes": [{"id": "a"}], "index": {"a": 1, "b": 2}, "tick": 0}
    assert check_invariant(state, "nodes.length >= 0")[0] is True
    assert check_invariant(state, "index.length >= 2")[0] is True
    assert check_invariant(state, "nodes.length >= 5")[0] is False  # 값 위반은 FAIL


def test_missing_path_not_passed():
    """§18-30: missing path는 PASS 처리하지 않는다 (empty와 구분)."""
    state = {"items": []}
    assert check_invariant(state, "items.length >= 0")[0] is True  # empty는 0으로 평가
    ok, msg = check_invariant(state, "ghost.length >= 0")
    assert ok is False and "필드 없음" in msg


def test_arbitrary_expression_not_evaluated():
    """§18-32,33: eval/predicate 언어는 평가하지 않는다 (기계 평가 불가)."""
    state = {"x": 1}
    assert check_invariant(state, "len(x) > 0")[0] is None
    assert check_invariant(state, "__import__('os').getcwd()")[0] is None
    assert check_invariant(state, "x > 0 and x < 5")[0] is None


_NODE_ENTITY_CONTRACT = {
    "state_entities": [
        {"name": "Node", "fields": ["id", "input_values", "output_values"],
         "invariants": ["input_values.length >= 0", "exists:id"]},
        {"name": "Edge", "fields": ["source_id", "target_id"],
         "invariants": ["exists:source_id", "exists:target_id"]},
        {"name": "GraphState", "fields": ["nodes", "edges", "global_tick"],
         "invariants": ["nodes.length >= 0", "edges.length >= 0", "global_tick >= 0"]},
    ]
}


def _replay(final_state):
    return {"s1": {"parsed": {"final_state": final_state}}}


def test_entity_invariants_resolved_from_collections():
    """§18-26,27: entity invariant가 dict-of-dicts/list 컬렉션 인스턴스에서 최소 해석된다."""
    fs = {
        "nodes": {"a": {"id": "a", "input_values": [1], "output_values": [2]}},
        "edges": [{"source_id": "a", "target_id": "b"}],
        "global_tick": 1,
    }
    result, summary = run_state_invariant_gate(_NODE_ENTITY_CONTRACT, _replay(fs))
    assert result.ok, result.problems
    assert summary["status"] == "PASS"
    assert summary["checked"] > 0


def test_entity_invariant_fail_vs_not_exposed():
    """§18-31: INVARIANT_FAIL과 INVARIANT_NOT_EXPOSED 구분 유지."""
    # global_tick 음수 → 값 위반 (FAIL)
    fs_fail = {"nodes": {}, "edges": [], "global_tick": -1}
    _, summary = run_state_invariant_gate(_NODE_ENTITY_CONTRACT, _replay(fs_fail))
    cats = {v["category"] for v in summary["violations"] if v["invariant"] == "global_tick >= 0"}
    assert cats == {"INVARIANT_FAIL"}
    # Node 인스턴스 컬렉션 자체가 없음 → NOT_EXPOSED 유지 (자동 PASS 금지)
    fs_missing = {"edges": [{"source_id": "a", "target_id": "b"}], "global_tick": 0}
    _, summary2 = run_state_invariant_gate(_NODE_ENTITY_CONTRACT, _replay(fs_missing))
    node_viol = [v for v in summary2["violations"] if v["invariant"] == "exists:id"]
    assert node_viol and node_viol[0]["category"] == "INVARIANT_NOT_EXPOSED"


# ---------------------------------------------------------------- §18-18~25: golden 보정 엄격 기준 (unit)

_CONTRACT_FIELDS = {"nodes", "edges", "execution_order", "global_tick"}


def _behind_golden():
    return {
        "scenario_id": "scenario_001", "comparison_mode": "exact",
        "expected_final_state": {"execution_order": ["a"], "global_tick": 1},
        "expected_events": ["node_created_event"],
        "expected_summary": "Execution completed successfully",
    }


def _replay_full():
    return {
        "ok": True,
        "final_state": {"execution_order": ["a"], "global_tick": 1,
                        "nodes": {"a": {"id": "a"}}, "edges": []},
        "events": [{"event": "node_created", "node_id": "a"}],
        "summary": "Completed", "errors": [],
    }


def test_golden_schema_repair_allowed():
    """§18-23,24: contract 필수 field 추가 + events/summary 정합은 허용된다."""
    entry = plan_scenario_repair(_behind_golden(), _replay_full(), _CONTRACT_FIELDS)
    assert not entry["blocked_reasons"]
    assert entry["new_golden"] is not None
    assert entry["comparison_mode"]["old"] == entry["comparison_mode"]["new"] == "exact"
    new_fs = entry["new_golden"]["expected_final_state"]
    assert "nodes" in new_fs and "edges" in new_fs
    assert entry["new_golden"]["expected_summary"] == "Completed"


def test_non_contract_field_addition_blocked():
    """§18-25: contract state field가 아닌 키(runner debug noise)는 golden 추가 금지."""
    replay = _replay_full()
    replay["final_state"]["debug_trace"] = ["x"]
    entry = plan_scenario_repair(_behind_golden(), replay, _CONTRACT_FIELDS)
    assert entry["new_golden"] is None
    assert any("debug_trace" in b and "noise" in b for b in entry["blocked_reasons"])


def test_value_tamper_blocked():
    """§8: 기존 기대값과 runner 값이 다르면 core 결함 — golden 수정으로 덮지 않는다."""
    golden = _behind_golden()
    golden["expected_final_state"]["global_tick"] = 99  # runner는 1을 냄
    entry = plan_scenario_repair(golden, _replay_full(), _CONTRACT_FIELDS)
    assert entry["new_golden"] is None
    assert any("기대값 훼손" in b for b in entry["blocked_reasons"])


def test_event_count_change_blocked():
    """§8: event 수 변경(축소/확대)은 차단된다."""
    replay = _replay_full()
    replay["events"] = replay["events"] + [{"event": "extra"}]
    entry = plan_scenario_repair(_behind_golden(), replay, _CONTRACT_FIELDS)
    assert entry["new_golden"] is None
    assert any("event 수 변경" in b for b in entry["blocked_reasons"])


def test_event_payload_value_tamper_blocked():
    """§8: event 종류가 같아도 payload 기대값 차이는 golden 교체로 덮지 않는다.

    runner가 결함으로 placeholder id를 내면(예: target_id 'system') 그 값이
    golden 기대값을 대체해선 안 된다 — final_state와 동일한 값 보호."""
    golden = {
        "scenario_id": "s3", "comparison_mode": "exact",
        "expected_final_state": {"execution_order": ["a"], "global_tick": 1},
        "expected_events": [{"type": "ERROR_OCCURRED", "target_id": "non_existent_id"}],
        "expected_summary": "Completed",
    }
    replay = {
        "ok": True,
        "final_state": {"execution_order": ["a"], "global_tick": 1},
        "events": [{"type": "ERROR_OCCURRED", "target_id": "system"}],
        "summary": "Completed", "errors": [],
    }
    entry = plan_scenario_repair(golden, replay, _CONTRACT_FIELDS)
    assert entry["new_golden"] is None
    assert any("expected_events[0].target_id" in b and "훼손" in b
               for b in entry["blocked_reasons"])


def test_event_kind_read_from_type_key():
    """dict event 종류는 'event' 키가 없으면 'type' 키로 판별한다 — 종류 불일치를 놓치지 않는다."""
    golden = {
        "scenario_id": "s4", "comparison_mode": "exact",
        "expected_final_state": {"execution_order": ["a"], "global_tick": 1},
        "expected_events": [{"type": "NODE_CREATED", "target_id": "a"}],
        "expected_summary": "Completed",
    }
    replay = {
        "ok": True,
        "final_state": {"execution_order": ["a"], "global_tick": 1},
        "events": [{"type": "NODE_DELETED", "target_id": "a"}],
        "summary": "Completed", "errors": [],
    }
    entry = plan_scenario_repair(golden, replay, _CONTRACT_FIELDS)
    assert entry["new_golden"] is None
    assert any("종류 불일치" in b for b in entry["blocked_reasons"])


def test_expected_field_deletion_blocked():
    """§18-22: 기존 expected field가 새 golden에서 사라지면 차단."""
    golden = _behind_golden()
    golden["expected_final_state"]["legacy_field"] = 1  # runner 출력에 없는 기존 기대 필드
    entry = plan_scenario_repair(golden, _replay_full(), _CONTRACT_FIELDS)
    assert entry["new_golden"] is None
    assert any("삭제" in b or "훼손" in b for b in entry["blocked_reasons"])


def test_partial_mode_keeps_final_state():
    """partial golden은 expected_final_state를 유지하고 events/summary schema만 정합."""
    golden = {
        "scenario_id": "s2", "comparison_mode": "partial",
        "expected_final_state": {"global_tick": 1},
        "expected_events": ["node_created_event"],
        "expected_summary": "Execution completed successfully",
    }
    entry = plan_scenario_repair(golden, _replay_full(), _CONTRACT_FIELDS)
    assert entry["new_golden"] is not None
    assert entry["new_golden"]["expected_final_state"] == {"global_tick": 1}
    assert entry["new_golden"]["comparison_mode"] == "partial"


def test_passing_golden_untouched():
    """이미 통과하는 golden은 변경하지 않는다."""
    replay = _replay_full()
    golden = {
        "scenario_id": "s1", "comparison_mode": "exact",
        "expected_final_state": json.loads(json.dumps(replay["final_state"])),
        "expected_events": json.loads(json.dumps(replay["events"])),
        "expected_summary": "Completed",
    }
    entry = plan_scenario_repair(golden, replay, _CONTRACT_FIELDS)
    assert entry["new_golden"] is None and not entry["blocked_reasons"]
    assert entry["changes"] == []


# ---------------------------------------------------------------- E2E fixture: mock run을 #47 상태로 재현

def _mock_base(tmp_path):
    llm = MockLLMClient(overrides=mock_core_factory_overrides(), call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


def _make_spec_repair_env(run_dir: Path) -> dict:
    """정상 run의 exact golden 하나를 뒤처지게 훼손하고 Phase 2A 산출물을 만든다."""
    ws = run_dir / "workspace"
    contract = _load(ws / "core_contract.json")
    fields = set()
    for e in contract.get("state_entities") or []:
        fields |= set(e.get("fields") or [])
    gpath = next(p for p in sorted((ws / "golden").glob("expected_*.json"))
                 if _load(p).get("comparison_mode") == "exact")
    golden = _load(gpath)
    key = next(k for k in golden["expected_final_state"] if k in fields)
    removed = golden["expected_final_state"].pop(key)
    golden["expected_summary"] = "OLD SUMMARY"
    _dump(gpath, golden)

    failures = [{"type": "GOLDEN_SCHEMA_MISMATCH", "evidence": "golden behind runner",
                 "repairable": True, "requires_spec_repair": True}]
    proposal = build_spec_repair_proposal(5, 47, failures, "low")
    review = build_spec_repair_review(proposal)
    _dump(run_dir / "spec_repair_proposal.json", proposal)
    _dump(run_dir / "spec_repair_review.json", review)
    _dump(run_dir / "phase2a_dashboard_summary.json", {
        "lane": "SPEC_REPAIR", "recommended_lane": "SPEC_REPAIR",
        "lane_reason": "golden schema mismatch", "lane_status": "제안서 생성됨, 적용은 보류",
        "base_run_id": 5, "challenge_id": 47, "current_verdict": "SPEC_REPAIR_REQUIRED",
        "proposal_generated": True, "review_generated": True, "apply_performed": False,
        "frozen_hash_status": "PASS", "risk_level": "low",
    })
    h = compute_frozen_hashes(ws, run_dir)
    write_frozen_hash_guard(run_dir, h, h)
    return {"golden_path": gpath, "removed_key": key, "removed_value": removed}


@pytest.fixture(scope="module")
def spec_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("spec2b1")
    base = _mock_base(tmp)
    run_dir = Path(base["run_dir"])
    meta = _make_spec_repair_env(run_dir)
    return {"tmp": tmp, "run_dir": run_dir, **meta}


def _clone(spec_env, tmp_path) -> Path:
    dst = tmp_path / "run"
    shutil.copytree(spec_env["run_dir"], dst)
    return dst


# ---------------------------------------------------------------- §18-1~11: dry-run / CLI 정책

def test_dry_run_generates_plan_without_modification(spec_env, tmp_path):
    """§18-1,4,5,12,46: dry-run은 plan만 만들고 파일을 수정하지 않는다."""
    run = _clone(spec_env, tmp_path)
    before = compute_frozen_hashes(run / "workspace", run)
    files_before = {p for p in run.rglob("*") if p.is_file()}
    out = run_spec_repair_apply(run_dir=run, apply=False, settings=SETTINGS, factory_settings=FSET)
    assert out["ok"] and out["status"] == "DRY_RUN_PASS"
    plan = _load(run / "spec_repair_apply_plan.json")
    assert plan["planned_files"], "보정 대상 golden이 계획에 있어야 함"
    assert plan["review_result"] == "APPROVE_FOR_PHASE2B"
    assert compute_frozen_hashes(run / "workspace", run) == before  # §18-5
    new_files = {p for p in run.rglob("*") if p.is_file()} - files_before
    assert {p.name for p in new_files} <= {"spec_repair_apply_plan.json", "spec_repair_apply_plan.md"}


def test_cli_dry_run_run_dir(spec_env, tmp_path, monkeypatch, capsys):
    """§18-1: CLI --run-dir --dry-run 동작 + resolved_run_dir 출력."""
    run = _clone(spec_env, tmp_path)
    monkeypatch.chdir(tmp_path)
    assert main(["factory-spec-repair-apply", "--run-dir", str(run), "--dry-run"]) == 0
    outp = capsys.readouterr().out
    assert "resolved_run_dir" in outp and "DRY_RUN_PASS" in outp


def test_cli_run_id_resolves_run_dir(spec_env, tmp_path, monkeypatch, capsys):
    """§18-2,3: --run-id 사용 시 resolved run_dir 출력."""
    run = _clone(spec_env, tmp_path)
    conn = open_factory_db(tmp_path / "c.db")
    rid = create_product_run(conn, 47, str(run / "workspace"), "standard")
    update_product_run(conn, rid, status="done", verdict="SPEC_REPAIR_REQUIRED")
    conn.close()
    monkeypatch.chdir(tmp_path)
    assert main(["factory-spec-repair-apply", "--run-id", str(rid), "--db", str(tmp_path / "c.db"),
                 "--dry-run"]) == 0
    outp = capsys.readouterr().out
    assert str(run) in outp  # resolved run_dir 출력


def test_apply_requires_target_and_no_all(tmp_path, monkeypatch):
    """§18-8,9,10: 대상 명시 필수, --all 금지(옵션 자체가 없음)."""
    monkeypatch.chdir(tmp_path)
    assert main(["factory-spec-repair-apply", "--apply"]) == 1  # 대상 없음
    with pytest.raises(SystemExit):
        main(["factory-spec-repair-apply", "--all"])
    with pytest.raises(SystemExit):
        main(["factory-spec-repair-apply", "--run-dir", "x", "--apply", "--limit", "2"])


def test_queue_spec_apply_still_forbidden(tmp_path, monkeypatch):
    """§18-11: queue 전체 spec apply 금지 유지 (--apply 옵션 없음)."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["factory-continue-queue", "--lane", "spec-repair", "--apply"])


def test_review_not_approved_blocks_apply(spec_env, tmp_path):
    """§18-6: review가 APPROVE_FOR_PHASE2B가 아니면 apply 거부."""
    run = _clone(spec_env, tmp_path)
    review = _load(run / "spec_repair_review.json")
    review["result"] = "NEEDS_REVISION"
    _dump(run / "spec_repair_review.json", review)
    out = run_spec_repair_apply(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "CANNOT_APPLY_SPEC_REPAIR"
    assert any("APPROVE_FOR_PHASE2B" in p for p in out["problems"])
    # 파일 미수정 확인
    g = _load(spec_env["golden_path"])
    assert g["expected_summary"] == "OLD SUMMARY"


def test_missing_proposal_cannot_apply(tmp_path):
    """§4: proposal/review 없는 디렉터리는 CANNOT_APPLY_SPEC_REPAIR."""
    run = tmp_path / "empty"
    (run / "workspace").mkdir(parents=True)
    out = run_spec_repair_apply(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "CANNOT_APPLY_SPEC_REPAIR"
    assert not (run / "spec_repair_apply_plan.json").exists()


def test_resolve_target_records_history(tmp_path):
    """§19-2: base_run_id와 continuation/history run id를 구분해 기록."""
    conn = open_factory_db(tmp_path / "c.db")
    base = tmp_path / "base"
    (base / "workspace").mkdir(parents=True)
    rid = create_product_run(conn, 47, str(base / "workspace"), "standard")
    cont = tmp_path / "cont"
    (cont / "workspace").mkdir(parents=True)
    _dump(cont / "continuation_run_summary.json", {"base_run_id": rid, "verdict": "SPEC_REPAIR_REQUIRED"})
    cid = create_product_run(conn, 47, str(cont / "workspace"), "standard")
    target, err, info = resolve_apply_target(run_id=rid, db_conn=conn)
    conn.close()
    assert err is None and target == base
    assert info["base_run_id"] == rid
    assert info["history_run_ids"] == [cid]


# ---------------------------------------------------------------- §18-12~17,34~37,44,46~49: apply E2E

@pytest.fixture(scope="module")
def applied(spec_env, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("applied")
    run = tmp / "run"
    shutil.copytree(spec_env["run_dir"], run)
    out = run_spec_repair_apply(run_dir=run, apply=True, mode="mock",
                                settings=SETTINGS, factory_settings=FSET)
    return {"run": run, "out": out, **{k: spec_env[k] for k in ("removed_key", "removed_value")}}


def test_apply_produces_artifacts(applied):
    """§18-12~16,47: plan/report/diff/snapshot/rollback_plan/hash 3종 생성."""
    run, out = applied["run"], applied["out"]
    assert out["ok"] and out["status"] == "APPLIED", out
    for rel in ("spec_repair_apply_plan.json", "spec_repair_apply_plan.md",
                "spec_repair_apply_report.json", "spec_repair_apply_report.md",
                "spec_repair_diff_summary.json", "pre_apply_snapshot_manifest.json",
                "rollback_plan.json", "frozen_hash_before_apply.json",
                "frozen_hash_after_apply.json", "frozen_hash_apply_check.json",
                "gate_rerun_after_spec_repair.json", "green_base_promotion_after_spec_repair.json",
                "phase2b1_dashboard_summary.json"):
        assert (run / rel).is_file(), rel
    check = _load(run / "frozen_hash_apply_check.json")
    assert check["status"] == "PASS" and not check["out_of_scope"]


def test_apply_repairs_golden_strictly(applied):
    """§18-23,48: 제거됐던 contract field가 복원되고 기존 값은 보존된다."""
    run, out = applied["run"], applied["out"]
    # applied_files 중 workspace golden 경로를 읽는다
    rel = next(f for f in out["applied_files"] if not f.startswith("final_artifact/"))
    golden = _load(run / "workspace" / rel)
    assert applied["removed_key"] in golden["expected_final_state"]
    assert golden["expected_final_state"][applied["removed_key"]] == applied["removed_value"]
    assert golden["comparison_mode"] == "exact"  # §18-19: 완화 없음
    assert golden["expected_summary"] != "OLD SUMMARY"
    diff = _load(run / "spec_repair_diff_summary.json")
    assert diff["comparison_mode_changes"] == []
    assert diff["deleted_expected_fields"] == []
    assert diff["scenario_count"]["before"] == diff["scenario_count"]["after"]


def test_apply_reruns_gates_and_validates(applied):
    """§18-34~37,44,49: gate 재실행 + product layer + build review + validate + green 재판정."""
    run, out = applied["run"], applied["out"]
    gr = _load(run / "gate_rerun_after_spec_repair.json")
    assert set(gr["gates"].keys()) >= {"core_contract", "runner", "scenario_replay",
                                       "golden_output", "state_invariant", "determinism",
                                       "anti_hardcode"}
    assert gr["gates_passed"] == gr["gates_total"], gr
    assert gr["product_layer_consumes_core"] is True
    assert gr["build_review_status"] is not None
    assert out["validate_ok"] is True
    promo = _load(run / "green_base_promotion_after_spec_repair.json")
    assert promo["promoted_to_green_base"] is True
    assert promo["new_verdict"] == "REVIEW_READY"
    assert (run / "green_base.json").is_file()


def test_applied_run_validates_end_to_end(applied):
    """§18-37: apply 후 factory-validate 전체 PASS."""
    ok, problems = validate_product_run_dir(applied["run"], [])
    assert ok, problems


def test_reapply_refused(applied):
    """이미 apply된 run은 재적용 거부."""
    out2 = run_spec_repair_apply(run_dir=applied["run"], apply=True,
                                 settings=SETTINGS, factory_settings=FSET)
    assert out2["status"] == "CANNOT_APPLY_SPEC_REPAIR"
    assert any("이미" in p for p in out2["problems"])


def test_apply_blocked_on_core_defect(spec_env, tmp_path):
    """§18-45: 기존 기대값과 runner 값이 다르면(코어 결함) apply가 차단되고 파일이 유지된다."""
    run = _clone(spec_env, tmp_path)
    gpath = run / "workspace" / "golden" / spec_env["golden_path"].name
    golden = _load(gpath)
    # runner 값과 다른 기대값을 심어 core 결함 상황 재현
    leaf_key = next(k for k in golden["expected_final_state"]
                    if isinstance(golden["expected_final_state"][k], (int, float)))
    golden["expected_final_state"][leaf_key] = 987654
    _dump(gpath, golden)
    before = compute_frozen_hashes(run / "workspace", run)
    out = run_spec_repair_apply(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "APPLY_BLOCKED"
    assert compute_frozen_hashes(run / "workspace", run) == before


def test_rollback_on_exception(spec_env, tmp_path, monkeypatch):
    """§18-17: apply 중 예외 발생 시 자동 rollback + rollback_report 생성."""
    import repo_idea_miner.factory_spec_repair as fsr

    run = _clone(spec_env, tmp_path)
    golden_before = (run / "workspace" / "golden" / spec_env["golden_path"].name).read_bytes()
    # 첫 호출(dry-run hash guard)은 통과시키고 apply 도중(try 내부) 호출에서 예외 발생
    real = fsr.compare_frozen_hashes
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("boom")
        return real(*a, **k)

    monkeypatch.setattr(fsr, "compare_frozen_hashes", flaky)
    out = run_spec_repair_apply(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "APPLY_ROLLED_BACK"
    assert out["rollback_executed"] is True
    report = _load(run / "rollback_report.json")
    assert report["executed"] is True and report["restored"]
    restored = (run / "workspace" / "golden" / spec_env["golden_path"].name).read_bytes()
    assert restored == golden_before


# ---------------------------------------------------------------- §18-38~43: validate 차단 규칙

def _fake_apply_run(tmp_path, **overrides) -> Path:
    """검증 규칙 테스트용 최소 apply 산출물 세트."""
    run = tmp_path / "fake"
    (run / "workspace").mkdir(parents=True)
    report = {
        "applied": True, "target_count": 1, "review_result": "APPROVE_FOR_PHASE2B",
        "resolved_run_dir": str(run), "applied_files": ["golden/expected_001.json"],
        "validate_ok": True,
    }
    report.update(overrides.get("report") or {})
    _dump(run / "spec_repair_apply_report.json", report)
    for rel in ("spec_repair_apply_plan.json", "pre_apply_snapshot_manifest.json",
                "rollback_plan.json", "frozen_hash_before_apply.json"):
        _dump(run / rel, {})
    _dump(run / "frozen_hash_after_apply.json", {})
    _dump(run / "frozen_hash_apply_check.json",
          overrides.get("check") or {"status": "PASS", "out_of_scope": []})
    _dump(run / "spec_repair_diff_summary.json", {
        "comparison_mode_changes": [], "deleted_expected_fields": [],
        "invariant_downgrades": [], "out_of_scope_changes": [],
        "scenario_count": {"before": 3, "after": 3},
        **(overrides.get("diff") or {}),
    })
    gates = {"core_contract": True, "runner": True, "scenario_replay": True,
             "golden_output": True, "state_invariant": True, "determinism": True,
             "anti_hardcode": True}
    gates.update(overrides.get("gates") or {})
    _dump(run / "gate_rerun_after_spec_repair.json", {"gates": gates})
    promo = {"promoted_to_green_base": True, "new_verdict": "REVIEW_READY", "validate_ok": True}
    promo.update(overrides.get("promo") or {})
    _dump(run / "green_base_promotion_after_spec_repair.json", promo)
    return run


def test_validate_clean_apply_passes(tmp_path):
    run = _fake_apply_run(tmp_path)
    assert _check_spec_repair_apply(run) == []


def test_validate_gate_fail_with_review_ready_fails(tmp_path):
    """§18-38,39: apply 후 gate fail + REVIEW_READY/green 승격 = FAIL."""
    run = _fake_apply_run(tmp_path, gates={"golden_output": False})
    problems = _check_spec_repair_apply(run)
    assert any("gate 실패" in p or "gate fail" in p for p in problems)


def test_validate_validate_fail_with_green_fails(tmp_path):
    """§18-40: validate fail + green_base = FAIL."""
    run = _fake_apply_run(tmp_path, promo={"validate_ok": False})
    problems = _check_spec_repair_apply(run)
    assert any("validate fail" in p for p in problems)


def test_validate_mode_loosening_fails(tmp_path):
    """§18-41: comparison_mode 완화 + REVIEW_READY = FAIL."""
    run = _fake_apply_run(tmp_path, diff={"comparison_mode_changes": [
        {"scenario_id": "s1", "old": "exact", "new": "partial"}]})
    problems = _check_spec_repair_apply(run)
    assert any("comparison_mode" in p for p in problems)


def test_validate_field_deletion_fails(tmp_path):
    """§18-42: golden expected field 삭제 + REVIEW_READY = FAIL."""
    run = _fake_apply_run(tmp_path, diff={"deleted_expected_fields": ["final_state.nodes"]})
    problems = _check_spec_repair_apply(run)
    assert any("field 삭제" in p for p in problems)


def test_validate_invariant_downgrade_fails(tmp_path):
    """§18-43: invariant warning화 + REVIEW_READY = FAIL."""
    run = _fake_apply_run(tmp_path, diff={"invariant_downgrades": ["nodes.length >= 0 → warning"]})
    problems = _check_spec_repair_apply(run)
    assert any("warning" in p for p in problems)


def test_validate_out_of_scope_and_target_count(tmp_path):
    """§17: 범위 밖 변경/다중 대상 차단."""
    run = _fake_apply_run(tmp_path, check={"status": "FAIL", "out_of_scope": ["fixtures/x.json"]})
    assert any("범위 밖" in p for p in _check_spec_repair_apply(run))
    run2 = _fake_apply_run(tmp_path / "t2", report={"target_count": 2})
    assert any("단일 대상" in p for p in _check_spec_repair_apply(run2))


def test_validate_unapproved_review_fails(tmp_path):
    """§17: review result가 APPROVE_FOR_PHASE2B가 아니었으면 FAIL."""
    run = _fake_apply_run(tmp_path, report={"review_result": "REQUIRES_HUMAN_REVIEW"})
    assert any("APPROVE_FOR_PHASE2B" in p for p in _check_spec_repair_apply(run))


# ---------------------------------------------------------------- 이슈 #5 §5.3: scenario 단위 partial spec repair

def _inject_core_conflict(run: Path, skip_name: str) -> Path:
    """다른 golden 하나를 replay 기반 exact로 바꾸고 leaf 값 하나를 충돌시킨다.

    runner 출력과 기대값이 실질 충돌하는 §8 차단 상황(core 결함과 얽힘)을 재현한다."""
    others = [p for p in sorted((run / "workspace" / "golden").glob("expected_*.json"))
              if p.name != skip_name]
    assert others, "충돌을 주입할 두 번째 golden이 필요"
    path = others[0]
    golden = _load(path)
    sid = golden.get("scenario_id") or path.stem.replace("expected_", "scenario_")
    replay = _load(run / "workspace" / "replay" / f"replay_{sid}.json")
    fs = json.loads(json.dumps(replay["final_state"]))

    def _tamper(node) -> bool:
        for k, v in node.items():
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                node[k] = 987654
                return True
            if isinstance(v, str):
                node[k] = v + "_CONFLICT"
                return True
            if isinstance(v, dict) and _tamper(v):
                return True
        return False

    assert _tamper(fs), "충돌시킬 leaf 값이 필요"
    golden.update(comparison_mode="exact", expected_final_state=fs,
                  expected_events=json.loads(json.dumps(replay.get("events") or [])),
                  expected_summary=replay.get("summary") or "")
    _dump(path, golden)
    return path


def test_dry_run_partial_status(spec_env, tmp_path):
    """§5.3: 적용 가능 scenario와 core 충돌 scenario가 공존하면 DRY_RUN_PARTIAL."""
    run = _clone(spec_env, tmp_path)
    _inject_core_conflict(run, spec_env["golden_path"].name)
    out = run_spec_repair_apply(run_dir=run, apply=False, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "DRY_RUN_PARTIAL"
    plan = _load(run / "spec_repair_apply_plan.json")
    assert plan["planned_files"] and plan["blocked_reasons"]
    decisions = {d["decision"] for d in plan["scenario_decisions"]}
    assert "APPLIED" in decisions and "DEFERRED_CORE_DEPENDENCY" in decisions


def test_partial_apply_scenario_decisions(spec_env, tmp_path):
    """§5.3~5.4: 독립 golden defect만 APPLIED, core 충돌 scenario는 DEFERRED로 보존.

    deferred가 남으면 green 승격 금지 — 일부 적용을 전체 성공으로 오인하지 않는다."""
    run = _clone(spec_env, tmp_path)
    conflict_path = _inject_core_conflict(run, spec_env["golden_path"].name)
    conflict_bytes = conflict_path.read_bytes()

    out = run_spec_repair_apply(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "APPLIED_PARTIAL"
    assert out["applied"] is True
    assert out["deferred_scenarios"]

    # 차단 golden은 그대로, 뒤처진 golden만 보정
    assert conflict_path.read_bytes() == conflict_bytes
    fixed = _load(run / "workspace" / "golden" / spec_env["golden_path"].name)
    assert spec_env["removed_key"] in fixed["expected_final_state"]

    decs = _load(run / "spec_repair_scenario_decisions.json")
    applied = [d for d in decs["decisions"] if d["decision"] == "APPLIED"]
    deferred = [d for d in decs["decisions"] if d["decision"] == "DEFERRED_CORE_DEPENDENCY"]
    assert applied and all(d["applied"] for d in applied)
    assert deferred and all(not d["applied"] and d["core_dependency"] for d in deferred)
    for d in deferred:
        assert d["reason_code"] == "VALUE_CONFLICT_WITH_RUNNER"
        assert d["evidence_refs"]

    promo = _load(run / "green_base_promotion_after_spec_repair.json")
    assert promo["promoted_to_green_base"] is False
    report = _load(run / "spec_repair_apply_report.json")
    assert report["partial_apply"] is True
    assert report["applied_scenarios"] and report["deferred_scenarios"]
    # validator가 partial 정합(결정 파일 존재, applied 일치, 승격 금지)을 통과시킨다
    assert _check_spec_repair_apply(run) == []


def test_scenario_decision_ambiguous_and_unchanged():
    """§5.3: replay evidence가 없으면 DEFERRED_AMBIGUOUS, 이미 유효하면 UNCHANGED_VALID."""
    fields = {"global_tick"}
    golden = {"scenario_id": "sX", "comparison_mode": "exact",
              "expected_final_state": {"global_tick": 1},
              "expected_events": [], "expected_summary": ""}
    entry = plan_scenario_repair(golden, None, fields)
    d = derive_scenario_decision(entry, golden, None)
    assert d["decision"] == "DEFERRED_AMBIGUOUS"
    assert d["reason_code"] == "NO_REPLAY_EVIDENCE"
    assert d["applied"] is False

    replay = {"ok": True, "final_state": {"global_tick": 1}, "events": [], "summary": ""}
    golden2 = {"scenario_id": "sY", "comparison_mode": "exact",
               "expected_final_state": {"global_tick": 1},
               "expected_events": [], "expected_summary": ""}
    entry2 = plan_scenario_repair(golden2, replay, fields)
    d2 = derive_scenario_decision(entry2, golden2, replay)
    assert d2["decision"] == "UNCHANGED_VALID"
    assert d2["reason_code"] == "ALREADY_PASSING"


def test_child_copy_inherits_apply_report_without_false_mismatch(applied, tmp_path):
    """child copy는 parent의 apply report를 계보(child_run_origin)로 승계한다 — 오탐 금지.

    origin이 없거나 다른 run을 가리키면 여전히 불일치로 잡는다."""
    import shutil as _shutil

    parent = applied["run"]
    child = tmp_path / "child_copy"
    _shutil.copytree(parent, child)
    _dump(child / "child_run_origin.json",
          {"parent_run_dir": str(parent).replace("\\", "/")})
    assert not [p for p in _check_spec_repair_apply(child) if "resolved_run_dir" in p]

    _dump(child / "child_run_origin.json", {"parent_run_dir": "runs/other_run"})
    assert any("resolved_run_dir" in p for p in _check_spec_repair_apply(child))
