# Phase 2D-0 Gemma Productization Autopilot — evidence 추출, hard blocker, auto_order/blueprint 생성, mock loop proof, 최소 루프 오케스트레이터 모듈.
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from repo_idea_miner.factory_autopilot_desks import (
    build_blueprint_prompt,
    build_gap_prompt,
    build_judge_prompt,
    build_lane_prompt,
    build_order_prompt,
    build_unified_prompt,
    execute_desk,
    mock_gap_classifier,
    mock_next_lane_planner,
    mock_order_slots,
    mock_product_judge,
    mock_repair_blueprint,
    mock_unified_packet,
)
from repo_idea_miner.factory_autopilot_schemas import (
    AUTO_ORDER_QUALITY_MIN,
    AUTOPILOT_HOLD_FOR_HUMAN,
    AUTOPILOT_INVALID_OUTPUT,
    AutoOrderSlots,
    GAP_TYPES,
    LANE_POLICY,
    LANE_TEMPLATES,
    MOCK_SAFE_LANES,
    ProductGapClassification,
    ProductStageLabel,
    RecommendedNextLane,
    RepairBlueprint,
    STAGE_RANK,
    UnifiedDecisionPacket,
    validate_against_hard_blockers,
    validate_judgment_evidence,
    validate_stage_gap_lane_consistency,
    write_schema_files,
)
from repo_idea_miner.factory_review import (
    _find_product_viewer,
    _first_replay_file,
    _viewer_field_mismatches,
    _viewer_reads_replay_evidence,
    compare_protected_hashes,
    compute_protected_hashes,
    read_gate_context,
    resolve_review_target,
)

REVIEW_SUBDIR = "review/phase2d0"

# review/phase2d0/ 필수 산출물 (§28)
REQUIRED_OUTPUTS = (
    "artifact_evidence.json",
    "user_facing_quality_evidence.json",
    "hard_blocker_result.json",
    "product_stage_label.json",
    "product_stage_label.md",
    "product_gap_classification.json",
    "product_gap_classification.md",
    "recommended_next_lane.json",
    "recommended_next_lane.md",
    "auto_order.md",
    "auto_order.json",
    "auto_order_quality_report.json",
    "scope_guard.json",
    "repair_blueprint.json",
    "expected_patch_plan.md",
    "tests_to_run.json",
    "rollback_or_failure_conditions.json",
    "product_loop_iteration_summary.json",
    "product_loop_iteration_summary.md",
    "product_loop_dashboard_summary.json",
    "mock_loop_order_following_report.json",
)

# 저작(authoring) 조작 감지 — 2C-0과 동일 기준 (§13)
_AUTHORING_RE = re.compile(
    r"add[_ ]?node|create[_ ]?node|add[_ ]?edge|create[_ ]?edge|new\s+Node|"
    r"contenteditable|<input|drag(start|over|drop)?|draggable|dropNode", re.I)
_VALIDATION_UI_RE = re.compile(r"validate|validation", re.I)

_OVERCLAIM_GUARDS = [
    "runner-backed execution 실증 없이 PRODUCT_CANDIDATE 금지",
    "edit→validate→execute→result→revise smoke 통과 없이 PRODUCT_CANDIDATE 금지",
    "user_can_understand_value_in_60s=false면 PRODUCT_CANDIDATE 금지",
    "hard blocker가 남아 있으면 PRODUCT_CANDIDATE 금지",
]


# ---------------------------------------------------------------- 공통 IO

def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _b(v) -> str:
    return str(bool(v)).lower()


# ---------------------------------------------------------------- Artifact Evidence 추출 (§7, §15.1)

def _latest_smoke(run_dir: Path) -> dict:
    """가장 최신 phase의 smoke 사실을 읽는다 (2c2 → 2c1 → 2c0 순)."""
    for rel in ("review/phase2c2/viewer_smoke_after_editor.json",
                "review/phase2c1/artifact_smoke_review_after_polish.json",
                "review/phase2c0/artifact_smoke_review.json"):
        d = _load_json(run_dir / rel)
        if d:
            return d
    return {}


def _latest_fitness(run_dir: Path) -> dict:
    for rel in ("review/phase2c2/product_fitness_report_after_editor.json",
                "review/phase2c1/product_fitness_report_after_polish.json",
                "review/phase2c0/product_fitness_report.json"):
        d = _load_json(run_dir / rel)
        if d:
            return d
    return {}


def _static_viewer_facts(run_dir: Path) -> dict:
    """review 산출물이 없어도 artifact에서 직접 확인 가능한 viewer 사실 (fixture/mock loop용)."""
    final_dir = run_dir / "final_artifact"
    viewer = _find_product_viewer(final_dir) if final_dir.is_dir() else None
    _f, replay = _first_replay_file(final_dir) if final_dir.is_dir() else (None, None)
    idx = _load_json(final_dir / "replay" / "index.json") or {}
    facts = {
        "viewer_exists": viewer is not None,
        "viewer_path": str(viewer.relative_to(run_dir).as_posix()) if viewer else None,
        "viewer_source": "",
        "viewer_reads_replay": False,
        "mismatches": [],
        "authoring_ui": False,
        "validation_ui": False,
        "replay_count": len(idx.get("replays") or []),
    }
    if viewer is not None:
        src = viewer.read_text(encoding="utf-8", errors="replace")
        facts["viewer_source"] = src
        facts["viewer_reads_replay"] = len(_viewer_reads_replay_evidence(src, replay)) >= 2
        facts["mismatches"] = _viewer_field_mismatches(replay, src)
        facts["authoring_ui"] = bool(_AUTHORING_RE.search(src))
        facts["validation_ui"] = bool(_VALIDATION_UI_RE.search(src))
    return facts


