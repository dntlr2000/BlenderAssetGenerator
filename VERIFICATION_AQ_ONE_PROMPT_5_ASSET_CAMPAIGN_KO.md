# AQ One-Prompt 실제 reference 5개 실험 캠페인 검증 기록

## 1. 판정

2026-08-31 현재 기존 volumetric R5/R8 이후 Stage 9 준비 R1~R5B가 append-only로 추가되었습니다.
R4 exact beauty는 **`needs_revision` 5/5**, current clean baseline은
`activation-baseline-4de9c955ee1e3716a4b14b49`입니다. 첫 18-object R5 Laser는 고정 build budget을
초과해 safe technical terminal로 닫혔고, 이를 결속한 11-object R5B는 **V0.6/IQ/source freeze pass,
추가 사용자 결정 0, technical approval 0, canonical corruption 0, exact beauty `needs_revision` 1/1,
activation NO-GO**입니다. R3/R4의 `needs_revision`은 R5B beauty의 판정으로 재사용하지 않았습니다.
아래 2~9절은 R5/R8까지의 선행 검증 이력을, 10절은 R1~R4 경계를 보존하며, 최신 상태와 다음 순서는
11절이 소유합니다.

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

기존 결함 보강과 첫 clean activation snapshot은 다음과 같이 완료했습니다.

1. recovery 수정 checkpoint `e375d84386af68544bac043c3b0e875b693e22b4` 이후 adapter terminal/recovery,
   package parser, package-local temporary ACL, UV serializer 결함을 보강했습니다.
2. 동일 reference의 structural R2, volumetric R5, tuned wood R8 이력은 수정하지 않고 보존했습니다.
3. clean commit `da44e3e6bf985ad6e5673bce1ff01582252c7e53`에서 source manifest
   `activation-source-2f0c9ca37d46915cf9d42712`, baseline
   `activation-baseline-8e341815e74247cd3ca389da`, empty candidate index와 NO-GO readiness를
   게시했습니다. 이 snapshot은 candidate 부족과 blocker 8개를 숨기지 않습니다.

다음 bounded closure는 아래 순서를 고정합니다.

1. 로드맵과 이 검증 기록이 stale step 설명 대신 run-owned machine decision을 가리키도록 먼저 갱신하고,
   전체 gate를 통과한 최종 clean commit에서 새 ActivationSourceManifest/Baseline을 생성합니다.
2. 현재 candidate set의 exact beauty 5개에 대해 진단용 human disposition을 별도로 받습니다. R2 판정은
   재사용하지 않으며 이 판정은 수정 방향만 정합니다.
3. 새 baseline 이후 새로운 job 5개를 만듭니다. plastic/rust/laser는 V0.4 structural re-entry부터,
   wood는 R8 구조 재현부터, crystal은 fresh IQ/delivery까지 One-Prompt 예산 안에서 실행합니다.
4. 새 candidate beauty 5개에 대해 최종 human disposition을 다시 받고, exact artifact와 baseline에
   결합된 Eligibility/Registry/Index/Readiness 및 campaign decision을 append-only로 게시합니다.
5. 다섯 세션이 completed 또는 명시적 safe terminal이고 pending adapter/recovery가 없으며 미해결 local
   framework 결함이 없고, 최소 한 새 candidate가 IQ/source freeze와 portable delivery를 완료하면
   base activation NO-GO와 별개로 ImageGen overlay 9단계를 `disabled_experimental` 상태에서 시작할 수
   있습니다. 품질 `needs_revision`은 base eligibility에 포함하지 않지만 bounded experimental 진입을
   자동으로 막지는 않습니다.
6. isolated immutable signage/decal reference, 별도 authorization/bake contract가 있는 dependency-rich
   texture closure, supporting-client closed loop, controller sandbox attestation, destination runtime parity는
   exact evidence가 생기기 전까지 base activation blocker로 보존합니다.

