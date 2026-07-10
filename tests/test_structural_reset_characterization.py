# R0 characterization — 리팩토링 전후 보존해야 할 현재 의미를 고정한다 (Structural Reset §10.4).
# hard rung override/anti-hardcode/representation lint 같은 코드 수준 불변은 기존 단위 테스트가
# 이미 고정하고 있으므로 여기서는 run 의미·CLI·문서 계약 등 계약 표면만 고정한다.
import json
import subprocess
from pathlib import Path

import pytest

from repo_idea_miner.architecture_scanner import extract_cli_commands

REPO_ROOT = Path(__file__).resolve().parents[1]
LOOP_47 = REPO_ROOT / "runs/factory_20260709_072220/review/phase2d1/loop_20260710_134033"
LOOP_54 = REPO_ROOT / "runs/factory_20260710_021635/review/phase2d1/loop_20260710_141947"

EXPECTED_CLI = {
    "run", "search", "view", "serve", "validate",
    "challenge", "challenge-search", "daemon", "dashboard", "status", "pause",
    "resume", "validate-db",
    "factory", "factory-build", "factory-status", "factory-validate",
    "factory-continue", "factory-continue-queue", "factory-spec-repair-apply",
    "factory-anti-hardcode-patch", "factory-review", "factory-product-polish",
    "factory-product-editor", "factory-draft-execution", "factory-product-loop",
}

ROOT_MD_WHITELIST = {"AI_INDEX.md", "PROJECT_CANON.md", "README.md",
                     "REENTRY.md", "checklist.md"}


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_cli_commands_preserved():
    """§15.1의 기존 command 집합이 전부 존재해야 한다 (없어지면 회귀)."""
    cmds = set(extract_cli_commands(REPO_ROOT))
    missing = EXPECTED_CLI - cmds
    assert not missing, f"사라진 CLI: {sorted(missing)}"


def test_root_markdown_whitelist_tracked():
    try:
        out = subprocess.run(["git", "ls-files", "*.md"], cwd=REPO_ROOT,
                             capture_output=True, text=True, timeout=30)
    except OSError:
        pytest.skip("git 없음")
    tracked_root = {Path(line).name for line in out.stdout.splitlines()
                    if "/" not in line.replace("\\", "/")}
    assert tracked_root == ROOT_MD_WHITELIST


def test_dashboard_main_routes_exist():
    src = (REPO_ROOT / "repo_idea_miner/challenge_dashboard.py").read_text(encoding="utf-8")
    for route in ("/products", "/product/", "/challenge/"):
        assert route in src, f"dashboard route 소실: {route}"


@pytest.mark.skipif(not LOOP_47.is_dir(), reason="#47 closed loop run 없음 (로컬 전용)")
def test_47_closed_loop_meaning_preserved():
    s = _load(LOOP_47 / "loop_summary.json")
    assert s["status"] == "AUTOPILOT_HOLD_FOR_HUMAN"
    assert s["final_stage"] == "INTERACTION_CANDIDATE"
    assert s["stop_conditions"] == ["human_decision_required"]
    it1 = s["iterations"][0]
    assert it1["primary_gap_before"] == "RUNNER_BACKED_EXECUTION_REQUIRED"
    assert it1["selected_lane"] == "RUNNER_BACKED_DRAFT_EXECUTION"
    assert s["active_candidate_run_dir"] == "runs/factory_20260709_072220"
    assert _load(LOOP_47 / "base_hash_check.json")["status"] == "PASS"


@pytest.mark.skipif(not LOOP_54.is_dir(), reason="#54 closed loop run 없음 (로컬 전용)")
def test_54_closed_loop_meaning_preserved():
    s = _load(LOOP_54 / "loop_summary.json")
    assert s["status"] == "AUTOPILOT_HOLD_FOR_HUMAN"
    assert s["final_stage"] == "REVIEWABLE_ARTIFACT"
    it1 = s["iterations"][0]
    assert it1["primary_gap_before"] == "CORE_PATCH_REQUIRED"
    assert it1["selected_lane"] == "CORE_PATCH"
    assert it1["lane_status"] == "FAILED"
    # 실패한 child는 승격되지 않는다 — active candidate는 base run 그대로
    assert s["active_candidate_run_dir"] == "runs/factory_20260710_021635"
    assert any("high risk lane" in c for c in s["stop_conditions"])
    assert _load(LOOP_54 / "base_hash_check.json")["status"] == "PASS"
    # hard rung override 기록 보존 (관측이 서술을 이긴다)
    js = _load(LOOP_54 / "iterations/iter01/before/judge_snapshot.json")
    assert js["gap_override"]["live_gap"] == "INTERACTION_UI_REQUIRED"
    assert js["gap_override"]["enforced_gap"] == "CORE_PATCH_REQUIRED"


@pytest.mark.skipif(not LOOP_54.is_dir(), reason="#54 closed loop run 없음 (로컬 전용)")
def test_54_hold_packet_single_question():
    p = _load(LOOP_54 / "hold_for_human_packet.json")
    assert p["blocking_gaps"] == ["CORE_PATCH_REQUIRED"]
    assert p["single_question_for_human"]
    assert p["recommended_options"]
