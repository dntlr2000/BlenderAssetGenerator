# AQ Approval Envelope 0.3 아키텍처

## AQ North Star

지원 범위 안의 새 정적 소품 작업은 최초 사용자 요청 한 번으로 시작하며,
사용자가 최초 요청에서 허용한 scope, budget, provider 및 delivery 범위 안에서는
routine user approval 없이 production delivery 또는 review terminal까지 진행되어야 한다.

Dependency closure, provenance, manifest, path rebinding, preflight,
technical retry, controller retry, rollback과 deterministic identity normalization은
사용자 승인 대상이 아니다.

추가 사용자 결정은 최초 권한 범위를 벗어나는 실제 scope, reference,
target, budget, delivery, destination write 변경 또는
레퍼런스 증거로 해결할 수 없는 중요한 디자인 선택에만 요구한다.

모든 AQ 기능은 정상 작업의 사용자 승인 수를 줄이는지, 유지하는지, 늘리는지를 기록한다.
사용자 승인 수를 늘리는 기능은 사용자가 아니면 판단할 수 없는 결정을 exact evidence로
증명해야 한다. 새로운 기술 edge case만으로 새 사용자 승인 계약을 만들지 않는다.

## 1. 목적과 버전 경계

Approval Envelope `0.3.0`은 기존 AQ v2 `RootAuthorizationV2 0.2.0`에 exact-hash로
결속되는 additive companion이다. 프로젝트는 계속 `0.9.0`, canonical SceneSpec은 계속
`0.2.0`이다. 기존 `standard`, `background_exterior`, AQ v1, envelope가 없는 AQ v2,
Material Identity Split의 specialized user approval과 V0.7 generic user approval은 제자리에서
변경하지 않는다.

이 확장은 새 형상 빌더, 재질 family, provider 또는 destination adapter를 추가하지 않는다.
기존 capability의 routine gate를 결정론적 host policy로 처리하고, 실제 사용자 결정만 하나의
통합 escalation으로 모으는 것이 목적이다.

두 experimental profile은 구현과 검증 뒤에도 자동 활성화하지 않는다.

- `autonomous_static_prop_v2`: `disabled_experimental`
- `autonomous_static_prop_v2_codex_imagegen`: `disabled_experimental`

## 2. 조사된 기존 경계

구현 전 코드 조사에서 확인한 기준은 다음과 같다.

- AQ v1은 exact `PolicyAuthorization`으로 routine gate를 처리하며 이를 user approval로
  기록하지 않는다.
- `RootAuthorizationV2`는 request, reference, target, profile, budget, phase tool profile과
  delivery를 결속하지만 approval mode나 routine gate envelope를 포함하지 않는다.
- 기존 AQ v2 supervisor는 controller output, caller-supplied IQ, material appearance 및 identity
  split evidence, V0.7 optimization approval에서 안전하게 정지한다.
- Material Closure는 dependency, path/hash, surface-detail/UV와 shadow compile 실패를 approval
  전에 차단한다.
- Material Identity Split은 현재 exact `MaterialIdentitySplitRootScopeApproval`을 요구한다.
- repository는 새 Codex task를 spawn하지 않는다. `desktop_in_session`은 현재 Codex task가
  request-owned output을 만들면 host가 채택하는 모델이다.

## 3. authority 계층

```text
최초 사용자 요청
└─ RootAuthorizationV2 0.2.0                 기존, 변경 없음
   └─ AutonomyApprovalEnvelope 0.3.0          선택적 companion
      ├─ AutonomyApprovalPolicyProfile 0.3.0  결정론적 정책과 hard cap
      ├─ AQV2ApprovalBudget 0.3.0             user/policy/technical 계수 분리
      └─ exact routine action
         ├─ AQV2RoutineGateEligibilityReport  host 재계산
         ├─ AQV2RoutinePolicyAuthorization    single-use, user approval 아님
         └─ AQV2PolicyDecisionReceipt         소비·결과·budget 전이
```

Envelope는 미래 candidate나 plan을 승인하지 않는다. 최초 요청이 허용한 범위 안에서 미래의 exact
artifact가 policy-authorizable한지 평가할 authority만 부여한다. 모든 canonical 또는 derived side
effect에는 current artifact를 다시 검증한 별도 single-use policy authorization이 필요하다.

## 4. approval mode

### 4.1 `autonomous`

정상 지원 범위의 목표는 최초 요청 1회, 추가 사용자 결정 0회, technical user approval request
0회다. eligible routine gate는 host policy가 처리한다. 최초 scope 밖 결정만 consolidated
escalation으로 보낸다.

### 4.2 `checkpointed`

사용자 결정 budget은 geometry, material, delivery checkpoint의 최대 3회다. closure repair,
rebinding, identity normalization, controller retry와 rollback은 checkpoint가 아니다. 세 checkpoint도
future artifact의 포괄 승인이 아니라 그 시점의 exact 사용자 결정으로 남는다.

### 4.3 `interactive`

기존 AQ v2/Standard형 승인 경계를 보존한다. Envelope가 없는 기존 session을 이 모드로
자동 migration하거나 새 authority를 부여하지 않는다. `interactive`는 새 envelope를 명시적으로
계획한 session에서만 mode 값으로 존재한다.

