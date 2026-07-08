# issue signal tag 테스트 (§34.5).
from repo_idea_miner.signals import compute_issue_stats, tag_issue


def test_bug_issue_defect_signal():
    assert "defect_signal" in tag_issue("App crashes on startup", "steps to reproduce: run it, error appears")


def test_feature_request_feature_signal():
    assert "feature_signal" in tag_issue("Feature request: dark theme", "would be great to add support for themes")


def test_automation_issue_workflow_signal():
    assert "workflow_signal" in tag_issue("Bulk export automation", "I want to automate the export of all records")


def test_docs_issue_confusion_signal():
    assert "confusion_signal" in tag_issue("Docs unclear", "the documentation and tutorial for setup is confusing")


def test_install_version_issue_noise_signal():
    assert "noise_signal" in tag_issue("Installation failed", "version conflict when I pip install this package")


def test_unknown_issue_uncertain_signal():
    assert tag_issue("hmm", "just a note") == ["uncertain_signal"]


def test_multiple_tags_allowed():
    tags = tag_issue("Export feature broken", "the export automation fails with an error, please add support for retry")
    assert "defect_signal" in tags and "workflow_signal" in tags and "feature_signal" in tags


def test_compute_issue_stats():
    records = [
        {"signal_tags": ["defect_signal"]},
        {"signal_tags": ["feature_signal", "workflow_signal"]},
        {"signal_tags": ["uncertain_signal"]},
    ]
    stats = compute_issue_stats(records)
    assert stats["sampled_issue_count"] == 3
    assert stats["classified_issue_count"] == 2
    assert stats["defect_count"] == 1
    assert stats["feature_request_count"] == 1
    assert stats["workflow_pain_count"] == 1
    assert stats["uncertain_count"] == 1
