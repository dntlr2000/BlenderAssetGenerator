# ② 자산 자료의 용량 상세 분석 — 2026-10-20

**모델 파일은 남아 있다. 다만 8.275GB의 대부분은 모델 자체가 아니라 QA 이미지, JSON, PDF와 실행 단계별 사본이다.** 이 분석에서 ②의 파일은 삭제·이동·수정하지 않았다. 65개 root라는 수는 성공한 자산·서로 다른 모델·인간 수용 수가 아니다.

모든 크기는 파일의 논리적 bytes 기준이며 GB=10⁹ bytes, MB=10⁶ bytes다. 용도 표와 확장자 표는 같은 파일을 다른 기준으로 본 것이므로 서로 합산하지 않는다.

## 용도별 크기

| 용도 | 파일 수 | MB | 비율 |
| --- | ---: | ---: | ---: |
| history·workflow·skill 실행 사본 | 22,233 | 2,704.46 | 32.7% |
| QA·렌더 | 18,287 | 1,912.02 | 23.1% |
| AQ·fidelity·controller 실행 자료 | 8,837 | 1,430.84 | 17.3% |
| 최적화·clean import | 2,485 | 1,359.37 | 16.4% |
| 발행된 package 전체 | 2,764 | 531.69 | 6.4% |
| 원본 input | 71 | 110.98 | 1.3% |
| 그 밖의 export·handoff | 1,262 | 97.46 | 1.2% |
| 루트 저작 소스·재질·텍스처·분석 | 846 | 81.86 | 1.0% |
| 기타 | 618 | 43.10 | 0.5% |
| 작업 안의 scratch | 44 | 3.30 | 0.0% |

## 파일 형식별 크기

| 형식 | 파일 수 | MB | 비율 |
| --- | ---: | ---: | ---: |
| `.png` | 20,733 | 3,624.22 | 43.8% |
| `.json` | 33,183 | 1,971.93 | 23.8% |
| `.pdf` | 554 | 1,514.87 | 18.3% |
| `.blend` | 1,241 | 559.13 | 6.8% |
| `.glb` | 58 | 187.82 | 2.3% |
| `.fbx` | 49 | 93.13 | 1.1% |
| `.blend1` | 71 | 21.42 | 0.3% |
| `(no extension)` | 510 | 298.23 | 3.6% |

PNG는 reference·렌더·texture와 그 사본이 섞여 있다. 경로에 texture가 포함된 이미지 2,991개는 합계 600.82MB다. 이 값도 위 PNG/용도 합계에 포함되며 별도 추가 용량이 아니다.

**PDF 554개가 1,514.87MB**다. 이 중 workflow 아래가 1,397.61MB, QA가 82.22MB다. 같은 이름의 workflow PDF도 실제 bytes가 달랐고, SHA-256 기준으로 동일 PDF를 단순 중복 제거할 수 있는 결과는 나오지 않았다.

## 모델은 어느 위치에 얼마나 있는가

모델 확장자 파일은 **1,429개, 861.89MB (10.4%)**다. 이 수에는 `.blend1` 백업, 최적화·import 사본, controller 후보 및 일부 fixture도 포함된다. 확장자 조사이며 새 Blender 열기·품질 검증을 수행한 것은 아니다.

| 위치 | 파일 수 | MB |
| --- | ---: | ---: |
| history·workflow 모델 사본 | 635 | 192.51 |
| 최적화·roundtrip 모델 | 155 | 183.64 |
| 발행된 package 안의 모델 | 81 | 243.91 |
| 각 root의 blender 폴더 | 131 | 40.57 |
| 그 밖의 export·fixture | 55 | 40.25 |
| AQ 후보·비교 모델 | 372 | 161.01 |

각 root의 `blender` 폴더는 `.blend` 67개 20.51MB와 `.blend1` 64개 20.07MB다. **최종 package에는 모델 81개, 243.91MB가 실제 존재**하며 package manifest도 81개 있다. package 전체(텍스처·metadata 포함)는 531.69MB다. manifest가 있다는 사실만으로 전부 현재 검증 통과·인간 수용이라고 판정하지 않는다.

모델끼리 SHA-256이 같은 내용은 1,176종이며, 복수 경로에 저장된 같은 모델 바이트의 초과분은 152.63MB다. ② 전체 파일의 같은 바이트 초과분은 2,133.13MB이지만, 독립 package와 hash-bound snapshot이 각각 그 경로를 요구하므로 이것을 즉시 삭제 가능한 용량으로 보고하지 않는다.

