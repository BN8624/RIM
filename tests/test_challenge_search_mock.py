# mock 모드 challenge-search 파이프라인 테스트: 정렬/index/실패 격리를 네트워크 없이 검증.
import json
from pathlib import Path

from repo_idea_miner.challenge_db import open_db
from repo_idea_miner.challenge_search_pipeline import prioritize_candidates, run_challenge_search
from repo_idea_miner.challenge_validate import validate_challenge_run_dir
from repo_idea_miner.config import Settings
from tests.test_pipeline_mock import FakeGitHub


class FakeSearchGitHub(FakeGitHub):
    """검색 API까지 흉내내는 GitHub 클라이언트."""

    def __init__(self, items):
        self.items = items

    def get_json(self, path, params=None):
        if path == "/search/repositories":
            return {"items": self.items}
        return super().get_json(path, params)


def _items(n=3, **overrides):
    items = []
    for i in range(n):
        item = {
            "full_name": f"owner/repo{i}",
            "html_url": f"https://github.com/owner/repo{i}",
            "description": f"테스트 레포 {i}",
            "stargazers_count": 1000 - i,
            "forks_count": 10,
            "topics": ["automation"],
            "language": "Python",
            "archived": False,
            "fork": False,
        }
        item.update(overrides)
        items.append(item)
    return items


def test_prioritize_dedup_fork_skip_archived_low():
    cands = [
        {"full_name": "a/x", "stars": 10, "fork": False, "archived": False},
        {"full_name": "a/x", "stars": 10, "fork": False, "archived": False},  # 중복
        {"full_name": "a/f", "stars": 999, "fork": True, "archived": False},  # fork skip
        {"full_name": "a/arch", "stars": 999, "fork": False, "archived": True},
        {"full_name": "a/top", "stars": 500, "fork": False, "archived": False},
    ]
    out = prioritize_candidates(cands, top=10)
    names = [c["full_name"] for c in out]
    assert names == ["a/top", "a/x", "a/arch"]  # archived는 맨 뒤


def test_mock_challenge_search_generates_index(tmp_path):
    settings = Settings(google_keys={})
    out = run_challenge_search(
        "demo",
        limit=5,
        top=3,
        mode="mock",
        output_dir=tmp_path,
        settings=settings,
        gh=FakeSearchGitHub(_items(3)),
    )
    run_dir = Path(out["run_dir"])
    assert (run_dir / "challenge_index.json").exists()
    assert (run_dir / "search_report.json").exists()
    assert (run_dir / "viewer.html").exists()
    assert (run_dir / "candidates.json").exists()

    index = json.loads((run_dir / "challenge_index.json").read_text(encoding="utf-8"))
    assert index["generated_count"] == 3
    assert index["query"] == "demo"
    for item in index["items"]:
        repo_dir = Path(item["artifact_dir"])
        assert (repo_dir / "challenge_card.json").exists()
        assert (repo_dir / "implementation_prompt.md").exists()

    viewer = (run_dir / "viewer.html").read_text(encoding="utf-8")
    assert "data-filter" in viewer

    ok, problems = validate_challenge_run_dir(run_dir, [])
    assert ok, problems


def test_one_repo_failure_does_not_stop_search(tmp_path, monkeypatch):
    import repo_idea_miner.challenge_search_pipeline as csp

    real = csp.run_challenge
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("live 실패 시뮬레이션")
        return real(*args, **kwargs)

    monkeypatch.setattr(csp, "run_challenge", flaky)
    settings = Settings(google_keys={})
    out = run_challenge_search(
        "demo", limit=5, top=3, mode="mock", output_dir=tmp_path,
        settings=settings, gh=FakeSearchGitHub(_items(3)),
    )
    assert len(out["index_items"]) == 2
    assert any("live 실패 시뮬레이션" in e for e in out["errors"])
    index = json.loads((Path(out["run_dir"]) / "challenge_index.json").read_text(encoding="utf-8"))
    assert index["generated_count"] == 2
    # 실패 후보가 있어도 validate는 통과해야 한다 (실패 기록은 정상)
    ok, problems = validate_challenge_run_dir(out["run_dir"], [])
    assert ok, problems


def test_search_saves_repos_and_challenges_to_db(tmp_path):
    conn = open_db(tmp_path / "challenge.db")
    try:
        settings = Settings(google_keys={})
        run_challenge_search(
            "demo", limit=5, top=2, mode="mock", output_dir=tmp_path,
            settings=settings, gh=FakeSearchGitHub(_items(3)), db_conn=conn,
        )
        repos = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
        challenges = conn.execute("SELECT COUNT(*) FROM challenges").fetchone()[0]
        assert repos == 3  # 후보 전체 저장
        assert challenges == 2  # top=2만 생성
    finally:
        conn.close()
