# 도메인 중립 RUNNER_BACKED_DRAFT_EXECUTION lane executor — 검증된 draft를 canonical execution contract로 변환해 실제 runner로 실행하고 side effect·evidence·validation을 수집한다 (이슈 #6).
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path

from repo_idea_miner.factory_core_gates import run_scenario_once
from repo_idea_miner.factory_interaction_ui import (
    KIND_GRAPH_EDITOR,
    first_fixture,
    has_error_signal,
    detect_interaction_kind,
)
from repo_idea_miner.factory_run_layout import resolve_artifact_root

# ---------------------------------------------------------------- 산출물 위치 (evidence ownership §8)

EXECUTION_SUBDIR = "review/draft_execution"
DRAFT_REL = "product/interaction/contract.json"  # generic draft artifact = INTERACTION_UI 산출물
CONTRACT_JSON = "execution_contract.json"
RESULT_JSON = "execution_result.json"
MANIFEST_JSON = "side_effect_manifest.json"
EVIDENCE_JSON = "execution_evidence.json"
REPORT_JSON = "draft_execution_report.json"
DASHBOARD_JSON = "draft_execution_dashboard_summary.json"

EXECUTION_KIND_ACTION_SCENARIO = "action_scenario"

# pre-execution 상태 (§5) — 어떤 것도 성공으로 취급하지 않는다 (READY_TO_EXECUTE 포함)
PRE_EXECUTION_STATUSES = (
    "READY_TO_EXECUTE",
    "INVALID_DRAFT",
    "MISSING_RUNNER",
    "UNSUPPORTED_EXECUTION_KIND",
    "MISSING_INPUT",
    "UNSAFE_SIDE_EFFECT",
    "MISSING_VALIDATION_CONTRACT",
)

# 실행 결과 상태 (§7) — EXECUTED는 runner 종료를 뜻할 뿐 제품 성공이 아니다
EXECUTION_STATUSES = (
    "EXECUTED",
    "VALIDATION_FAILED",
    "RUNNER_FAILED",
    "TIMED_OUT",
    "INVALID_INPUT",
    "UNSUPPORTED",
    "UNSAFE",
    "EVIDENCE_INCOMPLETE",
)

# side effect policy (§6) — temp copy 내부에서도 이 경로들은 실행이 바꾸면 안 된다
PROTECTED_REL_PREFIXES = ("golden/", "replay/", "src/")
PROTECTED_REL_FILES = (
    "core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json",
)
# executor가 temp copy에 직접 쓰는 시나리오 파일 위치 — 선언된 created 경로 (§6.3)
_EXEC_SCENARIO_DIR = "fixtures/_draft_execution"

