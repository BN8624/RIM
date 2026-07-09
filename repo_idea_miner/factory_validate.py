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


def validate_product_run_dir(run_dir: str | Path, secrets: list[str]) -> tuple[bool, list[str]]:
    """product run 디렉터리 전체를 검증한다. (ok, problems) 반환."""
    run_dir = Path(run_dir)
    problems: list[str] = []
    if not run_dir.is_dir():
        return False, [f"디렉터리 없음: {run_dir}"]

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
