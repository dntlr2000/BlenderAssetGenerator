# Autonomous Quality 0.2 — Harness Reliability & Fidelity Extension 아키텍처

## 1. 문서 상태와 판정 언어

이 문서는 프로젝트 `0.9.0`과 Autonomous Quality(AQ) `0.1.0` 위에 병렬로 추가된
**AQ 0.2의 구현 아키텍처와 아직 남은 활성화 설계**를 함께 기록한다. strict host contract,
Schema, deterministic metric/authoring service, ControllerExecutor, delivery supervisor와 CI 기반은
현재 공유 트리에 구현되어 있다. host 전체 회귀, 실제 Blender synthetic fixture, 독립 GLB+FBX
clean import와 V0.7~V0.9 root smoke도 2026-08-11 검증에서 통과했다. 다만 이 결과는 Desktop의
repository-side task spawn, optional App Server, 실제 사용자 승인 또는 임의 reference 품질을
증명하지 않는다. 기능마다 다음 판정 언어를 구분한다.

- `설계됨`: 이 문서가 정의한 목표와 경계
- `구현됨`: 코드와 strict schema가 존재하고 host test를 통과한 상태
- `Blender 검증됨`: 지원 환경에서 실제 Blender gate를 통과한 상태
- `verified_active`: 전체 필수 host/Blender/legacy gate와 문서 동기화가 통과한 profile만 가질 수
  있는 registry 상태
- `disabled_experimental` 또는 `experimental_unverified`: 구현이나 실기동 증거가 불완전한 상태

현재 `autonomous_static_prop_v2`는 `disabled_experimental`이다. MeshPayload 0.2,
Integrated Quality 0.2, MaterialGraphRuntime, local MaterialAuthoring, ControllerExecutor와
DeliveryProfile은 synthetic Blender/dual-delivery 범위까지 검증됐지만, Desktop controller는
adopt-only이고 supporting-client sandbox/App Server 및 사람 검토는 미검증이다. 현재 검증 상태는
`VERIFICATION_AQ_V02_KO.md`가 판단 원본이다.

### 1.1 2026-08-11 구현 snapshot

| 영역 | 현재 상태 | 활성화 해석 |
|---|---|---|
| AQ v2 profile/planner/state/advance/run/cancel | 구현·host/full test 통과 | profile은 계속 `disabled_experimental` |
| MeshPayload 0.2/V03 derived migration | strict companion과 명시적 plan/apply 구현 | canonical SceneSpec 0.2.0 자동 migration 없음 |
| IQ 0.2 contour/semantic/landmark/multiview/ranking | 구현·host test 통과 | 실제 reference 일반 품질 향상은 미검증 |
| MaterialGraphRuntime | strict registry/compiler + fixed Blender compile/reopen/inventory 통과 | arbitrary graph와 destination parity 없음 |
| MaterialAuthoring 0.1 | 8개 local strategy와 fixed Blender family smoke 통과 | canonical master/preview 상태는 별도이며 일반 재질 품질은 미검증 |
| ControllerExecutor 0.1 | execution-owned 격리와 fake/desktop adoption 검증 | Desktop는 adopt-only; App Server와 외부 sandbox는 미검증 |
| DeliveryProfile 0.1 | freeze/review/terminal + 실제 synthetic dual GLB/FBX roundtrip 통과 | 실제 사용자 승인·목적지 runtime은 미검증 |
| Python/Blender CI 정의 | workflow 파일과 정적 test 존재 | 실제 GitHub run/self-hosted Blender run은 별도 증거 필요 |

## 2. 목표와 비목표

AQ 0.2의 목적은 기존 계약·승인·receipt 중심 하네스를 유지하면서 그 하네스가 실제 형상,
재질, 시각 품질과 전달 품질을 더 강하게 증명하도록 확장하는 것이다.

주요 목표는 다음과 같다.

1. SceneSpec V03의 UV, normal, smoothing, face material과 GeometryIntent가 structural
   materialization부터 candidate, canonical, optimized LOD0, package, clean import까지 생존하거나
   포맷별 동등성으로 검증되게 한다.
2. 기존 V0.6 direct score를 바꾸지 않고 contour, semantic, landmark, multi-view companion
   evidence를 추가한다.
3. MaterialGraphSpec을 whitelist-only Blender compiler에 연결하고, 균일 fallback 외에 provenance가
   있는 decal, reference patch, wood, metal, emissive, crystal authoring 전략을 제공한다.
4. quality-approved canonical source freeze와 delivery format 선택을 분리해 같은 source에서 GLB와
   FBX를 각각 직접 만든다.
5. 기존 `desktop_in_session`을 보존하면서 격리된 controller executor를 끼울 수 있는 폐쇄 루프
   기반을 만든다.
6. synthetic benchmark와 제한된 project-local benchmark로 metric 방향성과 실제 향상을 구분한다.
7. root instruction, CI, registry와 문서가 실제 구현에서 드리프트하지 않게 한다.

이번 설계의 비목표는 다음과 같다.

- 프로젝트를 V1.0으로 승격
- SceneSpec `0.2.0` 또는 기존 V0.4~V0.9 공개 계약의 제자리 변경
- `autonomous_static_prop_v1`의 의미, 기본 동작 또는 기존 검증 상태 변경
- architecture, environment, measured, blueprint, interior profile 활성화
- rig, skinning, animation, gameplay 또는 CAD/B-Rep 지원
- Unity/Unreal 프로젝트 직접 수정, Prefab/Actor 자동 생성 또는 runtime parity 주장
- arbitrary Blender Python, arbitrary node graph, arbitrary shell authority 추가
- 외부 네트워크 texture/image provider를 기본 의존성으로 사용
- 단일 이미지의 숨은 면, 절대 치수, 내부 구조를 recovered truth로 주장
- fixture 성공을 arbitrary-reference 예술 품질 보장으로 확대

## 3. 버전과 하위 호환 정책

기존 public contract는 제자리에서 변경하지 않는다.

| 계층 | 유지 버전 | AQ 0.2 관계 |
|---|---:|---|
| Project | `0.9.0` | 유지, V1.0 승격 근거로 사용하지 않음 |
| canonical SceneSpec | `0.2.0` | standard/background/AQ v1의 canonical 계약 유지 |
| SceneSpec V03 | `0.3.0` | 구조 형상용 병렬 opt-in 계약 유지 |
| Reference/Constraint | `0.4.0` | 기존 source of truth 유지 |
| Material/Shader/Texture | `0.5.0` | 기존 canonical material 계약 유지 |
| Visual QA | `0.6.0` | direct score와 7-pass 의미 유지 |
| Portable Asset | `0.7.0` | approval, package, roundtrip 의미 유지 |
| Workflow | `0.8.0` | request/route/plan/receipt 의미 유지 |
| Stabilization/Handoff | `0.9.0` | audit와 Destination Handoff 의미 유지 |
| AQ/Integrated Quality | `0.1.0` | loader와 v1 실행 의미 유지 |

AQ 0.2는 다음 companion contract를 병렬 버전으로 구현한다.

