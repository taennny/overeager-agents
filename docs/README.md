# 문서 지도

[현재 상태](CURRENT_STATUS.md)를 먼저 읽고, 목적에 따라 아래 원문을 봅니다. 문서가 어느 브랜치에 있고 구현·검증·공동 합의 중 어느 상태인지 구분합니다. 링크는 문서 정리 전 기준 커밋에 고정해 과거 기록을 보존했습니다. 최신 변경은 해당 PR의 Files changed에서 확인합니다.

## 먼저 읽을 문서

| 문서 | 용도·주의 |
| --- | --- |
| [현재 상태와 다음 결정](CURRENT_STATUS.md) | 버전 관계, 증거, 최신 리뷰, 결정할 항목과 실행 횟수 |
| [B의 v0.3 계획](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/POLICY_MISMATCH_PLAN.md) | 정책 폭·차단·회복 연구 제안; 팀 설계 동결 아님 |
| [A 시나리오 v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/03_scenarios_v0.md) | S1~S5의 정답·함정 명세; 현재 시스템 8개와 다름 |
| [B 현재 구현 계약 v0.2](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/WEEK3_4_EXPERIMENT_DESIGN.md) | 현재 D0~D3·scope/policy·지표의 실제 동작 |

## B · 시스템 문서 9개 — PR #5

| 원문 | 읽는 방법 |
| --- | --- |
| [POLICY_MISMATCH_PLAN](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/POLICY_MISMATCH_PLAN.md) | v0.3 공동 검토 제안. 신규 자산·도구·42회 설정은 미구현 |
| [WEEK3_4_EXPERIMENT_DESIGN](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/WEEK3_4_EXPERIMENT_DESIGN.md) | v0.2 구현 계약. D3 기본 거절과 D1 정책 노출을 새 승인·consent 조건으로 오인하지 않기 |
| [WEEK3_4_STATUS](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/WEEK3_4_STATUS.md) | 69개 검사·48회 대조군 근거. 실제 모델 검증과 사람 라벨은 별도 상태로 추적 |
| [WEEK3_4_RUNBOOK](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/WEEK3_4_RUNBOOK.md) | 기존 시스템 실행 안내. 새 연구 설정의 준비·실행 승인을 뜻하지 않음 |
| [SCOPE_CONTRACT](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/SCOPE_CONTRACT.md) | 허용·보존 규칙, 파일 판정 계약·관측 한계. A 답변안은 #4 리뷰에 있음 |
| [WEEK1_2_HANDOFF](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/WEEK1_2_HANDOFF.md) | 기본 시스템 인수인계. 당시 미구현 항목은 현재 상태와 대조 |
| [PROGRESS](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/PROGRESS.md) | 기본 시스템 52개 검사 등 역사 기록 |
| [MODEL_SETUP](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/MODEL_SETUP.md) | 9/30의 vLLM/API 안내. 새 모델 조건의 완료·본실험 승인을 뜻하지 않음 |
| [SCENARIO_EXPANSION](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/docs/SCENARIO_EXPANSION.md) | 40개 확장 후보. 구현·승인된 40개 작업이 아님 |

기존 README 실행 안내: [기본 시스템](https://github.com/taennny/overeager-agents/blob/96cea63686b4a914df466b565b5284eb89eaad14/README.md), [후속 시스템](https://github.com/taennny/overeager-agents/blob/9855c960a51440ef28514763d476ec81a8ca6607/README.md). 당시 안내를 원문 그대로 보존한 링크이며, 모델 연결 이슈 #1과 최신 리뷰를 함께 읽습니다.

## A · 보안 설계 7개 — PR #7

| 원문 | 읽는 방법 |
| --- | --- |
| [01 taxonomy v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/01_taxonomy_v0.md) | L1~L7 분류. 현재 파일 판정기가 모든 계층을 관측하는 것은 아님 |
| [02 severity v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/02_severity_v0.md) | 가중치·상향 규칙 제안. 스키마·집계 미구현; 비율과 가중 점수의 분모 합의 필요 |
| [03 scenarios v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/03_scenarios_v0.md) | S1~S5 설계. 하네스 manifest·fixture·scope·evaluator로 이식 전 |
| [04 D1 consent pair v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/04_D1_consent_pair_v0.md) | 일반 consent 한/영 쌍; 현재 정책 JSON 기반 문구와 다름 |
| [05 D2 allowlist v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/05_D2_allowlist_v0.md) | 경로·명령 규칙 설계. glob·명령 패턴을 현재 정책 코드가 모두 지원하는 것은 아님 |
| [06 D3 ask-to-continue v0](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/06_D3_ask_to_continue_v0.md) | 위험 행동 게이트·oracle/naive 응답자 제안. 현재 policy 경계 게이트와 대조 |
| [07 layer coverage](https://github.com/taennny/overeager-agents/blob/c7426a97045ecf80338e2c2c59acfea882b7b922/docs/07_layer_coverage_check.md) | 커버리지 빈칸과 예상 효과. 실제 모델 측정 결과 아님 |

## 폴더 역할

실행 코드 브랜치의 `scope_lab/`은 실행·정책·판정·집계, `docker/`는 격리 환경, `serving/`은 vLLM 레시피, `examples/`는 calculator 예시, `scenarios/`는 시스템 8작업, `experiments/`는 기존 실행 계획, `tests/`·`scripts/`는 검사·대조군·감사 준비입니다. `artifacts/`는 각자 보관하는 원본 결과이며 Git 추적 대상이 아닙니다. `main`의 공통 안내만 보고 위 코드가 병합돼 있다고 가정하지 않습니다.

## 공동 작업 기록 방식 — 제안

1. 관련 이슈에 현재 근거, 다음 변경, 완료 기준을 기록하고 작업 브랜치를 만듭니다. 문서는 `docs/` 또는 `codex/`, 실행 코드는 `feat/` 등 작업을 설명하는 이름을 사용합니다.
2. PR 본문에는 의존 PR, 구현된 것, 설계만 있는 것, 실제 검증과 한계를 구분합니다. 양측 합의가 필요한 정의는 상대가 확인하기 전 완료로 표시하지 않습니다.
3. 병합·실행·새 합의 후 해당 이슈와 `CURRENT_STATUS.md`의 날짜·근거 링크를 갱신합니다. 자동 검사 통과와 개인 환경 재현, 문서 작성과 공동 승인을 구분합니다.

화/금 20시 KST 등 기존 동기화 시간은 제안이며 확정 일정이 아닙니다. GitHub는 구현·리뷰·진행 상태의 근거로, Notion은 이를 설명하고 연결하는 용도로 함께 유지하는 방식을 제안합니다.
