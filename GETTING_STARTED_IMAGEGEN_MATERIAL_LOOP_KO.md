# Codex ImageGen 0.2 Material Loop 시작 가이드

> 이 기능은 `disabled_experimental` profile의 host-side companion이다. Project `0.9.0`과
> canonical SceneSpec `0.2.0`은 유지된다. API key, OpenAI SDK/HTTP provider, 새 Codex task, daemon,
> user approval 또는 destination write를 제공하지 않는다.

## 1. 준비 조건

다음 evidence가 같은 job/workflow/dispatch/session/profile identity에 결속되어 있어야 한다.

- active AQ v2 RootAuthorization, plan, profile, budget와 current state
- canonical SceneSpec, geometry validation receipt와 current build provenance
- ImageGen plan/assignment/completion/candidate/quality/selection/terminal
- current-task `CodexImageSemanticReview`와, 다중 후보이면 exact companion selection receipt
- native normalization을 사용했다면 `CodexImageNativeCorePreparationReceipt`
- `ImageToMaterialAdoption 0.2.0`
- MaterialAuthoring `0.2.1` request/manifest/receipt와 모든 local texture output
- V0.5 bridge/normalized companion, MaterialGraph/ShaderRecipe/TextureManifest와 UV fingerprint
- `exact_adoption`이면 별도 actual Blender shadow preflight receipt
- previous canonical MaterialPlan 또는 exact absence evidence

변경 명령에는 두 opt-in을 함께 준다.

```powershell
--enable-v2 --enable-imagegen
```

이는 profile activation이나 production approval이 아니다.

## 2. native PNG 채택과 normalization

native output이 core assignment 크기와 다르면 core 계약을 완화하지 말고 세 action을 사용한다.

### 2.1 immutable original 채택

```powershell
uv run cbm codex-imagegen-native-normalize <JOB_ID> `
  --action adopt `
  --session-id <SESSION_ID> `
  --native-source <ABSOLUTE_PNG> `
  --allowed-source-root <ABSOLUTE_CONTAINED_ROOT> `
  --native-output-id <UNIQUE_ID> `
  --ordinal 0 `
  --output-role base_color `
  --enable-v2 --enable-imagegen
```

직접 role은 `base_color`, `decal_rgb`, `emission`, `opacity_source`만 허용한다. host는 source를
fresh decode/hash하고 run-owned immutable `original.png`로 한 번만 복사한다.

### 2.2 strict normalization 실행

별도 authoring 단계에서 current source/target과 requested operation에 결속된 plan을 만든 뒤 실행한다.

```powershell
uv run cbm codex-imagegen-native-normalize <JOB_ID> `
  --action execute `
  --normalization-plan <JOB_CONTAINED_PLAN_JSON> `
  --enable-v2 --enable-imagegen
```

pass-through, center crop, contain-pad와 explicit tile crop만 허용한다. silent stretch나 arbitrary
output path는 거부한다.

### 2.3 core completion 입력 준비

```powershell
uv run cbm codex-imagegen-native-normalize <JOB_ID> `
  --action prepare `
  --session-id <SESSION_ID> `
  --adoption-receipt <JOB_CONTAINED_ADOPTION_JSON> `
  --normalization-plan <JOB_CONTAINED_PLAN_JSON> `
  --receipt-contract-id <UNIQUE_RECEIPT_ID> `
  --enable-v2 --enable-imagegen
