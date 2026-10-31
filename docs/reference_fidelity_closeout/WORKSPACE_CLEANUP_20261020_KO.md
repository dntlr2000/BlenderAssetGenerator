# Workspace 과거 자료 정리 결과 — 2026-10-20

사용자가 네 가지 분류 중 **③ 과거 계약·재현·승인·검증 및 판단 보류 자료**, **④ 폐기 후보 실험·임시 자료**의 정리를 지시했다. ① 최신 닷츠산 업데이트 증거와 ② 자산 원본·최종 결과 보존 검토군은 삭제하지 않았다. 이 기록은 새 캠페인, 릴리스, 품질 판정 또는 인간 수용이 아니다.

Git 기준은 `Dots`의 `ca81eb719dd499d043ce4877c3153dcde489e25a`다. 정리 직후 검증에서 HEAD·branch와 기존 staged 17개 파일·unstaged 상태가 모두 작업 전과 같았다. 그 후 이 보고서와 안내 링크만 추가했다. 소스 수정, commit, push, state/terminal 수정, ACL 변경은 수행하지 않았다.

## 실제 정리량

| 항목 | 결과 |
| --- | ---: |
| ③·④ 원래 조사 범위 | 189개 root, 8,877,583,728 bytes |
| 실제 삭제 | **47,890개 파일, 8,750,323,734 bytes** |
| 삭제량 단위 환산 | **8.750 GB / 8.149 GiB** |
| 완전히 제거된 root | 180개 |
| 비어 있어 제거한 디렉터리 | 22,395개 |
| 삭제 오류·권한 강제 변경 | 0건 |
| 외부 최소 보존 ZIP | 87,461,824 bytes (87.46 MB) |
| ③·④ 원위치 잔여 | 496개 파일, 127,259,994 bytes |

위 삭제량은 실제 삭제된 파일의 논리적 크기 합계다. 외부 보존 ZIP과 이번 조사·receipt 보관 비용을 빼야 순수 파일 저장량 감소가 된다. 작업의 최종 보존 비용·임시파일 정리는 아래 completion receipt에 기록한다.

삭제 적용 구간의 E: 여유 공간은 77,629,804,544 → 93,182,484,480 bytes였다. 관측 증가는 15.553 GB로 파일 삭제량과 다르다. 다른 작업의 동시 디스크 활동을 포함할 수 있어 이 증가분 전체를 이번 확보량으로 계산하지 않는다.

## 원위치에 남긴 예외

| 경로 | 파일 수 | MB | 이유 |
| --- | ---: | ---: | --- |
| [workspace_archive/.cbm/plans](E:/Playground/BlenderAssetGenerator/workspace_archive/.cbm/plans) | 16 | 0.01 | ②가 사용하는 공유 계약·소비 또는 16개 archive의 원래 복원 plan/receipt |
| [workspace_archive/.cbm/receipts](E:/Playground/BlenderAssetGenerator/workspace_archive/.cbm/receipts) | 16 | 0.02 | ②가 사용하는 공유 계약·소비 또는 16개 archive의 원래 복원 plan/receipt |
| [workspaces/.fidelity_budget](E:/Playground/BlenderAssetGenerator/workspaces/.fidelity_budget) | 3 | 0.00 | ②가 사용하는 공유 계약·소비 또는 16개 archive의 원래 복원 plan/receipt |
| [workspaces/.fidelity_delegations](E:/Playground/BlenderAssetGenerator/workspaces/.fidelity_delegations) | 134 | 80.37 | ②가 사용하는 공유 계약·소비 또는 16개 archive의 원래 복원 plan/receipt |
| [workspaces/_staging](E:/Playground/BlenderAssetGenerator/workspaces/_staging) | 10 | 3.17 | ②의 lineage·재질 승인 등에서 직접 참조하는 파일과 명시된 파일 의존성 |
| [workspaces/aq_ref_fidelity_b407d18_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_ref_fidelity_b407d18_01_plastic_shard) | 283 | 18.89 | ②의 lineage·재질 승인 등에서 직접 참조하는 파일과 명시된 파일 의존성 |
| [workspaces/aq_rf_aa22b13_01p2](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_aa22b13_01p2) | 27 | 23.61 | ②의 lineage·재질 승인 등에서 직접 참조하는 파일과 명시된 파일 의존성 |
| [workspaces/aq_rf_df8b1514_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_df8b1514_01_plastic) | 6 | 1.18 | ②의 lineage·재질 승인 등에서 직접 참조하는 파일과 명시된 파일 의존성 |
| [workspaces/item_crystalgun_full_0](E:/Playground/BlenderAssetGenerator/workspaces/item_crystalgun_full_0) | 1 | 0.00 | 정션이 있는 작은 재현 fixture. 링크 대상을 따라가거나 삭제하지 않음 |

공유 4개 root는 그대로 보존했다. 추가로 ②의 직접 참조와 JSON 파일 의존성을 따라 326개 파일, 46,858,141 bytes를 보존했다. 정션 fixture의 일반 파일은 33 bytes다. 남은 부분 경로를 온전한 실행 workspace로 취급하지 않는다.

정확한 원위치 잔여 목록: [remaining-category3-and4.json](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/remaining-category3-and4.json). ②→③·④ 직접 참조 근거: [category2-exact-reference-protections.json](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/category2-exact-reference-protections.json).

