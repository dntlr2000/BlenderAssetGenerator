# V0.7.3 아키텍처 — Engine-neutral Portable Static Asset Cost & Delivery Core

## 버전 계약

| 계층 | 버전 | 역할 |
|---|---:|---|
| 프로젝트 | `0.7.3` | portable material conversion, opt-in interior safety, derived-only cleanup·cost evidence를 포함한 통합 static-asset 기능 |
| SceneSpec | `0.2.0` | canonical geometry, transform, assignment, camera |
| Reference/Constraint | `0.4.0` | 진단, 카메라 가정, measured residual |
| Optional InteriorScope | `0.1.0` | 명시적 실내 경계, exact-hash user approval, fail-closed validation |
| Material/Shader/Texture/Bake | `0.5.0` | authoring material과 portable raw 채널 |
| Render pass/Visual QA/Approval | `0.6.0` | 직접 비교와 guarded revision |
| Asset/Optimization/Package/Round trip | `0.7.0` | derived static-asset delivery |

V0.7은 SceneSpec에 export 필드를 덧붙이지 않습니다. Canonical authoring 계약과 derived delivery 계약을 분리해 기존 geometry/material/QA 작업을 다시 마이그레이션하지 않습니다.

## 데이터 흐름

```text
approved canonical source
  ├─ SceneSpec + geometry payloads
  ├─ optional InteriorScope + exact-hash approval (absence = disabled)
  ├─ verified source scene.blend + embedded build fingerprint
  ├─ stable semantic/material IDs
  └─ optional current V0.5 baked PBR channels
          ↓ freeze SourceProvenance
AssetProfile 0.7
          ↓ read-only Blender inspection
MeshPreflightReport
          ↓ derived run authorization
OptimizationPlan
          ↓
optimized scene.blend
  ├─ LODManifest
  ├─ CollisionManifest
  ├─ UVManifest
  └─ StaticAssetCostReport
          ↓ run-owned material conversion
PortableMaterialConversionManifest 0.7
  ├─ shared portable atlas UV
  ├─ portable material scene
  └─ raw Base Color/Roughness/Metallic/Normal/Emission
          ↓ atomic package build
raw PBR preservation + optional profile packing
          ↓
ExportPackageManifest
          ↓ clean Blender import
RoundTripValidation
          ↓ read-only projection
export PDF + sidecar source manifest
```

## SourceProvenance와 stale 차단

모든 preflight/optimization run은 다음을 고정합니다.

- SceneSpec path/hash
- canonical `.blend` path/hash
- embedded build fingerprint
- external geometry/heightmap payload hashes
- optional MaterialPlan hash
- TextureManifest hashes
- optional InteriorScope와 matching approval의 path/hash
- 결합 source fingerprint

Preflight 뒤 source가 바뀌면 같은 run ID로 optimization을 이어가지 않습니다. Packaging 전에도 source를 다시 비교합니다. Derived artifact를 만들었다는 이유로 canonical authoring state를 갱신하거나 정당화하지 않습니다.

## Optional InteriorScope 안전 경계

InteriorScope는 V0.7 package 기능이 아니라 그 이전 형상 authoring 단계의 opt-in 안전 계약입니다. 파일이 없으면 실내는 `default_disabled`이고 exterior-only workspace에 새 계약 파일이 생기지 않습니다. Scope가 있으면 해당 파일과 approval hash가 build fingerprint에 포함되며, scope 변경 뒤 과거 source `.blend`는 stale입니다.

실내 객체는 `.interior` semantic namespace 또는 명시적 interior tag로 식별하고 승인된 prefix·level·space·furnishing·evidence 경계를 통과해야 합니다. Scope 초안은 권한이 아니며 현재 SHA-256과 일치하는 사용자 approval이 필요합니다. Facade backing, window recess, door reveal과 exterior wall thickness는 interior ID/tag를 사용하지 않는 외관 보조 형상으로 유지할 수 있습니다.

V0.7 optimization과 packaging은 승인된 정적 실내 mesh도 다른 geometry처럼 derived 처리하지만 의미를 확장하지 않습니다. Interactive door, navigation, gameplay volume, 엔진 room system, light bake와 runtime shader는 목적 엔진을 고른 뒤 별도 adapter가 책임집니다.

## AssetProfile

AssetProfile은 특정 엔진 API가 아니라 교환 의미를 정의합니다.

