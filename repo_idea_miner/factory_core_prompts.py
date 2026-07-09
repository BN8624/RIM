# Phase 1.6 Core-first Harness prompt 생성과 mock 고정 core workspace(runner/fixtures/golden/product layer) 정의 모듈.
from __future__ import annotations

import json

from repo_idea_miner.factory_prompts import JSON_RULES, _clip

CORE_PRINCIPLES = """너는 RIM Product Factory Phase 1.6의 Core-first Harness 작업자다.
목표는 파일을 채우는 것이 아니라 검증 가능한 core system을 만드는 것이다.
UI/viewer부터 만들지 마라. core model → contract → runner → scenario/golden 순서를 지켜라.
hardcode/stub/fixture id 분기/고정 출력은 금지다.
사람에게 질문하지 마라. 스스로 결정하고 결과만 내라."""


# ---------------------------------------------------------------- schema 예시

_NORMALIZED_CHALLENGE_SCHEMA = {
    "challenge_id": "challenge 식별자 (없으면 빈 문자열)",
    "title": "Challenge 제목",
    "core_problem": "이 Challenge의 핵심 문제 (한두 문장)",
    "expected_artifact": "만들어야 할 core artifact 설명",
    "difficulty_anchors": ["절대 제거하면 안 되는 난점 1"],
    "forbidden_simplifications": ["금지된 단순화 1"],
    "success_conditions": ["성공 조건 1"],
    "unknowns": ["불명확한 부분 1"],
    "owner_clarity": 3,
}

_CLASSIFICATION_SCHEMA = {
    "artifact_class": "RULE_ENGINE | SIMULATION_ENGINE | WORKFLOW_ENGINE | DATA_TRANSFORM_ENGINE | PLANNER_EVALUATOR | INTERACTIVE_TOOL | VIEWER_ONLY",
    "reason": "분류 근거 (결정적 상태 전이/변환/평가 관점)",
    "core_first": True,
    "runner_required": True,
    "golden_required": True,
    "product_layer_required": True,
}

_CORE_CONTRACT_DRAFT_SCHEMA = {
    "core_contract": {
        "artifact_class": "RULE_ENGINE",
        "core_goal": "core system이 보장해야 할 것",
        "state_entities": [
            {"name": "entity 이름", "fields": ["필드 1"], "invariants": ["tick >= 0", "exists:history"]}
        ],
        "actions": [
            {
                "name": "action 이름 (코드 식별자)",
                "input": ["입력 1"],
                "preconditions": ["전제 1"],
                "state_change": ["상태 변화 1"],
                "output": ["출력/이벤트 1"],
            }
        ],
        "determinism": {"random_allowed": False, "seed_required": True},
        "forbidden_shortcuts": [
            "hardcoded output",
            "static UI only",
            "random behavior without seed",
            "no state transition",
            "scenario-id specific branching",
        ],
    },
    "runner_contract": {
        "runner_command": "python src/runner.py --scenario fixtures/scenario_001.json",
        "input_format": "scenario_json",
        "output_format": "json",
        "required_output_fields": ["ok", "final_state", "events", "summary", "errors"],
    },
}

_SPEC_REVIEW_SCHEMA = {
    "status": "PASS | NEEDS_REPAIR | FAIL",
    "blocking_issues": ["차단 문제 1"],
    "repair_instructions": ["수리 지시 1"],
    "risk_level": "low | medium | high",
}

_SCENARIO_GOLDEN_SCHEMA = {
    "scenarios": [
        {
            "id": "scenario_001",
            "title": "시나리오 제목",
            "case_type": "normal | boundary | invalid",
            "initial_state": {},
            "actions": [{"type": "action 이름", "payload": {}}],
            "expected_behavior": ["기대 동작 1"],
            "must_check": ["반드시 확인할 것 1"],
        }
    ],
    "goldens": [
        {
            "scenario_id": "scenario_001",
            "expected_final_state": {},
            "expected_events": [],
            "expected_summary": "",
            "comparison_mode": "exact | partial | invariant | review",
        }
    ],
    "oracle_risk": {
        "golden_source": "model_generated | deterministic_oracle | human_seeded",
        "risk_level": "low | medium | high",
        "risk_reasons": ["위험 근거 1"],
        "safe_for_auto_gate": True,
        "requires_human_review": False,
    },
}

_SCENARIO_GOLDEN_REVIEW_SCHEMA = {
    "status": "PASS | NEEDS_REPAIR | FAIL",
    "blocking_issues": ["차단 문제 1"],
    "repair_instructions": ["수리 지시 1"],
    "golden_strength": "strong | medium | weak",
    "safe_for_auto_gate": True,
}

_CORE_BUILD_SCHEMA = {
    "files": [{"path": "src/runner.py", "content": "파일 전체 내용"}],
    "build_report": "이번 빌드에서 만든 것/미룬 것 요약",
}

