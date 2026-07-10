# Phase 2A Continuation Queue Manager: run discovery(DB 우선+fs fallback)·lane routing·safe patch lane·spec repair proposal/review(read-only) 모듈.
from __future__ import annotations

import json
from pathlib import Path

from repo_idea_miner.challenge_db import utcnow_iso
from repo_idea_miner.factory_continue import (
    LANE_EXCLUDED,
    LANE_PATCH,
    LANE_REVIEW_ONLY,
    LANE_SPEC_REPAIR,
    NEVER_PATCH_FAILURE_TYPES,
    PATCH_SAFE_FAILURE_TYPES,
    assess_failure_patch_safety,
    build_spec_repair_proposal,
    build_spec_repair_review,
    load_continuation_base,
    run_continuation,
)
from repo_idea_miner.factory_db import list_product_runs, open_factory_db
from repo_idea_miner.factory_frozen import compute_frozen_hashes, write_frozen_hash_guard

# ---------------------------------------------------------------- 정책 상수 (주문서 §4.1, §5.1)

DRY_RUN_DEFAULT_LIMIT = 20
DRY_RUN_MAX_LIMIT = 50
EXECUTE_DEFAULT_LIMIT = 1
EXECUTE_MAX_LIMIT = 1
PROPOSAL_DEFAULT_LIMIT = 1
PROPOSAL_MAX_LIMIT = 1

REVIEW_ONLY_VERDICTS = ("REVIEW_READY", "PROMOTE_TO_CODEX", "KEEP_CANDIDATE")
EXCLUDED_VERDICTS = ("RUNS_BUT_WEAK", "DROP", "TOO_WEAK", "ERROR")

SPEC_REPAIR_REVIEW_RESULTS = (
    "APPROVE_FOR_PHASE2B", "NEEDS_REVISION", "REJECT", "REQUIRES_HUMAN_REVIEW",
)

# Spec Repair Lane에서 허용되는 출력 파일 전체 목록 (§4.5)
SPEC_REPAIR_ALLOWED_OUTPUTS = (
    "spec_repair_proposal.json",
    "spec_repair_proposal.md",
    "spec_repair_review.json",
    "spec_repair_review.md",
    "frozen_hash_before.json",
    "frozen_hash_after.json",
    "frozen_hash_check.json",
    "phase2a_dashboard_summary.json",
)

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- CLI 정책 (§4.1, §5.1)

def resolve_queue_policy(
    lane: str | None, execute: bool, proposal_only: bool, limit: int | None
) -> tuple[str | None, int, str]:
    """(error, effective_limit, operation) 반환. operation은 dry-run|execute|proposal."""
    if execute and proposal_only:
        return "--execute와 --proposal-only는 동시에 쓸 수 없습니다.", 0, "dry-run"
    if execute:
        if lane != "patch":
            return "--execute는 --lane patch에서만 허용됩니다 (spec-repair execute/apply 금지).", 0, "execute"
        eff = EXECUTE_DEFAULT_LIMIT if limit is None else limit
        if eff < 1 or eff > EXECUTE_MAX_LIMIT:
            return f"--execute limit은 최대 {EXECUTE_MAX_LIMIT}입니다 (무제한 처리 금지).", 0, "execute"
        return None, eff, "execute"
    if proposal_only:
        if lane != "spec-repair":
            return "--proposal-only는 --lane spec-repair에서만 허용됩니다.", 0, "proposal"
        eff = PROPOSAL_DEFAULT_LIMIT if limit is None else limit
        if eff < 1 or eff > PROPOSAL_MAX_LIMIT:
            return f"--proposal-only limit은 최대 {PROPOSAL_MAX_LIMIT}입니다.", 0, "proposal"
        return None, eff, "proposal"
    eff = DRY_RUN_DEFAULT_LIMIT if limit is None else limit
    if eff < 1 or eff > DRY_RUN_MAX_LIMIT:
        return f"dry-run limit은 1~{DRY_RUN_MAX_LIMIT}입니다 (무제한 queue 처리 금지).", 0, "dry-run"
    return None, eff, "dry-run"


def _spec_reason(failures: list[dict]) -> str:
    types = {f.get("type") for f in failures}
    bits: list[str] = []
    if "GOLDEN_SCHEMA_MISMATCH" in types or "RUNNER_OUTPUT_EXTRA_FIELD" in types:
        bits.append("golden schema mismatch")
    if "STATE_INVARIANT_NOT_EXPOSED" in types:
        bits.append("invariant DSL issue")
    if not bits:
        bits.append("spec/contract 정합성 문제")
    return " and ".join(bits) + " require spec repair"