| companion contract | 버전 | 역할 |
|---|---:|---|
| MeshPayload | `0.2.0` | loop 단위 UV와 GeometryIntent materialization 전달 |
| GeometryIntentSurvivalReport | `0.1.0` | 단계별 exact/equivalent survival 증거 |
| IntegratedQuality | `0.2.0` | contour·semantic·landmark·multi-view companion metric |
| MaterialGraphRuntime | `0.1.0` | whitelist graph compile 결과와 dependency 증거 |
| MaterialAuthoring | `0.1.0` | 실제 image/procedural authoring 전략과 provenance |
| AdvancedMaterialHandoff | `0.1.0` | destination 계획용 portable approximation 설명 |
| DeliveryProfile | `0.1.0` | quality freeze 이후 포맷별 전달 요청 |
| ControllerExecutor | `0.1.0` | 격리 controller 호출과 결과 검증 |
| Autonomy | `0.2.0` | v2 assignment, state와 terminal 결속 |

모든 새 loader는 기존 `0.1.0`을 계속 읽는다. legacy evidence가 없다는 이유로 과거 job을
실패시키지 않는다. 정보가 없는 0.1 payload를 0.2의 완전한 증거로 추정하거나 자동 migration하지
않는다. migration은 immutable plan, exact plan SHA-256, 별도 apply와 receipt를 사용하며
canonical source를 묵시적으로 교체하지 않는다.

## 4. 병렬 profile과 활성화 정책

```text
autonomous_static_prop_v1
  └─ 기존 의미와 verified_active 상태 유지

autonomous_static_prop_v2
  ├─ 현재: disabled_experimental
  ├─ host contract 구현·focused 검증 완료
  └─ 모든 필수 실제 Blender/legacy/delivery gate 통과 후에만: verified_active
```

v2 profile은 v1을 수정하는 feature flag가 아니다. immutable request, root authorization,
assignment와 plan에 profile ID와 version이 명시되어야 한다. v1 세션은 v2 payload, v2 metric,
v2 material compiler 또는 v2 delivery semantics를 자동으로 채택하지 않는다. 기존 session을
제자리에서 v2로 변환하거나 기존 blocked/review terminal을 새 정책으로 재분류하지 않는다.

v2가 허용하는 기본 scope도 정적 단일 소품, `primary_object_only`, 명시된
`target_subject`, concept evidence, standard underlying policy로 제한한다. architecture,
environment, measured, interior, rig, animation, gameplay와 engine-specific write는 profile
활성 여부와 관계없이 restricted scope다.

## 5. 전체 data flow

AQ v2는 별도 무제한 모델링 파이프라인이 아니라 기존 standard/V0.9 production 경계 위의
versioned supervisor다.

```text
immutable user reference + target/scope/output request
  → standard V0.8 workflow + V0.9 production dispatch
  → AQ v2 RootAuthorization / profile / budget / tool-profile hashes
  → Reference Evidence + camera hypotheses
  → workflow-owned geometry assignment
  → isolated geometry controller output
  → strict host validation
  → V03 structural candidate
     → materialize
     → MeshPayload 0.2
     → path-backed V02 custom_mesh compile
     → candidate build/inspect/validate
     → GeometryIntent survival gate
  → controller-only canonical promotion + history + receipt
  → workflow-owned material assignment
  → isolated material controller output
  → strict V0.5 material candidate validation
     → MaterialGraph whitelist compile
     → image/procedural texture authoring
     → rebuild/inspect/validate와 fresh provenance
     → strict canonical material promotion
  → caller가 exact input에 결속해 공급한 final V0.6 + IQ 0.2
     ├─ needs_revision/unscorable
     │    → review_required quality terminal + exact review bundle
     │    → source freeze/package authority 없음
     ├─ blocked
     │    → blocked quality terminal, review bundle/source freeze 없음
     └─ quality accepted
          → quality_approved terminal + exact canonical source freeze
          → requested DeliveryProfile plan(s)
             ├─ review_only → quality-approved evidence delivery, package 없음
             ├─ portable_gltf → V0.7 plan/approval/package/clean import
             └─ portable_fbx  → V0.7 plan/approval/package/clean import
          → format-specific material/geometry loss evidence
          → exact delivery terminal + result/review binding
          → 선택적 package-bound handoff envelope
```

핵심 분리는 다음 세 가지다.

- authoring candidate와 canonical source를 분리한다.
- quality acceptance와 format delivery를 분리한다.
- authoring metadata equality와 destination format의 최종 surface equivalence를 분리한다.

현재 supervisor는 geometry와 material phase를 위 순서로 전진시키고, caller가 제출한 IQ 0.2
report의 global/semantic reference·candidate PNG를 exact path/hash/kind로 유일하게 찾는다. host는
그 실제 bytes에서 contour·semantic metric을 다시 계산하고 gates, findings,
`revision_reasons`, reentry와 outcome을 다시 만든 뒤 제출 report 전체와 equality를 검사한다.
supervisor 자체가 IQ 점수나 사용자 승인을 합성하지 않는다.

PDF, contact sheet, `latest.json`, mutable state projection은 판단 원본이 아니다. strict JSON,
exact hashes, immutable plan/authorization/promotion/attempt/transition/manifest/receipt chain이
판단 원본이다.

## 6. 현재 evidence 구조

public v2 planner와 supervisor가 소유하는 session 경로는
`production/autonomy_v2/<session-id>/`다. geometry validation은 짧은 path를 위한 job-owned
`aq2/<validation-id>/`, material promotion은 session-owned `material_phase/<sequence>/`에 immutable
evidence를 둔다. 아래 트리는 역할 중심 요약이며 실제 판단은 각 artifact의 exact relative path와
hash를 따른다.

```text
workspaces/<job-id>/
├─ production/autonomy_v2/<session-id>/
│  ├─ profile.json
│  ├─ budget.json
│  ├─ root_authorization.json
│  ├─ plan.json
│  ├─ tool_profiles/
│  ├─ controller_executions/<execution-id>/
│  │  ├─ controller_workspace/inputs/
│  │  ├─ controller_workspace/outputs/
│  │  └─ controller_executor_evidence/
│  ├─ states/
│  ├─ material_phase/<sequence>/
│  ├─ integrated_quality_policy.json
│  ├─ quality_review_bundle.json  # needs_revision/unscorable일 때만
│  ├─ source_freeze.json
│  ├─ delivery_plan.json
│  ├─ delivery_reviews.json
│  ├─ delivery_terminal.json
│  └─ quality_terminal.json
├─ aq2/<validation-id>/
│  ├─ candidate_geometry.json
│  ├─ canonical_geometry.json
│  ├─ survival.json
│  └─ receipt.json
├─ reports/integrated_quality/runs/<run-id>/
├─ optimization/runs/<run-id>/geometry_survival/
├─ exports/packages/<profile-id>/<package-id>/
└─ exports/review_bundles/<bundle-id>/  # AQ v1 review bundle 경로
```

각 artifact는 job-relative path만 저장한다. package 내부 expected contract와 package 생성 후
run-owned actual clean-import evidence를 구분한다. 이미 immutable이 된 package에 roundtrip
결과를 뒤늦게 덮어쓰지 않는다.

## 7. MeshPayload 0.2

### 7.1 기존 손실 경계와 현재 보완

기존 structural materializer의 `loop_uvs`/`geometry_intent`와 legacy path-backed
`custom_mesh`의 `vertex_uvs` 소비 방식 사이에는 dialect 손실 가능성이 있었다. 현재 공유 트리에는
MeshPayload 0.2 strict loader/compiler, explicit migration과 GeometryIntent survival companion이
추가되어 host 단계에서 이 경계를 검증한다. 실제 Blender synthetic fixture에서는 V03
vertical-loft candidate의 materialization/build/promotion과 동일 source freeze의 optimized LOD0,
독립 GLB/FBX clean import 생존 검사가 통과했다. 이 bounded fixture가 모든 builder·modifier·format
조합의 생존이나 임의 자산의 시각 품질을 증명하는 것은 아니다.

