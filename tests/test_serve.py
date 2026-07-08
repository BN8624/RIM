# 읽기 전용 서버의 root 제한·traversal·secret 파일 차단 테스트.
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

from repo_idea_miner.serve import _is_denied, make_server


@contextmanager
def running_server(run_dir, port=8799):
    srv = make_server(run_dir, "127.0.0.1", port)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _status(url, method="GET"):
    try:
        req = urllib.request.Request(url, method=method)
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.fixture
def served_dir(tmp_path):
    (tmp_path / "viewer.html").write_text("<html>ok</html>", encoding="utf-8")
    (tmp_path / "idea_card.md").write_text("# card", encoding="utf-8")
    (tmp_path / ".env").write_text("GITHUB_TOKEN=ghp_secret", encoding="utf-8")
    (tmp_path / "debug" / "raw").mkdir(parents=True)
    (tmp_path / "debug" / "raw" / "metadata.json").write_text("{}", encoding="utf-8")
    (tmp_path / "debug" / "prompts").mkdir(parents=True)
    (tmp_path / "debug" / "prompts" / "bouncer.md").write_text("prompt", encoding="utf-8")
    (tmp_path / "debug" / "llm_calls.jsonl").write_text("{}", encoding="utf-8")
    outside = tmp_path.parent / "secret_outside.txt"
    outside.write_text("should not be reachable", encoding="utf-8")
    return tmp_path


# --- 3: 서버가 뜨고 정적 파일을 제공한다 -----------------------------------
def test_serve_starts_and_serves_viewer(served_dir):
    with running_server(served_dir, 8801) as base:
        assert _status(f"{base}/viewer.html") == 200
        assert _status(f"{base}/") == 200  # 루트는 viewer.html로


# --- 4: root가 run 디렉터리로 제한된다 ------------------------------------
def test_serve_blocks_outside_root(served_dir):
    with running_server(served_dir, 8802) as base:
        assert _status(f"{base}/../secret_outside.txt") == 403
        assert _status(f"{base}/%2e%2e/secret_outside.txt") == 403


# --- 5: .env 차단 ---------------------------------------------------------
def test_serve_blocks_env(served_dir):
    with running_server(served_dir, 8803) as base:
        assert _status(f"{base}/.env") == 403


# --- 6: path traversal 차단 -----------------------------------------------
def test_serve_blocks_traversal(served_dir):
    with running_server(served_dir, 8804) as base:
        assert _status(f"{base}/../../etc/hosts") == 403
        assert _status(f"{base}/debug/../.env") == 403


# --- 7: debug/raw · prompts · llm_calls 기본 차단 --------------------------
def test_serve_blocks_debug_raw_and_prompts(served_dir):
    with running_server(served_dir, 8805) as base:
        assert _status(f"{base}/debug/raw/metadata.json") == 403
        assert _status(f"{base}/debug/prompts/bouncer.md") == 403
        assert _status(f"{base}/debug/llm_calls.jsonl") == 403


def test_serve_is_read_only(served_dir):
    with running_server(served_dir, 8806) as base:
        assert _status(f"{base}/viewer.html", method="POST") == 501
        assert _status(f"{base}/viewer.html", method="DELETE") == 501


# --- _is_denied 단위 검증 (검색 결과의 중첩 경로 포함) ----------------------
def test_is_denied_unit():
    assert _is_denied("/.env")
    assert _is_denied("/debug/raw/metadata.json")
    assert _is_denied("/repos/o1_r1/debug/raw/metadata.json")
    assert _is_denied("/repos/o1_r1/debug/prompts/bouncer.md")
    assert _is_denied("/debug/llm_calls.jsonl")
    assert not _is_denied("/viewer.html")
    assert not _is_denied("/.env.example")
    assert not _is_denied("/repos/o1_r1/idea_card.md")
    assert not _is_denied("/debug/worker_outputs/critic_judge_final.json")
