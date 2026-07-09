# Product Factory Desk별 prompt 생성과 mock 고정 workspace 샘플 정의 모듈 (§7, §10, §20).
from __future__ import annotations

import json

JSON_RULES = """Return only valid JSON.
Do not wrap JSON in markdown fences.
Do not include explanations outside JSON.
Use the exact schema.
Answer text fields in Korean."""

FACTORY_PRINCIPLES = """너는 RIM Product Factory의 Desk 작업자다.
Challenge Card의 Difficulty Anchors는 절대 제거하지 마라.
Forbidden Simplifications를 위반하지 마라.
단순 TODO/검색창/정적 대시보드로 축소하지 마라.
사용자 행동과 상태 변화가 실제 코드에 존재해야 한다.
사람에게 질문하지 마라. 스스로 결정하고 결과만 내라."""

_MICRO_NOTE = """이 작업은 micro-workspace 라인이다 (STEAL_ONLY).
전체 제품을 만들지 마라. 훔칠 수 있는 핵심 루프/상호작용/구조 1개만 작게 구현한다.
그 핵심 루프의 Difficulty Anchor는 반드시 살아 있어야 한다."""


def _clip(text: str, limit: int = 14000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[길이 제한으로 잘렸습니다]"


def _line_note(line: str) -> str:
    return _MICRO_NOTE if line == "micro" else ""


# ---------------------------------------------------------------- schema 예시

_PRODUCT_BRIEF_SCHEMA = {
    "product_goal": "제품 목표 (한두 문장)",
    "target_user": "누가 쓰는가",
    "core_loop": "핵심 사용 루프 (행동 → 결과 → 다음 행동)",
    "first_screen_goal": "첫 화면에서 사용자가 바로 할 수 있는 것",
    "can_reduce": ["줄여도 되는 것 1"],
    "must_not_reduce": ["줄이면 안 되는 것 1 (Difficulty Anchor 기반)"],
}

_UX_SPEC_SCHEMA = {
    "ux_flow": {
        "first_screen": "첫 화면 묘사",
        "screens": ["주요 화면 1", "주요 화면 2"],
        "user_actions": ["1. 사용자가 ...를 누른다", "2. ..."],
        "state_changes": ["...를 누르면 ...가 ...로 바뀐다"],
        "success_screen": "성공 화면 묘사",
        "failure_screen": "실패 화면 묘사 (이렇게 되면 실패)",
        "thirty_second_demo": "30초 데모 흐름",
    },
    "screen_spec": [
        {"name": "화면 이름", "purpose": "화면 목적", "elements": ["요소 1", "요소 2"]}
    ],
    "state_transitions": [
        {"trigger": "사용자 행동", "from_state": "이전 상태", "to_state": "다음 상태", "effect": "화면 변화"}
    ],
}

_TECHNICAL_SPEC_SCHEMA = {
    "technical_plan": "구현 계획 (markdown 본문, 한국어)",
    "manifest": {
        "project_type": "static_web | python_cli | node_cli",
        "entrypoint": "index.html",
        "run_command": "python -m http.server 8000",
        "install_command": None,
        "check_commands": ["python checks/check_structure.py"],
        "files": [{"path": "index.html", "role": "entrypoint 화면"}, {"path": "src/app.js", "role": "이벤트 배선"}],
        "forbidden_files": [".env", "node_modules"],
    },
    "contract": {
        "entrypoint": "index.html",
        "required_files": ["index.html", "src/app.js"],
        "connections": [{"source": "index.html", "target": "src/app.js"}],
        "modules": [{"path": "src/app.js", "role": "이벤트 배선"}],
        "state_model": "상태가 어디에 어떻게 저장되고 무엇으로 바뀌는지",
        "core_interactions": ["핵심 상호작용 1"],
        "difficulty_anchor_requirements": [
            {"anchor": "anchor 원문", "expected_files": ["src/app.js"], "expected_markers": ["함수/식별자"]}
        ],
        "forbidden_simplification_rules": ["금지 규칙 원문"],
    },
    "build_task_packet": "Build Desk에 넘길 작업 지시 (파일별 목표 포함)",
}

_BUILD_OUTPUT_SCHEMA = {
    "files": [{"path": "src/app.js", "content": "파일 전체 내용"}],
    "build_report": "이번 빌드에서 만든 것/미룬 것 요약",
}

_DEBUG_OUTPUT_SCHEMA = {
    "files": [{"path": "src/app.js", "content": "수정된 파일 전체 내용"}],
    "debug_report": "실패 원인과 고친 방법",
}

_QA_OUTPUT_SCHEMA = {
    "anchors": [{"anchor": "anchor 원문", "alive": True, "evidence": "코드 근거 (파일/함수)"}],
    "forbidden": [{"rule": "금지 규칙 원문", "violated": False, "evidence": "근거"}],
    "is_degenerate": False,
    "degeneration_reason": "단순 TODO/검색창/정적 대시보드로 퇴화했는지 근거",
    "has_user_action": True,
    "has_state_change": True,
    "has_runnable_artifact": True,
    "summary": "QA 요약",
}

_JUDGE_OUTPUT_SCHEMA = {
    "verdict": "PROMOTE_TO_CODEX | KEEP_CANDIDATE | NEEDS_MORE_GEMMA_LOOP | TOO_WEAK | DROP",
    "reasons": ["판정 근거 1"],
    "strengths": ["강점 1"],
    "weaknesses": ["약점 1"],
    "next_goal": "다음 loop 또는 Codex/Claude가 이어서 할 목표",
}


# ---------------------------------------------------------------- prompt builders

def build_product_brief_prompt(challenge_context: str, line: str = "standard") -> str:
    return f"""You are the Product Planning Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}
{_line_note(line)}
Challenge Card를 제품 기획(product_brief)으로 바꿔라.
제품 목표 / 사용자 / 핵심 사용 루프 / 첫 화면 목표 / 줄여도 되는 것 / 줄이면 안 되는 것을 반드시 채워라.
줄이면 안 되는 것에는 Difficulty Anchors가 반영되어야 한다.

Schema (use exactly these keys):
{json.dumps(_PRODUCT_BRIEF_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CHALLENGE ===
{_clip(challenge_context)}
"""


def build_ux_spec_prompt(challenge_context: str, product_brief_md: str, line: str = "standard") -> str:
    return f"""You are the UX/Spec Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}
{_line_note(line)}
화면 흐름과 사용자 행동, 상태 변화를 정의하라.
정적 설명만 있으면 실패다. 반드시 사용자가 무엇을 누르고 그 결과가 어떻게 바뀌는지 써라.
첫 화면 / 주요 화면 / 사용자 행동 / 상태 변화 / 성공 화면 / 실패 화면 / 30초 데모를 모두 채워라.

Schema (use exactly these keys):
{json.dumps(_UX_SPEC_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CHALLENGE ===
{_clip(challenge_context, 8000)}

=== PRODUCT BRIEF ===
{_clip(product_brief_md, 4000)}
"""


def build_technical_spec_prompt(
    challenge_context: str, product_brief_md: str, ux_flow_md: str, line: str = "standard"
) -> str:
    return f"""You are the Technical Spec Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}
{_line_note(line)}
멀티파일 workspace 구조와 구현 계약(manifest/contract)을 만들어라.

규칙:
- src 파일은 2개 이상이어야 한다. 단일파일 구조는 실패다.
- manifest.files의 모든 파일이 실제로 만들어질 파일 목록이다.
- entrypoint에서 모든 src 모듈이 import/참조로 도달 가능해야 한다.
- difficulty_anchor_requirements에는 anchor별 담당 파일과 코드 마커(함수명 등)를 명시하라.
- project_type이 static_web이면 entrypoint는 html, run_command는 static server 명령으로 하라.
- 외부 패키지 의존성이 없으면 install_command는 null로 두라.
- check_commands에는 구조를 검증하는 스크립트 실행 명령을 넣어라 (예: python checks/check_structure.py).

Schema (use exactly these keys):
{json.dumps(_TECHNICAL_SPEC_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CHALLENGE ===
{_clip(challenge_context, 8000)}

=== PRODUCT BRIEF ===
{_clip(product_brief_md, 3000)}

=== UX FLOW ===
{_clip(ux_flow_md, 4000)}
"""


def build_build_prompt(
    challenge_context: str,
    manifest_json: str,
    contract_json: str,
    build_task_packet: str,
    file_tree: list[str],
    line: str = "standard",
) -> str:
    return f"""You are the Build Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}
{_line_note(line)}
contract와 build_task_packet에 맞춰 멀티파일 workspace 파일들을 생성하라.

규칙:
- manifest.files에 있는 모든 파일 + README.md + run_instructions.md + checks/ 스크립트를 만들어라.
- 파일 내용은 placeholder가 아니라 실제로 동작하는 완결 코드여야 한다.
- entrypoint에서 모든 src 모듈이 import/참조되어야 한다 (연결 안 된 파일 금지).
- difficulty_anchor_requirements의 expected_markers(함수명 등)를 해당 파일에 실제로 구현하라.
- 사용자 입력/버튼과 상태 변화가 실제 코드에 있어야 한다.
- 외부 API/서버/DB/로그인 없이 동작해야 한다.
- checks/ 스크립트는 필수 파일과 마커 존재를 검사하고 실패 시 exit code 1을 내야 한다.

Schema (use exactly these keys):
{json.dumps(_BUILD_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CHALLENGE ===
{_clip(challenge_context, 6000)}

=== MANIFEST ===
{_clip(manifest_json, 3000)}

=== CONTRACT ===
{_clip(contract_json, 4000)}

=== BUILD TASK PACKET ===
{_clip(build_task_packet, 3000)}

=== CURRENT FILE TREE ===
{json.dumps(file_tree, ensure_ascii=False)}
"""


def build_debug_prompt(
    error_log: str,
    file_tree: list[str],
    key_files: dict[str, str],
    contract_json: str,
    attempt: int,
    max_attempts: int,
) -> str:
    files_md = "\n\n".join(f"--- {path} ---\n{_clip(content, 4000)}" for path, content in key_files.items())
    return f"""You are the Debug Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}

검증 실패 로그를 보고 문제 파일만 고쳐라. (시도 {attempt}/{max_attempts})

규칙:
- 전체 프로젝트를 다시 쓰지 마라. 실패 원인이 된 파일만 전체 내용으로 교체하라.
- 이전에 통과한 구조(green base)를 깨지 마라.
- contract의 anchor 마커와 연결 관계를 유지하라.
- files에는 수정이 필요한 파일만 넣어라 (1~3개 권장).

Schema (use exactly these keys):
{json.dumps(_DEBUG_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== FAILURE LOG ===
{_clip(error_log, 5000)}

=== CONTRACT ===
{_clip(contract_json, 3000)}

=== FILE TREE ===
{json.dumps(file_tree, ensure_ascii=False)}

=== KEY FILES ===
{files_md}
"""


def build_qa_prompt(
    anchors: list[str],
    forbidden: list[str],
    file_tree: list[str],
    key_files: dict[str, str],
    gate_summary_md: str,
) -> str:
    files_md = "\n\n".join(f"--- {path} ---\n{_clip(content, 3500)}" for path, content in key_files.items())
    return f"""You are the QA Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}

결과물이 Challenge의 핵심을 지켰는지 검사하라.
아래 anchors/forbidden 각각에 대해 코드 근거를 들어 판정하라. 근거 없이 통과시키지 마라.

검사 항목:
- Difficulty Anchors가 실제 코드에 살아 있는가 (파일/함수 근거 필수)
- Forbidden Simplifications를 위반하지 않았는가
- 단순 TODO/검색창/정적 대시보드로 퇴화하지 않았는가
- 사용자 행동과 상태 변화가 있는가
- README만 있고 실행물이 없는 상태가 아닌가

Schema (use exactly these keys):
{json.dumps(_QA_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== DIFFICULTY ANCHORS ===
{json.dumps(anchors, ensure_ascii=False, indent=1)}

=== FORBIDDEN SIMPLIFICATIONS ===
{json.dumps(forbidden, ensure_ascii=False, indent=1)}

=== GATE RESULTS ===
{_clip(gate_summary_md, 3000)}

=== FILE TREE ===
{json.dumps(file_tree, ensure_ascii=False)}

=== KEY FILES ===
{files_md}
"""


def build_judge_prompt(
    challenge_context: str,
    gate_summary_md: str,
    qa_report_md: str,
    debug_count: int,
    line: str = "standard",
) -> str:
    micro_rule = (
        "\n- 이 run은 micro-workspace 라인(STEAL_ONLY)이다. 기본적으로 KEEP_CANDIDATE를 우선하고,"
        "\n  결과물이 매우 좋고 구조가 명확할 때만 PROMOTE_TO_CODEX를 줘라."
        if line == "micro"
        else ""
    )
    return f"""You are the Judge Desk of RIM Product Factory.

{FACTORY_PRINCIPLES}

이 workspace를 Gemma Factory 안에서 더 키울지, 버릴지, Codex/Claude로 승격할지 판정하라.

라벨 규칙:
- PROMOTE_TO_CODEX: 모든 gate와 QA를 통과했고 Codex/Claude가 제품화/확장할 가치가 있음.
- KEEP_CANDIDATE: 지금 승격은 아니지만 보관 가치 있음.
- NEEDS_MORE_GEMMA_LOOP: 가능성은 있으나 문법/구조/실행/상호작용 중 하나가 부족함.
- TOO_WEAK: 실행은 되지만 제품 느낌이 약함.
- DROP: 버림.
- gate나 QA가 실패했으면 PROMOTE_TO_CODEX를 주지 마라.{micro_rule}

Schema (use exactly these keys):
{json.dumps(_JUDGE_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CHALLENGE ===
{_clip(challenge_context, 5000)}

=== GATE RESULTS ===
{_clip(gate_summary_md, 3000)}

=== QA REPORT ===
{_clip(qa_report_md, 4000)}

=== DEBUG LOOP COUNT ===
{debug_count}
"""


# ---------------------------------------------------------------- mock 출력 (§20: 테스트 가능한 고정 workspace)

MOCK_ANCHORS = [
    "키보드 중심 명령 검색 (입력 즉시 후보 갱신, 방향키 선택)",
    "명령 실행과 실행 상태 변화",
    "실행 결과 카드 표시",
    "결과 카드에서 후속 액션 제공",
]

MOCK_FORBIDDEN = [
    "단순 검색창으로 만들지 말 것",
    "링크 모음으로 만들지 말 것",
    "정적 메뉴판으로 만들지 말 것",
    "TODO 앱으로 바꾸지 말 것",
]


def mock_product_brief() -> dict:
    return {
        "product_goal": "키보드만으로 명령을 검색·실행하고 결과 카드에서 후속 액션으로 이어지는 명령 센터를 만든다.",
        "target_user": "마우스 없이 빠르게 반복 작업을 처리하고 싶은 키보드 중심 사용자.",
        "core_loop": "검색 → 후보 선택 → 실행 → 결과 카드 → 후속 액션 → 다시 검색.",
        "first_screen_goal": "입력창에 글자를 치는 즉시 명령 후보가 갱신되고 Enter로 바로 실행할 수 있다.",
        "can_reduce": ["명령 종류는 내장 명령 5개로 제한", "테마/설정 화면 생략"],
        "must_not_reduce": MOCK_ANCHORS,
    }


def mock_ux_spec() -> dict:
    return {
        "ux_flow": {
            "first_screen": "중앙에 명령 검색창, 아래에 후보 목록과 실행 결과 카드 영역이 있다.",
            "screens": ["명령 검색 화면", "결과 카드 목록"],
            "user_actions": [
                "1. 검색창에 report를 입력한다",
                "2. 방향키로 후보를 고르고 Enter를 누른다",
                "3. 결과 카드의 후속 액션 버튼을 누른다",
            ],
            "state_changes": [
                "입력할 때마다 후보 목록이 갱신된다",
                "Enter를 누르면 결과 카드가 목록 맨 위에 추가된다",
                "후속 액션을 누르면 새 카드가 이어서 생성되고 이력이 저장된다",
            ],
            "success_screen": "결과 카드가 쌓여 있고 각 카드에 후속 액션 버튼이 살아 있다.",
            "failure_screen": "검색창만 있고 실행해도 화면이 바뀌지 않으면 실패다.",
            "thirty_second_demo": "report 입력 → Enter 실행 → 카드 생성 → 후속 액션 실행 → 카드가 이어짐.",
        },
        "screen_spec": [
            {
                "name": "명령 검색 화면",
                "purpose": "명령을 즉시 검색하고 실행한다",
                "elements": ["검색 입력창", "후보 목록", "선택 하이라이트"],
            },
            {
                "name": "결과 카드 목록",
                "purpose": "실행 결과를 카드로 남기고 후속 액션을 제공한다",
                "elements": ["결과 카드", "후속 액션 버튼", "실행 시각"],
            },
        ],
        "state_transitions": [
            {"trigger": "글자 입력", "from_state": "후보 없음", "to_state": "후보 갱신됨", "effect": "후보 목록이 다시 그려진다"},
            {"trigger": "Enter", "from_state": "후보 선택됨", "to_state": "실행됨", "effect": "결과 카드가 추가되고 이력이 저장된다"},
            {"trigger": "후속 액션 클릭", "from_state": "실행됨", "to_state": "후속 실행됨", "effect": "연결된 카드가 추가된다"},
        ],
    }


_MOCK_MANIFEST = {
    "project_type": "static_web",
    "entrypoint": "index.html",
    "run_command": "python -m http.server 8000",
    "install_command": None,
    "check_commands": ["python checks/check_structure.py"],
    "files": [
        {"path": "index.html", "role": "entrypoint 화면 (검색창/후보/카드 영역)"},
        {"path": "src/app.js", "role": "이벤트 배선과 키보드 처리"},
        {"path": "src/commands.js", "role": "명령 정의와 검색 매칭"},
        {"path": "src/state.js", "role": "실행 이력 상태 모델 (localStorage)"},
        {"path": "src/render.js", "role": "후보 목록·결과 카드·후속 액션 렌더링"},
        {"path": "src/style.css", "role": "화면 스타일"},
    ],
    "forbidden_files": [".env", "node_modules"],
}

_MOCK_CONTRACT = {
    "entrypoint": "index.html",
    "required_files": [
        "index.html",
        "src/app.js",
        "src/commands.js",
        "src/state.js",
        "src/render.js",
    ],
    "connections": [
        {"source": "index.html", "target": "src/app.js"},
        {"source": "src/app.js", "target": "src/commands.js"},
        {"source": "src/app.js", "target": "src/state.js"},
        {"source": "src/app.js", "target": "src/render.js"},
    ],
    "modules": [
        {"path": "src/app.js", "role": "이벤트 배선"},
        {"path": "src/commands.js", "role": "명령 검색 매칭"},
        {"path": "src/state.js", "role": "상태 모델"},
        {"path": "src/render.js", "role": "카드 렌더링"},
    ],
    "state_model": "실행 이력 배열(history)이 localStorage에 저장되고, 명령 실행/후속 액션마다 카드가 추가된다.",
    "core_interactions": [
        "입력 즉시 명령 후보 갱신",
        "Enter로 명령 실행 → 결과 카드 추가",
        "결과 카드의 후속 액션 실행 → 카드 연결",
    ],
    "difficulty_anchor_requirements": [
        {"anchor": MOCK_ANCHORS[0], "expected_files": ["src/commands.js", "src/app.js"], "expected_markers": ["filterCommands"]},
        {"anchor": MOCK_ANCHORS[1], "expected_files": ["src/state.js"], "expected_markers": ["executeCommand"]},
        {"anchor": MOCK_ANCHORS[2], "expected_files": ["src/render.js"], "expected_markers": ["renderCards"]},
        {"anchor": MOCK_ANCHORS[3], "expected_files": ["src/render.js"], "expected_markers": ["followUp"]},
    ],
    "forbidden_simplification_rules": MOCK_FORBIDDEN,
}


def mock_technical_spec() -> dict:
    return {
        "technical_plan": (
            "## 구현 계획\n\n"
            "- static_web 구조. index.html이 src/app.js(ES module)를 로드한다.\n"
            "- src/commands.js: 내장 명령 5개와 filterCommands(query) 매칭.\n"
            "- src/state.js: executeCommand로 이력 추가, localStorage 저장/복원.\n"
            "- src/render.js: 후보 목록 renderCandidates, 결과 카드 renderCards, followUp 액션.\n"
            "- src/app.js: input/keydown 이벤트 배선, 방향키 선택, Enter 실행.\n"
            "- checks/check_structure.py: 필수 파일·anchor 마커 존재 검사.\n"
        ),
        "manifest": json.loads(json.dumps(_MOCK_MANIFEST)),
        "contract": json.loads(json.dumps(_MOCK_CONTRACT)),
        "build_task_packet": (
            "Level 1 목표: manifest.files의 6개 파일 + README.md + run_instructions.md + "
            "checks/check_structure.py를 생성한다. entrypoint에서 모든 src 모듈이 도달 가능해야 하며, "
            "filterCommands/executeCommand/renderCards/followUp 마커가 실제 구현이어야 한다."
        ),
    }


_MOCK_INDEX_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Command Center Mini</title>
<link rel="stylesheet" href="src/style.css">
</head>
<body>
<main>
  <h1>Command Center Mini</h1>
  <input id="command-input" type="text" placeholder="명령을 검색하세요 (예: report)" autocomplete="off" autofocus>
  <ul id="command-list"></ul>
  <section id="result-cards"></section>
</main>
<script type="module" src="src/app.js"></script>
</body>
</html>
"""

_MOCK_COMMANDS_JS = """// 내장 명령 정의와 검색 매칭 모듈.
export const COMMANDS = [
  { id: "report", title: "Create weekly report", output: "주간 리포트 초안이 생성되었습니다.", followUps: ["copy", "rerun"] },
  { id: "note", title: "New quick note", output: "빈 메모가 생성되었습니다.", followUps: ["copy"] },
  { id: "timer", title: "Start focus timer", output: "25분 집중 타이머가 시작되었습니다.", followUps: ["rerun"] },
  { id: "clean", title: "Clean downloads", output: "다운로드 폴더 정리 목록이 만들어졌습니다.", followUps: ["copy", "rerun"] },
  { id: "share", title: "Share status", output: "상태 공유 메시지가 준비되었습니다.", followUps: ["copy"] },
];

export function filterCommands(query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return COMMANDS.slice(0, 5);
  return COMMANDS.filter(
    (c) => c.id.includes(q) || c.title.toLowerCase().includes(q)
  );
}
"""

_MOCK_STATE_JS = """// 실행 이력 상태 모델: executeCommand로 카드를 추가하고 localStorage에 저장한다.
const STORAGE_KEY = "command-center-history";

export function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

export function saveHistory(history) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
}

