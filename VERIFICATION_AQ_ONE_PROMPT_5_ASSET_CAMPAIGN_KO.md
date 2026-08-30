# AQ One-Prompt 실제 reference 5개 실험 캠페인 검증 기록

## 1. 판정

2026-08-30 현재 `aq-one-prompt-orchestrator`의 동일 reference 5개 volumetric 재캠페인은
**IQ pass 1/5, source freeze 1/5, 후속 wood portable GLTF delivery 1/1 통과, 새 beauty human
disposition 0/5, activation NO-GO**입니다. R2의 exact beauty 5개에 기록한 `needs_revision`은
그 R2 evidence에만 유효하며 이번 후보에는 재사용하지 않았습니다.

- 최초 캠페인의 adapter route/receipt와 ControllerExecutor protected-inventory 결함을 수정하고,
  orphan policy authorization도 exact replay 또는 `technical_failed` receipt로 회수하도록 보강했습니다.
- R2 이후 같은 immutable reference 5개를 얇은 extrusion이 아닌 depth를 가진 R5 후보로 다시
  실행했고, 모두 Reference → Geometry → Material → V0.6 → IQ 0.2 경계까지 도달했습니다.
- R5 crystal만 IQ 0.2 `passed`와 exact source freeze를 게시했습니다. plastic, rust, wood, laser는
  required boundary F-score hard gate에서 `blocked`로 닫혔으며 review bundle로 재분류하지 않았습니다.
- R5 run의 adapter route/receipt는 5/5 모두 terminal이며 orphan route는 0건입니다.
- canonical corruption, 추가 사용자 결정, technical user approval request는 모두 0건입니다.
- R5 crystal delivery와 후속 wood delivery에서 각각 policy parser, package-local temporary ACL,
  clean-import UV serializer tolerance 결함을 재현하고 수정했습니다. 실패 이력은 그대로 보존했습니다.
- tuned R8 wood는 IQ pass/source freeze 이후 portable GLTF package, round-trip clean import, geometry
  survival을 모두 통과해 `production_ready=true`로 완료했습니다.
- signage/decal 및 dependency-rich texture/bake Material Closure는 현재 저장소에 새 canary로 사용할
  isolated immutable reference와 별도 권한·bake contract가 없어 실행하지 않았습니다.

R5는 실제 depth를 추가했지만 plastic/rust/laser와 최초 wood 후보는 contour hard gate를 통과하지
못했고, crystal은 delivery technical terminal로 끝났습니다. R8 wood의 production-ready 결과도 단일
reference·단일 format의 local evidence일 뿐입니다. 따라서 이번 결과는 delivery 기계 경계의 한 사례를
검증했지만 human quality acceptance나 profile activation 근거를 충족하지 않습니다.

## 2. 캠페인 범위

| 번호 | 재질/구조 범주 | immutable reference | SHA-256 | 최종 job / run / session |
|---:|---|---|---|---|
| 1 | weathered plastic | `workspaces/collectible_plastic_01/input/reference.png` | `ef1a06d053cbf414b986d5488dd8d5c4b4a61b9387489fb957816feec167cc52` | `aq_campaign_r3_01_plastic_shard` / `aq-campaign-r3-01-plastic-shard` / `aqv2-20260829t090210855483z-66d52b1d` |
| 2 | rusted metal | `workspaces/collectible_scrap_01/input/reference.png` | `5a125a3d8a0b96f6bcfb7ec1438e59cdbff82fd02358f459126838e025386576` | `aq_campaign_r1_02_rusted_scrap` / `aq-campaign-r1-02-rusted-scrap` / `aqv2-20260829t085431079903z-684594b0` |
| 3 | weathered wood | `workspaces/collectible_wood_02/input/reference.png` | `b1312fedd5c1cfab2c7a1c522157442b1a3c543398612e8d02d4672af7df8fc7` | `aq_campaign_r1_03_weathered_wood_beam` / `aq-campaign-r1-03-weathered-wood-beam` / `aqv2-20260829t085434420780z-1e3884cb` |
| 4 | crystal / emission | `workspaces/item_crystalgun_full_0/input/reference.png` | `dd2ecc1bfeb403595d8a4f77875980fd7cad7d29582d661a248fa2d639c846bf` | `aq_campaign_r1_04_crystal_emitter` / `aq-campaign-r1-04-crystal-emitter` / `aqv2-20260829t085437029564z-18af6492` |
| 5 | shared material / sci-fi hard surface | `workspaces/item_lasergun_normal/input/reference.png` | `1a4a707f7aaa5c7c333ed473eed72ab5de43583bb69fad27552e5eea117c6420` | `aq_campaign_r1_05_shared_material_laser` / `aq-campaign-r1-05-shared-material-laser` / `aqv2-20260829t085439642819z-f8cd64cc` |

동일 immutable reference를 사용한 structural re-entry R2 run은 다음과 같습니다.

