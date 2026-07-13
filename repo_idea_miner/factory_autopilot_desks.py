# Phase 2D-0 Autopilot desk 실행기 — Gemma 프롬프트(정답/ID 미포함), mock desk, sequential/unified 공용 검증 래퍼 모듈.
from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

from repo_idea_miner.factory_autopilot_schemas import (
    AUTOPILOT_INFRA_FAIL,
    AUTOPILOT_INVALID_OUTPUT,
    GAP_TO_LANE,
    GAP_TYPES,
    LANE_POLICY,
    LANES,
    STAGE_RANK,
    classify_desk_failure,
    schema_repair_pass,
    validate_desk_output,
)
from repo_idea_miner.factory_desks import DeskError


class RawPassthrough(BaseModel):
    """LLM raw JSON을 그대로 받는 통과 모델 — strict 검증은 autopilot validator가 수행한다."""
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------- Desk 실행 래퍼 (§10, §11, §23)

def execute_desk(executor, schema_name: str, prompt: str, model_cls,
                 mock_output: dict | None = None) -> dict:
    """desk 1개를 실행하고 strict 검증 + schema repair 1회까지 처리한 결과를 돌려준다.

    반환: {status, model, raw, problems, failure_type, schema_repair_report}
    status: PASS | FAIL. FAIL이면 failure_type이 §23 분류다.
    """
    out = {"schema_name": schema_name, "status": "FAIL", "model": None, "raw": None,
           "problems": [], "failure_type": None, "schema_repair_report": None}
    if mock_output is not None:
        raw = mock_output
    else:
        try:
            model, _label = executor.call(schema_name, prompt, RawPassthrough)
            raw = model.model_dump()
        except DeskError as exc:
            if exc.kind in ("transient", "timeout", "exhausted", "auth"):
                out["failure_type"] = AUTOPILOT_INFRA_FAIL
            else:
                out["failure_type"] = AUTOPILOT_INVALID_OUTPUT
            out["problems"].append(str(exc))
            return out
    out["raw"] = raw

    model, problems = validate_desk_output(schema_name, raw, model_cls)
    if model is None:
        # schema repair pass 1회 (§11) — 구조만 고치고 의미는 바꾸지 않는다
        report = schema_repair_pass(raw, schema_name, model_cls)
        out["schema_repair_report"] = {k: v for k, v in report.items() if k != "model"}
        if report.get("meaning_changed"):
            out["problems"] = problems + report["problems"]
            out["failure_type"] = AUTOPILOT_INVALID_OUTPUT
            return out
        model = report.get("model")
        if model is None:
            out["problems"] = problems + report["problems"]
            out["failure_type"] = classify_desk_failure(out["problems"])
            return out
        out["raw"] = report.get("raw")
    out["model"] = model
    out["status"] = "PASS"
    return out


# ---------------------------------------------------------------- 프롬프트 (§15~§20)
# 주의: challenge_id/run_id/title/기대 정답은 절대 넣지 않는다 (§2, §12, §15.2).

_STAGE_RULES = """product stage 정의(사다리 순서):
- CORE_GREEN: core/golden/gate는 통과했지만 제품 표면이나 사용 경험은 약함.
- REVIEWABLE_ARTIFACT: 사람이 열어보고 기본 동작을 확인할 수 있음.
- POLISHABLE_PROTOTYPE: viewer/UI polish로 제품 후보로 키울 가능성이 있음.
- INTERACTION_CANDIDATE: 조작 UI는 있지만 사용자가 만든 입력을 runner/core로 실행하는 루프가 닫히지 않음.
- EXECUTION_CANDIDATE: 사용자가 만든 입력을 실행하고 결과를 볼 수 있음 (실패 이해/재수정 루프는 약할 수 있음).
- PRODUCT_CANDIDATE: 생성/편집/검증/실행/결과/수정/재실행 루프가 닫혔고 60초 안에 가치가 이해됨.
- ARCHIVE: green이어도 제품화 가치가 낮아 제외.

stage 판정 규칙:
- create + validate + export만 가능 → INTERACTION_CANDIDATE 이하.
- create + validate + execute + result 가능 → EXECUTION_CANDIDATE 가능.
- create + validate + execute + result + revise + rerun 가능 → PRODUCT_CANDIDATE 가능.
- hard blocker 결과(입력에 포함)는 절대 넘을 수 없다. max_stage를 초과하는 stage를 내지 마라."""

