# Product Factory 산출물의 structured summary json 생성(파이프라인)과 fallback 로딩(대시보드) 모듈 (§5·§6).
from __future__ import annotations

import json
from pathlib import Path

from repo_idea_miner.factory_schemas import VERDICT_TO_RECOMMENDED_ACTION
from repo_idea_miner.redaction import redact_text

GATE_KEYS = ("static", "contract", "syntax", "smoke")
GATE_STATUSES = ("PASS", "FAIL", "SKIP", "UNKNOWN")
QA_STATUSES = ("PASS", "PARTIAL", "FAIL", "UNKNOWN")


# ---------------------------------------------------------------- 공통 유틸

def read_json(path: Path | None) -> dict | None:
    """json 파일을 읽어 dict로 반환. 없거나 깨졌으면 None (대시보드가 절대 죽지 않도록)."""
    if path is None or not Path(path).is_file():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def head_lines(text: str | None, max_lines: int = 30, max_chars: int = 4000) -> str:
    """긴 출력을 앞쪽 몇 줄/글자로 제한한다 (§19 stdout/stderr 길이 제한)."""
    if not text:
        return ""
    lines = text.splitlines()
    clipped = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        clipped += f"\n… (총 {len(lines)}줄 중 {max_lines}줄 표시)"
    if len(clipped) > max_chars:
        clipped = clipped[:max_chars] + "\n… (길이 제한으로 잘림)"
    return clipped


def _command_str(cmd) -> str | None:
    """SandboxResult.command(list) → 사람이 읽을 실제 명령 문자열. sh -c / cmd /c의 마지막 인자를 쓴다."""
    if not cmd:
        return None
    if isinstance(cmd, str):
        return cmd
    if isinstance(cmd, (list, tuple)):
        if len(cmd) >= 3 and cmd[-2] in ("-c", "/c"):
            return str(cmd[-1])
        return " ".join(str(c) for c in cmd)
    return str(cmd)


# ---------------------------------------------------------------- 빌드: gate_summary.json (§6.2)

def _gate_status(result) -> str:
    if result is None:
        return "UNKNOWN"
    if getattr(result, "ok", False):
        return "PASS"
    problems = getattr(result, "problems", []) or []
    if any("생략" in p or "skip" in p.lower() for p in problems):
        return "SKIP"
    return "FAIL"


def _gate_line_summary(result) -> str:
    if result is None:
        return "리포트 없음"
    problems = getattr(result, "problems", []) or []
    if problems:
        return "; ".join(problems)[:400]
    notes = getattr(result, "notes", []) or []
    return ("; ".join(notes) or "통과")[:400]


def _smoke_section(smoke, manifest: dict | None) -> dict:
    status = _gate_status(smoke)
    sec = {"status": status, "summary": _gate_line_summary(smoke)}
    runs = getattr(smoke, "sandbox_runs", []) or []
    chosen = None
    for r in runs:  # 실패한 실행을 우선 노출 (문제 원인 파악용)
        if not getattr(r, "ok", True):
            chosen = r
            break
    if chosen is None and runs:
        chosen = runs[-1]
    if chosen is not None:
        sec.update(
            {
                "command": _command_str(getattr(chosen, "command", None)),
                "exit_code": getattr(chosen, "returncode", None),
                "stdout_preview": head_lines(getattr(chosen, "stdout", "")),
                "stderr_preview": head_lines(getattr(chosen, "stderr", "")),
                "timeout": bool(getattr(chosen, "timed_out", False)),
            }
        )
    else:  # static_web 등 sandbox 실행이 없는 경우
        sec.update(
            {
                "command": (manifest or {}).get("run_command"),
                "exit_code": None,
                "stdout_preview": "",
                "stderr_preview": "",
                "timeout": False,
            }
        )
    return sec


def build_gate_summary(results: dict, manifest: dict | None = None) -> dict:
    """gate 실행 결과(GateResult dict)에서 gate_summary.json 구조를 만든다."""
    out: dict = {}
    for key in ("static", "contract", "syntax"):
        r = results.get(key)
        out[key] = {"status": _gate_status(r), "summary": _gate_line_summary(r)}
    out["smoke"] = _smoke_section(results.get("smoke"), manifest)
    return out


# ---------------------------------------------------------------- 빌드: qa_summary.json (§6.3)

