# Phase 2D-1 §8~§9: Product Acceptance Gate와 iteration 전후 Progress Comparison (승인안: 한 모듈로 병합).
from __future__ import annotations

import json
from pathlib import Path

from repo_idea_miner.factory_autopilot_schemas import STAGE_RANK
from repo_idea_miner.factory_core_schemas import CORE_GATE_ORDER
from repo_idea_miner.factory_product_capabilities import normalize_loop_evidence

# PRODUCT_CANDIDATE에 요구되는 acceptance 체크 이름 (§8)
ACCEPTANCE_CHECKS = (
    "core_gates_all_pass",
    "factory_validate_pass",
    "post_product_anti_hardcode_pass",
    "mock_fallback_zero",
    "protected_hash_pass",
    "critical_requirement_coverage_full",
    "difficulty_anchor_coverage_full",
    "forbidden_simplification_zero",
    "product_loop_closed",
    "success_scenarios_min2",
    "failure_scenarios_min1",
    "revise_and_rerun_changed",
    "first_screen_cta_present",
    "feedback_actually_visible",
)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- requirement coverage (§8, §1-12)

def build_requirement_coverage(run_dir: str | Path, judge_coverage: dict | None = None) -> dict:
    """원 주문서 critical requirement/difficulty anchor/금지 단순화 coverage를 만든다.

    항목별 판정은 정적으로 일반화할 수 없으므로 judge_coverage(desk 판정, evidence_refs 포함)를
    받는다. 판정이 없는 항목은 unknown — coverage에 산입하지 않는다 (보수적: 과대평가 금지 §1-12).
    """
    run_dir = Path(run_dir)
    normalized = _load_json(run_dir / "normalized_challenge.json") or {}
    judged = {str(k): v for k, v in (judge_coverage or {}).items()}

    def _section(items: list, kind: str) -> dict:
        rows = []
        covered = 0
        for item in items:
            item = str(item)
            status = str(judged.get(item, {}).get("status", "unknown")) \
                if isinstance(judged.get(item), dict) else str(judged.get(item, "unknown"))
            if status not in ("implemented", "missing", "violated", "unknown", "respected"):
                status = "unknown"
            ok = status in ("implemented", "respected")
            covered += 1 if ok else 0
            rows.append({"requirement": item, "kind": kind, "status": status,
                         "evidence_refs": (judged.get(item) or {}).get("evidence_refs", [])
                         if isinstance(judged.get(item), dict) else []})
        coverage = (covered / len(items)) if items else 1.0
        return {"items": rows, "coverage": round(coverage, 4), "total": len(items),
                "covered": covered}

    critical = _section(normalized.get("success_conditions") or [], "critical_requirement")
    anchors = _section(normalized.get("difficulty_anchors") or [], "difficulty_anchor")
    forbidden_items = normalized.get("forbidden_simplifications") or []
    violations = [str(i) for i in forbidden_items
                  if isinstance(judged.get(str(i)), dict)
                  and judged[str(i)].get("status") == "violated"]
    return {
        "critical_requirement_coverage": critical["coverage"],
        "critical_requirements": critical["items"],
        "difficulty_anchor_coverage": anchors["coverage"],
        "difficulty_anchors": anchors["items"],
        "forbidden_simplification_violations": violations,
        "forbidden_simplification_violation_count": len(violations),
        "judged_by": "judge_desk" if judge_coverage else "none(unknown 처리)",
    }


# ---------------------------------------------------------------- acceptance gate (§8)

def evaluate_product_acceptance(
    run_dir: str | Path,
    probe_report: dict,
    gate_summary: dict,
    validate_ok: bool,
    post_anti_hardcode_status: str | None,
    protected_hash_status: str | None,
    requirement_coverage: dict,
    loop_evidence: dict,
    quality_fields: dict | None = None,
) -> dict:
    """PRODUCT_CANDIDATE acceptance를 §8 항목 전부로 판정한다.

    하나라도 미충족이면 stage 상한을 EXECUTION_CANDIDATE/POLISHABLE_PROTOTYPE로 제한한다.
    """
    loop = normalize_loop_evidence(loop_evidence or {})
    q = quality_fields or {}
    rc = requirement_coverage or {}
    checks = {
        "core_gates_all_pass": all(bool(gate_summary.get(g)) for g in CORE_GATE_ORDER),
        "factory_validate_pass": bool(validate_ok),
        "post_product_anti_hardcode_pass": post_anti_hardcode_status == "PASS",
        "mock_fallback_zero": probe_report.get("mock_fallback_count") == 0,
        "protected_hash_pass": protected_hash_status == "PASS",
        "critical_requirement_coverage_full":
            rc.get("critical_requirement_coverage") == 1.0,
        "difficulty_anchor_coverage_full": rc.get("difficulty_anchor_coverage") == 1.0,
        "forbidden_simplification_zero":
            rc.get("forbidden_simplification_violation_count") == 0,
        "product_loop_closed": loop.get("product_loop_closed") is True,
        "success_scenarios_min2": probe_report.get("success_scenarios_passed", 0) >= 2,
        "failure_scenarios_min1": probe_report.get("failure_scenarios_passed", 0) >= 1,
        "revise_and_rerun_changed": probe_report.get("revise_and_rerun_changed") is True,
        # CTA/피드백: probe의 정적 근거(§7-7·10) + quality evidence를 함께 요구.
        # 이슈 #22: UX_POLISH가 실증한 실제 CTA(요소·표시·클릭·계약 action 연결)가 있으면
        # 그것이 정본 근거 — 없으면 기존 proxy 판정 그대로 (기존 acceptance 계산 불변).
        "first_screen_cta_present": bool(q.get("first_screen_cta_evidence"))
        or (bool(probe_report.get("critical_flow_handlers_ok"))
            and bool(q.get("first_screen_understandable", True))
            and bool(q.get("clear_next_action", True))),
        "feedback_actually_visible": bool(probe_report.get("viewer_static_ok"))
        and bool(q.get("success_feedback_visible", True))
        and bool(q.get("failure_feedback_visible", True)),
    }
    failed = [name for name in ACCEPTANCE_CHECKS if not checks[name]]
    passed_count = len(ACCEPTANCE_CHECKS) - len(failed)
    accepted = not failed
    # §8 하한: critical requirement 미충족이면 최대 EXECUTION_CANDIDATE,
    # product loop 자체가 안 닫혔으면 POLISHABLE_PROTOTYPE까지로 본다.
    if accepted:
        max_stage = "PRODUCT_CANDIDATE"
    elif checks["product_loop_closed"]:
        max_stage = "EXECUTION_CANDIDATE"
    else:
        max_stage = "POLISHABLE_PROTOTYPE"
    return {
        "status": "PASS" if accepted else "FAIL",
        "product_candidate_allowed": accepted,
        "max_stage": max_stage,
        "checks": checks,
        "failed_checks": failed,
        "passed_count": passed_count,
        "total_count": len(ACCEPTANCE_CHECKS),
    }


