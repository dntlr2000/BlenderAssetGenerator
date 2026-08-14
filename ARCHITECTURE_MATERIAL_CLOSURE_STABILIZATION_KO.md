# AQ v2 Material Closure Stabilization 0.1.0 아키텍처

> 상태: additive companion 계약과 host/public surface 구현, focused host 검증 및 actual
> Blender 승인 전 fixture 완료. Project `0.9.0`, canonical SceneSpec `0.2.0`, 기존
> V0.4~V0.9와 AQ 계약의 의미는 유지한다. 최종 전체 회귀는 `1750 passed, 62 skipped,
> 8 warnings`로 통과했지만 full authorized promotion은 아직 미검증이다. 이 문서는 기존
> history를 migration하거나 실험 profile을 활성화하지 않는다.

## 1. 해결할 framework 결함

기존 material 흐름은 ControllerExecutionRequest, assignment, completion과 host
promotion validator가 각자 dependency map을 조립할 수 있었다. 서로 같은 누락 집합을
가리키면 map equality는 통과하지만 ShaderRecipe, TextureManifest, channel, reference 또는
MaterialGraph provenance 누락은 controller 실행 뒤 promotion에서야 발견됐다.

새 정상 경로는 다음 순서를 고정한다.

```text
geometry validation
→ candidate MaterialPlan/MaterialGraph staging
→ MaterialDependencyClosure
→ host-only MaterialGraph provenance rebinding
→ MaterialPromotionPreflight
→ isolated Blender shadow compile and neutral preview
→ exact MaterialAppearanceApproval
→ one exact-adoption controller invocation
→ existing host material promotion/rollback authority
→ MaterialPhaseReceiptV2
→ IQ 0.2
```

## 2. 권위 경계

- collector와 preflight는 candidate/staging derivative만 작성한다.
- graph rebinding은 path/hash만 바꾸며 material ID, layer, mask, channel, shader 값을
  변경하지 않는다.
- controller는 승인된 exact bytes를 request-owned output root에 게시하고 canonical을
  쓰지 않는다.
- `validate_and_promote_material_controller_result_v2`가 유일한 canonical MaterialPlan
  promotion, rebuild, validation, rollback authority로 남는다.
- preflight의 조기 검증과 promotion의 최종 재검증을 모두 유지한다.
- generic workflow approval과 PolicyAuthorization은 MaterialAppearanceApproval을 대체하지
  않는다.

## 3. 단일 dependency closure와 projection

`MaterialDependencyClosure 0.1.0`은 canonical/candidate SceneSpec, ModelingPlan,
MaterialPlan baseline 또는 explicit absence, candidate plan/graph, 모든 ShaderRecipe,
TextureManifest, channel/mask/reference, surface-detail/UV evidence, ImageGen chain,
phase profile, authorization, geometry validation, build provenance와 rollback baseline을
결정론적으로 정렬한다.

각 entry는 role, contained POSIX path, SHA-256, byte size, source kind, required 여부,
producer, dependency parent, semantic/material ID와 canonical/staging/request-owned scope를
가진다. duplicate path, conflicting hash, case-fold collision, link/escape, stale bytes,
missing required dependency를 fail-closed로 거부한다.

하나의 closure에서 다음 두 projection만 만든다.

- immutable input projection: request, assignment, controller input과 completion이 동일 사용
- planned output projection: exact plan/graph bytes와 completion의 schema/field binding

completion은 assignment/execution/map을 포함하므로 closure가 completion byte hash를 다시
포함하면 순환 hash가 된다. 따라서 plan/graph는 exact hash로, completion은 strict 구조와
closure hash 결속으로 검증한다.

### 3.1 source binding → rebinding → final closure 순서

Rebinding output을 final closure에 포함하면서 closure를 rebinding plan의 선행 입력으로 쓰면
순환 dependency가 된다. 따라서 host publication 순서는 다음과 같다.

```text
MaterialClosureSourceBindingArtifact
→ MaterialGraphRebindingPlan(source_binding exact artifact)
→ rebound_material_graph.json + MaterialGraphRebindingReceipt
→ final MaterialDependencyClosure
→ MaterialDependencyClosureReceipt
```