export function executeCommand(history, command, sourceCardId = null) {
  const card = {
    cardId: Date.now() + "-" + Math.random().toString(36).slice(2, 7),
    commandId: command.id,
    title: command.title,
    output: command.output,
    followUps: command.followUps,
    sourceCardId,
    executedAt: new Date().toISOString(),
  };
  const next = [card, ...history];
  saveHistory(next);
  return next;
}
"""

_MOCK_RENDER_JS = """// 후보 목록·결과 카드·후속 액션 렌더링 모듈.
export function renderCandidates(listEl, candidates, selectedIndex) {
  listEl.innerHTML = "";
  candidates.forEach((c, i) => {
    const li = document.createElement("li");
    li.textContent = c.title;
    li.dataset.commandId = c.id;
    if (i === selectedIndex) li.classList.add("selected");
    listEl.appendChild(li);
  });
}

export function renderCards(cardsEl, history, onFollowUp) {
  cardsEl.innerHTML = "";
  history.forEach((card) => {
    const article = document.createElement("article");
    article.className = "result-card";
    const h3 = document.createElement("h3");
    h3.textContent = card.title;
    const p = document.createElement("p");
    p.textContent = card.output;
    const meta = document.createElement("small");
    meta.textContent = card.executedAt + (card.sourceCardId ? " (후속 실행)" : "");
    article.append(h3, p, meta);
    (card.followUps || []).forEach((followUp) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = followUp === "copy" ? "결과 복사" : "다시 실행";
      btn.addEventListener("click", () => onFollowUp(card, followUp));
      article.appendChild(btn);
    });
    cardsEl.appendChild(article);
  });
}
"""

_MOCK_APP_JS = """// 이벤트 배선: 입력 즉시 후보 갱신, 방향키 선택, Enter 실행, 후속 액션 연결.
import { COMMANDS, filterCommands } from "./commands.js";
import { loadHistory, executeCommand } from "./state.js";
import { renderCandidates, renderCards } from "./render.js";

