# Phase 1.6 Dashboard 테스트: 검수용 한국어 목록 카드(기술 로그 미노출)와 상세 코어 검증 표시 (§11.10, §16-47~49).
import threading
import urllib.request
from types import SimpleNamespace

import pytest

from repo_idea_miner.challenge_dashboard import make_dashboard_server
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_core_pipeline import run_core_factory
from repo_idea_miner.factory_core_prompts import mock_core_factory_overrides
from repo_idea_miner.factory_db import open_factory_db
from repo_idea_miner.factory_pipeline import FactorySettings, sample_challenge
from repo_idea_miner.llm_client import MockLLMClient


def _get(base, path):
    with urllib.request.urlopen(base + path, timeout=10) as resp:
        assert resp.status == 200
        return resp.read().decode("utf-8")


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("dash16")
    db_path = tmp_path / "challenge.db"
    conn = open_factory_db(db_path)
    result = run_core_factory(
        sample_challenge(), mode="mock", output_dir=tmp_path / "runs",
        db_conn=conn, settings=Settings(google_keys={}),
        factory_settings=FactorySettings(use_docker="off", sandbox_timeout_seconds=60.0),
        llm=MockLLMClient(overrides=mock_core_factory_overrides()),
    )
    assert result["ok"], result["error"]
    conn.close()
    server = make_dashboard_server(db_path, host="127.0.0.1", port=0, secrets=[])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield SimpleNamespace(base=base, run_id=result["product_run_id"], result=result)
    server.shutdown()
    server.server_close()


def test_list_card_korean_review_format(env):
    """§16-47,48: 목록 카드가 §11.10 한국어 검수 형식이고 기술 로그를 노출하지 않는다."""
    body = _get(env.base, "/products")
    assert "검수 가능" in body  # REVIEW_READY 헤드라인
    assert "산출물 유형" in body
    assert "룰 엔진" in body
    assert "코어: 있음" in body
    assert "결정성" in body
    assert "위험" in body
    assert "실행해보고 판단" in body  # 추천
    # 기술 로그/원시 gate 이름은 목록 카드에 없다
    for raw in ("scenario_replay_summary", "anti_hardcode_summary", "stdout", "exit_code"):
        assert raw not in body, raw


def test_detail_core_verification_panel(env):
    """§16-49: 상세에서 runner/golden/determinism 등 코어 검증 표시."""
    body = _get(env.base, f"/product/{env.run_id}")
    assert "코어 시스템 검증" in body
    for label in ("러너 실행 검사", "시나리오 재생", "기대 출력 비교",
                  "상태 불변조건", "결정성 검사", "하드코딩 탐지"):
        assert label in body, label
    assert "실행 명령" in body
    assert "python src/runner.py" in body
    assert "실패 시나리오" in body


def test_detail_report_tabs_include_core_summaries(env):
    """상세 리포트 탭에서 core 요약 원문을 볼 수 있다."""
    body = _get(env.base, f"/product/{env.run_id}?tab=golden_diff_summary")
    assert "exact_total" in body
    body = _get(env.base, f"/product/{env.run_id}?tab=harness_summary")
    assert "core_spec" in body
    body = _get(env.base, f"/product/{env.run_id}?tab=green_base")
    assert "green_base_path" in body


def test_source_preview_covers_core_dirs(env):
    """fixtures/golden/product 파일도 소스 미리보기 화이트리스트에 포함된다."""
    body = _get(env.base, f"/product/{env.run_id}?src=fixtures/scenario_001.json")
    assert "허용되지 않은 경로" not in body
    body = _get(env.base, f"/product/{env.run_id}?src=product/viewer/index.html")
    assert "허용되지 않은 경로" not in body


def test_verdict_badge_korean(env):
    body = _get(env.base, f"/product/{env.run_id}")
    assert "검수 가능" in body  # REVIEW_READY 한국어 라벨