_BUILD_REVIEW_SCHEMA = {
    "status": "PASS | NEEDS_PATCH | FAIL",
    "blocking_issues": ["차단 문제 1"],
    "patch_instructions": ["patch 지시 1"],
    "failed_scenarios": ["scenario_002"],
    "hardcode_risk": "low | medium | high",
    "patchable": True,
    "next_goal": "다음 loop 목표 (구체적으로)",
}

_PATCH_SCHEMA = {
    "files": [{"path": "src/core/engine.py", "content": "수정된 파일 전체 내용"}],
    "patch_report": "실패 원인과 고친 방법",
}

_PRODUCT_LAYER_SCHEMA = {
    "files": [{"path": "product/viewer/index.html", "content": "파일 전체 내용"}],
    "product_report": "product layer가 core output을 어떻게 보여주는지 요약",
}

_PRODUCT_LAYER_REVIEW_SCHEMA = {
    "status": "PASS | NEEDS_REPAIR | FAIL",
    "blocking_issues": ["차단 문제 1"],
    "repair_instructions": ["수리 지시 1"],
}


# ---------------------------------------------------------------- prompt builders (Stage 1)

def build_normalize_prompt(challenge_context: str) -> str:
    return f"""You are the Challenge Normalizer of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

Challenge Card를 표준화하라. 핵심 문제와 만들 core artifact, 난점, 금지 단순화, 성공 조건을 뽑아라.

Schema (use exactly these keys):
{json.dumps(_NORMALIZED_CHALLENGE_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CHALLENGE ===
{_clip(challenge_context)}
"""


def build_classify_prompt(normalized_json: str) -> str:
    return f"""You are the Core Artifact Classifier of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

이 Challenge의 core artifact class를 정하라.
규칙:
- static_web/python_cli 같은 프로젝트 타입이 아니라, core system의 성격으로 분류하라.
- VIEWER_ONLY는 최후의 선택이다. 데이터 모델/interaction state/replayable input-output을
  만들 수 있으면 VIEWER_ONLY로 분류하지 마라 (§5.6).

Schema (use exactly these keys):
{json.dumps(_CLASSIFICATION_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== NORMALIZED CHALLENGE ===
{_clip(normalized_json, 8000)}
"""


def build_core_contract_prompt(normalized_json: str, classification_json: str) -> str:
    return f"""You are the Core Contract Draft desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

검증 가능한 core contract를 작성하라.
규칙:
- state_entities에는 실제 상태 모델(필드/불변조건)을 넣어라.
  invariants는 기계 검증 가능한 형식으로 써라: "<필드> >= 0", "<필드> <= 100", "exists:<필드>".
- actions의 name은 코드에 그대로 등장할 식별자여야 한다.
- determinism: random 금지 또는 seed 필수.
- runner_command는 fixtures/scenario_001.json을 입력으로 실행 가능한 실제 명령이어야 한다.
- runner 출력은 ok/final_state/events/summary/errors 필드를 가진 JSON이어야 한다 (§8.4).

Schema (use exactly these keys):
{json.dumps(_CORE_CONTRACT_DRAFT_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== NORMALIZED CHALLENGE ===
{_clip(normalized_json, 6000)}

=== ARTIFACT CLASSIFICATION ===
{_clip(classification_json, 2000)}
"""


def build_core_contract_review_prompt(normalized_json: str, contract_json: str) -> str:
    return f"""You are the Core Contract Review desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

"좋아 보인다"가 아니라 계약 기반으로 검토하라 (§5.10):
- Challenge의 핵심 난점을 보존했는가
- forbidden_simplifications를 차단하는가
- state/action 구조가 검증 가능한가
- runner로 실행 가능한가
- scenario/golden으로 검증 가능한가
- Phase 2에서 확장 가능한가
- UI 없이도 core가 독립적으로 검증 가능한가

Schema (use exactly these keys):
{json.dumps(_SPEC_REVIEW_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== NORMALIZED CHALLENGE ===
{_clip(normalized_json, 5000)}

=== CORE CONTRACT ===
{_clip(contract_json, 8000)}
"""


def build_core_contract_repair_prompt(contract_json: str, review_json: str) -> str:
    return f"""You are the Core Contract Repair desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

리뷰의 blocking_issues와 repair_instructions만 고쳐 core contract를 다시 내라.
구조를 새로 발명하지 말고 지적된 문제만 수리하라.

Schema (use exactly these keys):
{json.dumps(_CORE_CONTRACT_DRAFT_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CURRENT CONTRACT ===
{_clip(contract_json, 8000)}

=== REVIEW ===
{_clip(review_json, 4000)}
"""


# ---------------------------------------------------------------- prompt builders (Stage 2)

