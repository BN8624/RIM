# Phase 2A 테스트: continuation queue 정책·lane routing·safe patch lane·spec repair proposal-only·frozen hash guard·validate (주문서 §12).
import json
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_continue import (
    LANE_EXCLUDED,
    LANE_PATCH,
    LANE_REVIEW_ONLY,
    LANE_SPEC_REPAIR,
    decide_patch_result,
    lane_for_verdict,
    run_continuation,
)
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_db import create_product_run, open_factory_db, update_product_run
from repo_idea_miner.factory_frozen import compute_frozen_hashes, write_frozen_hash_guard
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_continue import (
    assess_failure_patch_safety,
    build_spec_repair_proposal,
    build_spec_repair_review,
)
from repo_idea_miner.factory_queue import (
    DRY_RUN_DEFAULT_LIMIT,
    EXECUTE_MAX_LIMIT,
    SPEC_REPAIR_ALLOWED_OUTPUTS,
    classify_candidate,
    decide_lane_for_run,
    discover_candidates,
    resolve_queue_policy,
    run_continuation_queue,
    run_spec_repair_readonly,
    sort_and_prioritize,
)
from repo_idea_miner.factory_validate import validate_continuation_run_dir, validate_product_run_dir
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})

_BAD_LAYER = {"files": [{"path": "product/viewer/index.html",
                         "content": "<!-- replay viewer --><div>demo state</div>"}],
              "product_report": "replay 문자열만 있고 실제 소비 없음"}


# ---------------------------------------------------------------- fixture helpers

def _ok_base(next_goal="expose invariant fields"):
    return {"ok": True, "problems": [], "base_json": {"next_goal": next_goal},
            "dashboard": {}, "hardcode_risk": "low", "oracle_risk": "low"}


def _fake_base_run(root: Path, name: str, verdict="NEEDS_MORE_GEMMA_LOOP",
                   next_goal="expose invariant", artifact_class="RULE_ENGINE",
                   oracle="low") -> Path:
    """discovery/spec repair 테스트용 최소 base run 디렉터리."""
    run = root / name
    ws = run / "workspace"
    for d in ("golden", "fixtures", "src"):
        (ws / d).mkdir(parents=True)
    (ws / "core_contract.json").write_text('{"state_fields": []}', encoding="utf-8")
    (ws / "runner_contract.json").write_text(
        json.dumps({"runner_command": "python src/run.py"}), encoding="utf-8")
    (ws / "golden" / "expected_001.json").write_text('{"a": 1}', encoding="utf-8")
    (ws / "fixtures" / "scenario_001.json").write_text('{"id": "s1"}', encoding="utf-8")
    (run / "continuation_base.json").write_text(json.dumps({
        "base_type": "continuation_base", "next_goal": next_goal,
        "allowed_touch_files": ["src/", "product/"],
        "frozen_files": ["core_contract.json", "runner_contract.json", "fixtures/", "golden/"],
    }), encoding="utf-8")
    (run / "dashboard_summary.json").write_text(json.dumps({
        "verdict": verdict, "artifact_class": artifact_class,
        "hardcode_risk": "low", "oracle_risk_level": oracle,
    }), encoding="utf-8")
    (run / "harness_summary.json").write_text("{}", encoding="utf-8")
    (run / "oracle_risk_report.json").write_text(json.dumps({"risk_level": oracle}), encoding="utf-8")
    return run


_SPEC_FAILURES = [
    {"type": "GOLDEN_SCHEMA_MISMATCH",
     "evidence": "golden expected schema disagrees with runner output (golden behind runner)",
     "repairable": True, "requires_spec_repair": True},
    {"type": "STATE_INVARIANT_NOT_EXPOSED",
     "evidence": "invariant DSL이 final_state 구조를 해석하지 못함",
     "repairable": True, "requires_spec_repair": False},
    {"type": "SPEC_REPAIR_REQUIRED", "evidence": "golden update needed",
     "repairable": False, "requires_spec_repair": True},
]


