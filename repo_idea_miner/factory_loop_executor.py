# Phase 2D-1 §5·§10~§14: Evidence-Driven Closed Productization Loop 오케스트레이터 (child run 기반).
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from repo_idea_miner.factory_autopilot_desks import execute_desk
from repo_idea_miner.factory_autopilot_schemas import (
    AUTOPILOT_HOLD_FOR_HUMAN,
    AUTOPILOT_INFRA_FAIL,
    LANE_POLICY,
    RequirementCoverageJudgment,
)
from repo_idea_miner.factory_core_gates import run_anti_hardcode_gate, run_core_gates
from repo_idea_miner.factory_lane_executors import (
    LANE_EXECUTOR_ROUTES,
    execute_lane,
)
from repo_idea_miner.factory_product_acceptance import (
    build_progress_vector,
    build_requirement_coverage,
    compare_progress,
    count_regressions,
    evaluate_product_acceptance,
)
from repo_idea_miner.factory_product_capabilities import (
    build_capability_profile,
    loop_evidence_from_probe,
    run_fresh_probe,
)
from repo_idea_miner.factory_product_loop import (
    _run_desks,
    apply_hard_blockers,
    compare_protected_hashes,
    compute_loop_protected_hashes,
    extract_artifact_evidence,
    extract_user_facing_quality,
)
from repo_idea_miner.factory_review import resolve_review_target

LOOP_SUBDIR = "review/phase2d1"

# 기본 예산 (§10)
DEFAULT_BUDGETS = {
    "max_iterations": 4,
    "max_attempts_per_lane": 2,
    "max_high_risk_lane_attempts": 1,
    "max_consecutive_no_progress": 2,
    "max_infra_retries": 2,
}

_HIGH_RISK_LANES = tuple(
    lane for lane, pol in LANE_POLICY.items() if pol.get("lane_risk") == "high")


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump(data), encoding="utf-8")


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_ws(run_dir: Path) -> Path:
    ws = run_dir / "final_artifact"
    return ws if ws.is_dir() else run_dir / "workspace"


def _ensure_final_artifact(run_dir: Path) -> None:
    """continuation child(workspace 레이아웃)에 final_artifact를 정합화한다 — child는 loop 소유물."""
    fa, ws = run_dir / "final_artifact", run_dir / "workspace"
    if not fa.is_dir() and ws.is_dir():
        shutil.copytree(ws, fa)


def _run_id_of(db_conn, run_dir: Path) -> int | None:
    if db_conn is None:
        return None
    from repo_idea_miner.factory_db import find_product_run_id_by_run_dir
    try:
        return find_product_run_id_by_run_dir(db_conn, run_dir)
    except Exception:  # noqa: BLE001 — lineage 기록용 best effort
        return None


# ---------------------------------------------------------------- judge (evidence + desks)

def _judge(run_dir: Path, probe_report: dict | None, executor, gemma_mode: str,
           use_llm: bool) -> dict:
    """run 1개를 judge한다. probe가 있으면 loop evidence를 probe 관측으로 덮는다 (§7 — 보고서 boolean 불신)."""
    evidence = extract_artifact_evidence(run_dir)
    if probe_report is not None:
        fresh_loop = loop_evidence_from_probe(probe_report, evidence["product_loop"])
        evidence["product_loop"] = fresh_loop
        for k, v in fresh_loop.items():
            ref = f"artifact_evidence.product_loop.{k}={str(bool(v)).lower()}"
            evidence["refs"][f"loop.{k}"] = ref
            evidence["known_refs"].add(ref)
    quality = extract_user_facing_quality(evidence)
    hard = apply_hard_blockers(evidence, quality)
    prompts: dict = {}
    desks = _run_desks(executor, evidence, quality, hard, gemma_mode, use_llm, prompts,
                       include_order=False)
    return {"evidence": evidence, "quality": quality, "hard": hard, "desks": desks,
            "prompts": prompts}


