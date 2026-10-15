> 2026-10-14: 이 문서의 48회 설정은 legacy 기록이다. 새 6/24/12회 및 D3-risk 실행은 [v0.5 안내](V05_REPRODUCE.md)를 사용한다. 기존 파일/조건은 비교 보존하며 최신 팀 합의를 뜻하지 않는다.

# Claude·GPT 우선 예비실험 — 2026-10-13

승아의 결정: 이번 예비실험은 Claude API와 GPT API 두 모델로 먼저 진행한다.
Qwen·EXAONE·Solar는 보류한다. GPU/Ollama 문제 해결은 이 실험의 선행 조건이 아니다.
연구 질문·T1~T3·scope·정책·격리·채점 기준은 유지한다. 기존 42회 로컬 모델 결과와 새 결과를 합산하지 않는다.

## 지금 준비된 것과 필요한 것

- 대표 3작업, scope.json, 좁음/적절함/넓음 정책 9개, 독립 evaluator는 이미 있다. 다시 작성할 일이 아니다.
- Claude Messages / GPT Chat Completions 어댑터를 기존 공통 JSON 행동 루프에 연결했다. ChatGPT/Claude 웹앱·Codex/Claude Code의 성능을 측정하는 것이 아니다.
- `api-smoke.json`(기본 코딩 2회), `api-preflight.json`(D0 6회), `api-pilot.json`(48회 후보)을 추가했다. 계획 생성은 호출/결제를 하지 않는다.
- 기본 6회에서 각 모델·작업의 유효 성공을 확인한 후에만 방어 비교를 시작한다. 원시 결과·코드·모델·이미지·자산이 바뀌면 새 점검이 필요하다.
- 한 번에 지정 모델의 미완료 작업 1개만 실행한다. 자동 재시도 0, 최대 24단계·300초, 응답당 최대 4096토큰, 요청 본문 최대 128 KiB. 요청 크기 초과는 호출 전에 중단한다.
- **실제 API 연결은 미검증.** 두 키와 정확한 모델 ID가 필요하다. 키 값은 채팅·GitHub·Notion에 넣지 않는다.
- 태윤의 승인·사람 라벨·본실험 동결을 코드 검사로 대신 완료 처리하지 않는다.

## 비용과 모델 설정

각 제공사 1만 원(총 2만 원)은 사용자 계획 예산이다. 코드의 단계/토큰/요청 크기 제한은 원화 결제 상한이 아니다.
현재 정확한 모델과 단가가 미정이므로 48회를 이 예산으로 완료할 수 있다고 보장하지 않는다.
모델별 첫 코딩 작업 후 제공사 사용량/청구와 로그 토큰을 확인하고 다음 1회를 실행한다. 자동 충전·추가 결제는 이 실행 절차에 없다.
API 오류에도 비용이 생길 수 있으므로 실패 로그의 토큰 값이 없다고 무료 호출로 계산하지 않는다.

`CLAUDE_MODEL`, `GPT_MODEL`에 사용할 계정에서 접근 가능한 정확한 ID를 지정한다. 가능하면 고정 버전을 쓰며 요청 ID와 반환 모델명을 모두 기록한다. 모델 선택/가격 확인 전 자동 기본 모델은 지정하지 않는다.
두 모델 모두 sampling은 `provider-default`로 명시적으로 기록한다. temperature·seed를 동일하게 고정했다고 주장하지 않는다. GPT 출력 상한에는 추론 토큰이 포함될 수 있으므로 같은 4096이라는 수가 같은 가시 출력/계산량을 뜻하지 않는다.
JSON은 공통 프롬프트로 요청하며 강제 JSON 변환·코드 펜스 제거·다른 모델의 수정은 하지 않는다. 포맷 오류도 기록한다.

## 실행 순서 (Docker + Python, GPU 불필요)

저장소의 `.env.example`을 로컬 `.env`로 복사해 아래 네 값을 입력한다. 이 파일은 Git에서 제외되고 자동 로드하지 않는다.

```text
ANTHROPIC_API_KEY
CLAUDE_MODEL
OPENAI_API_KEY
GPT_MODEL
```

```bash
# 비밀 파일을 올리지 않고 현재 셸에만 로드
set -a
source .env
set +a

# 무료 오프라인 구성 확인: 키 값·모델 응답을 출력하지 않음
python3 -m scope_lab.api_pilot

docker build -f docker/Dockerfile -t overeager-sandbox:api-v04 .

# 먼저 같은 T1 코딩 작업을 모델별 1회씩. 둘을 자동 연속 실행하지 않는다.
python3 -m scope_lab.batch run --config experiments/api-smoke.json \
  --out artifacts/api-smoke-001 --image overeager-sandbox:api-v04 \
  --live --profile claude --limit 1
# 결과·사용량을 확인한 뒤:
python3 -m scope_lab.batch run --config experiments/api-smoke.json \
  --out artifacts/api-smoke-001 --image overeager-sandbox:api-v04 \
  --live --profile gpt --limit 1
```

첫 실행을 확인한 뒤 `--config experiments/api-preflight.json --out artifacts/api-preflight-001`로 바꿔 모델별 3작업을 한 번에 1개씩 실행한다. 같은 폴더로 재실행하면 완료된 작업을 건너뛰지만, 중단된 유료 요청을 조용히 재전송하지 않는다. smoke 결과를 preflight에 복사하지 않는다.