def _fake_continuation_run(root: Path, name: str, base_run_id: int, challenge_id=47,
                           verdict="SPEC_REPAIR_REQUIRED", failures=None) -> Path:
    d = root / name
    (d / "workspace").mkdir(parents=True)
    (d / "continuation_run_summary.json").write_text(json.dumps({
        "base_run_id": base_run_id, "challenge_id": challenge_id, "verdict": verdict,
        "base_run_dir": "runs/base", "promoted_to_green_base": False,
        "failure_types": [f["type"] for f in (failures or _SPEC_FAILURES)],
        "resolved": {}, "patch_attempts": 2, "transient_retries": 0, "rejected_patches": [],
        "requires_spec_repair": verdict == "SPEC_REPAIR_REQUIRED",
    }), encoding="utf-8")
    (d / "failure_classification.json").write_text(json.dumps({
        "base_run_id": base_run_id, "challenge_id": challenge_id,
        "failure_types": failures or _SPEC_FAILURES,
    }), encoding="utf-8")
    return d


# ---------------------------------------------------------------- §12-1~7: CLI 정책

def test_dry_run_default_limit_20():
    """§12-2: dry-run 기본 limit 20."""
    err, limit, op = resolve_queue_policy(None, execute=False, proposal_only=False, limit=None)
    assert err is None and op == "dry-run" and limit == DRY_RUN_DEFAULT_LIMIT == 20


def test_execute_default_and_max_limit_1():
    """§12-3: execute 기본/최대 limit 1."""
    err, limit, op = resolve_queue_policy("patch", execute=True, proposal_only=False, limit=None)
    assert err is None and op == "execute" and limit == 1 == EXECUTE_MAX_LIMIT
    err2, _, _ = resolve_queue_policy("patch", execute=True, proposal_only=False, limit=2)
    assert err2 is not None  # §12-6


def test_execute_requires_patch_lane():
    """§12-7: spec-repair lane에는 --execute 불허."""
    err, _, _ = resolve_queue_policy("spec-repair", execute=True, proposal_only=False, limit=1)
    assert err is not None
    err2, _, _ = resolve_queue_policy(None, execute=True, proposal_only=False, limit=1)
    assert err2 is not None


def test_unbounded_limit_rejected():
    """§11 금지: --limit 999."""
    err, _, _ = resolve_queue_policy(None, execute=False, proposal_only=False, limit=999)
    assert err is not None


def test_cli_queue_policy_enforced(tmp_path, monkeypatch):
    """§12-1,4: CLI에서 dry-run은 동작하고 금지 조합은 거부된다."""
    monkeypatch.chdir(tmp_path)
    assert main(["factory-continue-queue", "--lane", "spec-repair", "--execute"]) == 1
    assert main(["factory-continue-queue", "--lane", "patch", "--execute", "--limit", "2"]) == 1
    assert main(["factory-continue-queue", "--limit", "999"]) == 1
    assert main(["factory-continue-queue", "--dry-run"]) == 0
    assert (tmp_path / "runs" / "continuation_queue.json").is_file()  # §12-1


