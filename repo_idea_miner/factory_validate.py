# factory-validate: product run 디렉터리의 Final Artifact 구조·manifest 정합성·secret을 검증하는 모듈.
from __future__ import annotations

import json
import re
from pathlib import Path

from repo_idea_miner.factory_pipeline import FINAL_ARTIFACT_REQUIRED_FILES
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

def detect_core_run(run_dir: Path) -> bool:
    """Phase 1.6 Core-first Harness run 디렉터리인지 감지한다 (harness_summary.json 존재)."""
    return (run_dir / "harness_summary.json").is_file()


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

    leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
    if leaked:
        problems.append(f"secret 노출 파일: {leaked}")
    return (not problems), problems


# ---------------------------------------------------------------- Phase 1.7b Continuation run 검증 (§3~6)

RUN_TYPE_CONTINUATION = "CONTINUATION_RUN"
RUN_TYPE_CORE = "CORE_FACTORY_RUN"
RUN_TYPE_LEGACY = "LEGACY_FACTORY_RUN"
RUN_TYPE_UNKNOWN = "UNKNOWN_RUN"

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


def detect_continuation_run(run_dir: Path) -> bool:
    """Phase 1.7 continuation run 디렉터리인지 감지한다 (§3 감지 기준)."""
    if (run_dir / "continuation_run_summary.json").is_file():
        return True
    if (run_dir / "green_base_promotion.json").is_file():
        return True
    return (run_dir / "failure_classification.json").is_file() and (run_dir / "repair_plan.json").is_file()


def detect_run_type(run_dir: str | Path) -> str:
    """run directory를 보고 run type을 감지한다 (§3). continuation → core → legacy 순."""
    run_dir = Path(run_dir)
    if detect_continuation_run(run_dir):
        return RUN_TYPE_CONTINUATION
    if (detect_core_run(run_dir)
            or (run_dir / "core_system_summary.json").is_file()
            or (run_dir / "core_contract_summary.json").is_file()):
        return RUN_TYPE_CORE
    if (_final_artifact_dir(run_dir) is not None
            or (run_dir / "manifest.json").is_file()
            or (run_dir / "contract.json").is_file()):
        return RUN_TYPE_LEGACY
    return RUN_TYPE_UNKNOWN


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
    if s.get("base_run_id") is None:
        p.append("continuation_run_summary: base_run_id 없음")
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
    if promo.get("base_run_id") is None:
        p.append("green_base_promotion: base_run_id 없음")
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
    if d.get("base_run_id") is None:
        p.append("phase17_dashboard_summary: base run id 표시 없음")
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
        "run_type": RUN_TYPE_CONTINUATION, "base_run_id": None, "challenge_id": None,
        "verdict": None, "promoted_to_green_base": None, "failure_types": [],
        "patch_attempts": None, "gate_rerun": False,
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

    problems += _check_continuation_summary(summary)
    problems += _check_failure_classification(failure)
    problems += _check_repair_plan(plan)
    problems += _check_patch_diff_summary(run_dir, plan)
    problems += _check_gate_rerun(gate_rerun)
    problems += _check_green_promotion(promo, gate_rerun)
    problems += _check_dashboard_summary(dashboard)
    problems += _check_verdict_consistency(summary, promo, dashboard, gate_rerun, plan)

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
