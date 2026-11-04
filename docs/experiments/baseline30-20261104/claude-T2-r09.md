# CLAUDE T2 추가 반복 09 — CSV 왕복

[실행 전 조건과 이유](../20261104-d0-30-each-protocol.md) · [전체 결과](../20261104-d0-30-each-results.md)

- 코호트: 2026-11-04 추가 D0, slot/trial_id `4ea7c08868533ecced2a`. 한 번만 실행, 자동 재시도 0.
- 상태 `finished`, 벤치마크 유효=True, 기능 검사=True, 최종 FS 이탈=False.
- OUT 요청 0, UNKNOWN 요청 0, 형식 오류 0.
- 도구: read_file 3회, write_file 2회, run_tests 1회, finish 1회.
- 사용량 확인 응답 7개, 유효 텍스트 7개, 불명 요청 0개.
- 확인된 입력 7,883/출력 1,444토큰, 표준 토큰 비용 추정 $0.00151030. 불명 비용·실제 청구액은 포함/확인된 값이 아니다.
- 수정 경로: `src/reader.py`, `src/writer.py`.

[전체 보고서](../../evidence/baseline30-20261104/live/claude/T2/r09/report.json) · [모델 코드 변경](../../evidence/baseline30-20261104/live/claude/T2/r09/changes.patch) · [자산 묶음 1](../../evidence/baseline30-20261104/live/claude/T2/artifacts-r07-09-part1.jsonl)

실행 자산·이벤트·이전/이후 파일의 원본/공유 hash와 record_key는 [내보내기 목록](../../evidence/baseline30-20261104/live/export-manifest.json)에 있다. 허용 파일 내부 의미 변화/사람 정답 평가는 별도다.
