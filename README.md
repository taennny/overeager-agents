# Overeager Agents — 코딩 에이전트 범위 이탈 연구

**현재: 최신 노션 C-02/C-03/C-04 구현 초안·API 없는 검증(2026-10-30).** 연구 질문은 “D1·D2·D3가 범위 이탈을 얼마나 줄이며, 정상 작업 수행에 어떤 비용을 만드는가?”입니다. 정책의 좁음·적절함·넓음은 원인을 설명하는 보조 분석입니다. Claude·GPT 연결 점검은 완료했고 최신 v0.5 연구용 실행은 준비 중입니다. Qwen·EXAONE·Solar는 보류합니다.

**협업 방식:** 모든 변경은 코드·문서·검증 근거를 함께 GitHub PR에서 관리합니다. [지금 다음 할 일](docs/NEXT_STEPS.md).

**실험·결과 공유:** [전체 정리](docs/experiments/README.md) · [검토·재현 안내](docs/REVIEW_HANDOFF.md).

**먼저 읽기:** [위험 규칙·삭제 도구](docs/C04_RISK_DELETE_20261030.md) · [최신 요청·실험 파일 반영](docs/C02_NATURAL_FIXTURES_20261030.md) · [B-10~19 구현·한계·검증](docs/V05_SYSTEM.md) · [재현·실행 안내](docs/V05_REPRODUCE.md) · [현재 상태](docs/CURRENT_STATUS.md) · [문서 지도](docs/README.md).

2026-10-15 후속: [태윤 보안 기준 검토·B 회신](docs/SECURITY_REVIEW_REPLY_20261015.md) · [심각도 저장·집계 안내](docs/SEVERITY_MEASUREMENT.md). 기존 전체 FS-OSR을 유지하고 등급별 지표를 추가합니다. 실제 작업별 등급 채택은 별도입니다.

## 코드와 팀 결정

- A · 태윤: 범위·시나리오·위험 규칙·측정 계층의 공동 결정.
- B · 승아: 하네스·격리·계측·집계·실행·재현.
- `research_scenarios/v05`는 검토 가능한 구현 제안입니다. `team_adopted: false`이며 C-02~06의 팀 합의를 대신하지 않습니다.
- 10/30 최신 노션 C-02/C-03/C-04 대조 후속은 `codex/c03-scope-grading-20261030` 검토용 후속 브랜치입니다. [반영 범위·검증·사람 판정 준비](docs/C03_SCOPE_REVIEW_20261030.md)를 확인하세요.
- 기반 v0.5 통합은 [초안 PR #11](https://github.com/taennny/overeager-agents/pull/11)의 `codex/v05-system-20261014` 작업 브랜치입니다. main 병합 여부는 [현재 상태](docs/CURRENT_STATUS.md)와 PR을 확인합니다. #7 보안 문서 원안은 수정하지 않았습니다.
- 기존 v03 자산·실험 설정 62파일 해시를 보존합니다. 기존 D3-policy 결과와 새 D3-risk 결과를 합치지 않습니다.

## API 없이 검사하기

Python 3.9 이상과 Docker가 필요합니다. 저장소 루트에서 실행합니다.

```sh
python3 -m unittest discover -s tests -v
docker build -f docker/Dockerfile -t overeager-sandbox:c04-v02 .
python3 -m scope_lab.reproduce --actor B --image overeager-sandbox:c04-v02 --out artifacts/v05-b
```

마지막 명령은 전체 Docker 검사와 **36회 스크립트 대조군**을 실행하고 코드·이미지·자산·결과 증거를 저장합니다. 실제 AI 모델 결과가 아니며 API를 호출하지 않습니다. 매번 새 출력 폴더를 지정합니다. 태윤 환경에서는 같은 커밋·이미지로 `--actor A`를 사용합니다. CI 통과는 태윤 환경 실행을 대신하지 않습니다.

## 새 실행 계획

| 설정 | 셀 수 | 목적 |
| --- | ---: | --- |
| `experiments/v05-preflight.json` | 6 | Claude·GPT × 대표 3작업 × D0, 연결·작업 가능성 |
| `experiments/v05-core.json` | 24 | 2모델 × 3작업 × D0/D1/D2-fit/D3-risk |
| `experiments/v05-policy-width.json` | 12 | D2 narrow/wide 보조 분석 |
| `experiments/v05-controls.json` | 36 | 정상·과잉·무행동 스크립트 × 3작업 × 4방어 |

```sh
python3 -m scope_lab.batch plan --config experiments/v05-core.json --out artifacts/v05-core-plan.json
```

계획 출력은 키·GPU·네트워크가 필요 없습니다. 별도 점검 6회와 핵심 비교 D0 6회는 자동 재사용하지 않습니다. 24회는 점검 후보이며 통계적 우열을 주장할 본실험 표본이 아닙니다. 기존 48회 계획은 legacy로 보존했습니다.

실제 유료 실행은 팀 결정 기록과 정확한 모델 ID·환경변수 준비 뒤 [새 실행 순서](docs/V05_REPRODUCE.md)에 따라 진행합니다. 이번 v0.5 작업에서는 유료 호출을 하지 않았습니다. 과거 로컬 모델 42회는 [기존 감사 기록](docs/WEEK5_READINESS.md)과 별개입니다.

## 측정 범위

FS-OSR은 최종 파일 변경에 대한 수치입니다. 요청·차단·승인·실행·효과·불명 상태는 따로 기록합니다. 직접 read_file 관측은 추가했지만 모든 셸 읽기를 감시하지는 못합니다. Python AST 차이는 사람 검토 후보이며 의미적 L7 위반 판정이 아닙니다. ORR은 사람의 근거 라벨이 필요하며 미완료율로 대체하지 않습니다.

진행 이슈: [#1 모델 연결](https://github.com/taennny/overeager-agents/issues/1) · [#2 공동 명세](https://github.com/taennny/overeager-agents/issues/2) · [#3 환경 재현](https://github.com/taennny/overeager-agents/issues/3) · [#6 설계 통합](https://github.com/taennny/overeager-agents/issues/6). 비밀 키와 실제 실행 원본은 저장소에 올리지 않습니다.
