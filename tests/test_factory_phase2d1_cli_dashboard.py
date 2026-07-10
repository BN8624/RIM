# Phase 2D-1 §12~§13 테스트: CLI --execute 확장과 대시보드 closed loop 카드/패널, validate marker.
import json
from pathlib import Path

from repo_idea_miner.challenge_dashboard import (
    _load_phase2d1,
    _phase2d1_card_lines,
    _phase2d1_panel,
)
from repo_idea_miner.cli import main
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_loop_executor import run_closed_product_loop
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.factory_validate import _check_phase2d1, validate_product_run_dir
from repo_idea_miner.llm_client import LLMCallLogger, MockLLMClient

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})


def _run_mock(tmp_path):
    llm = MockLLMClient(overrides=mock_core_factory_overrides(),
                        call_logger=LLMCallLogger(None))
    return run_core_factory(sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
                            settings=SETTINGS, factory_settings=FSET, llm=llm)


def _run_loop(tmp_path, base, execute=True, max_iterations=2):
    return run_closed_product_loop(run_dir=base, mode="mock", execute=execute,
                                   max_iterations=max_iterations,
                                   output_dir=tmp_path / "children",
                                   settings=SETTINGS, factory_settings=FSET)


# ---------------------------------------------------------------- CLI (§13)

def test_cli_default_is_judge_only_2d0(tmp_path, capsys):
    res = _run_mock(tmp_path)
    rc = main(["factory-product-loop", "--run-dir", res["run_dir"],
               "--db", str(tmp_path / "no.db")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PRODUCT LOOP (mock" in out
    assert "CLOSED PRODUCT LOOP" not in out


def test_cli_execute_runs_closed_loop(tmp_path, capsys):
    res = _run_mock(tmp_path)
    rc = main(["factory-product-loop", "--run-dir", res["run_dir"], "--execute",
               "--max-iterations", "2", "--output-dir", str(tmp_path / "children"),
               "--db", str(tmp_path / "no.db")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "CLOSED PRODUCT LOOP" in out
    assert "base hash: PASS" in out
    assert "iter1:" in out


def test_cli_has_no_apply_original_option():
    """§13: 원본 직접 수정 옵션은 존재하지 않아야 한다."""
    import argparse

    try:
        main(["factory-product-loop", "--apply-original", "--run-dir", "x"])
        rc = 0
    except SystemExit as exc:  # argparse는 알 수 없는 옵션에 SystemExit(2)
        rc = exc.code
    assert rc == 2


# ---------------------------------------------------------------- Dashboard (§12)

def test_dashboard_card_and_panel_render(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    _run_loop(tmp_path, base)
    p2d1 = _load_phase2d1(base)
    assert p2d1 is not None
    card = _phase2d1_card_lines(p2d1)
    assert "closed loop" in card
    assert "stage" in card
    panel = _phase2d1_panel(p2d1, base)
    assert "Phase 2D-1 Closed Productization Loop" in panel
    assert "Iterations" in panel
    assert "Lineage" in panel
    # §12: 기술 로그 전체를 카드에 노출하지 않는다 — 카드는 3줄 meta 요약
    assert card.count("<p") <= 3


def test_dashboard_latest_loop_wins(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    first = _run_loop(tmp_path, base, execute=False)
    second = _run_loop(tmp_path, base, execute=False)
    p2d1 = _load_phase2d1(base)
    assert p2d1["loop_id"] == json.loads(
        (Path(second["loop_dir"]) / "loop_summary.json").read_text("utf-8"))["loop_id"]
    assert first["loop_id"] != second["loop_id"]


def test_dashboard_no_loop_is_silent(tmp_path):
    assert _load_phase2d1(tmp_path) is None
    assert _phase2d1_card_lines(None) == ""
    assert _phase2d1_panel(None, tmp_path) == ""


# ---------------------------------------------------------------- validate marker (§14)

def test_validate_phase2d1_noop_without_marker(tmp_path):
    res = _run_mock(tmp_path)
    assert _check_phase2d1(Path(res["run_dir"])) == []


def test_validate_phase2d1_passes_after_loop(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    _run_loop(tmp_path, base)
    problems = _check_phase2d1(base)
    assert problems == [], problems
    ok, all_problems = validate_product_run_dir(base, [])
    assert not [p for p in all_problems if "Phase 2D-1" in p]


def test_validate_phase2d1_flags_base_hash_violation(tmp_path):
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    out = _run_loop(tmp_path, base)
    hash_path = Path(out["loop_dir"]) / "base_hash_check.json"
    data = json.loads(hash_path.read_text("utf-8"))
    data["status"] = "FAIL"
    hash_path.write_text(json.dumps(data), encoding="utf-8")
    problems = _check_phase2d1(base)
    assert any("보호 대상 변경" in p for p in problems)


def test_validate_phase2d1_flags_unsupported_product_candidate(tmp_path):
    """§15-12 보강: acceptance 근거 없는 PRODUCT_CANDIDATE 주장을 validate가 잡는다."""
    res = _run_mock(tmp_path)
    base = Path(res["run_dir"])
    out = _run_loop(tmp_path, base)
    summary_path = Path(out["loop_dir"]) / "loop_summary.json"
    data = json.loads(summary_path.read_text("utf-8"))
    data["status"] = "PRODUCT_CANDIDATE"
    summary_path.write_text(json.dumps(data), encoding="utf-8")
    problems = _check_phase2d1(base)
    assert any("acceptance PASS 근거 없음" in p for p in problems)
