# 대시보드 read model — challenge/product 조회, phase 요약 로더, 화이트리스트 기반 안전 파일 접근.
# HTML 렌더링과 HTTP는 challenge_dashboard.py가, 판정 정본은 factory_* 모듈이 담당한다.
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from repo_idea_miner.challenge_db import is_paused, queue_counts
from repo_idea_miner.challenge_schemas import LABEL_PRIORITY
from repo_idea_miner.factory_schemas import PRODUCT_OWNER_DECISIONS
from repo_idea_miner.redaction import redact_text

# 상세 화면에서 artifact_dir 내 이 파일들만 읽는다 (임의 경로 접근 금지)
DETAIL_FILES = {
    "owner_brief": "owner_brief.md",
    "screen_story": "screen_story.md",
    "challenge_card": "challenge_card.md",
    "implementation_prompt": "implementation_prompt.md",
    "validation_report": "validation_report.json",
}

# Report Preview 탭 화이트리스트 (§23). 사용자는 key만 고르므로 임의 경로 접근이 불가능하다.
# ("final"=final_artifact_dir, "run"=run 디렉터리) 순서가 곧 탭 순서다.
PRODUCT_REPORT_TABS = [
    ("readme", ("final", "README.md", "README.md")),
    ("run_instructions", ("final", "run_instructions.md", "run_instructions.md")),
    ("product_verdict", ("final", "product_verdict.md", "product_verdict.md")),
    ("qa_report", ("final", "reports/qa_report.md", "qa_report.md")),
    ("contract_report", ("final", "reports/contract_report.md", "contract_report.md")),
    ("syntax_report", ("final", "reports/syntax_report.md", "syntax_report.md")),
    ("smoke_report", ("final", "reports/smoke_report.md", "smoke_report.md")),
    ("manifest", ("final", "manifest.json", "manifest.json")),
    ("contract", ("final", "contract.json", "contract.json")),
    ("events", ("run", "events.jsonl", "events.jsonl")),
    ("debug_history", ("run", "debug_history.jsonl", "debug_history.jsonl")),
    ("product_summary", ("final", "product_summary.json", "product_summary.json")),
    ("gate_summary", ("final", "gate_summary.json", "gate_summary.json")),
    ("qa_summary", ("final", "qa_summary.json", "qa_summary.json")),
    # Phase 1.6 Core Harness 산출물 (§11.10 상세)
    ("dashboard_summary", ("final", "dashboard_summary.json", "dashboard_summary.json")),
    ("harness_summary", ("run", "harness_summary.json", "harness_summary.json")),
    ("core_system_summary", ("run", "core_system_summary.json", "core_system_summary.json")),
    ("runner_summary", ("final", "runner_summary.json", "runner_summary.json")),
    ("scenario_replay_summary", ("final", "scenario_replay_summary.json", "scenario_replay_summary.json")),
    ("golden_diff_summary", ("final", "golden_diff_summary.json", "golden_diff_summary.json")),
    ("determinism_summary", ("final", "determinism_summary.json", "determinism_summary.json")),
    ("anti_hardcode_summary", ("final", "anti_hardcode_summary.json", "anti_hardcode_summary.json")),
    ("green_base", ("run", "green_base.json", "green_base.json")),
    # Phase 2A 산출물 (상세 페이지 전용)
    ("phase2a_dashboard_summary", ("run", "phase2a_dashboard_summary.json", "phase2a_dashboard_summary.json")),
    ("continuation_run_summary", ("run", "continuation_run_summary.json", "continuation_run_summary.json")),
    ("spec_repair_proposal", ("run", "spec_repair_proposal.md", "spec_repair_proposal.md")),
    ("spec_repair_review", ("run", "spec_repair_review.md", "spec_repair_review.md")),
    ("frozen_hash_check", ("run", "frozen_hash_check.json", "frozen_hash_check.json")),
    # Phase 2B-1 산출물 (상세 페이지 전용)
    ("spec_repair_apply_plan", ("run", "spec_repair_apply_plan.md", "spec_repair_apply_plan.md")),
    ("spec_repair_apply_report", ("run", "spec_repair_apply_report.md", "spec_repair_apply_report.md")),
    ("spec_repair_diff_summary", ("run", "spec_repair_diff_summary.json", "spec_repair_diff_summary.json")),
    ("gate_rerun_after_spec_repair", ("run", "gate_rerun_after_spec_repair.json", "gate_rerun_after_spec_repair.json")),
    ("phase2b1_dashboard_summary", ("run", "phase2b1_dashboard_summary.json", "phase2b1_dashboard_summary.json")),
    # Phase 2B-1b 산출물 (상세 페이지 전용)
    ("anti_hardcode_patch_plan", ("run", "anti_hardcode_patch_plan.md", "anti_hardcode_patch_plan.md")),
    ("anti_hardcode_patch_report", ("run", "anti_hardcode_patch_report.md", "anti_hardcode_patch_report.md")),
    ("anti_hardcode_diff_summary", ("run", "anti_hardcode_diff_summary.json", "anti_hardcode_diff_summary.json")),
    ("gate_rerun_after_anti_hardcode_patch", ("run", "gate_rerun_after_anti_hardcode_patch.json", "gate_rerun_after_anti_hardcode_patch.json")),
    ("summary_repair_rule_update", ("run", "summary_repair_rule_update.md", "summary_repair_rule_update.md")),
    ("phase2b1b_dashboard_summary", ("run", "phase2b1b_dashboard_summary.json", "phase2b1b_dashboard_summary.json")),
    # Phase 2C-0 검수 패키지 (review/phase2c0/ — 상세 페이지 전용)
    ("review_package", ("run", "review/phase2c0/review_package.md", "검수 패키지")),
    ("product_fitness_report", ("run", "review/phase2c0/product_fitness_report.md", "제품성 리포트")),
    ("artifact_smoke_review", ("run", "review/phase2c0/artifact_smoke_review.md", "스모크 리뷰")),
    ("human_review_checklist", ("run", "review/phase2c0/human_review_checklist.md", "검수 체크리스트")),
    ("sixty_second_review_script", ("run", "review/phase2c0/sixty_second_review_script.md", "60초 검수")),
    ("demo_manifest", ("run", "review/phase2c0/demo_manifest.json", "demo_manifest")),
    ("phase2c0_dashboard_summary", ("run", "review/phase2c0/phase2c0_dashboard_summary.json", "phase2c0_dashboard_summary")),
    ("review_no_code_hash_check", ("run", "review/phase2c0/review_no_code_hash_check.json", "no-code-change 검사")),
    # Phase 2C-1 viewer polish (review/phase2c1/ — 상세 페이지 전용)
    ("phase2c1_polish_report", ("run", "review/phase2c1/phase2c1_polish_report.md", "viewer polish 리포트")),
    ("phase2c1_polish_plan", ("run", "review/phase2c1/phase2c1_polish_plan.md", "viewer polish 계획")),
    ("smoke_review_after_polish", ("run", "review/phase2c1/artifact_smoke_review_after_polish.md", "polish 후 스모크")),
    ("fitness_after_polish", ("run", "review/phase2c1/product_fitness_report_after_polish.md", "polish 후 제품성")),
    ("phase2c1_diff_summary", ("run", "review/phase2c1/phase2c1_diff_summary.json", "polish diff")),
    ("phase2c1_hash_check", ("run", "review/phase2c1/phase2c1_hash_check.json", "polish hash 검사")),
    ("phase2c1_dashboard_summary", ("run", "review/phase2c1/phase2c1_dashboard_summary.json", "phase2c1_dashboard_summary")),
    # Phase 2C-2 node draft editor (review/phase2c2/ — 상세 페이지 전용)
    ("phase2c2_editor_report", ("run", "review/phase2c2/phase2c2_editor_report.md", "editor 리포트")),
    ("phase2c2_editor_plan", ("run", "review/phase2c2/phase2c2_editor_plan.md", "editor 계획")),
    ("editor_smoke_review", ("run", "review/phase2c2/editor_smoke_review.json", "editor 스모크")),
    ("viewer_js_syntax_check", ("run", "review/phase2c2/viewer_js_syntax_check.json", "JS 구문 검사")),
    ("viewer_static_dom_check", ("run", "review/phase2c2/viewer_static_dom_check.json", "static DOM 검사")),
    ("viewer_handler_binding_check", ("run", "review/phase2c2/viewer_handler_binding_check.json", "handler binding 검사")),
    ("draft_schema_compatibility", ("run", "review/phase2c2/draft_schema_compatibility.json", "draft 호환성")),
    ("draft_roundtrip_check", ("run", "review/phase2c2/draft_roundtrip_check.json", "draft roundtrip")),
    ("viewer_smoke_after_editor", ("run", "review/phase2c2/viewer_smoke_after_editor.json", "editor 후 스모크")),
    ("fitness_after_editor", ("run", "review/phase2c2/product_fitness_report_after_editor.md", "editor 후 제품성")),
    ("phase2c2_hash_check", ("run", "review/phase2c2/phase2c2_hash_check.json", "editor hash 검사")),
    ("phase2c2_dashboard_summary", ("run", "review/phase2c2/phase2c2_dashboard_summary.json", "phase2c2_dashboard_summary")),
    # Phase 2C-3 runner-backed draft execution (review/phase2c3/ — 상세 페이지 전용)
    ("phase2c3_execution_report", ("run", "review/phase2c3/phase2c3_execution_report.md", "실행 리포트")),
    ("phase2c3_execution_plan", ("run", "review/phase2c3/phase2c3_execution_plan.md", "실행 계획")),
    ("execution_smoke", ("run", "review/phase2c3/execution_smoke.md", "실행 스모크")),
    ("adapter_check", ("run", "review/phase2c3/adapter_check.json", "어댑터 검사")),
    ("viewer_smoke_after_execution", ("run", "review/phase2c3/viewer_smoke_after_execution.json", "실행 후 스모크")),
    ("fitness_after_execution", ("run", "review/phase2c3/product_fitness_report_after_execution.md", "실행 후 제품성")),
    ("phase2c3_hash_check", ("run", "review/phase2c3/phase2c3_hash_check.json", "실행 hash 검사")),
    ("phase2c3_dashboard_summary", ("run", "review/phase2c3/phase2c3_dashboard_summary.json", "phase2c3_dashboard_summary")),
    # generic runner-backed draft execution (review/draft_execution/ — 상세 페이지 전용)
    ("draft_execution_report", ("run", "review/draft_execution/draft_execution_report.json", "draft 실행 리포트")),
    ("draft_execution_contract", ("run", "review/draft_execution/execution_contract.json", "실행 계약")),
    ("draft_execution_result", ("run", "review/draft_execution/execution_result.json", "실행 결과")),
    ("draft_execution_manifest", ("run", "review/draft_execution/side_effect_manifest.json", "side effect manifest")),
    ("draft_execution_evidence", ("run", "review/draft_execution/execution_evidence.json", "실행 evidence")),
    # generic viewer polish (review/viewer_polish/ — 상세 페이지 전용)
    ("viewer_polish_report", ("run", "review/viewer_polish/viewer_polish_report.json", "viewer polish 리포트")),
    ("viewer_polish_contract", ("run", "review/viewer_polish/viewer_contract.json", "viewer 계약")),
    ("viewer_polish_discovery", ("run", "review/viewer_polish/viewer_discovery.json", "replay discovery")),
    ("viewer_polish_evidence", ("run", "review/viewer_polish/viewer_evidence.json", "viewer evidence")),
    # Phase 2D-0 autopilot (review/phase2d0/ — 상세 페이지 전용)
    ("product_stage_label", ("run", "review/phase2d0/product_stage_label.md", "autopilot stage")),
    ("product_gap_classification", ("run", "review/phase2d0/product_gap_classification.md", "gap 분류")),
    ("recommended_next_lane", ("run", "review/phase2d0/recommended_next_lane.md", "next lane")),
    ("auto_order", ("run", "review/phase2d0/auto_order.md", "auto order")),
    ("auto_order_quality_report", ("run", "review/phase2d0/auto_order_quality_report.json", "auto order 품질")),
    ("scope_guard", ("run", "review/phase2d0/scope_guard.json", "scope guard")),
    ("repair_blueprint", ("run", "review/phase2d0/repair_blueprint.json", "repair blueprint")),
    ("expected_patch_plan", ("run", "review/phase2d0/expected_patch_plan.md", "expected patch plan")),
    ("hard_blocker_result", ("run", "review/phase2d0/hard_blocker_result.json", "hard blockers")),
    ("user_facing_quality_evidence", ("run", "review/phase2d0/user_facing_quality_evidence.json", "user-facing 품질")),
    ("mock_loop_order_following_report", ("run", "review/phase2d0/mock_loop_order_following_report.json", "mock loop 검증")),
    ("product_loop_iteration_summary", ("run", "review/phase2d0/product_loop_iteration_summary.md", "loop 요약")),
    ("product_loop_dashboard_summary", ("run", "review/phase2d0/product_loop_dashboard_summary.json", "product_loop_dashboard_summary")),
]
PRODUCT_REPORT_TABS_MAP = dict(PRODUCT_REPORT_TABS)

