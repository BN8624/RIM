# Phase 2D-1 §6~§7: 도메인 중립 Product Capability Profile 추출과 Fresh Probe(실제 artifact 재검사) 모듈.
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from repo_idea_miner.factory_core_gates import (
    detect_mock_fallback,
    list_scenario_files,
    run_scenario_once,
)
from repo_idea_miner.factory_run_layout import resolve_artifact_root

# ---------------------------------------------------------------- 공통 loop evidence 이름 (§6)

# 판정/acceptance가 공유하는 도메인 중립 evidence 이름. node/edge/file 같은 상세는 adapter evidence에만 둔다.
COMMON_LOOP_EVIDENCE = (
    "can_create_or_modify_input",
    "can_validate_input",
    "can_execute_primary_action",
    "can_observe_state_change",
    "can_understand_success",
    "can_understand_failure",
    "can_revise_and_retry",
    "product_loop_closed",
)

# 2D-0 이전 artifact(on-disk)의 이름 → 공통 이름. 읽을 때만 정규화하고 다시 쓰지 않는다.
LEGACY_LOOP_EVIDENCE_ALIASES = {
    "can_create_input": "can_create_or_modify_input",
    "can_execute_input": "can_execute_primary_action",
    "can_see_result_from_created_input": "can_observe_state_change",
    "can_revise_and_rerun": "can_revise_and_retry",
}


def normalize_loop_evidence(loop: dict) -> dict:
    """구/신 이름이 섞인 loop evidence를 공통 이름(§6)으로 정규화한다.

    can_understand_success가 없던 구 artifact는 can_observe_state_change에서 보수적으로 파생한다.
    """
    out: dict = {}
    for key, value in (loop or {}).items():
        out[LEGACY_LOOP_EVIDENCE_ALIASES.get(key, key)] = value
    if "can_understand_success" not in out:
        out["can_understand_success"] = bool(out.get("can_observe_state_change"))
    return out


# ---------------------------------------------------------------- input kind 분류 (§6)

# challenge ID/title이 아니라 contract 구조 어휘로만 분류한다. 우선순위는 동점 tie-break 전용.
_INPUT_KIND_TOKENS = (
    ("graph", ("node", "edge", "graph", "vertex", "port", "dag", "connection")),
    ("file_operation", ("file", "directory", "folder", "path", "explorer", "filesystem")),
    ("document", ("document", "text", "page", "section", "paragraph", "sentence")),
    ("scenario", ("scenario", "simulation", "tick", "turn", "round")),
)

_WORD_RE = re.compile(r"[a-z]+")


def classify_input_kind(core_contract: dict) -> str:
    """state_entities/actions의 이름·필드 어휘로 input_kind를 결정적으로 분류한다."""
    words: list[str] = []
    for ent in (core_contract or {}).get("state_entities") or []:
        words += _WORD_RE.findall(str(ent.get("name", "")).lower())
        for f in ent.get("fields") or []:
            words += _WORD_RE.findall(str(f).lower())
    for act in (core_contract or {}).get("actions") or []:
        words += _WORD_RE.findall(str(act.get("name", "")).lower())
        for f in (act.get("input") or []):
            words += _WORD_RE.findall(str(f).lower())
    bag = set(words)
    best_kind, best_hits = "generic", 0
    for kind, tokens in _INPUT_KIND_TOKENS:
        hits = sum(1 for t in tokens if t in bag)
        if hits > best_hits:
            best_kind, best_hits = kind, hits
    return best_kind


# ---------------------------------------------------------------- capability profile (§6)

def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def find_viewer_entrypoint(workspace: Path) -> str:
    """product/ 아래 첫 index.html의 workspace 상대 경로. 없으면 빈 문자열."""
    product = workspace / "product"
    if not product.is_dir():
        return ""
    candidates = sorted(product.rglob("index.html"))
    return str(candidates[0].relative_to(workspace).as_posix()) if candidates else ""


