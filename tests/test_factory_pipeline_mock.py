# Product Factory mock 파이프라인 E2E: Desk 산출물·gate·debug 루프·verdict·export·DB 기록 테스트.
import json

import pytest

from repo_idea_miner.config import Settings
from repo_idea_miner.factory_db import open_factory_db
from repo_idea_miner.factory_pipeline import (
    FactorySettings,
    PatchCandidate,
    run_product_factory,
    sample_challenge,
    select_patch_candidate,
)
from repo_idea_miner.factory_prompts import (
    mock_broken_build_output,
    mock_factory_overrides,
    mock_qa_output,
)
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off")
SETTINGS = Settings(google_keys={})


def _run(tmp_path, overrides=None, db=False, fset=FSET):
    conn = open_factory_db(tmp_path / "challenge.db") if db else None
    llm = MockLLMClient(overrides={**mock_factory_overrides(), **(overrides or {})},
                        call_logger=LLMCallLogger(None))
    try:
        result = run_product_factory(
            sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
            db_conn=conn, settings=SETTINGS, factory_settings=fset, llm=llm,
        )
        return result, conn, llm
    finally:
        if conn is not None and not db:
            conn.close()


@pytest.fixture(scope="module")
def full_run(tmp_path_factory):
    """전체 mock run 1회 (module 공유로 속도 확보)."""
    tmp_path = tmp_path_factory.mktemp("factory_full")
    conn = open_factory_db(tmp_path / "challenge.db")
    llm = MockLLMClient(overrides=mock_factory_overrides(), call_logger=LLMCallLogger(None))
    result = run_product_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=SETTINGS, factory_settings=FSET, llm=llm,
    )
    yield result, conn, llm, tmp_path
    conn.close()


def test_full_mock_run_succeeds(full_run):
    result, _, _, _ = full_run
    assert result["ok"], result["error"]
    assert result["line"] == "standard"
    assert all(result["gate_summary"].values()), result["gate_summary"]


def test_desk_documents_created(full_run):
    """product_brief/ux_flow/technical_plan/manifest/contract 생성 (§22-10~14)."""
    result, _, _, _ = full_run
    from pathlib import Path

    run_dir = Path(result["run_dir"])
    for doc in ("product_brief.md", "ux_flow.md", "technical_plan.md",
                "screen_spec.json", "state_transition_spec.json", "build_task_packet.md"):
        assert (run_dir / doc).is_file(), doc
    ws = run_dir / "workspace"
    manifest = json.loads((ws / "manifest.json").read_text(encoding="utf-8"))
    contract = json.loads((ws / "contract.json").read_text(encoding="utf-8"))
    assert manifest["entrypoint"] and manifest["files"]
    assert contract["difficulty_anchor_requirements"]


def test_multifile_workspace_created(full_run):
    """멀티파일 src 생성 (§22-15) — 단일파일이면 실패."""
    result, _, _, _ = full_run
    from pathlib import Path

    final = Path(result["final_artifact_dir"])
    src_files = [p for p in (final / "src").rglob("*") if p.is_file()]
    assert len(src_files) >= 2
    assert (final / "README.md").is_file()
    assert (final / "run_instructions.md").is_file()
    assert (final / "checks").is_dir()


def test_reports_and_verdict_created(full_run):
    """smoke/qa/verdict 리포트 생성 (§22-22~24)."""
    result, _, _, _ = full_run
    from pathlib import Path

    final = Path(result["final_artifact_dir"])
    for report in ("syntax_report.md", "contract_report.md", "smoke_report.md",
                   "qa_report.md", "anchor_check.md", "forbidden_simplification_check.md"):
        assert (final / "reports" / report).is_file(), report
    verdict_text = (final / "product_verdict.md").read_text(encoding="utf-8")
    assert "PROMOTE_TO_CODEX" in verdict_text
    assert result["verdict"] == "PROMOTE_TO_CODEX"
    assert result["recommended_action"] == "productize"


