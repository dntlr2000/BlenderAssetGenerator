# 완료 자산 폐기 및 실패·보류 자료 보존 — 2026-10-21

사용자가 완료된 자산은 더 이상 필요하지 않다고 지정하고, **package·clean import 등의 기술적 납품이 끝났더라도 알려진 시각 결함이나 후속 실패·보류가 있으면 남기는 기준**을 선택했다. 이 문서는 그 선택에 따라 실제 실행한 저장공간 정리 기록이다. 자산의 새 품질 평가, 인간 수용, 캠페인 재개가 아니다.

Git 기준은 `Dots` / `ca81eb719dd499d043ce4877c3153dcde489e25a`다. 기존 staged 20개 문서·생성 파일을 보존했다. source 구현·버전·태그·state·terminal·과거 receipt를 수정하지 않았으며 commit·push는 하지 않았다. 이후 이 안내와 문서 카탈로그만 갱신했다.

## 실행 결과

| 항목 | 결과 |
| --- | ---: |
| 완료 작업 root | **46개: Standard 20개, AQ 26개** |
| 실제 삭제 | **48,162개 파일, 7,198,029,397 bytes** |
| 삭제량 | **7.198 GB / 6.704 GiB** |
| 완전히 제거된 작업 root | **46개** |
| 제거한 빈 디렉터리 | 21,610개 |
| 최종 미삭제 오류·ACL 변경 | 0건 |
| 최소 보존 ZIP | 38,159,256 bytes, 약 38.16 MB |
| 보존한 실패·보류·시각 결함·불명확 자산 | **19개, 9,285파일, 1,077,024,948 bytes** |
| 공유 계약·소비·원래 archive receipt와 이전 부분 보존본 | 496파일, 127,259,994 bytes |
| workspace 계열 최종 일반 파일 합계 | 9,781파일, 1,204,284,942 bytes; 별도 0-byte `.gitkeep` 유지 |

46개는 동일 자산의 여러 과거 세션과 버전을 포함한 작업 폴더 수이며, 서로 다른 자산 46종이라는 뜻이 아니다. GB는 10진, GiB는 2진 단위다.

파일 삭제량에서 새 보존 ZIP·목록·receipt·문서 크기를 차감해야 순저장량 감소가 된다. 최종 비용은 [완료 receipt](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/completion.json)에 기록한다. E: 여유 공간은 첫 삭제 구간에서 110,160,969,728 → 117,468,307,456 bytes였지만 다른 작업의 디스크 활동을 포함하므로 그 차이 전체를 이번 확보량으로 세지 않는다.

파일명 `20260726T080016Z_revision_plan..pre_front_connectivity.json` 1개는 정리 helper가 basename의 두 점을 경로 이탈로 과도하게 거부했다. 원래 계획·경로 포함 관계·바이트 해시를 다시 확인해 별도 receipt로 제거했다. 첫 실패 receipt를 고치지 않았고 ACL을 바꾸거나 새로운 삭제 범위를 추가하지 않았다.

## 삭제한 완료 작업

