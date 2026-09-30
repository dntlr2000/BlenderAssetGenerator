# v0.9.1 문서·저장공간 정리와 복원 안내

2026-09-30. 사용자가 승인한 문서 재배치와 안전한 정리를 수행했다. Workspace는 기존 host가 허용하는 경우만 이전하고, 문서 변경은 로컬 commit으로 고정하며 push하지 않는 선택을 적용했다. Reference-fidelity 개발·캠페인은 재개하지 않았다.

## 현재 문서와 고정 버전

- 현재 진입점은 [인계 문서](../HANDOFF_KO.md), [문서 목차](../README.md), [82개 문서 이동표](../DOCUMENT_RELOCATION_KO.md)다.
- `v0.9.1` 태그는 `b59094c8c6b795ba3bfc3e2a25982e18e479f179`에 유지한다. 이번 문서 변경은 후속 이력이며 태그를 옮기지 않는다.
- 작업 시작 시 실제 GitHub main도 위 commit이었다. 원격 `v0.9.1` 태그는 없었다. 이번 작업의 push는 0회다.
- 루트 README·AGENTS·CHANGELOG와 machine verification locator가 참조하는 역사 검증 문서 2개는 유지한다. 역사 문서·machine JSON·receipt·로그의 기록을 새 버전의 성공으로 바꾸지 않는다.

## 실제 정리와 보존

| 항목 | 결과 |
| --- | --- |
| 루트 문서 | 82개를 docs 분류 아래로 이동 |
| 종료 증거 사본 | 프로젝트 `reports/reference_fidelity_closeout/v0.9.1`의 3,574개 파일, 300,871,457 bytes를 프로젝트 밖에서 보존 |
| 기존 외부 원본과 같은 중복본 | 1,331개, **115,101,701 bytes** 삭제. 외부 원본 SHA-256 일치 확인 |
| 별도 외부 보관으로 이전한 자료 | 2,243개, **185,769,756 bytes**. 복사·SHA 검증 후 프로젝트 사본 제거 |
| 정리 적용 구간의 E: 여유 공간 | 147,249,860,608 → 147,365,216,256 bytes. 관측 증가 115,355,648 bytes |
| Workspace·canonical 이전/수정 | 0회 |
| `.b/.t` cleanup apply | 0회. 현재 보호 참조 검사가 불완전하여 중단 |

같은 E: 볼륨의 이전량은 확보 용량이 아니다. 논리 중복 삭제량과 볼륨 여유 변화도 구분한다. 여유 변화에는 동시 디스크 활동이 포함될 수 있다. 작업 자체의 helper·검사 로그 보존 비용과 전체 시작/종료 값은 외부 완료 receipt에 별도로 기록한다.

기존 [릴리스 정리 결과](CLEANUP_RESULT_KO.md)의 약 2.600GiB는 **이전 작업의 실적**이며 위 수치에 더해 이번 작업의 확보량으로 보고하지 않는다.

## 외부 보관 위치와 정확한 매핑

- 이번 조사·정리·검증 증거: [bag-v091-tidy 실행 증거](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/).
- 신규 외부 보관소: [bag-v091-archive 보존 증거](E:/CodexValidation/bag-v091-archive-20260930-run01/evidence/).
- 전체 원경로→보존경로·크기·SHA-256: [archive-plan-v2.json](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/archive-plan-v2.json).
- 실제 처리 결과: [archive-apply-receipt.json](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/archive-apply-receipt.json), [파일별 journal](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/archive-apply-journal.jsonl).
- 문서 원문과 이동 기록: [docs-relocation.json](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/docs-relocation.json), [이동 전 문서](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/docs-before-relocation/).

적용 계획 SHA-256은 `c421b248419cc37ac47600acace71911c535b3290fa41e12b11569d03e05d96b`다. 최초 plan의 요약 합계가 null로 직렬화되어 v2에서 합계만 바로잡았고, 파일 목록·행동은 동일하다. 최초 plan은 적용하지 않고 그대로 보존했다.

외부에 이미 같은 원본이 있던 파일은 그 원본을 최종 보존 위치로 사용한다. 나머지는 신규 보관소의 `repository-relative/reports/reference_fidelity_closeout/v0.9.1/`에 있다. 따라서 기존 위치를 단일 새 prefix로 치환하지 말고 **파일별 매핑**을 따른다. Machine JSON 내부의 기존 절대·상대경로와 hash는 수정하지 않았다. 이 자료는 offline 보존이며 host workspace archive나 새로운 승인·terminal이 아니다.

