# 재검수 보완 요구서(§7~§8) 검증 테스트: targeted, key pool 집계, nullable schema,
# llm_calls validation_success, truncation warning, 최종 secret scan, CLI 진입점, 설정 파일 형식.
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from repo_idea_miner.config import Settings, load_google_keys
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.llm_client import GoogleGenAIGemmaClient, LLMCallLogger, MockLLMClient
from repo_idea_miner.pipeline import final_secret_scan, run_single_repo
from repo_idea_miner.schemas import Application, OneDayMvp, PatternPoc
from repo_idea_miner.search_pipeline import (
    compute_targeted_score,
    rank_candidates_targeted,
    run_search,
)
from repo_idea_miner.workers import mock_output

from tests.test_pipeline_mock import FakeGitHub

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- §8.2 CLI entry

def test_module_entry_help():
    proc = subprocess.run(
        [sys.executable, "-m", "repo_idea_miner", "--help"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert proc.returncode == 0
    assert "run" in proc.stdout and "search" in proc.stdout and "validate" in proc.stdout


# ---------------------------------------------------------------- §8.3 / §8.4 설정 파일 형식

def test_env_example_line_format():
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert len(lines) > 20
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert re.match(r"^[A-Z][A-Z0-9_]*=", stripped), f"환경변수 형식이 아님: {line!r}"


def test_gitignore_ignores_env():
    content = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    stripped = [l.strip() for l in content]
    assert ".env" in stripped
    assert "!.env.example" in stripped
    assert "runs/" in stripped


# ---------------------------------------------------------------- §7.1 --targeted

def test_targeted_score_matches_topics_and_description():
    score, matched = compute_targeted_score(
        "y/auto", "workflow automation for python", ["automation", "workflow"], "Python"
    )
    assert score > 0
    assert "automation" in matched and "workflow" in matched


def test_targeted_score_zero_for_unrelated():
    score, matched = compute_targeted_score("x/paint", "a color picker gui", [], "Rust")
    assert score == 0 and matched == []


def test_rank_candidates_targeted_reorders():
    candidates = [
        {"full_name": "x/plain", "description": "misc tool", "stars": 500, "topics": [], "language": "Go"},
        {"full_name": "y/auto", "description": "workflow automation for python", "stars": 100, "topics": ["automation"], "language": "Python"},
    ]
    ranked = rank_candidates_targeted(candidates)
    assert ranked[0]["full_name"] == "y/auto"
    assert ranked[0]["targeted_score"] > ranked[1]["targeted_score"]
    assert all("targeted_score" in c and "targeted_matched" in c for c in ranked)


class SearchFakeGitHub(FakeGitHub):
    def get_json(self, path, params=None):
        if path == "/search/repositories":
            return {
                "items": [
                    {"full_name": "x/plain", "html_url": "https://github.com/x/plain", "description": "misc tool", "stargazers_count": 500, "topics": [], "language": "Go", "archived": False, "fork": False},
                    {"full_name": "y/auto", "html_url": "https://github.com/y/auto", "description": "workflow automation for python", "stargazers_count": 100, "topics": ["automation", "workflow"], "language": "Python", "archived": False, "fork": False},
                ]
            }
        return super().get_json(path, params)


def test_search_targeted_recorded_in_candidates_json(tmp_path):
    out = run_search(
        "q", limit=5, top=3, mode="mock", output_dir=tmp_path, targeted=True,
        settings=Settings(google_keys={}), gh=SearchFakeGitHub(),
    )
    candidates = json.loads((Path(out["run_dir"]) / "candidates.json").read_text(encoding="utf-8"))
    assert candidates[0]["full_name"] == "y/auto"  # 정렬에 실제 반영
    assert candidates[0]["targeted_score"] > candidates[1]["targeted_score"]
    report = (Path(out["run_dir"]) / "search_report.md").read_text(encoding="utf-8")
    assert "targeted_sort: YES" in report


def test_search_without_targeted_keeps_api_order(tmp_path):
    out = run_search(
        "q", limit=5, top=3, mode="mock", output_dir=tmp_path, targeted=False,
        settings=Settings(google_keys={}), gh=SearchFakeGitHub(),
    )
    candidates = json.loads((Path(out["run_dir"]) / "candidates.json").read_text(encoding="utf-8"))
    assert candidates[0]["full_name"] == "x/plain"
    report = (Path(out["run_dir"]) / "search_report.md").read_text(encoding="utf-8")
    assert "targeted_sort: NO" in report


# ---------------------------------------------------------------- §7.2 key pool 집계

class StubCountingLLM(MockLLMClient):
    def __init__(self):
        super().__init__()
        self.retry_count = 3
        self.failover_count = 1


def test_search_report_aggregates_key_pool_counts(tmp_path):
    out = run_search(
        "q", limit=5, top=3, mode="mock", output_dir=tmp_path,
        settings=Settings(google_keys={}), gh=SearchFakeGitHub(), llm=StubCountingLLM(),
    )
    report = (Path(out["run_dir"]) / "search_report.md").read_text(encoding="utf-8")
    assert "retry_count: 3" in report
    assert "failover_count: 1" in report


def test_search_mock_key_pool_safe_values(tmp_path):
    out = run_search(
        "q", limit=5, top=3, mode="mock", output_dir=tmp_path,
        settings=Settings(google_keys={}), gh=SearchFakeGitHub(),
    )
    report = (Path(out["run_dir"]) / "search_report.md").read_text(encoding="utf-8")
    assert "retry_count: 0" in report
    assert "failover_count: 0" in report


# ---------------------------------------------------------------- §7.3 nullable schema

def test_unfit_area_null_related_project_ok():
    Application.model_validate({"area": "적용 부적합", "related_project": None, "reason": "r"})


def test_mvp_impossible_null_fields_ok():
    OneDayMvp.model_validate(
        {"status": "축소 불가", "feature": None, "input": None, "output": None, "excluded_scope": [], "reason": "r"}
    )


def test_poc_impossible_null_fields_ok():
    PatternPoc.model_validate({"status": "불가능", "idea": None, "input": None, "output": None, "reason": "r"})


def test_mvp_possible_null_fields_fail():
    with pytest.raises(ValidationError):
        OneDayMvp.model_validate(
            {"status": "가능", "feature": None, "input": "i", "output": "o", "excluded_scope": [], "reason": "r"}
        )


def test_poc_possible_null_fields_fail():
    with pytest.raises(ValidationError):
        PatternPoc.model_validate({"status": "가능", "idea": "x", "input": None, "output": "o", "reason": "r"})


def test_judge_with_null_optional_fields_renders(tmp_path):
    judge = mock_output("critic_judge")
    judge["application"]["area"] = "적용 부적합"
    judge["application"]["related_project"] = None
    judge["one_day_mvp"].update(status="축소 불가", feature=None, input=None, output=None)
    judge["pattern_poc"].update(status="불가능", idea=None, input=None, output=None)
    llm = MockLLMClient(overrides={"critic_judge": judge})
    result = run_single_repo(
        "https://github.com/owner/repo", mode="mock", output_dir=tmp_path,
        settings=Settings(google_keys={}), gh=FakeGitHub(), llm=llm,
    )
    assert result["ok"], result
    card = (Path(result["run_dir"]) / "idea_card.md").read_text(encoding="utf-8")
    assert "None" not in card.split("## 내 현재 병목에 적용")[1].split("## 만들면")[0]


# ---------------------------------------------------------------- §7.4 validation_success 의미

def test_llm_calls_validation_success_is_null_for_live_client(fake_env):
    # 실패(transient) 후 성공하는 시나리오 — 실패/성공 로그 모두 validation_success는 null이어야 한다
    logger = LLMCallLogger(None)
    settings = Settings(google_keys=load_google_keys(fake_env), retry_initial_delay_seconds=0.01)
    calls = {"n": 0}

    def transport(*a):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 UNAVAILABLE")
        return '{"ok": true}'

    client = GoogleGenAIGemmaClient(
        settings, KeyPool(settings.google_keys), call_logger=logger,
        transport=transport, sleep_fn=lambda s: None,
    )
    client.generate_json("p", "bouncer")
    assert len(logger.entries) >= 2, "실패/성공 로그가 모두 있어야 함"
    for entry in logger.entries:
        assert entry["validation_success"] is None


def test_llm_calls_validation_success_is_null_for_mock_client():
    logger = LLMCallLogger(None)
    MockLLMClient(call_logger=logger).generate_json("p", "bouncer")
    assert logger.entries[0]["validation_success"] is None


# ---------------------------------------------------------------- §7.5 truncation은 warning

def test_length_truncation_is_not_an_error(tmp_path):
    judge = mock_output("critic_judge")
    judge["one_line_conclusion"] = "가" * 500
    llm = MockLLMClient(overrides={"critic_judge": judge})
    result = run_single_repo(
        "https://github.com/owner/repo", mode="mock", output_dir=tmp_path,
        settings=Settings(google_keys={}), gh=FakeGitHub(), llm=llm,
    )
    assert result["ok"], result
    report = (Path(result["run_dir"]) / "run_report.md").read_text(encoding="utf-8")
    errors_section = report.split("## Errors")[1].split("## JSON Validation")[0]
    assert "LENGTH_TRUNCATED" not in errors_section
    trunc_section = report.split("## Length Truncation")[1].split("## Judge Raw")[0]
    assert "length_truncated: YES" in trunc_section
    assert "one_line_conclusion" in trunc_section


# ---------------------------------------------------------------- §7.6 최종 secret scan

def test_final_scan_includes_run_report(tmp_path):
    result = run_single_repo(
        "https://github.com/owner/repo", mode="mock", output_dir=tmp_path,
        settings=Settings(google_keys={}), gh=FakeGitHub(),
    )
    assert result["ok"]
    run_dir = Path(result["run_dir"])
    report_path = run_dir / "run_report.md"
    with open(report_path, "a", encoding="utf-8") as f:
        f.write("\nleak ghp_abcdef123456789012\n")
    leaked = final_secret_scan(run_dir, [])
    assert str(report_path) in leaked


def test_validate_search_skips_failed_candidates(tmp_path):
    # 실패가 기록된 후보(run_report의 JSON Validation FAIL)는 카드 부재를 위반으로 보지 않는다
    from repo_idea_miner.validate_run import validate_run_dir

    run_dir = tmp_path / "search_run"
    (run_dir / "repos" / "o_failed").mkdir(parents=True)
    for name in ("top_ideas.md", "search_report.md", "candidates.json"):
        (run_dir / name).write_text("{}", encoding="utf-8")
    (run_dir / "repos" / "o_failed" / "run_report.md").write_text(
        "# Run Report\n\n## JSON Validation\nFAIL\n", encoding="utf-8"
    )
    ok, problems = validate_run_dir(run_dir, [])
    assert ok, problems

    # run_report 자체가 없으면 여전히 위반
    (run_dir / "repos" / "o_missing").mkdir()
    ok, problems = validate_run_dir(run_dir, [])
    assert not ok
    assert any("run_report.md 없음" in p for p in problems)


def test_pipeline_fails_when_redaction_bypassed(tmp_path, monkeypatch):
    # redaction이 뚫린 상황을 가정 — 최종 스캔이 안전망으로 FAIL 처리해야 한다
    monkeypatch.setattr("repo_idea_miner.pipeline.redact_text", lambda text, extra=(): text)
    judge = mock_output("critic_judge")
    judge["one_line_conclusion"] = "결론에 secret ghp_abcdef123456789012 이 섞임"
    llm = MockLLMClient(overrides={"critic_judge": judge})
    result = run_single_repo(
        "https://github.com/owner/repo", mode="mock", output_dir=tmp_path,
        settings=Settings(google_keys={}), gh=FakeGitHub(), llm=llm,
    )
    assert not result["ok"]
    report = (Path(result["run_dir"]) / "run_report.md").read_text(encoding="utf-8")
    assert "## Secret Redaction\nFAIL" in report
    assert "## Token/API Key Exposure\nYES" in report