source binding은 source graph, candidate MaterialPlan, canonical MaterialPlan observation과
run-owned snapshot 또는 strict absence, rollback baseline, source mode별 typed evidence와
canonical run-owned rebind plan/receipt/rebound 경로를 선언한다. final collector는 plan, receipt,
source graph와 rebound graph의 exact bytes를 모두 entry로 수집하고 rebound graph에서 graph
dependency를 재귀 추적한다. planned MaterialPlan/graph hash는 closure entry와 같아야 한다.

### 3.2 source mode

- `procedural`: reference authority와 primary reference만 필수이며 ImageGen/manual root를 받지 않는다.
- `manual_image`: exact manual image root를 추가로 요구한다.
- `imagegen`: provider profile, assignment, completion, generated-image evidence, normalization
  plan/receipt, semantic review, selection, adoption, MaterialAuthoring request/manifest/receipt의
  전체 typed chain을 요구한다. 일부만 제공한 ImageGen root는 fail closed다.

## 4. graph rebinding과 preflight

Rebinding은 source graph를 수정하지 않고 immutable derivative를 게시한다. before/after
diff는 허용된 provenance path/hash field만 포함해야 한다. semantic payload가 달라지면
`no_visual_change`가 아니며 새 candidate와 material review가 필요하다.

종합 preflight는 closure freshness, material contracts, graph identity/provenance,
surface-detail coverage, UV fingerprint, budget, rollback baseline을 검사한 뒤 isolated
shadow root에서 Blender 5.0.1 graph compile, scene build, inspect, validate, material
assignment/UV/node inventory와 neutral preview를 실행한다. 실패 시 approval, controller
request, promotion intent, canonical write를 생성하지 않는다.

## 5. approval과 state projection

사용자 승인은 geometry, material appearance/promotion, optimization/delivery 세 경계에만
존재한다. 기술적 closure 재수집, path rebinding, serialization, manifest normalization에는
승인을 요구하지 않는다.

기존 `AutonomyStateV2`를 확장하거나 역사 state를 재작성하지 않고 다음 companion을 둔다.

- `MaterialAttemptState`
- `MaterialCanonicalSnapshot`
- `MaterialStateConsistencyReport`
- `AQV2StatusProjection`

combined status는 raw AQ state, material attempt, current canonical snapshot, closure,
preflight, approval, controller/promotion/rollback과 consistency를 함께 보여준다. rollback 뒤
active candidate가 남아 있는 것처럼 표시하지 않는다.

승인 생성 조건은 passed closure/rebinding/preflight/shadow receipt, 실제 preview,
state/canonical consistency, rollback baseline과 남은 budget이 모두 current인 경우다. 승인은
candidate MaterialPlan, rebound graph, closure, preflight, preview, canonical SceneSpec/Blend와 UV
fingerprint를 exact hash로 결속한다. 사용자 결정을 관찰하지 않은 host는 승인을 합성할 수 없고,
consumption receipt가 이미 있으면 재사용할 수 없다.

## 6. retry, supersession과 repair session

같은 closure의 controller retry는 output 전 명확한 종료 또는 canonical-write 전 timeout,
exact same bytes, zero-output evidence와 별도 retry budget이 있을 때 최대 한 번이다. 외관
bytes 변경은 새 closure/preflight/preview/approval을 요구한다.

기존 incident session은 append-only history로 보존한다. terminal state는 다시 transition하지
않고 `MaterialFrameworkFailureReport`, `MaterialRetrySupersessionReceipt`와 combined projection이
실행 불가 상태를 표시한다. 새 material repair session은 exact geometry/source binding만
재사용하며 scope나 approval을 합성하지 않는다.

## 7. 비목적

- 기존 state, approval, rollback, controller result의 in-place 수정
- standard/background/AQ v1 동작 변경
- experimental profile 자동 활성화
- arbitrary Blender Python/node/shell authority
- destination project write
- preflight를 production promotion이나 human review로 표현

## 8. 계약과 service 경계

모든 신규 top-level 계약은 strict Pydantic, `extra=forbid`, finite number, normalized relative
POSIX path, exact SHA-256, job/workflow/dispatch/session과 producer/version/time 결속을 사용한다.
기존 evidence는 자동 migration하지 않는다.