```

normalized bytes는 처음부터 새 core assignment candidate로 사용한다. 이미 선택된 과거 candidate에
derivative를 소급 연결하지 않는다.

`prepare`가 native `original.png`를 사용하면 normalization receipt는 exact adoption receipt를 함께
결속한다. 이후 replay는 assignment, immutable original, plan과 derivative를 재귀 검증하므로 receipt를
생략하거나 다른 original로 바꿀 수 없다.

같은 assignment의 core completion/selection까지 끝나면 host가
`CodexImageNativeCorePreparationReceipt`를 게시한다. 이 receipt는 adoption/original,
normalization plan/receipt/normalized image, completion/candidate/generated-image
evidence/quality/selection과 copied core image를 묶고 normalized-to-core exact byte identity를
검증한다. core `0.1.0` contract를 수정하지 않는다. 이후 bridge는 native-fed selected bytes를
감지하면 이 receipt를 필수로 요구한다.

## 3. semantic review와 다중 후보

status 명령은 기존 semantic evidence를 읽고 검증할 뿐 관찰을 작성하지 않는다.

```powershell
uv run cbm codex-imagegen-semantic-review-status <JOB_ID> <SESSION_ID>
```

항상 `human_reviewed=false`다. `review_required` 또는 `unavailable`을 deterministic score로
덮어쓰지 않는다. 후보가 둘 이상이면 모든 후보에 exact semantic review와 companion ranking
evidence가 필요하다. 누락/unresolved 후보가 하나라도 있으면 전체 selection이
`review_required`다.

선택 precedence는 file hard gate → deterministic quality → semantic outcome → material role →
repair cost → stable candidate ID다.

## 4. exact-adoption preflight와 bridge plan 게시

bridge plan은 job-contained strict JSON이며 canonical write 권한이 아니다.

`exact_adoption`을 선택하려면 먼저 V0.5 bridge receipt의 exact candidate plan/graph/dependency를
isolated shadow에서 실제 Blender whitelist compile한다.

```powershell
uv run cbm codex-imagegen-material-exact-adoption-preflight <JOB_ID> `
  --preflight-id <UNIQUE_PREFLIGHT_ID> `
  --v05-bridge-receipt <JOB_CONTAINED_V05_BRIDGE_RECEIPT_JSON> `
  --enable-v2 --enable-imagegen
```

이 명령은 `CodexImageV05ExactAdoptionPreflightReceipt`를 게시할 뿐 `ControllerResult`를 만들거나
canonical/destination을 쓰지 않는다. 기존 MaterialAuthoring `0.2.1` receipt는 계속
`staging_only=true`, `blender_compilation_status=not_run`이며 preflight가 그 bytes나 의미를 고치지
않는다. 작성할 bridge plan의 `exact_adoption_preflight`가 이 exact receipt를 가리켜야 한다.

```powershell
uv run cbm codex-imagegen-material-bridge-plan <JOB_ID> `
  --bridge-plan <JOB_CONTAINED_BRIDGE_PLAN_JSON> `
  --enable-v2 --enable-imagegen
```

계획은 current evidence를 fresh rehash하고 controller input, exact output root와 세 allowed outputs를
고정한다. `exact_adoption`은 expected hashes와 위 actual Blender shadow preflight를 모두 요구한다.
preflight가 없으면 `controller_authored_completion`을 사용하거나 evidence가 마련될 때까지 멈춘다.
다중 후보 bridge는 exact companion selection receipt를 필수로 결속하며 single-candidate bridge는 이를
가장할 수 없다.

## 5. 상태 조회

```powershell
uv run cbm codex-imagegen-material-bridge-status <JOB_ID> <SESSION_ID>
```

status에서 다음을 구분한다.

- current/stale/unverified
- controller input, exact request/result와 lifecycle
- material-loop/base AQ state와 next action
- selected candidate, native-to-core preparation, normalization, semantic/ranking과 MaterialAuthoring evidence
- promotion receipt, actual `MaterialPhaseReceiptV2`, preview와 IQ terminal
- delivery progress와 remaining companion budget

`material_promoted`/`waiting_for_quality`는 IQ pass가 아니다. `quality_approved`도 package 또는
destination 완료가 아니다.

## 6. controller 실행과 same-request resume

```powershell
uv run cbm codex-imagegen-material-bridge-run <JOB_ID> <SESSION_ID> `
  --timeout-seconds 900 `
  --enable-v2 --enable-imagegen
```

