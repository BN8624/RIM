# Repo Idea Card

레포: faxad/activflow

## 판정
MAYBE

## FAST DROP에 가까운가
NO

## 점수
5

## 한 줄 결론
Django 모델을 상태(State)로 정의하여 비즈니스 워크플로우를 관리하는 패턴은 유용하나, 프로젝트의 유지보수 상태가 매우 낮아 패턴 참고용으로만 적합하다.

## 왜 사람들이 관심 가졌나
복잡한 비즈니스 프로세스를 하드코딩하지 않고, 설정과 모델 정의만으로 자동화하려는 니즈

## 실제 사용자 고통
- 기존 Django 프로젝트 통합 방법 및 사용 가능한 옵션에 대한 문서 부족
- on_delete 관련 런타임 에러 발생

## 기능 요청 신호
- 다국어 지원 및 지역화(Internationalization and Localization) 기능

## 워크플로우/자동화 신호
- 기존 프로젝트에 라이브러리를 통합하는 과정에서의 가이드 및 예제 부족

## 가져올 패턴
비즈니스 프로세스의 각 단계(Activity)를 Django 모델로 추상화하고, 이를 통해 데이터 캡처와 검증 로직을 분리하는 상태 기반 워크플로우 엔진 패턴

## 버릴 것
- 오래된 Bootstrap 3.x 기반의 UI
- 특정 서버 환경(Remote Desktop)에서의 win32com 임포트 에러

## Dependency / Runtime Risk
- level: low
- reason: 표준적인 Django 및 PostgreSQL 스택을 사용하며 Docker 설정이 제공되어 환경 구축 리스크가 낮음

## 내 현재 병목에 적용
- area: 업무 자동화/OCR
- related_project: Repo Idea Miner
- reason: 비즈니스 프로세스 자동화를 위한 워크플로우 엔진 구조를 차용하여 업무 자동화 툴의 상태 관리 및 단계별 데이터 수집 로직에 적용 가능

## 1일 MVP
- status: 가능
- feature: 모델 기반의 간단한 상태 전이 시스템
- input: 상태 모델 정의 및 전이 규칙 설정
- output: 단계별 데이터 저장 및 다음 상태로의 전이
- excluded_scope: 복잡한 비즈니스 역할(Role) 매핑, 전체 관리자 UI 구현
- reason: Django의 모델 상속과 기본 CRUD를 이용하면 핵심 전이 로직은 빠르게 구현 가능함

## 1일 Pattern PoC
- status: 가능
- idea: Django 모델을 이용한 상태 머신(State Machine) 구현
- input: AbstractActivity를 상속받은 커스텀 활동 모델
- output: 워크플로우 상태 추적 로그 및 현재 단계의 유효성 검증 결과
- reason: 이미 검증된 Django 모델 구조를 활용하므로 구현 난이도가 낮고 직관적임

## 만들면 망하는 이유
- 프로젝트 유지보수 중단으로 인한 최신 Django 버전과의 호환성 문제 가능성
- 상세 문서 부족으로 인해 라이브러리 형태로 도입 시 학습 비용이 높음

## 왜 이 판정인가
- Django 기반의 비즈니스 프로세스 관리 패턴으로서의 아키텍처적 가치가 있음
- 단순한 상태 머신 라이브러리보다 비즈니스 데이터 모델링에 최적화된 구조를 제공함

## 다음 행동
Django-FSM 등 현대적인 상태 머신 라이브러리와의 구조적 차이점 분석 및 패턴 추출
