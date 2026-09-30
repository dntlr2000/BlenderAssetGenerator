# V0.7.4 최적화 사전 검토와 승인

V0.7.4부터 LOD·Collider·배칭 최적화는 사용자가 설정을 보기 전에 시작되지 않습니다. `asset-plan`은 파생 메시를 만들지 않고, 현재 프로필과 preflight 증거로 실행 계획과 예상 비용만 작성합니다.

## 실행 순서

```text
AssetProfile 작성
→ read-only preflight
→ optimization review 생성
→ 사용자 선택: approve / revise_asset / revise_profile / cancel
→ 정확한 plan SHA-256 승인
→ 승인된 run 1회 실행
→ package
→ clean-import 검증
```

계획 단계에서 생성되는 권위 있는 JSON은 다음과 같습니다.

```text
optimization/runs/<run-id>/
├─ mesh_preflight_report.json
├─ review_plan.json
├─ optimization_review.json
└─ optimization_plan.json
```

`review_plan.json`은 승인 해시의 원본이며 변경하지 않습니다. `optimization_plan.json`은 `draft → approved → running → complete|failed` 실행 상태를 기록합니다.

## 검토 내용

`optimization_review.json`에는 다음이 포함됩니다.

- LOD 사용 여부와 LOD0 보존 여부
- 각 LOD level의 triangle ratio와 최소 silhouette IoU 목표
- preflight 기준 source object·triangle 수
- per-object 반올림을 고려한 LOD triangle 상한 추정
- Collider 전략, 예상 개수, 예상 triangle 또는 최대 상한
- Collider당 hull·triangle 제한
- package에 Collider가 포함되는지 여부
- 배칭 방식
- 목적 엔진이 정해지기 전에는 검증할 수 없는 항목

LOD switch distance, 실제 런타임 메모리, 실제 draw call, 물리엔진 비용은 V0.7에서 확정하지 않습니다. 이 값은 목적 엔진 adapter가 선택된 뒤 측정합니다.

## 프로필 기본값과 변경

`portable_gltf`와 `fbx_interchange`의 기본값은 LOD 사용과 `compound` collision입니다. 현재 `compound` 구현은 source object마다 bounds box 한 개를 만듭니다. `obj_legacy`는 기본적으로 LOD와 collision을 사용하지 않습니다.

승인 전에 다음 옵션으로 기본값을 명시적으로 바꿀 수 있습니다.

```powershell
uv run cbm asset-profile-init <job-id> `
  --profile fbx_interchange `
  --asset-kind static_environment `
  --lod-mode disabled `
  --collision-strategy none `
  --overwrite
```

지원되는 LOD 모드는 `profile_default`, `enabled`, `disabled`입니다. Collider 전략은 `profile_default`, `none`, `box`, `sphere`, `capsule`, `convex_hull`, `compound`, `mesh_proxy`입니다.

프로필을 바꾸면 이전 preflight와 review의 승인은 무효입니다. 같은 run을 재사용하지 말고 새 run ID로 preflight와 review를 다시 생성합니다.

## 승인과 실행

```powershell
uv run cbm asset-preflight <job-id> `
  --profile fbx_interchange `
  --run-id fbx-review-01

uv run cbm asset-plan <job-id> `
  --profile fbx_interchange `
  --run-id fbx-review-01
```

`optimization_review.json`의 `plan_sha256`과 LOD·Collider 내용을 확인한 뒤 승인합니다.

```powershell
uv run cbm asset-plan-approve <job-id> `
  --run-id fbx-review-01 `
  --plan-sha256 <exact-plan-sha256> `
  --approval-note "표시된 LOD와 Collider 설정 승인"

uv run cbm asset-optimize <job-id> `
  --profile fbx_interchange `
  --run-id fbx-review-01 `
  --approved-plan-sha256 <exact-plan-sha256>
```

승인은 다음 값에 결합됩니다.

- `review_plan.json` SHA-256
- `optimization_review.json` SHA-256
- AssetProfile SHA-256
- preflight SHA-256
- canonical source fingerprint

승인은 한 번만 사용할 수 있습니다. 실패한 실행을 그대로 재사용하거나 변경된 소스에 적용하지 않습니다. 원인을 수정한 뒤 새 run으로 다시 검토합니다.

## Codex의 사용자 확인 규칙

Codex는 `asset-plan` 결과를 요약해서 다음 네 선택을 한 번 물어야 합니다.

1. `approve`: 표시된 설정과 plan SHA-256을 승인
2. `revise_asset`: 외형·실루엣·비율·semantic 구조를 standard workflow에서 수정한 뒤 build·QA와 새 V0.7 review를 수행
3. `revise_profile`: LOD·Collider·배칭·UV·텍스처·비용 설정만 바꾸고 새 review 생성
4. `cancel`: V0.7 최적화를 실행하지 않음

`optimization_review.json`의 `recommended_decision=revise_asset`은 직접 QA가
`needs_revision`인 경우의 검토 권고일 뿐 자동 전환이나 승인이 아닙니다. 기존
portable workflow를 standard로 변조하지 않으며, 사용자가 별도의 `revise_asset`
workflow를 요청해야 합니다. canonical 자산이 바뀌면 이전 V0.7 plan은 사용하지 않고
새 run ID로 preflight와 review부터 다시 수행합니다.

일반적인 “V0.7을 진행해줘” 요청이나 `asset-optimize` 호출 자체를 승인으로 간주하지 않습니다. 승인 후에도 canonical SceneSpec, geometry payload, material contract, source texture, authoring `.blend`는 변경되지 않습니다.