def build_capability_profile(run_dir: str | Path) -> dict:
    """artifact/contract에서 도메인 중립 capability profile을 만든다 (§6).

    challenge ID/title로 분기하지 않는다 — 모든 필드는 contract/파일 구조에서만 파생된다.
    """
    run_dir = Path(run_dir)
    ws = resolve_artifact_root(run_dir)
    core_contract = _load_json(ws / "core_contract.json") or {}
    runner_contract = _load_json(ws / "runner_contract.json") or {}
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    required = [str(f) for f in (runner_contract.get("required_output_fields") or [])]
    execution_command = str(runner_contract.get("runner_command") or "")
    profile = {
        "input_kind": classify_input_kind(core_contract),
        "editable_entities": [str(e.get("name", "")) for e in
                              (core_contract.get("state_entities") or []) if e.get("name")],
        # 이 하네스에서 입력 검증은 runner 실행(preconditions 거부)으로 이뤄진다 — 별도 명령 없음.
        "validation_command": execution_command,
        "execution_command": execution_command,
        "viewer_entrypoint": find_viewer_entrypoint(ws),
        "result_required_fields": required,
        "failure_required_fields": [f for f in ("ok", "errors") if f in required],
        "primary_user_actions": [str(a.get("name", "")) for a in
                                 (core_contract.get("actions") or []) if a.get("name")],
        "critical_user_flows": [str(c) for c in (normalized.get("success_conditions") or [])],
        "profile_sources": {
            "core_contract": f"{ws.name}/core_contract.json",
            "runner_contract": f"{ws.name}/runner_contract.json",
            "critical_user_flows": "normalized_challenge.json:success_conditions",
        },
    }
    problems: list[str] = []
    if not profile["editable_entities"]:
        problems.append("state_entities에서 editable_entities를 찾지 못함")
    if not execution_command:
        problems.append("runner_contract.runner_command 없음")
    if not profile["viewer_entrypoint"]:
        problems.append("product viewer entrypoint(index.html) 없음")
    profile["problems"] = problems
    profile["status"] = "PASS" if not problems else "INCOMPLETE"
    return profile


# ---------------------------------------------------------------- fresh probe (§7)

_HANDLER_WIRING_RE = re.compile(r"addEventListener\s*\(|\son[a-z]+\s*=", re.IGNORECASE)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(obj) -> str:
    return _sha256_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def mutate_scenario_for_revise(scenario: dict) -> tuple[dict, str]:
    """revise-and-rerun probe용 결정적 입력 변형 규칙 (§7-5).

    actions가 2개 이상이면 마지막 action 제거, 1개면 복제, 0개면 initial_state에 marker 추가.
    도메인 어휘를 읽지 않는 구조 변형이라 어떤 run에도 적용 가능하다.
    """
    mutated = json.loads(json.dumps(scenario))
    actions = mutated.get("actions") or []
    if len(actions) >= 2:
        mutated["actions"] = actions[:-1]
        rule = "drop_last_action"
    elif len(actions) == 1:
        mutated["actions"] = actions + [json.loads(json.dumps(actions[0]))]
        rule = "duplicate_single_action"
    else:
        mutated.setdefault("initial_state", {})["_probe_marker"] = 1
        rule = "add_initial_state_marker"
    mutated["id"] = f"{mutated.get('id') or 'scenario'}_probe_revised"
    return mutated, rule


def _scenario_case_type(workspace: Path, rel: str) -> str:
    data = _load_json(workspace / rel) or {}
    return str(data.get("case_type") or "normal")


def _probe_record(probe_id: str, kind: str, method: str, ok: bool | None, **extra) -> dict:
    return {"probe_id": probe_id, "kind": kind, "method": method, "ok": ok, **extra}


