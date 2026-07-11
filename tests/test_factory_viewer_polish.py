# 이슈 #7 §16: 도메인 중립 VIEWER_POLISH — discovery/contract/adapter/navigation/evidence/validator/lane 검증.
import json
import shutil
from pathlib import Path

import pytest

from repo_idea_miner.factory_product_evidence import viewer_field_mismatches
from repo_idea_miner.factory_validate import _check_viewer_polish_lane
from repo_idea_miner.factory_viewer_polish import (
    ADAPTER_GRAPH_LEGACY,
    ADAPTER_STANDARD,
    DISCOVERY_STATUSES,
    VIEWER_CONTRACT_REL,
    VIEWER_HTML_REL,
    VIEWER_STATUSES,
    ViewerModel,
    build_viewer_contract,
    check_js_syntax,
    discover_replay_sources,
    frames_from_replay,
    generate_viewer_html,
    run_navigation_smoke,
    run_viewer_polish,
    select_adapter,
    validate_viewer_contract,
)


def _dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_available() -> bool:
    return check_js_syntax("<script>var a = 1;</script>")["status"] == "PASS"


# 세 도메인 replay — state-rule형 / table형 / filesystem형 (§6.2). 동일 viewer core로 표현돼야 한다.
_DOMAINS = {
    "rules": {
        "state_contract": {"state_entities": [
            {"name": "ReviewState", "fields": ["streak", "last_grade"], "invariants": []}]},
        "initial_state": {"ReviewState": {"streak": 0, "last_grade": None}},
        "replay": {"ok": True, "errors": [], "summary": "2 answered",
                   "final_state": {"ReviewState": {"streak": 2, "last_grade": 5}},
                   "events": [{"type": "CARD_ANSWERED", "card_id": "card_1"},
                              {"type": "CARD_ANSWERED", "card_id": "card_2"}]},
    },
    "table": {
        "state_contract": {"state_entities": [
            {"name": "Table", "fields": ["columns", "rows"], "invariants": []}]},
        "initial_state": {"Table": {"columns": [], "rows": []}},
        "replay": {"ok": True, "errors": [], "summary": "1 column",
                   "final_state": {"Table": {"columns": ["col_a"], "rows": []}},
                   "events": [{"type": "COLUMN_ADDED", "target_id": "col_a"},
                              {"type": "CELL_UPDATED", "target_id": "row_1"}]},
    },
    "files": {
        "state_contract": {"state_entities": [
            {"name": "Tree", "fields": ["current", "entries"], "invariants": []}]},
        "initial_state": {"Tree": {"current": "root", "entries": ["root", "docs"]}},
        "replay": {"ok": True, "errors": [], "summary": "1 executed",
                   "final_state": {"Tree": {"current": "docs", "entries": ["root", "docs"]}},
                   "events": [{"type": "FOLDER_ENTERED", "target_id": "docs"},
                              {"type": "ITEM_SELECTED", "target_id": "file1"}]},
    },
}


def _make_viewer_run(tmp_path: Path, domain: str = "rules", name: str | None = None) -> Path:
    spec = _DOMAINS[domain]
    run = tmp_path / (name or f"run_{domain}")
    ws = run / "workspace"
    _dump(ws / "state_contract.json", spec["state_contract"])
    _dump(ws / "action_contract.json", {"actions": [{"name": "noop", "input": []}]})
    _dump(ws / "fixtures" / "scenario_001.json",
          {"id": "scenario_001", "initial_state": spec["initial_state"], "actions": []})
    _dump(ws / "replay" / "index.json",
          {"replays": [{"id": "scenario_001", "file": "replay_scenario_001.json", "ok": True}]})
    _dump(ws / "replay" / "replay_scenario_001.json", spec["replay"])
    return run


def _add_broken_viewer(run: Path) -> None:
    """fresh SRS 27형 결함 viewer — 존재하지만 실제 replay 파일을 읽지 못한다."""
    v = run / "workspace" / "product" / "viewer" / "index.html"
    v.parent.mkdir(parents=True, exist_ok=True)
    v.write_text('<html><script>fetch("../../replay/scenarios/none.json");'
                 '</script></html>', encoding="utf-8")


# ---------------------------------------------------------------- §16.1 Artifact Discovery

