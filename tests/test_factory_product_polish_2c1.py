# Phase 2C-1 테스트: #47 product viewer field mapping polish (replay schema 매핑/deterministic layout, 주문서 §14).
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.cli import main
from repo_idea_miner.factory_product_polish import (
    _POLISHED_SCRIPT,
    analyze_polish,
    compute_polish_protected_hashes,
    patch_viewer,
    run_product_polish,
)
from repo_idea_miner.factory_review import run_review_package
from repo_idea_miner.factory_validate import (
    _check_phase2c1,
    detect_phase2c1_run,
    validate_product_run_dir,
)

# 2C-0 테스트의 합성 green run 빌더/뷰어/replay를 재사용한다
from test_factory_review_2c0 import (  # noqa: E402
    _REPLAY_001,
    _VIEWER_CLEAN,
    _VIEWER_MISMATCH,
    _build_green_run,
    _dump,
)

FIXTURE_47 = Path("runs/factory_20260709_072220")


def _polished_run(tmp_path, viewer=_VIEWER_MISMATCH, apply=True):
    """합성 green run → 2C-0 review(NEEDS_PRODUCT_POLISH) → 2C-1 polish."""
    run = _build_green_run(tmp_path, viewer)
    run_review_package(run_dir=run)  # phase2c0 fitness 생성 (precondition)
    out = run_product_polish(run_dir=run, apply=apply)
    return run, out


# ---------------------------------------------------------------- Group A: patch / analyze 단위

def test_polished_viewer_has_no_raw_access_literals():
    """폴리시된 스크립트는 edge.from/ev.type/node.x 같은 raw-access 리터럴을 쓰지 않는다."""
    assert "edge.from" not in _POLISHED_SCRIPT
    assert "edge.to" not in _POLISHED_SCRIPT
    assert "ev.type" not in _POLISHED_SCRIPT
    assert "ev.message" not in _POLISHED_SCRIPT
    assert "node.x" not in _POLISHED_SCRIPT
    assert "node.y" not in _POLISHED_SCRIPT
    # 실제 schema를 읽는다
    assert "source_id" in _POLISHED_SCRIPT and "target_id" in _POLISHED_SCRIPT
    assert "node_id" in _POLISHED_SCRIPT
    assert "normalizeReplayForViewer" in _POLISHED_SCRIPT
    assert "computeLayout" in _POLISHED_SCRIPT
    # deterministic: random/시간 기반 금지
    assert "Math.random" not in _POLISHED_SCRIPT
    assert "Date.now" not in _POLISHED_SCRIPT
    assert "new Date" not in _POLISHED_SCRIPT


def test_patch_viewer_replaces_script(tmp_path):
    v = tmp_path / "index.html"
    v.write_text(_VIEWER_MISMATCH, encoding="utf-8")
    assert patch_viewer(v) is True
    src = v.read_text(encoding="utf-8")
    assert "normalizeReplayForViewer" in src
    assert "edge.from" not in src and "ev.type" not in src and "node.x" not in src


def test_analyze_polish_all_fixed(tmp_path):
    v = tmp_path / "index.html"
    v.write_text(_VIEWER_MISMATCH, encoding="utf-8")
    patch_viewer(v)
    out = analyze_polish(v.read_text(encoding="utf-8"), _REPLAY_001)
    assert out["edge_mapping_fixed"] is True
    assert out["event_mapping_fixed"] is True
    assert out["node_layout_generated"] is True
    assert out["layout_deterministic"] is True
    assert out["viewer_schema_mismatches_remaining"] == []


def test_analyze_polish_detects_unfixed():
    """수정 전 mismatch viewer는 fixed=False로 판정된다."""
    out = analyze_polish(_VIEWER_MISMATCH, _REPLAY_001)
    assert out["viewer_schema_mismatches_remaining"]
    assert out["edge_mapping_fixed"] is False or out["node_layout_generated"] is False


