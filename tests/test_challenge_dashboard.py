# Challenge Dashboard HTTP 테스트: 목록/상세/판정 POST를 로컬 서버로 검증.
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from repo_idea_miner.challenge_dashboard import make_dashboard_server
from repo_idea_miner.challenge_db import open_db, save_challenge
from repo_idea_miner.challenge_pipeline import run_challenge
from repo_idea_miner.challenge_prompts import mock_challenge_package
from repo_idea_miner.config import Settings
from tests.test_pipeline_mock import FakeGitHub


@pytest.fixture
def dashboard(tmp_path):
    db_path = tmp_path / "challenge.db"
    conn = open_db(db_path)
    # 실제 artifact를 가진 challenge 1건 생성
    result = run_challenge(
        "https://github.com/owner/repo",
        mode="mock",
        output_dir=tmp_path / "runs",
        settings=Settings(google_keys={}),
        gh=FakeGitHub(),
        db_conn=conn,
    )
    assert result["ok"]
    # artifact 없는 challenge 1건 (목록만)
    save_challenge(conn, mock_challenge_package("x/y"), "https://github.com/x/y", str(tmp_path))
    conn.close()

    server = make_dashboard_server(db_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, db_path, result["challenge_id"]
    server.shutdown()
    server.server_close()


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


def test_index_lists_challenges(dashboard):
    base, _, _ = dashboard
    body = _get(base + "/")
    assert "RIM Challenge Dashboard" in body
    assert "GOOD_CHALLENGE" in body
    assert "owner/repo" in body
    assert "오늘 생성" in body


def test_index_filters(dashboard):
    base, _, _ = dashboard
    body = _get(base + "/?final_label=GOOD_CHALLENGE&owner_status=unseen")
    assert "owner/repo" in body
    body = _get(base + "/?final_label=TOO_EASY")
    assert "표시할 challenge가 없습니다" in body


def test_detail_tabs(dashboard):
    base, _, cid = dashboard
    body = _get(f"{base}/challenge/{cid}?tab=implementation_prompt")
    assert "Implementation Prompt" in body
    assert "Forbidden Simplifications" in body
    body = _get(f"{base}/challenge/{cid}?tab=owner_brief")
    assert "쉽게 말해" in body
    assert "COPY IMPLEMENTATION PROMPT" in body


def test_review_post_updates_owner_status(dashboard):
    base, db_path, cid = dashboard
    data = urllib.parse.urlencode({"owner_status": "build_next", "note": "이거 먼저"}).encode()
    req = urllib.request.Request(f"{base}/challenge/{cid}/review", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200  # 303 redirect 후 상세 페이지
    conn = open_db(db_path)
    try:
        row = conn.execute(
            "SELECT owner_status, note FROM owner_reviews WHERE challenge_id=?", (cid,)
        ).fetchone()
        assert row["owner_status"] == "build_next"
        assert row["note"] == "이거 먼저"
    finally:
        conn.close()


def test_review_post_rejects_invalid_status(dashboard):
    base, _, cid = dashboard
    data = urllib.parse.urlencode({"owner_status": "hacked"}).encode()
    req = urllib.request.Request(f"{base}/challenge/{cid}/review", data=data, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("400이어야 함")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_unknown_paths_404(dashboard):
    base, _, _ = dashboard
    for path in ("/etc/passwd", "/challenge/999999", "/../.env"):
        try:
            urllib.request.urlopen(base + path, timeout=10)
            raise AssertionError("404여야 함")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
