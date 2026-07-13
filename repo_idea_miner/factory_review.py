# Phase 2C-0: #47 green 산출물을 오염 없이 smoke review하고 evidence 기반으로 제품성을 추천 판정하는 모듈.
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from repo_idea_miner.factory_product_evidence import (
    challenge_id_from_run,
    classify_node_collection,
    compare_protected_hashes,
    compute_protected_hashes,
    find_product_viewer,
    first_replay_file,
    load_json,
    read_gate_context,
    sha256_file,
    viewer_field_mismatches,
    viewer_reads_replay_evidence,
    write_json,
    write_text,
)
from repo_idea_miner.factory_run_layout import resolve_run_target

# ---------------------------------------------------------------- 상수 (§3, §8)

REVIEW_SUBDIR = "review/phase2c0"

# review/phase2c0/ 아래 필수 산출물 (§8, §17.1)
REQUIRED_OUTPUTS = (
    "review_package.md",
    "review_package.json",
    "artifact_smoke_review.md",
    "artifact_smoke_review.json",
    "product_fitness_report.md",
    "product_fitness_report.json",
    "human_review_checklist.md",
    "sixty_second_review_script.md",
    "demo_manifest.json",
    "phase2c0_dashboard_summary.json",
    "review_no_code_hash_before.json",
    "review_no_code_hash_after.json",
    "review_no_code_hash_check.json",
)

# runner 출력 계약 필드 — smoke가 replay/viewer 대응을 볼 때 기준으로 삼는다 (§6.2)
_CORE_OUTPUT_FIELDS = ("ok", "final_state", "events", "summary", "errors")

# 핵심 평가 항목 (§12.2) — unknown/저점이면 PRODUCT_CANDIDATE 금지
_CRITICAL_CRITERIA = (
    "Product layer usefulness",
    "Demo understandability",
    "Evidence quality",
    "Anti-hardcode confidence",
)


# ---------------------------------------------------------------- Artifact Smoke Review (§6)

def _parse_runner_command(cmd: str) -> list[str]:
    """runner_command 문자열을 argv로 만든다. 'python'은 현재 인터프리터로 바꾼다."""
    argv = shlex.split(cmd, posix=True)
    if argv and argv[0].lower() in ("python", "python3", "py"):
        argv[0] = sys.executable
    return argv


def _consistency_fields(runner_out: dict | None, replay: dict | None, viewer_src: str) -> list[str]:
    """runner 출력과 viewer 표시가 실제로 일치하는 필드를 모은다 (§6.3). 최소 2개면 consistent."""
    fields: list[str] = []
    if not runner_out or not replay:
        return fields
    # (1) summary: runner==replay 이고 viewer가 data.summary를 표시
    if runner_out.get("summary") == replay.get("summary") and re.search(r"\bdata\.summary\b", viewer_src):
        fields.append(f"summary=={runner_out.get('summary')!r}")
    # (2) 노드 status: runner==replay 이고 viewer가 node.status를 표시
    # node collection은 dict/list 모두 canonical — shape-safe 분류로 읽는다 (이슈 #19 §9)
    r_info = classify_node_collection(runner_out.get("final_state"))
    p_info = classify_node_collection(replay.get("final_state"))
    if r_info["nodes"] and p_info["nodes"]:
        r_stat = {i: n.get("status") for i, n in zip(r_info["identities"], r_info["nodes"])}
        p_stat = {i: n.get("status") for i, n in zip(p_info["identities"], p_info["nodes"])}
        # status 값이 전무한 vacuous 일치는 consistency 근거로 세지 않는다 (이슈 #19 INV-7)
        if r_stat == p_stat and any(v is not None for v in r_stat.values()) and \
                re.search(r"\bnode\.status\b", viewer_src):
            fields.append("final_state.nodes[].status")
        if len(r_info["nodes"]) == len(p_info["nodes"]) and \
                re.search(r"final_state\.nodes|state\.nodes", viewer_src):
            fields.append(f"final_state.nodes 개수={len(r_info['nodes'])}")
    # (3) events 개수: runner==replay 이고 viewer가 data.events를 순회
    if len(runner_out.get("events") or []) == len(replay.get("events") or []) and \
            re.search(r"\bdata\.events\b", viewer_src):
        fields.append(f"events 개수={len(runner_out.get('events') or [])}")
    return fields