# ---------------------------------------------------------------- progress vector + 비교 (§9)

def build_progress_vector(
    stage: str | None,
    gate_summary: dict,
    acceptance: dict,
    hard_blocker_count: int,
    requirement_coverage: dict,
    loop_evidence: dict,
    probe_report: dict,
    regression_count: int = 0,
) -> dict:
    loop = normalize_loop_evidence(loop_evidence or {})
    rc = requirement_coverage or {}
    return {
        "stage_rank": STAGE_RANK.get(stage or "", -1),
        "stage": stage,
        "core_gates_passed": sum(1 for g in CORE_GATE_ORDER if gate_summary.get(g)),
        "product_acceptance_passed": int(acceptance.get("passed_count") or 0),
        "hard_blocker_count": int(hard_blocker_count),
        "critical_requirement_coverage": float(rc.get("critical_requirement_coverage") or 0.0),
        "difficulty_anchor_coverage": float(rc.get("difficulty_anchor_coverage") or 0.0),
        "product_loop_parts_passed": sum(1 for k, v in loop.items()
                                         if k != "product_loop_closed" and v is True),
        "success_scenarios_passed": int(probe_report.get("success_scenarios_passed") or 0),
        "failure_scenarios_passed": int(probe_report.get("failure_scenarios_passed") or 0),
        "mock_fallback_count": int(probe_report.get("mock_fallback_count") or 0),
        "regression_count": int(regression_count),
    }


def count_regressions(before: dict, after: dict,
                      gate_before: dict | None = None, gate_after: dict | None = None) -> dict:
    """기존 PASS가 FAIL로 뒤집힌 항목을 센다 (§9 회귀 판정)."""
    regressions: list[str] = []
    for g in CORE_GATE_ORDER:
        if (gate_before or {}).get(g) and not (gate_after or {}).get(g):
            regressions.append(f"gate:{g} PASS→FAIL")
    for key in ("success_scenarios_passed", "failure_scenarios_passed"):
        if int(after.get(key) or 0) < int(before.get(key) or 0):
            regressions.append(f"probe:{key} {before.get(key)}→{after.get(key)}")
    if int(after.get("mock_fallback_count") or 0) > int(before.get("mock_fallback_count") or 0):
        regressions.append(
            f"mock_fallback_count {before.get('mock_fallback_count')}→{after.get('mock_fallback_count')}")
    return {"count": len(regressions), "items": regressions}


_IMPROVEMENT_KEYS = (
    ("stage_rank", "stage rank 상승"),
    ("product_acceptance_passed", "product acceptance 통과 수 증가"),
    ("critical_requirement_coverage", "critical requirement coverage 증가"),
    ("difficulty_anchor_coverage", "difficulty anchor coverage 증가"),
    ("product_loop_parts_passed", "product loop parts 증가"),
    ("failure_scenarios_passed", "실패 scenario PASS 전환"),
    ("success_scenarios_passed", "성공 scenario PASS 증가"),
)


def compare_progress(before: dict, after: dict, protected_hash_status: str | None) -> dict:
    """의미 있는 개선인지 판정한다 (§9). 문구 변경 같은 무의미 변화는 개선으로 세지 않는다."""
    improvements: list[str] = []
    for key, label in _IMPROVEMENT_KEYS:
        if float(after.get(key) or 0) > float(before.get(key) or 0):
            improvements.append(label)
    if int(after.get("hard_blocker_count") or 0) < int(before.get("hard_blocker_count") or 0):
        improvements.append("hard blocker 감소")

    blockers: list[str] = []
    if int(after.get("regression_count") or 0) != 0:
        blockers.append(f"regression {after.get('regression_count')}건")
    if protected_hash_status != "PASS":
        blockers.append("protected hash FAIL")
    if int(after.get("mock_fallback_count") or 0) > int(before.get("mock_fallback_count") or 0):
        blockers.append("mock fallback 증가")
    if int(after.get("core_gates_passed") or 0) < int(before.get("core_gates_passed") or 0):
        blockers.append("기존 PASS gate가 FAIL로 전환")

    meaningful = bool(improvements) and not blockers
    return {
        "meaningful_progress": meaningful,
        "verdict": "MEANINGFUL_PROGRESS" if meaningful else "NO_MEANINGFUL_PROGRESS",
        "improvements": improvements,
        "blockers": blockers,
        "before": before,
        "after": after,
    }