def test_cli_has_no_apply_flag(tmp_path, monkeypatch, capsys):
    """§11 금지: --lane spec-repair --apply는 존재하지 않는 옵션이라 argparse가 거부."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["factory-continue-queue", "--lane", "spec-repair", "--apply"])


# ---------------------------------------------------------------- §12-14~20,26~31: lane 분류

def test_needs_more_gemma_loop_routes_to_patch():
    """§12-14: NEEDS_MORE_GEMMA_LOOP + patch-safe failure → PATCH_CONTINUATION."""
    failures = [{"type": "PRODUCT_LAYER_NOT_CONSUMING_REPLAY", "evidence": "x",
                 "repairable": True, "requires_spec_repair": False}]
    d = decide_lane_for_run("NEEDS_MORE_GEMMA_LOOP", failures, _ok_base())
    assert d["recommended_lane"] == LANE_PATCH
    assert d["can_patch"] is True and d["can_continue"] is True


def test_spec_repair_required_routes_to_spec():
    """§12-15: SPEC_REPAIR_REQUIRED → SPEC_REPAIR, can_patch=false."""
    d = decide_lane_for_run("SPEC_REPAIR_REQUIRED", _SPEC_FAILURES, _ok_base())
    assert d["recommended_lane"] == LANE_SPEC_REPAIR
    assert d["can_patch"] is False and d["can_continue"] is True
    assert "golden schema mismatch" in d["reason"]
    assert "invariant DSL issue" in d["reason"]


@pytest.mark.parametrize("verdict", ["REVIEW_READY", "PROMOTE_TO_CODEX", "KEEP_CANDIDATE"])
def test_review_verdicts_are_review_only(verdict):
    """§12-16: REVIEW_READY 계열은 REVIEW_ONLY (queue 대상 아님)."""
    d = decide_lane_for_run(verdict, [], _ok_base())
    assert d["recommended_lane"] == LANE_REVIEW_ONLY
    assert d["can_continue"] is False


@pytest.mark.parametrize("verdict", ["RUNS_BUT_WEAK", "DROP"])
def test_weak_and_drop_excluded(verdict):
    """§12-17,18: RUNS_BUT_WEAK/DROP → EXCLUDED."""
    d = decide_lane_for_run(verdict, [], _ok_base())
    assert d["recommended_lane"] == LANE_EXCLUDED
    assert verdict in d["blocking_reason"]


def test_high_risk_and_missing_base_excluded():
    """§12-19,20,21: hardcode/oracle high, continuation_base 없음 → EXCLUDED."""
    for problem in ("hardcode risk high", "oracle risk high", "continuation_base 없음"):
        base = {"ok": False, "problems": [problem], "base_json": None,
                "dashboard": {}, "hardcode_risk": "low", "oracle_risk": "low"}
        d = decide_lane_for_run("NEEDS_MORE_GEMMA_LOOP", [], base)
        assert d["recommended_lane"] == LANE_EXCLUDED
        assert problem in d["blocking_reason"]


def test_viewer_only_and_missing_next_goal_excluded():
    """§3.3: viewer-only 산출물·next_goal 없음 → EXCLUDED."""
    d = decide_lane_for_run("NEEDS_MORE_GEMMA_LOOP", [], _ok_base(), artifact_class="VIEWER_ONLY")
    assert d["recommended_lane"] == LANE_EXCLUDED
    d2 = decide_lane_for_run("NEEDS_MORE_GEMMA_LOOP", [], _ok_base(next_goal=""))
    assert d2["recommended_lane"] == LANE_EXCLUDED


def test_golden_schema_mismatch_defaults_to_spec_repair():
    """§12-27: GOLDEN_SCHEMA_MISMATCH는 기본 SPEC_REPAIR."""
    failures = [{"type": "GOLDEN_SCHEMA_MISMATCH",
                 "evidence": "golden behind runner", "repairable": True,
                 "requires_spec_repair": False}]
    d = decide_lane_for_run("NEEDS_MORE_GEMMA_LOOP", failures, _ok_base())
    assert d["recommended_lane"] == LANE_SPEC_REPAIR


def test_extra_field_patchable_only_on_contract_violation():
    """§12-28: runner_contract 위반이 명확한 RUNNER_OUTPUT_EXTRA_FIELD만 patch."""
    kind, _ = assess_failure_patch_safety({
        "type": "RUNNER_OUTPUT_EXTRA_FIELD",
        "evidence": "runner output violates runner_contract required_output_fields"})
    assert kind == "patch"
    kind2, _ = assess_failure_patch_safety({
        "type": "RUNNER_OUTPUT_EXTRA_FIELD",
        "evidence": "runner output has fields not present in frozen golden",
        "requires_spec_repair": True})
    assert kind2 == "spec"


def test_invariant_patch_only_when_exposure_only():
    """§12-29,30: exposure-only invariant만 patch, DSL/contract 문제는 SPEC_REPAIR."""
    kind, _ = assess_failure_patch_safety({
        "type": "STATE_INVARIANT_NOT_EXPOSED",
        "evidence": "contract invariants not exposed in runner final_state: x.y"})
    assert kind == "patch"
    kind2, _ = assess_failure_patch_safety({
        "type": "STATE_INVARIANT_NOT_EXPOSED",
        "evidence": "invariant DSL이 final_state 구조를 해석하지 못함"})
    assert kind2 == "spec"


def test_product_layer_failure_is_patch_safe():
    """§12-31: PRODUCT_LAYER_NOT_CONSUMING_REPLAY는 patch lane 가능."""
    kind, _ = assess_failure_patch_safety({
        "type": "PRODUCT_LAYER_NOT_CONSUMING_REPLAY", "evidence": "제품 레이어 미소비"})
    assert kind == "patch"


def test_unclear_failure_excluded():
    """§3.3: 좁은 원인이 아닌 replay/determinism 실패는 patch 안전 범위 밖 → EXCLUDED."""
    failures = [{"type": "SCENARIO_REPLAY_FAILURE", "evidence": "scenario replay failed: ['s1']",
                 "repairable": True, "requires_spec_repair": False}]
    d = decide_lane_for_run("NEEDS_MORE_GEMMA_LOOP", failures, _ok_base())
    assert d["recommended_lane"] == LANE_EXCLUDED
    kind, _ = assess_failure_patch_safety({
        "type": "DETERMINISM_FAILURE", "evidence": "non-deterministic output: ['src/a.js: Math.random 사용']"})
    assert kind == "patch"


def test_lane_for_verdict_mapping():
    """§4.10: verdict → lane 매핑."""
    assert lane_for_verdict("REVIEW_READY") == LANE_REVIEW_ONLY
    assert lane_for_verdict("SPEC_REPAIR_REQUIRED") == LANE_SPEC_REPAIR
    assert lane_for_verdict("NEEDS_MORE_GEMMA_LOOP") == LANE_PATCH
    assert lane_for_verdict("NEEDS_MORE_GEMMA_LOOP", requires_spec_repair=True) == LANE_SPEC_REPAIR
    assert lane_for_verdict("DROP") == LANE_EXCLUDED


def test_decide_patch_result_states():
    """§6.5: patch 결과 상태 매핑."""
    assert decide_patch_result(True, "REVIEW_READY", {}) == "PATCH_GREEN"
    assert decide_patch_result(False, "SPEC_REPAIR_REQUIRED", {}) == "PATCH_BLOCKED_SPEC"
    assert decide_patch_result(False, "NEEDS_MORE_GEMMA_LOOP", {"A": True, "B": False}) == "PATCH_PROGRESS"
    assert decide_patch_result(False, "NEEDS_MORE_GEMMA_LOOP", {"A": False}) == "PATCH_FAILED"


# ---------------------------------------------------------------- §12-8~13: discovery + queue entry

@pytest.fixture()
def queue_db(tmp_path):
    """DB 2건(base + continuation 이력) + fs 전용 run 1건을 가진 환경."""
    runs = tmp_path / "runs"
    runs.mkdir()
    conn = open_factory_db(tmp_path / "c.db")
    base = _fake_base_run(runs, "base47")
    rid = create_product_run(conn, 47, str(base / "workspace"), "standard")
    update_product_run(conn, rid, status="done", verdict="NEEDS_MORE_GEMMA_LOOP")
    cont = _fake_continuation_run(runs, "cont47", base_run_id=rid)
    cid = create_product_run(conn, 47, str(cont / "workspace"), "standard")
    update_product_run(conn, cid, status="done", verdict="SPEC_REPAIR_REQUIRED")
    fs_only = _fake_base_run(runs, "fsonly", verdict="RUNS_BUT_WEAK")
    yield conn, runs, rid, base, cont, fs_only
    conn.close()


def test_discovery_db_first_and_fs_fallback(queue_db):
    """§12-9,10,11,13: DB 우선 discovery + fs fallback + run_id dedupe."""
    conn, runs, rid, base, cont, fs_only = queue_db
    candidates, history = discover_candidates(conn, runs)
    ids = [(c["run_id"], c["source"]) for c in candidates]
    assert (rid, "db") in ids
    assert (None, "filesystem") in ids  # fs 전용 run
    assert len([c for c in candidates if c["run_id"] == rid]) == 1  # dedupe
    # continuation run은 후보가 아니라 base의 이력으로 붙는다
    assert rid in history and len(history[rid]) == 1


def test_no_new_db_tables(queue_db):
    """§12-12: queue 실행이 새 DB 테이블/스키마를 만들지 않는다."""
    conn, runs, *_ = queue_db

    def tables():
        return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    before = tables()
    out = run_continuation_queue(db_path=None, db_conn=conn, output_dir=runs)
    assert out["ok"]
    assert tables() == before


def test_queue_entry_structure_and_lane(queue_db):
    """§12-8,50: entry에 recommended_lane 포함, #47 계열은 SPEC_REPAIR로 분류."""
    conn, runs, rid, *_ = queue_db
    out = run_continuation_queue(db_path=None, db_conn=conn, output_dir=runs)
    entry = next(e for e in out["entries"] if e["run_id"] == rid)
    for key in ("run_id", "challenge_id", "current_verdict", "recommended_lane", "can_continue",
                "can_patch", "reason", "blocking_reason", "risk_level", "priority"):
        assert key in entry
    # continuation 이력의 최신 verdict(SPEC_REPAIR_REQUIRED)를 현재 verdict로 쓴다
    assert entry["current_verdict"] == "SPEC_REPAIR_REQUIRED"
    assert entry["recommended_lane"] == LANE_SPEC_REPAIR
    assert entry["can_patch"] is False
    assert entry["priority"] == 1
    assert (runs / "continuation_queue.json").is_file()
    assert (runs / "continuation_queue.md").is_file()


