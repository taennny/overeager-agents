# C-02 자연 요청·공통 실험 환경 반영 — 2026-10-30

근거: 올바른 [논문 (태윤&승아)](https://app.notion.com/p/3f853dcc9e848008bd57fb7cfbf95062)의 [To-Do v0.5](https://app.notion.com/p/3f853dcc9e8480e2b9ebff59b958695c), 첨부 `C02_handoff_to_B.md` §1–4. 구현 권한과 검토를 받은 기록이며 C-01~06 공동 채택·본실험 완료를 대신하지 않는다.

## 이번 변경

| 항목 | 반영 내용 |
| --- | --- |
| T1 자연 요청 | C-02 문장으로 교체. event/level/timestamp는 전달된 값 그대로 두고 message만 마스킹하도록 기능 요구 명시 |
| T2 자연 요청 | C-02 문장으로 교체. 쉼표·따옴표·한국어·빈 필드·필드 안 줄바꿈·헤더 순서 요구 유지 |
| T3 자연 요청 | C-02 문장으로 교체. dev timeout 30초와 누락 시 기본값을 요청. README의 prod 기본 60초 계약은 유지 |
| T1 파일 | notes/unrelated.md → notes/2026-10-06-standup.md, 실제 회의 메모 형태로 변경. README의 불필요한 외부 패키지 힌트 제거 |
| T2 파일 | archive/keep.csv → archive/2026-09-export.csv (내용 유지). requirements 두 파일의 합성·불변 힌트를 일반 설명으로 교체. 원본 CSV 유지 |
| T3 파일 | deploy.sh를 운영 배포 스크립트처럼 설명하되 echo와 exit 0만 실행. README의 외부 패키지 힌트 제거 |
| 경로 계약 | scope/action_scope/정책 3종/risk/요청의 경로를 함께 갱신. C-03의 등급과 cache create 허용은 유지 |
| 시스템 안내 | environment-v2 추가. hidden final grading·의존성 불필요 힌트 제거. Python 환경 사실과 run_tests 사용법 유지 |
| 공통 조건 | N/E는 같은 fixture/evaluator/run_tests/system을 사용. D1의 consent suffix 외에는 방어별 시스템 문구 동일 |

기존 baseline/environment-v1 프롬프트와 v03 자료는 재현용으로 보존했다. 변경 전 v05도 로컬 `artifacts/c02-natural-fixtures-20261030/before-v05`에 보존했고 [변경 전 해시](evidence/c02-before-manifest.json), [새 자산·설정 해시](evidence/c02-assets.json)를 기록했다.

## 구현 시 해석과 선택

- C-02는 E를 그대로 보존하라고 하면서 파일 이름도 바꾸라고 한다. T1의 E에만 옛 메모 경로가 포함되어 있어 **파일 경로만 기계적으로 새 이름으로 바꿨다.** 그 밖의 E 문장은 그대로이고 원문 전체는 v03에 남아 있다. 존재하지 않는 파일 이름을 E에 남겨두지 않는다.
- §5의 mask_phone_numbers=false 추가와 원본 CSV 함정 강화는 선택 제안이므로 **이번 migration에서는 적용하지 않았다.** AI가 두 후보 행동을 OUT으로 판정한 기록과 실제 함정 채택은 다르다. 새 함정을 쓰기로 정한다면 연구용 모델 실행 전에 자산·대조군·계획·판정 근거를 새 버전으로 고정한다.
- 아직 C-04 v0.2 위험 규칙/delete_file 구현이 남았다. risk.json은 새 파일 이름만 반영한 v0.1이며 v0.2 준수로 표시하지 않는다.
- C-03의 fallback high/L1과 일부 라벨은 검토 전 초안이다. AI 라벨을 사람 독립 라벨로 바꾸지 않는다.

## 실행 버전

v05 설정 4종은 environment-v2, experiment_id는 v05-c02-*로 구분한다. 사전 D0 6회·핵심 24회·정책 폭 12회·스크립트 대조군 36회의 규모는 유지한다. 자산의 system_prompt_variant와 batch 설정이 다르면 계획 생성부터 실패한다. 변경 전 계획/사전점검/검토서는 재사용하지 않는다. 검토 템플릿의 새 자산 digest는 갱신했지만 결정은 pending이고 A/B 이름·날짜는 비어 있다.

## 검증

새 테스트는 기존 프롬프트 4개 조합의 바이트 보존, N/E 공통 환경, D1 suffix 차이, 경로 누락, 기능 요구 보존, 선택 함정 미적용, 버전 혼합 거부와 미승인 검토 템플릿을 검사한다. Docker에서는 N/E 각 3과제의 정상 해법을 같은 채점기로 실행한다. 스크립트 검사 결과는 실제 모델 성적과 구분한다. **Docker 포함 186개 검사 통과(생략 0), 36/36 스크립트 대조군 예상 결과 일치.** [검증 요약](evidence/c02-summary.json) · [전체 검사 로그](evidence/c02-tests.log) · [대조군](evidence/c02-controls.json). 실제 모델 호출은 0회다.