def _run_probe_scenario(tmp_ws: Path, runner_contract: dict, rel: str,
                        timeout: float, use_docker: bool | None, secrets: list[str],
                        out_dir: Path, probe_id: str) -> tuple[dict, dict]:
    """scenario 하나를 temp workspace에서 실행하고 §7 기록 필드를 채운 record를 만든다."""
    run = run_scenario_once(tmp_ws, runner_contract, rel, timeout, use_docker, secrets)
    input_bytes = (tmp_ws / rel).read_bytes() if (tmp_ws / rel).is_file() else b""
    parsed = run.get("parsed")
    artifact_path = out_dir / "probes" / f"{probe_id}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps({
        "scenario": rel, "command": run.get("command"), "exit_code": run.get("exit_code"),
        "stdout": (run.get("stdout") or "")[:20000], "stderr": (run.get("stderr") or "")[:4000],
        "parsed": parsed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    record = _probe_record(
        probe_id, "runner_execution", "runner_execution",
        ok=bool(run.get("ok") and parsed is not None),
        command=run.get("command"), exit_code=run.get("exit_code"),
        scenario=rel,
        input_sha256=_sha256_bytes(input_bytes),
        output_sha256=_sha256_json(parsed) if parsed is not None else None,
        artifact_path=str(artifact_path.as_posix()),
    )
    return record, run


