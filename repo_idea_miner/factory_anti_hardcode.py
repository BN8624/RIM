# Phase 2B-1b: 단일 run Anti-Hardcode 코드 patch — runner summary 하드코딩 제거 + state 파생 + gate 재검증 모듈.
from __future__ import annotations

import json
import re
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_run_target

from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.factory_continue import compute_build_review
from repo_idea_miner.factory_core_gates import (
    PRODUCT_READ_LIMIT,
    classify_summary_source,
    product_layer_consumes_core,
    run_core_gates,
    src_code_files,
)
from repo_idea_miner.factory_core_prompts import mock_build_review_pass
from repo_idea_miner.factory_core_schemas import CORE_GATE_ORDER
from repo_idea_miner.factory_db import get_product_run, update_product_run
from repo_idea_miner.factory_desks import DeskExecutor
from repo_idea_miner.factory_frozen import compare_frozen_hashes, compute_frozen_hashes
from repo_idea_miner.factory_pipeline import FactorySettings, load_factory_settings
from repo_idea_miner.factory_product_evidence import load_json, write_json
from repo_idea_miner.factory_workspace import save_green_base
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

# ---------------------------------------------------------------- 상수 (§9~§13)

SUMMARY_HELPER_REL = "src/core/summary.py"

PATCH_PLAN_JSON = "anti_hardcode_patch_plan.json"
PATCH_PLAN_MD = "anti_hardcode_patch_plan.md"
PATCH_REPORT_JSON = "anti_hardcode_patch_report.json"
PATCH_REPORT_MD = "anti_hardcode_patch_report.md"
DIFF_SUMMARY_JSON = "anti_hardcode_diff_summary.json"
HASH_BEFORE = "frozen_hash_before_anti_hardcode_patch.json"
HASH_AFTER = "frozen_hash_after_anti_hardcode_patch.json"
HASH_CHECK = "frozen_hash_anti_hardcode_check.json"
GATE_RERUN_JSON = "gate_rerun_after_anti_hardcode_patch.json"
PROMOTION_JSON = "green_base_promotion_after_anti_hardcode_patch.json"
DASHBOARD_JSON = "phase2b1b_dashboard_summary.json"
RULE_UPDATE_JSON = "summary_repair_rule_update.json"
RULE_UPDATE_MD = "summary_repair_rule_update.md"

# state 파생 summary formatter — golden에 맞춘 리터럴이 아니라 노드 상태에서 라벨을 파생한다 (§4.2).
_SUMMARY_HELPER_SRC = '''from typing import Any, Dict, List


def summarize_execution(final_state: Dict[str, Any], errors: List[Any]) -> str:
    """그래프 실행 상태에서 요약 라벨을 파생한다.

    golden expected_summary에 맞춘 하드코딩이 아니라, final_state의 노드 상태와
    실행 오류에서 계산한다. scenario id/golden literal에 의존하지 않는다.
    """
    nodes = (final_state or {}).get("nodes") or {}
    total = len(nodes)
    completed = sum(1 for n in nodes.values()
                    if isinstance(n, dict) and n.get("status") == "COMPLETED")
    if errors:
        return "Failed"
    if total and completed == total:
        return "Completed"
    if completed:
        return "Partially completed"
    return "Not executed"
'''

_SUMMARY_ASSIGN_RE = re.compile(r"""["']summary["']\s*:|(?<![\w.])summary\s*=""")
# result dict 키 라인만 잡도록 stripped 라인 시작에 앵커한다 (예외 핸들러의 print(...) 안 errors 오탐 방지).
_FINAL_STATE_RE = re.compile(r"""^["']final_state["']\s*:\s*(.+?),?\s*$""")
_ERRORS_RE = re.compile(r"""^["']errors["']\s*:\s*(.+?),?\s*$""")


def _load_goldens(workspace: Path) -> list[dict]:
    return [g for g in (load_json(p) for p in sorted((workspace / "golden").glob("expected_*.json")))
            if g is not None]


# ---------------------------------------------------------------- 대상 식별 / 사전 조건 (§3)