# ---------------------------------------------------------------- Lane 분류 (§3)

def decide_lane_for_run(
    verdict: str | None,
    failures: list[dict],
    base: dict,
    artifact_class: str | None = None,
    status: str | None = None,
) -> dict:
    """run 1건의 recommended lane과 근거를 결정한다."""
    risk_level = max(
        (base.get("hardcode_risk") or "low", base.get("oracle_risk") or "low"),
        key=lambda x: _RISK_ORDER.get(x, 1),
    )

    def _entry(lane, can_continue, can_patch, reason, blocking=""):
        return {
            "recommended_lane": lane, "can_continue": can_continue, "can_patch": can_patch,
            "reason": reason, "blocking_reason": blocking, "risk_level": risk_level,
        }

    if (status or "").lower() in ("error", "failed", "running", "pending"):
        return _entry(LANE_EXCLUDED, False, False, "run이 완료 상태가 아님",
                      f"status={status}는 continuation 대상이 아님")
    if verdict in REVIEW_ONLY_VERDICTS:
        return _entry(LANE_REVIEW_ONLY, False, False,
                      "사용자 검수 대상 — continuation queue 대상이 아님")
    if verdict in EXCLUDED_VERDICTS:
        return _entry(LANE_EXCLUDED, False, False, "continuation 가치 낮음",
                      f"{verdict} is not eligible for continuation")
    if artifact_class == "VIEWER_ONLY":
        return _entry(LANE_EXCLUDED, False, False, "viewer-only 산출물",
                      "viewer-only 산출물은 continuation 대상이 아님")
    if not base.get("ok"):
        problems = "; ".join(base.get("problems") or ["continuation base 정보 없음"])
        return _entry(LANE_EXCLUDED, False, False, "continuation 필수 조건 미충족", problems)
    next_goal = (base.get("base_json") or {}).get("next_goal") or ""
    if not next_goal.strip():
        return _entry(LANE_EXCLUDED, False, False, "next_goal 없음",
                      "next_goal이 없어 continuation 목표가 불명확")

    if verdict == "SPEC_REPAIR_REQUIRED":
        return _entry(LANE_SPEC_REPAIR, True, False, _spec_reason(failures))

    if verdict == "NEEDS_MORE_GEMMA_LOOP":
        assessments = [(f, *assess_failure_patch_safety(f)) for f in failures]
        spec = [f for f, kind, _ in assessments if kind == "spec"]
        unclear = [f for f, kind, _ in assessments if kind == "unclear"]
        if spec:
            return _entry(LANE_SPEC_REPAIR, True, False, _spec_reason(spec))
        if unclear:
            kinds = ", ".join(sorted({f.get("type") or "?" for f in unclear}))
            return _entry(LANE_EXCLUDED, False, False, "failure type 불명확",
                          f"patch-safe 범위 밖 failure: {kinds}")
        if assessments:
            kinds = ", ".join(sorted({f.get("type") or "?" for f, _, _ in assessments}))
            reason = f"patch-safe failure만 존재: {kinds}"
        else:
            reason = f"failure 미분류 — delta loop가 재분류 (next_goal: {next_goal[:80]})"
        return _entry(LANE_PATCH, True, True, reason)

    return _entry(LANE_EXCLUDED, False, False, "verdict 불명확",
                  f"verdict={verdict or 'null'}은 continuation 대상이 아님")


# ---------------------------------------------------------------- Run Discovery (§4.2)

