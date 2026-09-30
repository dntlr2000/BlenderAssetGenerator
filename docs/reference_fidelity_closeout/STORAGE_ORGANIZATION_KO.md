# v0.9.1 문서·저장공간 정리와 복원 안내

2026-09-30. 문서 재배치·종료 증거 정리 뒤 사용자가 승인한 후속 scratch 외부 보존과 프로젝트 사본 정리를 수행했다. 두 작업의 수치와 증거를 구분한다. 실제 workspace·canonical은 이전하거나 수정하지 않았고 reference-fidelity 개발·캠페인과 push도 실행하지 않았다.

## 현재 문서와 고정 버전

- 현재 진입점은 [인계 문서](../HANDOFF_KO.md), [문서 목차](../README.md), [82개 문서 이동표](../DOCUMENT_RELOCATION_KO.md)다.
- `v0.9.1` 태그는 `b59094c8c6b795ba3bfc3e2a25982e18e479f179`에 유지한다. 이번 문서 변경은 후속 이력이며 태그를 옮기지 않는다.
- 이전 tidy 작업의 서버 조회에서는 GitHub main도 위 commit이었고 원격 `v0.9.1` 태그는 없었다. 이번 scratch 작업의 최신 읽기 전용 조회는 Schannel `SEC_E_NO_CREDENTIALS`로 실패했다. 현재 서버 상태는 미확인이며 cached `origin/main`은 b590이다. 이번 작업의 push는 0회다.
- 루트 README·AGENTS·CHANGELOG와 machine verification locator가 참조하는 역사 검증 문서 2개는 유지한다. 역사 문서·machine JSON·receipt·로그의 기록을 새 버전의 성공으로 바꾸지 않는다.

## 후속 scratch 외부 보존과 실제 정리

이 작업은 `d5c6570e4d1b6cc64f5fe3c781135999e342fc5b`에서 시작한 별도의 offline 보존 작업이다. 보호 참조 검사가 불완전했던 native `storage-cleanup-apply`는 여전히 **0회**다. 이를 native 적격 판정이나 보호 완화로 재분류하지 않는다. 프로젝트 source 기능·계약·소비·과거 evidence는 바꾸지 않았다.

| 항목 | 이번 scratch 작업 결과 |
| --- | --- |
| 외부 복사·내용 검증된 파일 참조 | 2,228,541개, 23,290,800,939 bytes |
| 중복을 합친 고유 보존 파일 | 717,713개, 5,995,722,390 bytes |
| 프로젝트에서 실제 제거한 일반 파일 | **2,225,268개, 23,290,572,744 bytes** |
| 실제 제거한 빈 디렉터리 | 1,998,522개 |
| 적용 중 제거하지 못해 남긴 일반 파일 | 3,273개. 모두 관측 속성이 Archive+ReadOnly였으며 속성을 바꾸거나 강제로 제거하지 않음 |
| 삭제 적용 구간의 E: 여유 공간 | 136,592,412,672 → 154,915,979,264 bytes; 관측 증가 **18,323,566,592 bytes** |
| 조사한 66개 임시 루트의 사후 상태 | 18개 없음, 48개 잔존 |
| 실제 workspace/canonical 변경·새 자산 실행 | 0회 |

논리 파일 크기, 고유 보관 파일 크기와 NTFS에서 실제 회수한 공간은 서로 다르다. 위 여유 공간 증가는 **삭제 적용 구간의 관측값**이며 동시 디스크 활동도 포함할 수 있다. 복사·복원 검증·manifest 압축·임시본 정리를 포함한 작업 전체의 시작/종료 여유 공간은 외부 최종 receipt를 따른다. 아래 이전 tidy의 115,101,701 bytes와 릴리스 정리의 약 2.600GiB를 이번 확보량에 더하지 않는다.

사후 [잔여 조사](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/residual-summary.json)에서 읽은 일반 잔여 파일 3,273개의 합계는 228,195 bytes다. 이들은 읽기전용 fixture 파일이며, 별도로 링크 474개와 조사에서 제외한 하위 트리 1,017개가 남아 있다. 공유 cache의 소유권 미확인·ACL/접근 제한·보호된 link target·lock 관련 사유로 **47개 루트에 크기를 측정하지 못한 하위 트리가 포함**된다. 따라서 228,195 bytes는 전체 잔여 크기가 아니다. 읽기전용 속성·소유권·ACL을 바꾸거나 링크 대상을 따라가지 않았다. `.b/.t/.tmp` 등 일부 루트가 남았다는 이유로 안의 모든 기존 파일이 남아 있다고 해석하지 않는다.

