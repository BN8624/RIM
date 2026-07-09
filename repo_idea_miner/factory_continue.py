# Phase 1.7 Continuation Delta Loop: continuation_base를 읽어 실패 분류·delta patch·gate 재검증·green 승격 판단 파이프라인 (§6~17).
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.factory_core_gates import (
    PRODUCT_READ_LIMIT,
    product_layer_consumes_core,
    run_core_gates,
)
from repo_idea_miner.factory_core_prompts import (
    build_build_review_prompt,
    build_continuation_patch_prompt,
    mock_build_review_pass,
    mock_continuation_patch_output,
)
from repo_idea_miner.factory_core_schemas import CORE_GATE_ORDER, BuildReview, PatchOutput
from repo_idea_miner.factory_db import (
    add_product_artifact,
    create_product_run,
    get_product_run,
    log_product_event,
    update_product_run,
)
from repo_idea_miner.factory_desks import DeskError, DeskExecutor
from repo_idea_miner.factory_pipeline import FactorySettings, load_factory_settings, make_factory_run_dir
from repo_idea_miner.factory_workspace import (
    list_workspace_files,
    log_debug_history,
    read_workspace_file,
    save_green_base,
    write_workspace_file,
)
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient
from repo_idea_miner.redaction import redact_text, scan_files_for_secrets

# ---------------------------------------------------------------- 상수 (§8, §11)

FAILURE_TYPES = (
    "GOLDEN_SCHEMA_MISMATCH",
    "RUNNER_OUTPUT_EXTRA_FIELD",
    "RUNNER_OUTPUT_MISSING_FIELD",
    "STATE_INVARIANT_NOT_EXPOSED",
    "SCENARIO_REPLAY_FAILURE",
    "DETERMINISM_FAILURE",
    "PRODUCT_LAYER_NOT_CONSUMING_REPLAY",
    "ANTI_HARDCODE_FAILURE",
    "PATCH_TRANSIENT_FAILURE",
    "SPEC_REPAIR_REQUIRED",
)

MAX_CONTINUATION_PATCH_ATTEMPTS = 2
MAX_PATCH_TRANSIENT_RETRIES = 2

FROZEN_FILES = (
    "core_contract.json",
    "state_contract.json",
    "action_contract.json",
    "runner_contract.json",
)
FROZEN_PATH_PREFIXES = ("fixtures/", "golden/", "replay/")
ALLOWED_TOUCH_PREFIXES = ("src/", "product/")
ALLOWED_TOUCH_FILES = ("README.md", "run_instructions.md")