| 원래 경로 | 근거 | 원래 MB |
| --- | --- | ---: |
| `workspace_archive/completed/2026-08/collectible_cloth_01--65a9ab63` | Standard 완료 + 결속 clean import | 78.10 |
| `workspace_archive/completed/2026-08/collectible_plastic_02--7c6f4a0e` | Standard 완료 + 결속 clean import | 60.81 |
| `workspace_archive/completed/2026-08/collectible_wood_01--40bd8000` | Standard 완료 + 결속 clean import | 57.49 |
| `workspace_archive/completed/2026-08/item_cannongun_heavy--b3fa862a` | Standard 완료 + 결속 clean import | 153.42 |
| `workspace_archive/completed/2026-08/item_cannongun_light--e06dd72a` | Standard 완료 + 결속 clean import | 516.29 |
| `workspace_archive/completed/2026-08/item_canongun_normal--c54e50f1` | Standard 완료 + 결속 clean import | 253.38 |
| `workspace_archive/completed/2026-08/item_degradedgun--c0d9acc0` | Standard 완료 + 결속 clean import | 127.38 |
| `workspace_archive/completed/2026-08/item_lasergun_heavy--3d48881b` | Standard 완료 + 결속 clean import | 133.48 |
| `workspace_archive/completed/2026-08/item_lasergun_light--966f2475` | Standard 완료 + 결속 clean import | 272.86 |
| `workspace_archive/completed/2026-08/item_standardgun_light--36d88bb7` | Standard 완료 + 결속 clean import | 182.85 |
| `workspace_archive/completed/2026-08/item_standardgun_normal--8b0c3df6` | Standard 완료 + 결속 clean import | 123.58 |
| `workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4` | Standard 완료 + 결속 clean import | 1071.81 |
| `workspace_archive/completed/2026-08/underwater_aidkit--fee09372` | Standard 완료 + 결속 clean import | 92.38 |
| `workspace_archive/completed/2026-08/underwater_car4--ea9ed7a5` | Standard 완료 + 결속 clean import | 48.86 |
| `workspace_archive/completed/2026-08/underwater_department_v09--2f48c879` | Standard 완료 + 결속 clean import | 251.62 |
| `workspaces/aq_first_completion_4bb_01_plastic_shard` | AQ production terminal + 결속 clean import | 14.19 |
| `workspaces/aq_first_completion_4bb_02_rusted_scrap_r2` | AQ production terminal + 결속 clean import | 13.12 |
| `workspaces/aq_first_completion_4bb_03_weathered_wood_beam` | AQ production terminal + 결속 clean import | 11.53 |
| `workspaces/aq_first_completion_4bb_04_crystal_emitter_r2` | AQ production terminal + 결속 clean import | 8.26 |
| `workspaces/aq_first_completion_4bb_05_multi_material_laser` | AQ production terminal + 결속 clean import | 11.23 |
| `workspaces/aq_first_completion_735_vis1_01_plastic_shard` | AQ production terminal + 결속 clean import | 15.12 |
| `workspaces/aq_first_completion_c655_rv2_01_plastic_shard` | AQ production terminal + 결속 clean import | 14.85 |
| `workspaces/aq_first_completion_c655_rv2_02_rusted_scrap` | AQ production terminal + 결속 clean import | 13.12 |
| `workspaces/aq_first_completion_c655_rv2_03_weathered_wood_beam` | AQ production terminal + 결속 clean import | 11.54 |
| `workspaces/aq_first_completion_c655_rv2_04_crystal_emitter` | AQ production terminal + 결속 clean import | 8.26 |
| `workspaces/aq_first_completion_c655_rv2_05_multi_material_laser` | AQ production terminal + 결속 clean import | 11.23 |
| `workspaces/aq_first_completion_f68_fix1_01_plastic_shard` | AQ production terminal + 결속 clean import | 15.11 |
| `workspaces/aq_first_completion_n02_fix2_01_plastic_shard` | AQ production terminal + 결속 clean import | 15.93 |
| `workspaces/aq_first_completion_n02_fix2_02_rusted_scrap` | AQ production terminal + 결속 clean import | 105.56 |
| `workspaces/aq_first_completion_n02_fix2_05_multi_material_laser` | AQ production terminal + 결속 clean import | 19.33 |
| `workspaces/aq_first_completion_n03_fix3_01_plastic_shard` | AQ production terminal + 결속 clean import | 15.93 |
| `workspaces/aq_first_completion_n03_fix3_05_multi_material_laser` | AQ production terminal + 결속 clean import | 19.33 |
| `workspaces/aq_ref_fidelity_47e3928_01_plastic_shard` | AQ production terminal + 결속 clean import | 55.35 |
| `workspaces/aq_ref_fidelity_c8b1507_01_plastic_shard` | AQ production terminal + 결속 clean import | 55.35 |
| `workspaces/aq_rf_0feae890_01_plastic` | AQ production terminal + 결속 clean import | 352.89 |
| `workspaces/aq_rf_24632c6c_01_plastic` | AQ production terminal + 결속 clean import | 349.37 |
| `workspaces/aq_rf_24632c6c_02_rust_outline` | AQ production terminal + 결속 clean import | 240.36 |
| `workspaces/aq_rf_493f934b_01_plastic` | AQ production terminal + 결속 clean import | 349.34 |
| `workspaces/aq_rf_ab39_01p` | AQ production terminal + 결속 clean import | 518.87 |
| `workspaces/aq_rf_df8b1514_01_cap` | AQ production terminal + 결속 clean import | 345.93 |
| `workspaces/aq_volumetric_r8_03_weathered_wood_beam` | AQ production terminal + 결속 clean import | 11.45 |
| `workspaces/collectible_cloth_01` | Standard 완료 + 결속 clean import | 916.20 |
| `workspaces/collectible_plastic_01_desktop` | Standard 완료 + 결속 clean import | 53.01 |
| `workspaces/collectible_rock_01` | Standard 완료 + 결속 clean import | 86.07 |
| `workspaces/collectible_scrap_01` | Standard 완료 + 결속 clean import | 49.73 |
| `workspaces/item_plastic_standard_canary_01` | Standard 완료 + 결속 clean import | 66.15 |

이 완료 근거는 자동 기술 결과다. 별도 인간 acceptance 기록이 없는 작업을 인간 수용으로 승격하지 않았다. 과거 완료 실적과 이미 소비한 예산은 폐기 이후에도 유지하며 환급·초기화하지 않는다.