_EVIDENCE_RULES = """evidence_refs 규칙:
- 모든 판단(stage, not_product_reason, gap, lane)은 evidence_refs를 가져야 한다.
- evidence_refs는 아래 'available evidence refs' 목록에서 글자 그대로(verbatim) 골라야 한다. 새로 만들지 마라.
- not_product_reason은 최소 1개, primary_gap은 최소 2개의 evidence_refs가 필요하다."""

_OUTPUT_RULES = "출력은 JSON 객체 하나만. 설명 문장/마크다운/코드펜스 금지."

_HUMAN_DECISION_RULES = """human_decision_required 규칙 (semantic 결정 ≠ 승인):
- human_decision_required는 사람이 spec/golden/정책 의미를 선택해야 하는 unresolved semantic choice가 있을 때만 true다.
- requires_human_approval_before_apply(apply 전 승인 절차)를 human_decision_required로 복사하지 마라 — 둘은 다른 의미다.
- lane이 HOLD_FOR_HUMAN이 아니고 semantic 질문이 없으면 human_decision_required=false다."""


def _evidence_block(evidence: dict, quality: dict, hard: dict) -> str:
    facts = {k: v for k, v in (evidence.get("facts") or {}).items()
             if k not in ("product_file_snippets", "viewer_source")}
    parts = [
        "## artifact evidence (product loop)",
        json.dumps(evidence.get("product_loop") or {}, ensure_ascii=False, indent=1),
        "## artifact facts",
        json.dumps(facts, ensure_ascii=False, indent=1),
        "## user-facing quality evidence",
        json.dumps(quality.get("fields") or {}, ensure_ascii=False, indent=1),
        "## hard blocker result (판정 상한 — 넘을 수 없음)",
        json.dumps({"max_stage": hard.get("max_stage"),
                    "product_candidate_blocked": hard.get("product_candidate_blocked"),
                    "blockers": [b["rule"] for b in hard.get("blockers") or [] if b.get("triggered")]},
                   ensure_ascii=False, indent=1),
    ]
    snippets = (evidence.get("facts") or {}).get("product_file_snippets") or {}
    if snippets:
        parts.append("## product 주요 파일 snippet")
        for name, snip in snippets.items():
            parts.append(f"### {name}\n{snip[:1200]}")
    parts.append("## available evidence refs (이 목록에서만 verbatim 선택)")
    parts += [f"- {r}" for r in sorted(evidence.get("known_refs") or [])]
    return "\n".join(parts)


def build_judge_prompt(evidence: dict, quality: dict, hard: dict) -> str:
    return f"""너는 Product Factory의 Product Judge다.
green artifact의 실제 evidence를 읽고 현재 product stage를 판정한다. 요약문이 아니라 evidence로만 판단한다.

{_STAGE_RULES}

{_EVIDENCE_RULES}

{_OUTPUT_RULES}
필수 필드: stage(위 stage 중 하나), is_product_candidate(bool), confidence(high|medium|low),
evidence_refs(list), not_product_reasons(list of {{reason, evidence_refs}}),
product_loop_evidence(입력의 product loop 값을 그대로 반영),
user_facing_quality_evidence(입력의 quality 값을 그대로 반영),
hard_blockers_applied(적용된 blocker 문장 list), missing_loop_parts(list).

{_evidence_block(evidence, quality, hard)}
"""


def build_gap_prompt(evidence: dict, quality: dict, hard: dict, stage_label: dict) -> str:
    return f"""너는 Product Factory의 Gap Classifier다.
이 artifact가 아직 제품 후보가 아닌 이유를 gap으로 분류하고, 이번 iteration에서 고칠 primary_gap 하나만 고른다.

허용 gap types: {", ".join(GAP_TYPES)}
원칙: 한 루프에 하나의 주요 결함만 고친다. stage가 PRODUCT_CANDIDATE 또는 ARCHIVE면 primary_gap은 null이다.

{_EVIDENCE_RULES}

{_OUTPUT_RULES}
필수 필드: gaps(list of {{type, severity(blocking|major|minor), evidence_refs, explanation}}),
primary_gap(gap type 또는 null), primary_gap_evidence_refs(최소 2개), primary_gap_reason.

## Product Judge 판정 (참고)
{json.dumps({k: stage_label.get(k) for k in ("stage", "missing_loop_parts", "not_product_reasons")}, ensure_ascii=False, indent=1)}

{_evidence_block(evidence, quality, hard)}
"""


