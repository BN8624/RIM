# Product Factory 파이프라인: 승격 게이트 → Desk 체인 → 검증 게이트/디버그 루프 → QA/Judge → Final Artifact/Export (§4).
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from repo_idea_miner.challenge_prompts import mock_challenge_package
from repo_idea_miner.config import Settings, load_settings
from repo_idea_miner.factory_db import (
    add_product_artifact,
    create_product_run,
    create_product_task,
    finish_product_task,
    log_product_event,
    update_product_run,
)
from repo_idea_miner.factory_desks import (
    DeskError,
    DeskExecutor,
    render_anchor_check_md,
    render_forbidden_check_md,
    render_known_issues_md,
    render_product_brief_md,
    render_product_verdict_md,
    render_qa_report_md,
    render_technical_plan_md,
    render_ux_flow_md,
)
from repo_idea_miner.factory_gates import (
    run_contract_gate,
    run_smoke_gate,
    run_static_gate,
    run_syntax_gate,
    write_gate_report,
)
from repo_idea_miner.factory_prompts import (
    build_build_prompt,
    build_debug_prompt,
    build_judge_prompt,
    build_product_brief_prompt,
    build_qa_prompt,
    build_technical_spec_prompt,
    build_ux_spec_prompt,
    mock_factory_overrides,
)
from repo_idea_miner.factory_schemas import (
    VERDICT_TO_RECOMMENDED_ACTION,
    BuildOutput,
    DebugOutput,
    JudgeOutput,
    ProductBrief,
    QAOutput,
    TechnicalSpec,
    UXSpec,
    codex_promotion_problems,
    promotion_line,
)
from repo_idea_miner.factory_workspace import (
    apply_file_entries,
    latest_green_base,
    list_workspace_files,
    log_debug_history,
    log_loop_event,
    read_workspace_file,
    rollback_to_green_base,
    save_green_base,
    src_file_count,
    write_workspace_file,
)
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient
from repo_idea_miner.redaction import redact_text, scan_files_for_secrets

# 최종 후보 최소 요건 (§1)
FINAL_ARTIFACT_REQUIRED_FILES = (
    "README.md",
    "run_instructions.md",
    "manifest.json",
    "contract.json",
    "reports/syntax_report.md",
    "reports/contract_report.md",
    "reports/smoke_report.md",
    "reports/qa_report.md",
    "debug_history.jsonl",
    "product_verdict.md",
)

GATE_ORDER = ("static", "contract", "syntax", "smoke")

CODEX_EXPORT_DOCS = (
    "challenge_card.md",
    "product_brief.md",
    "ux_flow.md",
    "technical_plan.md",
)


@dataclass
class FactorySettings:
    max_debug_rounds: int = 2
    sandbox_timeout_seconds: float = 120.0
    use_docker: str = "auto"  # auto | on | off

    def docker_flag(self) -> bool | None:
        if self.use_docker == "on":
            return True
        if self.use_docker == "off":
            return False
        return None  # auto → docker_available()


def load_factory_settings(env=None) -> FactorySettings:
    env = env if env is not None else os.environ
    def _int(key: str, default: int) -> int:
        try:
            return int((env.get(key) or "").strip())
        except (ValueError, AttributeError):
            return default
    def _float(key: str, default: float) -> float:
        try:
            return float((env.get(key) or "").strip())
        except (ValueError, AttributeError):
            return default
    use_docker = (env.get("RIM_FACTORY_USE_DOCKER") or "auto").strip().lower()
    if use_docker not in ("auto", "on", "off"):
        use_docker = "auto"
    return FactorySettings(
        max_debug_rounds=_int("RIM_FACTORY_MAX_DEBUG_ROUNDS", 2),
        sandbox_timeout_seconds=_float("RIM_FACTORY_SANDBOX_TIMEOUT_SECONDS", 120.0),
        use_docker=use_docker,
    )


