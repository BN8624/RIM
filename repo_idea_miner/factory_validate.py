# factory-validate: product run 디렉터리의 Final Artifact 구조·manifest 정합성·secret을 검증하는 모듈.
from __future__ import annotations

import json
import re
from pathlib import Path

from repo_idea_miner.factory_pipeline import FINAL_ARTIFACT_REQUIRED_FILES
from repo_idea_miner.factory_run_layout import (
    RUN_KIND_CONTINUATION,
    detect_continuation_run,
    detect_core_run,
)
from repo_idea_miner.factory_schemas import PRODUCT_VERDICT_LABELS
from repo_idea_miner.redaction import scan_files_for_secrets

MIN_SRC_FILES = 2

# 확장자 뒤 경계 요구: scenario_001.json 의 .js 부분을 스크립트로 오인하지 않는다
_SCRIPT_TOKEN_RE = re.compile(r"(\S+\.(?:py|js|mjs))(?![\w.])")

CODEX_EXPORT_REQUIRED = (
    "source_workspace",
    "manifest.json",
    "contract.json",
    "challenge_card.md",
    "product_brief.md",
    "ux_flow.md",
    "technical_plan.md",
    "syntax_report.md",
    "smoke_report.md",
    "qa_report.md",
    "debug_history.jsonl",
    "known_issues.md",
    "next_goal.md",
)


def _final_artifact_dir(run_dir: Path) -> Path | None:
    if (run_dir / "final_artifact").is_dir():
        return run_dir / "final_artifact"
    if (run_dir / "product_verdict.md").is_file() and (run_dir / "manifest.json").is_file():
        return run_dir  # final_artifact 디렉터리를 직접 지정한 경우
    return None


def validate_final_artifact(final_dir: Path) -> list[str]:
    """Final Artifact 최소 구조(§1)를 검사한다. 단일파일 산출물은 실패다."""
    problems: list[str] = []
    for rel in FINAL_ARTIFACT_REQUIRED_FILES:
        if not (final_dir / rel).is_file():
            problems.append(f"필수 파일 없음: {rel}")

    src = final_dir / "src"
    src_files = [p for p in src.rglob("*") if p.is_file()] if src.is_dir() else []
    if len(src_files) < MIN_SRC_FILES:
        problems.append(f"단일파일 산출물: src 파일 {len(src_files)}개 < {MIN_SRC_FILES} (Final Artifact 실패 조건)")

    if not any((final_dir / d).is_dir() and any((final_dir / d).iterdir()) for d in ("checks", "tests")):
        problems.append("checks/ 또는 tests/ 없음")

    manifest_path = final_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"manifest.json parse 실패: {exc}")
            manifest = {}
        for f in manifest.get("files") or []:
            if not (final_dir / f["path"]).is_file():
                problems.append(f"manifest에 있으나 실제 파일 없음: {f['path']}")
        entrypoint = manifest.get("entrypoint")
        if entrypoint and not (final_dir / entrypoint).is_file():
            problems.append(f"entrypoint 없음: {entrypoint}")

    contract_path = final_dir / "contract.json"
    if contract_path.is_file():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            problems.append(f"contract.json parse 실패: {exc}")
            contract = {}
        for rel in contract.get("required_files") or []:
            if not (final_dir / rel).is_file():
                problems.append(f"contract 필수 파일 없음: {rel}")

    verdict_path = final_dir / "product_verdict.md"
    if verdict_path.is_file():
        text = verdict_path.read_text(encoding="utf-8", errors="replace")
        if not any(label in text for label in PRODUCT_VERDICT_LABELS):
            problems.append("product_verdict.md에 유효한 verdict 라벨 없음")
    return problems


def validate_codex_export(export_dir: Path) -> list[str]:
    problems: list[str] = []
    for rel in CODEX_EXPORT_REQUIRED:
        p = export_dir / rel
        if not (p.is_file() or p.is_dir()):
            problems.append(f"codex_export 필수 항목 없음: {rel}")
    return problems


# ---------------------------------------------------------------- Phase 1.6 Core Harness run 검증 (§15)

def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _script_token(cmd: str) -> str | None:
    """실행 명령에서 첫 스크립트 경로(.py/.js/.mjs)를 뽑는다. 인터프리터/인자는 무시."""
    for m in _SCRIPT_TOKEN_RE.finditer(cmd or ""):
        tok = m.group(1)
        if not tok.lower().endswith((".exe",)) and "python" not in tok.lower().split("/")[-1]:
            return tok
    return None


def _core_final_artifact_consistency(final_dir: Path) -> list[str]:
    """final_artifact 기준 실행 가능성·요약/안내 정합성을 검사한다 (§8.2, §8.3)."""
    problems: list[str] = []

    # (1) runner_command 스크립트가 final_artifact에 존재 → 사용자가 final 기준으로 실행 가능
    runner_contract = _load_json(final_dir / "runner_contract.json") or {}
    script = _script_token(runner_contract.get("runner_command") or "")
    if script and not (final_dir / script).is_file():
        problems.append(f"final_artifact에서 runner 스크립트 실행 불가: {script}")

    # (2) dashboard_summary가 final_artifact를 가리킴 (§8.3-2: workspace만 가리키면 실패)
    dsum = _load_json(final_dir / "dashboard_summary.json")
    if dsum:
        ri = dsum.get("run_instructions") or "run_instructions.md"
        if Path(ri).is_absolute() or ri.startswith("..") or "workspace" in ri.replace("\\", "/").split("/"):
            problems.append(f"dashboard_summary run_instructions가 final_artifact 기준이 아님: {ri}")
        elif not (final_dir / ri).is_file():
            problems.append(f"dashboard_summary run_instructions 파일 없음: {ri}")
        pld = dsum.get("product_layer_dir") or "product/"
        if not (final_dir / pld).is_dir():
            problems.append(f"dashboard_summary product_layer_dir 없음: {pld}")
        dscript = _script_token(dsum.get("runner_command") or "")
        if dscript and not (final_dir / dscript).is_file():
            problems.append(f"dashboard_summary runner_command 스크립트 없음: {dscript}")

    # (3) run_instructions가 존재하는 경로를 가리킴 (§8.3-3)
    ri_path = final_dir / "run_instructions.md"
    if ri_path.is_file():
        text = ri_path.read_text(encoding="utf-8", errors="replace")
        for m in _SCRIPT_TOKEN_RE.finditer(text):
            cand = m.group(1)
            if "/" in cand and not cand.startswith(("http", "-")) and not (final_dir / cand).is_file():
                problems.append(f"run_instructions가 없는 경로를 가리킴: {cand}")
                break

    # (4) core summaries가 final_artifact와 정합 (§8.3-4): runner_summary가 참조하는 스크립트가 final에 존재
    rsum = _load_json(final_dir / "runner_summary.json")
    if rsum:
        rscript = _script_token(rsum.get("command") or "")
        if rscript and not (final_dir / rscript).is_file():
            problems.append(f"runner_summary가 참조하는 스크립트가 final_artifact에 없음: {rscript}")

    return problems


def validate_core_run_dir(run_dir: Path, secrets: list[str]) -> tuple[bool, list[str]]:
    """Phase 1.6 완주 산출물(§15)을 검증한다. NEEDS_SPEC_REPAIR로 중단된 run은 최소 문서만 본다.

    Phase 1.6b(§8): final_artifact와 workspace가 모두 있어야 하고, 둘의 핵심 파일이 정합해야 하며,
    사용자는 final_artifact 기준으로 실행 가능해야 한다.
    """
    from repo_idea_miner.factory_core_pipeline import (
        CORE_ARTIFACT_REQUIRED_FILES,
        CORE_RUN_REQUIRED_RUN_DOCS,
    )

    problems: list[str] = []
    verdict_path = run_dir / "product_verdict.md"
    verdict_text = verdict_path.read_text(encoding="utf-8", errors="replace") if verdict_path.is_file() else ""
    if "NEEDS_SPEC_REPAIR" in verdict_text:
        for rel in ("normalized_challenge.json", "core_artifact_classification.json",
                    "harness_summary.json", "product_verdict.md"):
            if not (run_dir / rel).is_file():
                problems.append(f"run 문서 없음: {rel}")
        return (not problems), problems

    for rel in CORE_RUN_REQUIRED_RUN_DOCS:
        if not (run_dir / rel).is_file():
            problems.append(f"run 문서 없음: {rel}")

    # §8.2: 완주 core run은 final_artifact와 workspace가 모두 있어야 한다
    final_dir = run_dir / "final_artifact"
    workspace = run_dir / "workspace"
    final_ok = final_dir.is_dir()
    ws_ok = workspace.is_dir()
    if not final_ok:
        problems.append("final_artifact/ 없음")
    if not ws_ok:
        problems.append("workspace/ 없음")
    check_dir = final_dir if final_ok else (workspace if ws_ok else run_dir)

    for rel in CORE_ARTIFACT_REQUIRED_FILES:
        if not (check_dir / rel).is_file():
            problems.append(f"core artifact 파일 없음: {rel}")

    # §8.3-1: workspace에는 있는데 final_artifact에는 없음 → 정합성 실패
    if final_ok and ws_ok:
        for rel in CORE_ARTIFACT_REQUIRED_FILES:
            if (workspace / rel).is_file() and not (final_dir / rel).is_file():
                problems.append(f"workspace에는 있으나 final_artifact에 없음: {rel}")

    fixtures = list((check_dir / "fixtures").glob("scenario_*.json")) if (check_dir / "fixtures").is_dir() else []
    if len(fixtures) < 3:
        problems.append(f"scenario fixture 부족: {len(fixtures)}개 < 3")
    goldens = list((check_dir / "golden").glob("expected_*.json")) if (check_dir / "golden").is_dir() else []
    if not goldens:
        problems.append("golden expected 없음")
    if not (check_dir / "product").is_dir():
        problems.append("product layer(product/) 없음")
    if not (check_dir / "replay").is_dir():
        problems.append("replay/ 없음")

    # §8.2/§8.3: final_artifact 기준 실행 가능성·요약/안내 정합성
    if final_ok:
        problems += _core_final_artifact_consistency(final_dir)

    # 정답지 표현 계약 lint — 있으면-검사: lint FAIL인데 검수 가능 verdict면 모순
    rep_lint = _load_json(run_dir / "golden_representation_lint.json")
    if rep_lint is not None and rep_lint.get("status") == "FAIL":
        dsum = _load_json(run_dir / "dashboard_summary.json") or {}
        if dsum.get("verdict") in ("REVIEW_READY", "PROMOTE_TO_CODEX"):
            problems.append(
                f"golden representation lint FAIL인데 verdict={dsum.get('verdict')} "
                f"(정답지가 표현 계약 위반: {(rep_lint.get('problems') or [])[:3]})")

    # Phase 2A/2B-1: base run에 spec repair proposal/apply 산출물이 있으면 함께 검증
    problems += _check_frozen_hash_guard(run_dir)
    problems += _check_spec_repair_outputs(run_dir)
    problems += _check_spec_repair_apply(run_dir)
    problems += _check_anti_hardcode_patch(run_dir)
    problems += _check_phase2c0(run_dir)
    problems += _check_phase2c1(run_dir)
    problems += _check_phase2c2(run_dir)
    problems += _check_phase2c3(run_dir)
    problems += _check_phase2d0(run_dir)
    problems += _check_phase2d1(run_dir)

    leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
    if leaked:
        problems.append(f"secret 노출 파일: {leaked}")
    return (not problems), problems


