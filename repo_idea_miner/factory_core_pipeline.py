# Phase 1.6 Core-first Review-Repair Harness: 7-Stage(Core Spec→Scenario Oracle→Build→Verification→Repair→Product Layer→Verdict) 파이프라인 (§4).
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.factory_core_gates import product_layer_consumes_core, run_core_gates
from repo_idea_miner.factory_core_prompts import (
    build_build_review_prompt,
    build_classify_prompt,
    build_core_build_prompt,
    build_core_contract_prompt,
    build_core_contract_repair_prompt,
    build_core_contract_review_prompt,
    build_normalize_prompt,
    build_patch_prompt,
    build_product_layer_prompt,
    build_product_layer_repair_prompt,
    build_product_layer_review_prompt,
    build_scenario_golden_prompt,
    build_scenario_golden_repair_prompt,
    build_scenario_golden_review_prompt,
    mock_core_factory_overrides,
    render_build_task_packet_md,
)
from repo_idea_miner.factory_core_schemas import (
    CORE_GATE_ORDER,
    CORE_VERDICT_TO_RECOMMENDED_ACTION,
    MAX_CORE_CONTRACT_REPAIR_ATTEMPTS,
    MAX_PATCH_ATTEMPTS,
    MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS,
    MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS,
    BuildReview,
    CoreArtifactClassification,
    CoreBuildOutput,
    CoreContractDraft,
    NormalizedChallenge,
    PatchOutput,
    ProductLayerOutput,
    ProductLayerReview,
    Scenario,
    ScenarioGoldenOutput,
    ScenarioGoldenReview,
    SpecReview,
    build_live_validation_summary,
    decide_core_verdict,
    effective_candidates,
    golden_mode_stats,
    scenario_case_type_problems,
)

# Phase 1.6b에서 보강한 gate 목록 (live_validation_summary.gate_hardening_applied에 기록)
GATE_HARDENING_APPLIED = (
    "core_contract_gate_static_wiring",
    "core_contract_gate_runtime_reflection",
    "product_layer_consumes_core",
    "green_vs_continuation_base",
    "build_review_recompute_after_patch",
    "factory_validate_final_artifact_consistency",
)
from repo_idea_miner.factory_db import (
    add_product_artifact,
    create_product_run,
    create_product_task,
    finish_product_task,
    log_product_event,
    update_product_run,
)
from repo_idea_miner.factory_desks import DeskError, DeskExecutor
from repo_idea_miner.factory_labels import ARTIFACT_CLASS_LABELS
from repo_idea_miner.factory_pipeline import (
    FactorySettings,
    challenge_context_md,
    load_factory_settings,
    make_factory_run_dir,
)
from repo_idea_miner.factory_schemas import promotion_line
from repo_idea_miner.factory_workspace import (
    list_workspace_files,
    log_debug_history,
    log_loop_event,
    read_workspace_file,
    save_green_base,
    write_workspace_file,
)
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient
from repo_idea_miner.redaction import redact_text, scan_files_for_secrets

# 계약/시나리오/골든은 patch가 건드리면 안 되는 동결 파일 (§9.5)
FROZEN_PATH_PREFIXES = ("fixtures/", "golden/", "replay/")
FROZEN_FILES = (
    "core_contract.json",
    "state_contract.json",
    "action_contract.json",
    "runner_contract.json",
)

# Phase 1.6 완주 산출물 최소 목록 (§15) — factory-validate에서 사용
CORE_RUN_REQUIRED_RUN_DOCS = (
    "normalized_challenge.json",
    "core_artifact_classification.json",
    "core_contract_review.json",
    "scenario_golden_review.json",
    "oracle_risk_report.json",
    "build_task_packet.md",
    "build_review.json",
    "product_layer_review.json",
    "dashboard_summary.json",
    "harness_summary.json",
    "core_system_summary.json",
    "product_verdict.md",
)

CORE_ARTIFACT_REQUIRED_FILES = (
    "core_contract.json",
    "state_contract.json",
    "action_contract.json",
    "runner_contract.json",
    "runner_summary.json",
    "scenario_replay_summary.json",
    "golden_diff_summary.json",
    "determinism_summary.json",
    "anti_hardcode_summary.json",
    "README.md",
    "run_instructions.md",
)


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _scenario_filename(scenario_id: str) -> str:
    return f"fixtures/{scenario_id}.json"


def _golden_filename(scenario_id: str) -> str:
    m = re.match(r"^scenario_(\w+)$", scenario_id)
    return f"golden/expected_{m.group(1)}.json" if m else f"golden/expected_{scenario_id}.json"