| 번호 | R2 job / run | AQ v2 session |
|---:|---|---|
| 1 | `aq_reentry_r2_01_plastic_shard` / `aq-reentry-r2-01-plastic-shard` | `aqv2-20260829t122546280965z-afd1859c` |
| 2 | `aq_reentry_r2_02_rusted_scrap` / `aq-reentry-r2-02-rusted-scrap` | `aqv2-20260829t123742304344z-583784e4` |
| 3 | `aq_reentry_r2_03_weathered_wood_beam` / `aq-reentry-r2-03-weathered-wood-beam` | `aqv2-20260829t123748162495z-1fda247d` |
| 4 | `aq_reentry_r2_04_crystal_emitter` / `aq-reentry-r2-04-crystal-emitter` | `aqv2-20260829t123754494727z-647ea29c` |
| 5 | `aq_reentry_r2_05_shared_material_laser` / `aq-reentry-r2-05-shared-material-laser` | `aqv2-20260829t123759957278z-118c0074` |

같은 reference를 depth-bearing candidate로 재저작한 R5 run은 다음과 같습니다.

| 번호 | R5 job / run | AQ v2 session |
|---:|---|---|
| 1 | `aq_volumetric_r5_01_plastic_shard` / `aq-volumetric-r5-01-plastic-shard` | `aqv2-20260829t171709314110z-8ab5bcb7` |
| 2 | `aq_volumetric_r5_02_rusted_scrap` / `aq-volumetric-r5-02-rusted-scrap` | `aqv2-20260829t171714597269z-68c2aa60` |
| 3 | `aq_volumetric_r5_03_weathered_wood_beam` / `aq-volumetric-r5-03-weathered-wood-beam` | `aqv2-20260829t171719658594z-b7f23bfb` |
| 4 | `aq_volumetric_r5_04_crystal_emitter` / `aq-volumetric-r5-04-crystal-emitter` | `aqv2-20260829t171724926511z-c472b9b4` |
| 5 | `aq_volumetric_r5_05_shared_material_laser` / `aq-volumetric-r5-05-shared-material-laser` | `aqv2-20260829t171730262956z-0b6c300b` |

wood reference는 delivery 결함을 고친 fresh run으로만 재검증했습니다. 최종 성공 run은
`aq_volumetric_r8_03_weathered_wood_beam` / `aq-volumetric-r8-03-weathered-wood-beam` /
`aqv2-20260829t175401549148z-ae141b90`입니다. R6/R7 실패 evidence는 수정하거나 성공으로
소급 분류하지 않았습니다.

이번 corpus는 서로 다른 reference 5개라는 요청을 만족합니다. 다만 기존 activation benchmark에서
예시로 든 signage/decal 범주 대신 rusted metal을 사용했으므로, signage/decal coverage는 별도
후속 자산으로 남습니다. `underwater_ocean-department_test`의 원본에는 간판이 보이지만 건물 전체
reference이고 기존 plan도 sign mass만 범위로 두었으므로, 그 파일을 임의 crop하거나 decal 승인으로
확대 해석하지 않았습니다.

## 3. 최초 캠페인 단계 결과

| 단계 | 결과 | 근거 의미 |
|---|---:|---|
| Reference analysis/camera | 5/5 | 원본 input 불변, OpenCV 진단과 카메라 가정 생성 |
| Geometry controller adoption | 5/5 | exact assignment/input/profile/output 결속 |
| Geometry Blender validation/promotion | 5/5 | SceneSpec V03 구조 materialization, 실제 Blender build/inspect/validate, host-only canonical promotion |
| Material controller adoption | 5/5 | stable material ID와 exact graph provenance 결속 |
| Material validation/promotion | 5/5 | graph compile, neutral/reference preview manifest, 실제 Blender rebuild/validate, host-only canonical promotion |
| V0.6 fixed-camera QA | 5/5 | 정확히 7개 pass와 direct score 생성 |
| IQ 0.2 | `blocked` 5/5 | reference contour required hard gate 실패 |
| Quality source freeze | 0/5 | IQ pass 없음 |
| Review bundle | 0/5 | 결과가 `needs_revision`/`unscorable`이 아니라 required gate `blocked`였음 |
| Portable delivery | 0/5 | quality source freeze가 없어 의도적으로 미실행 |

Material 후보는 모두 constant/local-only PBR이므로 full texture dependency closure나 bake를 검증한
캠페인은 아닙니다. 이번 5/5 material 통과를 dependency-rich Material Closure 전체 활성화 근거로
확대 해석하지 않습니다.

### 3.1 Structural re-entry R2 단계 결과

| 단계 | 결과 | 근거 의미 |
|---|---:|---|
| Reference analysis/camera | 5/5 | 원본 input 불변, 동일 reference hash와 fixed camera 유지 |
| Geometry controller adoption | 5/5 | mask contour 기반 SceneSpec V03를 isolated output에서만 작성 |
| Geometry Blender validation/promotion | 5/5 | `multi_loop_extrude`, geometry intent survival `exact`, host-only promotion |
| Material validation/promotion | 5/5 | constant/local-only graph compile와 실제 Blender rebuild 통과 |
| V0.6 fixed-camera QA | 5/5 | exact 7-pass, direct score `0.959022`~`0.991305` |
| IQ 0.2 | pass 4 / blocked 1 | rust boundary F-score만 required `0.8` 미달 |
| Quality source freeze | 4/5 | plastic, wood, crystal, laser의 exact canonical source freeze |
| Adapter route/receipt closure | 5/5 | routes와 receipts 동일, pending route 0 |
| Delivery | 0/5 | wood canary가 승인된 ShaderRecipe 부재로 fail-closed 종료; package/clean import 없음 |
| Human quality disposition | 5/5 | exact R2 beauty hash에만 결속된 `needs_revision`; IQ 상태와 분리 |