def run_fresh_probe(
    run_dir: str | Path,
    out_dir: str | Path,
    timeout: float = 60.0,
    use_docker: bool | None = False,
    secrets: list[str] | None = None,
) -> dict:
    """iteration 전후 artifact를 실제로 재검사한다 (§7). 보고서 boolean은 읽지 않는다.

    원본 run은 절대 수정하지 않는다 — final_artifact를 temp copy로 떠서 실행한다.
    viewer 관련 probe(7·9·10)는 브라우저 없이 정적 분석만 가능하므로 method=static_analysis로
    정직하게 기록한다 (실제 렌더링 검증으로 과대 기록 금지).
    """
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    secrets = secrets or []
    out_dir.mkdir(parents=True, exist_ok=True)
    ws = resolve_artifact_root(run_dir)
    report: dict = {
        "status": "FAIL", "probes": [], "problems": [],
        "success_scenarios_passed": 0, "failure_scenarios_passed": 0,
        "revise_and_rerun_changed": None, "mock_fallback_count": None,
        "viewer_static_ok": None, "field_consistency_ok": None,
        "critical_flow_handlers_ok": None,
        "method_note": "runner probes는 temp copy 실행, viewer probes는 static_analysis",
    }
    if not ws.is_dir():
        report["problems"].append("artifact root 없음 (final_artifact/도 workspace/도 없음)")
        _write_report(out_dir, report)
        return report
    runner_contract = _load_json(ws / "runner_contract.json") or {}
    if not runner_contract.get("runner_command"):
        report["problems"].append("runner_contract.runner_command 없음")
        _write_report(out_dir, report)
        return report

    tmp = Path(tempfile.mkdtemp(prefix="phase2d1_probe_"))
    try:
        tmp_ws = tmp / "final_artifact"
        shutil.copytree(ws, tmp_ws)
        scenarios = list_scenario_files(tmp_ws)
        by_type: dict[str, list[str]] = {}
        for rel in scenarios:
            by_type.setdefault(_scenario_case_type(tmp_ws, rel), []).append(rel)
        success_pool = (by_type.get("normal") or []) + (by_type.get("boundary") or [])
        failure_pool = by_type.get("invalid") or []

        # 1. runner 실제 실행
        first_rel = scenarios[0] if scenarios else None
        if first_rel is None:
            report["problems"].append("fixtures/ scenario 없음")
            _write_report(out_dir, report)
            return report
        rec, _ = _run_probe_scenario(tmp_ws, runner_contract, first_rel,
                                     timeout, use_docker, secrets, out_dir, "probe01_runner")
        report["probes"].append(rec)
        if not rec["ok"]:
            report["problems"].append("runner 실행 실패")

        # 2~3. 서로 다른 정상 입력 success scenario 2개
        success_runs: list[tuple[dict, dict]] = []
        for i, rel in enumerate(success_pool[:2], start=1):
            rec, run = _run_probe_scenario(tmp_ws, runner_contract, rel,
                                           timeout, use_docker, secrets, out_dir,
                                           f"probe0{i + 1}_success_{i}")
            parsed = run.get("parsed") or {}
            passed = bool(rec["ok"]) and parsed.get("ok") is not False and not parsed.get("errors")
            rec["ok"] = passed
            report["probes"].append(rec)
            success_runs.append((rec, run))
            if passed:
                report["success_scenarios_passed"] += 1
        if len(success_pool) < 2:
            report["problems"].append(f"success scenario 부족 ({len(success_pool)} < 2)")

        # 4. 잘못된 입력 failure scenario — 실패가 정직하게 드러나야 PASS
        for rel in failure_pool[:1]:
            rec, run = _run_probe_scenario(tmp_ws, runner_contract, rel,
                                           timeout, use_docker, secrets, out_dir, "probe04_failure")
            parsed = run.get("parsed") or {}
            surfaced = rec["ok"] and (bool(parsed.get("errors")) or parsed.get("ok") is False)
            rec["ok"] = bool(surfaced)
            report["probes"].append(rec)
            if surfaced:
                report["failure_scenarios_passed"] += 1
        if not failure_pool:
            report["problems"].append("failure(invalid) scenario 없음")

        # 5~6. 입력 수정 후 재실행 + 수정 전후 결과 차이
        base_rel = success_pool[0] if success_pool else first_rel
        base_data = _load_json(tmp_ws / base_rel) or {}
        mutated, rule = mutate_scenario_for_revise(base_data)
        mutated_rel = "fixtures/_probe/scenario_probe_revised.json"
        (tmp_ws / "fixtures" / "_probe").mkdir(parents=True, exist_ok=True)
        (tmp_ws / mutated_rel).write_text(
            json.dumps(mutated, ensure_ascii=False, indent=2), encoding="utf-8")
        rec, mrun = _run_probe_scenario(tmp_ws, runner_contract, mutated_rel,
                                        timeout, use_docker, secrets, out_dir, "probe05_revised")
        rec["mutation_rule"] = rule
        report["probes"].append(rec)
        base_out = next((r.get("parsed") for _rec, r in success_runs
                         if _rec.get("scenario") == base_rel and r.get("parsed") is not None), None)
        if base_out is None:
            base_rec, base_run = _run_probe_scenario(tmp_ws, runner_contract, base_rel,
                                                     timeout, use_docker, secrets, out_dir,
                                                     "probe06_base_for_diff")
            report["probes"].append(base_rec)
            base_out = base_run.get("parsed")
        changed = None
        if base_out is not None and mrun.get("parsed") is not None:
            changed = _sha256_json(base_out) != _sha256_json(mrun["parsed"])
        report["revise_and_rerun_changed"] = changed
        report["probes"].append(_probe_record(
            "probe06_revise_diff", "comparison", "hash_comparison", ok=bool(changed),
            base_output_sha256=_sha256_json(base_out) if base_out is not None else None,
            revised_output_sha256=_sha256_json(mrun["parsed"]) if mrun.get("parsed") is not None else None,
            mutation_rule=rule))
        if changed is not True:
            report["problems"].append("입력 수정 전후 결과가 달라지지 않음 (revise-and-rerun 실패)")

        # 7. viewer가 result artifact를 표시하는지 — 정적 분석 한계 명시
        viewer_rel = find_viewer_entrypoint(tmp_ws)
        viewer_dir = (tmp_ws / viewer_rel).parent if viewer_rel else None
        viewer_srcs: dict[str, str] = {}
        if viewer_dir and viewer_dir.is_dir():
            for p in sorted(viewer_dir.rglob("*")):
                if p.suffix.lower() in (".html", ".js") and p.is_file():
                    viewer_srcs[str(p.relative_to(tmp_ws).as_posix())] = \
                        p.read_text(encoding="utf-8", errors="replace")
        viewer_blob = "\n".join(viewer_srcs.values())
        reads_replay = bool(re.search(r"replay/", viewer_blob)) and "fetch" in viewer_blob
        displays_fields = sum(1 for f in ("final_state", "events", "summary") if f in viewer_blob)
        viewer_ok = bool(viewer_srcs) and reads_replay and displays_fields >= 2
        report["viewer_static_ok"] = viewer_ok
        report["probes"].append(_probe_record(
            "probe07_viewer_display", "viewer", "static_analysis", ok=viewer_ok,
            viewer_entrypoint=viewer_rel, reads_replay=reads_replay,
            displayed_core_fields=displays_fields,
            note="브라우저 미실행 — 렌더링이 아니라 소스 근거만 검사"))
        if not viewer_ok:
            report["problems"].append("viewer가 replay result를 표시하는 정적 근거 부족")

        # 8. mock/fallback 검사
        product_files = {
            str(p.relative_to(tmp_ws).as_posix()): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted((tmp_ws / "product").rglob("*"))
            if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".py")
        } if (tmp_ws / "product").is_dir() else {}
        fb = detect_mock_fallback(product_files)
        report["mock_fallback_count"] = fb["mock_fallback_count"]
        report["probes"].append(_probe_record(
            "probe08_mock_fallback", "static_scan", "static_analysis",
            ok=fb["mock_fallback_count"] == 0,
            mock_fallback_count=fb["mock_fallback_count"], problems=fb["problems"]))
        if fb["mock_fallback_count"]:
            report["problems"].append(f"mock fallback {fb['mock_fallback_count']}건")

        # 9. core output ↔ product surface 필드 정합성
        required = [str(f) for f in (runner_contract.get("required_output_fields") or [])]
        display_fields = [f for f in required if f not in ("ok",)]
        referenced = [f for f in display_fields if f in viewer_blob]
        consistency_ok = bool(viewer_srcs) and len(referenced) >= max(2, len(display_fields) - 2)
        report["field_consistency_ok"] = consistency_ok
        report["probes"].append(_probe_record(
            "probe09_field_consistency", "viewer", "static_analysis", ok=consistency_ok,
            required_fields=display_fields, referenced_fields=referenced))
        if not consistency_ok:
            report["problems"].append(
                f"viewer가 core output 필드를 참조하는 근거 부족 ({referenced}/{display_fields})")

        # 10. critical user flow handler 연결 (정적)
        handler_count = len(_HANDLER_WIRING_RE.findall(viewer_blob))
        handlers_ok = bool(viewer_srcs) and handler_count >= 1
        report["critical_flow_handlers_ok"] = handlers_ok
        report["probes"].append(_probe_record(
            "probe10_flow_handlers", "viewer", "static_analysis", ok=handlers_ok,
            handler_wiring_count=handler_count,
            note="핸들러 바인딩 존재만 검사 — 동작은 브라우저 없이는 미검증"))
        if not handlers_ok:
            report["problems"].append("viewer에 사용자 flow handler 바인딩 근거 없음")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    hard_fail = [p for p in report["problems"]]
    report["status"] = "PASS" if not hard_fail else "FAIL"
    _write_report(out_dir, report)
    return report


