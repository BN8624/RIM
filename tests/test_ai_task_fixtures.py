# 대표 AI 작업 fixture 검증 — Context Pack recall 100% / primary≤5 / forbidden 0 / byte-identical (§20).
import json
from pathlib import Path

import pytest

from repo_idea_miner.architecture_context import build_context

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ai_tasks"
FIXTURES = sorted(FIXTURE_DIR.glob("task*.json")) + sorted(FIXTURE_DIR.glob("blind_*.json"))


def test_thirteen_representative_tasks_exist():
    # 대표 task 8종 + A7 blind 검증 ground truth 승격 5종
    assert len(FIXTURES) == 13


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_ai_task_recall(path):
    fx = json.loads(path.read_text(encoding="utf-8"))
    ctx = build_context(REPO_ROOT, fx["query"])

    primary = [e["path"] for e in ctx["read_first"]]
    assert len(primary) <= 5, primary

    # 필수 recall 100% (§20 완료 조건)
    missing_files = set(fx["required_primary_files"]) - set(primary)
    assert not missing_files, f"primary 누락: {sorted(missing_files)} (있는 것: {primary})"
    missing_canon = set(fx["required_canon_ids"]) - set(ctx["canon_ids"])
    assert not missing_canon, f"CANON 누락: {sorted(missing_canon)}"
    got_symbols = {s["symbol_id"] for e in ctx["read_first"] for s in e["symbols"]}
    missing_syms = set(fx["required_symbols"]) - got_symbols
    assert not missing_syms, f"symbol 누락: {sorted(missing_syms)}"
    got_inv = {i["invariant_id"] for i in ctx["invariants"]}
    assert not set(fx["required_invariants"]) - got_inv
    assert not set(fx["required_tests"]) - set(ctx["tests_to_run"])
    got_contracts = {c["contract_id"] for c in ctx["contracts"]}
    assert not set(fx.get("required_contracts", [])) - got_contracts

    # forbidden file이 primary로 추천되면 실패
    assert not set(fx["forbidden_files"]) & set(primary)

    # 동일 query byte-identical
    again = build_context(REPO_ROOT, fx["query"])
    assert json.dumps(ctx, sort_keys=True) == json.dumps(again, sort_keys=True)
