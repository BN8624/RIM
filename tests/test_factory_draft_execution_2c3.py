# Phase 2C-3 테스트: draft editor 초안의 runner-backed 실행 (어댑터/브리지/실행 스모크/validate).
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.factory_draft_execution import (
    ADAPTER_SOURCE,
    REQUIRED_OUTPUTS,
    _EXEC_BLOCK,
    check_execution_preconditions,
    check_handler_binding,
    check_static_dom,
    compute_execution_protected_hashes,
    inject_execution_panel,
    run_draft_execution,
    run_execution_smoke,
)
from repo_idea_miner.factory_product_editor import _extract_scripts, run_product_editor
from repo_idea_miner.factory_product_polish import run_product_polish
from repo_idea_miner.factory_review import run_review_package
from repo_idea_miner.factory_validate import _check_phase2c3, detect_phase2c3_run

# 2C-0/2C-2 테스트의 합성 green run 빌더를 재사용한다
from test_factory_review_2c0 import _VIEWER_MISMATCH, _build_green_run, _dump  # noqa: E402

FIXTURE_47 = Path("runs/factory_20260709_072220")
_HAS_NODE = bool(shutil.which("node"))


def _load_adapter(tmp_path: Path):
    import importlib.util

    p = tmp_path / "adapter_under_test.py"
    p.write_text(ADAPTER_SOURCE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("adapter_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_2c2_decision(run: Path):
    (run / "user_review_decision.md").write_text(
        "# 검수 결과\n## 최종 결정\n- [x] Phase 2C-2 진행\n", encoding="utf-8")


def _write_2c3_decision(run: Path):
    p = run / "review" / "phase2d0"
    p.mkdir(parents=True, exist_ok=True)
    (p / "user_review_decision.md").write_text(
        "# 검수 결과\n## 최종 결정\n- [x] Phase 2C-3 진행\n", encoding="utf-8")


def _execution_ready_run(tmp_path) -> Path:
    """green run → 2C-0 → 2C-1 polish → 2C-2 editor(candidate) → 2C-3 사용자 승인."""
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    out = run_product_polish(run_dir=run, apply=True)
    assert out["recommended_fitness"] == "NEEDS_PRODUCT_POLISH"
    _write_2c2_decision(run)
    out = run_product_editor(run_dir=run, apply=True)
    assert out["ok"]
    _write_2c3_decision(run)
    return run


def _applied_run(tmp_path):
    run = _execution_ready_run(tmp_path)
    out = run_draft_execution(run_dir=run, apply=True)
    return run, out


# ---------------------------------------------------------------- Group A: 어댑터 단위

def test_adapter_diamond_ports_and_inputs(tmp_path):
    ad = _load_adapter(tmp_path)
    draft = {
        "nodes": [{"id": "in", "type": "INPUT", "label": "in"},
                  {"id": "l", "type": "MUL_2", "label": "l"},
                  {"id": "r", "type": "MUL_3", "label": "r"},
                  {"id": "s", "type": "SUM", "label": "s"}],
        "edges": [{"source_id": "in", "target_id": "l"},
                  {"source_id": "in", "target_id": "r"},
                  {"source_id": "l", "target_id": "s"},
                  {"source_id": "r", "target_id": "s"}],
    }
    out = ad.draft_to_scenario(draft, input_value=10)
    assert out["ok"], out["problems"]
    actions = out["scenario"]["actions"]
    assert [a["type"] for a in actions[:4]] == ["add_node"] * 4
    edge_actions = [a for a in actions if a["type"] == "add_edge"]
    sum_ports = sorted(a["payload"]["target_port"] for a in edge_actions
                       if a["payload"]["target_id"] == "s")
    assert sum_ports == [0, 1]  # 다입력 노드는 포트가 겹치면 안 됨
    execute = actions[-1]
    assert execute["type"] == "execute_graph"
    assert execute["payload"]["initial_inputs"] == {"in": [10]}


def test_adapter_rejects_from_to_edge(tmp_path):
    ad = _load_adapter(tmp_path)
    draft = {"nodes": [{"id": "a", "type": "INPUT"}, {"id": "b", "type": "OUTPUT"}],
             "edges": [{"from": "a", "to": "b"}]}
    out = ad.draft_to_scenario(draft)
    assert not out["ok"]
    assert any("from/to" in p for p in out["problems"])


def test_adapter_rejects_duplicate_id(tmp_path):
    ad = _load_adapter(tmp_path)
    out = ad.draft_to_scenario({"nodes": [{"id": "a", "type": "X"},
                                          {"id": "a", "type": "X"}], "edges": []})
    assert not out["ok"]
    assert any("duplicate" in p for p in out["problems"])


def test_adapter_rejects_empty_draft(tmp_path):
    ad = _load_adapter(tmp_path)
    out = ad.draft_to_scenario({"nodes": [], "edges": []})
    assert not out["ok"]


def test_adapter_rejects_dangling_edge(tmp_path):
    ad = _load_adapter(tmp_path)
    out = ad.draft_to_scenario({"nodes": [{"id": "a", "type": "X"}],
                                "edges": [{"source_id": "a", "target_id": "ghost"}]})
    assert not out["ok"]
    assert any("ghost" in p for p in out["problems"])


def test_adapter_rejects_self_loop(tmp_path):
    ad = _load_adapter(tmp_path)
    out = ad.draft_to_scenario({"nodes": [{"id": "a", "type": "X"}],
                                "edges": [{"source_id": "a", "target_id": "a"}]})
    assert not out["ok"]


def test_adapter_rejects_non_numeric_input(tmp_path):
    ad = _load_adapter(tmp_path)
    out = ad.draft_to_scenario({"nodes": [{"id": "a", "type": "X"}], "edges": []},
                               input_value="ten")
    assert not out["ok"]


def test_adapter_deterministic(tmp_path):
    ad = _load_adapter(tmp_path)
    draft = {"nodes": [{"id": "a", "type": "INPUT"}, {"id": "b", "type": "ADD_10"}],
             "edges": [{"source_id": "a", "target_id": "b"}]}
    s1 = ad.draft_to_scenario(draft, input_value=7)
    s2 = ad.draft_to_scenario(draft, input_value=7)
    assert s1 == s2


# ---------------------------------------------------------------- Group B: viewer 주입/정적 근거

_FAKE_VIEWER = ('<!DOCTYPE html><html><body><div id="main-container"></div>'
                '<!-- PHASE2C2_EDITOR_START --><div id="p2c2-editor"></div>'
                '<!-- PHASE2C2_EDITOR_END --></body></html>')


def test_exec_block_no_forbidden_literals():
    """주입 스크립트가 mismatch 감지 리터럴/비결정 API를 절대 쓰지 않는다."""
    for pat in (r"edge\.from", r"edge\.to", r"ev\.type", r"ev\.message",
                r"\.type\b", r"node\.x", r"node\.y", r"Math\.random", r"Date\.now"):
        assert not re.search(pat, _EXEC_BLOCK), f"금지 리터럴 발견: {pat}"


def test_inject_requires_editor_marker(tmp_path):
    v = tmp_path / "index.html"
    v.write_text("<html><body></body></html>", encoding="utf-8")
    assert inject_execution_panel(v) is False


def test_inject_after_editor_and_idempotent(tmp_path):
    v = tmp_path / "index.html"
    v.write_text(_FAKE_VIEWER, encoding="utf-8")
    assert inject_execution_panel(v) is True
    assert inject_execution_panel(v) is True  # 재주입 안전
    html = v.read_text(encoding="utf-8")
    assert html.count("PHASE2C3_EXEC_START") == 1
    assert html.index("PHASE2C2_EDITOR_END") < html.index("PHASE2C3_EXEC_START")


def test_static_dom_and_handler_pass(tmp_path):
    v = tmp_path / "index.html"
    v.write_text(_FAKE_VIEWER, encoding="utf-8")
    inject_execution_panel(v)
    html = v.read_text(encoding="utf-8")
    assert check_static_dom(html)["status"] == "PASS"
    assert check_handler_binding(html)["status"] == "PASS"


def test_static_dom_detects_missing():
    out = check_static_dom("<html></html>")
    assert out["status"] == "FAIL"
    assert "execute_button" in out["missing"]


@pytest.mark.skipif(not _HAS_NODE, reason="node 없음")
def test_exec_block_scripts_valid_js(tmp_path):
    v = tmp_path / "index.html"
    v.write_text(_FAKE_VIEWER, encoding="utf-8")
    inject_execution_panel(v)
    for i, sc in enumerate(_extract_scripts(v.read_text(encoding="utf-8"))):
        js = tmp_path / f"s{i}.js"
        js.write_text(sc, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- Group C: 사전 조건

def test_preconditions_block_without_editor(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    problems = check_execution_preconditions(
        run, {"verdict": "REVIEW_READY", "green_base": True})
    assert any("2C-2" in p for p in problems)


def test_dry_run_blocked_without_decision(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    run_product_polish(run_dir=run, apply=True)
    _write_2c2_decision(run)
    run_product_editor(run_dir=run, apply=True)
    out = run_draft_execution(run_dir=run)  # 2C-3 결정 없음
    assert out["status"] == "DRY_RUN_BLOCKED"
    assert any("2C-3" in p for p in out["problems"])


def test_dry_run_pass_and_no_modification(tmp_path):
    run = _execution_ready_run(tmp_path)
    before = compute_execution_protected_hashes(run)
    viewer = run / "final_artifact" / "product" / "viewer" / "index.html"
    vh = viewer.read_text(encoding="utf-8")
    out = run_draft_execution(run_dir=run)
    assert out["status"] == "DRY_RUN_PASS"
    assert compute_execution_protected_hashes(run) == before
    assert viewer.read_text(encoding="utf-8") == vh  # dry-run은 viewer 미변경
    assert not (run / "final_artifact" / "src" / "adapters").exists()


# ---------------------------------------------------------------- Group D: apply E2E (합성 run)

def test_apply_creates_outputs_and_scopes(tmp_path):
    run, out = _applied_run(tmp_path)
    assert out["applied"]
    rd = run / "review" / "phase2c3"
    for rel in REQUIRED_OUTPUTS:
        assert (rd / rel).is_file(), rel
    assert out["hash_status"] == "PASS"
    for f in out["patched_files"]:
        assert ("/product/" in f) or ("/src/adapters/" in f), f


def test_apply_execution_smoke_closes_loop(tmp_path):
    run, out = _applied_run(tmp_path)
    es = out["execution_smoke"]
    assert es["adapter_ok"], es["failures"]
    assert es["runner_execution_ok"], es["failures"]
    assert es["result_reflects_edit"], es["failures"]
    assert es["revise_cycle_changes_result"], es["failures"]
    assert es["bridge_server_ok"], es["failures"]
    assert es["viewer_served_ok"], es["failures"]
    assert es["original_replay_unchanged"]
    assert es["product_loop_closed"]
    assert es["execution_smoke_pass"]


def test_apply_original_replay_and_protected_unchanged(tmp_path):
    run = _execution_ready_run(tmp_path)
    replay = run / "final_artifact" / "replay" / "replay_scenario_001.json"
    golden = run / "final_artifact" / "golden" / "expected_001.json"
    r_before = replay.read_bytes()
    g_before = golden.read_bytes()
    run_draft_execution(run_dir=run, apply=True)
    assert replay.read_bytes() == r_before
    assert golden.read_bytes() == g_before


@pytest.mark.skipif(not _HAS_NODE, reason="node 없음 (JS 검사 UNKNOWN이면 candidate 하향)")
def test_apply_yields_product_candidate(tmp_path):
    run, out = _applied_run(tmp_path)
    fit = out["fitness"]
    assert out["recommended_fitness"] == "PRODUCT_CANDIDATE"
    assert fit["runner_backed_execution_included"] is True
    assert fit["product_loop_closed"] is True


def test_apply_does_not_touch_prior_review_dirs(tmp_path):
    run = _execution_ready_run(tmp_path)
    prior = {}
    for rev in ("phase2c0", "phase2c1", "phase2c2"):
        d = run / "review" / rev
        prior[rev] = {p.relative_to(d).as_posix(): p.read_bytes()
                      for p in d.rglob("*") if p.is_file()}
    run_draft_execution(run_dir=run, apply=True)
    for rev, files in prior.items():
        d = run / "review" / rev
        for rel, content in files.items():
            assert (d / rel).read_bytes() == content, f"{rev}/{rel} 변경됨"


def test_execution_smoke_standalone_after_apply(tmp_path):
    run, _out = _applied_run(tmp_path)
    es = run_execution_smoke(run)
    assert es["product_loop_closed"]


# ---------------------------------------------------------------- Group E: validate

def _write_min_exec(run: Path, *, recommended="PRODUCT_CANDIDATE", hash_status="PASS",
                    smoke_overrides=None, fitness_overrides=None, diff_overrides=None,
                    skip=()):
    rd = run / "review" / "phase2c3"
    smoke = {
        "adapter_ok": True, "runner_execution_ok": True, "result_reflects_edit": True,
        "revise_cycle_changes_result": True, "bridge_server_ok": True,
        "viewer_served_ok": True, "execution_smoke_pass": True,
        "product_loop_closed": True, "original_replay_unchanged": True,
        "can_execute_input": True, "can_see_result_from_created_input": True,
        "failures": [],
    }
    smoke.update(smoke_overrides or {})
    fitness = {
        "recommended_fitness": recommended,
        "runner_backed_execution_included": True,
        "product_loop_closed": True,
        "criteria": [],
    }
    fitness.update(fitness_overrides or {})
    diff = {"patched_files": ["final_artifact/product/viewer/index.html",
                              "final_artifact/src/adapters/draft_to_runner_input.py"],
            "out_of_scope_changes": []}
    diff.update(diff_overrides or {})
    files = {
        "phase2c3_execution_plan.json": {"status": "DRY_RUN_PASS"},
        "phase2c3_execution_report.json": {"recommended_fitness": recommended},
        "phase2c3_diff_summary.json": diff,
        "phase2c3_hash_check.json": {"status": hash_status, "changed": [], "added": [],
                                     "removed": []},
        "adapter_check.json": {"status": "PASS", "problems": []},
        "execution_smoke.json": smoke,
        "viewer_js_syntax_check.json": {"status": "PASS"},
        "viewer_static_dom_check.json": {"status": "PASS"},
        "viewer_handler_binding_check.json": {"status": "PASS"},
        "viewer_smoke_after_execution.json": {"mismatches": []},
        "product_fitness_report_after_execution.json": fitness,
        "phase2c3_dashboard_summary.json": {"phase": "2c3",
                                            "recommended_fitness": recommended},
    }
    for name, data in files.items():
        if name not in skip:
            _dump(rd / name, data)
    return run


def test_detect_marker(tmp_path):
    run = tmp_path / "run"
    assert not detect_phase2c3_run(run)
    _write_min_exec(run)
    assert detect_phase2c3_run(run)


def test_validate_no_marker_no_check(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    assert _check_phase2c3(run) == []


def test_validate_clean_passes(tmp_path):
    run = _write_min_exec(tmp_path / "run")
    assert _check_phase2c3(run) == []


def test_validate_hash_fail(tmp_path):
    run = _write_min_exec(tmp_path / "run", hash_status="FAIL")
    assert any("보호 대상" in p for p in _check_phase2c3(run))


def test_validate_out_of_scope_fail(tmp_path):
    run = _write_min_exec(tmp_path / "run", diff_overrides={
        "patched_files": ["final_artifact/src/core/engine.py"]})
    assert any("허용 범위 밖" in p for p in _check_phase2c3(run))


def test_validate_replay_changed_fails(tmp_path):
    run = _write_min_exec(tmp_path / "run",
                          smoke_overrides={"original_replay_unchanged": False})
    assert any("original_replay_unchanged" in p for p in _check_phase2c3(run))


def test_validate_candidate_without_bridge_fails(tmp_path):
    run = _write_min_exec(tmp_path / "run",
                          smoke_overrides={"bridge_server_ok": False,
                                           "can_see_result_from_created_input": False,
                                           "product_loop_closed": False,
                                           "execution_smoke_pass": False})
    problems = _check_phase2c3(run)
    assert any("bridge_server_ok" in p for p in problems)
    assert any("실행 실증 없음" in p for p in problems)


def test_validate_candidate_without_revise_fails(tmp_path):
    run = _write_min_exec(tmp_path / "run",
                          smoke_overrides={"revise_cycle_changes_result": False})
    assert any("revise_cycle_changes_result" in p for p in _check_phase2c3(run))


def test_validate_loop_closed_mismatch_fails(tmp_path):
    run = _write_min_exec(tmp_path / "run",
                          smoke_overrides={"product_loop_closed": False})
    assert any("미완결" in p for p in _check_phase2c3(run))


def test_validate_missing_required_fails(tmp_path):
    run = _write_min_exec(tmp_path / "run", skip=("execution_smoke.json",))
    assert any("execution_smoke.json" in p for p in _check_phase2c3(run))


def test_validate_non_candidate_tolerates_partial(tmp_path):
    """NEEDS_PRODUCT_POLISH면 실행 미완결이어도 산출물 정합성만 본다 (정직한 실패 허용)."""
    run = _write_min_exec(
        tmp_path / "run", recommended="NEEDS_PRODUCT_POLISH",
        smoke_overrides={"bridge_server_ok": False, "product_loop_closed": False,
                         "execution_smoke_pass": False,
                         "can_see_result_from_created_input": False},
        fitness_overrides={"runner_backed_execution_included": False,
                           "product_loop_closed": False})
    assert _check_phase2c3(run) == []


# ---------------------------------------------------------------- Group F: 합성 run validate 통합

def test_applied_run_validate_clean(tmp_path):
    run, _out = _applied_run(tmp_path)
    problems = _check_phase2c3(run)
    assert problems == [] or all("PRODUCT_CANDIDATE" not in p for p in problems)


# ---------------------------------------------------------------- Group G: CLI

def test_cli_dry_run_and_apply(tmp_path, monkeypatch):
    run = _execution_ready_run(tmp_path)
    monkeypatch.chdir(tmp_path)
    rel = str(run)
    assert main(["factory-draft-execution", "--run-dir", rel, "--dry-run"]) == 0
    assert main(["factory-draft-execution", "--run-dir", rel, "--apply"]) == 0


def test_cli_rejects_both_flags(tmp_path):
    assert main(["factory-draft-execution", "--run-dir", str(tmp_path),
                 "--dry-run", "--apply"]) == 1


# ---------------------------------------------------------------- Group H: 실제 #47 E2E

@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_draft_execution(tmp_path):
    """실제 #47 산출물 tmp 복사본에 2C-3 apply — 원본 무변경."""
    run = tmp_path / "run47"
    shutil.copytree(FIXTURE_47, run,
                    ignore=shutil.ignore_patterns("__pycache__", "js_check", "snapshot"))
    _write_2c3_decision(run)
    out = run_draft_execution(run_dir=run, apply=True)
    assert out["applied"], out.get("error")
    assert out["hash_status"] == "PASS"
    es = out["execution_smoke"]
    assert es["adapter_ok"], es["failures"]
    assert es["runner_execution_ok"], es["failures"]
    assert es["result_reflects_edit"], es["failures"]
    assert es["revise_cycle_changes_result"], es["failures"]
    assert es["product_loop_closed"], es["failures"]
    if _HAS_NODE:
        assert out["recommended_fitness"] == "PRODUCT_CANDIDATE"
        assert out["fitness"]["runner_backed_execution_included"] is True
    assert _check_phase2c3(run) == []