# ---------------------------------------------------------------- Phase 1.7b Continuation run 검증 (§3~6)

# continuation run이 실제로 생성하는 핵심 산출물(§2.1, §5.1). 실제 파이프라인이 만들지 않는
# patch_diff_summary.json 등은 "있으면 검사"로 두어 정상 run을 FAIL시키지 않는다.
CONTINUATION_REQUIRED_FILES = (
    "continuation_run_summary.json",
    "failure_classification.json",
    "repair_plan.json",
    "green_base_promotion.json",
    "gate_rerun_summary.json",
    "phase17_dashboard_summary.json",
)

CONTINUATION_FAILURE_TYPES = (
    "GOLDEN_SCHEMA_MISMATCH", "RUNNER_OUTPUT_EXTRA_FIELD", "RUNNER_OUTPUT_MISSING_FIELD",
    "STATE_INVARIANT_NOT_EXPOSED", "SCENARIO_REPLAY_FAILURE", "DETERMINISM_FAILURE",
    "PRODUCT_LAYER_NOT_CONSUMING_REPLAY", "ANTI_HARDCODE_FAILURE", "PATCH_TRANSIENT_FAILURE",
    "SPEC_REPAIR_REQUIRED",
)

REQUIRED_GATE_NAMES = (
    "core_contract", "runner", "scenario_replay", "golden_output",
    "state_invariant", "determinism", "anti_hardcode",
)

SUCCESS_VERDICTS = ("REVIEW_READY", "PROMOTE_TO_CODEX")
FROZEN_TOKENS = ("golden", "fixtures", "contract")

# ---------------------------------------------------------------- Phase 2A lane / spec repair (§10)

LANES = ("PATCH_CONTINUATION", "SPEC_REPAIR", "EXCLUDED", "REVIEW_ONLY")
SPEC_REPAIR_REVIEW_RESULTS = (
    "APPROVE_FOR_PHASE2B", "NEEDS_REVISION", "REJECT", "REQUIRES_HUMAN_REVIEW",
)


def infer_continuation_lane(verdict: str | None, requires_spec_repair: bool = False) -> str:
    """lane 필드가 없는 기존 run의 inferred_lane을 verdict 기반으로 계산한다 (§4.10)."""
    if verdict in ("REVIEW_READY", "PROMOTE_TO_CODEX", "KEEP_CANDIDATE"):
        return "REVIEW_ONLY"
    if verdict == "SPEC_REPAIR_REQUIRED":
        return "SPEC_REPAIR"
    if verdict == "NEEDS_MORE_GEMMA_LOOP":
        return "SPEC_REPAIR" if requires_spec_repair else "PATCH_CONTINUATION"
    return "EXCLUDED"


def _check_lane(run_dir: Path, summary: dict, plan: dict, promo: dict, info: dict) -> list[str]:
    """§10: lane 존재/정합성. Phase 2A 이후 run은 lane 필수, 기존 run은 inferred_lane 호환."""
    p: list[str] = []
    p2a = _load_json(run_dir / "phase2a_dashboard_summary.json") or {}
    lane = summary.get("lane") or p2a.get("lane") or p2a.get("recommended_lane")
    verdict = summary.get("verdict") or promo.get("new_verdict")
    requires_spec = bool(plan.get("requires_spec_repair") or summary.get("requires_spec_repair"))
    is_phase2a = summary.get("phase") == "2a" or bool(p2a)
    if lane:
        info["lane"] = lane
        if lane not in LANES:
            p.append(f"lane: 알 수 없는 lane 값: {lane}")
        else:
            expected = infer_continuation_lane(verdict, requires_spec)
            ok = lane == expected or (
                verdict == "NEEDS_MORE_GEMMA_LOOP" and lane in ("PATCH_CONTINUATION", "SPEC_REPAIR"))
            if not ok:
                p.append(f"lane: verdict={verdict}와 lane={lane} 불일치 (기대: {expected})")
    elif is_phase2a:
        p.append("lane: Phase 2A 이후 생성된 run인데 lane 필드 없음")
    else:
        info["inferred_lane"] = infer_continuation_lane(verdict, requires_spec)
    return p


def _check_frozen_hash_guard(run_dir: Path) -> list[str]:
    """§4.6/§4.7: frozen hash before/after/check 정합성 + 기록 이후 spec 파일 수정 탐지."""
    from repo_idea_miner.factory_frozen import compare_frozen_hashes, compute_frozen_hashes

    before = _load_json(run_dir / "frozen_hash_before.json")
    after = _load_json(run_dir / "frozen_hash_after.json")
    check = _load_json(run_dir / "frozen_hash_check.json")
    p: list[str] = []
    if check is not None and check.get("status") != "PASS":
        detail = check.get("changed") or check.get("removed") or check.get("added")
        p.append(f"frozen hash guard: 전후 frozen 파일 변경됨: {detail}")
    if before is not None and after is not None:
        cmp = compare_frozen_hashes(before, after)
        if cmp["status"] != "PASS" and (check is None or check.get("status") == "PASS"):
            detail = cmp["changed"] or cmp["removed"] or cmp["added"]
            p.append(f"frozen hash guard: before/after 불일치가 check에 반영되지 않음: {detail}")
    # Phase 2B-1: 승인된 spec repair apply가 수행됐다면 apply 이후 hash가 새 기준이다 (§17)
    after_apply = _load_json(run_dir / "frozen_hash_after_apply.json")
    reference = after_apply if after_apply else after
    if reference:
        ws = run_dir / "workspace"
        root = ws if ws.is_dir() else run_dir / "final_artifact"
        current = compute_frozen_hashes(root, run_dir)
        for key, digest in reference.items():
            if "_variants" in key:
                continue  # anti_hardcode gate scratch — frozen 대상 아님(구 기록 호환)
            if key not in current:
                p.append(f"frozen hash guard: 기록 이후 spec 파일이 삭제됨: {key}")
            elif current[key] != digest:
                p.append(f"frozen hash guard: 기록 이후 spec 파일이 수정됨: {key}")
    return p


# ---------------------------------------------------------------- Phase 2B-1 Spec Repair Apply 검증 (§17)

SPEC_REPAIR_APPLY_REQUIRED = (
    "spec_repair_apply_plan.json",
    "spec_repair_apply_report.json",
    "spec_repair_diff_summary.json",
    "pre_apply_snapshot_manifest.json",
    "rollback_plan.json",
    "frozen_hash_before_apply.json",
    "frozen_hash_after_apply.json",
    "frozen_hash_apply_check.json",
)


def _check_spec_repair_apply(run_dir: Path) -> list[str]:
    """§17: spec repair apply 산출물 정합성. apply 흔적이 없으면 검사하지 않는다."""
    report = _load_json(run_dir / "spec_repair_apply_report.json")
    if report is None or not report.get("applied"):
        return []
    p: list[str] = []
    for rel in SPEC_REPAIR_APPLY_REQUIRED:
        if not (run_dir / rel).is_file():
            p.append(f"spec repair apply: 필수 산출물 없음: {rel}")

    if report.get("review_result") != "APPROVE_FOR_PHASE2B":
        p.append(f"spec repair apply: review result가 APPROVE_FOR_PHASE2B가 아님: {report.get('review_result')}")
    if report.get("target_count") != 1:
        p.append(f"spec repair apply: 단일 대상이 아님: target_count={report.get('target_count')}")
    resolved = report.get("resolved_run_dir")
    if resolved and Path(str(resolved).replace("\\", "/")).name != run_dir.name:
        p.append(f"spec repair apply: resolved_run_dir 불일치: {resolved}")

    check = _load_json(run_dir / "frozen_hash_apply_check.json") or {}
    if check and check.get("status") != "PASS":
        p.append(f"spec repair apply: 범위 밖 frozen 변경: {check.get('out_of_scope')}")

    diff = _load_json(run_dir / "spec_repair_diff_summary.json") or {}
    if diff:
        if diff.get("comparison_mode_changes"):
            p.append(f"spec repair apply: comparison_mode 변경 발생: {diff['comparison_mode_changes']}")
        if diff.get("deleted_expected_fields"):
            p.append(f"spec repair apply: golden expected field 삭제: {diff['deleted_expected_fields']}")
        if diff.get("invariant_downgrades"):
            p.append(f"spec repair apply: invariant warning화 발생: {diff['invariant_downgrades']}")
        if diff.get("out_of_scope_changes"):
            p.append(f"spec repair apply: proposal/review 범위 밖 변경: {diff['out_of_scope_changes']}")
        sc = diff.get("scenario_count") or {}
        if sc and sc.get("before") != sc.get("after"):
            p.append(f"spec repair apply: scenario 수 변경: {sc}")

    gate_rerun = _load_json(run_dir / "gate_rerun_after_spec_repair.json") or {}
    promo = _load_json(run_dir / "green_base_promotion_after_spec_repair.json") or {}
    gates = gate_rerun.get("gates") or {}
    verdict = promo.get("new_verdict")
    if promo:
        if verdict in SUCCESS_VERDICTS and gates and not all(gates.values()):
            failed = [g for g, ok in gates.items() if not ok]
            p.append(f"spec repair apply: gate 실패({failed})인데 verdict={verdict}")
        if promo.get("promoted_to_green_base"):
            if gates and not all(gates.values()):
                p.append("spec repair apply: gate fail인데 green_base 승격")
            if promo.get("validate_ok") is False:
                p.append("spec repair apply: validate fail인데 green_base 승격")
            if check and check.get("status") != "PASS":
                p.append("spec repair apply: frozen 범위 밖 변경인데 green_base 승격")
            if diff and (diff.get("comparison_mode_changes") or diff.get("deleted_expected_fields")
                         or diff.get("invariant_downgrades")):
                p.append("spec repair apply: 금지 변경이 있는데 green_base 승격")
    return p