def test_discovery_explicit_index_ref(tmp_path):
    run = _make_viewer_run(tmp_path)
    d = discover_replay_sources(run / "workspace")
    assert d["status"] == "FOUND"
    assert d["provenance"] == "explicit_index_ref"
    assert d["sources"][0]["ref"] == "replay/replay_scenario_001.json"
    assert d["sources"][0]["replay_id"] == "scenario_001"


def test_discovery_single_legacy_candidate(tmp_path):
    run = _make_viewer_run(tmp_path)
    (run / "workspace" / "replay" / "index.json").unlink()
    d = discover_replay_sources(run / "workspace")
    assert d["status"] == "FOUND"
    assert d["provenance"] == "compatibility_single_candidate"


def test_discovery_no_candidate_is_missing(tmp_path):
    run = _make_viewer_run(tmp_path)
    shutil.rmtree(run / "workspace" / "replay")
    d = discover_replay_sources(run / "workspace")
    assert d["status"] == "MISSING"
    assert d["sources"] == []


def test_discovery_multiple_candidates_is_ambiguous(tmp_path):
    run = _make_viewer_run(tmp_path)
    rdir = run / "workspace" / "replay"
    (rdir / "index.json").unlink()
    (rdir / "replay_scenario_002.json").write_text("{}", encoding="utf-8")
    d = discover_replay_sources(run / "workspace")
    assert d["status"] == "AMBIGUOUS"
    assert d["sources"] == []
    # 후보 나열은 결정적(정렬)이다
    assert d["candidates"] == sorted(d["candidates"])


def test_discovery_invalid_index_schema(tmp_path):
    run = _make_viewer_run(tmp_path)
    (run / "workspace" / "replay" / "index.json").write_text('{"x": 1}', encoding="utf-8")
    d = discover_replay_sources(run / "workspace")
    assert d["status"] == "INVALID"


def test_discovery_index_entries_without_file_ref(tmp_path):
    run = _make_viewer_run(tmp_path)
    _dump(run / "workspace" / "replay" / "index.json", {"replays": [{"id": "s1"}]})
    d = discover_replay_sources(run / "workspace")
    assert d["status"] == "INVALID"


def test_module_has_no_challenge_or_filename_hardcode():
    src = Path("repo_idea_miner/factory_viewer_polish.py").read_text(encoding="utf-8")
    assert "challenge" not in src.lower()
    # 특정 run/제품 이름 하드코드 금지 — 파일명 패턴은 discovery/compatibility 층에만
    for token in ("factory_2026", "scenario_001", "card_", "col_", "node_in"):
        assert token not in src, token


# ---------------------------------------------------------------- §16.2 Canonical Contract

def test_valid_contract_has_required_meaning(tmp_path):
    run = _make_viewer_run(tmp_path)
    built = build_viewer_contract(run / "workspace")
    assert built["viewer_status"] == "REPLAY_READY"
    c = built["contract"]
    for key in ("viewer_id", "viewer_kind", "source_artifact_refs", "title",
                "replays", "current_frame", "capabilities", "validation_rules",
                "evidence_requirements", "viewer_status"):
        assert key in c, key
    r = c["replays"][0]
    for key in ("replay_id", "source_ref", "source_sha256", "ok", "errors",
                "initial_state", "final_state", "frames", "replay_status"):
        assert key in r, key
    assert validate_viewer_contract(c)["pass"] is True


def test_contract_is_deterministic(tmp_path):
    run = _make_viewer_run(tmp_path)
    a = build_viewer_contract(run / "workspace")["contract"]
    b = build_viewer_contract(run / "workspace")["contract"]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_contract_all_sources_invalid(tmp_path):
    run = _make_viewer_run(tmp_path)
    (run / "workspace" / "replay" / "replay_scenario_001.json").write_text(
        "깨진 json", encoding="utf-8")
    built = build_viewer_contract(run / "workspace")
    assert built["viewer_status"] == "REPLAY_INVALID"
    assert built["contract"] is None


