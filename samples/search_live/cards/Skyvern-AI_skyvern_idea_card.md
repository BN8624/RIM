# Repo Idea Card

레포: Skyvern-AI/skyvern

## 판정
MAYBE

## FAST DROP에 가까운가
NO

## 점수
5

## 한 줄 결론
XPath/DOM 의존성을 제거하고 Vision LLM으로 브라우저를 제어하는 패턴은 매우 강력하나, 전체 시스템의 인프라 의존성이 너무 무겁다.

## 왜 사람들이 관심 가졌나
기존의 Selenium/Playwright 기반 자동화는 웹사이트 레이아웃이 조금만 바뀌어도 XPath가 깨져 유지보수 비용이 극심했는데, 이를 AI 비전으로 해결하려 함.

## 실제 사용자 고통
- 웹사이트 구조 변경 시 자동화 스크립트가 즉시 파손됨
- 복잡한 DOM 구조에서 정확한 선택자를 찾는 작업의 피로도
- Docker 환경에서의 루프백 제한으로 인한 셀프 힐링 기능 작동 불능

## 기능 요청 신호
- Docker 환경 내 self-heal 기능을 복구하기 위한 게이트웨이 허용 리스트 도입

## 워크플로우/자동화 신호
- 보안 강화 조치 이후 로컬 개발 환경에서 핵심 기능인 self-heal 사용 불가

## 가져올 패턴
Vision LLM을 이용해 화면 스크린샷을 분석하고, 이를 기반으로 Playwright 액션(좌표 클릭, 입력 등)을 동적으로 생성하는 'DOM-less' 자동화 루프

## 버릴 것
- 에이전트 스웜(Swarm)의 복잡한 오케스트레이션
- Postgres 기반의 상태 저장 및 이력 관리 시스템
- 노코드 워크플로우 빌더 UI

## Dependency / Runtime Risk
- level: high
- reason: Playwright 브라우저 바이너리, Postgres DB, 고비용의 Vision LLM API가 모두 필수적이며, 환경 설정 난이도가 높음.

## 내 현재 병목에 적용
- area: 업무 자동화/OCR
- related_project: Repo Idea Miner
- reason: 웹 기반 워크플로우 자동화 및 비전 분석을 통한 요소 식별 패턴을 적용할 수 있음.

## 1일 MVP
- status: 가능
- feature: 단일 페이지 비전 기반 액션 생성기
- input: 웹페이지 스크린샷 + 수행할 작업(텍스트)
- output: Playwright 클릭 좌표 및 실행 코드
- excluded_scope: 에이전트 스웜 구조, 데이터베이스 연동, 노코드 UI, 셀프 힐링 루프
- reason: 전체 프레임워크를 제외하고 '스크린샷 -> LLM -> 좌표 추출 -> Playwright 실행'의 단일 파이프라인만 구현하면 1일 내 가능함.

## 1일 Pattern PoC
- status: 가능
- idea: DOM 분석 없이 스크린샷만으로 버튼 위치를 찾아 클릭하는 PoC
- input: 특정 웹사이트 URL
- output: 목표 버튼 클릭 성공 여부
- reason: GPT-4o 등 최신 Vision 모델의 좌표 추출 능력을 검증하는 수준이므로 구현이 간단함.

## 만들면 망하는 이유
- Vision LLM의 토큰 비용이 매우 높아 상용화 시 비용 효율성 문제 발생
- 좌표 추출의 비결정론적 특성으로 인해 100% 신뢰도가 필요한 엔터프라이즈 환경에서 불안정함
- 인프라 설정(Postgres, Playwright)의 무거움으로 인해 진입 장벽이 높음

## 왜 이 판정인가
- KEEP 사유: 기존 RPA의 최대 난제인 'Selector 유지보수'를 완전히 해결하는 패러다임 시프트적 접근임.
- MAYBE 사유: 아이디어는 훌륭하나 런타임 리스크가 너무 크고, MVP 수준으로 축소했을 때의 가치가 전체 시스템의 가치보다 현저히 낮음.

## 다음 행동
유사한 Vision-based Browser Agent 레포(예: LaVague 등)와 구현 복잡도 비교
