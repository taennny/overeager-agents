# v0.5 재현·실행 안내

10/30 사용자 위임 후속: [6회 실행 전 조건·이유](experiments/20261030-delegated-preflight-protocol.md)에 따라, 이번 D0 6회는 사용자가 AI에 조건·판정을 명시 위임했다. 별도 `design-review-delegated-v0.1` 기록을 사용하며 A/B 공동 채택으로 세지 않는다. 이 기록은 24회/정책 폭 비교를 열지 않는다. 원본 팀 검토 양식은 pending으로 보존한다.

10/30 이전 준비 기록: 현재 C-04 도구는 overeager-sandbox:c04-v02를 사용한다. [다음 실행 준비](NEXT_STEPS.md)의 미결정·예산 항목을 확인하고 실제 채택 기록을 준비한 뒤 유료 실행한다.

[항목 매핑·한계](V05_SYSTEM.md)를 먼저 본다. 기존 48회 [API 안내](CLAUDE_GPT_PILOT.md)는 이전 자산·D3-policy 기록이다.

## 1. API 없이 A/B 재현

정확한 PR 코드 커밋을 checkout한 깨끗한 작업 폴더에서 Python 3.9+와 Docker를 준비한다. API 키는 필요 없다.

```sh
git rev-parse HEAD
git status --short
docker build -f docker/Dockerfile -t overeager-sandbox:c04-v02 .
python3 -m scope_lab.reproduce --actor B --image overeager-sandbox:c04-v02 --out artifacts/v05-b
```

A는 `--actor A --out artifacts/v05-a`로 실행한다. 6/24/12/36셀 계획, 전체 테스트와 Docker 36대조군을 검사한다. 출력은 새 폴더만 허용한다. 모델 호출은 없다.

- evidence.json: 커밋·코드 hash·tracked 수정 여부·Python/OS/아키텍처·Docker 버전·이미지 ID/platform·Dockerfile/자산 hash·상태.
- tests.log: Docker 포함 전체 unittest와 skip 여부.
- controls-validation.json: 36셀 예상/실제 벡터·정리 성공·all_passed.
- controls-metrics.json: 관측별 집계. ORR 사람 라벨 미작성은 null.
- controls/: 개별 계획·스냅샷·도구 로그·평가 원본. scripted_control_not_llm 자료다.

같은 Dockerfile도 플랫폼/레이어 차이로 image ID가 다를 수 있다. 동일 이미지 재현은 B의 검증 이미지를 docker save로 공유하고 A에서 docker load해 기록된 image ID로 실행한다. 이미지 공유·플랫폼/에뮬레이션 지원은 실제 환경에서 확인한다. 다른 이미지를 썼다면 차이를 기록하고 동일 이미지 완료로 표기하지 않는다.

```sh
python3 -m scope_lab.reproduce --compare artifacts/v05-b/evidence.json artifacts/v05-a/evidence.json
```

비교기는 커밋·코드·이미지·플랫폼·자산·계획, clean 상태에서 검사와 36대조군 통과를 확인한다. actor는 자기 신고이고 실제 두 사람/두 환경이라는 인증은 아니다. 양측이 실행 사실을 확인해 #3에 증거를 연결해야 B-18 완료다. CI는 A 환경이 아니다. CI의 임시 merge commit이 다르면 코드 hash도 확인하되 동일 커밋이라고 쓰지 않는다.

## 2. 무료 계획 출력

```sh
python3 -m scope_lab.batch plan --config experiments/v05-preflight.json --out artifacts/v05-preflight-plan.json
python3 -m scope_lab.batch plan --config experiments/v05-core.json --out artifacts/v05-core-plan.json
python3 -m scope_lab.batch plan --config experiments/v05-policy-width.json --out artifacts/v05-width-plan.json
```

핵심은 D0 6+D1 6+D2-fit 6+D3-risk 6=24셀. 기본 점검 D0 6셀은 별도 단계로 자동 재사용하지 않는다. 정확한 셀·trial_id·자산 fingerprint가 출력된다. 절대 경로 때문에 컴퓨터별 trial_id는 다를 수 있어, 자산 fingerprint와 재현 증거를 비교한다.

## 3. 팀 결정 기록

`experiments/v05-design-review.template.json`은 미승인 양식이다. 실제 C-02~06 검토 뒤에만 검토자 A/B·날짜·결정 근거 및 decision=adopt_for_pilot을 입력한다. AI가 합의를 대신 작성하지 않는다. 자산이 바뀌면 아래 fingerprint를 확인해 새 기록을 만든다.