GitHub에는 문서와 보존 안내가 포함된다. 외부 증거·실제 workspace는 포함되지 않으므로 새 clone만으로 로컬 증거 링크가 모두 열리지는 않는다.

## 남긴 항목과 이유

- 최신 native 보호 검사: 경로 760개, hash 140,936개, 검증된 성공 root 21개를 읽었으나 접근 불가 11개가 남아 완전하지 않았다. [정확한 목록과 fingerprint](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/native-protection-index.json).
- 과거 `.b/.t` inventory의 239개 보호 트리·읽힌 약 20.56GiB는 확보 가능한 용량이 아니다. 이번에는 보호 검사에서 멈춰 전체 tree inventory와 apply를 반복하지 않았다. 과거 inaccessible 50개와 이번 11개는 조사 범위가 다르다.
- `.b/fid` 및 ACL 제한 자료는 강제 권한 변경 없이 남겼다. 링크 대상을 따라가거나 lock을 임의로 제거하지 않았다.
- Workspace 234개 중 native 적격은 Standard Plastic 1개였지만, historical fixture·QA·인간 package 승인·시각 비교가 원위치를 참조해 이전하지 않았다. [외부 참조 조사](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/native-archive-reference-review.json).
- AQ Plastic/Rust와 부모 계약·소비·원본 reference·QA·package·history는 원위치에 남겼다. Rust state 0007의 `running / quality`는 행정적 종료와 별개이며 직접 수정하지 않았다.
- 다른 대형 임시 폴더는 캠페인 helper·재현 자료·공유 cache가 섞여 있어 통째로 삭제하지 않았다. 빈 폴더 9개도 소유 근거가 없고 확보 용량이 0이라 유지했다. Python cache 59개 중 53개는 재생성 가능성이 확인됐으나 완전한 참조·사용 여부를 입증하지 못해 보존했다. [분류 목록](E:/CodexValidation/bag-v091-tidy-20260930-run01/evidence/scratch-candidates.json).
- `.git`, `.env`, `.venv`, 추적되는 `.agents`·`.codex`는 실행 환경·소스 예외다. 공용 temp 루트나 다른 작업의 파일은 정리하지 않았다.

외부로 옮긴 JSON에 들어 있던 scratch 경로 62개와 hash 8,647개의 보호 의미는 [보존 참조 목록](preserved_scratch_references.json)에 남겼다. Native protection scanner가 계속 읽을 수 있는 문서 데이터이며 실행 권한·새 계약·승인이 아니다. 외부 이전 때문에 기존 `.b/.t` 보호가 사라지는 것을 막는다.

## 복원과 후속 작업

1. 인계 문서와 현재 사용자 요청부터 확인한다. 이 정리 기록은 캠페인 재개 권한이 아니다.
2. 필요한 원경로를 archive-plan-v2의 `source`에서 찾고 `destination`의 SHA-256·크기를 검증한다.
3. 기존 경로를 필요로 하는 검증을 실행하려면 관련 의존 파일 전체를 원래 위치로 복원한다. 목적지가 이미 있으면 덮어쓰지 말고 현재 내용과 비교한다. Link·ACL·사용 여부를 확인한다.
4. 원래 machine JSON·계약·승인·receipt는 수정하지 않는다. 복원은 별도의 사용자 요청과 현재 검증을 따른다.
5. AQ workspace는 이동하지 않았으므로 위치 복원은 필요 없다. 기존 source 결속·소비·terminal 제약은 그대로 남아 있으며 과거 승인을 새 source에 재사용할 수 없다.
6. 과거 gate가 필요하면 E:\CodexTemp의 고정 소스 검증 복제본에서 실행하고 필수 증거를 E:\CodexValidation에 보존한다. 실제 gate의 repo-local 제약을 문서나 환경변수만으로 우회했다고 주장하지 않는다.

## 검증 범위

이 작업은 문서·보존 위치 정리다. 새 자산 후보·렌더·QA·promotion·delivery·Activation·인간 품질 판정은 0회다. 전체 pytest나 Blender gate를 새로 통과했다고 주장하지 않는다. 문서 링크, 보존 hash, source/자산 불변성, 지침과 repository summary, Git whitespace를 확인한 결과와 최종 commit은 이번 외부 완료 receipt에 기록한다.
