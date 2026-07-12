# Phase 1.6 core 스키마 테스트: 후보 수 정책·케이스 타입·golden 정책·PROMOTE 금지·verdict 판정 (§16-3,14~17,21,22,40~46).
import pytest

from repo_idea_miner.factory_core_schemas import (
    ARTIFACT_CLASSES,
    CORE_GATE_ORDER,
    MAX_CORE_CONTRACT_REPAIR_ATTEMPTS,
    MAX_PATCH_ATTEMPTS,
    MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS,
    MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS,
    Scenario,
    decide_core_verdict,
    effective_candidates,
    golden_mode_stats,
    promote_to_codex_problems,
    scenario_case_type_problems,
)


def test_repair_limits_match_spec():
    """§5.10/§6.9/§9.5/§10.5 repair 제한값."""
    assert MAX_CORE_CONTRACT_REPAIR_ATTEMPTS == 1
    assert MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS == 1
    assert MAX_PATCH_ATTEMPTS == 2
    assert MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS == 1


def test_artifact_classes_contain_spec_set():
    assert set(ARTIFACT_CLASSES) == {
        "RULE_ENGINE", "SIMULATION_ENGINE", "WORKFLOW_ENGINE",
        "DATA_TRANSFORM_ENGINE", "PLANNER_EVALUATOR", "INTERACTIVE_TOOL", "VIEWER_ONLY",
    }


# ---------------------------------------------------------------- 후보 수 정책 (§2.4, §13)

def test_live_default_candidates_is_one():
    """§16-21: live 기본 candidates = 1."""
    assert effective_candidates("live", None)[0] == 1
    n, notes = effective_candidates("live", 3)
    assert n == 1 and notes  # 보정 사유 기록


def test_mock_candidates_allow_one_to_two():
    """§16-22: mock candidates = 1~2 허용."""
    assert effective_candidates("mock", None)[0] == 1
    assert effective_candidates("mock", 2)[0] == 2
    n, notes = effective_candidates("mock", 5)
    assert n == 2 and notes
    assert effective_candidates("mock", 0)[0] == 1


# ---------------------------------------------------------------- scenario 케이스 최소 조건 (§6.4)

def test_scenario_case_types_required():
    normal = Scenario(id="s1", title="정상", case_type="normal")
    boundary = Scenario(id="s2", title="경계", case_type="boundary")
    invalid = Scenario(id="s3", title="무효", case_type="invalid")
    assert scenario_case_type_problems([normal, boundary, invalid]) == []
    problems = scenario_case_type_problems([normal, normal])
    assert any("boundary" in p for p in problems)
    assert any("invalid" in p for p in problems)


# ---------------------------------------------------------------- golden 정책 (§6.7)

def test_golden_mode_stats():
    goldens = [
        {"comparison_mode": "exact"},
        {"comparison_mode": "partial"},
        {"comparison_mode": "review"},
    ]
    stats = golden_mode_stats(goldens)
    assert stats["exact_count"] == 1
    assert stats["auto_gate_count"] == 2
    assert stats["review_count"] == 1
    assert stats["total"] == 3


# ---------------------------------------------------------------- PROMOTE_TO_CODEX 금지 (§6.7, §11.9)

_ALL_PASS = {g: True for g in CORE_GATE_ORDER}


def _promote_problems(**overrides):
    kwargs = dict(
        gate_summary=dict(_ALL_PASS),
        exact_golden_count=2,
        oracle_risk_level="low",
        hardcode_risk="low",
        artifact_class="RULE_ENGINE",
        product_layer_status="PASS",
        golden_total=3,
        review_golden_count=0,
    )
    kwargs.update(overrides)
    return promote_to_codex_problems(**kwargs)


def test_promote_allowed_when_all_conditions_met():
    assert _promote_problems() == []


def test_promote_forbidden_without_runner():
    """§16-40: runner 없는 산출물 PROMOTE 금지."""
    gates = dict(_ALL_PASS, runner=False)
    assert any("runner" in p for p in _promote_problems(gate_summary=gates))


def test_promote_forbidden_without_golden():
    """§16-41: golden 없는(전부 review 포함) 산출물 PROMOTE 금지."""
    gates = dict(_ALL_PASS, golden_output=False)
    assert any("golden" in p for p in _promote_problems(gate_summary=gates))
    # comparison_mode=review에만 의존해도 금지 (§11.9)
    problems = _promote_problems(golden_total=2, review_golden_count=2)
    assert any("review" in p for p in problems)


def test_promote_forbidden_for_viewer_only():
    """§16-42: viewer-only 산출물 PROMOTE 금지."""
    assert any("viewer-only" in p for p in _promote_problems(artifact_class="VIEWER_ONLY"))


def test_promote_forbidden_for_high_hardcode_risk():
    """§16-43: hardcode risk high PROMOTE 금지."""
    assert any("hardcode" in p for p in _promote_problems(hardcode_risk="high"))


def test_promote_forbidden_zero_exact_golden():
    """§16-16: exact golden 0개면 PROMOTE 금지."""
    assert any("exact golden" in p for p in _promote_problems(exact_golden_count=0))


def test_promote_forbidden_oracle_risk_high():
    """§16-17: oracle risk high면 PROMOTE 금지."""
    assert any("oracle" in p for p in _promote_problems(oracle_risk_level="high"))


# ---------------------------------------------------------------- verdict 판정 (§11)