캠페인 중 source/framework 결함이 발견되면 세션 이력을 고치지 않습니다. 수정 commit과 새 baseline을
생성한 뒤 영향받은 job을 새 ID로 다시 실행합니다. 캠페인 결과는 추적 문서에 소급 삽입하지 않고 정확한
run-owned `reports/activation_readiness/.../campaign_decision.json`에서 상태를 소유합니다.

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

## 10. 2026-08-31 Stage 9 준비 R1~R4와 현재 경계

기존 R5/R8 이후 새 clean baseline
`activation-baseline-83e2ce0614a263e622d790d9`에 결속해 Stage 9 준비 캠페인을 실행했습니다.
R1/R2는 첫 자산의 host failure 뒤 나머지를 취소하는 안전 terminal로 닫혔고, 이 실패 이력은
수정하지 않았습니다. R3는 다섯 beauty를 생성했으며 사용자가 그 exact hash 5개 모두를
`needs_revision`으로 승인했습니다. 그 disposition set은 R4의 revision authority로만 사용됐고
package 승인이나 profile activation 권한으로 확대하지 않았습니다.

R4 authoritative campaign evidence:

- campaign: `aq-stage9-prep-r4-material-identity-campaign`
- launch SHA-256: `c3ba0e39dbdbb2bd03a1fc3ef4f7c2b0009e2720e0f3eb3afb20400856dfc738`
- result SHA-256: `a63e436c7e8b9a42c9057f179eb6330e2ebfbf1a0f3d554c542345aa1e2354e3`
- human review request SHA-256: `37443f12078e8c2d152647115c3271cd7c4da30fa1ef0e04c524eb18d0ffb7d6`
- additional user decisions `0`, technical user approval requests `0`, destination writes `0`

| R4 asset | V0.6 direct | IQ boundary F | machine outcome | exact beauty SHA-256 | 현재 경계 |
|---|---:|---:|---|---|---|
| plastic | `0.971514` | `0.844297` | `passed` | `e3970d5bc7ab47b0950ab93cbb5a8d4bb4baaed1166e167e9250fccd00632640` | exact human disposition + V0.7 approval 미기록 |
| rust | `0.909899` | `0.671268` | `blocked` | `fb581cf0fa4302a360a1a50e0539c160684f6f97164de10ec82b336d33f04e47` | exact human disposition 미기록; delivery 없음 |
| wood | `0.944595` | `1.000000` | `passed` | `a22e5dd424a1f676091a7bb50dde09362ce88f8b54fb5def4049f5a021b8f71b` | exact human disposition + V0.7 approval 미기록 |
| crystal | `0.903000` | `0.829136` | `passed` | `0377a4a0abb9a5ad33f76e998bab961c804295ff36cd6458357bb3c03b2b8403` | exact human disposition + V0.7 approval 미기록 |
| laser | `0.969576` | `0.804149` | `passed` | `e16ad7cff3221b167e8e08e7045e4935fb0ffaeeef08f78741a6a9cb51d629f0` | exact human disposition + V0.7 approval 미기록 |

R4 machine pass는 contour/profile gate의 통과이지 production 시각 품질 acceptance가 아니다. 특히
wood V0.6 report에는 high direct-reference missing finding이 남아 있는데 기존 R4 IQ policy가 이를
contour 결과와 함께 필수 재계산하지 않아 F-score `1.0`만으로 source freeze가 발행됐다. 이 historical
R4 결과는 고쳐 쓰지 않는다. 신규 AQ plan에만 V0.6 high authoritative finding bridge를 요구하는
additive policy를 적용해 같은 생략을 fail-closed하게 만들며, old policy의 의미는 유지한다.

시각 검토상 다섯 R4 candidate 모두 production bar에는 아직 미달하지만, 이는 사용자 exact disposition을
대신하지 않는다. 반복 비용과 결함 분리를 위해 다음 실행은 다섯 자산 전체 R5가 아니라 Laser 단일
fresh canary로 제한한다. 순서는 다음과 같다.

1. 위 R4 exact beauty 5개의 human disposition을 기록한다. generic approval이나 R3 판정을 재사용하지 않는다.
2. V0.6 finding bridge와 bounded beveled-relief geometry를 전체 gate로 검증한 clean commit에서 새
   ActivationSourceManifest/Baseline을 만든다.
