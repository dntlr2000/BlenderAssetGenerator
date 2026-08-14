# Codex ImageGen Material Loop 실사용 프롬프트 모음

이 문서는 사용자가 현재 Codex 작업에 복사해 붙여 넣을 수 있는
`autonomous_static_prop_v2_codex_imagegen`용 프롬프트 모음이다. 저장소의 현재 구현은
Project `0.9.0`, canonical SceneSpec `0.2.0`, Codex Built-in ImageGen core `0.1.0`,
MaterialAuthoring `0.2.1`과 additive Material Loop `0.1.0`을 유지한다.

이 profile은 계속 `disabled_experimental`이다. 프롬프트는 opt-in 의사를 표현하지만 profile
활성화, 사용자 승인, human review, production package acceptance 또는 destination parity를
자동으로 만들지 않는다.

상세 CLI 순서는 [Material Loop 시작 가이드](GETTING_STARTED_IMAGEGEN_MATERIAL_LOOP_KO.md),
계약과 권위 경계는 [아키텍처](ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md), 실제 확인된 범위는
[검증 기록](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다.

## 1. Placeholder

| Placeholder | 값 |
|---|---|
| `<JOB_ID>` | 기존 또는 새 lowercase job ID |
| `<AQ_SESSION_ID>` | current AQ v2 session ID |
| `<MATERIAL_FAMILY>` | `wood`, `signage_decal`, `emissive`, `crystal` 등 현재 목표 family |
| `<TARGET_MATERIAL_IDS>` | 변경을 허용할 stable material ID 목록 |
| `<TARGET_SEMANTIC_IDS>` | 대상 semantic ID 목록 |
| `<DELIVERY_PROFILES>` | `review_only`, `portable_gltf`, `portable_fbx`의 요청 조합 |
| `<NATIVE_SOURCE_PATH>` | 현재 Codex 작업이 만든 PNG 또는 허용된 historical PNG의 절대 경로 |
| `<QUALITY_SUBMISSION_PATH>` | current job 안의 strict IQ submission JSON 경로 |

Codex가 보고하지 않은 session ID, artifact path, SHA-256 또는 approval ID를 추측해 넣지 않는다.

## 2. 모든 프롬프트에 적용되는 경계

- 현재 Codex 작업의 built-in ImageGen만 사용한다. OpenAI API, SDK, API key, 외부 HTTP provider를
  추가하지 않는다.
- 저장소가 새 Codex 작업을 만들거나 앱 종료 뒤 자동 실행한다고 주장하지 않는다.
- `workspaces/*/input/`, canonical SceneSpec, geometry, semantic ID와 승인된 UV를 바꾸지 않는다.
- native PNG 원본을 immutable evidence로 보존하고, 크기·비율 변경은 별도 deterministic
  derivative와 receipt로만 수행한다.
- Codex semantic review는 `human_reviewed=false`다. 관찰이 없거나 불확실하면
  `review_required`에서 멈춘다.
- ImageGen pixels는 `base_color`, `decal_rgb`, `emission`, `opacity_source` 후보로만 사용한다.
  normal, roughness, metallic, height, displacement, AO와 tangent는 authoritative ImageGen
  channel로 채택하지 않는다.
- 기존 MaterialAuthoring `0.2.1` receipt의 `staging_only`와 compile `not_run` 의미를 바꾸지 않는다.
- `exact_adoption`은 exact candidate bytes에 대한 별도 actual Blender shadow preflight가 있을 때만
  사용한다. 그렇지 않으면 `controller_authored_completion` 또는 대기 상태를 사용한다.
- ControllerResult는 기존 ControllerExecutor가 발행한다. JSON을 손으로 합성하지 않는다.
- canonical MaterialPlan과 `.blend`는 기존 host material promotion service만 변경한다.
- `material_promoted`, `quality_approved`, review bundle, raw export와 production package completion을
  서로 같은 상태로 취급하지 않는다.
- OptimizationApproval, PolicyAuthorization, human review 또는 destination write를 합성하지 않는다.

## 3. 가장 짧은 전체 Material Loop 시작 프롬프트

Geometry promotion이 완료되고 Material Loop를 시작하려는 일반적인 경우다.

```text
<JOB_ID>의 current AQ v2 session에서 Codex Built-in ImageGen Material Loop를
disabled_experimental 명시적 opt-in으로 진행해줘.

- aq_session_id: <AQ_SESSION_ID>
- material_family: <MATERIAL_FAMILY>
- target_material_ids: <TARGET_MATERIAL_IDS>
- target_semantic_ids: <TARGET_SEMANTIC_IDS>
- requested_delivery_profiles: <DELIVERY_PROFILES>

먼저 read-only status로 RootAuthorization, profile, budget, current predecessor,
canonical SceneSpec, geometry receipt, build fingerprint, UV와 MaterialPlan baseline을 검증해.
stale, missing, tampered 또는 다른 session evidence가 있으면 아무것도 쓰지 말고 멈춰.

현재 Codex 작업의 built-in ImageGen만 사용하고 외부 API/provider나 새 Codex task를 만들지 마.
native 원본을 immutable evidence로 보존하고 deterministic normalization derivative만 사용해.
모든 후보에 current-task Codex semantic review를 만들되 human_reviewed=false로 기록해.
다중 후보이면 exact companion ranking/selection precedence를 적용하고 unresolved 후보가 있으면
review_required에서 멈춰.

MaterialAuthoring staging candidate를 만든 뒤 exact-adoption 조건을 실제 Blender shadow preflight로
증명할 수 있으면 exact_adoption을, 아니면 bounded controller_authored_completion을 사용해.
ControllerResult를 직접 쓰지 말고 기존 ControllerExecutor lifecycle을 사용해.
canonical promotion은 기존 material_phase_service만 호출하고 actual MaterialPhaseReceiptV2,
neutral preview와 companion receipt를 검증한 뒤 base AQ를 IQ 경계로 한 action만 재개해.

IQ pass 전에는 quality_approved라고 보고하지 마. V0.7 exact 사용자 승인 없이는
waiting_for_v07_approval에서 멈추고 package나 delivery terminal을 만들지 마.
마지막에는 current/stale/unverified, selected candidate, normalization/semantic 상태,
controller request/result, MaterialPhaseReceiptV2, base AQ next action, IQ/delivery 상태,
remaining budget와 latest failure를 보고해.
```

## 4. Read-only 상태 감사 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 ImageGen Material Loop 상태를 read-only로 감사해줘.

파일을 생성·수정하거나 controller를 실행하지 마. 다음을 fresh rehash해:
- base AQ plan/profile/budget/current state와 predecessor chain
- ImageGen assignment/completion/candidate/quality/core selection/terminal
- native adoption/normalization/native-core preparation
- semantic review와 multi-candidate companion selection
- ImageToMaterialAdoption, MaterialAuthoring와 V0.5 bridge/preflight
- controller input/request/result와 allowed output inventory
- promotion receipt, MaterialPhaseReceiptV2, neutral preview
- IQ terminal/freeze, delivery progress와 remaining budget

current, stale, unverified를 구분하고 정확한 next_action만 보고해.
missing evidence를 만들어 채우거나 실패 이력을 고치지 마.
```

## 5. Native 크기 불일치 처리 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 built-in ImageGen native PNG를 기존 core completion에
바로 끼워 넣지 말고 안전하게 준비해줘.

- native_source_path: <NATIVE_SOURCE_PATH>
- target material family: <MATERIAL_FAMILY>

원본 PNG를 fresh decode/hash하고 assignment-bound immutable original.png로 채택해.
원본 크기, alpha, ICC/color-space와 aspect ratio를 기록해.
current target과 requested operation에 결속된 normalization plan을 작성하고,
pass-through, center crop, contain+pad 또는 explicit tile crop 중 canonical geometry만 사용해.
silent stretch, arbitrary output path와 과거 selected candidate의 post-hoc 교체는 거부해.

normalized derivative로 새 core assignment/completion/selection을 처음부터 수행하고
CodexImageNativeCorePreparationReceipt로 original → normalization → copied core bytes →
completion/candidate/quality/selection을 exact하게 묶어. 원본과 derivative의 path, size,
SHA-256, operation과 review_required 여부를 보고하고 다음 material bridge 실행 전 멈춰.
```

## 6. Semantic review와 다중 후보 선택 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 ImageGen 후보 전부를 current-task Codex semantic review로 검사해줘.

unwanted text/object/background, material family와 role 적합성, signage/decal 용도,
wood grain 방향, emissive/crystal pattern, tile/repetition, lighting hotspot, perspective,
근접 한계와 경계 오염을 strict evidence로 기록해. human_reviewed=false를 유지하고
deterministic pixel score를 semantic 관찰로 가장하지 마.

후보가 둘 이상이면 모든 후보에 exact semantic review와 ranking evidence를 요구하고
file hard gate → deterministic quality → semantic outcome → material-role suitability →
repair cost → stable candidate ID 순서로 선택해. 가장 높은 deterministic score가 semantic
hard-fail이면 제외하고 다음 eligible 후보를 검토해. 하나라도 missing/unresolved이면
selected candidate 없이 review_required로 멈춰.
```

## 7. Exact-adoption preflight와 controller 실행 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 current V0.5 bridge candidate를 material controller에 연결해줘.

먼저 execution_mode를 추측하지 말고 V0.5 receipt와 exact candidate plan/graph/dependency를 검증해.
exact_adoption을 사용하려면 isolated shadow job에서 actual Blender whitelist compile을 실행하고
CodexImageV05ExactAdoptionPreflightReceipt를 게시해. 기존 staging receipt의 not_run 값을 고치거나
ControllerResult/canonical/destination write를 만들지 마.

preflight가 없거나 controller authoring이 필요하면 controller_authored_completion을 사용해.
request-owned workspace에는 material_plan.json, material_graph.json, completion.json 세 출력만
허용해. 기존 ControllerExecutor가 request/result를 발행하게 하고 extra/missing/changed output,
protected source mutation, wrong producer/profile/session과 duplicate invocation을 거부해.

waiting_for_output이면 새 request나 budget을 만들지 말고 같은 request의 exact resume 방법과
현재 workspace를 보고해.
```

## 8. Promotion과 중단 복구 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 completed material-controller result를 host promotion 경계에서 처리해줘.

먼저 exact bridge plan, controller input/request/result, current canonical observation,
immutable baseline snapshot과 promotion budget을 재검증해. 기존 material_phase_service를 통해서만
MaterialGraph compile, canonical MaterialPlan CAS, Blender rebuild/inspect/validate를 실행하고
actual MaterialPhaseReceiptV2와 rollback 또는 pre-write failure evidence를 발행해.

중단 이력이 있으면 새 controller invocation이나 promotion을 만들지 말고 existing request/result,
promotion intent, receipt, base state와 journal을 exact-adopt해. canonical이 old/candidate/third hash 중
어느 상태인지 구분하고 third hash나 mismatched intent는 fail-closed해.

성공 뒤 fixed neutral preview와 promotion companion을 결속하고 base AQ가 IQ submission을 기다리는
경계에서 멈춰. material_promoted를 IQ pass나 전체 workflow completion으로 설명하지 마.
```

## 9. IQ 제출과 delivery 경계 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 ImageGen material promotion을 기존 IQ 0.2 경계로 한 단계 진행해줘.

- quality_submission_path: <QUALITY_SUBMISSION_PATH>

current MaterialPhaseReceiptV2, canonical MaterialPlan/blend, build provenance, geometry receipt,
generated/derived evidence, graph compile와 neutral preview를 재귀 검증해.
caller submission을 host가 새로 합성하거나 점수를 유리하게 고치지 마.

passed이면 exact QualityApprovedSourceFreeze와 quality_approved companion을 기록해.
needs_revision/unscorable이면 review_required, authoritative hard failure이면 blocked/failed로 멈춰.
base quality state 기록 뒤 companion terminal 전 crash 이력이 있으면 동일 submission으로 terminal만
복구하고 IQ를 다시 실행하지 마.

delivery profile이 review_only이면 package 없이 검토 경계만 보고해.
portable_gltf/portable_fbx이면 같은 freeze에서 서로 독립된 V0.7 review plan을 준비하되
exact OptimizationApproval이 없으면 waiting_for_v07_approval에서 멈춰.
GLB 결과를 FBX 증거로 재사용하지 말고 destination project를 수정하지 마.
```

## 10. Historical actual source를 감사할 때

```text
<JOB_ID>의 historical built-in ImageGen PNG를 current contract에 재사용 가능한지 감사해줘.

- native_source_path: <NATIVE_SOURCE_PATH>

이 작업을 fresh built-in ImageGen invocation이라고 기록하지 마. 원본 bytes와 기록된 prompt SHA를
검증하고 새 unique assignment에서 immutable native adoption과 normalization만 수행해.
current-task semantic review evidence가 실제로 없으면 pass를 합성하지 말고 review_required에서 멈춰.
human_reviewed=false를 유지하고 canonical MaterialPlan, MaterialPhaseReceipt, IQ pass, package 또는
destination parity를 생성·주장하지 마. exact source hash와 멈춘 경계를 보고해.
```

## 11. 실패 후 안전한 재개 프롬프트

```text
<JOB_ID> / <AQ_SESSION_ID>의 ImageGen Material Loop 실패를 새 실행 없이 진단하고 재개 가능성을 판단해줘.

먼저 status와 append-only journal을 읽고 실패 지점을 native normalization, semantic review,
controller waiting/result, pre-write promotion, canonical replace/rollback, MaterialPhaseReceipt,
state transition, IQ terminal/freeze 또는 delivery review로 분류해.

동일 exact request/intent/receipt를 adopt할 수 있을 때만 기존 resume 경계를 사용해.
오류 문자열만으로 success나 rollback evidence를 만들지 마. source/SceneSpec/UV/MaterialPlan/profile/
authorization가 바뀌었으면 stale로 종료하고 새 unique plan이 필요하다고 보고해.
사용자 승인이나 budget을 새로 만들지 말고, 재사용할 artifact와 거부 이유를 exact path/SHA로 보고해.
```

## 12. 보고할 상태의 정확한 의미

| 상태 | 의미 | 뜻하지 않는 것 |
|---|---|---|
| `controller_promotion_required` | core staging/adoption 완료 | canonical material promotion |
| `promoting_material` | host promotion 진행/복구 중 | 성공 |
| `material_promoted` | canonical material과 receipt 결속 성공 | IQ pass, package |
| `waiting_for_quality` | exact IQ submission 대기 | quality approval |
| `quality_approved` | IQ pass와 source freeze | V0.7 approval, package, destination 완료 |
| `review_required` | 사람 또는 별도 evidence 검토 필요 | 실패 은폐, human review 완료 |
| `waiting_for_v07_approval` | exact optimization-plan 승인 대기 | 자동 승인 가능 |
| `approval_pending` | closure/preflight/preview 완료, appearance decision 대기 | approval 생성, controller/promotion 완료 |

## 13. 현재 검증 한계

- Fake four-family Blender fixture는 material/IQ mechanism evidence이며 actual ImageGen이 아니다.
- 보존된 historical PNG는 current-task review boundary까지만 확인됐고 fresh invocation이 아니다.
- 승인 없는 raw GLB/FBX clean import는 production package acceptance가 아니다.
- Human review, 목적지 runtime parity, 임의 자산의 품질 개선과 profile activation은 검증되지 않았다.

## 14. Material Closure Stabilization을 적용하는 공통 프롬프트

아래 block은 새 stabilized attempt에만 사용한다. 기존 ImageGen core/Material Loop history를 새
contract로 rewrite하지 않는다.

```text
<JOB_ID> / <AQ_SESSION_ID>의 ImageGen material candidate를 controller 전에 Material Closure 0.1.0으로
검증해줘.

1. source_mode=imagegen strict source binding으로 provider profile, assignment, completion,
   generated-image evidence, normalization plan/receipt, semantic review, selection, adoption,
   MaterialAuthoring request/manifest/receipt와 primary/reference authority를 current hash로 결속해.
2. host가 source graph를 보존한 canonical run-owned derivative에서 provenance path/hash만 rebind해.
   material ID, layer, mask, channel, shader parameter가 바뀌면 중단하고 새 review가 필요하다고 보고해.
3. rebind plan/receipt/source/rebound graph와 candidate plan, 모든 ShaderRecipe/TextureManifest/image/
   channel/mask/reference, surface-detail/UV, canonical baseline과 rollback을 graph-derived closure에 넣어.
4. request/assignment/completion map을 closure projection 하나에서만 만들고 reduced map을 거부해.
5. approval 전에 finite budget, consistency, full-scene Blender 5.0.1 shadow compile과 실제 neutral
   preview를 검증해. 실패하면 framework failure를 발행하고 approval/controller/canonical write는 0으로 유지해.
6. 성공하면 approval_pending에서 멈춰. 사용자가 exact candidate/graph/preview를 명시적으로 결정하기
   전에는 MaterialAppearanceApproval을 만들지 마. existing technical retry approval이나 generic
   workflow approval을 재사용하지 마.
```

terminal AQ session에는 이 block으로 controller를 재개하지 않는다. 별도 material repair session의
preapproval 단계로만 사용한다. 상세 placeholder와 승인 후/rollback prompt는
[Material Closure 프롬프트 모음](MATERIAL_CLOSURE_STABILIZATION_PROMPTS_KO.md)을 따른다.

Material Closure가 shared material identity 때문에 `scope_change`를 반환하면 기존 ImageGen evidence를
새 material ID의 권한으로 재분류하거나 appearance approval로 우회하지 않는다. 별도
[Material Identity Split 프롬프트](MATERIAL_IDENTITY_SPLIT_PROMPTS_KO.md)로 paired canonical 후보와
root-scope ApprovalRequest까지만 검증하고, 사용자 결정 전에는 apply 또는 ImageGen material loop를
재개하지 않는다.