def build_lane_prompt(evidence: dict, gap: dict) -> str:
    policy_text = json.dumps(LANE_POLICY, ensure_ascii=False, indent=1)
    return f"""너는 Product Factory의 Next Lane Planner다.
primary_gap을 해결할 다음 productization lane 하나를 고른다.

허용 lanes: {", ".join(LANES)}
gap → lane 매핑 규칙: {json.dumps(GAP_TO_LANE, ensure_ascii=False)}
lane risk policy (출력의 lane_risk/dry_run_allowed/auto_execute_allowed/requires_human_approval_before_apply는
이 정책 값을 그대로 써야 한다):
{policy_text}

{_HUMAN_DECISION_RULES}

{_EVIDENCE_RULES}
추가 규칙: evidence_refs에 primary_gap evidence_refs 중 최소 1개를 포함하라.

{_OUTPUT_RULES}
필수 필드: recommended_next_lane, reason, evidence_refs, lane_risk, dry_run_allowed,
auto_execute_allowed, requires_human_approval_before_apply, allowed_file_scopes,
protected_file_scopes, human_decision_required(bool).

## Gap Classification
{json.dumps(gap, ensure_ascii=False, indent=1)}

## available evidence refs (이 목록에서만 verbatim 선택)
{chr(10).join("- " + r for r in sorted(evidence.get("known_refs") or []))}
"""


def build_order_prompt(evidence: dict, gap: dict, lane: dict, template: dict) -> str:
    return f"""너는 Product Factory의 Scoped Order Writer다.
선택된 lane의 lane template 빈칸(slots)을 evidence 기반으로 채운다. 주문서 전체 구조를 새로 발명하지 마라.

lane: {lane.get("recommended_next_lane")}
lane template 기본값 (allowed/protected scopes와 forbidden actions는 이 값을 포함해야 한다):
{json.dumps({k: template.get(k) for k in ("title", "allowed_scopes", "protected_scopes", "forbidden_actions", "expected_patch_shape")}, ensure_ascii=False, indent=1)}

{_EVIDENCE_RULES}

{_OUTPUT_RULES}
필수 필드: background, observed_gap, evidence_refs, allowed_scopes, protected_scopes,
forbidden_actions, concrete_acceptance_tests(구체적 검증 항목 list), expected_outputs,
stop_conditions, report_format(보고 항목 list), repair_actions(비워도 됨: []).

## Gap / Lane
{json.dumps({"primary_gap": gap.get("primary_gap"), "primary_gap_reason": gap.get("primary_gap_reason"), "lane": lane.get("recommended_next_lane")}, ensure_ascii=False, indent=1)}

## available evidence refs (이 목록에서만 verbatim 선택)
{chr(10).join("- " + r for r in sorted(evidence.get("known_refs") or []))}
"""


def build_blueprint_prompt(evidence: dict, gap: dict, lane: dict, template: dict) -> str:
    return f"""너는 Product Factory의 Repair Blueprint Writer다.
다음 lane 수리를 '어떻게 고칠 것인가'까지 설계한다. 단, 이 blueprint는 적용되지 않는다(blueprint only).

lane: {lane.get("recommended_next_lane")}
lane template 기대 patch shape: {json.dumps(template.get("expected_patch_shape"), ensure_ascii=False)}
규칙:
- apply_allowed는 반드시 false다 (live artifact repair apply 금지).
- expected_changed_file_scopes는 lane allowed scopes 안에서만 제안한다.
- protected_file_scopes는 절대 수정 제안하지 않는다.

{_EVIDENCE_RULES}

{_OUTPUT_RULES}
필수 필드: target_lane, observed_gap, evidence_refs, apply_allowed(false), purpose,
proposed_implementation_approach, expected_changed_file_scopes, protected_file_scopes,
expected_patch_shape, tests_to_run(list), rollback_conditions, failure_conditions,
product_candidate_overclaim_guards(과대평가 방지 조건 list).

## Gap / Lane / Scopes
{json.dumps({"primary_gap": gap.get("primary_gap"), "lane": lane.get("recommended_next_lane"), "allowed_scopes": template.get("allowed_scopes"), "protected_scopes": template.get("protected_scopes")}, ensure_ascii=False, indent=1)}

## available evidence refs (이 목록에서만 verbatim 선택)
{chr(10).join("- " + r for r in sorted(evidence.get("known_refs") or []))}
"""