`controller_authored_completion`은 current Codex task가 request-owned workspace에 정확히
`material_plan.json`, `material_graph.json`, `completion.json`만 작성하는 경로다. output이 아직
없으면 같은 request에서 기다린다. 재호출은 새 request/invocation/budget을 만들지 않고 기존
workspace와 protected source를 다시 검증한다.

handwritten ControllerResult, extra/missing/empty/escaped output, source mutation과 duplicate invocation은
거부한다.

## 7. host promotion과 복구

completed ControllerResult가 current일 때만 실행한다.

```powershell
uv run cbm codex-imagegen-material-promote <JOB_ID> <SESSION_ID> `
  --preview-size 512 `
  --enable-v2 --enable-imagegen
```

이 명령은 기존 host material phase service를 호출해 graph compile, canonical MaterialPlan CAS,
Blender rebuild/inspect/validate와 actual `MaterialPhaseReceiptV2`를 만든 뒤 fixed neutral preview와
promotion companion을 결속한다. bridge가 canonical을 직접 쓰지 않는다.

crash 후에는 같은 idempotent 경계를 사용한다.

```powershell
uv run cbm codex-imagegen-material-resume <JOB_ID> <SESSION_ID> `
  --preview-size 512 `
  --enable-v2 --enable-imagegen
```

partial staging이나 오류 문자열만으로 success/rollback을 만들지 않는다. canonical write 뒤 실패는
기존 material-phase rollback evidence를 재검증한다.

## 8. IQ 경계로 진행

```powershell
uv run cbm autonomy-v2-codex-imagegen-continue <JOB_ID> <SESSION_ID> `
  --quality-submission <JOB_CONTAINED_IQ_SUBMISSION_JSON> `
  --enable-v2 --enable-imagegen
```

host는 current promotion closure와 actual MaterialPhaseReceiptV2를 확인한 뒤 기존 AQ/IQ supervisor의
한 action만 실행한다. base quality terminal이 이미 게시된 crash window에서는 exact terminal/freeze를
재검증해 companion 기록만 복구한다.

- passed → `quality_approved`와 exact source freeze
- needs_revision/unscorable → `review_required`
- blocked → freeze 없는 `blocked`

caller report나 user approval을 host가 합성하지 않는다.

## 9. delivery 경계

Material Loop 명령은 OptimizationApproval을 작성하지 않는다.

- `review_only`: quality-approved evidence 전달, package 없음
- `portable_gltf` / `portable_fbx`: 각각 독립 V0.7 review와 exact plan-hash 사용자 승인 필요
- 승인 없음: `waiting_for_v07_approval`에서 정지
- raw exporter/clean-import test: mechanism evidence일 뿐 production package/terminal이 아님

GLB 성공은 FBX 성공을 뜻하지 않고 어느 결과도 destination runtime parity를 뜻하지 않는다.

## 10. 공개 명령과 MCP

Material Loop는 다음 9개 CLI와 동등한 9개 MCP를 additive하게 제공한다.

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

기존 ImageGen core CLI/MCP 5개도 그대로 유지된다.

## 11. stale와 fail-closed

다음이 바뀌면 기존 bridge/request는 재사용할 수 없다.

- SceneSpec 또는 MaterialPlan baseline
- UV fingerprint, generated source, native adoption/normalization/core-preparation/semantic/ranking evidence
- exact-adoption preflight shadow input, compile report 또는 compiler artifact
- RootAuthorization, profile, session 또는 predecessor
- controller input, output inventory, stored result 또는 lifecycle receipt

history를 고치거나 stale evidence를 새 session으로 복사하지 말고 source 문제를 해결한 뒤 새 unique
plan/run을 만든다.

## 12. 현재 검증 한계

- historical built-in PNG 재사용은 fresh ImageGen invocation이 아니다.
- 해당 source의 current-task non-human semantic review는 `review_required`에서 멈췄다.
- fake four-family Blender 결과는 actual ImageGen이나 general quality를 증명하지 않는다.
- approval 없는 raw GLB/FBX clean import는 package acceptance가 아니다.
- human review와 destination runtime parity는 수행하지 않았다.
- 두 profile은 계속 `disabled_experimental`이다.