def discover_candidates(conn, runs_root: str | Path) -> tuple[list[dict], dict]:
    """DB 우선 + filesystem fallback으로 continuation 후보와 continuation 이력을 수집한다.

    반환: (candidates, history) — history는 base_run_id → continuation run 목록.
    새 DB 테이블/스키마를 만들지 않고 기존 product_runs 조회 구조만 재사용한다.
    """
    runs_root = Path(runs_root)
    candidates: list[dict] = []
    history: dict[int, list[dict]] = {}
    seen_dirs: set[str] = set()
    seen_ids: set[int] = set()

    def _dir_key(d: Path) -> str:
        try:
            return str(d.resolve())
        except OSError:
            return str(d)

    if conn is not None:
        for row in list_product_runs(conn, limit=500):
            ws = row.get("workspace_dir")
            run_dir = Path(ws).parent if ws else None
            if run_dir is not None:
                seen_dirs.add(_dir_key(run_dir))
            summary = _load_json(run_dir / "continuation_run_summary.json") if run_dir else None
            if summary is not None:
                base_id = summary.get("base_run_id")
                if base_id is not None:
                    history.setdefault(base_id, []).append(
                        {"run_dir": run_dir, "summary": summary, "run_id": row["id"]})
                continue
            if row["id"] in seen_ids:  # run_id 기준 dedupe
                continue
            seen_ids.add(row["id"])
            candidates.append({
                "run_id": row["id"], "challenge_id": row.get("challenge_id"),
                "verdict": row.get("verdict"), "status": row.get("status"),
                "run_dir": run_dir, "source": "db",
                "live_validation": bool(run_dir and (run_dir / "live_validation_summary.json").is_file()),
            })

    # filesystem fallback: DB에서 찾지 못한 run만 (§4.2-4,5)
    if runs_root.is_dir():
        for d in sorted(runs_root.iterdir()):
            if not d.is_dir() or _dir_key(d) in seen_dirs:
                continue
            cont = _load_json(d / "continuation_run_summary.json")
            if cont is not None:
                base_id = cont.get("base_run_id")
                if base_id is not None:
                    history.setdefault(base_id, []).append(
                        {"run_dir": d, "summary": cont, "run_id": None})
                seen_dirs.add(_dir_key(d))
                continue
            if (d / "harness_summary.json").is_file():
                dsum = _load_json(d / "dashboard_summary.json") or {}
                candidates.append({
                    "run_id": None, "challenge_id": dsum.get("challenge_id"),
                    "verdict": dsum.get("verdict"), "status": "done",
                    "run_dir": d, "source": "filesystem",
                    "live_validation": (d / "live_validation_summary.json").is_file(),
                })
                seen_dirs.add(_dir_key(d))
    return candidates, history


def classify_candidate(cand: dict, history: dict) -> dict:
    """후보 run 1건을 queue entry로 분류한다. continuation 이력이 있으면 최신 verdict를 쓴다."""
    run_dir = cand.get("run_dir")
    hist = sorted(history.get(cand.get("run_id")) or [], key=lambda h: str(h["run_dir"]))
    latest = hist[-1] if hist else None
    current_verdict = ((latest or {}).get("summary") or {}).get("verdict") or cand.get("verdict")

    failures: list[dict] = []
    if latest is not None:
        fc = _load_json(latest["run_dir"] / "failure_classification.json") or {}
        failures = [f for f in (fc.get("failure_types") or []) if isinstance(f, dict)]

    if run_dir is not None and Path(run_dir).is_dir():
        base = load_continuation_base(Path(run_dir))
    else:
        base = {"ok": False, "problems": ["run_dir 없음"], "base_json": None,
                "dashboard": {}, "hardcode_risk": "low", "oracle_risk": "low"}
    artifact_class = (base.get("dashboard") or {}).get("artifact_class")
    decision = decide_lane_for_run(current_verdict, failures, base,
                                   artifact_class=artifact_class, status=cand.get("status"))
    return {
        "run_id": cand.get("run_id"),
        "challenge_id": cand.get("challenge_id"),
        "current_verdict": current_verdict,
        **decision,
        "priority": None,
        "failure_types": [f.get("type") for f in failures],
        "has_continuation_history": bool(hist),
        "live_validation": bool(cand.get("live_validation")),
        "run_dir": str(run_dir) if run_dir else None,
        "latest_continuation_dir": str(latest["run_dir"]) if latest else None,
        "source": cand.get("source"),
    }


def sort_and_prioritize(entries: list[dict]) -> list[dict]:
    """queue 대상(PATCH/SPEC)을 §4.2 우선순위로 정렬하고 priority를 매긴다."""
    def _key(e):
        return (
            0 if (e["has_continuation_history"] or e["live_validation"]) else 1,
            0 if e["current_verdict"] in ("SPEC_REPAIR_REQUIRED", "NEEDS_MORE_GEMMA_LOOP") else 1,
            -(e["run_id"] or 0),
            _RISK_ORDER.get(e["risk_level"], 1),
            0 if e["failure_types"] else 1,
        )

    queued = sorted([e for e in entries if e["recommended_lane"] in (LANE_PATCH, LANE_SPEC_REPAIR)], key=_key)
    others = sorted([e for e in entries if e["recommended_lane"] not in (LANE_PATCH, LANE_SPEC_REPAIR)],
                    key=lambda e: -(e["run_id"] or 0))
    for i, e in enumerate(queued):
        e["priority"] = i + 1
    return queued + others


# ---------------------------------------------------------------- Queue 출력 (§5.2)