def extract_artifact_evidence(run_dir: Path) -> dict:
    """artifact/review 산출물에서 product loop evidence와 evidence_refs 카탈로그를 만든다.

    판정 기준은 ID가 아니라 product loop evidence다 (§12) — challenge_id/title은 읽지 않는다.
    """
    run_dir = Path(run_dir)
    gate = read_gate_context(run_dir)
    smoke = _latest_smoke(run_dir)
    fitness = _latest_fitness(run_dir)
    editor_report = _load_json(run_dir / "review/phase2c2/phase2c2_editor_report.json") or {}
    editor_smoke = editor_report.get("editor_smoke") or \
        _load_json(run_dir / "review/phase2c2/editor_smoke_review.json") or {}
    js_check = _load_json(run_dir / "review/phase2c2/viewer_js_syntax_check.json") or {}
    hb_check = _load_json(run_dir / "review/phase2c2/viewer_handler_binding_check.json") or {}
    static = _static_viewer_facts(run_dir)

    has_editor = bool(editor_smoke)
    facts: dict = {
        "viewer_exists": bool(smoke.get("product_viewer_exists", static["viewer_exists"])),
        "viewer_path": smoke.get("product_viewer_path") or static["viewer_path"],
        "viewer_source": static["viewer_source"],
        "viewer_reads_replay": bool(smoke.get("product_viewer_reads_replay",
                                              static["viewer_reads_replay"])),
        "mismatches": smoke.get("mismatches", static["mismatches"]) or [],
        "authoring_ui": bool(smoke.get("product_interactive_authoring", static["authoring_ui"])),
        "runner_executable": smoke.get("runner_executable"),
        "runner_command": smoke.get("runner_command"),
        "runner_viewer_consistent": smoke.get("runner_viewer_consistent"),
        "replay_count": smoke.get("replay_count", static["replay_count"]) or static["replay_count"],
        "green_base": gate.get("green_base"),
        "gate_fail": bool(gate.get("gate_fail")),
        "verdict": gate.get("verdict"),
        "js_syntax_status": js_check.get("status") or editor_smoke.get("js_syntax_status"),
        "handler_binding_status": hb_check.get("status"),
        "viewer_js_functions": sorted((js_check.get("functions_present") or {}).keys()),
        "prior_fitness_label": fitness.get("recommended_fitness"),
        "prior_fitness_qualifier": "draft_editor_candidate" if fitness.get("draft_editor_candidate") else None,
        "critical_red_flags": fitness.get("critical_red_flags") or [],
        "limitations": fitness.get("limitations") or [],
        "has_editor_report": has_editor,
        "runner_backed_execution_included": editor_smoke.get("runner_backed_execution_included")
        if has_editor else None,
        "draft_export_supported": editor_smoke.get("draft_export_supported") if has_editor else None,
        "graph_validation_supported": editor_smoke.get("graph_validation_supported")
        if has_editor else None,
    }
    facts["mismatch_count"] = len(facts["mismatches"])
    facts["archive_recommended"] = fitness.get("recommended_fitness") == "ARCHIVE"
    # evidence 충분성: green/gate 문맥과 viewer/smoke 근거가 있어야 판정 가능 (§23)
    facts["evidence_sufficient"] = bool(
        (gate.get("verdict") or gate.get("gates")) and
        (facts["viewer_exists"] or smoke or has_editor))

    # ---- product loop evidence (§7)
    can_create = bool(facts["authoring_ui"] and editor_smoke.get("add_node_supported", True)) \
        if facts["authoring_ui"] else False
    can_validate = bool(editor_smoke.get("graph_validation_supported")) if has_editor \
        else bool(facts["authoring_ui"] and static["validation_ui"])
    can_execute = bool(editor_smoke.get("runner_backed_execution_included")) if has_editor else False
    can_see_result = bool(editor_smoke.get("draft_execution_result_visible")) and can_execute
    can_understand_failure = bool(editor_smoke.get("draft_failure_feedback_visible")) and can_execute
    can_revise = bool(editor_smoke.get("draft_revise_and_rerun_supported")) and can_execute
    # 공통 evidence 이름 (Phase 2D-1 §6) — 도메인 상세는 adapter evidence(2C-2/2C-3 report)에만 둔다.
    # can_understand_success는 실행 결과가 화면에 보이는 것(성공 피드백)과 같은 근거에서 파생된다.
    loop = {
        "can_create_or_modify_input": can_create,
        "can_validate_input": can_validate,
        "can_execute_primary_action": can_execute,
        "can_observe_state_change": can_see_result,
        "can_understand_success": can_see_result,
        "can_understand_failure": can_understand_failure,
        "can_revise_and_retry": can_revise,
    }
    loop["product_loop_closed"] = all(loop.values())

    # ---- available user actions (근거 기반)
    actions: list[str] = []
    if facts["viewer_exists"]:
        actions.append("open product viewer")
    if facts["viewer_reads_replay"]:
        actions.append("load replay scenario")
    if can_create:
        actions += ["add/edit/delete node", "add/delete edge"]
    if can_validate:
        actions.append("validate draft graph")
    if facts.get("draft_export_supported"):
        actions.append("export draft JSON")
    if can_execute:
        actions.append("execute created input via runner")
    facts["available_user_actions"] = actions

    # ---- product 주요 파일 snippet (§15.1) — 프롬프트 전용
    snippets: dict[str, str] = {}
    if facts["viewer_source"]:
        snippets["product_viewer"] = facts["viewer_source"][:1200]
    facts["product_file_snippets"] = snippets

    # ---- evidence_refs 카탈로그 (§9)
    refs: dict[str, str] = {}
    for k, v in loop.items():
        refs[f"loop.{k}"] = f"artifact_evidence.product_loop.{k}={_b(v)}"
    for k in ("viewer_exists", "viewer_reads_replay", "authoring_ui", "green_base", "gate_fail",
              "evidence_sufficient", "archive_recommended", "mismatch_count", "replay_count",
              "runner_executable", "verdict"):
        refs[f"facts.{k}"] = f"artifact_evidence.facts.{k}={str(facts.get(k)).lower()}"
    if has_editor:
        refs["editor.runner_backed_execution_included"] = (
            f"phase2c2_editor_report.runner_backed_execution_included="
            f"{_b(editor_smoke.get('runner_backed_execution_included'))}")
        refs["editor.draft_export_supported"] = (
            f"editor_smoke_review.draft_export_supported={_b(editor_smoke.get('draft_export_supported'))}")
    if facts["js_syntax_status"]:
        refs["check.js_syntax"] = f"viewer_js_syntax_check.status={facts['js_syntax_status']}"
    if facts["handler_binding_status"]:
        refs["check.handler_binding"] = f"viewer_handler_binding_check.status={facts['handler_binding_status']}"
    for i, lim in enumerate(facts["limitations"]):
        refs[f"limitation.{i}"] = f'product_fitness_report.limitations includes "{lim}"'

    known = set(refs.values())
    # desk가 파생 판단을 참조할 수 있는 refs (§9 허용 예시)
    for part in ("runner_backed_execution", "result_from_edited_input",
                 "failure_understanding", "revise_and_rerun"):
        known.add(f"product_stage_label.missing_loop_parts includes {part}")
    for g in GAP_TYPES:
        known.add(f"product_gap_classification.primary_gap={g}")

    return {"product_loop": loop, "facts": facts, "refs": refs, "known_refs": known}


# ---------------------------------------------------------------- User-Facing Quality Evidence (§8)

def extract_user_facing_quality(evidence: dict) -> dict:
    """artifact evidence에서 사용자-facing 품질 evidence를 파생한다 (§8)."""
    facts = evidence["facts"]
    loop = evidence["product_loop"]
    viewer_src = facts.get("viewer_source") or ""
    success_visible = bool(
        facts.get("runner_viewer_consistent") is True or
        re.search(r"data\.summary|node\.status", viewer_src))
    fields = {
        "first_screen_understandable": bool(
            facts.get("viewer_exists") and facts.get("viewer_reads_replay")
            and not facts.get("mismatches")),
        "clear_next_action": bool(
            facts.get("handler_binding_status") == "PASS" or facts.get("authoring_ui")
            or re.search(r"<button|<select", viewer_src)),
        "has_example_or_seed_data": (facts.get("replay_count") or 0) > 0,
        "success_feedback_visible": success_visible,
        "failure_feedback_visible": bool(loop.get("can_understand_failure")),
        "empty_screen_risk": (facts.get("replay_count") or 0) == 0,
    }
    fields["user_can_understand_value_in_60s"] = bool(
        fields["first_screen_understandable"] and fields["success_feedback_visible"]
        and loop.get("product_loop_closed"))
    refs = {f"quality.{k}": f"user_facing_quality_evidence.{k}={_b(v)}" for k, v in fields.items()}
    # 카탈로그에 병합
    evidence["refs"].update(refs)
    evidence["known_refs"].update(refs.values())
    return {"fields": fields, "refs": refs}


# ---------------------------------------------------------------- Deterministic Hard Blockers (§6)