### 7.2 strict contract

`schemas/mesh_payload_v02.schema.json`은 최소한 다음 정보를 strict하게 표현한다.

- `schema_version`, `semantic_id`, `builder_kind`
- `vertices`, `faces`, polygon 순서에 대응하는 loop count 또는 loop offsets
- polygon-loop 순서의 `loop_uvs`
- ordered `material_slot_ids`와 `polygon_material_indices`
- `sharp_edges`, `uv_seams`, `edge_creases`, `bevel_weights`
- `face_groups`
- `smooth_polygon_flags` 또는 명시적 `smoothing_policy`
- `custom_attribute_manifest`
- `modifier_materialization_policy`
- `weighted_normal_intent`, `subdivision_intent`
- 원본 `source_geometry_intent`
- `findings`
- payload, V03 candidate, external geometry/texture 등 transitive dependency의 exact source hashes

UV의 권위 표현은 per-loop다. 한 vertex가 seam 양쪽에서 서로 다른 UV를 가져야 하므로
per-vertex UV만으로는 충분하지 않다. `loop_uvs` 길이는 모든 polygon corner 수의 합과 정확히
일치해야 한다. UV가 의도적으로 없으면 빈 배열을 허용하는 대신 별도 명시 상태와 finding을
요구하며, 값 누락을 성공으로 해석하지 않는다.

검증기는 다음을 fail-closed로 검사한다.

- finite vertex/UV/weight 값과 non-degenerate face
- 모든 face index와 edge index의 범위
- intent edge가 face-derived edge set에 실제 존재하는지
- polygon material index가 ordered slot 범위 안인지
- smooth flag와 polygon 수의 일치
- face-group polygon/edge 참조의 유효성
- 중복되거나 상충하는 seam/sharp/crease/material assignment
- source hash map의 누락, stale 또는 path escape
- baked와 recreated 효과의 중복 선언
- unknown field와 미지원 contract version

### 7.3 legacy loader와 migration

- unversioned/legacy `vertex_uvs` payload는 기존 방식으로 계속 읽는다.
- `StructuralMeshPayload 0.1.0` loader와 schema를 제거하거나 의미를 바꾸지 않는다.
- v2 assignment만 0.2 payload를 요구한다.
- 0.1→0.2 migration은 존재하는 정보만 옮기며 UV, normal, material slot이나 modifier 결과를
  추측하지 않는다.
- migration plan은 source file hash, parsed model hash, proposed output hash, limitation을 결속한다.
- apply는 exact plan SHA-256을 재검증하고 derived copy와 receipt만 발행한다.
- incomplete migration은 AQ v2 executable evidence가 아니라 status/audit-only evidence다.

## 8. GeometryIntent materialization과 runtime

### 8.1 효과 분류

GeometryIntent는 각 효과를 정확히 한 번만 적용하도록 두 종류로 분리한다.

| 분류 | 대표 효과 | 처리 원칙 |
|---|---|---|
| `recreate_in_compiled_build` | sharp, seam, crease, face material, smoothing, weighted normal, non-destructive subdivision | MeshPayload data/modifier intent로 전달하고 compiled build에서 idempotent하게 복원 |
| `bake_into_mesh` | boolean 결과, topology가 확정되는 operation, 최종 evaluated geometry가 필요한 modifier | materialization에서 적용하고 결과 mesh/signature를 기록하며 compiled build에서 다시 적용하지 않음 |

modifier materialization policy는 effect별 disposition, modifier order, source intent hash와 결과
signature를 포함한다. 동일 subdivision, weighted normal, bevel 또는 boolean을 baked geometry와
재생성 modifier 양쪽에서 중복 적용하면 validation failure다.

### 8.2 runtime 단계

`geometry_intent_runtime`의 구현 책임은 다음처럼 나눈다.

1. mesh data intent 적용
   - loop UV
   - polygon material index
   - sharp/seam/crease/bevel edge state
   - face-group attribute
   - polygon smooth flags
2. modifier intent 적용
   - weighted-normal intent
   - subdivision level, render level과 boundary smoothing
   - deterministic modifier ordering과 AQ-owned idempotent marker
3. 결과 snapshot
   - base mesh와 evaluated mesh의 counts/signatures
   - 적용된 data attributes
   - modifier inventory와 disposition

명시적 sharp edge는 `smooth_by_angle` 계산에 의해 사라지면 안 된다. angle-derived sharp와
explicit sharp의 precedence를 계약에 고정한다. legacy ObjectSpec modifier와 v2 intent modifier가
같은 효과를 요구하면 중복을 거부하거나 명시적으로 하나의 권위 원본으로 normalize한다.

### 8.3 structural builder 책임

loft, sweep, multi-loop, boolean과 whitelist Geometry Nodes builder는 vertices/faces만 만드는 것으로
완료되지 않는다. 해당 builder가 UV 또는 face group을 주장한다면 deterministic한 loop mapping과
의미 있는 materialization evidence를 출력해야 한다. 예를 들어 loft/sweep은 ring/path 방향의
안정된 UV parameterization과 seam 위치를 가져야 한다. V0.7 smart-project UV를 나중에 생성하는
것은 V03 UV intent 생존 증거가 아니다.

boolean/geometry-node처럼 topology를 확정하는 operation은 evaluated result를 bake하되 source
tree/template hash와 baked topology signature를 남긴다. authored modifier를 남길지 bake할지는
effect별 policy에 의해 결정하고 builder 내부 암묵 동작으로 숨기지 않는다.

### 8.4 multi-material companion

SceneSpec V03 ObjectSpec은 기존 호환성을 위해 단일 `material_id`를 유지한다. 여러 face material을
지원하기 위해 SceneSpec 0.3.0을 제자리에서 늘리는 대신 v2 run-owned companion binding을 둔다.

- semantic ID
- ordered material slot IDs
- face-group 또는 polygon-range → slot assignment
- source SceneSpec/material contract hash
- confidence와 limitation

단일 material object는 slot 0으로 자연스럽게 매핑한다. companion 없이 multi-material을
추측하거나 polygon index만 보존해 의미 없는 slot을 만드는 것은 금지한다.

## 9. GeometryIntentSurvivalReport

하나의 mutable latest report가 전체 생존을 주장하지 않는다. 각 단계는 이전 단계와 exact hash로
연결된 immutable report를 발행한다.

```text
structural materialization
  → compiled candidate
  → promoted canonical build
  → optimized LOD0
  → clean-import GLB
  → clean-import FBX
```

각 report는 최소한 다음을 비교한다.

- source/target artifact hash와 build/source fingerprint
- semantic ID와 builder/topology profile
- vertex, face, loop와 evaluated triangle counts
- UV coordinate/binding fingerprint
- ordered material slot과 per-polygon assignment
- sharp edge 또는 결과 split-normal equivalence
- crease/bevel authored state와 결과 surface effect
- polygon smoothing state
- custom attribute manifest
- modifier inventory 또는 baked-geometry equivalence
- 허용된 format/optimization loss와 예상 밖 loss
- 판정 `exact`, `equivalent`, `known_loss`, `unscorable`, `failed`

candidate promotion은 materialization→compiled 단계의 필수 생존 gate를 통과해야 한다. 이 gate는
V0.6 direct score에 숫자를 섞지 않으며 geometry contract failure로 독립 처리한다.