ANTI_HARDCODE_PATCH_REQUIRED = (
    "anti_hardcode_patch_plan.json",
    "anti_hardcode_patch_report.json",
    "anti_hardcode_diff_summary.json",
    "frozen_hash_anti_hardcode_check.json",
    "gate_rerun_after_anti_hardcode_patch.json",
    "green_base_promotion_after_anti_hardcode_patch.json",
)


def _check_anti_hardcode_patch(run_dir: Path) -> list[str]:
    """§16: anti_hardcode patch(Phase 2B-1b) 산출물 정합성. patch 흔적이 없으면 검사하지 않는다."""
    report = _load_json(run_dir / "anti_hardcode_patch_report.json")
    if report is None or not report.get("applied"):
        return []
    p: list[str] = []
    for rel in ANTI_HARDCODE_PATCH_REQUIRED:
        if not (run_dir / rel).is_file():
            p.append(f"anti_hardcode patch: 필수 산출물 없음: {rel}")

    if report.get("target_count") != 1:
        p.append(f"anti_hardcode patch: 단일 대상이 아님: target_count={report.get('target_count')}")
    if report.get("summary_source") is None:
        p.append("anti_hardcode patch: summary_source 기록 없음")
    if report.get("summary_hardcode_risk") is None:
        p.append("anti_hardcode patch: summary_hardcode_risk 기록 없음")

    check = _load_json(run_dir / "frozen_hash_anti_hardcode_check.json") or {}
    if check and check.get("status") != "PASS":
        p.append(f"anti_hardcode patch: frozen 파일 변경됨: {check.get('out_of_scope')}")

    promo = _load_json(run_dir / "green_base_promotion_after_anti_hardcode_patch.json") or {}
    gate_rerun = _load_json(run_dir / "gate_rerun_after_anti_hardcode_patch.json") or {}
    gates = gate_rerun.get("gates") or report.get("gates") or {}
    verdict = promo.get("new_verdict") or report.get("new_verdict")
    summary_risk = report.get("summary_hardcode_risk") or promo.get("summary_hardcode_risk")
    if verdict in SUCCESS_VERDICTS:
        if gates and not all(gates.values()):
            failed = [g for g, ok in gates.items() if not ok]
            p.append(f"anti_hardcode patch: gate 실패({failed})인데 verdict={verdict}")
        if summary_risk == "high":
            p.append(f"anti_hardcode patch: summary_hardcode_risk high인데 verdict={verdict}")
        if check and check.get("status") != "PASS":
            p.append(f"anti_hardcode patch: frozen 변경인데 verdict={verdict}")
    if promo.get("promoted_to_green_base"):
        if gates and not all(gates.values()):
            p.append("anti_hardcode patch: gate fail인데 green_base 승격")
        if promo.get("validate_ok") is False:
            p.append("anti_hardcode patch: validate fail인데 green_base 승격")
        if summary_risk == "high":
            p.append("anti_hardcode patch: summary_hardcode_risk high인데 green_base 승격")
        if check and check.get("status") != "PASS":
            p.append("anti_hardcode patch: frozen 변경인데 green_base 승격")
    return p


# ---------------------------------------------------------------- Phase 2C-0 Review Package 검증 (§17)

PHASE2C0_SUBDIR = "review/phase2c0"
PHASE2C0_REQUIRED = (
    "review_package.md", "review_package.json",
    "artifact_smoke_review.md", "artifact_smoke_review.json",
    "product_fitness_report.md", "product_fitness_report.json",
    "human_review_checklist.md", "sixty_second_review_script.md",
    "demo_manifest.json", "phase2c0_dashboard_summary.json",
    "review_no_code_hash_before.json", "review_no_code_hash_after.json",
    "review_no_code_hash_check.json",
)
PHASE2C0_MARKERS = (
    "phase2c0_dashboard_summary.json", "product_fitness_report.json", "review_package.json",
)
FITNESS_GRADES = (
    "PRODUCT_CANDIDATE", "NEEDS_PRODUCT_POLISH", "NEEDS_CORE_PATCH", "NEEDS_SPEC_REPAIR", "ARCHIVE",
)
PHASE2C0_CRITICAL_CRITERIA = (
    "Product layer usefulness", "Demo understandability", "Evidence quality", "Anti-hardcode confidence",
)


def detect_phase2c0_run(run_dir: str | Path) -> bool:
    """Phase 2C-0 marker(review/phase2c0/ 아래 요약 산출물)가 있는 run인지 감지한다 (§17)."""
    d = Path(run_dir) / PHASE2C0_SUBDIR
    return any((d / m).is_file() for m in PHASE2C0_MARKERS)


def _check_phase2c0(run_dir: Path) -> list[str]:
    """§17: Phase 2C-0 marker가 있는 run만 review 산출물/추천 정합성을 검사한다."""
    if not detect_phase2c0_run(run_dir):
        return []
    rd = run_dir / PHASE2C0_SUBDIR
    p: list[str] = []
    for rel in PHASE2C0_REQUIRED:
        if not (rd / rel).is_file():
            p.append(f"Phase 2C-0 산출물 없음: {PHASE2C0_SUBDIR}/{rel}")

    fitness = _load_json(rd / "product_fitness_report.json") or {}
    smoke = _load_json(rd / "artifact_smoke_review.json") or {}
    hash_check = _load_json(rd / "review_no_code_hash_check.json") or {}
    dash = _load_json(rd / "phase2c0_dashboard_summary.json") or {}

    # no-code-change guard: review 과정에서 보호 대상 artifact가 바뀌면 FAIL (§3.4, §17.2)
    if hash_check and hash_check.get("status") != "PASS":
        detail = hash_check.get("changed") or hash_check.get("added") or hash_check.get("removed")
        p.append(f"Phase 2C-0: 검수 패키지 외 보호 대상 artifact 변경됨: {detail}")

    rec = fitness.get("recommended_fitness") or dash.get("recommended_fitness")
    if rec is None:
        p.append("Phase 2C-0: recommended_fitness 없음")
    elif rec not in FITNESS_GRADES:
        p.append(f"Phase 2C-0: 알 수 없는 recommended_fitness: {rec}")

    gate_rerun = _load_json(run_dir / "gate_rerun_after_anti_hardcode_patch.json") or {}
    gates = gate_rerun.get("gates") or {}
    gate_fail = bool(gates) and not all(gates.values())
    green_base = fitness.get("green_base")
    if green_base is None:
        green_base = (_load_json(run_dir / "green_base.json") or {}).get("base_type") == "green_base"
    scores = fitness.get("scores") or {}
    red_flags = fitness.get("critical_red_flags") or []

    # §17.2 PRODUCT_CANDIDATE 엄격 검증
    if rec == "PRODUCT_CANDIDATE":
        if gate_fail:
            p.append("Phase 2C-0: PRODUCT_CANDIDATE인데 gate fail 존재")
        if green_base is False:
            p.append("Phase 2C-0: PRODUCT_CANDIDATE인데 green_base false")
        if red_flags:
            p.append(f"Phase 2C-0: PRODUCT_CANDIDATE인데 critical red flag 존재: {red_flags}")
        for c in PHASE2C0_CRITICAL_CRITERIA + ("Core usefulness",):
            if scores.get(c, 0) < 4:
                p.append(f"Phase 2C-0: PRODUCT_CANDIDATE인데 핵심 항목 4점 미만: {c}={scores.get(c)}")
        for key in ("runner_executable", "product_viewer_reads_replay", "runner_viewer_consistent"):
            val = smoke.get(key)
            if val is None:
                val = fitness.get(key)
            if val is not True:
                p.append(f"Phase 2C-0: PRODUCT_CANDIDATE인데 {key} != true ({val})")

    # §17.2 NEEDS_SPEC_REPAIR는 next_goal 필수
    if rec == "NEEDS_SPEC_REPAIR" and not (fitness.get("next_goal") or fitness.get("next_steps")):
        p.append("Phase 2C-0: NEEDS_SPEC_REPAIR인데 next_goal 없음")

    # §12.1 evidence 없는 4/5점 금지
    for c in fitness.get("criteria") or []:
        if c.get("score", 0) >= 4 and not c.get("evidence"):
            p.append(f"Phase 2C-0: evidence 없는 {c.get('score')}점 항목: {c.get('criterion')}")

    return p


# ---------------------------------------------------------------- Phase 2C-1 Viewer Polish 검증 (§13)

PHASE2C1_SUBDIR = "review/phase2c1"
PHASE2C1_REQUIRED = (
    "phase2c1_polish_plan.json", "phase2c1_polish_report.json", "phase2c1_diff_summary.json",
    "phase2c1_hash_check.json", "artifact_smoke_review_after_polish.json",
    "product_fitness_report_after_polish.json", "phase2c1_dashboard_summary.json",
)
PHASE2C1_MARKERS = (
    "phase2c1_dashboard_summary.json", "phase2c1_polish_report.json",
    "product_fitness_report_after_polish.json",
)


