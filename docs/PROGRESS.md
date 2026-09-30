# 1·2주차 진행 보고 — B 시스템

작성일: 2026-09-30. 팀 저장소 taennny/overeager-agents, 구현 브랜치 feat/system-week1-2.
이 문서는 구현·검증·공동 승인을 구분한다. 체크박스는 다른 사람 대신 완료하지 않는다.

| 계획 항목 | 현재 상태 | 완료에 필요한 증거 |
|---|---|---|
| 킥오프·OSR/ORR/TSR 통일 | 계약 초안 작성 | 두 사람의 정의·분모 합의 |
| 하네스 ↔ scope 인터페이스 | JSON 입력·실행 가능한 예제 작성 | A의 실제 시나리오 매핑·리뷰 |
| 저장소·브랜치·동기화 | 팀 레포, 시스템 브랜치, CI 구성 | 회의 시간 합의 |
| ReAct형 에이전트 루프 | 구현·단위 검증 | 실제 LLM 코딩 실행은 별도 확인 |
| Docker clean 컨테이너 | 구현·Linux CI 통합 검증 | 각자 로컬 환경 재현도 확인 |
| repo·CI·의존성 | Python 표준 라이브러리, CI 구성 | A/B 각각 로컬 재현 |
| FS-diff oracle v0 | 구현·단위 검증 | 사람 라벨 검증은 4주차 별도 |
| Qwen3-8B·EXAONE 서빙 | 실행 스크립트·연결 클라이언트 준비 | GPU 접근, EXAONE ID, 실제 로딩·응답 |
| 상용 API·키 관리 | 환경변수·모의 HTTP 검증 코드 | 제공사·모델·실제 endpoint 응답 |
| 시나리오 → 실행 → oracle | 계산기 대조군 Docker 통합 검증 | A 공식 시나리오 + 실제 모델 확인 |

## 검증 기록

- 기존 FS oracle·API 클라이언트 39개 + 새 에이전트 루프 8개: 로컬 47개 통과.
- Linux CI: Python 3.9/3.12 각각 일반 테스트 47개 통과. Docker 별도 job에서 통합 테스트 5개 통과. 일반 단위 job의 Docker skip을 통과로 세지 않는다.
- 초기 구현 a8c8f24 검증: [CI 실행 및 로그](https://github.com/taennny/overeager-agents/actions/runs/36686818023). 최신 커밋 결과는 PR Checks를 확인한다.
- 스크립트 대조군은 실제 AI 실험이 아니다. 실제 모델 3종 연결은 미완료다.

## 교수님께 설명할 문장

“1·2주차 시스템 기반으로 에이전트의 행동·관측 루프, 실행마다 초기화하는 Docker 환경,
실행 전후 파일 변경을 정답 범위와 비교하는 oracle을 구현했습니다. 기능 성공과 범위 준수를
분리해 보고하고, 자동 테스트와 알려진 행동 대조군으로 시스템을 검증합니다.
실제 모델 연결, 보안 담당의 공식 시나리오 이식, 두 사람의 재현 확인은 별도 검증 단계로 남겨뒀습니다.”

## 아직 하면 안 되는 주장

- “AI의 이탈률을 측정했다”: 실제 모델 실험·표본 집계 전이다.
- “7계층 전체를 자동 판정한다”: 현재 최종 파일 상태의 경로 단위 측정만 가능하다.
- “oracle 정확도 κ 검증 완료”: 사람의 라벨과 비교한 적 없다.
- “두 사람 실행 성공 / 공동 명세 합의”: 상대의 확인 전이다.
- “세 모델 서빙 완료”: 실제 GPU·상용 endpoint 검증 전이다.

공동 계약, 재현 명령, 지표 정의와 교수님 예상 질문은 [WEEK1_2_HANDOFF.md](WEEK1_2_HANDOFF.md)에 있다.

## 남은 작업 이슈

- [#1 B — 실제 모델 서빙·API 검증](https://github.com/taennny/overeager-agents/issues/1)
- [#2 공동 — scope 계약·A 공식 시나리오 이식](https://github.com/taennny/overeager-agents/issues/2)
- [#3 공동 — 두 사람 로컬 재현·협업 일정](https://github.com/taennny/overeager-agents/issues/3)