3. Laser만 새 job/run으로 실행해 passing outer contour를 유지하면서 receiver/body/grip/sight/muzzle의
   실제 depth와 chamfer를 검증한다. R4 canonical/history는 변경하지 않는다.
4. 새 Laser beauty에 exact `accepted` 또는 `needs_revision` disposition을 받는다. `needs_revision`이면
   같은 결함을 무기한 반복하지 않고 원인·개선량·retry budget을 재평가한다.
5. Laser가 exact `accepted`일 때만 별도 exact V0.7 plan approval을 받아 portable delivery canary를
   실행하고, 그 terminal evidence로 Activation Index/Readiness를 재평가한다.
6. Laser의 단일 폐루프가 통과한 뒤에만 plastic/rust/wood/crystal에 필요한 서로 다른 capability를
   정의하고 최종 5-reference 캠페인의 진입 조건을 확정한다.

따라서 10절 기록 시점에는 R4 사람 판정 전이어서 delivery나 activation을 진행할 권한이 없었습니다.
이 historical 경계는 고쳐 쓰지 않으며, 이후 exact disposition과 canary 상태는 11절이 이어서 소유합니다.
Stage 9 overlay와 AQ base activation은 계속 별도 결정이고 둘 다 `disabled_experimental`을 유지합니다.

## 11. R4 disposition, current baseline과 R5/R5B Laser canary

10절의 R4 사람 판정 경계는 이후 exact 사용자 문장으로 해소했습니다. 사용자는 review request
SHA-256 `37443f12078e8c2d152647115c3271cd7c4da30fa1ef0e04c524eb18d0ffb7d6`에 포함된
다섯 exact beauty를 모두 `needs_revision`으로 기록하고, 별도로 확인된 0바이트 임시 lock
`.tmp-validation/uv-4720c9a03c218abf.lock` 하나의 삭제만 승인했습니다.

- disposition set ID: `stage9-prep-disposition-set-7154466146a3f399e0bbd6f8`
- disposition set logical SHA-256:
  `7154466146a3f399e0bbd6f80e4098de145dcbd55ee32bfd662cc32a30deffa5`
- disposition set file SHA-256:
  `c6508e3f35084abac3ae6cba3cc758a7a8488d8c113fabe472f2dd6b53f9f65c`
- record count/disposition: `5` / `needs_revision`
- 기록 시각: `2026-08-31T06:26:46.673291Z`
- 권한 효과: R4 quality disposition만 생성; future beauty, V0.7 delivery, profile activation,
  destination write 권한은 생성하지 않음

승인된 lock 하나를 삭제한 뒤 source checkpoint는 commit
`6572b22d45dba610e3b69468bedf4e2b34c6296c`, tree
`c4e3ff480db0f5e52f1994471eca0572a4e2e774`, staged/unstaged/untracked source 0으로
재검증했습니다. 기존 NO-GO snapshot은 보존하고 다음 current baseline을 새로 게시했습니다.

- source manifest ID: `activation-source-26f37fa8e845482a5309e11e`
- source manifest file SHA-256:
  `000520bccb9839e186a642555e20434a83d5bbc250b61feb4c30bcac81b578fc`
- baseline ID: `activation-baseline-4de9c955ee1e3716a4b14b49`
- baseline logical SHA-256:
  `4de9c955ee1e3716a4b14b49bc35f41f2cfa46906343c24b8d997e3e0ebc237d`
- baseline file SHA-256:
  `c17f02daa1bc1d5d100ea77165d506f2d89bf23a45636a85ba58ac8c82971acb`
- validation receipts: `17`
- readiness: `validation_blocked`, candidate `0/5`, blocker `10`, profile `disabled_experimental`

### 11.1 실패한 R5 18-object canary

