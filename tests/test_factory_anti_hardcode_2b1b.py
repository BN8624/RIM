# Phase 2B-1b 테스트: anti_hardcode summary 하드코딩 탐지/제거 + expected_summary 규칙 강화 + gate 재검증 (주문서 §17).
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_anti_hardcode import (
    _rewrite_runner,
    build_patch_plan,
    check_patch_preconditions,
    detect_hardcoded_summary,
    run_anti_hardcode_patch,
)
from repo_idea_miner.factory_core_gates import classify_summary_source
from repo_idea_miner.factory_frozen import compute_frozen_hashes
from repo_idea_miner.factory_pipeline import FactorySettings
from repo_idea_miner.factory_spec_repair import plan_scenario_repair
from repo_idea_miner.factory_validate import _check_anti_hardcode_patch, validate_product_run_dir

FSET = FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0)
SETTINGS = Settings(google_keys={})

# 실제 #47 Phase 2B-1 산출물 — E2E green 경로 검증용 (gitignore된 runtime 산출물이라 없으면 skip)
FIXTURE_47 = Path("runs/factory_20260709_072220")

_HARDCODED_RUNNER = '''import json
import sys
from core.engine import WorkflowEngine

def run(scenario):
    engine = WorkflowEngine()
    errors = []
    try:
        for action in scenario.get("actions", []):
            engine.apply(action)
    except Exception as e:
        print(json.dumps({"ok": False, "errors": [f"error: {str(e)}"]}, ensure_ascii=True))
        sys.exit(1)
    result = {
        "ok": len(errors) == 0,
        "final_state": engine.state.to_dict(),
        "events": engine.events,
        "summary": "Completed" if len(errors) == 0 else "Failed",
        "errors": errors
    }
    return result
'''

_STATE_DERIVED_RUNNER = '''from core.summary import summarize_execution

def run(final_state, errors):
    return {"summary": summarize_execution(final_state, errors)}
'''

_SUMMARY_HELPER = '''def summarize_execution(final_state, errors):
    nodes = (final_state or {}).get("nodes") or {}
    completed = sum(1 for n in nodes.values() if n.get("status") == "COMPLETED")
    if errors:
        return "Failed"
    if nodes and completed == len(nodes):
        return "Completed"
    return "Partially completed"
'''


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _mini_ws(tmp_path: Path, runner_src: str, extra: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "src" / "core").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "runner.py").write_text(runner_src, encoding="utf-8")
    for rel, content in (extra or {}).items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (ws / "golden").mkdir(exist_ok=True)
    _dump(ws / "golden" / "expected_001.json",
          {"scenario_id": "scenario_001", "comparison_mode": "exact", "expected_summary": "Completed"})
    return ws


# ---------------------------------------------------------------- §17-12~16,26~33: classify_summary_source

def test_classify_hardcoded_inline():
    """summary 대입에 golden 리터럴이 직접 결합되면 hardcoded high."""
    code = {"src/runner.py": '    result = {"summary": "Completed" if not errors else "Failed"}\n'}
    out = classify_summary_source(code, [{"expected_summary": "Completed"}])
    assert out["summary_source"] == "hardcoded"
    assert out["summary_hardcode_risk"] == "high"
    assert out["problems"]


def test_classify_state_derived_helper_passes():
    """리터럴이 final_state/status를 읽는 formatter 안의 결과 상수면 state_derived low."""
    code = {"src/runner.py": _STATE_DERIVED_RUNNER, "src/core/summary.py": _SUMMARY_HELPER}
    out = classify_summary_source(code, [{"expected_summary": "Completed"}])
    assert out["summary_source"] == "state_derived"
    assert out["summary_hardcode_risk"] == "low"
    assert not out["problems"]


def test_classify_event_derived():
    """events만 읽는 formatter는 event_derived."""
    code = {"src/x.py": 'def f(events):\n    if events:\n        return "Completed"\n    return "None"\n'}
    out = classify_summary_source(code, [{"expected_summary": "Completed"}])
    assert out["summary_source"] == "event_derived"
    assert not out["problems"]


def test_classify_module_constant_is_hardcoded():
    """모듈 상수로 golden 리터럴을 박으면(파생 근거 없음) hardcoded high."""
    code = {"src/canned.py": 'CANNED = "Completed run"\n'}
    out = classify_summary_source(code, [{"expected_summary": "Completed run"}])
    assert out["summary_source"] == "hardcoded"
    assert out["summary_hardcode_risk"] == "high"