## 보존한 자산

| 현재 경로 | 이유 | MB |
| --- | --- | ---: |
| [workspaces/item_standardgun_heavy](E:/Playground/BlenderAssetGenerator/workspaces/item_standardgun_heavy) | 최신 Standard 진행·승인 대기 또는 blocked | 218.57 |
| [workspaces/underwater_ocean-department_test](E:/Playground/BlenderAssetGenerator/workspaces/underwater_ocean-department_test) | package는 있으나 권위 있는 완료 상태 미확인 | 126.38 |
| [workspaces/collectible_scrap_02](E:/Playground/BlenderAssetGenerator/workspaces/collectible_scrap_02) | package는 있으나 권위 있는 완료 상태 미확인 | 110.15 |
| [workspaces/aq_first_completion_n03_fix3_02_rusted_scrap](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_02_rusted_scrap) | 기술 완료와 별도로 알려진 구조·시각 결함 | 105.58 |
| [workspaces/item_lasergun_normal](E:/Playground/BlenderAssetGenerator/workspaces/item_lasergun_normal) | 최신 Standard 진행·승인 대기 또는 blocked | 89.36 |
| [workspaces/collectible_wood_03_standard](E:/Playground/BlenderAssetGenerator/workspaces/collectible_wood_03_standard) | package는 있으나 권위 있는 완료 상태 미확인 | 82.39 |
| [workspaces/aq_first_completion_n03_fix3_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_03_weathered_wood_beam) | 기술 완료와 별도로 알려진 구조·시각 결함 | 70.15 |
| [workspaces/aq_first_completion_n03_fix3_04_crystal_emitter](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_04_crystal_emitter) | 기술 완료와 별도로 알려진 구조·시각 결함 | 58.64 |
| [workspaces/aq_first_completion_f68_fix1_02_rusted_scrap](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_f68_fix1_02_rusted_scrap) | 원래 AQ 실패·중단·미완료 상태 포함 | 42.32 |
| [workspace_archive/completed/2026-08/wooprider_mainstage_1--e4caabc2](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/wooprider_mainstage_1--e4caabc2) | workflow 완료지만 package/import 완료 범위 불명확 | 32.09 |
| [workspaces/underwater_car3](E:/Playground/BlenderAssetGenerator/workspaces/underwater_car3) | 최신 Standard 진행·승인 대기 또는 blocked | 26.91 |
| [workspaces/underwater_car2](E:/Playground/BlenderAssetGenerator/workspaces/underwater_car2) | 최신 Standard 진행·승인 대기 또는 blocked | 25.33 |
| [workspaces/aq_first_completion_4bb_rv1d_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_rv1d_01_plastic_shard) | 원래 AQ 실패·중단·미완료 상태 포함 | 14.82 |
| [workspaces/aq_first_completion_4bb_rv1c_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_rv1c_01_plastic_shard) | 원래 AQ 실패·중단·미완료 상태 포함 | 14.78 |
| [workspaces/aq_first_completion_4bb_rv1b_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_rv1b_01_plastic_shard) | 원래 AQ 실패·중단·미완료 상태 포함 | 14.78 |
| [workspaces/aq_stage9_prep_r5d_01_laser_perspective_canary](E:/Playground/BlenderAssetGenerator/workspaces/aq_stage9_prep_r5d_01_laser_perspective_canary) | 원래 AQ 실패·중단·미완료 상태 포함 | 14.25 |
| [workspaces/aq_first_completion_b87_01_plastic_shard_retry02](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_b87_01_plastic_shard_retry02) | 원래 AQ 실패·중단·미완료 상태 포함 | 14.17 |
| [workspaces/aq_volumetric_r7_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_volumetric_r7_03_weathered_wood_beam) | 원래 AQ 실패·중단·미완료 상태 포함 | 11.43 |
| [workspaces/underwater_car1](E:/Playground/BlenderAssetGenerator/workspaces/underwater_car1) | 최신 Standard 진행·승인 대기 또는 blocked | 4.93 |

실패·보류로 확정된 것만 남긴 것이 아니라, 완료 근거가 불명확한 4개도 보수적으로 보존했다. AQ 바깥 V0.8의 오래된 `waiting_for_agent`만으로 실패를 추정하지 않고 실제 AQ terminal과 final-state·package/import 해시 결속을 확인했다.

19개 전체와 과거 부분 보존본의 JSON 파일 참조 및 전이 의존성을 검사했고, 이번 삭제 대상의 기존 파일에 대한 직접 의존성은 발견되지 않았다. 공유 계약과 archive receipt는 이력용 원문으로 유지했으며, 과거 job ID나 receipt가 가리킨다는 이유만으로 폐기한 모델 전체를 다시 보관하지 않았다.

