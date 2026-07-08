# secret redaction 테스트 (§34.14).
from repo_idea_miner.redaction import contains_secret, redact_text


def test_github_token_value_redacted():
    fake = "ghp_faketoken1234567890abcd"
    out = redact_text(f"token is {fake} ok", [fake])
    assert fake not in out


def test_google_key_values_redacted(fake_env):
    text = " ".join(fake_env.values())
    out = redact_text(text, list(fake_env.values()))
    for value in fake_env.values():
        assert value not in out


def test_pattern_only_redaction_without_known_values():
    text = "keys: ghp_abcdef123456789012 github_pat_ABC123456789012 AIzaSyFakeKey12345678 sk-fakekey123456789012 AQ.Ab8RfakefakefakefakeXYZ"
    out = redact_text(text)
    assert "ghp_" not in out
    assert "github_pat_" not in out
    assert "AIza" not in out
    assert "sk-" not in out
    assert "AQ." not in out


def test_contains_secret_detects(fake_env):
    assert contains_secret("x ghp_abcdef123456789012 y")
    assert contains_secret(f"leak {fake_env['GOOGLE_API_KEY_11']}", list(fake_env.values()))
    assert not contains_secret("평범한 텍스트")