```bash
python3 -m scope_lab.readiness artifacts/api-preflight-001 \
  --out artifacts/api-preflight-001/readiness.json
python3 -m scope_lab.metrics artifacts/api-preflight-001 \
  --out artifacts/api-preflight-001/summary.json
```

6회가 완료되고 각 모델·작업이 기본 상태에서 성공하면, 비용·팀 기준을 검토하여 48회 후보의 일부 또는 전체를 진행한다. 첫 성공은 공학적 연결 점검이며 연구 결론이 아니다.

```bash
# 여전히 호출 한 번당 한 작업만 실행. --preflight 없이 방어 비교 불가.
python3 -m scope_lab.batch run --config experiments/api-pilot.json \
  --out artifacts/api-pilot-001 --image overeager-sandbox:api-v04 \
  --live --profile claude --limit 1 --preflight artifacts/api-preflight-001
```

각 작업 24단계이므로 `--limit 1`은 API 요청 1회가 아니라 **코딩 작업 1회(최대 24요청)**다.
진행할 모델은 `--profile gpt` 또는 `claude`로 지정한다. 두 키/모델 ID는 최초 계획 잠금 전에 모두 설정해야 한다.
예산이 부족하면 중단하고 미완료 셀을 그대로 보고한다. 성공한 셀만 모아 완성된 비교로 보고하지 않는다.

## 태윤이 작성·검토한 곳과 반영 상태

2026-10-13 GitHub에서 원문을 읽고 대조했다.

- [PR #7](https://github.com/taennny/overeager-agents/pull/7), `docs/week1-3-security`: 태윤의 7개 문서(7계층, 심각도, S1~S5, D1, D2, D3, 커버리지). 원문 작성 커밋 `c7426a97045ecf80338e2c2c59acfea882b7b922`. 후속 README/진행 정리는 승아 계정의 변경이다. PR은 아직 열려 있다.
- [#4 리뷰](https://github.com/taennny/overeager-agents/pull/4#pullrequestreview-5438146770): 네트워크 사전 안내 제거·합성 fixture 추적 수정은 main에 반영됐다.
- [#5 리뷰](https://github.com/taennny/overeager-agents/pull/5#pullrequestreview-5438272652): 일반 consent D1·D3 조건 이름 구분은 main에 반영됐다. 대표 작업/정책 폭 통합 제안도 이미 있다.
- [PR #10](https://github.com/taennny/overeager-agents/pull/10): 대표 3작업·격리 run_tests·범위 기반 모의 승인·행동 지표·기존 42회 감사와 현재 API 전환 준비. PR #9 구현을 포함한다.

| 태윤의 원안 | 현재 대표 3작업과의 관계 | 이번에 처리한 상태 |
| --- | --- | --- |
| S1 임시 파일 정리 + 비밀 백업 삭제 | T1은 마스킹 작업으로 다른 과제. 개인정보와 관련돼도 같은 S1 데이터가 아님 | 원안을 보존. T1에서 비밀 열람/유출을 측정했다고 주장하지 않음 |
| S2 개발 로그 설정, 운영 설정 보존 | T3 개발 timeout 설정과 같은 Config 계열이나 다른 요청·fixture | 이미 있는 T3를 사용, S2 그대로 이식했다고 하지 않음 |
| S3 lint 수정, 의존성 보존 | T2 CSV의 의존성 보존은 일부 겹치지만 lint 과제가 아님 | 이미 있는 T2를 사용, S3와 동일 표본으로 세지 않음 |
| S4 Git staging / S5 테스트만 실행 | T1~T3의 전용 비교 과제에 없음 | 별도 후속. 7계층 전체를 구현·측정했다고 하지 않음 |
| D1 일반 consent | 시스템 끝 삽입, 정책과 무관, 제거하면 D0와 일치 | 반영 및 검사됨 |
| D2 allowlist | scope/policy 분리, narrow/fit/wide, 격리 테스트 | 반영 및 검사됨 |
| D3 위험 행동 게이트·oracle/naive 응답자 | 현재는 **정책 밖 요청** + 범위 기반 모의 응답자 | 게이트 차이를 명시. 실제 사람 승인·위험 기반 D3·naive를 완료 처리하지 않음 |
| L7 AST/텍스트 diff·severity 가중·네트워크/셸 관측 | 현재 FS 및 제한된 행동 판정의 관측 범위 밖/추가 구현 후보 | API 연결의 선행 조건에서 제외, 별도 확장 검토 |

대표 범위를 다시 작성할 필요는 없다. 남은 팀 확인은 위 D3/커버리지 차이를 본실험에서 어떻게 취급할지와 사람 판정·평가 과제·규모 확정이다.

## 근거

- [OpenAI Chat Completions 요청 형식](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Anthropic Messages 요청 형식](https://platform.claude.com/docs/en/api/messages/create)
- [기존 5주차 감사 기록](WEEK5_READINESS.md)

이 문서의 API 전환이 기존 Ollama 우선 계획보다 우선한다. 과거 실험 파일/설정은 재현용으로 유지한다.
