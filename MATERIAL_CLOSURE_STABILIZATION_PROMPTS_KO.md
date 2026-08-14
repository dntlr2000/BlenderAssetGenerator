# Material Closure Stabilization 재사용 프롬프트 모음

이 문서는 Material Closure `0.1.0`을 운용하거나 검토할 때 사용할 저장소 공통 프롬프트 모음이다.
특정 자산의 job/session/semantic ID, 실제 SHA-256, sequence, retry 이름은 넣지 않는다. 해당 값은
실행 시 current evidence에서 읽어 `<...>` placeholder를 채운다.

프로젝트는 계속 `0.9.0`, canonical SceneSpec은 계속 `0.2.0`이다. Material Closure는 기존
standard/background/AQ/ImageGen 계약을 재해석하지 않는 additive companion이며, profile 상태를
활성화하지 않는다.

## 1. 공통 placeholder

| Placeholder | 의미 |
|---|---|
| `<JOB_ID>` | 기존 lowercase job ID |
| `<SOURCE_SESSION_ID>` | 읽기 전용으로 동결할 기존 AQ session |
| `<REPAIR_SESSION_ID>` | 새 unique `material-repair-*` session |
| `<SOURCE_BINDING_PATH>` | strict `MaterialClosureSourceBinding` artifact |
| `<REPAIR_SOURCE_BINDING_PATH>` | strict `MaterialRepairSourceBinding` artifact |
| `<CANDIDATE_MATERIAL_PLAN_PATH>` | current candidate MaterialPlan |
| `<SOURCE_MATERIAL_GRAPH_PATH>` | 불변 source MaterialGraph |
| `<PREFLIGHT_REQUEST_PATH>` | closure/rebind/snapshot/budget에 결속된 request |
| `<PREFLIGHT_REPORT_PATH>` | passed preflight report |
| `<APPEARANCE_APPROVAL_PATH>` | 사용자가 직접 결정한 exact appearance approval |
| `<EXPECTED_SHA256>` | 현재 파일을 재해시해 얻은 exact digest |

## 2. 모든 프롬프트의 절대 경계

- `workspaces/*/input/`, 과거 request/plan/approval/state/receipt/result를 수정하지 않는다.
- 기존 terminal AQ session을 재개하거나 새 AQ state로 덮어쓰지 않는다. companion status/supersession만 발행한다.
- dependency는 caller가 고른 목록이 아니라 graph-derived closure로 재귀 수집한다.
- graph rebinding은 host가 source를 보존한 별도 derivative로 수행하며 semantic payload를 바꾸지 않는다.
- approval 전에 closure, rebinding, budget, surface detail/UV, real Blender shadow compile, 실제 neutral preview를 모두 검증한다.
- technical path/hash repair에는 사용자 승인을 요구하지 않는다. appearance/scope 변화만 전문 승인 경계로 보낸다.
- `MaterialAppearanceApproval`은 사용자의 명시적 current 결정을 exact artifact로 받은 경우에만 발행한다.
- ControllerResult를 손으로 만들지 않는다. ControllerExecutor가 closure projection과 동일한 map으로 한 번만 실행한다.
- canonical MaterialPlan/blend는 기존 host material promotion authority만 쓴다. 실패 시 기존 rollback authority를 사용한다.
- destination project를 쓰지 않고, review evidence와 production package를 동일시하지 않는다.
- fake fixture, historical ImageGen, dry-run, shadow compile을 human review나 production promotion으로 보고하지 않는다.

## 3. Read-only 기준선 및 incident 감사 프롬프트

```text
<JOB_ID> / <SOURCE_SESSION_ID>의 material 상태를 read-only로 감사해 줘.

1. public status authority로 state chain을 재구성하고 latest raw state, terminal, cancellation,
   controller invocation, budget, promotion, rollback, IQ 진입 여부를 exact hash로 확인해.
2. canonical SceneSpec, ModelingPlan, MaterialPlan 또는 strict absence, blend, inventory,
   validation, build provenance를 fresh rehash하고 서로의 현재성을 비교해.
3. pending retry마다 plan, approval bytes 또는 approval absence, source state를 분리해 기록해.
4. preflight 실패, asset quality failure, controller failure, promotion failure, rollback success/failure를
   서로 다른 상태로 분류해.
5. 기존 evidence를 수정하거나 pending retry를 실행하지 말고 discrepancy/failure/supersession에
   필요한 exact 입력만 보고해.
```

## 4. Closure와 host graph rebinding 준비 프롬프트