def test_classify_absent_literal_is_na():
    """리터럴이 코드에 없으면(포맷 파생 등) n/a low."""
    code = {"src/runner.py": 'summary = "%d done" % n\n'}
    out = classify_summary_source(code, [{"expected_summary": "5 done ok extra"}])
    assert out["summary_source"] == "n/a"
    assert not out["problems"]


# ---------------------------------------------------------------- §4: detect / rewrite

def test_detect_hardcoded_summary(tmp_path):
    ws = _mini_ws(tmp_path, _HARDCODED_RUNNER)
    d = detect_hardcoded_summary(ws)
    assert d["summary_hardcode_risk"] == "high"
    assert d["runner_rel"] == "src/runner.py"
    assert d["final_state_expr"] == "engine.state.to_dict()"
    # §regression: errors 표현식을 예외 핸들러 print(...) 안에서 잘못 뽑지 않는다
    assert d["errors_expr"] == "errors"


def test_rewrite_runner_produces_valid_python(tmp_path):
    ws = _mini_ws(tmp_path, _HARDCODED_RUNNER)
    d = detect_hardcoded_summary(ws)
    text = (ws / "src" / "runner.py").read_text(encoding="utf-8")
    rewritten = _rewrite_runner(text, d)
    compile(rewritten, "runner.py", "exec")  # 문법 오류 없어야 함
    assert "summarize_execution(engine.state.to_dict(), errors)" in rewritten
    assert "from core.summary import summarize_execution" in rewritten
    assert '"Completed" if' not in rewritten  # 하드코딩 대입 제거됨


# ---------------------------------------------------------------- §7: expected_summary 규칙 강화

def _behind_golden():
    return {"scenario_id": "scenario_001", "comparison_mode": "exact",
            "expected_final_state": {"nodes": {}}, "expected_events": [],
            "expected_summary": "OLD"}


def _replay():
    return {"final_state": {"nodes": {}}, "events": [], "summary": "Completed", "errors": []}


def test_summary_repair_blocked_when_hardcoded():
    """§7.2: runner summary가 하드코딩이면 expected_summary 보정을 차단한다."""
    entry = plan_scenario_repair(_behind_golden(), _replay(), set(), summary_hardcoded=True)
    assert entry["new_golden"] is None
    assert any("SUMMARY_REPAIR_BLOCKED_HARDCODE_RISK" in b for b in entry["blocked_reasons"])


def test_summary_repair_allowed_when_derived():
    """§7.1: runner summary가 state 파생이면 expected_summary 보정을 허용한다."""
    entry = plan_scenario_repair(_behind_golden(), _replay(), set(), summary_hardcoded=False)
    assert entry["new_golden"] is not None
    assert entry["new_golden"]["expected_summary"] == "Completed"


# ---------------------------------------------------------------- §10: patch plan

def test_patch_plan_pass(tmp_path):
    ws = _mini_ws(tmp_path, _HARDCODED_RUNNER)
    d = detect_hardcoded_summary(ws)
    plan = build_patch_plan(tmp_path, d, {"base_run_id": 5, "challenge_id": 47}, {"verdict": "NEEDS_MORE_GEMMA_LOOP"})
    assert plan["status"] == "DRY_RUN_PASS"
    assert "src/runner.py" in plan["planned_files"]
    assert "Completed" in plan["hardcoded_literals"]


def test_patch_plan_blocked_when_not_hardcoded(tmp_path):
    ws = _mini_ws(tmp_path, _STATE_DERIVED_RUNNER, extra={"src/core/summary.py": _SUMMARY_HELPER})
    d = detect_hardcoded_summary(ws)
    plan = build_patch_plan(tmp_path, d, {}, {})
    assert plan["status"] == "DRY_RUN_BLOCKED"
    assert plan["blocked_reasons"]


# ---------------------------------------------------------------- §3: preconditions

def _pre_env(run_dir: Path, remaining=("anti_hardcode",), promoted=False, verdict="NEEDS_MORE_GEMMA_LOOP"):
    run_dir.mkdir(parents=True, exist_ok=True)
    _dump(run_dir / "spec_repair_apply_report.json", {"applied": True, "base_run_id": 5, "challenge_id": 47})
    _dump(run_dir / "gate_rerun_after_spec_repair.json", {"gates": {}})
    _dump(run_dir / "green_base_promotion_after_spec_repair.json",
          {"remaining_failures": list(remaining), "promoted_to_green_base": promoted, "new_verdict": verdict})


def test_precondition_ok(tmp_path):
    _pre_env(tmp_path / "run")
    problems, _ = check_patch_preconditions(tmp_path / "run", [])
    assert problems == []


def test_precondition_missing_apply(tmp_path):
    (tmp_path / "run").mkdir()
    problems, _ = check_patch_preconditions(tmp_path / "run", [])
    assert any("spec repair apply" in p for p in problems)


