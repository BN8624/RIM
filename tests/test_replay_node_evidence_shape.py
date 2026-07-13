# 이슈 #19: replay node collection shape-safe evidence 계약 — dict/list/empty/missing/malformed 분리, crash 0, silent PASS 0.
import pytest

from repo_idea_miner.factory_product_evidence import (
    NODE_COLLECTION_EMPTY,
    NODE_COLLECTION_MALFORMED,
    NODE_COLLECTION_MISSING,
    NODE_LIST,
    NODE_MAP,
    classify_node_collection,
    viewer_field_mismatches,
    viewer_reads_replay_evidence,
)
from repo_idea_miner.factory_review import _consistency_fields

_VIEWER = "fetch('replay/index.json'); node.status"

_DICT_NODES = {"a": {"id": "a", "status": "ready"}, "b": {"id": "b", "status": "locked"}}
_LIST_NODES = [{"id": "a", "status": "ready"}, {"id": "b", "status": "locked"}]


def _replay(nodes=..., final_state=...):
    if final_state is not ...:
        return {"final_state": final_state}
    fs = {} if nodes is ... else {"nodes": nodes}
    return {"final_state": fs}


# ---------------------------------------------------------------- §19.1 shape classification

def test_dict_nodes_is_node_map():
    info = classify_node_collection({"nodes": _DICT_NODES})
    assert info["shape"] == NODE_MAP
    assert len(info["nodes"]) == 2
    assert info["identities"] == ["a", "b"]
    assert info["malformed_entries"] == 0


def test_list_nodes_is_node_list():
    info = classify_node_collection({"nodes": _LIST_NODES})
    assert info["shape"] == NODE_LIST
    assert len(info["nodes"]) == 2
    assert info["identities"] == ["0", "1"]
    assert info["malformed_entries"] == 0


@pytest.mark.parametrize("empty", [{}, []])
def test_empty_collection_is_empty_not_missing(empty):
    info = classify_node_collection({"nodes": empty})
    assert info["shape"] == NODE_COLLECTION_EMPTY
    assert info["nodes"] == []
    assert info["malformed_entries"] == 0


def test_missing_nodes_is_missing_not_empty():
    assert classify_node_collection({})["shape"] == NODE_COLLECTION_MISSING
    assert classify_node_collection({"items": [1]})["shape"] == NODE_COLLECTION_MISSING


@pytest.mark.parametrize("bad", ["broken", 123, True, None])
def test_scalar_or_null_nodes_is_malformed(bad):
    info = classify_node_collection({"nodes": bad})
    assert info["shape"] == NODE_COLLECTION_MALFORMED
    assert info["nodes"] == []
    assert info["malformed_entries"] == 1


def test_non_dict_final_state_is_missing_without_crash():
    for fs in (None, [1, 2], "x", 7):
        assert classify_node_collection(fs)["shape"] == NODE_COLLECTION_MISSING


def test_classification_is_deterministic():
    fs = {"nodes": {"b": {"id": "b"}, "a": {"id": "a"}}}
    assert classify_node_collection(fs) == classify_node_collection(fs)
    # 입력 순서 보존 (dict insertion order / list order)
    assert classify_node_collection(fs)["identities"] == ["b", "a"]


# ---------------------------------------------------------------- §19.2 node extraction

def test_mixed_list_counts_valid_and_malformed():
    info = classify_node_collection({"nodes": [{"id": "a", "status": "ready"}, "broken", 3]})
    assert info["shape"] == NODE_LIST
    assert len(info["nodes"]) == 1
    assert info["malformed_entries"] == 2
    assert info["identities"] == ["0"]  # index fallback은 valid 원소만


def test_mixed_map_counts_valid_and_malformed():
    info = classify_node_collection({"nodes": {"a": {"status": "ready"}, "b": "broken"}})
    assert info["shape"] == NODE_MAP
    assert len(info["nodes"]) == 1
    assert info["malformed_entries"] == 1
    assert info["identities"] == ["a"]


def test_status_extraction_parity_dict_vs_list():
    ev_d = viewer_reads_replay_evidence(_VIEWER, _replay(nodes=_DICT_NODES))
    ev_l = viewer_reads_replay_evidence(_VIEWER, _replay(nodes=_LIST_NODES))
    assert ev_d == ev_l
    assert any("status(locked,ready)" in e for e in ev_d)


def test_missing_status_does_not_crash_and_is_not_vacuous_evidence():
    # crash 0 — status 없는 canonical node 허용, 단 빈 status는 positive evidence가 아니다 (INV-7)
    ev = viewer_reads_replay_evidence(_VIEWER, _replay(nodes=[{"id": "a"}]))
    assert not any("node.status" in e for e in ev)
    # 대신 viewer가 node.status를 읽는데 값이 전무하면 렌더링 결함으로 명시된다
    mm = viewer_field_mismatches(_replay(nodes=[{"id": "a", "state": "visited"}]), _VIEWER)
    assert any("node.status" in m and "미렌더링" in m for m in mm)
    # status가 실제로 있으면 mismatch 아님
    assert viewer_field_mismatches(_replay(nodes=_LIST_NODES), _VIEWER) == []