const input = document.getElementById("command-input");
const listEl = document.getElementById("command-list");
const cardsEl = document.getElementById("result-cards");

let history = loadHistory();
let candidates = filterCommands("");
let selectedIndex = 0;

function onFollowUp(card, followUp) {
  if (followUp === "copy" && navigator.clipboard) {
    navigator.clipboard.writeText(card.output).catch(() => {});
    return;
  }
  const command = COMMANDS.find((c) => c.id === card.commandId);
  if (command) {
    history = executeCommand(history, command, card.cardId);
    renderCards(cardsEl, history, onFollowUp);
  }
}

function refresh() {
  renderCandidates(listEl, candidates, selectedIndex);
  renderCards(cardsEl, history, onFollowUp);
}

input.addEventListener("input", () => {
  candidates = filterCommands(input.value);
  selectedIndex = 0;
  renderCandidates(listEl, candidates, selectedIndex);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") {
    selectedIndex = Math.min(selectedIndex + 1, candidates.length - 1);
    renderCandidates(listEl, candidates, selectedIndex);
    event.preventDefault();
  } else if (event.key === "ArrowUp") {
    selectedIndex = Math.max(selectedIndex - 1, 0);
    renderCandidates(listEl, candidates, selectedIndex);
    event.preventDefault();
  } else if (event.key === "Enter" && candidates[selectedIndex]) {
    history = executeCommand(history, candidates[selectedIndex]);
    renderCards(cardsEl, history, onFollowUp);
    input.select();
    event.preventDefault();
  }
});