def test_precondition_no_anti_hardcode_remaining(tmp_path):
    _pre_env(tmp_path / "run", remaining=("golden_output",))
    problems, _ = check_patch_preconditions(tmp_path / "run", [])
    assert any("anti_hardcode 없음" in p for p in problems)


def test_precondition_already_promoted(tmp_path):
    _pre_env(tmp_path / "run", promoted=True, verdict="REVIEW_READY")
    problems, _ = check_patch_preconditions(tmp_path / "run", [])
    assert any("이미 green_base" in p for p in problems)


def test_precondition_already_patched(tmp_path):
    _pre_env(tmp_path / "run")
    _dump(tmp_path / "run" / "anti_hardcode_patch_report.json", {"applied": True})
    problems, _ = check_patch_preconditions(tmp_path / "run", [])
    assert any("이미 anti_hardcode patch" in p for p in problems)


# ---------------------------------------------------------------- §16: validate 규칙

def _patched_run(run_dir: Path, gates=None, verdict="REVIEW_READY", summary_risk="low",
                 frozen="PASS", promoted=True):
    run_dir.mkdir(parents=True, exist_ok=True)
    gates = gates or {g: True for g in
                      ("core_contract", "runner", "scenario_replay", "golden_output",
                       "state_invariant", "determinism", "anti_hardcode")}
    for rel in ("anti_hardcode_patch_plan.json", "anti_hardcode_diff_summary.json"):
        _dump(run_dir / rel, {})
    _dump(run_dir / "anti_hardcode_patch_report.json", {
        "applied": True, "target_count": 1, "summary_source": "state_derived",
        "summary_hardcode_risk": summary_risk, "gates": gates, "new_verdict": verdict})
    _dump(run_dir / "frozen_hash_anti_hardcode_check.json", {"status": frozen})
    _dump(run_dir / "gate_rerun_after_anti_hardcode_patch.json", {"gates": gates})
    _dump(run_dir / "green_base_promotion_after_anti_hardcode_patch.json",
          {"new_verdict": verdict, "promoted_to_green_base": promoted,
           "summary_hardcode_risk": summary_risk, "validate_ok": True})


def test_validate_clean_green(tmp_path):
    _patched_run(tmp_path / "run")
    assert _check_anti_hardcode_patch(tmp_path / "run") == []


def test_validate_no_patch_no_check(tmp_path):
    (tmp_path / "run").mkdir()
    assert _check_anti_hardcode_patch(tmp_path / "run") == []


def test_validate_gate_fail_but_review_ready(tmp_path):
    gates = {"anti_hardcode": True, "runner": True, "core_contract": True, "scenario_replay": True,
             "state_invariant": True, "determinism": True, "golden_output": False}
    _patched_run(tmp_path / "run", gates=gates, promoted=False)
    problems = _check_anti_hardcode_patch(tmp_path / "run")
    assert any("gate 실패" in p for p in problems)


def test_validate_summary_risk_high_but_review_ready(tmp_path):
    _patched_run(tmp_path / "run", summary_risk="high")
    problems = _check_anti_hardcode_patch(tmp_path / "run")
    assert any("summary_hardcode_risk high" in p for p in problems)


def test_validate_frozen_changed_but_review_ready(tmp_path):
    _patched_run(tmp_path / "run", frozen="FAIL")
    problems = _check_anti_hardcode_patch(tmp_path / "run")
    assert any("frozen" in p for p in problems)


def test_validate_missing_required_artifact(tmp_path):
    _patched_run(tmp_path / "run")
    (tmp_path / "run" / "anti_hardcode_diff_summary.json").unlink()
    problems = _check_anti_hardcode_patch(tmp_path / "run")
    assert any("필수 산출물 없음" in p for p in problems)


# ---------------------------------------------------------------- frozen guard: _variants 제외

def test_frozen_excludes_variants(tmp_path):
    ws = tmp_path / "ws"
    (ws / "fixtures" / "_variants").mkdir(parents=True)
    (ws / "fixtures" / "scenario_001.json").write_text("{}", encoding="utf-8")
    (ws / "fixtures" / "_variants" / "scenario_001_variant.json").write_text("{}", encoding="utf-8")
    h = compute_frozen_hashes(ws, None)
    assert any("scenario_001.json" in k and "_variants" not in k for k in h)
    assert not any("_variants" in k for k in h)


# ---------------------------------------------------------------- §9: CLI 정책

def test_cli_requires_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["factory-anti-hardcode-patch"]) == 1  # 대상 없음
    assert main(["factory-anti-hardcode-patch", "--run-dir", "x", "--dry-run", "--apply"]) == 1