def build_scenario_golden_prompt(normalized_json: str, contract_json: str) -> str:
    return f"""You are the Scenario/Golden Draft desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

core contract를 검증할 scenario fixture와 golden expected를 함께 만들어라.
규칙 (§6.4, §6.7):
- 정상(normal) 1개 이상, 경계(boundary) 1개 이상, 실패/무효(invalid) 1개 이상.
- scenario의 actions는 contract의 action 이름을 그대로 써라.
- golden은 runner 출력(ok/final_state/events/summary/errors)과 비교 가능해야 한다.
- comparison_mode: 확신 있으면 exact, 일부 필드만 확실하면 partial,
  구조/불변조건만 보장되면 invariant, 자신 없으면 review.
- review 모드 golden은 자동 gate 근거로 쓰이지 않는다. 남발하지 마라.
- oracle_risk에는 golden의 신뢰도를 정직하게 기록하라.

Schema (use exactly these keys):
{json.dumps(_SCENARIO_GOLDEN_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== NORMALIZED CHALLENGE ===
{_clip(normalized_json, 4000)}

=== CORE CONTRACT ===
{_clip(contract_json, 8000)}
"""


def build_scenario_golden_review_prompt(contract_json: str, scenario_golden_json: str) -> str:
    return f"""You are the Scenario/Golden Review desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

검토 항목 (§6.9):
- happy path만 있지 않은가
- 경계 케이스가 있는가
- 실패/무효 케이스가 있는가
- Golden expected가 너무 모델 편의적이지 않은가
- comparison_mode가 적절한가
- forbidden_simplifications를 잡을 수 있는가
- 자동 gate로 사용 가능한가

Schema (use exactly these keys):
{json.dumps(_SCENARIO_GOLDEN_REVIEW_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CORE CONTRACT ===
{_clip(contract_json, 5000)}

=== SCENARIOS / GOLDENS ===
{_clip(scenario_golden_json, 16000)}
"""


def build_scenario_golden_repair_prompt(scenario_golden_json: str, review_json: str) -> str:
    return f"""You are the Scenario/Golden Repair desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

리뷰의 blocking_issues와 repair_instructions만 고쳐 scenario/golden 전체를 다시 내라.
정상/경계/실패 케이스 최소 구성을 유지하라.

Schema (use exactly these keys):
{json.dumps(_SCENARIO_GOLDEN_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CURRENT SCENARIOS / GOLDENS ===
{_clip(scenario_golden_json, 16000)}

=== REVIEW ===
{_clip(review_json, 4000)}
"""


# ---------------------------------------------------------------- prompt builders (Stage 3)

# build_task_packet.md 필수 문구 (§7.5)
BUILD_TASK_PACKET_CORE_TEXT = """너의 목표는 파일을 채우는 것이 아니다.
너의 목표는 core contract와 scenario/golden을 만족하는 첫 시제품을 구현하는 것이다.

먼저 core system, runner, scenario replay를 구현하라.
그 다음 core를 조작하거나 확인할 수 있는 product layer를 붙여라.

viewer/product layer는 core logic을 대체하면 안 된다.
viewer는 core output, state snapshot, replay result를 보여주는 레이어여야 한다."""

BUILDER_FORBIDDEN = (
    "UI부터 만들기",
    "runner 생략",
    "core logic을 viewer 안에만 구현",
    "scenario fixture를 무시",
    "expected output을 코드에 박기",
    "scenario_001 같은 fixture id별 분기",
    "random/Date.now로 결과 흔들기",
)


def render_build_task_packet_md(
    contract_json: str, runner_contract: dict, scenario_ids: list[str]
) -> str:
    forbidden = "\n".join(f"- {f}" for f in BUILDER_FORBIDDEN)
    scenarios = "\n".join(f"- fixtures/{sid}.json" for sid in scenario_ids)
    return f"""# Build Task Packet (Core-first)

{BUILD_TASK_PACKET_CORE_TEXT}

## 필수 요구 (§7.6)
- src/core 또는 src/engine 구조
- runner command: `{runner_contract.get('runner_command')}`
- runner 출력: {', '.join(runner_contract.get('required_output_fields') or [])} 필드를 가진 JSON
- fixtures 실행 가능 / golden 비교 가능
- deterministic behavior (random은 seed 없이는 금지)
- product layer의 기반 준비 (replay 결과를 보여줄 수 있는 구조)
- README.md / run_instructions.md

## 재생해야 할 scenario
{scenarios}

## 금지 (§7.9)
{forbidden}

## Core Contract
```json
{contract_json}
```
"""


def build_core_build_prompt(
    build_task_packet_md: str,
    contract_json: str,
    scenarios_json: str,
    file_tree: list[str],
) -> str:
    return f"""You are the Core Build desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

build task packet에 따라 core-first 시제품 파일들을 생성하라.
- runner는 scenario json 하나를 받아 ok/final_state/events/summary/errors JSON을 stdout에 출력해야 한다.
- runner의 JSON 출력은 ASCII-safe여야 한다 (python이면 json.dumps 기본값/ensure_ascii=True 사용).
- 모든 scenario fixture를 재생할 수 있어야 한다. fixture id로 분기하지 마라.
- golden expected 문자열을 코드에 박지 마라. 실제 로직으로 계산하라.
- validators/ 아래에 구조 자가 검사 스크립트를 넣어라.
- product/ 디렉터리는 아직 만들지 마라 (Product Layer Stage에서 별도로 만든다).

Schema (use exactly these keys):
{json.dumps(_CORE_BUILD_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== BUILD TASK PACKET ===
{_clip(build_task_packet_md, 6000)}

=== CORE CONTRACT ===
{_clip(contract_json, 5000)}

=== SCENARIOS ===
{_clip(scenarios_json, 6000)}

=== CURRENT FILE TREE ===
{json.dumps(file_tree, ensure_ascii=False)}
"""