# 허용된 Source Preview 범위 (§22). final_artifact 안에서만, 이 루트/파일만 읽는다.
SOURCE_PREVIEW_FILES = {
    "README.md", "run_instructions.md", "manifest.json", "contract.json",
    "core_contract.json", "state_contract.json", "action_contract.json", "runner_contract.json",
}
SOURCE_PREVIEW_PREFIXES = ("src/", "reports/", "fixtures/", "golden/", "replay/", "product/", "validators/")

# preview 길이 제한 (§30 large file truncate)
PREVIEW_MAX_BYTES = 60000


# ---------------------------------------------------------------- Challenge read model

_ORDER_SQL = (
    "ORDER BY CASE c.final_label "
    + " ".join(f"WHEN '{lab}' THEN {pri}" for lab, pri in LABEL_PRIORITY.items())
    + " ELSE 99 END, c.owner_clarity_score DESC, c.score_total DESC, c.created_at DESC"
)


def query_challenges(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    sql = (
        "SELECT c.*, COALESCE(r.owner_status, 'unseen') AS owner_status, r.note AS owner_note, "
        "repos.language AS language "
        "FROM challenges c "
        "LEFT JOIN owner_reviews r ON r.challenge_id = c.id "
        "LEFT JOIN repos ON repos.repo_url = c.repo_url WHERE 1=1"
    )
    args: list = []
    if filters.get("final_label"):
        sql += " AND c.final_label = ?"
        args.append(filters["final_label"])
    if filters.get("owner_status"):
        sql += " AND COALESCE(r.owner_status, 'unseen') = ?"
        args.append(filters["owner_status"])
    if filters.get("language"):
        sql += " AND repos.language = ?"
        args.append(filters["language"])
    if filters.get("created_date"):
        sql += " AND c.created_at LIKE ?"
        args.append(filters["created_date"] + "%")
    if filters.get("score_min"):
        sql += " AND c.score_total >= ?"
        args.append(int(filters["score_min"]))
    if filters.get("score_max"):
        sql += " AND c.score_total <= ?"
        args.append(int(filters["score_max"]))
    sql += f" {_ORDER_SQL} LIMIT 200"
    return [dict(r) for r in conn.execute(sql, args)]


def today_summary(conn: sqlite3.Connection) -> dict:
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    since = local_midnight.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    labels = {
        row["final_label"]: row["n"]
        for row in conn.execute(
            "SELECT final_label, COUNT(*) AS n FROM challenges WHERE created_at >= ? GROUP BY final_label",
            (since,),
        )
    }
    total = conn.execute("SELECT COUNT(*) FROM challenges WHERE created_at >= ?", (since,)).fetchone()[0]
    errors = conn.execute(
        "SELECT COUNT(*) FROM events WHERE timestamp >= ? AND event_type IN ('repo_error','llm_error','seed_error','validation_error')",
        (since,),
    ).fetchone()[0]
    counts = queue_counts(conn)
    keys = [dict(r) for r in conn.execute("SELECT * FROM api_keys ORDER BY key_id")]
    return {
        "today_total": total,
        "labels": labels,
        "errors": errors,
        "queue": counts,
        "keys": keys,
        "paused": is_paused(conn),
    }


def get_challenge_detail(conn: sqlite3.Connection, challenge_id: int) -> dict | None:
    """challenge + owner review 상세 1건 (없으면 None)."""
    row = conn.execute(
        "SELECT c.*, COALESCE(r.owner_status,'unseen') AS owner_status, r.note AS owner_note "
        "FROM challenges c LEFT JOIN owner_reviews r ON r.challenge_id=c.id WHERE c.id=?",
        (challenge_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def get_challenge_brief(conn: sqlite3.Connection, challenge_id: int) -> dict | None:
    """product 상세 화면에서 원본 challenge 링크용 최소 정보."""
    row = conn.execute(
        "SELECT id, challenge_title, repo_url FROM challenges WHERE id=?", (challenge_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def challenge_detail_content(artifact_dir: Path, tab: str, secrets: list[str]) -> str:
    """DETAIL_FILES 화이트리스트 탭 내용을 읽는다 (validation_report는 pretty JSON)."""
    target = artifact_dir / DETAIL_FILES[tab]
    if not (artifact_dir.is_dir() and target.is_file()):
        return "(artifact 파일 없음)"
    text = target.read_text(encoding="utf-8", errors="replace")
    if tab == "validation_report":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    return redact_text(text, secrets)


def challenge_copy_text(artifact_dir: Path, tab: str, secrets: list[str]) -> str | None:
    """복사 버튼용 원문 (파일 없으면 None)."""
    p = artifact_dir / DETAIL_FILES[tab]
    if not (artifact_dir.is_dir() and p.is_file()):
        return None
    return redact_text(p.read_text(encoding="utf-8", errors="replace"), secrets)


# ---------------------------------------------------------------- Product read model

def product_dirs(run: dict) -> tuple[Path | None, Path | None]:
    """DB run row → (final_artifact_dir, run 디렉터리). run 디렉터리는 workspace_dir의 부모."""
    final_dir = Path(run["final_artifact_dir"]) if run.get("final_artifact_dir") else None
    ws = run.get("workspace_dir")
    run_root = Path(ws).parent if ws else None
    return final_dir, run_root


def _load_summary_json(run_root: Path | None, rel: str) -> dict | None:
    if run_root is None:
        return None
    p = run_root / rel
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_phase2c0(run_root: Path | None) -> dict | None:
    """Phase 2C-0 제품성 추천 요약(review/phase2c0/)을 읽는다. 없으면 None(기존 표시 유지)."""
    return _load_summary_json(run_root, "review/phase2c0/phase2c0_dashboard_summary.json")


def load_phase2c1(run_root: Path | None) -> dict | None:
    """Phase 2C-1 viewer polish 요약(review/phase2c1/)을 읽는다. 없으면 None."""
    return _load_summary_json(run_root, "review/phase2c1/phase2c1_dashboard_summary.json")


def load_phase2c2(run_root: Path | None) -> dict | None:
    """Phase 2C-2 node draft editor 요약(review/phase2c2/)을 읽는다. 없으면 None."""
    return _load_summary_json(run_root, "review/phase2c2/phase2c2_dashboard_summary.json")


def load_phase2c3(run_root: Path | None) -> dict | None:
    """Phase 2C-3 runner-backed execution 요약(review/phase2c3/)을 읽는다. 없으면 None."""
    return _load_summary_json(run_root, "review/phase2c3/phase2c3_dashboard_summary.json")


def load_draft_execution(run_root: Path | None) -> dict | None:
    """generic runner-backed draft execution 요약(review/draft_execution/)을 읽는다. 없으면 None."""
    return _load_summary_json(run_root, "review/draft_execution/draft_execution_dashboard_summary.json")


def load_viewer_polish(run_root: Path | None) -> dict | None:
    """generic viewer polish 요약(review/viewer_polish/)을 읽는다. 없으면 None."""
    return _load_summary_json(run_root, "review/viewer_polish/viewer_polish_dashboard_summary.json")


def load_phase2d0(run_root: Path | None) -> dict | None:
    """Phase 2D-0 autopilot 요약(review/phase2d0/)을 읽는다. 없으면 None."""
    return _load_summary_json(run_root, "review/phase2d0/product_loop_dashboard_summary.json")


def load_phase2d0_details(run_root: Path | None) -> dict:
    """Phase 2D-0 상세 패널용 evidence/판정 산출물 묶음 (파일 없으면 빈 dict 값)."""
    rel = "review/phase2d0"
    return {
        "evidence": _load_summary_json(run_root, f"{rel}/artifact_evidence.json") or {},
        "quality": _load_summary_json(run_root, f"{rel}/user_facing_quality_evidence.json") or {},
        "hard": _load_summary_json(run_root, f"{rel}/hard_blocker_result.json") or {},
        "label": _load_summary_json(run_root, f"{rel}/product_stage_label.json") or {},
        "gap": _load_summary_json(run_root, f"{rel}/product_gap_classification.json") or {},
        "lane": _load_summary_json(run_root, f"{rel}/recommended_next_lane.json") or {},
        "quality_report": _load_summary_json(run_root, f"{rel}/auto_order_quality_report.json") or {},
        "mock": _load_summary_json(run_root, f"{rel}/mock_loop_order_following_report.json") or {},
    }


def load_phase2d1(run_root: Path | None) -> dict | None:
    """Phase 2D-1 closed loop 요약 — 가장 최근 loop_*의 dashboard summary. 없으면 None."""
    if run_root is None:
        return None
    root = run_root / "review/phase2d1"
    if not root.is_dir():
        return None
    for loop_dir in sorted((d for d in root.iterdir() if d.is_dir()), reverse=True):
        p = loop_dir / "phase2d1_dashboard_summary.json"
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                data["_loop_dir"] = str(loop_dir.relative_to(run_root).as_posix())
                return data
            except (OSError, json.JSONDecodeError):
                continue
    return None


def load_phase2d1_details(p2d1: dict | None, run_root: Path | None) -> dict:
    """Phase 2D-1 상세 패널용 loop_summary/lineage/hold packet 묶음."""
    loop_rel = (p2d1 or {}).get("_loop_dir") or ""
    base = run_root if (run_root and loop_rel) else None
    return {
        "summary": (_load_summary_json(base, f"{loop_rel}/loop_summary.json") or {}) if base else {},
        "lineage": (_load_summary_json(base, f"{loop_rel}/lineage.json") or {}) if base else {},
        "hold": (_load_summary_json(base, f"{loop_rel}/hold_for_human_packet.json") or {}) if base else {},
    }


def match_product_filters(run: dict, rev: dict | None, filters: dict) -> bool:
    verdict = filters.get("verdict")
    status = filters.get("status")
    review = (filters.get("review") or "").lower()
    if verdict and (run.get("verdict") or "") != verdict:
        return False
    if status and (run.get("status") or "") != status:
        return False
    if review == "unreviewed" and rev is not None:
        return False
    if review == "reviewed" and rev is None:
        return False
    if review in PRODUCT_OWNER_DECISIONS and (rev or {}).get("action") != review:
        return False
    return True


# ---------------------------------------------------------------- 안전 파일 접근 (preview)

def read_capped(path: Path, secrets: list[str]) -> str:
    """화이트리스트 파일을 크기 제한 안에서 읽고 secret을 마스킹한다 (§30)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return "(읽기 실패)"
    truncated = len(raw) > PREVIEW_MAX_BYTES
    text = raw[:PREVIEW_MAX_BYTES].decode("utf-8", errors="replace")
    text = redact_text(text, secrets)
    if truncated:
        text += "\n… (길이 제한으로 잘림)"
    return text


def safe_source_path(final_dir: Path | None, rel: str) -> Path | None:
    """source preview 요청 경로를 화이트리스트 루트로 제한한다 (§22·§30: 절대경로/../ 차단)."""
    if not final_dir or not rel:
        return None
    p = Path(rel)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        return None
    if not (rel in SOURCE_PREVIEW_FILES or any(rel.startswith(pre) for pre in SOURCE_PREVIEW_PREFIXES)):
        return None
    target = final_dir / p
    try:
        resolved = target.resolve()
    except OSError:
        return None
    if not str(resolved).startswith(str(final_dir.resolve())):
        return None
    return resolved if resolved.is_file() else None


def source_files(final_dir: Path | None) -> list[str]:
    """source preview 대상 파일 목록 (final_artifact 안, 허용 루트만)."""
    if not final_dir or not final_dir.is_dir():
        return []
    out: list[str] = []
    for name in sorted(SOURCE_PREVIEW_FILES):
        if (final_dir / name).is_file():
            out.append(name)
    for root in ("src", "fixtures", "golden", "product", "validators"):
        base = final_dir / root
        for p in sorted(base.rglob("*")) if base.is_dir() else []:
            if p.is_file():
                out.append(p.relative_to(final_dir).as_posix())
    return out


def final_tree(final_dir: Path | None, limit: int = 200) -> str:
    if not final_dir or not final_dir.is_dir():
        return "(아직 생성된 파일이 없습니다)"
    lines = ["final_artifact/"]
    paths = sorted(p for p in final_dir.rglob("*") if p.is_file())
    for p in paths[:limit]:
        rel = p.relative_to(final_dir).as_posix()
        indent = "  " * (rel.count("/") + 1)
        lines.append(f"{indent}{p.name}")
    if len(paths) > limit:
        lines.append(f"  … (총 {len(paths)}개 중 {limit}개 표시)")
    return "\n".join(lines)