R5는 R4 Laser의 passing outer contour를 유지하면서 17개 convex panel을 beveled relief로 바꾸고,
primary concave shell 1개를 포함한 18-object candidate를 작성했습니다. 하지만 AQ v2 기본
`total_blender_builds=14`에서 geometry candidate는 object별 materialization 18회와 결합 candidate build
1회가 필요하고, 후속 material closure는 2회를 추가로 요구합니다. 따라서 이 구성은 최소 `21`회로
처음부터 고정 예산 안에서 완료 불가능했습니다.

host는 candidate 계약을 읽은 직후, validation root 생성과 실제 Blender materialization보다 먼저
`total_blender_builds` budget을 fail-closed했습니다. 이미 작성된 controller output과 실패 state는
append-only로 보존하고 adapter recovery를 terminal까지 닫았습니다.

- campaign: `aq-stage9-prep-r5-laser-relief-canary`
- launch SHA-256: `3dca3d704ef8de8c2b3d5908b6d8004e1c1ca58e49e3103f61fc987b61288f3d`
- job/session: `aq_stage9_prep_r5_01_laser_relief_canary` /
  `aqv2-20260831t062849993981z-64e9e08a`
- technical failure SHA-256:
  `9c294ef923fd6cbc628307ebba725b7fbb56dada877848acfd3e669260dda6d8`
- One-Prompt terminal SHA-256:
  `2baf2540668add024ccdb1192c97da63974dfae1099d6a2e313e0200050d0d0f`
- terminal type/status: `blocked` / final AQ state `failed`
- 실제 candidate materialization 0, canonical promotion 0, canonical corruption 0
- 추가 사용자 결정 0, technical user approval request 0, destination write 0

이는 host 안전 결함이 아니라 campaign object 계획과 immutable budget의 용량 계약 불일치입니다.
역사적 R5 budget이나 terminal을 수정하거나 전역 budget을 소급 확대하지 않습니다.

### 11.2 budget-bounded R5B recovery canary

R5B는 실패한 R5 terminal과 같은 current baseline을 exact binding하고 새 job으로 실행했습니다. R4의
10개 관측 panel은 모두 four-section beveled relief로 전환했지만, R5에서 추가했던 rear stock frame/pad,
receiver collar, upper/lower rail, trigger, foregrip 7개는 이번 primitive canary에서 제외했습니다.
primary concave shell 1개를 포함한 총 11 objects는 geometry `12` + material `2`로 고정 budget `14/14`를
정확히 사용했습니다.

- campaign: `aq-stage9-prep-r5b-laser-relief-canary`
- launch SHA-256: `ef17c07688614f3d3dcd0ea8bf27dbb5fc49ef3b7988842bf79693a272b2cfa5`
- campaign result SHA-256:
  `d0374b01266e6289a3f6945ba3cd66fd32b8e00edc13b00fc1bdaaa048d1a606`
- job/session: `aq_stage9_prep_r5b_01_laser_relief_canary` /
  `aqv2-20260831t063616945434z-405cdbd4`
- V0.6 direct / silhouette IoU: `0.972529` / `0.968892`
- IQ boundary F / edge chamfer norm: `0.878564583340811` / `0.0022416958658623303`
- IQ report SHA-256:
  `a17f81fd68d73c2966715d214955115b6c690818c3a502f22a4d3396dd7a511a`
- source freeze SHA-256:
  `a0cb25e9e65013ad63c2122409b35b9b838ddb4fd8adeb2a5c12d54f5b2f04c9`
- quality terminal SHA-256:
  `9ead9c56040c86ab4c61bf1a61975376b2f2a400a30c59286e983fabeca4cd42`
- delivery review SHA-256:
  `4794a303752ae28b01fbe437b909e651d8b09b485920fa68d0c7bb790fc69826`
- host status/next action: `delivery_pending` / `await_v07_approval`
- additional user decisions `0`, technical user approval requests `0`, routine policy authorizations `2`,
  delivery user approvals `0`, canonical corruption `0`

현재 새 human review request와 beauty는 다음 exact bytes에 결속됩니다.

- review request SHA-256:
  `6c7e4270501b50cd6223b4f716439ba0bfa333bfde7898887c0af4ce2a9caf0b`
- beauty SHA-256:
  `c497f6751f3918d1665efe6c7ab5ab313388de0630eb75437f6996aa76f7cafd`