def build_qa_summary(qa: dict | None, judge: dict | None, verdict: str | None) -> dict:
    recommended = VERDICT_TO_RECOMMENDED_ACTION.get(verdict or "", "drop").upper()
    next_goal = (judge or {}).get("next_goal") or ""
    if qa is None:
        return {
            "anchor_status": "UNKNOWN",
            "forbidden_status": "UNKNOWN",
            "core_interaction_status": "UNKNOWN",
            "issue_summary": "QA 미실행 (gate 실패로 건너뜀)",
            "evidence": [],
            "next_goal": next_goal,
            "recommended_action": recommended,
        }
    anchors = qa.get("anchors") or []
    alive = sum(1 for a in anchors if a.get("alive"))
    if anchors and alive == len(anchors):
        anchor_status = "PASS"
    elif alive == 0:
        anchor_status = "FAIL" if anchors else "UNKNOWN"
    else:
        anchor_status = "PARTIAL"

    forbidden = qa.get("forbidden") or []
    violated = [f for f in forbidden if f.get("violated")]
    forbidden_status = "FAIL" if violated else ("PASS" if forbidden else "UNKNOWN")

    core_flags = [qa.get("has_user_action"), qa.get("has_state_change"), qa.get("has_runnable_artifact")]
    core_true = sum(1 for f in core_flags if f)
    if qa.get("is_degenerate") or core_true == 0:
        core_status = "FAIL"
    elif core_true == len(core_flags):
        core_status = "PASS"
    else:
        core_status = "PARTIAL"

    issue = _qa_issue_summary(qa, anchors, violated)
    evidence: list[str] = []
    for a in anchors:
        if not a.get("alive"):
            evidence.append(f"anchor 죽음: {a.get('anchor')} — {a.get('evidence')}")
    for f in violated:
        evidence.append(f"forbidden 위반: {f.get('rule')} — {f.get('evidence')}")
    if not evidence:  # 통과 run이면 살아 있는 근거 몇 개라도 노출
        evidence = [f"{a.get('anchor')}: {a.get('evidence')}" for a in anchors[:3]]

    return {
        "anchor_status": anchor_status,
        "forbidden_status": forbidden_status,
        "core_interaction_status": core_status,
        "issue_summary": issue,
        "evidence": evidence[:8],
        "next_goal": next_goal,
        "recommended_action": recommended,
    }


def _qa_issue_summary(qa: dict, anchors: list, violated: list) -> str:
    if qa.get("is_degenerate"):
        return f"퇴화 의심: {qa.get('degeneration_reason') or '단순화됨'}"
    dead = [a.get("anchor") for a in anchors if not a.get("alive")]
    if dead:
        return "미구현/약화된 anchor: " + ", ".join(str(d) for d in dead)
    if violated:
        return "forbidden 위반: " + ", ".join(str(f.get("rule")) for f in violated)
    return qa.get("summary") or "핵심 결함 없음"


# ---------------------------------------------------------------- 빌드: product_summary.json (§6.1)

