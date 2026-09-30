# Material Identity Split 0.1.0 아키텍처

Material Identity Split은 이미 승인된 geometry와 UV를 바꾸지 않고, 공유 material identity를
객체별 identity로 분리해야 할 때 사용하는 additive host companion이다. 프로젝트는 계속
`0.9.0`, canonical SceneSpec은 계속 `0.2.0`이며 AQ v2와 ImageGen profile은
`disabled_experimental`을 유지한다.

## 1. 해결하는 문제

localized `spatial_v1` detail은 대상 material이 다른 객체와 공유되면 소유권을 증명할 수 없다.
이때 material ID 추가와 object assignment 변경은 geometry 변경은 아니지만 `scope_change`이므로
`no_visual_change`, 일반 workflow 승인, MaterialAppearanceApproval로 처리할 수 없다.

정상 흐름은 다음과 같다.

```text
immutable planning evidence
→ paired SceneSpec/ModelingPlan candidate
→ exact diff + clone/assignment validation
→ isolated Blender 5.0.1 build/inspect/validate
→ invariant report
→ ApprovalRequest
→ framework_ready_for_explicit_scope_approval
→ explicit specialized user decision (별도 호출)
→ caller-authored ApplyIntent (별도 호출)
→ host-locked paired canonical transaction
→ post-apply authority refresh
```

ApprovalRequest는 승인이 아니며 첫 단계의 정상 종료점은
`framework_ready_for_explicit_scope_approval`이다.

## 2. strict contract

모든 계약은 schema version `0.1.0`, `extra=forbid`, finite number, contained POSIX-relative
path, exact SHA-256/size binding을 사용한다.

- `MaterialIdentitySplitPlan`
- `MaterialIdentitySplitPreapprovalRequest/Report/Failure`
- `MaterialIdentitySplitShadowBuildReceipt`
- `MaterialIdentitySplitInvariantReport`
- `MaterialIdentitySplitApprovalRequest`
- `MaterialIdentitySplitRootScopeApproval`
- `MaterialIdentitySplitApprovalConsumptionReceipt`
- `MaterialIdentitySplitApplyIntent`
- `MaterialIdentitySplitTransactionState`
- `MaterialIdentitySplitApplyReceipt`
- `MaterialIdentitySplitRollbackReceipt`
- `MaterialIdentitySplitRecoveryReceipt`
- `MaterialIdentitySplitGeometryContinuationReceipt`
- `MaterialIdentitySplitStatusProjection`

Schema는 `scripts/generate_schemas.py`가 Draft 2020-12 JSON Schema로 생성한다. 과거 schema나
workspace evidence는 새 의미로 재분류하지 않는다.

## 3. paired candidate와 exact clone

SceneSpec candidate는 다음 변경만 허용한다.

1. source material의 semantic clone identity 추가
2. 계획된 단일 target object의 `material_id`를 새 identity로 변경

ModelingPlan candidate는 같은 detail의 `target_material_id`만 함께 변경한다. appearance,
shader, texture strategy, geometry, transform, parent, dimension, UV, reference/content scope는
바뀌면 안 된다. source material과 clone의 canonical semantic projection은 material ID 외에
동일해야 하고, 새 identity는 정확히 계획된 객체 하나만 사용해야 한다.

## 4. 승인 전 shadow validation

preapproval은 canonical SceneSpec, ModelingPlan, Blend와 MaterialPlan 부재를 먼저 rehash한다.
그 뒤 run-owned shadow root에 paired candidates와 필요한 dependency를 복사하고, canonical
mesh payload를 덮지 않는 material-slot derivative를 만든다. derivative leaf는 긴 run ID에서도
legacy Windows 경로 한계에 걸리지 않는 compact deterministic path를 사용한다.

실제 Blender 5.0.1에서 build, inspect, validate를 각각 한 번 실행한다. 다음 항목이 모두
passed이고 canonical before/after hash와 size가 같을 때만 ApprovalRequest를 발행한다.

- paired diff allowlist
- semantic clone equivalence
- 신규/기존 assignment exclusivity
- object ID, geometry, topology, transform, dimension, UV
- reference, target subject, content scope
- 계획된 material identity와 assignment

이 단계는 approval, consumption, ApplyIntent, canonical write, repair session, controller,
promotion, IQ, package, destination write를 만들지 않는다.

## 5. specialized approval

