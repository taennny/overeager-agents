# 3·4주차 실행 안내

전체 설계는 [WEEK3_4_EXPERIMENT_DESIGN.md](WEEK3_4_EXPERIMENT_DESIGN.md).
이 디렉터리의 모든 명령은 저장소 루트에서 실행한다. 새 출력 이름을 사용한다.

## 모의 실험 — 키·GPU 없이 가능

```bash
docker build -f docker/Dockerfile -t overeager-sandbox:week1 .
SCOPE_DOCKER_TESTS=1 python3 -m unittest discover -s tests -v
python3 -m scope_lab.batch run --config experiments/mock.json --out artifacts/mock-v02 --limit 4
python3 -m scope_lab.metrics artifacts/mock-v02 --out artifacts/mock-v02-metrics.json
```

D0/D1의 FS-OSR=1, D2/D3=0, 네 조건 모두 TSR=1을 기대한다. 이것은 모든 조건에서 똑같은
정해진 행동을 내보내는 mock을 사용한 **배선 검사**다. 특히 D1 prompt를 mock이 이해하지 않으므로
“D1은 효과 없다”라는 결과가 아니다. 토큰·ORR은 null이 정상이다. D3 질문 1건은 모의 응답이다.

8개 작업의 정답·무행동·이탈 대조군을 D0/D2로 검증하려면:

```bash
python3 -m scope_lab.batch run --config experiments/controls.json --out artifacts/controls-v02 --limit 48
python3 -m scope_lab.metrics artifacts/controls-v02 --out artifacts/controls-v02-metrics.json
python3 scripts/export_audit.py artifacts/controls-v02 --out artifacts/audit-v02
```

감사 자료의 blind-items.csv는 사람 A/B가 독립 작성한다. oracle-key.csv는 라벨 고정 뒤 합친다.
합친 CSV에는 trial_id,human_a,human_b,adjudicated,oracle 열을 두고 0/1로 입력한다.
`--audit-csv 파일.csv`를 metrics에 추가하면 κ와 precision/recall을 계산한다.
ORR은 별도 JSON에서 `{ "trial_id": {"over_refusal": false, "evidence": "로그 근거"} }` 형식으로
확정한 라벨만 넣고 `--labels`로 전달한다. 미라벨은 자동으로 false 처리하지 않는다.

## 실제 5종 연결

로컬에서 `.env.example`을 복사해 키를 설정한다. 키를 GitHub·채팅·로그에 적지 않는다.
정확한 모델 ID를 먼저 설정한다. GPT·Claude·Solar에는 임의 최신 모델 기본값을 넣지 않았다.

| profile | 모델 환경변수 | 키 | 방식 |
|---|---|---|---|
| gpt | GPT_MODEL | OPENAI_API_KEY | Chat Completions, max_completion_tokens |
| claude | CLAUDE_MODEL | ANTHROPIC_API_KEY | native Messages API |
| exaone | EXAONE_MODEL | VLLM_API_KEY | vLLM 호환 API |
| qwen | QWEN_MODEL (기본 Qwen/Qwen3-8B) | VLLM_API_KEY | vLLM, thinking=false |
| solar | SOLAR_MODEL | UPSTAGE_API_KEY | Chat API |

각자 먼저 다음 smoke의 profile을 바꿔 확인한다.

```bash
python3 -m scope_lab smoke --profile claude --max-tokens 512 --out artifacts/claude-smoke-v02.json
python3 -m scope_lab.batch plan --config experiments/screening.json --out artifacts/screening-plan.json
python3 -m scope_lab.batch run --config experiments/screening.json --out artifacts/screening-live --live --profile claude --limit 6
```

`plan`은 API를 호출하지 않는다. `run --live`는 유료 호출 가능성이 있다. 기본 limit은 20 trial이며
제공사의 전체 청구액 상한을 강제하는 기능은 아니다. trial별 최대 12 calls·출력 2048토큰·재시도 1회,
총 예상 호출·입력 context 비용을 확인하고 제공사별 예산을 설정한다.

모델 다섯 개의 ID·환경변수를 갖춘 후 같은 plan에서 profile을 바꾸며 실행한다. Qwen·EXAONE은
GPU에서 순차 로딩한다. endpoint는 모델 실행 여부를 확인하지 않고 임의 전환하지 않는다.
실제 endpoint·파라미터 호환은 smoke와 짧은 실제 코딩 실행으로 확인해야 한다.
현재 키·GPU가 없어서 실제 모델 응답 검증은 완료하지 않았다.

## 재시작과 로그

같은 명령은 result.json이 있는 trial을 건너뛰고 남은 trial을 진행한다. 코드·이미지·입력이 바뀌면
기존 batch resume를 거부한다. .running이 남았으면 프로세스가 실제 종료됐는지 먼저 확인한다.
attempt-result.json이 없는 attempt는 유료 호출 여부가 불명확하므로 수동 조사 후 새 batch를 만든다.
원시 로그는 artifacts 안에만 두고, fixture 외 실제 자료를 넣지 않는다.

summary JSON/CSV의 planned,missing,invalid,valid를 먼저 본다. pending 0건을 정상 실행 0건과 혼동하지 않는다.
모의 결과와 실모델 결과는 분리하고 논문 표에는 정확한 commit·image ID·model ID·조건·라벨 분모를 적는다.

## 공식 API 근거

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): 기존 하네스 공통 텍스트 프로토콜용. 모든 최신 기능을 쓴다는 의미는 아니다.
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create): system 별도 필드, 메시지 배열, 텍스트 응답·usage 정규화.
- [Solar Chat API](https://console.upstage.ai/api/chat): 모델별 지원 인자는 실제 선택 모델에서 확인.

API 어댑터의 모의 통신 테스트는 실제 제공사 인증·모델 실행 성공을 대체하지 않는다.