def apply_hard_blockers(evidence: dict, quality: dict) -> dict:
    """코드 기반 hard blocker를 적용한다. Gemma judge는 이 결과를 넘을 수 없다 (§6)."""
    facts = evidence["facts"]
    loop = evidence["product_loop"]
    q = quality["fields"]
    r = evidence["refs"]

    blockers: list[dict] = []

    def block(rule: str, triggered: bool, ref_keys: tuple[str, ...], cap: str | None = None):
        blockers.append({
            "rule": rule, "triggered": bool(triggered),
            "evidence_refs": [r[k] for k in ref_keys if k in r],
            "stage_cap": cap,
        })

    block("runner-backed execution 없음 → PRODUCT_CANDIDATE 금지",
          not loop["can_execute_primary_action"],
          ("loop.can_execute_primary_action", "editor.runner_backed_execution_included"))
    block("사용자가 만든 입력을 실행할 수 없음 → PRODUCT_CANDIDATE 금지",
          not loop["can_execute_primary_action"], ("loop.can_execute_primary_action",))
    block("실행 결과를 볼 수 없음 → PRODUCT_CANDIDATE 금지",
          not loop["can_observe_state_change"],
          ("loop.can_observe_state_change",))
    block("수정 후 재실행할 수 없음 → PRODUCT_CANDIDATE 금지",
          not loop["can_revise_and_retry"], ("loop.can_revise_and_retry",))
    block("JS syntax FAIL → PRODUCT_CANDIDATE 금지",
          facts.get("js_syntax_status") == "FAIL", ("check.js_syntax",))
    block("critical red flag 존재 → PRODUCT_CANDIDATE 금지",
          bool(facts.get("critical_red_flags")), ("facts.viewer_exists",))
    block("viewer/product surface 없음 → REVIEWABLE_ARTIFACT 이상 금지",
          not facts.get("viewer_exists"), ("facts.viewer_exists",), cap="CORE_GREEN")
    block("조작 UI 없음 → INTERACTION_CANDIDATE 이상 금지",
          not facts.get("authoring_ui"), ("facts.authoring_ui",), cap="POLISHABLE_PROTOTYPE")
    block("조작 UI는 있으나 실행 없음 → EXECUTION_CANDIDATE 이상 금지",
          facts.get("authoring_ui") and not loop["can_execute_primary_action"],
          ("facts.authoring_ui", "loop.can_execute_primary_action"), cap="INTERACTION_CANDIDATE")
    block("success_feedback_visible=false → EXECUTION_CANDIDATE 이상 제한",
          not q["success_feedback_visible"], ("quality.success_feedback_visible",),
          cap="INTERACTION_CANDIDATE")
    block("60초 이해성 evidence 없음 → PRODUCT_CANDIDATE 금지",
          not q["user_can_understand_value_in_60s"],
          ("quality.user_can_understand_value_in_60s",))
    block("first_screen_understandable=false → PRODUCT_CANDIDATE 금지",
          not q["first_screen_understandable"], ("quality.first_screen_understandable",))
    block("clear_next_action=false → PRODUCT_CANDIDATE 금지",
          not q["clear_next_action"], ("quality.clear_next_action",))
    block("has_example_or_seed_data=false → PRODUCT_CANDIDATE 금지 또는 UX_POLISH_REQUIRED",
          not q["has_example_or_seed_data"], ("quality.has_example_or_seed_data",))
    block("failure_feedback_visible=false → PRODUCT_CANDIDATE 금지",
          not q["failure_feedback_visible"], ("quality.failure_feedback_visible",))

    max_stage = "PRODUCT_CANDIDATE"
    for b in blockers:
        if b["triggered"] and b["stage_cap"] and STAGE_RANK[b["stage_cap"]] < STAGE_RANK[max_stage]:
            max_stage = b["stage_cap"]
    product_blocked = any(b["triggered"] for b in blockers) or max_stage != "PRODUCT_CANDIDATE"
    result = {
        "blockers": blockers,
        "applied": [b["rule"] for b in blockers if b["triggered"]],
        "max_stage": max_stage if STAGE_RANK[max_stage] < STAGE_RANK["PRODUCT_CANDIDATE"]
        else ("PRODUCT_CANDIDATE" if not product_blocked else "EXECUTION_CANDIDATE"),
        "product_candidate_blocked": product_blocked,
    }
    for b in blockers:
        if b["triggered"]:
            ref = f"hard_blocker_result.blockers includes '{b['rule']}'"
            evidence["known_refs"].add(ref)
    return result


# ---------------------------------------------------------------- Auto Order 생성 + 품질 검증 (§18)

def build_auto_order_json(lane_name: str, slots: dict) -> dict:
    template = LANE_TEMPLATES[lane_name]
    policy = LANE_POLICY[lane_name]
    return {
        "lane": lane_name,
        "lane_template": lane_name,
        "title": template["title"],
        "background": slots["background"],
        "observed_gap": slots["observed_gap"],
        "evidence_refs": slots["evidence_refs"],
        "allowed_scopes": slots["allowed_scopes"],
        "protected_scopes": slots["protected_scopes"],
        "forbidden_actions": slots["forbidden_actions"],
        "dry_run": {"allowed": policy["dry_run_allowed"],
                    "description": "기본 동작 — 계획/diff만 생성하고 파일을 바꾸지 않는다."},
        "apply": {"auto_execute_allowed": policy["auto_execute_allowed"],
                  "requires_human_approval": policy["requires_human_approval_before_apply"],
                  "description": "명시적 --apply + 승인 조건 충족 시에만 실제 수정."},
        "hash_guard": {"protected_scopes": slots["protected_scopes"],
                       "description": "보호 대상 hash before/after/check — 변경 감지 시 FAIL/rollback."},
        "expected_outputs": slots["expected_outputs"],
        "smoke_gate": ["smoke 재실행", "gate/검증 재실행"],
        "validate": ["factory-validate 재실행", "scope/hash guard 검사"],
        "acceptance_tests": slots["concrete_acceptance_tests"],
        "stop_conditions": slots["stop_conditions"],
        "report_format": slots["report_format"],
        "product_candidate_overclaim_guards": list(_OVERCLAIM_GUARDS),
        "repair_actions": slots.get("repair_actions") or [],
    }


def build_auto_order_md(order: dict) -> str:
    def ul(items):
        return "\n".join(f"- {i}" for i in items) if items else "- (없음)"

    return f"""# {order['title']}

## 1. 작업 배경
{order['background']}

## 2. 정확한 정의
- lane: {order['lane']} (lane template 기반 — free-form 아님)
- primary gap 해결이 목적이다.

## 3. 하지 말 것
{ul(order['forbidden_actions'])}

## 4. 수정 가능 범위 (allowed scopes)
{ul(order['allowed_scopes'])}

## 5. 보호 대상 + hash guard
{ul(order['protected_scopes'])}
- {order['hash_guard']['description']}

## 6. Dry-run
- {order['dry_run']['description']}

## 7. Apply
- auto_execute_allowed: {order['apply']['auto_execute_allowed']}
- requires_human_approval: {order['apply']['requires_human_approval']}
- {order['apply']['description']}

## 8. 산출물
{ul(order['expected_outputs'])}

## 9. Smoke / Gate
{ul(order['smoke_gate'])}

## 10. Validate
{ul(order['validate'])}

## 11. 테스트 요구사항 (acceptance tests)
{ul(order['acceptance_tests'])}

## 12. 완료 기준
- 위 acceptance tests가 모두 evidence와 함께 통과한다.
- 보호 대상 hash가 불변이다.

## 13. 작업 보고 형식
{ul(order['report_format'])}

## 14. PRODUCT_CANDIDATE 과대평가 방지 조건
{ul(order['product_candidate_overclaim_guards'])}

## 15. Stop conditions
{ul(order['stop_conditions'])}

## 16. Observed gap / Evidence
- observed_gap: {order['observed_gap']}
{ul(order['evidence_refs'])}
"""


def score_auto_order(order: dict, gap: dict, known_refs: set[str]) -> dict:
    """auto_order 품질 검증 (§18.3) — 미달이면 HOLD_FOR_HUMAN이다."""
    lane = order.get("lane")
    template = LANE_TEMPLATES.get(lane) or {}
    primary = gap.get("primary_gap") or ""
    gap_refs = set(gap.get("primary_gap_evidence_refs") or [])
    order_refs = set(order.get("evidence_refs") or [])
    checks = {
        "lane_title_match": order.get("title") == template.get("title"),
        "addresses_primary_gap": bool(
            (gap.get("primary_gap_reason") or primary) and (
                primary in json.dumps(order.get("background", "") + order.get("observed_gap", ""),
                                      ensure_ascii=False)
                or bool(order_refs & gap_refs))),
        "allowed_scope_matches_lane": bool(order.get("allowed_scopes")) and
        set(order["allowed_scopes"]) <= set(template.get("allowed_scopes") or []),
        "protected_scope_sufficient": set(template.get("protected_scopes") or [])
        <= set(order.get("protected_scopes") or []),
        "forbidden_actions_present": bool(order.get("forbidden_actions")),
        "dry_run_apply_separated": bool(order.get("dry_run")) and bool(order.get("apply")),
        "hash_guard_present": bool(order.get("hash_guard")),
        "smoke_gate_validate_present": bool(order.get("smoke_gate")) and bool(order.get("validate")),
        "stop_conditions_present": bool(order.get("stop_conditions")),
        "report_format_present": bool(order.get("report_format")),
        "overclaim_guard_present": bool(order.get("product_candidate_overclaim_guards")),
        "evidence_refs_valid": bool(order_refs) and all(x in known_refs for x in order_refs),
    }
    passed = sum(1 for v in checks.values() if v)
    score = round(passed / len(checks), 3)
    return {
        "auto_order_quality_score": score,
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "status": "PASS" if score >= AUTO_ORDER_QUALITY_MIN else "HOLD_FOR_HUMAN",
        "threshold": AUTO_ORDER_QUALITY_MIN,
    }


# ---------------------------------------------------------------- Blueprint 산출물 (§19)