def build_unified_prompt(evidence: dict, quality: dict, hard: dict, template_by_lane: dict) -> str:
    return f"""너는 Product Factory의 Productization Autopilot이다.
한 번의 응답으로 unified decision packet을 생성한다: product_stage_label, product_gap_classification,
recommended_next_lane, repair_blueprint, auto_order_slots, scope_guard_draft.

{_STAGE_RULES}

허용 gap types: {", ".join(GAP_TYPES)}
허용 lanes: {", ".join(LANES)}
gap → lane 매핑: {json.dumps(GAP_TO_LANE, ensure_ascii=False)}
lane risk policy(그대로 사용): {json.dumps(LANE_POLICY, ensure_ascii=False)}
repair_blueprint.apply_allowed는 반드시 false다.

{_HUMAN_DECISION_RULES}

{_EVIDENCE_RULES}

{_OUTPUT_RULES}
최상위 필드: product_stage_label, product_gap_classification, recommended_next_lane,
repair_blueprint, auto_order_slots, scope_guard_draft.

{_evidence_block(evidence, quality, hard)}
"""


# ---------------------------------------------------------------- Mock desks (mock 모드 / mock loop proof용)
# 어떤 challenge_id/run_id/title도 보지 않는다 — 판정 기준은 product loop evidence다 (§12).

def _ref(evidence: dict, name: str) -> str | None:
    return (evidence.get("refs") or {}).get(name)


def _refs(evidence: dict, *names: str) -> list[str]:
    out = []
    for n in names:
        r = _ref(evidence, n)
        if r and r not in out:
            out.append(r)
    return out


def derive_stage_from_evidence(evidence: dict, quality: dict, hard: dict) -> str:
    """evidence ladder + hard blocker 상한으로 stage를 결정한다 (mock judge의 핵심)."""
    facts = evidence.get("facts") or {}
    loop = evidence.get("product_loop") or {}
    q = quality.get("fields") or {}
    if facts.get("archive_recommended"):
        return "ARCHIVE"
    if not facts.get("viewer_exists"):
        stage = "CORE_GREEN"
    elif facts.get("mismatches") or not facts.get("viewer_reads_replay"):
        stage = "REVIEWABLE_ARTIFACT"
    elif not facts.get("authoring_ui"):
        stage = "POLISHABLE_PROTOTYPE"
    elif not loop.get("can_execute_primary_action"):
        stage = "INTERACTION_CANDIDATE"
    elif not loop.get("product_loop_closed"):
        stage = "EXECUTION_CANDIDATE"
    elif all(q.get(k) for k in ("first_screen_understandable", "clear_next_action",
                                "has_example_or_seed_data", "success_feedback_visible",
                                "failure_feedback_visible", "user_can_understand_value_in_60s")):
        stage = "PRODUCT_CANDIDATE"
    else:
        stage = "EXECUTION_CANDIDATE"
    max_stage = hard.get("max_stage")
    if max_stage in STAGE_RANK and STAGE_RANK.get(stage, 0) > STAGE_RANK[max_stage]:
        stage = max_stage
    return stage


_MISSING_PART_BY_FIELD = {
    "can_execute_primary_action": "runner_backed_execution",
    "can_observe_state_change": "result_from_edited_input",
    "can_understand_failure": "failure_understanding",
    "can_revise_and_retry": "revise_and_rerun",
}