def resolve_patch_target(run_dir=None, run_id=None, db_conn=None) -> tuple[Path | None, str | None, dict]:
    """patch 대상 run_dir를 확정한다. run-id 사용 시 resolved run_dir를 info에 기록한다."""
    return resolve_run_target(run_dir, run_id, db_conn)


def check_patch_preconditions(run_dir: Path, secrets: list[str]) -> tuple[list[str], dict]:
    """§3: Phase 2B-1 apply 이후 anti_hardcode 실패가 남아 있고, 아직 green 미승격인지 확인한다."""
    problems: list[str] = []
    apply_report = load_json(run_dir / "spec_repair_apply_report.json")
    gate_rerun = load_json(run_dir / "gate_rerun_after_spec_repair.json")
    promo = load_json(run_dir / "green_base_promotion_after_spec_repair.json") or {}

    if apply_report is None or not apply_report.get("applied"):
        problems.append("Phase 2B-1 spec repair apply 산출물이 없음 (apply_report.applied != true)")
    if gate_rerun is None:
        problems.append("gate_rerun_after_spec_repair.json 없음")
    remaining = (promo.get("remaining_failures")
                 or (apply_report or {}).get("remaining_failures") or [])
    if "anti_hardcode" not in remaining:
        problems.append(f"remaining_failures에 anti_hardcode 없음: {remaining}")
    if promo.get("promoted_to_green_base"):
        problems.append("이미 green_base로 승격된 run")
    verdict = promo.get("new_verdict") or (apply_report or {}).get("new_verdict")
    if verdict not in ("NEEDS_MORE_GEMMA_LOOP", "SPEC_REPAIR_REQUIRED"):
        problems.append(f"current verdict가 patch 대상이 아님: {verdict}")
    if (run_dir / PATCH_REPORT_JSON).is_file():
        prev = load_json(run_dir / PATCH_REPORT_JSON) or {}
        if prev.get("applied"):
            problems.append("이미 anti_hardcode patch가 수행된 run")

    return problems, {"apply_report": apply_report or {}, "promo": promo,
                      "remaining": remaining, "verdict": verdict}


# ---------------------------------------------------------------- 하드코딩 탐지 (§4)

def detect_hardcoded_summary(workspace: Path) -> dict:
    """runner src에서 하드코딩된 summary 리터럴과 대입식을 찾는다. patch 가능성을 함께 판단한다."""
    goldens = _load_goldens(workspace)
    code = src_code_files(workspace)
    cls = classify_summary_source(code, goldens)
    literals = sorted({(g.get("expected_summary") or "").strip() for g in goldens
                       if len((g.get("expected_summary") or "").strip()) >= 8})

    runner_rel = None
    summary_lineno = None
    final_state_expr = None
    errors_expr = None
    for rel, text in code.items():
        if not rel.startswith("src/"):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if _SUMMARY_ASSIGN_RE.search(line) and any(lit in line for lit in literals):
                runner_rel = rel
                summary_lineno = i
        if runner_rel == rel and summary_lineno is not None:
            # summary 라인과 같은 들여쓰기(같은 dict의 sibling 키)에서만 추출한다
            sindent = len(lines[summary_lineno]) - len(lines[summary_lineno].lstrip())
            for line in lines:
                if (len(line) - len(line.lstrip())) != sindent:
                    continue
                stripped = line.strip()
                mfs = _FINAL_STATE_RE.match(stripped)
                if mfs and final_state_expr is None:
                    final_state_expr = mfs.group(1).strip()
                mer = _ERRORS_RE.match(stripped)
                if mer and errors_expr is None:
                    errors_expr = mer.group(1).strip()

    return {
        "summary_source": cls["summary_source"],
        "summary_hardcode_risk": cls["summary_hardcode_risk"],
        "summary_evidence": cls["summary_evidence"],
        "hardcoded_literals": [lit for lit in literals if lit in "\n".join(code.values())],
        "runner_rel": runner_rel,
        "summary_lineno": summary_lineno,
        "final_state_expr": final_state_expr,
        "errors_expr": errors_expr,
    }


# ---------------------------------------------------------------- Patch plan (§10)

