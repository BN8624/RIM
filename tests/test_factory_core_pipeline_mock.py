# Phase 1.6 Core Harness mock E2E: 7-Stage 산출물·repair 제한·patch 루프·product layer·green base·DB 기록 (§16).
import json
from pathlib import Path

import pytest

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import (
    mock_broken_core_build_output,
    mock_core_factory_overrides,
    mock_runnerless_core_build_output,
)
from repo_idea_miner.factory_db import open_factory_db
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})


def _run(tmp_path, overrides=None, db=False, candidates=None, mode="mock", challenge=None):
    conn = open_factory_db(tmp_path / "challenge.db") if db else None
    llm = MockLLMClient(overrides={**mock_core_factory_overrides(), **(overrides or {})},
                        call_logger=LLMCallLogger(None))
    result = run_core_factory(
        challenge or sample_challenge(), mode=mode, output_dir=tmp_path / "runs",
        db_conn=conn, settings=SETTINGS, factory_settings=FSET, llm=llm,
        candidates=candidates,
    )
    return result, conn, llm


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    """전체 mock 완주 1회 (module 공유로 속도 확보) — §16-55."""
    tmp_path = tmp_path_factory.mktemp("core_full")
    conn = open_factory_db(tmp_path / "challenge.db")
    llm = MockLLMClient(overrides=mock_core_factory_overrides(), call_logger=LLMCallLogger(None))
    result = run_core_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=SETTINGS, factory_settings=FSET, llm=llm,
    )
    yield result, conn, llm, tmp_path
    conn.close()


# ---------------------------------------------------------------- 완주 (§15, §16-55)

def test_full_mock_run_succeeds(full_run):
    result, _, _, _ = full_run
    assert result["ok"], result["error"]
    assert result["spec_status"] is None
    assert all(result["gate_summary"].values()), result["gate_summary"]
    assert result["verdict"] in ("REVIEW_READY", "NEEDS_MORE_GEMMA_LOOP")  # §15 허용 결과
    assert result["artifact_class"] == "RULE_ENGINE"


def test_stage1_core_spec_artifacts(full_run):
    """§16-1,2,4~8: normalizer/classifier/contract/review 산출물."""
    result, _, _, _ = full_run
    run_dir = Path(result["run_dir"])
    ws = run_dir / "workspace"
    normalized = json.loads((run_dir / "normalized_challenge.json").read_text(encoding="utf-8"))
    assert normalized["core_problem"]
    classification = json.loads((run_dir / "core_artifact_classification.json").read_text(encoding="utf-8"))
    assert classification["artifact_class"] != "VIEWER_ONLY"  # §16-3
    for name in ("core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json"):
        assert (ws / name).is_file(), name
    review = json.loads((run_dir / "core_contract_review.json").read_text(encoding="utf-8"))
    assert review["status"] == "PASS"


def test_stage2_scenario_golden_artifacts(full_run):
    """§16-10~13: 정상/경계/실패 scenario + golden + oracle risk + review."""
    result, _, _, _ = full_run
    run_dir = Path(result["run_dir"])
    ws = run_dir / "workspace"
    scenarios = sorted((ws / "fixtures").glob("scenario_*.json"))
    assert len(scenarios) >= 3
    case_types = {json.loads(p.read_text(encoding="utf-8"))["case_type"] for p in scenarios}
    assert {"normal", "boundary", "invalid"} <= case_types
    goldens = sorted((ws / "golden").glob("expected_*.json"))
    assert len(goldens) >= 3
    risk = json.loads((run_dir / "oracle_risk_report.json").read_text(encoding="utf-8"))
    assert risk["risk_level"] in ("low", "medium", "high")
    review = json.loads((run_dir / "scenario_golden_review.json").read_text(encoding="utf-8"))
    assert review["status"] == "PASS"


def test_stage3_build_task_packet_core_first(full_run):
    """§16-19,20: build_task_packet 생성 + core-first 필수 문구 포함."""
    result, _, _, _ = full_run
    run_dir = Path(result["run_dir"])
    packet = (run_dir / "build_task_packet.md").read_text(encoding="utf-8")
    assert "너의 목표는 파일을 채우는 것이 아니다" in packet
    assert "core contract와 scenario/golden을 만족하는 첫 시제품" in packet
    assert "viewer는 core output, state snapshot, replay result를 보여주는 레이어" in packet
    assert (run_dir / "build_task_packet.json").is_file()