def test_protected_hashes_exclude_product_include_replay(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    h = compute_polish_protected_hashes(run)
    keys = " ".join(h.keys())
    assert "/product/" not in keys  # product는 보호 대상 아님
    assert "replay/index.json" in keys  # replay는 보호 대상
    assert any(k.endswith("src/runner.py") for k in h)


# ---------------------------------------------------------------- Group B: dry-run / apply / hash

def test_dry_run_does_not_modify(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    viewer = run / "final_artifact" / "product" / "viewer" / "index.html"
    before = viewer.read_text(encoding="utf-8")
    out = run_product_polish(run_dir=run, apply=False)
    assert out["status"] == "DRY_RUN_PASS"
    assert viewer.read_text(encoding="utf-8") == before  # 미수정
    assert not (run / "review" / "phase2c1" / "phase2c1_polish_report.json").is_file()


def test_dry_run_plan_lists_mismatches(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    out = run_product_polish(run_dir=run, apply=False)
    assert out["plan"]["detected_mismatches"]
    assert any("product/" in f for f in out["plan"]["planned_files"])


def test_apply_protected_hash_unchanged(tmp_path):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    before = compute_polish_protected_hashes(run)
    out = run_product_polish(run_dir=run, apply=True)
    after = compute_polish_protected_hashes(run)
    assert out["status"] == "POLISHED"
    assert out["hash_status"] == "PASS"
    assert before == after  # src/golden/fixtures/contract/replay 불변
    assert out["patched_files"]


def test_apply_changes_only_product(tmp_path):
    run, out = _polished_run(tmp_path)
    diff = json.loads((run / "review" / "phase2c1" / "phase2c1_diff_summary.json").read_text("utf-8"))
    assert diff["core_golden_fixtures_contract_replay_changed"] is False
    assert all("/product/" in c for c in diff["product_files_changed"])


def test_apply_does_not_touch_src_or_replay(tmp_path):
    run, _ = _polished_run(tmp_path)
    runner_before = _REPLAY_001  # sentinel; check runner unchanged content
    runner = (run / "final_artifact" / "src" / "runner.py").read_text("utf-8")
    assert "argparse" in runner  # runner 그대로
    replay = json.loads((run / "final_artifact" / "replay" / "replay_scenario_001.json").read_text("utf-8"))
    # replay 노드에 좌표를 추가하지 않았다
    for node in replay["final_state"]["nodes"].values():
        assert "x" not in node and "y" not in node


# ---------------------------------------------------------------- Group C: smoke + fitness after polish

def test_smoke_after_polish_generated(tmp_path):
    run, out = _polished_run(tmp_path)
    rd = run / "review" / "phase2c1"
    smoke = json.loads((rd / "artifact_smoke_review_after_polish.json").read_text("utf-8"))
    assert smoke["edge_mapping_fixed"] is True
    assert smoke["event_mapping_fixed"] is True
    assert smoke["node_layout_generated"] is True
    assert smoke["layout_deterministic"] is True
    assert smoke["viewer_schema_mismatches_remaining"] == []
    assert smoke["runner_executable"] is True
    assert smoke["runner_viewer_consistent"] is True


def test_fitness_after_polish_improves_but_stays_polish(tmp_path):
    """result-viewer-only(#47류)는 field mapping이 고쳐져도 NEEDS_PRODUCT_POLISH 유지 (§11)."""
    run, out = _polished_run(tmp_path)
    assert out["recommended_fitness"] == "NEEDS_PRODUCT_POLISH"
    # Product layer / Demo 점수는 mismatch 해소로 4점으로 개선
    assert out["fitness"]["scores"]["Product layer usefulness"] == 4
    assert out["fitness"]["scores"]["Demo understandability"] == 4
    assert any("조작 가능한 product experience" in r for r in out["fitness"]["critical_red_flags"])


def test_polish_blocked_when_already_candidate(tmp_path):
    """2C-0에서 이미 PRODUCT_CANDIDATE인 run(조작 가능한 clean viewer)은 polish 대상이 아니다 (§8)."""
    run = _build_green_run(tmp_path, _VIEWER_CLEAN)
    r0 = run_review_package(run_dir=run)
    assert r0["recommended_fitness"] == "PRODUCT_CANDIDATE"
    out = run_product_polish(run_dir=run, apply=True)
    assert out["status"] == "CANNOT_POLISH"
    assert any("NEEDS_PRODUCT_POLISH" in p for p in out["problems"])


def test_precondition_requires_2c0_polish(tmp_path):
    """2C-0 fitness가 없으면 polish 차단."""
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)  # 2C-0 review 미실행
    out = run_product_polish(run_dir=run, apply=True)
    assert out["status"] == "CANNOT_POLISH"
    assert any("2C-0" in p or "phase2c0" in p.lower() for p in out["problems"])


# ---------------------------------------------------------------- Group D: validate 규칙 (§13)

def _write_min_polish(run_dir: Path, *, recommended="NEEDS_PRODUCT_POLISH",
                      edge=True, event=True, layout=True, remaining=None, consistent=True,
                      hash_status="PASS", protected_changed=False, product_changed=None,
                      scores=None, red_flags=None, criteria=None):
    rd = run_dir / "review" / "phase2c1"
    remaining = remaining if remaining is not None else []
    product_changed = product_changed if product_changed is not None else \
        ["final_artifact/product/viewer/index.html"]
    scores = scores or {"Core usefulness": 5, "Interaction clarity": 3,
                        "Product layer usefulness": 4, "Demo understandability": 4,
                        "Extension potential": 4, "Evidence quality": 5, "Anti-hardcode confidence": 4}
    smoke = {"edge_mapping_fixed": edge, "event_mapping_fixed": event,
             "node_layout_generated": layout, "layout_deterministic": layout,
             "viewer_schema_mismatches_remaining": remaining,
             "runner_executable": True, "product_viewer_reads_replay": True,
             "runner_viewer_consistent": consistent}
    fitness = {"recommended_fitness": recommended, "average_score": 4.14, "scores": scores,
               "criteria": criteria or [{"criterion": k, "score": v, "evidence": ["x"]}
                                        for k, v in scores.items()],
               "critical_red_flags": red_flags or [], "green_base": True, "gate_fail": False,
               "runner_viewer_consistent": consistent,
               "edge_mapping_fixed": edge, "event_mapping_fixed": event,
               "node_layout_generated": layout,
               "viewer_schema_mismatches_remaining": remaining}
    for rel in ("phase2c1_polish_plan.md", "phase2c1_polish_report.md",
                "artifact_smoke_review_after_polish.md", "product_fitness_report_after_polish.md"):
        (rd / rel).parent.mkdir(parents=True, exist_ok=True)
        (rd / rel).write_text("# stub\n", encoding="utf-8")
    _dump(rd / "phase2c1_polish_plan.json", {})
    _dump(rd / "phase2c1_polish_report.json", {"applied": True})
    _dump(rd / "phase2c1_diff_summary.json", {
        "core_golden_fixtures_contract_replay_changed": protected_changed,
        "product_files_changed": product_changed})
    _dump(rd / "phase2c1_hash_check.json", {"status": hash_status})
    _dump(rd / "artifact_smoke_review_after_polish.json", smoke)
    _dump(rd / "product_fitness_report_after_polish.json", fitness)
    _dump(rd / "phase2c1_dashboard_summary.json", {"recommended_fitness": recommended})
    return rd


def test_detect_marker(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    assert detect_phase2c1_run(run) is False
    _write_min_polish(run)
    assert detect_phase2c1_run(run) is True


def test_validate_clean_polish_passes(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run)
    assert _check_phase2c1(run) == []


def test_validate_no_marker_no_check(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    assert _check_phase2c1(run) == []


def test_validate_protected_changed_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run, hash_status="FAIL")
    assert any("보호 대상" in p for p in _check_phase2c1(run))


def test_validate_replay_changed_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run, protected_changed=True)
    assert any("golden/fixtures/contract/replay 변경" in p for p in _check_phase2c1(run))


def test_validate_change_outside_product_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run, product_changed=["final_artifact/src/runner.py"])
    assert any("허용 범위 밖" in p for p in _check_phase2c1(run))


def test_validate_candidate_edge_unfixed_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run, recommended="PRODUCT_CANDIDATE", edge=False)
    assert any("edge_mapping_fixed != true" in p for p in _check_phase2c1(run))