_STDIO_SUMMARY_LIMIT = 400  # 전체 stdout/stderr 복제 금지 (§6.3) — 요약만


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _hash_tree(base: Path) -> dict[str, str]:
    if not base.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(base.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[p.relative_to(base).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _is_protected_rel(rel: str) -> bool:
    return rel in PROTECTED_REL_FILES or any(rel.startswith(p) for p in PROTECTED_REL_PREFIXES)


# ---------------------------------------------------------------- canonical execution contract (§4)

def _fixture_actions(artifact_root: Path, allowed: set[str]) -> tuple[list[dict], list[str]]:
    """fixture에서 draft 실행에 쓸 action 인스턴스를 얻는다. allowed 밖 type은 정직하게 문제로 남긴다."""
    problems: list[str] = []
    fixture = first_fixture(artifact_root) or {}
    actions = [a for a in (fixture.get("actions") or [])
               if isinstance(a, dict) and a.get("type")]
    outside = sorted({a["type"] for a in actions} - allowed)
    if outside:
        problems.append(f"fixture action type이 draft allowed_actions 밖: {outside}")
        actions = [a for a in actions if a["type"] in allowed]
    return actions, problems


def build_execution_contract(artifact_root: Path, timeout: float) -> dict:
    """기존 draft(interaction contract)·runner contract·fixture에서 canonical execution
    contract를 만든다 (§4.1). 새 schema를 지어내지 않고 기존 구조의 의미를 재사용한다.

    반환: {"pre_execution_status", "problems", "contract"(READY일 때만)}
    """
    problems: list[str] = []

    kind = detect_interaction_kind(artifact_root)
    if kind == KIND_GRAPH_EDITOR:
        return {"pre_execution_status": "UNSUPPORTED_EXECUTION_KIND",
                "problems": ["graph 도메인은 legacy 2C-3 adapter가 담당 — lane 라우터에서 분기"],
                "contract": None}

    draft = _load_json(artifact_root / DRAFT_REL)
    if draft is None or draft.get("supported") is not True \
            or not draft.get("available_actions") \
            or not isinstance(draft.get("initial_state"), dict):
        return {"pre_execution_status": "INVALID_DRAFT",
                "problems": [f"draft({DRAFT_REL})가 없거나 schema-valid하지 않음"],
                "contract": None}

    runner_contract = _load_json(artifact_root / "runner_contract.json") or {}
    runner_command = str(runner_contract.get("runner_command") or "")
    if not runner_command:
        return {"pre_execution_status": "MISSING_RUNNER",
                "problems": ["runner_contract.runner_command 없음"], "contract": None}
    # 안전 경계 (§6.2): 저장소/워크스페이스 밖 접근·네트워크 흔적이 있는 명령은 실행하지 않는다
    lowered = runner_command.lower()
    if ".." in runner_command or lowered.startswith(("/", "\\")) \
            or ":" in runner_command.split(" ")[0] \
            or any(tok in lowered for tok in ("http://", "https://", "curl ", "wget ")):
        return {"pre_execution_status": "UNSAFE_SIDE_EFFECT",
                "problems": [f"runner_command가 안전 경계를 벗어남: {runner_command}"],
                "contract": None}

    allowed = {a.get("name") for a in draft.get("available_actions") or [] if a.get("name")}
    actions, action_problems = _fixture_actions(artifact_root, allowed)
    problems += action_problems
    if not actions:
        return {"pre_execution_status": "MISSING_INPUT",
                "problems": problems + ["실행 가능한 draft action 인스턴스가 없음"],
                "contract": None}

    validation_rules = list(draft.get("validation_rules") or [])
    evidence_requirements = list(draft.get("evidence_requirements") or [])
    if not validation_rules and not evidence_requirements:
        return {"pre_execution_status": "MISSING_VALIDATION_CONTRACT",
                "problems": ["draft에 validation_rules도 evidence_requirements도 없음"],
                "contract": None}

    with_input = next((a for a in draft["available_actions"] if a.get("input")), None)
    exchanges = [{"name": "valid_action", "actions": actions[:1],
                  "expect": "state_transition"}]
    revised = actions[:2] if len(actions) >= 2 else actions[:1] * 2
    exchanges.append({"name": "revise_and_rerun", "actions": revised,
                      "expect": "different_result"})
    if with_input is not None:
        exchanges.append({"name": "invalid_action_missing_input",
                          "actions": [{"type": with_input["name"], "payload": {}}],
                          "expect": "explicit_rejection"})
    else:
        problems.append("input이 있는 action이 없어 invalid 거부 exchange를 만들 수 없음")

    scenario_template = dict(draft.get("scenario_template")
                             or {"initial_state": draft["initial_state"]})
    input_payload = {"scenario_template": scenario_template, "exchanges": exchanges}
    contract = {
        "execution_id": "exec_" + _digest({
            "draft": _digest(draft), "runner": runner_command,
            "input": _digest(input_payload)})[:16],
        "draft_ref": DRAFT_REL,
        "runner_ref": runner_command,
        "execution_kind": EXECUTION_KIND_ACTION_SCENARIO,
        "input_payload": input_payload,
        "initial_state": draft["initial_state"],
        "allowed_actions": sorted(allowed),
        "expected_outputs": [str(f) for f in
                             (runner_contract.get("required_output_fields") or [])],
        "side_effect_policy": {
            "workspace": "temporary_copy_only",
            "declared_created_prefixes": [_EXEC_SCENARIO_DIR + "/"],
            "protected_prefixes": list(PROTECTED_REL_PREFIXES),
            "protected_files": list(PROTECTED_REL_FILES),
            "network": "forbidden",
            "subprocess": "runner_contract_command_only",
        },
        "timeout_policy": {"per_exchange_seconds": float(timeout)},
        "validation_rules": validation_rules,
        "evidence_requirements": evidence_requirements,
    }
    return {"pre_execution_status": "READY_TO_EXECUTE", "problems": problems,
            "contract": contract}


# ---------------------------------------------------------------- 실행 (§6~§7)

def execute_contract(artifact_root: Path, contract: dict, *,
                     use_docker: bool | None = False,
                     secrets: list[str] | None = None) -> dict:
    """canonical contract를 temp copy에서 실제 runner로 실행한다. 원본 artifact는 불변이다.

    반환: {"exchanges", "manifest", "runner_status", "started_at", "finished_at"}
    runner_status는 runner 계층 판정만 담당한다 — 의미 검증은 validate_execution이 한다.
    """
    secrets = secrets or []
    timeout = float(contract["timeout_policy"]["per_exchange_seconds"])
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.monotonic()
    exchanges_out: list[dict] = []
    tmp = Path(tempfile.mkdtemp(prefix="draft_exec_"))
    try:
        tmp_ws = tmp / "ws"
        shutil.copytree(artifact_root, tmp_ws,
                        ignore=shutil.ignore_patterns("__pycache__"))
        hash_before = _hash_tree(tmp_ws)
        runner_contract = _load_json(tmp_ws / "runner_contract.json") or {}

        (tmp_ws / _EXEC_SCENARIO_DIR).mkdir(parents=True, exist_ok=True)
        template = contract["input_payload"]["scenario_template"]
        timed_out = False
        for i, ex in enumerate(contract["input_payload"]["exchanges"], start=1):
            scenario = json.loads(json.dumps(template))
            scenario["actions"] = ex["actions"]
            rel = f"{_EXEC_SCENARIO_DIR}/exchange_{i:02d}.json"
            (tmp_ws / rel).write_text(json.dumps(scenario, ensure_ascii=True),
                                      encoding="utf-8")
            t_ex = time.monotonic()
            run = run_scenario_once(tmp_ws, runner_contract, rel, timeout,
                                    use_docker, secrets)
            parsed = run.get("parsed")
            timed_out = timed_out or bool(run.get("timed_out"))
            exchanges_out.append({
                "exchange": ex["name"],
                "expect": ex["expect"],
                "actions": [a.get("type") for a in ex["actions"]],
                "command": run.get("command"),
                "exit_code": run.get("exit_code"),
                "timed_out": bool(run.get("timed_out")),
                "elapsed_seconds": round(time.monotonic() - t_ex, 3),
                "parsed": parsed is not None,
                "input_sha256": _digest(scenario),
                "output_sha256": _digest(parsed) if parsed is not None else None,
                "missing_fields": list(run.get("missing_fields") or []),
                "error_signal": has_error_signal(parsed),
                "final_state": (parsed or {}).get("final_state"),
                "events_count": len((parsed or {}).get("events") or []),
                "errors": list((parsed or {}).get("errors") or [])[:5],
                "stderr_summary": (run.get("stderr") or "")[:_STDIO_SUMMARY_LIMIT],
            })

        hash_after = _hash_tree(tmp_ws)
        created = sorted(k for k in hash_after if k not in hash_before)
        deleted = sorted(k for k in hash_before if k not in hash_after)
        modified = sorted(k for k in hash_before
                          if k in hash_after and hash_before[k] != hash_after[k])
        protected_changed = sorted(
            k for k in created + deleted + modified if _is_protected_rel(k))
        declared = tuple(contract["side_effect_policy"]["declared_created_prefixes"])
        undeclared_created = [k for k in created
                              if not any(k.startswith(d) for d in declared)]
        manifest = {
            "created": created,
            "modified": modified,
            "deleted": deleted,
            "undeclared_created": undeclared_created,
            "protected_paths_changed": protected_changed,
            "protected_paths_unchanged": not protected_changed,
            "exit_codes": [e["exit_code"] for e in exchanges_out],
            "any_timeout": timed_out,
            "elapsed_seconds": round(time.monotonic() - t0, 3),
            "stdout_stderr_policy": f"요약 {_STDIO_SUMMARY_LIMIT}자 한도 — 전체 복제 없음",
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # runner 계층 상태 판정 (§7)
    if timed_out:
        runner_status = "TIMED_OUT"
    elif protected_changed or undeclared_created:
        runner_status = "UNSAFE"
    elif not exchanges_out:
        runner_status = "INVALID_INPUT"
    elif any(not e["parsed"] for e in exchanges_out):
        runner_status = "RUNNER_FAILED"
    else:
        runner_status = "EXECUTED"
    return {"exchanges": exchanges_out, "manifest": manifest,
            "runner_status": runner_status, "started_at": started_at,
            "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ---------------------------------------------------------------- 검증 (§9)

def validate_execution(contract: dict, execution: dict) -> dict:
    """runner 실행/출력/state 전이/side effect/evidence 완전성을 구분해 판정한다 (§9).

    exit 0·파일 생성·validator 미실행을 성공으로 승격하는 경로는 없다.
    """
    exchanges = {e["exchange"]: e for e in execution["exchanges"]}
    manifest = execution["manifest"]
    valid = exchanges.get("valid_action") or {}
    revised = exchanges.get("revise_and_rerun") or {}
    invalid = exchanges.get("invalid_action_missing_input") or {}

    runner_ok = bool(valid.get("parsed")) and valid.get("exit_code") == 0 \
        and not valid.get("timed_out")
    output_ok = runner_ok and not valid.get("missing_fields")
    state_ok = (runner_ok and valid.get("final_state") is not None
                and valid["final_state"] != contract["initial_state"]
                and not valid.get("error_signal"))
    invalid_rejected = bool(invalid) and bool(invalid.get("parsed")) \
        and bool(invalid.get("error_signal"))
    revise_ok = bool(revised.get("parsed")) and \
        revised.get("output_sha256") not in (None, valid.get("output_sha256"))
    side_effect_ok = bool(manifest.get("protected_paths_unchanged")) \
        and not manifest.get("undeclared_created")
    evidence_complete = all([
        bool(valid.get("input_sha256")),
        valid.get("output_sha256") is not None or not runner_ok,
        "exit_codes" in manifest,
        bool(execution.get("started_at")),
    ]) and bool(invalid)  # invalid 거부 실증 없이는 evidence 요구(§8)를 못 채운다

    checks = {
        "runner_invocation_ok": runner_ok,
        "output_fields_ok": output_ok,
        "state_transition_ok": state_ok,
        "invalid_action_rejected": invalid_rejected,
        "revise_changes_result": revise_ok,
        "side_effect_policy_ok": side_effect_ok,
        "evidence_complete": evidence_complete,
    }
    problems = [name for name, ok in checks.items() if not ok]
    return {"checks": checks, "problems": problems, "pass": not problems}


def _final_execution_status(runner_status: str, validation: dict) -> str:
    """runner 계층 상태와 validation을 §7 상태 하나로 정규화한다."""
    if runner_status != "EXECUTED":
        return runner_status
    if not validation["checks"]["evidence_complete"]:
        return "EVIDENCE_INCOMPLETE"
    if not validation["pass"]:
        return "VALIDATION_FAILED"
    return "EXECUTED"


# ---------------------------------------------------------------- executor 본체 (lane 계약)

def run_runner_backed_execution(run_dir=None, run_id=None, apply: bool = False,
                                db_conn=None, timeout: float = 60.0,
                                use_docker: bool | None = False,
                                secrets: list[str] | None = None) -> dict:
    """도메인 중립 runner-backed draft execution executor.

    반환 계약은 lane executor(_exec_apply_tool)와 동일 — applied/patched_files/problems/
    error/ok/status. applied·ok=true는 실제 실행 + validation PASS일 때만이다."""
    result: dict = {"ok": False, "status": None, "applied": False, "patched_files": [],
                    "execution_kind": None, "pre_execution_status": None,
                    "execution_status": None, "problems": [], "error": None,
                    "execution_evidence": None}
    if run_dir is None:
        result["status"] = "PRECONDITION_NO_TARGET"
        result["error"] = "run_dir가 필요합니다"
        return result
    run_dir = Path(run_dir)
    artifact_root = resolve_artifact_root(run_dir)
    if artifact_root is None or not Path(artifact_root).is_dir():
        result["status"] = "PRECONDITION_NO_ARTIFACT_ROOT"
        result["error"] = "artifact root(workspace/final_artifact) 없음 — explicit missing state"
        return result
    artifact_root = Path(artifact_root)

    pre = build_execution_contract(artifact_root, timeout)
    result["pre_execution_status"] = pre["pre_execution_status"]
    result["problems"] = list(pre["problems"])
    if pre["pre_execution_status"] != "READY_TO_EXECUTE":
        result["status"] = f"PRECONDITION_{pre['pre_execution_status']}"
        result["error"] = "; ".join(pre["problems"]) or pre["pre_execution_status"]
        _write_outputs(run_dir, contract=pre.get("contract"), execution=None,
                       validation=None, report=_report_dict(result, None, None))
        return result
    contract = pre["contract"]
    result["execution_kind"] = contract["execution_kind"]

    if not apply:
        result["ok"] = True
        result["status"] = "PLAN_ONLY"
        result["plan"] = {
            "pre_execution_status": "READY_TO_EXECUTE",
            "execution_id": contract["execution_id"],
            "runner_ref": contract["runner_ref"],
            "exchanges": [e["name"] for e in contract["input_payload"]["exchanges"]],
        }
        _write_outputs(run_dir, contract=contract,
                       report=_report_dict(result, None, None))
        return result

    execution = execute_contract(artifact_root, contract,
                                 use_docker=use_docker, secrets=secrets)
    validation = validate_execution(contract, execution)
    status = _final_execution_status(execution["runner_status"], validation)
    result["execution_status"] = status
    result["status"] = status
    included = status == "EXECUTED" and validation["pass"]
    result["applied"] = included
    result["ok"] = included
    result["problems"] += [f"validation: {p}" for p in validation["problems"]]
    if not included:
        result["error"] = f"execution status {status}: " + \
            ("; ".join(validation["problems"]) or execution["runner_status"])

    valid_ex = next((e for e in execution["exchanges"]
                     if e["exchange"] == "valid_action"), {})
    exec_result = {
        "execution_id": contract["execution_id"],
        "status": status,
        "started_at": execution["started_at"],
        "finished_at": execution["finished_at"],
        "runner": contract["runner_ref"],
        "inputs_digest": _digest(contract["input_payload"]),
        "initial_state_digest": _digest(contract["initial_state"]),
        "final_state_digest": _digest(valid_ex.get("final_state"))
        if valid_ex.get("final_state") is not None else None,
        "outputs": [{"exchange": e["exchange"], "output_sha256": e["output_sha256"],
                     "events_count": e["events_count"]}
                    for e in execution["exchanges"]],
        "side_effects": execution["manifest"],
        "validation_refs": [f"{EXECUTION_SUBDIR}/{EVIDENCE_JSON}#validation"],
        "evidence_refs": [f"{EXECUTION_SUBDIR}/{EVIDENCE_JSON}"],
        "error_code": None if status == "EXECUTED" else status,
        "error_summary": result.get("error"),
    }
    evidence = {
        "execution_provenance": {
            "execution_id": contract["execution_id"],
            "produced_by": "factory_runner_backed_execution",
            "started_at": execution["started_at"],
            "finished_at": execution["finished_at"],
            "fresh": True,
        },
        "input_digest": exec_result["inputs_digest"],
        "runner_identity": contract["runner_ref"],
        "exchanges": execution["exchanges"],
        "initial_state_digest": exec_result["initial_state_digest"],
        "final_state_digest": exec_result["final_state_digest"],
        "state_change_observed": validation["checks"]["state_transition_ok"],
        "invalid_action_rejected": validation["checks"]["invalid_action_rejected"],
        "revise_changes_result": validation["checks"]["revise_changes_result"],
        "side_effect_summary": {
            k: execution["manifest"][k]
            for k in ("created", "modified", "deleted", "protected_paths_unchanged",
                      "exit_codes", "any_timeout", "elapsed_seconds")},
        "validation": validation,
    }
    result["execution_evidence"] = {
        "can_execute_input": included and validation["checks"]["state_transition_ok"],
        "result_visible_in_ui": (artifact_root / "product/interaction/index.html").is_file(),
        "state_change_observed": validation["checks"]["state_transition_ok"],
        "invalid_action_rejected": validation["checks"]["invalid_action_rejected"],
        "revise_changes_result": validation["checks"]["revise_changes_result"],
    }
    report = _report_dict(result, exec_result, validation)
    _write_outputs(run_dir, contract=contract, execution_result=exec_result,
                   execution=execution, validation=validation, evidence=evidence,
                   report=report)
    return result


def _report_dict(result: dict, exec_result: dict | None, validation: dict | None) -> dict:
    included = bool(result.get("applied")) and bool((validation or {}).get("pass"))
    return {
        "applied": bool(result.get("applied")),
        "execution_kind": result.get("execution_kind"),
        "pre_execution_status": result.get("pre_execution_status"),
        "execution_status": result.get("execution_status"),
        "runner_backed_execution_included": included,
        "execution_evidence": result.get("execution_evidence"),
        "execution_id": (exec_result or {}).get("execution_id"),
        "problems": list(result.get("problems") or []),
        "error": result.get("error"),
    }


def _write_outputs(run_dir: Path, *, contract=None, execution_result=None,
                   execution=None, validation=None, evidence=None, report=None) -> None:
    out_dir = Path(run_dir) / EXECUTION_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if contract is not None:
        (out_dir / CONTRACT_JSON).write_text(_dump(contract) + "\n", encoding="utf-8")
    if execution_result is not None:
        (out_dir / RESULT_JSON).write_text(_dump(execution_result) + "\n", encoding="utf-8")
    if execution is not None:
        (out_dir / MANIFEST_JSON).write_text(
            _dump(execution["manifest"]) + "\n", encoding="utf-8")
    if evidence is not None:
        (out_dir / EVIDENCE_JSON).write_text(_dump(evidence) + "\n", encoding="utf-8")
    if report is not None:
        (out_dir / REPORT_JSON).write_text(_dump(report) + "\n", encoding="utf-8")
        (out_dir / DASHBOARD_JSON).write_text(_dump({
            "phase": "draft_execution",
            "execution_status": report.get("execution_status")
            or report.get("pre_execution_status"),
            "pre_execution_status": report.get("pre_execution_status"),
            "runner_backed_execution_included": report.get("runner_backed_execution_included"),
            "validation_pass": bool((validation or {}).get("pass")),
            "validation_problems": list((validation or {}).get("problems") or []),
            "execution_id": report.get("execution_id"),
            "problems": list(report.get("problems") or [])[:10],
        }) + "\n", encoding="utf-8")