def test_contract_zero_frames_flagged(tmp_path):
    run = _make_viewer_run(tmp_path)
    spec = dict(_DOMAINS["rules"]["replay"], events=[])
    _dump(run / "workspace" / "replay" / "replay_scenario_001.json", spec)
    built = build_viewer_contract(run / "workspace")
    c = built["contract"]
    assert c["replays"][0]["replay_status"] == "REPLAY_VALIDATION_FAILED"
    v = validate_viewer_contract(c)
    assert v["pass"] is False
    assert any("navigable" in p for p in v["problems"])


def test_contract_missing_fixture_initial_state_is_explicit(tmp_path):
    run = _make_viewer_run(tmp_path)
    shutil.rmtree(run / "workspace" / "fixtures")
    built = build_viewer_contract(run / "workspace")
    r = built["contract"]["replays"][0]
    assert r["initial_state"] is None
    assert any("initial_state 미확보" in p for p in built["problems"])


def test_validate_contract_rejects_broken_sequence(tmp_path):
    run = _make_viewer_run(tmp_path)
    c = build_viewer_contract(run / "workspace")["contract"]
    c["replays"][0]["frames"][0]["sequence"] = 7
    v = validate_viewer_contract(c)
    assert v["pass"] is False
    assert any("sequence" in p for p in v["problems"])


# ---------------------------------------------------------------- §16.3 Domain Adapters

def test_adapter_selected_by_schema_shape_not_domain_name():
    typed = [{"events": [{"type": "X", "target_id": "a"}]}]
    legacy = [{"events": [{"event": "node_created", "node_id": "n1"}]}]
    assert select_adapter(typed)[0] == ADAPTER_STANDARD
    assert select_adapter(legacy)[0] == ADAPTER_GRAPH_LEGACY


def test_adapter_mixed_or_unknown_schema_unsupported():
    mixed = [{"events": [{"type": "X"}, {"event": "Y"}]}]
    unknown = [{"events": [{"kind": "Z"}]}]
    assert select_adapter(mixed)[0] is None
    assert select_adapter(unknown)[0] is None
    assert select_adapter([{"events": ["문자열"]}])[0] is None


@pytest.mark.parametrize("domain", sorted(_DOMAINS))
def test_standard_adapter_converts_all_domains_same_core(tmp_path, domain):
    """SRS/table/filesystem 세 도메인이 동일 adapter·동일 contract 구조로 변환된다 (§6.2)."""
    run = _make_viewer_run(tmp_path, domain)
    built = build_viewer_contract(run / "workspace")
    c = built["contract"]
    assert c["viewer_kind"] == ADAPTER_STANDARD
    frames = c["replays"][0]["frames"]
    raw = _DOMAINS[domain]["replay"]["events"]
    assert [f["event_kind"] for f in frames] == [e["type"] for e in raw]
    assert [f["payload"] for f in frames] == raw  # 원시 event 보존 — 날조 없음
    assert frames[0]["before_state"] == _DOMAINS[domain]["initial_state"]
    assert frames[-1]["after_state"] == _DOMAINS[domain]["replay"]["final_state"]
    assert all(f["sequence"] == i + 1 for i, f in enumerate(frames))


def test_graph_legacy_adapter_converts_event_key():
    frames = frames_from_replay(
        ADAPTER_GRAPH_LEGACY, "s1",
        {"events": [{"event": "node_created", "node_id": "n1"}],
         "final_state": {"nodes": {}}, "errors": []},
        initial_state=None)
    assert frames[0]["event_kind"] == "node_created"
    assert frames[0]["affected_targets"] == ["node_id=n1"]


def test_adapter_does_not_fabricate_missing_values():
    """§11.3: 값이 없으면 null/생략 — 임의 message·중간 state를 만들지 않는다."""
    frames = frames_from_replay(
        ADAPTER_STANDARD, "s1",
        {"events": [{"type": "A"}, {"type": "B"}, {"type": "C"}],
         "final_state": {"x": 1}, "errors": []},
        initial_state=None)
    assert frames[0]["before_state"] is None  # initial 미확보 → null
    assert frames[0]["after_state"] is None
    assert frames[1]["before_state"] is None and frames[1]["after_state"] is None
    assert frames[2]["after_state"] == {"x": 1}
    assert frames[0]["affected_targets"] == []


# ---------------------------------------------------------------- §16.4 Viewer Runtime (model)

