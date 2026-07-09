# Product Factory Desk 실행기(LLM 호출 + key scheduler 연동)와 Desk 산출물 markdown 렌더러 모듈.
from __future__ import annotations

import time

from pydantic import BaseModel, ValidationError

from repo_idea_miner.challenge_key_scheduler import ChallengeKeyScheduler, classify_challenge_error
from repo_idea_miner.config import Settings
from repo_idea_miner.errors import LLMCallError, RIMError
from repo_idea_miner.factory_db import worker_key_label
from repo_idea_miner.key_pool import KeyPool
from repo_idea_miner.llm_client import GoogleGenAIGemmaClient, LLMCallLogger, LLMClient


class DeskError(Exception):
    """Desk 실행 실패 (LLM 호출/스키마 검증 실패)."""


class DeskExecutor:
    """Desk 하나의 LLM 호출을 담당한다.

    - mock/주입 llm이 있으면 그대로 사용한다.
    - live면 공유 key scheduler에서 key를 얻어 단일 key 클라이언트로 호출하고,
      성공/실패를 scheduler에 반영한다 (Challenge daemon과 같은 상태 저장소 공유, §12).
    """

    def __init__(
        self,
        mode: str,
        settings: Settings,
        scheduler: ChallengeKeyScheduler | None = None,
        llm: LLMClient | None = None,
        call_logger: LLMCallLogger | None = None,
        key_wait_seconds: float = 120.0,
        sleep_fn=time.sleep,
    ):
        self.mode = mode
        self.settings = settings
        self.scheduler = scheduler
        self.llm = llm
        self.logger = call_logger or LLMCallLogger(None)
        self.key_wait_seconds = key_wait_seconds
        self._sleep = sleep_fn

    def call(self, schema_name: str, prompt: str, model_cls: type[BaseModel]) -> tuple[BaseModel, str]:
        """LLM을 호출해 schema 검증까지 마친 (model, worker_key_id)를 반환한다."""
        if self.llm is not None:
            raw = self.llm.generate_json(prompt, schema_name, worker=schema_name)
            return _validate_output(schema_name, raw, model_cls), "MOCK"
        if self.scheduler is None:
            raise DeskError(f"{schema_name}: live 모드인데 key scheduler가 없습니다.")

        acquired = self._acquire_key()
        if acquired is None:
            raise DeskError(f"{schema_name}: {self.key_wait_seconds}초 내 사용 가능한 key가 없습니다.")
        key_id, api_key = acquired
        label = worker_key_label(key_id)
        client = GoogleGenAIGemmaClient(
            self.settings, KeyPool({key_id: api_key}, "round_robin"), call_logger=self.logger
        )
        try:
            raw = client.generate_json(prompt, schema_name, worker=schema_name)
        except (LLMCallError, RIMError) as exc:
            kind, msg = classify_challenge_error(exc)
            self.scheduler.release_error(key_id, kind, msg)
            raise DeskError(f"{schema_name}: LLM 호출 실패 ({kind}): {msg[:200]}") from exc
        except Exception as exc:  # noqa: BLE001 - key 상태 반영 후 재던짐
            kind, msg = classify_challenge_error(exc)
            self.scheduler.release_error(key_id, kind, msg)
            raise
        self.scheduler.release_success(key_id)
        return _validate_output(schema_name, raw, model_cls), label

    def _acquire_key(self):
        deadline = time.monotonic() + self.key_wait_seconds
        while True:
            acquired = self.scheduler.acquire()
            if acquired is not None:
                return acquired
            if time.monotonic() >= deadline:
                return None
            self._sleep(2.0)


def _validate_output(schema_name: str, raw: dict, model_cls: type[BaseModel]) -> BaseModel:
    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise DeskError(f"{schema_name}: 스키마 검증 실패 ({exc.error_count()}개 필드 오류)") from exc


# ---------------------------------------------------------------- markdown 렌더러