def validate_blueprint_scopes(blueprint: dict, live: bool) -> list[str]:
    """blueprint가 protected scope 수정을 제안하거나 live apply를 허용하면 무효 (§30.2)."""
    p: list[str] = []
    if live and blueprint.get("apply_allowed") is not False:
        p.append("repair_blueprint: live run인데 apply_allowed != false")
    template = LANE_TEMPLATES.get(blueprint.get("target_lane")) or {}
    allowed = set(template.get("allowed_scopes") or [])
    protected = set(blueprint.get("protected_file_scopes") or []) | \
        set(template.get("protected_scopes") or [])
    for scope in blueprint.get("expected_changed_file_scopes") or []:
        norm = str(scope).replace("\\", "/")
        if allowed and not any(norm.startswith(a) or a.startswith(norm) for a in allowed):
            p.append(f"repair_blueprint: allowed scope 밖 변경 제안: {scope}")
        if any(norm.startswith(pr) for pr in protected):
            p.append(f"repair_blueprint: protected scope 수정 제안: {scope}")
    return p


def render_expected_patch_plan_md(blueprint: dict) -> str:
    def ul(items):
        return "\n".join(f"- {i}" for i in items) if items else "- (없음)"

    return f"""# Expected Patch Plan ({blueprint['target_lane']})

이 문서는 blueprint only다 — 적용하지 않는다 (apply_allowed={blueprint['apply_allowed']}).

## Observed gap
{blueprint['observed_gap']}

## 구현 접근
{blueprint['proposed_implementation_approach']}

## Expected patch shape
{ul(blueprint['expected_patch_shape'])}

## 변경 예상 scope (allowed 안에서만)
{ul(blueprint['expected_changed_file_scopes'])}

## 보호 scope (수정 제안 금지)
{ul(blueprint['protected_file_scopes'])}

## 실행할 테스트
{ul(blueprint['tests_to_run'])}

## Rollback 조건
{ul(blueprint['rollback_conditions'])}

## Failure 조건
{ul(blueprint['failure_conditions'])}

## PRODUCT_CANDIDATE 과대평가 방지 조건
{ul(blueprint['product_candidate_overclaim_guards'])}

## Evidence refs
{ul(blueprint['evidence_refs'])}
"""


# ---------------------------------------------------------------- 문서 렌더링

def render_stage_label_md(label: dict) -> str:
    loop = label.get("product_loop_evidence") or {}
    q = label.get("user_facing_quality_evidence") or {}
    L = ["# Product Stage Label (Phase 2D-0)", "",
         f"- prior_fitness_label: {label.get('prior_fitness_label')}"
         f" ({label.get('prior_fitness_qualifier') or '-'})",
         f"- autopilot_stage: **{label.get('autopilot_stage')}**",
         f"- autopilot_is_product_candidate: {label.get('autopilot_is_product_candidate')}",
         f"- confidence: {label.get('confidence')}",
         f"- reason: {label.get('reason')}", "", "## Product loop evidence"]
    L += [f"- {k}: {v}" for k, v in loop.items()]
    L += ["", "## User-facing quality evidence"]
    L += [f"- {k}: {v}" for k, v in q.items()]
    L += ["", "## Evidence refs"]
    L += [f"- {r}" for r in label.get("evidence_refs") or []]
    L += ["", "## Not product reasons"]
    for r in label.get("not_product_reasons") or []:
        L.append(f"- {r.get('reason')}")
        L += [f"  - {e}" for e in r.get("evidence_refs") or []]
    L += ["", "## Hard blockers applied"]
    L += [f"- {b}" for b in label.get("hard_blockers_applied") or []] or ["- (없음)"]
    L += ["", "## Missing loop parts"]
    L += [f"- {m}" for m in label.get("missing_loop_parts") or []] or ["- (없음)"]
    return "\n".join(L) + "\n"


def render_gap_md(gap: dict) -> str:
    L = ["# Product Gap Classification (Phase 2D-0)", "",
         f"- primary_gap: **{gap.get('primary_gap')}**",
         f"- reason: {gap.get('primary_gap_reason')}", "", "## Primary gap evidence refs"]
    L += [f"- {r}" for r in gap.get("primary_gap_evidence_refs") or []] or ["- (없음)"]
    L += ["", "## Gaps"]
    for g in gap.get("gaps") or []:
        L.append(f"### {g.get('type')} ({g.get('severity')})")
        L.append(f"- {g.get('explanation')}")
        L += [f"- 근거: {e}" for e in g.get("evidence_refs") or []]
    return "\n".join(L) + "\n"


def render_lane_md(lane: dict) -> str:
    L = ["# Recommended Next Lane (Phase 2D-0)", "",
         f"- recommended_next_lane: **{lane.get('recommended_next_lane')}**",
         f"- reason: {lane.get('reason')}",
         f"- lane_risk: {lane.get('lane_risk')}",
         f"- dry_run_allowed: {lane.get('dry_run_allowed')}",
         f"- auto_execute_allowed: {lane.get('auto_execute_allowed')}",
         f"- requires_human_approval_before_apply: {lane.get('requires_human_approval_before_apply')}",
         f"- human_decision_required: {lane.get('human_decision_required')}",
         "", "## Evidence refs"]
    L += [f"- {r}" for r in lane.get("evidence_refs") or []]
    L += ["", "## Allowed scopes"]
    L += [f"- {s}" for s in lane.get("allowed_file_scopes") or []] or ["- (없음)"]
    L += ["", "## Protected scopes"]
    L += [f"- {s}" for s in lane.get("protected_file_scopes") or []] or ["- (없음)"]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- Mock/Safe Loop Proof (§22)

_PROOF_VIEWER = """<!DOCTYPE html><html><body>
<select id="s"></select><button onclick="load()">Load</button>
<div id="g"></div><div id="d"></div>
<script>
async function init(){ const r = await fetch("../../replay/index.json"); const data = await r.json();
  const sel = document.getElementById("s");
  data.replays.forEach(x=>{const o=document.createElement("option"); o.value=x.file;
    o.textContent=x.id; sel.appendChild(o);}); }
async function load(){ const f = document.getElementById("s").value;
  const r = await fetch("../../replay/"+f); const data = await r.json();
  document.getElementById("d").textContent = JSON.stringify(data.summary);
  const st = data.final_state; const nodes = st.nodes; const edges = st.edges;
  Object.entries(nodes).forEach(([id,node])=>{ const n=document.createElement("div");
    n.textContent = id + " " + node.status; document.getElementById("g").appendChild(n); });
  edges.forEach(edge=>{ const a = nodes[edge.from]; const b = nodes[edge.to];
    if(a && b){ const e=document.createElement("div"); e.className="edge";
      document.getElementById("g").appendChild(e);} });
}
window.onload = init;
</script></body></html>
"""

_PROOF_REPLAY = {
    "ok": True,
    "final_state": {
        "nodes": {"a": {"id": "a", "type": "INPUT", "status": "COMPLETED"},
                  "b": {"id": "b", "type": "OUTPUT", "status": "COMPLETED"}},
        "edges": [{"source_id": "a", "source_port": 0, "target_id": "b", "target_port": 0}],
        "execution_order": ["a", "b"], "global_tick": 1,
    },
    "events": [{"event": "node_created", "node_id": "a"}],
    "summary": "Completed",
    "errors": [],
}


def build_proof_fixture(proof_dir: Path) -> Path:
    """제품성 결함(viewer field mismatch) 1개를 주입한 mock/safe fixture artifact를 만든다 (§22)."""
    fixture = proof_dir / "fixture_run"
    fa = fixture / "final_artifact"
    _write_json(fa / "replay" / "index.json",
                {"replays": [{"id": "scenario_001", "file": "replay_scenario_001.json", "ok": True}]})
    _write_json(fa / "replay" / "replay_scenario_001.json", _PROOF_REPLAY)
    _write_json(fa / "golden" / "expected_001.json",
                {"scenario_id": "scenario_001", "expected_summary": "Completed"})
    _write_text(fa / "product" / "viewer" / "index.html", _PROOF_VIEWER)
    _write_json(fixture / "green_base.json",
                {"base_type": "green_base", "verdict": "REVIEW_READY", "source": "mock_loop_proof"})
    _write_json(fixture / "gate_rerun_after_anti_hardcode_patch.json", {
        "gates": {g: True for g in ("core_contract", "runner", "scenario_replay", "golden_output",
                                    "state_invariant", "determinism", "anti_hardcode")},
        "summary_source": "state_derived", "summary_hardcode_risk": "low"})
    return fixture


