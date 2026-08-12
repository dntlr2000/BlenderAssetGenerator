# Codex ImageGen 0.2 Material Loop 아키텍처

> 상태: **additive companion 구현됨, profile 비활성**. 프로젝트는 `0.9.0`, canonical
> SceneSpec은 `0.2.0`이며 `autonomous_static_prop_v2`와
> `autonomous_static_prop_v2_codex_imagegen`은 모두 `disabled_experimental`이다. 실제 실행
> 범위와 미검증 항목은 [검증 기록](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다.

## 1. 목적과 권위 경계

Codex Built-in ImageGen core `0.1.0`은 생성 assignment, 후보 PNG, deterministic quality,
selection과 MaterialAuthoring `0.2.1` staging receipt까지 제공한다. Material Loop companion은 그
staging evidence를 기존 AQ v2 material controller, host promotion, IQ `0.2.0` 경계에 연결한다.

이 연결은 권위를 합치지 않는다.

- ImageGen completion 또는 selection은 canonical material promotion이 아니다.
- MaterialAuthoring `0.2.1` receipt는 staging evidence이며 기존 bytes를 소급 수정하지 않는다.
- canonical MaterialPlan은 기존 host material phase service만 쓸 수 있다.
- IQ pass, V0.7 최적화 승인, package acceptance와 destination parity는 서로 다른 증거다.
- current-task Codex 의미 검토는 항상 `human_reviewed=false`다.

## 2. 버전과 비목적

유지되는 버전:

- Project `0.9.0`, canonical SceneSpec `0.2.0`
- AQ v2 / Integrated Quality `0.2.0`
- Codex Built-in ImageGen core `0.1.0`
- Image-to-material adoption `0.2.0`
- MaterialAuthoring Codex-image staging companion `0.2.1`
- ControllerExecutor, DeliveryProfile과 Material Loop companion contract `0.1.0`

비목적:

- OpenAI API/SDK/API key 또는 repository-owned HTTP ImageGen provider
- 새 Codex task, daemon, 앱 종료 뒤 자동 실행
- generated normal, roughness, metallic, height, AO 또는 tangent-space map의 직접 채택
- bridge/controller가 canonical SceneSpec이나 destination project를 직접 쓰는 것
- 사람 검토, specialized approval, production package 또는 runtime parity 합성
- 기존 ImageGen/AQ/MaterialAuthoring evidence의 자동 migration이나 재분류

## 3. additive contract 묶음

Material Loop contract는 strict Pydantic, `extra=forbid`, non-finite 거부, exact SHA-256,
repository-relative POSIX path, containment, immutable ID, UTC timestamp와 전체
job/workflow/dispatch/session/profile identity를 사용한다.

주요 contract는 다음과 같다.

| contract | 역할 |
|---|---|
| `CodexImageNativeOutputAdoptionReceipt` | 외부 native PNG bytes를 run-owned immutable `original.png`로 채택 |
| `ImageGenNativeNormalizationPlan` / `Receipt` | crop, contain-pad, tile-crop 또는 pass-through의 deterministic 계획과 결과 |
| `CodexImageNativeCorePreparationReceipt 0.1.0` | native adoption/normalization과 core completion/candidate/quality/selection 사이의 exact byte identity 결속 |
| `CodexImageSemanticReview` | current Codex task의 구조화된 non-human 관찰 |
| `CodexImageCandidateRankingEvidence` | 후보별 hard gate, quality, semantic, role, repair-cost precedence 결속 |
| `CodexImageCompanionSelectionReceipt` | 모든 다중 후보의 ranking grounds와 core selection 결속 |
| `CodexImageV05ExactAdoptionPreflightReceipt` | V0.5 staging 의미를 바꾸지 않고 exact candidate graph bytes의 실제 Blender shadow compile을 결속 |
| `ImageGeneratedMaterialBridgePlan` | staging chain과 material-controller authority ceiling 고정 |
| `ImageGeneratedMaterialControllerInput` / `Binding` | exact immutable input closure와 실제 ControllerExecutionRequest/Result 결속 |
| `ImageGeneratedMaterialPromotionReceipt` | controller, compile, canonical snapshots와 실제 `MaterialPhaseReceiptV2` 결속 |
| `ImageGeneratedMaterialNeutralPreview` | 고정 neutral preview 설정과 output hash 결속 |
| `CodexImageMaterialLoopState` / `Terminal` | append-only companion 진행과 최종 material/IQ 경계 기록 |

V0.5 adapter가 canonical MaterialPlan 부재를 입력으로 사용할 때는 별도
`CodexImageV05CanonicalMaterialAbsence` evidence가 그 부재를 exact하게 고정한다. 기존 schema나
역사 artifact를 제자리에서 넓히지 않는다.

## 4. 전체 흐름

```text
Codex native PNG
→ immutable native original adoption
→ deterministic normalization plan/receipt
→ normalized bytes를 처음부터 새 ImageGen assignment candidate로 사용
→ completion + deterministic quality
→ current-task non-human semantic review
→ single-candidate legacy selection 또는 multi-candidate companion ranking/selection receipt
→ native-to-core preparation receipt
→ ImageToMaterialAdoption 0.2.0
→ MaterialAuthoring 0.2.1 staging receipt
→ V0.5 bridge/normalized companion evidence
→ exact_adoption이면 isolated Blender shadow preflight receipt
→ ImageGeneratedMaterialBridgePlan + ControllerInput
→ request-owned ControllerExecutionRequest / ControllerResult
→ host material validation, MaterialGraph compile, canonical CAS, Blender rebuild
→ actual MaterialPhaseReceiptV2 + promotion companion + neutral preview
→ overlay material_promoted / waiting_for_quality
→ base AQ material_candidate_validated / IQ 0.2
→ quality_approved | review_required | blocked | failed | cancelled
→ existing review_only or V0.7 delivery approval boundary
```

각 단계는 이전 exact bytes, identity와 predecessor를 다시 검증한다. companion terminal은 전체 AQ
workflow나 package 완료를 대신하지 않는다.

## 5. native adoption과 normalization

Codex built-in ImageGen의 native output 크기가 assignment target과 다를 수 있으므로 core `0.1.0`
dimension 규칙을 느슨하게 만들지 않고 additive 경로를 사용한다.

1. allowed source root 안의 PNG를 fresh decode/hash한다.
2. exact bytes를 run-owned `original.png`로 한 번만 게시한다.
3. source/target 크기, 요청 연산, crop/padding, resampler, colorspace와 alpha policy를 plan에 고정한다.
4. deterministic `normalized.png`와 receipt를 게시한다.
5. 기존 core completion에는 이 normalized bytes를 새 assignment의 원본 후보로 공급한다.

native `original.png`를 source로 삼은 normalization receipt는 해당
`CodexImageNativeOutputAdoptionReceipt`를 생략할 수 없다. replay는 assignment identity,
원본 path/hash/metadata, normalization plan과 derivative를 재귀적으로 다시 검증한다. adoption receipt가
빠졌거나 다른 original을 가리키면 bridge 전 단계에서 fail-closed한다.

normalization이 같은 assignment의 selected core bytes를 공급했다면
`CodexImageNativeCorePreparationReceipt`가 assignment, adoption receipt/original, normalization
plan/receipt/normalized image, core completion/candidate/generated-image evidence/quality/selection과
copied core generated image를 함께 묶는다. `normalized_image`와 copied core image는 exact byte
identity여야 하고 기존 core contract는 수정되지 않는다. artifact kind는
`codex-image-native-core-preparation-receipt`, canonical leaf는 다음과 같다.

```text
production/autonomy_v2/<session>/codex_imagegen/assignments/<assignment_id>/
└─ evidence/native-core-preparation-<ordinal:02d>.json
```

허용 연산은 pass-through, center crop, contain + deterministic pad, 명시적 tile crop이다. silent
stretch, 임의 output path, source overwrite, stale plan과 허용 한계를 벗어난 종횡비는 거부하거나
`review_required`로 끝낸다. 이미 selection이 끝난 과거 completion에 derivative를 소급 연결하지
않는다.

## 6. semantic review와 다중 후보 선택

`CodexImageSemanticReview`는 unwanted text/object/background, family/role suitability, wood grain,
decal, emissive/crystal pattern, style alignment, repeat/tile, hotspot, perspective와 boundary
contamination을 canonical order로 기록한다.

- `human_reviewed=false`, `observed_reference_truth=false`
- deterministic file/quality gate를 대체하지 않음
- explicit forbidden content만 제한된 hard failure 가능
- 미적 판단 또는 불충분한 관찰은 `review_required`/`unavailable`

후보가 둘 이상이면 모든 후보에 exact semantic review와 ranking evidence가 있어야 한다. 하나라도
누락되거나 unresolved이면 selection 전체가 `review_required`다. 해소된 후보의 오름차순 precedence는
다음과 같다.

```text
file hard gate
→ deterministic quality outcome/score
→ semantic outcome
→ material-role suitability
→ repair cost
→ stable candidate ID
```

따라서 deterministic score가 가장 높아도 hard-fail한 후보는 다음 유효 후보보다 앞설 수 없다.
single-candidate core selection의 기존 의미는 바꾸지 않는다.

다중 후보에서 발행한 `CodexImageCompanionSelectionReceipt`는 core selection, 선택 candidate/quality,
후보별 semantic/ranking evidence를 하나의 closure로 묶는다. bridge plan, controller input과 promotion
receipt가 같은 artifact를 계속 결속하고 replay한다. `candidate_count>1`인데 receipt가 없거나 선택
결과가 달라지면 거부하며, single-candidate legacy selection은 이 companion receipt를 가장할 수 없다.

## 7. bridge와 controller 실행 모드

bridge plan은 AQ authorization/plan/profile/budget/current state, SceneSpec/geometry/build, 전체
ImageGen chain, semantic/normalization/adoption/native-to-core preparation, MaterialAuthoring/V0.5
companion, texture와 graph
dependency, 이전 MaterialPlan 또는 exact absence evidence를 fresh rehash한다. target material과
semantic ID, mutable/immutable material set, delivery request, output root와 정확히 세 개의 output을
고정하며 geometry/semantic mutation과 destination write를 금지한다.

bridge/controller/promotion의 optional `native_core_preparation_receipt`는 같은 assignment의 native
normalization이 selected bytes를 공급했을 때 필수다. native-fed selection인데 누락되거나 다른
candidate/ordinal/role/target size를 가리키면 거부한다. native 경로를 사용하지 않은 legacy chain은 이
optional field가 없다는 이유만으로 실패하거나 migration되지 않는다.

실행 모드는 둘이다.

- `exact_adoption`: expected output hash가 모두 있고 별도
  `CodexImageV05ExactAdoptionPreflightReceipt`가 exact candidate MaterialPlan/MaterialGraph bytes와
  dependency를 run-owned isolated shadow에 복사해 실제 Blender whitelist compile을 통과했을 때만
  사용한다. preflight는 `ControllerResult`를 만들거나 canonical/destination을 쓰지 않는다. 원래
  MaterialAuthoring receipt는 계속 `staging_only=true`, `blender_compilation_status=not_run`이며 그
  bytes나 의미를 compile pass로 재해석하지 않는다.
- `controller_authored_completion`: 현재 Codex task가 request-owned workspace 안에서 정확히
  `material_plan.json`, `material_graph.json`, `completion.json`만 완성한다.

어느 모드도 handwritten `ControllerResult`, extra output, source mutation, 두 번째 invocation,
canonical 또는 destination write를 허용하지 않는다.

## 8. host promotion과 preview

유일한 canonical writer는 기존 `validate_and_promote_material_controller_result_v2`다. 이 service가
authorization, request/result, SceneSpec 불변, material scope와 dependency를 검증하고 MaterialGraph
compile, canonical MaterialPlan compare-and-swap, Blender rebuild/inspect/validate와 rollback을
수행한 뒤 `MaterialPhaseReceiptV2`를 발행한다.

기존 MaterialAuthoring `0.2.1` receipt의 `blender_compilation_status=not_run`은 변경하지 않는다.
exact-adoption shadow compile, host promotion compile과 fixed neutral preview는 각각 새 run-owned
evidence로 결속하며 서로의 권위를 대신하지 않는다. compiler manifest의
`rendered=false`는 preview pass가 아니다. canonical write 전후 오류는 exact failure/rollback
evidence를 남기며 부분 staging을 success receipt로 승격하지 않는다.

## 9. state, IQ와 delivery

companion state는 다음과 같이 append-only로 진행한다.

```text
controller_promotion_required
→ promoting_material
→ material_promoted
→ waiting_for_quality
→ quality_approved | review_required | blocked | failed | cancelled
```

base AQ state는 기존 transition service만 사용해 `material_candidate_validated`와
`run_integrated_quality`로 진행한다. companion의 `quality_approved`는 exact base quality terminal과
freeze에 결속된 결과이며 package 완료를 의미하지 않는다.

IQ 의미도 바꾸지 않는다. only-passed IQ가 current MaterialPlan, actual MaterialPhaseReceiptV2,
geometry/build와 generated/derived source에 결속된 freeze를 만든다. `needs_revision` 또는
`unscorable`은 review evidence, `blocked`는 freeze 없는 blocked evidence로 끝난다.

delivery는 기존 profile을 재사용한다.

- `review_only`: package가 아님
- `portable_gltf` / `portable_fbx`: 같은 freeze에서 독립 V0.7 review와 exact user approval 필요
- approval 전에는 `waiting_for_v07_approval`; package/terminal을 합성하지 않음
- raw exporter/clean-import test는 mechanism evidence일 뿐 package acceptance가 아님

## 10. crash recovery와 stale 규칙

native adoption, normalization, native-to-core preparation, selection, exact-adoption preflight,
bridge, controller lifecycle, promotion, preview, base AQ
transition과 IQ terminal은 모두 immutable non-overwrite publication을 사용한다. 재개는 같은 exact
plan/request/result/receipt bytes만 채택하고 다음 변경을 fail-closed한다.

- SceneSpec, MaterialPlan baseline, UV fingerprint 또는 generated source 변경
- authorization/profile/session/controller-input/predecessor 변경
- output inventory나 stored result bytes 변경
- duplicate budget/action/receipt 소비

canonical write 뒤 실패는 기존 material-phase rollback만 사용한다. 역사 evidence를 수리하거나
과거 실패를 성공으로 재분류하지 않는다.

## 11. 공개 표면

Material Loop는 기존 ImageGen core 5개 CLI/MCP를 유지하면서 다음 9개 CLI와 동등한 9개 MCP host
facade를 additive하게 제공한다.

| CLI | MCP |
|---|---|
| `codex-imagegen-material-bridge-plan` | `plan_codex_imagegen_material_bridge` |
| `codex-imagegen-material-exact-adoption-preflight` | `preflight_codex_imagegen_material_exact_adoption` |
| `codex-imagegen-material-bridge-status` | `get_codex_imagegen_material_bridge_status` |
| `codex-imagegen-material-bridge-run` | `run_codex_imagegen_material_bridge` |
| `codex-imagegen-material-promote` | `promote_codex_imagegen_material` |
| `codex-imagegen-material-resume` | `resume_codex_imagegen_material` |
| `codex-imagegen-native-normalize` | `normalize_codex_imagegen_native_output` |
| `codex-imagegen-semantic-review-status` | `get_codex_imagegen_semantic_review_status` |
| `autonomy-v2-codex-imagegen-continue` | `continue_autonomy_v2_codex_imagegen` |

이 표면은 API key, ImageGen API 호출, semantic observation 작성, approval 작성, arbitrary output,
canonical 직접 write 또는 destination write를 제공하지 않는다.

## 12. 검증과 활성화 경계

fake family, historical built-in source와 실제 production 승인은 분리한다.

- fake family는 contract와 실제 Blender material/IQ mechanism을 검증할 수 있지만 actual ImageGen이
  아니다.
- 보존된 historical PNG를 새 run에 채택하는 것은 fresh ImageGen invocation이 아니다.
- current-task non-human semantic review가 `review_required`이면 promotion 전에 멈춘다.
- 승인 없는 raw GLB/FBX clean import는 production package 또는 terminal evidence가 아니다.
- 사람 review와 destination runtime parity는 검증되지 않았다.

따라서 두 experimental profile은 계속 비활성이다. 최종 실행 명령과 결과는 verification 문서에만
기록한다.
