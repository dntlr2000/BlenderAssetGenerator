# v0.9.1 문서·저장공간 정리와 보존 현황

2026-10-10~11 갱신. 과거 정리 실적과 이번 외부 보관소 폐기를 구분한다. 이번 요청은 오래된 보관소 한 곳의 삭제·기록·추가 후보 조사이며, source 기능 변경이나 자산 캠페인 재개가 아니다.

## 현재 안내

- 현재 진입점은 [인계 문서](../HANDOFF_KO.md), [문서 목차](../README.md), [82개 문서 이동표](../DOCUMENT_RELOCATION_KO.md)다.
- 사용자가 과거 검증의 후속 실행 계획을 폐기하고 `E:\CodexValidation\bag-v091-scratch-archive-20260930-run01` 보관소 삭제를 요청했다. [폐기 사유·실제 결과·보존한 최소 기록](archive_retirement_20261010/README_KO.md)을 따른다.
- 위 보관소는 더 이상 복원 원본으로 안내하지 않는다. 완료 receipt·요약·locator는 프로젝트 docs에 옮겼지만, 원본 payload와 대형 manifest 전체를 보존한 것은 아니다.
- 다른 자료는 삭제하지 않고 [추가 후보와 용량](CLEANUP_CANDIDATES_20261010_KO.md)만 조사했다. 실제 workspace·canonical·approval·package·소비·terminal은 이번 삭제 범위 밖이다.
- 이번 조사 기준은 `Dots` / `ca81eb719dd499d043ce4877c3153dcde489e25a`다. 2026-09-30 릴리스 태그를 이동하거나 commit·push하지 않는다. 이후 소스 갱신은 [2026-10-08 checkpoint 검증](../verification/BAG_CHECKPOINT_UPDATE_20261008_KO.md)에 별도로 기록되어 있다.

## 2026-09-30 첫 scratch 정리의 역사 기록

당시 작업은 `d5c6570e4d1b6cc64f5fe3c781135999e342fc5b`에서 시작한 offline 보존이었다. Native `storage-cleanup-apply`는 0회였고, 과거 AQ 성공이나 인간 수용을 새로 만들지 않았다. 수치는 [원본 바이트를 보존한 당시 완료 receipt](archive_retirement_20261010/completion-receipt.json)의 기록이며 이번 새 검사 실적이 아니다.

| 항목 | 당시 결과 |
| --- | --- |
| 외부 복사·내용 검증된 파일 참조 | 2,228,541개, 23,290,800,939 bytes |
| 중복을 합친 고유 보존 파일 | 717,713개, 5,995,722,390 bytes |
| 프로젝트에서 제거한 일반 파일 | 2,225,268개, 23,290,572,744 bytes |
| 프로젝트에서 제거한 빈 디렉터리 | 1,998,522개 |
| 첫 정리 직후 잔여 | 일반 파일 3,273개와 접근·링크 등의 예외; 48개 임시 루트 잔존 |
| 당시 삭제 구간의 E: 여유 공간 관측 증가 | 18,323,566,592 bytes |
| 당시 복원 파일/읽기 검사/역사 anchor | 1,641개 / fidelity 50개 / anchor 16개 |

**위 잔여 수치는 현재 상태가 아니다.** 같은 날의 별도 [잔여 정리 보고서](E:/CodexValidation/bag-v091-residual-cleanup-20260930-run01/evidence/REPORT_KO.md)에서 48개 루트의 제거를 완료했다. 그때 만든 `bag-v091-residual-cleanup-20260930-run01` 보관소는 이번에 삭제하지 않았다.

파일 길이 합계는 NTFS 실제 할당량과 다르다. 여유 공간 변화에는 동시 디스크 활동이 포함될 수 있다. 과거 확보량을 이번 보관소 삭제의 확보량에 다시 더하지 않는다.

## 폐기 후 역사 링크와 복원 한계

- 역사 검증 문서의 `.b/fid` 링크 13개는 [과거 locator의 보존 사본](archive_retirement_20261010/historical-evidence-locator.json)으로 원래 연결 관계만 확인한다. locator 내부의 destination은 이번 폐기 이후 접근 가능한 사본을 보장하지 않는다.
- 옛 `preservation-v3.jsonl.gz`, 상세 복원 검사 파일, 개별 scratch payload는 폐기 대상에 포함된다. 기존 안내의 prefix 치환·manifest 기반 복원 절차를 이 보관소에 적용할 수 없다. 별도 보존처가 있는지는 파일별로 다시 확인해야 한다.
- 역사 Markdown·machine JSON·receipt의 옛 경로와 hash를 변경하거나 과거 검증을 새 source의 검증으로 재분류하지 않았다. 요약 receipt만 남은 상태와 원본 실증 파일까지 남은 상태를 구분한다.
- 원래 역사 README가 참조한 [Crystalgun 사건 기록](../history/CRYSTALGUN_FRAMEWORK_INCIDENT_KO.md), [Material Closure 검증 기록](../verification/VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)은 그대로 보존한다. `verification/evidence/` 원본 문서는 수정하지 않는다.