이 R2 캠페인도 texture/bake 의존성을 추가하지 않았습니다. 또한 얇은 extrusion은 contour와 camera
framing 회귀를 검증하는 bounded 구조 후보이며 volumetric reconstruction 증거가 아닙니다.

### 3.2 Volumetric R5와 wood R8 단계 결과

| 단계 | R5 결과 | 근거 의미 |
|---|---:|---|
| Reference analysis/camera | 5/5 | 동일 immutable input hash와 fixed camera 유지 |
| Geometry controller/Blender promotion | 5/5 | depth-bearing SceneSpec V03 후보, 실제 Blender build/inspect/validate, host-only promotion |
| Material controller/Blender promotion | 5/5 | exact ShaderRecipe를 포함한 local-only graph compile/rebuild/promotion |
| V0.6 fixed-camera QA | 5/5 | exact 7-pass와 direct score 생성 |
| IQ 0.2 | pass 1 / blocked 4 | crystal만 pass; 나머지는 required boundary F-score hard gate 실패 |
| Quality source freeze | 1/5 | crystal exact source freeze만 게시 |
| Adapter route/receipt terminal | 5/5 | pending route와 orphan receipt 0 |
| R5 delivery | technical terminal 1 / 미실행 4 | crystal packaging policy parser failure; blocked 4개는 delivery 미실행 |
| R5 review bundle | 0/5 | required hard-gate `blocked`를 usable review terminal로 재분류하지 않음 |
| 새 beauty human disposition | 0/5 | R2 판정을 재사용하지 않음 |

후속 wood R6/R7/R8은 같은 wood reference를 fresh job으로 다시 실행했습니다. R8은 IQ/source freeze,
portable GLTF package, clean import와 geometry survival을 통과했으며 production-ready terminal로
완료했습니다. 이 결과는 R5의 다른 네 자산이나 다른 전달 format으로 일반화하지 않습니다.

dependency-rich Material Closure는 실행 전 입력 감사를 수행했습니다. 저장소의 기존 texture manifest와
channel 파일은 hash/color-space/UV binding이 유효한 사례가 있지만 새 AQ canary에 이전할 별도 권한과
bake manifest/receipt가 없습니다. `item_crystalgun_full_0`의 보존된 closure는 dependency closure 뒤
shared localized material identity preflight에서 실패했고, 이를 재개하려면 별도의 exact material-identity
split 승인이 필요합니다. 따라서 이번 목표에서 승인이나 bake evidence를 합성하지 않고 미실행 경계로
남겼습니다.

## 4. 최초 캠페인 품질 측정값

| job | V0.6 direct score | IQ boundary F-score | normalized chamfer | IQ outcome |
|---|---:|---:|---:|---|
| `aq_campaign_r3_01_plastic_shard` | `0.400147` | `0.029478` | `0.089824` | `blocked` |
| `aq_campaign_r1_02_rusted_scrap` | `0.511312` | `0.028744` | `0.059653` | `blocked` |
| `aq_campaign_r1_03_weathered_wood_beam` | `0.416650` | `0.017883` | `0.087898` | `blocked` |
| `aq_campaign_r1_04_crystal_emitter` | `0.547703` | `0.076980` | `0.062047` | `blocked` |
| `aq_campaign_r1_05_shared_material_laser` | `0.463162` | `0.086636` | `0.073018` | `blocked` |

정책 기준은 minimum boundary F-score `0.8`, maximum normalized chamfer `0.05`입니다. 현재 후보는
reference의 실제 외형을 충분히 재현한 production asset이 아니라 orchestration과 안전 경계를
검증하기 위한 bounded structural 후보입니다. 낮은 값을 임의로 pass나 `needs_revision`으로
재분류하지 않았습니다.

### 4.1 Structural re-entry R2 품질 측정값

| job | V0.6 direct | silhouette IoU | IQ boundary F | normalized chamfer | IQ outcome |
|---|---:|---:|---:|---:|---|
| `aq_reentry_r2_01_plastic_shard` | `0.976217` | `0.964672` | `0.910625` | `0.003571` | `passed` |
| `aq_reentry_r2_02_rusted_scrap` | `0.959022` | `0.939552` | `0.642257` | `0.005536` | `blocked` |
| `aq_reentry_r2_03_weathered_wood_beam` | `0.990368` | `0.986523` | `1.000000` | `0.001322` | `passed` |
| `aq_reentry_r2_04_crystal_emitter` | `0.959877` | `0.942845` | `0.991660` | `0.001571` | `passed` |
| `aq_reentry_r2_05_shared_material_laser` | `0.991305` | `0.987360` | `1.000000` | `0.000918` | `passed` |

