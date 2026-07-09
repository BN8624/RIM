# Product Result Dashboard(Phase 1.5) 테스트: 검수 대기함/상세/필터/review 저장/보안/불완전 run (§33).
import threading
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace

import pytest

from repo_idea_miner.challenge_dashboard import make_dashboard_server
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_db import (
    create_product_run,
    open_factory_db,
    update_product_run,
)
from repo_idea_miner.factory_pipeline import (
    FactorySettings,
    run_product_factory,
    sample_challenge,
)
from repo_idea_miner.factory_prompts import mock_factory_overrides
from repo_idea_miner.llm_client import MockLLMClient

SECRET = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _get(base, path, expect=200):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as resp:
            assert resp.status == expect, (path, resp.status)
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if expect != 200:
            assert exc.code == expect, (path, exc.code)
            return ""
        raise


def _post(base, path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(base + path, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "challenge.db"
    conn = open_factory_db(db_path)
    result = run_product_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=Settings(google_keys={}),
        factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert result["ok"], result["error"]
    # status=error / verdict=null / challenge_id 없음 run (§4·§31)
    err_id = create_product_run(conn, None, str(tmp_path / "noexist" / "workspace"), "standard")
    update_product_run(conn, err_id, status="error", current_stage="smoke_gate")
    # 삭제된 challenge를 가리키는 run (§12·§31)
    ghost_id = create_product_run(conn, 99999, str(tmp_path / "gone" / "workspace"), "standard")
    update_product_run(conn, ghost_id, status="error")
    conn.close()

    server = make_dashboard_server(db_path, host="127.0.0.1", port=0, secrets=[SECRET])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield SimpleNamespace(
        base=base, db_path=db_path, result=result,
        run_id=result["product_run_id"], err_id=err_id, ghost_id=ghost_id, tmp_path=tmp_path,
    )
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------- 목록 / 분리 표시

def test_products_index_is_review_queue(env):
    body = _get(env.base, "/products")
    assert "Product Runs" in body
    assert "Challenge Inbox" in body  # 상단 nav (§7)
    assert "Codex 승격 후보" in body  # verdict 배지 (§8)
    assert "미검수" in body  # review 상태 (§27)
    assert f"/product/{env.run_id}" in body


def test_status_verdict_review_separated(env):
    body = _get(env.base, "/products")
    # ERROR는 verdict가 아니라 status로 표시 (§4)
    assert "ERROR" in body
    assert f"/product/{env.err_id}" in body


# ---------------------------------------------------------------- 필터 (§11)

def test_verdict_filter(env):
    body = _get(env.base, "/products?verdict=PROMOTE_TO_CODEX")
    assert f"/product/{env.run_id}" in body
    assert f"/product/{env.err_id}" not in body


def test_status_error_filter(env):
    body = _get(env.base, "/products?status=error")
    assert f"/product/{env.err_id}" in body
    assert f'href="/product/{env.run_id}"' not in body


def test_review_filters(env):
    _post(env.base, f"/product/{env.run_id}/decision", {"decision": "keep"})
    reviewed = _get(env.base, "/products?review=reviewed")
    assert f"/product/{env.run_id}" in reviewed
    unreviewed = _get(env.base, "/products?review=unreviewed")
    assert f'href="/product/{env.run_id}"' not in unreviewed
    assert f"/product/{env.err_id}" in unreviewed
    keep = _get(env.base, "/products?review=keep")
    assert f"/product/{env.run_id}" in keep


def test_review_retry_and_productize_filters(env):
    _post(env.base, f"/product/{env.run_id}/decision", {"decision": "retry"})
    assert f"/product/{env.run_id}" in _get(env.base, "/products?review=RETRY")
    _post(env.base, f"/product/{env.err_id}/decision", {"decision": "productize"})
    assert f"/product/{env.err_id}" in _get(env.base, "/products?review=PRODUCTIZE")


# ---------------------------------------------------------------- 상세 화면 (§13~§24)

def test_detail_sections_present(env):
    body = _get(env.base, f"/product/{env.run_id}")
    for header in (
        "원본 Challenge 요약", "Gate Summary", "QA Summary",
        "Known Issues / Next Goal", "Smoke Output Preview", "Artifact Paths",
        "Final Artifact File Tree", "허용된 Source Preview", "Report Preview",
    ):
        assert header in body, header
    assert "PRODUCTIZE (추천)" in body  # PROMOTE_TO_CODEX → productize 강조 (§25)
    for label in ("KEEP", "DROP", "RETRY", "ARCHIVE"):
        assert label in body


def test_challenge_summary_and_link(env):
    body = _get(env.base, f"/product/{env.run_id}")
    # sample run은 challenge_id 없음 → 안내 표시하되 anchors는 product_summary에서 (§12·§15)
    assert "원본 Challenge 정보 없음" in body
    assert "Difficulty Anchors" in body


def test_error_run_detail_not_500(env):
    body = _get(env.base, f"/product/{env.err_id}")
    assert "run #" in body
    assert "(final_artifact 없음)" in body  # missing final artifact여도 안전 (§31)


def test_deleted_challenge_run_detail(env):
    body = _get(env.base, f"/product/{env.ghost_id}")
    assert "원본 Challenge 정보 없음" in body


def test_invalid_run_id(env):
    _get(env.base, "/product/999999", expect=404)
    _get(env.base, "/product/abc", expect=404)


# ---------------------------------------------------------------- Gate / QA summary 우선순위 + fallback

def test_gate_summary_json_priority(env):
    body = _get(env.base, f"/product/{env.run_id}")
    assert "gp-PASS" in body  # gate_summary.json 기반 PASS pill (§16)


def test_gate_summary_fallback_when_json_missing(env):
    run_dir = env.tmp_path / "runs"
    for p in list(run_dir.rglob("gate_summary.json")):
        p.unlink()
    body = _get(env.base, f"/product/{env.run_id}")
    assert "Gate Summary" in body
    assert "gp-PASS" in body  # reports/*.md fallback로도 PASS 추정 (§16)


def test_qa_summary_fallback_when_json_missing(env):
    run_dir = env.tmp_path / "runs"
    for p in list(run_dir.rglob("qa_summary.json")):
        p.unlink()
    body = _get(env.base, f"/product/{env.run_id}")
    assert "QA Summary" in body


# ---------------------------------------------------------------- 보안 (§30)

def test_source_preview_whitelist_and_traversal(env):
    ok = _get(env.base, f"/product/{env.run_id}?src=README.md")
    assert "허용되지 않은 경로" not in ok
    for bad in ("../../../etc/passwd", "/etc/passwd", "events.jsonl"):
        blocked = _get(env.base, f"/product/{env.run_id}?src={urllib.parse.quote(bad)}")
        assert "허용되지 않은 경로" in blocked
        assert "root:" not in blocked


def test_report_tab_whitelist_and_default(env):
    qa = _get(env.base, f"/product/{env.run_id}?tab=qa_report")
    assert "QA Report" in qa
    events = _get(env.base, f"/product/{env.run_id}?tab=events")
    assert "events.jsonl" in events
    bogus = _get(env.base, f"/product/{env.run_id}?tab=__nope__")
    assert "Product Verdict" in bogus or "최종 판정" in bogus  # 기본 탭으로 안전 폴백


def test_html_escaped_secret_masked_truncated(env):
    final_dir = env.tmp_path / "runs"
    reports = list(final_dir.rglob("final_artifact/reports/qa_report.md"))
    assert reports, "final_artifact qa_report.md가 있어야 함"
    payload = "<script>alert(1)</script>\n" + SECRET + "\n" + ("x" * 80000)
    reports[0].write_text(payload, encoding="utf-8")
    body = _get(env.base, f"/product/{env.run_id}?tab=qa_report")
    assert "&lt;script&gt;" in body  # HTML escape (§30)
    assert "<script>alert(1)</script>" not in body
    assert "[REDACTED]" in body  # secret 마스킹
    assert SECRET not in body
    assert "길이 제한으로 잘림" in body  # large file truncate (§30)


# ---------------------------------------------------------------- review 저장 (§26)

def test_review_append_only_and_latest(env):
    _post(env.base, f"/product/{env.run_id}/decision", {"decision": "keep"})
    _post(env.base, f"/product/{env.run_id}/decision", {"decision": "retry"})
    conn = open_factory_db(env.db_path)
    try:
        rows = conn.execute(
            "SELECT action FROM product_reviews WHERE product_run_id=? ORDER BY id", (env.run_id,)
        ).fetchall()
        assert [r["action"] for r in rows] == ["keep", "retry"]  # append-only
        run = conn.execute("SELECT owner_decision FROM product_runs WHERE id=?", (env.run_id,)).fetchone()
        assert run["owner_decision"] == "retry"  # 최신 review 반영
    finally:
        conn.close()
    # 목록에는 최신 review만 (§27)
    body = _get(env.base, "/products")
    assert "RETRY" in body


def test_retry_saves_selected_next_goal(env):
    _post(env.base, f"/product/{env.run_id}/decision",
          {"decision": "retry", "selected_next_goal": "scrubber jump 구현"})
    conn = open_factory_db(env.db_path)
    try:
        row = conn.execute(
            "SELECT selected_next_goal FROM product_reviews WHERE product_run_id=? ORDER BY id DESC LIMIT 1",
            (env.run_id,),
        ).fetchone()
        assert row["selected_next_goal"] == "scrubber jump 구현"
    finally:
        conn.close()


def test_invalid_decision_rejected(env):
    body = urllib.parse.urlencode({"decision": "yolo"}).encode()
    req = urllib.request.Request(env.base + f"/product/{env.run_id}/decision", data=body, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("400이어야 함")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
