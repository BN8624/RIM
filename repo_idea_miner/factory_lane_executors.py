# Phase 2D-1 §4~§5: lane executor registry — 기존 repair/polish/editor/execution 경로를 child run에 연결.
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from repo_idea_miner.factory_product_loop import (
    compare_protected_hashes,
    compute_loop_protected_hashes,
)

# lane → 재사용하는 기존 경로 (§4 연결표 — 보고서에도 이 표를 그대로 쓴다)
LANE_EXECUTOR_ROUTES = {
    "SPEC_REPAIR": "Phase 2B-1 factory_spec_repair.run_spec_repair_apply (child copy에 apply)",
    "CORE_PATCH": "Phase 2A factory_continue.run_continuation (continuation run이 child)",
    "RUNNER_PATCH": "Phase 2A factory_continue.run_continuation (continuation run이 child)",
    "VIEWER_POLISH": "generic factory_viewer_polish.run_viewer_polish (graph 도메인 포함 — "
                     "이슈 #23 canonical 전환, legacy 2C-1 adapter 라우팅 제거, "
                     "child copy에 apply)",
    "INTERACTION_UI": "generic factory_interaction_ui.run_interaction_ui (graph 도메인 포함 — "
                      "이슈 #20 canonical graph renderer, legacy 2C-2 adapter 라우팅 제거, "
                      "child copy에 apply)",
    "RUNNER_BACKED_DRAFT_EXECUTION":
        "generic factory_runner_backed_execution.run_runner_backed_execution (graph 도메인 포함 — "
        "이슈 #21 canonical 전환, legacy 2C-3 adapter 라우팅 제거, child copy에 apply)",
    "UX_POLISH": "generic factory_ux_polish.run_ux_polish (제한된 operation catalog, "
                 "child copy에 apply — 이슈 #8)",
    "ARCHIVE": "apply 없음 — archive report 생성",
    "HOLD_FOR_HUMAN": "apply 없음 — human decision packet 생성 (§11)",
}

# lane별 allowed scope (workspace 상대 prefix). §1-5 검증에 사용.
LANE_ALLOWED_SCOPES = {
    "SPEC_REPAIR": ("golden/", "fixtures/", "core_contract.json", "state_contract.json",
                    "action_contract.json", "runner_contract.json"),
    "CORE_PATCH": ("src/", "product/", "run_instructions.md", "README.md"),
    "RUNNER_PATCH": ("src/", "product/", "run_instructions.md", "README.md"),
    "VIEWER_POLISH": ("product/",),
    "INTERACTION_UI": ("product/",),
    "RUNNER_BACKED_DRAFT_EXECUTION": ("product/", "src/adapters/"),
    "UX_POLISH": ("product/",),
}

