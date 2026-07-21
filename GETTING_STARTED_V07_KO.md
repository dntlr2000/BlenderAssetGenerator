# V0.7.3 빠른 시작 — Portable Static Asset Cost & Delivery Core

V0.7은 승인된 Blender authoring scene을 바꾸지 않고, 다른 DCC나 런타임으로 전달할 수 있는 정적 자산 패키지를 만듭니다. 대상 엔진이 정해지지 않아도 사용할 수 있도록 GLB, FBX, OBJ 교환 계약과 raw PBR 채널을 우선합니다.

## 1. 설치와 기본 확인

```powershell
uv sync --frozen --extra dev --extra vision
uv run pytest
uv run ruff check .
uv run cbm doctor
uv run cbm blender-compat
```

V0.7 Blender 실기동 기준 환경은 Blender 5.0.1입니다. 기존 EEVEE feature probe, `--python-exit-code 1`, `stdin=DEVNULL`, exporter fallback을 그대로 사용합니다.

## 2. 시작 전 조건

Portable asset 작업을 시작하기 전에 선택한 job에 다음 자료가 있어야 합니다.

```text
analysis/scene_spec.json
blender/scene.blend
reports/scene_inventory.json
reports/validation.json
```

재질을 함께 전달하려면 현재 build fingerprint와 일치하는 V0.5 계약이 필요합니다. UV가 아닌 object/generated/triplanar mapping 또는 Blender 전용 procedural graph는 V0.7.1의 run-owned material conversion으로 portable atlas와 PBR 채널을 만든 뒤 패키징합니다. SceneSpec, geometry payload, MaterialPlan, ShaderRecipe, TextureManifest 또는 이미지 채널을 바꿨다면 먼저 `build`를 다시 실행해야 합니다.

V0.7은 canonical SceneSpec이나 `blender/scene.blend`를 최적화 결과로 덮어쓰지 않습니다.

### 2.1 선택적 실내 범위 확인

실내는 portable profile의 기본 요구사항이 아닙니다. `architecture/interior_scope.json`이 없으면 정책은 `disabled`이고, 외관 자산에는 추가 계약 파일이 생기지 않습니다.

```powershell
uv run cbm interior-scope-status <job-id>
```

실내가 있는 자산은 사용자가 명시적으로 요청한 scope와 현재 scope SHA-256에 결합된 승인만 허용합니다. scope가 `draft`, `stale`이거나 범위 밖 interior object가 있으면 먼저 authoring 단계에서 해결해야 합니다.

```powershell
uv run cbm interior-scope-validate <job-id>
```

scope 또는 approval을 바꾼 뒤에는 build provenance가 달라지므로 `build → inspect → validate`를 다시 통과한 새 source `.blend`에서 V0.7 preflight를 시작합니다. V0.7 package는 정적 실내 geometry를 전달할 수 있지만 interactive door, navigation, gameplay volume, light bake나 목적 엔진별 room system을 생성하지 않습니다. 자세한 opt-in 절차는 [선택적 실내 범위와 승인 가이드](INTERIOR_SCOPE_KO.md)를 참조합니다.

## 3. AssetProfile 선택

```powershell
uv run cbm asset-profile-init <job-id> `
  --profile portable_gltf `
  --asset-kind static_environment `
  --consolidation by_semantic_group `
  --budget-enforcement warning
```

지원 profile:

| profile | primary | 용도 | 주의점 |
|---|---|---|---|
| `portable_gltf` | GLB | 기본 engine-neutral 전달 | glTF ORM 파생본과 raw PBR 채널을 함께 보존 |
| `fbx_interchange` | FBX | 범용 DCC/엔진 교환 | raw PBR sidecar를 사용하며 importer material 재구성은 별도 |
| `obj_legacy` | OBJ | legacy geometry 전달 | custom property, LOD, collision 의미 손실 가능 |

Asset kind는 `static_prop`, `static_environment`, `static_architecture` 중 하나입니다. Rigged 또는 animated asset은 V0.7 범위가 아닙니다.

V0.7.3의 새 profile 옵션:

- `--consolidation none|by_semantic_group|by_spatial_cell`: derived 객체 배칭 정책
- `--spatial-cell-size-m`: spatial 배칭 셀 크기
- `--maximum-objects-per-batch`: 한 배치의 최대 source object 수
- `--budget-enforcement warning|fail`: 설정된 비용 budget의 처리 방식; budget 옵션을 생략하면 평가 항목이 없습니다.
- `--max-render-objects`, `--max-material-slots`, `--max-draw-calls`, `--max-lod0-triangles`, `--max-collider-triangles`, `--max-overlap-candidates`: 선택적 정적 비용 budget