contour 개선은 실측됐지만 beauty 확인 결과 다섯 후보 모두 얇은 silhouette proxy입니다. 특히 crystal과
laser의 internal assembly, plastic/rust/wood의 깊이와 표면 세부가 생략됐으므로 이 수치를 production
asset fidelity로 해석하지 않습니다.

### 4.2 Volumetric R5와 tuned wood 품질 측정값

| job | V0.6 direct | silhouette IoU | IQ boundary F | normalized chamfer | IQ outcome |
|---|---:|---:|---:|---:|---|
| `aq_volumetric_r5_01_plastic_shard` | `0.959290` | `0.940349` | `0.250998` | `0.006213` | `blocked` |
| `aq_volumetric_r5_02_rusted_scrap` | `0.913537` | `0.878723` | `0.079899` | `0.011871` | `blocked` |
| `aq_volumetric_r5_03_weathered_wood_beam` | `0.929944` | `0.907345` | `0.094276` | `0.009589` | `blocked` |
| `aq_volumetric_r5_04_crystal_emitter` | `0.948972` | `0.922067` | `0.925395` | `0.002210` | `passed` |
| `aq_volumetric_r5_05_shared_material_laser` | `0.957222` | `0.941062` | `0.697056` | `0.004223` | `blocked` |
| `aq_volumetric_r8_03_weathered_wood_beam` | `0.991963` | `0.990230` | `1.000000` | `0.000947` | `passed` |

R8 wood는 profile scale `(0.95238, 1.0, 0.94864)`과 depth `0.92 m`인 새 후보이며 R5 wood를
역사 안에서 고치지 않았습니다. IQ threshold를 낮추거나 required finding을 우회하지 않고 fresh
candidate에서 수렴했습니다.

## 5. 최초 캠페인 집계 KPI

| KPI | 결과 | activation 기준 판정 |
|---|---:|---|
| 서로 다른 immutable reference | 5 | 충족 |
| initial user request | 5 total, 자산별 1 | 충족 |
| additional user decisions | 0 | 충족 |
| technical user approval requests | 0 | 충족 |
| controller invocations | 10 | 정보 |
| canonical promotions | 10 | 정보 |
| recorded Blender builds | 23 | 정보 |
| IQ evaluations | 5 | 정보 |
| canonical corruption | 0 | 충족 |
| AQ state/quality terminal | 5/5 | fail-closed 관점 충족 |
| public One-Prompt status terminal | 4/5 | 미충족 |
| skill adapter status terminal | 4/5 | 미충족 |
| production 또는 review-required terminal | 0/5 | 미충족 |
| quality-approved source freeze | 0/5 | 미충족 |
| portable delivery | 0/5 | 미검증 |
| 별도 human quality disposition | 0/5 | 미완료 |

`technical user approval requests=0`은 자동 실행이 매끄러웠다는 뜻이 아닙니다. 아래 기술 복구에는
현재 Codex task의 operator intervention이 필요했으므로 별도 실패로 기록합니다.

### 5.1 Structural re-entry R2 집계 KPI

| KPI | 결과 | 현재 판정 |
|---|---:|---|
| 서로 다른 immutable reference | 5 | 충족 |
| initial user request | 자산별 1 | 충족 |
| additional user decisions | 0 | 충족 |
| technical user approval requests | 0 | 충족 |
| controller invocations | 10 | 예상 범위 |
| canonical promotions | 10 | 예상 범위 |
| recorded Blender builds | 20 | 예상 범위 |
| IQ evaluations | 5 | 충족 |
| IQ passed / source freeze | 4/5 | delivery canary 선행조건 충족 |
| IQ blocked safe terminal | 1/5 | fail-closed |
| canonical corruption | 0 | 충족 |
| adapter route/receipt closure | 5/5 | 충족 |
| delivery-ready base state | 4/5 | `quality_approved / plan_delivery` |
| production/review terminal | 0/5 | delivery 미실행으로 미충족 |
| portable delivery/clean import | 0/5 | wood canary가 안전 실패; fresh volumetric wood에서 재검증 필요 |
| 별도 human quality disposition | 5/5 | R2 exact beauty 5개 모두 `needs_revision` |

policy decision은 applied 9건과 복구용 `technical_failed` 1건입니다. 이 receipt는 user approval이
아니며, plastic의 첫 잘못된 freeze submission이 남긴 single-use authorization을 canonical 변경 없이
회수한 증거입니다.

### 5.2 Volumetric R5와 wood R8 집계 KPI

| KPI | 결과 | 현재 판정 |
|---|---:|---|
| 서로 다른 immutable reference | 5 | 충족 |
| initial user request | 자산별 1 | 충족 |
| additional user decisions | 0 | 충족 |
| technical user approval requests | 0 | 충족 |
| Geometry/Material promotion | 5/5 | 충족 |
| V0.6 / IQ evaluation | 5/5 | 충족 |
| IQ passed / source freeze | 1/5 | 미충족 |
| IQ blocked safe terminal | 4/5 | fail-closed, usable review terminal은 아님 |
| adapter route/receipt terminal | 5/5 | 충족 |
| canonical corruption | 0 | 충족 |
| production-ready terminal | same-reference replacement 포함 1/5 | wood R8만 충족 |
| portable GLTF package/clean import | wood 1/1 | 단일 canary 통과 |
| package absolute paths / missing dependencies | `0 / 0` | wood R8 충족 |
| 새 beauty exact human disposition | 0/5 | 미완료; R2 판정 재사용 금지 |
| isolated signage/decal coverage | 0/1 | 필수 입력 없음 |
| authorized dependency-rich bake closure | 0/1 | 별도 권한·bake contract 없음 |

