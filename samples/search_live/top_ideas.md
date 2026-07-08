# Top Ideas

## 검색어
automation workflow python

## 전체 요약
- 분석 후보 수: 3
- FAST DROP 수: 0
- KEEP 수: 1
- MAYBE 수: 2
- DROP 수: 0

## Top KEEP
- **blackholll/loonflow** (score 7): 시각적 워크플로우 설계기와 MCP 통합 패턴은 매우 강력하지만, 전체 시스템은 무거우므로 '디자이너-엔진' 핵심 루프만 추출해야 한다.

## Top MAYBE
- **langgenius/dify** (score 5): 전체 플랫폼은 너무 무겁지만, 'Human-in-the-loop'가 포함된 에이전틱 워크플로우 시각화 패턴은 즉시 적용 가능한 핵심 가치이다.
- **martinrusev/imbox** (score 5): 이메일을 JSON으로 변환하여 에이전트 입력값으로 만드는 패턴은 유용하나, IMAP 서버별 파싱 호환성 문제가 심각하여 라이브러리 자체보다는 데이터 구조 설계 패턴만 참고할 가치가 있다.

## 빠르게 버린 후보
(없음)

## 비교해볼 만한 패턴
- langgenius/dify: 노드 기반의 LLM 오케스트레이션 및 Human-in-the-loop 상태 관리 패턴
- martinrusev/imbox: IMAP 프로토콜을 통해 수집한 이메일 데이터를 LLM이 읽기 좋은 정형 JSON 구조(Struct)로 매핑하는 데이터 파이프라인 패턴
- blackholll/loonflow: Visual Node-based Workflow Designer $\rightarrow$ JSON Configuration $\rightarrow$ Plugin-based Execution Engine

## 다음 행동
KEEP 후보의 1일 MVP 범위를 확정하고 착수한다.