- human disposition: exact `needs_revision` (`1/1`)
- disposition set ID / logical SHA-256:
  `stage9-prep-disposition-set-50800d64fbd48ce53857abb5` /
  `50800d64fbd48ce53857abb5c06a76f474f9b6aa68cfab527d294e984d308e94`
- disposition set file SHA-256:
  `9d4b6347a9ff064274d8ae49997ef054b2ef6f4accea1def3b5939a948a296b4`
- disposition record ID / logical SHA-256:
  `stage9-prep-human-disposition-e25d886aaef661c4be215b64` /
  `e25d886aaef661c4be215b64f5504db37272b5b1ff5431d6d64ad48c160b84da`
- disposition record file SHA-256:
  `497bacea2c460297c22fb7017f2c272755e24b0a839588b7ecfc145cd5f4b79a`
- recorded at: `2026-08-31T07:46:40.675420Z`
- authority effects: V0.7 delivery, budget expansion, package, activation, destination write 모두 `false`

machine IQ pass는 beveled-relief capability와 exact contour 개선 증거이지만 production visual acceptance가
아닙니다. 제외한 7개 assembly object 때문에 reference의 rear stock, receiver collar, rail, trigger,
foregrip 구조가 아직 부족하다는 판정을 사용자가 exact `needs_revision`으로 확정했습니다. 이 판정은
R5B source freeze를 delivery에 사용하거나 전역 budget을 늘리는 권한이 아닙니다.

### 11.3 현재 다음 경계

1. 위 R5B exact beauty의 `needs_revision` disposition을 append-only로 기록했습니다.
2. budget accounting이나 schema version을 바꾸지 않고 기존 strict `boolean_tree` 위에
   `build_balanced_component_union()`을 추가했습니다. 2~32개의 same-material operand만 받아 균형
   `EXACT UNION`을 만들며, 여섯 분리 profile extrusion이 한 materialization 뒤 여섯 connected component로
   남는 actual Blender 5.0.1 smoke가 통과했습니다. 관련 Python focused `59 passed`, 전체 Python
   `2020 passed, 65 skipped, 8 warnings`, structural Blender 5.0.1 `11 passed`, Ruff가 통과했습니다.
3. focused/full/Blender 회귀를 통과한 clean commit과 새 Activation baseline을 만든 뒤, 누락 assembly를
   material identity별 composition object로 묶은 fresh Laser canary를 고정 build budget 안에서 실행합니다.
4. 새 Laser beauty가 exact `accepted`일 때만 별도 exact V0.7 plan 승인을 받아 portable delivery canary를
   실행합니다. 새 beauty가 다시 `needs_revision`이면 같은 결함을 렌더만 바꿔 반복하지 않습니다.
5. exact accepted beauty와 passed package/clean-import terminal이 모두 존재한 뒤에만 새
   Registry/Eligibility/Index/Readiness를 게시해 Activation을 재평가합니다.
6. 단일 Laser 폐루프 전에는 5-reference 전체 캠페인과 ImageGen overlay benchmark를 시작하지 않습니다.

따라서 현재 authoritative 판단은 **R5B machine canary pass, human quality needs_revision, delivery
unauthorized, bounded composition regression 진행 중, Activation NO-GO**입니다. AQ base와 ImageGen
overlay profile은 모두 `disabled_experimental`을 유지합니다.

## 12. R5C/R5D Laser 폐루프와 V0.7 technical recovery

### 12.1 R5C composition과 R5D perspective compensation

R5C는 R5B에서 빠졌던 assembly를 material-identity composition으로 묶어 고정 build budget 안에서
실행했습니다. 실제 adapter terminal은 닫혔지만 V0.6 direct `0.932642`, silhouette IoU `0.904873`,
IQ boundary F `0.627697`로 quality hard gate에서 `blocked`됐습니다.

- campaign launch file SHA-256:
  `a449a24e14bc3321575cb2c9c35e472b6940b0082327488a24a8755e96c21518`