따라서 one-prompt safety/terminal consistency와 단일 GLTF delivery 기계 경계는 전진했지만, 다섯
reference의 quality terminal 및 사람 판정과 빠진 material coverage는 activation 기준에 미달합니다.

## 6. 발견된 통합 결함과 보존된 실패 증거

1. Reference receipt 이후 V0.9 production step을 완료하면 workflow state SHA가 바뀌어 AQ reference
   receipt가 stale이 됩니다. assignment 발행만으로는 SHA가 바뀌지 않으므로 현재 성공 경로는
   “reference → production assignment 발행 → AQ controller”의 민감한 순서를 요구합니다.
2. desktop controller가 waiting 상태인 동안 skill adapter가 route/snapshot evidence를 먼저 쓰면
   protected job inventory가 변경됐다고 판정되어 controller adoption이 거부됩니다.
3. Geometry controller request가 현재 `analysis/modeling_plan.json`을 immutable input으로 결속하지
   않으면 candidate validator가 거부합니다. 현재는 operator가 baseline을 먼저 authored 상태로
   만들고 request에 수동 포함했습니다.
4. skill adapter 실행이 underlying validator 예외로 끝나면 route 파일만 남고 receipt sequence가
   전진하지 않을 수 있습니다. 같은 run 재개는 create-once route 충돌로 실패합니다. plastic의
   `skill_runs/aq-campaign-r3-01-plastic-shard/routes/0005.json`이 이 증거입니다. AQ state와
   quality terminal은 `blocked`지만 public One-Prompt status와 adapter는 `running`으로 남았습니다.
5. R5 crystal delivery는 Approval Envelope 0.3의 `AQV2RoutinePolicyAuthorization`을 legacy AQ 0.1
   `PolicyAuthorization`으로만 해석해 packaging이 technical failure로 닫혔습니다. packaging service는
   이제 두 schema를 구분하고 exact canonical/snapshot bytes, gate, target, timestamp를 검증하며 0.3
   authorization을 user approval로 변환하지 않습니다.
6. R6 wood GLTF export는 Blender가 package-local temporary child를 Python 기본 `0o700` mode로 만들 때
   Windows inherited ACL을 잃어 `WinError 5`로 실패했습니다. exporter는 Windows에서 해당 package-local
   temp child의 그 exact mode만 parent ACL 상속 mode로 바꾸며 다른 경로나 mode는 건드리지 않습니다.
7. R7 wood clean import는 exporter의 미세한 UV float serialization 차이 때문에 geometry survival이
   실패했습니다. delivery inspector는 triangle corner의 world-position/UV 결속을 유지한 채 UV만
   `1e-5`로 양자화합니다. 실제 `2e-5` UV 이동은 여전히 다른 fingerprint로 검출됩니다.
8. Windows Python 3.14가 pytest와 `TemporaryDirectory`의 `0o700` 생성 mode를 restrictive ACL로
   해석해 공식 AQ gate가 `WinError 5`로 중단됐습니다. gate runner는 명시된 `--basetemp`와 그 형제
   process-temp 안에서만 inherited ACL mode를 사용하고 종료 시 `os.mkdir`, `TEMP`, `TMP`,
   `tempfile.tempdir`를 모두 복원합니다. V0.7/V0.8/V0.9/AQ Windows gate가 같은 실행기를 사용합니다.

초기 실패 job, 최초 캠페인의 plastic R1/R2 실패 job, 이번 re-entry의 r1 순서 오류 job과 잘못된
첫 quality submission, R5 crystal과 R6/R7 wood delivery 실패는 immutable failure history로
보존했습니다. 이를 삭제하거나 성공으로 소급 재분류하지 않았습니다.

R2 실행 전후 보완 결과:

- skill route는 exact source snapshot으로 재유도한 뒤 receipt 없는 단일 route만 회수하며, underlying
  예외도 failed receipt로 닫습니다. public One-Prompt terminal과 adapter terminal도 재동기화합니다.
- `skill_runs/`는 host-owned routing projection으로 ControllerExecutor protected controller inventory에서
  분리했습니다. 실제 controller request/output과 canonical source 보호 범위는 유지됩니다.
- reference scaffold를 바꾸기 전에 V0.9 immutable assignment를 먼저 발행하고, authored ModelingPlan은
  AQ controller의 isolated output으로만 게시하도록 캠페인 경계를 수정했습니다.
- ordinary policy action 예외는 아직 사용되지 않은 authorization을 `technical_failed` decision receipt로
  닫고, crash로 남은 exact authorization은 동일 target이면 재사용하고 다른 target이면 먼저 안전 종결합니다.
- focused 회귀는 adapter/controller `62 passed, 2 skipped`, Approval Envelope/policy recovery
  `25 passed`이고, 관련 supervisor/candidate/material 묶음 최종 결과는 `120 passed, 2 skipped`입니다.
  실제 R2 5개에서도 pending adapter route 0을 재확인했습니다.