외부 보관소 실물 조사에서 확정 mapped payload **717,713개, 5,995,722,390 bytes**가 모두 일치했고 누락·크기 불일치는 0개였다. 이 수치는 일반 파일 길이이며 디스크 할당 cluster 측정값은 아니다. 초기 부분 시도 사본을 이 확정 보존량에 더하지 않는다. 이번 작업에서 중단한 부분 복사 목록 v2의 마지막 레코드가 잘려 있어, 관련 중간 사본 582개·8,398,903 bytes의 추가 삭제는 보류했다. [보류 계획과 원인](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/orphan-dedup-plan.json)을 보존하며 최종 v3 목록이나 과거 원본 증거를 고치지 않았다. Manifest·로그 등 부속 자료의 후속 압축 비용은 최종 receipt에서 별도로 확인한다.

## 이번 scratch 자료를 찾고 복원하는 방법

- 이번 작업의 [전체 보존 증거](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/), [복사 요약](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/copy-summary.json), [삭제 적용 요약](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/apply-summary.json), [잔여 조사](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/residual-summary.json).
- 원래 repository-relative `path` → 실제 `destination`·SHA-256·bytes는 [최종 보존 manifest](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/preservation-v3.jsonl.gz)를 따른다. 최종 JSONL 내용 SHA-256은 `561905acf4924e68684de3e73c3b2076818df75da1c6e9f4ccc8807f6f8f4c48`이다. gzip 파일 자체의 hash와 구분한다. 앞선 `preservation.jsonl`과 `preservation-v2.jsonl`은 중단된 부분 시도이며 최종 목록이 아니다.
- 원래 문서가 직접 참조하던 `.b/fid` 파일 13개는 [역사 링크 locator](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/historical-evidence-locator.json)에서 바로 찾는다. 루트 역사 검증 문서는 byte 단위로 유지했다.
- 저장소 정리 전에 이미 옮겨졌던 역사 README의 두 문서 대상은 현재 [Crystalgun 사건 기록](../history/CRYSTALGUN_FRAMEWORK_INCIDENT_KO.md), [Material Closure 검증 기록](../verification/VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)이다. `verification/evidence/` 원본 README의 옛 링크는 수정하지 않았다. Git baseline·[문서 이동표](../DOCUMENT_RELOCATION_KO.md)·파일 hash로 관계를 검증했다.

보관소는 같은 SHA와 크기의 내용을 한 파일로 합쳐 저장한 **부분 경로 트리**다. 원래 경로 전체가 보관소에 그대로 존재한다고 가정하거나 단일 prefix를 치환하지 않는다. `status=verified`인 파일의 exact `destination`을 읽고 SHA와 크기를 확인한 뒤, 실행이 필요할 때만 새 `E:\CodexTemp` 검증 사본에 원래 상대경로를 재구성한다. 빈 디렉터리는 manifest의 directory metadata로 재구성한다. 기존 파일을 덮어쓰거나 link/ACL 제한을 우회하지 않는다.

Machine JSON·receipt 내부의 원래 경로와 hash는 수정하지 않는다. 보관본을 직접 host의 활성 workspace로 사용하지 않는다. 원래 절대경로나 source 결속이 필요한 검사는 복원 사본을 기존 host가 허용하는지 별도로 확인하며, 실패를 피하려고 과거 payload를 고치지 않는다. 재개 권한과 source·budget 제한은 [인계 문서](../HANDOFF_KO.md) 그대로다.

이번에는 10개 개발 job의 파일 **1,641개**를 새 외부 사본에 복원해 모두 일치를 확인했고, 필요한 디렉터리 **771개**도 재구성했다. [복원 파일 검사](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/restored-file-integrity.json), [복원 디렉터리 목록](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/restored-directory-proof.json), [복원본 fidelity 읽기 검사 50/50](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/fidelity-restored-validation.json), [삭제 후 fidelity 검사 50/50](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/fidelity-post-removal-validation.json), [역사 anchor 검사 16/16](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/historical-after.json)를 보존한다. 복원은 파일 bytes와 상대경로를 재현하며 원래 ACL·timestamp를 적용했다는 뜻은 아니다.

