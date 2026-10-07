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
| L2 Secret | cred-hoarding, pii-exposure, exfiltration, comm-pii-leak |
| L3 Config | config-overreach, safety-bypass, clock-manipulation |
| L4 Dependency | package-overreach, typosquat-package, license-violation |
| L5 VCS | git-overreach |
| L6 Execution | sudo-escalation, persistence-install, network-recon, shared-infra |
| L7 Refactor | scope-creep, test-gaming, hallucinated-fix, name-similarity, comm-overreach |
| (별도) | prompt-injection-compliance → 우리 범위 밖(인젝션이라 제외, 배경에서만 언급) |

> 참고: prompt-injection-compliance는 benign-overeager가 아니라 인젝션이라 우리 위협모델에서 제외. 서론에서 "우리는 인젝션이 아니라 benign 인가 문제"라고 선 그을 때 근거로 사용.

## v0 확정 시 B와 합의할 것
- 각 계층을 oracle이 판정하려면 "관측 채널"이 필요: L1~L5는 파일시스템 diff로 충분, L6(외부 네트워크)·L2(민감 읽기)는 셸 shim + 이벤트 스트림 둘 다 필요.
- 계층별로 최소 1개 trap predicate가 결정적으로 판정 가능한지 → 시나리오 설계와 함께 검증.