상세 계약은 [아키텍처](ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md), 테스트 범위는
[테스트 계획](TEST_PLAN_IMAGEGEN_MATERIAL_LOOP_KO.md), 실제 결과는
[검증 기록](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다.

## 13. Codex에 붙여 넣는 프롬프트

CLI를 직접 조합하지 않고 현재 Codex 작업에 목적과 안전 경계를 전달하려면
[Material Loop 실사용 프롬프트 모음](IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md)을 사용한다.
새 reference부터 전체 제작 단계를 조율할 때는
[새 레퍼런스 단계별 프롬프트](NEW_REFERENCE_VALIDATION_PROMPTS_KO.md)의 1.6과 5A를 사용한다.

저장소 내부 agent-authored step에는
[`prompts/imagegen_material_loop.md`](prompts/imagegen_material_loop.md)를 사용한다. 이 prompt는
별도 승인이나 provider 권한을 추가하지 않으며 다음 핵심 경계를 고정한다.

- current Codex task의 built-in ImageGen만 사용
- native original → normalization → native-core preparation exact closure
- `human_reviewed=false` semantic review와 다중 후보 precedence
- actual Blender shadow preflight가 없는 `exact_adoption` 거부
- 기존 ControllerExecutor와 host material promotion만 사용
- `material_promoted`, `quality_approved`, V0.7 approval/package/destination 완료 분리

가장 짧은 시작 요청은 다음과 같다.

```text
<JOB_ID> / <AQ_SESSION_ID>의 current AQ v2 geometry 결과에서
autonomous_static_prop_v2_codex_imagegen Material Loop를 disabled_experimental opt-in으로 시작해줘.
현재 Codex 작업의 built-in ImageGen만 사용하고 native 원본을 보존해.
semantic review는 human_reviewed=false로 기록하고, exact Blender preflight가 없으면
controller_authored_completion을 사용해. ControllerResult를 직접 쓰지 말고 기존
ControllerExecutor와 material_phase_service로만 promotion해.
MaterialPhaseReceiptV2 뒤 IQ 경계에서 멈추고, exact V0.7 승인 없이는 package를 만들지 마.
```

## 14. Stabilized preapproval 경로

Material Closure Stabilization이 적용된 새 attempt에서는 위 예시의 controller 실행 전에 다음을
추가한다.

```text
typed ImageGen source binding
→ host path/hash-only graph rebind
→ final graph-derived closure
→ surface-detail/UV/budget/canonical consistency preflight
→ actual Blender 5.0.1 full-scene shadow compile
→ actual neutral preview
→ approval_pending
```

이 경로가 통과하기 전에는 appearance approval을 요청하거나 controller를 실행하지 않는다.
`material-appearance-approve`는 사용자가 exact candidate/graph/preview를 명시적으로 결정한 뒤에만
사용한다. generic workflow approval, existing retry approval, PolicyAuthorization 또는 ImageGen
opt-in을 material appearance 승인으로 재사용하지 않는다.

terminal historical session은 resume하지 않고 material-only repair session을 새로 만든다. repair
session이 preview까지 통과해도 canonical promotion, `MaterialPhaseReceiptV2`, IQ와 package가 완료된
것은 아니다. 상세 재사용 프롬프트는
[Material Closure 프롬프트 모음](MATERIAL_CLOSURE_STABILIZATION_PROMPTS_KO.md)을 따른다.

현재 검증은 한 procedural actual-Blender preapproval fixture와 current incident의 승인 전
fail-closed 결과까지다. ImageGen+localized material의 이 전체 경로, 실제 사용자 승인 이후
controller/promotion과 `MaterialPhaseReceiptV2`는 아직 검증되지 않았다.

현재 검증은 한 procedural actual-Blender preapproval fixture와 current incident의 승인 전
fail-closed 결과까지다. ImageGen+localized material의 이 전체 경로, 실제 사용자 승인 이후
controller/promotion과 `MaterialPhaseReceiptV2`는 아직 검증되지 않았다.