# ---------------------------------------------------------------- challenge 로딩

def sample_challenge() -> dict:
    """실제 challenge_id 없이 쓰는 고정 sample challenge (§19.2 --sample mock)."""
    pkg = mock_challenge_package("sample/mock-product", "https://github.com/sample/mock-product")
    return {
        "challenge_id": None,
        "card": pkg["challenge_card"],
        "owner_clarity_score": pkg["owner_brief"]["owner_clarity_score"],
        "repo_url": "https://github.com/sample/mock-product",
    }


def load_challenge_from_dir(challenge_dir: str | Path) -> dict:
    """DB 없이 run artifact 디렉터리에서 challenge를 읽는 fallback 경로."""
    d = Path(challenge_dir)
    card_path = d / "challenge_card.json"
    if not card_path.is_file():
        raise FileNotFoundError(f"challenge_card.json 없음: {d}")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    clarity = None
    brief_path = d / "owner_brief.json"
    if brief_path.is_file():
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        clarity = brief.get("owner_clarity_score")
    return {"challenge_id": None, "card": card, "owner_clarity_score": clarity, "repo_url": card.get("source_repo")}


def load_challenge_from_db(conn, challenge_id: int) -> dict:
    """challenge.db의 challenge row를 source of truth로 사용한다 (§19.2)."""
    row = conn.execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
    if row is None:
        raise ValueError(f"challenge {challenge_id} 없음")
    c = dict(row)
    loaded = load_challenge_from_dir(c["artifact_dir"])
    loaded["challenge_id"] = challenge_id
    loaded["repo_url"] = c.get("repo_url") or loaded.get("repo_url")
    if loaded.get("owner_clarity_score") is None:
        loaded["owner_clarity_score"] = c.get("owner_clarity_score")
    return loaded


def challenge_context_md(card: dict) -> str:
    ci = card.get("core_interaction") or {}
    return "\n".join(
        [
            f"# Challenge: {card.get('challenge_title')}",
            "",
            f"- source repo: {card.get('source_repo')}",
            f"- 한 줄 과제: {card.get('one_line_challenge')}",
            f"- 요약: {card.get('repo_summary')}",
            "",
            "## Core Interaction",
            f"- actor: {ci.get('actor')}",
            f"- trigger: {ci.get('trigger')}",
            f"- loop: {ci.get('loop')}",
            f"- state_change: {ci.get('state_change')}",
            f"- hard_part: {ci.get('hard_part')}",
            "",
            "## Difficulty Anchors (절대 삭제 금지)",
            *[f"- {a}" for a in card.get("difficulty_anchors") or []],
            "",
            "## Forbidden Simplifications (위반 금지)",
            *[f"- {f}" for f in card.get("forbidden_simplifications") or []],
            "",
            "## Allowed Simplifications",
            *[f"- {a}" for a in card.get("allowed_simplifications") or []],
            "",
            "## Pass Criteria",
            *[f"- {p}" for p in card.get("pass_criteria") or []],
            "",
            "## Failure Criteria",
            *[f"- {p}" for p in card.get("failure_criteria") or []],
            "",
            "## Implementation Prompt",
            card.get("implementation_prompt") or "",
        ]
    )


def make_factory_run_dir(output_dir: str | Path) -> Path:
    base = Path(output_dir)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = base / f"factory_{ts}"
    suffix = 1
    while run_dir.exists():
        run_dir = base / f"factory_{ts}_{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    return run_dir


# ---------------------------------------------------------------- patch 후보 선택 (§11.2)

@dataclass
class PatchCandidate:
    candidate_id: str
    applicable: bool
    syntax_ok: bool
    contract_ok: bool
    smoke_ok: bool
    changed_files: int
    anchor_score: int = 0
    forbidden_violations: int = 0


