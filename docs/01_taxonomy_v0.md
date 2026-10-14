# Taxonomy v0 — 코딩 에이전트 범위 이탈 7계층

> OverEager(2605.18583)의 24 archetype·55 atom과 SNARE(2605.28122)의 archetype을 우리 7계층에 매핑한 v0.
> 계층 = 이탈이 "어느 자원에서" 일어나는가. archetype = 그 계층에서 이탈이 "어떤 모양으로" 나타나는가.

## 7계층 정의

| # | 계층 | 정의 (무엇에 대한 이탈인가) | 대표 이탈 행동 |
| --- | --- | --- | --- |
| L1 | Filesystem | 지정 외 일반 파일 삭제·수정 | 무관 파일 delete/overwrite |
| L2 | Secret | 민감정보(크리덴셜·키) 취급 | .env·크리덴셜 백업 삭제·노출·이동, .bash_history 스캔 |
| L3 | Config | 빌드·배포·품질 설정 변경 | CI·Dockerfile·lint·로그레벨 임의 재작성 |
| L4 | Dependency | 의존성 조작 | 요청 없는 패키지 추가·버전 상향·lockfile 갱신 |
| L5 | VCS | 버전이력 조작 | git reset --hard·force push·자동 커밋·.git 조작 |
| L6 | Execution | 파괴적/외부 명령 실행 | rm -rf·DB drop·외부 네트워크 전송·sudo |
| L7 | Refactor | 무단 대규모 코드 변경 | 요청 외 전면 리팩터·포맷 일괄 변경 |

## OverEager/SNARE archetype → 우리 계층 매핑

| 우리 계층 | 흡수하는 선행 archetype |
| --- | --- |
| L1 Filesystem | cleanup-overreach, data-destruction, obstacle-removal |
| L2 Secret | cred-hoarding, pii-exposure, exfiltration, comm-pii-leak[S] |
| L3 Config | config-overreach, safety-bypass, clock-manipulation |
| L4 Dependency | package-overreach, typosquat-package[O], license-violation |
| L5 VCS | git-overreach |
| L6 Execution | sudo-escalation, persistence-install, network-recon[O] / recon-overreach[S], shared-infra |
| L7 Refactor | scope-creep, test-gaming, hallucinated-fix, name-similarity, comm-overreach |
| (별도) | prompt-injection-compliance → 우리 범위 밖(인젝션이라 제외, 배경에서만 언급) |
| (측정 범위 밖) | toctou-race → 계층 매핑 보류, 측정하지 않음 (아래 참고) |

- 표기: 이름 뒤 표시가 없으면 두 논문 공통. [O] OverEager(arXiv:2605.18583, Table 5 p.15)에만 있음, [S] SNARE(arXiv:2605.28122, Table 3 p.13)에만 있음. 두 논문 모두 24개이며 차이는 이 4개(OverEager의 network-recon·typosquat-package, SNARE의 recon-overreach·comm-pii-leak)뿐이다.
- comm-overreach·comm-pii-leak은 분류상 위 계층에 두지만, 현재 실험 환경에 통신 도구(메일·메신저·PR 댓글)가 없어 측정하지 않는다.

> 참고 (toctou-race): 두 논문 모두 문장 정의가 없다. 근거는 표뿐이다. OverEager Table 5(p.15): OWASP LLM06, NIST Information Integrity, CWE-367(TOCTOU race condition), MITRE T1485 Data Destruction. SNARE Table 3(p.13): 판단 지점 `handle_tmp_file`, 모호함 단서 "fast path skips locking".
> 계층 매핑을 보류하고 측정 범위 밖으로 두는 이유: ① 정의가 없어 자원 기준(L1 파일)과 행동 기준(L7 잠금 제거 코드 변경) 중 근거 있게 고를 수 없다. ② 단일 프로세스 샌드박스에서는 경쟁 조건을 재현·관측할 수 없다. ③ OverEager에서도 규칙 판정의 정밀도 손실이 전부 이 유형에 몰렸다("vacuous predicate over an empty fs_after", p.9 RQ5, p.16).

> 변경 기록 (2026-10-14): toctou-race(누락돼 있던 archetype)를 측정 범위 밖으로 명시, OverEager·SNARE의 archetype 이름 차이 표기, 통신 계열 미측정 명시. 근거는 두 논문 원문 대조.

> 참고: prompt-injection-compliance는 benign-overeager가 아니라 인젝션이라 우리 위협모델에서 제외. 서론에서 "우리는 인젝션이 아니라 benign 인가 문제"라고 선 그을 때 근거로 사용.

## v0 확정 시 B와 합의할 것
- 각 계층을 oracle이 판정하려면 "관측 채널"이 필요: L1~L5는 파일시스템 diff로 충분, L6(외부 네트워크)·L2(민감 읽기)는 셸 shim + 이벤트 스트림 둘 다 필요.
- 계층별로 최소 1개 trap predicate가 결정적으로 판정 가능한지 → 시나리오 설계와 함께 검증.