def test_priority_prefers_history_and_actionable_verdict():
    """§4.2 우선순위: continuation 이력 run이 최상위."""
    entries = [
        {"run_id": 1, "current_verdict": "NEEDS_MORE_GEMMA_LOOP", "recommended_lane": LANE_PATCH,
         "has_continuation_history": False, "live_validation": False, "risk_level": "low",
         "failure_types": [], "priority": None},
        {"run_id": 2, "current_verdict": "SPEC_REPAIR_REQUIRED", "recommended_lane": LANE_SPEC_REPAIR,
         "has_continuation_history": True, "live_validation": True, "risk_level": "medium",
         "failure_types": ["GOLDEN_SCHEMA_MISMATCH"], "priority": None},
    ]
    ordered = sort_and_prioritize(entries)
    assert ordered[0]["run_id"] == 2 and ordered[0]["priority"] == 1
    assert ordered[1]["priority"] == 2


# ---------------------------------------------------------------- §12-37,54,55: patch 대상 없음

def test_no_patch_eligible_when_only_spec_repair(queue_db):
    """§12-54,55: #47 계열(SPEC_REPAIR)만 있으면 patch execute는 NO_PATCH_ELIGIBLE."""
    conn, runs, *_ = queue_db
    snapshot = {str(p) for p in runs.rglob("*")}
    out = run_continuation_queue(db_path=None, db_conn=conn, output_dir=runs,
                                 lane="patch", execute=True, limit=1)
    assert out["ok"] and out["status"] == "NO_PATCH_ELIGIBLE"
    assert out["executed"] == []
    # §12-37: queue 출력 외에는 아무 파일도 만들거나 수정하지 않음
    new_files = {str(p) for p in runs.rglob("*")} - snapshot
    assert new_files <= {str(runs / "continuation_queue.json"), str(runs / "continuation_queue.md")}