optimizer는 LOD0을 quality-approved source와 strict/equivalent하게 비교한다. LOD1 이상은 의도된
triangle 감소 때문에 raw topology equality를 요구하지 않고 승인된 LOD policy, silhouette,
semantic/material traceability와 loss report를 검사한다. intent-protected object의 consolidation은
기본 비활성 또는 의미 보존이 증명되는 좁은 방식으로 제한한다.

GLB/FBX는 exporter가 vertex split, reorder, triangulation과 axis conversion을 수행할 수 있다.
따라서 seam flag나 raw loop index가 같아야 한다고 요구하지 않는다. 공통 좌표계에서 quantized
position, per-corner UV, evaluated/split normal, material ID와 face orientation으로 구성한
canonicalized triangulated surface multiset을 비교한다. seam/crease 같은 authoring metadata가
사라져도 최종 UV/normal/visual surface가 동등하면 `known metadata loss`로 기록할 수 있으며,
동등성을 검사하지 못하면 pass 대신 `unscorable`이다.

## 10. Integrated Quality 0.2

### 10.1 v1/V0.6 보존

기존 `VisualQAReport 0.6.0`, 정확히 7개 pass와 `overall_direct_score`의 계산 및 의미를 변경하지
않는다. `IntegratedQuality 0.1.0` loader도 유지한다. IQ 0.2는 기존 점수를 입력 evidence로
인용하는 companion이며 과거 점수를 재계산해 다른 의미로 덮어쓰지 않는다.

### 10.2 metric 계층

Reference Fidelity:

- 기존 V0.6 overall direct score와 silhouette IoU
- contour boundary precision/recall/F-score
- edge distance-transform score
- semantic mask IoU와 semantic boundary F-score
- optional observed landmark reprojection error
- bbox/occupancy와 camera reprojection residual
- optional deterministic perceptual metric

Structural Consistency:

- 기존 five-view visibility
- multi-view silhouette stability
- semantic part placement
- assembly broad phase와 BVH narrow phase
- penetration/contact/symmetry
- side thickness plausibility와 rear completion
- topology profile와 GeometryIntent survival 요약

Advisory:

- estimated depth consistency
- estimated normal consistency
- generated-target comparison

advisory evidence는 provider/model/version/hash/confidence와 `authoritative=false`를 기록한다.
없으면 `unscorable`이며 0점이나 pass로 대체하지 않는다. 단독 hard gate 또는 promotion authority가
될 수 없다.

authoritative hard finding은 설명 문자열만으로 hard failure가 되지 않는다. exact required gate
ID와 그 gate의 `failed` 결과, authoritative input artifact/hash에 결속해야 한다. required gate가
통과했거나 누락됐는데 hard finding만 삽입한 IQ report는 strict validation에서 거부한다.

### 10.3 contour, semantic, landmark

Contour tolerance는 고정 pixel 하나가 아니라 이미지 대각선 비율과 bounded pixel tolerance를
함께 기록한다. reference mask 크기, render mask 크기, camera hash, preprocessing version과 exact
input hash에 결속한다. 작은 물체와 큰 물체에 같은 절대 오차를 강요하지 않는다.

semantic metric은 등록된 `observed` reference mask만 canonical authority로 사용한다. generated
또는 inferred mask는 advisory다. semantic ID별 점수와 aggregate를 분리하고, critical semantic
누락이 평균값에 묻히지 않도록 critical set과 required-evidence 상태를 둔다.

landmark는 optional companion contract다. source image coordinate, semantic ID, evidence status,
confidence와 exact source hash를 기록하며 observed landmark만 authoritative다. landmark가 없는
작업은 failure가 아니라 해당 metric `unscorable`이다.

현재 typed host-verifiable raw input receipt가 없는 required authoritative scored landmark 또는
required scored multi-view 결과는 quality pass authority로 사용할 수 없다. 이 경우 host는
fail-closed하며, self-consistent한 고득점 숫자만으로 `passed`를 만들 수 없다.

### 10.4 후보 비교와 reentry

후보는 단일 weighted score로 promotion하지 않는다.

```text
1. hard-gate 실패 제거
2. required evidence unavailable 분리
3. critical regression 제거
4. minimum meaningful gain 검사
5. Pareto front 또는 profile에 명시된 lexicographic priority
6. 변경 path 수와 전체 변화량 최소화
7. stable candidate ID tie-break
```

finding은 원인 계층으로 되돌린다.

| finding | 기본 reentry |
|---|---|
| camera/contour/semantic mismatch | structural authoring |
| local parametric proportion | bounded parametric convergence |
| material/texture mismatch | material authoring |
| topology/UV/normal survival | production repair 또는 structural compile |
| authoritative evidence 누락 | review 또는 blocked |
| prohibited scope 발견 | `restricted_scope_required` |

IQ 0.2의 pass는 실제 source와 profile threshold에 결속된 quality 판정이지 범용 완성도
백분율이나 destination runtime 인증이 아니다.

## 11. 품질 benchmark

### 11.1 deterministic synthetic benchmark

외부 저작권 asset을 다운로드하지 않는다. 현재 host benchmark는 project-local synthetic
raster recipe에서 beauty/silhouette/object-ID, semantic mask, known camera와 의도적으로
perturb한 candidate를 만든다. 각 case는 특정 변화가 metric을 어느 방향으로 움직여야 하는지
기대값을 가진다. 2026-08-11 검증에서는 host 10개 case와 manifest가 허용한 두 fixed Blender
probe가 모두 통과했다.

최소 범주는 simple hard-surface box, curved loft, swept handle, boolean panel, ornate
multi-part prop, multi-material prop, wood, signage/decal, emissive/crystal-like prop와 small
static assembly다.

### 11.2 project-local reference benchmark

저장소에 이미 존재하고 권리 상태가 명확한 reference만 사용한다. 적합한 evidence가 부족하면
synthetic 결과만 기록하고 실제 reference 품질 benchmark는 `unverified`로 남긴다.

synthetic manifest가 사용하는 비교 stage label은 다음이다. 이 label이 실제 production
V0.9/v1/v2 run을 수행했다는 뜻은 아니다.

- V0.9 standard initial
- AQ v1 initial best
- AQ v2 initial best
- AQ v2 final best

contour, semantic part, silhouette, multi-view structure, topology, UV, material, build/render/
iteration/rollback 수, termination reason, package 결과와 duration을 기록한다. contact sheet와
human-evaluation manifest를 만들 수 있지만 사람이 실제 평가하지 않았다면 `human-reviewed`라고
표시하지 않는다. benchmark evidence 없이 “AQ v2가 실제 reference 품질을 향상했다”고 주장하지
않는다.

## 12. MaterialGraph runtime compiler

`MaterialGraphSpec 0.1.0`을 기존 MaterialPlan/ShaderRecipe `0.5.0`의 대체물로 만들지 않는다.
현재 AQ v2 runtime compiler contract, registry와 fixed Blender script는 registry에 등록된
template, node type, socket과 연결 규칙만 Blender node로 compile하도록 구현되어 있다. host
strict/negative tests와 실제 Blender compile·save/reopen·node inventory fixture가 통과했다. 이
fixture는 whitelist compiler의 실행 증거이지 arbitrary graph, 고급 shader 품질 또는 목적지
runtime parity 증거가 아니다.