기존 V0.7.2 profile 파일에는 새 필드가 없어도 로드되며 `consolidation.mode=none`으로 해석됩니다. 새 profile을 만들 때만 안전한 `by_semantic_group` 기본값이 명시됩니다.

넓게 배치된 환경 모델은 `by_semantic_group`으로 멀리 떨어진 객체까지 하나로 묶으면 목적 엔진의 공간 컬링 효율이 낮아질 수 있습니다. 이런 자산은 `by_spatial_cell`과 명시적인 `--spatial-cell-size-m`을 사용하고, 실제 컬링 성능은 목적 엔진 adapter 단계에서 측정하세요.

Profile 파일은 다음 위치에 저장됩니다.

```text
workspaces/<job-id>/asset_profiles/<profile-id>.json
```

## 4. Read-only preflight

```powershell
uv run cbm asset-preflight <job-id> `
  --profile portable_gltf `
  --run-id portable-review-01
```

Preflight는 canonical `.blend`를 읽기만 하며 다음을 검사합니다.

- stable semantic ID와 material ID
- topology, boundary/non-manifold/degenerate face
- transform과 negative scale
- normal/tangent 준비 상태
- UV 존재 여부와 profile 요구사항
- mesh/triangle budget 관련 finding
- embedded build fingerprint와 현재 source fingerprint

결과는 `optimization/runs/portable-review-01/mesh_preflight_report.json`에 저장됩니다. Failed finding이 있으면 최적화를 진행하지 말고 canonical 모델링 단계에서 원인을 해결한 뒤 새 run ID로 다시 시작합니다.

## 5. Pre-optimization review and approved derived optimization

```powershell
uv run cbm asset-plan <job-id> `
  --profile portable_gltf `
  --run-id portable-review-01

uv run cbm asset-plan-approve <job-id> `
  --run-id portable-review-01 `
  --plan-sha256 <optimization-review-plan-sha256> `
  --approval-note "표시된 LOD와 Collider 설정 승인"

uv run cbm asset-optimize <job-id> `
  --profile portable_gltf `
  --run-id portable-review-01 `
  --approved-plan-sha256 <optimization-review-plan-sha256>
```

출력 예:

```text
optimization/runs/portable-review-01/
├─ mesh_preflight_report.json
├─ optimization_plan.json
├─ execution_plan.json
├─ optimized_asset_evidence.json
├─ asset_cost_report.json
├─ optimized/scene.blend
├─ lod_manifest.json
├─ collision_manifest.json
└─ uv_manifest.json
```

`asset-optimize` 호출은 이 derived run 생성만 승인합니다. 원본 SceneSpec, geometry payload, material contract, source texture, canonical `.blend`는 읽기 전용입니다.

`asset_cost_report.json`에는 최적화 전후 LOD0 object 수, material slot 수, estimated draw-call proxy, vertex/triangle 수, LOD·collider 비용, consolidation batch, cleanup record, 반복 mesh group, AABB overlap 후보와 budget 판정이 기록됩니다. `estimated_draw_calls`는 목적 엔진에서 측정한 값이 아니라 material-slot 기반 비교 지표입니다.

자동 cleanup은 다음 범위로 제한됩니다.

- face에 쓰이지 않는 loose vertex/edge
- 같은 object 안의 중복 material slot
- semantic/strategy/world mesh가 완전히 동일한 collider
- semantic ID, material IDs, LOD, UV layer signature가 같은 derived object의 배칭

반복 mesh는 instancing 후보로만 보고하며, AABB overlap은 broad-phase 후보일 뿐입니다. Internal face, coplanar face, 실제 mesh intersection은 자동 삭제하지 않습니다.

## 6. Run-owned portable material conversion

```powershell
uv run cbm asset-material-convert <job-id> `
  --profile portable_gltf `
  --run-id portable-review-01 `
  --conversion-id portable-materials-01 `
  --resolution 1024 `
  --margin-px 16 `
  --render-device auto
```

이 단계는 canonical authoring 셰이더와 `.blend`를 수정하지 않습니다. 정확한 source/profile/run hash에 묶인 derived scene에서 공유 portable UV atlas를 만들고 Base Color, Roughness, Metallic, Normal, Emission 채널을 베이크합니다. 결과는 conversion 전용 디렉터리와 `portable_material_conversion_manifest.json`에 기록되며, 같은 conversion ID는 덮어쓰지 않습니다.