# ---------------------------------------------------------------- prompt builders (Stage 5)

def build_build_review_prompt(gate_report_md: str, contract_json: str, file_tree: list[str]) -> str:
    return f"""You are the Build Review desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

Gate 결과를 보고 판단하라 (§9.4):
- runner가 실제 core를 실행하는가
- scenario를 제대로 replay하는가
- golden을 하드코딩하지 않았는가
- state transition이 실제로 있는가
- core logic이 UI에 묻히지 않았는가
- 실패가 patch로 고칠 수 있는가

next_goal에는 다음 loop가 이어받을 구체적 목표를 써라.

Schema (use exactly these keys):
{json.dumps(_BUILD_REVIEW_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== GATE RESULTS ===
{_clip(gate_report_md, 8000)}

=== CORE CONTRACT ===
{_clip(contract_json, 4000)}

=== FILE TREE ===
{json.dumps(file_tree, ensure_ascii=False)}
"""


def build_patch_prompt(
    gate_report_md: str,
    patch_instructions: list[str],
    key_files: dict[str, str],
    attempt: int,
    max_attempts: int,
) -> str:
    files_md = "\n\n".join(f"--- {path} ---\n{_clip(content, 4000)}" for path, content in key_files.items())
    return f"""You are the Patch Repair desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

기존 Contract/Scenario/Golden을 통과시키기 위한 제한적 수리만 수행하라 (시도 {attempt}/{max_attempts}).
규칙 (§9.5):
- 처음부터 재생성 금지. 실패한 scenario/gate 중심으로만 수정하라.
- green 부분을 보존하라.
- core contract를 임의로 바꾸지 마라.
- fixtures/golden/contract 파일을 수정하거나 우회하지 마라.
- 새 기능/새 시스템/새 product layer 확장은 금지다 (Phase 2 범위).

Schema (use exactly these keys):
{json.dumps(_PATCH_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== GATE FAILURES ===
{_clip(gate_report_md, 6000)}

=== PATCH INSTRUCTIONS ===
{json.dumps(patch_instructions, ensure_ascii=False, indent=1)}

=== KEY FILES ===
{files_md}
"""


# ---------------------------------------------------------------- prompt builders (Stage 6)

def build_product_layer_prompt(
    contract_json: str, replay_index_json: str, run_instructions: str, file_tree: list[str]
) -> str:
    return f"""You are the Product Layer Build desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

검증된 core를 사람이 실행·조작·확인할 수 있는 최소 product layer를 만들어라.
원칙 (§10.4):
- product/ 디렉터리 아래에만 파일을 만들어라.
- core logic을 복제하거나 대체하지 마라.
- core runner output / state snapshot / replay result(replay/ 디렉터리)를 불러와 보여줘라.
- product layer에서만 동작하고 runner로 검증 불가한 구조는 실패다.

Schema (use exactly these keys):
{json.dumps(_PRODUCT_LAYER_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CORE CONTRACT ===
{_clip(contract_json, 4000)}

=== REPLAY INDEX ===
{_clip(replay_index_json, 3000)}

=== RUN INSTRUCTIONS ===
{_clip(run_instructions, 2000)}

=== FILE TREE ===
{json.dumps(file_tree, ensure_ascii=False)}
"""


def build_product_layer_review_prompt(product_files: dict[str, str], contract_json: str) -> str:
    files_md = "\n\n".join(f"--- {path} ---\n{_clip(content, 3000)}" for path, content in product_files.items())
    return f"""You are the Product Layer Review desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

검토 항목 (§10.5):
- viewer/product layer가 core output(replay 결과)을 보여주는가
- core logic을 복제하지 않았는가
- 사용자가 결과를 확인할 수 있는가
- 실행 방법이 명확한가
- product layer가 core 검증 결과와 불일치하지 않는가

Schema (use exactly these keys):
{json.dumps(_PRODUCT_LAYER_REVIEW_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CORE CONTRACT ===
{_clip(contract_json, 3000)}

=== PRODUCT LAYER FILES ===
{files_md}
"""


