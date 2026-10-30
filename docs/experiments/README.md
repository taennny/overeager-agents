# 실험·결과 공유 — 여기서 시작

2026-10-30 정리. 실제 모델 응답이 있는 실행, 연결 요청, 스크립트 대조군, 회귀 검사를 분리한 공유 자료다. 본실험은 아직 시작하지 않았다. 코드는 검토용 후속 브랜치이며 main 병합/공동 채택과 구분한다.

## 읽는 순서

1. [10/7 고정 파일럿 42회](20261007-local-pilot.md): Qwen·EXAONE의 실패와 확대 HOLD 근거.
2. [10/7 연결·형식·복구 점검](20261007-connection-and-repair.md): 추가 탐색/중단/설정 변경 이력. 고정 파일럿에 합산하지 않는다.
3. [10/30 GPT·Claude 연결용 코딩 점검](20261030-api-connection.md): GPT 실패·Claude 통과, 토큰/비용 추정과 한계.
4. [공학 검증 이력](20261030-engineering-validation.md): 최신 201개 검사·36개 대조군과 C-02/C-03/C-04 연결.
5. [검토할 결정과 재현 방법](../REVIEW_HANDOFF.md): 다음 실행 전에 확인할 사항.

## 숫자를 읽는 기준

- 42는 10/7의 고정 모델 trial 수다. 연결·복구 점검은 조건이 달라 별도다.
- GPT·Claude의 코딩 trial은 모델별 1개이고, 그 안의 API 응답은 각각 5개와 7개다. READY 요청과 실패 시도를 분리한다.
- 201은 최신 코드 검사 수, 36은 스크립트 대조군 수다. 실제 모델 실험 수가 아니다.
- 기능 실패·프로토콜 무효·FS 이탈·미관측·step_limit를 서로 바꾸어 쓰지 않는다. 없는 사람 라벨·비용 청구액·표본을 만들어 채우지 않는다.

## 근거 파일

[전체 report/중복/미완료/대조군 검증 목록](../evidence/published/experiment-inventory.json) · [공개용 원시 LLM 보고서](../evidence/published/runs/) · [probe 요청 목록](../evidence/published/probe-inventory.json) · [변환 전후 해시](../evidence/published/export-manifest.json).

공개본은 자격증명과 운영자 홈/임시 경로를 정리했다. 원본 작업 디렉터리, 생성된 가상환경, 모델 파일/템플릿, .env, 무관한 채팅 백업은 올리지 않는다. 원시 원본은 각자 로컬 artifacts에 보존하고 공유본의 source SHA-256으로 대조한다. 원본에서 최종 보고서가 없으면 미완료로 남긴다.

원시 실행은 파일 수를 줄여 묶음별 JSON의 records에 보관했다. 전체 목록의 published_report와 published_record_key로 원하는 실행을 찾는다. GPT·Claude 최신 코딩 보고서 2개는 별도 파일로도 볼 수 있다.

GitHub에서도 Python 3.9/3.12 및 Docker 자동 검사가 통과했다. [CI·재현 근거](../REVIEW_HANDOFF.md#github-자동-검사-확인).