- 현재 source 변경을 포함한 전체 회귀는 `2010 passed, 63 skipped`, 변경 경로 focused 회귀는
  `117 passed, 1 skipped`, 공식 AQ focused는 `925 passed, 26 skipped`,
  실제 Blender smoke `45 passed, 1 skipped`입니다. 최초 smoke의 `signage_decal`/`emissive` 2건은
  265자 pytest 경로에서 manifest lookup이 실패했으나 저장소 루트의 짧은 basetemp로 정확히 재실행해
  `2 passed`를 확인했습니다. 이에 PowerShell AQ gate의 기본 pytest root도 Windows MAX_PATH 아래의
  `/.b/`로 줄였습니다.
- 실제 Blender benchmark는 AQ 0.1 `8/8`, AQ 0.2 `10/10`, 실패 0입니다. V0.9 isolated gate도
  Blender 5.0.1에서 GLB package manifest의 absolute path 0, missing dependency 0, clean import `passed`,
  valid handoff `1/1`, canonical unchanged를 확인했습니다.
- R5의 exact policy technical failure도 base AQ state를 append-only `failed` terminal로 닫고
  authorization decision을 `technical_failed`로 소진하는 것을 실제 evidence로 재확인했습니다.
- UV tolerance 수정 뒤 실제 Blender 5.0.1 GLB/FBX delivery geometry smoke는 `1 passed`입니다.

## 7. Exact human disposition과 delivery canary

사용자는 2026-08-30 KST에 아래 문장으로 제시된 R2 beauty SHA-256 5개 전부의
`needs_revision` 기록을 명시적으로 승인했습니다.

```text
제시된 R2 beauty SHA-256 5개 모두를 `needs_revision`으로 기록하는 것을 승인합니다.
```

- 기록 시각: `2026-08-29T16:32:52.0183717Z`
- 사용자 문장 UTF-8 SHA-256: `7c50ecd8d39040e9699a736ff95f96baeea6b36b882b6955a8d2b756c25e0725`
- 권한 범위: 아래 exact R2 beauty 5개만 해당
- 비권한 범위: future volumetric/R3 beauty, IQ outcome 변경, source freeze 승인, delivery/package 승인,
  Approval Envelope authorization, Activation acceptance

| R2 job | exact beauty evidence | SHA-256 | human disposition | 근거 |
|---|---|---|---|---|
| `aq_reentry_r2_01_plastic_shard` | `qa/runs/aq-reentry-r2-01-v06/passes/beauty.png` | `3dd29ba08f3a4f6c818bf3a33e3fd846c9370be07b4fd1a749c6e601c3fa1959` | `needs_revision` | 실제 전후 깊이와 주요 표면 마모 부족 |
| `aq_reentry_r2_02_rusted_scrap` | `qa/runs/aq-reentry-r2-02-v06/passes/beauty.png` | `71f07dd9f5feac4c72b0c840485ee03e717eef9b756161b46765745fecefc19a` | `needs_revision` | 금속 두께·조립·부식 구조 부족, IQ boundary F hard gate 실패 |
| `aq_reentry_r2_03_weathered_wood_beam` | `qa/runs/aq-reentry-r2-03-v06/passes/beauty.png` | `908e3225277e0919358c63d0321f08bd72f17b9e0202aa1fd4ab64c09c460d5a` | `needs_revision` | 실제 beam 체적, 절단면과 균열 구조 부족 |
| `aq_reentry_r2_04_crystal_emitter` | `qa/runs/aq-reentry-r2-04-v06/passes/beauty.png` | `f16dbad986c49c8b3b4074a192404b22f339d7b0b4bbac5c6b72c7e6a03bf0bb` | `needs_revision` | housing/core/emission 내부 조립과 깊이 관계 부족 |
| `aq_reentry_r2_05_shared_material_laser` | `qa/runs/aq-reentry-r2-05-v06/passes/beauty.png` | `a70caf0b6090b3ae87379a490bee4e46d8189ad67ca4dadc8a8ac9131ecd5325` | `needs_revision` | receiver/barrel/grip/energy 조립과 실제 깊이 부족 |

각 경로는 해당 `workspaces/<job>/` 아래의 job-relative 경로입니다. 같은 렌더를 가리키는
`renders/passes/beauty.png`의 SHA-256도 각각 일치함을 재검증했습니다. 이 사람 판정은 machine IQ
`passed` 4건과 `blocked` 1건을 변경하거나 소급 재분류하지 않습니다.

wood delivery canary는 다음 exact R2 evidence에서 실행했습니다.

- job/run/session: `aq_reentry_r2_03_weathered_wood_beam` /
  `aq-reentry-r2-03-weathered-wood-beam` / `aqv2-20260829t123748162495z-1fda247d`
