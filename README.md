# Overeager Agents — 코딩 에이전트 범위 이탈 연구

**먼저 읽기:** [v0.3 구현·91개 검사·63회 대조군](docs/V03_IMPLEMENTATION.md) · [현재 상태와 다음 결정](docs/CURRENT_STATUS.md) · [문서 지도](docs/README.md)

사용자가 허용한 범위를 코딩 에이전트가 넘는지, 방어가 범위 이탈과 정상 작업 수행에 어떤 영향을 주는지 연구합니다.

- **A · 태윤 (`taennny`)**: 범위 명세, taxonomy, 시나리오, 방어 정책.
- **B · 승아 (`soooongaaa`)**: 하네스, Docker 격리, oracle, 모델 연결, 실행 파이프라인.

## 현재 버전은 어디에 있는가

2026-10-07 기준, **실행 코드와 보안 설계는 아래 PR에서 검토 중**입니다. 공통 안내 정리는 [PR #8](https://github.com/taennny/overeager-agents/pull/8)로 추적합니다. 이 문서 정리는 코드 PR의 승인이나 공동 설계 확정을 뜻하지 않습니다.

| 작업 | 브랜치 | PR와 진행 관계 |
| --- | --- | --- |
| 기본 실행 루프·Docker·FS 판정기 | [`feat/system-week1-2`](https://github.com/taennny/overeager-agents/tree/feat/system-week1-2) | [#4](https://github.com/taennny/overeager-agents/pull/4) → `main`, 수정 요청 상태 |
| 방어·배치·지표·v0.3 연구 제안 | [`feat/system-week3-4`](https://github.com/taennny/overeager-agents/tree/feat/system-week3-4) | [#5](https://github.com/taennny/overeager-agents/pull/5) → #4의 브랜치, 수정 요청·설계 논의 중 |
| 7계층·심각도·5개 시나리오·D1~D3 설계 | [`docs/week1-3-security`](https://github.com/taennny/overeager-agents/tree/docs/week1-3-security) | [#7](https://github.com/taennny/overeager-agents/pull/7) → `main`, 공동 검토 필요 |

실행 코드를 읽을 때는 `feat/system-week3-4`, 기본 시스템만 검토할 때는 #4, 태윤의 보안 명세는 #7을 봅니다. #4 병합 후 #5의 대상 브랜치를 `main`으로 바꾸는 순서입니다.

## 검증된 것과 남은 것

- **시스템 검증:** 기본 시스템 52개, 후속 시스템 69개 테스트 통과 기록 및 스크립트 대조군 48회 예상 결과 일치. 실제 AI의 범위 이탈률 결과가 아닙니다.
- **모델 연결·사람 라벨:** 구현과 실제 검증을 구분해 [#1](https://github.com/taennny/overeager-agents/issues/1)에서 추적하며, 본실험 결과로 보고하지 않습니다.
- **공동 결정 필요:** 대표 작업, D1 consent 문구·삽입 위치, D3 게이트·응답자, 정책 폭, L7 별도 분석, 지표 분모와 사람 라벨.
- **v0.3 후속 구현:** 사용자 확정 대표 3작업, 격리 `run_tests`, 범위 명세 기반 D3 승인·회복 기록과 42회 설정을 추가했습니다. 코드 검사 91개·정해진 행동 대조군 63회 통과. 실제 Qwen·EXAONE 42회는 서버 연결 대기 중이며, 이 검증은 AI 비교 결과가 아닙니다.

## 작업 상태를 확인하는 곳

| 이슈 | 추적하는 작업 |
| --- | --- |
| [#1 모델 연결](https://github.com/taennny/overeager-agents/issues/1) | 실제 모델 연결·설정·응답 형식·예산 |
| [#2 공동 명세](https://github.com/taennny/overeager-agents/issues/2) | 대표 시나리오·scope·D1/D3·L7·지표 합의와 이식 |
| [#3 협업·재현](https://github.com/taennny/overeager-agents/issues/3) | 두 사람의 환경 재현, 보고 형식과 동기화 절차 |
| [#6 공동 설계 통합](https://github.com/taennny/overeager-agents/issues/6) | 설계 통합, 구현 의존성, 본실험 준비 |

작업별 브랜치와 PR에서 검토하고, 결정한 내용·날짜·근거를 관련 이슈와 [현황 문서](docs/CURRENT_STATUS.md)에 함께 남깁니다. 구현, 검증, 공동 승인을 별도로 표시합니다. 기존 실행 결과 원본은 각자의 `artifacts/`에 보관하고 API 키·접속 정보는 저장소에 올리지 않습니다.