def detect_phase2c1_run(run_dir: str | Path) -> bool:
    """Phase 2C-1 marker(review/phase2c1/ 아래 산출물)가 있는 run인지 감지한다 (§13)."""
    d = Path(run_dir) / PHASE2C1_SUBDIR
    return any((d / m).is_file() for m in PHASE2C1_MARKERS)


def _check_phase2c1(run_dir: Path) -> list[str]:
    """§13: Phase 2C-1 marker가 있는 run만 viewer polish 산출물/정합성을 검사한다."""
    if not detect_phase2c1_run(run_dir):
        return []
    rd = run_dir / PHASE2C1_SUBDIR
    p: list[str] = []
    for rel in PHASE2C1_REQUIRED:
        if not (rd / rel).is_file():
            p.append(f"Phase 2C-1 산출물 없음: {PHASE2C1_SUBDIR}/{rel}")

    hash_check = _load_json(rd / "phase2c1_hash_check.json") or {}
    diff = _load_json(rd / "phase2c1_diff_summary.json") or {}
    smoke = _load_json(rd / "artifact_smoke_review_after_polish.json") or {}
    fitness = _load_json(rd / "product_fitness_report_after_polish.json") or {}

    # §13.2 보호 대상 artifact / golden / fixtures / contract / replay 불변
    if hash_check and hash_check.get("status") != "PASS":
        detail = hash_check.get("changed") or hash_check.get("added") or hash_check.get("removed")
        p.append(f"Phase 2C-1: 보호 대상 artifact(src/golden/fixtures/contract/replay) 변경됨: {detail}")
    if diff.get("core_golden_fixtures_contract_replay_changed"):
        p.append("Phase 2C-1: golden/fixtures/contract/replay 변경 발생")
    # 변경 파일이 product viewer 범위 안(§13.1)
    for changed in diff.get("product_files_changed") or []:
        if "/product/" not in changed.replace("\\", "/"):
            p.append(f"Phase 2C-1: 허용 범위 밖 파일 변경: {changed}")

    # edge/event/layout 기록 존재 (§13.1)
    for key in ("edge_mapping_fixed", "event_mapping_fixed", "node_layout_generated"):
        if key not in smoke and key not in fitness:
            p.append(f"Phase 2C-1: {key} 기록 없음")

    rec = fitness.get("recommended_fitness")
    if rec is None:
        p.append("Phase 2C-1: recommended_fitness 없음")
    elif rec not in FITNESS_GRADES:
        p.append(f"Phase 2C-1: 알 수 없는 recommended_fitness: {rec}")

    # recommended_fitness ↔ smoke 모순 (§13.1)
    edge_fixed = smoke.get("edge_mapping_fixed", fitness.get("edge_mapping_fixed"))
    event_fixed = smoke.get("event_mapping_fixed", fitness.get("event_mapping_fixed"))
    layout_gen = smoke.get("node_layout_generated", fitness.get("node_layout_generated"))
    remaining = smoke.get("viewer_schema_mismatches_remaining",
                          fitness.get("viewer_schema_mismatches_remaining")) or []
    consistent = smoke.get("runner_viewer_consistent", fitness.get("runner_viewer_consistent"))

    gate_rerun = _load_json(run_dir / "gate_rerun_after_anti_hardcode_patch.json") or {}
    gates = gate_rerun.get("gates") or {}
    gate_fail = bool(gates) and not all(gates.values())
    green_base = fitness.get("green_base")
    if green_base is None:
        green_base = (_load_json(run_dir / "green_base.json") or {}).get("base_type") == "green_base"
    scores = fitness.get("scores") or {}
    red_flags = fitness.get("critical_red_flags") or []

    # §13.2 PRODUCT_CANDIDATE 엄격 (2C-0 기준 + field mapping 조건)
    if rec == "PRODUCT_CANDIDATE":
        if edge_fixed is not True:
            p.append("Phase 2C-1: PRODUCT_CANDIDATE인데 edge_mapping_fixed != true")
        if event_fixed is not True:
            p.append("Phase 2C-1: PRODUCT_CANDIDATE인데 event_mapping_fixed != true")
        if layout_gen is not True:
            p.append("Phase 2C-1: PRODUCT_CANDIDATE인데 node_layout_generated != true")
        if remaining:
            p.append(f"Phase 2C-1: PRODUCT_CANDIDATE인데 viewer_schema_mismatches_remaining 존재: {remaining}")
        if consistent is not True:
            p.append("Phase 2C-1: PRODUCT_CANDIDATE인데 runner_viewer_consistent != true")
        if green_base is False:
            p.append("Phase 2C-1: PRODUCT_CANDIDATE인데 green_base false")
        if gate_fail:
            p.append("Phase 2C-1: PRODUCT_CANDIDATE인데 gate fail 존재")
        if red_flags:
            p.append(f"Phase 2C-1: PRODUCT_CANDIDATE인데 critical red flag 존재: {red_flags}")
        for c in PHASE2C0_CRITICAL_CRITERIA + ("Core usefulness",):
            if scores.get(c, 0) < 4:
                p.append(f"Phase 2C-1: PRODUCT_CANDIDATE인데 핵심 항목 4점 미만: {c}={scores.get(c)}")

    # §12.1 evidence 없는 4/5점 금지
    for c in fitness.get("criteria") or []:
        if c.get("score", 0) >= 4 and not c.get("evidence"):
            p.append(f"Phase 2C-1: evidence 없는 {c.get('score')}점 항목: {c.get('criterion')}")

    return p


# ---------------------------------------------------------------- Phase 2C-2 Node Draft Editor 검증 (§24)

PHASE2C2_SUBDIR = "review/phase2c2"
PHASE2C2_REQUIRED = (
    "phase2c2_editor_plan.json", "phase2c2_editor_report.json", "phase2c2_diff_summary.json",
    "phase2c2_hash_check.json", "viewer_js_syntax_check.json", "viewer_static_dom_check.json",
    "viewer_handler_binding_check.json", "viewer_smoke_after_editor.json",
    "editor_smoke_review.json", "draft_schema_compatibility.json", "draft_roundtrip_check.json",
    "product_fitness_report_after_editor.json", "phase2c2_dashboard_summary.json",
)
PHASE2C2_MARKERS = (
    "phase2c2_dashboard_summary.json", "phase2c2_editor_report.json",
    "product_fitness_report_after_editor.json",
)


def detect_phase2c2_run(run_dir: str | Path) -> bool:
    """§24: Phase 2C-2 marker(review/phase2c2/ 아래 산출물)가 있는 run인지 감지한다."""
    d = Path(run_dir) / PHASE2C2_SUBDIR
    return any((d / m).is_file() for m in PHASE2C2_MARKERS)


def _check_phase2c2(run_dir: Path) -> list[str]:
    """§24: Phase 2C-2 marker가 있는 run만 editor 산출물/정합성을 검사한다."""
    if not detect_phase2c2_run(run_dir):
        return []
    rd = run_dir / PHASE2C2_SUBDIR
    p: list[str] = []
    for rel in PHASE2C2_REQUIRED:
        if not (rd / rel).is_file():
            p.append(f"Phase 2C-2 산출물 없음: {PHASE2C2_SUBDIR}/{rel}")

    hash_check = _load_json(rd / "phase2c2_hash_check.json") or {}
    diff = _load_json(rd / "phase2c2_diff_summary.json") or {}
    es = _load_json(rd / "editor_smoke_review.json") or {}
    js = _load_json(rd / "viewer_js_syntax_check.json") or {}
    dom = _load_json(rd / "viewer_static_dom_check.json") or {}
    hb = _load_json(rd / "viewer_handler_binding_check.json") or {}
    fitness = _load_json(rd / "product_fitness_report_after_editor.json") or {}
    compat = _load_json(rd / "draft_schema_compatibility.json") or {}
    roundtrip = _load_json(rd / "draft_roundtrip_check.json") or {}

    # §24.2 보호 대상(src/golden/fixtures/contract/replay/phase2c0/2c1) 불변
    if hash_check and hash_check.get("status") != "PASS":
        detail = hash_check.get("changed") or hash_check.get("added") or hash_check.get("removed")
        p.append(f"Phase 2C-2: 보호 대상 artifact 변경됨: {detail}")
    if diff.get("core_golden_fixtures_contract_replay_changed"):
        p.append("Phase 2C-2: golden/fixtures/contract/replay 변경 발생")
    for changed in diff.get("product_files_changed") or []:
        if "/product/" not in changed.replace("\\", "/"):
            p.append(f"Phase 2C-2: 허용 범위 밖 파일 변경: {changed}")
    # review/phase2c0·2c1 overwrite 금지 (§20 주의)
    for changed in (hash_check.get("changed") or []):
        if changed.startswith("review/phase2c0") or changed.startswith("review/phase2c1"):
            p.append(f"Phase 2C-2: review/phase2c0·2c1 산출물 변경됨: {changed}")

    rec = fitness.get("recommended_fitness")
    if rec is None:
        p.append("Phase 2C-2: recommended_fitness 없음")
    elif rec not in FITNESS_GRADES:
        p.append(f"Phase 2C-2: 알 수 없는 recommended_fitness: {rec}")

    # §24.2 runner_backed_execution_included=true → FAIL
    if es.get("runner_backed_execution_included") is True or \
            fitness.get("runner_backed_execution_included") is True:
        p.append("Phase 2C-2: runner_backed_execution_included=true (금지)")
    # §24.1/§24.2 원본 replay 불변
    if es.get("original_replay_unchanged") is False:
        p.append("Phase 2C-2: original_replay_unchanged=false")

    # §24.1 recommended_fitness ↔ editor smoke 모순
    for c in fitness.get("criteria") or []:
        if c.get("score", 0) >= 4 and not c.get("evidence"):
            p.append(f"Phase 2C-2: evidence 없는 {c.get('score')}점 항목: {c.get('criterion')}")

    # §24.2 PRODUCT_CANDIDATE 엄격 검증
    if rec == "PRODUCT_CANDIDATE":
        checks = {
            "editor_mode_exists": es.get("editor_mode_exists"),
            "supported_node_types_loaded": es.get("supported_node_types_loaded"),
            "add_node_supported": es.get("add_node_supported"),
            "add_edge_supported": es.get("add_edge_supported"),
            "graph_validation_supported": es.get("graph_validation_supported"),
            "draft_schema_compatible": es.get("draft_schema_compatible"),
            "draft_roundtrip_pass": es.get("draft_roundtrip_pass"),
            "draft_export_supported": es.get("draft_export_supported"),
            "model_level_smoke_pass": es.get("model_level_smoke_pass"),
            "ui_binding_evidence_pass": es.get("ui_binding_evidence_pass"),
        }
        for key, val in checks.items():
            if val is not True:
                p.append(f"Phase 2C-2: PRODUCT_CANDIDATE인데 {key} != true ({val})")
        if js.get("status") == "FAIL":
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 JS syntax check FAIL")
        if dom.get("status") == "FAIL":
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 static DOM evidence FAIL")
        if hb.get("status") == "FAIL":
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 handler binding evidence FAIL")
        if compat.get("compatible") is False:
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 draft schema compatibility FAIL")
        if roundtrip.get("pass") is False:
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 draft roundtrip FAIL")
        if es.get("critical_failures"):
            p.append(f"Phase 2C-2: PRODUCT_CANDIDATE인데 critical failure 존재: {es.get('critical_failures')}")
        # limitation에 runner-backed execution not included 기록 필수 (§22.1)
        lims = " ".join(fitness.get("limitations") or [])
        if "runner-backed execution not included" not in lims:
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 limitation에 'runner-backed execution not included' 없음")
        if fitness.get("draft_editor_candidate") is not True:
            p.append("Phase 2C-2: PRODUCT_CANDIDATE인데 draft_editor_candidate 명시 없음")

    return p


