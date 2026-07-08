# mock 모드 전체 파이프라인 통합 테스트: 네트워크 없이 fake GitHub 클라이언트로 검증.
import json

from repo_idea_miner.config import Settings
from repo_idea_miner.pipeline import run_single_repo
from repo_idea_miner.renderer import IDEA_CARD_SECTIONS
from repo_idea_miner.validate_run import validate_run_dir


class FakeGitHub:
    """GitHubClient 대체: 미리 준비한 응답을 돌려준다."""

    def get_json(self, path, params=None):
        if path.endswith("/languages"):
            return {"Python": 1000}
        if path.startswith("/repos/") and path.count("/") == 2:
            return {
                "name": "repo",
                "full_name": "owner/repo",
                "description": "테스트 레포",
                "stargazers_count": 120,
                "forks_count": 10,
                "subscribers_count": 5,
                "topics": ["automation"],
                "language": "Python",
                "updated_at": "2026-07-01T00:00:00Z",
                "created_at": "2024-01-01T00:00:00Z",
                "pushed_at": "2026-07-01T00:00:00Z",
                "archived": False,
                "disabled": False,
                "fork": False,
                "is_template": False,
                "mirror_url": None,
                "open_issues_count": 4,
                "license": {"spdx_id": "MIT"},
                "homepage": None,
                "default_branch": "main",
                "size": 800,
                "html_url": "https://github.com/owner/repo",
            }
        return {}

    def get_optional_json(self, path, params=None):
        if "/issues/" in path and path.endswith("/comments"):
            return [
                {"user": {"login": f"u{i}"}, "author_association": "NONE"} for i in range(3)
            ]
        if path.endswith("/issues"):
            if params and params.get("state") == "open":
                return [
                    {
                        "number": 1,
                        "title": "Export crashes with error",
                        "state": "open",
                        "labels": [],
                        "comments": 12,
                        "updated_at": "2026-07-01T00:00:00Z",
                        "created_at": "2026-06-01T00:00:00Z",
                        "closed_at": None,
                        "body": "steps to reproduce: click export, it fails with error",
                        "html_url": "https://github.com/owner/repo/issues/1",
                    },
                    {
                        "number": 2,
                        "title": "Feature request: bulk automation",
                        "state": "open",
                        "labels": [],
                        "comments": 0,
                        "updated_at": "2026-06-20T00:00:00Z",
                        "created_at": "2026-06-01T00:00:00Z",
                        "closed_at": None,
                        "body": "would be great to automate batch export",
                        "html_url": "https://github.com/owner/repo/issues/2",
                    },
                ]
            return []
        if path.endswith("/pulls"):
            return [
                {"number": 3, "title": "Fix crash", "user": {"login": "alice"}, "state": "open", "updated_at": "2026-07-01T00:00:00Z", "html_url": "x"},
                {"number": 4, "title": "Bump deps", "user": {"login": "dependabot[bot]"}, "state": "open", "updated_at": "2026-07-01T00:00:00Z", "html_url": "y"},
            ]
        if "/git/trees/" in path:
            return {"tree": [{"path": "src", "type": "tree"}, {"path": "src/main.py", "type": "blob"}, {"path": "docs/guide.md", "type": "blob"}], "truncated": False}
        return None

    def get_optional_raw(self, path):
        if path.endswith("/readme"):
            return "# Repo\n\n## Install\npip install repo\n\n## Usage\nrepo run"
        if path.endswith("/contents/pyproject.toml"):
            return '[project]\ndependencies = ["requests"]\n\n[project.optional-dependencies]\ndev = ["pytest"]\n'
        return None


def test_mock_run_produces_all_artifacts(tmp_path):
    settings = Settings(google_keys={1: "AQ.fake_key_for_test_aaaaaaaaaa"})
    result = run_single_repo(
        "https://github.com/owner/repo",
        mode="mock",
        input_mode="direct",
        output_dir=tmp_path,
        settings=settings,
        gh=FakeGitHub(),
    )
    assert result["ok"], result
    from pathlib import Path

    run_dir = Path(result["run_dir"])
    assert (run_dir / "idea_card.md").exists()
    assert (run_dir / "run_report.md").exists()
    assert (run_dir / "debug" / "evidence_packet.md").exists()
    assert (run_dir / "debug" / "llm_calls.jsonl").exists()
    assert (run_dir / "debug" / "judge_output_raw.json").exists()
    assert (run_dir / "debug" / "judge_output_final.json").exists()
    for worker in ("bouncer", "readme_scout", "pain_scout", "structure_risk_scout"):
        assert (run_dir / "debug" / "worker_outputs" / f"{worker}.json").exists()

    card = (run_dir / "idea_card.md").read_text(encoding="utf-8")
    for section in IDEA_CARD_SECTIONS:
        assert section in card

    report = (run_dir / "run_report.md").read_text(encoding="utf-8")
    assert "PASS" in report

    ok, problems = validate_run_dir(run_dir, settings.secret_values())
    assert ok, problems


def test_mock_run_validation_fail_no_card(tmp_path):
    from repo_idea_miner.llm_client import MockLLMClient
    from repo_idea_miner.workers import mock_output

    bad_judge = mock_output("critic_judge")
    del bad_judge["next_action"]
    llm = MockLLMClient(overrides={"critic_judge": bad_judge})
    settings = Settings(google_keys={})
    result = run_single_repo(
        "https://github.com/owner/repo",
        mode="mock",
        output_dir=tmp_path,
        settings=settings,
        gh=FakeGitHub(),
        llm=llm,
    )
    assert result["error"] == "VALIDATION_FAIL"
    assert not result["ok"]
    from pathlib import Path

    run_dir = Path(result["run_dir"])
    assert not (run_dir / "idea_card.md").exists()