def _ready_contract(tmp_path, domain="rules"):
    run = _make_viewer_run(tmp_path, domain)
    return build_viewer_contract(run / "workspace")["contract"]


def test_navigation_initial_next_previous_reset(tmp_path):
    c = _ready_contract(tmp_path)
    m = ViewerModel(c)
    first = m.current_frame()
    assert first["sequence"] == 1
    assert m.next() is True
    assert m.current_frame()["sequence"] == 2
    assert m.previous() is True
    assert m.current_frame()["frame_id"] == first["frame_id"]
    m.select_frame(2)
    assert m.status() == "REPLAY_COMPLETE"
    m.reset()
    assert m.current_frame()["sequence"] == 1


def test_navigation_smoke_passes_on_valid_contract(tmp_path):
    c = _ready_contract(tmp_path)
    smoke = run_navigation_smoke(c)
    assert smoke["pass"] is True
    assert len(smoke["visited_frames"]) >= 2
    assert smoke["checks"]["state_transition_observed"] is True


def test_navigation_smoke_fails_without_navigable_replay(tmp_path):
    c = _ready_contract(tmp_path)
    for r in c["replays"]:
        r["frames"] = []
    smoke = run_navigation_smoke(c)
    assert smoke["pass"] is False


def test_navigation_smoke_fails_when_state_never_changes(tmp_path):
    run = _make_viewer_run(tmp_path)
    same = dict(_DOMAINS["rules"]["replay"],
                final_state=_DOMAINS["rules"]["initial_state"])
    _dump(run / "workspace" / "replay" / "replay_scenario_001.json", same)
    c = build_viewer_contract(run / "workspace")["contract"]
    smoke = run_navigation_smoke(c)
    assert smoke["checks"]["state_transition_observed"] is False
    assert smoke["pass"] is False


def test_viewer_html_has_no_raw_key_or_mock_literals():
    html = generate_viewer_html()
    for lit in ("edge.from", "edge.to", "ev.type", "ev.message", "node.x", "node.y",
                "Math.random", "Date.now"):
        assert lit not in html, lit
    import re
    assert not re.search(r"\.type\b", html)
    # 오류 상태 7종이 core에 존재한다 (§7.3)
    for status in ("REPLAY_MISSING", "REPLAY_COMPLETE", "REPLAY_READY"):
        assert status in html, status


@pytest.mark.skipif(not _node_available(), reason="node 없음 — JS 파싱 검증 불가")
def test_viewer_html_js_parses_with_node():
    assert check_js_syntax(generate_viewer_html())["status"] == "PASS"


# ---------------------------------------------------------------- executor (§7, §9.3)

def test_executor_applies_and_writes_contract_viewer(tmp_path):
    run = _make_viewer_run(tmp_path)
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is True and out["ok"] is True
    assert out["status"] == "APPLIED"
    assert sorted(out["patched_files"]) == sorted([VIEWER_HTML_REL, VIEWER_CONTRACT_REL])
    ws = run / "workspace"
    assert (ws / VIEWER_HTML_REL).is_file()
    written = _load(ws / VIEWER_CONTRACT_REL)
    assert written["viewer_kind"] == ADAPTER_STANDARD
    report = _load(run / "review/viewer_polish/viewer_polish_report.json")
    assert report["viewer_polish_included"] is True
    assert report["discovery_status"] == "FOUND"


def test_executor_dry_run_writes_nothing_to_product(tmp_path):
    run = _make_viewer_run(tmp_path)
    out = run_viewer_polish(run_dir=run, apply=False)
    assert out["status"] == "PLAN_ONLY"
    assert not (run / "workspace" / VIEWER_HTML_REL).is_file()


def test_executor_missing_replay_is_explicit_precondition(tmp_path):
    run = _make_viewer_run(tmp_path)
    shutil.rmtree(run / "workspace" / "replay")
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "PRECONDITION_REPLAY_MISSING"
    assert out["discovery_status"] == "MISSING"
    # 실패도 report/discovery로 기록된다 — 빈 화면으로 감추지 않는다
    report = _load(run / "review/viewer_polish/viewer_polish_report.json")
    assert report["viewer_status"] == "REPLAY_MISSING"
    assert not (run / "workspace" / VIEWER_HTML_REL).is_file()


