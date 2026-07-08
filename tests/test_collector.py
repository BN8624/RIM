# GitHub collector 순수 헬퍼 테스트 (§34.3, §34.7): PR 필터, issue/PR 분리, comments 신호.
from repo_idea_miner.github_api import (
    analyze_comments,
    filter_issue_items,
    is_bot_pr,
    split_prs,
)


def pr(author, title):
    return {"user": {"login": author}, "title": title}


def test_bot_pr_excluded():
    assert is_bot_pr(pr("dependabot[bot]", "Bump lodash from 4 to 5"))
    assert is_bot_pr(pr("renovate[bot]", "Update dependency react"))
    assert is_bot_pr(pr("github-actions[bot]", "ci fix"))
    assert is_bot_pr(pr("pre-commit-ci[bot]", "autofix"))


def test_bot_title_patterns_excluded():
    assert is_bot_pr(pr("human", "chore(deps): update stuff"))
    assert is_bot_pr(pr("human", "build(deps-dev): bump pytest"))
    assert is_bot_pr(pr("human", "Bump version of requests"))


def test_human_pr_kept():
    human, excluded = split_prs(
        [pr("alice", "Fix crash on empty input"), pr("dependabot[bot]", "Bump x")]
    )
    assert len(human) == 1 and human[0]["user"]["login"] == "alice"
    assert len(excluded) == 1


def test_issue_list_excludes_prs():
    items = [
        {"number": 1, "title": "real issue"},
        {"number": 2, "title": "actually a PR", "pull_request": {"url": "x"}},
    ]
    filtered = filter_issue_items(items)
    assert [i["number"] for i in filtered] == [1]


# ---- §34.6 comments / bike-shedding ----

def comment(login, assoc="NONE"):
    return {"user": {"login": login}, "author_association": assoc}


def test_high_comments_few_unique_bike_shedding():
    issue = {"comments": 15, "labels": []}
    comments = [comment("a"), comment("b")] * 7
    result = analyze_comments(issue, comments)
    assert result["unique_commenters_count"] == 2
    assert result["bike_shedding_possible"] is True


def test_many_unique_commenters_not_bike_shedding():
    issue = {"comments": 12, "labels": []}
    comments = [comment(f"user{i}") for i in range(12)]
    result = analyze_comments(issue, comments)
    assert result["unique_commenters_count"] == 12
    assert result["bike_shedding_possible"] is False


def test_maintainer_dominated_marked():
    issue = {"comments": 12, "labels": []}
    comments = [comment("owner1", "OWNER") for _ in range(8)] + [comment(f"u{i}") for i in range(4)]
    result = analyze_comments(issue, comments)
    assert result["maintainer_comment_ratio"] >= 0.6
    assert result["bike_shedding_possible"] is True


def test_bot_comments_counted_separately():
    issue = {"comments": 3, "labels": []}
    comments = [comment("a"), comment("stale[bot]"), comment("b")]
    result = analyze_comments(issue, comments)
    assert result["bot_comment_count"] == 1
    assert result["unique_commenters_count"] == 2
