# Top Ideas

## 검색어
automation workflow python

## 전체 요약
- 분석 후보 수: 10
- FAST DROP 수: 0
- KEEP 수: 3
- MAYBE 수: 2
- DROP 수: 2

## Top KEEP
- **pydoit/doit** (score 8): 파이썬 네이티브 DAG 기반의 증분 빌드 패턴은 분석 파이프라인의 효율성을 극대화할 수 있는 핵심 구조다.
- **blackholll/loonflow** (score 7): 엔터프라이즈급 워크플로우 엔진의 시각적 설계 패턴과 MCP 통합 구조를 통해 고도화된 업무 자동화 도구 구현 가능.
- **jmathai/elodie** (score 7): 메타데이터 기반의 파일 자동 정리 패턴과 --dry-run을 통한 안전한 실행 구조가 핵심이며, 업무 자동화 도구로 적용 가능하다.

## Top MAYBE
- **Skyvern-AI/skyvern** (score 5): XPath/DOM 의존성을 제거하고 Vision LLM으로 브라우저를 제어하는 패턴은 매우 강력하나, 전체 시스템의 인프라 의존성이 너무 무겁다.
- **faxad/activflow** (score 5): Django 모델을 상태(State)로 정의하여 비즈니스 워크플로우를 관리하는 패턴은 유용하나, 프로젝트의 유지보수 상태가 매우 낮아 패턴 참고용으로만 적합하다.

## 빠르게 버린 후보
(없음)

## 비교해볼 만한 패턴
- blackholll/loonflow: Visual Process Designer <-> Backend Workflow Engine <-> MCP(Model Context Protocol) Server 통합 패턴
- PrefectHQ/prefect: 상태 기반 워크플로우 오케스트레이션 (State-based Workflow Orchestration)
- Skyvern-AI/skyvern: Vision LLM을 이용해 화면 스크린샷을 분석하고, 이를 기반으로 Playwright 액션(좌표 클릭, 입력 등)을 동적으로 생성하는 'DOM-less' 자동화 루프
- apache/airflow: DAG(Directed Acyclic Graph) 기반의 태스크 의존성 관리 및 상태 기반 실행 엔진
- faxad/activflow: 비즈니스 프로세스의 각 단계(Activity)를 Django 모델로 추상화하고, 이를 통해 데이터 캡처와 검증 로직을 분리하는 상태 기반 워크플로우 엔진 패턴

## 다음 행동
KEEP 후보의 1일 MVP 범위를 확정하고 착수한다.