def test_validate_candidate_remaining_mismatch_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run, recommended="PRODUCT_CANDIDATE",
                      remaining=["viewer는 node.x/node.y ..."])
    assert any("mismatches_remaining" in p for p in _check_phase2c1(run))


def test_validate_candidate_inconsistent_fails(tmp_path):
    run = tmp_path / "r"
    _write_min_polish(run, recommended="PRODUCT_CANDIDATE", consistent="unknown")
    assert any("runner_viewer_consistent != true" in p for p in _check_phase2c1(run))


def test_validate_candidate_low_critical_fails(tmp_path):
    run = tmp_path / "r"
    low = {"Core usefulness": 5, "Interaction clarity": 3,
           "Product layer usefulness": 3, "Demo understandability": 4,
           "Extension potential": 4, "Evidence quality": 5, "Anti-hardcode confidence": 4}
    _write_min_polish(run, recommended="PRODUCT_CANDIDATE", scores=low)
    assert any("핵심 항목 4점 미만" in p for p in _check_phase2c1(run))


def test_validate_missing_required_fails(tmp_path):
    run = tmp_path / "r"
    rd = _write_min_polish(run)
    (rd / "phase2c1_dashboard_summary.json").unlink()
    assert any("산출물 없음" in p for p in _check_phase2c1(run))