- source freeze SHA-256: `c9d7f71b766d52fbb62240a5b336522713e709f88374859222a7953d7018c6c2`
- 결과: `RuntimeError: mat.wood_beam.weathered has no approved ShaderRecipe`
- technical failure SHA-256: `b30ae8ac0a9e5482c7f98a0c5650b1c40356799efe0cd5408f8e8603d41a1ada`
- delivery terminal SHA-256: `9a2f9e1a8edf6989ada68faa7f177ad45fc5122b82c67d99295592fd97cb085c`
- package manifest/round-trip: 생성 안 됨
- 안전성 결과: canonical 변경 0, 추가 사용자 결정 0, technical approval request 0,
  adapter/base/public terminal 정합

이는 adapter/recovery의 fail-closed 동작 증거이지 portable delivery 성공 증거가 아닙니다. 기존 R2
source freeze나 실패 이력을 수정하지 않고, 승인된 ShaderRecipe를 material dependency로 포함하는 새
volumetric wood job에서 delivery를 먼저 재검증해야 합니다.

### 7.1 R5/R8 beauty disposition 경계

현재 비교할 새 candidate set은 R5 plastic/rust/crystal/laser와 최종 R8 wood입니다. 다음 exact beauty는
아직 사람 판정이 없으며 R2의 `needs_revision`을 상속하지 않습니다.

| 현재 candidate | exact beauty SHA-256 | human disposition |
|---|---|---|
| `aq_volumetric_r5_01_plastic_shard` | `dfc96c4403079a205f2cb921733365a30b8ba88b5b07d985aac6ccc59570a704` | 미기록 |
| `aq_volumetric_r5_02_rusted_scrap` | `018cc6309406927479b449e137300efd196cb18d37619b5e284683600d3fdc10` | 미기록 |
| `aq_volumetric_r8_03_weathered_wood_beam` | `bcfbdf042de37fa9e537587aff4eb57ee4dc9537c8ded8143ffaec3bed5351b9` | 미기록 |
| `aq_volumetric_r5_04_crystal_emitter` | `5d580356ae924ba3d9e96cb236c05148390ee2defeff5c8d9c3b2d534bbe4cf4` | 미기록 |
| `aq_volumetric_r5_05_shared_material_laser` | `df72918543a2d59cf07df5aaf1081f3738a104aae191b7ea22a2639d159991e5` | 미기록 |

### 7.2 Volumetric delivery failure chain과 R8 성공

| run | 결과 | 보존된 경계 |
|---|---|---|
| R5 crystal | IQ/source freeze 통과 뒤 technical failure | Approval Envelope 0.3 packaging parser failure; package acceptance 없음 |
| R6 wood | IQ/source freeze 통과 뒤 technical failure | package-local GLTF temp ACL `WinError 5` |
| R7 wood | package/round-trip 생성 뒤 technical failure | clean-import UV fingerprint serializer sensitivity |
| R8 wood | `completed`, `production_ready=true` | fresh source freeze와 package/round-trip/survival evidence |

R8 wood authoritative hashes:

- source freeze: `8f774e89fd6ba0c2b9cd3be6b385f3be8ae9a70e31669fa96588033b0d87f17d`
- delivery terminal: `b3e7848b3bb4e771a7314d4cbf9e4d76b5429bc0b26e216352c1d0294700042e`
- One-Prompt terminal: `bfbaeaf48a84280597abc9403d2afd1c38de0240144036836ff156b99bc0df4b`
- immutable package manifest: `e33cf92952860bc86ffc214b4798b038e29fbd3eaf83eb2d60c35ce9008f677e`
- round-trip validation: `8162765d5fa66a8f541665f1cfef68c5301a2b8a4f2ab97ff1180fe803fe53d7`
- optimized-to-clean-import survival: `e91e5837d34b38191fb1073a432a1772e4ff6ee1a52c0fb52157c93499383525`

package는 26개 파일, absolute path 0, missing dependency 0이며 독립 재해시 26/26 일치,
canonical unchanged입니다. 이는 local engine-neutral GLTF evidence이며 destination project write나
Unity/Unreal runtime parity 증거가 아닙니다.

## 8. Activation 결정과 다음 실행 조건

현재 `autonomous_static_prop_v2`와 `aq-one-prompt-orchestrator`는 계속
`disabled_experimental`이어야 합니다.

현재 판단은 다음과 같습니다.

1. **단일 wood delivery canary는 통과:** R8은 exact ShaderRecipe, source freeze, immutable package manifest,
   clean import와 geometry survival을 모두 만족했습니다. R2/R6/R7 실패는 별도 history로 유지합니다.
2. **동일 5개 reference volumetric quality는 미달:** R5 IQ pass는 1/5이고 required hard-gate block 4/5입니다.
   R8 wood를 같은 reference의 fresh replacement로 포함해도 production-ready terminal은 1/5입니다.
3. **새 human disposition은 미완료:** R2 exact beauty 5개는 모두 `needs_revision`이지만 현재 candidate
   set의 exact beauty 5개에는 disposition이 없습니다.
4. **빠진 coverage는 입력 경계에서 정지:** isolated immutable signage/decal reference와 별도 권한이
   부여된 bake-bound texture dependency가 없어 signage/decal 0/1, dependency-rich closure 0/1입니다.
   기존 output이나 approval을 다른 job으로 복사하지 않았습니다.