def test_stage4_gate_summaries_written(full_run):
    """§16-23~31: runner 존재 + gate 요약 json 생성."""
    result, _, _, _ = full_run
    final = Path(result["final_artifact_dir"])
    assert (final / "src" / "runner.py").is_file()  # §16-23
    for name in ("gate_results.json", "core_contract_summary.json", "runner_summary.json",
                 "scenario_replay_summary.json", "golden_diff_summary.json",
                 "state_invariant_summary.json", "determinism_summary.json",
                 "anti_hardcode_summary.json", "regression_summary.json"):
        assert (final / name).is_file(), name
    replay_index = json.loads((final / "replay" / "index.json").read_text(encoding="utf-8"))
    assert len(replay_index["replays"]) == 3


def test_stage5_build_review_written(full_run):
    """§16-32: Build Review 생성."""
    result, _, _, _ = full_run
    run_dir = Path(result["run_dir"])
    review = json.loads((run_dir / "build_review.json").read_text(encoding="utf-8"))
    assert review["status"] in ("PASS", "NEEDS_PATCH", "FAIL")
    assert review["next_goal"]
    assert (run_dir / "build_review.md").is_file()


def test_stage6_product_layer_required_and_core_based(full_run):
    """§16-36~38: Product Layer 필수 + core output 기반 + review 생성."""
    result, _, _, _ = full_run
    run_dir = Path(result["run_dir"])
    final = Path(result["final_artifact_dir"])
    product_files = [p for p in (final / "product").rglob("*") if p.is_file()]
    assert product_files  # §16-36
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in product_files)
    assert "replay" in blob  # §16-37: core output(replay 결과) 기반
    review = json.loads((run_dir / "product_layer_review.json").read_text(encoding="utf-8"))
    assert review["status"] == "PASS"


def test_stage7_verdict_dashboard_green_base(full_run):
    """§16-44,47,50~54: verdict/dashboard_summary/green_base 저장."""
    result, _, _, _ = full_run
    run_dir = Path(result["run_dir"])
    assert result["verdict"] == "REVIEW_READY"
    dsum = json.loads((run_dir / "dashboard_summary.json").read_text(encoding="utf-8"))
    assert dsum["headline"] == "검수 가능"
    assert dsum["artifact_class_ko"] == "룰 엔진"
    assert dsum["determinism"] == "통과"
    green = json.loads((run_dir / "green_base.json").read_text(encoding="utf-8"))
    assert Path(green["green_base_path"]).is_dir()  # §16-51
    assert "failed_scenarios" in green  # §16-52
    assert "golden_diff" in green  # §16-53
    assert green["next_goal"]  # §16-54
    assert green["regression_suite"]
    assert (run_dir / "harness_summary.json").is_file()
    assert (run_dir / "core_system_summary.json").is_file()
    assert (run_dir / "product_eval_summary.json").is_file()


def test_db_rows_and_new_columns(full_run):
    """§14: artifact_class/harness_summary_path/core_system_summary_path/green_base_path 저장."""
    result, conn, _, _ = full_run
    run = conn.execute("SELECT * FROM product_runs WHERE id=?", (result["product_run_id"],)).fetchone()
    assert run["status"] == "done"
    assert run["verdict"] == "REVIEW_READY"
    assert run["artifact_class"] == "RULE_ENGINE"
    assert run["harness_summary_path"] and Path(run["harness_summary_path"]).is_file()
    assert run["core_system_summary_path"] and Path(run["core_system_summary_path"]).is_file()
    assert run["green_base_path"] and Path(run["green_base_path"]).is_dir()
    desks = {t["desk_name"] for t in conn.execute(
        "SELECT desk_name FROM product_tasks WHERE product_run_id=?", (run["id"],))}
    assert {"core_spec_normalize", "core_spec_classify", "core_contract_draft",
            "core_contract_review", "scenario_golden_draft", "scenario_golden_review",
            "core_build", "build_review", "product_layer", "product_layer_review"} <= desks


def test_no_codex_auto_invocation(full_run):
    """§3: Codex/Claude 자동 호출 없음 — desk worker 이름 화이트리스트."""
    _, _, llm, _ = full_run
    workers = {e["worker"] for e in llm.logger.entries}
    assert not any("codex" in w.lower() or "claude" in w.lower() for w in workers)


def test_promote_not_given_for_mixed_goldens(full_run):
    """§15: mock 완주는 PROMOTE_TO_CODEX 남발 없이 REVIEW_READY."""
    result, _, _, _ = full_run
    assert result["verdict"] != "PROMOTE_TO_CODEX"
    assert result["codex_export_dir"] is None