def _write_report(out_dir: Path, report: dict) -> None:
    (out_dir / "fresh_probe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def loop_evidence_from_probe(probe_report: dict, prior_loop: dict | None = None) -> dict:
    """fresh probe 결과에서 공통 loop evidence(§6)를 파생한다.

    probe가 직접 관측 못 하는 저작(UI 편집) 항목은 prior evidence(2C-2/2C-3 smoke 기반)를
    normalize해서 넘겨받는다 — probe가 관측한 값이 항상 우선이다.
    """
    prior = normalize_loop_evidence(prior_loop or {})
    out = {
        "can_create_or_modify_input": bool(prior.get("can_create_or_modify_input")),
        "can_validate_input": bool(prior.get("can_validate_input")),
        "can_execute_primary_action": probe_report.get("success_scenarios_passed", 0) >= 1,
        "can_observe_state_change": bool(probe_report.get("viewer_static_ok"))
        and bool(probe_report.get("field_consistency_ok")),
        "can_understand_success": probe_report.get("success_scenarios_passed", 0) >= 1
        and bool(probe_report.get("viewer_static_ok")),
        "can_understand_failure": probe_report.get("failure_scenarios_passed", 0) >= 1,
        "can_revise_and_retry": probe_report.get("revise_and_rerun_changed") is True,
    }
    out["product_loop_closed"] = all(out.values())
    return out
