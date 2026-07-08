# Repo Idea Card

레포: blackholll/loonflow

## 판정
KEEP

## FAST DROP에 가까운가
NO

## 점수
7

## 한 줄 결론
엔터프라이즈급 워크플로우 엔진의 시각적 설계 패턴과 MCP 통합 구조를 통해 고도화된 업무 자동화 도구 구현 가능.

## 왜 사람들이 관심 가졌나
복잡한 비즈니스 프로세스를 코딩 없이 시각적으로 설계하고, 이를 실제 티켓팅/워크플로우 시스템과 연동하여 자동화하려는 니즈가 강함.

## 실제 사용자 고통
- Microsoft Teams SSO 로그인 후 페이지 새로고침 시 세션이 유지되지 않는 인증 불안정성
- 프로세스 설계기 내 역할 태그의 지속적인 UI 깜빡임 현상
- 참여자 유형 설정 시 UUID와 문자열 간의 타입 불일치로 인한 시스템 오류

## 기능 요청 신호
- 복잡한 워크플로우를 자동으로 정리해주는 자동 레이아웃(Auto Layout) 기능

## 워크플로우/자동화 신호
- SSO 인증 환경에서 세션 끊김으로 인한 업무 연속성 저해

## 가져올 패턴
Visual Process Designer <-> Backend Workflow Engine <-> MCP(Model Context Protocol) Server 통합 패턴

## 버릴 것
- 복잡한 엔터프라이즈 권한 관리 및 조직도 체계
- SaaS 에디션 관련 결제 및 관리 모듈
- 상세한 MUI 테마 및 스타일 설정

## Dependency / Runtime Risk
- level: medium
- reason: Django와 React의 풀스택 구조이며, MCP 서버 등 외부 프로토콜 의존성이 있어 초기 환경 설정 및 런타임 구성 비용이 발생함

## 내 현재 병목에 적용
- area: 업무 자동화/OCR
- related_project: Repo Idea Miner
- reason: 워크플로우 시각화 및 자동화 엔진 패턴을 적용하여 아이디어 채굴 프로세스를 자동화하거나, 검증 파이프라인을 시각적으로 구축하는 데 활용 가능

## 1일 MVP
- status: 가능
- feature: 간이 드래그 앤 드롭 노드 기반 액션 실행기
- input: JSON 형태의 노드 연결 정의
- output: 정의된 순서에 따른 Python 함수 순차 실행
- excluded_scope: 전체 UI 프레임워크, 복잡한 권한 관리, SSO 인증 및 세션 관리
- reason: React-flow 같은 라이브러리와 간단한 Python 백엔드를 연결하면 '시각적 정의 -> 실행'이라는 핵심 가치를 빠르게 검증할 수 있음

## 1일 Pattern PoC
- status: 가능
- idea: MCP 서버를 통한 티켓 자동 생성 및 워크플로우 트리거 구현
- input: 특정 이벤트(예: 이슈 생성)
- output: MCP 툴을 통한 자동 응답 및 상태 변경
- reason: 이미 mcp_ticket_server.py가 구현되어 있어 해당 로직을 추출하여 독립적인 POC 구성이 가능함

## 만들면 망하는 이유
- 너무 방대한 엔터프라이즈 기능을 모두 구현하려다 MVP 단계에서 오버엔지니어링될 위험
- 시각적 에디터의 복잡도가 높아 구현 및 유지보수 비용이 급증할 수 있음

## 왜 이 판정인가
- MCP(Model Context Protocol) 지원이라는 최신 AI 인터페이스 트렌드가 반영되어 있어 확장성이 매우 높음
- 단순한 폼 입력을 넘어 '프로세스' 자체를 설계하는 패턴은 업무 자동화 도구의 핵심 경쟁력이 됨

## 다음 행동
React-flow 기반의 유사 워크플로우 라이브러리와 MCP 서버 구현체 비교 분석
