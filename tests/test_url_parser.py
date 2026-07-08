# URL parser 테스트 (§34.1).
import pytest

from repo_idea_miner.url_parser import InvalidRepoURLError, parse_repo_url


def test_parse_basic():
    assert parse_repo_url("https://github.com/OWNER/REPO") == ("OWNER", "REPO")


def test_parse_variants():
    assert parse_repo_url("http://github.com/a/b.git") == ("a", "b")
    assert parse_repo_url("github.com/a/b/issues/3") == ("a", "b")
    assert parse_repo_url("https://www.github.com/a-1/b_2.c") == ("a-1", "b_2.c")


@pytest.mark.parametrize("bad", ["", "https://gitlab.com/a/b", "https://github.com/onlyowner", "not a url", None])
def test_parse_invalid(bad):
    with pytest.raises(InvalidRepoURLError):
        parse_repo_url(bad)