- campaign result file SHA-256:
  `5cee30e32084cc4eff66954a8b60ca284ed3a77c94d246be207501adb4b41f2b`
- review request SHA-256:
  `4baa26bd134cfe5cfaa264539d802d84220eae229710926f305bb23b6a9657d0`
- beauty SHA-256:
  `b0193e2b7a3893913e05dc1ee6a5de261ce09dc256c727a01ebb98ad030651b1`
- exact human disposition: `needs_revision`
- disposition set logical/file SHA-256:
  `0559479fe58b9064f347439da3ed47303d957023a858fa00b086e86cdc5b8c9a` /
  `f8431f0b0560774d38cee795685944880f603cdaf995531227886019329132a9`

R5C diagnostic은 reference와 candidate의 perspective 차이를 별도 attribution으로 고정했습니다. 같은
immutable reference에서 전체 topology나 budget을 넓히지 않고 bounded perspective compensation만 적용한
R5D는 V0.6 direct `0.946730`, silhouette IoU `0.935239`, IQ boundary F `0.816738`, chamfer
`0.003923`으로 IQ pass/source freeze에 도달했습니다.

- campaign launch file SHA-256:
  `cb4981049d5b713709812f72e6c5f188f44f657097994485da455a9f53335d56`
- campaign result file SHA-256:
  `67d24d6d56c7862157a3bf61a9fbd50802509c05877d13582c55fb1091bc1040`
- source freeze SHA-256:
  `6b1faba801374645db5b07d3e28e801bcdc41cf5ae21f4a0a2ab259a124f49bc`
- review request SHA-256:
  `3e62d43cac0f4ebdcda80bfdfc1ccd442f32144025c3e0a965e8ca7683b45e9f`
- beauty SHA-256:
  `b538f7acc0ff84c427dd5a70b7268e89696cc2955b6e5e33868493049575e6ec`
- exact human disposition: `accepted`
- disposition set logical/file SHA-256:
  `d5907e72ba5e3c014263c07175380b710fa8b9a745bebcceeee268a582e7a394` /
  `84888eb2dac47b2e1319db21e891f12e674c5a09ea0a84ef8c286d49f7ba1965`

이 visual acceptance는 V0.7 package나 Activation의 사전 승인이 아닙니다. 사용자는 이후 별도의 exact
portable GLTF optimization plan SHA-256
`65c13c1e2ccacaa056ad40b5bbe5ec8d4ffe2cfe4bd6a3a27b16dda74acecd95`를 승인했습니다.

### 12.2 원래 host terminal과 append-only R01~R07

승인된 계획의 원래 AQ host 실행은 production package를 만들지 못한 채 다음 exact safe terminal로
종료됐습니다. 이 state와 terminal은 모든 recovery 뒤에도 수정하지 않았습니다.

- failed state SHA-256:
  `8cd9e923fc60b5e69dc7de6af06c70005a1634471f74cc071e9a1b0b6a45d621`
- failed delivery terminal SHA-256:
  `5c116036df12c868aebf68167332178771a264179df7e5a351a272ead51312ae`
- consumed exact approval SHA-256:
  `f94f96d18e6c5170e75338fae7d56142bf62c723d804d9f1442e3b18eccf0dd6`
- canonical SceneSpec/MaterialPlan/blend SHA-256:
  `b0fcf6c786fe8badf866fce357b703474361e43e3e17b127270dfc4afb4343c2` /
  `7dbb233703c48bfbf3129b4af8bd5d33c65117c2e3b0aa895df307a4eee7dd02` /
  `93a462943f2a82a6f4372b00167a7232666db67df733b3d4931c9eb6111d23c8`

각 technical recovery는 새 경로와 새 attempt/result로만 실행했습니다.

