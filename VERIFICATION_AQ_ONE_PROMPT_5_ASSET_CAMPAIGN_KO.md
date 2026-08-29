# AQ One-Prompt 실제 reference 5개 실험 캠페인 검증 기록

## 1. 판정

2026-08-29 현재 `aq-one-prompt-orchestrator`의 동일 reference 5개 structural re-entry 재캠페인은
**IQ pass 4/5, source freeze 4/5, activation NO-GO**입니다.

- 최초 캠페인의 adapter route/receipt와 ControllerExecutor protected-inventory 결함을 수정하고,
  orphan policy authorization도 exact replay 또는 `technical_failed` receipt로 회수하도록 보강했습니다.
- 새 R2 job 5개 모두 Reference → Geometry controller/Blender 검증/승격 → Material controller/graph
  compile/Blender rebuild/승격 → V0.6 7-pass → IQ 0.2까지 도달했습니다.
- plastic, wood, crystal, laser는 IQ 0.2 `passed` 및 exact source freeze를 게시했고
  `quality_approved / plan_delivery`에서 의도적으로 정지했습니다.
- rust는 boundary F-score hard gate만 통과하지 못해 `blocked` safe terminal로 닫혔습니다.
- 새 R2 run의 adapter route/receipt는 5/5 모두 일치하며 orphan route는 0건입니다.
- canonical corruption, 추가 사용자 결정, technical user approval request는 모두 0건입니다.

그러나 R2 geometry는 관측 silhouette를 보존한 0.08 m 얇은 extrusion입니다. IQ contour 계약은
4개를 수락했지만, 실제 beauty의 깊이·조립·표면 세부는 production 3D 품질에 미달합니다. 따라서
source freeze는 delivery 기계 경계를 시험할 수 있는 자격이지 human quality acceptance나 profile
activation 근거가 아닙니다.

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

이번 corpus는 서로 다른 reference 5개라는 요청을 만족합니다. 다만 기존 activation benchmark에서
예시로 든 signage/decal 범주 대신 rusted metal을 사용했으므로, signage/decal coverage는 별도
후속 자산으로 남습니다.

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
| Delivery | 0/5 | 가능 여부 판단을 위해 `plan_delivery` 직전 의도적 정지 |
| Human quality disposition | 0/5 | IQ pass를 사람의 production 품질 승인으로 확대하지 않음 |

이 R2 캠페인도 texture/bake 의존성을 추가하지 않았습니다. 또한 얇은 extrusion은 contour와 camera
framing 회귀를 검증하는 bounded 구조 후보이며 volumetric reconstruction 증거가 아닙니다.

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
| portable delivery/clean import | 0/5 | 다음 canary에서 검증 |
| 별도 human quality disposition | 0/5 | 미완료 |

policy decision은 applied 9건과 복구용 `technical_failed` 1건입니다. 이 receipt는 user approval이
아니며, plastic의 첫 잘못된 freeze submission이 남긴 single-use authorization을 canonical 변경 없이
회수한 증거입니다.

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

초기 실패 job, 최초 캠페인의 plastic R1/R2 실패 job, 이번 re-entry의 r1 순서 오류 job과 잘못된
첫 quality submission은 immutable failure history로 보존했습니다. 이를 삭제하거나 성공으로 소급
재분류하지 않았습니다.

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
- Phase 1 최종 회귀는 `2002 passed, 63 skipped`, AQ focused `923 passed, 26 skipped`,
  실제 Blender smoke `43 passed, 1 skipped`입니다. 최초 smoke의 `signage_decal`/`emissive` 2건은
  265자 pytest 경로에서 manifest lookup이 실패했으나 저장소 루트의 짧은 basetemp로 정확히 재실행해
  `2 passed`를 확인했습니다. 이에 PowerShell AQ gate의 기본 pytest root도 Windows MAX_PATH 아래의
  `/.b/`로 줄였습니다.
- 실제 Blender benchmark는 AQ 0.1 `8/8`, AQ 0.2 `10/10`, 실패 0입니다. V0.9 isolated gate도
  Blender 5.0.1에서 GLB package manifest의 absolute path 0, missing dependency 0, clean import `passed`,
  valid handoff `1/1`, canonical unchanged를 확인했습니다.

## 7. Activation 결정과 다음 실행 조건

현재 `autonomous_static_prop_v2`와 `aq-one-prompt-orchestrator`는 계속
`disabled_experimental`이어야 합니다.

현재 판단은 다음과 같습니다.

1. **Delivery canary 실행 가능:** source freeze가 있는 4개 중 clean recovery history와 최고 direct
   score를 가진 `aq_reentry_r2_03_weathered_wood_beam`을 portable GLTF package/clean-import의 첫
   기계적 canary로 권장합니다. 이는 패키징 계약 검증이며 production 미술 품질 승인이 아닙니다.
2. **Activation readiness 재생성은 아직 불가:** Phase 1 source gate는 통과했지만 실제 R2 delivery/clean
   import 및 human acceptance가 없습니다. 먼저 recovery 수정의 clean checkpoint를 고정하되,
   ActivationSourceManifest/Baseline은 delivery와 후속 volumetric campaign까지 완료한 새 clean commit에만
   결속해야 합니다.
3. **Activation 판정은 계속 NO-GO:** profile status가 명시하는 human review, supporting-client closed
   loop, controller sandbox attestation, destination runtime parity blocker가 남아 있습니다. R2 beauty의
   volumetric fidelity도 production acceptance에 미달합니다.

다음 실행 순서는 다음과 같습니다.

1. 관련 source gate와 실제 Blender 회귀를 통과시키고 수정 사항을 clean commit으로 고정합니다.
2. wood delivery canary 1개만 실행해 immutable package manifest와 clean-import evidence를 확인합니다.
3. 다섯 beauty에 대한 별도 human `quality_pass`/`needs_revision` disposition을 machine IQ와 분리해
   기록합니다. 현재 render 기준으로는 production `quality_pass`를 권장하지 않습니다.
4. rust boundary contour를 보완하고, 나머지 4개도 얇은 silhouette가 아닌 volumetric assembly로
   재저작한 뒤 동일 reference benchmark를 반복합니다.
5. signage/decal 1개와 dependency-rich texture/bake Material Closure 1개를 추가합니다.
6. 그 결과를 clean commit의 새 ActivationSourceManifest/Baseline/Index에 묶은 뒤에만 human
   Activation acceptance 및 readiness report를 재평가합니다.

## 8. 주요 authoritative evidence

- 각 job의 base state: `production/autonomy_v2/<session>/states/0008.json`
- 각 job의 quality terminal: `production/autonomy_v2/<session>/quality_terminal.json`
- 실제 V0.6 pass/report: `qa/runs/<campaign-v06-run>/`
- 최초 host-recomputable IQ 제출: `production/autonomy_v2/<session>/quality_evidence/<campaign-v06-run>-r1/`
- R2 host-recomputable IQ 제출: `production/autonomy_v2/<session>/quality_evidence/<reentry-v06-run>-iq02/`
  (plastic 최종 exact retry는 `-iq03`)
- R2 source freeze: `production/autonomy_v2/<session>/source_freeze.json` (pass 4개만 존재)
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

이 문서는 machine JSON을 대체하지 않습니다. 경로·SHA·state·receipt가 서로 다르면 machine JSON이
권위입니다.
