# 협업 검토와 재현 안내

첫 페이지는 [실험·결과 색인](experiments/README.md)이다. 변경 코드와 C-02/C-03/C-04 설명, 실제 모델 결과와 자동 검증을 같은 브랜치에서 검토한다. 기준 구현은 기존 [PR #11](https://github.com/taennny/overeager-agents/pull/11)의 af066f3이며 이번 후속은 해당 브랜치를 대상으로 하는 별도 초안 PR로 공유한다. #11이 main에 병합되기 전에는 후속 코드가 main에 있다고 가정하지 않는다.

## 확인할 결정

| 검토 항목 | 지금의 구현/증거 | 결정 상태 |
| --- | --- | --- |
| C-03 기본 등급 | 보호 자원 고정 라벨과 보조 소스/문서 low 분리. 나머지 high/L1은 초안 | 공동 채택 전 |
| C-04 패턴·셸 한계 | temp 우선, 키/설정 패턴 공통. 해석 불가 셸은 확인·UNKNOWN 거절 | 구현/자동 검증 완료, 연구 조건 채택 전 |
| 사람 검증 범위 | 두 경계 사례는 사용자 위임에 따른 AI 판정이며 A 제안도 사전 열람 | 독립 사람 라벨/κ/사람 정답 대비 precision·recall 미완료 |
| 다음 실행 | 새 D0 6회, 예산 뒤 핵심 24회 후보. 기존 연결용 결과는 재사용하지 않음 | 아직 실행하지 않음 |

문서의 해당 줄에 질문/수정 의견을 남기고, 결정 내용과 이유를 후속 커밋으로 반영한다. 자동 검사 통과와 연구 설계 동의를 구분한다. AI가 검토자 이름·날짜·서명을 채우지 않는다. 위임 실험은 기존 연구를 유지하는 소규모 추가 후보이며 OWASP 배경/선행 차이 확인 뒤 채택한다. 현재 다중 에이전트 실험 결과는 없다.

## API 없이 재현

Python 3.9 이상과 Docker가 필요하다. 저장소 루트에서 새 출력 폴더를 지정한다.

```sh
docker build -f docker/Dockerfile -t overeager-sandbox:c04-v02 .
SCOPE_DOCKER_TESTS=1 SCOPE_V03_IMAGE=overeager-sandbox:c04-v02 python3 -m unittest discover -s tests -v
python3 -m scope_lab.validate_controls --config experiments/v05-controls.json --image overeager-sandbox:c04-v02 --out artifacts/review-controls
python3 -m scope_lab.batch plan --config experiments/v05-core.json --out artifacts/review-core-plan.json
```

이 명령은 실제 모델 API를 호출하지 않는다. macOS arm64의 로컬 이미지와 Linux CI의 이미지 ID는 다를 수 있으므로 코드·자산·플랫폼·이미지와 로그를 함께 비교한다. CI는 두 사람의 독립 환경 실행이나 팀 채택을 대신하지 않는다. API 키를 기다리지 않고 문서 검토와 위 검증을 진행할 수 있다.

모델 실행은 정확한 제공사 모델 ID·설계·예산/잔액·오류/재시도 규칙·새 자산에 맞는 검토 기록을 확인한 뒤 별도 수행한다. 이번 문서 공유와 CI에는 실제 모델 호출이 없다. F1~F6 공식 평가 세트 전체와 본실험/G3는 완료되지 않았다.

## 근거와 변경 추적

- 원본 로컬 결과는 artifacts에 보존하고, 공유용 보고서는 키/개인 경로를 정리했다. [내보내기 명세](evidence/published/export-manifest.json)의 source_sha256과 공개 파일·record 키로 대조한다.
- 원시 LLM 보고서/프롬프트는 묶음 JSON에, 스크립트 결과는 전체 실행 목록과 조건별 validation에 보관한다. 가상환경·모델 파일·.env·운영자 접속 설정은 포함하지 않는다.
- C-02 이전, C-03, C-04의 과거 숫자는 각 코드/자산 hash에 연결된다. 조건을 바꾸고 같은 표본으로 세거나 실패를 덮지 않는다.

## GitHub 자동 검사 확인

[GitHub Actions 41020260337](https://github.com/taennny/overeager-agents/actions/runs/41020260337)은 코드 커밋 34f9dd57efef5f84d75d1a8cce1f1d6beb8c358f에서 Python 3.9/3.12 검사와 Linux Docker 재현을 모두 통과했다. Docker 전체 검사는 201개(생략 0), 대조군은 36/36이다. [CI 증거](evidence/handoff-ci.json), [검사 로그](evidence/handoff-ci-tests.log), [대조군](evidence/handoff-ci-controls.json)을 저장했다.

구현 hash는 로컬 C-04 기록과 동일하다. CI linux/amd64와 로컬 arm64의 이미지 ID가 다른 사실을 유지하며, 이를 태윤의 별도 환경 재현이나 공동 연구 채택으로 표시하지 않는다. 이후 문서만 추가하는 커밋은 검증된 코드 hash를 바꾸지 않는다.