| Recovery | result logical SHA-256 | 결과 | 고정한 경계 |
|---|---|---|---|
| R01 tangent topology | `e097642502279b96b6c45f811fc80f7dffa78be5c2742ebbb880f41b823a1e7a` | failed | exporter n-gon tangent 계산 실패 |
| R02 exporter probe | `68b8ee943da5a5b889e54adb565a3565e8a9aae81be3daa93966cb35b1e31f84` | failed | recovery adapter 호출 signature 실패, Blender side effect 0 |
| R03 adapter signature | `1eceaec1b2225d6c2862e535e467eafe1b3796d956e0da2b4527646304b2caa0` | failed | Windows GLTF temporary path 길이 실패 |
| R04 Windows temp path | `44d9f3671d1673e21142cd51bc83b7ecf3d465aee4c083f6d922bb9fd275875f` | failed | package 생성, clean-import tangent/UV/survival 실패 |
| R05 serialization alignment | `a678062b947962b9781087c49023f68b26c78916d4b418a1f17e3db7ab730017` | failed | conversion의 near-collinear tangent residual 1개 |
| R06 pre-normal topology | `0bd7b8b61f87bf9eee55e264f13b4f7eed737c287434c4d8090d881fcbab896e` | failed | package/round-trip pass, UV fingerprint boundary false negative |
| R07 UV fingerprint evidence | `a3ab953192560de9c886b34c27bf8c7009a6a964902e30a435087a7d0704006b` | completed | 기존 R06 package의 evidence-only geometry survival 재검증 |

R06 conversion은 exporter와 같은 `FIXED/EAR_CLIP` topology를 물리 고정하고, 면적
`1e-7 m²` 이하이면서 aspect ratio `1e-5` 이하인 negligible triangulation face만 derived mesh에서
제거했습니다. 실제 Blender 5.0.1 diagnostic에서 33개가 제거됐고 tangent invalid loop, residual
micro/collinear sliver와 bounds delta는 모두 0이었습니다. canonical 3개 hash는 변하지 않았습니다.

R06 package와 post-publication evidence:

- technical package ID: `r5d-recovery-r06-gltf`
- package manifest SHA-256:
  `2ddcfd0e2125871e22282a3a4fd9558364bbfc673d6a8a71806e5821f0b97257`
- round-trip validation SHA-256:
  `227783a4065df4283027e5ae94c91206d84c71dd2bf91df1e622913bc0bd620c`
- R07 geometry survival SHA-256:
  `83bc1fae301df2f9a7b7ee6ace1ebf79de72b625663fd5879b9f839403019d0e`
- package: `complete`, 파일 `26`, absolute path `0`, missing dependency `0`, errors/warnings `0/0`
- clean import: `passed`, failed checks `0`, semantic/material coverage `1.0/1.0`
- geometry survival: `known_loss`, exact `7`, equivalent `1`, failed `0`, format-hidden known loss `7`
- R07 terminal: `technical_package_validated=true`, conversion/package 재실행 `false`

R06 UV mismatch는 2,415개 corner와 436개 semantic-position key가 모두 같고 최대 raw delta가
`2.98023223876953e-08`인 상태에서 기존 `1e-5` quantization 경계에 걸린 8개 V 값만 달랐던
false negative였습니다. 비교 cell을 `2e-5`로 제한해 재검증했으며 material-visible UV displacement를
허용하거나 실제 좌표 차이를 package pass로 재분류하지 않았습니다.