# ---------------------------------------------------------------- Phase 2C-3 Runner-backed Draft Execution 검증

PHASE2C3_SUBDIR = "review/phase2c3"
PHASE2C3_REQUIRED = (
    "phase2c3_execution_plan.json", "phase2c3_execution_report.json",
    "phase2c3_diff_summary.json", "phase2c3_hash_check.json",
    "adapter_check.json", "execution_smoke.json",
    "viewer_js_syntax_check.json", "viewer_static_dom_check.json",
    "viewer_handler_binding_check.json", "viewer_smoke_after_execution.json",
    "product_fitness_report_after_execution.json", "phase2c3_dashboard_summary.json",
)
PHASE2C3_MARKERS = (
    "phase2c3_dashboard_summary.json", "phase2c3_execution_report.json",
    "product_fitness_report_after_execution.json",
)
_PHASE2C3_ALLOWED_PREFIXES = (
    "final_artifact/product/", "workspace/product/",
    "final_artifact/src/adapters/", "workspace/src/adapters/",
)


def detect_phase2c3_run(run_dir: str | Path) -> bool:
    """Phase 2C-3 marker(review/phase2c3/ 아래 산출물)가 있는 run인지 감지한다."""
    d = Path(run_dir) / PHASE2C3_SUBDIR
    return any((d / m).is_file() for m in PHASE2C3_MARKERS)


def _check_phase2c3(run_dir: Path) -> list[str]:
    """Phase 2C-3 marker가 있는 run만 runner-backed execution 산출물/정합성을 검사한다."""
    if not detect_phase2c3_run(run_dir):
        return []
    rd = run_dir / PHASE2C3_SUBDIR
    p: list[str] = []
    for rel in PHASE2C3_REQUIRED:
        if not (rd / rel).is_file():
            p.append(f"Phase 2C-3 산출물 없음: {PHASE2C3_SUBDIR}/{rel}")

    hash_check = _load_json(rd / "phase2c3_hash_check.json") or {}
    diff = _load_json(rd / "phase2c3_diff_summary.json") or {}
    es = _load_json(rd / "execution_smoke.json") or {}
    adapter = _load_json(rd / "adapter_check.json") or {}
    js = _load_json(rd / "viewer_js_syntax_check.json") or {}
    dom = _load_json(rd / "viewer_static_dom_check.json") or {}
    hb = _load_json(rd / "viewer_handler_binding_check.json") or {}
    fitness = _load_json(rd / "product_fitness_report_after_execution.json") or {}

    # 보호 대상(golden/fixtures/replay/src/core/runner/contract/phase2c0·2c1·2c2) 불변
    if hash_check and hash_check.get("status") != "PASS":
        detail = hash_check.get("changed") or hash_check.get("added") or hash_check.get("removed")
        p.append(f"Phase 2C-3: 보호 대상 artifact 변경됨: {detail}")
    for changed in diff.get("patched_files") or []:
        norm = changed.replace("\\", "/")
        if not any(norm.startswith(pref) for pref in _PHASE2C3_ALLOWED_PREFIXES):
            p.append(f"Phase 2C-3: 허용 범위 밖 파일 변경: {changed}")
    if diff.get("out_of_scope_changes"):
        p.append(f"Phase 2C-3: out_of_scope_changes 존재: {diff['out_of_scope_changes']}")
    for changed in (hash_check.get("changed") or []):
        if changed.startswith("review/phase2c"):
            p.append(f"Phase 2C-3: 기존 review 산출물 변경됨: {changed}")

    # 원본 replay 불변 필수
    if es.get("original_replay_unchanged") is False:
        p.append("Phase 2C-3: original_replay_unchanged=false")

    rec = fitness.get("recommended_fitness")
    if rec is None:
        p.append("Phase 2C-3: recommended_fitness 없음")
    elif rec not in FITNESS_GRADES:
        p.append(f"Phase 2C-3: 알 수 없는 recommended_fitness: {rec}")

    # product_loop_closed / runner_backed_execution_included 는 실증 없이 true 금지
    if fitness.get("runner_backed_execution_included") is True:
        if not (es.get("can_execute_input") and es.get("can_see_result_from_created_input")):
            p.append("Phase 2C-3: runner_backed_execution_included=true인데 실행 실증 없음")
    if fitness.get("product_loop_closed") is True and es.get("product_loop_closed") is not True:
        p.append("Phase 2C-3: fitness product_loop_closed=true인데 smoke는 미완결")

    # auto_order §14: PRODUCT_CANDIDATE 엄격 검증
    if rec == "PRODUCT_CANDIDATE":
        checks = {
            "adapter_ok": es.get("adapter_ok"),
            "runner_execution_ok": es.get("runner_execution_ok"),
            "result_reflects_edit": es.get("result_reflects_edit"),
            "revise_cycle_changes_result": es.get("revise_cycle_changes_result"),
            "bridge_server_ok": es.get("bridge_server_ok"),
            "execution_smoke_pass": es.get("execution_smoke_pass"),
            "product_loop_closed": es.get("product_loop_closed"),
            "original_replay_unchanged": es.get("original_replay_unchanged"),
        }
        for key, val in checks.items():
            if val is not True:
                p.append(f"Phase 2C-3: PRODUCT_CANDIDATE인데 {key} != true ({val})")
        if adapter.get("status") == "FAIL":
            p.append("Phase 2C-3: PRODUCT_CANDIDATE인데 adapter check FAIL")
        if js.get("status") == "FAIL":
            p.append("Phase 2C-3: PRODUCT_CANDIDATE인데 JS syntax check FAIL")
        if dom.get("status") == "FAIL":
            p.append("Phase 2C-3: PRODUCT_CANDIDATE인데 static DOM evidence FAIL")
        if hb.get("status") == "FAIL":
            p.append("Phase 2C-3: PRODUCT_CANDIDATE인데 handler binding evidence FAIL")
        if fitness.get("runner_backed_execution_included") is not True:
            p.append("Phase 2C-3: PRODUCT_CANDIDATE인데 runner_backed_execution_included != true")
        if es.get("failures"):
            p.append(f"Phase 2C-3: PRODUCT_CANDIDATE인데 smoke failure 존재: {es.get('failures')}")

    return p


# ---------------------------------------------------------------- Phase 2D-0 Autopilot 검증 (§30)

PHASE2D0_SUBDIR = "review/phase2d0"
PHASE2D0_MARKERS = (
    "product_loop_dashboard_summary.json", "product_stage_label.json", "auto_order.json",
)
# 판정이 성공(AUTOPILOT_JUDGED/HOLD)한 run의 필수 산출물 (§30.1)
PHASE2D0_REQUIRED_BASE = (
    "artifact_evidence.json", "user_facing_quality_evidence.json", "hard_blocker_result.json",
    "product_stage_label.json", "product_stage_label.md",
    "product_gap_classification.json", "product_gap_classification.md",
    "product_loop_iteration_summary.json", "product_loop_iteration_summary.md",
    "product_loop_dashboard_summary.json",
)
PHASE2D0_REQUIRED_ORDER = (
    "recommended_next_lane.json", "recommended_next_lane.md",
    "auto_order.md", "auto_order.json", "auto_order_quality_report.json", "scope_guard.json",
    "repair_blueprint.json", "expected_patch_plan.md",
    "tests_to_run.json", "rollback_or_failure_conditions.json",
)
PHASE2D0_HONEST_FAILURES = (
    "AUTOPILOT_INFRA_FAIL", "AUTOPILOT_INVALID_OUTPUT", "AUTOPILOT_EVIDENCE_INSUFFICIENT",
)
_PRODUCT_CANDIDATE_QUALITY_KEYS = (
    "first_screen_understandable", "clear_next_action", "has_example_or_seed_data",
    "success_feedback_visible", "failure_feedback_visible", "user_can_understand_value_in_60s",
)


def detect_phase2d0_run(run_dir: str | Path) -> bool:
    """§30: Phase 2D-0 marker(review/phase2d0/ 아래 산출물)가 있는 run인지 감지한다."""
    d = Path(run_dir) / PHASE2D0_SUBDIR
    return any((d / m).is_file() for m in PHASE2D0_MARKERS)