def build_product_layer_repair_prompt(product_files: dict[str, str], review_json: str) -> str:
    files_md = "\n\n".join(f"--- {path} ---\n{_clip(content, 3000)}" for path, content in product_files.items())
    return f"""You are the Product Layer Repair desk of RIM Product Factory Phase 1.6.

{CORE_PRINCIPLES}

리뷰가 지적한 문제만 고쳐라 (§10.5):
- core logic 수정 금지. product/ 파일과 실행 안내만 수정하라.

Schema (use exactly these keys):
{json.dumps(_PRODUCT_LAYER_SCHEMA, ensure_ascii=False, indent=2)}

{JSON_RULES}

=== CURRENT PRODUCT FILES ===
{files_md}

=== REVIEW ===
{_clip(review_json, 3000)}
"""


# ---------------------------------------------------------------- mock 출력 (테스트 가능한 고정 core workspace)

def mock_normalized_challenge() -> dict:
    return {
        "challenge_id": "",
        "title": "키보드 명령 센터의 명령 실행 코어",
        "core_problem": "명령 실행과 후속 액션이 만드는 실행 이력 상태 전이를 결정적으로 관리한다.",
        "expected_artifact": "명령 실행 이력을 관리하는 rule engine core + runner + 검증 fixture",
        "difficulty_anchors": [
            "명령 실행과 실행 상태 변화",
            "결과 카드에서 후속 액션 제공",
            "무효 명령 거부 시 상태 오염 없음",
        ],
        "forbidden_simplifications": [
            "단순 검색창으로 만들지 말 것",
            "정적 메뉴판으로 만들지 말 것",
        ],
        "success_conditions": [
            "scenario replay로 상태 전이를 재현할 수 있다",
            "같은 입력에 항상 같은 출력이 나온다",
        ],
        "unknowns": ["명령 종류 확장 방식"],
        "owner_clarity": 4,
    }


def mock_core_classification() -> dict:
    return {
        "artifact_class": "RULE_ENGINE",
        "reason": "명령 실행이 결정적 상태 전이(이력 추가/거부)를 만들기 때문",
        "core_first": True,
        "runner_required": True,
        "golden_required": True,
        "product_layer_required": True,
    }


_MOCK_CORE_CONTRACT = {
    "artifact_class": "RULE_ENGINE",
    "core_goal": "명령 실행/후속 액션이 실행 이력 상태를 결정적으로 바꾸고, 무효 액션은 상태를 오염시키지 않는다.",
    "state_entities": [
        {
            "name": "history",
            "fields": ["card_id", "command_id", "output", "source_card_id"],
            "invariants": ["exists:history"],
        },
        {
            "name": "counters",
            "fields": ["tick", "history_count"],
            "invariants": ["tick >= 0", "history_count >= 0"],
        },
    ],
    "actions": [
        {
            "name": "execute_command",
            "input": ["command_id"],
            "preconditions": ["command_id가 명령 목록에 존재"],
            "state_change": ["history에 결과 카드 추가", "tick 1 증가", "history_count 갱신"],
            "output": ["command_executed 이벤트"],
        },
        {
            "name": "follow_up",
            "input": ["card_id"],
            "preconditions": ["card_id가 history에 존재"],
            "state_change": ["원본 카드에 연결된 후속 카드 추가", "tick 1 증가"],
            "output": ["follow_up_executed 이벤트"],
        },
    ],
    "determinism": {"random_allowed": False, "seed_required": True},
    "forbidden_shortcuts": [
        "hardcoded output",
        "static UI only",
        "random behavior without seed",
        "no state transition",
        "scenario-id specific branching",
    ],
}

_MOCK_RUNNER_CONTRACT = {
    "runner_command": "python src/runner.py --scenario fixtures/scenario_001.json",
    "input_format": "scenario_json",
    "output_format": "json",
    "required_output_fields": ["ok", "final_state", "events", "summary", "errors"],
}


def mock_core_contract_draft() -> dict:
    return json.loads(json.dumps({
        "core_contract": _MOCK_CORE_CONTRACT,
        "runner_contract": _MOCK_RUNNER_CONTRACT,
    }))


def mock_spec_review_pass() -> dict:
    return {
        "status": "PASS",
        "blocking_issues": [],
        "repair_instructions": [],
        "risk_level": "low",
    }


_MOCK_SCENARIOS = [
    {
        "id": "scenario_001",
        "title": "정상: 명령 2개 실행",
        "case_type": "normal",
        "initial_state": {},
        "actions": [
            {"type": "execute_command", "payload": {"command_id": "report"}},
            {"type": "execute_command", "payload": {"command_id": "note"}},
        ],
        "expected_behavior": ["카드 2개가 이력에 추가된다", "tick이 2가 된다"],
        "must_check": ["history_count == 2"],
    },
    {
        "id": "scenario_002",
        "title": "경계: 후속 액션 연쇄",
        "case_type": "boundary",
        "initial_state": {},
        "actions": [
            {"type": "execute_command", "payload": {"command_id": "report"}},
            {"type": "follow_up", "payload": {"card_id": "card_1"}},
            {"type": "follow_up", "payload": {"card_id": "card_2"}},
        ],
        "expected_behavior": ["후속 카드가 원본 카드에 연결되어 3개가 된다"],
        "must_check": ["history_count == 3", "후속 카드의 source_card_id가 연결됨"],
    },
    {
        "id": "scenario_003",
        "title": "실패/무효: 알 수 없는 명령과 없는 카드",
        "case_type": "invalid",
        "initial_state": {},
        "actions": [
            {"type": "execute_command", "payload": {"command_id": "unknown_cmd"}},
            {"type": "follow_up", "payload": {"card_id": "card_99"}},
        ],
        "expected_behavior": ["두 액션 모두 거부된다", "상태가 오염되지 않는다"],
        "must_check": ["history_count == 0", "errors 2건"],
    },
]