```text
<JOB_ID>에서 <SOURCE_BINDING_PATH>를 strict-load해 Material Closure를 준비해 줘.

- canonical geometry와 MaterialPlan-or-absence, candidate plan, source graph, references,
  ShaderRecipe, TextureManifest, 모든 image/channel/mask, surface-detail/UV evidence,
  ImageGen/normalization/selection/authoring evidence, authorization/profile/budget/rollback baseline을
  graph-derived 방식으로 재귀 수집해.
- Windows case-fold path collision, duplicate semantic/material ID, link/escape, missing/stale hash,
  wrong job/workflow/dispatch/session, reduced dependency map을 fail closed 처리해.
- host가 request-owned canonical path로 path/hash-only MaterialGraph derivative를 만들고
  rebind plan/receipt/source/rebound bytes를 모두 closure에 포함해.
- planned material_plan/material_graph는 exact hash, completion은 circular hash가 없는 strict
  structural binding으로 선언해.
- request immutable map == assignment immutable map == completion immutable map ==
  closure immutable projection인지 확인해.
- closure와 receipt를 run-owned immutable path에 발행하고 controller는 아직 실행하지 마.
```

## 5. 승인 전 종합 preflight 프롬프트

```text
<JOB_ID>의 <PREFLIGHT_REQUEST_PATH>를 current evidence로 검증하고 canonical-write-free preflight를 실행해 줘.

순서는 closure replay → graph rebinding replay → material contracts → surface-detail/UV/inventory →
build provenance → bounded resource reservation → Blender 5.0.1 graph/full-scene shadow compile →
inspect/validate → fixed neutral preview야.

모든 artifact와 canonical baseline을 실행 전후 재해시해. 캐시는 request+closure+rebound hash가 exact하고
모든 output을 다시 검증한 경우에만 zero-cost adopt해. session-wide resource cap을 넘지 마.

성공하면 passed report, resource receipt, shadow receipt, 실제 PNG preview manifest만 발행하고
approval/controller/canonical/IQ/destination write는 0으로 유지해. 실패하면 strict framework failure를
발행하고 asset quality failure라고 표현하지 마.
```

## 6. Material appearance 승인 요청 프롬프트

```text
<PREFLIGHT_REPORT_PATH>를 current canonical bytes에 대해 다시 검증해 줘.

passed closure/rebind/preflight/shadow receipt, neutral preview, consistency, rollback baseline, budget가
모두 current일 때만 사용자에게 candidate MaterialPlan SHA, rebound graph SHA, preview SHA,
material/semantic scope, UV fingerprint, known limitation을 보여 줘.

사용자가 명시적으로 승인 또는 거부하기 전에는 MaterialAppearanceApproval을 만들지 마.
generic workflow approval, technical repair approval, policy authorization을 대체물로 사용하지 마.
사용자 결정이 있으면 caller-authored exact approval을 specialized host publisher로 한 번 발행해.
```

## 7. 승인 후 exact controller 및 promotion 프롬프트

```text
<APPEARANCE_APPROVAL_PATH>가 current preflight/closure/rebound/preview에 exact하게 결속됐는지 확인해.

host가 single-use consumption receipt를 먼저 발행하고, closure projection만으로 ControllerExecutionRequest를
만들어 bounded fixed controller를 한 번 실행해. 허용 output 외 파일, reduced map, partial output,
canonical mutation, stale approval은 거부해.

ControllerResult를 받은 뒤 같은 boundary를 다시 검증하고 기존 material_phase host authority에만
promotion을 위임해. CAS, Blender rebuild/inspect/validate, receipt 또는 rollback을 확인해.
MaterialPhaseReceiptV2가 실제로 존재할 때만 AQ quality boundary를 한 action 진행해.
```

## 8. 새 material repair session 프롬프트

```text
<JOB_ID>의 terminal <SOURCE_SESSION_ID>를 재개하지 말고 <REPAIR_SESSION_ID>를 새로 준비해 줘.

<REPAIR_SOURCE_BINDING_PATH>의 SceneSpec, ModelingPlan, blend, geometry validation/approval,
latest successful rollback, MaterialPlan-or-absence, primary reference, UV fingerprint, target scope,
framework failure, reusable ImageGen evidence를 fresh rehash해. geometry hash가 하나라도 다르면 blocked로 멈춰.

자동 단계는 geometry 확인 → candidate 준비 → closure → rebinding → preflight → shadow compile →
neutral preview → approval request까지만 실행해. geometry/canonical/destination write, synthetic authority,
synthetic approval, approval consumption, controller invocation은 모두 0이어야 해.

passed preview와 exact candidate가 준비되면 attempt state를 approval_pending으로 발행하고 멈춰.
```