5. **Activation 판정은 계속 NO-GO:** 위 품질·사람 판정·coverage 외에도 profile status가 명시하는
   supporting-client closed loop, controller sandbox attestation, destination runtime parity blocker가
   남아 있습니다. 단일 local GLTF canary는 이 blocker를 해제하지 않습니다.

다음 실행 순서는 다음과 같습니다.

1. recovery 수정 checkpoint commit `e375d84386af68544bac043c3b0e875b693e22b4`를 유지합니다.
2. 현재 source/tests/docs를 전체 gate로 검증하고 clean commit에 고정합니다.
3. 그 clean commit에서 새 ActivationSourceManifest/Baseline/Index를 생성하되, 미충족 항목을
   누락하거나 pass로 바꾸지 않고 NO-GO readiness를 게시합니다.
4. 현재 candidate set의 exact beauty 5개에 대해 별도 human disposition을 받습니다.
5. plastic/rust/laser contour를 fresh candidate에서 수렴시키고 crystal delivery를 fresh run으로 재검증합니다.
6. 사용자가 제공한 isolated immutable signage/decal reference와 별도 authorization/bake contract가 있는
   texture dependency로 각각 1개 canary를 수행합니다.
7. supporting-client closed loop, controller sandbox attestation, destination runtime parity까지 exact
   evidence가 갖춰진 뒤에만 human Activation acceptance와 profile enablement를 다시 검토합니다.

## 9. 주요 authoritative evidence

- 각 job의 base state: `production/autonomy_v2/<session>/states/0008.json`
- 각 job의 quality terminal: `production/autonomy_v2/<session>/quality_terminal.json`
- 실제 V0.6 pass/report: `qa/runs/<campaign-v06-run>/`
- 최초 host-recomputable IQ 제출: `production/autonomy_v2/<session>/quality_evidence/<campaign-v06-run>-r1/`
- R2 host-recomputable IQ 제출: `production/autonomy_v2/<session>/quality_evidence/<reentry-v06-run>-iq02/`
  (plastic 최종 exact retry는 `-iq03`)
- R2 source freeze: `production/autonomy_v2/<session>/source_freeze.json` (pass 4개만 존재)
- R5 host-recomputable IQ 제출: `production/autonomy_v2/<session>/quality_evidence/<volumetric-v06-run>-iq02/`
- R5 source freeze: crystal session의 `production/autonomy_v2/<session>/source_freeze.json`
- R8 wood package manifest: `exports/packages/portable_gltf/delivery-plan-aqv2-20260829t175401549148z-ae141b90-gltf-package/package_manifest.json`
- R8 wood round-trip/survival: `optimization/runs/delivery-plan-aqv2-20260829t175401549148z-ae141b90-gltf-run/roundtrip/`와 같은 run의 `aq_v2/geometry/`
- adapter closure: `skill_runs/<run>/routes/`와 `skill_runs/<run>/receipts/`의 동일 sequence
- Geometry promotion receipt: `aq2/<validation-id>/receipt.json`
- Material promotion receipt: `production/autonomy_v2/<session>/material_phase/0006/promotion_receipt.json`

최초 캠페인 IQ report SHA-256:

- plastic: `4ee30cc0b936329f9659b4370d7e30decc62fee421d23339838e70e5b60cbc19`
- rusted metal: `1bef78759442eb6ffbe0b495505acc2d583b3654cb54ed1108affe7e7b8b7c24`
- wood: `eacd00b97bac895c3d2c773e5ed25b47ac698ba6530af99e7c783b26ff0e0130`
- crystal/emission: `a7b46cc69d68517a483b6da664dc79142c7c1ce0cd4bf51edf6df42f05d89ae0`
- shared-material laser: `60a8a570bb1e3238c3331ee1a0e121b5ebee8c38843ece59fabd8191ee6908bf`

R2 IQ report SHA-256:

- plastic: `114f43e299c89bb86873f3ef6988fca571403403427514945fdf6a34eb1e0d05`
- rusted metal: `cd45fa0af307ecf8da990b3714531dff8d97c5a504d6334bb47e1a1b7b63da91`
- wood: `06d0a12c98b76af29c5016058edf59aa009e6bf8610f34dc877caaedd7641440`
- crystal/emission: `8f6ef6cf95c887939febe57d549a9fa985a7fc59efd72a0579d7774ec0d49dd3`
- shared-material laser: `873c7b5bfece6c2334e0f08f729775498ecb32ceeb7c556ee6356e2707d692e8`

R5 IQ report SHA-256:

- plastic: `908409048142c2c8afe3a850107744ecf6bb66dc776c6c9042e675b09b65f34e`
- rusted metal: `fec8dc6d45ad800d33a7d257ca1416935b8ca166c0a8cf5f730cab27eb3c7816`
- wood: `d38a001522c67c9a810984da58c94fbf298339621f8ff4b9957ec9c90186a7a7`
- crystal/emission: `863bb44bffc94da6af61d8e16e620240c117a42e424b3f1b5f4ab2763531ac75`
- shared-material laser: `25a29a2ab203c6ffd033fa9bf7b8df870a132bc36933b4ce5d654e96a1cfa9d2`

이 문서는 machine JSON을 대체하지 않습니다. 경로·SHA·state·receipt가 서로 다르면 machine JSON이
권위입니다.