_MOCK_GOLDENS = [
    {
        "scenario_id": "scenario_001",
        "expected_final_state": {
            "history": [
                {"card_id": "card_1", "command_id": "report", "output": "주간 리포트 초안 생성",
                 "source_card_id": None},
                {"card_id": "card_2", "command_id": "note", "output": "빈 메모 생성",
                 "source_card_id": None},
            ],
            "tick": 2,
            "history_count": 2,
        },
        "expected_events": [
            {"type": "command_executed", "command_id": "report", "card_id": "card_1"},
            {"type": "command_executed", "command_id": "note", "card_id": "card_2"},
        ],
        "expected_summary": "2 cards, 0 rejected",
        "comparison_mode": "exact",
    },
    {
        "scenario_id": "scenario_002",
        "expected_final_state": {"tick": 3, "history_count": 3},
        "expected_events": [],
        "expected_summary": "",
        "comparison_mode": "partial",
    },
    {
        "scenario_id": "scenario_003",
        "expected_final_state": {"history": [], "tick": 0, "history_count": 0},
        "expected_events": [],
        "expected_summary": "",
        "comparison_mode": "invariant",
    },
]


def mock_scenario_golden_output() -> dict:
    return json.loads(json.dumps({
        "scenarios": _MOCK_SCENARIOS,
        "goldens": _MOCK_GOLDENS,
        "oracle_risk": {
            "golden_source": "model_generated",
            "risk_level": "low",
            "risk_reasons": ["결정적 rule engine이라 golden 계산이 단순함"],
            "safe_for_auto_gate": True,
            "requires_human_review": False,
        },
    }))


def mock_scenario_golden_review_pass() -> dict:
    return {
        "status": "PASS",
        "blocking_issues": [],
        "repair_instructions": [],
        "golden_strength": "medium",
        "safe_for_auto_gate": True,
    }


# ---------------------------------------------------------------- mock core workspace 파일

_MOCK_ENGINE_PY = '''# 명령 실행 이력을 관리하는 결정적 rule engine 코어 (random/시간 의존 없음).
from copy import deepcopy

COMMANDS = {
    "report": "\\uc8fc\\uac04 \\ub9ac\\ud3ec\\ud2b8 \\ucd08\\uc548 \\uc0dd\\uc131",
    "note": "\\ube48 \\uba54\\ubaa8 \\uc0dd\\uc131",
    "timer": "\\uc9d1\\uc911 \\ud0c0\\uc774\\uba38 \\uc2dc\\uc791",
}


def initial_state(overrides=None):
    state = {"history": [], "tick": 0, "history_count": 0}
    if overrides:
        state.update(deepcopy(overrides))
    return state


def _append_card(state, command_id, output, source_card_id):
    state["tick"] += 1
    card = {
        "card_id": "card_%d" % state["tick"],
        "command_id": command_id,
        "output": output,
        "source_card_id": source_card_id,
    }
    state["history"].append(card)
    state["history_count"] = len(state["history"])
    return card


def apply_action(state, action):
    """action을 적용해 (new_state, events, errors)를 반환한다. 무효 action은 상태를 바꾸지 않는다."""
    action_type = (action or {}).get("type")
    payload = (action or {}).get("payload") or {}
    new_state = deepcopy(state)
    events = []
    errors = []

    if action_type == "execute_command":
        command_id = payload.get("command_id")
        if command_id not in COMMANDS:
            reason = "unknown command: %s" % command_id
            events.append({"type": "invalid_action_rejected", "action": "execute_command", "reason": reason})
            errors.append(reason)
            return deepcopy(state), events, errors
        card = _append_card(new_state, command_id, COMMANDS[command_id], None)
        events.append({"type": "command_executed", "command_id": command_id, "card_id": card["card_id"]})
        return new_state, events, errors

    if action_type == "follow_up":
        source_id = payload.get("card_id")
        source = next((c for c in new_state["history"] if c["card_id"] == source_id), None)
        if source is None:
            reason = "unknown card: %s" % source_id
            events.append({"type": "invalid_action_rejected", "action": "follow_up", "reason": reason})
            errors.append(reason)
            return deepcopy(state), events, errors
        card = _append_card(new_state, source["command_id"], source["output"], source_id)
        events.append({"type": "follow_up_executed", "card_id": card["card_id"], "source_card_id": source_id})
        return new_state, events, errors

    reason = "unknown action type: %s" % action_type
    events.append({"type": "invalid_action_rejected", "action": action_type, "reason": reason})
    errors.append(reason)
    return deepcopy(state), events, errors
'''