현재 registry v2 whitelist는 Texture Coordinate, Mapping, Image Texture, Noise, Voronoi, Wave,
Gradient, 2-stop Color Ramp, Mix Color, Math, Separate/Combine Color, Normal Map, Bump, Fresnel,
Principled BSDF, Transparent BSDF, Emission, Mix Shader와 Material Output의 20개 template으로
제한한다. Noise/Voronoi는 3D, Separate/Combine은 RGB, Math는
add/subtract/multiply/divide/minimum/maximum subset이다. current registry SHA-256은
`b51acc851cf3f9609fdd48a90a2bdc34358bc718b1f05d0ce7a92f5c099231e8`이고, 기존 7-template
evidence는 legacy SHA-256
`57818419668d417ff2018159af37102976b71b3c4325b1bfce18588f8d61ec10`으로 계속 검증한다.

각 node는 허용 socket, enum, numeric range, texture role을 strict schema로 제한한다. graph node
수, graph depth, texture 수와 output 수에 profile hard cap을 둔다. cycle, unknown socket,
unsupported connection과 missing dependency는 compile 전에 거부한다.

다음은 허용하지 않는다.

- Script node, arbitrary node type 또는 arbitrary expression
- arbitrary node group/file path
- driver, Python callback 또는 external executable
- unsupported custom node와 임의 Blender source execution

compiler는 compiled material blend, compile report, node inventory, dependency manifest, deterministic
graph fingerprint, unsupported-feature finding과 portable approximation report를 발행한다. neutral
studio preview와 reference-matched preview는 서로 다른 evidence로 보존한다. reference preview만
좋다는 이유로 material을 통과시키지 않는다.

## 13. Material Authoring 0.1

기존 균일 256 PBR 경로는 삭제하지 않고 `uniform_portable_fallback_v1`이라는 제한된 fallback
의미로 유지한다. 고품질 경로의 기본값 또는 실제 공간 디테일 증거로 부르지 않는다.

현재 local host service는 아래 8개 strategy의 raw PBR channel, exact provenance와 immutable
receipt를 결정론적으로 생성한다. 별도 isolated Blender 5.0.1 smoke에서 wood, metal,
signage/decal, emissive, crystal의 fixed Principled compile·save/reopen·render는 `5 passed`를
기록했다. 다만 이 receipt는 canonical authoring manifest를 바꾸지 않으며 master compile과
neutral/reference preview 상태는 계속 `not_run`, manifest 상태는 `unverified` 또는
`review_required`다. 자세한 현재 계약은 `MATERIAL_AUTHORING_KO.md`를 따른다.

### 13.1 authoring strategy

| strategy | 핵심 입력과 경계 |
|---|---|
| `user_image_pbr_v1` | 사용자 제공 채널의 exact hash, provenance/license, color space, UV와 stale fingerprint 검증 |
| `localized_decal_v1` | 사용자 이미지 또는 exact text, project-local font, bounded UV rect/mask, alpha/mip padding |
| `planar_reference_patch_v1` | reference hash와 observed bounded polygon의 perspective rectification; 자동 corner는 advisory |
| `procedural_wood_v1` | grain/ring/knot/roughness/pore/end-grain/finish를 물리 scale과 deterministic seed에 결속 |
| `procedural_metal_v1` | base metal, bounded roughness, brushed direction, subtle normal; 근거 없는 scratch 금지 |
| `emissive_pattern_v1` | source-bound emission pattern과 neutral/reference evidence |
| `crystal_portable_approximation_v1` | Blender master transmission/IOR/absorption과 portable PBR 근사의 명시적 분리 |

`user_image_pbr_v1`은 Base Color, Roughness, Metallic, Normal, Height, AO, Opacity, Emission을
지원하되 각 channel의 dimensions, colorspace, containment, channel consistency, UV set, texel
density와 source hash를 검사한다.

`localized_decal_v1`은 간판, 로고, 라벨, 경고 표시와 고유 문양을 대상으로 한다. 판독할 수
없는 문구를 임의로 발명하지 않는다. 사용자가 exact text를 주지 않았거나 source에서 확실히
관찰되지 않으면 `unknown_text` 또는 `inferred_placeholder`로 남긴다. project-local font만
결정론적으로 rasterize한다.

`planar_reference_patch_v1`은 reference hash, 네 corner 또는 bounded polygon, semantic ID,
confidence, observed/inferred 상태와 output resolution을 결속한다. source crop, rectification,
mask와 cleanup의 provenance를 immutable하게 남긴다.

wood 결과는 Blender master material, neutral/reference preview, optional bake와 raw Base Color,
Roughness, Normal, Height/AO manifest를 포함한다. spatial variance, grain axis, physical scale,
seam, mapping과 bake resolution을 검사한다. metal은 근거 없는 마모·스크래치를 추가하지 않는다.
crystal은 master shader와 portable approximation을 분리하고 transmission, refraction, thickness,
absorption이 GLB/FBX에서 동일하다고 주장하지 않는다.

### 13.2 AssetScaleContext와 해상도

고정 256을 high-quality 기본값으로 사용하지 않는다. projected pixel footprint, target texel
density, object bounds, material family, unique/tileable/decal 유형과 package budget으로 256,
512, 1024, 2048, 4096 tier를 선택한다. 4096 초과는 별도 명시 없이 금지한다.

bevel, bump, displacement, grain scale, decal padding, contact tolerance와 texture resolution은
공통 AssetScaleContext resolver를 사용한다. 동일 형상의 0.1m, 1m, 10m fixture에서 상대 bevel,
grain/bump size, texel density, light size, camera clipping과 contact tolerance가 일관되는지
검사한다.

### 13.3 material quality

공통 quality evidence는 material contract, graph compile, channel existence, color space, UV
ownership, texel density, bake status, raw PBR와 package mapping을 포함한다.

- wood: grain direction, non-uniform spatial detail, scale, seam, normal/roughness variation
- signage/decal: source/text provenance, placement, crop/rectification, alpha edge, UV fingerprint
- metal: metallic consistency, bounded roughness variation, normal scale, unsupported scratch
- crystal/emissive: emission, opacity/transmission approximation과 feature-loss report

neutral studio evidence가 누락되면 reference-matched preview만으로 pass시키지 않는다.

## 14. Advanced Material Handoff

기존 V0.9 Destination Handoff contract와 exact approval을 변경하지 않는다. AQ v2는 다음 정보를
담는 companion `AdvancedMaterialContract 0.1.0`을 package/handoff 계획에 제공한다.

- material ID와 family
- raw PBR channel mapping, color spaces와 normal convention
- authoring shader feature와 portable approximation
- required destination feature와 unsupported feature
- preferred shader family와 approximation policy
- transparency, double-sided, emission, clear coat
- transmission, IOR, thickness/absorption이 있는 경우 해당 값
- source hashes, confidence와 limitation

Unity URP/HDRP용 host 계획 generator는 standard PBR, clear coat, emissive, crystal에 대한
advisory JSON을 만든다. 현재 output은 `advanced_material_handoff_request.json`, 대상에 따른
`unity_urp_material_plan.json` 또는 `unity_hdrp_material_plan.json`, 그리고
`advanced_material_handoff_receipt.json`이다. limitation은 JSON plan 안에 들어가며 별도
`known_limitations.md`가 생성된다고 가정하지 않는다. 이 결과는 Unity 프로젝트 수정, importer
실행 또는 runtime parity 증거가 아니다.

## 15. quality terminal과 DeliveryProfile 분리

AQ v1의 `portable_gltf` 고정 의미는 유지한다. v2는 다음 값을 RootAuthorization과 immutable
plan에 분리해 결속한다.

