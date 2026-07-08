# Repo Idea Card

레포: langgenius/dify

## 판정
MAYBE

## FAST DROP에 가까운가
NO

## 점수
5

## 한 줄 결론
전체 플랫폼은 너무 무겁지만, 'Human-in-the-loop'가 포함된 에이전틱 워크플로우 시각화 패턴은 즉시 적용 가능한 핵심 가치이다.

## 왜 사람들이 관심 가졌나
LLM을 단순 챗봇이 아니라 복잡한 업무 프로세스(워크플로우)로 구축하고, 이를 로우코드 UI로 관리하며 운영 환경에 배포하려는 니즈가 매우 강함.

## 실제 사용자 고통
- 에이전트 앱 프롬프트 자동 생성 시 잘못된 모드 전송 버그
- 데이터셋 삭제 시 벡터 컬렉션이 남는 리소스 누수 문제
- Human-input 단계 이후 결과 콘텐츠가 출력되지 않는 UI/UX 결함
- 업로드 방식(UI vs API)에 따른 검색 점수(Retrieval score) 불일치

## 기능 요청 신호
- 워크플로우 루프(Loop) 내에 인간 검토(Human review) 노드 추가 기능

## 워크플로우/자동화 신호
- 개발 환경에서 운영 환경으로 워크플로우 임포트 시 툴(Tools) 연결 유실 문제

## 가져올 패턴
노드 기반의 LLM 오케스트레이션 및 Human-in-the-loop 상태 관리 패턴

## 버릴 것
- 멀티 테넌시 및 복잡한 권한 관리 시스템
- 셀프 호스팅을 위한 Docker/K8s 인프라 설정 전체
- 방대한 양의 기본 내장 툴셋(Tools) 구현체

## Dependency / Runtime Risk
- level: high
- reason: Python 백엔드, TS 프론트엔드, Postgres, Redis, Vector DB 등 런타임 의존성이 매우 많아 전체 빌드 및 환경 구축 난이도가 높음.

## 내 현재 병목에 적용
- area: 업무 자동화/OCR
- related_project: Repo Idea Miner
- reason: LLM 에이전트를 활용한 복잡한 업무 자동화 파이프라인을 설계하고 검증하는 구조를 차용할 수 있음.

## 1일 MVP
- status: 가능
- feature: Human-in-the-loop 기반의 단순 LLM 워크플로우 체인
- input: 사용자 입력 쿼리 및 중간 단계 승인/수정 값
- output: 최종 LLM 생성 결과물
- excluded_scope: 벡터 DB 전체 구현, 멀티 테넌시, 복잡한 권한 관리, 셀프 호스팅 인프라
- reason: React Flow 같은 라이브러리를 사용하여 시각적 노드 연결을 구현하고, 백엔드에서 단순한 상태 머신으로 LLM 체인을 실행하는 것은 1일 내 POC 가능함.

## 1일 Pattern PoC
- status: 가능
- idea: 노드 기반의 LLM 프롬프트 시퀀싱 및 상태 관리 패턴
- input: JSON 형태의 워크플로우 정의서 (노드 및 엣지 정보)
- output: 단계별 실행 로그 및 최종 결과값
- reason: Dify의 핵심은 '워크플로우 정의 -> 실행 엔진 -> 상태 저장'의 흐름이며, 이는 경량화된 라이브러리로 구현 가능함.

## 만들면 망하는 이유
- 전체 플랫폼의 거대한 아키텍처를 그대로 복제하려 하면 인프라 설정과 의존성 지옥에 빠져 MVP 단계에서 포기하게 됨.

## 왜 이 판정인가
- 단순 챗봇을 넘어선 '에이전틱 워크플로우'는 현재 AI 서비스의 핵심 트렌드이며, 특히 Human-in-the-loop 패턴은 실무 적용 시 필수적이므로 패턴 추출 가치가 매우 높음.

## 다음 행동
React Flow 기반의 경량 워크플로우 엔진 구현 사례 조사