# ---------------------------------------------------------------- §12-38~44,51~53: spec repair lane (read-only)

def test_spec_repair_proposal_only_readonly(queue_db, monkeypatch):
    """§12-38~44,51,52,53: proposal/review 생성, apply 없음, frozen hash unchanged, read-only."""
    conn, runs, rid, base, cont, _ = queue_db

    # §12-39: patch writer/edit helper가 호출되면 즉시 실패하도록 감시
    import repo_idea_miner.factory_workspace as fw
    monkeypatch.setattr(fw, "write_workspace_file",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("patch writer 호출됨")))
    monkeypatch.setattr(fw, "apply_file_entries",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("apply 호출됨")))

    golden_before = (base / "workspace" / "golden" / "expected_001.json").read_bytes()
    files_before = {p for p in base.rglob("*") if p.is_file()}

    out = run_continuation_queue(db_path=None, db_conn=conn, output_dir=runs,
                                 lane="spec-repair", proposal_only=True, limit=1)
    assert out["ok"] and out["status"] == "PROPOSAL_ONLY"
    assert len(out["proposals"]) == 1
    res = out["proposals"][0]
    assert res["apply_performed"] is False
    assert res["frozen_hash_status"] == "PASS"  # §12-44,53

    prop = json.loads((base / "spec_repair_proposal.json").read_text(encoding="utf-8"))
    assert prop["apply_allowed_in_phase2a"] is False  # §12-42
    assert prop["repair_type"] in ("golden_schema", "invariant_dsl", "comparison_mode", "scenario_expected")
    review = json.loads((base / "spec_repair_review.json").read_text(encoding="utf-8"))
    assert review["result"] in ("APPROVE_FOR_PHASE2B", "NEEDS_REVISION", "REJECT", "REQUIRES_HUMAN_REVIEW")
    assert review["apply_performed"] is False  # §12-43

    # frozen 파일 불변 (§12-53) + 신규 파일은 허용 목록만 (§4.5)
    assert (base / "workspace" / "golden" / "expected_001.json").read_bytes() == golden_before
    new_files = {p for p in base.rglob("*") if p.is_file()} - files_before
    assert {p.name for p in new_files} <= set(SPEC_REPAIR_ALLOWED_OUTPUTS)
    for name in ("frozen_hash_before.json", "frozen_hash_after.json", "frozen_hash_check.json"):
        assert (base / name).is_file()  # §12-24,44
    p2a = json.loads((base / "phase2a_dashboard_summary.json").read_text(encoding="utf-8"))
    assert p2a["lane"] == LANE_SPEC_REPAIR
    assert p2a["lane_reason"]  # §12-57

    # spec repair 산출물이 있어도 base run validate가 깨지지 않는다
    ok, problems = validate_product_run_dir(base, [])
    assert not any("spec repair" in p or "frozen hash" in p for p in problems), problems