## 7. Immutable package

```powershell
uv run cbm asset-package <job-id> `
  --profile portable_gltf `
  --run-id portable-review-01 `
  --material-conversion-id portable-materials-01 `
  --package-id portable-package-01
```

패키지는 임시 staging 디렉터리에서 완성된 뒤 한 번에 승격됩니다. 같은 package ID는 덮어쓰지 않습니다.

```text
exports/packages/portable_gltf/portable-package-01/
├─ asset.glb
├─ textures/
├─ metadata/
│  ├─ asset_profile.json
│  ├─ execution_plan.json
│  ├─ mesh_preflight_report.json
│  ├─ lod_manifest.json
│  ├─ collision_manifest.json
│  ├─ uv_manifest.json
│  ├─ asset_cost_report.json
│  └─ delivery_mapping.json
├─ export_evidence.json
├─ texture_pack_manifest.json
└─ package_manifest.json
```

선택한 material conversion의 raw PBR 채널을 byte-for-byte로 보존합니다. `portable_gltf`는 별도로 `R=occlusion`, `G=roughness`, `B=metallic`인 glTF ORM을 만들며, 누락 채널은 manifest에 기록된 명시적 상수만 사용합니다. Package는 supplied conversion ID와 exact run/profile/source hash가 일치하지 않으면 실패합니다.

`execution_plan.json`은 Blender가 실제로 소비한 불변 계획입니다. `optimization_plan.json`은 완료 상태와 출력 영수증을 추가하는 실행 결과 계약이며, 둘의 해시는 패키징 전에 다시 검증됩니다.

## 8. Clean-import round trip

```powershell
uv run cbm asset-validate <job-id> `
  --profile portable_gltf `
  --package-id portable-package-01 `
  --bounds-tolerance-m 0.0001
```

새 Blender 프로세스가 package primary file만 가져와 다음을 확인합니다.

- 선택 format을 실제로 다시 열 수 있는가
- export operator의 축·meter 단위 선언과 imported bounds가 일관적인가. 파일 내부 축·단위 metadata는 직접 검사하지 않으므로 `unverified` 경고를 유지합니다.
- aggregate bounds 오차가 tolerance 이내인가
- semantic/material ID coverage가 profile의 보존 기대와 일치하는가
- UV, normal, tangent, texture dependency가 유효한가
- package 안에 누락 파일이나 절대 경로가 없는가

결과는 해당 optimization run의 `roundtrip/<package-id>/roundtrip_validation.json`에 기록됩니다.

## 9. 상태와 PDF

```powershell
uv run cbm asset-status <job-id>
uv run cbm report-pdf <job-id> `
  --scope export `
  --optimization-run-id portable-review-01 `
  --package-id portable-package-01
```

PDF와 sidecar manifest는 기본적으로 다음 위치에 생성됩니다.

```text
output/pdf/<job-id>/export_report.pdf
output/pdf/<job-id>/export_report.manifest.json
```

PDF는 사람이 검토하는 projection입니다. 자동 판정은 계속 AssetProfile, preflight, manifests, package receipt, RoundTripValidation JSON을 사용합니다.

## 10. 격리 smoke gate

```powershell
.\scripts\run_v07_gates.ps1
```

이 스크립트는 매 실행마다 `reports/v07_smoke/<run>/workspaces`를 새로 만들고 `geometry_showcase`만 import합니다. 사용자의 기존 workspace를 읽거나 변경하지 않습니다. 생성된 smoke 자료는 진단을 위해 남겨 둡니다.

InteriorScope의 default-disabled, draft/stale approval, prefix/level/space와 facade-helper 회귀는 전체 `pytest`의 `tests/test_v072_interior_scope.py`에서 별도로 검사합니다. 실제 interior job의 portable 검증은 사용자가 scope hash를 승인한 뒤 해당 job ID로 수행합니다.

## 11. V0.7 경계

V0.7이 제공하지 않는 항목:

- Unity prefab/importer, Unreal actor/import task 또는 다른 엔진 전용 adapter
- Unity smoothness, Unreal mask convention 등 대상 엔진 전용 패킹
- 엔진별 shader graph 자동 재구성
- rig, skinning, animation, skeletal LOD
- 수작업 수준의 retopology, seam authoring, atlas packing
- 모든 collider의 gameplay 적합성 보장

대상 엔진을 정한 뒤에는 immutable package와 raw PBR 채널을 입력으로 별도 adapter를 설계하고, 실제 엔진 import 결과를 검증해야 합니다.