## 무엇을 외부에 보존했는가

- [최소 원본 보존 ZIP](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/preserved-minimum.zip): 9,794개 원경로의 선택 자료, 중복을 제거한 6,480개 내용. 모든 ZIP member SHA-256을 검증했다.
- 원본 input의 내용·원경로, job 식별 정보, 핵심 루트 저작 소스와 마지막 Blender 파일, 선택된 상태·예산·승인·terminal·finding 기록을 보존했다.
- 미해결 Rust/Wood/Crystalgun의 선택 소스·대표 QA, 원래 Laser 회귀 fixture 6개, 예전 first_reference_test의 최종 FBX package와 clean-import 기록도 보존했다.
- 각 파일의 보존 이유와 원경로→`blobs/<sha256>` 매핑은 ZIP의 `original-path-map.json`과 외부 selection에 있다. 같은 바이트는 한 번만 저장했다.
- 보존 ZIP SHA-256: `410d2787192b0d5b92bbd40bf6d8f72c67b356801478de354c0cb2fe13ecc7b0`.
- [선별 목록·사유](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/preservation-selection.json.gz), [보존 검증 receipt](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/preservation-verification.json).

이 ZIP은 **전체 workspace·native AQ 세션을 복원하는 백업이 아니다**. 대량 shadow job·반복 빌드·QA pass·스냅샷은 폐기했다. 따라서 폐기된 경로에 의존하는 과거 full-tree gate, archive/QA 재검증, 중단 세션의 그대로 재개는 지원하지 않는다. 기존 JSON 안의 경로와 hash를 바꾸지 않았으므로 그 경로가 현재 존재한다는 뜻으로 읽으면 안 된다.

기존 소비·승인·terminal의 의미를 환급하거나 새 실행 권한으로 바꾸지 않았다. 원래 running 상태도 완료·취소로 고쳐 쓰지 않았다. 이후 과거 AQ 이력을 이용하려면 외부 보존 원본과 누락 의존성을 별도로 확인해야 하며, 이 정리를 근거로 lifetime counter를 초기화할 수 없다. 현재 사용 목적은 과거 캠페인 종료와 자료 정리이며 캠페인 재개가 아니다.

## 삭제 후 검증

- ② **65개 root, 57,447개 파일, 8,275,054,345 bytes**의 경로·크기·수정 시각·SHA-256이 전부 이전과 같다.
- ① `bagcp-261008-5a25f0af/evidence`의 **129개 파일** 해시가 같다.
- ③·④에서 남긴 파일까지 합쳐 **57,943개 파일**을 다시 해시 검증했고 오류가 없다.
- 16개 native archive의 파일과 공유 receipt/plan을 유지했다. 이전에 통과한 native archive 검증의 원본은 변경하지 않았으며 새 자산 검증을 실행한 것은 아니다.
- 파일별 삭제 전에 exact plan·보존 ZIP·해시·경로 포함 관계·reparse point·크기·수정 시각을 검사했다. 빈 디렉터리만 비재귀 방식으로 제거했다.
- 현재 사용 중인 BAG·Blender·Python·uv 프로세스가 없음을 실행 직전 확인했다. 다른 작업의 프로세스를 종료하지 않았다.
- 보존 파일 전체 확인과 Git whitespace/catalog 등 문서 검사를 구분한다. 전체 pytest, Blender build, render, QA, delivery를 재실행하지 않았다.

삭제 계획 SHA-256: `4793040e0d9271d415f425398e51fa635d3acb891c5fdcd208f96ec011c9db81`. [정확한 삭제 계획의 무손실 압축본](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/delete-plan.json.gz), [삭제 receipt](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/deletion-receipt.json), [보존 자료 사후 검증](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/post-delete-verification.json).

이번 작업에서 새로 만든 대형 삭제 계획·journal·선별 목록은 GZip으로 압축하고 해제 스트림의 SHA-256 일치를 검증했다. [압축 보관 매핑](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/compressed-evidence-locator.json)에 원래 bytes/hash와 현재 보관 경로가 있다. receipt의 원래 hash는 압축 파일 자체가 아니라 해제한 원문에 적용한다. 이전 작업의 증거를 압축·변경한 것은 아니다.

②의 크기·모델·큰 파일 분석은 [별도 분석 문서](WORKSPACE_CATEGORY2_STORAGE_20261020_KO.md)를 참조한다. ②의 후속 삭제는 이 작업에 포함하지 않았다.

최종 정리 비용과 작업용 임시 폴더 결과: [작업 완료 receipt](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/completion.json).


## 2026-10-21 완료 자산 폐기

사용자의 새 보존 기준에 따라 완료 작업 46개(48,162파일, 7.198 GB)를 실제 폐기했다. 실패·보류·알려진 시각 결함·완료 불명확 자산 19개와 공유 소비 기록은 유지했다. 완료 모델·package 전체는 복원할 수 없으며 원본 reference와 최소 이력만 외부에 보존했다. 앞선 표의 보존·복원 설명은 각 기록 날짜의 상태다. [실제 삭제 목록·현재 보존 목록·무결성 검증](WORKSPACE_COMPLETED_RETIREMENT_20261021_KO.md)을 따른다.