승인 계약은 `approval_scope=material_identity_split`,
`satisfies_required_approval=root_scope`, `approved_by=user`, exact candidate/diff/preapproval,
현재 canonical preconditions와 원문 결정 bytes의 SHA-256을 결속한다. boolean 하나나 generic
approval은 대체할 수 없다. caller가 완성한 strict payload와 실제 사용자 결정 파일을 제공하고
`explicit_user_decision_observed=true`인 경우에만 host publisher가 create-once로 게시한다.

## 6. guarded paired transaction

apply는 caller-authored `ApplyIntent`를 받는다. host canonical lock 안에서 approval/request/intent
전체 chain, status, canonical CAS를 다시 검증한 뒤 intent와 approval consumption을 한 번만
게시한다. SceneSpec, ModelingPlan, Blend 원본을 immutable archive에 보존하고 다음 append-only
state를 순서대로 기록한다.

```text
planned → preapproval_running
→ eligible_for_explicit_user_scope_approval
→ approval_consumed → archives_written
→ scene_spec_replaced → modeling_plan_replaced
→ blender_rebuilt → invariants_verified
→ committed | rollback_started → rolled_back | recovery_required
```

canonical JSON 교체는 같은 디렉터리의 exact temporary file과 atomic replace를 사용한다.
partial state를 완료로 투영하지 않는다.

## 7. crash recovery와 technical retry

SceneSpec 직후, ModelingPlan 직후, Blender rebuild 직후, invariant 직후, ApplyReceipt 직전,
ApplyReceipt 직후, rollback 도중 crash를 구분한다. recovery는 이미 변경된 canonical bytes를
이전 precondition으로 오인해 거부하지 않고, exact plan/request/approval/intent/archive chain을
재검증한다.

- exact ApplyReceipt가 있으면 post bytes를 검증하고 commit을 끝낸다.
- ApplyReceipt가 없으면 세 archive를 exact rollback한다.
- 자동 복구가 끝나지 않으면 `recovery_required`를 게시한다.
- `recovery_required` 이후 동일 authority/intent/candidate/precondition의 기술 재시도는 최대 1회다.
- approval을 다시 소비하거나 새 ApplyIntent를 만들지 않는다.

## 8. post-apply authority refresh

성공 transaction은 기존 material closure나 preflight를 current로 재사용하지 않는다. 새 run-owned
SceneInventory, BuildProvenance, strict MaterialPlan absence, canonical snapshot과
`MaterialIdentitySplitGeometryContinuationReceipt`를 게시한다. continuation은 과거 geometry review
decision과 geometry validation, ApplyIntent/ApplyReceipt, post canonical bytes, invariant, reference와
content scope, exact identity diff를 재귀적으로 결속한다. 이는 geometry approval을 합성하지 않고
승인된 geometry가 material-only identity split을 통과했음을 증명할 뿐이다.

후속 material repair는 새 canonical을 source로 새 candidate, TextureManifest/ShaderRecipe,
dependency closure, preflight, neutral preview와 별도 MaterialAppearanceApproval을 다시 만들어야 한다.

## 9. public surface와 비목적

CLI 7개와 동등 MCP 7개는 plan, status, preapproval, approval-request 조회, approve, apply,
recover를 제공한다. approve는 caller-authored approval과 결정 bytes를, apply는 caller-authored
ApplyIntent를 요구한다. controller tool에는 canonical write authority를 부여하지 않는다.

이 companion은 MaterialPlan, TextureManifest, ShaderRecipe, MaterialAppearanceApproval,
ControllerResult, MaterialPhaseReceiptV2, IQ, package 또는 destination evidence를 생성하지 않는다.

## 10. Approval Envelope 0.3 authority adapter

기존 `MaterialIdentitySplitRootScopeApproval`과 그 consumption은 삭제하거나 완화하지 않는다. 새
autonomous/checkpointed envelope session에서 host가 exact paired candidate와 모든 기존 불변식, shadow
Blender, clone equivalence, assignment exclusivity, rollback 준비, identity cap을 재검증한 경우에만
`bounded_material_identity_split` policy authorization을 별도 ApplyIntent adapter로 전달할 수 있다.

Policy ApplyIntent와 consumption receipt는 schema `0.3.0`, 별도 artifact kind/path, `is_user_approval=false`,
`approved_by_user=false`, `user_approval_created=false`를 사용한다. 한 policy authority는 한 substantive
ApplyIntent에만 결속되며 exact replay만 create-once adopt할 수 있다. Policy authority를 specialized
approval로 변환하지 않으며 `interactive`, envelope 없는 session, bounded 조건 밖 candidate와 기존
Crystalgun history는 계속 explicit user approval 경계를 사용한다.