- `authoring_profile`
- `quality_profile`
- `allowed_delivery_profiles`
- `requested_delivery_profiles`
- `destination_hint`

최종 IQ 0.2가 accepted되면 exact canonical SceneSpec, geometry payload, authoring blend,
MaterialPlan/ShaderRecipe/TextureManifest, build provenance와 IQ evidence를 묶은
quality-approved source freeze를 발행한다. passed IQ의 source/input map은 current canonical
ModelingPlan, SceneSpec, blend, build provenance, MaterialPlan, ShaderRecipe, TextureManifest,
external geometry와 accepted geometry/material promotion receipt 및 GeometryIntent survival에 exact
결속해야 한다. 누락되거나 superseded된 source를 summary field로 보완하지 않는다. 이 freeze가
delivery plan의 유일한 source다.

v2 freeze에는 `geometry_candidate_validation_receipt`와 `material_phase_receipt`가 명시적 필수
필드다. receipt가 없는 호환 분기는 없으며 publish, reuse, delivery 직전마다 두 receipt와 current
canonical source 및 host-recomputed IQ를 다시 검증한다.

`QualityTerminalV2`는 quality 결과를 먼저 종결한다. `quality_approved`는 exact IQ report와
source freeze를 결속하고, `review_required`는 source freeze 대신 exact review bundle을 결속한다.
`blocked`와 `failed`는 review bundle을 delivery 성공처럼 가질 수 없다. non-pass terminal과
DeliveryProfile의 `review_only`는 서로 다른 의미다. 후자는 quality-approved freeze 이후 선택하는
package 없는 delivery 결과다.

DeliveryProfile 0.1의 초기 값은 다음과 같다.

- `review_only`
- `portable_gltf`
- `portable_fbx`
- RootAuthorization이 허용한 경우 둘 이상의 독립 delivery profile

GLB와 FBX는 서로 변환하지 않는다. 동일한 frozen canonical 또는 승인된 derived Blender
source에서 각각 직접 export한다. 각 format은 별도 package ID, optimization plan, exact V0.7
approval, manifest, dependency manifest, clean-import roundtrip, material/geometry loss report와
handoff eligibility를 가진다. 한 포맷의 성공이 다른 포맷 성공을 의미하지 않으며 format-specific
failure가 다른 package를 덮어쓰지 않는다.

generic AQ authorization은 V0.7 exact optimization-plan SHA-256 approval이나 Destination
Handoff approval을 사용자 승인으로 위조하지 않는다. RootAuthorization은 처음 허용한 output
범위를 넘어 새 format이나 destination을 실행 중 추가할 수 없다.

portable `DeliveryTerminalV2`는 exact quality terminal, source freeze, delivery plan,
`DeliveryReviewBinding`과 format별 results를 함께 hash-bound한다. result마다 review entry,
optimization approval, package, roundtrip, material loss와 geometry survival evidence가 plan의
identity와 일치해야 한다. `review_only`만 있는 terminal은 V0.7 review binding을 가질 수 없다.
현재 public AQ v2 supervisor는 quality-approved terminal에서 review/approval 경계를 거쳐 delivery
executor와 nested terminal validator까지 호출한다. host supervisor test에서 `review_only`가,
별도 synthetic Blender fixture에서 독립 GLB+FBX production/clean import가 통과했다. test fixture의 exact approval artifact는 승인
검증을 위한 입력이며 실제 사용자가 대화형으로 production plan을 승인했다는 증거가 아니다.
DeliveryTerminal validator는 참조된 QualityTerminal을 단순 hash/상태 비교로 신뢰하지 않고 full
QualityTerminal validator를 nested 호출한다. 따라서 forged `quality_approved` terminal, stale IQ
source 또는 불완전 source freeze를 가진 delivery chain은 package가 존재해도 거부된다.

## 16. optimization, package와 clean import

AQ v2 package preflight는 source freeze와 GeometryIntent survival receipt를 요구한다. optimizer는
다음 원칙을 따른다.

- LOD0의 UV0, material assignment와 evaluated normal을 보존하고 before/after snapshot을 남긴다.
- normal이 유효한 경우 unconditional recalculation로 authored intent를 덮지 않는다.
- UV1 생성은 UV0 교체와 분리한다.
- intent-protected mesh의 consolidation/join은 보존을 증명할 수 있을 때만 허용한다.
- higher LOD의 triangle 감소는 승인된 loss로 기록하며 semantic/material traceability를 유지한다.
- canonical authoring source는 절대 수정하지 않는다.

package 내부에는 expected intent/equivalence/loss manifest를 포함할 수 있다. clean import 후의 actual
survival report는 immutable package를 수정하지 않고 optimization/roundtrip의 run-owned evidence로
발행한다. package manifest는 exact relative paths, 모든 file SHA-256, dependency closure와 no-path-
escape를 계속 요구한다.

GLB/FBX roundtrip은 imported bounds, semantic/material identity와 dependency에 더해 LOD0의 UV,
surface normal, per-face material과 visual surface equivalence를 검사한다. 독립 inspector가 없는
axis/unit metadata, custom tangent 또는 format feature는 검증됐다고 표시하지 않는다.

## 17. ControllerExecutor

### 17.1 protocol

기존 `desktop_in_session` 실행 모드는 유지한다. 새 protocol은 controller 구현을 교체 가능하게
하되 authority를 확대하지 않는다.

```python
class CandidateAuthoringController(Protocol):
    def execute(
        self,
        assignment,
        immutable_inputs,
        allowed_output_paths,
        tool_profile,
        timeout,
    ) -> ControllerResult: ...
```

이 protocol과 다음 구현은 현재 host 코드에 존재한다.

- `DesktopInSessionController`: 기존 동작 wrapper, exact assignment/output/completion/hash 검증
- `FakeControllerForTests`: success, timeout, stale, partial, path escape, extra output와 반복 실패 주입
- `OptionalCodexAppServerController`: 공식 interface가 supporting client에서 명시적으로 주입된
  경우만 호출 가능한 optional adapter

Optional adapter는 API/명령을 추측하지 않는다. credential을 저장소에 저장하지 않고 controller
전용 격리 workspace에서 immutable input snapshot과 allowed output directory만 노출한다. canonical
job root는 controller가 직접 쓰지 못한다. supervisor가 결과 file set, schema, exact hash, path와
extra-file policy를 검증한 뒤 staging으로 복사하고 별도 promotion을 수행한다. 실제 sandbox/
allowlist attestation을 만들지 못하면 adapter는 `experimental_unverified`로 유지한다.

### 17.2 bounded closed loop

기존 AQ v1의 `autonomy-run`은 별도 v1 public surface다. AQ v2는 public
`autonomy-v2-advance`와 `autonomy-v2-run`을 제공한다. 전자는 한 bounded action, 후자는
global/per-phase budget 안의 여러 action을 처리한다. 둘 다 controller output, caller-supplied IQ,
V0.7 exact approval 또는 다른 specialized evidence가 없으면 해당 경계에서 정지한다. Desktop
controller는 adopt-only이므로 repository가 새 Codex task를 spawn해 output을 만든다는 뜻은 아니다.

같은 assignment/input/output에서 재실행한 duplicate action은 거부한다. partial output과 allowed
root 밖의 file은 candidate로 채택하지 않는다. raw ControllerExecutor는 timeout receipt에
`retryable=true`를 기록할 수 있지만 AQ v2 bridge는 timeout을 즉시 nonretryable `failed` terminal로
끝내며 새 invocation을 만들지 않는다. deterministic schema/build/contract failure도 자동 retry하지
않는다.

