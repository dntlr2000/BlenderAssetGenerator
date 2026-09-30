# Material Identity Split 0.1.0 재사용 프롬프트 모음

이 문서는 특정 job/session/material/object/hash를 포함하지 않는 공통 운영 프롬프트다.

## Placeholder

- `<JOB_ID>`
- `<PLANNING_ROOT>`
- `<RUN_ID>`
- `<MATERIAL_PLAN_ABSENCE_PATH>`
- `<PLAN_PATH>`
- `<MODELING_PLAN_DIFF_PATH>`
- `<CANONICAL_SCENE_INVENTORY_PATH>`
- `<APPROVAL_REQUEST_PATH>`
- `<CALLER_APPROVAL_PATH>`
- `<USER_DECISION_PATH>`
- `<APPLY_INTENT_PATH>`

## 1. 계획 replay

```text
<JOB_ID>에서 <PLANNING_ROOT>를 exact-load해 Material Identity Split 0.1.0 계획을 준비해.
canonical SceneSpec/ModelingPlan/Blend와 <MATERIAL_PLAN_ABSENCE_PATH>를 rehash하고, material identity
clone과 target object assignment 및 paired ModelingPlan detail target 외의 변경은 모두 거부해.
승인, canonical write, material promotion은 수행하지 마.
```

## 2. 승인 전 Blender 검증

```text
<PLAN_PATH>, <MODELING_PLAN_DIFF_PATH>, <CANONICAL_SCENE_INVENTORY_PATH>를 exact replay해.
isolated shadow에서 Blender 5.0.1 build/inspect/validate와 geometry/topology/transform/UV/reference,
clone/assignment invariant를 검사해. 모두 passed일 때만 ApprovalRequest를 게시하고
framework_ready_for_explicit_scope_approval에서 멈춰. 실제 approval, ApplyIntent, canonical write,
repair session, controller, promotion, IQ, package, destination write는 0으로 유지해.
```

## 3. 사용자 결정 게시

```text
사용자가 별도 메시지로 exact identity split을 승인하거나 거부한 경우에만 진행해.
<APPROVAL_REQUEST_PATH>, caller-authored <CALLER_APPROVAL_PATH>, 원문 <USER_DECISION_PATH>를
재검증하고 explicit_user_decision_observed=true일 때 specialized approval을 create-once 게시해.
generic approval이나 MaterialAppearanceApproval을 대체물로 사용하지 마.
```

## 4. guarded apply 또는 recovery

```text
사용자가 별도로 승인한 뒤 caller-authored <APPLY_INTENT_PATH>가 있을 때만 host apply를 실행해.
canonical lock 안에서 전체 authority chain과 CAS를 다시 검증하고 SceneSpec/ModelingPlan/Blend를
paired transaction으로 처리해. crash면 기존 approval과 intent를 재사용하는 exact recovery만
수행하고 새 intent나 approval consumption을 만들지 마. 기술 재시도는 1회로 제한해.
```

## 5. 최종 보고

```text
contract/schema/public surface, state journal, crash/recovery, post-apply refresh mechanism,
actual Blender run ID와 process count, paired candidates/diffs/preapproval/invariant/ApprovalRequest의
path/hash/size, canonical before/after, 모든 approval/apply/downstream count를 보고해.
실행하지 않은 user approval, canonical apply, material repair, controller, IQ, package는 unverified로
명시해.
```