def test_validate_evidence_less_high_score_blocked(tmp_path):
    run = tmp_path / "r"
    crit = [{"criterion": "Core usefulness", "score": 5, "evidence": []}]
    _write_min_polish(run, criteria=crit)
    assert any("evidence 없는" in p for p in _check_phase2c1(run))


# ---------------------------------------------------------------- Group E: CLI

def test_cli_requires_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["factory-product-polish"]) == 1
    assert main(["factory-product-polish", "--run-dir", "x", "--dry-run", "--apply"]) == 1


def test_cli_apply_on_synthetic(tmp_path, monkeypatch):
    run = _build_green_run(tmp_path, _VIEWER_MISMATCH)
    run_review_package(run_dir=run)
    monkeypatch.chdir(tmp_path)
    rc = main(["factory-product-polish", "--run-dir", str(run), "--apply"])
    assert rc == 0
    assert (run / "review" / "phase2c1" / "phase2c1_polish_report.md").is_file()


# ---------------------------------------------------------------- Group F: 실제 #47 E2E

@pytest.mark.skipif(not FIXTURE_47.is_dir(), reason="#47 runtime 산출물 없음")
def test_e2e_47_polish(tmp_path):
    run = tmp_path / FIXTURE_47.name
    shutil.copytree(FIXTURE_47, run)
    for sub in ("phase2c1",):
        d = run / "review" / sub
        if d.is_dir():
            shutil.rmtree(d)
    # 2C-0 review를 다시 생성(원본 viewer 기준)
    if (run / "review" / "phase2c0").is_dir():
        shutil.rmtree(run / "review" / "phase2c0")
    # pre-polish viewer로 되돌린다(원본 #47은 이미 polish됐을 수 있음)
    _restore_prepolish_viewer(run)
    run_review_package(run_dir=run)
    before = compute_polish_protected_hashes(run)
    out = run_product_polish(run_dir=run, apply=True)
    after = compute_polish_protected_hashes(run)
    assert out["status"] == "POLISHED"
    assert out["hash_status"] == "PASS"
    assert before == after  # src/golden/fixtures/contract/replay 불변
    assert out["extra"]["edge_mapping_fixed"] is True
    assert out["extra"]["event_mapping_fixed"] is True
    assert out["extra"]["node_layout_generated"] is True
    assert out["extra"]["viewer_schema_mismatches_remaining"] == []
    ok, problems = validate_product_run_dir(run, [])
    assert ok, problems


def _restore_prepolish_viewer(run: Path):
    """이미 폴리시된 #47 사본을 pre-polish(결함 매핑) viewer로 되돌려 E2E가 항상 mismatch에서 시작하게 한다."""
    prepolish_script = """<script>
        async function init(){ const r = await fetch('../../replay/index.json'); const d = await r.json();
          const s = document.getElementById('scenario-select'); s.innerHTML='';
          d.replays.forEach(x=>{const o=document.createElement('option'); o.value=x.file; o.textContent=x.id; s.appendChild(o);}); }
        async function loadSelectedScenario(){ const f=document.getElementById('scenario-select').value;
          const r=await fetch('../../replay/'+f); const data=await r.json();
          document.getElementById('details-content').innerHTML=JSON.stringify(data.summary);
          data.events.forEach(ev=>{ const e=ev.type+': '+ev.message; });
          const nodes=data.final_state.nodes; const edges=data.final_state.edges;
          edges.forEach(edge=>{ const a=nodes[edge.from]; const b=nodes[edge.to]; });
          Object.entries(nodes).forEach(([id,node])=>{ const x=node.x; const y=node.y; });
        }
        window.onload = init;
    </script>"""
    import re as _re
    for base in ("final_artifact", "workspace"):
        v = run / base / "product" / "viewer" / "index.html"
        if v.is_file():
            txt = v.read_text(encoding="utf-8")
            txt = _re.sub(r"<script>.*?</script>", prepolish_script, txt, count=1, flags=_re.DOTALL)
            v.write_text(txt, encoding="utf-8")
