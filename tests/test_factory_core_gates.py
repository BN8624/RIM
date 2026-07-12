# Phase 1.6 core gate 테스트: contract/runner/replay/golden/invariant/determinism/anti-hardcode 통과·실패 (§16-23~31).
import json
from pathlib import Path

import pytest

from repo_idea_miner.factory_core_gates import (
    _entity_collection_exposure,
    _is_universal_field_invariant,
    compare_golden,
    check_invariant,
    run_anti_hardcode_gate,
    run_core_contract_gate,
    run_core_gates,
    run_determinism_gate,
    run_golden_output_gate,
    run_runner_gate,
    run_scenario_replay_gate,
    run_state_invariant_gate,
)
from repo_idea_miner.factory_core_prompts import (
    mock_broken_core_build_output,
    mock_core_build_output,
    mock_core_contract_draft,
    mock_runnerless_core_build_output,
    mock_scenario_golden_output,
)

TIMEOUT = 60.0


def _write_files(ws: Path, files: list[dict]) -> None:
    for f in files:
        p = ws / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"], encoding="utf-8")


def build_mock_workspace(tmp_path: Path, build=None) -> tuple[Path, dict, dict, dict]:
    """mock 산출물로 검증 가능한 core workspace를 만든다."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    draft = mock_core_contract_draft()
    core, runner = draft["core_contract"], draft["runner_contract"]
    (ws / "core_contract.json").write_text(json.dumps(core, ensure_ascii=False), encoding="utf-8")
    (ws / "state_contract.json").write_text(
        json.dumps({"state_entities": core["state_entities"]}, ensure_ascii=False), encoding="utf-8")
    (ws / "action_contract.json").write_text(
        json.dumps({"actions": core["actions"]}, ensure_ascii=False), encoding="utf-8")
    (ws / "runner_contract.json").write_text(json.dumps(runner, ensure_ascii=False), encoding="utf-8")
    sg = mock_scenario_golden_output()
    for s in sg["scenarios"]:
        p = ws / "fixtures" / f"{s['id']}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    for g in sg["goldens"]:
        num = g["scenario_id"].split("_", 1)[1]
        p = ws / "golden" / f"expected_{num}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    _write_files(ws, (build or mock_core_build_output())["files"])
    return ws, core, runner, sg


# ---------------------------------------------------------------- Core Contract Gate (§16-24)

def test_core_contract_gate_pass_and_fail(tmp_path):
    ws, core, runner, _ = build_mock_workspace(tmp_path)
    assert run_core_contract_gate(ws, core, runner).ok
    # contract 파일 삭제 → 실패
    (ws / "state_contract.json").unlink()
    r = run_core_contract_gate(ws, core, runner)
    assert not r.ok and any("state_contract.json" in p for p in r.problems)
    # 코드에 없는 action → 실패
    ws2, core2, runner2, _ = build_mock_workspace(tmp_path / "b")
    core2["actions"].append({"name": "teleport_everything", "input": [], "preconditions": [],
                             "state_change": [], "output": []})
    r2 = run_core_contract_gate(ws2, core2, runner2)
    assert not r2.ok and any("teleport_everything" in p for p in r2.problems)


# ---------------------------------------------------------------- Runner Gate (§16-25)

def test_runner_gate_pass(tmp_path):
    ws, _, runner, _ = build_mock_workspace(tmp_path)
    result, run = run_runner_gate(ws, runner, TIMEOUT, False, [])
    assert result.ok, result.problems
    assert run["parsed"]["ok"] is True
    assert not run["missing_fields"]


def test_runner_gate_fails_on_non_json_output(tmp_path):
    ws, _, runner, _ = build_mock_workspace(tmp_path, build=mock_runnerless_core_build_output())
    result, _ = run_runner_gate(ws, runner, TIMEOUT, False, [])
    assert not result.ok
    assert any("JSON" in p for p in result.problems)


# ---------------------------------------------------------------- Scenario Replay Gate (§16-26)

def test_scenario_replay_gate_pass_and_index(tmp_path):
    ws, _, runner, _ = build_mock_workspace(tmp_path)
    result, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    assert result.ok, result.problems
    assert set(outputs) == {"scenario_001", "scenario_002", "scenario_003"}
    index = json.loads((ws / "replay" / "index.json").read_text(encoding="utf-8"))
    assert len(index["replays"]) == 3
    assert (ws / "replay" / "replay_scenario_001.json").is_file()


def test_scenario_replay_gate_fails_without_fixtures(tmp_path):
    ws, _, runner, _ = build_mock_workspace(tmp_path)
    for p in (ws / "fixtures").glob("scenario_*.json"):
        p.unlink()
    result, _ = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    assert not result.ok


# ---------------------------------------------------------------- Golden Output Gate (§16-27, §16-14)

def test_golden_output_gate_pass_and_fail(tmp_path):
    ws, _, runner, sg = build_mock_workspace(tmp_path)
    _, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    result, summary = run_golden_output_gate(ws, sg["goldens"], outputs)
    assert result.ok, result.problems
    assert summary["exact_passed"] >= 1

    # tick 버그가 있는 빌드 → exact golden 불일치
    ws2, _, runner2, sg2 = build_mock_workspace(tmp_path / "b", build=mock_broken_core_build_output())
    _, outputs2 = run_scenario_replay_gate(ws2, runner2, TIMEOUT, False, [])
    result2, summary2 = run_golden_output_gate(ws2, sg2["goldens"], outputs2)
    assert not result2.ok
    assert "scenario_001" in summary2["failed_scenarios"]


def test_review_mode_not_counted_as_auto_pass(tmp_path):
    """§16-14: comparison_mode=review는 Golden Output Gate PASS 근거가 아니다."""
    ws, _, runner, sg = build_mock_workspace(tmp_path)
    _, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    review_goldens = [dict(g, comparison_mode="review") for g in sg["goldens"]]
    result, summary = run_golden_output_gate(ws, review_goldens, outputs)
    assert not result.ok  # 전부 review → 자동 gate 근거 없음
    assert summary["review_skipped"] == 3
    assert summary["passed"] == 0


def test_compare_golden_modes():
    parsed = {"final_state": {"a": 1, "b": {"c": 2}}, "events": [{"t": "x"}], "summary": "s",
              "errors": []}
    exact = {"comparison_mode": "exact", "expected_final_state": {"a": 1, "b": {"c": 2}},
             "expected_events": [{"t": "x"}], "expected_summary": "s"}
    assert compare_golden(exact, parsed)[0] == "PASS"
    partial = {"comparison_mode": "partial", "expected_final_state": {"b": {"c": 2}},
               "expected_events": [], "expected_summary": ""}
    assert compare_golden(partial, parsed)[0] == "PASS"
    invariant = {"comparison_mode": "invariant", "expected_final_state": {"a": 0, "b": {}}}
    assert compare_golden(invariant, parsed)[0] == "PASS"  # 키 존재만 검사
    review = {"comparison_mode": "review", "expected_final_state": {"zzz": 1}}
    assert compare_golden(review, parsed)[0] == "REVIEW"
    bad = {"comparison_mode": "exact", "expected_final_state": {"a": 999}}
    assert compare_golden(bad, parsed)[0] == "FAIL"


# ---------------------------------------------------------------- State Invariant Gate (§16-28)

def test_check_invariant_forms():
    state = {"tick": 3, "history": [], "nested": {"n": -1}}
    assert check_invariant(state, "tick >= 0")[0] is True
    assert check_invariant(state, "exists:history")[0] is True
    assert check_invariant(state, "nested.n >= 0")[0] is False
    assert check_invariant(state, "missing >= 0")[0] is False
    assert check_invariant(state, "자연어 불변조건")[0] is None  # 평가 불가 → note


def test_state_invariant_gate_pass_and_fail(tmp_path):
    ws, core, runner, _ = build_mock_workspace(tmp_path)
    _, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    result, summary = run_state_invariant_gate(core, outputs)
    assert result.ok, result.problems
    assert summary["checked"] > 0
    # 음수 불가 필드 위반을 흉내낸 replay 출력
    fake = {"s": {"parsed": {"final_state": {"history": [], "tick": -1, "history_count": 0}}}}
    result2, summary2 = run_state_invariant_gate(core, fake)
    assert not result2.ok
    assert summary2["violations"]


def test_state_invariant_singleton_entity_exposed():
    """entity 이름 키 singleton 중첩(final_state[name])도 invariant 평가 대상이다 (§9).

    golden expected_final_state와 같은 중첩 구조를 runner가 방출했는데
    NOT_EXPOSED로 오탐하면 patch lane이 불필요한 노이즈 수정을 유발한다."""
    core = {"state_entities": [
        {"name": "FileSystem", "fields": ["root_node", "version"],
         "invariants": ["version >= 0", "exists:root_node"]},
        {"name": "NavigationState", "fields": ["current_path", "selected_id"],
         "invariants": ["exists:current_path", "current_path.length >= 1"]},
    ]}
    ok_state = {"FileSystem": {"root_node": {"id": "root"}, "version": 0},
                "NavigationState": {"current_path": ["root"], "selected_id": None}}
    result, summary = run_state_invariant_gate(core, {"s1": {"parsed": {"final_state": ok_state}}})
    assert result.ok, result.problems
    assert summary["counts"]["not_exposed"] == 0

    # 값 위반은 NOT_EXPOSED가 아니라 FAIL로 구분된다
    bad = json.loads(json.dumps(ok_state))
    bad["FileSystem"]["version"] = -1
    result2, summary2 = run_state_invariant_gate(core, {"s1": {"parsed": {"final_state": bad}}})
    assert not result2.ok
    assert {v["category"] for v in summary2["violations"]} == {"INVARIANT_FAIL"}

    # 필드가 하나라도 없으면 singleton으로 해석하지 않는다 — 자동 PASS 금지
    missing = {"FileSystem": {"version": 0},
               "NavigationState": {"current_path": ["root"], "selected_id": None}}
    result3, summary3 = run_state_invariant_gate(core, {"s1": {"parsed": {"final_state": missing}}})
    assert not result3.ok
    fs_viol = [v for v in summary3["violations"]
               if v["invariant"] in ("version >= 0", "exists:root_node")]
    assert fs_viol
    assert all(v["category"] == "INVARIANT_NOT_EXPOSED" for v in fs_viol)


# ------------------------------------------------- Empty Collection Exposure (이슈 #16 §5~§8)

_ITEM_ENTITY = {"name": "Item", "fields": ["id"], "invariants": ["exists:id"]}


def _gate(final_state: dict, entity: dict = None):
    core = {"state_entities": [entity or _ITEM_ENTITY]}
    return run_state_invariant_gate(core, {"s1": {"parsed": {"final_state": final_state}}})


def test_exposure_contract_states():
    """NOT_EXPOSED / EXPOSED_EMPTY / EXPOSED_NONEMPTY / WRONG_TYPE / AMBIGUOUS 분리 (INV-1~6)."""
    e = _ITEM_ENTITY
    assert _entity_collection_exposure(e, {})["status"] == "NOT_EXPOSED"
    empty = _entity_collection_exposure(e, {"items": []})
    assert empty["status"] == "EXPOSED_EMPTY"
    assert empty["resolved_path"] == "items"
    assert empty["collection_type"] == "list"
    nonempty = _entity_collection_exposure(e, {"items": [{"id": "a"}]})
    assert nonempty["status"] == "EXPOSED_NONEMPTY"
    assert len(nonempty["instances"]) == 1
    # 빈 dict는 collection으로 자동 승격 금지 → WRONG_TYPE
    assert _entity_collection_exposure(e, {"items": {}})["status"] == "EXPOSED_WRONG_TYPE"
    # 복수 후보 경로 → 병합·임의 선택 금지, fail-closed
    amb = _entity_collection_exposure(e, {"items": [], "group": {"items": []}})
    assert amb["status"] == "AMBIGUOUS_EXPOSURE"
    assert amb["resolved_path"] == ["group.items", "items"]


def test_exposure_singular_plural_case_nested():
    """Task↔tasks 단수/복수·대소문자 정규화, dict/list 중첩 경로 발견 (§6)."""
    task = {"name": "Task", "fields": ["id", "parent_plan_id"], "invariants": []}
    assert _entity_collection_exposure(task, {"tasks": []})["status"] == "EXPOSED_EMPTY"
    assert _entity_collection_exposure(task, {"Tasks": []})["status"] == "EXPOSED_EMPTY"
    nested = _entity_collection_exposure(task, {"pipeline": {"tasks": []}})
    assert nested["status"] == "EXPOSED_EMPTY"
    assert nested["resolved_path"] == "pipeline.tasks"
    in_list = _entity_collection_exposure(task, {"pipelines": [{"tasks": []}]})
    assert in_list["status"] == "EXPOSED_EMPTY"
    assert in_list["resolved_path"] == "pipelines[0].tasks"


def test_universal_field_invariant_predicate():
    """vacuous 대상은 entity 선언 필드 술어만 — collection 경로 참조는 제외 (§7)."""
    task = {"name": "Task", "fields": ["id", "parent_plan_id"], "invariants": []}
    assert _is_universal_field_invariant(task, "exists:parent_plan_id")
    assert _is_universal_field_invariant(task, "id >= 0")
    assert not _is_universal_field_invariant(task, "tasks.length >= 1")  # cardinality 의미
    assert not _is_universal_field_invariant(task, "exists:tasks")
    assert not _is_universal_field_invariant(task, "자연어 불변조건")


def test_state_invariant_vacuous_pass_empty_collection():
    """EXPOSED_EMPTY + universal field invariant → VACUOUS_PASS, evidence 포함 (§7·§9)."""
    result, summary = _gate({"items": []})
    assert result.ok, result.problems
    assert summary["counts"]["vacuous_pass"] == 1
    v = summary["vacuous_passes"][0]
    assert v["exposure_status"] == "EXPOSED_EMPTY"
    assert v["reason_code"] == "VACUOUS_PASS_EMPTY_COLLECTION"
    assert v["evaluated_instance_count"] == 0
    assert v["violating_instance_count"] == 0
    # 중첩 empty collection도 동일
    result2, summary2 = _gate({"group": {"items": []}})
    assert result2.ok, result2.problems
    assert summary2["counts"]["vacuous_pass"] == 1
    assert summary2["vacuous_passes"][0]["resolved_path"] == "group.items"


def test_state_invariant_no_vacuous_for_missing_wrong_type_ambiguous():
    """missing collection·wrong type·ambiguous는 vacuous PASS 금지 — 기존 실패 유지 (§7.3)."""
    for state in ({}, {"items": {}}, {"items": [], "group": {"items": []}}):
        result, summary = _gate(state)
        assert not result.ok, state
        assert summary["counts"]["vacuous_pass"] == 0
        assert summary["counts"]["not_exposed"] == 1


def test_state_invariant_cardinality_independent_of_vacuous():
    """minimum-existence(length) 요구는 빈 collection에서 계속 FAIL — vacuous 우회 금지 (§8)."""
    entity = {"name": "Item", "fields": ["id"],
              "invariants": ["exists:id", "items.length >= 1"]}
    result, summary = _gate({"items": []}, entity)
    assert not result.ok
    # exists:id는 vacuous PASS, items.length >= 1은 INVARIANT_FAIL로 남는다
    assert summary["counts"]["vacuous_pass"] == 1
    assert [v["category"] for v in summary["violations"]] == ["INVARIANT_FAIL"]
    # 채워지면 둘 다 PASS
    result2, summary2 = _gate({"items": [{"id": "a"}]}, entity)
    assert result2.ok, result2.problems
    assert summary2["counts"]["vacuous_pass"] == 0


def test_state_invariant_nonempty_semantics_unchanged():
    """non-empty 평가 의미 회귀 — valid/invalid instance 판정 유지 (§12)."""
    valid, s_valid = _gate({"items": [{"id": "a"}, {"id": "b"}]})
    assert valid.ok, valid.problems
    assert s_valid["counts"]["vacuous_pass"] == 0
    invalid, s_invalid = _gate({"items": [{"id": "a"}, {}]})
    assert not invalid.ok
    assert s_invalid["counts"]["vacuous_pass"] == 0


# ---------------------------------------------------------------- Determinism Gate (§16-29)

def test_determinism_gate_pass(tmp_path):
    ws, core, runner, _ = build_mock_workspace(tmp_path)
    _, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    result, summary = run_determinism_gate(ws, core, runner, outputs, TIMEOUT, False, [])
    assert result.ok, result.problems
    assert summary["reran"] == 3
    assert summary["rerun_order"] == "reversed"  # fixture 순서 변경 검사 겸용


def test_determinism_gate_detects_random(tmp_path):
    ws, core, runner, _ = build_mock_workspace(tmp_path)
    (ws / "src" / "shaky.js").write_text("export const roll = () => Math.random();", encoding="utf-8")
    result, summary = run_determinism_gate(ws, core, runner, {}, TIMEOUT, False, [])
    assert not result.ok
    assert any("Math.random" in p for p in summary["static_problems"])


# ---------------------------------------------------------------- Anti-Hardcode Gate (§16-30, §16-31)

def test_anti_hardcode_level1_detects_fixture_branching(tmp_path):
    ws, _, runner, sg = build_mock_workspace(tmp_path)
    (ws / "src" / "cheat.py").write_text(
        '# cheat\ndef pick(sid):\n    if sid == "scenario_001":\n        return 1\n', encoding="utf-8")
    result, summary = run_anti_hardcode_gate(ws, sg["goldens"], runner, {}, TIMEOUT, False, [],
                                             run_level2=False)
    assert not result.ok
    assert summary["hardcode_risk"] == "high"
    assert any("fixture id" in p for p in summary["level1_problems"])


def test_anti_hardcode_level1_detects_golden_string(tmp_path):
    ws, _, runner, sg = build_mock_workspace(tmp_path)
    (ws / "src" / "canned.py").write_text(
        'CANNED = "2 cards, 0 rejected"\n', encoding="utf-8")
    result, summary = run_anti_hardcode_gate(ws, sg["goldens"], runner, {}, TIMEOUT, False, [],
                                             run_level2=False)
    assert not result.ok
    assert any("expected_summary" in p for p in summary["level1_problems"])


def test_anti_hardcode_level2_variant_run(tmp_path):
    """§16-31: id/title 변형 fixture 실행 — 정직한 runner는 통과."""
    ws, _, runner, sg = build_mock_workspace(tmp_path)
    _, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    result, summary = run_anti_hardcode_gate(ws, sg["goldens"], runner, outputs, TIMEOUT, False, [])
    assert result.ok, result.problems
    assert summary["level2_ran"] is True
    assert summary["hardcode_risk"] == "low"


def test_anti_hardcode_level2_catches_id_dependent_output(tmp_path):
    """scenario id에 따라 출력이 달라지는 runner를 잡는다."""
    build = mock_core_build_output()
    for f in build["files"]:
        if f["path"] == "src/runner.py":
            f["content"] = f["content"].replace(
                'result = run_scenario(scenario)',
                'result = run_scenario(scenario)\n'
                '    result["final_state"]["fixture_tag"] = scenario.get("id")',
            )
    ws, _, runner, sg = build_mock_workspace(tmp_path, build=build)
    _, outputs = run_scenario_replay_gate(ws, runner, TIMEOUT, False, [])
    result, summary = run_anti_hardcode_gate(ws, sg["goldens"], runner, outputs, TIMEOUT, False, [])
    assert not result.ok
    assert summary["level2_problems"]
    assert summary["hardcode_risk"] == "high"


def test_todo_marks_medium_risk(tmp_path):
    ws, _, runner, sg = build_mock_workspace(tmp_path)
    (ws / "src" / "wip.py").write_text("# TODO: implement later\n", encoding="utf-8")
    result, summary = run_anti_hardcode_gate(ws, sg["goldens"], runner, {}, TIMEOUT, False, [],
                                             run_level2=False)
    assert result.ok  # TODO만으로 gate FAIL은 아님
    assert summary["hardcode_risk"] == "medium"


# ---------------------------------------------------------------- 전체 gate 체인 (§16-23)

def test_run_core_gates_all_pass_with_runner(tmp_path):
    """§16-23: Core Build 결과에 runner가 존재하고 전 gate 통과."""
    ws, core, runner, sg = build_mock_workspace(tmp_path)
    gates = run_core_gates(ws, core, runner, sg["goldens"], timeout_seconds=TIMEOUT,
                           use_docker=False, secrets=[])
    assert all(gates["summary"].values()), gates["problems"]
    assert (ws / "replay" / "index.json").is_file()
    for name in ("runner_summary", "scenario_replay_summary", "golden_diff_summary",
                 "state_invariant_summary", "determinism_summary", "anti_hardcode_summary"):
        assert name in gates["artifacts"]