refresh();
"""

_MOCK_STYLE_CSS = """main { max-width: 640px; margin: 40px auto; font-family: system-ui, sans-serif; }
#command-input { width: 100%; font-size: 1.1rem; padding: 12px; box-sizing: border-box; }
#command-list { list-style: none; padding: 0; margin: 8px 0; }
#command-list li { padding: 8px 12px; border-radius: 8px; }
#command-list li.selected { background: #2563eb; color: #fff; }
.result-card { border: 1px solid #d1d5db; border-radius: 12px; padding: 12px; margin: 10px 0; }
.result-card button { margin-right: 8px; margin-top: 6px; }
"""

_MOCK_CHECK_STRUCTURE_PY = """# workspace 구조와 anchor 마커 존재를 검사하는 스크립트. 실패 시 exit code 1.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "index.html",
    "src/app.js",
    "src/commands.js",
    "src/state.js",
    "src/render.js",
]

MARKERS = {
    "src/commands.js": "filterCommands",
    "src/state.js": "executeCommand",
    "src/render.js": "renderCards",
}

def main() -> int:
    problems = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            problems.append(f"missing file: {rel}")
    for rel, marker in MARKERS.items():
        p = ROOT / rel
        if p.is_file() and marker not in p.read_text(encoding="utf-8", errors="replace"):
            problems.append(f"missing marker {marker} in {rel}")
    if problems:
        for prob in problems:
            print("FAIL:", prob)
        return 1
    print("structure check pass")
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""