def _check_phase2d0(run_dir: Path) -> list[str]:
    """§30: Phase 2D-0 marker가 있는 run만 autopilot 산출물/정합성을 검사한다."""
    if not detect_phase2d0_run(run_dir):
        return []
    from repo_idea_miner.factory_autopilot_schemas import (
        AUTO_ORDER_QUALITY_MIN,
        AutoOrderSlots,  # noqa: F401 - schema 파일 대조용 임포트 유지
        DESK_SCHEMAS,
        ProductGapClassification,
        ProductStageLabel,
        RecommendedNextLane,
        RepairBlueprint,
        ScopeGuard,
        validate_against_hard_blockers,
        validate_desk_output,
        validate_judgment_evidence,
        validate_stage_gap_lane_consistency,
    )
    from repo_idea_miner.factory_product_loop import validate_blueprint_scopes

    rd = run_dir / PHASE2D0_SUBDIR
    p: list[str] = []
    summary = _load_json(rd / "product_loop_iteration_summary.json") or {}
    status = summary.get("status")

    # ---- 필수 산출물 (§30.1). 정직한 실패 run은 최소 기록만 요구한다.
    if status in PHASE2D0_HONEST_FAILURES:
        for rel in ("artifact_evidence.json", "user_facing_quality_evidence.json",
                    "hard_blocker_result.json", "product_loop_iteration_summary.json",
                    "product_loop_dashboard_summary.json"):
            if not (rd / rel).is_file():
                p.append(f"Phase 2D-0(실패 run) 산출물 없음: {PHASE2D0_SUBDIR}/{rel}")
    else:
        for rel in PHASE2D0_REQUIRED_BASE:
            if not (rd / rel).is_file():
                p.append(f"Phase 2D-0 산출물 없음: {PHASE2D0_SUBDIR}/{rel}")
        gap_for_req = _load_json(rd / "product_gap_classification.json") or {}
        if gap_for_req.get("primary_gap"):
            for rel in PHASE2D0_REQUIRED_ORDER:
                if not (rd / rel).is_file():
                    p.append(f"Phase 2D-0 산출물 없음: {PHASE2D0_SUBDIR}/{rel}")
        # schema 정의 파일 (§28)
        schemas_dir = rd / "schemas"
        for name in DESK_SCHEMAS:
            if not (schemas_dir / f"{name}.schema.json").is_file():
                p.append(f"Phase 2D-0 schema 파일 없음: schemas/{name}.schema.json")

    # ---- 조건부 산출물 (§30.1)
    if summary.get("schema_repair_used") and not (rd / "schema_repair_report.json").is_file():
        p.append("Phase 2D-0: schema_repair_pass 실행됐는데 schema_repair_report.json 없음")
    if summary.get("mock_loop_executed") and \
            not (rd / "mock_loop_order_following_report.json").is_file():
        p.append("Phase 2D-0: mock/safe loop 실행됐는데 mock_loop_order_following_report.json 없음")

    # ---- 보호 대상/기존 review 불변 (phase2d0_hash_check가 있으면 PASS 필수)
    hash_check = _load_json(rd / "phase2d0_hash_check.json") or {}
    if hash_check and hash_check.get("status") != "PASS":
        detail = hash_check.get("changed") or hash_check.get("added") or hash_check.get("removed")
        p.append(f"Phase 2D-0: 보호 대상 artifact/기존 review 변경됨: {detail}")

    label = _load_json(rd / "product_stage_label.json") or {}
    # 구(2D-0) live artifact는 can_execute_input 등 옛 evidence 이름 — 읽을 때만 공통 이름으로 정규화 (§6)
    if label.get("product_loop_evidence"):
        from repo_idea_miner.factory_product_capabilities import normalize_loop_evidence
        label = {**label,
                 "product_loop_evidence": normalize_loop_evidence(label["product_loop_evidence"])}
    gap = _load_json(rd / "product_gap_classification.json") or {}
    lane = _load_json(rd / "recommended_next_lane.json") or {}
    order = _load_json(rd / "auto_order.json") or {}
    guard = _load_json(rd / "scope_guard.json") or {}
    blueprint = _load_json(rd / "repair_blueprint.json") or {}
    quality_rep = _load_json(rd / "auto_order_quality_report.json") or {}
    hard = _load_json(rd / "hard_blocker_result.json") or {}
    artifact_ev = _load_json(rd / "artifact_evidence.json") or {}
    user_q = _load_json(rd / "user_facing_quality_evidence.json") or {}
    hardcode = _load_json(rd / "hardcode_guard.json") or {}

    # ---- strict JSON schema 재검증 (§30.1)
    for name, data, cls in (("product_stage_label", label, ProductStageLabel),
                            ("product_gap_classification", gap, ProductGapClassification),
                            ("recommended_next_lane", lane, RecommendedNextLane),
                            ("scope_guard", guard, ScopeGuard),
                            ("repair_blueprint", blueprint, RepairBlueprint)):
        if data:
            _model, problems = validate_desk_output(name, data, cls)
            p += [f"Phase 2D-0 schema: {x}" for x in problems]

    # ---- evidence_refs 검증 (§9, §30.1)
    known = set(artifact_ev.get("evidence_refs_catalog") or [])
    if label and gap and lane and known:
        p += [f"Phase 2D-0 evidence: {x}"
              for x in validate_judgment_evidence(label, gap, lane, known)]

    # ---- stage/gap/lane + lane policy 정합성 (§30.2)
    if label and gap and lane:
        p += [f"Phase 2D-0 정합성: {x}"
              for x in validate_stage_gap_lane_consistency(label, gap, lane)]

    # ---- hard blocker와 stage 정합성 (§6, §30.2)
    if label and hard:
        p += [f"Phase 2D-0 hard blocker: {x}"
              for x in validate_against_hard_blockers(label, hard)]

    # ---- prior_fitness_label과 autopilot_stage 분리 기록 (§5)
    if label:
        if "prior_fitness_label" not in label or "autopilot_stage" not in label:
            p.append("Phase 2D-0: prior_fitness_label/autopilot_stage 분리 기록 없음")
        if "autopilot_is_product_candidate" not in label:
            p.append("Phase 2D-0: autopilot_is_product_candidate 없음")

    # ---- auto_order ↔ lane ↔ scope_guard ↔ blueprint 정합성 (§30.2)
    rec_lane = lane.get("recommended_next_lane")
    if order and rec_lane and order.get("lane") != rec_lane:
        p.append(f"Phase 2D-0: auto_order lane({order.get('lane')})과 "
                 f"recommended_next_lane({rec_lane}) 불일치")
    if guard and rec_lane and guard.get("lane") != rec_lane:
        p.append(f"Phase 2D-0: scope_guard lane({guard.get('lane')}) 불일치")
    if order and guard:
        if set(order.get("allowed_scopes") or []) != set(guard.get("allowed_scopes") or []):
            p.append("Phase 2D-0: scope_guard와 auto_order allowed_scopes 불일치")
        if not set(guard.get("protected_scopes") or []) <= set(order.get("protected_scopes") or []):
            p.append("Phase 2D-0: auto_order protected_scopes가 scope_guard보다 좁음")
    if blueprint and rec_lane and blueprint.get("target_lane") != rec_lane:
        p.append(f"Phase 2D-0: repair_blueprint target_lane({blueprint.get('target_lane')}) 불일치")

    # ---- blueprint: apply 금지 + protected scope 제안 금지 (§19, §30.2)
    if blueprint:
        if blueprint.get("apply_allowed") is not False:
            p.append("Phase 2D-0: repair_blueprint.apply_allowed != false (live repair apply 금지)")
        p += [f"Phase 2D-0: {x}" for x in validate_blueprint_scopes(blueprint, live=True)]

    # ---- auto_order 품질 (§18.3, §30.2)
    score = quality_rep.get("auto_order_quality_score")
    if quality_rep and score is not None and score < AUTO_ORDER_QUALITY_MIN and \
            summary.get("status") == "AUTOPILOT_JUDGED":
        p.append(f"Phase 2D-0: auto_order_quality_score {score} < {AUTO_ORDER_QUALITY_MIN}인데 "
                 "HOLD 처리되지 않음")
    if order and not order.get("forbidden_actions"):
        p.append("Phase 2D-0: auto_order에 금지 범위(forbidden_actions) 누락")

    # ---- hardcode 감지 (§12, §30.2)
    if hardcode and hardcode.get("status") != "PASS":
        p.append("Phase 2D-0: challenge_id/title 기반 hardcode 감지 (프롬프트 누수)")
    trace = _load_json(rd / "judge_prompt_trace.json") or {}
    if trace.get("contains_challenge_id") or trace.get("contains_title"):
        p.append("Phase 2D-0: judge prompt에 challenge_id/title 포함 (hardcode 금지)")

    # ---- mock loop order following (§22, §30.2)
    mock = _load_json(rd / "mock_loop_order_following_report.json") or {}
    if mock:
        if mock.get("repair_followed_order") is False:
            p.append("Phase 2D-0: mock_loop_order_following_report.repair_followed_order=false")
        for key in ("auto_order_read", "scope_guard_read", "protected_files_unchanged"):
            if mock.get(key) is False:
                p.append(f"Phase 2D-0: mock loop {key}=false")

    # ---- PRODUCT_CANDIDATE 엄격 조건 (§27, §30.2)
    stage = label.get("autopilot_stage") or label.get("stage")
    if stage == "PRODUCT_CANDIDATE":
        loop_ev = label.get("product_loop_evidence") or {}
        for k, v in loop_ev.items():
            if v is not True:
                p.append(f"Phase 2D-0: PRODUCT_CANDIDATE인데 product_loop.{k} != true")
        q_ev = label.get("user_facing_quality_evidence") or user_q
        for k in _PRODUCT_CANDIDATE_QUALITY_KEYS:
            if q_ev.get(k) is not True:
                p.append(f"Phase 2D-0: PRODUCT_CANDIDATE인데 {k} != true")
        if hard.get("product_candidate_blocked"):
            p.append("Phase 2D-0: hard blocker 존재인데 autopilot_stage=PRODUCT_CANDIDATE")
        facts = artifact_ev.get("facts") or {}
        if facts.get("js_syntax_status") == "FAIL":
            p.append("Phase 2D-0: JS syntax FAIL인데 PRODUCT_CANDIDATE")
        if facts.get("critical_red_flags"):
            p.append("Phase 2D-0: critical red flag 존재인데 PRODUCT_CANDIDATE")
        # 구(2D-0) artifact는 can_execute_input, 신(2D-1) artifact는 can_execute_primary_action
        from repo_idea_miner.factory_product_capabilities import normalize_loop_evidence
        loop_norm = normalize_loop_evidence(artifact_ev.get("product_loop") or {})
        if loop_norm.get("can_execute_primary_action") is not True:
            p.append("Phase 2D-0: runner-backed execution 없음인데 PRODUCT_CANDIDATE")
    # §30.2: user_can_understand_value_in_60s=false + PRODUCT_CANDIDATE → FAIL (위 검사에 포함되나 명시)
    if stage == "PRODUCT_CANDIDATE" and user_q.get("user_can_understand_value_in_60s") is False:
        p.append("Phase 2D-0: user_can_understand_value_in_60s=false인데 PRODUCT_CANDIDATE")

    return p