_MOCK_CORE_INIT_PY = "# rule engine core 패키지.\n"

_MOCK_RUNNER_PY = '''# scenario fixture를 재생해 core 결과 JSON(ok/final_state/events/summary/errors)을 출력하는 runner.
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import engine  # noqa: E402


def run_scenario(scenario):
    state = engine.initial_state(scenario.get("initial_state"))
    events = []
    errors = []
    for action in scenario.get("actions") or []:
        state, new_events, new_errors = engine.apply_action(state, action)
        events.extend(new_events)
        errors.extend(new_errors)
    summary = "%d cards, %d rejected" % (state["history_count"], len(errors))
    return {"ok": True, "final_state": state, "events": events, "summary": summary, "errors": errors}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    args = parser.parse_args()
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    result = run_scenario(scenario)
    # ASCII-safe 출력: 콘솔 인코딩(cp949 등)과 무관하게 동일한 JSON을 보장한다
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

_MOCK_CHECK_CORE_PY = '''# core workspace 구조와 핵심 마커 존재를 검사하는 자가 검증 스크립트. 실패 시 exit code 1.
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = [
    "src/runner.py",
    "src/core/engine.py",
    "core_contract.json",
    "runner_contract.json",
    "fixtures/scenario_001.json",
    "golden/expected_001.json",
]

MARKERS = {
    "src/core/engine.py": ["apply_action", "execute_command", "follow_up"],
    "src/runner.py": ["final_state", "events"],
}