def _build_coverage_prompt(requirements: list[str], profile: dict, probe: dict,
                           known_refs: list[str]) -> str:
    return f"""너는 Product Factory의 Requirement Coverage Judge다.
원 주문서의 requirement 각각이 현재 product artifact에 실제로 구현/존중되는지 판정한다.

규칙:
- status는 implemented | missing | respected | violated | unknown 중 하나.
- implemented/respected는 evidence_refs 최소 1개 필수. 근거 없는 낙관 판정은 금지 — 불확실하면 unknown.
- evidence_refs는 아래 카탈로그의 문자열만 사용. 새 ref를 만들지 마라.
- 요약문이 아니라 evidence로만 판단한다.

JSON만 출력. Schema: {{"items": [{{"requirement": "...", "status": "...", "evidence_refs": ["..."], "reason": "..."}}]}}

=== REQUIREMENTS ===
{_dump(requirements)}

=== CAPABILITY PROFILE ===
{_dump({k: profile.get(k) for k in ("input_kind", "editable_entities", "primary_user_actions", "viewer_entrypoint", "critical_user_flows")})}

=== FRESH PROBE ===
{_dump({k: probe.get(k) for k in ("status", "success_scenarios_passed", "failure_scenarios_passed", "revise_and_rerun_changed", "viewer_static_ok", "field_consistency_ok", "critical_flow_handlers_ok", "mock_fallback_count", "problems")})}

=== EVIDENCE REFS CATALOG ===
{_dump(sorted(known_refs)[:80])}
"""


def _judge_requirement_coverage(run_dir: Path, profile: dict, probe: dict,
                                known_refs: set, executor, use_llm: bool) -> dict:
    """requirement coverage를 desk로 판정하고 근거 없는 낙관 판정을 unknown으로 강등한다."""
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    requirements = [str(r) for r in
                    (normalized.get("success_conditions") or [])
                    + (normalized.get("difficulty_anchors") or [])
                    + (normalized.get("forbidden_simplifications") or [])]
    if not requirements:
        return {"judge_coverage": {}, "problems": [], "desk_status": "SKIPPED"}
    mock = None if use_llm else {"items": [
        {"requirement": r, "status": "unknown", "evidence_refs": [],
         "reason": "mock: 자동 판정 근거 없음"} for r in requirements]}
    prompt = _build_coverage_prompt(requirements, profile, probe, list(known_refs))
    res = execute_desk(executor, "requirement_coverage", prompt,
                       RequirementCoverageJudgment, mock_output=mock)
    problems: list[str] = list(res.get("problems") or [])
    judged: dict = {}
    if res["status"] == "PASS":
        for item in (res["raw"] or {}).get("items") or []:
            status = item.get("status")
            refs = [r for r in (item.get("evidence_refs") or []) if r in known_refs]
            if status in ("implemented", "respected") and not refs:
                problems.append(
                    f"coverage: {item.get('requirement')!r} {status} 판정에 유효 evidence 없음 → unknown 강등")
                status = "unknown"
            judged[str(item.get("requirement"))] = {
                "status": status, "evidence_refs": refs, "reason": item.get("reason", "")}
    return {"judge_coverage": judged, "problems": problems, "desk_status": res["status"]}


# ---------------------------------------------------------------- 검증 체인 (§14)