def build_patch_plan(run_dir: Path, detect: dict, target_info: dict, inputs: dict) -> dict:
    blocked: list[str] = []
    if detect["summary_hardcode_risk"] != "high":
        blocked.append(f"summary가 이미 하드코딩이 아님(source={detect['summary_source']}) — patch 불필요")
    if detect["runner_rel"] is None:
        blocked.append("summary 대입에 하드코딩된 리터럴을 가진 runner 라인을 찾지 못함")
    if detect["runner_rel"] is not None:
        if detect["final_state_expr"] is None:
            blocked.append("runner 결과에서 final_state 표현식을 찾지 못함 — 안전한 파생 불가")
        if detect["errors_expr"] is None:
            blocked.append("runner 결과에서 errors 표현식을 찾지 못함 — 안전한 파생 불가")

    planned_files = []
    if not blocked:
        planned_files = [detect["runner_rel"], SUMMARY_HELPER_REL]

    plan = {
        "base_run_id": target_info.get("base_run_id"),
        "challenge_id": target_info.get("challenge_id"),
        "resolved_run_dir": str(run_dir),
        "current_verdict": inputs.get("verdict"),
        "remaining_failure": "anti_hardcode",
        "anti_hardcode_evidence": detect["summary_evidence"],
        "hardcoded_literals": detect["hardcoded_literals"],
        "summary_source_before": detect["summary_source"],
        "planned_files": planned_files,
        "summary_derivation_method": (
            "summarize_execution(final_state, errors): final_state.nodes의 status(COMPLETED) 개수와 "
            "실행 오류에서 Completed/Failed/Partially completed/Not executed를 파생 (§4.2)"),
        "frozen_files_protected": ["golden/", "fixtures/", "core_contract.json",
                                   "state_contract.json", "action_contract.json",
                                   "runner_contract.json", "oracle_risk_report.json"],
        "blocked_reasons": blocked,
        "status": "DRY_RUN_BLOCKED" if blocked else "DRY_RUN_PASS",
    }
    return plan