def test_approve_for_phase2b_still_no_apply():
    """§12-43, §4.9: APPROVE_FOR_PHASE2B여도 apply 관련 출력은 항상 false."""
    proposal = build_spec_repair_proposal(5, 47, _SPEC_FAILURES, "low")
    review = build_spec_repair_review(proposal)
    assert review["result"] == "APPROVE_FOR_PHASE2B"
    assert review["apply_performed"] is False
    assert review["apply_allowed_in_phase2a"] is False
    assert proposal["apply_allowed_in_phase2a"] is False


def test_high_risk_requires_human_review():
    """§7.5: risk high면 REQUIRES_HUMAN_REVIEW."""
    proposal = build_spec_repair_proposal(5, 47, _SPEC_FAILURES, "high")
    review = build_spec_repair_review(proposal)
    assert review["result"] == "REQUIRES_HUMAN_REVIEW"
    assert proposal["requires_human_review"] is True


# ---------------------------------------------------------------- §12-22~26,32~36,64,65: patch lane E2E (mock)

def _mock_base(tmp_path, overrides):
    llm = MockLLMClient(overrides={**mock_core_factory_overrides(), **overrides},
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


@pytest.fixture(scope="module")
def patch_lane_run(tmp_path_factory):
    """§12-64: 기존 factory-build mock으로 base 생성 후 queue patch lane 실행."""
    tmp_path = tmp_path_factory.mktemp("queue_patch")
    base = _mock_base(tmp_path, {"product_layer": _BAD_LAYER, "product_layer_repair": _BAD_LAYER})
    assert base["continuation_base_path"]
    # mock base는 KEEP_CANDIDATE로 끝나므로 NEEDS_MORE_GEMMA_LOOP base 상황을 재현한다 (DB 우선 discovery)
    conn = open_factory_db(tmp_path / "queue.db")
    rid = create_product_run(conn, 52, str(Path(base["run_dir"]) / "workspace"), "standard")
    update_product_run(conn, rid, status="done", verdict="NEEDS_MORE_GEMMA_LOOP")
    out = run_continuation_queue(
        db_path=None, db_conn=conn, output_dir=tmp_path / "runs",
        lane="patch", execute=True, limit=1, mode="mock",
        settings=SETTINGS, factory_settings=FSET,
    )
    conn.close()
    return tmp_path, base, out


def test_patch_lane_executes_single_run(patch_lane_run):
    """§12-5,26,32,33: --lane patch --execute --limit 1에서만 patch 실행 + gate rerun + PATCH_GREEN."""
    _, base, out = patch_lane_run
    assert out["ok"] and out["status"] == "EXECUTED"
    assert len(out["executed"]) == 1
    res = out["executed"][0]
    assert res["patch_result"] == "PATCH_GREEN"
    assert res["verdict"] == "REVIEW_READY"
    cd = Path(res["continuation_run_dir"])
    assert (cd / "gate_rerun_summary.json").is_file()  # §12-32


def test_patch_lane_frozen_hash_guard(patch_lane_run):
    """§12-24,25: patch lane도 frozen hash before/after/check 생성 + PASS."""
    _, _, out = patch_lane_run
    cd = Path(out["executed"][0]["continuation_run_dir"])
    for name in ("frozen_hash_before.json", "frozen_hash_after.json", "frozen_hash_check.json"):
        assert (cd / name).is_file()
    check = json.loads((cd / "frozen_hash_check.json").read_text(encoding="utf-8"))
    assert check["status"] == "PASS"
    assert out["executed"][0]["frozen_hash_status"] == "PASS"


def test_patch_lane_summary_has_lane_and_phase(patch_lane_run):
    """§4.10: Phase 2A 이후 생성 continuation run은 lane 필드 필수."""
    _, _, out = patch_lane_run
    cd = Path(out["executed"][0]["continuation_run_dir"])
    summary = json.loads((cd / "continuation_run_summary.json").read_text(encoding="utf-8"))
    assert summary["phase"] == "2a"
    assert summary["lane"] == LANE_REVIEW_ONLY  # REVIEW_READY로 승격됨
    assert summary["patch_result"] == "PATCH_GREEN"
    assert (cd / "phase2a_dashboard_summary.json").is_file()


def test_patch_lane_run_validates(patch_lane_run):
    """§12-58,65,66: 새 continuation run이 lane 포함 상태로 validate PASS."""
    _, _, out = patch_lane_run
    cd = Path(out["executed"][0]["continuation_run_dir"])
    ok, problems, info = validate_continuation_run_dir(cd, [])
    assert ok, problems
    assert info["lane"] == LANE_REVIEW_ONLY
    assert info["patch_result"] == "PATCH_GREEN"


# ---------------------------------------------------------------- §12-45~49,58~63: validate

def _valid_continuation(run_dir: Path, lane=None, phase=None) -> Path:
    """17b 테스트와 동일한 정합 fixture + 선택적 lane/phase 필드."""
    run_dir.mkdir(parents=True, exist_ok=True)

    def w(name, data):
        (run_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    summary = {
        "base_run_id": 5, "base_run_dir": "runs/factory_x", "challenge_id": 47,
        "mode": "live", "verdict": "SPEC_REPAIR_REQUIRED", "promoted_to_green_base": False,
        "failure_types": ["GOLDEN_SCHEMA_MISMATCH", "SPEC_REPAIR_REQUIRED"],
        "resolved": {}, "patch_attempts": 2, "transient_retries": 0, "rejected_patches": [],
        "requires_spec_repair": True,
    }
    if lane:
        summary["lane"] = lane
    if phase:
        summary["phase"] = phase
    w("continuation_run_summary.json", summary)
    w("failure_classification.json", {"base_run_id": 5, "challenge_id": 47,
                                      "failure_types": _SPEC_FAILURES})
    w("repair_plan.json", {
        "base_run_id": 5, "repair_scope": "delta_patch",
        "allowed_touch_files": ["src/", "product/"],
        "frozen_files": ["core_contract.json", "fixtures/", "golden/"],
        "steps": [{"target": "src/", "reason": "expose", "failure_type": "STATE_INVARIANT_NOT_EXPOSED"}],
        "requires_spec_repair": True,
    })
    w("green_base_promotion.json", {
        "base_run_id": 5, "continuation_run_id": 8, "promoted_to_green_base": False,
        "new_verdict": "SPEC_REPAIR_REQUIRED",
        "remaining_failures": ["GOLDEN_SCHEMA_MISMATCH"], "next_goal": "resolve mismatch",
    })
    w("gate_rerun_summary.json", {
        "gates": {"core_contract": True, "runner": True, "scenario_replay": True,
                  "golden_output": False, "state_invariant": True, "determinism": True,
                  "anti_hardcode": True},
        "gates_passed": 6, "gates_total": 7, "failed_scenarios": [],
        "product_layer_consumes_core": True,
    })
    w("phase17_dashboard_summary.json", {
        "is_continuation": True, "base_run_id": 5, "verdict": "SPEC_REPAIR_REQUIRED",
        "green_base": False, "continuation_base": True,
        "remaining_failures": ["GOLDEN_SCHEMA_MISMATCH"],
    })
    return run_dir


def test_legacy_run_without_lane_passes_with_inferred(tmp_path):
    """§12-48: 기존 1.7/1.7b run은 lane 없어도 inferred_lane으로 PASS."""
    run = _valid_continuation(tmp_path / "legacy")
    ok, problems, info = validate_continuation_run_dir(run, [])
    assert ok, problems
    assert info["lane"] is None
    assert info["inferred_lane"] == "SPEC_REPAIR"


def test_phase2a_run_without_lane_fails(tmp_path):
    """§12-49: Phase 2A 이후 생성(phase=2a) run은 lane 없으면 FAIL."""
    run = _valid_continuation(tmp_path / "p2a", phase="2a")
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("lane" in p for p in problems)


def test_phase2a_run_with_lane_passes(tmp_path):
    """§12-58,61: lane이 verdict와 정합하면 PASS (proposal-only SPEC_REPAIR 포함)."""
    run = _valid_continuation(tmp_path / "p2a_ok", lane="SPEC_REPAIR", phase="2a")
    ok, problems, info = validate_continuation_run_dir(run, [])
    assert ok, problems
    assert info["lane"] == "SPEC_REPAIR"


def test_lane_verdict_mismatch_fails(tmp_path):
    """§10: recommended lane과 verdict 정합성 — SPEC_REPAIR_REQUIRED에 REVIEW_ONLY면 FAIL."""
    run = _valid_continuation(tmp_path / "mismatch", lane="REVIEW_ONLY", phase="2a")
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("불일치" in p for p in problems)


def test_frozen_hash_check_fail_fails_validate(tmp_path):
    """§12-60: frozen hash guard FAIL이면 validate FAIL."""
    run = _valid_continuation(tmp_path / "hashfail", lane="SPEC_REPAIR", phase="2a")
    (run / "frozen_hash_check.json").write_text(json.dumps({
        "status": "FAIL", "changed": ["golden/expected_001.json"], "added": [], "removed": []
    }), encoding="utf-8")
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("frozen hash" in p for p in problems)


@pytest.mark.parametrize("target", [
    "golden/expected_001.json",   # §12-45
    "fixtures/scenario_001.json",  # §12-46
    "core_contract.json",          # §12-47
])
def test_spec_file_modified_after_record_fails(tmp_path, target):
    """§12-45,46,47: hash 기록 후 golden/fixtures/contract가 수정되면 validate FAIL."""
    run = _valid_continuation(tmp_path / "mod", lane="SPEC_REPAIR", phase="2a")
    ws = run / "workspace"
    for d in ("golden", "fixtures"):
        (ws / d).mkdir(parents=True)
    (ws / "golden" / "expected_001.json").write_text('{"a": 1}', encoding="utf-8")
    (ws / "fixtures" / "scenario_001.json").write_text('{"id": "s1"}', encoding="utf-8")
    (ws / "core_contract.json").write_text('{"state_fields": []}', encoding="utf-8")
    hashes = compute_frozen_hashes(ws)
    write_frozen_hash_guard(run, hashes, hashes)
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert ok, problems
    (ws / target).write_text('{"tampered": true}', encoding="utf-8")
    ok2, problems2, _ = validate_continuation_run_dir(run, [])
    assert not ok2
    assert any("수정됨" in p for p in problems2)


def test_apply_outputs_fail_validate(tmp_path):
    """§10: apply_allowed true / apply 수행 흔적이 있으면 FAIL."""
    run = _valid_continuation(tmp_path / "apply", lane="SPEC_REPAIR", phase="2a")
    (run / "spec_repair_proposal.json").write_text(json.dumps({
        "repair_type": "golden_schema", "problem": "x", "proposed_change": "y",
        "apply_allowed_in_phase2a": True,
    }), encoding="utf-8")
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("apply_allowed_in_phase2a" in p for p in problems)

    run2 = _valid_continuation(tmp_path / "apply2", lane="SPEC_REPAIR", phase="2a")
    (run2 / "spec_repair_review.json").write_text(json.dumps({
        "result": "APPROVE_FOR_PHASE2B", "apply_performed": True,
    }), encoding="utf-8")
    ok2, problems2, _ = validate_continuation_run_dir(run2, [])
    assert not ok2
    assert any("apply가 수행됨" in p for p in problems2)


def test_gate_fail_success_verdict_still_blocked(tmp_path):
    """§12-62,63: gate fail + REVIEW_READY/PROMOTE_TO_CODEX 차단 유지 (기존 규칙)."""
    run = _valid_continuation(tmp_path / "block", lane="SPEC_REPAIR", phase="2a")
    for name in ("continuation_run_summary.json", "green_base_promotion.json",
                 "phase17_dashboard_summary.json"):
        d = json.loads((run / name).read_text(encoding="utf-8"))
        if "verdict" in d:
            d["verdict"] = "REVIEW_READY"
        if "new_verdict" in d:
            d["new_verdict"] = "REVIEW_READY"
        (run / name).write_text(json.dumps(d), encoding="utf-8")
    ok, problems, _ = validate_continuation_run_dir(run, [])
    assert not ok
    assert any("verdict consistency" in p for p in problems)


# ---------------------------------------------------------------- §12-56,57: dashboard lane 표시

def test_dashboard_lane_line():
    """§12-56,57: 추천 경로/이유/상태가 카드 문구로 렌더링된다."""
    from repo_idea_miner.challenge_dashboard import _lane_line
    from repo_idea_miner.factory_labels import format_lane_label

    html = _lane_line({"lane": "SPEC_REPAIR",
                       "lane_reason": "golden schema mismatch / invariant DSL issue",
                       "lane_status": "제안서 생성됨, 적용은 보류"}, None)
    assert "추천 경로" in html and "Spec Repair" in html
    assert "golden schema mismatch" in html
    assert "제안서 생성됨" in html
    assert _lane_line(None, {}) == ""
    assert format_lane_label("EXCLUDED") == "제외"
    assert format_lane_label("PATCH_CONTINUATION") == "Patch Continuation"
