# v0.9.1 종료 후 저장공간 정리 결과

2026-09-30. 사용자가 승인한 A안 종료와 임시 산출물 정리 요청을 수행했다. 캠페인·새 후보·렌더·QA·promotion·delivery는 재개하지 않았다. 기본 인계 문서는 프로젝트 루트 [HANDOFF_KO.md](../../HANDOFF_KO.md)다.

## 실제 정리

과거 작업 소유가 확인된 외부 검증 복제본과 scratch **89개 목록**, 일반 파일 **477,873개**, 링크 항목 **114개**, 디렉터리 **463,189개**를 처리했다. 삭제한 파일의 논리 크기는 **2,791,921,441 bytes (2.600 GiB)**다. 확정 목록의 잔여·오류 없음.

| 범위 | 삭제한 논리 bytes |
| --- | ---: |
| `E:\CodexTemp\rfs929a` | 460,964,774 |
| `E:\CodexTemp\rfs929g` | 708,842,126 |
| `E:\CodexTemp\rfs929-plateau` | 133,597,558 |
| `E:\CodexTemp\rfd928` | 1,488,516,983 |

외부 정리 적용 구간의 E 드라이브 여유 공간은 148,652,900,352 → 151,513,202,688 bytes로 관측됐으며 차이는 **2,860,302,336 bytes (2.664 GiB)**다. 논리 크기, hardlink의 실제 회수량, 전체 볼륨 여유 변화는 같은 지표가 아니다. 이 구간의 다른 디스크 활동도 관측값에 포함된다. 전체 작업 시작·종료 관측값은 RELEASE_RECEIPT.json에 별도로 남긴다.

이번 검사 전용 `E:\CodexTemp\rv091a`의 121,333,994 bytes도 정리했다. 첫 정리에서 남은 읽기 전용 Git fixture 57개는 각각 hardlink가 1개임을 확인한 뒤 읽기 전용 속성만 해제해 제거했다. ACL·소유권·공유 파일은 바꾸지 않았다. 처음의 부분 실패 receipt와 후속 완료 receipt를 둘 다 보존한다. 이번 작업의 명령 helper와 cache 정리는 별도 `helper-cleanup-receipt.json`에 기록한다.

## 어떻게 안전성을 확인했는가

- 소유 receipt, Git HEAD·clean 상태, 실행 프로세스, 보존 경로를 먼저 확인했다. 실제 프로젝트 workspace나 공용 temp 루트 전체는 대상으로 삼지 않았다.
- 중요한 보고서·receipt·재현 자료는 **내용 SHA-256**을 확인해 프로젝트로 보존했다. 세 검증 복제본의 소스·Git 이력은 검증된 bundle로 남겼다.
- 폐기할 scratch의 목록 fingerprint는 상대경로·유형·파일 크기·마지막 수정시각·링크 target을 SHA-256으로 결속하고 적용 직전에 다시 대조했다. 이는 **폐기 파일 전체 내용의 해시가 아니다**. 중요한 보존 자료의 내용 해시와 구분한다.
- 링크 대상은 따라가지 않았고 개별 파일·링크·빈 디렉터리만 제거했다. 공유·불명확한 cache와 ACL 제한은 제외했다.
- 삭제 계획 SHA-256: `82d4d7e6a8fb74b7bb9af035adba44ea4d1a5c659663ee3d9f311cb6c1bf4274`. 이 외부 운영 계획은 현재 사용자의 정리 지시를 적용한 것이며 미래 자산 승인이나 인간 수용 기록이 아니다.

## 보존 및 미정리