## 가장 큰 자산 폴더에서 실제로 큰 것

| root | 전체 MB | 모델 합계 MB | 큰 구성 |
| --- | ---: | ---: | --- |
| [sunken_submarine_a--11cc69c4](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4) | 1,071.81 | 46.29 | `workflows` 642.30MB, `qa` 337.75MB, `exports` 50.73MB |
| [collectible_cloth_01](E:/Playground/BlenderAssetGenerator/workspaces/collectible_cloth_01) | 916.20 | 104.19 | `history` 461.05MB, `workflows` 149.73MB, `qa` 145.60MB |
| [aq_rf_ab39_01p](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p) | 518.87 | 60.67 | `production` 216.19MB, `optimization` 150.86MB, `fidelity` 84.30MB |
| [item_cannongun_light--e06dd72a](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_cannongun_light--e06dd72a) | 516.29 | 181.69 | `workflows` 278.97MB, `qa` 133.04MB, `exports` 52.31MB |
| [aq_rf_0feae890_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_0feae890_01_plastic) | 352.89 | 42.41 | `optimization` 151.60MB, `production` 82.24MB, `fidelity` 53.55MB |
| [aq_rf_24632c6c_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_01_plastic) | 349.37 | 42.22 | `optimization` 151.52MB, `production` 82.20MB, `fidelity` 50.21MB |
| [aq_rf_493f934b_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_493f934b_01_plastic) | 349.34 | 42.20 | `optimization` 151.55MB, `production` 82.15MB, `fidelity` 50.21MB |
| [aq_rf_df8b1514_01_cap](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_df8b1514_01_cap) | 345.93 | 42.27 | `optimization` 151.55MB, `production` 82.05MB, `fidelity` 46.86MB |
| [item_lasergun_light--966f2475](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_lasergun_light--966f2475) | 272.86 | 13.13 | `workflows` 151.93MB, `qa` 93.51MB, `exports` 14.47MB |
| [item_canongun_normal--c54e50f1](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_canongun_normal--c54e50f1) | 253.38 | 11.88 | `workflows` 112.48MB, `qa` 97.86MB, `exports` 18.95MB |
| [underwater_department_v09--2f48c879](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/underwater_department_v09--2f48c879) | 251.62 | 6.37 | `qa` 216.35MB, `exports` 13.28MB, `optimization` 6.95MB |
| [aq_rf_24632c6c_02_rust_outline](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_02_rust_outline) | 240.36 | 34.56 | `production` 72.82MB, `fidelity` 56.40MB, `exports` 49.59MB |

- `sunken_submarine_a`의 1.072GB 중 workflow 642.30MB와 QA 337.75MB가 대부분이며 루트 blender는 0.56MB다.
- `collectible_cloth_01`의 916.20MB 중 history 461.05MB, workflow 149.73MB, QA 145.60MB가 크다. 루트 blender는 0.28MB다.
- `aq_rf_ab39_01p`는 518.87MB 중 production 216.19MB, optimization 150.86MB, fidelity 84.30MB다. 최적화 전후 triangle-corner 원본 JSON 두 개만 약 134.45MB를 차지한다. 실제 package가 그만큼 큰 것은 아니다.
- 현재 Cloth와 archive의 Cloth는 reference가 같더라도 job·SceneSpec·이력이 다르다. 이름이 비슷하다는 이유로 전체 중복본이라고 분류하지 않는다.

## 큰 개별 파일