def mock_product_judge(evidence: dict, quality: dict, hard: dict) -> dict:
    loop = evidence.get("product_loop") or {}
    facts = evidence.get("facts") or {}
    stage = derive_stage_from_evidence(evidence, quality, hard)
    missing = [part for field, part in _MISSING_PART_BY_FIELD.items() if not loop.get(field)]

    ev_refs = _refs(evidence, "loop.can_execute_primary_action", "loop.product_loop_closed")
    if facts.get("runner_backed_execution_included") is not None:
        ev_refs += _refs(evidence, "editor.runner_backed_execution_included")
    if not ev_refs:
        ev_refs = list(sorted(evidence.get("known_refs") or []))[:2]

    reasons = []
    if stage not in ("PRODUCT_CANDIDATE", "ARCHIVE"):
        if not loop.get("can_execute_primary_action"):
            reasons.append({
                "reason": "Edited draft cannot yet be executed by runner/core.",
                "evidence_refs": _refs(evidence, "loop.can_execute_primary_action",
                                       "editor.runner_backed_execution_included") or ev_refs[:1],
            })
        elif not loop.get("product_loop_closed"):
            reasons.append({
                "reason": "Product loop (revise and rerun) is not closed yet.",
                "evidence_refs": _refs(evidence, "loop.product_loop_closed",
                                       "loop.can_revise_and_retry") or ev_refs[:1],
            })
        elif not facts.get("viewer_exists"):
            reasons.append({"reason": "No product viewer surface.",
                            "evidence_refs": _refs(evidence, "facts.viewer_exists") or ev_refs[:1]})
        elif facts.get("mismatches"):
            reasons.append({"reason": "Viewer field mapping does not match replay schema.",
                            "evidence_refs": _refs(evidence, "facts.viewer_reads_replay",
                                                   "facts.mismatch_count") or ev_refs[:1]})
        elif not facts.get("authoring_ui"):
            reasons.append({"reason": "No interactive authoring UI.",
                            "evidence_refs": _refs(evidence, "facts.authoring_ui") or ev_refs[:1]})
        else:
            reasons.append({"reason": "Product feel is not strong enough for a product candidate.",
                            "evidence_refs": ev_refs[:1]})
    return {
        "stage": stage,
        "is_product_candidate": stage == "PRODUCT_CANDIDATE",
        "confidence": "low" if not facts.get("evidence_sufficient", True) else "high",
        "evidence_refs": ev_refs,
        "not_product_reasons": reasons,
        "product_loop_evidence": dict(loop),
        "user_facing_quality_evidence": dict(quality.get("fields") or {}),
        "hard_blockers_applied": [b["rule"] for b in hard.get("blockers") or [] if b.get("triggered")],
        "missing_loop_parts": missing,
    }


def derive_primary_gap(evidence: dict, quality: dict, stage_label: dict) -> str | None:
    """evidence ladder로 primary gap을 결정한다 — ID/title은 보지 않는다."""
    facts = evidence.get("facts") or {}
    loop = evidence.get("product_loop") or {}
    q = quality.get("fields") or {}
    stage = stage_label.get("stage")
    if stage in ("PRODUCT_CANDIDATE",):
        return None
    if not facts.get("evidence_sufficient", True):
        return "EVIDENCE_INSUFFICIENT"
    if stage == "ARCHIVE" or facts.get("archive_recommended"):
        return "ARCHIVE_RECOMMENDED"
    if facts.get("verdict") == "SPEC_REPAIR_REQUIRED":
        return "SPEC_REPAIR_REQUIRED"
    # green_base 부재만으로는 core 결함 근거가 아니다 — gate가 전부 PASS인 미승격 run
    # (KEEP_CANDIDATE류)을 CORE_PATCH로 오진해 고칠 것 없는 patch lane을 반복하게 된다.
    if facts.get("gate_fail"):
        return "CORE_PATCH_REQUIRED"
    if facts.get("runner_executable") is False:
        return "RUNNER_PATCH_REQUIRED"
    if not facts.get("viewer_exists") or facts.get("mismatches") or not facts.get("viewer_reads_replay"):
        return "VIEWER_POLISH_REQUIRED"
    if not facts.get("authoring_ui"):
        return "INTERACTION_UI_REQUIRED"
    if not loop.get("can_execute_primary_action"):
        return "RUNNER_BACKED_EXECUTION_REQUIRED"
    # 이슈 #6 §10.2: interaction UI(draft)는 있는데 실행 계열 report(2c3/generic draft execution)가
    # 없으면 draft 실행이 아직 lane으로 실증되지 않은 것 — probe의 fixture 실행만으로는 이 gap을
    # 닫지 않는다. editor 기록 기반 graph 경로는 불변이다 (CANON-07 재요구 금지).
    if facts.get("has_interaction_report") and not facts.get("has_execution_report"):
        return "RUNNER_BACKED_EXECUTION_REQUIRED"
    if not loop.get("product_loop_closed") or not q.get("user_can_understand_value_in_60s"):
        return "UX_POLISH_REQUIRED"
    # 이슈 #8 §12.4: UX rung은 machine-checkable UX 실증(진단→bounded operation→검증)이
    # 있어야만 닫힌다 — loop/60s 지표만으로 UX 결함(viewport/keyboard/feedback)을 덮지 않는다.
    if not facts.get("has_ux_polish_report"):
        return "UX_POLISH_REQUIRED"
    # UX 실증까지 있으면 남은 것은 요구사항 coverage/사람 결정 레벨 — lane으로 보낼 gap이 없다.
    return None


