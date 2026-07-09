# Product Dashboard 표시 문구 한국어화 테스트: enum/기술 용어 → 한국어, 내부값 불변 (용어개선 §18).
import threading
import urllib.request
from types import SimpleNamespace

import pytest

from repo_idea_miner import factory_labels as L
from repo_idea_miner.challenge_dashboard import make_dashboard_server
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_db import open_factory_db, update_product_run
from repo_idea_miner.factory_pipeline import (
    FactorySettings,
    run_product_factory,
    sample_challenge,
)
from repo_idea_miner.factory_prompts import mock_factory_overrides
from repo_idea_miner.llm_client import MockLLMClient


# ---------------------------------------------------------------- 라벨 단위 테스트 (§18.1~16)

@pytest.mark.parametrize("enum,ko", [
    ("PROMOTE_TO_CODEX", "제품화 후보"),
    ("KEEP_CANDIDATE", "보관 후보"),
    ("NEEDS_MORE_GEMMA_LOOP", "더 돌려야 함"),
    ("TOO_WEAK", "약함"),
    ("DROP", "버림"),
])
def test_verdict_labels(enum, ko):
    assert L.format_verdict_label(enum) == ko


def test_verdict_none_label():
    assert L.format_verdict_label(None) == "판정 없음"


@pytest.mark.parametrize("status,ko", [
    ("completed", "완료"), ("done", "완료"), ("error", "오류"),
    ("failed", "실패"), ("running", "실행 중"), ("pending", "대기 중"),
])
def test_status_labels(status, ko):
    assert L.format_status_label(status) == ko


@pytest.mark.parametrize("action,ko", [
    ("keep", "보관"), ("drop", "버림"), ("productize", "제품화"),
    ("retry", "다시 돌리기"), ("archive", "보류"),
])
def test_review_labels(action, ko):
    assert L.format_review_label(action) == ko


def test_review_unreviewed():
    assert L.format_review_label(None) == "미검수"


@pytest.mark.parametrize("key,ko", [
    ("static", "파일 구조 검사"), ("contract", "구현 연결 검사"),
    ("syntax", "문법 검사"), ("smoke", "기본 실행 검사"),
])
def test_gate_labels(key, ko):
    assert L.format_gate_label(key) == ko


@pytest.mark.parametrize("st,ko", [("PASS", "통과"), ("FAIL", "실패"), ("SKIP", "건너뜀"), ("UNKNOWN", "알 수 없음")])
def test_gate_status_labels(st, ko):
    assert L.format_gate_status(st) == ko


@pytest.mark.parametrize("st,ko", [("PASS", "좋음"), ("PARTIAL", "일부 부족"), ("FAIL", "실패"), ("UNKNOWN", "알 수 없음")])
def test_qa_status_labels(st, ko):
    assert L.format_qa_status(st) == ko


@pytest.mark.parametrize("text", [
    "src/app.js does not wire onJump handler",
    "scrubber onJump missing",
    "timeline scrubber onJump not implemented",
])
def test_humanize_scrubber_issue(text):
    # §17: scrubber/onJump 문제는 "타임라인을 움직여도 사진이 바뀌지 않음" 계열로
    assert L.humanize_issue(text) == "타임라인을 움직여도 사진이 바뀌지 않음"


def test_humanize_other_patterns():
    assert L.humanize_issue("Smoke Gate timeout") == "기본 실행 중 시간이 초과됨"
    assert L.humanize_issue("button exists but click handler not implemented") == "버튼은 있지만 눌러도 동작하지 않음"
    # 통짜 매칭이 없으면 용어만 풀어 씀 (한국어 문장 보존)
    assert "핵심 조건" in L.humanize_issue("anchors 확인 완료")


# ---------------------------------------------------------------- 통합: enum 접힘 보존 + 내부값 불변 (§18.18~20)

@pytest.fixture
def detail(tmp_path):
    db_path = tmp_path / "challenge.db"
    conn = open_factory_db(db_path)
    result = run_product_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=Settings(google_keys={}),
        factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert result["ok"], result["error"]
    run_id = result["product_run_id"]
    # 화면 라벨만 검증하기 위해 verdict를 다른 enum으로 바꿔도 내부값은 enum 그대로여야 한다
    update_product_run(conn, run_id, verdict="NEEDS_MORE_GEMMA_LOOP")
    conn.close()

    server = make_dashboard_server(db_path, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield SimpleNamespace(base=base, db_path=db_path, run_id=run_id, tmp_path=tmp_path)
    server.shutdown()
    server.server_close()


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        return resp.read().decode("utf-8")


def test_korean_label_shown_english_enum_in_collapsible(detail):
    body = _get(detail.base, f"/product/{detail.run_id}")
    assert "더 돌려야 함" in body  # 한국어 표시명 (§2)
    assert "원본 상태값 보기" in body  # 영어 원문 접힘 영역 (§13·§14)
    # 영어 enum 원문은 가독 텍스트로는 접힘 영역에서만 노출된다 (색상용 class 제외)
    assert "verdict: NEEDS_MORE_GEMMA_LOOP" in body
    # 상단 요약 문장에는 한국어만 (enum을 사람이 읽는 문장으로 노출하지 않음)
    hero = body.split("원본 상태값 보기")[0]
    assert "verdict: NEEDS_MORE_GEMMA_LOOP" not in hero


def test_internal_values_unchanged(detail):
    conn = open_factory_db(detail.db_path)
    try:
        row = conn.execute("SELECT verdict FROM product_runs WHERE id=?", (detail.run_id,)).fetchone()
        assert row["verdict"] == "NEEDS_MORE_GEMMA_LOOP"  # DB enum 값 불변
    finally:
        conn.close()
    # 파일명도 그대로 (manifest.json 등)
    manifests = list(detail.tmp_path.rglob("final_artifact/manifest.json"))
    assert manifests, "manifest.json 파일명은 유지되어야 함"