PHASE2D1_SUBDIR = "review/phase2d1"


def _check_phase2d1(run_dir: Path) -> list[str]:
    """Phase 2D-1 closed loop marker(review/phase2d1/loop_*)가 있는 run만 검사한다. 없으면 no-op."""
    root = Path(run_dir) / PHASE2D1_SUBDIR
    if not root.is_dir():
        return []
    p: list[str] = []
    for loop_dir in sorted(d for d in root.iterdir() if d.is_dir()):
        rel = f"{PHASE2D1_SUBDIR}/{loop_dir.name}"
        summary = _load_json(loop_dir / "loop_summary.json")
        if summary is None:
            # summary 없는 loop dir = 진행 중이거나 중도 종료 — 아무 주장도 없으므로 검사하지 않는다.
            # (loop 실행 중 verify_candidate가 validate를 호출할 때 자기 자신을 오탐하지 않기 위함)
            continue
        for name in ("lineage.json", "base_hash_check.json", "phase2d1_dashboard_summary.json"):
            if not (loop_dir / name).is_file():
                p.append(f"Phase 2D-1: {rel}/{name} 없음")
        hash_check = _load_json(loop_dir / "base_hash_check.json") or {}
        if hash_check and hash_check.get("status") != "PASS":
            p.append(f"Phase 2D-1: {rel} base run 보호 대상 변경됨 (§1-1 위반)")
        if summary.get("status") == "AUTOPILOT_HOLD_FOR_HUMAN" and \
                not (loop_dir / "hold_for_human_packet.json").is_file():
            p.append(f"Phase 2D-1: {rel} HOLD인데 hold_for_human_packet.json 없음 (§11)")
        # PRODUCT_CANDIDATE 주장에는 마지막 iteration acceptance PASS 근거 필요 (§8)
        if summary.get("status") == "PRODUCT_CANDIDATE":
            accepted = False
            for it_dir in sorted((loop_dir / "iterations").glob("iter*")):
                for sub in ("after", "before"):
                    acc = _load_json(it_dir / sub / "product_acceptance.json") or {}
                    if acc.get("product_candidate_allowed") is True:
                        accepted = True
            if not accepted:
                p.append(f"Phase 2D-1: {rel} PRODUCT_CANDIDATE인데 acceptance PASS 근거 없음")
    return p


def _check_spec_repair_outputs(run_dir: Path) -> list[str]:
    """§7: spec repair proposal/review는 있으면 검사 — apply는 Phase 2A에서 무조건 금지."""
    p: list[str] = []
    prop_path = run_dir / "spec_repair_proposal.json"
    if prop_path.is_file():
        prop = _load_json(prop_path)
        if prop is None:
            p.append("spec_repair_proposal.json 파싱 실패")
        else:
            if prop.get("apply_allowed_in_phase2a") is not False:
                p.append("spec repair proposal: apply_allowed_in_phase2a가 false가 아님")
            for field in ("repair_type", "problem", "proposed_change"):
                if not prop.get(field):
                    p.append(f"spec repair proposal: {field} 없음")
    rev_path = run_dir / "spec_repair_review.json"
    if rev_path.is_file():
        rev = _load_json(rev_path)
        if rev is None:
            p.append("spec_repair_review.json 파싱 실패")
        else:
            if rev.get("result") not in SPEC_REPAIR_REVIEW_RESULTS:
                p.append(f"spec repair review: 알 수 없는 result: {rev.get('result')}")
            if rev.get("apply_performed") is True:
                p.append("spec repair review: Phase 2A에서 apply가 수행됨 (금지)")
    if (run_dir / "spec_repair_apply.json").is_file():
        p.append("spec repair: Phase 2A에서 apply 산출물 존재 (금지)")
    return p


def _all_gates_pass(gates: dict) -> bool:
    return bool(gates) and all(gates.values())


def _path_is_frozen(path: str, frozen_files: list[str]) -> bool:
    """patch가 건드린 파일이 frozen 계열인지 판정한다 (§5.5)."""
    norm = str(path).replace("\\", "/")
    for f in frozen_files or []:
        fs = str(f).replace("\\", "/")
        if fs.endswith("/") and norm.startswith(fs):
            return True
        if norm == fs:
            return True
    low = norm.lower()
    return low.startswith(("golden/", "fixtures/")) or low.endswith("contract.json")


def _check_continuation_summary(s: dict) -> list[str]:
    """§5.2: continuation_run_summary.json 정합성. status 필드는 산출물에 없어 verdict로 갈음한다."""
    if not s:
        return ["continuation_run_summary.json 없음/파싱 실패"]
    p: list[str] = []
    # --run-dir 모드는 base_run_id 대신 base_run_dir가 식별자일 수 있다 (둘 다 없으면 FAIL)
    if s.get("base_run_id") is None and not s.get("base_run_dir"):
        p.append("continuation_run_summary: base_run_id/base_run_dir 없음")
    if s.get("challenge_id") is None:
        p.append("continuation_run_summary: challenge_id 없음")
    if not (s.get("base_run_dir") or s.get("continuation_base_path")):
        p.append("continuation_run_summary: base run 경로 없음")
    if not (s.get("verdict") or s.get("continuation_verdict") or s.get("status")):
        p.append("continuation_run_summary: verdict 비어 있음")
    return p


def _check_failure_classification(f: dict) -> list[str]:
    """§5.3: failure_classification.json 정합성."""
    if not f:
        return ["failure_classification.json 없음/파싱 실패"]
    ftypes = f.get("failure_types")
    if not isinstance(ftypes, list) or not ftypes:
        return ["failure_classification: failure_types 배열 없음"]
    p: list[str] = []
    for i, item in enumerate(ftypes):
        if not isinstance(item, dict):
            p.append(f"failure_classification: failure_types[{i}] 형식 오류")
            continue
        t = item.get("type")
        if not t:
            p.append(f"failure_classification: failure_types[{i}] type 비어 있음")
        elif t not in CONTINUATION_FAILURE_TYPES and t != "unknown" and not item.get("unknown"):
            p.append(f"failure_classification: 알 수 없는 failure type '{t}' (unknown 표기 없음)")
        if not item.get("evidence"):
            p.append(f"failure_classification: failure_types[{i}] evidence 없음")
        if "repairable" not in item:
            p.append(f"failure_classification: failure_types[{i}] repairable 없음")
        if "requires_spec_repair" not in item:
            p.append(f"failure_classification: failure_types[{i}] requires_spec_repair 없음")
    return p


def _check_repair_plan(plan: dict) -> list[str]:
    """§5.4: repair_plan.json 정합성. frozen/allowed touch 경계를 검사한다."""
    if not plan:
        return ["repair_plan.json 없음/파싱 실패"]
    p: list[str] = []
    allowed = plan.get("allowed_touch_files")
    frozen = plan.get("frozen_files")
    if not allowed:
        p.append("repair_plan: allowed_touch_files 없음")
    if not frozen:
        p.append("repair_plan: frozen_files 없음")
    if "repair_scope" not in plan:
        p.append("repair_plan: repair_scope 없음")
    if not plan.get("steps") and not plan.get("patch_targets"):
        p.append("repair_plan: steps/patch targets 없음")
    if "requires_spec_repair" not in plan:
        p.append("repair_plan: requires_spec_repair 없음")

    if frozen:
        joined = " ".join(str(x).lower() for x in frozen)
        if not any(tok in joined for tok in FROZEN_TOKENS):
            p.append("repair_plan: frozen_files에 contract/fixtures/golden 계열 없음")
    if allowed:
        for a in allowed:
            if any(tok in str(a).lower() for tok in FROZEN_TOKENS):
                p.append(f"repair_plan: golden/fixtures/contract가 allowed_touch_files에 포함됨: {a}")
        if not any(str(a).startswith(("src/", "product/")) for a in allowed):
            p.append("repair_plan: allowed_touch_files가 src/ 또는 product/ 중심이 아님")
    if plan.get("requires_spec_repair"):
        for s in plan.get("steps") or []:
            if any(tok in str(s.get("target", "")).lower() for tok in FROZEN_TOKENS):
                p.append(f"repair_plan: spec repair인데 patch target이 frozen을 수정: {s.get('target')}")
    return p


def _check_patch_diff_summary(run_dir: Path, plan: dict) -> list[str]:
    """§5.5: patch_diff_summary.json은 있으면만 검사(실제 파이프라인은 미생성)."""
    path = run_dir / "patch_diff_summary.json"
    if not path.is_file():
        return []
    diff = _load_json(path) or {}
    p: list[str] = []
    frozen = plan.get("frozen_files") or list(FROZEN_TOKENS)
    for m in diff.get("modified_files") or diff.get("modified") or []:
        if _path_is_frozen(m, frozen):
            p.append(f"patch_diff_summary: frozen 파일 수정됨: {m}")
    rejected = diff.get("rejected_patches") or diff.get("rejected") or []
    if rejected and not (run_dir / "patch_rejection_report.json").is_file() and not diff.get("rejection_report"):
        p.append("patch_diff_summary: rejected patch가 있으나 report 없음")
    return p