```sh
cp experiments/v05-design-review.template.json artifacts/v05-design-review.json
python3 -c 'from scope_lab.batch import make_plan,digest; p=make_plan("experiments/v05-core.json"); print(digest(sorted({c["fingerprint"] for c in p["trials"]})))'
```

기록 검증은 필드/자산 일치 검사이며 사람 신원/동의 인증이 아니다. team_adopted=false인 원본 제안을 덮어쓰지 않고, 채택 기록을 해당 실행에 별도 보관한다.

## 4. 일반 유료 API 실행 절차 — 위임 6회 결과는 별도 문서 참조

환경 변수는 ANTHROPIC_API_KEY, CLAUDE_MODEL, OPENAI_API_KEY, GPT_MODEL이다. 실제 사용 가능한 정확한 모델 ID를 넣고 키 값은 채팅·Git·노션에 올리지 않는다. 공식 API endpoint를 사용한다. `python3 -m scope_lab.api_pilot`은 키/설정만 검사하며 출력 셀 수는 legacy이므로 새 실행에는 아래 v05 설정을 사용한다.

실제 설계 결정·모델 접근·예산이 준비된 후에만 한 번에 한 모델 한 trial로 실행한다. 자동 retry=0이다.

```sh
python3 -m scope_lab.batch run --config experiments/v05-preflight.json --out artifacts/v05-live-preflight --image overeager-sandbox:c04-v02 --live --profile claude --limit 1 --design-review artifacts/v05-design-review.json
```

같은 폴더/설정으로 남은 Claude 셀을 하나씩, GPT는 --profile gpt로 하나씩 실행한다. 모델·이미지·자산·코드 변경 시 새 폴더/점검이 필요하다. 실패 셀을 임의 삭제하거나 성공할 때까지 몰래 재시도하지 않는다.

```sh
python3 -m scope_lab.readiness artifacts/v05-live-preflight --out artifacts/v05-live-readiness.json
```

각 모델의 3작업에 유효 D0 성공이 있고 오류가 없는지 검토한다. 이는 작업 가능성/연결 기준이지 0% 이탈이면 연구 중단하는 기준이 아니다. 원본 6결과와 코드·모델·설정·이미지 일치를 검증한 뒤 팀 판단으로 24회에 진행한다.

```sh
python3 -m scope_lab.batch run --config experiments/v05-core.json --out artifacts/v05-live-core --image overeager-sandbox:c04-v02 --live --profile claude --limit 1 --preflight artifacts/v05-live-preflight --design-review artifacts/v05-design-review.json
```

정책 폭 12회는 별도 v05-policy-width.json과 새 출력 폴더다. 중간 결과를 보고 같은 실험의 조건을 바꾸지 않는다. 미실행·오류·관측 누락도 남긴다.

## 5. 결과와 사람 라벨

```sh
python3 -m scope_lab.metrics artifacts/v05-live-core --out artifacts/v05-live-metrics.json
```

무료 대조군 집계는 입력을 artifacts/v05-b/controls로 바꾼다. JSON의 observation_rates에 각 분자/분모/unknown/bounds가 있으며 동명 CSV도 생성한다. ORR은 trial_id별 {"over_refusal": true 또는 false, "evidence": "실제 로그 근거"} 매핑 JSON을 작성해 --labels로 전달한다. 미작성은 null이다.

cleanup_error면 중지하고 컨테이너/staging 정리를 확인한다. 관측된 FS 위반은 보존한다. 재현 도구는 실패를 failed_infrastructure/failed_tests/failed_controls로 남긴다. A 환경, 실제 API, 사람 라벨, 팀 채택, main 병합은 각기 별도 증거가 필요하다.

## 6. 10/30 위임된 소액 예비실험 재현 안내

아래 실행은 실제 유료 요청이다. 원본 결정은 당시 작업 폴더의 plan_id에 고정되어 있다. 다른 경로에서는 plan_id가 달라질 수 있으므로 원본 기록을 승인된 새 실행으로 복사하지 않는다. 새 실행의 권한·조건·남은 예산을 확인하고 별도 기록해야 한다. CI의 복사 기록은 모의 HTTP 테스트 전용이며 사람 승인/유료 실행 증거가 아니다.

```sh
PYTHONPATH=. python3 scripts/run_delegated_preflight.py --env-file /absolute/private/path/.env --out artifacts/new-delegated-preflight
```

스크립트는 깨끗하게 커밋된 코드/명세와 새 출력 폴더만 허용한다. 원본 키 파일은 저장소에 올리지 않는다. manifest·비용 장부·원시 trial·집계를 보존하며, 모델/실행 오류가 나면 중단한다. 기능 실패는 유지한 채 다른 대표 과제까지 확인하고, 성공까지 자동 반복하지 않는다.
