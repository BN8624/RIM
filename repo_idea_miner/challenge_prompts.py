# Challenge Mode 통합 prompt(challenge_package) 생성과 mock 고정 샘플 정의 모듈.
from __future__ import annotations

import json

_SNAPSHOT_LIMIT = 16000

JSON_RULES = """Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
If evidence is insufficient, use conservative low scores rather than inventing facts."""

# §11 공통 원칙 — 모든 Challenge Mode prompt에 포함한다.
CHALLENGE_PRINCIPLES = """너는 제품 아이디어를 추천하지 않는다.
너는 GitHub 레포에서 구현 도전 과제를 추출한다.

목표는 쉬운 앱을 만드는 것이 아니다.
목표는 원본 레포의 핵심 난이도와 상호작용을 작게 재현하는 것이다.

단순 TODO 앱, 단순 검색창, 정적 대시보드, 요약기, 링크 모음으로 축소하지 마라.

반드시 Difficulty Anchors와 Forbidden Simplifications를 명시하라.

출력은 개발자만 이해하는 추상어가 아니라,
바이브코더 사장이 이해할 수 있는 장면으로 설명하라.

architecture / abstraction / framework / pipeline / graph-based / real-time sync /
extensible system 같은 단어를 쓰려면 반드시 쉬운 설명을 붙여라."""

_SCHEMA_EXAMPLE = {
    "owner_brief": {
        "source_repo": "owner/repo",
        "what_is_this": "쉽게 말해 이게 뭔지 (한국어 한두 문장)",
        "why_people_like_it": "사람들이 왜 좋아하는지",
        "what_we_steal": "우리가 훔칠 핵심",
        "what_screen_looks_like": "화면에서 어떻게 보이는지",
        "what_user_does": ["사용자가 누르는 것 1", "사용자가 누르는 것 2"],
        "why_it_might_be_fun_or_useful": "만들면 뭐가 재밌거나 쓸모 있는지",
        "how_it_differs_from_easy_version": "그냥 쉬운 버전과 뭐가 다른지",
        "owner_clarity_score": 4,
        "owner_clarity_risk": "바이브코더가 이해하기 어려운 지점",
    },
    "screen_story": {
        "first_screen": "첫 화면 묘사",
        "user_actions": ["1. ...를 누른다", "2. ...를 입력한다"],
        "thirty_second_demo": "30초 데모 장면",
        "success_feeling": "성공했을 때 느낌",
        "failure_screen": "실패한 화면 (이렇게 되면 실패다)",
    },
    "challenge_card": {
        "source_repo": "owner/repo",
        "repo_summary": "레포 요약 (한국어)",
        "surface_features": ["겉으로 보이는 기능 1"],
        "core_interaction": {
            "actor": "누가",
            "trigger": "무엇으로 시작하고",
            "loop": "어떤 반복 루프가 돌고",
            "reward": "무엇을 얻고",
            "state_change": "상태가 어떻게 바뀌는지",
            "hard_part": "구현에서 진짜 어려운 부분",
        },
        "difficulty_anchors": ["절대 삭제하면 안 되는 핵심 난이도 1"],
        "forbidden_simplifications": ["금지되는 쉬운 축소 1"],
        "allowed_simplifications": ["허용되는 축소 1"],
        "challenge_title": "과제 제목",
        "one_line_challenge": "한 줄 과제 정의",
        "poc_30_min": "30분 PoC 범위",
        "build_1_day": "1일 빌드 범위",
        "expansion_3_day": "3일 확장 범위",
        "pass_criteria": ["통과 기준 1"],
        "failure_criteria": ["실패 기준 1"],
        "scores": {
            "difficulty_anchor_alive": 4,
            "not_too_easy": 4,
            "buildable_in_one_day": 4,
            "visual_dependency_low": 3,
            "immediate_demo_value": 4,
            "owner_clarity": 4,
            "user_taste_fit": 3,
            "reuse_potential": 3,
        },
        "final_label": "GOOD_CHALLENGE",
        "taste_risk": "사용자 취향과 어긋날 수 있는 지점",
        "implementation_prompt": "구현자에게 그대로 넘길 지시문 (목표/산출 파일/기술 제약/Difficulty Anchors/Forbidden Simplifications/Allowed Simplifications/Pass Criteria/Failure Criteria 포함)",
    },
}