| 책임 | 계약/서비스 |
|---|---|
| root 선언과 closure | `MaterialClosureSourceBindingArtifact`, `MaterialDependencyClosure`, receipt, collector/projector |
| provenance derivative | `MaterialGraphRebindingPlan`, `MaterialGraphRebindingReceipt`, host rebinding service |
| 승인 전 검사 | `MaterialPromotionPreflightRequest/Report/Failure`, budget/resource receipt, shadow/preview receipt |
| 사용자 경계 | `MaterialApprovalImpactReport`, `MaterialAppearanceApproval`, consumption receipt |
| lifecycle | `MaterialCanonicalSnapshot`, `MaterialAttemptState`, `MaterialStateConsistencyReport`, `AQV2StatusProjection` |
| failure/recovery | framework failure/discrepancy, retry approval absence/supersession, repair binding/plan/supersession |
| incident source | `JobSpecificRecoverySourceInventory` |

`material_closure/`가 contract와 pure/host service의 기준 구현이다. `material_preflight/`,
`material_promotion/`, `material_recovery/`는 중복 authority가 아니라 기존 public facade를 얇게
분리한다. 기존 `material_phase_service.py`의 최종 검증을 제거하지 않는다.

신규 schema projection은 다음 파일로 고정한다.

```text
aq_v2_status_projection.schema.json
autonomy_v02_material_closure_promotion_boundary.schema.json
incident_state_discrepancy_report.schema.json
job_specific_recovery_source_inventory.schema.json
material_appearance_approval.schema.json
material_appearance_approval_consumption_receipt.schema.json
material_approval_impact_report.schema.json
material_aq_budget_observation.schema.json
material_attempt_state.schema.json
material_canonical_material_plan_absence.schema.json
material_canonical_snapshot.schema.json
material_closure_source_binding.schema.json
material_dependency_closure.schema.json
material_dependency_closure_receipt.schema.json
material_framework_failure_report.schema.json
material_graph_rebinding_plan.schema.json
material_graph_rebinding_receipt.schema.json
material_neutral_preview_manifest.schema.json
material_preflight_budget.schema.json
material_preflight_resource_receipt.schema.json
material_promotion_preflight_failure.schema.json
material_promotion_preflight_report.schema.json
material_promotion_preflight_request.schema.json
material_repair_session_plan.schema.json
material_repair_source_binding.schema.json
material_retry_approval_absence.schema.json
material_retry_supersession_receipt.schema.json
material_rollback_restoration_observation.schema.json
material_session_supersession_receipt.schema.json
material_shadow_compile_receipt.schema.json
material_state_consistency_report.schema.json
```

대표적인 immutable output layout은 다음과 같다.

```text
production/material_closure/<session>/source_binding.json
production/material_closure/<session>/graph_rebindings/<plan>/
production/material_closure/<session>/preflights/<request>/
production/material_closure/<session>/appearance_approvals/<approval>.json
production/material_repair/<repair-session>/plan.json
production/material_repair/<repair-session>/attempts/<attempt>/state-0001.json
```

실제 파일 존재와 hash가 권위이며 이 예시는 임의 caller output path를 허용하지 않는다.

## 9. 공개 surface

CLI와 MCP는 같은 12개 기능을 additive public surface로 제공한다.

```text
material-closure-plan          material-closure-status
material-graph-rebind          material-preflight-run
material-preflight-status      material-shadow-compile
material-appearance-approve    material-state-consistency
material-framework-failure-status
material-retry-supersede       material-repair-session-plan
material-repair-session-run
```

Focused host tests에서 12/12 registration과 schema/capability parity를 확인했다. 이 결과는 실제
사용자 승인, controller execution 또는 canonical promotion의 성공 증거가 아니다.

`material-appearance-approve`도 사용자 결정을 대신하지 않는다. caller-authored strict approval과
명시적 decision observation을 host가 current preflight에 대해 검증·게시할 뿐이다. repair run은
기본적으로 `approval_pending`에서 멈추며 승인, controller, canonical promotion을 자동 실행하지
않는다. 실제 공개/동등성 검증 상태는 검증 기록을 따른다.