_GAP_REFS = {
    "RUNNER_BACKED_EXECUTION_REQUIRED": ("loop.can_execute_primary_action",
                                         "editor.runner_backed_execution_included",
                                         "loop.product_loop_closed"),
    "INTERACTION_UI_REQUIRED": ("facts.authoring_ui", "loop.can_create_or_modify_input"),
    "VIEWER_POLISH_REQUIRED": ("facts.mismatch_count", "facts.viewer_reads_replay",
                               "facts.viewer_exists"),
    "UX_POLISH_REQUIRED": ("quality.user_can_understand_value_in_60s", "loop.product_loop_closed",
                           "facts.has_ux_polish_report"),
    "CORE_PATCH_REQUIRED": ("facts.green_base", "facts.gate_fail"),
    "RUNNER_PATCH_REQUIRED": ("facts.runner_executable", "facts.green_base"),
    "SPEC_REPAIR_REQUIRED": ("facts.verdict", "facts.green_base"),
    "EVIDENCE_INSUFFICIENT": ("facts.evidence_sufficient", "facts.viewer_exists"),
    "ARCHIVE_RECOMMENDED": ("facts.archive_recommended", "facts.viewer_exists"),
    "SCOPE_CREEP_RISK": ("facts.evidence_sufficient", "facts.viewer_exists"),
}

_GAP_REASONS = {
    "RUNNER_BACKED_EXECUTION_REQUIRED": "The user can create and export a draft, but cannot execute it.",
    "INTERACTION_UI_REQUIRED": "The viewer shows results but the user cannot author a graph.",
    "VIEWER_POLISH_REQUIRED": "The viewer does not faithfully render the replay schema.",
    "UX_POLISH_REQUIRED": "The loop runs but the product value is not understandable fast enough.",
    "CORE_PATCH_REQUIRED": "Core gates or green base are not satisfied.",
    "RUNNER_PATCH_REQUIRED": "The runner could not be executed successfully.",
    "SPEC_REPAIR_REQUIRED": "Spec/golden verification criteria are wrong.",
    "EVIDENCE_INSUFFICIENT": "There is not enough artifact evidence to judge product stage.",
    "ARCHIVE_RECOMMENDED": "Green but the productization value is low.",
    "SCOPE_CREEP_RISK": "The next repair would exceed a safe scope.",
}


def mock_gap_classifier(evidence: dict, quality: dict, stage_label: dict) -> dict:
    primary = derive_primary_gap(evidence, quality, stage_label)
    if primary is None:
        return {"gaps": [], "primary_gap": None, "primary_gap_evidence_refs": [],
                "primary_gap_reason": None}
    refs = _refs(evidence, *_GAP_REFS.get(primary, ()))
    if len(refs) < 2:
        refs = (refs + sorted(evidence.get("known_refs") or []))[:2]
    severity = "blocking" if primary not in ("UX_POLISH_REQUIRED",) else "major"
    return {
        "gaps": [{"type": primary, "severity": severity, "evidence_refs": refs,
                  "explanation": _GAP_REASONS.get(primary, primary)}],
        "primary_gap": primary,
        "primary_gap_evidence_refs": refs,
        "primary_gap_reason": _GAP_REASONS.get(primary, primary),
    }


# boolean fact에서 직접 유도되는 rung — 여기서는 live desk의 판단 여지가 없다 (§7).
HARD_EVIDENCE_GAPS = (
    "EVIDENCE_INSUFFICIENT",
    "ARCHIVE_RECOMMENDED",
    "SPEC_REPAIR_REQUIRED",
    "CORE_PATCH_REQUIRED",
    "RUNNER_PATCH_REQUIRED",
)


def viewer_fault_facts(evidence: dict) -> dict:
    """gap override 기록용 machine-checkable viewer fact 요약 (이슈 #24 §4.4)."""
    facts = (evidence or {}).get("facts") or {}
    return {
        "viewer_exists": bool(facts.get("viewer_exists")),
        "viewer_reads_replay": bool(facts.get("viewer_reads_replay")),
        "mismatch_count": len(facts.get("mismatches") or []),
    }


def is_machine_checkable_viewer_fault(evidence: dict) -> bool:
    """artifact에서 직접 검증 가능한 objective viewer fault 여부 (이슈 #24 §4.1).

    viewer 부재 / replay 미연결 / viewer-replay field mismatch만 fault다.
    미관·제품 느낌·CTA 문구·mismatch 없는 60초 이해성 부족 같은 주관 판정은
    이 함수의 입력(facts boolean/count)에 존재하지 않으므로 승격될 수 없다.
    """
    vf = viewer_fault_facts(evidence)
    return (not vf["viewer_exists"]) or (not vf["viewer_reads_replay"]) \
        or vf["mismatch_count"] > 0


