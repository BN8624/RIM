# 신규/기존 CLI 서브커맨드 help·mock 실행·validate-db·pause/resume 동작 테스트.
import pytest

from repo_idea_miner.cli import build_parser, main


@pytest.mark.parametrize(
    "command",
    ["run", "search", "view", "serve", "validate", "challenge", "challenge-search",
     "daemon", "dashboard", "status", "pause", "resume", "validate-db"],
)
def test_cli_help_for_all_commands(command, capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([command, "--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out


def test_challenge_mock_via_cli(tmp_path, monkeypatch, capsys):
    import repo_idea_miner.challenge_pipeline as cp
    from tests.test_pipeline_mock import FakeGitHub

    monkeypatch.setattr(cp, "GitHubClient", lambda token: FakeGitHub())
    code = main(
        [
            "challenge",
            "--repo", "https://github.com/owner/repo",
            "--mode", "mock",
            "--output-dir", str(tmp_path / "runs"),
            "--db", str(tmp_path / "challenge.db"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "final_label: GOOD_CHALLENGE" in out
    assert "challenge_id: 1" in out


def test_challenge_search_mock_via_cli(tmp_path, monkeypatch, capsys):
    import repo_idea_miner.challenge_search_pipeline as csp
    from tests.test_challenge_search_mock import FakeSearchGitHub, _items

    monkeypatch.setattr(csp, "GitHubClient", lambda token: FakeSearchGitHub(_items(3)))
    code = main(
        [
            "challenge-search",
            "--query", "demo",
            "--limit", "5",
            "--top", "3",
            "--mode", "mock",
            "--output-dir", str(tmp_path / "runs"),
            "--db", str(tmp_path / "challenge.db"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "generated: 3" in out


def test_validate_db_cli(tmp_path, capsys):
    from repo_idea_miner.challenge_db import open_db

    db = tmp_path / "challenge.db"
    open_db(db).close()
    assert main(["validate-db", "--db", str(db)]) == 0
    assert "DB VALIDATION PASS" in capsys.readouterr().out


def test_pause_resume_status_cli(tmp_path, capsys):
    db = str(tmp_path / "challenge.db")
    assert main(["pause", "--db", db]) == 0
    assert main(["status", "--db", db]) == 0
    assert "miner_paused: True" in capsys.readouterr().out
    assert main(["resume", "--db", db]) == 0
    assert main(["status", "--db", db]) == 0
    assert "miner_paused: False" in capsys.readouterr().out