아래 이전 tidy 보관소는 이번 폐기 보관소와 **다르다**. 아래 링크·복원 안내는 실제 파일이 남아 있는 그 tidy 자료에만 적용한다.

## 이전 문서 정리(tidy)의 실적

아래는 앞선 `bag-v091-tidy-20260930-run01`에서 수행한 문서·종료 증거 정리 기록이다. 후속 scratch 작업의 결과와 합산하지 않는다.

| 항목 | 결과 |
| --- | --- |
| 루트 문서 | 82개를 docs 분류 아래로 이동 |
| 종료 증거 사본 | 프로젝트 `reports/reference_fidelity_closeout/v0.9.1`의 3,574개 파일, 300,871,457 bytes를 프로젝트 밖에서 보존 |
| 기존 외부 원본과 같은 중복본 | 1,331개, **115,101,701 bytes** 삭제. 외부 원본 SHA-256 일치 확인 |
| 별도 외부 보관으로 이전한 자료 | 2,243개, **185,769,756 bytes**. 복사·SHA 검증 후 프로젝트 사본 제거 |
| 정리 적용 구간의 E: 여유 공간 | 147,249,860,608 → 147,365,216,256 bytes. 관측 증가 115,355,648 bytes |
| Workspace·canonical 이전/수정 | 0회 |
| `.b/.t` cleanup apply | 당시 0회. 보호 참조 검사가 불완전하여 중단 |

같은 E: 볼륨의 이전량은 확보 용량이 아니다. 논리 중복 삭제량과 볼륨 여유 변화도 구분한다. 여유 변화에는 동시 디스크 활동이 포함될 수 있다. 작업 자체의 helper·검사 로그 보존 비용과 전체 시작/종료 값은 외부 완료 receipt에 별도로 기록한다.

기존 [릴리스 정리 결과](CLEANUP_RESULT_KO.md)의 약 2.600GiB는 **이전 작업의 실적**이며 위 수치에 더해 이번 작업의 확보량으로 보고하지 않는다.

## 이전 tidy 증거의 보관 위치와 매핑

- 이번 조사·정리·검증 증거: [bag-v091-tidy 실행 증거](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/).
- 신규 외부 보관소: [bag-v091-archive 보존 증거](E:/CodexValidation/bag-v091-archive-20260930-run01/evidence/).
- 전체 원경로→보존경로·크기·SHA-256: [archive-plan-v2.json](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/archive-plan-v2.json).
- 실제 처리 결과: [archive-apply-receipt.json](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/archive-apply-receipt.json), [파일별 journal](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/archive-apply-journal.jsonl).
- 문서 원문과 이동 기록: [docs-relocation.json](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/docs-relocation.json), [이동 전 문서](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/docs-before-relocation/).

적용 계획 SHA-256은 `c421b248419cc37ac47600acace71911c535b3290fa41e12b11569d03e05d96b`다. 최초 plan의 요약 합계가 null로 직렬화되어 v2에서 합계만 바로잡았고, 파일 목록·행동은 동일하다. 최초 plan은 적용하지 않고 그대로 보존했다.

외부에 이미 같은 원본이 있던 파일은 그 원본을 최종 보존 위치로 사용한다. 나머지는 신규 보관소의 `repository-relative/reports/reference_fidelity_closeout/v0.9.1/`에 있다. 따라서 기존 위치를 단일 새 prefix로 치환하지 말고 **파일별 매핑**을 따른다. Machine JSON 내부의 기존 절대·상대경로와 hash는 수정하지 않았다. 이 자료는 offline 보존이며 host workspace archive나 새로운 승인·terminal이 아니다.

Git 추적 대상은 문서와 보존 안내다. 이번 후속 문서는 아직 push하지 않았다. 외부 증거·실제 workspace는 Git에 포함되지 않으므로 새 clone만으로 로컬 증거 링크가 모두 열리지는 않는다.

## 이전 tidy에서 남긴 항목과 당시 이유

다음은 당시 보류 사유를 보존한 기록이다. 현재 상태는 위의 후속 잔여 정리·보관소 폐기 기록과 구분하며, 이 목록을 오늘의 잔여 목록으로 해석하지 않는다.