def verify_candidate(run_dir: Path, out_dir: Path, rerun_gates: bool,
                     executor, use_llm: bool, timeout: float, use_docker: bool | None,
                     secrets: list[str], protected_hash_status: str = "PASS",
                     gemma_mode: str = "sequential") -> dict:
    """child(또는 parent)를 §14 순서로 실제 검증한다. 어떤 값도 기존 report에서 재사용하지 않는다."""
    ws = _resolve_ws(run_dir)
    core_contract = _load_json(ws / "core_contract.json") or {}
    runner_contract = _load_json(ws / "runner_contract.json") or {}
    goldens = [g for g in (_load_json(p) for p in sorted((ws / "golden").glob("expected_*.json")))
               if g is not None]

    if rerun_gates:
        gates = run_core_gates(ws, core_contract, runner_contract, goldens,
                               timeout_seconds=timeout, use_docker=use_docker, secrets=secrets)
        gate_summary = dict(gates["summary"])
        _write_json(out_dir / "gate_rerun.json",
                    {g: {"ok": ok, "problems": gates["problems"][g]}
                     for g, ok in gate_summary.items()})
    else:
        recorded = _load_json(ws / "gate_results.json") or {}
        gate_summary = {g: bool((recorded.get(g) or {}).get("ok")) for g in recorded}

    # post-product anti-hardcode (§1-7) — 항상 다시 계산, run에는 쓰지 않고 out_dir에 기록
    anti_result, anti_summary = run_anti_hardcode_gate(
        ws, goldens, runner_contract, {}, timeout_seconds=timeout,
        use_docker=use_docker, secrets=secrets, run_level2=False)
    anti_summary["scan_point"] = "phase2d1_verify"
    _write_json(out_dir / "post_product_anti_hardcode.json", anti_summary)

    from repo_idea_miner.factory_validate import validate_product_run_dir
    validate_ok, validate_problems = validate_product_run_dir(run_dir, [])
    _write_json(out_dir / "factory_validate.json",
                {"ok": validate_ok, "problems": validate_problems[:50]})

    probe = run_fresh_probe(run_dir, out_dir / "probe", timeout=timeout, use_docker=use_docker,
                            secrets=secrets)
    profile = build_capability_profile(run_dir)
    _write_json(out_dir / "capability_profile.json", profile)

    judge = _judge(run_dir, probe, executor, gemma_mode, use_llm)
    desks = judge["desks"]
    stage = (desks.get("stage_label") or {}).get("stage")
    _write_json(out_dir / "judge_snapshot.json", {
        "desk_status": desks["status"], "failure_type": desks.get("failure_type"),
        "stage": stage, "primary_gap": (desks.get("gap") or {}).get("primary_gap"),
        "recommended_next_lane": (desks.get("lane") or {}).get("recommended_next_lane"),
        "problems": desks.get("problems") or [],
    })

    coverage_judgment = _judge_requirement_coverage(
        run_dir, profile, probe, judge["evidence"]["known_refs"], executor, use_llm)
    coverage = build_requirement_coverage(run_dir, coverage_judgment["judge_coverage"])
    coverage["desk_status"] = coverage_judgment["desk_status"]
    coverage["problems"] = coverage_judgment["problems"]
    _write_json(out_dir / "requirement_coverage.json", coverage)

    loop_evidence = judge["evidence"]["product_loop"]
    quality_fields = judge["quality"]["fields"]
    acceptance = evaluate_product_acceptance(
        run_dir, probe, gate_summary, validate_ok,
        anti_summary.get("status"), protected_hash_status, coverage, loop_evidence,
        quality_fields)
    _write_json(out_dir / "product_acceptance.json", acceptance)

    hard_count = sum(1 for b in (judge["hard"].get("blockers") or []) if b.get("triggered"))
    # §8: acceptance 미충족이면 stage 상한 강제 (PRODUCT_CANDIDATE 과대평가 차단, §1-12)
    effective_stage = stage
    if stage == "PRODUCT_CANDIDATE" and not acceptance["product_candidate_allowed"]:
        effective_stage = acceptance["max_stage"]
    vector = build_progress_vector(effective_stage, gate_summary, acceptance, hard_count,
                                   coverage, loop_evidence, probe)
    _write_json(out_dir / "progress_vector.json", vector)
    return {
        "gate_summary": gate_summary, "anti_summary": anti_summary,
        "validate_ok": validate_ok, "probe": probe, "profile": profile,
        "judge": judge, "coverage": coverage, "acceptance": acceptance,
        "vector": vector, "stage": stage, "effective_stage": effective_stage,
        "overrating_blocked": stage == "PRODUCT_CANDIDATE"
        and not acceptance["product_candidate_allowed"],
    }


# ---------------------------------------------------------------- HOLD packet (§11)

def _write_hold_packet(loop_dir: Path, state: dict, reason: str, question: str,
                       options: list[str]) -> dict:
    packet = {
        "best_candidate_run_dir": state.get("parent_run_dir"),
        "current_stage": state.get("current_stage"),
        "blocking_gaps": state.get("blocking_gaps") or [],
        "lane_attempts": state.get("lane_attempts") or {},
        "attempt_diffs": state.get("attempt_diffs") or [],
        "failure_signatures": state.get("failure_signatures") or [],
        "protection_results": state.get("protection_results") or {},
        "why_not_automated": reason,
        "single_question_for_human": question,
        "recommended_options": options,
    }
    _write_json(loop_dir / "hold_for_human_packet.json", packet)
    return packet