기존 `.fidelity_budget`, `.fidelity_delegations`, archive plan/receipt, `_staging`과 소수 부분 보존 경로는 이번 46개 범위 밖이다. 정션 fixture도 그대로이며 링크 대상을 따라가지 않았다. 이전 10월 20일 정리로 이미 bulk가 삭제된 실패 작업까지 새로 복원한 것은 아니다.

## 외부 최소 보존본과 복원 한계

- [원본·최소 이력 ZIP](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/preserved-minimum.zip): 원래 경로 2,694개에 대응하는 고유 바이트 2,643개. 원본 input, job 식별 정보, session state·소비·권한·terminal, package manifest·clean-import 요약·기존 인간 판정, 선택 visual finding과 fixture anchor를 보존했다.
- ZIP SHA-256: `41a4a2abc5bbeac273632d0652441dce11aa6518238b68a6e667a462c80c7815`.
- [파일별 선별 사유와 원경로 매핑](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/preservation-selection.json.gz), [모든 ZIP member 해시 검사](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/preservation-verification.json).
- **완료 모델 `.blend`·`.glb`·`.fbx`와 package 전체는 보존 대상이 아니다.** 예외적인 과거 fixture anchor의 작은 저작 JSON은 남겼지만 전체 저작 의존성을 갖춘 복원본은 아니다.
- 기존 Plastic before/after·reference·Standard 비교 이미지와 10월 20일 보존 ZIP의 Wood cutback 이미지 하나를 정확한 바이트로 열람 가능하게 두었다. [시각 기록](VISUAL_EVIDENCE_KO.md)의 링크만 갱신했고 새 이미지를 생성하거나 새 시각 판정을 만들지 않았다.
- 삭제된 경로를 요구하는 과거 historical-anchor/full-tree/native archive 검증은 원위치에서 그대로 재실행할 수 없다. native archive 16개 중 15개 payload를 이번에 폐기했으며, WoopRider 1개와 공유 원래 receipt는 유지했다. 원래 receipt의 존재가 폐기된 15개를 복원 가능하다는 뜻은 아니다.
- 기존 machine JSON·fixture·receipt 안의 경로와 hash를 수정하거나 자동 migration하지 않았다. 외부 원본 locator는 역사 조회를 위한 것이며 새 실행 authority가 아니다.

## 확인한 무결성과 증거

- 삭제 직전 57,943파일의 크기·수정 시각·SHA-256을 대조했다. 완료 분류를 현재 파일에서 다시 계산했고 최초 검토와 일치했다.
- 삭제 후 남은 **9,781파일 전체**와 최신 닷츠산 checkpoint의 **129파일 / 14,248,010 bytes**를 재해시했고 내용 변경이 없었다.
- 원위치 19개와 공유 계약·소비·archive 원본 기록이 동일하며, Git HEAD·index·기존 문서 변경은 문서 갱신 직전까지 모두 같았다.
- 관련 BAG/Blender/Python/uv 및 workspace 사용 프로세스가 없음을 읽기 전용으로 확인했다. 과거 PDF용 Edge profile의 LOCK 21개도 사용 프로세스가 없었으며 다른 프로세스를 종료하지 않았다.
- exact 파일 목록만 native PowerShell로 제거하고, 확인된 빈 디렉터리만 비재귀 삭제했다. 정션·상위 루트·알 수 없는 새 파일은 삭제하지 않았다.
- 자산 실행 및 전체 pytest/Blender 검증은 수행하지 않았다. 문서·카탈로그·invariant·whitespace 검사와 저장공간 무결성 검사는 [문서 검증 결과](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/documentation-validation.json) 및 완료 receipt로 구분한다.

정확한 삭제 계획 SHA-256: `3f24b781c74e83f0ae1007269b099a451d5baf1adaf26513e36fc95b0c520363`.

[삭제 계획](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/delete-plan.json.gz) · [첫 삭제 receipt](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/deletion-receipt.json) · [1개 잔여 파일 처리](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/residual-retirement-receipt.json) · [최종 보존 검증](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/post-delete-verification-final.json) · [원문/압축 파일 hash 매핑](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/compressed-evidence-locator.json) · [최종 용량·임시파일 정리 결과](E:/CodexValidation/bag-completed-retirement-20261021-run02/evidence/completion.json)

이번 새 대형 계획·journal만 무손실 압축한 뒤 해제 hash를 검증했다. 이전 증거는 변경하지 않았다. 과거 자료 보존 결정을 변경하거나 추가 삭제하려면 현재 필요를 다시 확인하며, 이 문서는 추가 개발·캠페인·push 지시가 아니다.