_MOCK_README = """# Command Center Mini

키보드만으로 명령을 검색·실행하고 결과 카드에서 후속 액션으로 이어지는 명령 센터 데모.

## 핵심 루프
검색 → 방향키 선택 → Enter 실행 → 결과 카드 → 후속 액션 → 다시 검색

## 구조
- index.html — entrypoint 화면
- src/app.js — 이벤트 배선 (입력/방향키/Enter)
- src/commands.js — 명령 정의와 검색 매칭 (filterCommands)
- src/state.js — 실행 이력 상태 모델 (executeCommand, localStorage)
- src/render.js — 후보 목록·결과 카드·후속 액션 렌더링
- checks/check_structure.py — 구조 검사 스크립트
"""

_MOCK_RUN_INSTRUCTIONS = """# 실행 방법

## 실행
```bash
python -m http.server 8000
```
브라우저에서 http://localhost:8000/index.html 을 연다.

## 검증
```bash
python checks/check_structure.py
```

## 30초 데모
1. 검색창에 report를 입력한다.
2. Enter를 눌러 실행한다 — 결과 카드가 추가된다.
3. 카드의 "다시 실행"을 눌러 후속 카드가 이어지는 것을 확인한다.
4. 새로고침해도 이력이 유지된다 (localStorage).
"""


