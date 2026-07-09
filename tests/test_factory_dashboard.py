# Dashboard의 Product Factory 화면: 목록/상세 verdict 표시·버튼 매핑·owner decision POST 테스트.
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from repo_idea_miner.challenge_dashboard import make_dashboard_server
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_db import get_product_run, open_factory_db
from repo_idea_miner.factory_pipeline import FactorySettings, run_product_factory, sample_challenge
from repo_idea_miner.factory_prompts import mock_factory_overrides
from repo_idea_miner.factory_schemas import VERDICT_TO_RECOMMENDED_ACTION
from repo_idea_miner.llm_client import MockLLMClient


@pytest.fixture
def dashboard(tmp_path):
    db_path = tmp_path / "challenge.db"
    conn = open_factory_db(db_path)
    result = run_product_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=Settings(google_keys={}),
        factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert result["ok"], result["error"]
    conn.close()

    server = make_dashboard_server(db_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, db_path, result
    server.shutdown()
    server.server_close()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


def test_products_index_shows_verdict(dashboard):
    """Dashboard에서 Product Verdict 표시 (§22-33)."""
    base, _, result = dashboard
    body = _get(base + "/products")
    assert "Product Runs" in body
    assert "제품화 후보" in body  # PROMOTE_TO_CODEX verdict 배지 한국어 라벨
    assert f"/product/{result['product_run_id']}" in body


def test_product_detail_shows_recommended_button(dashboard):
    """Dashboard 버튼과 Product Verdict 매핑 (§22-34, §15)."""
    base, _, result = dashboard
    body = _get(base + f"/product/{result['product_run_id']}")
    assert "제품화 (추천)" in body  # PROMOTE_TO_CODEX → 제품화 추천 (한국어 버튼)
    for label in ("보관", "버림", "다시 돌리기", "보류"):
        assert label in body
    assert "최종 판정" in body  # product_verdict.md 원문 (접힘 영역)
    assert "PROMOTE_TO_CODEX" in body  # 원본 상태값 보기 + 원문
    assert VERDICT_TO_RECOMMENDED_ACTION["PROMOTE_TO_CODEX"] == "productize"


def test_product_detail_report_tabs(dashboard):
    base, _, result = dashboard
    run_id = result["product_run_id"]
    qa = _get(base + f"/product/{run_id}?tab=qa_report")
    assert "QA Report" in qa
    smoke = _get(base + f"/product/{run_id}?tab=smoke_report")
    assert "Smoke Gate" in smoke


def test_owner_decision_post(dashboard):
    base, db_path, result = dashboard
    run_id = result["product_run_id"]
    data = urllib.parse.urlencode({"decision": "keep"}).encode()
    req = urllib.request.Request(base + f"/product/{run_id}/decision", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200  # redirect 후 상세 페이지
    conn = open_factory_db(db_path)
    try:
        assert get_product_run(conn, run_id)["owner_decision"] == "keep"
        n = conn.execute(
            "SELECT COUNT(*) FROM product_events WHERE event_type='owner_decision'"
        ).fetchone()[0]
        assert n == 1
    finally:
        conn.close()


def test_invalid_decision_rejected(dashboard):
    base, _, result = dashboard
    data = urllib.parse.urlencode({"decision": "yolo"}).encode()
    req = urllib.request.Request(
        base + f"/product/{result['product_run_id']}/decision", data=data, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("400이어야 함")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
