# Phase 2B-1: 단일 run Spec Repair Apply — proposal/review 기반 golden 엄격 보정 + snapshot/rollback + gate 재검증 + 정직한 green 판정 모듈.
from __future__ import annotations

import json
import shutil
from pathlib import Path

from repo_idea_miner.factory_run_layout import resolve_run_target

from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.factory_continue import compute_build_review
from repo_idea_miner.factory_core_gates import (
    PRODUCT_READ_LIMIT,
    compare_golden,
    product_layer_consumes_core,
    run_core_gates,
)
from repo_idea_miner.factory_core_prompts import mock_build_review_pass
from repo_idea_miner.factory_core_schemas import CORE_GATE_ORDER
from repo_idea_miner.factory_db import get_product_run, list_product_runs, update_product_run
from repo_idea_miner.factory_desks import DeskExecutor
from repo_idea_miner.factory_frozen import compare_frozen_hashes, compute_frozen_hashes
from repo_idea_miner.factory_pipeline import FactorySettings, load_factory_settings
from repo_idea_miner.factory_product_evidence import load_json, sha256_file, write_json
from repo_idea_miner.factory_workspace import save_green_base
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

# ---------------------------------------------------------------- 상수 (§6, §11, §13)

SNAPSHOT_SUBDIR = Path("snapshot") / "pre_spec_repair_apply"
INVARIANT_EVALUATOR_FILE = "repo_idea_miner/factory_core_gates.py"

APPLY_PLAN_JSON = "spec_repair_apply_plan.json"
APPLY_PLAN_MD = "spec_repair_apply_plan.md"
APPLY_REPORT_JSON = "spec_repair_apply_report.json"
APPLY_REPORT_MD = "spec_repair_apply_report.md"
DIFF_SUMMARY_JSON = "spec_repair_diff_summary.json"
SNAPSHOT_MANIFEST_JSON = "pre_apply_snapshot_manifest.json"
ROLLBACK_PLAN_JSON = "rollback_plan.json"
ROLLBACK_REPORT_JSON = "rollback_report.json"
HASH_BEFORE_APPLY = "frozen_hash_before_apply.json"
HASH_AFTER_APPLY = "frozen_hash_after_apply.json"
HASH_APPLY_CHECK = "frozen_hash_apply_check.json"
GATE_RERUN_JSON = "gate_rerun_after_spec_repair.json"
PROMOTION_JSON = "green_base_promotion_after_spec_repair.json"
DASHBOARD_JSON = "phase2b1_dashboard_summary.json"

# comparison_mode 완화 검사용 엄격도 (§7.2 — 낮아지면 금지)
_MODE_STRICTNESS = {"exact": 3, "partial": 2, "invariant": 1, "review": 0}


# ---------------------------------------------------------------- 대상 식별 (§3)

def resolve_apply_target(run_dir=None, run_id=None, db_conn=None) -> tuple[Path | None, str | None, dict]:
    """apply 대상 run_dir를 확정한다. run-id 사용 시 resolved run_dir를 info에 기록한다."""
    run_dir, err, info = resolve_run_target(run_dir, run_id, db_conn)
    info["history_run_ids"] = []
    if err is not None:
        return None, err, info
    # base run과 continuation/history run id 구분 기록 (§3)
    if db_conn is not None and info["base_run_id"] is None:
        p2a = load_json(run_dir / "phase2a_dashboard_summary.json") or {}
        info["base_run_id"] = p2a.get("base_run_id")
    if db_conn is not None and info["base_run_id"] is not None:
        for row in list_product_runs(db_conn, limit=500):
            ws = row.get("workspace_dir")
            if not ws:
                continue
            summary = load_json(Path(ws).parent / "continuation_run_summary.json")
            if summary and summary.get("base_run_id") == info["base_run_id"]:
                info["history_run_ids"].append(row["id"])
    return run_dir, None, info


# ---------------------------------------------------------------- 사전 조건 (§4)