def write_queue_files(entries: list[dict], out_dir: str | Path, meta: dict) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": utcnow_iso(), **meta, "entries": entries}
    json_path = out_dir / "continuation_queue.json"
    json_path.write_text(_dump(payload), encoding="utf-8")

    lines = ["# Continuation Queue (Phase 2A)", "",
             f"생성: {payload['generated_at']} · lane filter: {meta.get('lane_filter') or '전체'}"
             f" · operation: {meta.get('operation')} · limit: {meta.get('limit')}", "",
             "| priority | run | challenge | verdict | lane | can_patch | risk | reason |",
             "|---|---|---|---|---|---|---|---|"]
    for e in entries:
        lines.append(
            f"| {e['priority'] if e['priority'] is not None else '-'} | {e['run_id'] or '-'} "
            f"| {e['challenge_id'] or '-'} | {e['current_verdict'] or '-'} | {e['recommended_lane']} "
            f"| {e['can_patch']} | {e['risk_level']} | {(e['reason'] or '')[:80]} |")
    if not entries:
        lines.append("| - | - | - | - | - | - | - | 대상 없음 |")
    md_path = out_dir / "continuation_queue.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------- Spec Repair Proposal/Review 렌더링 (§7)

def _proposal_md(p: dict) -> str:
    return "\n".join([
        "# Spec Repair Proposal (Phase 2A — proposal only)", "",
        f"- base_run_id: {p['base_run_id']} / challenge_id: {p['challenge_id']}",
        f"- repair_type: {p['repair_type']}"
        + (f" (+ {', '.join(p['secondary_repair_types'])})" if p.get("secondary_repair_types") else ""),
        f"- risk_level: {p['risk_level']} / requires_human_review: {p['requires_human_review']}",
        f"- apply_allowed_in_phase2a: {p['apply_allowed_in_phase2a']}", "",
        "## Problem", p["problem"], "",
        "## Proposed Change", p["proposed_change"], "",
        "## Why spec problem", p["why_this_is_spec_problem"], "",
        "## Why not code patch", p["why_this_is_not_code_patch"], "",
    ]) + "\n"


def _review_md(r: dict) -> str:
    lines = ["# Spec Repair Review (Phase 2A — apply 금지)", "",
             f"- result: {r['result']}",
             f"- apply_performed: {r['apply_performed']}", "", "## Checks"]
    for c in r["checks"]:
        lines.append(f"- [{'OK' if c['ok'] else 'WARN'}] {c['item']} — {c['note']}")
    lines += ["", r["note"]]
    return "\n".join(lines) + "\n"


def run_spec_repair_readonly(entry: dict) -> dict:
    """SPEC_REPAIR lane 1건을 read-only로 처리한다 (§7).

    patch writer/apply_patch/edit helper를 호출하지 않으며, §4.5 허용 출력 파일만 쓴다.
    """
    target_dir = Path(entry["run_dir"])
    source_dir = Path(entry["latest_continuation_dir"]) if entry.get("latest_continuation_dir") else target_dir
    workspace = target_dir / "workspace"
    if not workspace.is_dir():
        workspace = target_dir / "final_artifact"

    before = compute_frozen_hashes(workspace, target_dir)

    fc = _load_json(source_dir / "failure_classification.json") or {}
    failures = [f for f in (fc.get("failure_types") or []) if isinstance(f, dict)]
    proposal = build_spec_repair_proposal(
        entry.get("run_id"), entry.get("challenge_id"), failures, entry.get("risk_level") or "medium")
    review = build_spec_repair_review(proposal)

    def _write_allowed(name: str, text: str) -> None:
        if name not in SPEC_REPAIR_ALLOWED_OUTPUTS:
            raise ValueError(f"Spec Repair Lane 허용 출력이 아님: {name}")
        (target_dir / name).write_text(text, encoding="utf-8")

    _write_allowed("spec_repair_proposal.json", _dump(proposal))
    _write_allowed("spec_repair_proposal.md", _proposal_md(proposal))
    _write_allowed("spec_repair_review.json", _dump(review))
    _write_allowed("spec_repair_review.md", _review_md(review))

    after = compute_frozen_hashes(workspace, target_dir)
    check = write_frozen_hash_guard(target_dir, before, after)

    dashboard = {
        "lane": LANE_SPEC_REPAIR,
        "recommended_lane": LANE_SPEC_REPAIR,
        "lane_reason": entry.get("reason") or _spec_reason(failures),
        "lane_status": "제안서 생성됨, 적용은 보류",
        "base_run_id": entry.get("run_id"),
        "challenge_id": entry.get("challenge_id"),
        "current_verdict": entry.get("current_verdict"),
        "failure_types": [f.get("type") for f in failures],
        "risk_level": entry.get("risk_level"),
        "blocking_reason": entry.get("blocking_reason") or "",
        "proposal_generated": True,
        "review_generated": True,
        "review_result": review["result"],
        "apply_performed": False,
        "frozen_hash_status": check["status"],
    }
    _write_allowed("phase2a_dashboard_summary.json", _dump(dashboard))

    return {
        "run_id": entry.get("run_id"),
        "challenge_id": entry.get("challenge_id"),
        "target_dir": str(target_dir),
        "proposal_path": str(target_dir / "spec_repair_proposal.json"),
        "review_path": str(target_dir / "spec_repair_review.json"),
        "review_result": review["result"],
        "apply_performed": False,
        "frozen_hash_status": check["status"],
    }