waiting controller invocation은 같은 request/execution workspace를 유지한다. public advance/run은
모든 input과 protected job-root source를 exact rehash한 뒤에만 output을 채택하며, no-output이면
state와 budget을 전혀 전진시키지 않는다. 전체 state chain도 initial state, transition, source/input,
producer, provenance delta와 monotonic budget을 재구성해 phase splice와 rollback을 거부한다.
execution-root `result.json`과 `adoption/result.json` 복구는 request, immutable input snapshot, tool
profile, output inventory, lifecycle receipts와 저장된 exact result bytes를 모두 재구성한다. 직접
side effect 전에는 session의 `RootAuthorizationV2`가 active·미만료이며 exact plan/profile/budget,
phase profile과 delivery scope에 결속됐는지도 다시 확인한다.

## 18. phase tool profile

기존 전체 MCP 도구 목록과 기존 Codex 사용을 제거하지 않는다. production/controller assignment에
별도의 exact-hash-bound phase profile을 추가한다.

| profile | 허용 책임 | 금지 책임 |
|---|---|---|
| `reference_readonly` | reference 분석과 상태 조회 | 모든 write |
| `geometry_authoring` | candidate staging geometry | canonical/package/handoff write |
| `material_authoring` | material candidate root | geometry canonical 변경 |
| `quality_readonly` | immutable evidence 평가 | candidate/canonical 변경 |
| `delivery` | frozen source read, derived package | authoring source/destination write |
| `handoff_plan` | package-bound plan 작성 | destination project 수정 |
| `admin_audit` | bounded read-only audit | repair/migration/delete |

각 profile은 허용 도구, 금지 도구, file role, canonical write 권한, network 정책, destination write
정책과 exact profile hash를 가진다. RootAuthorization과 assignment 모두 같은 profile hash를
가리켜야 한다. public MCP allowlist는 host safety envelope보다 넓은 권한을 부여할 수 없고,
호출자가 전달한 path 제한은 envelope를 좁힐 수만 있다.

## 19. service facade와 state transition

큰 v1 `autonomy/service.py`의 기존 import, CLI와 MCP 호출은 facade로 유지한다. v2는 별도
`autonomy_v2/planner.py`, `controller_bridge.py`, `candidate_validation_service.py`,
`material_phase_service.py`, `quality_terminal_service.py`, `delivery_service.py`,
`delivery_executor.py`, `supervisor_service.py`, `transitions.py`에 구현되어 v1 service 의미를
바꾸지 않는다. 아래 세분화는 향후 v1 facade를 더 작게 나눌 때의 목표이며 현재 모두 존재하는
module 목록이 아니다.

```text
autonomy/
├─ session_service.py
├─ candidate_phase_service.py
├─ material_phase_service.py
├─ promotion_service.py
├─ quality_terminal_service.py
├─ package_terminal_service.py
├─ review_terminal_service.py
├─ recovery_service.py
├─ controller_bridge.py
└─ transitions/
```

가능한 상태 변화는 다음 형태의 순수 함수로 분리한다.

```text
next_state = transition(current_state, event, immutable_evidence)
```

파일 쓰기, Blender 실행, authorization 소비와 canonical compare-and-swap은 service/executor가
담당한다. facade는 기존 v1 경로를 기존 함수로 dispatch하고 v2 profile만 신규 service로 보낸다.
리팩터링 전후 동일 v1 event/evidence에 같은 상태가 나오는 golden transition test를 둔다.

새 service 메서드와 변경 메서드는 저장소 규칙에 따라 기능 설명 docstring 또는 주석을 가진다.

## 20. authorization, promotion과 복구 불변 조건

- user input과 `workspaces/*/input/`은 immutable evidence다.
- controller/adviser는 canonical을 직접 쓰지 않는다.
- 모든 canonical promotion은 exact source/candidate hash 재검증, history archive, atomic replace,
  result hash 검증과 immutable receipt 순서를 따른다.
- `PolicyAuthorization`은 user approval이 아니며 `approved_by=user`를 합성하지 않는다.
- 기존 Workflow/InteriorScope/V0.6 revision/V0.7 optimization/Handoff approval을 대체하지 않는다.
- `RootAuthorizationV2`는 exact plan/profile/budget/tool profile과 delivery scope에 결속된
  session-scoped `active|expired|cancelled` 권한이다. specialized approval과 action grant만 각 계약이
  정한 single-use 소비 규칙을 따른다.
- source, profile, plan 또는 candidate가 stale이면 fail-closed다.
- non-improvement/regression은 canonical에 적용하지 않거나 exact archived source로 복원한다.
- complete receipt를 덮어쓰지 않고 incomplete staging을 성공 evidence로 채택하지 않는다.
- lock expiry만으로 writer ownership을 탈취하지 않는다.
- cancellation은 미래 action을 중단할 뿐 기존 canonical/immutable evidence를 삭제하지 않는다.
- cycle, plateau, budget exhaustion과 repeated failure를 quality pass로 재분류하지 않는다.
- 안전한 best-known candidate가 있으면 review-only로 라우팅하며 package/handoff eligibility는 false다.

## 21. instruction, CI와 registry 동기화

AQ 0.2 구현은 root `AGENTS.md`의 안전 규칙을 보존하면서 실제 instruction loading 한도에 맞게
root와 leaf instruction을 계층화한다. root는 12 KiB 이하, 특정 작업 경로의 root→leaf 합은
28 KiB 이하를 목표로 한다. immutable input, JSON source of truth, 사용자 변경 보호, reset/clean/
restore 금지, synthesized approval 금지, controller-only canonical write, arbitrary code 금지,
package/review 구분, destination write 금지와 무검증 지원 주장 금지는 root에 남긴다.

`scripts/check_agent_instructions.py`는 byte size, required sentinel, conflicting rule, missing leaf와
docs link를 검사한다. 단순히 `project_doc_max_bytes`를 크게 올려 문제를 숨기지 않는다.

현재 CI 정의의 역할은 다음과 같다.

- `python-ci.yml`: project minimum과 Blender bundled 기준인 Python `3.11` 고정, frozen dependency
  sync, Ruff, 전체 pytest, AQ v1/v2 deterministic benchmark,
  AQ v2 host/schema/public/catalog/controller/material contract, instruction 검사와
  registry/README/tree/manifest 동기화
- `blender-smoke.yml`: `workflow_dispatch` 기반 self-hosted Windows/Blender 5 runner에서
  `run_autonomous_quality_gates.ps1 -RunBlender`를 호출한다. 이 gate는 AQ v1/legacy 호출을 보존하고
  v2 geometry, material graph, benchmark와 material-authoring fixed smoke를 opt-in으로 실행한다.
  실제 GitHub runner 실행 결과가 없으므로 v2 intent/material/dual delivery 전체가 검증됐다고
  확대하지 않는다.

self-hosted runner나 Blender가 없으면 명확히 `not-run`/`skipped`로 기록한다. 실행되지 않은 job을
성공 증거로 사용하지 않는다. README builder/profile/output/MCP 목록과 verification summary는
authoritative registry에서 생성·검사하고 tracked tree/manifest 드리프트를 CI에서 실패시킨다.

## 22. 검증 계층과 활성화 gate

AQ v2 구현 완료 판정에는 다음 계층이 모두 필요하다.