def _max_risk(*levels: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return max(levels, key=lambda level: order.get(level, 1))


# ---------------------------------------------------------------- 파이프라인 본체

def run_core_factory(
    challenge: dict,
    mode: str = "mock",
    output_dir: str | Path = "runs",
    db_conn=None,
    settings: Settings | None = None,
    factory_settings: FactorySettings | None = None,
    scheduler=None,
    llm=None,
    run_dir: Path | None = None,
    force_line: str | None = None,
    candidates: int | None = None,
    live_validation: bool = False,
) -> dict:
    """Challenge 하나를 Core-first Review-Repair Harness(§4)로 밀어붙인다.

    반환: 요약 dict (run_dir/verdict/gate_summary/green_base_path 등).
    """
    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    secrets = settings.secret_values()
    card = challenge["card"]
    challenge_id = challenge.get("challenge_id")

    result: dict = {
        "ok": False,
        "run_dir": None,
        "product_run_id": None,
        "challenge_id": challenge_id,
        "line": None,
        "verdict": None,
        "recommended_action": None,
        "artifact_class": None,
        "spec_status": None,
        "gate_summary": {},
        "failed_scenarios": [],
        "patch_attempts": 0,
        "candidates": None,
        "green_base_path": None,
        "continuation_base_path": None,
        "final_artifact_dir": None,
        "codex_export_dir": None,
        "auto_adjustments": [],
        "error": None,
    }

    # 후보 수 정책 (§2.4, §13)
    eff_candidates, candidate_notes = effective_candidates(mode, candidates)
    result["candidates"] = eff_candidates
    result["auto_adjustments"] += candidate_notes

    # Auto Promotion Gate (기존 §6 유지)
    line, gate_reasons = promotion_line(card, challenge.get("owner_clarity_score"))
    if force_line:
        line = force_line
    if line is None:
        result["error"] = "승격 기준 미달: " + "; ".join(gate_reasons)
        if db_conn is not None:
            log_product_event(db_conn, None, "promotion_rejected", result["error"],
                              metadata={"challenge_id": challenge_id})
        return result
    result["line"] = line

    run_dir = run_dir or make_factory_run_dir(output_dir)
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    result["run_dir"] = str(run_dir)

    run_id = None
    if db_conn is not None:
        run_id = create_product_run(db_conn, challenge_id, str(workspace), line)
        result["product_run_id"] = run_id
        log_product_event(db_conn, run_id, "core_factory_start",
                          f"line={line} mode={mode} candidates={eff_candidates}")

    log_debug_history(run_dir, secrets, {"event": "core_factory_start", "line": line,
                                         "mode": mode, "candidates": eff_candidates})
    log_loop_event(run_dir, secrets, stage="promotion_gate", validation="PASS",
                   next_state="core_spec", reasons=gate_reasons)

    if llm is None and mode == "mock":
        llm = MockLLMClient(overrides=mock_core_factory_overrides(),
                            call_logger=LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", secrets))
    call_logger = LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", secrets)
    executor = DeskExecutor(mode, settings, scheduler=scheduler, llm=llm, call_logger=call_logger)

    context = challenge_context_md(card)
    harness: dict = {"stages": {}, "limits": {
        "core_contract_repair_max": MAX_CORE_CONTRACT_REPAIR_ATTEMPTS,
        "scenario_golden_repair_max": MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS,
        "patch_max": MAX_PATCH_ATTEMPTS,
        "product_layer_repair_max": MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS,
    }, "candidates": {"requested": candidates, "effective": eff_candidates, "mode": mode}}

    def _write_run_doc(name: str, text: str) -> None:
        (run_dir / name).write_text(redact_text(text, secrets), encoding="utf-8")

    def _write_run_json(name: str, data) -> None:
        _write_run_doc(name, _dump(data))

    def _stage(stage: str) -> None:
        if db_conn is not None and run_id is not None:
            update_product_run(db_conn, run_id, current_stage=stage)

    def _desk_call(desk_name: str, schema_name: str, prompt: str, model_cls, input_artifact=None):
        task_id = None
        if db_conn is not None and run_id is not None:
            task_id = create_product_task(db_conn, run_id, desk_name, input_artifact=input_artifact)
        try:
            model, key_label = executor.call(schema_name, prompt, model_cls)
        except DeskError as exc:
            if task_id is not None:
                finish_product_task(db_conn, task_id, "error", last_error=str(exc))
            raise
        if task_id is not None:
            finish_product_task(db_conn, task_id, "done", output_artifact=schema_name, attempt_count=1)
            db_conn.execute("UPDATE product_tasks SET worker_key_id=? WHERE id=?", (key_label, task_id))
            db_conn.commit()
        return model, key_label

    def _fail_run(stage: str, msg: str) -> dict:
        result["error"] = msg
        if db_conn is not None and run_id is not None:
            update_product_run(db_conn, run_id, status="error", current_stage=stage)
            log_product_event(db_conn, run_id, "core_factory_error", msg[:300])
        log_loop_event(run_dir, secrets, stage=stage, validation="FAIL", error=msg[:300])
        return result

    def _finish_needs_spec_repair(stage: str, review: dict, blocking: list[str]) -> dict:
        """Review 2회 실패 → Build로 넘기지 않고 NEEDS_SPEC_REPAIR로 종료 (§5.10, §6.9)."""
        result["spec_status"] = "NEEDS_SPEC_REPAIR"
        harness["stages"][stage]["status"] = "NEEDS_SPEC_REPAIR"
        _write_run_doc("product_verdict.md", "\n".join([
            "# Product Verdict", "",
            "## 최종 판정", "NEEDS_SPEC_REPAIR", "",
            f"- 중단 Stage: {stage}",
            "## 차단 문제",
            *[f"- {b}" for b in blocking or ["(기록 없음)"]],
        ]) + "\n")
        _write_run_json("harness_summary.json", harness)
        if db_conn is not None and run_id is not None:
            update_product_run(db_conn, run_id, status="done", current_stage=stage)
            log_product_event(db_conn, run_id, "needs_spec_repair", f"stage={stage}")
        log_loop_event(run_dir, secrets, stage=stage, validation="FAIL",
                       next_state="stopped", spec_status="NEEDS_SPEC_REPAIR")
        result["ok"] = True
        return result

    try:
        # ---------------------------------------------------------- Stage 1: Core Spec (§5)
        _stage("core_spec")
        normalized_model, key = _desk_call("core_spec_normalize", "normalized_challenge",
                                           build_normalize_prompt(context), NormalizedChallenge)
        normalized = normalized_model.model_dump()
        if challenge_id is not None:
            normalized["challenge_id"] = str(challenge_id)
        if challenge.get("owner_clarity_score") is not None:
            normalized["owner_clarity"] = challenge["owner_clarity_score"]
        _write_run_json("normalized_challenge.json", normalized)
        _write_run_json("challenge_constraints.json", {
            "difficulty_anchors": card.get("difficulty_anchors") or [],
            "forbidden_simplifications": card.get("forbidden_simplifications") or [],
            "allowed_simplifications": card.get("allowed_simplifications") or [],
            "pass_criteria": card.get("pass_criteria") or [],
            "failure_criteria": card.get("failure_criteria") or [],
        })

        classification_model, _ = _desk_call("core_spec_classify", "core_classification",
                                             build_classify_prompt(_dump(normalized)),
                                             CoreArtifactClassification)
        classification = classification_model.model_dump()
        artifact_class = classification["artifact_class"]
        result["artifact_class"] = artifact_class
        _write_run_json("core_artifact_classification.json", classification)
        if artifact_class == "VIEWER_ONLY":
            result["auto_adjustments"].append(
                "VIEWER_ONLY 분류 → Build 우선순위 낮음, 데이터 모델/replayable IO 재검토 필요 (§5.6)"
            )

        draft_model, _ = _desk_call("core_contract_draft", "core_contract_draft",
                                    build_core_contract_prompt(_dump(normalized), _dump(classification)),
                                    CoreContractDraft)
        draft = draft_model.model_dump()

        def _write_contracts(d: dict) -> None:
            write_workspace_file(workspace, "core_contract.json", _dump(d["core_contract"]), secrets)
            write_workspace_file(workspace, "state_contract.json",
                                 _dump({"state_entities": d["core_contract"]["state_entities"]}), secrets)
            write_workspace_file(workspace, "action_contract.json",
                                 _dump({"actions": d["core_contract"]["actions"]}), secrets)
            write_workspace_file(workspace, "runner_contract.json", _dump(d["runner_contract"]), secrets)

        _write_contracts(draft)

        spec_attempts = 0
        review_model, _ = _desk_call("core_contract_review", "core_contract_review",
                                     build_core_contract_review_prompt(_dump(normalized), _dump(draft)),
                                     SpecReview)
        review = review_model.model_dump()
        while review["status"] != "PASS" and spec_attempts < MAX_CORE_CONTRACT_REPAIR_ATTEMPTS:
            spec_attempts += 1
            repaired_model, _ = _desk_call("core_contract_repair", "core_contract_repair",
                                           build_core_contract_repair_prompt(_dump(draft), _dump(review)),
                                           CoreContractDraft)
            draft = repaired_model.model_dump()
            _write_contracts(draft)
            _write_run_doc("core_contract_repair_report.md",
                           "# Core Contract Repair Report\n\n"
                           + "\n".join(f"- {i}" for i in review["repair_instructions"] or ["(지시 없음)"])
                           + f"\n\n(시도 {spec_attempts}/{MAX_CORE_CONTRACT_REPAIR_ATTEMPTS})\n")
            review_model, _ = _desk_call("core_contract_review", "core_contract_review",
                                         build_core_contract_review_prompt(_dump(normalized), _dump(draft)),
                                         SpecReview)
            review = review_model.model_dump()
        _write_run_json("core_contract_review.json", review)
        harness["stages"]["core_spec"] = {
            "status": review["status"], "repair_attempts": spec_attempts,
            "artifact_class": artifact_class,
        }
        log_loop_event(run_dir, secrets, stage="core_spec", desk="Core Spec Stage",
                       worker_key_id=key, validation=review["status"],
                       output_files=["core_contract.json", "runner_contract.json"],
                       next_state="scenario_oracle" if review["status"] == "PASS" else "stopped")
        if review["status"] != "PASS":
            return _finish_needs_spec_repair("core_spec", review, review["blocking_issues"])

        core_contract = draft["core_contract"]
        runner_contract = draft["runner_contract"]

        # ---------------------------------------------------------- Stage 2: Scenario Oracle (§6)
        _stage("scenario_oracle")
        sg_model, _ = _desk_call("scenario_golden_draft", "scenario_golden",
                                 build_scenario_golden_prompt(_dump(normalized), _dump(core_contract)),
                                 ScenarioGoldenOutput)
        sg = sg_model.model_dump()

        def _harness_sg_problems(data: dict) -> list[str]:
            problems = scenario_case_type_problems(
                [Scenario.model_validate(s) for s in data["scenarios"]]
            )
            scenario_ids = {s["id"] for s in data["scenarios"]}
            for g in data["goldens"]:
                if g["scenario_id"] not in scenario_ids:
                    problems.append(f"golden이 없는 scenario를 참조: {g['scenario_id']}")
            return problems

        def _write_scenarios(data: dict) -> None:
            for s in data["scenarios"]:
                write_workspace_file(workspace, _scenario_filename(s["id"]), _dump(s), secrets)
            for g in data["goldens"]:
                write_workspace_file(workspace, _golden_filename(g["scenario_id"]), _dump(g), secrets)

        _write_scenarios(sg)
        _write_run_json("oracle_risk_report.json", sg["oracle_risk"])

        sg_attempts = 0
        sg_review_model, _ = _desk_call("scenario_golden_review", "scenario_golden_review",
                                        build_scenario_golden_review_prompt(_dump(core_contract), _dump(sg)),
                                        ScenarioGoldenReview)
        sg_review = sg_review_model.model_dump()
        harness_problems = _harness_sg_problems(sg)
        sg_status = "NEEDS_REPAIR" if (harness_problems and sg_review["status"] == "PASS") else sg_review["status"]
        while sg_status != "PASS" and sg_attempts < MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS:
            sg_attempts += 1
            merged_review = dict(sg_review)
            merged_review["blocking_issues"] = harness_problems + (sg_review["blocking_issues"] or [])
            repaired_model, _ = _desk_call("scenario_golden_repair", "scenario_golden_repair",
                                           build_scenario_golden_repair_prompt(_dump(sg), _dump(merged_review)),
                                           ScenarioGoldenOutput)
            sg = repaired_model.model_dump()
            _write_scenarios(sg)
            _write_run_json("oracle_risk_report.json", sg["oracle_risk"])
            _write_run_doc("scenario_golden_repair_report.md",
                           "# Scenario/Golden Repair Report\n\n"
                           + "\n".join(f"- {i}" for i in merged_review["blocking_issues"] or ["(지시 없음)"])
                           + f"\n\n(시도 {sg_attempts}/{MAX_SCENARIO_GOLDEN_REPAIR_ATTEMPTS})\n")
            sg_review_model, _ = _desk_call("scenario_golden_review", "scenario_golden_review",
                                            build_scenario_golden_review_prompt(_dump(core_contract), _dump(sg)),
                                            ScenarioGoldenReview)
            sg_review = sg_review_model.model_dump()
            harness_problems = _harness_sg_problems(sg)
            sg_status = "NEEDS_REPAIR" if (harness_problems and sg_review["status"] == "PASS") else sg_review["status"]
        _write_run_json("scenario_golden_review.json", sg_review)
        oracle_risk_level = sg["oracle_risk"]["risk_level"]
        harness["stages"]["scenario_oracle"] = {
            "status": sg_status, "repair_attempts": sg_attempts,
            "scenario_count": len(sg["scenarios"]), "golden_count": len(sg["goldens"]),
            "oracle_risk_level": oracle_risk_level,
            "golden_strength": sg_review["golden_strength"],
        }
        log_loop_event(run_dir, secrets, stage="scenario_oracle", desk="Scenario Oracle Stage",
                       validation=sg_status,
                       output_files=[_scenario_filename(s["id"]) for s in sg["scenarios"]],
                       next_state="core_build" if sg_status == "PASS" else "stopped")
        if sg_status != "PASS":
            return _finish_needs_spec_repair("scenario_oracle", sg_review,
                                             harness_problems + (sg_review["blocking_issues"] or []))
        if oracle_risk_level != "low":
            result["auto_adjustments"].append(f"oracle risk {oracle_risk_level} → 검수 화면에 표시 (§6.7)")

        goldens = sg["goldens"]
        scenario_ids = [s["id"] for s in sg["scenarios"]]

        # ---------------------------------------------------------- Stage 3: Core Build (§7)
        _stage("core_build")
        packet_md = render_build_task_packet_md(_dump(core_contract), runner_contract, scenario_ids)
        _write_run_doc("build_task_packet.md", packet_md)
        _write_run_json("build_task_packet.json", {
            "runner_command": runner_contract["runner_command"],
            "scenario_ids": scenario_ids,
            "core_first": True,
            "candidates": eff_candidates,
        })

        def _apply_build_files(entries: list[dict], allow_product: bool = False) -> tuple[list[str], list[str]]:
            """빌드/patch 파일을 적용하되 동결 파일(fixtures/golden/contract)은 거부한다."""
            written, rejected = [], []
            for e in entries:
                path = e["path"].replace("\\", "/").lstrip("./")
                frozen = (
                    path in FROZEN_FILES
                    or any(path.startswith(pfx) for pfx in FROZEN_PATH_PREFIXES)
                    or (not allow_product and path.startswith("product/"))
                )
                if frozen:
                    rejected.append(path)
                    continue
                write_workspace_file(workspace, path, e["content"], secrets)
                written.append(path)
            return written, rejected

        build_model, _ = _desk_call("core_build", "core_build",
                                    build_core_build_prompt(packet_md, _dump(core_contract),
                                                            _dump(sg["scenarios"]),
                                                            list_workspace_files(workspace)),
                                    CoreBuildOutput)
        build_out = build_model.model_dump()
        written, rejected = _apply_build_files(build_out["files"])
        if rejected:
            log_debug_history(run_dir, secrets, {"event": "build_rejected_paths", "paths": rejected})
        if not (workspace / "run_instructions.md").is_file():
            write_workspace_file(workspace, "run_instructions.md",
                                 f"# 실행 방법\n\n```bash\n{runner_contract['runner_command']}\n```\n", secrets)
        if not (workspace / "README.md").is_file():
            write_workspace_file(workspace, "README.md",
                                 f"# {normalized['title']}\n\n{normalized['expected_artifact']}\n", secrets)
        write_workspace_file(workspace, "reports/build_report.md",
                             f"# Build Report\n\n{build_out['build_report']}\n", secrets)
        harness["stages"]["core_build"] = {"status": "DONE", "files": len(written),
                                           "candidates": eff_candidates}
        log_loop_event(run_dir, secrets, stage="core_build", desk="Core Build Stage",
                       output_files=written, validation="PASS", next_state="core_verification")

        # ---------------------------------------------------------- Stage 4: Core Verification (§8)
        def _run_and_record_gates() -> dict:
            _stage("core_verification")
            gates = run_core_gates(
                workspace, core_contract, runner_contract, goldens,
                timeout_seconds=fset.sandbox_timeout_seconds,
                use_docker=fset.docker_flag(), secrets=secrets,
            )
            for name, data in gates["artifacts"].items():
                write_workspace_file(workspace, f"{name}.json", _dump(data), secrets)
            write_workspace_file(workspace, "gate_results.json",
                                 _dump({g: {"ok": ok, "problems": gates["problems"][g]}
                                        for g, ok in gates["summary"].items()}), secrets)
            for gate in CORE_GATE_ORDER:
                log_loop_event(run_dir, secrets, stage=f"{gate}_gate", desk="Core Verification Stage",
                               worker_key_id="HARNESS",
                               validation="PASS" if gates["summary"][gate] else "FAIL",
                               error=None if gates["summary"][gate] else "; ".join(gates["problems"][gate])[:300])
            return gates

        gates = _run_and_record_gates()
        harness["stages"]["core_verification"] = {"gates": gates["summary"]}

        # ---------------------------------------------------------- Stage 5: Repair (§9, §7 재계산)
        _stage("repair")

        def _compute_build_review(gate_state: dict) -> dict:
            """현재 gate 결과로 Build Review를 (재)계산한다 (§7.2: patch 후에도 최신 gate 기준)."""
            gate_md = "\n\n".join(gate_state["results"][g].report_md() for g in CORE_GATE_ORDER)
            review_model, _ = _desk_call("build_review", "build_review",
                                         build_build_review_prompt(gate_md, _dump(core_contract),
                                                                   list_workspace_files(workspace)),
                                         BuildReview)
            review = review_model.model_dump()
            _write_run_json("build_review.json", review)
            _write_run_doc("build_review.md", "\n".join([
                "# Build Review", "",
                f"- 상태: {review['status']}",
                f"- hardcode risk: {review['hardcode_risk']}",
                f"- patch 가능: {review['patchable']}",
                "## 차단 문제",
                *[f"- {b}" for b in review["blocking_issues"] or ["(없음)"]],
                "## Patch 지시",
                *[f"- {p}" for p in review["patch_instructions"] or ["(없음)"]],
                f"\n## 다음 목표\n{review['next_goal'] or '(없음)'}",
            ]) + "\n")
            return review

        build_review = _compute_build_review(gates)
        build_review_recomputes = 0

        patch_attempts = 0
        while (not all(gates["summary"].values())
               and build_review.get("patchable", True)
               and patch_attempts < MAX_PATCH_ATTEMPTS):
            patch_attempts += 1
            failed_gates = [g for g in CORE_GATE_ORDER if not gates["summary"][g]]
            fail_md = "\n\n".join(gates["results"][g].report_md() for g in failed_gates)
            key_files = {}
            for rel in list_workspace_files(workspace):
                if rel.startswith("src/") and len(key_files) < 6:
                    key_files[rel] = read_workspace_file(workspace, rel, 4000)
            try:
                patch_model, _ = _desk_call("patch_repair", "patch_repair",
                                            build_patch_prompt(fail_md, build_review["patch_instructions"],
                                                               key_files, patch_attempts, MAX_PATCH_ATTEMPTS),
                                            PatchOutput)
            except DeskError as exc:
                log_debug_history(run_dir, secrets, {"event": "patch_desk_error", "error": str(exc)[:300]})
                break
            patch = patch_model.model_dump()
            written, rejected = _apply_build_files(patch["files"])
            log_debug_history(run_dir, secrets, {
                "event": "patch_applied", "attempt": patch_attempts,
                "failed_gates": failed_gates, "files": written, "rejected": rejected,
                "report": patch["patch_report"][:300],
            })
            log_loop_event(run_dir, secrets, stage="repair", desk="Patch Repair",
                           output_files=written, validation="APPLIED",
                           next_state="core_verification", attempt=patch_attempts)
            gates = _run_and_record_gates()
            # §7.2: patch 후 gate가 바뀌었으므로 Build Review를 최신 gate 기준으로 재계산
            build_review = _compute_build_review(gates)
            build_review_recomputes += 1

        result["patch_attempts"] = patch_attempts
        gate_summary = gates["summary"]
        result["gate_summary"] = gate_summary
        failed_scenarios = sorted(set(
            (gates["artifacts"]["scenario_replay_summary"].get("failed_scenarios") or [])
            + (gates["artifacts"]["golden_diff_summary"].get("failed_scenarios") or [])
        ))
        result["failed_scenarios"] = failed_scenarios
        harness["stages"]["repair"] = {
            "patch_attempts": patch_attempts,
            "build_review_recomputes": build_review_recomputes,
            "gates_after": gate_summary,
            "failed_scenarios": failed_scenarios,
            "build_review_status": build_review["status"],
        }

        # ---------------------------------------------------------- Stage 6: Product Layer (§10)
        _stage("product_layer")
        replay_index = read_workspace_file(workspace, "replay/index.json", 3000)
        run_instructions = read_workspace_file(workspace, "run_instructions.md", 2000)
        product_model, _ = _desk_call("product_layer", "product_layer",
                                      build_product_layer_prompt(_dump(core_contract), replay_index,
                                                                 run_instructions,
                                                                 list_workspace_files(workspace)),
                                      ProductLayerOutput)
        product_out = product_model.model_dump()

        def _apply_product_files(entries: list[dict]) -> tuple[list[str], list[str]]:
            written, rejected = [], []
            for e in entries:
                path = e["path"].replace("\\", "/").lstrip("./")
                if path.startswith("product/") or path == "run_instructions.md":
                    write_workspace_file(workspace, path, e["content"], secrets)
                    written.append(path)
                else:
                    rejected.append(path)
            return written, rejected

        def _product_files_text() -> dict[str, str]:
            return {
                rel: read_workspace_file(workspace, rel, 3000)
                for rel in list_workspace_files(workspace) if rel.startswith("product/")
            }

        def _product_harness_problems() -> list[str]:
            # §5 보강: replay artifact 실제 접근 + final_state/events/summary 소비 + core 복제 금지
            return product_layer_consumes_core(_product_files_text(), core_contract)

        written, rejected = _apply_product_files(product_out["files"])
        if rejected:
            log_debug_history(run_dir, secrets, {"event": "product_rejected_paths", "paths": rejected})

        pl_attempts = 0
        pl_review_model, _ = _desk_call("product_layer_review", "product_layer_review",
                                        build_product_layer_review_prompt(_product_files_text(),
                                                                          _dump(core_contract)),
                                        ProductLayerReview)
        pl_review = pl_review_model.model_dump()
        pl_problems = _product_harness_problems()
        pl_status = "NEEDS_REPAIR" if (pl_problems and pl_review["status"] == "PASS") else pl_review["status"]
        while pl_status != "PASS" and pl_attempts < MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS:
            pl_attempts += 1
            merged = dict(pl_review)
            merged["blocking_issues"] = pl_problems + (pl_review["blocking_issues"] or [])
            try:
                repaired_model, _ = _desk_call("product_layer_repair", "product_layer_repair",
                                               build_product_layer_repair_prompt(_product_files_text(),
                                                                                 _dump(merged)),
                                               ProductLayerOutput)
            except DeskError as exc:
                log_debug_history(run_dir, secrets, {"event": "product_repair_error", "error": str(exc)[:300]})
                break
            written, rejected = _apply_product_files(repaired_model.model_dump()["files"])
            if rejected:
                log_debug_history(run_dir, secrets, {"event": "product_rejected_paths", "paths": rejected})
            pl_review_model, _ = _desk_call("product_layer_review", "product_layer_review",
                                            build_product_layer_review_prompt(_product_files_text(),
                                                                              _dump(core_contract)),
                                            ProductLayerReview)
            pl_review = pl_review_model.model_dump()
            pl_problems = _product_harness_problems()
            pl_status = "NEEDS_REPAIR" if (pl_problems and pl_review["status"] == "PASS") else pl_review["status"]

        _write_run_json("product_layer_review.json", {**pl_review, "status": pl_status,
                                                      "harness_problems": pl_problems,
                                                      "repair_attempts": pl_attempts})
        _write_run_doc("product_layer_review.md", "\n".join([
            "# Product Layer Review", "",
            f"- 상태: {pl_status}",
            f"- repair 시도: {pl_attempts}/{MAX_PRODUCT_LAYER_REPAIR_ATTEMPTS}",
            "## 차단 문제",
            *[f"- {b}" for b in (pl_problems + (pl_review["blocking_issues"] or [])) or ["(없음)"]],
        ]) + "\n")
        harness["stages"]["product_layer"] = {"status": pl_status, "repair_attempts": pl_attempts}
        log_loop_event(run_dir, secrets, stage="product_layer", desk="Product Layer Stage",
                       validation=pl_status, next_state="verdict")

        # ---------------------------------------------------------- Stage 7: Verdict / Dashboard / Green Base (§11)
        _stage("verdict")
        anti_summary = gates["artifacts"]["anti_hardcode_summary"]
        hardcode_risk = _max_risk(anti_summary.get("hardcode_risk", "low"),
                                  build_review.get("hardcode_risk", "low"))
        stats = golden_mode_stats(goldens)
        has_transitions = any(
            (run.get("parsed") or {}).get("events")
            for run in gates["replay_outputs"].values()
        )
        next_goal = build_review.get("next_goal") or ""
        if not next_goal and failed_scenarios:
            next_goal = f"실패 scenario({', '.join(failed_scenarios)})를 통과시키는 patch"
        if not next_goal:
            next_goal = "scenario/golden 커버리지를 넓히고 core contract를 확장한다."

        verdict, reasons = decide_core_verdict(
            gate_summary=gate_summary,
            gate_problems=gates["problems"],
            artifact_class=artifact_class,
            scenario_count=len(scenario_ids),
            replay_failed=gates["replay_failed"],
            golden_failed=gates["artifacts"]["golden_diff_summary"].get("failed_scenarios") or [],
            exact_golden_count=gates["artifacts"]["golden_diff_summary"].get("exact_passed", 0),
            golden_stats=stats,
            oracle_risk_level=oracle_risk_level,
            hardcode_risk=hardcode_risk,
            product_layer_status=pl_status,
            golden_strength=sg_review["golden_strength"],
            patchable=build_review.get("patchable", True),
            next_goal=next_goal,
            has_state_transitions=has_transitions,
        )
        result["verdict"] = verdict
        recommended = CORE_VERDICT_TO_RECOMMENDED_ACTION.get(verdict, "drop")
        result["recommended_action"] = recommended

        gates_passed = sum(1 for g in CORE_GATE_ORDER if gate_summary.get(g))
        risk_display = _max_risk(hardcode_risk, oracle_risk_level)

        verdict_md = "\n".join([
            "# Product Verdict", "",
            "## 최종 판정", verdict, "",
            f"- 라인: {line}",
            f"- 산출물 유형: {ARTIFACT_CLASS_LABELS.get(artifact_class, artifact_class)} ({artifact_class})",
            f"- 검증: {gates_passed}/{len(CORE_GATE_ORDER)} 통과",
            f"- 결정성: {'통과' if gate_summary.get('determinism') else '실패'}",
            f"- hardcode risk: {hardcode_risk} / oracle risk: {oracle_risk_level}",
            f"- product layer: {pl_status}",
            f"- 추천 버튼: {recommended.upper()}",
            "",
            "## 판정 근거",
            *[f"- {r}" for r in reasons],
            "",
            "## Gate 결과",
            *[f"- {g}: {'PASS' if gate_summary.get(g) else 'FAIL'}" for g in CORE_GATE_ORDER],
            "",
            "## 자동 보정",
            *[f"- {a}" for a in result["auto_adjustments"] or ["(없음)"]],
            "",
            f"## 다음 목표\n{next_goal}",
        ]) + "\n"
        _write_run_doc("product_verdict.md", verdict_md)

        # regression 준비 (§8.2: Phase 1.6은 green_base 저장 중심으로 준비만)
        regression_suite = [_scenario_filename(sid) for sid in scenario_ids]

        # Green Base vs Continuation Base (§6): 명칭·조건 분리 — 일부 gate 실패는 green이 아님
        green_base_path = None
        continuation_base_path = None
        gates_all_pass = all(gate_summary.get(g) for g in CORE_GATE_ORDER)
        base_common = {
            "verdict": verdict,
            "failed_scenarios": failed_scenarios,
            "golden_diff": gates["artifacts"]["golden_diff_summary"],
            "next_goal": next_goal,
            "allowed_touch_files": ["src/", "product/", "run_instructions.md", "README.md"],
            "frozen_files": list(FROZEN_FILES) + ["fixtures/", "golden/"],
            "regression_suite": regression_suite,
        }
        # green_base (§6.3): 모든 필수 core gate 통과 + product layer PASS + hardcode low/medium
        green_ready = (gates_all_pass and pl_status == "PASS"
                       and hardcode_risk in ("low", "medium") and bool(next_goal))
        # continuation_base (§6.3): core_contract+runner는 통과, 일부 gate 실패, patch 가능, hardcode high 아님
        continuation_ready = (bool(gate_summary.get("core_contract")) and bool(gate_summary.get("runner"))
                              and build_review.get("patchable", True)
                              and hardcode_risk != "high" and bool(next_goal))
        if green_ready:
            snap = save_green_base(run_dir, workspace, f"green_core_{patch_attempts:02d}")
            green_base_path = str(snap)
            _write_run_json("green_base.json", {"base_type": "green_base",
                                                "green_base_path": green_base_path, **base_common})
        elif continuation_ready:
            snap = save_green_base(run_dir, workspace, f"continuation_core_{patch_attempts:02d}")
            continuation_base_path = str(snap)
            _write_run_json("continuation_base.json", {"base_type": "continuation_base",
                                                       "continuation_base_path": continuation_base_path,
                                                       **base_common})
        result["green_base_path"] = green_base_path
        result["continuation_base_path"] = continuation_base_path

        write_workspace_file(workspace, "regression_summary.json", _dump({
            "status": "PREPARED",
            "note": "본격적인 Regression Gate는 Phase 2 범위 (§8.2). base 저장까지만 준비.",
            "green_base_path": green_base_path,
            "continuation_base_path": continuation_base_path,
            "regression_suite": regression_suite,
        }), secrets)

        # 요약 산출물 (§11.3)
        core_system_summary = {
            "artifact_class": artifact_class,
            "core_goal": core_contract.get("core_goal"),
            "state_entities": [e.get("name") for e in core_contract.get("state_entities") or []],
            "actions": [a.get("name") for a in core_contract.get("actions") or []],
            "runner_command": runner_contract.get("runner_command"),
            "scenario_count": len(scenario_ids),
            "golden_modes": stats["modes"],
            "exact_golden_count": stats["exact_count"],
            "has_state_transitions": has_transitions,
        }
        _write_run_json("core_system_summary.json", core_system_summary)

        product_layer_consumes = pl_status == "PASS" and not pl_problems
        harness["stages"]["verdict"] = {"verdict": verdict, "recommended_action": recommended,
                                        "green_base_saved": green_base_path is not None,
                                        "continuation_base_saved": continuation_base_path is not None,
                                        "product_layer_consumes_core": product_layer_consumes}
        harness["gate_summary"] = gate_summary
        harness["hardcode_risk"] = hardcode_risk
        harness["oracle_risk_level"] = oracle_risk_level
        _write_run_json("harness_summary.json", harness)

        dashboard_summary = {
            "verdict": verdict,
            "headline": {
                "REVIEW_READY": "검수 가능",
                "NEEDS_MORE_GEMMA_LOOP": "더 돌려야 함",
                "RUNS_BUT_WEAK": "약함",
                "KEEP_CANDIDATE": "보관 후보",
                "DROP": "버림",
                "PROMOTE_TO_CODEX": "제품화 후보",
            }.get(verdict, verdict),
            "artifact_class": artifact_class,
            "artifact_class_ko": ARTIFACT_CLASS_LABELS.get(artifact_class, artifact_class),
            "core_present": bool(gate_summary.get("core_contract") and gate_summary.get("runner")),
            "gates_passed": gates_passed,
            "gates_total": len(CORE_GATE_ORDER),
            "gates": gate_summary,
            "determinism": "통과" if gate_summary.get("determinism") else "실패",
            "risk_level": {"low": "낮음", "medium": "중간", "high": "높음"}.get(risk_display, risk_display),
            "hardcode_risk": hardcode_risk,
            "oracle_risk_level": oracle_risk_level,
            "recommendation": {
                "REVIEW_READY": "실행해보고 판단",
                "NEEDS_MORE_GEMMA_LOOP": "한 번 더 돌린 뒤 확인",
                "RUNS_BUT_WEAK": "보류 또는 버림",
                "KEEP_CANDIDATE": "보관",
                "DROP": "버림",
                "PROMOTE_TO_CODEX": "제품화 검토",
            }.get(verdict, "보류 또는 버림"),
            "failed_scenarios": failed_scenarios,
            "next_goal": next_goal,
            "run_instructions": "run_instructions.md",
            "product_layer_dir": "product/",
            "runner_command": runner_contract.get("runner_command"),
            # Phase 1.6b 보강 표시 (§10)
            "green_base": green_base_path is not None,
            "continuation_base": continuation_base_path is not None,
            "product_layer_consumes_core": product_layer_consumes,
            "is_live_validation": bool(live_validation),
        }
        _write_run_json("dashboard_summary.json", dashboard_summary)

        # Live Validation 판정 검증표 (§9): live 검증 run에서만 생성
        if live_validation:
            live_summary = build_live_validation_summary(
                challenge_id=challenge_id, run_id=run_id, verdict=verdict,
                gate_summary=gate_summary, hardcode_risk=hardcode_risk,
                product_layer_status=pl_status, has_state_transitions=has_transitions,
                scenario_count=len(scenario_ids), gate_hardening_applied=list(GATE_HARDENING_APPLIED),
            )
            _write_run_json("live_validation_summary.json", live_summary)

        # Product Dashboard 호환 요약 (기존 화면이 그대로 읽는 product_summary.json)
        issue = ("특이 결함 없음" if gates_all_pass
                 else "실패 scenario: " + ", ".join(failed_scenarios) if failed_scenarios
                 else "core gate 일부 실패")
        product_summary = {
            "product_run_id": run_id,
            "challenge_id": challenge_id,
            "challenge_title": card.get("challenge_title"),
            "status": "done",
            "stage": "verdict",
            "verdict": verdict,
            "recommended_action": recommended.upper(),
            "reason": "; ".join(reasons)[:400],
            "issue_summary": issue,
            "known_issues": [f"gate 실패: {g}" for g in CORE_GATE_ORDER if not gate_summary.get(g)],
            "next_goal": next_goal,
            "workspace_dir": str(workspace),
            "final_artifact_dir": None,  # 아래에서 채움
            "codex_export_dir": None,
            "challenge_anchors": card.get("difficulty_anchors") or [],
            "challenge_forbidden": card.get("forbidden_simplifications") or [],
            "owner_brief_summary": card.get("one_line_challenge") or card.get("repo_summary") or "",
        }

        # Final Artifact 조립
        _stage("final_artifact")
        final_dir = run_dir / "final_artifact"
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.copytree(workspace, final_dir)
        (final_dir / "product_verdict.md").write_text(redact_text(verdict_md, secrets), encoding="utf-8")
        debug_history = run_dir / "debug_history.jsonl"
        if debug_history.is_file():
            shutil.copy2(debug_history, final_dir / "debug_history.jsonl")
        result["final_artifact_dir"] = str(final_dir)
        product_summary["final_artifact_dir"] = str(final_dir)

        eval_summary = {
            "verdict": verdict,
            "reasons": reasons,
            "gate_summary": gate_summary,
            "failed_scenarios": failed_scenarios,
            "patch_attempts": patch_attempts,
            "product_layer_status": pl_status,
            "hardcode_risk": hardcode_risk,
            "oracle_risk_level": oracle_risk_level,
            "exact_golden_count": stats["exact_count"],
            "green_base_path": green_base_path,
            "continuation_base_path": continuation_base_path,
            "product_layer_consumes_core": product_layer_consumes,
            "next_goal": next_goal,
            "auto_adjustments": result["auto_adjustments"],
        }
        _write_run_json("product_eval_summary.json", eval_summary)
        for name, data in (("product_summary.json", product_summary),
                           ("dashboard_summary.json", dashboard_summary),
                           ("harness_summary.json", harness),
                           ("core_system_summary.json", core_system_summary),
                           ("product_eval_summary.json", eval_summary)):
            (final_dir / name).write_text(redact_text(_dump(data), secrets), encoding="utf-8")
        _write_run_json("product_summary.json", product_summary)
        if live_validation:
            (final_dir / "live_validation_summary.json").write_text(
                redact_text(_dump(live_summary), secrets), encoding="utf-8")

        # PROMOTE_TO_CODEX export bundle (자동 호출 아님, §3)
        if verdict == "PROMOTE_TO_CODEX":
            export_dir = _assemble_core_codex_export(run_dir, workspace, card, next_goal,
                                                     eval_summary, secrets)
            result["codex_export_dir"] = str(export_dir)
            product_summary["codex_export_dir"] = str(export_dir)
            if db_conn is not None and run_id is not None:
                add_product_artifact(db_conn, run_id, "codex_export", str(export_dir))

        # secret scan (전체 run_dir)
        leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
        if leaked:
            result["error"] = f"secret 노출 파일: {leaked}"

        if db_conn is not None and run_id is not None:
            update_product_run(
                db_conn, run_id, status="done", current_stage="final_artifact",
                final_artifact_dir=str(final_dir), verdict=verdict,
                artifact_class=artifact_class,
                harness_summary_path=str(run_dir / "harness_summary.json"),
                core_system_summary_path=str(run_dir / "core_system_summary.json"),
                green_base_path=green_base_path,
            )
            add_product_artifact(db_conn, run_id, "workspace", str(workspace))
            add_product_artifact(db_conn, run_id, "final_artifact", str(final_dir))
            add_product_artifact(db_conn, run_id, "product_verdict", str(final_dir / "product_verdict.md"))
            if green_base_path:
                add_product_artifact(db_conn, run_id, "green_base", green_base_path)
            log_product_event(db_conn, run_id, "core_factory_done", f"verdict={verdict}",
                              metadata={"gate_summary": gate_summary,
                                        "patch_attempts": patch_attempts})

        log_loop_event(run_dir, secrets, stage="verdict", validation="PASS",
                       verdict=verdict, next_state="dashboard_review")
        result["ok"] = result["error"] is None
        return result

    except DeskError as exc:
        return _fail_run("desk_error", str(exc))
    except Exception as exc:  # noqa: BLE001 - run 하나의 실패가 상위 루프를 죽이면 안 됨
        return _fail_run("internal_error", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- codex export (§11.9, bundle 생성까지만)

def _assemble_core_codex_export(run_dir: Path, workspace: Path, card: dict, next_goal: str,
                                eval_summary: dict, secrets: list[str]) -> Path:
    from repo_idea_miner.challenge_renderer import render_challenge_card_md

    export_dir = run_dir / "codex_export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)
    shutil.copytree(workspace, export_dir / "source_workspace")
    (export_dir / "challenge_card.md").write_text(
        redact_text(render_challenge_card_md(card), secrets), encoding="utf-8"
    )
    (export_dir / "core_eval_summary.json").write_text(
        redact_text(json.dumps(eval_summary, ensure_ascii=False, indent=2), secrets), encoding="utf-8"
    )
    known = [f"gate {g}: FAIL" for g, ok in (eval_summary.get("gate_summary") or {}).items() if not ok]
    (export_dir / "known_issues.md").write_text(
        redact_text("# Known Issues\n\n" + ("\n".join(f"- {k}" for k in known) or "- (없음)") + "\n", secrets),
        encoding="utf-8",
    )
    (export_dir / "next_goal.md").write_text(
        redact_text(f"# Next Goal\n\n{next_goal}\n", secrets), encoding="utf-8"
    )
    return export_dir