- 최신 native 보호 검사: 경로 760개, hash 140,936개, 검증된 성공 root 21개를 읽었으나 접근 불가 11개가 남아 완전하지 않았다. [정확한 목록과 fingerprint](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/native-protection-index.json).
- 과거 `.b/.t` inventory의 239개 보호 트리·읽힌 약 20.56GiB는 확보 가능한 용량이 아니다. 이번에는 보호 검사에서 멈춰 전체 tree inventory와 apply를 반복하지 않았다. 과거 inaccessible 50개와 이번 11개는 조사 범위가 다르다.
- `.b/fid` 및 ACL 제한 자료는 강제 권한 변경 없이 남겼다. 링크 대상을 따라가거나 lock을 임의로 제거하지 않았다.
- Workspace 234개 중 native 적격은 Standard Plastic 1개였지만, historical fixture·QA·인간 package 승인·시각 비교가 원위치를 참조해 이전하지 않았다. [외부 참조 조사](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/native-archive-reference-review.json).
- AQ Plastic/Rust와 부모 계약·소비·원본 reference·QA·package·history는 원위치에 남겼다. Rust state 0007의 `running / quality`는 행정적 종료와 별개이며 직접 수정하지 않았다.
- 다른 대형 임시 폴더는 캠페인 helper·재현 자료·공유 cache가 섞여 있어 통째로 삭제하지 않았다. 빈 폴더 9개도 소유 근거가 없고 확보 용량이 0이라 유지했다. Python cache 59개 중 53개는 재생성 가능성이 확인됐으나 완전한 참조·사용 여부를 입증하지 못해 보존했다. [분류 목록](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/scratch-candidates.json).
- `.git`, `.env`, `.venv`, 추적되는 `.agents`·`.codex`는 실행 환경·소스 예외다. 공용 temp 루트나 다른 작업의 파일은 정리하지 않았다.

외부로 옮긴 JSON에 들어 있던 scratch 경로 62개와 hash 8,647개의 보호 의미는 [보존 참조 목록](preserved_scratch_references.json)에 남겼다. Native protection scanner가 계속 읽을 수 있는 문서 데이터이며 실행 권한·새 계약·승인이 아니다. 외부 이전 때문에 기존 `.b/.t` 보호가 사라지는 것을 막는 보수적 이력이다. 이번 보관소 폐기를 이유로 이 machine 목록을 자동 수정하지 않았으며, 이 목록 자체가 개별 원본의 현재 존재를 보장하지는 않는다.

## 이전 tidy 자료의 복원과 공통 후속 경계

1. 인계 문서와 현재 사용자 요청부터 확인한다. 이 정리 기록은 캠페인 재개 권한이 아니다.
2. 필요한 원경로를 archive-plan-v2의 `source`에서 찾고 `destination`의 SHA-256·크기를 검증한다.
3. 기존 경로를 필요로 하는 검증을 실행하려면 관련 의존 파일 전체를 원래 위치로 복원한다. 목적지가 이미 있으면 덮어쓰지 말고 현재 내용과 비교한다. Link·ACL·사용 여부를 확인한다.
4. 원래 machine JSON·계약·승인·receipt는 수정하지 않는다. 복원은 별도의 사용자 요청과 현재 검증을 따른다.
5. AQ workspace는 이동하지 않았으므로 위치 복원은 필요 없다. 기존 source 결속·소비·terminal 제약은 그대로 남아 있으며 과거 승인을 새 source에 재사용할 수 없다.
6. 과거 gate가 필요하면 E:\CodexTemp의 고정 소스 검증 복제본에서 실행하고 필수 증거를 E:\CodexValidation에 보존한다. 실제 gate의 repo-local 제약을 문서나 환경변수만으로 우회했다고 주장하지 않는다.

## 검증 범위

두 정리 작업 모두 문서·보존 위치 정리다. 새 자산 후보·렌더·QA·promotion·delivery·Activation·인간 품질 판정은 0회다. 전체 pytest나 Blender gate를 새로 통과했다고 주장하지 않는다. 문서 링크, 보존 hash, source/자산 불변성, 지침과 repository summary, Git whitespace를 확인한 결과와 각 작업의 최종 commit은 해당 외부 완료 receipt에 기록한다.


## 2026-10-20 workspace 후속 정리

위의 이전 작업 당시 원위치 보존·복원 설명과 현재 상태를 구분한다. 사용자가 승인한 ③·④ 정리는 [이번 정리 결과](WORKSPACE_CLEANUP_20261020_KO.md)에 기록했다. ①·②와 공유 authority는 보존했고, ③·④의 bulk payload는 폐기했다. 최소 ZIP은 native 전체 복원본이 아니다. [② 용량 상세 분석](WORKSPACE_CATEGORY2_STORAGE_20261020_KO.md)은 후속 삭제를 수행한 기록이 아니다.


## 2026-10-21 완료 자산 폐기

사용자의 새 보존 기준에 따라 완료 작업 46개(48,162파일, 7.198 GB)를 실제 폐기했다. 실패·보류·알려진 시각 결함·완료 불명확 자산 19개와 공유 소비 기록은 유지했다. 완료 모델·package 전체는 복원할 수 없으며 원본 reference와 최소 이력만 외부에 보존했다. 앞선 표의 보존·복원 설명은 각 기록 날짜의 상태다. [실제 삭제 목록·현재 보존 목록·무결성 검증](WORKSPACE_COMPLETED_RETIREMENT_20261021_KO.md)을 따른다.
