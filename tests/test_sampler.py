# issue body sampler 테스트 (§34.4).
from repo_idea_miner.sampler import MAX_SAMPLE_CHARS, build_body_sample


def test_env_front_issue_still_includes_tail_and_keywords():
    env_block = "## Environment\n" + "\n".join(f"OS: Windows / Python 3.11 / row {i}" for i in range(30))
    pain = "The export button always crashes with an error when I select bulk items."
    body = env_block + "\n\n" + pain
    sample = build_body_sample(body)
    assert "export" in sample
    assert "crash" in sample or "error" in sample


def test_feature_request_keyword_detected_in_sample():
    body = ("intro text " * 60) + " It would be great to add support for CSV export. " + ("outro " * 5)
    sample = build_body_sample(body)
    assert "add support" in sample or "would be great" in sample


def test_long_logs_compressed():
    log_block = "```\n" + ("ERROR stacktrace line xyz\n" * 200) + "```"
    body = "Crash happens.\n" + log_block + "\nPlease fix."
    sample = build_body_sample(body)
    assert "[로그 압축됨]" in sample or len(sample) <= MAX_SAMPLE_CHARS


def test_sample_max_1500_chars():
    body = "bug " * 5000
    assert len(build_body_sample(body)) <= MAX_SAMPLE_CHARS


def test_empty_body():
    assert build_body_sample(None) == ""
    assert build_body_sample("") == ""