def _plan_md(plan: dict) -> str:
    lines = ["# Anti-Hardcode Patch Plan (Phase 2B-1b)", "",
             f"- base_run_id: {plan['base_run_id']} / challenge_id: {plan['challenge_id']}",
             f"- resolved_run_dir: {plan['resolved_run_dir']}",
             f"- current verdict: {plan['current_verdict']} / remaining: {plan['remaining_failure']}",
             f"- summary source(before): {plan['summary_source_before']}",
             f"- status: {plan['status']}", "",
             "## 하드코딩된 summary 리터럴"]
    lines += [f"- {lit!r}" for lit in plan["hardcoded_literals"]] or ["- (없음)"]
    lines += ["", "## 수정 예정 파일"] + ([f"- {f}" for f in plan["planned_files"]] or ["- (없음)"])
    lines += ["", "## summary 파생 방법", plan["summary_derivation_method"],
              "", "## 보호되는 frozen 파일"] + [f"- {f}" for f in plan["frozen_files_protected"]]
    if plan["blocked_reasons"]:
        lines += ["", "## Blocked"] + [f"- {b}" for b in plan["blocked_reasons"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Patch 적용 (§4, §11)

def _rewrite_runner(text: str, detect: dict) -> str:
    """runner 소스의 summary 대입을 state 파생 helper 호출로 교체하고 import를 추가한다."""
    lines = text.splitlines()
    i = detect["summary_lineno"]
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    trailing = "," if lines[i].rstrip().endswith(",") else ""
    lines[i] = (f'{indent}"summary": summarize_execution('
                f'{detect["final_state_expr"]}, {detect["errors_expr"]}){trailing}')

    # import 삽입 — 최상단 연속 import 블록 다음 줄
    import_line = "from core.summary import summarize_execution"
    if import_line not in text:
        insert_at = 0
        for j, line in enumerate(lines):
            if line.startswith(("import ", "from ")):
                insert_at = j + 1
            elif line.strip() and insert_at:
                break
        lines.insert(insert_at, import_line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _apply_patch_files(run_dir: Path, workspace: Path, detect: dict) -> tuple[list[str], dict]:
    """runner + summary helper를 workspace와 final_artifact에 쓴다. 원본은 되돌리기용으로 반환."""
    applied: list[str] = []
    originals: dict[str, str | None] = {}
    runner_rel = detect["runner_rel"]
    for base in (workspace, run_dir / "final_artifact"):
        if not base.is_dir():
            continue
        # summary helper
        helper = base / SUMMARY_HELPER_REL
        key = str(helper)
        originals[key] = helper.read_text(encoding="utf-8") if helper.is_file() else None
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_text(_SUMMARY_HELPER_SRC, encoding="utf-8")
        applied.append(str(helper.relative_to(run_dir).as_posix()))
        # runner
        runner = base / runner_rel
        if runner.is_file():
            key = str(runner)
            originals[key] = runner.read_text(encoding="utf-8")
            runner.write_text(_rewrite_runner(originals[key], detect), encoding="utf-8")
            applied.append(str(runner.relative_to(run_dir).as_posix()))
    return applied, originals


def _restore(originals: dict) -> None:
    for path_str, content in originals.items():
        p = Path(path_str)
        if content is None:
            if p.is_file():
                p.unlink()
        else:
            p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------- 오케스트레이터 (§10~§15)

def _verdict_after(remaining: list[str]) -> str:
    spec_side = {"golden_output", "state_invariant"}
    if remaining and set(remaining) <= spec_side:
        return "SPEC_REPAIR_REQUIRED"
    return "NEEDS_MORE_GEMMA_LOOP"


def run_anti_hardcode_patch(
    run_dir: str | Path | None = None,
    run_id: int | None = None,
    apply: bool = False,
    mode: str = "mock",
    db_conn=None,
    settings: Settings | None = None,
    factory_settings: FactorySettings | None = None,
    llm=None,
    scheduler=None,
) -> dict:
    """#47류 단일 run의 anti_hardcode summary 하드코딩을 dry-run/patch한다 (§10~§15)."""
    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    secrets = settings.secret_values()

    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None, "base_run_id": run_id,
        "challenge_id": None, "applied": False, "applied_files": [],
        "promoted_to_green_base": False, "new_verdict": None, "gates": None,
        "validate_ok": None, "frozen_hash_status": None, "summary_source": None,
        "problems": [], "error": None,
    }

    target, err, target_info = resolve_patch_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = target_info.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    run_dir = target
    workspace = run_dir / "workspace"

    problems, inputs = check_patch_preconditions(run_dir, secrets)
    apply_report = inputs["apply_report"]
    target_info["base_run_id"] = target_info.get("base_run_id") or apply_report.get("base_run_id")
    target_info["challenge_id"] = target_info.get("challenge_id") or apply_report.get("challenge_id")
    result["base_run_id"] = target_info["base_run_id"]
    result["challenge_id"] = target_info["challenge_id"]
    if problems:
        result["status"] = "CANNOT_PATCH_ANTI_HARDCODE"
        result["problems"] = problems
        result["error"] = "; ".join(problems)
        return result

    detect = detect_hardcoded_summary(workspace)
    result["summary_source"] = detect["summary_source"]
    hash_pre = compute_frozen_hashes(workspace, run_dir)
    plan = build_patch_plan(run_dir, detect, target_info, inputs)
    write_json(run_dir / PATCH_PLAN_JSON, plan)
    (run_dir / PATCH_PLAN_MD).write_text(_plan_md(plan), encoding="utf-8")

    # dry-run이 frozen 파일을 바꾸면 실패 (§10)
    if compare_frozen_hashes(hash_pre, compute_frozen_hashes(workspace, run_dir))["status"] != "PASS":
        result["status"] = "DRY_RUN_FAILED"
        result["error"] = "dry-run 중 frozen 파일 hash가 변경됨"
        return result

    if not apply:
        result["ok"] = True
        result["status"] = plan["status"]
        result["plan"] = plan
        return result

    if plan["blocked_reasons"]:
        result["status"] = "PATCH_BLOCKED"
        result["problems"] = plan["blocked_reasons"]
        result["error"] = "patch plan이 차단됨"
        return result

    # ---- Patch 적용 (§11)
    write_json(run_dir / HASH_BEFORE, hash_pre)
    try:
        applied_files, originals = _apply_patch_files(run_dir, workspace, detect)
        hash_after = compute_frozen_hashes(workspace, run_dir)
        cmp = compare_frozen_hashes(hash_pre, hash_after)
        out_of_scope = sorted(set(cmp["changed"] + cmp["added"] + cmp["removed"]))
        apply_check = {
            "status": "PASS" if not out_of_scope else "FAIL",
            "changed": cmp["changed"], "added": cmp["added"], "removed": cmp["removed"],
            "out_of_scope": out_of_scope,
            "note": "anti_hardcode patch는 src만 수정한다 — golden/fixtures/contract는 불변이어야 함",
        }
        write_json(run_dir / HASH_AFTER, hash_after)
        write_json(run_dir / HASH_CHECK, apply_check)
        result["frozen_hash_status"] = apply_check["status"]
        if out_of_scope:
            _restore(originals)
            result["status"] = "PATCH_REJECTED_FROZEN_CHANGED"
            result["error"] = f"frozen 파일 변경으로 patch 거부: {out_of_scope}"
            return result
    except Exception as exc:  # noqa: BLE001 — patch 중 예외는 원복
        try:
            _restore(originals)  # type: ignore[has-type]
        except Exception:  # noqa: BLE001
            pass
        result["status"] = "PATCH_ROLLED_BACK"
        result["error"] = f"patch 중 예외: {exc}"
        return result

    result["applied"] = True
    result["applied_files"] = applied_files

    # ---- diff summary (§12)
    write_json(run_dir / DIFF_SUMMARY_JSON, {
        "base_run_id": target_info["base_run_id"], "challenge_id": target_info["challenge_id"],
        "applied_files": applied_files,
        "summary_hardcode_removed": True,
        "summary_derivation_method": plan["summary_derivation_method"],
        "summary_source_before": detect["summary_source"],
        "hardcoded_literals_removed": detect["hardcoded_literals"],
        "frozen_changes": [],
        "golden_fixtures_contract_changed": False,
    })

    # ---- Gate rerun (§13)
    core_contract = load_json(workspace / "core_contract.json") or {}
    runner_contract = load_json(workspace / "runner_contract.json") or {}
    goldens = _load_goldens(workspace)
    gates = run_core_gates(workspace, core_contract, runner_contract, goldens,
                           timeout_seconds=fset.sandbox_timeout_seconds,
                           use_docker=fset.docker_flag(), secrets=secrets)
    for name, data in gates["artifacts"].items():
        write_json(workspace / f"{name}.json", data)
        final_copy = run_dir / "final_artifact" / f"{name}.json"
        if final_copy.parent.is_dir() and final_copy.is_file():
            write_json(final_copy, data)
    final_replay = run_dir / "final_artifact" / "replay"
    if final_replay.is_dir():
        import shutil
        shutil.rmtree(final_replay)
        shutil.copytree(workspace / "replay", final_replay)

    from repo_idea_miner.factory_workspace import list_workspace_files, read_workspace_file

    product_files = {rel: read_workspace_file(workspace, rel, PRODUCT_READ_LIMIT)
                     for rel in list_workspace_files(workspace) if rel.startswith("product/")}
    product_problems = product_layer_consumes_core(product_files, core_contract)
    product_consumes = not product_problems

    if llm is None and mode == "mock":
        llm = MockLLMClient(overrides={"build_review": mock_build_review_pass()},
                            call_logger=LLMCallLogger(None))
    executor = DeskExecutor(mode, settings, scheduler=scheduler, llm=llm,
                            call_logger=LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", secrets))
    build_review = compute_build_review(
        executor, gates, core_contract, workspace,
        lambda name, data: write_json(run_dir / name, data))

    gate_summary = gates["summary"]
    anti = gates["artifacts"]["anti_hardcode_summary"]
    result["gates"] = gate_summary
    all_gates_pass = all(gate_summary.get(g) for g in CORE_GATE_ORDER)
    remaining = [g for g in CORE_GATE_ORDER if not gate_summary.get(g)]
    if not product_consumes:
        remaining.append("product_layer")

    gate_rerun = {
        "gates": gate_summary,
        "gates_passed": sum(1 for g in CORE_GATE_ORDER if gate_summary.get(g)),
        "gates_total": len(CORE_GATE_ORDER),
        "anti_hardcode_status": anti.get("status"),
        "summary_source": anti.get("summary_source"),
        "summary_hardcode_risk": anti.get("summary_hardcode_risk"),
        "product_layer_consumes_core": product_consumes,
        "build_review_status": (build_review or {}).get("status"),
        "after_anti_hardcode_patch": True,
    }
    write_json(run_dir / GATE_RERUN_JSON, gate_rerun)
    result["summary_source"] = anti.get("summary_source")

    # ---- 초기 report (validate가 §16 항목을 볼 수 있도록 먼저 기록)
    hardcode_risk = anti.get("hardcode_risk") or "low"
    summary_risk = anti.get("summary_hardcode_risk") or "low"
    oracle = load_json(run_dir / "oracle_risk_report.json") or {}
    oracle_risk = oracle.get("risk_level") or "low"
    report = {
        "applied": True, "target_count": 1,
        "base_run_id": target_info["base_run_id"], "challenge_id": target_info["challenge_id"],
        "resolved_run_dir": str(run_dir),
        "applied_files": applied_files,
        "summary_source": anti.get("summary_source"),
        "summary_hardcode_risk": summary_risk,
        "hardcode_risk": hardcode_risk,
        "frozen_hash_apply_status": result["frozen_hash_status"],
        "gates": gate_summary, "validate_ok": None,
        "promoted_to_green_base": False, "new_verdict": None,
        "golden_fixtures_contract_changed": False,
    }
    write_json(run_dir / PATCH_REPORT_JSON, report)

    # validate가 "green promotion 결과 존재"(§16)를 확인할 수 있도록 예비 promotion을 먼저 기록
    write_json(run_dir / PROMOTION_JSON, {
        "base_run_id": target_info["base_run_id"], "challenge_id": target_info["challenge_id"],
        "promoted_to_green_base": False, "new_verdict": None,
        "remaining_failures": remaining, "hardcode_risk": hardcode_risk,
        "summary_hardcode_risk": summary_risk, "oracle_risk": oracle_risk,
        "validate_ok": None, "after_anti_hardcode_patch": True,
    })

    # ---- factory-validate (§13)
    from repo_idea_miner.factory_validate import validate_product_run_dir

    validate_ok, validate_problems = validate_product_run_dir(run_dir, secrets)
    result["validate_ok"] = validate_ok

    # ---- Green promotion (§14)
    frozen_ok = result["frozen_hash_status"] == "PASS"
    promoted = (all_gates_pass and product_consumes and validate_ok and frozen_ok
                and hardcode_risk != "high" and summary_risk != "high" and oracle_risk != "high")
    if promoted:
        new_verdict = "REVIEW_READY"
        green_path = str(save_green_base(run_dir, workspace, "green_anti_hardcode_00"))
        write_json(run_dir / "green_base.json", {
            "base_type": "green_base", "green_base_path": green_path,
            "verdict": new_verdict, "source": "anti_hardcode_patch",
            "next_goal": "사용자 검수 후 제품화 판단",
        })
        result["green_base_path"] = green_path
    else:
        new_verdict = _verdict_after(remaining)
    result["promoted_to_green_base"] = promoted
    result["new_verdict"] = new_verdict

    write_json(run_dir / PROMOTION_JSON, {
        "base_run_id": target_info["base_run_id"], "challenge_id": target_info["challenge_id"],
        "promoted_to_green_base": promoted, "new_verdict": new_verdict,
        "remaining_failures": remaining,
        "hardcode_risk": hardcode_risk, "summary_hardcode_risk": summary_risk,
        "oracle_risk": oracle_risk, "validate_ok": validate_ok,
        "next_goal": "사용자 검수 후 제품화 판단" if promoted else "남은 gate 실패 원인 해소",
        "after_anti_hardcode_patch": True,
    })

    # ---- summary repair 규칙 강화 기록 (§7, §12)
    write_json(run_dir / RULE_UPDATE_JSON, {
        "target": "factory_spec_repair.plan_scenario_repair",
        "old_behavior": "expected_summary를 runner 출력값으로 무조건 덮음 (빈 값일 때만 차단)",
        "new_behavior": ("runner summary가 state/events 파생일 때만 expected_summary 보정 허용; "
                         "하드코딩이면 SUMMARY_REPAIR_BLOCKED_HARDCODE_RISK로 차단"),
        "blocked_cases": ["runner code에 expected_summary literal 직접 존재",
                          "summary source 추적 불가", "anti_hardcode summary risk high"],
        "allowed_cases": ["summary가 final_state.nodes/status/execution_order/events에서 파생됨"],
        "enforced_by": "factory_core_gates.classify_summary_source",
    })
    (run_dir / RULE_UPDATE_MD).write_text(
        "# Summary Repair 규칙 강화 (Phase 2B-1b §7)\n\n"
        "- old: expected_summary를 runner 출력으로 무조건 덮음.\n"
        "- new: runner summary가 state/events 파생일 때만 보정, 하드코딩이면 차단.\n"
        "- 판정기: classify_summary_source (summary_source/summary_hardcode_risk).\n",
        encoding="utf-8")

    # ---- 최종 report / dashboard (§12, §15)
    report.update({
        "validate_ok": validate_ok, "validate_problems": validate_problems[:20],
        "promoted_to_green_base": promoted, "new_verdict": new_verdict,
        "remaining_failures": remaining,
    })
    write_json(run_dir / PATCH_REPORT_JSON, report)
    (run_dir / PATCH_REPORT_MD).write_text(_report_md(report), encoding="utf-8")

    status_label = ("Green 승격" if promoted
                    else "적용됨, 재검증 실패" if not (validate_ok and all_gates_pass)
                    else "추가 수정 필요")
    write_json(run_dir / DASHBOARD_JSON, {
        "recommended_path": "Anti-Hardcode Patch",
        "lane": "PATCH_CONTINUATION", "recommended_lane": "PATCH_CONTINUATION",
        "lane_reason": "summary hardcode 제거",
        "lane_status": status_label, "patch_status": status_label,
        "base_run_id": target_info["base_run_id"], "challenge_id": target_info["challenge_id"],
        "verdict": new_verdict, "promoted_to_green_base": promoted,
        "summary_source": anti.get("summary_source"),
        "summary_hardcode_risk": summary_risk,
        "gates": gate_summary, "gates_passed": gate_rerun["gates_passed"],
        "gates_total": gate_rerun["gates_total"],
        "remaining_failures": remaining, "validate_ok": validate_ok,
        "frozen_hash_status": result["frozen_hash_status"],
        "applied_files": applied_files,
    })

    if db_conn is not None and result["base_run_id"] is not None:
        update_product_run(db_conn, result["base_run_id"], verdict=new_verdict,
                           green_base_path=result.get("green_base_path"))

    result["ok"] = True
    result["status"] = "PATCHED"
    return result


def _report_md(report: dict) -> str:
    gates = report.get("gates") or {}
    lines = ["# Anti-Hardcode Patch Report (Phase 2B-1b)", "",
             f"- base_run_id: {report['base_run_id']} / challenge_id: {report['challenge_id']}",
             f"- resolved_run_dir: {report['resolved_run_dir']}",
             f"- applied files: {', '.join(report['applied_files']) or '-'}",
             f"- summary source: {report['summary_source']} / summary risk: {report['summary_hardcode_risk']}",
             f"- frozen hash check: {report['frozen_hash_apply_status']}",
             f"- validate: {'PASS' if report['validate_ok'] else 'FAIL'}",
             f"- promoted_to_green_base: {report['promoted_to_green_base']}",
             f"- new_verdict: {report['new_verdict']}",
             f"- remaining failures: {', '.join(report.get('remaining_failures') or []) or '없음'}",
             "", "## Gate Rerun"]
    lines += [f"- {g}: {'PASS' if ok else 'FAIL'}" for g, ok in gates.items()]
    return "\n".join(lines) + "\n"