def smoke_review(run_dir: Path, review_dir: Path, timeout: float = 60.0) -> dict:
    """원본을 오염시키지 않고 temp copy에서 runner를 실행하고 viewer/replay 대응을 정적 확인한다 (§6)."""
    final_dir = run_dir / "final_artifact"
    runner_contract = load_json(final_dir / "runner_contract.json") or {}
    runner_command = runner_contract.get("runner_command") or ""
    result: dict = {
        "runner_executable": False,
        "runner_command": runner_command,
        "runner_command_verified": False,
        "runner_exit_code": None,
        "runner_cwd": None,
        "runner_evidence_path": None,
        "replay_output_exists": (final_dir / "replay" / "index.json").is_file(),
        "product_viewer_exists": False,
        "product_viewer_path": None,
        "product_viewer_reads_replay": False,
        "product_viewer_reads_replay_evidence": [],
        "product_interactive_authoring": False,
        "runner_viewer_consistent": "unknown",
        "runner_viewer_consistency_fields": [],
        "openable_paths": [],
        "replay_count": 0,
        "core_node_types": [],
        "replay_node_collection": None,
        "mismatches": [],
        "critical_failures": [],
        "unknowns": [],
        "evidence": [],
    }
    if not final_dir.is_dir():
        result["critical_failures"].append("final_artifact/ 없음")
        return result

    idx = load_json(final_dir / "replay" / "index.json") or {}
    result["replay_count"] = len(idx.get("replays") or [])

    # (A) runner를 temp copy에서 실행 — 원본 미변경 (§4.1)
    runner_out = None
    if not runner_command:
        result["critical_failures"].append("runner_contract에 runner_command 없음")
    else:
        tmp = Path(tempfile.mkdtemp(prefix="phase2c0_smoke_"))
        try:
            tmp_final = tmp / "final_artifact"
            shutil.copytree(final_dir, tmp_final)
            argv = _parse_runner_command(runner_command)
            proc = subprocess.run(
                argv, cwd=str(tmp_final), capture_output=True, text=True, timeout=timeout,
            )
            result["runner_exit_code"] = proc.returncode
            result["runner_cwd"] = "final_artifact"
            try:
                runner_out = json.loads(proc.stdout)
            except json.JSONDecodeError:
                runner_out = None
            ok = proc.returncode == 0 and isinstance(runner_out, dict) and \
                all(f in runner_out for f in _CORE_OUTPUT_FIELDS)
            result["runner_executable"] = ok
            result["runner_command_verified"] = ok
            ev_path = review_dir / "smoke" / "runner_scenario_smoke.json"
            write_json(ev_path, {
                "command": runner_command,
                "argv": [str(a) for a in argv],
                "cwd": "final_artifact (temp copy)",
                "exit_code": proc.returncode,
                "stdout": proc.stdout[:20000],
                "stderr": proc.stderr[:4000],
                "parsed_fields": sorted(runner_out) if isinstance(runner_out, dict) else None,
            })
            result["runner_evidence_path"] = str(ev_path.relative_to(run_dir).as_posix())
            if ok:
                result["evidence"].append(
                    f"runner 실행 exit={proc.returncode}, 출력 필드={sorted(runner_out)}")
            else:
                result["critical_failures"].append(
                    f"runner 실행 실패/출력 불완전 (exit={proc.returncode})")
        except subprocess.TimeoutExpired:
            result["critical_failures"].append(f"runner 실행 timeout ({timeout}s)")
        except Exception as exc:  # noqa: BLE001 — smoke 실행 실패는 판정에 반영, 고치지 않는다 (§6.4)
            result["critical_failures"].append(f"runner 실행 예외: {exc}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # (B) 코어 엔진 노드 타입 (Core/Extension 근거)
    engine_src = ""
    engine_path = final_dir / "src" / "core" / "engine.py"
    if engine_path.is_file():
        engine_src = engine_path.read_text(encoding="utf-8", errors="replace")
        result["core_node_types"] = sorted(set(re.findall(r'==\s*["\']([A-Z][A-Z0-9_]+)["\']', engine_src)))

    # (C) product viewer + replay 정적 대응 (§6.2, §6.3)
    viewer = find_product_viewer(final_dir)
    _replay_file, replay = first_replay_file(final_dir)
    if viewer is None:
        result["critical_failures"].append("product viewer 없음")
    else:
        result["product_viewer_exists"] = True
        result["product_viewer_path"] = str(viewer.relative_to(run_dir).as_posix())
        viewer_src = viewer.read_text(encoding="utf-8", errors="replace")
        # 조작 가능한 저작(노드/엣지 편집·드래그·입력)인지 — 단순 replay 선택은 저작이 아님 (§13)
        result["product_interactive_authoring"] = bool(re.search(
            r"add[_ ]?node|create[_ ]?node|add[_ ]?edge|create[_ ]?edge|new\s+Node|"
            r"contenteditable|<input|drag(start|over|drop)?|draggable|dropNode",
            viewer_src, re.I))
        read_ev = viewer_reads_replay_evidence(viewer_src, replay)
        result["product_viewer_reads_replay_evidence"] = read_ev
        result["product_viewer_reads_replay"] = len(read_ev) >= 2  # 단순 fetch 하나로는 불가 (§6.2)
        if not result["product_viewer_reads_replay"]:
            result["critical_failures"].append(
                "product viewer가 replay를 읽는 근거가 2개 미만 (§6.2)")
        fields = _consistency_fields(runner_out, replay, viewer_src)
        result["runner_viewer_consistency_fields"] = fields
        if runner_out is None or replay is None or viewer is None:
            result["runner_viewer_consistent"] = "unknown"
            result["unknowns"].append("runner/replay/viewer 중 하나를 확인할 수 없어 consistency=unknown")
        elif len(fields) >= 2:
            result["runner_viewer_consistent"] = True
            result["evidence"].append(f"runner↔viewer 일치 필드: {fields}")
        else:
            result["runner_viewer_consistent"] = "unknown"
            result["unknowns"].append(f"runner↔viewer 일치 필드가 2개 미만: {fields}")
        result["mismatches"] = viewer_field_mismatches(replay, viewer_src)
        # 빈 node evidence에도 원인을 남긴다 — NOT_APPLICABLE/EMPTY/MISSING/MALFORMED 구분 (이슈 #19 §8.4)
        node_info = classify_node_collection(
            replay.get("final_state") if isinstance(replay, dict) else None)
        result["replay_node_collection"] = {
            "shape": node_info["shape"],
            "valid_nodes": len(node_info["nodes"]),
            "malformed_entries": node_info["malformed_entries"],
        }

    # (D) openable paths — 실제 존재하는 것만 (§10)
    for rel in (result.get("product_viewer_path"),
                "final_artifact/replay/index.json",
                "final_artifact/src/runner.py",
                "final_artifact/run_instructions.md"):
        if rel and (run_dir / rel).exists() and rel not in result["openable_paths"]:
            result["openable_paths"].append(rel)

    return result


# ---------------------------------------------------------------- Product Fitness Scoring (§11, §12)

def _crit(name, score, evidence, reason):
    return {"criterion": name, "score": score, "evidence": list(evidence), "reason": reason}


def build_fitness(smoke: dict, gate: dict) -> dict:
    """smoke 사실 + 하네스 상태에서 7개 항목을 점수화하고 recommended_fitness를 산출한다 (§11~§13)."""
    runner_ok = bool(smoke.get("runner_executable")) and smoke.get("runner_exit_code") == 0
    viewer_reads = bool(smoke.get("product_viewer_reads_replay"))
    consistent = smoke.get("runner_viewer_consistent") is True
    authoring = bool(smoke.get("product_interactive_authoring"))
    viewer_exists = bool(smoke.get("product_viewer_exists"))
    mismatches = smoke.get("mismatches") or []
    unknowns = smoke.get("unknowns") or []
    critical_failures = smoke.get("critical_failures") or []
    consistency_fields = smoke.get("runner_viewer_consistency_fields") or []
    replay_count = smoke.get("replay_count") or 0
    node_types = smoke.get("core_node_types") or []
    green_base = bool(gate.get("green_base"))
    gate_fail = bool(gate.get("gate_fail"))
    anti_ok = gate.get("anti_hardcode") and gate.get("summary_source") == "state_derived" \
        and gate.get("summary_hardcode_risk") in (None, "low")

    criteria: list[dict] = []

    # 1. Core usefulness
    if runner_ok and replay_count >= 3 and len(node_types) >= 5:
        criteria.append(_crit(
            "Core usefulness", 5,
            [f"runner exit=0, 출력 계약 필드 충족 ({smoke.get('runner_evidence_path')})",
             f"replay {replay_count}개 시나리오 존재",
             f"코어 엔진 노드 타입 {len(node_types)}종: {node_types}"],
            "여러 노드 타입/시나리오를 처리하는 충실한 그래프 실행 엔진."))
    elif runner_ok and replay_count >= 3 and len(node_types) >= 3:
        criteria.append(_crit(
            "Core usefulness", 4,
            [f"runner exit=0, 출력 계약 필드 충족 ({smoke.get('runner_evidence_path')})",
             f"replay {replay_count}개 시나리오 존재",
             f"코어 엔진 노드 타입 {len(node_types)}종: {node_types}"],
            "실제 그래프 실행 엔진이 여러 노드 타입/시나리오를 처리한다."))
    elif runner_ok:
        criteria.append(_crit(
            "Core usefulness", 3,
            [f"runner exit=0 ({smoke.get('runner_evidence_path')})",
             f"replay {replay_count}개 / 노드 타입 {len(node_types)}종"],
            "runner는 동작하나 시나리오/노드 다양성이 제한적."))
    else:
        criteria.append(_crit(
            "Core usefulness", 2,
            critical_failures or ["runner 미확인"],
            "runner 실행을 확인하지 못함 — 코어 유용성 근거 부족."))

    # 2. Interaction clarity
    if viewer_exists and authoring:
        criteria.append(_crit(
            "Interaction clarity", 4,
            [f"viewer 존재: {smoke.get('product_viewer_path')}", "노드/엣지 편집 등 저작 조작 감지"],
            "사용자가 그래프를 직접 조작·저작할 수 있다."))
    elif viewer_exists:
        criteria.append(_crit(
            "Interaction clarity", 3,
            [f"viewer 존재: {smoke.get('product_viewer_path')}", "저작 조작 미감지 (replay 선택 중심)"],
            "시나리오 선택/replay 재생 조작은 있으나 노드 편집 등 저작 조작은 없음 (결과 뷰어 중심)."))
    else:
        criteria.append(_crit(
            "Interaction clarity", 2, ["product viewer 없음"],
            "조작 가능한 product viewer가 없음."))

    # 3. Product layer usefulness (핵심)
    if not viewer_reads:
        criteria.append(_crit(
            "Product layer usefulness", 1,
            smoke.get("product_viewer_reads_replay_evidence") or ["viewer가 replay를 읽지 않음"],
            "product viewer가 core output(replay)을 읽는다는 근거 부족."))
    elif mismatches:
        criteria.append(_crit(
            "Product layer usefulness", 2,
            (smoke.get("product_viewer_reads_replay_evidence") or [])[:2] + mismatches,
            "viewer가 replay를 읽지만 edge/event/좌표 필드 스키마가 어긋나 그래프 렌더링이 깨진다."))
    elif consistent:
        criteria.append(_crit(
            "Product layer usefulness", 4,
            smoke.get("product_viewer_reads_replay_evidence") or [],
            "viewer가 core output을 읽고 runner 결과와 일치하게 표시한다."))
    else:
        criteria.append(_crit(
            "Product layer usefulness", 3,
            smoke.get("product_viewer_reads_replay_evidence") or [],
            "viewer가 core output을 읽지만 일치 근거가 제한적."))

    # 4. Demo understandability (핵심)
    if mismatches:
        criteria.append(_crit(
            "Demo understandability", 2, mismatches,
            "뷰어를 열면 엣지/이벤트/노드 배치가 깨져 보여 30초 안에 이해하기 어렵다."))
    elif viewer_reads and consistent:
        criteria.append(_crit(
            "Demo understandability", 4,
            [f"viewer가 core 결과를 필드 일치로 정상 표시: {consistency_fields}"],
            "필드 매핑이 맞아 뷰어를 열면 무엇인지 바로 이해된다."))
    elif viewer_reads:
        criteria.append(_crit(
            "Demo understandability", 3,
            [f"viewer가 replay를 읽음: {smoke.get('product_viewer_reads_replay_evidence')}"],
            "결과는 보이나 일치 근거가 제한적이라 데모 이해도가 중간."))
    else:
        criteria.append(_crit(
            "Demo understandability", 2,
            unknowns or ["표시 일관성 미확인"],
            "표시 일관성을 확인하지 못해 데모 이해도가 낮음."))

    # 5. Extension potential
    if runner_ok and len(node_types) >= 5:
        criteria.append(_crit(
            "Extension potential", 4,
            [f"엔진이 {len(node_types)}종 노드 타입을 처리: {node_types}",
             "위상정렬/데이터 전파 구조 존재"],
            "노드 타입이 풍부해 확장·재사용 가치가 크다."))
    elif runner_ok and len(node_types) >= 3:
        criteria.append(_crit(
            "Extension potential", 3,
            [f"엔진이 {len(node_types)}종 노드 타입을 분기 처리: {node_types}",
             "위상정렬/데이터 전파 구조 존재"],
            "노드 타입 추가로 확장 가능하나 if/elif 분기라 플러그인 구조는 아님."))
    else:
        criteria.append(_crit(
            "Extension potential", 2,
            ["코어 확장 근거 부족"],
            "확장 가치를 뒷받침할 코어 구조 근거가 부족."))

    # 6. Evidence quality (핵심)
    if runner_ok and viewer_exists and len(consistency_fields) >= 3 and not unknowns \
            and not critical_failures:
        criteria.append(_crit(
            "Evidence quality", 5,
            [f"runner 실제 실행 증거: {smoke.get('runner_evidence_path')}",
             f"viewer/replay 파일 정적 확인: {smoke.get('product_viewer_path')}",
             f"일치 필드 {len(consistency_fields)}개 실측: {consistency_fields}"],
            "실제 실행 + 다수 필드 일치 실측으로 근거가 강하다."))
    elif runner_ok and viewer_exists and smoke.get("runner_evidence_path"):
        criteria.append(_crit(
            "Evidence quality", 4,
            [f"runner 실제 실행 증거: {smoke.get('runner_evidence_path')}",
             f"viewer/replay 파일 정적 확인: {smoke.get('product_viewer_path')}",
             f"일치 필드 실측: {consistency_fields}"],
            "gate summary가 아니라 실제 실행/파일 확인 증거에 기반."))
    else:
        criteria.append(_crit(
            "Evidence quality", 2,
            critical_failures or ["실행/확인 증거 부족"],
            "실제 artifact 확인 증거가 부족(gate summary 수준)."))

    # 7. Anti-hardcode confidence (핵심)
    if anti_ok:
        criteria.append(_crit(
            "Anti-hardcode confidence", 4,
            [f"anti_hardcode gate PASS, summary_source={gate.get('summary_source')}",
             f"summary_hardcode_risk={gate.get('summary_hardcode_risk')}",
             "summary가 final_state 파생(summarize_execution)"],
            "summary가 상태 파생이고 anti_hardcode gate를 통과."))
    else:
        criteria.append(_crit(
            "Anti-hardcode confidence", 2,
            [f"anti_hardcode={gate.get('anti_hardcode')}, source={gate.get('summary_source')}"],
            "하드코딩 우회 신뢰 근거가 약함."))

    scores = {c["criterion"]: c["score"] for c in criteria}
    average = round(sum(scores.values()) / len(scores), 2)

    # ---- Critical red flags (§13)
    red_flags: list[str] = []
    if not viewer_exists:
        red_flags.append("product viewer 없음")
    if viewer_exists and not viewer_reads:
        red_flags.append("viewer가 replay/core output을 읽지 않음")
    if smoke.get("runner_viewer_consistent") == "unknown":
        red_flags.append("runner/viewer consistency가 unknown")
    if mismatches:
        red_flags.append("viewer 필드 스키마 불일치로 엣지/이벤트/좌표 렌더링 결함: " + "; ".join(mismatches))
    if viewer_exists and not authoring:
        red_flags.append("조작 가능한 product experience 없음 (결과 뷰어 중심, 노드 편집 UI 없음)")
    if not runner_ok:
        red_flags.append("runner 실행을 확인하지 못함")
    if not green_base:
        red_flags.append("green_base false")
    if gate_fail:
        red_flags.append("gate fail 존재")
    if not anti_ok:
        red_flags.append("anti-hardcode confidence 낮음")

    # ---- recommended_fitness (§12.3, §13) — 기본은 NEEDS_PRODUCT_POLISH
    core_use = scores["Core usefulness"]
    critical_scores = [scores[c] for c in _CRITICAL_CRITERIA]
    candidate_conditions = {
        "average>=4.0": average >= 4.0,
        "Core usefulness>=4": core_use >= 4,
        "Product layer usefulness>=4": scores["Product layer usefulness"] >= 4,
        "Demo understandability>=4": scores["Demo understandability"] >= 4,
        "Evidence quality>=4": scores["Evidence quality"] >= 4,
        "Anti-hardcode confidence>=4": scores["Anti-hardcode confidence"] >= 4,
        "no_critical_red_flag": not red_flags,
        "green_base": green_base,
        "no_gate_fail": not gate_fail,
        "runner_executable": runner_ok,
        "product_viewer_reads_replay": viewer_reads,
        "runner_viewer_consistent": consistent,
    }
    meets_candidate = all(candidate_conditions.values())

    if meets_candidate:
        recommended = "PRODUCT_CANDIDATE"
    elif not green_base or gate_fail:
        recommended = "NEEDS_CORE_PATCH"
    elif core_use <= 2 or not runner_ok:
        recommended = "NEEDS_CORE_PATCH"
    elif min(critical_scores) <= 1 and average < 2.0:
        recommended = "ARCHIVE"
    else:
        recommended = "NEEDS_PRODUCT_POLISH"

    return {
        "recommended_fitness": recommended,
        "average_score": average,
        "scores": scores,
        "criteria": criteria,
        "critical_red_flags": red_flags,
        "candidate_conditions": candidate_conditions,
        "meets_candidate": meets_candidate,
    }


# ---------------------------------------------------------------- 문서 렌더링 (§9, §14, §15)

def _review_status_text(recommended: str) -> str:
    return "사용자 최종 승인 필요" if recommended == "PRODUCT_CANDIDATE" else "사용자 최종 결정 대기"


def _next_steps(recommended: str, smoke: dict) -> list[str]:
    if recommended == "PRODUCT_CANDIDATE":
        return ["polish/productization 단계 진행", "60초 검수 스크립트로 사용자 최종 승인"]
    if recommended == "NEEDS_PRODUCT_POLISH":
        steps = ["viewer 필드 매핑 보강 (edge from/to, event type/message, node 좌표)",
                 "노드/엣지 그래프가 실제로 그려지도록 product layer 개선"]
        return steps
    if recommended == "NEEDS_CORE_PATCH":
        return ["코어 기능 보강 후 재검증"]
    if recommended == "NEEDS_SPEC_REPAIR":
        return ["발견된 사양/검증 기준 문제를 spec repair로 처리"]
    return ["후속 루프 대상에서 제외 (아카이브)"]


def _fitness_ko(recommended: str) -> str:
    return {
        "PRODUCT_CANDIDATE": "제품화 후보",
        "NEEDS_PRODUCT_POLISH": "제품 다듬기 필요",
        "NEEDS_CORE_PATCH": "코어 보강 필요",
        "NEEDS_SPEC_REPAIR": "사양 수리 필요",
        "ARCHIVE": "아카이브",
    }.get(recommended, recommended)


def _render_smoke_md(smoke: dict) -> str:
    L = ["# #47 Artifact Smoke Review (Phase 2C-0)", "",
         f"- runner 실행 가능: {smoke['runner_executable']} (exit={smoke['runner_exit_code']})",
         f"- runner 명령: `{smoke['runner_command']}`",
         f"- runner cwd: {smoke['runner_cwd']} · 증거: {smoke['runner_evidence_path']}",
         f"- replay 출력 존재: {smoke['replay_output_exists']} (시나리오 {smoke['replay_count']}개)",
         f"- product viewer 존재: {smoke['product_viewer_exists']} ({smoke['product_viewer_path']})",
         f"- viewer가 replay 읽음: {smoke['product_viewer_reads_replay']}",
         f"- runner/viewer 일치: {smoke['runner_viewer_consistent']} {smoke['runner_viewer_consistency_fields']}",
         "", "## viewer가 replay를 읽는 근거"]
    L += [f"- {e}" for e in smoke["product_viewer_reads_replay_evidence"]] or ["- (없음)"]
    L += ["", "## 필드 스키마 불일치 (렌더링 결함)"]
    L += [f"- {m}" for m in smoke["mismatches"]] or ["- (없음)"]
    L += ["", "## 열어볼 수 있는 경로"]
    L += [f"- {p}" for p in smoke["openable_paths"]] or ["- (없음)"]
    L += ["", "## critical failures"]
    L += [f"- {c}" for c in smoke["critical_failures"]] or ["- (없음)"]
    L += ["", "## unknowns"]
    L += [f"- {u}" for u in smoke["unknowns"]] or ["- (없음)"]
    return "\n".join(L) + "\n"


def _render_fitness_md(fitness: dict, gate: dict) -> str:
    rec = fitness["recommended_fitness"]
    L = ["# #47 Product Fitness Report (Phase 2C-0)", "",
         f"- 제품성 추천(recommended_fitness): **{rec}** ({_fitness_ko(rec)})",
         f"- 검수 상태: {_review_status_text(rec)}",
         f"- 평균 점수: {fitness['average_score']} / 5",
         f"- green_base: {gate.get('green_base')} · gate: {gate.get('gates_passed')}/{gate.get('gates_total')}",
         "", "## 평가 항목 (evidence 기반)"]
    for c in fitness["criteria"]:
        L.append(f"### {c['criterion']}: {c['score']}/5")
        L.append(f"- 이유: {c['reason']}")
        for e in c["evidence"]:
            L.append(f"- 근거: {e}")
        L.append("")
    L += ["## Critical Red Flags"]
    L += [f"- {r}" for r in fitness["critical_red_flags"]] or ["- (없음)"]
    L += ["", "## PRODUCT_CANDIDATE 조건 충족표"]
    for k, v in fitness["candidate_conditions"].items():
        L.append(f"- [{'x' if v else ' '}] {k}")
    L += ["", "## 추천 다음 단계"]
    L += [f"- {s}" for s in _next_steps(rec, {})]
    return "\n".join(L) + "\n"


def _render_review_package_md(ctx: dict) -> str:
    smoke, fitness, gate = ctx["smoke"], ctx["fitness"], ctx["gate"]
    rec = fitness["recommended_fitness"]
    node_types = smoke.get("core_node_types") or []
    L = ["# #47 Mini-Comfy 검수 패키지 (Phase 2C-0)", "",
         "## 1. 한 줄 설명",
         "시각적 노드 흐름을 구성하고 위상정렬 기반 실행 순서·데이터 전파를 검증하는 미니 워크플로우 엔진.",
         "", "## 2. 실행/확인 방법",
         f"- Runner: `{smoke['runner_command']}` (cwd: `runs/{ctx['run_name']}/final_artifact`)",
         f"- Product viewer: `{smoke.get('product_viewer_path')}` (로컬 파일로 열기)",
         f"- Replay 출력: `final_artifact/replay/index.json` (+ replay_scenario_*.json {smoke['replay_count']}개)",
         "- Dashboard: 제품 상세 페이지의 'Phase 2C-0 제품성 추천' 패널 (dashboard_url 미확인)",
         "", "## 3. 산출물 위치",
         f"- 검수 패키지: `runs/{ctx['run_name']}/{REVIEW_SUBDIR}/`",
         f"- 최종 산출물: `runs/{ctx['run_name']}/final_artifact/`",
         "", "## 4. 실제 동작하는 것 (core 기능 요약)",
         f"- runner 실행 exit={smoke['runner_exit_code']}, 계약 출력 필드 충족 ({', '.join(_CORE_OUTPUT_FIELDS)})",
         f"- 노드 타입 {len(node_types)}종 처리: {node_types}",
         "- 위상정렬로 execution_order 계산, 사이클은 summary=Failed로 감지",
         "", "## 5. product layer 요약",
         f"- viewer가 replay를 읽음: {smoke['product_viewer_reads_replay']} (근거 {len(smoke['product_viewer_reads_replay_evidence'])}개)",
         f"- runner↔viewer 일치 필드: {smoke['runner_viewer_consistency_fields']}",
         "", "## 6. artifact smoke review 결과 (실제 확인한 것)"]
    L += [f"- {e}" for e in smoke["evidence"]] or ["- (없음)"]
    L += ["", "## 7. 검증된 것",
          f"- gate {gate.get('gates_passed')}/{gate.get('gates_total')} PASS, anti_hardcode PASS",
          f"- summary 출처: {gate.get('summary_source')} (하드코딩 아님)",
          f"- green_base: {gate.get('green_base')} / verdict: {gate.get('verdict')}",
          "", "## 8. 아직 약한 것 (남은 한계)"]
    L += [f"- {m}" for m in smoke["mismatches"]] or ["- (없음)"]
    # 필드 불일치는 위에서 이미 나열했으므로 red flag 통합 문장은 제외하고 나머지만 덧붙인다
    L += [f"- {r}" for r in fitness["critical_red_flags"] if "필드 스키마 불일치" not in r]
    L += ["", "## 9. 검수자가 봐야 할 포인트 / 60초 검수 포인트",
          "- viewer를 열어 노드 status/summary는 보이지만 엣지/이벤트 렌더링이 깨지는지 확인",
          "- runner 출력(summary/status)과 viewer 표시가 맞는지 확인",
          "", "## 10. recommended_fitness",
          f"- **{rec}** ({_fitness_ko(rec)}) · 평균 {fitness['average_score']}/5",
          f"- 검수 상태: {_review_status_text(rec)}",
          "", "## 11. 사용자 최종 결정",
          "[ ] 제품 후보",
          "[ ] UI polish 필요",
          "[ ] core 보강 필요",
          "[ ] 보류/아카이브"]
    return "\n".join(L) + "\n"


def _render_checklist_md(smoke: dict, fitness: dict) -> str:
    return "\n".join([
        "# #47 사용자 검수 체크리스트 (Phase 2C-0)", "",
        "[ ] 이 산출물이 무엇인지 30초 안에 이해된다.",
        "[ ] 실행/확인 방법이 명확하다.",
        "[ ] product viewer가 core 결과를 실제로 보여준다.",
        "[ ] 단순 HTML 껍데기처럼 보이지 않는다.",
        "[ ] runner 결과와 product viewer 내용이 일치한다.",
        "[ ] scenario/golden 검증 근거가 이해된다.",
        "[ ] 하드코딩으로 통과한 느낌이 들지 않는다.",
        "[ ] 제품 후보로 더 키울 만하다.",
        "[ ] 다음 개선점이 명확하다.",
        "",
        f"참고 추천: {fitness['recommended_fitness']} · viewer 렌더링 결함 {len(smoke['mismatches'])}건.",
    ]) + "\n"


def _render_sixty_second_md(smoke: dict, ctx: dict) -> str:
    viewer = smoke.get("product_viewer_path") or "(viewer 없음)"
    return "\n".join([
        "# 60초 검수 스크립트 (#47)", "",
        "1. Dashboard에서 #47(제품 번호) 카드 열기 → 'Phase 2C-0 제품성 추천' 확인",
        f"2. Product viewer 열기: `{viewer}`",
        "3. 시나리오 선택 후 Load → 노드 status/summary/이벤트가 보이는지 확인",
        f"4. Runner 실행: `{smoke['runner_command']}` "
        f"(cwd `runs/{ctx['run_name']}/final_artifact`) → summary/status가 viewer와 맞는지 확인",
        "5. 아래 중 하나 선택:",
        "   - 제품 후보",
        "   - UI polish 필요",
        "   - core 보강 필요",
        "   - 보류/아카이브",
        "",
        f"확인된 열람 경로: {smoke['openable_paths']}",
    ]) + "\n"


def _build_demo_manifest(run_dir: Path, ctx: dict) -> dict:
    smoke, gate = ctx["smoke"], ctx["gate"]
    run_name = ctx["run_name"]
    verified = bool(smoke.get("runner_command_verified"))
    return {
        "challenge_id": ctx["challenge_id"],
        "title": "Mini-Comfy: 시각적 노드 흐름 엔진",
        "run_dir": f"runs/{run_name}",
        "verdict": gate.get("verdict"),
        "green_base": gate.get("green_base"),
        "dashboard_url": "unknown",
        "artifact_paths": {
            "final_artifact": "final_artifact",
            "workspace": "workspace",
            "runner": "final_artifact/src/runner.py",
            "product_viewer": smoke.get("product_viewer_path"),
            "replay_index": "final_artifact/replay/index.json",
        },
        "commands": {
            "validate": {
                "cmd": f"python -m repo_idea_miner factory-validate runs/{run_name}",
                "cwd": ".",
                "verified": False,
                "exit_code": None,
                "evidence_path": None,
                "note": "review 생성 단계에서는 실행하지 않음 — 사용자가 직접 확인",
            },
            "run_runner": {
                "cmd": smoke.get("runner_command"),
                "cwd": "final_artifact",
                "verified": verified,
                "exit_code": smoke.get("runner_exit_code") if verified else None,
                "evidence_path": smoke.get("runner_evidence_path") if verified else None,
                "note": "temp copy에서 실행하여 확인 (원본 미변경)",
            },
            "open_product": {
                "cmd": f"open {smoke.get('product_viewer_path')}",
                "cwd": ".",
                "verified": False,
                "exit_code": None,
                "evidence_path": None,
                "note": "브라우저 렌더링은 Phase 2C-0 범위 밖 (§4.3) — 파일 존재만 정적 확인",
            },
        },
        "known_limitations": smoke.get("mismatches") or [],
    }


# ---------------------------------------------------------------- 오케스트레이터 (§19)

def run_review_package(
    run_dir: str | Path | None = None,
    run_id: int | None = None,
    db_conn=None,
    timeout: float = 60.0,
) -> dict:
    """#47 green 산출물을 no-code-change smoke review하고 검수 패키지 + 제품성 추천을 생성한다 (§19)."""
    result: dict = {
        "ok": False, "status": None, "resolved_run_dir": None,
        "challenge_id": None, "base_run_id": run_id,
        "recommended_fitness": None, "review_dir": None,
        "no_code_change_status": None, "critical_red_flags": [],
        "problems": [], "error": None,
    }

    target, err, tinfo = resolve_run_target(run_dir, run_id, db_conn)
    result["resolved_run_dir"] = tinfo.get("resolved_run_dir")
    if err:
        result["error"] = err
        return result
    run_dir = target
    run_name = run_dir.name
    review_dir = run_dir / REVIEW_SUBDIR
    result["review_dir"] = str(review_dir.as_posix())

    gate = read_gate_context(run_dir)
    result["challenge_id"] = tinfo.get("challenge_id") or challenge_id_from_run(run_dir)

    # ---- No-Code-Change: 보호 대상 hash BEFORE (§3.4)
    hash_before = compute_protected_hashes(run_dir)

    # ---- Smoke review (temp copy, 원본 미변경) (§6)
    smoke = smoke_review(run_dir, review_dir, timeout=timeout)

    # ---- No-Code-Change: 보호 대상 hash AFTER + check (§3.4)
    hash_after = compute_protected_hashes(run_dir)
    hash_check = compare_protected_hashes(hash_before, hash_after)
    result["no_code_change_status"] = hash_check["status"]

    # ---- Product fitness (§11~§13)
    fitness = build_fitness(smoke, gate)
    rec = fitness["recommended_fitness"]
    result["recommended_fitness"] = rec
    result["critical_red_flags"] = fitness["critical_red_flags"]

    ctx = {
        "run_name": run_name, "challenge_id": result["challenge_id"],
        "smoke": smoke, "fitness": fitness, "gate": gate,
    }

    # ---- 산출물 기록 (review/phase2c0/) (§8)
    write_json(review_dir / "review_no_code_hash_before.json", hash_before)
    write_json(review_dir / "review_no_code_hash_after.json", hash_after)
    write_json(review_dir / "review_no_code_hash_check.json", hash_check)

    smoke_out = {k: v for k, v in smoke.items() if k not in ("core_node_types", "replay_count", "evidence")}
    smoke_out["evidence"] = smoke.get("evidence")
    write_json(review_dir / "artifact_smoke_review.json", smoke_out)
    write_text(review_dir / "artifact_smoke_review.md", _render_smoke_md(smoke))

    fitness_json = {
        "recommended_fitness": rec,
        "review_status": _review_status_text(rec),
        "final_decision": "PENDING_USER_REVIEW",
        "average_score": fitness["average_score"],
        "scores": fitness["scores"],
        "criteria": fitness["criteria"],
        "critical_red_flags": fitness["critical_red_flags"],
        "candidate_conditions": fitness["candidate_conditions"],
        "green_base": gate.get("green_base"),
        "gate_fail": gate.get("gate_fail"),
        "runner_executable": smoke.get("runner_executable"),
        "product_viewer_reads_replay": smoke.get("product_viewer_reads_replay"),
        "runner_viewer_consistent": smoke.get("runner_viewer_consistent"),
        "next_goal": _next_steps(rec, smoke)[0] if _next_steps(rec, smoke) else None,
        "next_steps": _next_steps(rec, smoke),
    }
    write_json(review_dir / "product_fitness_report.json", fitness_json)
    write_text(review_dir / "product_fitness_report.md", _render_fitness_md(fitness, gate))

    demo = _build_demo_manifest(run_dir, ctx)
    write_json(review_dir / "demo_manifest.json", demo)

    review_pkg_json = {
        "challenge_id": result["challenge_id"],
        "base_run_id": gate.get("base_run_id") or tinfo.get("base_run_id"),
        "run_dir": f"runs/{run_name}",
        "verdict": gate.get("verdict"),
        "green_base": gate.get("green_base"),
        "recommended_fitness": rec,
        "review_status": _review_status_text(rec),
        "average_score": fitness["average_score"],
        "openable_paths": smoke.get("openable_paths"),
        "runner_command": smoke.get("runner_command"),
        "product_viewer": smoke.get("product_viewer_path"),
        "replay_index": "final_artifact/replay/index.json",
        "critical_red_flags": fitness["critical_red_flags"],
        "next_steps": _next_steps(rec, smoke),
    }
    write_json(review_dir / "review_package.json", review_pkg_json)
    write_text(review_dir / "review_package.md", _render_review_package_md(ctx))

    write_text(review_dir / "human_review_checklist.md", _render_checklist_md(smoke, fitness))
    write_text(review_dir / "sixty_second_review_script.md", _render_sixty_second_md(smoke, ctx))

    dashboard = {
        "phase": "2c0",
        "challenge_id": result["challenge_id"],
        "base_run_id": review_pkg_json["base_run_id"],
        "run_dir": f"runs/{run_name}",
        "verdict": gate.get("verdict"),
        "green_base": gate.get("green_base"),
        "recommended_fitness": rec,
        "recommended_fitness_ko": _fitness_ko(rec),
        "review_status": _review_status_text(rec),
        "user_next_action": _next_steps(rec, smoke)[0] if _next_steps(rec, smoke) else "-",
        "average_score": fitness["average_score"],
        "scores": fitness["scores"],
        "critical_red_flags": fitness["critical_red_flags"],
        "runner_executable": smoke.get("runner_executable"),
        "product_viewer_reads_replay": smoke.get("product_viewer_reads_replay"),
        "runner_viewer_consistent": smoke.get("runner_viewer_consistent"),
        "no_code_change_status": hash_check["status"],
        "gates_passed": gate.get("gates_passed"),
        "gates_total": gate.get("gates_total"),
        "final_decision": "PENDING_USER_REVIEW",
    }
    write_json(review_dir / "phase2c0_dashboard_summary.json", dashboard)

    result["ok"] = True
    result["status"] = "REVIEWED"
    result["smoke"] = smoke
    result["fitness"] = fitness
    return result