def main():
    problems = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).is_file():
            problems.append("missing file: %s" % rel)
    for rel, markers in MARKERS.items():
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in markers:
            if marker not in text:
                problems.append("missing marker %s in %s" % (marker, rel))
    if problems:
        for problem in problems:
            print("FAIL:", problem)
        return 1
    print("core structure check pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

_MOCK_CORE_README = """# Command Rule Engine Core

명령 실행/후속 액션이 실행 이력 상태를 결정적으로 바꾸는 rule engine 코어.

## 구조
- src/core/engine.py — 상태 전이 코어 (apply_action)
- src/runner.py — scenario 재생 runner (JSON 출력)
- fixtures/ — scenario fixture (정상/경계/실패)
- golden/ — 기대 출력 (exact/partial/invariant)
- validators/check_core.py — 구조 자가 검사
- product/viewer/ — replay 결과를 보여주는 product layer

## 핵심 루프
scenario 입력 → runner 재생 → final_state/events/summary 출력 → golden 비교
"""

_MOCK_CORE_RUN_INSTRUCTIONS = """# 실행 방법

## 코어 runner 실행
```bash
python src/runner.py --scenario fixtures/scenario_001.json
```
출력은 ok/final_state/events/summary/errors 필드를 가진 JSON 한 줄이다.

## 구조 자가 검사
```bash
python validators/check_core.py
```

## Product Layer (뷰어)
```bash
python -m http.server 8000
```
브라우저에서 http://localhost:8000/product/viewer/index.html 을 연다.
뷰어는 replay/ 디렉터리의 runner 재생 결과를 그대로 표시한다 (core logic 복제 없음).
"""


def mock_core_build_output() -> dict:
    return {
        "files": [
            {"path": "src/core/__init__.py", "content": _MOCK_CORE_INIT_PY},
            {"path": "src/core/engine.py", "content": _MOCK_ENGINE_PY},
            {"path": "src/runner.py", "content": _MOCK_RUNNER_PY},
            {"path": "validators/check_core.py", "content": _MOCK_CHECK_CORE_PY},
            {"path": "README.md", "content": _MOCK_CORE_README},
            {"path": "run_instructions.md", "content": _MOCK_CORE_RUN_INSTRUCTIONS},
        ],
        "build_report": (
            "core-first 빌드 완료: engine(상태 전이) + runner(JSON 출력) + validators. "
            "명령 데이터는 COMMANDS 테이블로 분리, fixture id 분기 없음, random/시간 의존 없음."
        ),
    }


def mock_broken_core_build_output() -> dict:
    """Patch Repair 테스트용: tick이 2씩 증가해 golden exact 비교가 실패하는 빌드."""
    out = mock_core_build_output()
    broken = json.loads(json.dumps(out))
    for f in broken["files"]:
        if f["path"] == "src/core/engine.py":
            f["content"] = f["content"].replace('state["tick"] += 1', 'state["tick"] += 2')
    broken["build_report"] = "빌드 완료 (tick 증가 버그 포함 — patch 테스트용)."
    return broken


def mock_runnerless_core_build_output() -> dict:
    """Runner Gate 실패 테스트용: runner가 JSON이 아닌 텍스트를 출력하는 빌드."""
    out = mock_core_build_output()
    broken = json.loads(json.dumps(out))
    for f in broken["files"]:
        if f["path"] == "src/runner.py":
            f["content"] = f["content"].replace(
                "print(json.dumps(result, ensure_ascii=True))",
                'print("done (not json)")',
            )
    broken["build_report"] = "빌드 완료 (runner JSON 출력 누락 — runner gate 테스트용)."
    return broken


def mock_build_review_pass() -> dict:
    return {
        "status": "PASS",
        "blocking_issues": [],
        "patch_instructions": [],
        "failed_scenarios": [],
        "hardcode_risk": "low",
        "patchable": True,
        "next_goal": "명령 정의를 데이터 파일로 분리하고 boundary scenario를 2개 추가한다.",
    }


def mock_patch_output() -> dict:
    """mock_broken_core_build_output의 tick 버그를 고치는 patch."""
    return {
        "files": [{"path": "src/core/engine.py", "content": _MOCK_ENGINE_PY}],
        "patch_report": "tick이 2씩 증가하던 버그를 1씩 증가로 수정 (golden exact 비교 복구).",
    }


# ---------------------------------------------------------------- mock product layer

_MOCK_VIEWER_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Core Replay Viewer</title>
<style>
main { max-width: 720px; margin: 32px auto; font-family: system-ui, sans-serif; }
select { font-size: 1rem; padding: 6px; }
pre { background: #f3f4f6; border-radius: 8px; padding: 12px; overflow-x: auto; }
.event { border: 1px solid #d1d5db; border-radius: 8px; padding: 8px; margin: 6px 0; }
</style>
</head>
<body>
<main>
  <h1>Core Replay Viewer</h1>
  <p>core runner가 재생한 replay 결과를 그대로 표시한다 (core logic 복제 없음).</p>
  <label>재생 결과 선택: <select id="replay-select"></select></label>
  <p id="summary"></p>
  <h2>Final State</h2>
  <pre id="state"></pre>
  <h2>Events</h2>
  <div id="events"></div>
  <script src="viewer.js"></script>
</main>
</body>
</html>
"""

_MOCK_VIEWER_JS = """// replay/ 디렉터리의 core runner 출력을 불러와 표시하는 뷰어 (core logic 없음).
const selectEl = document.getElementById("replay-select");
const summaryEl = document.getElementById("summary");
const stateEl = document.getElementById("state");
const eventsEl = document.getElementById("events");

async function loadIndex() {
  const res = await fetch("../../replay/index.json");
  return res.json();
}

async function showReplay(file) {
  const res = await fetch("../../replay/" + file);
  const replay = await res.json();
  summaryEl.textContent = "summary: " + replay.summary + " / errors: " + (replay.errors || []).length;
  stateEl.textContent = JSON.stringify(replay.final_state, null, 2);
  eventsEl.innerHTML = "";
  (replay.events || []).forEach((event) => {
    const div = document.createElement("div");
    div.className = "event";
    div.textContent = JSON.stringify(event);
    eventsEl.appendChild(div);
  });
}

loadIndex().then((index) => {
  (index.replays || []).forEach((entry) => {
    const option = document.createElement("option");
    option.value = entry.file;
    option.textContent = entry.id + (entry.ok ? "" : " (실행 실패)");
    selectEl.appendChild(option);
  });
  selectEl.addEventListener("change", () => showReplay(selectEl.value));
  if (selectEl.value) showReplay(selectEl.value);
});
"""


def mock_product_layer_output() -> dict:
    return {
        "files": [
            {"path": "product/viewer/index.html", "content": _MOCK_VIEWER_HTML},
            {"path": "product/viewer/viewer.js", "content": _MOCK_VIEWER_JS},
        ],
        "product_report": (
            "replay/index.json과 replay 결과 JSON을 불러와 final_state/events/summary를 표시하는 뷰어. "
            "core logic을 복제하지 않고 runner 출력만 사용한다."
        ),
    }


def mock_product_layer_review_pass() -> dict:
    return {"status": "PASS", "blocking_issues": [], "repair_instructions": []}


MOCK_CORE_DESK_OUTPUTS = {
    "normalized_challenge": mock_normalized_challenge,
    "core_classification": mock_core_classification,
    "core_contract_draft": mock_core_contract_draft,
    "core_contract_review": mock_spec_review_pass,
    "core_contract_repair": mock_core_contract_draft,
    "scenario_golden": mock_scenario_golden_output,
    "scenario_golden_review": mock_scenario_golden_review_pass,
    "scenario_golden_repair": mock_scenario_golden_output,
    "core_build": mock_core_build_output,
    "build_review": mock_build_review_pass,
    "patch_repair": mock_patch_output,
    "product_layer": mock_product_layer_output,
    "product_layer_review": mock_product_layer_review_pass,
    "product_layer_repair": mock_product_layer_output,
}


def mock_core_factory_overrides() -> dict[str, dict]:
    """MockLLMClient overrides용 schema_name → 고정 출력 dict (Phase 1.6)."""
    return {name: fn() for name, fn in MOCK_CORE_DESK_OUTPUTS.items()}