def _fixture_hashes(fixture: Path, protected_prefixes: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(fixture.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(fixture).as_posix()
        if any(rel.startswith(pre) for pre in protected_prefixes):
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def follow_auto_order(fixture: Path, order_path: Path, guard_path: Path) -> dict:
    """generated auto_order/scope_guard를 '실제로 읽고' 그 지시대로만 repair를 실행한다 (§22).

    hardcoded repair는 없다 — repair_actions가 비어 있으면 정직하게 실패로 기록한다.
    """
    result = {
        "auto_order_read": False, "scope_guard_read": False, "repair_followed_order": False,
        "changed_files": [], "changed_files_within_allowed_scope": False,
        "protected_files_unchanged": False, "actual_file_changed": False,
        "problems": [],
    }
    order = _load_json(order_path)
    guard = _load_json(guard_path)
    if order is None:
        result["problems"].append("auto_order.json 읽기 실패")
        return result
    result["auto_order_read"] = True
    if guard is None:
        result["problems"].append("scope_guard.json 읽기 실패")
        return result
    result["scope_guard_read"] = True

    allowed = [s.replace("\\", "/") for s in guard.get("allowed_scopes") or []]
    protected = [s.replace("\\", "/") for s in guard.get("protected_scopes") or []]
    prot_prefixes = tuple(p for p in protected)
    hashes_before = _fixture_hashes(fixture, prot_prefixes)

    actions = order.get("repair_actions") or []
    if not actions:
        result["problems"].append("auto_order에 repair_actions 없음 — 따라 할 order가 없다")
        return result

    changed: list[str] = []
    for act in actions:
        rel = str(act.get("file") or "").replace("\\", "/")
        if not any(rel.startswith(a) for a in allowed):
            result["problems"].append(f"allowed scope 밖 수정 시도 차단: {rel}")
            continue
        if any(rel.startswith(p) for p in protected):
            result["problems"].append(f"protected scope 수정 시도 차단: {rel}")
            continue
        target = fixture / rel
        if act.get("action") != "replace_in_file" or not target.is_file():
            result["problems"].append(f"실행 불가 action: {act.get('action')} {rel}")
            continue
        src = target.read_text(encoding="utf-8")
        new = src.replace(act.get("find") or "", act.get("replace") or "")
        if new != src:
            target.write_text(new, encoding="utf-8")
            if rel not in changed:
                changed.append(rel)

    result["changed_files"] = changed
    result["actual_file_changed"] = bool(changed)
    result["repair_followed_order"] = bool(changed)
    result["changed_files_within_allowed_scope"] = bool(changed) and all(
        any(c.startswith(a) for a in allowed) for c in changed)
    hashes_after = _fixture_hashes(fixture, prot_prefixes)
    result["protected_files_unchanged"] = hashes_before == hashes_after
    return result


def run_mock_loop_proof(proof_dir: Path) -> dict:
    """judge → order → repair → smoke/validate → rejudge E2E 루프를 fixture에서 1회 증명한다 (§22)."""
    proof_dir = Path(proof_dir)
    fixture = build_proof_fixture(proof_dir)

    # 1) judge (mock, evidence 기반)
    evidence = extract_artifact_evidence(fixture)
    quality = extract_user_facing_quality(evidence)
    hard = apply_hard_blockers(evidence, quality)
    stage_label = mock_product_judge(evidence, quality, hard)
    gap = mock_gap_classifier(evidence, quality, stage_label)
    lane = mock_next_lane_planner(evidence, gap)
    lane_name = lane["recommended_next_lane"]

    report = {
        "fixture": str(fixture.as_posix()),
        "injected_defect": "viewer가 edge.from/edge.to를 읽지만 replay edge 키는 source_id/target_id",
        "stage_before": stage_label["stage"],
        "primary_gap": gap.get("primary_gap"),
        "lane": lane_name,
        "lane_in_mock_safe_lanes": lane_name in MOCK_SAFE_LANES,
        "auto_order_read": False, "scope_guard_read": False, "repair_followed_order": False,
        "changed_files_within_allowed_scope": False, "protected_files_unchanged": False,
        "actual_file_changed": False,
        "smoke_ran": False, "validate_ran": False, "rejudge_ran": False,
        "stage_after": None, "stage_improved": False, "stage_improved_or_honest_stop": False,
        "honest_stop_reason": None, "problems": [],
    }
    if lane_name not in MOCK_SAFE_LANES:
        report["problems"].append(f"mock/safe lane이 아님: {lane_name}")
        report["honest_stop_reason"] = "허용되지 않은 lane — repair 없이 정직하게 중단"
        report["stage_improved_or_honest_stop"] = True
        _write_json(proof_dir / "mock_loop_order_following_report.json", report)
        return report

    # 2) lane template 기반 auto_order + scope_guard 생성
    template = LANE_TEMPLATES[lane_name]
    slots = mock_order_slots(evidence, gap, lane, template)
    # fixture 경로 기준 scope로 좁힌다 (fixture의 final_artifact/product/만 허용)
    order = build_auto_order_json(lane_name, slots)
    guard = {"lane": lane_name, "allowed_scopes": slots["allowed_scopes"],
             "protected_scopes": slots["protected_scopes"],
             "forbidden_actions": slots["forbidden_actions"]}
    order_path = proof_dir / "auto_order.json"
    guard_path = proof_dir / "scope_guard.json"
    _write_json(order_path, order)
    _write_text(proof_dir / "auto_order.md", build_auto_order_md(order))
    _write_json(guard_path, guard)

    # 3) generated order를 실제로 읽고 따르는 repair (§22 필수 흐름 1~7)
    follow = follow_auto_order(fixture, order_path, guard_path)
    report.update({k: follow[k] for k in (
        "auto_order_read", "scope_guard_read", "repair_followed_order",
        "changed_files_within_allowed_scope", "protected_files_unchanged",
        "actual_file_changed")})
    report["changed_files"] = follow["changed_files"]
    report["problems"] += follow["problems"]

    # 4) smoke — mismatch 재검사
    smoke_facts = _static_viewer_facts(fixture)
    report["smoke_ran"] = True
    report["mismatches_after"] = smoke_facts["mismatches"]

    # 5) validate — scope/protected 검사 결과 종합
    report["validate_ran"] = True
    report["validate_pass"] = (follow["changed_files_within_allowed_scope"]
                               and follow["protected_files_unchanged"]
                               and not smoke_facts["mismatches"])

    # 6) rejudge
    evidence2 = extract_artifact_evidence(fixture)
    quality2 = extract_user_facing_quality(evidence2)
    hard2 = apply_hard_blockers(evidence2, quality2)
    stage_after = mock_product_judge(evidence2, quality2, hard2)["stage"]
    report["rejudge_ran"] = True
    report["stage_after"] = stage_after
    report["stage_improved"] = STAGE_RANK.get(stage_after, -1) > STAGE_RANK.get(report["stage_before"], -1)
    if not report["stage_improved"]:
        report["honest_stop_reason"] = "stage 개선 없음 — 정직하게 중단"
    report["stage_improved_or_honest_stop"] = report["stage_improved"] or \
        bool(report["honest_stop_reason"])
    _write_json(proof_dir / "mock_loop_order_following_report.json", report)
    return report


# ---------------------------------------------------------------- 보호 대상 hash guard (§2, §21.2)

def compute_loop_protected_hashes(run_dir: Path) -> dict[str, str]:
    """Phase 2D-0은 판단 전용 — artifact(src/product/golden/fixtures/contract/replay)와
    기존 review/phase2c0·2c1·2c2 산출물이 모두 불변이어야 한다."""
    run_dir = Path(run_dir)
    out = compute_protected_hashes(run_dir)
    for root_name in ("workspace", "final_artifact"):
        rdir = run_dir / root_name / "replay"
        if rdir.is_dir():
            for p in sorted(rdir.rglob("*")):
                if p.is_file():
                    out[f"{root_name}/{p.relative_to(run_dir / root_name).as_posix()}"] = \
                        hashlib.sha256(p.read_bytes()).hexdigest()
    for sub in ("review/phase2c0", "review/phase2c1", "review/phase2c2"):
        d = run_dir / sub
        if d.is_dir():
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    out[p.relative_to(run_dir).as_posix()] = \
                        hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------------------------------------------------------------- Hardcode guard (§12)

def _title_tokens(run_dir: Path) -> list[str]:
    """run 문서에서 challenge title 토큰을 모은다 — 프롬프트 누수 검사 전용 (판정에는 미사용)."""
    tokens: list[str] = []
    for rel in ("normalized_challenge.json", "dashboard_summary.json",
                "phase2b1b_dashboard_summary.json"):
        d = _load_json(run_dir / rel) or {}

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if "title" in str(k).lower() and isinstance(v, str) and len(v) >= 4:
                        tokens.append(v)
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(d)
    return sorted(set(tokens))


def build_hardcode_guard(run_dir: Path, prompts: dict[str, str]) -> dict:
    challenge_id = None
    for rel in ("phase2b1b_dashboard_summary.json", "dashboard_summary.json"):
        d = _load_json(run_dir / rel) or {}
        if d.get("challenge_id") is not None:
            challenge_id = d["challenge_id"]
            break
    titles = _title_tokens(run_dir)
    joined = "\n".join(prompts.values())
    contains_id = challenge_id is not None and bool(
        re.search(rf"challenge[_ ]?id\D{{0,4}}{challenge_id}\b", joined))
    contains_title = any(t in joined for t in titles)
    return {
        "challenge_id": challenge_id,
        "title_tokens_checked": len(titles),
        "prompt_contains_challenge_id": contains_id,
        "prompt_contains_title": contains_title,
        "judgment_inputs": "artifact evidence only (challenge_id/title은 판정 입력에서 제외)",
        "status": "PASS" if not (contains_id or contains_title) else "FAIL",
    }


# ---------------------------------------------------------------- Loop 오케스트레이터 (§21)

def _run_desks(executor, evidence, quality, hard, gemma_mode: str, use_llm: bool,
               prompts_out: dict, include_order: bool = True) -> dict:
    """sequential 또는 unified 모드로 desk를 실행한다. 검증 기준은 동일하다 (§20).

    include_order=False면 judge/gap/lane까지만 실행한다 — Phase 2D-1 closed loop는
    auto_order/blueprint 대신 lane executor가 직접 실행하므로 두 desk가 필요 없다.
    """
    out = {"status": "FAIL", "failure_type": None, "problems": [],
           "stage_label": None, "gap": None, "lane": None, "slots": None, "blueprint": None,
           "schema_repair_reports": [], "selected_mode": gemma_mode}

    def _record_repair(desk_result):
        if desk_result.get("schema_repair_report"):
            out["schema_repair_reports"].append(desk_result["schema_repair_report"])

    if gemma_mode == "unified":
        prompt = build_unified_prompt(evidence, quality, hard, LANE_TEMPLATES)
        prompts_out["unified"] = prompt
        mock = None if use_llm else mock_unified_packet(evidence, quality, hard)
        res = execute_desk(executor, "unified_decision_packet", prompt, UnifiedDecisionPacket,
                           mock_output=mock)
        _record_repair(res)
        if res["status"] != "PASS":
            out.update(failure_type=res["failure_type"], problems=res["problems"])
            return out
        raw = res["raw"]
        out["stage_label"] = raw["product_stage_label"]
        out["gap"] = raw["product_gap_classification"]
        out["lane"] = raw["recommended_next_lane"]
        out["slots"] = raw["auto_order_slots"]
        out["blueprint"] = raw["repair_blueprint"]
        out["status"] = "PASS"
        return out

    # ---- sequential desk 흐름 (§21.1)
    prompt = build_judge_prompt(evidence, quality, hard)
    prompts_out["judge"] = prompt
    mock = None if use_llm else mock_product_judge(evidence, quality, hard)
    res = execute_desk(executor, "product_stage_label", prompt, ProductStageLabel, mock_output=mock)
    _record_repair(res)
    if res["status"] != "PASS":
        out.update(failure_type=res["failure_type"], problems=res["problems"])
        return out
    out["stage_label"] = res["raw"]

    prompt = build_gap_prompt(evidence, quality, hard, out["stage_label"])
    prompts_out["gap"] = prompt
    mock = None if use_llm else mock_gap_classifier(evidence, quality, out["stage_label"])
    res = execute_desk(executor, "product_gap_classification", prompt, ProductGapClassification,
                       mock_output=mock)
    _record_repair(res)
    if res["status"] != "PASS":
        out.update(failure_type=res["failure_type"], problems=res["problems"])
        return out
    out["gap"] = res["raw"]

    if out["gap"].get("primary_gap") is None:
        out["status"] = "PASS"  # PRODUCT_CANDIDATE 도달 — lane/order 없음
        return out

    prompt = build_lane_prompt(evidence, out["gap"])
    prompts_out["lane"] = prompt
    mock = None if use_llm else mock_next_lane_planner(evidence, out["gap"])
    res = execute_desk(executor, "recommended_next_lane", prompt, RecommendedNextLane,
                       mock_output=mock)
    _record_repair(res)
    if res["status"] != "PASS":
        out.update(failure_type=res["failure_type"], problems=res["problems"])
        return out
    out["lane"] = res["raw"]

    if not include_order:
        out["status"] = "PASS"  # closed loop(2D-1)는 order/blueprint desk를 쓰지 않는다
        return out

    template = LANE_TEMPLATES.get(out["lane"]["recommended_next_lane"]) or {}
    prompt = build_order_prompt(evidence, out["gap"], out["lane"], template)
    prompts_out["order"] = prompt
    mock = None if use_llm else mock_order_slots(evidence, out["gap"], out["lane"], template)
    res = execute_desk(executor, "auto_order", prompt, AutoOrderSlots, mock_output=mock)
    _record_repair(res)
    if res["status"] != "PASS":
        out.update(failure_type=res["failure_type"], problems=res["problems"])
        return out
    out["slots"] = res["raw"]

    prompt = build_blueprint_prompt(evidence, out["gap"], out["lane"], template)
    prompts_out["blueprint"] = prompt
    mock = None if use_llm else mock_repair_blueprint(evidence, out["gap"], out["lane"], template)
    res = execute_desk(executor, "repair_blueprint", prompt, RepairBlueprint, mock_output=mock)
    _record_repair(res)
    if res["status"] != "PASS":
        out.update(failure_type=res["failure_type"], problems=res["problems"])
        return out
    out["blueprint"] = res["raw"]
    out["status"] = "PASS"
    return out


def run_product_loop(
    run_dir: str | Path | None = None,
    run_id: int | None = None,
    mode: str = "mock",
    gemma_mode: str = "sequential",
    max_iterations: int = 1,
    db_conn=None,
    scheduler=None,
    llm=None,
    run_mock_proof: bool = True,
) -> dict:
    """Productization Autopilot 최소 루프를 1회(기본) 실행한다 (§21).

    기본값: max_iterations=1, repair_execute=false, live_repair_apply=false.
    live에서는 judge/gap/lane/order/blueprint 생성까지만 하고 어떤 repair도 apply하지 않는다.
    """
    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None, "challenge_id": None,
        "review_dir": None, "failure_type": None, "problems": [],
        "autopilot_stage": None, "primary_gap": None, "next_lane": None,
        "auto_order_quality_score": None, "auto_order_quality_status": None,
        "prior_fitness_label": None, "hash_status": None, "stop_conditions": [],
        "live_repair_apply": False, "repair_execute": False,
    }
    target, err, tinfo = resolve_review_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = tinfo.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    run_dir = target
    review_dir = run_dir / REVIEW_SUBDIR
    result["review_dir"] = str(review_dir.as_posix())
    from repo_idea_miner.factory_review import _challenge_id_from_run

    result["challenge_id"] = tinfo.get("challenge_id") or _challenge_id_from_run(run_dir)
    live = mode == "live"
    use_llm = live or llm is not None

    # ---- 보호 대상 hash BEFORE — Phase 2D-0은 어떤 artifact도 수정하지 않는다
    hash_before = compute_loop_protected_hashes(run_dir)
    _write_json(review_dir / "phase2d0_hash_before.json", hash_before)

    # ---- evidence / quality / hard blockers (§21.1 1~5)
    evidence = extract_artifact_evidence(run_dir)
    quality = extract_user_facing_quality(evidence)
    hard = apply_hard_blockers(evidence, quality)
    facts = evidence["facts"]
    result["prior_fitness_label"] = facts.get("prior_fitness_label")

    ev_out = {"product_loop": evidence["product_loop"],
              "facts": {k: v for k, v in facts.items()
                        if k not in ("viewer_source", "product_file_snippets")},
              "evidence_refs_catalog": sorted(evidence["known_refs"])}
    _write_json(review_dir / "artifact_evidence.json", ev_out)
    _write_json(review_dir / "user_facing_quality_evidence.json", quality["fields"])
    _write_json(review_dir / "hard_blocker_result.json", hard)
    write_schema_files(review_dir / "schemas")

    # ---- desk executor
    executor = None
    if use_llm:
        from repo_idea_miner.config import load_settings
        from repo_idea_miner.factory_desks import DeskExecutor
        from repo_idea_miner.llm_client import LLMCallLogger

        settings = load_settings()
        secrets = settings.secret_values()
        executor = DeskExecutor(mode, settings, scheduler=scheduler, llm=llm,
                                call_logger=LLMCallLogger(review_dir / "debug" / "llm_calls.jsonl",
                                                          secrets))
    else:
        secrets = []

    iterations: list[dict] = []
    prev_primary = None
    desks = None
    stop_conditions: list[str] = []
    schema_repair_reports: list[dict] = []
    prompts: dict[str, str] = {}

    for i in range(max(1, int(max_iterations))):
        it: dict = {"iteration": i + 1}
        desks = _run_desks(executor, evidence, quality, hard, gemma_mode, use_llm, prompts)
        schema_repair_reports += desks["schema_repair_reports"]
        it["desk_status"] = desks["status"]
        if desks["status"] != "PASS":
            it["failure_type"] = desks["failure_type"]
            stop_conditions.append("strict JSON schema/desk 검증 실패"
                                   if desks["failure_type"] != "AUTOPILOT_INFRA_FAIL"
                                   else "live Gemma failure")
            iterations.append(it)
            break

        stage_raw, gap_raw, lane_raw = desks["stage_label"], desks["gap"], desks["lane"]
        # hard blocker / evidence / 정합성 검증 (§6, §9, §30.2)
        problems = validate_against_hard_blockers(stage_raw, hard)
        if problems:
            desks["status"], desks["failure_type"] = "FAIL", AUTOPILOT_INVALID_OUTPUT
            desks["problems"] += problems
            it.update(failure_type=AUTOPILOT_INVALID_OUTPUT, desk_status="FAIL")
            stop_conditions.append("hard blocker 위반")
            iterations.append(it)
            break
        if lane_raw is not None:
            problems = validate_judgment_evidence(stage_raw, gap_raw, lane_raw,
                                                  evidence["known_refs"])
            if problems:
                desks["status"] = "FAIL"
                desks["failure_type"] = "AUTOPILOT_EVIDENCE_INSUFFICIENT"
                desks["problems"] += problems
                it.update(failure_type=desks["failure_type"], desk_status="FAIL")
                stop_conditions.append("evidence_refs 검증 실패")
                iterations.append(it)
                break
            problems = validate_stage_gap_lane_consistency(stage_raw, gap_raw, lane_raw)
            if problems:
                desks["status"], desks["failure_type"] = "FAIL", AUTOPILOT_INVALID_OUTPUT
                desks["problems"] += problems
                it.update(failure_type=AUTOPILOT_INVALID_OUTPUT, desk_status="FAIL")
                stop_conditions.append("stage/gap/lane 정합성 실패")
                iterations.append(it)
                break

        it["stage"] = stage_raw.get("stage")
        it["primary_gap"] = gap_raw.get("primary_gap")
        it["lane"] = (lane_raw or {}).get("recommended_next_lane")
        iterations.append(it)

        # ---- stop conditions (§24)
        if stage_raw.get("stage") == "PRODUCT_CANDIDATE":
            stop_conditions.append("PRODUCT_CANDIDATE 도달")
            break
        if stage_raw.get("stage") == "ARCHIVE":
            stop_conditions.append("ARCHIVE 판정")
            break
        if (lane_raw or {}).get("human_decision_required") or \
                (lane_raw or {}).get("recommended_next_lane") == "HOLD_FOR_HUMAN":
            stop_conditions.append("human_decision_required = true")
            break
        if prev_primary is not None and prev_primary == gap_raw.get("primary_gap"):
            stop_conditions.append("same primary_gap 2회 반복")
            break
        prev_primary = gap_raw.get("primary_gap")
        # Phase 2D-0은 repair_execute=false — 개선이 없으므로 1 iteration이 기본이다
        if i + 1 >= max(1, int(max_iterations)):
            stop_conditions.append("max_iterations 도달")

    # ---- 판정 산출물 기록
    failure_type = desks.get("failure_type") if desks else AUTOPILOT_INVALID_OUTPUT
    result["problems"] = desks.get("problems") if desks else []
    quality_report = None

    if desks and desks["stage_label"] is not None:
        stage_raw = desks["stage_label"]
        reason = (stage_raw.get("not_product_reasons") or [{}])[0].get("reason") \
            if stage_raw.get("stage") != "PRODUCT_CANDIDATE" else "product loop closed"
        label_out = {
            "prior_fitness_label": facts.get("prior_fitness_label"),
            "prior_fitness_qualifier": facts.get("prior_fitness_qualifier"),
            "autopilot_stage": stage_raw.get("stage"),
            "autopilot_is_product_candidate": bool(stage_raw.get("is_product_candidate")),
            "reason": reason,
            **stage_raw,
        }
        _write_json(review_dir / "product_stage_label.json", label_out)
        _write_text(review_dir / "product_stage_label.md", render_stage_label_md(label_out))
        result["autopilot_stage"] = stage_raw.get("stage")
    if desks and desks["gap"] is not None:
        _write_json(review_dir / "product_gap_classification.json", desks["gap"])
        _write_text(review_dir / "product_gap_classification.md", render_gap_md(desks["gap"]))
        result["primary_gap"] = desks["gap"].get("primary_gap")
    if desks and desks["lane"] is not None:
        _write_json(review_dir / "recommended_next_lane.json", desks["lane"])
        _write_text(review_dir / "recommended_next_lane.md", render_lane_md(desks["lane"]))
        result["next_lane"] = desks["lane"].get("recommended_next_lane")

    order = None
    if desks and desks["slots"] is not None and desks["lane"] is not None:
        lane_name = desks["lane"]["recommended_next_lane"]
        order = build_auto_order_json(lane_name, desks["slots"])
        _write_json(review_dir / "auto_order.json", order)
        _write_text(review_dir / "auto_order.md", build_auto_order_md(order))
        guard = {"lane": lane_name,
                 "allowed_scopes": desks["slots"]["allowed_scopes"],
                 "protected_scopes": desks["slots"]["protected_scopes"],
                 "forbidden_actions": desks["slots"]["forbidden_actions"]}
        _write_json(review_dir / "scope_guard.json", guard)
        quality_report = score_auto_order(order, desks["gap"], evidence["known_refs"])
        _write_json(review_dir / "auto_order_quality_report.json", quality_report)
        result["auto_order_quality_score"] = quality_report["auto_order_quality_score"]
        result["auto_order_quality_status"] = quality_report["status"]
        if quality_report["status"] != "PASS":
            stop_conditions.append("auto_order_quality_score < 0.85")
            failure_type = failure_type or AUTOPILOT_HOLD_FOR_HUMAN
        policy = LANE_POLICY.get(lane_name) or {}
        if policy.get("auto_execute_allowed") is False:
            stop_conditions.append("lane policy상 auto_execute_allowed = false")

    blueprint_problems: list[str] = []
    if desks and desks["blueprint"] is not None:
        bp = dict(desks["blueprint"])
        if live:
            bp["apply_allowed"] = False  # live artifact repair apply 금지 (§19)
        blueprint_problems = validate_blueprint_scopes(bp, live=live)
        if blueprint_problems:
            stop_conditions.append("repair_blueprint가 protected scope 수정을 제안")
            result["problems"] += blueprint_problems
            failure_type = failure_type or AUTOPILOT_INVALID_OUTPUT
        _write_json(review_dir / "repair_blueprint.json", bp)
        _write_text(review_dir / "expected_patch_plan.md", render_expected_patch_plan_md(bp))
        _write_json(review_dir / "tests_to_run.json",
                    {"target_lane": bp["target_lane"], "tests": bp["tests_to_run"],
                     "note": "blueprint only — Phase 2C-3 order의 보조 자료"})
        _write_json(review_dir / "rollback_or_failure_conditions.json",
                    {"target_lane": bp["target_lane"],
                     "rollback_conditions": bp["rollback_conditions"],
                     "failure_conditions": bp["failure_conditions"]})

    # ---- schema repair report (조건부 필수, §28)
    schema_repair_used = bool(schema_repair_reports)
    if schema_repair_used:
        _write_json(review_dir / "schema_repair_report.json",
                    {"used": True, "passes": schema_repair_reports})

    # ---- prompt trace + hardcode guard (§12, §28) — secret 제거 후 기록
    def _redact(text: str) -> str:
        for s in secrets or []:
            if s:
                text = text.replace(s, "[REDACTED]")
        return text

    hardcode_guard = build_hardcode_guard(run_dir, prompts)
    _write_json(review_dir / "hardcode_guard.json", hardcode_guard)
    if prompts.get("judge") or prompts.get("unified"):
        _write_json(review_dir / "judge_prompt_trace.json",
                    {"prompt": _redact(prompts.get("judge") or prompts.get("unified")),
                     "contains_challenge_id": hardcode_guard["prompt_contains_challenge_id"],
                     "contains_title": hardcode_guard["prompt_contains_title"]})
    if prompts.get("order"):
        _write_json(review_dir / "order_writer_prompt_trace.json",
                    {"prompt": _redact(prompts["order"]),
                     "contains_challenge_id": hardcode_guard["prompt_contains_challenge_id"],
                     "contains_title": hardcode_guard["prompt_contains_title"]})

    # ---- mock/safe loop proof (§22) — live artifact와 무관한 fixture에서 실행
    mock_report = None
    if run_mock_proof:
        mock_report = run_mock_loop_proof(review_dir / "mock_loop_proof")
        _write_json(review_dir / "mock_loop_order_following_report.json", mock_report)
        result["mock_loop"] = {k: mock_report.get(k) for k in (
            "auto_order_read", "scope_guard_read", "repair_followed_order",
            "changed_files_within_allowed_scope", "protected_files_unchanged",
            "smoke_ran", "validate_ran", "rejudge_ran", "stage_improved_or_honest_stop")}

    # ---- 보호 대상 hash AFTER + check
    hash_after = compute_loop_protected_hashes(run_dir)
    hash_check = compare_protected_hashes(hash_before, hash_after)
    hash_check["note"] = "Phase 2D-0은 판단 전용 — 보호 대상 artifact/기존 review가 바뀌면 FAIL"
    _write_json(review_dir / "phase2d0_hash_after.json", hash_after)
    _write_json(review_dir / "phase2d0_hash_check.json", hash_check)
    result["hash_status"] = hash_check["status"]

    # ---- 최종 상태
    desk_ok = bool(desks and desks["status"] == "PASS" and not blueprint_problems)
    order_ok = desks is not None and (desks.get("gap") or {}).get("primary_gap") is None or (
        order is not None and quality_report is not None and quality_report["status"] == "PASS")
    ok = desk_ok and order_ok and hash_check["status"] == "PASS" and \
        hardcode_guard["status"] == "PASS"
    status = "AUTOPILOT_JUDGED" if ok else (failure_type or AUTOPILOT_INVALID_OUTPUT)
    # 판단 불확실/사람 결정 필요는 정직한 HOLD로 기록한다 (§23)
    if ok and result["next_lane"] == "HOLD_FOR_HUMAN":
        status = AUTOPILOT_HOLD_FOR_HUMAN
    result["ok"] = ok
    result["status"] = status
    result["failure_type"] = None if ok else (failure_type or AUTOPILOT_INVALID_OUTPUT)
    result["stop_conditions"] = stop_conditions

    summary = {
        "phase": "2d0",
        "mode": mode,
        "gemma_mode": gemma_mode,
        "selected_mode": gemma_mode,
        "shared_validator": True,
        "max_iterations": max_iterations,
        "iterations": iterations,
        "live_repair_apply": False,
        "repair_execute": False,
        "status": status,
        "failure_type": result["failure_type"],
        "problems": result["problems"],
        "prior_fitness_label": facts.get("prior_fitness_label"),
        "prior_fitness_qualifier": facts.get("prior_fitness_qualifier"),
        "autopilot_stage": result["autopilot_stage"],
        "primary_gap": result["primary_gap"],
        "recommended_next_lane": result["next_lane"],
        "auto_order_quality_score": result["auto_order_quality_score"],
        "auto_order_quality_status": result["auto_order_quality_status"],
        "schema_repair_used": schema_repair_used,
        "mock_loop_executed": bool(mock_report),
        "mock_loop_pass": bool(mock_report and mock_report.get("repair_followed_order")
                               and mock_report.get("protected_files_unchanged")),
        "hardcode_guard": hardcode_guard["status"],
        "hash_status": hash_check["status"],
        "stop_conditions": stop_conditions,
    }
    _write_json(review_dir / "product_loop_iteration_summary.json", summary)
    _write_text(review_dir / "product_loop_iteration_summary.md",
                _render_iteration_summary_md(summary))

    dashboard = {
        "phase": "2d0",
        "challenge_id": result["challenge_id"],
        "run_dir": f"runs/{run_dir.name}",
        "mode": mode,
        "prior_fitness_label": facts.get("prior_fitness_label"),
        "prior_fitness_qualifier": facts.get("prior_fitness_qualifier"),
        "autopilot_stage": result["autopilot_stage"],
        "autopilot_is_product_candidate": result["autopilot_stage"] == "PRODUCT_CANDIDATE",
        "next_lane": result["next_lane"],
        "autopilot_status": "auto_order generated" if ok else (result["failure_type"] or "FAIL"),
        "auto_order_status": result["auto_order_quality_status"] or "-",
        "auto_order_quality_score": result["auto_order_quality_score"],
        "repair_blueprint_status": ("generated / apply_allowed=false"
                                    if (review_dir / "repair_blueprint.json").is_file() else "-"),
        "stop_conditions": stop_conditions,
        "hash_status": hash_check["status"],
        "mock_loop_pass": summary["mock_loop_pass"],
    }
    _write_json(review_dir / "product_loop_dashboard_summary.json", dashboard)
    return result


def _render_iteration_summary_md(s: dict) -> str:
    L = ["# Product Loop Iteration Summary (Phase 2D-0)", "",
         f"- mode: {s['mode']} / gemma_mode: {s['gemma_mode']}",
         f"- status: **{s['status']}**",
         f"- prior_fitness_label: {s['prior_fitness_label']} ({s['prior_fitness_qualifier'] or '-'})",
         f"- autopilot_stage: **{s['autopilot_stage']}**",
         f"- primary_gap: {s['primary_gap']}",
         f"- recommended_next_lane: {s['recommended_next_lane']}",
         f"- auto_order_quality: {s['auto_order_quality_status']} ({s['auto_order_quality_score']})",
         f"- live_repair_apply: {s['live_repair_apply']} / repair_execute: {s['repair_execute']}",
         f"- schema_repair_used: {s['schema_repair_used']}",
         f"- mock_loop_executed: {s['mock_loop_executed']} (pass: {s['mock_loop_pass']})",
         f"- hardcode_guard: {s['hardcode_guard']} / hash: {s['hash_status']}",
         "", "## Iterations"]
    for it in s["iterations"]:
        L.append(f"- #{it['iteration']}: desk={it.get('desk_status')} stage={it.get('stage')} "
                 f"gap={it.get('primary_gap')} lane={it.get('lane')}"
                 + (f" failure={it['failure_type']}" if it.get("failure_type") else ""))
    L += ["", "## Stop conditions"]
    L += [f"- {c}" for c in s["stop_conditions"]] or ["- (없음)"]
    if s.get("problems"):
        L += ["", "## Problems"]
        L += [f"- {p}" for p in s["problems"]]
    return "\n".join(L) + "\n"