def check_apply_preconditions(run_dir: Path) -> tuple[list[str], dict]:
    """§4 필수 입력/조건을 검사한다. 미충족이면 problems에 사유를 담는다."""
    problems: list[str] = []
    proposal = load_json(run_dir / "spec_repair_proposal.json")
    review = load_json(run_dir / "spec_repair_review.json")
    p2a = load_json(run_dir / "phase2a_dashboard_summary.json") or {}
    if proposal is None:
        problems.append("spec_repair_proposal.json 없음 (Phase 2A 산출물 필요)")
    if review is None:
        problems.append("spec_repair_review.json 없음 (Phase 2A 산출물 필요)")
    if review is not None:
        if review.get("result") != "APPROVE_FOR_PHASE2B":
            problems.append(f"review result가 APPROVE_FOR_PHASE2B가 아님: {review.get('result')}")
        if review.get("apply_performed") is True:
            problems.append("review에 apply_performed=true (이미 적용됨)")
    if proposal is not None and proposal.get("apply_allowed_in_phase2a") is not False:
        problems.append("proposal의 apply_allowed_in_phase2a가 false가 아님")
    lane = p2a.get("lane") or p2a.get("recommended_lane")
    if lane != "SPEC_REPAIR":
        problems.append(f"current lane이 SPEC_REPAIR가 아님: {lane}")
    verdict = p2a.get("current_verdict") or p2a.get("verdict")
    if verdict != "SPEC_REPAIR_REQUIRED":
        problems.append(f"current verdict가 SPEC_REPAIR_REQUIRED가 아님: {verdict}")
    if (run_dir / APPLY_REPORT_JSON).is_file():
        prev = load_json(run_dir / APPLY_REPORT_JSON) or {}
        if prev.get("applied"):
            problems.append("이미 spec repair apply가 수행된 run")
    return problems, {"proposal": proposal or {}, "review": review or {}, "p2a": p2a}


# ---------------------------------------------------------------- Golden 보정 계획 (§7, §8)

def _event_kind(event) -> str | None:
    """event 항목의 종류를 뽑는다. 'node_created_event' 문자열과 {'event': 'node_created'}를 동일 종류로 본다.

    dict event는 'event' 키 우선, 없으면 'type' 키 — 둘 다 없으면 None(종류 판별 불가)."""
    if isinstance(event, str):
        return event[:-len("_event")] if event.endswith("_event") else event
    if isinstance(event, dict):
        return event.get("event") if "event" in event else event.get("type")
    return None