def test_codex_export_bundle_created(full_run):
    """PROMOTE_TO_CODEX → codex_export bundle 생성 (§22-25)."""
    result, _, _, _ = full_run
    from pathlib import Path

    export = Path(result["codex_export_dir"])
    for item in ("source_workspace", "manifest.json", "contract.json", "challenge_card.md",
                 "product_brief.md", "ux_flow.md", "technical_plan.md", "syntax_report.md",
                 "smoke_report.md", "qa_report.md", "debug_history.jsonl",
                 "known_issues.md", "next_goal.md"):
        assert (export / item).exists(), item


def test_no_codex_auto_invocation(full_run):
    """PROMOTE_TO_CODEX는 export bundle 생성일 뿐 Codex/Claude 호출이 아니다 (§22-26)."""
    _, _, llm, _ = full_run
    workers = {e["worker"] for e in llm.logger.entries}
    assert workers <= {"product_brief", "ux_spec", "technical_spec", "build_output",
                       "debug_output", "qa_output", "judge_output"}
    assert not any("codex" in w.lower() or "claude" in w.lower() for w in workers)


def test_db_rows_created(full_run):
    """product_runs/product_tasks/product_events row 생성 (§22-27)."""
    result, conn, _, _ = full_run
    run = conn.execute("SELECT * FROM product_runs WHERE id=?", (result["product_run_id"],)).fetchone()
    assert run["status"] == "done" and run["verdict"] == "PROMOTE_TO_CODEX"
    tasks = [dict(r) for r in conn.execute("SELECT * FROM product_tasks WHERE product_run_id=?", (run["id"],))]
    desk_names = {t["desk_name"] for t in tasks}
    assert {"planning", "ux_spec", "technical_spec", "build", "qa", "judge"} <= desk_names
    assert conn.execute("SELECT COUNT(*) FROM product_events WHERE product_run_id=?", (run["id"],)).fetchone()[0] >= 2
    assert conn.execute("SELECT COUNT(*) FROM product_artifacts WHERE product_run_id=?", (run["id"],)).fetchone()[0] >= 3


def test_worker_key_id_contains_no_secret(full_run, fake_env):
    """worker_key_id가 실제 secret을 포함하지 않는다 (§22-28)."""
    result, conn, _, _ = full_run
    for row in conn.execute("SELECT worker_key_id FROM product_tasks"):
        v = row["worker_key_id"] or ""
        assert v in ("MOCK", "HARNESS") or v.startswith("KEY_")
        for secret in fake_env.values():
            assert secret not in v


def test_events_and_debug_history_written(full_run):
    result, _, _, _ = full_run
    from pathlib import Path

    run_dir = Path(result["run_dir"])
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    stages = {e["stage"] for e in events}
    assert {"promotion_gate", "planning", "build", "static_gate", "final_artifact"} <= stages
    assert (run_dir / "debug_history.jsonl").is_file()
    assert (run_dir / "snapshot").is_dir()  # green base 보존


def test_syntax_failure_routes_to_debug_desk(tmp_path):
    """문법 검사 실패 시 Debug Desk로 이동해 고친다 (§22-20)."""
    result, _, llm = _run(tmp_path, overrides={"build_output": mock_broken_build_output()})
    assert result["debug_rounds"] == 1
    assert all(result["gate_summary"].values()), result["gate_summary"]
    assert result["ok"], result["error"]
    workers = [e["worker"] for e in llm.logger.entries]
    assert "debug_output" in workers


def test_debug_desk_max_rounds_enforced(tmp_path):
    """Debug Desk 최대 횟수 제한 — 무한 루프 금지 (§22-21)."""
    broken = mock_broken_build_output()
    broken_patch = {
        "files": [f for f in broken["files"] if f["path"] == "src/app.js"],
        "debug_report": "여전히 깨진 patch (테스트용)",
    }
    result, _, _ = _run(
        tmp_path,
        overrides={"build_output": broken, "debug_output": broken_patch},
        fset=FactorySettings(use_docker="off", max_debug_rounds=2),
    )
    assert result["debug_rounds"] == 2
    assert not result["gate_summary"]["syntax"]
    assert result["verdict"] == "NEEDS_MORE_GEMMA_LOOP"