def mock_build_output() -> dict:
    return {
        "files": [
            {"path": "index.html", "content": _MOCK_INDEX_HTML},
            {"path": "src/app.js", "content": _MOCK_APP_JS},
            {"path": "src/commands.js", "content": _MOCK_COMMANDS_JS},
            {"path": "src/state.js", "content": _MOCK_STATE_JS},
            {"path": "src/render.js", "content": _MOCK_RENDER_JS},
            {"path": "src/style.css", "content": _MOCK_STYLE_CSS},
            {"path": "checks/check_structure.py", "content": _MOCK_CHECK_STRUCTURE_PY},
            {"path": "README.md", "content": _MOCK_README},
            {"path": "run_instructions.md", "content": _MOCK_RUN_INSTRUCTIONS},
        ],
        "build_report": (
            "Level 1 빌드 완료: entrypoint + src 5개 파일 + checks 1개. "
            "filterCommands/executeCommand/renderCards/followUp 마커 구현. 미룬 것: 검색 랭킹 고도화."
        ),
    }


def mock_broken_build_output() -> dict:
    """Debug Desk 테스트용: src/app.js에 일부러 문법 오류를 넣은 빌드."""
    out = mock_build_output()
    broken = json.loads(json.dumps(out))
    for f in broken["files"]:
        if f["path"] == "src/app.js":
            f["content"] = f["content"].replace("refresh();", "refresh(;")
    broken["build_report"] = "빌드 완료 (문법 오류 포함 — debug 테스트용)."
    return broken