def test_executor_ambiguous_and_unsupported_are_explicit(tmp_path):
    run = _make_viewer_run(tmp_path)
    rdir = run / "workspace" / "replay"
    (rdir / "index.json").unlink()
    (rdir / "replay_scenario_002.json").write_text("{}", encoding="utf-8")
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["status"] == "PRECONDITION_REPLAY_AMBIGUOUS"

    run2 = _make_viewer_run(tmp_path, name="run_unsupported")
    _dump(run2 / "workspace" / "replay" / "replay_scenario_001.json",
          {"ok": True, "errors": [], "final_state": {},
           "events": [{"unknown_key": 1}]})
    out2 = run_viewer_polish(run_dir=run2, apply=True)
    assert out2["status"] == "PRECONDITION_REPLAY_UNSUPPORTED"


def test_executor_graph_domain_routes_away(tmp_path):
    run = _make_viewer_run(tmp_path)
    _dump(run / "workspace" / "state_contract.json", {"state_entities": [
        {"name": "GraphState", "fields": ["nodes", "edges"], "invariants": []}]})
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["status"] == "PRECONDITION_GRAPH_DOMAIN"


def test_executor_zero_frame_only_is_validation_failed_not_applied(tmp_path):
    """§8: frame 0개·HTML 생성만으로는 성공을 인정하지 않는다."""
    run = _make_viewer_run(tmp_path)
    spec = dict(_DOMAINS["rules"]["replay"], events=[])
    _dump(run / "workspace" / "replay" / "replay_scenario_001.json", spec)
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is False
    assert out["status"] == "VIEWER_VALIDATION_FAILED"
    assert not (run / "workspace" / VIEWER_HTML_REL).is_file()
    report = _load(run / "review/viewer_polish/viewer_polish_report.json")
    assert report["viewer_polish_included"] is False


# ---------------------------------------------------------------- §16.5 Viewer Evidence

def test_evidence_is_machine_checkable_and_fresh(tmp_path):
    run = _make_viewer_run(tmp_path, "table")
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is True
    ev = _load(run / "review/viewer_polish/viewer_evidence.json")
    for key in ("viewer_contract_digest", "source_replay_refs", "adapter_identity",
                "frame_count", "initial_frame", "visited_frames",
                "state_transitions_observed", "validation_failures",
                "discovery_status", "render_status", "navigation"):
        assert key in ev, key
    assert ev["viewer_provenance"]["fresh"] is True
    assert all(r.get("sha256") for r in ev["source_replay_refs"])
    assert len(ev["visited_frames"]) >= 2


# ---------------------------------------------------------------- validator (§8)

def _applied_run(tmp_path, domain="rules"):
    run = _make_viewer_run(tmp_path, domain)
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is True
    return run


def test_validator_accepts_honest_run(tmp_path):
    run = _applied_run(tmp_path)
    assert _check_viewer_polish_lane(run) == []


def test_validator_blocks_included_overclaim(tmp_path):
    run = _applied_run(tmp_path)
    rp = run / "review/viewer_polish/viewer_polish_report.json"
    report = _load(rp)
    report["applied"] = False
    _dump(rp, report)
    problems = _check_viewer_polish_lane(run)
    assert any("과장" in p for p in problems)


def test_validator_blocks_navigation_overclaim(tmp_path):
    run = _applied_run(tmp_path)
    ep = run / "review/viewer_polish/viewer_evidence.json"
    ev = _load(ep)
    ev["navigation"]["pass"] = False
    _dump(ep, ev)
    problems = _check_viewer_polish_lane(run)
    assert any("navigation 실증 없이" in p for p in problems)


def test_validator_blocks_zero_frame_and_missing_digest(tmp_path):
    run = _applied_run(tmp_path)
    ep = run / "review/viewer_polish/viewer_evidence.json"
    ev = _load(ep)
    ev["frame_count"] = 0
    ev["source_replay_refs"] = [{"ref": "replay/x.json"}]
    _dump(ep, ev)
    problems = _check_viewer_polish_lane(run)
    assert any("frame 0개" in p for p in problems)
    assert any("mock 의심" in p for p in problems)