# ---------------------------------------------------------------- Repair 제한 (§16-9,18)

def test_core_contract_repair_max_one(tmp_path):
    """§16-9: Core Contract Repair는 1회로 제한되고 2번째 리뷰 실패 시 Build로 넘어가지 않는다."""
    needs_repair = {"status": "NEEDS_REPAIR", "blocking_issues": ["state 모델 검증 불가"],
                    "repair_instructions": ["invariant 추가"], "risk_level": "high"}
    result, _, llm = _run(tmp_path, overrides={"core_contract_review": needs_repair})
    assert result["spec_status"] == "NEEDS_SPEC_REPAIR"
    workers = [e["worker"] for e in llm.logger.entries]
    assert workers.count("core_contract_repair") == 1  # max 1회
    assert workers.count("core_contract_review") == 2  # repair 후 재리뷰
    assert "core_build" not in workers  # Build 미진행
    assert "NEEDS_SPEC_REPAIR" in (Path(result["run_dir"]) / "product_verdict.md").read_text(encoding="utf-8")


def test_scenario_golden_repair_max_one(tmp_path):
    """§16-18: Scenario/Golden Repair 1회 제한."""
    needs_repair = {"status": "NEEDS_REPAIR", "blocking_issues": ["경계 케이스 부족"],
                    "repair_instructions": ["boundary 추가"], "golden_strength": "weak",
                    "safe_for_auto_gate": False}
    result, _, llm = _run(tmp_path, overrides={"scenario_golden_review": needs_repair})
    assert result["spec_status"] == "NEEDS_SPEC_REPAIR"
    workers = [e["worker"] for e in llm.logger.entries]
    assert workers.count("scenario_golden_repair") == 1
    assert workers.count("scenario_golden_review") == 2
    assert "core_build" not in workers


# ---------------------------------------------------------------- Patch 루프 (§16-33~35)

def test_patch_repair_fixes_broken_build(tmp_path):
    """§16-35: gate 실패 → patch → Core Gates 재실행 → 통과."""
    result, _, llm = _run(tmp_path, overrides={"core_build": mock_broken_core_build_output()})
    assert result["ok"], result["error"]
    assert result["patch_attempts"] == 1
    assert all(result["gate_summary"].values()), result["gate_summary"]
    workers = [e["worker"] for e in llm.logger.entries]
    assert "patch_repair" in workers


def test_patch_repair_max_two(tmp_path):
    """§16-33: Patch Repair 최대 2회."""
    broken = mock_broken_core_build_output()
    broken_patch = {"files": [f for f in broken["files"] if f["path"] == "src/core/engine.py"],
                    "patch_report": "여전히 깨진 patch (테스트용)"}
    result, _, llm = _run(tmp_path, overrides={"core_build": broken,
                                               "patch_repair": broken_patch})
    assert result["patch_attempts"] == 2
    assert not result["gate_summary"]["golden_output"]
    assert result["verdict"] == "NEEDS_MORE_GEMMA_LOOP"
    assert result["failed_scenarios"] == ["scenario_001", "scenario_002"]


def test_patch_cannot_touch_frozen_files(tmp_path):
    """§16-34: patch가 fixtures/golden/contract를 수정(우회)하지 못한다."""
    broken = mock_broken_core_build_output()
    cheating_patch = {
        "files": [
            {"path": "golden/expected_001.json", "content": "{}"},
            {"path": "fixtures/scenario_001.json", "content": "{}"},
            {"path": "core_contract.json", "content": "{}"},
        ],
        "patch_report": "golden을 고쳐서 통과시키려는 부정 patch",
    }
    result, _, _ = _run(tmp_path, overrides={"core_build": broken, "patch_repair": cheating_patch})
    ws = Path(result["run_dir"]) / "workspace"
    golden = json.loads((ws / "golden" / "expected_001.json").read_text(encoding="utf-8"))
    assert golden.get("scenario_id") == "scenario_001"  # 원본 유지
    assert not result["gate_summary"]["golden_output"]  # 우회 실패 → 여전히 FAIL


# ---------------------------------------------------------------- Runner 필수 (§16-40 흐름)