# ---------------------------------------------------------------- Patch Lane 실행 (§6)

def execute_patch_lane(entries: list[dict], conn, mode: str, output_dir, limit: int,
                       **continuation_kwargs) -> dict:
    """PATCH_CONTINUATION entry를 최대 limit(=1)건 실행한다. 대상 없으면 NO_PATCH_ELIGIBLE."""
    eligible = [e for e in entries if e["recommended_lane"] == LANE_PATCH][:limit]
    if not eligible:
        return {"status": "NO_PATCH_ELIGIBLE", "executed": [],
                "note": "patch lane에 안전하게 실행할 대상이 없음 — 아무 파일도 수정하지 않음"}
    executed = []
    for e in eligible:
        if conn is not None and e.get("run_id"):
            res = run_continuation(base_run_id=e["run_id"], mode=mode,
                                   output_dir=output_dir, db_conn=conn, **continuation_kwargs)
        else:
            res = run_continuation(base_run_dir=e["run_dir"], mode=mode,
                                   output_dir=output_dir, db_conn=None, **continuation_kwargs)
        executed.append({
            "run_id": e.get("run_id"), "challenge_id": e.get("challenge_id"),
            "continuation_run_dir": res.get("continuation_run_dir"),
            "patch_result": res.get("patch_result"),
            "verdict": res.get("verdict"),
            "lane": res.get("lane"),
            "promoted_to_green_base": res.get("promoted_to_green_base"),
            "frozen_hash_status": res.get("frozen_hash_status"),
            "error": res.get("error"), "status": res.get("status"),
        })
    return {"status": "EXECUTED", "executed": executed}


# ---------------------------------------------------------------- 메인 엔트리

def run_continuation_queue(
    db_path: str | Path | None = "challenge.db",
    output_dir: str | Path = "runs",
    lane: str | None = None,
    execute: bool = False,
    proposal_only: bool = False,
    limit: int | None = None,
    mode: str = "mock",
    db_conn=None,
    **continuation_kwargs,
) -> dict:
    """continuation queue를 만들고 (기본 dry-run) lane별 작업을 수행한다 (§5)."""
    err, eff_limit, operation = resolve_queue_policy(lane, execute, proposal_only, limit)
    if err:
        return {"ok": False, "error": err, "operation": operation}

    own_conn = False
    conn = db_conn
    if conn is None and db_path is not None and Path(db_path).exists():
        conn = open_factory_db(db_path)
        own_conn = True
    try:
        candidates, history = discover_candidates(conn, output_dir)
        entries = sort_and_prioritize([classify_candidate(c, history) for c in candidates])

        lane_map = {"patch": LANE_PATCH, "spec-repair": LANE_SPEC_REPAIR}
        counts: dict[str, int] = {}
        for e in entries:
            counts[e["recommended_lane"]] = counts.get(e["recommended_lane"], 0) + 1
        if lane in lane_map:
            shown = [e for e in entries if e["recommended_lane"] == lane_map[lane]][:eff_limit]
        else:
            shown = entries[:eff_limit]

        qjson, qmd = write_queue_files(shown, output_dir, {
            "lane_filter": lane, "operation": operation, "limit": eff_limit,
            "dry_run": operation == "dry-run", "lane_counts": counts,
        })
        result = {
            "ok": True, "operation": operation, "entries": shown, "lane_counts": counts,
            "queue_json": str(qjson), "queue_md": str(qmd),
        }
        if operation == "execute":
            result.update(execute_patch_lane(shown, conn, mode, output_dir, eff_limit,
                                             **continuation_kwargs))
        elif operation == "proposal":
            targets = [e for e in shown if e["recommended_lane"] == LANE_SPEC_REPAIR][:eff_limit]
            if not targets:
                result.update({"status": "NO_SPEC_REPAIR_ELIGIBLE", "proposals": []})
            else:
                result.update({"status": "PROPOSAL_ONLY",
                               "proposals": [run_spec_repair_readonly(e) for e in targets]})
        return result
    finally:
        if own_conn and conn is not None:
            conn.close()