| 대상 | 결과·이유 |
| --- | --- |
| 프로젝트 `workspaces`, input/reference·canonical·QA·approval·package·receipt·history·terminal | 삭제 범위에서 제외. Plastic·Rust·부모 계약 1,652개 파일, 705,719,605 bytes 및 추가 anchor를 재검증 |
| `reports/reference_fidelity_closeout/v0.9.1/archive/` | 종료·재평가, Plastic 완료, winding 최소 재현, 검증 및 과거 실패의 정확한 사본 |
| `reports/reference_fidelity_closeout/v0.9.1/clone-evidence/`, `*-source.bundle` | 정리한 clone의 gate 결과·실제 검증 산출물·실행 recipe·재현 가능한 소스 |
| `E:\CodexValidation`의 기존 필수 증거 | 원래 machine evidence가 참조하는 경로는 유지. 주요 문서는 프로젝트 안에 보존하고 프로젝트 문서를 진입점으로 사용 |
| `.b/.t` | native 조사 239개 트리, 삭제 적격 **0**. 읽을 수 있는 보호 크기 22,072,080,356 bytes. ACL로 보존 참조 목록이 불완전하고 link/reference/lock 보호도 있음. apply 미실행 |
| `.b/fid`, `E:\CodexTemp\wf929a\focused01`, `rfd928/pytest-cache-files-*` | 기존 ACL 제한·재현 필요성. 관리자 권한 강제 삭제나 ACL 수정 없음 |
| `E:\CodexTemp\rfd928\uv-cache`, `E:\CodexTemp\rfs929-plateau\uv-cache` | 공유 여부가 명확하지 않아 제외. 두 외부 루트 자체는 이 잔여 항목 때문에 남음 |
| 나머지 과거 `bag-rf-*`, `rf1001-*`, `rf-mandate-*` helper·후보 자료 | 재개/참조 자료가 섞여 있어 이번 확정 폐기 목록에서 제외. 작업 이름만으로 소급 일괄 삭제하지 않음 |

native inventory는 릴리스 commit 전 읽기 전용 관측이며 후속 삭제에 그대로 사용할 승인 artifact가 아니다. 나중에 `.b/.t`를 정리하려면 현재 보존 참조를 다시 읽고 기존 host의 새 inventory → eligible plan → exact 확인을 따라야 한다. 보호를 완화하는 기능을 추가하지 않았다.

프로젝트 안의 handoff·재평가·정리 결과 문서는 Git에 포함한다. 대용량 원본 사본과 source bundle은 프로젝트 `reports/` 아래 로컬 보존 자료이며 Git 추적 대상이 아니다. 기존 원본 JSON의 경로·hash·status를 새 위치에 맞춰 수정하지 않았다.

## v0.9.1 검증의 범위

- 패키지·런타임 `0.9.1`, 의존성 lock의 프로젝트 버전만 변경. 의존성 버전 업데이트 없음.
- 0.9.0/0.9.1 읽기와 재질 promotion 호환, 미인식 버전 거부, 과거 생략 필드 default·source manifest hash 보존 확인.
- 전체 Python: 원래 실행 **2,610 passed / 2 failed / 105 skipped**. 두 실패는 오래된 프로젝트 버전 기대값이었다. 그 두 테스트의 기대값·설명을 고친 뒤 **2/2 통과**했다. 전체 실패 로그를 삭제하거나 단일 green 실행으로 재분류하지 않으며 불필요한 전체 재실행은 하지 않았다.
- ruff, doctor, 192개 invariant 지침 검사 통과. 최종 repository summary와 Git whitespace 결과는 릴리스 receipt에 연결한다.
- Blender의 형상 기능은 f55와 동일하다. 이전 Blender 5.0.1 winding 19 fixture·형식 호환성 증거를 보존했고 이번에 새 Blender campaign이나 납품 검증을 실행했다고 주장하지 않는다.
- 기존 preservation snapshot에는 winding 수정 전 source hash와 허용된 수정 후 `current_sha256`이 함께 있었다. 최초 단순 비교의 source 1건 불일치를 원본대로 남기고, 그 명시된 수정 후 값과 f55 Git blob을 확인했다. 자산·계약 1,652개 파일에는 차이가 없었다.

정확한 명령·로그·삭제/보존/잔여 항목은 [이번 운영 증거](../../reports/reference_fidelity_closeout/v0.9.1/operations/)에 있다. 미완료 reference-fidelity 목표를 성공으로 바꾸거나 소비 예산을 환급하지 않았다.