def test_runnerless_build_drops(tmp_path):
    """runner가 JSON을 못 내면 patch로 못 살릴 경우 DROP 계열로 떨어진다."""
    broken = mock_runnerless_core_build_output()
    broken_patch = {"files": [f for f in broken["files"] if f["path"] == "src/runner.py"],
                    "patch_report": "여전히 JSON 미출력"}
    result, _, _ = _run(tmp_path, overrides={"core_build": broken, "patch_repair": broken_patch})
    assert not result["gate_summary"]["runner"]
    assert result["verdict"] == "DROP"
    assert result["green_base_path"] is None


# ---------------------------------------------------------------- Product Layer (§16-36,39)

def test_product_layer_repair_max_one_and_keep_candidate(tmp_path):
    """§16-39: Product Layer Repair 1회 제한, 실패 시 REVIEW_READY 불가."""
    bad_layer = {"files": [{"path": "src/hack.py", "content": "# core 밖 수정 시도"}],
                 "product_report": "core logic을 건드리는 잘못된 product layer"}
    result, _, llm = _run(tmp_path, overrides={"product_layer": bad_layer,
                                               "product_layer_repair": bad_layer})
    assert result["ok"], result["error"]
    workers = [e["worker"] for e in llm.logger.entries]
    assert workers.count("product_layer_repair") == 1
    assert result["verdict"] == "KEEP_CANDIDATE"  # core는 통과, product layer 미통과
    assert result["green_base_path"] is None  # §11.11: green base 조건 미충족
    ws = Path(result["run_dir"]) / "workspace"
    assert not (ws / "src" / "hack.py").is_file()  # product 밖 경로는 거부됨


def test_product_layer_repair_recovers(tmp_path):
    """product layer 1차 불량 → repair(정상 mock)로 회복 → REVIEW_READY."""
    bad_layer = {"files": [{"path": "notes.md", "content": "그냥 메모"}],
                 "product_report": "core output을 안 보는 잘못된 산출물"}
    result, _, llm = _run(tmp_path, overrides={"product_layer": bad_layer})
    assert result["verdict"] == "REVIEW_READY"
    workers = [e["worker"] for e in llm.logger.entries]
    assert workers.count("product_layer_repair") == 1


# ---------------------------------------------------------------- VIEWER_ONLY 정책 (§5.6)

def test_viewer_only_capped_at_runs_but_weak(tmp_path):
    viewer_cls = {"artifact_class": "VIEWER_ONLY", "reason": "표시 전용",
                  "core_first": False, "runner_required": True,
                  "golden_required": True, "product_layer_required": True}
    result, _, _ = _run(tmp_path, overrides={"core_classification": viewer_cls})
    assert result["ok"], result["error"]
    assert result["verdict"] == "RUNS_BUT_WEAK"
    assert any("VIEWER_ONLY" in a for a in result["auto_adjustments"])


# ---------------------------------------------------------------- 후보 수 정책 (§16-21,22)

def test_mock_candidates_two_allowed(tmp_path):
    result, _, _ = _run(tmp_path, candidates=2)
    assert result["ok"], result["error"]
    assert result["candidates"] == 2


def test_live_candidates_forced_to_one(tmp_path):
    """live 모드는 후보 수를 1로 강제한다 (§2.4). LLM은 주입 mock이라 key 호출 없음."""
    result, _, _ = _run(tmp_path, candidates=3, mode="live")
    assert result["candidates"] == 1
    assert any("live 기본 candidates=1" in a for a in result["auto_adjustments"])


# ---------------------------------------------------------------- secret scan (§16-60)

def test_secret_scan_passes_with_fake_keys(tmp_path, fake_env):
    keys = {i: fake_env[f"GOOGLE_API_KEY_{i}"] for i in range(1, 12)}
    settings = Settings(google_keys=keys, github_token=fake_env["GITHUB_TOKEN"])
    llm = MockLLMClient(overrides=mock_core_factory_overrides())
    result = run_core_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        settings=settings, factory_settings=FSET, llm=llm,
    )
    assert result["ok"], result["error"]
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in Path(result["run_dir"]).rglob("*") if p.is_file()
    )
    for secret in fake_env.values():
        assert secret not in blob


# ---------------------------------------------------------------- 승격 게이트 (기존 §6 유지)

def test_promotion_gate_rejects_bad_challenge(tmp_path):
    challenge = sample_challenge()
    challenge["card"]["final_label"] = "TOO_EASY"
    result, _, _ = _run(tmp_path, challenge=challenge)
    assert result["error"] and "승격 기준 미달" in result["error"]
    assert result["run_dir"] is None