## 5. strict 계약 집합

| 계약 | 버전 | 역할 |
|---|---:|---|
| `AutonomyApprovalEnvelope` | `0.3.0` | 최초 delegation의 범위와 exact root binding |
| `AutonomyApprovalPolicyProfile` | `0.3.0` | routine gate registry, bounded policy와 hard cap |
| `AQV2RoutineGateEligibilityReport` | `0.3.0` | exact target에 대한 host-only eligibility 판정 |
| `AQV2RoutinePolicyAuthorization` | `0.3.0` | exact eligible action의 single-use policy authority |
| `AQV2PolicyDecisionReceipt` | `0.3.0` | authorization 소비와 action 결과, budget 전이 |
| `AQV2ApprovalBudget` | `0.3.0` | 사용자·정책·기술 지표와 한도 분리 |
| `AQV2ConsolidatedEscalationRequest` | `0.3.0` | 같은 시점의 실제 사용자 결정 통합 |
| `AQV2EscalationDecision` | `0.3.0` | 한 번의 exact 사용자 decision payload |
| `AQV2ApprovalTelemetryReport` | `0.3.0` | machine-readable approval KPI |
| `AQV2OnePromptRunPlan` | `0.1.0` | envelope-bound bounded E2E plan |
| `AQV2OnePromptRunTerminal` | `0.1.0` | production/review/escalation/blocked terminal |
| `FrameworkChangeJustification` | `0.1.0` | framework 변경과 job-local 수정 분류 |
| `HistoricalSessionAutonomyEligibilityReport` | `0.3.0` | 과거 session의 read-only 가상 적합성 분석 |

모든 계약은 strict Pydantic, `extra=forbid`, `allow_inf_nan=false`, `frozen=true`, timezone-aware
timestamp, normalized POSIX relative path, SHA-256, immutable ID, job/workflow/dispatch/session/root/profile
binding과 Draft 2020-12 schema parity를 요구한다.

## 6. routine gate registry

초기 registry는 다음 exact gate만 허용한다.

```text
geometry_candidate_promotion
structural_candidate_promotion
bounded_parametric_revision
bounded_material_identity_split
material_candidate_promotion
material_quality_acknowledgement
iq_quality_acceptance
optimization_plan_authorization
package_acknowledgement
review_bundle_terminal
technical_retry
rollback
imagegen_candidate_adoption
```

eligibility는 LLM/controller가 아니라 host service가 계산한다. report는 exact target, current canonical
snapshot, root, envelope, policy profile, budget before/after, forbidden condition, predecessor receipt와
decision reason을 결속한다. stale, tampered, path escape, budget excess, unauthorized provider/delivery,
scope/reference/target drift는 fail-closed다.

## 7. bounded transformation 정책

### 7.1 no-visual technical normalization

path-only rebinding, hash-map reconstruction, manifest ordering, closure collection, deterministic
serialization, request/assignment/completion projection, output normalization과 rollback archive는
technical repair다. user approval이나 policy authorization을 합성하지 않고 별도 technical repair
counter만 증가시킨다.

### 7.2 bounded geometry/parameter revision

target/scope/semantic object set 유지, declared path allowlist, budget, constraint non-regression,
silhouette 또는 structural metric 개선, passed preflight와 exact rollback baseline이 모두 필요하다.

### 7.3 bounded material identity split

미래 envelope session에서 exact semantic clone, exclusive assignment, geometry/topology/transform/
dimensions/UV/reference/appearance 불변, paired SceneSpec/ModelingPlan-only diff, Blender shadow rebuild,
clone equivalence, assignment exclusivity, rollback archive와 post-apply authority refresh가 모두 통과한
경우에만 `bounded_material_identity_split` policy authorization을 허용한다. 기본 상한은 4, hard max는
8이며 profile은 더 낮게 제한할 수 있다.

기존 `MaterialIdentitySplitRootScopeApproval`은 기존/envelope-less session, interactive, 사용자가
checkpoint를 선택한 경우와 bounded 조건 밖에서 계속 사용한다. policy authorization을 specialized
user approval로 변환하지 않는다. additive authority adapter가 두 권한을 별도 provenance로 수용한다.

### 7.4 bounded material promotion

dependency closure, graph rebinding, surface-detail/UV preflight, Blender shadow compile, neutral preview,
initial material scope, required semantic/reference evidence, critical regression 0, threshold pass와
rollback baseline을 요구한다. 결과는 reference/quality evidence 기반 자동 promotion이며 human
aesthetic approval이 아니다.

### 7.5 optimization/package

최초 요청과 root/envelope에 포함된 GLB/FBX에 대해서만 exact source freeze와 optimization plan에
결속된 AQ v2 policy authorization을 허용한다. 기존 V0.7 `OptimizationApproval`을 변경하거나
합성하지 않는다. AQ 전용 adapter는 explicit V0.7 user approval 또는 AQ v2 policy authority 중
정확히 하나만 수용한다.

## 8. technical failure와 genuine escalation