def mock_debug_output() -> dict:
    """mock_broken_build_output의 문법 오류를 고치는 patch."""
    return {
        "files": [{"path": "src/app.js", "content": _MOCK_APP_JS}],
        "debug_report": "src/app.js 마지막 줄 refresh(; 문법 오류를 refresh();로 수정.",
    }


def mock_qa_output(anchors: list[str] | None = None, forbidden: list[str] | None = None) -> dict:
    anchors = anchors or MOCK_ANCHORS
    forbidden = forbidden or MOCK_FORBIDDEN
    evidence_map = {
        0: "src/commands.js filterCommands + src/app.js input/keydown(방향키) 이벤트",
        1: "src/state.js executeCommand가 이력을 추가하고 localStorage에 저장",
        2: "src/render.js renderCards가 결과 카드를 그림",
        3: "src/render.js followUp 버튼이 onFollowUp으로 후속 실행 연결",
    }
    return {
        "anchors": [
            {"anchor": a, "alive": True, "evidence": evidence_map.get(i, "src/ 코드에서 확인")}
            for i, a in enumerate(anchors)
        ],
        "forbidden": [
            {"rule": r, "violated": False, "evidence": "실행 결과 카드와 상태 변화가 존재해 해당 축소가 아님"}
            for r in forbidden
        ],
        "is_degenerate": False,
        "degeneration_reason": "검색→실행→카드→후속 액션 루프가 있어 단순 검색창/TODO로 퇴화하지 않음.",
        "has_user_action": True,
        "has_state_change": True,
        "has_runnable_artifact": True,
        "summary": "anchors 4개 모두 코드 근거로 확인, forbidden 위반 없음.",
    }


def mock_judge_output() -> dict:
    return {
        "verdict": "PROMOTE_TO_CODEX",
        "reasons": [
            "모든 gate(static/contract/syntax/smoke) 통과",
            "QA에서 Difficulty Anchors 4개 모두 살아 있음 확인",
        ],
        "strengths": ["핵심 루프(검색→실행→카드→후속)가 실제 코드로 동작", "상태가 localStorage에 유지됨"],
        "weaknesses": ["검색 랭킹이 단순 포함 매칭", "명령이 내장 5개로 고정"],
        "next_goal": "명령 정의를 JSON으로 분리하고 카드 타입별 렌더러와 검색 랭킹을 추가한다.",
    }


MOCK_DESK_OUTPUTS = {
    "product_brief": mock_product_brief,
    "ux_spec": mock_ux_spec,
    "technical_spec": mock_technical_spec,
    "build_output": mock_build_output,
    "debug_output": mock_debug_output,
    "qa_output": mock_qa_output,
    "judge_output": mock_judge_output,
}


def mock_factory_overrides() -> dict[str, dict]:
    """MockLLMClient overrides용 schema_name → 고정 출력 dict."""
    return {name: fn() for name, fn in MOCK_DESK_OUTPUTS.items()}