def _verdict(**overrides):
    kwargs = dict(
        gate_summary=dict(_ALL_PASS),
        gate_problems={g: [] for g in CORE_GATE_ORDER},
        artifact_class="RULE_ENGINE",
        scenario_count=3,
        replay_failed=[],
        golden_failed=[],
        exact_golden_count=1,
        golden_stats={"total": 3, "exact_count": 1, "auto_gate_count": 3, "review_count": 0,
                      "modes": {}},
        oracle_risk_level="low",
        hardcode_risk="low",
        product_layer_status="PASS",
        golden_strength="medium",
        patchable=True,
        next_goal="scenario를 늘린다",
        has_state_transitions=True,
    )
    kwargs.update(overrides)
    return decide_core_verdict(**kwargs)


def test_review_ready_when_all_pass():
    """§16-44: REVIEW_READY 라벨 생성 가능."""
    verdict, reasons = _verdict()
    assert verdict == "REVIEW_READY"
    assert reasons


def test_needs_more_gemma_loop_on_partial_failure():
    """§16-45: 일부 gate 실패 + patch 가능 → NEEDS_MORE_GEMMA_LOOP."""
    gates = dict(_ALL_PASS, golden_output=False)
    verdict, _ = _verdict(gate_summary=gates, golden_failed=["scenario_002"])
    assert verdict == "NEEDS_MORE_GEMMA_LOOP"


def test_runs_but_weak_labels():
    """§16-46: RUNS_BUT_WEAK 라벨 생성 가능 (viewer-only / scenario 빈약 / review 전용)."""
    assert _verdict(artifact_class="VIEWER_ONLY")[0] == "RUNS_BUT_WEAK"
    assert _verdict(scenario_count=2)[0] == "RUNS_BUT_WEAK"
    review_only = {"total": 2, "exact_count": 0, "auto_gate_count": 0, "review_count": 2, "modes": {}}
    assert _verdict(golden_stats=review_only)[0] == "RUNS_BUT_WEAK"


def test_drop_when_runner_missing_or_no_transition():
    """§11.8: runner 실패/상태 전이 없음 → DROP."""
    gates = dict(_ALL_PASS, runner=False)
    assert _verdict(gate_summary=gates)[0] == "DROP"
    assert _verdict(has_state_transitions=False)[0] == "DROP"
    assert _verdict(hardcode_risk="high")[0] == "DROP"


def test_keep_candidate_when_product_layer_fails():
    """core는 통과했으나 product layer 미통과 → KEEP_CANDIDATE."""
    assert _verdict(product_layer_status="FAIL")[0] == "KEEP_CANDIDATE"


def test_promote_is_conservative():
    """§11.9: 전부 exact + strong + 저위험일 때만 PROMOTE, 아니면 REVIEW_READY."""
    all_exact = {"total": 3, "exact_count": 3, "auto_gate_count": 3, "review_count": 0, "modes": {}}
    verdict, _ = _verdict(golden_stats=all_exact, exact_golden_count=3, golden_strength="strong")
    assert verdict == "PROMOTE_TO_CODEX"
    # golden 강도가 medium이면 승격하지 않는다
    verdict, _ = _verdict(golden_stats=all_exact, exact_golden_count=3, golden_strength="medium")
    assert verdict == "REVIEW_READY"
    # 혼합 모드(전부 exact 아님)면 승격하지 않는다
    verdict, _ = _verdict(golden_strength="strong")
    assert verdict == "REVIEW_READY"


def test_viewer_only_is_not_default_class():
    """§16-3: mock 분류가 VIEWER_ONLY가 아니어야 한다."""
    from repo_idea_miner.factory_core_prompts import mock_core_classification

    assert mock_core_classification()["artifact_class"] != "VIEWER_ONLY"


# ---------------------------------------------------------------- blind batch 4 generic repair


def test_runner_contract_rejects_sandbox_unsupported_interpreter():
    """batch 4 D1: sandbox에 없는 interpreter의 runner_command는 동결 전에 거부돼야 한다 —
    동결 후에는 patch가 runner를 다시 써도 command를 못 바꿔 영구 회복 불가."""
    from pydantic import ValidationError

    from repo_idea_miner.factory_core_schemas import RunnerContract

    ok = RunnerContract(runner_command="python src/runner.py --scenario fixtures/scenario_001.json")
    assert ok.runner_command.startswith("python ")
    for bad in ("node src/runner.js --scenario fixtures/scenario_001.json",
                "npm run scenario", "deno run runner.ts", "   "):
        with pytest.raises(ValidationError):
            RunnerContract(runner_command=bad)


def test_prompts_declare_sandbox_runtime_and_rejection_channel():
    """batch 4 D1/D2: 생성 프롬프트가 sandbox 런타임(python)과 구조적 무효 action의
    errors 채널 명시 거부를 계약으로 선언해야 한다 (검증 계약과의 모순 해소 —
    검출기 약화가 아니라 생성 규칙 정합)."""
    from repo_idea_miner.factory_core_prompts import (
        build_core_build_prompt,
        build_core_contract_prompt,
    )

    contract_prompt = build_core_contract_prompt("{}", "{}")
    assert "python" in contract_prompt
    assert "silent-accept 금지" in contract_prompt
    assert "errors" in contract_prompt

    build_prompt = build_core_build_prompt("", "{}", "[]", [])
    assert "python 스크립트여야 한다" in build_prompt
    assert "silent-accept 금지" in build_prompt
