# viewer.html 생성·모델 빌더·fallback·secret scan·validate --require-viewer 테스트.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_idea_miner.config import Settings
from repo_idea_miner.pipeline import run_single_repo
from repo_idea_miner.redaction import scan_files_for_secrets
from repo_idea_miner.search_pipeline import run_search
from repo_idea_miner.validate_run import validate_run_dir
from repo_idea_miner.viewer import build_model, generate_viewer, load_card, parse_idea_card


class FakeGitHub:
    """단일/검색 모두 커버하는 fake GitHub 클라이언트."""

    def __init__(self, search_items: list[dict] | None = None):
        self._search_items = search_items or []

    def get_json(self, path, params=None):
        if path == "/search/repositories":
            return {"items": self._search_items}
        if path.endswith("/languages"):
            return {"Python": 1000}
        if path.startswith("/repos/") and path.count("/") == 3:
            _, _, owner, repo = path.split("/")
            return {
                "name": repo,
                "full_name": f"{owner}/{repo}",
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
                "html_url": f"https://github.com/{owner}/{repo}",
            }
        return {}

    def get_optional_json(self, path, params=None):
        if "/issues/" in path and path.endswith("/comments"):
            return [{"user": {"login": f"u{i}"}, "author_association": "NONE"} for i in range(3)]
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
            ]
        if "/git/trees/" in path:
            return {"tree": [{"path": "src", "type": "tree"}, {"path": "src/main.py", "type": "blob"}], "truncated": False}
        return None

    def get_optional_raw(self, path):
        if path.endswith("/readme"):
            return "# Repo\n\n## Install\npip install repo\n\n## Usage\nrepo run"
        if path.endswith("/contents/pyproject.toml"):
            return '[project]\ndependencies = ["requests"]\n'
        return None


def _settings() -> Settings:
    return Settings(google_keys={1: "AQ.fake_key_for_test_aaaaaaaaaa"})


@pytest.fixture
def single_run(tmp_path) -> Path:
    result = run_single_repo(
        "https://github.com/owner/repo",
        mode="mock",
        input_mode="direct",
        output_dir=tmp_path,
        settings=_settings(),
        gh=FakeGitHub(),
    )
    return Path(result["run_dir"])


@pytest.fixture
def search_run(tmp_path) -> Path:
    items = [
        {"full_name": f"o{i}/r{i}", "html_url": f"https://github.com/o{i}/r{i}",
         "description": "automation workflow tool", "stargazers_count": 100 - i,
         "topics": ["automation", "workflow"], "language": "Python",
         "archived": False, "fork": False}
        for i in range(3)
    ]
    out = run_search(
        "automation workflow python",
        limit=10,
        top=5,
        mode="mock",
        output_dir=tmp_path,
        targeted=True,
        settings=_settings(),
        gh=FakeGitHub(search_items=items),
    )
    return Path(out["run_dir"])


# --- 1, 2: view가 viewer.html 생성 ---------------------------------------
def test_view_creates_viewer_single(single_run):
    out = generate_viewer(single_run)
    assert out.exists() and out.name == "viewer.html"
    assert "<html" in out.read_text(encoding="utf-8")


def test_view_creates_viewer_search(search_run):
    out = generate_viewer(search_run)
    assert out.exists()
    model = build_model(search_run)
    assert model["kind"] == "search"
    assert len(model["cards"]) == 3


# --- 8, 9, 10, 11, 12: viewer.html 필수 요소 -----------------------------
def test_viewer_has_verdict_labels(search_run):
    html = generate_viewer(search_run).read_text(encoding="utf-8")
    for label in ("KEEP", "MAYBE", "DROP", "ERROR"):
        assert label in html


def test_viewer_has_score(search_run):
    html = generate_viewer(search_run).read_text(encoding="utf-8")
    assert "data-score" in html and "score" in html


def test_viewer_has_repo_links(search_run):
    html = generate_viewer(search_run).read_text(encoding="utf-8")
    assert "https://github.com/o0/r0" in html
    assert 'target="_blank"' in html


