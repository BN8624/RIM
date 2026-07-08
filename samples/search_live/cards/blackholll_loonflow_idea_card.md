# Repo Idea Card

레포: blackholll/loonflow

## 판정
KEEP

## FAST DROP에 가까운가
NO

## 점수
7

## 한 줄 결론
시각적 워크플로우 설계기와 MCP 통합 패턴은 매우 강력하지만, 전체 시스템은 무거우므로 '디자이너-엔진' 핵심 루프만 추출해야 한다.

## 왜 사람들이 관심 가졌나
복잡한 비즈니스 로직을 코딩 없이 시각적으로 설계하고, MCP(Model Context Protocol)를 통해 AI 모델의 컨텍스트를 워크플로우에 통합하려는 니즈가 높음.

## 실제 사용자 고통
- Microsoft Teams SSO 로그인 후 페이지 새로고침 시 세션이 유지되지 않고 로그아웃되는 문제
- 프로세스 설계기에서 역할 태그가 지속적으로 깜빡이는 UI 렌더링 버그
- 참여자 유형 설정 시 UUID 객체를 문자열로 처리하지 못해 발생하는 TypeError

## 기능 요청 신호
- 복잡한 워크플로우를 자동으로 정리해주는 '자동 레이아웃(Auto Layout)' 기능

## 워크플로우/자동화 신호
- SSO 인증 사용 시 세션 끊김으로 인한 사용자 경험 및 업무 연속성 저해

## 가져올 패턴
Visual Node-based Workflow Designer $\rightarrow$ JSON Configuration $\rightarrow$ Plugin-based Execution Engine

## 버릴 것
- 엔터프라이즈급 SaaS 관리 및 결제 기능
- 복잡한 SSO/OAuth 상세 설정
- 상세한 권한 관리 및 멀티 테넌시 시스템

## Dependency / Runtime Risk
- level: medium
- reason: Django와 React 기반의 대규모 풀스택 구조이며, Docker 및 비동기 작업 처리(tasks.py) 등 인프라 설정 복잡도가 높음.

## 내 현재 병목에 적용
- area: 업무 자동화/OCR
- related_project: Repo Idea Miner
- reason: 비즈니스 프로세스 자동화 및 시각적 설계 패턴을 업무 자동화 도구의 핵심 인터페이스로 적용 가능.

## 1일 MVP
- status: 가능
- feature: 간이 시각적 워크플로우 실행기
- input: 드래그 앤 드롭으로 연결된 노드 그래프 (JSON)
- output: 정의된 순서에 따른 백엔드 함수 순차 실행 결과
- excluded_scope: SaaS 계정 관리, 상세 권한 제어, 복잡한 SSO 연동
- reason: React Flow와 같은 라이브러리와 Python 함수 맵핑만으로 핵심 가치(시각적 설계 $\rightarrow$ 실행)를 빠르게 검증할 수 있음.

## 1일 Pattern PoC
- status: 가능
- idea: MCP 기반 AI 에이전트 워크플로우 설계기
- input: AI 도구 노드와 조건 분기 노드의 조합
- output: LLM이 판단하여 경로를 선택하고 도구를 실행하는 자동화 흐름
- reason: Loonflow의 플러그인 아키텍처와 MCP 통합 개념을 차용하여 AI 에이전트의 실행 경로를 시각화하는 POC 구현이 가능함.

## 만들면 망하는 이유
- 전체 시스템을 그대로 복제하려 할 경우, 과도한 인프라 설정과 무거운 Django 구조에 매몰되어 개발 속도가 저하될 위험이 큼
- UI/UX의 세부 버그(깜빡임 등)가 발견되는 것으로 보아, 프론트엔드 상태 관리를 정교하게 설계하지 않으면 사용성이 크게 떨어짐

## 왜 이 판정인가
- 시각적 워크플로우 엔진과 MCP 통합이라는 최신 트렌드의 핵심 패턴을 보유하고 있어 아이디어 가치가 높음
- 단순한 폼 입력을 넘어선 '프로세스 설계'라는 고차원적 자동화 인터페이스를 제공함

## 다음 행동
React Flow 기반의 유사 오픈소스 워크플로우 엔진과 구현 복잡도 및 확장성 비교