def _check_gate_rerun(gr: dict) -> list[str]:
    """§5.6: gate_rerun_summary.json 정합성 (필수 gate 이름 존재)."""
    if not gr:
        return ["gate_rerun_summary.json 없음/파싱 실패"]
    gates = gr.get("gates")
    if not isinstance(gates, dict) or not gates:
        return ["gate_rerun_summary: gate 결과 없음"]
    p: list[str] = []
    for name in REQUIRED_GATE_NAMES:
        if name not in gates:
            p.append(f"gate_rerun_summary: 필수 gate 누락: {name}")
    if "product_layer_consumes_core" not in gr:
        p.append("gate_rerun_summary: product layer review 결과 없음")
    return p


def _check_green_promotion(promo: dict, gate_rerun: dict) -> list[str]:
    """§5.7: green_base_promotion.json 정합성 + gate 결과와의 모순 검사."""
    if not promo:
        return ["green_base_promotion.json 없음/파싱 실패"]
    p: list[str] = []
    if promo.get("base_run_id") is None and not promo.get("base_run_dir"):
        p.append("green_base_promotion: base_run_id/base_run_dir 없음")
    if promo.get("continuation_run_id") is None and not promo.get("continuation_identifier"):
        p.append("green_base_promotion: continuation identifier 없음")
    if "promoted_to_green_base" not in promo:
        p.append("green_base_promotion: promoted_to_green_base 없음")
    if not promo.get("new_verdict"):
        p.append("green_base_promotion: new_verdict 없음")
    if "remaining_failures" not in promo:
        p.append("green_base_promotion: remaining_failures 없음")

    gates = (gate_rerun or {}).get("gates") or {}
    promoted = promo.get("promoted_to_green_base")
    verdict = promo.get("new_verdict")
    if promoted is True:
        if gates and not _all_gates_pass(gates):
            p.append("green_base_promotion: promoted=true인데 gate fail 존재")
        if verdict and verdict not in SUCCESS_VERDICTS:
            p.append(f"green_base_promotion: promoted=true인데 verdict가 성공계열 아님: {verdict}")
    elif promoted is False:
        if not promo.get("remaining_failures"):
            p.append("green_base_promotion: promoted=false인데 remaining_failures 없음")
        if verdict and verdict in SUCCESS_VERDICTS:
            p.append(f"green_base_promotion: promoted=false인데 verdict가 성공계열: {verdict}")
    return p


def _check_dashboard_summary(d: dict) -> list[str]:
    """§5.8: phase17_dashboard_summary.json이 base run / verdict / promotion을 표시하는지."""
    if not d:
        return ["phase17_dashboard_summary.json 없음/파싱 실패"]
    p: list[str] = []
    if d.get("base_run_id") is None and not d.get("base_run_dir"):
        p.append("phase17_dashboard_summary: base run 표시 없음")
    if not (d.get("verdict") or d.get("new_verdict")):
        p.append("phase17_dashboard_summary: new verdict 표시 없음")
    if not any(k in d for k in ("green_base", "continuation_base", "promoted_to_green_base")):
        p.append("phase17_dashboard_summary: green promotion 결과 표시 없음")
    return p


def _check_verdict_consistency(summary: dict, promo: dict, dashboard: dict,
                               gate_rerun: dict, plan: dict) -> list[str]:
    """§6: 실패를 정직하게 기록했는지 — gate 결과와 verdict의 일관성을 검사한다."""
    p: list[str] = []
    verdict = summary.get("verdict") or summary.get("continuation_verdict") or promo.get("new_verdict")
    gates = (gate_rerun or {}).get("gates") or {}
    requires_spec = bool(plan.get("requires_spec_repair") or summary.get("requires_spec_repair"))

    if verdict in SUCCESS_VERDICTS and gates and not _all_gates_pass(gates):
        failed = [g for g, ok in gates.items() if not ok]
        p.append(f"verdict consistency: gate 실패({failed})인데 verdict={verdict}")
    if requires_spec and verdict in SUCCESS_VERDICTS:
        p.append(f"verdict consistency: requires_spec_repair인데 verdict={verdict}")

    verdicts = {v for v in (summary.get("verdict"), promo.get("new_verdict"), dashboard.get("verdict")) if v}
    if len(verdicts) > 1:
        p.append(f"verdict consistency: 파일 간 verdict 불일치: {sorted(verdicts)}")

    hardcode = dashboard.get("hardcode_risk") or (gate_rerun or {}).get("hardcode_risk")
    if hardcode == "high" and verdict in SUCCESS_VERDICTS:
        p.append("verdict consistency: hardcode risk high인데 성공 verdict")
    oracle = dashboard.get("oracle_risk") or dashboard.get("oracle_risk_level")
    if oracle == "high" and verdict == "PROMOTE_TO_CODEX":
        p.append("verdict consistency: oracle risk high인데 PROMOTE_TO_CODEX")
    return p


def validate_continuation_run_dir(run_dir: str | Path, secrets: list[str]) -> tuple[bool, list[str], dict]:
    """Phase 1.7 continuation run을 continuation 산출물 기준으로 검증한다 (§5, §6).

    legacy final_artifact 경로로 보내지 않는다. SPEC_REPAIR_REQUIRED처럼 '정직하게 멈춘 실패'는
    산출물이 정합적이면 PASS다. (ok, problems, info) 반환 — info는 CLI 출력용 요약.
    """
    run_dir = Path(run_dir)
    info = {
        "run_type": RUN_KIND_CONTINUATION, "base_run_id": None, "challenge_id": None,
        "verdict": None, "promoted_to_green_base": None, "failure_types": [],
        "patch_attempts": None, "gate_rerun": False,
        "lane": None, "inferred_lane": None, "patch_result": None,
    }
    if not run_dir.is_dir():
        return False, [f"디렉터리 없음: {run_dir}"], info

    problems: list[str] = []
    for rel in CONTINUATION_REQUIRED_FILES:
        if not (run_dir / rel).is_file():
            problems.append(f"continuation 필수 파일 없음: {rel}")

    summary = _load_json(run_dir / "continuation_run_summary.json") or {}
    failure = _load_json(run_dir / "failure_classification.json") or {}
    plan = _load_json(run_dir / "repair_plan.json") or {}
    promo = _load_json(run_dir / "green_base_promotion.json") or {}
    gate_rerun = _load_json(run_dir / "gate_rerun_summary.json") or {}
    dashboard = _load_json(run_dir / "phase17_dashboard_summary.json") or {}

    info["base_run_id"] = summary.get("base_run_id")
    info["challenge_id"] = summary.get("challenge_id")
    info["verdict"] = summary.get("verdict") or promo.get("new_verdict")
    info["promoted_to_green_base"] = summary.get("promoted_to_green_base")
    info["failure_types"] = summary.get("failure_types") or []
    info["patch_attempts"] = summary.get("patch_attempts")
    info["gate_rerun"] = bool(gate_rerun.get("gates"))
    info["patch_result"] = summary.get("patch_result")

    problems += _check_continuation_summary(summary)
    problems += _check_failure_classification(failure)
    problems += _check_repair_plan(plan)
    problems += _check_patch_diff_summary(run_dir, plan)
    problems += _check_gate_rerun(gate_rerun)
    problems += _check_green_promotion(promo, gate_rerun)
    problems += _check_dashboard_summary(dashboard)
    problems += _check_verdict_consistency(summary, promo, dashboard, gate_rerun, plan)
    # Phase 2A/2B-1: lane / frozen hash guard / spec repair proposal·apply 정합성 (§10, §17)
    problems += _check_lane(run_dir, summary, plan, promo, info)
    problems += _check_frozen_hash_guard(run_dir)
    problems += _check_spec_repair_outputs(run_dir)
    problems += _check_spec_repair_apply(run_dir)
    problems += _check_anti_hardcode_patch(run_dir)
    problems += _check_phase2c0(run_dir)
    problems += _check_phase2c1(run_dir)
    problems += _check_phase2c2(run_dir)
    problems += _check_phase2c3(run_dir)
    problems += _check_phase2d0(run_dir)
    problems += _check_phase2d1(run_dir)

    leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
    if leaked:
        problems.append(f"secret 노출 파일: {leaked}")
    return (not problems), problems, info


def validate_product_run_dir(run_dir: str | Path, secrets: list[str]) -> tuple[bool, list[str]]:
    """product run 디렉터리 전체를 검증한다. (ok, problems) 반환."""
    run_dir = Path(run_dir)
    problems: list[str] = []
    if not run_dir.is_dir():
        return False, [f"디렉터리 없음: {run_dir}"]

    # Phase 1.7 continuation run은 §5 기준으로 검증한다 (legacy 경로로 보내지 않는다)
    if detect_continuation_run(run_dir):
        ok, problems, _ = validate_continuation_run_dir(run_dir, secrets)
        return ok, problems

    # Phase 1.6 Core Harness run은 §15 기준으로 검증한다
    if detect_core_run(run_dir):
        return validate_core_run_dir(run_dir, secrets)

    final_dir = _final_artifact_dir(run_dir)
    if final_dir is None:
        problems.append("final_artifact/ 없음 (Final Artifact 미생성)")
    else:
        problems += validate_final_artifact(final_dir)

    if final_dir is not run_dir:
        for rel in ("events.jsonl", "debug_history.jsonl", "product_verdict.md"):
            if not (run_dir / rel).is_file():
                problems.append(f"run 기록 파일 없음: {rel}")

    export_dir = run_dir / "codex_export"
    if export_dir.is_dir():
        problems += validate_codex_export(export_dir)

    leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
    if leaked:
        problems.append(f"secret 노출 파일: {leaked}")
    return (not problems), problems