dependency/manifest/path/hash/schema/projection/normalization/rollback-archive 실패는 approval category가
아니다. approval factory는 technical category 입력을 거부한다. deterministic host repair 또는 같은
candidate의 transient controller retry 최대 1회만 허용하며, 복구 불가·반복 실패는
`FrameworkChangeJustification`과 framework failure report를 가진 blocked/review terminal로 끝낸다.

실제 사용자 결정 reason은 다음으로 제한한다.

```text
scope_expansion
reference_replacement
target_change
budget_expansion
delivery_expansion
destination_project_write
provider_scope_expansion
unresolved_design_ambiguity
missing_exact_user_text
rights_or_license_decision
```

같은 시점에 알려진 모든 결정을 `AQV2ConsolidatedEscalationRequest` 하나로 묶는다. 사용자가 결정하지
않으면 current best와 unresolved finding을 review bundle로 종료할 수 있다.

## 9. One-Prompt Supervisor

```text
AQV2OnePromptRunPlan
→ geometry controller/validation/policy
→ material closure/controller/validation/policy
→ Integrated Quality 0.2/policy
→ requested delivery policy/package/roundtrip
→ AQV2OnePromptRunTerminal
```

supervisor는 hard global action budget 안에서만 진행하고 routine approval에서 기다리지 않는다.
controller output이 필요하면 request-owned assignment를 게시하고 `waiting_for_controller`를 보존한다.
현재 Codex task가 allowed output을 제공하면 same request/source/budget을 다시 검증해 resume한다.
repository는 새 Codex task를 spawn하지 않는다. 앱 종료 후 background 실행을 주장하지 않으며,
persisted state와 budget만 보존한다.

정상 autonomous terminal은 `production_delivery`, `review_bundle`, `genuine_escalation`이다. 복구할 수
없는 framework failure는 별도 `blocked` terminal이다.

## 10. telemetry와 benchmark

모든 one-prompt run은 사용자 요청/결정/approval, policy authorization, technical repair,
controller invocation, promotion, rollback, ImageGen, quality, delivery와 terminal을 exact counter로
기록한다. autonomous success는 initial request 1, additional decision 0, technical approval 0,
canonical corruption 0과 production 또는 review terminal을 요구한다.

대표 benchmark는 procedural metal/plastic, localized decal/signage, detailed wood, crystal/emission/
alpha, bounded identity split의 최소 5개 case를 포함한다. synthetic/representative fixture는 실제
사용자 품질 검증으로 표현하지 않는다.

## 11. 저장 경로와 single-writer

신규 session evidence는 기존 session root 아래 additive namespace를 사용한다.

```text
production/autonomy_v2/<session-id>/approval_envelope/
├─ policy_profile.json
├─ approval_budget.json
├─ envelope.json
├─ eligibility/<gate-id>.json
├─ authorizations/<authorization-id>.json
├─ decisions/<receipt-id>.json
├─ escalations/
├─ telemetry/
├─ one_prompt/
└─ framework/
```

controller/adviser는 이 namespace의 candidate staging만 만들 수 있고 eligibility나 canonical state를
결정하지 못한다. 기존 supervisor/host transaction만 canonical 또는 production evidence를 쓴다.

## 12. migration과 historical session

Envelope가 없는 session은 `legacy_without_envelope`로 읽고 기존 의미를 유지한다. 자동 mode 선택,
auto migration, retroactive policy authority와 user approval 재분류는 금지한다. Crystalgun은 기존
specialized approval 경계를 유지하고 canonical apply를 수행하지 않는다. read-only
`HistoricalSessionAutonomyEligibilityReport`만 미래 bounded policy 조건을 가상 평가한다.

## 13. approval 영향 요약

| 기능 | 정상 작업 승인 수 영향 | 근거 |
|---|---|---|
| Approval Envelope | 감소 | routine exact gate를 host policy로 이동 |
| One-Prompt Supervisor | 감소 | 알려진 user decision만 통합 escalation |
| technical repair 분류 | 감소 | 기술 실패 approval factory 차단 |
| bounded identity split adapter | 감소 | strict no-appearance/no-geometry split만 policy 처리 |
| delivery adapter | 감소 | 최초 요청 delivery에 한해 exact policy 처리 |
| checkpointed mode | 유지/상한 고정 | 사용자 선택 checkpoint 최대 3회 |
| interactive mode | 유지 | 기존 계약 회귀 보존 |

## 14. 구현 후 검증 상태

Approval Envelope strict contract/schema, deterministic policy engine, authority adapter,
One-Prompt 상태 전이, telemetry와 representative contract KPI는 focused gate로 검증했다. 신규
Material Closure/Identity Split 경계 2건도 실제 Blender 5.0.1에서 통과했다.

다만 representative fixture는 실제 자산 E2E가 아니다. 전체 actual Blender 묶음은 구현 전과 같은
legacy 10건 실패가 남아 있고, 실제 One-Prompt 사용자 자산 완주, built-in ImageGen 실제 호출,
human review와 profile activation은 `unverified`다. exact command/count/evidence는
`VERIFICATION_AQ_APPROVAL_ENVELOPE_KO.md`를 권위로 한다.