def _clip(text: str, limit: int = _SNAPSHOT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[스냅샷이 길이 제한으로 잘렸습니다]"


def build_challenge_package_prompt(snapshot_md: str) -> str:
    """기본 live 호출용 통합 prompt. repo 하나당 이 호출 1회를 목표로 한다."""
    return f"""You are the Challenge Extractor of RIM Challenge Mode.

{CHALLENGE_PRINCIPLES}

라벨 규칙:
- final_label은 GOOD_CHALLENGE / TOO_EASY / TOO_BIG / NOT_MY_TASTE / STEAL_ONLY / UNCLEAR_TO_OWNER / DROP 중 하나다.
- GOOD_CHALLENGE: 작게 만들 수 있지만 핵심 난이도가 살아 있음.
- TOO_EASY: 핵심 앵커가 약한 뻔한 과제. TOO_BIG: 핵심을 살리려면 너무 큼.
- STEAL_ONLY: 전체 과제는 별로지만 UI/루프/구조 하나는 훔칠 만함.
- UNCLEAR_TO_OWNER: 바이브코더가 읽어도 뭘 만들라는 건지 감이 안 옴.
- owner_clarity_score < 3이면 GOOD_CHALLENGE를 주지 마라.
- 모든 score는 1~5 정수다.

implementation_prompt 규칙:
- 구현자(Claude/Codex/Gemma/외주)에게 복사해 바로 넘길 수 있는 완결된 한국어 지시문으로 쓴다.
- 구현 목표, 산출 파일 목록, 기술 제약, Difficulty Anchors, Forbidden Simplifications,
  Allowed Simplifications, Pass Criteria, Failure Criteria, 금지되는 쉬운 축소 버전을 반드시 포함한다.
- 기본 산출물은 index.html / style.css / app.js / README.md, 기본 제약은
  서버 없음 / DB 없음 / 로그인 없음 / 외부 API 없음 / localStorage 허용 / 모바일 브라우저 확인 가능.
- 원본 레포 성격상 CLI 과제가 더 적합하면 CLI 산출물로 바꿔도 되지만,
  그 경우 owner_brief에서 왜 CLI가 더 적합한지 설명해야 한다.

Schema (use exactly these keys):
{json.dumps(_SCHEMA_EXAMPLE, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== REPO SNAPSHOT ===
{_clip(snapshot_md)}
"""


# ---------------------------------------------------------------- mock output

def mock_challenge_package(full_name: str = "example/example", repo_url: str | None = None) -> dict:
    """mock 모드 고정 샘플. placeholder가 아니라 검증/테스트 가능한 완결 데이터다."""
    url = repo_url or f"https://github.com/{full_name}"
    return {
        "owner_brief": {
            "source_repo": full_name,
            "what_is_this": "쉽게 말하면, 사용자가 명령어를 검색해서 바로 실행하고, 실행 결과에서 다시 다음 행동으로 이어가는 작업 명령 센터다.",
            "why_people_like_it": "마우스로 메뉴를 뒤지지 않고 키보드 몇 번으로 원하는 작업이 끝나서 좋아한다.",
            "what_we_steal": "명령 검색 → 실행 → 결과 카드 → 후속 액션으로 이어지는 키보드 중심 루프.",
            "what_screen_looks_like": f"화면 중앙에 검색창 하나가 떠 있고, 입력할 때마다 아래에 명령 후보 목록이 갱신된다. ({url})",
            "what_user_does": [
                "Ctrl/Cmd+K를 눌러 명령창을 연다",
                "report를 입력해 명령을 검색한다",
                "Enter로 명령을 실행한다",
                "결과 카드에서 Copy 또는 Run follow-up을 누른다",
            ],
            "why_it_might_be_fun_or_useful": "자주 하는 작업이 3초 안에 끝나는 걸 바로 체감할 수 있다.",
            "how_it_differs_from_easy_version": "그냥 검색창은 결과를 보여주고 끝나지만, 이건 실행 결과가 카드로 남고 그 카드에서 다음 행동으로 이어진다.",
            "owner_clarity_score": 4,
            "owner_clarity_risk": "명령 실행 상태가 어떻게 저장되는지는 바이브코더가 바로 이해하기 어렵다.",
        },
        "screen_story": {
            "first_screen": "중앙에 command palette(명령 검색창)가 있고, 아래에 최근 실행 카드 목록이 보인다.",
            "user_actions": [
                "1. Ctrl/Cmd+K를 누른다",
                "2. report를 입력한다",
                "3. Create weekly report 명령을 선택한다",
                "4. 결과 카드가 생성된다",
                "5. 카드에서 Copy, Save, Run follow-up을 누른다",
            ],
            "thirty_second_demo": "명령창을 열고 report를 입력해 실행하면 결과 카드가 쌓이고, 카드에서 후속 명령을 한 번 더 실행해 보인다.",
            "success_feeling": "키보드에서 손을 떼지 않고 일이 끝났다는 속도감.",
            "failure_screen": "검색창만 있고 실행 결과 카드가 없으면 실패다.",
        },
        "challenge_card": {
            "source_repo": full_name,
            "repo_summary": "키보드 중심 command launcher. 명령을 검색·실행하고 결과 카드에서 후속 액션으로 이어간다.",
            "surface_features": [
                "명령 검색창(command palette)",
                "명령 실행",
                "실행 결과 카드 표시",
                "결과 카드의 후속 액션 버튼",
            ],
            "core_interaction": {
                "actor": "키보드 중심 사용자",
                "trigger": "Ctrl/Cmd+K로 명령창을 연다",
                "loop": "검색 → 선택 → 실행 → 결과 카드 → 후속 액션 → 다시 검색",
                "reward": "실행 결과가 카드로 즉시 쌓인다",
                "state_change": "실행 이력과 결과 카드가 localStorage에 누적된다",
                "hard_part": "입력할 때마다 갱신되는 명령 매칭과, 결과 카드에서 이어지는 후속 액션 연결",
            },
            "difficulty_anchors": [
                "키보드 중심 명령 검색 (입력 즉시 후보 갱신, 방향키 선택)",
                "명령 실행과 실행 상태 변화",
                "실행 결과 카드 표시",
                "결과 카드에서 후속 액션 제공",
            ],
            "forbidden_simplifications": [
                "단순 검색창으로 만들지 말 것",
                "링크 모음으로 만들지 말 것",
                "정적 메뉴판으로 만들지 말 것",
                "TODO 앱으로 바꾸지 말 것",
            ],
            "allowed_simplifications": [
                "명령 종류는 내장 명령 5개로 제한해도 된다",
                "테마/설정 화면은 생략해도 된다",
            ],
            "challenge_title": "키보드 명령 센터 미니 구현",
            "one_line_challenge": "Ctrl/Cmd+K로 여는 명령창에서 명령을 검색·실행하고 결과 카드에서 후속 액션으로 이어지는 루프를 재현하라.",
            "poc_30_min": "명령창 열기 + 하드코딩된 명령 3개 검색/선택/실행 로그 출력.",
            "build_1_day": "결과 카드 렌더링 + 카드별 Copy/Run follow-up + localStorage 이력 저장까지 완성.",
            "expansion_3_day": "명령 정의를 JSON으로 분리하고 카드 타입별 렌더러와 검색 랭킹을 추가.",
            "pass_criteria": [
                "키보드만으로 명령 검색→실행→후속 액션이 이어진다",
                "실행 결과가 카드로 화면에 남는다",
                "새로고침 후에도 실행 이력이 유지된다",
            ],
            "failure_criteria": [
                "검색창만 있고 실행 결과 카드가 없다",
                "마우스 없이는 명령을 실행할 수 없다",
                "실행해도 화면 상태가 바뀌지 않는다",
            ],
            "scores": {
                "difficulty_anchor_alive": 4,
                "not_too_easy": 4,
                "buildable_in_one_day": 4,
                "visual_dependency_low": 4,
                "immediate_demo_value": 4,
                "owner_clarity": 4,
                "user_taste_fit": 4,
                "reuse_potential": 4,
            },
            "final_label": "GOOD_CHALLENGE",
            "taste_risk": "명령 launcher 자체에 흥미가 없으면 데모가 밋밋하게 느껴질 수 있다.",
            "implementation_prompt": (
                "너는 아래 Challenge Card를 구현한다.\n"
                "\n"
                "구현 목표: Ctrl/Cmd+K로 여는 명령창에서 명령을 검색·실행하고, "
                "실행 결과 카드에서 후속 액션으로 이어지는 키보드 중심 명령 센터를 만든다.\n"
                "\n"
                "산출 파일: index.html, style.css, app.js, README.md\n"
                "\n"
                "기술 제약: 서버 없음, DB 없음, 로그인 없음, 외부 API 없음, "
                "localStorage 허용, 모바일 브라우저에서 확인 가능.\n"
                "\n"
                "Difficulty Anchors (절대 삭제 금지):\n"
                "- 키보드 중심 명령 검색 (입력 즉시 후보 갱신, 방향키 선택)\n"
                "- 명령 실행과 실행 상태 변화\n"
                "- 실행 결과 카드 표시\n"
                "- 결과 카드에서 후속 액션 제공\n"
                "\n"
                "Forbidden Simplifications (위반 금지):\n"
                "- 단순 검색창으로 만들지 말 것\n"
                "- 링크 모음으로 만들지 말 것\n"
                "- 정적 메뉴판으로 만들지 말 것\n"
                "- TODO 앱으로 바꾸지 말 것\n"
                "\n"
                "Allowed Simplifications:\n"
                "- 명령 종류는 내장 명령 5개로 제한해도 된다\n"
                "- 테마/설정 화면은 생략해도 된다\n"
                "\n"
                "Pass Criteria:\n"
                "- 키보드만으로 명령 검색→실행→후속 액션이 이어진다\n"
                "- 실행 결과가 카드로 화면에 남는다\n"
                "- 새로고침 후에도 실행 이력이 유지된다\n"
                "\n"
                "Failure Criteria (하나라도 해당하면 실패):\n"
                "- 검색창만 있고 실행 결과 카드가 없다\n"
                "- 마우스 없이는 명령을 실행할 수 없다\n"
                "- 실행해도 화면 상태가 바뀌지 않는다\n"
            ),
        },
    }