# ---------------------------------------------------------------- §19.3 applicability

def test_non_graph_replay_not_forced():
    # 비graph 제품: nodes 키 부재 + viewer도 node.status 안 읽음 → evidence/problem 0
    rep = _replay(final_state={"items": [{"name": "x"}]})
    assert viewer_reads_replay_evidence("data.items", rep) == []
    assert viewer_field_mismatches(rep, "data.items") == []


def test_viewer_without_node_status_gets_no_node_evidence():
    ev = viewer_reads_replay_evidence("no node refs", _replay(nodes=_DICT_NODES))
    assert not any("node.status" in e for e in ev)


# ---------------------------------------------------------------- §19.4 fail-closed

@pytest.mark.parametrize("bad", ["broken", 123, True, None])
def test_malformed_collection_is_explicit_problem_not_silent(bad):
    mm = viewer_field_mismatches(_replay(nodes=bad), _VIEWER)
    assert any("fail-closed" in m for m in mm)
    # evidence 쪽은 조용히 PASS하지 않는다 — node evidence 0
    ev = viewer_reads_replay_evidence(_VIEWER, _replay(nodes=bad))
    assert not any("node.status" in e for e in ev)


def test_malformed_entries_recorded_as_problem():
    mm = viewer_field_mismatches(_replay(nodes=[{"id": "a"}, "broken", 3]), _VIEWER)
    assert any("2개" in m and "malformed" in m for m in mm)


def test_empty_collection_is_not_a_problem_and_not_evidence():
    for empty in ({}, []):
        rep = _replay(nodes=empty)
        assert viewer_field_mismatches(rep, _VIEWER) == []
        assert not any("node.status" in e for e in viewer_reads_replay_evidence(_VIEWER, rep))


def test_no_exception_on_any_shape():
    shapes = [None, "x", 5, [], {}, {"final_state": None}, {"final_state": [1]},
              {"final_state": {"nodes": object()}},
              {"final_state": {"nodes": [object(), {"id": "a"}]}},
              {"final_state": {"edges": {"e": 1}, "nodes": _LIST_NODES}},
              {"final_state": {"nodes": _DICT_NODES}, "events": "bad"}]
    for rep in shapes:
        viewer_reads_replay_evidence(_VIEWER + " edge.from ev.type node.x", rep if isinstance(rep, dict) else None)
        viewer_field_mismatches(rep if isinstance(rep, dict) else None, _VIEWER + " edge.from ev.type node.x")


def test_non_dict_final_state_is_fail_closed_problem():
    mm = viewer_field_mismatches({"final_state": [1, 2]}, _VIEWER)
    assert any("object가 아님" in m for m in mm)


# ---------------------------------------------------------------- §19.5 adjacent evaluator parity

def test_consistency_fields_dict_list_parity():
    viewer = "node.status; final_state.nodes"
    rep_d = _replay(nodes=_DICT_NODES)
    rep_l = _replay(nodes=_LIST_NODES)
    f_d = _consistency_fields(rep_d, rep_d, viewer)
    f_l = _consistency_fields(rep_l, rep_l, viewer)
    assert "final_state.nodes[].status" in f_d
    assert "final_state.nodes[].status" in f_l
    assert f_d == f_l


def test_consistency_fields_all_none_status_is_vacuous():
    # status 값이 전무한 일치(None==None)는 consistency 근거가 아니다 (INV-7)
    rep = _replay(nodes=[{"id": "a", "state": "visited"}])
    fields = _consistency_fields(rep, rep, "node.status; final_state.nodes")
    assert "final_state.nodes[].status" not in fields


def test_consistency_fields_no_crash_on_malformed():
    for bad in ("broken", 123, None, [{"id": "a"}, "x"]):
        rep = _replay(nodes=bad)
        assert isinstance(_consistency_fields(rep, rep, "node.status"), list)


def test_mismatches_list_nodes_xy_check_applies():
    # 인접 drift 수리: list nodes에도 node.x/y mismatch 검사가 dict와 동일하게 적용된다
    rep = _replay(nodes=[{"id": "a", "status": "ready"}])  # x/y 없음
    mm = viewer_field_mismatches(rep, "node.x node.y")
    assert any("node.x/node.y" in m for m in mm)
    rep_ok = _replay(nodes=[{"id": "a", "x": 1, "y": 2}])
    assert viewer_field_mismatches(rep_ok, "node.x node.y") == []