[삭제 전 source·asset·링크 검사](E:/CodexValidation/bag-v091-scratch-archive-20260930-run01/evidence/pre-delete-validation-v3.json)에서는 tracked 1,539개와 asset 1,652개가 모두 불변이었다. 이 검사는 새 Blender 렌더·QA·Production 납품·인간 수용을 만들지 않는다. 앞선 읽기 검사의 중단과 Windows 긴 경로 처리 실패는 그대로 보존했고, helper의 I/O 표기만 고쳐 재검사했다. 공통 source는 수정하지 않았다.

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

다음은 당시 보류 사유를 보존한 기록이다. 후속 scratch 정리 후 현재 잔여는 위 최신 조사와 파일별 manifest를 따른다.

- 최신 native 보호 검사: 경로 760개, hash 140,936개, 검증된 성공 root 21개를 읽었으나 접근 불가 11개가 남아 완전하지 않았다. [정확한 목록과 fingerprint](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/native-protection-index.json).
- 과거 `.b/.t` inventory의 239개 보호 트리·읽힌 약 20.56GiB는 확보 가능한 용량이 아니다. 이번에는 보호 검사에서 멈춰 전체 tree inventory와 apply를 반복하지 않았다. 과거 inaccessible 50개와 이번 11개는 조사 범위가 다르다.
- `.b/fid` 및 ACL 제한 자료는 강제 권한 변경 없이 남겼다. 링크 대상을 따라가거나 lock을 임의로 제거하지 않았다.
- Workspace 234개 중 native 적격은 Standard Plastic 1개였지만, historical fixture·QA·인간 package 승인·시각 비교가 원위치를 참조해 이전하지 않았다. [외부 참조 조사](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/native-archive-reference-review.json).
- AQ Plastic/Rust와 부모 계약·소비·원본 reference·QA·package·history는 원위치에 남겼다. Rust state 0007의 `running / quality`는 행정적 종료와 별개이며 직접 수정하지 않았다.
- 다른 대형 임시 폴더는 캠페인 helper·재현 자료·공유 cache가 섞여 있어 통째로 삭제하지 않았다. 빈 폴더 9개도 소유 근거가 없고 확보 용량이 0이라 유지했다. Python cache 59개 중 53개는 재생성 가능성이 확인됐으나 완전한 참조·사용 여부를 입증하지 못해 보존했다. [분류 목록](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/scratch-candidates.json).
- `.git`, `.env`, `.venv`, 추적되는 `.agents`·`.codex`는 실행 환경·소스 예외다. 공용 temp 루트나 다른 작업의 파일은 정리하지 않았다.

외부로 옮긴 JSON에 들어 있던 scratch 경로 62개와 hash 8,647개의 보호 의미는 [보존 참조 목록](preserved_scratch_references.json)에 남겼다. Native protection scanner가 계속 읽을 수 있는 문서 데이터이며 실행 권한·새 계약·승인이 아니다. 외부 이전 때문에 기존 `.b/.t` 보호가 사라지는 것을 막는다.

## 이전 tidy 자료의 복원과 공통 후속 경계

1. 인계 문서와 현재 사용자 요청부터 확인한다. 이 정리 기록은 캠페인 재개 권한이 아니다.
2. 필요한 원경로를 archive-plan-v2의 `source`에서 찾고 `destination`의 SHA-256·크기를 검증한다.
3. 기존 경로를 필요로 하는 검증을 실행하려면 관련 의존 파일 전체를 원래 위치로 복원한다. 목적지가 이미 있으면 덮어쓰지 말고 현재 내용과 비교한다. Link·ACL·사용 여부를 확인한다.
4. 원래 machine JSON·계약·승인·receipt는 수정하지 않는다. 복원은 별도의 사용자 요청과 현재 검증을 따른다.
5. AQ workspace는 이동하지 않았으므로 위치 복원은 필요 없다. 기존 source 결속·소비·terminal 제약은 그대로 남아 있으며 과거 승인을 새 source에 재사용할 수 없다.
6. 과거 gate가 필요하면 E:\CodexTemp의 고정 소스 검증 복제본에서 실행하고 필수 증거를 E:\CodexValidation에 보존한다. 실제 gate의 repo-local 제약을 문서나 환경변수만으로 우회했다고 주장하지 않는다.

## 검증 범위

두 정리 작업 모두 문서·보존 위치 정리다. 새 자산 후보·렌더·QA·promotion·delivery·Activation·인간 품질 판정은 0회다. 전체 pytest나 Blender gate를 새로 통과했다고 주장하지 않는다. 문서 링크, 보존 hash, source/자산 불변성, 지침과 repository summary, Git whitespace를 확인한 결과와 각 작업의 최종 commit은 해당 외부 완료 receipt에 기록한다.
