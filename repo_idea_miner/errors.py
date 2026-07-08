# 프로젝트 전역 예외 계층 정의 모듈.


class RIMError(Exception):
    """Repo Idea Miner 기본 예외."""


class ConfigError(RIMError):
    """설정/환경변수 오류."""


class LLMCallError(RIMError):
    """LLM 호출 실패 (재시도 소진 포함)."""


class LLMAuthError(LLMCallError):
    """모든 key가 인증 실패."""


class LLMConfigError(LLMCallError):
    """model not found / invalid payload 등 재시도 불가 설정 오류."""


class NoAvailableKeyError(LLMCallError):
    """key pool에 사용 가능한 key가 없음."""


class GitHubError(RIMError):
    """GitHub API 오류."""


class RepoNotFoundError(GitHubError):
    """repo not found 또는 private 접근 불가."""


class GitHubAuthError(GitHubError):
    """GitHub API 인증 실패."""


class GitHubRateLimitError(GitHubError):
    """metadata도 수집 불가한 rate limit."""


class ValidationFailError(RIMError):
    """worker JSON 구조 검증 실패."""


class SecretLeakError(RIMError):
    """산출물에 secret이 남아 있음."""