## 9. Retry/rollback 복구 프롬프트

```text
기존 retry는 절대 실행하지 말고 현재 state와 framework failure에 exact하게 supersede해 줘.
approval이 있었던 retry는 그 bytes를 보존하고, 없었던 retry는 expected path와 observation state에
결속된 explicit absence를 먼저 발행해. 동일 request를 재실행하지 마.

새 transient retry는 controller가 output을 하나도 만들지 않았고 canonical write 전에 outcome이
확정됐으며 closure/candidate/request bytes가 동일하고 retry budget이 남은 경우 한 번만 허용해.
byte 변화가 있으면 새 closure/preflight/preview/approval부터 시작해.
```

## 10. 검증 및 최종 보고 프롬프트

```text
Material Closure 변경을 검증해 줘.

- strict schema parity와 unknown/path/hash 음성 테스트
- graph-derived completeness와 reduced map rejection
- rebind diff allowlist와 source immutability
- missing dependency / UV conflict가 approval/controller 전에 차단됨
- resource budget/cache/tamper/crash adoption
- explicit approval 및 single-use consumption
- ControllerExecutor exact adoption과 host promotion/rollback
- status projection과 terminal historical session
- job-specific framework literal scan
- procedural, ImageGen+localized detail, crystal/emission/alpha 실제 Blender 5.0.1 fixture
- standard/background/AQ v1/AQ v2/ImageGen/V0.7–V0.9 회귀
- Ruff, full pytest, doctor, blender-compat, instruction/schema/repository parity, diff-check

실행한 명령과 exact 결과만 기록하고 실행하지 않은 gate는 unverified로 남겨. fake, historical,
actual Blender, actual asset, human approval, production package를 각각 구분해.
```

## 11. 공개 surface 확인

CLI/MCP는 최소 다음 동등 기능을 제공한다.

```text
material-closure-plan
material-closure-status
material-graph-rebind
material-preflight-run
material-preflight-status
material-shadow-compile
material-appearance-approve
material-state-consistency
material-framework-failure-status
material-retry-supersede
material-repair-session-plan
material-repair-session-run
```

모든 mutating surface는 immutable publication 또는 기존 host authority로만 전달한다. CLI/MCP가 approval,
ControllerResult, canonical state, destination output을 합성하지 않는다.

## 12. scope-change material identity split 라우팅

```text
Material Closure가 object material assignment 또는 material identity 추가 때문에 scope_change를
보고하면 closure validator, spatial ownership 또는 approval requirement를 완화하지 마.

<JOB_ID>의 current canonical bytes와 기존 immutable identity-split planning evidence를 exact-load하고
Material Identity Split 0.1.0으로 paired SceneSpec/ModelingPlan 후보, semantic clone, exact diff,
isolated Blender shadow와 invariant를 검증해. 통과하면 ApprovalRequest만 게시하고
framework_ready_for_explicit_scope_approval에서 멈춰.

사용자의 별도 explicit root-scope 결정 없이는 approval, consumption, ApplyIntent, canonical apply,
새 material repair, controller, promotion, IQ, package 또는 destination write를 수행하지 마.
```

Material Identity Split의 전체 reusable prompt와 apply/recovery 경계는
`MATERIAL_IDENTITY_SPLIT_PROMPTS_KO.md`를 따른다.

## 13. 다음 단계인 Standard ImageGen 시작 조건

Standard Codex ImageGen material companion 작업은 다음이 모두 충족된 뒤 별도 작업으로 시작한다.

1. Material Closure focused/full/real-Blender gate가 통과했다.
2. 현재 repair asset이 approval-pending까지 실제 dry-run을 통과했다.
3. 서로 다른 실제 자산 3종 이상의 material regression이 통과했다.
4. specialized approval과 rollback/state consistency가 검증됐다.
5. AQ v2와 ImageGen overlay는 계속 `disabled_experimental`이다.

Standard 통합은 기존 `standard` 승인 중심 절차를 유지하는 optional material companion이어야 하며,
새 자동 실행 정책이나 destination write 권한을 만들지 않는다.

이 목록은 다음 작업의 acceptance checklist이지 현재 완료 선언이 아니다. 실행자는
`VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md`의 latest actual result를 먼저 확인하고,
`unverified`, `not_run` 또는 preflight failure를 성공으로 승격하지 않는다.