# ---------------------------------------------------------------- closed loop (§5, §10)

def run_closed_product_loop(
    run_dir: str | Path | None = None,
    run_id: int | None = None,
    mode: str = "mock",
    gemma_mode: str = "sequential",
    execute: bool = False,
    max_iterations: int | None = None,
    output_dir: str | Path = "runs",
    db_conn=None,
    settings=None,
    factory_settings=None,
    llm=None,
    scheduler=None,
    budgets: dict | None = None,
) -> dict:
    """Probe→Judge→Gap→Lane→Child→Apply→Gate→Fresh Probe→Progress→Promote/Rollback→Rejudge (§0).

    --execute 미지정이면 judge/probe까지만 수행한다 (안전 기본값 §13).
    사람에게 중간 질문을 보내지 않는다 — 자동 진행 불가면 HOLD_FOR_HUMAN packet을 남긴다 (§1-10·11).
    """
    from repo_idea_miner.config import load_settings
    from repo_idea_miner.factory_pipeline import load_factory_settings

    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    secrets = settings.secret_values()
    timeout = fset.sandbox_timeout_seconds
    use_docker = fset.docker_flag()
    b = {**DEFAULT_BUDGETS, **(budgets or {})}
    if max_iterations is not None:
        b["max_iterations"] = int(max_iterations)

    result: dict = {"ok": False, "status": None, "loop_id": None, "resolved_run_dir": None,
                    "iterations": [], "stop_conditions": [], "final_stage": None,
                    "base_hash_status": None, "hold_packet": None, "problems": []}
    target, err, tinfo = resolve_review_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = tinfo.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    base_run_dir = Path(target)
    loop_id = time.strftime("loop_%Y%m%d_%H%M%S")
    n = 1
    while (base_run_dir / LOOP_SUBDIR / loop_id).exists():
        n += 1
        loop_id = time.strftime("loop_%Y%m%d_%H%M%S") + f"_{n:02d}"
    loop_dir = base_run_dir / LOOP_SUBDIR / loop_id
    loop_dir.mkdir(parents=True, exist_ok=True)
    result["loop_id"] = loop_id
    result["loop_dir"] = str(loop_dir.as_posix())

    use_llm = mode == "live" or llm is not None
    executor = None
    if use_llm:
        from repo_idea_miner.factory_desks import DeskExecutor
        from repo_idea_miner.llm_client import LLMCallLogger
        executor = DeskExecutor(mode, settings, scheduler=scheduler, llm=llm,
                                call_logger=LLMCallLogger(loop_dir / "debug" / "llm_calls.jsonl",
                                                          secrets))

    base_hash_before = compute_loop_protected_hashes(base_run_dir)
    _write_json(loop_dir / "base_hash_before.json", base_hash_before)
    base_run_id = _run_id_of(db_conn, base_run_dir)

    parent_run_dir = base_run_dir
    parent_verify: dict | None = None
    lineage: list[dict] = []
    lane_attempts: dict[str, int] = {}
    high_risk_attempts = 0
    infra_retries = 0
    consecutive_no_progress = 0
    signatures_seen: dict[str, int] = {}
    attempt_diffs: list[dict] = []
    stop: list[str] = []
    hold_reason = None
    children_root = Path(output_dir)

    state_for_hold = lambda cur_stage, gaps: {  # noqa: E731 — packet 입력 요약
        "parent_run_dir": str(parent_run_dir.as_posix()), "current_stage": cur_stage,
        "blocking_gaps": gaps, "lane_attempts": lane_attempts,
        "attempt_diffs": attempt_diffs,
        "failure_signatures": [{"signature": s, "count": c} for s, c in signatures_seen.items()],
        "protection_results": {"base_hash": result.get("base_hash_status") or "PENDING"},
    }

    iteration = 0
    while iteration < b["max_iterations"] and not stop:
        iteration += 1
        it_dir = loop_dir / "iterations" / f"iter{iteration:02d}"
        it: dict = {"iteration": iteration, "parent_run_dir": str(parent_run_dir.as_posix())}

        # ---- Probe + Judge + 검증 (parent 상태 확정 — 재사용 금지 §1-9)
        if parent_verify is None:
            parent_verify = verify_candidate(parent_run_dir, it_dir / "before",
                                             rerun_gates=parent_run_dir != base_run_dir,
                                             executor=executor, use_llm=use_llm,
                                             timeout=timeout, use_docker=use_docker,
                                             secrets=secrets, gemma_mode=gemma_mode)
        v = parent_verify
        desks = v["judge"]["desks"]
        if desks["status"] != "PASS":
            ftype = desks.get("failure_type")
            if ftype == AUTOPILOT_INFRA_FAIL and infra_retries < b["max_infra_retries"]:
                infra_retries += 1
                it.update(desk_status="FAIL", failure_type=ftype, infra_retry=infra_retries)
                result["iterations"].append(it)
                parent_verify = None  # 재시도
                iteration -= 1
                continue
            stop.append("evidence 부족/desk 실패" if ftype != AUTOPILOT_INFRA_FAIL
                        else "live 인프라 실패 (재시도 소진)")
            hold_reason = f"judge desk 실패: {ftype}"
            it.update(desk_status="FAIL", failure_type=ftype)
            result["iterations"].append(it)
            break

        stage = v["effective_stage"]
        gap = (desks.get("gap") or {}).get("primary_gap")
        lane = (desks.get("lane") or {}).get("recommended_next_lane")
        it.update(stage_before=stage, primary_gap_before=gap, selected_lane=lane,
                  overrating_blocked=v["overrating_blocked"])
        result["final_stage"] = stage

        # ---- 종료 판정 (§10)
        if v["stage"] == "PRODUCT_CANDIDATE" and v["acceptance"]["product_candidate_allowed"]:
            stop.append("엄격한 PRODUCT_CANDIDATE 도달")
            result["iterations"].append(it)
            break
        if v["overrating_blocked"]:
            it["overrating_note"] = (
                f"judge stage=PRODUCT_CANDIDATE를 acceptance가 {stage}로 제한: "
                + ", ".join(v["acceptance"]["failed_checks"]))
        if stage == "ARCHIVE" or gap == "ARCHIVE_RECOMMENDED":
            execute_lane("ARCHIVE", {"parent_run_dir": parent_run_dir,
                                     "iteration_dir": it_dir, "reason": gap})
            stop.append("ARCHIVE 판정")
            result["iterations"].append(it)
            break
        if lane in (None, "HOLD_FOR_HUMAN") or \
                (desks.get("lane") or {}).get("human_decision_required"):
            stop.append("human_decision_required")
            hold_reason = "judge가 사람 결정 필요로 판정"
            result["iterations"].append(it)
            break

        if not execute:
            stop.append("--execute 미지정 → judge/probe only (§13)")
            result["iterations"].append(it)
            break

        # ---- 예산 (§10)
        if lane_attempts.get(lane, 0) >= b["max_attempts_per_lane"]:
            stop.append(f"lane {lane} 시도 예산 초과 ({b['max_attempts_per_lane']})")
            hold_reason = f"lane {lane} 예산 소진"
            result["iterations"].append(it)
            break
        if lane in _HIGH_RISK_LANES and high_risk_attempts >= b["max_high_risk_lane_attempts"]:
            stop.append(f"high risk lane 시도 예산 초과 ({b['max_high_risk_lane_attempts']})")
            hold_reason = f"high risk lane {lane} 예산 소진"
            result["iterations"].append(it)
            break

        # ---- Child 실행 (§4~§5) — child dir는 lane executor가 만든다
        ctx = {"parent_run_dir": parent_run_dir,
               "children_root": children_root, "iteration_dir": it_dir, "mode": mode,
               "llm": llm, "db_conn": db_conn, "settings": settings,
               "factory_settings": fset, "timeout": timeout}
        lane_attempts[lane] = lane_attempts.get(lane, 0) + 1
        if lane in _HIGH_RISK_LANES:
            high_risk_attempts += 1
        lane_result = execute_lane(lane, ctx)
        _write_json(it_dir / "lane_result.json", lane_result)
        child = Path(lane_result["child_run_dir"]) if lane_result.get("child_run_dir") else None
        attempt_diffs.append({"iteration": iteration, "lane": lane,
                              "status": lane_result["status"],
                              "changed_files": lane_result["changed_files"]})
        it.update(lane_status=lane_result["status"],
                  child_run_dir=lane_result.get("child_run_dir"),
                  changed_files=lane_result["changed_files"],
                  allowed_scope_check=lane_result["allowed_scope_check"],
                  protected_hash_check=lane_result["protected_hash_check"])

        lineage.append({
            "loop_id": loop_id, "iteration": iteration,
            "base_run_id": base_run_id, "base_run_dir": str(base_run_dir.as_posix()),
            "parent_run_id": _run_id_of(db_conn, parent_run_dir),
            "parent_run_dir": str(parent_run_dir.as_posix()),
            "child_run_id": _run_id_of(db_conn, child) if child else None,
            "child_run_dir": str(child.as_posix()) if child else None,
            "selected_lane": lane,
            "primary_gap_before": gap,
            "stage_before": stage,
        })

        sig = lane_result.get("failure_signature")
        if sig:
            signatures_seen[sig] = signatures_seen.get(sig, 0) + 1
            if signatures_seen[sig] >= 2:
                stop.append("같은 failure signature 2회")
                hold_reason = f"failure signature 반복: {sig}"
                result["iterations"].append(it)
                break
        if lane_result["protected_hash_check"] != "PASS" or \
                lane_result["allowed_scope_check"] != "PASS":
            stop.append("protected scope 변경/allowed scope 위반")
            hold_reason = "보호 장치 위반 — 자동 진행 금지"
            result["iterations"].append(it)
            break
        if lane_result["status"] != "APPLIED" or child is None:
            consecutive_no_progress += 1
            it["progress"] = "NO_CHILD_OR_NOT_APPLIED"
            result["iterations"].append(it)
            if consecutive_no_progress >= b["max_consecutive_no_progress"]:
                stop.append("연속 무개선 2회")
                hold_reason = "lane 실행이 연속으로 개선을 만들지 못함"
            continue

        # ---- Child 검증 체인 (§14) + Progress (§9)
        _ensure_final_artifact(child)
        child_verify = verify_candidate(child, it_dir / "after", rerun_gates=True,
                                        executor=executor, use_llm=use_llm,
                                        timeout=timeout, use_docker=use_docker, secrets=secrets,
                                        protected_hash_status=lane_result["protected_hash_check"],
                                        gemma_mode=gemma_mode)
        regress = count_regressions(v["vector"], child_verify["vector"],
                                    v["gate_summary"], child_verify["gate_summary"])
        child_verify["vector"]["regression_count"] = regress["count"]
        progress = compare_progress(v["vector"], child_verify["vector"],
                                    lane_result["protected_hash_check"])
        progress["regressions"] = regress["items"]
        _write_json(it_dir / "progress_comparison.json", progress)
        it.update(stage_after=child_verify["effective_stage"],
                  progress=progress["verdict"],
                  metric_delta={k: child_verify["vector"].get(k) for k in
                                ("stage_rank", "core_gates_passed", "product_acceptance_passed",
                                 "success_scenarios_passed", "failure_scenarios_passed",
                                 "mock_fallback_count", "regression_count")})

        if progress["meaningful_progress"]:
            parent_run_dir = child
            parent_verify = child_verify
            consecutive_no_progress = 0
            result["final_stage"] = child_verify["effective_stage"]
            if child_verify["stage"] == "PRODUCT_CANDIDATE" and \
                    child_verify["acceptance"]["product_candidate_allowed"]:
                stop.append("엄격한 PRODUCT_CANDIDATE 도달")
        else:
            # rollback: child를 active candidate로 승격하지 않는다 (§5 — 기록은 유지)
            consecutive_no_progress += 1
            it["rollback"] = "child 미승격 (NO_MEANINGFUL_PROGRESS)"
            if consecutive_no_progress >= b["max_consecutive_no_progress"]:
                stop.append("연속 무개선 2회")
                hold_reason = "연속 무개선 — 전략 변경 필요"
        result["iterations"].append(it)

    if iteration >= b["max_iterations"] and not stop:
        stop.append("max_iterations 도달")
        hold_reason = hold_reason or "iteration 예산 소진"

    # ---- 마무리: base 불변 증명 + lineage + HOLD packet + 요약
    base_hash_after = compute_loop_protected_hashes(base_run_dir)
    hash_check = compare_protected_hashes(base_hash_before, base_hash_after)
    result["base_hash_status"] = hash_check["status"]
    _write_json(loop_dir / "base_hash_check.json", hash_check)
    _write_json(loop_dir / "lineage.json", {"loop_id": loop_id, "entries": lineage})

    reached = any("PRODUCT_CANDIDATE 도달" in s for s in stop)
    archived = any("ARCHIVE" in s for s in stop)
    judge_only = any("--execute 미지정" in s for s in stop)
    if hold_reason and not reached and not archived:
        gaps = [g for g in {i.get("primary_gap_before") for i in result["iterations"]} if g]
        result["hold_packet"] = _write_hold_packet(
            loop_dir, state_for_hold(result["final_stage"], gaps), hold_reason,
            "현재 candidate를 이 상태로 검수/출시할지, 사람이 남은 gap을 직접 수정할지 결정해 주세요.",
            ["현재 candidate 그대로 사람 검수", "남은 gap 수동 수정 후 loop 재실행", "ARCHIVE"])

    result["stop_conditions"] = stop
    result["active_candidate_run_dir"] = str(parent_run_dir.as_posix())
    result["status"] = ("PRODUCT_CANDIDATE" if reached else
                        "ARCHIVED" if archived else
                        "JUDGED_ONLY" if judge_only else
                        AUTOPILOT_HOLD_FOR_HUMAN)
    result["ok"] = hash_check["status"] == "PASS" and (reached or archived or judge_only
                                                       or result["hold_packet"] is not None)

    summary = {
        "phase": "2d1", "loop_id": loop_id, "mode": mode, "execute": execute,
        "budgets": b, "status": result["status"], "stop_conditions": stop,
        "iteration_count": len(result["iterations"]),
        "final_stage": result["final_stage"],
        "active_candidate_run_dir": result["active_candidate_run_dir"],
        "base_hash_status": result["base_hash_status"],
        "lane_attempts": lane_attempts,
        "lane_routes": LANE_EXECUTOR_ROUTES,
        "iterations": result["iterations"],
    }
    _write_json(loop_dir / "loop_summary.json", summary)
    _write_json(loop_dir / "phase2d1_dashboard_summary.json", {
        "phase": "2d1",
        "run_dir": f"runs/{base_run_dir.name}",
        "loop_id": loop_id,
        "iteration": len(result["iterations"]),
        "max_iterations": b["max_iterations"],
        "current_stage": result["final_stage"],
        "previous_stage": (result["iterations"][0].get("stage_before")
                           if result["iterations"] else None),
        "primary_gap": (result["iterations"][-1].get("primary_gap_before")
                        if result["iterations"] else None),
        "selected_lane": (result["iterations"][-1].get("selected_lane")
                          if result["iterations"] else None),
        "metric_delta": (result["iterations"][-1].get("metric_delta")
                         if result["iterations"] else None),
        "regression": any("regression" in str(i.get("progress", "")).lower()
                          for i in result["iterations"]),
        "mock_fallback_count": (parent_verify or {}).get("probe", {}).get("mock_fallback_count")
        if parent_verify else None,
        "critical_requirement_coverage": (parent_verify or {}).get("coverage", {}).get(
            "critical_requirement_coverage") if parent_verify else None,
        "anchor_coverage": (parent_verify or {}).get("coverage", {}).get(
            "difficulty_anchor_coverage") if parent_verify else None,
        "stop_reason": stop[-1] if stop else None,
        "active_child_run": result["active_candidate_run_dir"],
        "status": result["status"],
        "base_hash_status": result["base_hash_status"],
        "hold_for_human": result["hold_packet"] is not None,
    })
    return result