def test_validator_blocks_unknown_status_and_stale_provenance(tmp_path):
    run = _applied_run(tmp_path)
    rp = run / "review/viewer_polish/viewer_polish_report.json"
    report = _load(rp)
    report["viewer_status"] = "GREAT_SUCCESS"
    _dump(rp, report)
    ep = run / "review/viewer_polish/viewer_evidence.json"
    ev = _load(ep)
    ev["viewer_provenance"]["fresh"] = False
    _dump(ep, ev)
    problems = _check_viewer_polish_lane(run)
    assert any("알 수 없는 viewer 상태" in p for p in problems)
    assert any("재사용 의심" in p for p in problems)


def test_statuses_enums_are_closed():
    assert set(DISCOVERY_STATUSES) == {"FOUND", "MISSING", "AMBIGUOUS", "INVALID",
                                       "UNSUPPORTED"}
    assert "REPLAY_COMPLETE" in VIEWER_STATUSES and "REPLAY_VALIDATION_FAILED" in VIEWER_STATUSES


# ---------------------------------------------------------------- §16.6 Product Loop

def test_lane_routes_graph_to_legacy_and_generic_to_new(tmp_path, monkeypatch):
    import repo_idea_miner.factory_lane_executors as fle
    import repo_idea_miner.factory_product_polish as fpp
    import repo_idea_miner.factory_viewer_polish as fvp

    calls = []

    def fake_legacy(run_dir=None, apply=False, timeout=60.0, **kw):
        calls.append("graph_adapter")
        return {"applied": False, "patched_files": [], "problems": [], "error": None,
                "ok": False, "status": "PRECONDITION_TEST"}

    def fake_generic(run_dir=None, apply=False, timeout=60.0, **kw):
        calls.append("generic")
        return {"applied": False, "patched_files": [], "problems": [], "error": None,
                "ok": False, "status": "PRECONDITION_TEST"}

    monkeypatch.setattr(fpp, "run_product_polish", fake_legacy)
    monkeypatch.setattr(fvp, "run_viewer_polish", fake_generic)

    generic_run = _make_viewer_run(tmp_path)
    fle.execute_lane("VIEWER_POLISH",
                     {"parent_run_dir": generic_run, "children_root": tmp_path / "children"})
    graph_run = tmp_path / "graph_parent"
    _dump(graph_run / "workspace" / "state_contract.json", {"state_entities": [
        {"name": "GraphState", "fields": ["nodes", "edges"], "invariants": []}]})
    fle.execute_lane("VIEWER_POLISH",
                     {"parent_run_dir": graph_run, "children_root": tmp_path / "children"})
    assert calls == ["generic", "graph_adapter"]


def test_lane_execution_in_child_keeps_parent_untouched(tmp_path):
    import repo_idea_miner.factory_lane_executors as fle

    run = _make_viewer_run(tmp_path, "files")
    before = (run / "workspace" / "replay" / "replay_scenario_001.json").read_bytes()
    result = fle.execute_lane(
        "VIEWER_POLISH", {"parent_run_dir": run, "children_root": tmp_path / "children"})
    assert result["status"] == "APPLIED", result
    assert result["protected_hash_check"] == "PASS"
    assert result["allowed_scope_check"] == "PASS"
    child = Path(result["child_run_dir"])
    assert (child / "workspace" / VIEWER_CONTRACT_REL).is_file()
    assert not (run / "workspace" / VIEWER_HTML_REL).is_file()  # parent 불변
    assert (run / "workspace" / "replay" / "replay_scenario_001.json").read_bytes() == before


def _viewer_gap(run):
    from repo_idea_miner.factory_autopilot_desks import derive_primary_gap, mock_product_judge
    from repo_idea_miner.factory_product_loop import (
        apply_hard_blockers,
        extract_artifact_evidence,
        extract_user_facing_quality,
    )
    ev = extract_artifact_evidence(run)
    q = extract_user_facing_quality(ev)
    h = apply_hard_blockers(ev, q)
    sl = mock_product_judge(ev, q, h)
    return ev, derive_primary_gap(ev, q, sl)


def _add_gate_context(run: Path) -> None:
    _dump(run / "green_base.json", {"base_type": "green_base", "verdict": "REVIEW_READY"})