def enforce_evidence_ladder(gap: dict | None, evidence: dict, quality: dict,
                            stage_label: dict) -> tuple[dict | None, dict | None]:
    """hard fact rung은 live desk의 gap 판정보다 우선한다 (§7: 관측이 서술을 이긴다).

    deterministic ladder가 hard rung(gate 실패, runner 실행 불가 등)을 지시하는데
    live gap이 다르면 deterministic 분류로 교체하고 override 기록을 함께 돌려준다.

    이슈 #24 §4.1~4.2: objective viewer fault(viewer 부재/replay 미연결/field mismatch —
    전부 artifact에서 직접 확인)가 있고 ladder가 VIEWER_POLISH_REQUIRED를 지시하면,
    live desk의 파생 증상 판정(UX_POLISH_REQUIRED 등)도 root cause로 교체한다.
    viewer fault가 없는 interaction/UX 같은 판단 rung은 desk 판정을 존중한다.
    """
    ladder = derive_primary_gap(evidence, quality, stage_label)
    live = (gap or {}).get("primary_gap")
    if ladder is None or live == ladder:
        return gap, None
    if ladder in HARD_EVIDENCE_GAPS:
        enforced = mock_gap_classifier(evidence, quality, stage_label)
        override = {
            "live_gap": live,
            "deterministic_gap": ladder,
            "enforced_gap": ladder,
            "override_kind": "HARD_EVIDENCE_RUNG",
            "reason": "deterministic evidence ladder가 hard rung을 지시 — live desk 판정을 override",
            "evidence_refs": list(enforced.get("primary_gap_evidence_refs") or []),
        }
        return enforced, override
    if ladder == "VIEWER_POLISH_REQUIRED" and is_machine_checkable_viewer_fault(evidence):
        enforced = mock_gap_classifier(evidence, quality, stage_label)
        override = {
            "live_gap": live,
            "deterministic_gap": ladder,
            "enforced_gap": ladder,
            "override_kind": "OBJECTIVE_VIEWER_FAULT",
            "reason": "machine-checkable viewer fault outranks derived UX symptom",
            "viewer_faults": viewer_fault_facts(evidence),
            "evidence_refs": list(enforced.get("primary_gap_evidence_refs") or []),
        }
        return enforced, override
    return gap, None


def mock_next_lane_planner(evidence: dict, gap: dict) -> dict:
    primary = gap.get("primary_gap")
    lane = GAP_TO_LANE.get(primary, "HOLD_FOR_HUMAN") if primary else "ARCHIVE"
    policy = LANE_POLICY[lane]
    from repo_idea_miner.factory_autopilot_schemas import LANE_TEMPLATES

    template = LANE_TEMPLATES.get(lane) or {}
    refs = list(gap.get("primary_gap_evidence_refs") or [])[:2] or \
        sorted(evidence.get("known_refs") or [])[:1]
    return {
        "recommended_next_lane": lane,
        "reason": gap.get("primary_gap_reason") or f"Next lane for {primary or 'no gap'}.",
        "evidence_refs": refs,
        "lane_risk": policy["lane_risk"],
        "dry_run_allowed": policy["dry_run_allowed"],
        "auto_execute_allowed": policy["auto_execute_allowed"],
        "requires_human_approval_before_apply": policy["requires_human_approval_before_apply"],
        "allowed_file_scopes": list(template.get("allowed_scopes") or []),
        "protected_file_scopes": list(template.get("protected_scopes") or []),
        "human_decision_required": lane == "HOLD_FOR_HUMAN",
    }


def _mismatch_repair_actions(evidence: dict) -> list[dict]:
    """viewer 필드 mismatch에서 기계 실행 가능한 교체 액션을 만든다 (mock/safe VIEWER_POLISH lane)."""
    facts = evidence.get("facts") or {}
    viewer_rel = facts.get("viewer_path")
    if not viewer_rel:
        return []
    actions = []
    pairs = (("edge.from", "edge.source_id"), ("edge.to", "edge.target_id"),
             ("ev.type", "ev.event"), ("ev.message", "JSON.stringify(ev)"))
    viewer_src = facts.get("viewer_source") or ""
    for find, replace in pairs:
        if find in viewer_src:
            actions.append({"action": "replace_in_file", "file": viewer_rel,
                            "find": find, "replace": replace})
    return actions