```text
profile identity and primary format
units / up axis / forward axis
LOD policy and silhouette thresholds
collision strategy
UV0/UV1 requirements
texture preservation and packing policy
derived consolidation and cleanup policy
optional warning/fail static cost budgets
known limitations
```

기본 profile:

- `portable_gltf`: GLB와 glTF metallic-roughness 의미
- `fbx_interchange`: FBX geometry/material identity와 raw PBR sidecar
- `obj_legacy`: 제한된 legacy geometry 전달

Profile은 Unity, Unreal, Godot 또는 proprietary engine의 import 결과를 보장하지 않습니다.

## Read-only preflight

Host는 profile과 canonical provenance를 검증한 뒤 Blender 5-compatible diagnostic script를 실행합니다. Blender raw evidence를 Pydantic `MeshPreflightReport`로 정규화합니다.

검사 범주:

```text
topology
transform
normal / tangent
material identity
UV requirements
triangle budget
```

`canonical_unchanged=true`는 계약 불변값입니다. Preflight는 수정 도구가 아니며 자동 cleanup도 하지 않습니다.

## Optimization run

```text
optimization/runs/<run-id>/
```

각 run은 immutable source/profile에 묶입니다. Blender는 canonical 파일과 분리된 `optimized/scene.blend`에서만 derived LOD, collider, UV 데이터를 만듭니다.

### V0.7.3 cleanup, consolidation, cost

V0.7.3은 canonical authoring data를 수정하지 않고 run-owned derived scene만 정리합니다. 기본 신규 profile은 `by_semantic_group`을 사용하며 다음 값이 모두 같은 객체만 한 배치로 결합합니다.

```text
stable semantic ID
ordered material ID list
LOD level
UV layer signature
optional spatial cell
```

결합 전후 triangle 합계는 같아야 하며, LOD budget은 배치된 전체 mesh가 아니라 source instance별 원래 triangle 수를 기준으로 검증합니다. 기존 V0.7.2 profile은 새 필드가 없을 때 `mode=none`으로 로드되어 과거 derived 결과를 암묵적으로 바꾸지 않습니다.

자동 cleanup 허용 범위는 loose vertex/edge, 중복 material slot, exact duplicate collider입니다. Render mesh의 AABB overlap, internal/coplanar face, 실제 face intersection은 자동 삭제하지 않습니다. Repeated mesh fingerprint는 향후 destination adapter가 instancing을 선택할 수 있는 advisory evidence입니다.

`StaticAssetCostReport 0.7.0`은 다음을 기록합니다.

```text
before/after LOD0 object and material-slot counts
estimated draw-call proxy
vertex/triangle and total derived triangle counts
LOD and collider object/triangle counts
consolidation batches and cleanup records
exact repeated-mesh groups
broad-phase AABB overlap candidates
warning/fail budget results
unverified runtime/internal-face checks
```

Estimated draw calls는 material-slot proxy이며 목적 엔진의 runtime 측정치가 아닙니다. `budget.enforcement=fail` 위반은 derived run을 실패시키지만 canonical 파일은 그대로 유지합니다.

### LOD

- LOD0은 source 의미와 material ID를 보존합니다.
- Profile target ratio에 따라 LOD1+를 생성합니다.
- 각 entry는 triangle count, ratio, bounds, semantic/material identity와 artifact hash를 기록합니다.
- 현재 자동 decimation은 static mesh용 보수적 fallback이며 silhouette-critical authored LOD를 대체하지 않습니다.
- 전용 silhouette 검증을 아직 실행하지 않은 derived LOD는 `quality_status=partially_verified`와 `unverified_checks=[silhouette_iou]`로 명시합니다.

### Collision

- Strategy: none, primitive, convex hull, compound, mesh proxy 계열
- Collider는 render geometry와 분리된 derived object입니다.
- Gameplay 적합성, walkability, trigger 의미는 엔진 adapter에서 별도 검토합니다.

### UV

- 기존 UV0가 있으면 보존합니다.
- Profile이 요구할 때 missing UV0 또는 UV1을 bounded Blender operator로 생성합니다.
- degenerate UV는 측정해 기록합니다. overlap과 texel density를 측정하지 못한 run은 null을 만들고 `quality_status=partially_verified`로 명시하며 통과값을 추정하지 않습니다.
- 자동 UV1은 lightmap-ready 후보이지 특정 엔진 lightmapper의 통과 보장이 아닙니다.