1. strict contract/schema parity
   - MeshPayload 0.1/0.2 loader
   - unknown/non-finite/count/index/source-hash 실패
   - explicit migration plan/apply
2. GeometryIntent host/Blender
   - sharp box, UV seam cube, crease/subdivision, weighted-normal bevel
   - multi-material face, V03 loft+UV, V03 sweep+sharp, boolean+material group
   - duplicate effect 방지
3. 전체 survival 경로
   - V03 → payload 0.2 → compiled V02 → candidate → promotion
   - optimized LOD0 → 직접 GLB/FBX export → clean import
4. IQ 0.2
   - contour exact/misaligned, scale-normalized tolerance
   - critical semantic 누락, landmark present/absent
   - advisory unavailable, hard-gate precedence, Pareto와 reentry
5. material runtime/authoring
   - whitelist/forbidden graph, cycle/depth/socket/dependency
   - image/decal/rectification/exact text/unknown text
   - wood scale/direction, metal, emissive, crystal와 fallback regression
6. delivery/controller
   - v1 portable GLTF regression
   - v2 GLB, FBX, dual, review-only와 format-specific failure
   - fake controller timeout/partial/extra/stale/escape/repeat/crash/resume/cancel
7. legacy regression
   - standard, background_exterior, AQ v1
   - manual/bounded V0.6, V0.7 GLB/FBX/OBJ
   - V0.8 workflow, V0.9 production/audit/handoff, external intake와 기존 interior 경계
8. full repository
   - full pytest, Ruff, schema/docs/registry parity
   - 가능한 환경의 Blender 5.0.1 gate

`autonomous_static_prop_v2`는 위 필수 gate와 실제 기록이 모두 통과하기 전까지
`verified_active`가 될 수 없다. contract test만 통과하면 `contract_verified` 범위까지만 말할 수
있고 Blender unavailable이면 Blender support를 주장하지 않는다.

## 23. 구현 순서

대규모 동시 전환을 피하기 위한 권장 순서는 다음과 같다.

1. 구현 전 architecture/test/migration/verification 문서와 compatibility fixture 고정
2. instruction hierarchy와 drift checker를 기존 안전 규칙 손실 없이 추가
3. MeshPayload 0.2 model/schema/version-dispatch/migration 추가
4. materializer/custom_mesh/runtime와 candidate survival gate를 v2 opt-in으로 연결
5. GeometryIntent snapshot/report와 optimizer/package/roundtrip equivalence 추가
6. IQ 0.2 metric, ranking, reentry와 synthetic benchmark 추가
7. MaterialGraph runtime compiler와 neutral studio evidence 추가
8. Material Authoring/AssetScaleContext/material-quality/advanced handoff companion 추가
9. quality source freeze와 DeliveryProfile GLB/FBX 분리
10. controller protocol, fake adapter와 phase tool profile 추가
11. facade-preserving service extraction과 transition golden test
12. CI/registry/docs generator 연결
13. targeted → full host → 실제 Blender → V0.7~V0.9/AQ v1 chained regression
14. 실제 결과를 verification에만 기록하고 profile 상태 결정

각 단계는 기존 public v1 test가 통과하는 상태로 끝나야 한다. v2 일부가 준비되지 않았으면 해당
기능을 비활성 상태로 남기며 v1 의미를 바꿔 우회하지 않는다.

## 24. 예상 회귀 위험과 완화

| 위험 | 완화 설계 |
|---|---|
| legacy custom mesh가 strict v2 loader에 의해 거부됨 | explicit version dispatch와 기존 unversioned/0.1 loader 보존 |
| exporter reorder/split 때문에 false survival failure | canonicalized triangulated surface equivalence와 format tolerance |
| modifier가 bake와 recreate 양쪽에 중복됨 | effect별 disposition과 idempotent modifier marker |
| optimizer가 UV/normal intent를 덮음 | LOD0 before/after snapshot, conditional normal repair, UV0/UV1 분리 |
| multi-material slot 의미가 사라짐 | ordered slot companion과 polygon index bounds |
| generated/inferred evidence가 pass 권한을 얻음 | authoritative flag, unavailable/unscorable와 hard-gate precedence |
| 단일 aggregate가 critical part 누락을 숨김 | semantic per-ID score와 critical required set |
| 고해상도 texture가 budget을 무제한 소비 | AssetScaleContext와 resolution tier hard cap |
| controller가 canonical/외부 path를 씀 | isolated output root, exact file-set validation, supervisor promotion |
| v2 변경이 v1 state를 바꿈 | profile dispatch와 transition golden regression |
| GLB 성공을 FBX 성공으로 간주 | format별 독립 package/roundtrip/terminal evidence |
| fixture 성공을 일반 품질 향상으로 주장 | synthetic/project-local benchmark 범위와 상태 언어 분리 |

## 25. public surface 정책

기존 CLI, MCP와 Python import는 제거하거나 이름을 바꾸지 않는다. 특히 v1 autonomy,
Integrated Quality 0.1, SceneSpec V03 derived migration, V0.7 package, V0.8 workflow와 V0.9
handoff 공개 표면을 유지한다.

현재 신규 CLI는 `autonomy-v2-profile-status`, `autonomy-v2-delivery-profiles`,
`autonomy-v2-plan`, `autonomy-v2-status`, `autonomy-v2-advance`, `autonomy-v2-run`,
`autonomy-v2-cancel`,
`controller-executor-status`, `scene-spec-v03-migration-plan`과
`scene-spec-v03-migration-apply`다. 대응 MCP는 project allowlist에 명시적으로 등록되어 있다.
material-authoring companion 전용 CLI나 dual-delivery 자동 승인 명령은 없다. `run`은 approval을
합성하지 않고 exact V0.7 approval이 없으면 정지한다.
어떤 public surface도 exact-hash, allowed-output, single-use와 audit 불변 조건을 우회하지 않는다.

## 26. 안전성과 최종 제한

AQ 0.2가 구현되더라도 다음 제한은 유지된다.

- canonical input, authoring evidence와 사용자 workspace를 gate 성공용으로 수정하지 않는다.
- machine-readable JSON이 권위 원본이며 PDF는 파생 보고서다.
- package와 review bundle은 다른 terminal이다. review bundle은 production package가 아니다.
- uniform fallback은 고품질 texture가 아니다.
- generated/advisory evidence는 authoritative reference를 대체하지 않는다.
- actual Blender test 없이 Blender support를 주장하지 않는다.
- 실제 benchmark 없이 arbitrary-reference 품질 향상을 주장하지 않는다.
- GLB/FBX clean import는 Unity/Unreal/custom runtime parity가 아니다.
- advanced material handoff는 destination plan이지 engine shader graph 자동 생성 증거가 아니다.
- controller adapter가 공식 interface와 sandbox를 실제 증명하지 못하면 experimental이다.
- external provider는 기본 비활성이며 provenance/license/network authorization 없이 사용하지 않는다.
- 기존 approval을 policy authorization으로 변환하거나 포괄 승인으로 specialized gate를 대체하지
  않는다.
- project `0.9.0`과 AQ v1을 보존하며 AQ v2 구현만으로 V1.0 승격을 선언하지 않는다.

이 설계의 완료는 코드를 많이 추가하는 것으로 판정하지 않는다. v1 하위 호환, exact evidence
chain, 실제 GeometryIntent 생존, IQ 0.2의 권위 구분, material spatial detail, format별 direct
delivery, controller confinement와 실제 host/Blender/legacy gate가 함께 증명되어야 한다.