def test_viewer_has_filter_buttons(search_run):
    html = generate_viewer(search_run).read_text(encoding="utf-8")
    for f in ("ALL", "KEEP", "MAYBE", "DROP", "ERROR", "HIDE_DROP"):
        assert f'data-filter="{f}"' in html


def test_viewer_has_mobile_viewport(single_run, search_run):
    for run in (single_run, search_run):
        html = generate_viewer(run).read_text(encoding="utf-8")
        assert 'name="viewport"' in html
        assert "width=device-width" in html


# --- 13, 14: viewer.html secret scan --------------------------------------
def test_viewer_secret_scan_catches_github_token(tmp_path):
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html>token ghp_faketoken1234567890abcd</html>", encoding="utf-8")
    leaked = scan_files_for_secrets([viewer], [])
    assert str(viewer) in leaked


def test_viewer_secret_scan_catches_google_key(tmp_path):
    viewer = tmp_path / "viewer.html"
    viewer.write_text("<html>key AIzaSyFAKE_key_value_123456</html>", encoding="utf-8")
    leaked = scan_files_for_secrets([viewer], [])
    assert str(viewer) in leaked


def test_generated_viewer_is_clean(search_run):
    out = generate_viewer(search_run)
    assert scan_files_for_secrets([out], _settings().secret_values()) == []


# --- 15, 16: validate --require-viewer ------------------------------------
def test_validate_require_viewer_fails_when_missing(single_run):
    ok, problems = validate_run_dir(single_run, require_viewer=True)
    assert not ok
    assert any("viewer.html 없음" in p for p in problems)


def test_validate_require_viewer_passes_when_present(single_run):
    generate_viewer(single_run)
    ok, problems = validate_run_dir(single_run, _settings().secret_values(), require_viewer=True)
    assert ok, problems


# --- 17: JSON 부재 시 idea_card.md fallback --------------------------------
def test_missing_json_falls_back_to_idea_card(single_run):
    final = single_run / "debug" / "worker_outputs" / "critic_judge_final.json"
    final.unlink()
    card = load_card(single_run)
    assert card["verdict"] in ("KEEP", "MAYBE", "DROP")
    assert card["one_line_conclusion"]  # idea_card.md에서 파싱됨


def test_parse_idea_card_extracts_fields(single_run):
    text = (single_run / "idea_card.md").read_text(encoding="utf-8")
    parsed = parse_idea_card(text)
    assert parsed["repo"] == "owner/repo"
    assert parsed["verdict"] in ("KEEP", "MAYBE", "DROP")
    assert isinstance(parsed["score"], int)


# --- 18, 19: 카드 부재 시 ERROR 카드 + 검색 viewer에 ERROR 표시 -------------
def test_missing_card_becomes_error_not_crash(search_run):
    victim = next((search_run / "repos").glob("*"))
    (victim / "idea_card.md").unlink()
    (victim / "debug" / "worker_outputs" / "critic_judge_final.json").unlink()
    card = load_card(victim, repo_name="o0/r0", url="https://github.com/o0/r0")
    assert card["verdict"] == "ERROR"
    assert card["error"]


def test_search_viewer_displays_error_candidates(search_run):
    victim = next((search_run / "repos").glob("*"))
    (victim / "idea_card.md").unlink()
    (victim / "debug" / "worker_outputs" / "critic_judge_final.json").unlink()
    # 실제 실패 후보는 cards/ 복사본도 없으므로 함께 제거해 ERROR 상태를 재현한다
    for copy in (search_run / "cards").glob(f"{victim.name}_idea_card.md"):
        copy.unlink()
    model = build_model(search_run)
    assert model["summary"]["error"] >= 1
    html = generate_viewer(search_run).read_text(encoding="utf-8")
    assert 'data-verdict="ERROR"' in html


# --- 20: targeted_score 정렬 옵션 -----------------------------------------
def test_targeted_sort_shown_when_available(search_run):
    cands = json.loads((search_run / "candidates.json").read_text(encoding="utf-8"))
    assert all("targeted_score" in c for c in cands)
    model = build_model(search_run)
    assert model["summary"]["has_targeted"]
    html = generate_viewer(search_run).read_text(encoding="utf-8")
    assert 'value="targeted"' in html