## Texture packing

V0.5 계약은 canonical authoring material evidence입니다. V0.7.1은 object/generated/triplanar 또는 Blender 전용 graph를 canonical 파일에 손대지 않고 exact optimization run에 묶인 portable atlas와 PBR 채널로 변환합니다. Conversion ID, source/profile/run fingerprint, Blender runtime, atlas UV, material별 output hash와 알려진 손실을 `PortableMaterialConversionManifest 0.7.0`에 기록합니다.

Package 계층은 명시적으로 선택한 conversion의 raw 이미지를 byte-for-byte 복사한 뒤 profile packing을 파생합니다. Stale conversion, 다른 run/profile의 conversion, incomplete output은 package 승격 전에 거부합니다.

```text
raw/
  base_color, roughness, metallic, normal, emission, ...
packed/
  gltf_orm.png   # R=occlusion, G=roughness, B=metallic
```

FBX는 현재 Blender 이미지 의존성을 주 파일에 포함하고 raw PBR sidecar도 별도로 보존합니다. OBJ는 exporter의 `COPY` 경로 정책으로 패키지 루트에 호환 텍스처를 복사하고 MTL에는 상대 파일명을 기록합니다. 두 형식 모두 raw PBR sidecar와 `TexturePackManifest`가 재질 재구성의 권위 있는 근거이며, 형식 자체가 모든 PBR 의미를 보존한다고 주장하지 않습니다.

모든 packed channel은 source artifact, optional constant, inversion 여부, color space, resolution, output hash를 기록합니다. Engine-specific smoothness/mask packing은 V0.7에 포함하지 않습니다.

## Atomic package

Package는 job-local staging에서 완성한 뒤 최종 directory로 원자적으로 승격됩니다. Existing package ID는 overwrite하지 않습니다.

`ExportPackageManifest`는 다음을 보장합니다.

- primary file과 모든 sidecar의 relative path, media type, byte size, SHA-256
- optimization plan과 source manifests hash
- semantic/material ID 목록
- absolute path count와 missing dependency count
- known format losses, warnings, errors
- `canonical_unchanged=true`

## Clean-import round trip

Exporter 성공만으로 package를 완료로 간주하지 않습니다. Fresh Blender process에서 primary file을 다시 가져오고 normalized inventory를 만듭니다.

비교 범위:

- format import 성공
- export operator의 meter/axis 선언과 imported bounds를 통한 간접 정규화 근거. 파일 내부 metadata는 별도 inspector가 없으면 `unverified`
- aggregate bounds tolerance
- expected/observed semantic IDs
- expected/observed material IDs
- UV, normal, tangent
- texture/dependency availability

OBJ처럼 custom property를 보존하지 않는 format은 알려진 loss로 명시하고 profile-specific expectation으로 평가합니다. 숨기거나 완전 보존으로 보고하지 않습니다.

## PDF projection

`export` scope는 다음 canonical evidence만 읽습니다.

```text
AssetProfile
MeshPreflightReport
OptimizationPlan
StaticAssetCostReport
LOD / Collision / UV manifests
TexturePackManifest
ExportPackageManifest
RoundTripValidation
```

PDF sidecar에는 개별 source hash, 결합 fingerprint, optimization run ID, package ID, PDF hash를 기록합니다. PDF는 V0.7 판정 입력으로 역수입하지 않습니다.

## Blender 5.0.1 호환성

- Blender child process는 `--python-exit-code 1`과 `stdin=DEVNULL`
- operator/property는 runtime feature probe와 명시적 fallback 사용
- GLB/FBX/OBJ exporter와 importer를 실제로 호출
- FBX texture embed와 OBJ relative-copy 경로를 사용하고 clean import에서 외부 절대 의존성을 거부
- 원본 `.blend`를 저장하지 않고 run-owned output만 기록
- absolute/escaping path와 stale embedded fingerprint를 host/Blender 양쪽에서 확인

## 확장 경계

V0.7 위의 engine adapter는 다음을 별도 계약으로 다뤄야 합니다.

```text
destination engine/version
coordinate/import preset
engine material reconstruction
engine-specific channel packing
prefab/actor/scene assembly
collider and LOD registration
actual runtime screenshot/performance validation
```

대상 엔진을 모르는 상태에서는 이 값을 추정하거나 패키지에 하드코딩하지 않습니다.
