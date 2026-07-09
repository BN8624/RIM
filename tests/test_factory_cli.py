# factory/factory-build/factory-status/factory-validate CLI와 안전 모드(--once/--max-runs/--continuous) 테스트.
import pytest

from repo_idea_miner.cli import build_parser, main
from repo_idea_miner.config import Settings
from repo_idea_miner.factory_pipeline import FactorySettings
from repo_idea_miner.factory_prompts import mock_factory_overrides
from repo_idea_miner.factory_runner import eligible_challenges, run_factory
from repo_idea_miner.llm_client import MockLLMClient


@pytest.mark.parametrize("command", ["factory", "factory-build", "factory-status", "factory-validate"])
def test_factory_cli_help(command, capsys):
    """§22-1~4: factory 계열 CLI help."""
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([command, "--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out


def _seed_challenges(tmp_path, n=1):
    """mock challenge n건을 DB에 만든다 (GOOD_CHALLENGE)."""
    import repo_idea_miner.challenge_pipeline  # noqa: F401 - FakeGitHub import 경로 확보
    from repo_idea_miner.challenge_db import open_db
    from repo_idea_miner.challenge_pipeline import run_challenge
    from tests.test_pipeline_mock import FakeGitHub

    db_path = tmp_path / "challenge.db"
    conn = open_db(db_path)
    ids = []
    for i in range(n):
        res = run_challenge(
            f"https://github.com/owner/repo{i}",
            mode="mock",
            output_dir=tmp_path / "runs",
            settings=Settings(google_keys={}),
            gh=FakeGitHub(),
            db_conn=conn,
        )
        assert res["ok"], res["error"]
        ids.append(res["challenge_id"])
    conn.close()
    return db_path, ids


def test_factory_mock_once_via_cli(tmp_path, monkeypatch, capsys):
    """§22-5: factory --mode mock --once 실행."""
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    db_path, _ = _seed_challenges(tmp_path, n=2)
    code = main(["factory", "--mode", "mock", "--once",
                 "--db", str(db_path), "--output-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "processed: 1" in out  # --once는 1건만


def test_factory_default_is_safe_mode(tmp_path, monkeypatch, capsys):
    """§19.1: 제한 옵션 없이 실행해도 기본 max_runs=1 안전 모드."""
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    db_path, _ = _seed_challenges(tmp_path, n=2)
    code = main(["factory", "--mode", "mock", "--db", str(db_path),
                 "--output-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "processed: 1" in out


def test_factory_live_max_runs_limit(tmp_path):
    """§22-6: live 모드 --max-runs 제한 (LLM은 주입 mock, key 호출 없음)."""
    db_path, _ = _seed_challenges(tmp_path, n=3)
    summary = run_factory(
        db_path=db_path, mode="live", output_dir=tmp_path / "runs",
        max_runs=2, settings=Settings(google_keys={}),
        factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert summary["processed"] == 2
    assert len(summary["runs"]) == 2


def test_factory_continuous_requires_explicit_flag(tmp_path):
    """§22-7: --continuous를 명시해야 계속 실행. max_cycles로 종료를 강제해 검증."""
    parser = build_parser()
    args = parser.parse_args(["factory", "--mode", "mock"])
    assert args.continuous is False  # 기본값은 continuous 아님
    db_path, _ = _seed_challenges(tmp_path, n=2)
    summary = run_factory(
        db_path=db_path, mode="mock", output_dir=tmp_path / "runs",
        continuous=True, poll_seconds=0.0, max_cycles=1,
        settings=Settings(google_keys={}),
        factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert summary["continuous"] is True
    assert summary["processed"] == 2  # 한 사이클에서 대상 전부 처리


def test_factory_build_sample_mock_via_cli(tmp_path, monkeypatch, capsys):
    """§22-8: factory-build --sample mock --mode mock."""
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    code = main(["factory-build", "--sample", "mock", "--mode", "mock",
                 "--db", str(tmp_path / "challenge.db"), "--output-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "verdict: PROMOTE_TO_CODEX" in out
    assert "product_run_id: 1" in out


def test_factory_build_challenge_id_via_cli(tmp_path, monkeypatch, capsys):
    """§22-9: factory-build --challenge-id mock 실행."""
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    db_path, ids = _seed_challenges(tmp_path, n=1)
    code = main(["factory-build", "--challenge-id", str(ids[0]), "--mode", "mock",
                 "--db", str(db_path), "--output-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "line: standard" in out
    assert "gates: static=PASS" in out


def test_factory_build_requires_source(capsys):
    assert main(["factory-build", "--mode", "mock"]) == 1
    assert "하나가 필요" in capsys.readouterr().err


def test_factory_status_via_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    db_path = tmp_path / "challenge.db"
    assert main(["factory-build", "--sample", "mock", "--mode", "mock",
                 "--db", str(db_path), "--output-dir", str(tmp_path / "runs")]) == 0
    capsys.readouterr()
    assert main(["factory-status", "--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "product_runs: 1" in out
    assert "PROMOTE_TO_CODEX" in out


def test_factory_validate_via_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    db_path = tmp_path / "challenge.db"
    assert main(["factory-build", "--sample", "mock", "--mode", "mock",
                 "--db", str(db_path), "--output-dir", str(tmp_path / "runs")]) == 0
    out = capsys.readouterr().out
    run_dir = next(line.split("run_dir: ", 1)[1] for line in out.splitlines() if line.startswith("run_dir: "))
    assert main(["factory-validate", run_dir]) == 0
    assert "FACTORY VALIDATION PASS" in capsys.readouterr().out


def test_eligible_challenges_skips_processed(tmp_path, monkeypatch):
    """이미 run이 있는 challenge는 다시 뽑지 않는다."""
    monkeypatch.setenv("RIM_FACTORY_USE_DOCKER", "off")
    db_path, ids = _seed_challenges(tmp_path, n=2)
    from repo_idea_miner.factory_db import open_factory_db

    conn = open_factory_db(db_path)
    try:
        first = eligible_challenges(conn)
        assert len(first) == 2
    finally:
        conn.close()
    summary = run_factory(
        db_path=db_path, mode="mock", output_dir=tmp_path / "runs", max_runs=1,
        settings=Settings(google_keys={}), factory_settings=FactorySettings(use_docker="off"),
        llm=MockLLMClient(overrides=mock_factory_overrides()),
    )
    assert summary["processed"] == 1
    conn = open_factory_db(db_path)
    try:
        remaining = eligible_challenges(conn)
        assert len(remaining) == 1
        assert remaining[0]["challenge_id"] != summary["runs"][0]["challenge_id"]
    finally:
        conn.close()