def _leaf_paths(obj, prefix=""):
    """dict/list를 걷어 (path, scalar 값) 목록을 만든다."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _leaf_paths(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _leaf_paths(v, f"{prefix}[{i}]")
    else:
        out.append((prefix, obj))
    return out


def _get_by_path(obj, path: str):
    """_leaf_paths가 만든 path 문자열로 값을 찾는다. 반환: (value, found)."""
    node = obj
    for token in path.replace("]", "").replace("[", ".").split("."):
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return None, False
    return node, True


def _key_paths(obj, prefix="") -> set:
    """dict 키 경로 집합 (list 인덱스는 제외) — expected field 삭제 검사용."""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            out |= _key_paths(v, p)
    elif isinstance(obj, list):
        for v in obj:
            out |= _key_paths(v, prefix)
    return out


def plan_scenario_repair(golden: dict, replay: dict | None, contract_fields: set,
                         summary_hardcoded: bool = False) -> dict:
    """golden 1건의 보정안을 만든다. §8 엄격 기준을 어기면 blocked_reasons에 기록하고 new_golden=None.

    summary_hardcoded=True면(runner summary가 state/events 파생이 아니라 하드코딩) expected_summary
    보정을 차단한다 — 하드코딩된 runner 출력을 golden에 그대로 반영하지 못하게 한다 (Phase 2B-1b §7)."""
    sid = golden.get("scenario_id") or "(없음)"
    mode = golden.get("comparison_mode") or "exact"
    entry = {"scenario_id": sid, "comparison_mode": {"old": mode, "new": mode},
             "changes": [], "blocked_reasons": [], "new_golden": None}

    if mode == "review":
        return entry  # 자동 gate 대상이 아님 — 변경 없음
    if replay is None or not isinstance(replay.get("final_state"), dict):
        entry["blocked_reasons"].append("replay 출력 없음/불완전 — golden 보정 근거 부족")
        return entry
    if compare_golden(golden, replay)[0] == "PASS":
        return entry  # 이미 통과 — 변경 없음

    new_golden = dict(golden)
    old_fs = golden.get("expected_final_state") or {}
    blocked = entry["blocked_reasons"]

    if mode == "exact":
        new_fs = json.loads(json.dumps(replay["final_state"]))
        # §8.1: 추가되는 top-level 필드는 contract state field여야 한다 (runner noise 금지)
        for added in sorted(set(new_fs) - set(old_fs)):
            if added not in contract_fields:
                blocked.append(
                    f"'{added}'는 contract state field가 아님 — runner output noise 가능, golden 추가 금지 (§8.1)")
            else:
                entry["changes"].append(f"expected_final_state.{added} 추가 (contract 필수 state field)")
        # §8 금지: 기존 expected field 삭제
        deleted = sorted(_key_paths(old_fs) - _key_paths(new_fs))
        if deleted:
            blocked.append(f"기존 expected field 삭제 발생: {deleted} (§8 금지)")
        # §8 금지: 기존 기대값 훼손 (core 결함을 golden으로 덮기)
        for path, value in _leaf_paths(old_fs):
            new_value, found = _get_by_path(new_fs, path)
            if not found or new_value != value:
                shown = repr(new_value) if found else "(없음)"
                blocked.append(
                    f"기존 기대값 훼손: expected_final_state.{path} {value!r} → "
                    f"{shown} — core 결함을 golden 수정으로 덮는 변경 금지 (§8)")
        if not blocked:
            new_golden["expected_final_state"] = new_fs
            if _key_paths(new_fs) - _key_paths(old_fs):
                entry["changes"].append("expected_final_state를 runner/contract 정합 schema로 보강")
    # partial/invariant: expected_final_state는 유지 (이미 통과 범위) — events/summary schema만 정합

    old_events = golden.get("expected_events") or []
    new_events = replay.get("events") or []
    if old_events and old_events != new_events:
        if len(old_events) != len(new_events):
            blocked.append(
                f"event 수 변경 (기대 {len(old_events)} → {len(new_events)}) — scenario 결과 축소/확대 금지 (§8)")
        else:
            for i, (o, n) in enumerate(zip(old_events, new_events)):
                if _event_kind(o) != _event_kind(n):
                    blocked.append(f"events[{i}] 종류 불일치: {_event_kind(o)} → {_event_kind(n)} (§8)")
                elif isinstance(o, dict):
                    # §8: event payload 기대값도 final_state와 동일하게 보호한다 —
                    # 종류가 같아도 기존 값이 바뀌면 core 결함을 golden으로 덮는 변경이므로 차단.
                    if not isinstance(n, dict):
                        blocked.append(
                            f"events[{i}]가 dict에서 {type(n).__name__}로 축소 — 기대 구조 약화 금지 (§8)")
                        continue
                    for path, value in _leaf_paths(o):
                        new_value, found = _get_by_path(n, path)
                        if not found or new_value != value:
                            shown = repr(new_value) if found else "(없음)"
                            blocked.append(
                                f"기존 기대값 훼손: expected_events[{i}].{path} {value!r} → "
                                f"{shown} — core 결함을 golden 수정으로 덮는 변경 금지 (§8)")
            if not blocked:
                new_golden["expected_events"] = json.loads(json.dumps(new_events))
                entry["changes"].append("expected_events를 runner event 객체 schema로 정합 (수/종류/순서 보존)")

    old_summary = golden.get("expected_summary")
    new_summary = replay.get("summary")
    if old_summary and old_summary != new_summary:
        if not new_summary:
            blocked.append("runner summary가 비어 있음 — expected_summary 비우기 금지 (§8)")
        elif summary_hardcoded:
            blocked.append(
                "runner summary가 state/events 파생이 아니라 하드코딩됨 — expected_summary 보정 차단 "
                "(SUMMARY_REPAIR_BLOCKED_HARDCODE_RISK, Phase 2B-1b §7.2)")
        else:
            new_golden["expected_summary"] = new_summary
            entry["changes"].append(f"expected_summary 정합: {old_summary!r} → {new_summary!r}")

    if blocked or not entry["changes"]:
        entry["new_golden"] = None
        return entry
    # 보정 결과가 실제로 runner 출력과 정합해야 한다 (sanity)
    result, diffs = compare_golden(new_golden, replay)
    if result == "FAIL":
        entry["blocked_reasons"].append(f"보정 golden이 여전히 runner 출력과 불일치: {diffs[:3]}")
        entry["new_golden"] = None
        return entry
    entry["new_golden"] = new_golden
    return entry


def build_apply_plan(run_dir: Path, inputs: dict, target_info: dict) -> dict:
    """§11 apply plan을 만든다. 실행/파일 수정 없이 기존 replay/ 산출물만 근거로 쓴다."""
    workspace = run_dir / "workspace"
    contract = load_json(workspace / "core_contract.json") or {}
    runner_contract = load_json(workspace / "runner_contract.json") or {}
    contract_fields: set = set()
    for entity in contract.get("state_entities") or []:
        contract_fields |= set(entity.get("fields") or [])

    golden_files = sorted((workspace / "golden").glob("expected_*.json"))
    goldens_all = [load_json(g) or {} for g in golden_files]
    # runner summary가 하드코딩이면 expected_summary 보정을 차단한다 (Phase 2B-1b §7)
    from repo_idea_miner.factory_core_gates import src_code_files, classify_summary_source
    summary_class = classify_summary_source(src_code_files(workspace), goldens_all)
    summary_hardcoded = summary_class["summary_hardcode_risk"] == "high"

    scenarios: list[dict] = []
    planned_files: list[str] = []
    blocked: list[str] = []
    for gpath in golden_files:
        golden = load_json(gpath) or {}
        sid = golden.get("scenario_id") or gpath.stem.replace("expected_", "scenario_")
        replay = load_json(workspace / "replay" / f"replay_{sid}.json")
        entry = plan_scenario_repair(golden, replay, contract_fields, summary_hardcoded)
        entry["golden_file"] = f"golden/{gpath.name}"
        scenarios.append(entry)
        if entry["blocked_reasons"]:
            blocked += [f"{sid}: {b}" for b in entry["blocked_reasons"]]
        elif entry["new_golden"] is not None:
            planned_files.append(f"golden/{gpath.name}")

    proposal = inputs["proposal"]
    review = inputs["review"]
    edges_note = (
        "edges는 core_contract GraphState의 필수 state field라 golden 추가 허용 (§8.1)"
        if "edges" in contract_fields else
        "edges가 contract state field가 아니므로 golden에 추가하지 않음 (§8.1)"
    )
    plan = {
        "base_run_id": target_info.get("base_run_id") or (inputs["p2a"].get("base_run_id")),
        "challenge_id": target_info.get("challenge_id") or inputs["p2a"].get("challenge_id"),
        "resolved_run_dir": str(run_dir),
        "history_run_ids": target_info.get("history_run_ids") or [],
        "proposal_path": str(run_dir / "spec_repair_proposal.json"),
        "review_path": str(run_dir / "spec_repair_review.json"),
        "review_result": review.get("result"),
        "repair_type": proposal.get("repair_type"),
        "planned_files": planned_files,
        "planned_changes": scenarios,
        "scenario_count": {"before": len(golden_files), "after": len(golden_files)},
        "comparison_mode_changes": [],  # plan 단계에서 mode 변경은 생성되지 않음 (§7.2)
        "risk_level": proposal.get("risk_level"),
        "summary_source": summary_class["summary_source"],
        "summary_hardcode_risk": summary_class["summary_hardcode_risk"],
        "edges_decision": edges_note,
        "invariant_dsl_note": (
            "invariant 평가기는 factory_core_gates의 length/entity 인스턴스 최소 해석으로 보강됨 "
            "(§9 — arbitrary eval 없음, missing path 자동 PASS 없음)"),
        "why_safe_to_apply": [
            "runner 출력이 runner_contract required_output_fields를 충족함",
            "기존 golden 기대값(값 수준)을 전부 보존함 — 훼손 시 blocked",
            "comparison_mode를 변경하지 않음",
            "contract state field만 expected_final_state에 추가함",
            "scenario/golden 수를 변경하지 않음",
        ],
        "blocked_reasons": blocked,
        "runner_command": runner_contract.get("runner_command"),
        "status": "DRY_RUN_BLOCKED" if blocked else "DRY_RUN_PASS",
    }
    return plan


def _plan_md(plan: dict) -> str:
    lines = ["# Spec Repair Apply Plan (Phase 2B-1)", "",
             f"- base_run_id: {plan['base_run_id']} / challenge_id: {plan['challenge_id']}",
             f"- resolved_run_dir: {plan['resolved_run_dir']}",
             f"- review result: {plan['review_result']} / risk: {plan['risk_level']}",
             f"- status: {plan['status']}", "",
             "## 수정 예정 파일"]
    lines += [f"- {f}" for f in plan["planned_files"]] or ["- (없음)"]
    lines += ["", "## Scenario별 변경"]
    for s in plan["planned_changes"]:
        lines.append(f"### {s['scenario_id']} ({s['comparison_mode']['old']})")
        lines += [f"- {c}" for c in s["changes"]] or ["- 변경 없음"]
        lines += [f"- [BLOCKED] {b}" for b in s["blocked_reasons"]]
    lines += ["", "## edges 판단", plan["edges_decision"],
              "", "## 안전 근거"] + [f"- {w}" for w in plan["why_safe_to_apply"]]
    if plan["blocked_reasons"]:
        lines += ["", "## Blocked"] + [f"- {b}" for b in plan["blocked_reasons"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- Snapshot / Rollback (§6)

def _snapshot_targets(run_dir: Path) -> list[Path]:
    workspace = run_dir / "workspace"
    targets: list[Path] = []
    for sub in ("golden", "fixtures"):
        d = workspace / sub
        if d.is_dir():
            targets += [p for p in sorted(d.rglob("*")) if p.is_file()]
    for name in ("core_contract.json", "state_contract.json", "action_contract.json",
                 "runner_contract.json", "oracle_risk_report.json"):
        for base in (workspace, run_dir):
            p = base / name
            if p.is_file():
                targets.append(p)
    final_golden = run_dir / "final_artifact" / "golden"
    if final_golden.is_dir():
        targets += [p for p in sorted(final_golden.rglob("*")) if p.is_file()]
    return targets


def create_pre_apply_snapshot(run_dir: Path) -> tuple[dict, dict]:
    """§6: apply 전 snapshot manifest + rollback plan을 만든다."""
    snap_root = run_dir / SNAPSHOT_SUBDIR
    if snap_root.exists():
        shutil.rmtree(snap_root)
    entries = []
    for src in _snapshot_targets(run_dir):
        rel = src.relative_to(run_dir).as_posix()
        dst = snap_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        entries.append({"path": rel, "sha256": sha256_file(src),
                        "snapshot": str(dst.relative_to(run_dir).as_posix())})
    evaluator = Path(__file__).resolve().parent.parent / INVARIANT_EVALUATOR_FILE
    manifest = {
        "snapshot_dir": str(SNAPSHOT_SUBDIR.as_posix()),
        "files": entries,
        "invariant_evaluator": {
            "path": INVARIANT_EVALUATOR_FILE,
            "sha256": sha256_file(evaluator) if evaluator.is_file() else None,
            "note": "git 추적 코드 파일 — rollback은 git으로 수행",
        },
    }
    rollback = {
        "restore_from": str(SNAPSHOT_SUBDIR.as_posix()),
        "procedure": "snapshot 파일을 원래 경로로 복사해 되돌린다 (execute_rollback).",
        "files": [{"restore": e["snapshot"], "to": e["path"]} for e in entries],
        "auto_rollback_on": ["apply 중 예외", "proposal/review 범위 밖 파일 변경(out_of_scope)"],
        "note": "gate fail 자체는 rollback 대상이 아님 — 정직한 verdict로 남긴다 (§6.3)",
    }
    write_json(run_dir / SNAPSHOT_MANIFEST_JSON, manifest)
    write_json(run_dir / ROLLBACK_PLAN_JSON, rollback)
    return manifest, rollback


def execute_rollback(run_dir: Path, reason: str) -> dict:
    """snapshot에서 원본 파일을 복원하고 rollback_report.json을 남긴다 (§6.3)."""
    manifest = load_json(run_dir / SNAPSHOT_MANIFEST_JSON) or {"files": []}
    restored = []
    errors = []
    for e in manifest.get("files") or []:
        src = run_dir / e["snapshot"]
        dst = run_dir / e["path"]
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(e["path"])
        except OSError as exc:
            errors.append(f"{e['path']}: {exc}")
    report = {"executed": True, "reason": reason, "restored": restored, "errors": errors}
    write_json(run_dir / ROLLBACK_REPORT_JSON, report)
    return report


# ---------------------------------------------------------------- Apply 본체 (§12)

def _apply_status_label(applied: bool, promoted: bool, validate_ok: bool, gates_ok: bool) -> str:
    """§16 목록 카드 상태 문구."""
    if not applied:
        return "적용 보류"
    if promoted:
        return "Green 승격"
    if validate_ok and gates_ok:
        return "적용됨"
    return "적용됨, 재검증 실패"


def run_spec_repair_apply(
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
    """#47류 단일 run의 spec repair를 dry-run/apply한다 (§10~§15). 반환: 요약 dict."""
    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    secrets = settings.secret_values()

    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None, "base_run_id": run_id,
        "challenge_id": None, "history_run_ids": [], "applied": False,
        "applied_files": [], "promoted_to_green_base": False, "new_verdict": None,
        "gates": None, "validate_ok": None, "frozen_hash_apply_status": None,
        "rollback_executed": False, "problems": [], "error": None,
    }

    target, err, target_info = resolve_apply_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = target_info.get("resolved_run_dir")
    result["base_run_id"] = target_info.get("base_run_id")
    result["history_run_ids"] = target_info.get("history_run_ids") or []
    if err:
        result["error"] = err
        return result
    run_dir = target

    problems, inputs = check_apply_preconditions(run_dir)
    result["challenge_id"] = target_info.get("challenge_id") or inputs["p2a"].get("challenge_id")
    result["base_run_id"] = target_info.get("base_run_id") or inputs["p2a"].get("base_run_id")
    target_info["base_run_id"] = result["base_run_id"]
    target_info["challenge_id"] = result["challenge_id"]
    if inputs["proposal"] == {} or inputs["review"] == {}:
        result["status"] = "CANNOT_APPLY_SPEC_REPAIR"
        result["problems"] = problems
        result["error"] = "; ".join(problems)
        return result
    if problems:
        result["status"] = "CANNOT_APPLY_SPEC_REPAIR"
        result["problems"] = problems
        result["error"] = "; ".join(problems)
        return result

    workspace = run_dir / "workspace"
    hash_pre = compute_frozen_hashes(workspace, run_dir)
    plan = build_apply_plan(run_dir, inputs, target_info)
    write_json(run_dir / APPLY_PLAN_JSON, plan)
    (run_dir / APPLY_PLAN_MD).write_text(_plan_md(plan), encoding="utf-8")

    # §11: dry-run 중 frozen hash가 바뀌면 실패
    hash_post_plan = compute_frozen_hashes(workspace, run_dir)
    if compare_frozen_hashes(hash_pre, hash_post_plan)["status"] != "PASS":
        result["status"] = "DRY_RUN_FAILED"
        result["error"] = "dry-run 중 frozen 파일 hash가 변경됨"
        return result

    if not apply:
        result["ok"] = True
        result["status"] = plan["status"]  # DRY_RUN_PASS | DRY_RUN_BLOCKED
        result["plan"] = plan
        return result

    if plan["blocked_reasons"]:
        result["status"] = "APPLY_BLOCKED"
        result["problems"] = plan["blocked_reasons"]
        result["error"] = "apply plan이 §8 엄격 기준에서 차단됨"
        return result
    if not plan["planned_files"]:
        result["status"] = "NOTHING_TO_APPLY"
        result["error"] = "보정할 golden이 없음"
        return result

    # ---- Apply (§12 적용 전 절차)
    create_pre_apply_snapshot(run_dir)
    write_json(run_dir / HASH_BEFORE_APPLY, hash_pre)

    applied_files: list[str] = []
    try:
        for entry in plan["planned_changes"]:
            if entry["new_golden"] is None:
                continue
            rel = entry["golden_file"]
            write_json(workspace / rel, entry["new_golden"])
            applied_files.append(rel)
            final_target = run_dir / "final_artifact" / rel
            if final_target.parent.is_dir():
                write_json(final_target, entry["new_golden"])
                applied_files.append(f"final_artifact/{rel}")

        hash_after = compute_frozen_hashes(workspace, run_dir)
        write_json(run_dir / HASH_AFTER_APPLY, hash_after)
        cmp = compare_frozen_hashes(hash_pre, hash_after)
        out_of_scope = sorted(
            k for k in (cmp["changed"] + cmp["added"] + cmp["removed"])
            if k not in set(plan["planned_files"]))
        apply_check = {
            "status": "PASS" if not out_of_scope else "FAIL",
            "changed": cmp["changed"], "added": cmp["added"], "removed": cmp["removed"],
            "planned": plan["planned_files"], "out_of_scope": out_of_scope,
        }
        write_json(run_dir / HASH_APPLY_CHECK, apply_check)
        result["frozen_hash_apply_status"] = apply_check["status"]
        if out_of_scope:
            execute_rollback(run_dir, f"proposal/review 범위 밖 파일 변경: {out_of_scope}")
            result["rollback_executed"] = True
            result["status"] = "APPLY_ROLLED_BACK"
            result["error"] = f"범위 밖 변경으로 rollback: {out_of_scope}"
            return result
    except Exception as exc:  # noqa: BLE001 — §6.3 apply 중 예외는 자동 rollback
        execute_rollback(run_dir, f"apply 중 예외: {exc}")
        result["rollback_executed"] = True
        result["status"] = "APPLY_ROLLED_BACK"
        result["error"] = f"apply 중 예외: {exc}"
        return result

    result["applied"] = True
    result["applied_files"] = applied_files

    # ---- diff summary (§13)
    diff_summary = {
        "base_run_id": plan["base_run_id"], "challenge_id": plan["challenge_id"],
        "applied_files": applied_files,
        "scenario_count": plan["scenario_count"],
        "comparison_mode_changes": [],
        "deleted_expected_fields": [],
        "invariant_downgrades": [],
        "out_of_scope_changes": [],
        "edges_decision": plan["edges_decision"],
        "changes": [
            {"scenario_id": s["scenario_id"], "comparison_mode": s["comparison_mode"],
             "changes": s["changes"]}
            for s in plan["planned_changes"] if s["new_golden"] is not None
        ],
    }
    write_json(run_dir / DIFF_SUMMARY_JSON, diff_summary)

    # ---- Gate rerun (§14)
    core_contract = load_json(workspace / "core_contract.json") or {}
    runner_contract = load_json(workspace / "runner_contract.json") or {}
    goldens = [g for g in (load_json(p) for p in sorted((workspace / "golden").glob("expected_*.json")))
               if g is not None]
    gates = run_core_gates(workspace, core_contract, runner_contract, goldens,
                           timeout_seconds=fset.sandbox_timeout_seconds,
                           use_docker=fset.docker_flag(), secrets=secrets)
    for name, data in gates["artifacts"].items():
        write_json(workspace / f"{name}.json", data)
        final_copy = run_dir / "final_artifact" / f"{name}.json"
        if final_copy.parent.is_dir() and final_copy.is_file():
            write_json(final_copy, data)
    # replay 산출물도 final_artifact에 정합하게 반영
    final_replay = run_dir / "final_artifact" / "replay"
    if final_replay.is_dir():
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
    result["gates"] = gate_summary
    gate_rerun = {
        "gates": gate_summary,
        "gates_passed": sum(1 for g in CORE_GATE_ORDER if gate_summary.get(g)),
        "gates_total": len(CORE_GATE_ORDER),
        "failed_scenarios": gates["artifacts"]["golden_diff_summary"].get("failed_scenarios") or [],
        "product_layer_consumes_core": product_consumes,
        "product_layer_problems": product_problems,
        "build_review_status": (build_review or {}).get("status"),
        "after_spec_repair_apply": True,
    }
    write_json(run_dir / GATE_RERUN_JSON, gate_rerun)

    # ---- 초기 apply report (validate가 §17 항목을 검사할 수 있도록 먼저 기록)
    report = {
        "applied": True, "target_count": 1,
        "base_run_id": plan["base_run_id"], "challenge_id": plan["challenge_id"],
        "resolved_run_dir": str(run_dir), "history_run_ids": plan["history_run_ids"],
        "review_result": plan["review_result"], "repair_type": plan["repair_type"],
        "applied_files": applied_files,
        "comparison_mode_changes": [], "scenario_count": plan["scenario_count"],
        "deleted_expected_fields": [], "invariant_downgrades": [],
        "frozen_hash_apply_status": result["frozen_hash_apply_status"],
        "rollback_executed": False,
        "gates": gate_summary, "validate_ok": None,
        "promoted_to_green_base": False, "new_verdict": None,
    }
    write_json(run_dir / APPLY_REPORT_JSON, report)

    # ---- factory-validate (§14)
    from repo_idea_miner.factory_validate import validate_product_run_dir

    validate_ok, validate_problems = validate_product_run_dir(run_dir, secrets)
    result["validate_ok"] = validate_ok

    # ---- Green promotion (§15)
    anti = gates["artifacts"]["anti_hardcode_summary"]
    oracle = load_json(run_dir / "oracle_risk_report.json") or {}
    hardcode_risk = anti.get("hardcode_risk") or "low"
    oracle_risk = oracle.get("risk_level") or "low"
    all_gates_pass = all(gate_summary.get(g) for g in CORE_GATE_ORDER)
    promoted = (all_gates_pass and product_consumes and validate_ok
                and hardcode_risk != "high" and oracle_risk != "high")
    remaining = [g for g in CORE_GATE_ORDER if not gate_summary.get(g)]
    if not product_consumes:
        remaining.append("product_layer")
    if promoted:
        new_verdict = "REVIEW_READY"
        green_path = str(save_green_base(run_dir, workspace, "green_spec_repair_00"))
        write_json(run_dir / "green_base.json", {
            "base_type": "green_base", "green_base_path": green_path,
            "verdict": new_verdict, "source": "spec_repair_apply",
            "next_goal": "사용자 검수 후 제품화 판단",
        })
        result["green_base_path"] = green_path
    else:
        # §15.3: 정직한 verdict — spec측 gate 실패면 SPEC_REPAIR_REQUIRED, 그 외 NEEDS_MORE_GEMMA_LOOP
        spec_side = {"golden_output", "state_invariant"}
        if remaining and set(remaining) <= spec_side:
            new_verdict = "SPEC_REPAIR_REQUIRED"
        else:
            new_verdict = "NEEDS_MORE_GEMMA_LOOP"
    result["promoted_to_green_base"] = promoted
    result["new_verdict"] = new_verdict

    promotion = {
        "base_run_id": plan["base_run_id"], "challenge_id": plan["challenge_id"],
        "promoted_to_green_base": promoted, "new_verdict": new_verdict,
        "remaining_failures": remaining,
        "hardcode_risk": hardcode_risk, "oracle_risk": oracle_risk,
        "validate_ok": validate_ok,
        "next_goal": "사용자 검수 후 제품화 판단" if promoted else "남은 gate 실패 원인 해소",
        "after_spec_repair_apply": True,
    }
    write_json(run_dir / PROMOTION_JSON, promotion)

    # ---- 최종 report / dashboard (§13, §16)
    report.update({
        "validate_ok": validate_ok, "validate_problems": validate_problems[:20],
        "promoted_to_green_base": promoted, "new_verdict": new_verdict,
        "remaining_failures": remaining,
    })
    write_json(run_dir / APPLY_REPORT_JSON, report)
    (run_dir / APPLY_REPORT_MD).write_text(_report_md(report, plan), encoding="utf-8")

    status_label = _apply_status_label(True, promoted, validate_ok, all_gates_pass)
    write_json(run_dir / DASHBOARD_JSON, {
        "lane": "SPEC_REPAIR", "recommended_lane": "SPEC_REPAIR",
        "lane_reason": "golden schema + invariant DSL 수리",
        "lane_status": status_label,
        "apply_status": status_label,
        "base_run_id": plan["base_run_id"], "challenge_id": plan["challenge_id"],
        "verdict": new_verdict, "promoted_to_green_base": promoted,
        "gates": gate_summary, "gates_passed": gate_rerun["gates_passed"],
        "gates_total": gate_rerun["gates_total"],
        "remaining_failures": remaining,
        "validate_ok": validate_ok,
        "frozen_hash_status": result["frozen_hash_apply_status"],
        "applied_files": applied_files,
        "risk_level": max(hardcode_risk, oracle_risk,
                          key=lambda x: {"low": 0, "medium": 1, "high": 2}.get(x, 1)),
    })

    if db_conn is not None and result["base_run_id"] is not None:
        update_product_run(db_conn, result["base_run_id"], verdict=new_verdict,
                           green_base_path=result.get("green_base_path"))

    result["ok"] = True
    result["status"] = "APPLIED"
    return result


def _report_md(report: dict, plan: dict) -> str:
    gates = report.get("gates") or {}
    lines = ["# Spec Repair Apply Report (Phase 2B-1)", "",
             f"- base_run_id: {report['base_run_id']} / challenge_id: {report['challenge_id']}",
             f"- resolved_run_dir: {report['resolved_run_dir']}",
             f"- review result: {report['review_result']}",
             f"- applied files: {', '.join(report['applied_files']) or '-'}",
             f"- frozen hash apply check: {report['frozen_hash_apply_status']}",
             f"- validate: {'PASS' if report['validate_ok'] else 'FAIL'}",
             f"- promoted_to_green_base: {report['promoted_to_green_base']}",
             f"- new_verdict: {report['new_verdict']}",
             f"- remaining failures: {', '.join(report.get('remaining_failures') or []) or '없음'}",
             "", "## Gate Rerun"]
    lines += [f"- {g}: {'PASS' if ok else 'FAIL'}" for g, ok in gates.items()]
    lines += ["", "## edges 판단", plan["edges_decision"]]
    return "\n".join(lines) + "\n"