def _ul(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "- (없음)"


def render_product_brief_md(brief: dict) -> str:
    return f"""# Product Brief

## 제품 목표
{brief['product_goal']}

## 사용자
{brief['target_user']}

## 핵심 사용 루프
{brief['core_loop']}

## 첫 화면 목표
{brief['first_screen_goal']}

## 줄여도 되는 것
{_ul(brief['can_reduce'])}

## 줄이면 안 되는 것
{_ul(brief['must_not_reduce'])}
"""


def render_ux_flow_md(ux: dict) -> str:
    flow = ux["ux_flow"]
    transitions = "\n".join(
        f"- {t['trigger']}: {t['from_state']} → {t['to_state']} ({t['effect']})"
        for t in ux["state_transitions"]
    )
    screens = "\n".join(
        f"### {s['name']}\n- 목적: {s['purpose']}\n- 요소: {', '.join(s['elements'])}"
        for s in ux["screen_spec"]
    )
    return f"""# UX Flow

## 첫 화면
{flow['first_screen']}

## 주요 화면
{_ul(flow['screens'])}

## 사용자 행동
{_ul(flow['user_actions'])}

## 상태 변화
{_ul(flow['state_changes'])}

## 성공 화면
{flow['success_screen']}

## 실패 화면
{flow['failure_screen']}

## 30초 데모
{flow['thirty_second_demo']}

## 화면 스펙
{screens}

## 상태 전이
{transitions}
"""


def render_technical_plan_md(spec: dict) -> str:
    manifest = spec["manifest"]
    files = "\n".join(f"- {f['path']} — {f['role']}" for f in manifest["files"])
    return f"""# Technical Plan

{spec['technical_plan']}

## 파일 구성
{files}

## 실행
- entrypoint: {manifest['entrypoint']}
- 실행 명령: {manifest['run_command']}
- 검증 명령: {', '.join(manifest.get('check_commands') or []) or '(없음)'}
"""


def render_qa_report_md(qa: dict, qa_pass: bool) -> str:
    anchors = "\n".join(
        f"- [{'살아 있음' if a['alive'] else '죽음'}] {a['anchor']}\n  - 근거: {a['evidence']}"
        for a in qa["anchors"]
    )
    forbidden = "\n".join(
        f"- [{'위반' if f['violated'] else '준수'}] {f['rule']}\n  - 근거: {f['evidence']}"
        for f in qa["forbidden"]
    )
    return f"""# QA Report

결과: {'PASS' if qa_pass else 'FAIL'}

## Difficulty Anchors
{anchors}

## Forbidden Simplifications
{forbidden}

## 퇴화 검사
- 퇴화 여부: {'퇴화함' if qa['is_degenerate'] else '퇴화 아님'}
- 근거: {qa['degeneration_reason']}

## 상호작용 검사
- 사용자 행동 존재: {'예' if qa['has_user_action'] else '아니오'}
- 상태 변화 존재: {'예' if qa['has_state_change'] else '아니오'}
- 실행물 존재: {'예' if qa['has_runnable_artifact'] else '아니오'}

## 요약
{qa['summary']}
"""


def render_anchor_check_md(qa: dict) -> str:
    lines = ["# Anchor Check", ""]
    for a in qa["anchors"]:
        lines.append(f"## {a['anchor']}")
        lines.append(f"- 판정: {'살아 있음' if a['alive'] else '죽음'}")
        lines.append(f"- 근거: {a['evidence']}")
        lines.append("")
    return "\n".join(lines)


def render_forbidden_check_md(qa: dict) -> str:
    lines = ["# Forbidden Simplification Check", ""]
    for f in qa["forbidden"]:
        lines.append(f"## {f['rule']}")
        lines.append(f"- 판정: {'위반' if f['violated'] else '준수'}")
        lines.append(f"- 근거: {f['evidence']}")
        lines.append("")
    return "\n".join(lines)


def render_product_verdict_md(
    verdict: str,
    judge: dict | None,
    gate_summary: dict,
    line: str,
    auto_adjustments: list[str],
    recommended_action: str,
) -> str:
    gates = "\n".join(
        f"- {name}: {'PASS' if ok else 'FAIL'}" for name, ok in gate_summary.items()
    )
    judge_md = ""
    if judge:
        judge_md = f"""
## Judge 판단
- 근거: {'; '.join(judge.get('reasons') or [])}
- 강점: {'; '.join(judge.get('strengths') or []) or '(없음)'}
- 약점: {'; '.join(judge.get('weaknesses') or []) or '(없음)'}

## 다음 목표
{judge.get('next_goal') or '(없음)'}
"""
    adjustments_md = ""
    if auto_adjustments:
        adjustments_md = "\n## 자동 판정 보정\n" + _ul(auto_adjustments) + "\n"
    return f"""# Product Verdict

## 최종 판정
{verdict}

- 라인: {line} ({'micro-workspace' if line == 'micro' else '일반 Product Factory'})
- Dashboard 추천 버튼: {recommended_action.upper()}

## Gate 결과
{gates}
{judge_md}{adjustments_md}"""


def render_known_issues_md(judge: dict | None, gate_summary: dict, qa: dict | None) -> str:
    lines = ["# Known Issues", ""]
    for name, ok in gate_summary.items():
        if not ok:
            lines.append(f"- gate 실패: {name}")
    if qa:
        for a in qa["anchors"]:
            if not a["alive"]:
                lines.append(f"- anchor 죽음: {a['anchor']}")
        for f in qa["forbidden"]:
            if f["violated"]:
                lines.append(f"- forbidden 위반: {f['rule']}")
    if judge:
        for w in judge.get("weaknesses") or []:
            lines.append(f"- 약점: {w}")
    if len(lines) == 2:
        lines.append("- (알려진 심각한 문제 없음)")
    return "\n".join(lines) + "\n"