def test_gap_removed_after_viewer_polish(tmp_path):
    """§9.4: viewer가 replay를 못 읽음 → VIEWER_POLISH_REQUIRED, lane 적용 후 gap 제거."""
    run = _make_viewer_run(tmp_path)
    _add_gate_context(run)
    _add_broken_viewer(run)
    ev, gap = _viewer_gap(run)
    assert ev["facts"]["viewer_reads_replay"] is False
    assert gap == "VIEWER_POLISH_REQUIRED"
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is True
    ev2, gap2 = _viewer_gap(run)
    assert ev2["facts"]["viewer_exists"] is True
    assert ev2["facts"]["viewer_reads_replay"] is True
    assert ev2["facts"]["mismatches"] == []
    assert gap2 != "VIEWER_POLISH_REQUIRED"


def test_gap_kept_when_viewer_polish_failed(tmp_path):
    """§9.4: navigation 실증 실패면 gap이 유지된다 — 실패를 성공으로 포장하지 않는다."""
    run = _make_viewer_run(tmp_path)
    _add_gate_context(run)
    _add_broken_viewer(run)
    spec = dict(_DOMAINS["rules"]["replay"], events=[])
    _dump(run / "workspace" / "replay" / "replay_scenario_001.json", spec)
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is False
    ev, gap = _viewer_gap(run)
    assert ev["facts"]["has_viewer_polish_report"] is False
    assert gap == "VIEWER_POLISH_REQUIRED"


# ---------------------------------------------------------------- detector 수리 (§11.1)

_TYPED_REPLAY = {"events": [{"type": "COLUMN_ADDED", "target_id": "c1"}],
                 "final_state": {}, "errors": []}
_GRAPH_REPLAY = {"events": [{"event": "node_created", "node_id": "n1"}],
                 "final_state": {"nodes": {"n1": {}}, "edges": []}, "errors": []}


def test_mismatch_detector_requires_only_read_keys():
    viewer_type_only = "<script>x.events.forEach(function(ev){show(ev.type);});</script>"
    assert viewer_field_mismatches(_TYPED_REPLAY, viewer_type_only) == []
    viewer_message = "<script>x.events.forEach(function(ev){show(ev.type, ev.message);});</script>"
    out = viewer_field_mismatches(_TYPED_REPLAY, viewer_message)
    assert len(out) == 1
    assert "event.message" in out[0] and "event.type" not in out[0]


def test_mismatch_detector_still_catches_graph_schema_mismatch():
    viewer = "<script>x.events.forEach(function(ev){show(ev.type);});</script>"
    out = viewer_field_mismatches(_GRAPH_REPLAY, viewer)
    assert len(out) == 1 and "type" in out[0]


# ---------------------------------------------------------------- 실런 회귀 (§12·§13 준비)

_REAL_RUNS = {
    "srs_child": Path("runs/factory_20260711_030900"),
    "table_child": Path("runs/factory_20260711_030900_1"),
    "fs54_child": Path("runs/factory_20260711_030809"),
}
_GRAPH47 = Path("runs/factory_20260709_072220")


@pytest.mark.parametrize("label", sorted(_REAL_RUNS))
def test_real_domain_runs_convert_with_same_executor(tmp_path, label):
    src = _REAL_RUNS[label]
    if not src.is_dir():
        pytest.skip(f"{src} 없음")
    run = tmp_path / label
    shutil.copytree(src, run, ignore=shutil.ignore_patterns("__pycache__", "phase2d1"))
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["applied"] is True, out["problems"]
    assert out["viewer_kind"] == ADAPTER_STANDARD
    assert _check_viewer_polish_lane(run) == []
    # 원본 immutable run은 그대로다 (tmp copy에만 apply)
    assert not (src / "review" / "viewer_polish").exists()


def test_real_graph_47_routes_to_legacy(tmp_path):
    if not _GRAPH47.is_dir():
        pytest.skip("#47 run 없음")
    run = tmp_path / "graph47"
    shutil.copytree(_GRAPH47, run, ignore=shutil.ignore_patterns("__pycache__", "phase2d1"))
    out = run_viewer_polish(run_dir=run, apply=True)
    assert out["status"] == "PRECONDITION_GRAPH_DOMAIN"
    assert out["applied"] is False