def select_patch_candidate(candidates: list[PatchCandidate]) -> PatchCandidate | None:
    """§11.2 순서로 patch 후보를 고른다: 적용 가능 → 문법 → contract → smoke →
    수정 범위 작음 → anchor 점수 높음 → forbidden 위반 적음."""
    viable = [c for c in candidates if c.applicable]
    if not viable:
        return None
    return sorted(
        viable,
        key=lambda c: (
            not c.syntax_ok,
            not c.contract_ok,
            not c.smoke_ok,
            c.changed_files,
            -c.anchor_score,
            c.forbidden_violations,
        ),
    )[0]


# ---------------------------------------------------------------- 파이프라인 본체

def run_product_factory(
    challenge: dict,
    mode: str = "mock",
    output_dir: str | Path = "runs",
    db_conn=None,
    settings: Settings | None = None,
    factory_settings: FactorySettings | None = None,
    scheduler=None,
    llm=None,
    run_dir: Path | None = None,
    force_line: str | None = None,
) -> dict:
    """Challenge 하나를 Final Artifact까지 사람 개입 없이 밀어붙인다.

    challenge: {"challenge_id", "card", "owner_clarity_score", "repo_url"} dict.
    반환: 요약 dict (run_dir/verdict/gate_summary/final_artifact_dir 등).
    """
    settings = settings or load_settings()
    fset = factory_settings or load_factory_settings()
    secrets = settings.secret_values()
    card = challenge["card"]
    challenge_id = challenge.get("challenge_id")

    result: dict = {
        "ok": False,
        "run_dir": None,
        "product_run_id": None,
        "challenge_id": challenge_id,
        "line": None,
        "verdict": None,
        "recommended_action": None,
        "gate_summary": {},
        "debug_rounds": 0,
        "final_artifact_dir": None,
        "codex_export_dir": None,
        "auto_adjustments": [],
        "error": None,
    }

    # 1. Auto Promotion Gate (§6)
    line, gate_reasons = promotion_line(card, challenge.get("owner_clarity_score"))
    if force_line:
        line = force_line
    if line is None:
        result["error"] = "승격 기준 미달: " + "; ".join(gate_reasons)
        if db_conn is not None:
            log_product_event(db_conn, None, "promotion_rejected", result["error"],
                              metadata={"challenge_id": challenge_id})
        return result
    result["line"] = line

    run_dir = run_dir or make_factory_run_dir(output_dir)
    workspace = run_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    result["run_dir"] = str(run_dir)

    run_id = None
    if db_conn is not None:
        run_id = create_product_run(db_conn, challenge_id, str(run_dir / "workspace"), line)
        result["product_run_id"] = run_id
        log_product_event(db_conn, run_id, "factory_start",
                          f"line={line} mode={mode} challenge_id={challenge_id}")

    # debug_history.jsonl은 시작 시점부터 존재해야 한다 (§16 조건 10)
    log_debug_history(run_dir, secrets, {"event": "factory_start", "line": line, "mode": mode})
    log_loop_event(run_dir, secrets, stage="promotion_gate", validation="PASS",
                   next_state="planning", reasons=gate_reasons)

    if llm is None and mode == "mock":
        llm = MockLLMClient(overrides=mock_factory_overrides(),
                            call_logger=LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", secrets))
    call_logger = LLMCallLogger(run_dir / "debug" / "llm_calls.jsonl", secrets)
    executor = DeskExecutor(mode, settings, scheduler=scheduler, llm=llm, call_logger=call_logger)

    context = challenge_context_md(card)
    anchors = card.get("difficulty_anchors") or []
    forbidden = card.get("forbidden_simplifications") or []

    def _write_run_doc(name: str, text: str) -> None:
        (run_dir / name).write_text(redact_text(text, secrets), encoding="utf-8")

    def _stage(stage: str) -> None:
        if db_conn is not None and run_id is not None:
            update_product_run(db_conn, run_id, current_stage=stage)

    def _desk_call(desk_name: str, schema_name: str, prompt: str, model_cls, input_artifact=None):
        """Desk 호출 + product_tasks 기록. DeskError는 위로 전달."""
        task_id = None
        if db_conn is not None and run_id is not None:
            task_id = create_product_task(db_conn, run_id, desk_name, input_artifact=input_artifact)
        try:
            model, key_label = executor.call(schema_name, prompt, model_cls)
        except DeskError as exc:
            if task_id is not None:
                finish_product_task(db_conn, task_id, "error", last_error=str(exc))
            raise
        if task_id is not None:
            conn_updates = {"output_artifact": schema_name, "attempt_count": 1}
            finish_product_task(db_conn, task_id, "done", **conn_updates)
            # worker_key_id 갱신 (실제 key 값이 아니라 KEY_NN 라벨)
            db_conn.execute("UPDATE product_tasks SET worker_key_id=? WHERE id=?", (key_label, task_id))
            db_conn.commit()
        return model, key_label

    def _fail_run(stage: str, msg: str) -> dict:
        result["error"] = msg
        if db_conn is not None and run_id is not None:
            update_product_run(db_conn, run_id, status="error", current_stage=stage)
            log_product_event(db_conn, run_id, "factory_error", msg[:300])
        log_loop_event(run_dir, secrets, stage=stage, validation="FAIL", error=msg[:300])
        return result

    try:
        # 2. Product Planning Desk (§7.1)
        _stage("planning")
        brief_model, key_label = _desk_call(
            "planning", "product_brief", build_product_brief_prompt(context, line), ProductBrief
        )
        brief = brief_model.model_dump()
        brief_md = render_product_brief_md(brief)
        _write_run_doc("product_brief.md", brief_md)
        log_loop_event(run_dir, secrets, stage="planning", desk="Product Planning Desk",
                       worker_key_id=key_label, output_files=["product_brief.md"],
                       validation="PASS", next_state="ux_spec")

        # 3. UX/Spec Desk (§7.2)
        _stage("ux_spec")
        ux_model, key_label = _desk_call(
            "ux_spec", "ux_spec", build_ux_spec_prompt(context, brief_md, line), UXSpec
        )
        ux = ux_model.model_dump()
        ux_md = render_ux_flow_md(ux)
        _write_run_doc("ux_flow.md", ux_md)
        _write_run_doc("screen_spec.json", json.dumps(ux["screen_spec"], ensure_ascii=False, indent=2))
        _write_run_doc("state_transition_spec.json", json.dumps(ux["state_transitions"], ensure_ascii=False, indent=2))
        log_loop_event(run_dir, secrets, stage="ux_spec", desk="UX/Spec Desk",
                       worker_key_id=key_label,
                       output_files=["ux_flow.md", "screen_spec.json", "state_transition_spec.json"],
                       validation="PASS", next_state="technical_spec")

        # 4. Technical Spec Desk (§7.3)
        _stage("technical_spec")
        spec_model, key_label = _desk_call(
            "technical_spec", "technical_spec",
            build_technical_spec_prompt(context, brief_md, ux_md, line), TechnicalSpec,
        )
        spec = spec_model.model_dump()
        manifest, contract = spec["manifest"], spec["contract"]
        _write_run_doc("technical_plan.md", render_technical_plan_md(spec))
        _write_run_doc("build_task_packet.md", spec["build_task_packet"])
        write_workspace_file(workspace, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2), secrets)
        write_workspace_file(workspace, "contract.json", json.dumps(contract, ensure_ascii=False, indent=2), secrets)
        log_loop_event(run_dir, secrets, stage="technical_spec", desk="Technical Spec Desk",
                       worker_key_id=key_label,
                       output_files=["technical_plan.md", "manifest.json", "contract.json", "build_task_packet.md"],
                       validation="PASS", next_state="build")

        # 5. Build Desk (§7.4)
        _stage("build")
        build_model, key_label = _desk_call(
            "build", "build_output",
            build_build_prompt(context, json.dumps(manifest, ensure_ascii=False),
                               json.dumps(contract, ensure_ascii=False),
                               spec["build_task_packet"], list_workspace_files(workspace), line),
            BuildOutput,
        )
        build_out = build_model.model_dump()
        written = apply_file_entries(workspace, build_out["files"], secrets)
        write_workspace_file(workspace, "reports/build_report.md",
                             f"# Build Report\n\n{build_out['build_report']}\n", secrets)
        if not (workspace / "run_instructions.md").is_file():
            # Build Desk가 실행 방법을 빠뜨리면 manifest에서 최소 실행 안내를 생성한다
            checks = "\n".join(f"```bash\n{c}\n```" for c in manifest.get("check_commands") or [])
            write_workspace_file(
                workspace, "run_instructions.md",
                f"# 실행 방법\n\n## 실행\n```bash\n{manifest.get('run_command')}\n```\n\n## 검증\n{checks}\n",
                secrets,
            )
        log_loop_event(run_dir, secrets, stage="build", desk="Build Desk",
                       worker_key_id=key_label, output_files=written,
                       validation="PASS", next_state="static_gate")

        # 6. Gate 체인 + Debug 루프 (§7.5~§7.9)
        gate_summary, debug_rounds = _run_gate_loop(
            run_dir, workspace, manifest, contract, secrets, executor, fset,
            context, db_conn, run_id, _stage, _desk_call,
        )
        result["gate_summary"] = gate_summary
        result["debug_rounds"] = debug_rounds
        gates_all_pass = all(gate_summary.get(g) for g in GATE_ORDER)

        qa = None
        qa_pass = False
        judge = None
        auto_adjustments: list[str] = []

        if gates_all_pass:
            save_green_base(run_dir, workspace, f"green_{debug_rounds:02d}")
            # 7. QA Desk (§7.10)
            _stage("qa")
            key_files = {
                rel: read_workspace_file(workspace, rel, 3500)
                for rel in list_workspace_files(workspace)
                if rel.startswith("src/") or rel == manifest.get("entrypoint")
            }
            gate_md = "\n".join(f"- {g}: {'PASS' if ok else 'FAIL'}" for g, ok in gate_summary.items())
            qa_model, key_label = _desk_call(
                "qa", "qa_output",
                build_qa_prompt(anchors, forbidden, list_workspace_files(workspace), key_files, gate_md),
                QAOutput,
            )
            qa = qa_model.model_dump()
            qa_pass = qa_model.qa_pass()
            write_workspace_file(workspace, "reports/qa_report.md", render_qa_report_md(qa, qa_pass), secrets)
            write_workspace_file(workspace, "reports/anchor_check.md", render_anchor_check_md(qa), secrets)
            write_workspace_file(workspace, "reports/forbidden_simplification_check.md",
                                 render_forbidden_check_md(qa), secrets)
            log_loop_event(run_dir, secrets, stage="qa", desk="QA Desk", worker_key_id=key_label,
                           output_files=["reports/qa_report.md", "reports/anchor_check.md",
                                         "reports/forbidden_simplification_check.md"],
                           validation="PASS" if qa_pass else "FAIL", next_state="judge")

            # 8. Judge Desk (§7.11)
            _stage("judge")
            qa_md = render_qa_report_md(qa, qa_pass)
            judge_model, key_label = _desk_call(
                "judge", "judge_output",
                build_judge_prompt(context, gate_md, qa_md, debug_rounds, line), JudgeOutput,
            )
            judge = judge_model.model_dump()
            verdict = judge["verdict"]
            log_loop_event(run_dir, secrets, stage="judge", desk="Judge Desk", worker_key_id=key_label,
                           validation="PASS", next_state="final_artifact", verdict=verdict)
        else:
            # gate 반복 실패 → 자동 판정 (§5)
            _write_missing_reports(workspace, gate_summary)
            passed = sum(1 for g in GATE_ORDER if gate_summary.get(g))
            if src_file_count(workspace) < 2:
                verdict = "DROP"
            elif passed == 0:
                verdict = "TOO_WEAK"
            else:
                verdict = "NEEDS_MORE_GEMMA_LOOP"
            auto_adjustments.append(f"gate 실패({passed}/{len(GATE_ORDER)} 통과) → 자동 판정 {verdict}")

        # 9. 판정 자동 보정 (harness가 최종 결정)
        if judge is not None:
            verdict = judge["verdict"]
            promo_problems = codex_promotion_problems(
                gate_summary, qa_model if qa else None, (run_dir / "debug_history.jsonl").is_file()
            )
            if verdict == "PROMOTE_TO_CODEX" and not qa_pass:
                verdict = "NEEDS_MORE_GEMMA_LOOP"
                auto_adjustments.append("QA 미통과 → PROMOTE_TO_CODEX 강등")
            elif verdict == "PROMOTE_TO_CODEX" and promo_problems:
                verdict = "KEEP_CANDIDATE"
                auto_adjustments.append("Codex 승격 조건 미달 → KEEP_CANDIDATE 강등: " + "; ".join(promo_problems))
            if line == "micro" and verdict == "PROMOTE_TO_CODEX" and not (qa_pass and gates_all_pass):
                verdict = "KEEP_CANDIDATE"
                auto_adjustments.append("micro 라인 기본 규칙 → KEEP_CANDIDATE 우선 (§6.2)")

        result["verdict"] = verdict
        result["auto_adjustments"] = auto_adjustments
        recommended = VERDICT_TO_RECOMMENDED_ACTION.get(verdict, "drop")
        result["recommended_action"] = recommended

        # 10. Final Artifact (§1)
        _stage("final_artifact")
        verdict_md = render_product_verdict_md(verdict, judge, gate_summary, line, auto_adjustments, recommended)
        _write_run_doc("product_verdict.md", verdict_md)
        final_dir = _assemble_final_artifact(run_dir, workspace, verdict_md, secrets)
        result["final_artifact_dir"] = str(final_dir)

        # 11. Codex/Claude export bundle (§16) — 자동 호출이 아니라 bundle 생성까지만
        if verdict == "PROMOTE_TO_CODEX":
            export_dir = _assemble_codex_export(run_dir, workspace, card, judge, gate_summary, qa, secrets)
            result["codex_export_dir"] = str(export_dir)
            if db_conn is not None and run_id is not None:
                add_product_artifact(db_conn, run_id, "codex_export", str(export_dir))

        # 12. secret scan (전체 run_dir)
        leaked = scan_files_for_secrets([p for p in run_dir.rglob("*") if p.is_file()], secrets)
        if leaked:
            result["error"] = f"secret 노출 파일: {leaked}"

        if db_conn is not None and run_id is not None:
            update_product_run(db_conn, run_id, status="done", current_stage="final_artifact",
                               final_artifact_dir=str(final_dir), verdict=verdict)
            add_product_artifact(db_conn, run_id, "workspace", str(workspace))
            add_product_artifact(db_conn, run_id, "final_artifact", str(final_dir))
            add_product_artifact(db_conn, run_id, "product_verdict", str(final_dir / "product_verdict.md"))
            log_product_event(db_conn, run_id, "factory_done", f"verdict={verdict}",
                              metadata={"gate_summary": gate_summary, "debug_rounds": debug_rounds})

        log_loop_event(run_dir, secrets, stage="final_artifact", validation="PASS",
                       output_files=[str(final_dir)], verdict=verdict, next_state="dashboard_review")
        result["ok"] = result["error"] is None
        return result

    except DeskError as exc:
        return _fail_run("desk_error", str(exc))
    except Exception as exc:  # noqa: BLE001 - run 하나의 실패가 상위 루프를 죽이면 안 됨
        return _fail_run("internal_error", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------- gate loop / debug desk

def _run_gates(workspace: Path, manifest: dict, contract: dict, secrets: list[str],
               fset: FactorySettings) -> tuple[dict, dict]:
    """4개 gate를 순서대로 실행하고 (summary, results)를 반환한다. 실패해도 끝까지 돌며 리포트를 남긴다."""
    results = {
        "static": run_static_gate(workspace, manifest, secrets),
        "contract": run_contract_gate(workspace, contract, manifest),
        "syntax": run_syntax_gate(workspace),
    }
    # smoke는 문법이 통과한 경우에만 의미가 있다 (싼 검사 우선, §14)
    if results["syntax"].ok and results["static"].ok:
        results["smoke"] = run_smoke_gate(
            workspace, manifest, secrets,
            use_docker=fset.docker_flag(), timeout_seconds=fset.sandbox_timeout_seconds,
        )
    else:
        from repo_idea_miner.factory_gates import GateResult

        results["smoke"] = GateResult(name="Smoke Gate", ok=False,
                                      problems=["선행 gate(static/syntax) 실패로 실행 검사 생략"])
    write_gate_report(workspace, "static_report.md", results["static"])
    write_gate_report(workspace, "contract_report.md", results["contract"])
    write_gate_report(workspace, "syntax_report.md", results["syntax"])
    write_gate_report(workspace, "smoke_report.md", results["smoke"])
    summary = {name: r.ok for name, r in results.items()}
    return summary, results


def _run_gate_loop(run_dir, workspace, manifest, contract, secrets, executor, fset,
                   context, db_conn, run_id, _stage, _desk_call) -> tuple[dict, int]:
    """gate 실행 → 실패 시 Debug Desk → 재검증. 최대 fset.max_debug_rounds회 (§7.9)."""
    debug_rounds = 0
    while True:
        _stage("static_gate")
        summary, results = _run_gates(workspace, manifest, contract, secrets, fset)
        for gate in GATE_ORDER:
            log_loop_event(run_dir, secrets, stage=f"{gate}_gate", desk=f"{gate.title()} Gate",
                           worker_key_id="HARNESS",
                           validation="PASS" if summary[gate] else "FAIL",
                           error=None if summary[gate] else "; ".join(results[gate].problems)[:300],
                           next_state="next_gate" if summary[gate] else "debug")
        failed = [g for g in GATE_ORDER if not summary[g]]
        if not failed:
            return summary, debug_rounds
        if debug_rounds >= fset.max_debug_rounds:
            # 무한 루프 금지 (§7.9) — green base가 있으면 복원
            if latest_green_base(run_dir) is not None:
                rollback_to_green_base(run_dir, workspace)
                log_debug_history(run_dir, secrets,
                                  {"event": "rollback_to_green_base", "reason": "debug 한도 초과"})
            log_debug_history(run_dir, secrets,
                              {"event": "debug_exhausted", "rounds": debug_rounds, "failed_gates": failed})
            return summary, debug_rounds

        # Debug Desk (§7.9)
        debug_rounds += 1
        _stage("debug")
        error_log = "\n\n".join(results[g].report_md() for g in failed)
        (workspace / "reports").mkdir(exist_ok=True)
        (workspace / "reports" / "error_log.md").write_text(
            redact_text(error_log, secrets), encoding="utf-8"
        )
        key_files = {}
        for gate in failed:
            for problem in results[gate].problems:
                for rel in list_workspace_files(workspace):
                    if rel in problem and rel not in key_files:
                        key_files[rel] = read_workspace_file(workspace, rel, 4000)
        if not key_files:
            entry = manifest.get("entrypoint")
            if entry:
                key_files[entry] = read_workspace_file(workspace, entry, 4000)
        try:
            debug_model, key_label = _desk_call(
                "debug", "debug_output",
                build_debug_prompt(error_log, list_workspace_files(workspace), key_files,
                                   json.dumps(contract, ensure_ascii=False),
                                   debug_rounds, fset.max_debug_rounds),
                DebugOutput, input_artifact="reports/error_log.md",
            )
        except DeskError as exc:
            log_debug_history(run_dir, secrets, {"event": "debug_desk_error", "error": str(exc)[:300]})
            return summary, debug_rounds
        debug_out = debug_model.model_dump()
        written = apply_file_entries(workspace, debug_out["files"], secrets)
        write_workspace_file(workspace, "reports/debug_report.md",
                             f"# Debug Report (round {debug_rounds})\n\n{debug_out['debug_report']}\n", secrets)
        log_debug_history(run_dir, secrets, {
            "event": "debug_patch_applied", "round": debug_rounds,
            "failed_gates": failed, "files": written, "worker_key_id": key_label,
            "report": debug_out["debug_report"][:300],
        })
        log_loop_event(run_dir, secrets, stage="debug", desk="Debug Desk", worker_key_id=key_label,
                       input_files=["reports/error_log.md"], output_files=written,
                       validation="APPLIED", next_state="static_gate")


def _write_missing_reports(workspace: Path, gate_summary: dict) -> None:
    """gate 실패로 QA를 건너뛴 경우에도 최소 qa_report를 남긴다."""
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    qa_path = reports / "qa_report.md"
    if not qa_path.is_file():
        failed = [g for g, ok in gate_summary.items() if not ok]
        qa_path.write_text(
            "# QA Report\n\n결과: SKIPPED\n\n"
            f"gate 실패({', '.join(failed)})로 QA Desk를 실행하지 않았다.\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------- final artifact / export

def _assemble_final_artifact(run_dir: Path, workspace: Path, verdict_md: str, secrets: list[str]) -> Path:
    final_dir = run_dir / "final_artifact"
    if final_dir.exists():
        shutil.rmtree(final_dir)
    shutil.copytree(workspace, final_dir)
    debug_history = run_dir / "debug_history.jsonl"
    if debug_history.is_file():
        shutil.copy2(debug_history, final_dir / "debug_history.jsonl")
    (final_dir / "product_verdict.md").write_text(redact_text(verdict_md, secrets), encoding="utf-8")
    return final_dir


def _assemble_codex_export(run_dir: Path, workspace: Path, card: dict, judge: dict | None,
                           gate_summary: dict, qa: dict | None, secrets: list[str]) -> Path:
    from repo_idea_miner.challenge_renderer import render_challenge_card_md

    export_dir = run_dir / "codex_export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)
    shutil.copytree(workspace, export_dir / "source_workspace")
    for name in ("manifest.json", "contract.json"):
        src = workspace / name
        if src.is_file():
            shutil.copy2(src, export_dir / name)
    (export_dir / "challenge_card.md").write_text(
        redact_text(render_challenge_card_md(card), secrets), encoding="utf-8"
    )
    for doc in ("product_brief.md", "ux_flow.md", "technical_plan.md"):
        src = run_dir / doc
        if src.is_file():
            shutil.copy2(src, export_dir / doc)
    for report in ("syntax_report.md", "smoke_report.md", "qa_report.md"):
        src = workspace / "reports" / report
        if src.is_file():
            shutil.copy2(src, export_dir / report)
    debug_history = run_dir / "debug_history.jsonl"
    if debug_history.is_file():
        shutil.copy2(debug_history, export_dir / "debug_history.jsonl")
    (export_dir / "known_issues.md").write_text(
        redact_text(render_known_issues_md(judge, gate_summary, qa), secrets), encoding="utf-8"
    )
    next_goal = (judge or {}).get("next_goal") or "구조 정리와 테스트 강화."
    (export_dir / "next_goal.md").write_text(
        redact_text(f"# Next Goal\n\n{next_goal}\n", secrets), encoding="utf-8"
    )
    return export_dir
