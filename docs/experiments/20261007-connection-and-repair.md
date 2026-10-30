# 10/7 연결·형식·EXAONE 복구 탐색 기록

42회 고정 파일럿 외에 남아 있는 점검 기록을 별도 목록으로 정리했다. 아래 개수는 report.json 존재 개수이며, 전부 완료된 모델 추론이라는 뜻은 아니다. 초기 서버 측 실행 오류는 모델 응답 자체를 확인하지 못했다. 프로토콜/템플릿/프롬프트/예산/모델 크기 등이 바뀌는 복구 과정이므로 같은 실험의 독립 반복으로 합산하지 않는다.

| 보관 묶음 | LLM 모드 보고서 | 기능 성공 기록 | model_error | 실행 환경 error |
| --- | ---: | ---: | ---: | ---: |
| ollama-check-20261007 | 4 | 1 | 0 | 2 |
| ollama-json-check-20261007 | 2 | 2 | 0 | 0 |
| exaone-recheck-20261007 | 3 | 0 | 2 | 0 |
| exaone-repair-20261007 | 28 | 10 | 5 | 0 |

초기 calculator 점검은 Qwen 성공·EXAONE step_limit 실패였고, JSON 형식 점검 뒤 calculator는 두 모델 모두 성공했다. 이 과제는 대표 T1–T3와 다르다. JSON 형식 전용 요청 2개는 기대 read_file 행동을 반환했다. EXAONE 대표 과제 재점검 3개에서는 성공 0, 응답 미완료 model_error 2개가 기록됐다.

## EXAONE 복구 묶음별 기록

| 로컬 묶음 이름 | 보고서 | 기능 성공 | model_error | step_limit |
| --- | ---: | ---: | ---: | ---: |
| exaone32-r1 | 1 | 1 | 0 | 0 |
| hybrid-r1 | 3 | 1 | 0 | 2 |
| hybrid-r2 | 1 | 0 | 0 | 1 |
| hybrid-r3 | 3 | 2 | 0 | 1 |
| hybrid-r4 | 3 | 1 | 0 | 1 |
| hybrid-r5 | 3 | 1 | 0 | 1 |
| hybrid-r6 | 3 | 2 | 0 | 1 |
| r1 | 2 | 0 | 1 | 1 |
| r3 | 3 | 0 | 3 | 0 |
| r4 | 2 | 1 | 1 | 1 |
| r5 | 1 | 0 | 0 | 0 |
| r6 | 1 | 1 | 0 | 0 |
| r7 | 2 | 0 | 0 | 2 |

이름은 보관 폴더의 식별자다. 이름만으로 모든 설정을 추정하지 않는다. 보고서의 model/시스템 프롬프트/예산/구현 hash를 각각 확인한다. `exaone32-r1`은 EXAONE 32b의 보고서가 남은 실행이며, 결과가 없는 시작 폴더는 완료/실패를 임의 확정하지 않는다. step_limit에서도 기능 평가가 통과한 경우가 있으므로 종료 상태와 기능 성공을 분리한다. 일부 성공 사례를 골라 기존 실패 파일럿을 덮거나 모델 우열을 주장하지 않는다.

템플릿·text/schema/json 전용 probe는 과제 trial과 별도다. [probe 목록](../evidence/published/probe-inventory.json), [원시 결과/미완료/중복 목록](../evidence/published/experiment-inventory.json), [공개용 LLM 보고서](../evidence/published/runs/exaone-repair-20261007.json)를 본다. 초기 연결 오류 보고서와 형식 점검도 해당 runs 하위 폴더에 보존했다.

## 중단·미완료 기록

최종 LLM 결과가 없는 시작/중단 기록 10개도 보존했다. pending 또는 구현 수정 중단 상태이며 완료/기능 실패/정상 종료로 임의 치환하지 않는다.

| 보관 경로 | 원래 상태 |
| --- | --- |
| exaone-repair-20261007/exaone32-r1/01-log-mask/report.json | pending |
| exaone-repair-20261007/exaone32-r2/01-log-mask/report.json | pending |
| exaone-repair-20261007/r1/02-csv-roundtrip/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r2/03-dev-config/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r4/02-csv-roundtrip/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r5/01-log-mask/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r6/01-log-mask/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r7/02-csv-roundtrip/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r8/03-dev-config/report.json | interrupted_for_implementation_revision |
| exaone-repair-20261007/r9/03-dev-config/report.json | interrupted_for_implementation_revision |