# patch 대상 파일과 연결되는 failure type (§9.1)
_PATCHABLE_TARGET = {
    "PRODUCT_LAYER_NOT_CONSUMING_REPLAY": "product/",
    "STATE_INVARIANT_NOT_EXPOSED": "src/",
    "RUNNER_OUTPUT_MISSING_FIELD": "src/",
    "SCENARIO_REPLAY_FAILURE": "src/",
    "DETERMINISM_FAILURE": "src/",
}


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _max_risk(*levels: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    return max(levels, key=lambda level: order.get(level, 1))


# ---------------------------------------------------------------- Load Continuation Base (§7)

def load_continuation_base(base_run_dir: Path) -> dict:
    """기존 run에서 continuation에 필요한 정보를 읽는다. 실패 시 status=CANNOT_CONTINUE."""
    ws = base_run_dir / "workspace"
    core_contract = _load_json(ws / "core_contract.json")
    runner_contract = _load_json(ws / "runner_contract.json")
    cont = _load_json(base_run_dir / "continuation_base.json")
    green = _load_json(base_run_dir / "green_base.json")
    base_json = cont or green
    dashboard = _load_json(base_run_dir / "dashboard_summary.json") or {}
    anti = _load_json(ws / "anti_hardcode_summary.json") or {}
    oracle = _load_json(base_run_dir / "oracle_risk_report.json") or {}

    hardcode_risk = anti.get("hardcode_risk") or dashboard.get("hardcode_risk") or "low"
    oracle_risk = oracle.get("risk_level") or dashboard.get("oracle_risk_level") or "low"

    problems: list[str] = []
    if runner_contract is None or not (runner_contract.get("runner_command")):
        problems.append("runner 없음")
    if core_contract is None:
        problems.append("core_contract 없음")
    if base_json is None:
        problems.append("continuation_base 없음")
    if hardcode_risk == "high":
        problems.append("hardcode risk high")
    if oracle_risk == "high":
        problems.append("oracle risk high")
    allowed = (base_json or {}).get("allowed_touch_files")
    frozen = (base_json or {}).get("frozen_files")
    if not allowed:
        problems.append("allowed_touch_files 없음")
    if not frozen:
        problems.append("frozen_files 없음")

    return {
        "ok": not problems,
        "problems": problems,
        "base_json": base_json,
        "core_contract": core_contract,
        "runner_contract": runner_contract,
        "dashboard": dashboard,
        "hardcode_risk": hardcode_risk,
        "oracle_risk": oracle_risk,
        "allowed_touch_files": allowed or list(ALLOWED_TOUCH_PREFIXES) + list(ALLOWED_TOUCH_FILES),
        "frozen_files": frozen or (list(FROZEN_FILES) + ["fixtures/", "golden/"]),
        "base_type": (base_json or {}).get("base_type", "continuation_base"),
        "green_present": green is not None,
    }


# ---------------------------------------------------------------- Failure Classifier (§8)

def classify_failures(
    gate_summary: dict,
    golden_diff: dict,
    invariant_summary: dict,
    replay_summary: dict,
    determinism_summary: dict,
    anti_hardcode_summary: dict,
    product_layer_problems: list[str],
    patch_transient: bool = False,
) -> list[dict]:
    """gate 실패를 수리 가능한 failure type으로 분류한다 (§8.2). 각 항목은 repairable/requires_spec_repair 포함."""
    failures: list[dict] = []

    def _add(ftype: str, evidence: str, repairable: bool, requires_spec_repair: bool):
        failures.append({
            "type": ftype, "evidence": evidence,
            "repairable": repairable, "requires_spec_repair": requires_spec_repair,
        })

    # Golden 스키마 불일치
    if golden_diff and golden_diff.get("status") == "FAIL":
        diff_lines: list[str] = []
        for d in golden_diff.get("diffs") or []:
            diff_lines += d.get("diffs") or []
        blob = " ".join(diff_lines)
        if "골든에 없는 키" in blob or "golden에 없는 키" in blob:
            _add("RUNNER_OUTPUT_EXTRA_FIELD",
                 "runner output has fields not present in frozen golden",
                 repairable=True, requires_spec_repair=True)
        if "출력에 없는 키" in blob:
            _add("RUNNER_OUTPUT_MISSING_FIELD",
                 "runner output missing fields the golden expects",
                 repairable=True, requires_spec_repair=False)
        # 값/이벤트/summary 불일치가 남아 있으면 golden 스키마 자체 불일치
        value_mismatch = any("기대" in ln and "실제" in ln for ln in diff_lines)
        extra_key = "골든에 없는 키" in blob or "golden에 없는 키" in blob
        if value_mismatch or extra_key:
            _add("GOLDEN_SCHEMA_MISMATCH",
                 "golden expected schema disagrees with runner output (golden behind runner)",
                 repairable=True, requires_spec_repair=extra_key)

    # State invariant 노출 실패
    if invariant_summary and invariant_summary.get("status") == "FAIL":
        not_exposed = invariant_summary.get("not_exposed") or []
        failed = invariant_summary.get("failed") or []
        if not_exposed:
            paths = ", ".join(sorted({v.get("invariant", "") for v in not_exposed}))
            _add("STATE_INVARIANT_NOT_EXPOSED",
                 f"contract invariants not exposed in runner final_state: {paths}",
                 repairable=True, requires_spec_repair=False)
        if failed:
            _add("STATE_INVARIANT_NOT_EXPOSED",
                 "invariant value violated in final_state (core logic mismatch)",
                 repairable=True, requires_spec_repair=False)

    # Scenario replay 실패
    if replay_summary and replay_summary.get("failed_scenarios"):
        _add("SCENARIO_REPLAY_FAILURE",
             f"scenario replay failed: {replay_summary.get('failed_scenarios')}",
             repairable=True, requires_spec_repair=False)

    # Determinism 실패
    if determinism_summary and determinism_summary.get("status") == "FAIL":
        _add("DETERMINISM_FAILURE",
             f"non-deterministic output: {determinism_summary.get('static_problems') or determinism_summary.get('mismatches')}",
             repairable=True, requires_spec_repair=False)

    # Anti-hardcode 실패 (high면 애초에 CANNOT_CONTINUE지만 방어적으로 분류)
    if anti_hardcode_summary and anti_hardcode_summary.get("hardcode_risk") == "high":
        _add("ANTI_HARDCODE_FAILURE",
             "hardcoded/stubbed output suspected",
             repairable=False, requires_spec_repair=False)

    # Product layer replay 소비 실패
    if product_layer_problems:
        _add("PRODUCT_LAYER_NOT_CONSUMING_REPLAY",
             "; ".join(product_layer_problems),
             repairable=True, requires_spec_repair=False)

    if patch_transient:
        _add("PATCH_TRANSIENT_FAILURE", "patch model call failed transiently",
             repairable=True, requires_spec_repair=False)

    # golden 수정이 필요한(spec repair) 항목이 있으면 별도 표식
    if any(f["requires_spec_repair"] for f in failures):
        _add("SPEC_REPAIR_REQUIRED",
             "golden/contract update needed; frozen in Phase 1.7 auto-patch",
             repairable=False, requires_spec_repair=True)
    return failures


# ---------------------------------------------------------------- Repair Plan Builder (§9)

def build_repair_plan(failures: list[dict], allowed_touch_files: list[str], frozen_files: list[str]) -> dict:
    """failure 분류에서 구체적 repair plan을 만든다. frozen을 건드리는 항목은 spec repair로 분리."""
    steps: list[dict] = []
    seen_targets: set[str] = set()
    for f in failures:
        if f["requires_spec_repair"] or not f["repairable"]:
            continue
        target = _PATCHABLE_TARGET.get(f["type"])
        if target is None:
            continue
        key = (target, f["type"])
        if key in seen_targets:
            continue
        seen_targets.add(key)
        steps.append({
            "target": target,
            "reason": {
                "PRODUCT_LAYER_NOT_CONSUMING_REPLAY":
                    "Consume replay/index.json and render final_state/events/summary",
                "STATE_INVARIANT_NOT_EXPOSED":
                    "Expose contract invariant fields in runner final_state",
                "RUNNER_OUTPUT_MISSING_FIELD":
                    "Add missing output fields the golden expects",
                "SCENARIO_REPLAY_FAILURE": "Fix runner so all scenarios replay",
                "DETERMINISM_FAILURE": "Remove non-deterministic sources",
            }.get(f["type"], "Repair"),
            "failure_type": f["type"],
        })
    requires_spec_repair = any(f["requires_spec_repair"] for f in failures)
    return {
        "repair_scope": "delta_patch",
        "allowed_touch_files": allowed_touch_files,
        "frozen_files": frozen_files,
        "steps": steps,
        "requires_spec_repair": requires_spec_repair,
    }


def _repair_plan_md(plan: dict) -> str:
    lines = ["# Repair Plan", "", f"scope: {plan['repair_scope']}",
             f"spec repair 필요: {plan['requires_spec_repair']}", "", "## Steps"]
    for s in plan["steps"] or []:
        lines.append(f"- [{s['failure_type']}] {s['target']} — {s['reason']}")
    if not plan["steps"]:
        lines.append("- (자동 patch 대상 없음 — 전부 spec repair 필요)")
    return "\n".join(lines) + "\n"


def _failure_md(failures: list[dict]) -> str:
    lines = ["# Failure Classification", ""]
    for f in failures:
        flag = " (spec repair)" if f["requires_spec_repair"] else ""
        lines.append(f"- **{f['type']}**{flag}: {f['evidence']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 파이프라인 본체 (§6)

def run_continuation(
    base_run_dir: str | Path | None = None,
    base_run_id: int | None = None,
    mode: str = "mock",
    max_patches: int = MAX_CONTINUATION_PATCH_ATTEMPTS,
    output_dir: str | Path = "runs",
    db_conn=None,
    settings: Settings | None = None,
    factory_settings: FactorySettings | None = None,
    scheduler=None,
    llm=None,
    sleep_fn=time.sleep,
) -> dict:
    """continuation_base 1건을 delta loop로 재검증한다 (§6). 반환: 요약 dict."""
    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    secrets = settings.secret_values()

    result: dict = {
        "ok": False, "status": None, "continuation_run_dir": None,
        "base_run_id": base_run_id, "base_run_dir": None, "challenge_id": None,
        "verdict": None, "promoted_to_green_base": False, "green_base_path": None,
        "failure_types": [], "resolved": {}, "patch_attempts": 0,
        "transient_retries": 0, "rejected_patches": [], "error": None,
    }

    # run_id → run_dir
    if base_run_dir is None and base_run_id is not None and db_conn is not None:
        run = get_product_run(db_conn, base_run_id)
        if run is None:
            result["error"] = f"run_id {base_run_id} 없음"
            return result
        base_run_dir = Path(run["workspace_dir"]).parent
        result["challenge_id"] = run.get("challenge_id")
    if base_run_dir is None:
        result["error"] = "--run-id 또는 --run-dir가 필요합니다."
        return result
    base_run_dir = Path(base_run_dir)
    result["base_run_dir"] = str(base_run_dir)

    # 1. Load Continuation Base (§7)
    base = load_continuation_base(base_run_dir)
    if not base["ok"]:
        result["status"] = "CANNOT_CONTINUE"
        result["error"] = "; ".join(base["problems"])
        return result

    core_contract = base["core_contract"]
    runner_contract = base["runner_contract"]
    allowed = base["allowed_touch_files"]
    frozen = base["frozen_files"]

    # continuation run 디렉터리 + workspace seed (continuation_base snapshot 우선)
    cont_dir = make_factory_run_dir(output_dir)
    workspace = cont_dir / "workspace"
    seed = _resolve_seed(base_run_dir, base["base_json"])
    shutil.copytree(seed, workspace)
    result["continuation_run_dir"] = str(cont_dir)

    goldens = [
        _load_json(p) for p in sorted((workspace / "golden").glob("expected_*.json"))
        if _load_json(p) is not None
    ]

    if llm is None and mode == "mock":
        llm = MockLLMClient(overrides={
            "continuation_patch": mock_continuation_patch_output(),
            "build_review": mock_build_review_pass(),
        }, call_logger=LLMCallLogger(cont_dir / "debug" / "llm_calls.jsonl", secrets))
    call_logger = LLMCallLogger(cont_dir / "debug" / "llm_calls.jsonl", secrets)
    executor = DeskExecutor(mode, settings, scheduler=scheduler, llm=llm, call_logger=call_logger)

    run_id = None
    if db_conn is not None:
        run_id = create_product_run(db_conn, result["challenge_id"], str(workspace),
                                    base["dashboard"].get("line") or "standard")
        result["continuation_run_id"] = run_id
        log_product_event(db_conn, run_id, "continuation_start",
                          f"base_run_dir={base_run_dir} mode={mode}")

    def _write(name: str, text: str) -> None:
        (cont_dir / name).write_text(redact_text(text, secrets), encoding="utf-8")

    def _write_json(name: str, data) -> None:
        _write(name, _dump(data))

    def _rerun_gates() -> dict:
        gates = run_core_gates(workspace, core_contract, runner_contract, goldens,
                               timeout_seconds=fset.sandbox_timeout_seconds,
                               use_docker=fset.docker_flag(), secrets=secrets)
        for name, data in gates["artifacts"].items():
            write_workspace_file(workspace, f"{name}.json", _dump(data), secrets)
        return gates

    def _product_problems() -> list[str]:
        files = {rel: read_workspace_file(workspace, rel, PRODUCT_READ_LIMIT)
                 for rel in list_workspace_files(workspace) if rel.startswith("product/")}
        return product_layer_consumes_core(files, core_contract)

    def _classify(gates: dict, patch_transient: bool) -> list[dict]:
        return classify_failures(
            gate_summary=gates["summary"],
            golden_diff=gates["artifacts"]["golden_diff_summary"],
            invariant_summary=gates["artifacts"]["state_invariant_summary"],
            replay_summary=gates["artifacts"]["scenario_replay_summary"],
            determinism_summary=gates["artifacts"]["determinism_summary"],
            anti_hardcode_summary=gates["artifacts"]["anti_hardcode_summary"],
            product_layer_problems=_product_problems(),
            patch_transient=patch_transient,
        )

    # 2~3. 초기 gate 재실행 + Failure Classifier + Repair Plan
    gates = _rerun_gates()
    failures = _classify(gates, patch_transient=False)
    plan = build_repair_plan(failures, allowed, frozen)
    _write_json("failure_classification.json", {
        "base_run_id": base_run_id, "challenge_id": result["challenge_id"],
        "failure_types": failures,
    })
    _write("failure_classification.md", _failure_md(failures))
    _write_json("repair_plan.json", {"base_run_id": base_run_id, **plan})
    _write("repair_plan.md", _repair_plan_md(plan))
    result["failure_types"] = [f["type"] for f in failures]

    # 4. Patch Task Packet + 5. Patch Repair loop (§10, §11, §12)
    build_review = None
    transient_total = 0
    patch_attempts = 0
    initial_problem_types = {f["type"] for f in failures if not f["requires_spec_repair"]}
    # patchable 실패(product/invariant/runner 등)가 남아 있는 한 patch (§6). core gate 전부 통과여도
    # product layer 미소비는 patch 대상이므로 gate-all-pass만으로 종료하지 않는다.
    while plan["steps"] and patch_attempts < max_patches:
        patch_attempts += 1
        key_files = _collect_key_files(workspace, plan)
        packet_md = _patch_task_packet_md(plan, failures, patch_attempts, max_patches)
        if patch_attempts == 1:
            _write("patch_task_packet.md", packet_md)
            _write_json("patch_task_packet.json", {"steps": plan["steps"],
                                                   "allowed_touch_files": allowed,
                                                   "frozen_files": frozen})
        patch, transient, err = _patch_with_retry(
            executor, packet_md, _failure_md(failures), key_files, allowed, frozen,
            patch_attempts, max_patches, MAX_PATCH_TRANSIENT_RETRIES, sleep_fn,
            lambda rec: log_debug_history(cont_dir, secrets, rec),
        )
        transient_total += transient
        if patch is None:
            # transient/모델 실패 최종 → NEEDS_MORE_GEMMA_LOOP 유지 (§11.4, §12.3)
            log_debug_history(cont_dir, secrets, {"event": "patch_final_fail", "error": str(err)[:200]})
            failures = _classify(gates, patch_transient=True)
            break
        written, rejected = _apply_continuation_files(workspace, patch["files"], allowed, frozen, secrets)
        result["rejected_patches"] += rejected
        if rejected:
            _write_json("patch_rejection_report.json", {"attempt": patch_attempts, "rejected": rejected})
        log_debug_history(cont_dir, secrets, {"event": "continuation_patch_applied",
                                              "attempt": patch_attempts, "written": written,
                                              "rejected": rejected, "report": patch["patch_report"][:200]})
        gates = _rerun_gates()
        build_review = _compute_build_review(executor, gates, core_contract, workspace, _write_json)
        failures = _classify(gates, patch_transient=False)
        plan = build_repair_plan(failures, allowed, frozen)

    result["patch_attempts"] = patch_attempts
    result["transient_retries"] = transient_total

    # 6. Product Layer recheck (§14)
    product_problems = _product_problems()
    product_consumes = not product_problems
    _write_json("product_layer_recheck.json", {
        "consumes_replay_output": product_consumes,
        "problems": product_problems,
    })

    # 재분류(최종) + 해결 여부
    final_failures = _classify(gates, patch_transient=result["transient_retries"] > 0 and patch_attempts >= max_patches)
    final_types = {f["type"] for f in final_failures}
    result["resolved"] = {t: (t not in final_types) for t in sorted(initial_problem_types)}

    # 7. Build Review 최종 기록
    if build_review is None:
        build_review = _compute_build_review(executor, gates, core_contract, workspace, _write_json)

    # gate rerun 요약
    gate_summary = gates["summary"]
    _write_json("gate_rerun_summary.json", {
        "gates": gate_summary,
        "gates_passed": sum(1 for g in CORE_GATE_ORDER if gate_summary.get(g)),
        "gates_total": len(CORE_GATE_ORDER),
        "failed_scenarios": gates["artifacts"]["golden_diff_summary"].get("failed_scenarios") or [],
        "product_layer_consumes_core": product_consumes,
        "build_review_status": (build_review or {}).get("status"),
    })

    # 10. Green Base Promotion Check (§17)
    hardcode_risk = _max_risk(gates["artifacts"]["anti_hardcode_summary"].get("hardcode_risk", "low"),
                              base["hardcode_risk"])
    promo = decide_promotion(gate_summary, product_consumes, hardcode_risk, base["oracle_risk"],
                             final_failures, base["base_json"].get("next_goal") or "")
    result["verdict"] = promo["new_verdict"]
    result["promoted_to_green_base"] = promo["promoted_to_green_base"]

    green_base_path = None
    if promo["promoted_to_green_base"]:
        snap = save_green_base(cont_dir, workspace, f"green_core_{patch_attempts:02d}")
        green_base_path = str(snap)
        _write_json("green_base.json", {"base_type": "green_base", "green_base_path": green_base_path,
                                        "verdict": promo["new_verdict"], "next_goal": promo["next_goal"],
                                        "allowed_touch_files": allowed, "frozen_files": frozen})
    result["green_base_path"] = green_base_path

    green_promotion = {
        "base_run_id": base_run_id,
        "continuation_run_id": result.get("continuation_run_id"),
        "promoted_to_green_base": promo["promoted_to_green_base"],
        "new_verdict": promo["new_verdict"],
        "remaining_failures": promo["remaining_failures"],
        "next_goal": promo["next_goal"],
    }
    _write_json("green_base_promotion.json", green_promotion)

    # 11. Dashboard / Report (§18)
    dashboard_summary = _continuation_dashboard_summary(
        base, result, gate_summary, product_consumes, promo, green_base_path is not None)
    _write_json("phase17_dashboard_summary.json", dashboard_summary)
    _write_json("dashboard_summary.json", dashboard_summary)

    continuation_summary = {
        "base_run_id": base_run_id, "base_run_dir": str(base_run_dir),
        "challenge_id": result["challenge_id"], "mode": mode,
        "verdict": promo["new_verdict"], "promoted_to_green_base": promo["promoted_to_green_base"],
        "failure_types": result["failure_types"], "resolved": result["resolved"],
        "patch_attempts": patch_attempts, "transient_retries": transient_total,
        "rejected_patches": result["rejected_patches"],
        "requires_spec_repair": plan["requires_spec_repair"],
    }
    _write_json("continuation_run_summary.json", continuation_summary)

    # final_artifact 조립
    final_dir = cont_dir / "final_artifact"
    if final_dir.exists():
        shutil.rmtree(final_dir)
    shutil.copytree(workspace, final_dir)
    for name in ("dashboard_summary.json", "phase17_dashboard_summary.json",
                 "green_base_promotion.json", "continuation_run_summary.json",
                 "failure_classification.json", "product_layer_recheck.json"):
        src = cont_dir / name
        if src.is_file():
            (final_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    result["final_artifact_dir"] = str(final_dir)

    # secret scan
    leaked = scan_files_for_secrets([p for p in cont_dir.rglob("*") if p.is_file()], secrets)
    if leaked:
        result["error"] = f"secret 노출 파일: {leaked}"

    if db_conn is not None and run_id is not None:
        update_product_run(db_conn, run_id, status="done", current_stage="continuation",
                           final_artifact_dir=str(final_dir), verdict=promo["new_verdict"],
                           green_base_path=green_base_path)
        add_product_artifact(db_conn, run_id, "continuation_final", str(final_dir))
        log_product_event(db_conn, run_id, "continuation_done",
                          f"verdict={promo['new_verdict']} promoted={promo['promoted_to_green_base']}")

    result["status"] = "DONE"
    result["ok"] = result["error"] is None
    return result


# ---------------------------------------------------------------- 하위 유틸

def _resolve_seed(base_run_dir: Path, base_json: dict) -> Path:
    """continuation workspace seed 디렉터리를 고른다: continuation_base snapshot > final_artifact > workspace."""
    for key in ("continuation_base_path", "green_base_path"):
        p = (base_json or {}).get(key)
        if p:
            cand = Path(str(p).replace("\\", "/"))
            if cand.is_dir():
                return cand
    for name in ("final_artifact", "workspace"):
        cand = base_run_dir / name
        if cand.is_dir():
            return cand
    return base_run_dir / "workspace"


def _all_gates_pass(gate_summary: dict) -> bool:
    return all(gate_summary.get(g) for g in CORE_GATE_ORDER)


def _collect_key_files(workspace: Path, plan: dict) -> dict[str, str]:
    prefixes = tuple(s["target"] for s in plan["steps"]) or ("src/", "product/")
    out: dict[str, str] = {}
    for rel in list_workspace_files(workspace):
        if rel.startswith(prefixes) and len(out) < 8:
            out[rel] = read_workspace_file(workspace, rel, 4000)
    return out


def _patch_task_packet_md(plan: dict, failures: list[dict], attempt: int, max_attempts: int) -> str:
    from repo_idea_miner.factory_core_prompts import CONTINUATION_PATCH_MANDATE

    lines = ["# Patch Task Packet (Phase 1.7)", "", f"시도 {attempt}/{max_attempts}", "",
             CONTINUATION_PATCH_MANDATE, "", "## Repair Steps"]
    for s in plan["steps"]:
        lines.append(f"- [{s['failure_type']}] {s['target']}: {s['reason']}")
    lines += ["", "## 허용 수정 경로", json.dumps(plan["allowed_touch_files"], ensure_ascii=False),
              "## 동결 경로", json.dumps(plan["frozen_files"], ensure_ascii=False)]
    return "\n".join(lines) + "\n"


def _is_frozen(path: str, frozen_files: list[str]) -> bool:
    if path in FROZEN_FILES or path in (frozen_files or []):
        return True
    return any(path.startswith(pfx) for pfx in FROZEN_PATH_PREFIXES)


def _is_allowed(path: str, allowed_touch_files: list[str]) -> bool:
    if path in ALLOWED_TOUCH_FILES:
        return True
    prefixes = tuple(a for a in (allowed_touch_files or []) if a.endswith("/")) or ALLOWED_TOUCH_PREFIXES
    if path.startswith(prefixes):
        return True
    return path in (allowed_touch_files or [])


def _apply_continuation_files(
    workspace: Path, entries: list[dict], allowed: list[str], frozen: list[str], secrets: list[str]
) -> tuple[list[str], list[str]]:
    """allowed_touch_files 안에서만 쓰고 frozen 경로는 거부한다 (§11.3)."""
    written, rejected = [], []
    for e in entries:
        path = e["path"].replace("\\", "/").lstrip("./")
        if _is_frozen(path, frozen) or not _is_allowed(path, allowed):
            rejected.append(path)
            continue
        write_workspace_file(workspace, path, e["content"], secrets)
        written.append(path)
    return written, rejected


def _patch_with_retry(executor, packet_md, failure_md, key_files, allowed, frozen,
                      attempt, max_attempts, max_transient, sleep_fn, log_fn):
    """patch desk 호출을 transient 실패 시 backoff 재시도한다 (§12). 반환: (patch|None, transient_count, error)."""
    prompt = build_continuation_patch_prompt(packet_md, failure_md, key_files, allowed, frozen,
                                             attempt, max_attempts)
    transient = 0
    invalid_retried = False
    while True:
        try:
            model, _ = executor.call("continuation_patch", prompt, PatchOutput)
            return model.model_dump(), transient, None
        except DeskError as exc:
            kind = exc.kind
            if kind in ("transient", "timeout") and transient < max_transient:
                transient += 1
                log_fn({"event": "patch_transient_retry", "attempt": attempt,
                        "retry": transient, "kind": kind})
                sleep_fn(min(2.0 * transient, 8.0))
                continue
            if kind == "schema" and not invalid_retried:
                invalid_retried = True
                log_fn({"event": "patch_invalid_retry", "attempt": attempt})
                continue
            return None, transient, exc
        except Exception as exc:  # noqa: BLE001 - 주입 mock의 예외도 transient로 취급
            if transient < max_transient:
                transient += 1
                log_fn({"event": "patch_transient_retry", "attempt": attempt, "retry": transient})
                sleep_fn(min(2.0 * transient, 8.0))
                continue
            return None, transient, exc


def _compute_build_review(executor, gates, core_contract, workspace, write_json) -> dict:
    gate_md = "\n\n".join(gates["results"][g].report_md() for g in CORE_GATE_ORDER)
    try:
        model, _ = executor.call("build_review",
                                 build_build_review_prompt(gate_md, json.dumps(core_contract, ensure_ascii=False),
                                                           list_workspace_files(workspace)),
                                 BuildReview)
        review = model.model_dump()
    except DeskError:
        review = {"status": "NEEDS_PATCH", "patchable": True, "next_goal": ""}
    write_json("build_review.json", review)
    return review


def decide_promotion(gate_summary, product_consumes, hardcode_risk, oracle_risk,
                     failures, next_goal) -> dict:
    """green_base 승격 여부와 실패 시 verdict를 판단한다 (§17)."""
    all_pass = _all_gates_pass(gate_summary)
    green = (all_pass and product_consumes and hardcode_risk != "high" and oracle_risk != "high")
    remaining = sorted({f["type"] for f in failures if f["type"] != "SPEC_REPAIR_REQUIRED"})
    if green:
        return {"promoted_to_green_base": True, "new_verdict": "REVIEW_READY",
                "remaining_failures": [], "next_goal": next_goal}

    requires_spec = any(f["requires_spec_repair"] for f in failures)
    runner_ok = bool(gate_summary.get("runner"))
    contract_ok = bool(gate_summary.get("core_contract"))
    if not runner_ok or not contract_ok:
        verdict = "DROP"
    elif hardcode_risk == "high":
        verdict = "DROP"
    elif requires_spec:
        verdict = "SPEC_REPAIR_REQUIRED"
    elif next_goal:
        verdict = "NEEDS_MORE_GEMMA_LOOP"
    else:
        verdict = "RUNS_BUT_WEAK"
    goal = next_goal or "실패한 gate를 통과시키는 delta patch"
    if verdict == "SPEC_REPAIR_REQUIRED":
        goal = "Resolve runner/golden schema mismatch without editing frozen golden files"
    return {"promoted_to_green_base": False, "new_verdict": verdict,
            "remaining_failures": remaining, "next_goal": goal}


def _continuation_dashboard_summary(base, result, gate_summary, product_consumes, promo, green_saved) -> dict:
    passed = sum(1 for g in CORE_GATE_ORDER if gate_summary.get(g))
    return {
        "is_continuation": True,
        "base_run_id": result["base_run_id"],
        "verdict": promo["new_verdict"],
        "headline": {
            "REVIEW_READY": "검수 가능", "NEEDS_MORE_GEMMA_LOOP": "더 돌려야 함",
            "SPEC_REPAIR_REQUIRED": "스펙 수정 필요", "RUNS_BUT_WEAK": "약함", "DROP": "버림",
        }.get(promo["new_verdict"], promo["new_verdict"]),
        "artifact_class": base["dashboard"].get("artifact_class"),
        "artifact_class_ko": base["dashboard"].get("artifact_class_ko"),
        "core_present": bool(gate_summary.get("core_contract") and gate_summary.get("runner")),
        "gates": gate_summary,
        "gates_passed": passed, "gates_total": len(CORE_GATE_ORDER),
        "determinism": "통과" if gate_summary.get("determinism") else "실패",
        "product_layer_consumes_core": product_consumes,
        "green_base": green_saved,
        "continuation_base": not green_saved,
        "is_live_validation": False,
        "continuation_resolved": result["resolved"],
        "patch_attempts": result["patch_attempts"],
        "transient_retries": result["transient_retries"],
        "remaining_failures": promo["remaining_failures"],
        "next_goal": promo["next_goal"],
        "runner_command": (base["runner_contract"] or {}).get("runner_command"),
        "recommendation": {
            "REVIEW_READY": "실행해보고 판단", "NEEDS_MORE_GEMMA_LOOP": "한 번 더 돌린 뒤 확인",
            "SPEC_REPAIR_REQUIRED": "계약/골든 수정 검토", "RUNS_BUT_WEAK": "보류 또는 버림",
            "DROP": "버림",
        }.get(promo["new_verdict"], "보류 또는 버림"),
    }