def build_product_summary(
    run_id: int | None,
    challenge_id: int | None,
    card: dict,
    status: str,
    stage: str | None,
    verdict: str | None,
    judge: dict | None,
    gate_summary_bool: dict,
    qa_summary: dict,
    workspace_dir: str | None,
    final_artifact_dir: str | None,
    codex_export_dir: str | None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict:
    recommended = VERDICT_TO_RECOMMENDED_ACTION.get(verdict or "", "drop").upper()
    failed_gates = [g for g in GATE_KEYS if g in gate_summary_bool and not gate_summary_bool.get(g)]
    known_issues = [f"gate 실패: {g}" for g in failed_gates]
    qa_issue = qa_summary.get("issue_summary")
    if qa_issue and qa_issue not in ("핵심 결함 없음", "QA 미실행 (gate 실패로 건너뜀)"):
        known_issues.append(qa_issue)
    for w in (judge or {}).get("weaknesses") or []:
        known_issues.append(f"약점: {w}")

    issue_summary = qa_issue or (known_issues[0] if known_issues else "특이 결함 없음")
    next_goal = (judge or {}).get("next_goal") or qa_summary.get("next_goal") or ""
    reason = _hero_reason(verdict, judge, failed_gates, qa_summary)

    return {
        "product_run_id": run_id,
        "challenge_id": challenge_id,
        "challenge_title": card.get("challenge_title"),
        "status": status,
        "stage": stage,
        "verdict": verdict,
        "recommended_action": recommended,
        "reason": reason,
        "issue_summary": issue_summary,
        "known_issues": known_issues,
        "next_goal": next_goal,
        "workspace_dir": workspace_dir,
        "final_artifact_dir": final_artifact_dir,
        "codex_export_dir": codex_export_dir,
        # 원본 challenge가 삭제돼도 상세 화면이 깨지지 않도록 사본을 남긴다 (§15)
        "challenge_anchors": card.get("difficulty_anchors") or [],
        "challenge_forbidden": card.get("forbidden_simplifications") or [],
        "owner_brief_summary": card.get("one_line_challenge") or card.get("repo_summary") or "",
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _hero_reason(verdict: str | None, judge: dict | None, failed_gates: list, qa_summary: dict) -> str:
    if judge and judge.get("reasons"):
        return "; ".join(judge["reasons"])[:400]
    if failed_gates:
        return f"gate 실패({', '.join(failed_gates)})로 자동 판정."
    issue = qa_summary.get("issue_summary")
    if issue and issue not in ("핵심 결함 없음",):
        return issue
    return f"자동 판정 결과: {verdict}."


# ---------------------------------------------------------------- 파이프라인: 파일 쓰기

def write_summary_files(
    dirs: list[Path],
    product_summary: dict,
    gate_summary: dict,
    qa_summary: dict,
    secrets: list[str],
) -> None:
    """summary json 3종을 주어진 디렉터리들(run_dir, final_artifact_dir)에 추가로 쓴다.

    기존 산출물은 건드리지 않는다 (§5: summary json은 추가만).
    """
    payload = {
        "product_summary.json": product_summary,
        "gate_summary.json": gate_summary,
        "qa_summary.json": qa_summary,
    }
    for d in dirs:
        if d is None:
            continue
        d = Path(d)
        if not d.is_dir():
            continue
        for name, data in payload.items():
            text = json.dumps(data, ensure_ascii=False, indent=2)
            (d / name).write_text(redact_text(text, secrets), encoding="utf-8")


# ---------------------------------------------------------------- 대시보드: fallback 로딩

def _first_json(names: list[str], *dirs: Path | None) -> dict | None:
    for d in dirs:
        if d is None:
            continue
        for name in names:
            data = read_json(Path(d) / name)
            if data is not None:
                return data
    return None


def _parse_gate_report_status(text: str) -> str:
    """gate report markdown의 '결과: PASS/FAIL' 라인에서 상태를 뽑는다 (fallback)."""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("결과:") or s.startswith("결과 :"):
            val = s.split(":", 1)[1].strip().upper()
            if "PASS" in val:
                return "PASS"
            if "SKIP" in val:
                return "SKIP"
            if "FAIL" in val:
                return "FAIL"
    return "UNKNOWN"


def load_gate_summary(final_dir: Path | None, run_dir: Path | None) -> dict:
    """gate_summary.json 우선, 없으면 reports/*.md fallback, 그래도 없으면 UNKNOWN (§16)."""
    data = _first_json(["gate_summary.json"], final_dir, run_dir)
    if data:
        out = {}
        for key in GATE_KEYS:
            sec = data.get(key) or {}
            status = (sec.get("status") or "UNKNOWN").upper()
            out[key] = {**sec, "status": status if status in GATE_STATUSES else "UNKNOWN"}
        return out
    out = {}
    report_names = {
        "static": "static_report.md",
        "contract": "contract_report.md",
        "syntax": "syntax_report.md",
        "smoke": "smoke_report.md",
    }
    for key, fname in report_names.items():
        status = "UNKNOWN"
        summary = "리포트 없음"
        for d in (final_dir, run_dir):
            if d is None:
                continue
            p = Path(d) / "reports" / fname
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")
                status = _parse_gate_report_status(text)
                summary = "report에서 추정" if status != "UNKNOWN" else "리포트 파싱 실패"
                break
        out[key] = {"status": status, "summary": summary}
    return out


def load_qa_summary(final_dir: Path | None, run_dir: Path | None) -> dict:
    """qa_summary.json 우선, 없으면 qa_report.md에서 대략적 상태 fallback (§17)."""
    data = _first_json(["qa_summary.json"], final_dir, run_dir)
    if data:
        return data
    for d in (final_dir, run_dir):
        if d is None:
            continue
        p = Path(d) / "reports" / "qa_report.md"
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="replace")
            status = _parse_gate_report_status(text)
            if "SKIP" in text.upper():
                status = "UNKNOWN"
            return {
                "anchor_status": status,
                "forbidden_status": status,
                "core_interaction_status": status,
                "issue_summary": "qa_report.md에서 추정 (structured summary 없음)",
                "evidence": [],
                "next_goal": "",
                "recommended_action": "",
            }
    return {
        "anchor_status": "UNKNOWN",
        "forbidden_status": "UNKNOWN",
        "core_interaction_status": "UNKNOWN",
        "issue_summary": "QA 정보 없음",
        "evidence": [],
        "next_goal": "",
        "recommended_action": "",
    }


def load_product_summary(final_dir: Path | None, run_dir: Path | None) -> dict | None:
    return _first_json(["product_summary.json"], final_dir, run_dir)


def gate_pass_count(gate_summary: dict) -> tuple[int, int]:
    """PASS gate 수와 전체 gate 수 (§8: 'Gate 4/4 PASS')."""
    passed = sum(1 for g in GATE_KEYS if (gate_summary.get(g) or {}).get("status") == "PASS")
    return passed, len(GATE_KEYS)