def test_cli_no_all_option(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(["factory-anti-hardcode-patch", "--all"])


# ---------------------------------------------------------------- §17-34,35: 실제 #47 E2E green 경로

def _reset_to_pre_patch(run_dir: Path):
    """복사한 #47을 patch 이전(하드코딩 summary) 상태로 되돌린다."""
    hardcoded = '''import json
import argparse
import sys
from core.engine import WorkflowEngine

def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args()
    try:
        with open(args.scenario, 'r', encoding='utf-8') as f:
            scenario = json.load(f)
    except Exception as e:
        print(json.dumps({"ok": False, "errors": [f"File load error: {str(e)}"]}, ensure_ascii=True))
        sys.exit(1)
    engine = WorkflowEngine()
    errors = []
    for action in scenario.get("actions", []):
        try:
            atype = action["type"]
            payload = action["payload"]
            if atype == "add_node":
                engine.add_node(**payload)
            elif atype == "add_edge":
                engine.add_edge(**payload)
            elif atype == "execute_graph":
                engine.execute_graph(**payload)
        except Exception as e:
            errors.append(str(e))
            break
    result = {
        "ok": len(errors) == 0,
        "final_state": engine.state.to_dict(),
        "events": engine.events,
        "summary": "Completed" if len(errors) == 0 else "Failed",
        "errors": errors
    }
    print(json.dumps(result, ensure_ascii=True))

if __name__ == "__main__":
    run()
'''
    for base in (run_dir / "workspace", run_dir / "final_artifact"):
        (base / "src" / "runner.py").write_text(hardcoded, encoding="utf-8")
        sm = base / "src" / "core" / "summary.py"
        if sm.is_file():
            sm.unlink()
        v = base / "fixtures" / "_variants"
        if v.is_dir():
            shutil.rmtree(v)
    for name in ("anti_hardcode_patch_report.json", "anti_hardcode_patch_plan.json",
                 "green_base_promotion_after_anti_hardcode_patch.json",
                 "gate_rerun_after_anti_hardcode_patch.json", "green_base.json"):
        p = run_dir / name
        if p.is_file():
            p.unlink()


@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_dry_run_no_modification(tmp_path):
    run = tmp_path / FIXTURE_47.name  # resolved_run_dir 정합 위해 원본 dir 이름 유지
    shutil.copytree(FIXTURE_47, run)
    _reset_to_pre_patch(run)
    before = compute_frozen_hashes(run / "workspace", run)
    out = run_anti_hardcode_patch(run_dir=run, apply=False, settings=SETTINGS, factory_settings=FSET)
    assert out["ok"] and out["status"] == "DRY_RUN_PASS"
    assert out["summary_source"] == "hardcoded"
    assert compute_frozen_hashes(run / "workspace", run) == before  # 파일 미수정
    assert not (run / "anti_hardcode_patch_report.json").is_file()


@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_apply_promotes_to_green(tmp_path):
    run = tmp_path / FIXTURE_47.name  # resolved_run_dir 정합 위해 원본 dir 이름 유지
    shutil.copytree(FIXTURE_47, run)
    _reset_to_pre_patch(run)
    out = run_anti_hardcode_patch(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out["status"] == "PATCHED", out.get("error")
    # 모든 gate PASS + summary state 파생 + frozen 불변 → green 승격
    assert all(out["gates"].values()), out["gates"]
    assert out["summary_source"] == "state_derived"
    assert out["frozen_hash_status"] == "PASS"
    assert out["validate_ok"] is True
    assert out["promoted_to_green_base"] is True
    assert out["new_verdict"] == "REVIEW_READY"
    # patch된 runner는 golden literal을 summary 대입에 직접 박지 않는다
    runner = (run / "workspace" / "src" / "runner.py").read_text(encoding="utf-8")
    assert '"summary": "Completed"' not in runner
    assert "summarize_execution(" in runner
    # 독립 factory-validate도 PASS
    ok, problems = validate_product_run_dir(run, [])
    assert ok, problems


@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_reapply_blocked(tmp_path):
    run = tmp_path / FIXTURE_47.name  # resolved_run_dir 정합 위해 원본 dir 이름 유지
    shutil.copytree(FIXTURE_47, run)
    _reset_to_pre_patch(run)
    run_anti_hardcode_patch(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    out2 = run_anti_hardcode_patch(run_dir=run, apply=True, settings=SETTINGS, factory_settings=FSET)
    assert out2["status"] == "CANNOT_PATCH_ANTI_HARDCODE"
    assert any("이미" in p for p in out2["problems"])
