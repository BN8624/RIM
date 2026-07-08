# 5개 worker(Bouncer/Scouts/Judge)의 프롬프트 생성과 mock 출력 정의 모듈.
from __future__ import annotations

import json

WORKER_ORDER = ["bouncer", "readme_scout", "pain_scout", "structure_risk_scout", "critic_judge"]

JSON_RULES = """Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
If evidence is insufficient, use "불확실" or "unknown" rather than inventing facts."""

_EVIDENCE_LIMIT = 16000


def _clip(text: str, limit: int = _EVIDENCE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[증거 패킷이 길이 제한으로 잘렸습니다]"


def build_bouncer_prompt(evidence_md: str) -> str:
    return f"""You are the Bouncer of Repo Idea Miner.
Look at the evidence packet and decide whether full analysis is worth running.
Principles: 좋은 레포를 너무 빨리 버리면 안 된다. 불확실하면 PROCEED 또는 UNCERTAIN_PROCEED.
Only clearly worthless repos (empty, no signal at all) are FAST_DROP.

Schema:
{{"bouncer_decision": "PROCEED" | "FAST_DROP" | "UNCERTAIN_PROCEED", "fast_drop": true/false, "reason": "한국어로 근거"}}

{JSON_RULES}

=== EVIDENCE PACKET ===
{_clip(evidence_md)}
"""


def build_readme_scout_prompt(evidence_md: str) -> str:
    return f"""You are the README Scout of Repo Idea Miner.
From the README evidence, extract what the repo CLAIMS (not what is proven).
Separate self-promotion from verifiable substance. Answer in Korean.

Schema:
{{"claimed_core_value": "...", "readme_attractions": ["..."], "overclaim_risks": ["..."], "unverifiable_points": ["..."]}}

{JSON_RULES}

=== EVIDENCE PACKET ===
{_clip(evidence_md)}
"""


def build_pain_scout_prompt(evidence_md: str) -> str:
    return f"""You are the Pain Scout of Repo Idea Miner.
From the issue evidence, extract REAL user pain: bugs, feature requests, workflow/automation pain.
Separate noise (install/env/version conflicts, stale, duplicates). Do not overrate bike-shedding threads
(high comments but few unique commenters or maintainer-dominated debates). Answer in Korean.

Schema:
{{"user_pain": ["..."], "feature_requests": ["..."], "workflow_pain": ["..."], "noise_issues": ["..."], "bike_shedding_notes": ["..."]}}

{JSON_RULES}

=== EVIDENCE PACKET ===
{_clip(evidence_md)}
"""


def build_structure_risk_prompt(evidence_md: str) -> str:
    return f"""You are the Structure / Risk Scout of Repo Idea Miner.
From the file tree and dependency evidence, estimate implementation weight and runtime risk.
Rules: dev/test dependency와 runtime dependency를 구분한다. Dockerfile/docker-compose 존재만으로 high risk 금지.
origin이 DOCKER_LOCAL / CONFIG_ONLY이면 risk를 올리지 않는다. evidence가 없으면 "not_collected", 있는데 판단 불가면 "unknown".
Answer in Korean.

Schema:
{{"implementation_weight": "light"|"medium"|"heavy"|"unknown", "runtime_risk_level": "low"|"medium"|"high"|"unknown"|"not_collected", "runtime_risk_reason": "...", "dev_vs_runtime_notes": ["..."], "pattern_poc_feasibility": "가능"|"불가능"|"불확실"}}

{JSON_RULES}

=== EVIDENCE PACKET ===
{_clip(evidence_md)}
"""


JUDGE_SCHEMA_EXAMPLE = {
    "verdict": "DROP",
    "fast_drop": False,
    "score": 2,
    "one_line_conclusion": "이 레포에서 가져올 핵심 패턴은 ... 이지만 현재는 DROP에 가깝다.",
    "why_people_cared": "...",
    "user_pain": ["..."],
    "feature_requests": ["..."],
    "workflow_pain": ["..."],
    "core_pattern": "...",
    "what_to_ignore": ["..."],
    "dependency_runtime_risk": {"level": "medium", "reason": "..."},
    "application": {"area": "아이디어 채굴", "related_project": "Repo Idea Miner", "reason": "..."},
    "one_day_mvp": {
        "status": "가능",
        "feature": "...",
        "input": "...",
        "output": "...",
        "excluded_scope": ["..."],
        "reason": "...",
    },
    "pattern_poc": {"status": "가능", "idea": "...", "input": "...", "output": "...", "reason": "..."},
    "issue_signal_stats": {
        "sampled_issue_count": 0,
        "classified_issue_count": 0,
        "defect_count": 0,
        "feature_request_count": 0,
        "workflow_pain_count": 0,
        "confusion_count": 0,
        "install_env_version_count": 0,
        "noise_count": 0,
        "product_pain_count": 0,
        "confidence": "medium",
    },
    "why_it_fails": ["..."],
    "why_drop_or_keep": ["..."],
    "next_action": "유사 레포 3개와 비교",
    "ceiling_rules_applied": [],
}


def build_judge_prompt(evidence_md: str, worker_outputs: dict, issue_stats: dict) -> str:
    return f"""You are the Critic / Judge of Repo Idea Miner.
Synthesize the scout outputs and evidence into a final KEEP / MAYBE / DROP verdict with score 0-10.
Rules:
- verdict: KEEP(7-10, 적용 가능 + 1일 MVP 가능), MAYBE(4-6), DROP(0-3).
- application.area must be one of: 코딩 하네스/검증, 아이디어 채굴, 업무 자동화/OCR, 게임 시뮬레이션/뷰어, 문서/카드 UI, 적용 부적합.
- one_day_mvp.status: 가능 | 축소 불가 | 불확실. pattern_poc.status: 가능 | 불가능 | 불확실.
- dependency_runtime_risk.level: low | medium | high | unknown | not_collected.
- issue_signal_stats에는 아래 제공된 DETERMINISTIC ISSUE STATS 값을 그대로 사용한다.
- why_it_fails(만들면 망하는 이유)와 why_drop_or_keep은 반드시 1개 이상.
- Answer values in Korean.

Schema (use exactly these keys):
{json.dumps(JUDGE_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== DETERMINISTIC ISSUE STATS (copy into issue_signal_stats) ===
{json.dumps(issue_stats, ensure_ascii=False)}

=== README SCOUT ===
{json.dumps(worker_outputs.get("readme_scout"), ensure_ascii=False)}

=== PAIN SCOUT ===
{json.dumps(worker_outputs.get("pain_scout"), ensure_ascii=False)}

=== STRUCTURE / RISK SCOUT ===
{json.dumps(worker_outputs.get("structure_risk_scout"), ensure_ascii=False)}

=== EVIDENCE PACKET ===
{_clip(evidence_md, 10000)}
"""


PROMPT_BUILDERS = {
    "bouncer": build_bouncer_prompt,
    "readme_scout": build_readme_scout_prompt,
    "pain_scout": build_pain_scout_prompt,
    "structure_risk_scout": build_structure_risk_prompt,
}


# ---------------------------------------------------------------- mock outputs

_MOCK_OUTPUTS: dict[str, dict] = {
    "bouncer": {
        "bouncer_decision": "PROCEED",
        "fast_drop": False,
        "reason": "mock 모드: 구조 검증을 위해 full worker를 실행한다.",
    },
    "readme_scout": {
        "claimed_core_value": "mock: README가 주장하는 핵심 가치 (구조 검증용)",
        "readme_attractions": ["mock: 설치가 간단하다고 주장", "mock: 예제가 풍부하다고 주장"],
        "overclaim_risks": ["mock: 성능 주장에 벤치마크 근거 없음"],
        "unverifiable_points": ["mock: 실제 사용자 수 확인 불가"],
    },
    "pain_scout": {
        "user_pain": ["mock: 대용량 입력에서 느려짐", "mock: 에러 메시지가 불친절함"],
        "feature_requests": ["mock: export 기능 요청"],
        "workflow_pain": ["mock: 반복 작업 자동화 요청"],
        "noise_issues": ["mock: 설치 환경 문제 이슈 다수"],
        "bike_shedding_notes": [],
    },
    "structure_risk_scout": {
        "implementation_weight": "medium",
        "runtime_risk_level": "low",
        "runtime_risk_reason": "mock: runtime 필수 외부 서비스 근거 없음",
        "dev_vs_runtime_notes": ["mock: 테스트 의존성은 dev group에 분리됨"],
        "pattern_poc_feasibility": "가능",
    },
    "critic_judge": {
        "verdict": "MAYBE",
        "fast_drop": False,
        "score": 5,
        "one_line_conclusion": "mock: 신호는 있으나 유사 레포와 비교가 필요한 MAYBE 후보다.",
        "why_people_cared": "mock: 반복 작업을 줄여주는 도구라는 기대 때문에 관심을 받았다.",
        "user_pain": ["mock: 대용량 입력에서 느려짐"],
        "feature_requests": ["mock: export 기능 요청"],
        "workflow_pain": ["mock: 반복 작업 자동화 요청"],
        "core_pattern": "mock: evidence 분리 수집 + 판정 카드 렌더링 패턴",
        "what_to_ignore": ["mock: 과장된 성능 주장"],
        "dependency_runtime_risk": {"level": "low", "reason": "mock: runtime 필수 의존성 근거 없음"},
        "application": {
            "area": "아이디어 채굴",
            "related_project": "Repo Idea Miner",
            "reason": "mock: 아이디어 채굴 파이프라인에 참고 가능",
        },
        "one_day_mvp": {
            "status": "가능",
            "feature": "mock: 단일 기능 축소 MVP",
            "input": "mock: repo URL",
            "output": "mock: 판정 카드",
            "excluded_scope": ["mock: 웹 UI"],
            "reason": "mock: 핵심 파이프라인만 축소 구현 가능",
        },
        "pattern_poc": {
            "status": "가능",
            "idea": "mock: evidence packet 패턴 PoC",
            "input": "mock: 수집 JSON",
            "output": "mock: markdown packet",
            "reason": "mock: 하루 안에 패턴 검증 가능",
        },
        "issue_signal_stats": {
            "sampled_issue_count": 5,
            "classified_issue_count": 5,
            "defect_count": 2,
            "feature_request_count": 1,
            "workflow_pain_count": 1,
            "confusion_count": 1,
            "install_env_version_count": 0,
            "noise_count": 0,
            "product_pain_count": 2,
            "confidence": "medium",
        },
        "why_it_fails": ["mock: 차별화 없이 만들면 기존 도구에 묻힌다"],
        "why_drop_or_keep": ["mock: pain 신호가 있으나 비교 검증 전"],
        "next_action": "유사 레포 3개와 비교",
        "ceiling_rules_applied": [],
    },
}


def mock_output(schema_name: str) -> dict:
    if schema_name not in _MOCK_OUTPUTS:
        raise KeyError(f"알 수 없는 worker schema: {schema_name}")
    return json.loads(json.dumps(_MOCK_OUTPUTS[schema_name]))