def test_qa_failure_downgrades_promote(tmp_path):
    """QA 미통과면 PROMOTE_TO_CODEX가 강등된다."""
    qa = mock_qa_output()
    qa["forbidden"][0]["violated"] = True
    result, _, _ = _run(tmp_path, overrides={"qa_output": qa})
    assert result["verdict"] == "NEEDS_MORE_GEMMA_LOOP"
    assert any("강등" in a for a in result["auto_adjustments"])


def test_promotion_gate_rejects_bad_challenge(tmp_path):
    challenge = sample_challenge()
    challenge["card"]["final_label"] = "TOO_EASY"
    result = run_product_factory(
        challenge, mode="mock", output_dir=tmp_path / "runs",
        settings=SETTINGS, factory_settings=FSET,
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert result["error"] and "승격 기준 미달" in result["error"]
    assert result["run_dir"] is None  # workspace를 만들지 않는다


def test_micro_line_for_steal_only(tmp_path):
    challenge = sample_challenge()
    challenge["card"]["final_label"] = "STEAL_ONLY"
    result = run_product_factory(
        challenge, mode="mock", output_dir=tmp_path / "runs",
        settings=SETTINGS, factory_settings=FSET,
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert result["line"] == "micro"
    # mock 결과물은 gate/QA 전부 통과 → 예외적으로 PROMOTE 허용 (§6.2 단서)
    assert result["verdict"] in ("PROMOTE_TO_CODEX", "KEEP_CANDIDATE")


def test_select_patch_candidate_priority():
    """patch 후보 선택 기준 (§22-32, §11.2 순서)."""
    a = PatchCandidate("a", applicable=True, syntax_ok=True, contract_ok=True, smoke_ok=True,
                       changed_files=3, anchor_score=2)
    b = PatchCandidate("b", applicable=True, syntax_ok=True, contract_ok=True, smoke_ok=True,
                       changed_files=1, anchor_score=1)
    c = PatchCandidate("c", applicable=True, syntax_ok=False, contract_ok=True, smoke_ok=True,
                       changed_files=1, anchor_score=5)
    d = PatchCandidate("d", applicable=False, syntax_ok=True, contract_ok=True, smoke_ok=True,
                       changed_files=1, anchor_score=5)
    # 적용 불가(d) 제외, 문법 실패(c) 후순위, 수정 범위 작은 b 우선
    assert select_patch_candidate([a, b, c, d]).candidate_id == "b"
    # 수정 범위 같으면 anchor 점수 높은 쪽
    e = PatchCandidate("e", applicable=True, syntax_ok=True, contract_ok=True, smoke_ok=True,
                       changed_files=1, anchor_score=4)
    assert select_patch_candidate([b, e]).candidate_id == "e"
    # forbidden 위반 적은 쪽
    f1 = PatchCandidate("f1", applicable=True, syntax_ok=True, contract_ok=True, smoke_ok=True,
                        changed_files=1, anchor_score=4, forbidden_violations=1)
    assert select_patch_candidate([f1, e]).candidate_id == "e"
    assert select_patch_candidate([d]) is None


def test_secret_scan_passes_with_fake_keys(tmp_path, fake_env):
    """산출물 어디에도 key 원문이 없어야 한다 (§22-37)."""
    from pathlib import Path

    keys = {i: fake_env[f"GOOGLE_API_KEY_{i}"] for i in range(1, 12)}
    settings = Settings(google_keys=keys, github_token=fake_env["GITHUB_TOKEN"])
    llm = MockLLMClient(overrides=mock_factory_overrides())
    result = run_product_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        settings=settings, factory_settings=FSET, llm=llm,
    )
    assert result["ok"], result["error"]
    blob = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in Path(result["run_dir"]).rglob("*") if p.is_file()
    )
    for secret in fake_env.values():
        assert secret not in blob