| 실제 파일 | MB |
| --- | ---: |
| [workspaces/aq_rf_ab39_01p/optimization/runs/delivery-plan-aqv2-20260929t015114075784z-a16a0f35-gltf-run/aq_v2/geometry/clean_import_glb_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p/optimization/runs/delivery-plan-aqv2-20260929t015114075784z-a16a0f35-gltf-run/aq_v2/geometry/clean_import_glb_corners.json) | 67.23 |
| [workspaces/aq_rf_ab39_01p/optimization/runs/delivery-plan-aqv2-20260929t015114075784z-a16a0f35-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p/optimization/runs/delivery-plan-aqv2-20260929t015114075784z-a16a0f35-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 67.23 |
| [workspaces/aq_rf_0feae890_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t071051110034z-014a1880-gltf-run/aq_v2/geometry/clean_import_glb_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_0feae890_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t071051110034z-014a1880-gltf-run/aq_v2/geometry/clean_import_glb_corners.json) | 67.22 |
| [workspaces/aq_rf_24632c6c_01_plastic/optimization/runs/delivery-plan-aqv2-20260920t132026256627z-f1e45212-gltf-run/aq_v2/geometry/clean_import_glb_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_01_plastic/optimization/runs/delivery-plan-aqv2-20260920t132026256627z-f1e45212-gltf-run/aq_v2/geometry/clean_import_glb_corners.json) | 67.22 |
| [workspaces/aq_rf_493f934b_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t131749717210z-896f562a-gltf-run/aq_v2/geometry/clean_import_glb_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_493f934b_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t131749717210z-896f562a-gltf-run/aq_v2/geometry/clean_import_glb_corners.json) | 67.22 |
| [workspaces/aq_rf_df8b1514_01_cap/optimization/runs/delivery-plan-aqv2-20260917t133124449532z-5735c8a2-gltf-run/aq_v2/geometry/clean_import_glb_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_df8b1514_01_cap/optimization/runs/delivery-plan-aqv2-20260917t133124449532z-5735c8a2-gltf-run/aq_v2/geometry/clean_import_glb_corners.json) | 67.22 |
| [workspaces/aq_rf_0feae890_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t071051110034z-014a1880-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_0feae890_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t071051110034z-014a1880-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 67.22 |
| [workspaces/aq_rf_24632c6c_01_plastic/optimization/runs/delivery-plan-aqv2-20260920t132026256627z-f1e45212-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_01_plastic/optimization/runs/delivery-plan-aqv2-20260920t132026256627z-f1e45212-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 67.22 |
| [workspaces/aq_rf_493f934b_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t131749717210z-896f562a-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_493f934b_01_plastic/optimization/runs/delivery-plan-aqv2-20260919t131749717210z-896f562a-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 67.22 |
| [workspaces/aq_rf_df8b1514_01_cap/optimization/runs/delivery-plan-aqv2-20260917t133124449532z-5735c8a2-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_df8b1514_01_cap/optimization/runs/delivery-plan-aqv2-20260917t133124449532z-5735c8a2-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 67.22 |
| [workspaces/aq_first_completion_n03_fix3_02_rusted_scrap/optimization/runs/delivery-plan-aqv2-20260903t084805714607z-55d163f4-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_02_rusted_scrap/optimization/runs/delivery-plan-aqv2-20260903t084805714607z-55d163f4-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 31.65 |
| [workspaces/aq_first_completion_n02_fix2_02_rusted_scrap/optimization/runs/delivery-plan-aqv2-20260903t071722011184z-0c1ca353-gltf-run/aq_v2/geometry/optimized_lod0_corners.json](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n02_fix2_02_rusted_scrap/optimization/runs/delivery-plan-aqv2-20260903t071722011184z-0c1ca353-gltf-run/aq_v2/geometry/optimized_lod0_corners.json) | 31.65 |

대표적인 큰 PDF:

- [workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4/workflows/wf-20260729t162010z-2a3c631d/artifacts/pdf/640930982b3e.pdf](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4/workflows/wf-20260729t162010z-2a3c631d/artifacts/pdf/640930982b3e.pdf): 10.64MB.
- [workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4/workflows/wf-20260729t161112z-754004a7/artifacts/pdf/640930982b3e.pdf](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4/workflows/wf-20260729t161112z-754004a7/artifacts/pdf/640930982b3e.pdf): 10.64MB.
- [workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4/workflows/wf-20260729t154757z-204181a6/artifacts/pdf/640930982b3e.pdf](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4/workflows/wf-20260729t154757z-204181a6/artifacts/pdf/640930982b3e.pdf): 10.64MB.

## 65개 root 전체

| 경로 | 전체 MB | 모델 파일 수 | 모델 합계 MB |
| --- | ---: | ---: | ---: |
| [workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/sunken_submarine_a--11cc69c4) | 1,071.81 | 83 | 46.29 |
| [workspaces/collectible_cloth_01](E:/Playground/BlenderAssetGenerator/workspaces/collectible_cloth_01) | 916.20 | 157 | 104.19 |
| [workspaces/aq_rf_ab39_01p](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p) | 518.87 | 42 | 60.67 |
| [workspace_archive/completed/2026-08/item_cannongun_light--e06dd72a](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_cannongun_light--e06dd72a) | 516.29 | 78 | 181.69 |
| [workspaces/aq_rf_0feae890_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_0feae890_01_plastic) | 352.89 | 23 | 42.41 |
| [workspaces/aq_rf_24632c6c_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_01_plastic) | 349.37 | 23 | 42.22 |
| [workspaces/aq_rf_493f934b_01_plastic](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_493f934b_01_plastic) | 349.34 | 23 | 42.20 |
| [workspaces/aq_rf_df8b1514_01_cap](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_df8b1514_01_cap) | 345.93 | 23 | 42.27 |
| [workspace_archive/completed/2026-08/item_lasergun_light--966f2475](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_lasergun_light--966f2475) | 272.86 | 59 | 13.13 |
| [workspace_archive/completed/2026-08/item_canongun_normal--c54e50f1](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_canongun_normal--c54e50f1) | 253.38 | 41 | 11.88 |
| [workspace_archive/completed/2026-08/underwater_department_v09--2f48c879](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/underwater_department_v09--2f48c879) | 251.62 | 10 | 6.37 |
| [workspaces/aq_rf_24632c6c_02_rust_outline](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_02_rust_outline) | 240.36 | 29 | 34.56 |
| [workspaces/item_standardgun_heavy](E:/Playground/BlenderAssetGenerator/workspaces/item_standardgun_heavy) | 218.57 | 41 | 9.74 |
| [workspace_archive/completed/2026-08/item_standardgun_light--36d88bb7](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_standardgun_light--36d88bb7) | 182.85 | 45 | 9.02 |
| [workspace_archive/completed/2026-08/item_cannongun_heavy--b3fa862a](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_cannongun_heavy--b3fa862a) | 153.42 | 33 | 9.40 |
| [workspace_archive/completed/2026-08/item_lasergun_heavy--3d48881b](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_lasergun_heavy--3d48881b) | 133.48 | 24 | 4.24 |
| [workspace_archive/completed/2026-08/item_degradedgun--c0d9acc0](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_degradedgun--c0d9acc0) | 127.38 | 33 | 5.62 |
| [workspaces/underwater_ocean-department_test](E:/Playground/BlenderAssetGenerator/workspaces/underwater_ocean-department_test) | 126.38 | 9 | 10.60 |
| [workspace_archive/completed/2026-08/item_standardgun_normal--8b0c3df6](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/item_standardgun_normal--8b0c3df6) | 123.58 | 21 | 6.03 |
| [workspaces/collectible_scrap_02](E:/Playground/BlenderAssetGenerator/workspaces/collectible_scrap_02) | 110.15 | 32 | 10.06 |
| [workspaces/aq_first_completion_n03_fix3_02_rusted_scrap](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_02_rusted_scrap) | 105.58 | 15 | 13.97 |
| [workspaces/aq_first_completion_n02_fix2_02_rusted_scrap](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n02_fix2_02_rusted_scrap) | 105.56 | 15 | 13.94 |
| [workspace_archive/completed/2026-08/underwater_aidkit--fee09372](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/underwater_aidkit--fee09372) | 92.38 | 20 | 3.94 |
| [workspaces/item_lasergun_normal](E:/Playground/BlenderAssetGenerator/workspaces/item_lasergun_normal) | 89.36 | 24 | 5.23 |
| [workspaces/collectible_rock_01](E:/Playground/BlenderAssetGenerator/workspaces/collectible_rock_01) | 86.07 | 19 | 1.76 |
| [workspaces/collectible_wood_03_standard](E:/Playground/BlenderAssetGenerator/workspaces/collectible_wood_03_standard) | 82.39 | 22 | 2.22 |
| [workspace_archive/completed/2026-08/collectible_cloth_01--65a9ab63](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/collectible_cloth_01--65a9ab63) | 78.10 | 18 | 13.25 |
| [workspaces/aq_first_completion_n03_fix3_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_03_weathered_wood_beam) | 70.15 | 14 | 9.26 |
| [workspaces/item_plastic_standard_canary_01](E:/Playground/BlenderAssetGenerator/workspaces/item_plastic_standard_canary_01) | 66.15 | 14 | 3.71 |
| [workspace_archive/completed/2026-08/collectible_plastic_02--7c6f4a0e](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/collectible_plastic_02--7c6f4a0e) | 60.81 | 17 | 2.15 |
| [workspaces/aq_first_completion_n03_fix3_04_crystal_emitter](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_04_crystal_emitter) | 58.64 | 17 | 8.60 |
| [workspace_archive/completed/2026-08/collectible_wood_01--40bd8000](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/collectible_wood_01--40bd8000) | 57.49 | 12 | 2.95 |
| [workspaces/aq_ref_fidelity_47e3928_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_ref_fidelity_47e3928_01_plastic_shard) | 55.35 | 14 | 6.21 |
| [workspaces/aq_ref_fidelity_c8b1507_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_ref_fidelity_c8b1507_01_plastic_shard) | 55.35 | 14 | 6.21 |
| [workspaces/collectible_plastic_01_desktop](E:/Playground/BlenderAssetGenerator/workspaces/collectible_plastic_01_desktop) | 53.01 | 15 | 2.93 |
| [workspaces/collectible_scrap_01](E:/Playground/BlenderAssetGenerator/workspaces/collectible_scrap_01) | 49.73 | 18 | 2.99 |
| [workspace_archive/completed/2026-08/underwater_car4--ea9ed7a5](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/underwater_car4--ea9ed7a5) | 48.86 | 12 | 6.77 |
| [workspaces/aq_first_completion_f68_fix1_02_rusted_scrap](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_f68_fix1_02_rusted_scrap) | 42.32 | 15 | 14.03 |
| [workspace_archive/completed/2026-08/wooprider_mainstage_1--e4caabc2](E:/Playground/BlenderAssetGenerator/workspace_archive/completed/2026-08/wooprider_mainstage_1--e4caabc2) | 32.09 | 8 | 1.30 |
| [workspaces/underwater_car3](E:/Playground/BlenderAssetGenerator/workspaces/underwater_car3) | 26.91 | 4 | 0.82 |
| [workspaces/underwater_car2](E:/Playground/BlenderAssetGenerator/workspaces/underwater_car2) | 25.33 | 4 | 0.64 |
| [workspaces/aq_first_completion_n02_fix2_05_multi_material_laser](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n02_fix2_05_multi_material_laser) | 19.33 | 19 | 3.33 |
| [workspaces/aq_first_completion_n03_fix3_05_multi_material_laser](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_05_multi_material_laser) | 19.33 | 19 | 3.33 |
| [workspaces/aq_first_completion_n02_fix2_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n02_fix2_01_plastic_shard) | 15.93 | 14 | 2.28 |
| [workspaces/aq_first_completion_n03_fix3_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_01_plastic_shard) | 15.93 | 14 | 2.28 |
| [workspaces/aq_first_completion_735_vis1_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_735_vis1_01_plastic_shard) | 15.12 | 14 | 2.28 |
| [workspaces/aq_first_completion_f68_fix1_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_f68_fix1_01_plastic_shard) | 15.11 | 14 | 2.28 |
| [workspaces/aq_first_completion_c655_rv2_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_c655_rv2_01_plastic_shard) | 14.85 | 14 | 2.28 |
| [workspaces/aq_first_completion_4bb_rv1d_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_rv1d_01_plastic_shard) | 14.82 | 14 | 2.28 |
| [workspaces/aq_first_completion_4bb_rv1c_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_rv1c_01_plastic_shard) | 14.78 | 14 | 2.25 |
| [workspaces/aq_first_completion_4bb_rv1b_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_rv1b_01_plastic_shard) | 14.78 | 14 | 2.25 |
| [workspaces/aq_stage9_prep_r5d_01_laser_perspective_canary](E:/Playground/BlenderAssetGenerator/workspaces/aq_stage9_prep_r5d_01_laser_perspective_canary) | 14.25 | 15 | 2.87 |
| [workspaces/aq_first_completion_4bb_01_plastic_shard](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_01_plastic_shard) | 14.19 | 12 | 2.04 |
| [workspaces/aq_first_completion_b87_01_plastic_shard_retry02](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_b87_01_plastic_shard_retry02) | 14.17 | 12 | 2.04 |
| [workspaces/aq_first_completion_c655_rv2_02_rusted_scrap](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_c655_rv2_02_rusted_scrap) | 13.12 | 9 | 1.20 |
| [workspaces/aq_first_completion_4bb_02_rusted_scrap_r2](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_02_rusted_scrap_r2) | 13.12 | 9 | 1.20 |
| [workspaces/aq_first_completion_c655_rv2_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_c655_rv2_03_weathered_wood_beam) | 11.54 | 9 | 1.13 |
| [workspaces/aq_first_completion_4bb_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_03_weathered_wood_beam) | 11.53 | 9 | 1.13 |
| [workspaces/aq_volumetric_r8_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_volumetric_r8_03_weathered_wood_beam) | 11.45 | 9 | 1.10 |
| [workspaces/aq_volumetric_r7_03_weathered_wood_beam](E:/Playground/BlenderAssetGenerator/workspaces/aq_volumetric_r7_03_weathered_wood_beam) | 11.43 | 9 | 1.10 |
| [workspaces/aq_first_completion_c655_rv2_05_multi_material_laser](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_c655_rv2_05_multi_material_laser) | 11.23 | 13 | 2.25 |
| [workspaces/aq_first_completion_4bb_05_multi_material_laser](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_05_multi_material_laser) | 11.23 | 13 | 2.25 |
| [workspaces/aq_first_completion_c655_rv2_04_crystal_emitter](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_c655_rv2_04_crystal_emitter) | 8.26 | 9 | 1.47 |
| [workspaces/aq_first_completion_4bb_04_crystal_emitter_r2](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_4bb_04_crystal_emitter_r2) | 8.26 | 9 | 1.47 |
| [workspaces/underwater_car1](E:/Playground/BlenderAssetGenerator/workspaces/underwater_car1) | 4.93 | 2 | 0.31 |

## 다음에 ②를 줄인다면

현재 명령은 분석까지만이므로 아래 항목을 삭제하지 않았다.

1. **완성 자산을 계속 쓸 경우**: input, 마지막 저작 SceneSpec·geometry·material/texture dependency, Blender 원본, 선택한 최종 package·clean-import·인간 수용을 한 묶음으로 남기는 범위를 먼저 정한다.
2. **workflow PDF·QA history가 가장 큰 절감 후보**다. 다만 사용자가 전체 이력 재검증·이전 revision 복구를 포기하는 범위를 정해야 한다. 단순 이름 중복 제거 대신 파일별 연결을 확인하고, 필요한 raw 증거만 선별 보존하는 방식을 적용한다.
3. **AQ numerical-survival corner JSON**은 현재 정확한 납품 검증에 사용되는 원본이다. 요약 report만 남기면 raw proof를 다시 검증할 수 없다. 그 검증 가능성을 유지하려면 원본 또는 무손실 보존본이 필요하다. 원위치 압축 변경은 native 경로 검증을 깨므로 자동으로 하지 않는다.
4. **native archive 16개**는 receipt가 전체 tree에 결속되어 있다. 내부 파일 몇 개만 삭제하면 현재 archive 검증·복원 계약이 깨진다. 전체 tree를 보존할지, 필요한 최종 모델만 별도로 보존하고 archive를 폐기할지 명확히 선택해야 한다.
5. 바이트가 같다는 분석은 삭제 권한이나 대체 보존 경로 검증을 대신하지 않는다. 이번 수치로 ② 전체를 재생성 가능한 cache라고 간주하지 않는다.

추가 삭제 가능량은 아직 확정하지 않았다. 이번 ③·④의 실제 정리 결과는 [정리 결과 문서](WORKSPACE_CLEANUP_20261020_KO.md)에 있다.

원자료: [category2-analysis.json](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/category2-analysis.json), [category2-details.json](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/category2-details.json), [모델 전체 경로·크기·SHA-256](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/category2-models.json), [모델의 바이트 동일 그룹](E:/CodexValidation/bag-history-cleanup-20261020-run01/evidence/category2-model-byte-duplicates.json).


## 2026-10-21 완료 자산 폐기

사용자의 새 보존 기준에 따라 완료 작업 46개(48,162파일, 7.198 GB)를 실제 폐기했다. 실패·보류·알려진 시각 결함·완료 불명확 자산 19개와 공유 소비 기록은 유지했다. 완료 모델·package 전체는 복원할 수 없으며 원본 reference와 최소 이력만 외부에 보존했다. 앞선 표의 보존·복원 설명은 각 기록 날짜의 상태다. [실제 삭제 목록·현재 보존 목록·무결성 검증](WORKSPACE_COMPLETED_RETIREMENT_20261021_KO.md)을 따른다.