# child run 복사에서 제외 — loop 자신의 bookkeeping과 로그는 계보에 속하지 않는다
_CHILD_COPY_IGNORES = ("phase2d1", "debug", "__pycache__")


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def failure_signature(lane: str, problems: list[str] | None, error: str | None) -> str | None:
    """중단 조건(§10 '같은 failure signature 2회')용 안정적 signature."""
    items = sorted((problems or [])[:5]) + ([error] if error else [])
    if not items:
        return None
    blob = lane + "|" + "|".join(str(i)[:200] for i in items)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def _rewrite_child_base_pointers(parent_run_dir: Path, child_run_dir: Path) -> None:
    """child로 복사된 base 포인터가 parent 내부를 가리키면 child 내부 경로로 재작성한다.

    포인터가 parent를 계속 가리키면 child continuation의 seed가 parent snapshot이 되어
    child에서의 수정이 전부 무시된다 (§5 원본 불변의 대칭 — child는 child를 봐야 한다)."""
    for fname in ("continuation_base.json", "green_base.json"):
        fpath = child_run_dir / fname
        data = _load_json(fpath)
        if not isinstance(data, dict):
            continue
        changed = False
        for key in ("continuation_base_path", "green_base_path"):
            val = data.get(key)
            if not isinstance(val, str) or not val:
                continue
            try:
                rel = Path(val.replace("\\", "/")).resolve().relative_to(
                    Path(parent_run_dir).resolve())
            except (ValueError, OSError):
                continue
            data[key] = (Path(child_run_dir) / rel).as_posix()
            changed = True
        if changed:
            fpath.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def copy_run_as_child(parent_run_dir: Path, child_run_dir: Path | None,
                      children_root: Path | None = None) -> Path:
    """parent run 전체를 child run으로 복사한다 (§5 — 원본 불변, child에서만 apply)."""
    if child_run_dir is None:
        from repo_idea_miner.factory_pipeline import make_factory_run_dir
        child_run_dir = make_factory_run_dir(children_root or Path("runs"))
    shutil.copytree(parent_run_dir, child_run_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*_CHILD_COPY_IGNORES))
    _rewrite_child_base_pointers(Path(parent_run_dir), Path(child_run_dir))
    (child_run_dir / "child_run_origin.json").write_text(json.dumps({
        "parent_run_dir": str(Path(parent_run_dir).as_posix()),
        "created_by": "phase2d1_loop_executor",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return child_run_dir


def check_allowed_scope(lane: str, changed_files: list[str]) -> str:
    allowed = LANE_ALLOWED_SCOPES.get(lane)
    if allowed is None or not changed_files:
        return "PASS"
    for rel in changed_files:
        norm = str(rel).replace("\\", "/").lstrip("./")
        # run 문서(diff/report 등 run_dir 루트 기록물)는 산출물 기록이라 허용
        if "/" not in norm and norm.endswith((".json", ".md")):
            continue
        if not any(norm.startswith(pfx) or norm == pfx.rstrip("/") for pfx in allowed):
            return "FAIL"
    return "PASS"


def _common_result(lane: str, status: str, child_run_dir: Path | None,
                   changed_files: list[str], targeted_tests: list[str],
                   targeted_test_status: str, problems: list[str], error: str | None,
                   underlying: dict | None = None) -> dict:
    return {
        "lane": lane,
        "status": status,  # APPLIED | BLOCKED | FAILED | NO_CHANGE
        "child_run_dir": str(child_run_dir.as_posix()) if child_run_dir else None,
        "changed_files": changed_files,
        "allowed_scope_check": check_allowed_scope(lane, changed_files),
        "protected_hash_check": None,  # execute_lane이 parent 기준으로 채운다
        "targeted_tests": targeted_tests,
        "targeted_test_status": targeted_test_status,
        "failure_signature": None if status == "APPLIED" else failure_signature(lane, problems, error),
        "problems": problems,
        "error": error,
        "underlying_status": (underlying or {}).get("status"),
        "route": LANE_EXECUTOR_ROUTES.get(lane, ""),
    }


# ---------------------------------------------------------------- lane별 executor

def _exec_spec_repair(ctx: dict) -> dict:
    from repo_idea_miner.factory_spec_repair import run_spec_repair_apply
    child = copy_run_as_child(ctx["parent_run_dir"], ctx.get("child_run_dir"),
                              ctx.get("children_root"))
    res = run_spec_repair_apply(run_dir=child, apply=True, mode=ctx["mode"], llm=ctx.get("llm"),
                                settings=ctx.get("settings"),
                                factory_settings=ctx.get("factory_settings"))
    changed = [str(f) for f in (res.get("applied_files") or [])]
    if res.get("applied"):
        status = "APPLIED"
    elif res.get("status") in ("NOTHING_TO_APPLY",):
        status = "NO_CHANGE"
    elif res.get("status") in ("CANNOT_APPLY_SPEC_REPAIR", "APPLY_BLOCKED"):
        status = "BLOCKED"
    else:
        status = "FAILED"
    return _common_result("SPEC_REPAIR", status, child, changed,
                          ["spec_repair_gate_rerun"],
                          "PASS" if res.get("applied") and all(
                              (res.get("gates") or {}).values()) else
                          ("FAIL" if res.get("applied") else "NOT_RUN"),
                          list(res.get("problems") or []), res.get("error"), res)


def _exec_continuation(lane: str, ctx: dict) -> dict:
    from repo_idea_miner.factory_continue import run_continuation
    res = run_continuation(base_run_dir=ctx["parent_run_dir"], mode=ctx["mode"],
                           output_dir=ctx["children_root"], db_conn=ctx.get("db_conn"),
                           settings=ctx.get("settings"),
                           factory_settings=ctx.get("factory_settings"), llm=ctx.get("llm"))
    child = Path(res["continuation_run_dir"]) if res.get("continuation_run_dir") else None
    changed: list[str] = []
    if child is not None:
        diff = _load_json(child / "continuation_diff_summary.json") or \
            _load_json(child / "diff_summary.json") or {}
        changed = [str(f) for f in (diff.get("files") or diff.get("changed_files") or [])]
    if res.get("status") == "CANNOT_CONTINUE":
        status = "BLOCKED"
    elif res.get("promoted_to_green_base"):
        status = "APPLIED"
    elif res.get("patch_attempts", 0) == 0 and not res.get("error"):
        status = "NO_CHANGE"
    else:
        status = "FAILED"
    return _common_result(lane, status, child, changed,
                          ["continuation_gate_rerun"],
                          "PASS" if res.get("promoted_to_green_base") else
                          ("FAIL" if child is not None else "NOT_RUN"),
                          list(res.get("failure_types") or []), res.get("error"), res)


def _exec_apply_tool(lane: str, ctx: dict, runner) -> dict:
    child = copy_run_as_child(ctx["parent_run_dir"], ctx.get("child_run_dir"),
                              ctx.get("children_root"))
    res = runner(run_dir=child, apply=True, timeout=ctx.get("timeout", 60.0))
    changed = [str(f) for f in (res.get("patched_files") or [])]
    if res.get("applied"):
        status = "APPLIED"
    elif res.get("error") or res.get("problems"):
        blocked_markers = ("PRECONDITION", "NOT_NEEDED", "ALREADY", "CANNOT")
        status = "BLOCKED" if any(m in str(res.get("status") or "") for m in blocked_markers) \
            else "FAILED"
    else:
        status = "NO_CHANGE"
    smoke_pass = bool(res.get("ok")) and res.get("applied")
    return _common_result(lane, status, child, changed,
                          [f"{lane.lower()}_smoke"],
                          "PASS" if smoke_pass else ("FAIL" if res.get("applied") else "NOT_RUN"),
                          list(res.get("problems") or []), res.get("error"), res)


def _exec_viewer_polish(ctx: dict) -> dict:
    # 이슈 #23: graph 포함 전 도메인이 canonical viewer polish executor를 사용한다 —
    # replay discovery → schema-shape adapter → canonical viewer contract → generic
    # viewer core → navigation evidence. legacy 2C-1 adapter 라우팅(2C-0 report·
    # REVIEW_READY·green_base·#47 viewer shape 전제)은 제거됨. challenge 분기 없음.
    from repo_idea_miner.factory_viewer_polish import run_viewer_polish
    return _exec_apply_tool("VIEWER_POLISH", ctx, run_viewer_polish)


def _exec_interaction_ui(ctx: dict) -> dict:
    # 이슈 #20: graph 포함 전 도메인이 canonical interaction executor를 사용한다 —
    # graph는 contract 기반 graph renderer(#19 shape 정본 재사용)로 렌더만 분기하며,
    # legacy 2C-2 editor adapter 라우팅은 제거됨. 특정 challenge 분기 없음.
    from repo_idea_miner.factory_interaction_ui import run_interaction_ui
    return _exec_apply_tool("INTERACTION_UI", ctx, run_interaction_ui)


def _exec_draft_execution(ctx: dict) -> dict:
    # 이슈 #21: graph 포함 전 도메인이 canonical runner-backed executor를 사용한다 —
    # 실행 근거는 draft(interaction contract)·runner contract·fixture이며,
    # legacy 2C-3 adapter 라우팅(2C-2 report/REVIEW_READY/green_base/human gate 전제)은 제거됨.
    from repo_idea_miner.factory_runner_backed_execution import run_runner_backed_execution
    return _exec_apply_tool("RUNNER_BACKED_DRAFT_EXECUTION", ctx, run_runner_backed_execution)


def _exec_ux_polish(ctx: dict) -> dict:
    # 이슈 #8: 제한된 operation catalog 기반 generic UX executor — 자유 형식 수정 없음.
    # 도메인/graph 분기 없음: 진단이 catalog와 일치하지 않으면 executor가 스스로
    # UX_READY/UNSUPPORTED/UPSTREAM_BLOCKED로 정직하게 남긴다.
    from repo_idea_miner.factory_ux_polish import run_ux_polish
    return _exec_apply_tool("UX_POLISH", ctx, run_ux_polish)


def _exec_archive(ctx: dict) -> dict:
    report_dir = Path(ctx["iteration_dir"])
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "archive_report.json").write_text(json.dumps({
        "lane": "ARCHIVE",
        "parent_run_dir": str(Path(ctx["parent_run_dir"]).as_posix()),
        "reason": ctx.get("reason") or "gap 판정이 ARCHIVE_RECOMMENDED",
        "apply": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return _common_result("ARCHIVE", "NO_CHANGE", None, [], [], "NOT_RUN", [], None)


def _exec_hold_for_human(ctx: dict) -> dict:
    # packet 자체는 orchestrator가 §11 필수 필드로 작성한다 — 여기서는 apply 없음만 보장.
    return _common_result("HOLD_FOR_HUMAN", "NO_CHANGE", None, [], [], "NOT_RUN", [], None)


LANE_EXECUTORS = {
    "SPEC_REPAIR": _exec_spec_repair,
    "CORE_PATCH": lambda ctx: _exec_continuation("CORE_PATCH", ctx),
    "RUNNER_PATCH": lambda ctx: _exec_continuation("RUNNER_PATCH", ctx),
    "VIEWER_POLISH": _exec_viewer_polish,
    "INTERACTION_UI": _exec_interaction_ui,
    "RUNNER_BACKED_DRAFT_EXECUTION": _exec_draft_execution,
    "UX_POLISH": _exec_ux_polish,
    "ARCHIVE": _exec_archive,
    "HOLD_FOR_HUMAN": _exec_hold_for_human,
}


def execute_lane(lane: str, ctx: dict) -> dict:
    """lane 1개를 실행한다 (§4). parent run 보호 hash를 전후 비교해 원본 불변을 증명한다."""
    executor = LANE_EXECUTORS.get(lane)
    if executor is None:
        return _common_result(lane, "BLOCKED", None, [], [], "NOT_RUN",
                              [f"알 수 없는 lane: {lane}"], None)
    parent = Path(ctx["parent_run_dir"])
    before = compute_loop_protected_hashes(parent)
    try:
        result = executor(ctx)
    except Exception as exc:  # noqa: BLE001 — lane 실패는 기록하고 loop가 중단을 판단한다
        result = _common_result(lane, "FAILED", None, [], [], "NOT_RUN",
                                [f"executor 예외: {exc}"], str(exc))
    after = compute_loop_protected_hashes(parent)
    check = compare_protected_hashes(before, after)
    result["protected_hash_check"] = check["status"]
    if check["status"] != "PASS":
        result["status"] = "FAILED"
        result["problems"] = list(result.get("problems") or []) + [
            f"parent run 보호 대상이 변경됨: {check.get('changed') or check.get('added') or check.get('removed')}"]
    return result