def mock_order_slots(evidence: dict, gap: dict, lane: dict, template: dict) -> dict:
    primary = gap.get("primary_gap") or "no primary gap"
    refs = list(gap.get("primary_gap_evidence_refs") or []) or \
        sorted(evidence.get("known_refs") or [])[:2]
    lane_name = lane.get("recommended_next_lane")
    repair_actions = _mismatch_repair_actions(evidence) if lane_name == "VIEWER_POLISH" else []
    return {
        "background": (f"Autopilot이 evidence 기반으로 primary gap {primary}을 선택했다. "
                       f"이 주문은 {lane_name} lane template의 빈칸을 채운 scoped order다."),
        "observed_gap": gap.get("primary_gap_reason") or primary,
        "evidence_refs": refs,
        "allowed_scopes": list(template.get("allowed_scopes") or []),
        "protected_scopes": list(template.get("protected_scopes") or []),
        "forbidden_actions": list(template.get("forbidden_actions") or []),
        "concrete_acceptance_tests": list(template.get("acceptance_tests") or []),
        "expected_outputs": list(template.get("expected_outputs") or []),
        "stop_conditions": [
            "protected scope 수정 감지 시 중단",
            "smoke/validate 실패 시 중단",
            "auto_order_quality_score < 0.85 시 HOLD_FOR_HUMAN",
        ],
        "report_format": ["수정 파일", "보호 대상 hash 검사", "smoke/gate", "validate",
                          "stage 재판정", "PRODUCT_CANDIDATE 과대평가 방지 조건"],
        "repair_actions": repair_actions,
    }


def mock_repair_blueprint(evidence: dict, gap: dict, lane: dict, template: dict) -> dict:
    primary = gap.get("primary_gap") or "no primary gap"
    refs = list(gap.get("primary_gap_evidence_refs") or []) or \
        sorted(evidence.get("known_refs") or [])[:2]
    shape = list(template.get("expected_patch_shape") or ["scoped repair"])
    return {
        "target_lane": lane.get("recommended_next_lane"),
        "observed_gap": gap.get("primary_gap_reason") or primary,
        "evidence_refs": refs,
        "apply_allowed": False,
        "purpose": "Blueprint only for the next lane order. Not applied to the live artifact.",
        "proposed_implementation_approach": (
            f"{lane.get('recommended_next_lane')} lane template에 따라 "
            f"{', '.join(shape)} 순서로 구현한다. 보호 대상 scope는 수정하지 않는다."),
        "expected_changed_file_scopes": list(template.get("allowed_scopes") or []),
        "protected_file_scopes": list(template.get("protected_scopes") or []),
        "expected_patch_shape": shape,
        "tests_to_run": [f"{s} 검증" for s in shape],
        "rollback_conditions": ["보호 대상 hash 변경 감지", "smoke/gate FAIL", "validate FAIL"],
        "failure_conditions": ["repair 후에도 primary gap evidence가 남음",
                               "protected scope 수정이 필요해짐"],
        "product_candidate_overclaim_guards": [
            "runner-backed execution 실증 없이 PRODUCT_CANDIDATE 금지",
            "edit→validate→execute→result→revise smoke 통과 없이 PRODUCT_CANDIDATE 금지",
            "user_can_understand_value_in_60s=false면 PRODUCT_CANDIDATE 금지",
        ],
    }


def mock_unified_packet(evidence: dict, quality: dict, hard: dict) -> dict:
    """unified_decision_packet mode의 mock 출력 (§20) — sequential과 같은 파생 로직."""
    from repo_idea_miner.factory_autopilot_schemas import LANE_TEMPLATES

    stage_label = mock_product_judge(evidence, quality, hard)
    gap = mock_gap_classifier(evidence, quality, stage_label)
    lane = mock_next_lane_planner(evidence, gap)
    template = LANE_TEMPLATES.get(lane["recommended_next_lane"]) or {}
    slots = mock_order_slots(evidence, gap, lane, template)
    blueprint = mock_repair_blueprint(evidence, gap, lane, template)
    scope_guard = {
        "lane": lane["recommended_next_lane"],
        "allowed_scopes": slots["allowed_scopes"],
        "protected_scopes": slots["protected_scopes"],
        "forbidden_actions": slots["forbidden_actions"],
    }
    return {
        "product_stage_label": stage_label,
        "product_gap_classification": gap,
        "recommended_next_lane": lane,
        "repair_blueprint": blueprint,
        "auto_order_slots": slots,
        "scope_guard_draft": scope_guard,
    }