최종 회귀 과정에서는 Blender image API가 `\\?\` extended temp path를 직접 거부하는 별도 GLTF
image-encoding 경계를 발견했습니다. exporter는 이제 process temp 아래의 짧은 고유 normal-path staging
root를 사용하고, 그 root 내부의 Python `0o700` child 생성만 inherited ACL mode로 바꾼 뒤 전역
`tempfile.tempdir`와 `os.mkdir`를 복원합니다. 실패했던 signage/emissive preview 2건은 불필요하게 긴
pytest basetemp에서만 재현된 경로 길이 오탐이었고, GLTF fake-signage export 1건은 이 staging 수정으로
해소됐습니다. 세 exact 재현은 `3 passed`였고 최종 공식 gate는 다음을 기록했습니다.

- V0.7 full gate: `2021 passed`, `65 skipped`; Blender 5.0.1 GLTF/FBX/OBJ package와 clean import 통과
- AQ focused gate: `935 passed`, `26 skipped`
- AQ Blender smoke: `47 passed`, `1 skipped`
- AQ 0.1 benchmark: `8 passed`, `0 failed`, Blender case `3`
- AQ 0.2 benchmark: `10 passed`, `0 failed`, Blender case `2`, human review `not_reviewed`

이 검증은 현재 소스 결함을 닫는 회귀 증거이며 R06 package를 재생성하거나 원래 failed terminal을
변경하지 않았습니다. 이 회귀 실행 자체는 package acceptance, destination write 또는 profile Activation
권한을 만들지 않았습니다.

### 12.3 현재 Activation과 다음 exact 권한 경계

R5D는 새 Laser의 IQ/source freeze, exact human `accepted`, 실제 Blender package, clean import와 geometry
survival이라는 기술 선행조건을 충족했습니다. R06은 원래 exact plan package ID와 다른 technical recovery
package이므로 원래 failed delivery terminal이나 stale workflow gate를 재결박하지 않았습니다.

2026-09-01 사용자는 다음 두 exact SHA-256을 package acceptance 대상으로 승인하면서 destination write와
profile Activation은 명시적으로 제외했습니다.

- package manifest:
  `2ddcfd0e2125871e22282a3a4fd9558364bbfc673d6a8a71806e5821f0b97257`
- post-publication round-trip:
  `227783a4065df4283027e5ae94c91206d84c71dd2bf91df1e622913bc0bd620c`

Host의 `asset-package-accept`는 exact bytes, package receipt, source freshness, clean-import identity, bounds와
semantic/material coverage를 다시 검증한 뒤 다음 append-only receipt를 single-use로 소비했습니다.

- acceptance ID: `package.acceptance.2ddcfd0e2125871e22282a3a`
- acceptance path:
  `workspaces/aq_stage9_prep_r5d_01_laser_perspective_canary/optimization/runs/delivery-plan-aqv2-20260831t115126214507z-605fc5bf-gltf-run/package_acceptances/r5d-recovery-r06-gltf/acceptance.json`
- acceptance file SHA-256:
  `c6ad1650ef9ada5e2017381da942dbad35a9222352bb599baaeba526e5cab1df`
- acceptance time: `2026-09-01T08:09:04.856349Z`
- `status=accepted`, `single_use=true`, `consumed=true`
- `canonical_unchanged=true`, `destination_project_modified=false`
- clean import/bounds pass, semantic/material coverage `1.0/1.0`

승인 소비 뒤에도 원래 state `0010.json` SHA-256
`8cd9e923fc60b5e69dc7de6af06c70005a1634471f74cc071e9a1b0b6a45d621`와 delivery terminal SHA-256
`5c116036df12c868aebf68167332178771a264179df7e5a351a272ead51312ae`는 그대로입니다. 따라서 R07의
아래 필드는 historical result로 불변 보존하고, 이후의 exact acceptance를 별도 권위 기록으로 해석합니다.

- `technical_package_validated=true`
- `host_delivery_adopted=false`
- `production_package_authorized=false`
- `profile_activation_authorized=false`
- AQ base와 ImageGen overlay 모두 `disabled_experimental`
- exact package acceptance: **완료**
- destination write/runtime parity/profile Activation: **미승인**
- Activation 판정: 새 baseline-bound machine 재평가 전까지 **NO-GO 유지**

다음 단계는 새 모델링이나 package 재생성이 아닙니다. package acceptance blocker는 닫혔으므로 full gate와
최종 clean source commit을 기준으로 새 ActivationSourceManifest/Baseline, Candidate
Registry/Eligibility/Index/Readiness를 게시합니다. 이때 R5D가 시작된 historical baseline과 새 source
baseline의 차이, 원래 failed AQ terminal, accepted technical package를 각각 숨기지 않고 평가해야 합니다.
그 machine evidence에서 Stage 9 overlay의 bounded experimental 진입 가능 여부와 AQ base NO-GO blocker를
분리해 결정합니다. package acceptance는 Destination Handoff plan 승인, destination write, runtime parity 또는
profile Activation 승인이 아닙니다.
