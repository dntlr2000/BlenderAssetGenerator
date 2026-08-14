# Autonomous Quality 0.2 테스트 계획

## 1. 문서 상태와 목적

이 문서는 **Autonomous Quality 0.2 — Harness Reliability & Fidelity Extension의 구현 및
활성화 테스트 계획**이다. 아래 MP/GI/IQ/MG/MA/DL/CE/LR 표는 acceptance
criterion이며 행의 초기 `unverified`를 현재 test 결과로 읽지 않는다. B 표는 최신 bounded
Blender snapshot을 요약하며 exact 명령과 판단 원본은 `VERIFICATION_AQ_V02_KO.md`다. 2026-08-11 최종 실행은 full pytest
`1350 passed, 39 skipped`, AQ focused `397 passed, 17 skipped`, actual Blender
`30 passed, 6 warnings`다. 독립 GLB+FBX synthetic fixture와 V0.7~V0.9 root smoke도 통과했지만 Desktop
adopt-only/App Server·human review가 미검증이므로 profile은 계속 `disabled_experimental`이다.

검증 목표는 다음과 같다.

- 기존 Project `0.9.0`, SceneSpec `0.2.0`, SceneSpec V03 `0.3.0`, V0.4~V0.9 및 AQ
  `0.1.0` 공개 계약을 회귀 없이 유지한다.
- MeshPayload `0.2.0`과 GeometryIntent가 candidate부터 package clean import까지
  생존하는지 검증한다.
- Integrated Quality `0.2.0`의 contour, semantic, landmark, multi-view companion
  metric이 실제 evidence를 사용하되 기존 V0.6 direct score를 변경하지 않는지 검증한다.
- MaterialGraphRuntime `0.1.0` whitelist compiler와 MaterialAuthoring `0.1.0`의
  texture 생성·배치·bake·평가를 실제 Blender에서 검증한다.
- quality terminal과 DeliveryProfile `0.1.0`을 분리하고, 동일한 승인 source에서 GLB와
  FBX를 각각 직접 생성하는지 검증한다.
- ControllerExecutor `0.1.0`의 출력 경계, bounded loop, receipt chain, crash recovery를
  음성 fixture까지 포함해 검증한다.
- synthetic benchmark와 권리 상태가 명확한 project-local benchmark가 있을 때만 실제
  reference 품질 향상을 주장한다.

권장 신규 companion 버전은 다음과 같이 독립적으로 다룬다.

| 계약 | 계획 버전 | 하위 호환 원칙 |
|---|---:|---|
| MeshPayload | `0.2.0` | 기존 `0.1.x` loader 유지, 자동 migration 금지 |
| GeometryIntentSurvivalReport | `0.1.0` | 새 companion evidence이며 canonical authority가 아님 |
| IntegratedQuality | `0.2.0` | `0.1.0` loader와 기존 V0.6 direct score 유지 |
| MaterialGraphRuntime | `0.1.0` | 기존 MaterialGraphSpec `0.1.x` 입력을 whitelist로 compile |
| MaterialAuthoring | `0.1.0` | 기존 V0.5 계약과 `uniform_portable_fallback_v1` 유지 |
| AdvancedMaterialHandoff | `0.1.0` | 기존 V0.9 handoff를 대체하지 않는 companion |
| DeliveryProfile | `0.1.0` | 기존 v1 `portable_gltf` 고정 경로 유지 |
| ControllerExecutor | `0.1.0` | 기존 `desktop_in_session` 의미 유지 |
| Autonomy | `0.2.0` | `autonomous_static_prop_v1` 불변, v2는 검증 전 비활성 |

## 2. 판정 어휘와 증거 등급

각 gate 결과는 다음 셋 중 하나로만 외부에 보고한다.

- `pass`: 이 문서가 요구한 전체 명령이 exit code 0이고, 예상 산출물의 Schema·hash·경로·
  불변성 검사까지 모두 통과했다.
- `fail`: 명령 실패, expected output 누락, hash 불일치, 금지된 쓰기, false success, 예상과
  다른 음성 fixture 수용 중 하나라도 관찰됐다.
- `unverified`: 구현되지 않음, 실행하지 않음, Blender/runner/fixture 없음, 선택적 검사가
  skip됨, 또는 evidence가 불완전함. `skip`, `not-run`, `contract only`를 `pass`로 바꾸지 않는다.

검증 등급은 결과와 별도로 기록한다.

| 등급 | 필요한 증거 | 금지되는 주장 |
|---|---|---|
| `contract_verified` | host loader, Schema parity, deterministic math 및 음성 contract test | Blender node/mesh/package가 실제 동작했다고 주장 |
| `blender_verified` | Blender 5.0.1 실기동, exact input/output hash, run receipt | reference 품질 향상 또는 목적 엔진 parity 주장 |
| `benchmark_verified` | 동일 reference/camera의 비교군, metric·비용·termination evidence | benchmark 범위 밖 일반화, human review가 없는 human-reviewed 주장 |

음성 fixture는 요청을 거부하고 허용 경로에 새 canonical/derived 파일을 남기지 않아야
`pass`다. 단순 예외 발생만으로는 충분하지 않으며 reason code, attempt receipt 및 사전·사후
file-set digest도 일치해야 한다. Blender가 없으면 Blender gate 전체는 `unverified`이고,
host 계약이 통과하더라도 최고 등급은 `contract_verified`다.

각 실행은 `<AQ_V02_OUTPUT_ROOT>/results/<GATE_ID>.json`에 최소한 다음을 기록하도록 구현한다.

```text
gate_id, verdict, verification_level, exact_command_argv,
started_at, completed_at, host_os, python_version,
blender_version, blender_python_version, input_hashes,
output_paths, output_hashes, warnings, limitations,
expected_rejection, observed_reason_code
```

PDF나 콘솔 출력은 이 JSON을 대체하지 않는다.

## 3. 격리 실행과 fixture 불변성

### 3.1 격리 root

새 AQ 0.2 테스트는 OS 임시 디렉터리 아래의 매 실행 고유 root만 쓴다. 저장소의
`workspaces/`, 기존 package, report, history, receipt와 사용자 job을 gate 성공용으로
변경하지 않는다.

PowerShell 준비 명령:

```powershell
$RunId = "aq-v02-{0}-{1}" -f ([DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")), $PID
$AqRoot = Join-Path ([System.IO.Path]::GetTempPath()) $RunId
$env:CBM_AQ_V02_OUTPUT_ROOT = Join-Path $AqRoot "evidence"
$env:CBM_WORKSPACE_ROOT = Join-Path $AqRoot "workspaces"
New-Item -ItemType Directory -Path $env:CBM_AQ_V02_OUTPUT_ROOT -Force | Out-Null
New-Item -ItemType Directory -Path $env:CBM_WORKSPACE_ROOT -Force | Out-Null
```

Bash 준비 명령:

```bash
RUN_ID="aq-v02-$(date -u +%Y%m%dT%H%M%SZ)-$$"
export CBM_AQ_V02_OUTPUT_ROOT="${TMPDIR:-/tmp}/$RUN_ID/evidence"
export CBM_WORKSPACE_ROOT="${TMPDIR:-/tmp}/$RUN_ID/workspaces"
mkdir -p "$CBM_AQ_V02_OUTPUT_ROOT" "$CBM_WORKSPACE_ROOT"
```

`pytest`에는 모든 호출마다 `--basetemp <AQ_ROOT>/pytest-<scope>`를 준다. 실패 root는
조사 evidence로 보존하며 gate script가 자동 삭제하지 않는다. 성공 root 정리는 CI runner의
수명 주기에 맡긴다. symlink/junction/reparse point와 `..`, absolute path를 이용해 이 root를
벗어나는 출력은 즉시 실패다.

### 3.2 계획 fixture 구조

아래 경로는 구현 시 추가할 fixture의 목표 구조다. 현재 존재한다고 가정하지 않는다.

```text
tests/fixtures/aq_v02/
├─ mesh_payload/
│  ├─ legacy_v01/
│  ├─ valid_v02/
│  └─ invalid/
├─ geometry_intent/
│  ├─ sharp_box.json
│  ├─ uv_seam_cube.json
│  ├─ crease_subdivision.json
│  ├─ weighted_normal_bevel.json
│  ├─ multi_material_faces.json
│  ├─ v03_loft_uv.json
│  ├─ v03_sweep_sharp.json
│  └─ boolean_material_groups.json
├─ integrated_quality/
│  ├─ contour/
│  ├─ semantic/
│  ├─ landmarks/
│  ├─ advisory/
│  └─ ranking/
├─ material_graph/
│  ├─ allowed/
│  └─ rejected/
├─ material_authoring/
│  ├─ user_image/
│  ├─ decal_signage/
│  ├─ planar_patch/
│  ├─ wood/
│  ├─ metal/
│  └─ crystal_emissive/
├─ delivery/
├─ controller/
└─ legacy/

examples/autonomous_quality_benchmarks_v02/
└─ manifest.json
```

현재 synthetic image/camera recipe는 `manifest.json` 안에 들어 있다. 향후 별도 fixture 원본을
추가하면 read-only input으로 취급하고 실행 시 `<AQ_ROOT>/fixture-copies/`로 exact copy한 뒤 hash
manifest를 만든다. 이미지와 font는 저장소에 포함할 권리가 확인된 것만 사용한다.
권리 또는 license 상태가 불명확한 project-local reference는 benchmark 입력에서 제외하고
해당 항목을 `unverified`로 남긴다.

## 4. Contract 및 음성 gate matrix

현재 구현된 AQ 0.2 focused test 파일의 핵심 목록:

```text
tests/test_aq_v02_geometry.py
tests/test_aq_v02_geometry_blender.py
tests/test_integrated_quality_v02_metrics.py
tests/test_integrated_quality_v02_ranking.py
tests/test_integrated_quality_v02_schemas.py
tests/test_integrated_quality_v02_service.py
tests/test_material_graph_runtime.py
tests/test_material_authoring_v02.py
tests/test_material_authoring_schemas_v02.py
tests/test_material_authoring_blender_v02.py
tests/test_advanced_material_handoff_v02.py
tests/test_autonomy_v2_contracts.py
tests/test_autonomy_v2_planner.py
tests/test_autonomy_v2_controller_bridge.py
tests/test_autonomy_v2_delivery_service.py
tests/test_controller_executor_v02.py
tests/test_autonomous_quality_benchmarks_v02.py
tests/test_aq_v02_schema_registry.py
tests/test_repository_catalog.py
tests/test_ci_workflows.py
```

이 목록과 public Schema/CLI/MCP parity는 구현 변경 시 문서, registry와 CI를 같은 변경에서
동기화한다.

### 4.1 MeshPayload 0.1/0.2와 migration

| ID | fixture/행동 | `pass` 조건 | `fail` 조건 | 초기 상태 |
|---|---|---|---|---|
| MP-01 | valid legacy `0.1` `vertex_uvs` load | 읽기 성공, 원본 byte 불변, 자동 rewrite 없음 | load 거부 또는 암묵적 `0.2` 저장 | unverified |
| MP-02 | valid `0.2` per-loop UV load | loop count와 `loop_uvs` 길이, hash가 정확히 일치 | per-vertex로 축약 또는 순서 변경 | unverified |
| MP-03 | unknown field 삽입 | strict loader가 거부 | extra field 무시 | unverified |
| MP-04 | NaN/Infinity/-Infinity | encode·load 모두 거부 | non-finite 수용 | unverified |
| MP-05 | loop UV count ±1 | index-aware reason으로 거부 | 잘못된 loop 배열 수용 | unverified |
| MP-06 | negative/out-of-range edge index | 거부, output 없음 | clamp 또는 무시 | unverified |
| MP-07 | polygon material index가 slot 범위 밖 | 거부, output 없음 | fallback material로 조용히 대체 | unverified |
| MP-08 | source geometry/hash 하나 변경 | stale source로 fail-closed | 새 hash로 자동 재결속 | unverified |
| MP-09 | `0.1 → 0.2` plan | 원본 hash, 한계, 예상 output hash를 가진 immutable plan만 생성 | 원본 또는 canonical 수정 | unverified |
| MP-10 | exact plan hash로 apply | 새 derived `0.2` copy와 receipt 생성, single-use | stale/wrong/reused plan 허용 | unverified |
| MP-11 | Pydantic/checked-in Schema parity | generator 뒤 byte diff 0, Draft 2020-12 validation 동일 | drift 또는 Schema 미등록 | unverified |

### 4.2 GeometryIntent 생존

모든 fixture는 `structural materialization → MeshPayload 0.2 → compiled V02 custom_mesh →
candidate build → promotion → optimized blend → package → clean import`의 단계별
GeometryIntentSurvivalReport를 만든다.

| ID | 의도 | host/Blender 검사 | package/clean-import 검사 | 초기 상태 |
|---|---|---|---|---|
| GI-01 | sharp edge | stable edge index와 sharp/split-normal 의도 재현 | GLB/FBX 최종 normal·시각 동등성 | unverified |
| GI-02 | UV seam | seam edge와 per-loop UV fingerprint 유지 | seam flag 미보존 포맷은 UV island 동등성 | unverified |
| GI-03 | edge crease | crease 값·edge mapping 유지 | baked/evaluated shape 허용오차 내 동등 | unverified |
| GI-04 | bevel weight | weight와 modifier policy 결속 | bevel 효과의 bounds/normal 동등 | unverified |
| GI-05 | face material | polygon material index와 stable material ID 유지 | semantic/material coverage와 face assignment | unverified |
| GI-06 | smoothing | smooth polygon flag/policy와 split normal 유지 | imported normal/appearance 동등 | unverified |
| GI-07 | weighted normal | `recreate_in_compiled_build`로 정확히 한 번 적용 | imported normal 동등 및 duplicate 없음 | unverified |
| GI-08 | subdivision | non-destructive intent 또는 명시적 bake 정책 준수 | topology/shape가 선언 정책과 일치 | unverified |
| GI-09 | baked modifier/boolean | evaluated mesh와 source intent hash 결속 | 최종 topology·bounds 동등 | unverified |
| GI-10 | duplicate-effect injection | bake+modifier 이중 적용을 build 전에 거부 | 중복 bevel/subdivision package 생성 없음 | unverified |
| GI-11 | clean-import equivalence | 단계별 vertex/face/loop, UV, material, normal, semantic 비교 | 포맷별 손실은 loss report에 명시 | unverified |

authoring metadata가 포맷에 존재하지 않는다는 이유만으로 실패시키지 않는다. 단, 그 경우에는
동일한 source에서 생성한 neutral render와 imported render, UV fingerprint, split normal,
bounds, material face coverage 중 계약이 정한 대체 evidence가 모두 있어야 한다. 대체 evidence가
없으면 `unverified`이며 자동 `pass`가 아니다.

### 4.3 Integrated Quality 0.2

| ID | fixture | 기대 판정 | 금지 동작 | 초기 상태 |
|---|---|---|---|---|
| IQ-01 | 동일 binary mask | contour precision/recall/F-score `1.0` | 기존 direct score 재계산식 변경 | unverified |
| IQ-02 | 알려진 pixel만큼 이동한 mask | exact보다 contour/edge-distance가 낮음 | bbox overlap만으로 exact 처리 | unverified |
| IQ-03 | 동일 상대 오차의 작은/큰 물체 | image diagonal 또는 object scale 정규화 허용오차 일관 | 모든 해상도에 고정 pixel 임계값 강제 | unverified |
| IQ-04 | critical semantic part 제거 | aggregate가 높아도 hard finding과 regression rejection | 평균에 묻혀 promotion | unverified |
| IQ-05 | observed landmark present | source coordinate/camera/hash에 결속해 reprojection 계산 | inferred landmark를 authoritative 처리 | unverified |
| IQ-06 | landmark absent | `unavailable/unscorable` | 0점이나 pass로 대체 | unverified |
| IQ-07 | depth/normal provider evidence | provenance·model·hash·confidence와 `authoritative=false` | 단독 hard gate/promotion authority | unverified |
| IQ-08 | required evidence unavailable | quality pass 불가, review/blocked route 기록 | unavailable을 neutral score로 평균 | unverified |
| IQ-09 | 높은 soft score + hard gate failure | hard gate가 ranking에 우선 | weighted total로 선택 | unverified |
| IQ-10 | 교차 우위 candidates | Pareto 또는 profile의 명시적 lexicographic 순서와 stable ID tie-break | 숨은 단일 weighted score | unverified |
| IQ-11 | critical metric regression | meaningful aggregate gain이 있어도 제거/rollback | regression candidate promotion | unverified |
| IQ-12 | finding family별 routing | camera/contour/semantic→structural, local proportion→convergence, material→authoring, topology/UV/normal→production repair | 잘못된 phase에서 canonical 수정 | unverified |
| IQ-13 | V0.6 golden fixtures | 기존 `overall_direct_score`와 version을 exact 비교 | AQ 0.2가 V0.6 산식을 교체 | unverified |
| IQ-14 | ground/background mask | primary contour와 분리된 environment evidence | 넓은 ground가 primary score를 왜곡 | unverified |
| IQ-15 | authoritative hard finding | exact required gate ID, `failed` outcome과 authoritative input hash 결속 | passed/missing gate에 forged hard finding 삽입 | unverified |
| IQ-16 | raw-mask host recomputation | exact global/semantic PNG bytes로 metric·gate·finding·outcome 전체 재생성 | self-consistent forged high score 수용 | host regression |
| IQ-17 | landmark/multi-view authority | typed host-verifiable raw receipt 없이는 required scored pass 거부 | caller 숫자를 pass authority로 사용 | host regression |

### 4.4 MaterialGraphRuntime compiler

허용 node registry에는 Texture Coordinate, Mapping, Image Texture, Noise, Voronoi, Wave,
Gradient, bounded 2-stop Color Ramp, Mix Color, bounded Math, RGB Separate/Combine Color,
Normal Map, Bump, Fresnel, Principled BSDF, Transparent BSDF, Emission, Mix Shader,
Material Output의 20개 template만 등록한다. 각 node의 socket, 타입, 값 범위, 최대 node 수,
graph depth, texture 수는 별도 strict registry hash에 결속한다. Layer Weight는 현재 whitelist에
없다.

| ID | fixture | `pass` 조건 | `fail` 조건 | 초기 상태 |
|---|---|---|---|---|
| MG-01 | allowed connected graph | compile report, `.blend`, node/dependency inventory 생성 | placeholder report만 생성 | unverified |
| MG-02 | unknown node name | compile 전 거부 | Blender가 임의 node 검색 | unverified |
| MG-03 | Script/custom group/driver | forbidden reason으로 거부 | node 생성 또는 외부 실행 | unverified |
| MG-04 | 최대 depth +1 | deterministic depth-limit failure | 부분 graph 저장 | unverified |
| MG-05 | missing image texture | missing dependency failure | 검은색 fallback으로 성공 | unverified |
| MG-06 | BaseColor=Non-Color 또는 Normal=sRGB | channel별 color-space failure | 자동 추정 후 성공 | unverified |
| MG-07 | graph cycle | acyclic validation failure | cycle compile/hang | unverified |
| MG-08 | unsupported socket/link | source/target socket를 명시해 거부 | link 무시 | unverified |
| MG-09 | 같은 graph 두 번 compile | canonicalized graph fingerprint와 node inventory hash 동일 | 실행 순서/ID에 따라 hash 변경 | unverified |
| MG-10 | neutral/reference preview | 서로 다른 목적과 source hash로 둘 다 기록 | reference preview만으로 material pass | unverified |

### 4.5 Material authoring, texturing, baking

| ID | strategy/fixture | 필수 검증 | 음성/회귀 조건 | 초기 상태 |
|---|---|---|---|---|
| MA-01 | `user_image_pbr_v1` | exact hash, contained path, dimensions, channel, color space, UV set, texel density, provenance/license | stale UV 또는 unknown license를 production-ready로 처리 금지 | unverified |
| MA-02 | `localized_decal_v1` image | exact placement/mask/UV rect, alpha edge, padding, channel bake | parent/material 불일치나 path escape 거부 | unverified |
| MA-03 | `planar_reference_patch_v1` | 4 corners/polygon, perspective rectification, crop/mask, source-to-output receipt | advisory corner를 observed로 승격 금지 | unverified |
| MA-04 | exact text signage | user text hash, project-local font hash/license, deterministic raster | 다른 문자열 또는 system font 암묵 사용 금지 | unverified |
| MA-05 | unreadable/unknown text | `unknown_text` 또는 `inferred_placeholder`, 품질 제한 기록 | 임의 문구 발명 금지 | unverified |
| MA-06 | `procedural_wood_v1` | non-uniform variance, grain axis, physical grain/ring/pore scale, seam, UV/triplanar, deterministic seed, raw PBR bake | 균일색을 wood success로 처리 금지 | unverified |
| MA-07 | 0.1m/1m/10m wood | 공통 AssetScaleContext로 상대 grain/bump/texel density 일관 | object scale에 따라 무작위 패턴 크기 | unverified |
| MA-08 | `procedural_metal_v1` | metallic consistency, bounded roughness variance, brushed direction, subtle normal | 근거 없는 scratches/edge wear 자동 추가 금지 | unverified |
| MA-09 | `emissive_pattern_v1` | emission map과 strength, neutral preview, raw PBR emission | beauty bloom만으로 채널 존재 주장 금지 | unverified |
| MA-10 | `crystal_portable_approximation_v1` | Blender IOR/transmission/roughness와 portable BaseColor/Roughness/Normal/Emission/Opacity, feature-loss report | GLB/FBX 굴절 parity 주장 금지 | unverified |
| MA-11 | `uniform_portable_fallback_v1` | 기존 256 fallback 명칭·출력·V0.5 loader 유지 | 고품질 기본 경로로 승격 금지 | unverified |
| MA-12 | bake freshness | SceneSpec, build, material graph, texture, ordered-corner UV fingerprint 모두 current | stale build/UV에서 bake 성공 금지 | unverified |
| MA-13 | raw PBR manifest | 모든 planned channel, output hash, color space, resolution, provenance/license 기록 | PDF 또는 packed map만 남김 | unverified |

### 4.6 AssetScaleContext와 resolution selector

0.1m, 1m, 10m의 동일 정규화 형상을 사용하며 scale만 달리한다.

| ID | 측정 | `pass` 조건 | 초기 상태 |
|---|---|---|---|
| AS-01 | bevel | shortest dimension 대비 같은 비율, 절대값은 scale에 선형 비례 | unverified |
| AS-02 | grain/bump/displacement | intended real-world scale에 맞는 공간 주파수와 amplitude | unverified |
| AS-03 | texel density/resolution | footprint, bounds, family, unique/tileable/decal, package budget로 256/512/1024/2048/4096 중 deterministic 선택 | unverified |
| AS-04 | 256 tier | fallback/thumbnail로만 선택되고 high-quality pass의 유일 evidence가 아님 | unverified |
| AS-05 | >4096 | 별도 exact authorization이 없으면 거부 | unverified |
| AS-06 | decal padding | resolution과 mip policy에 맞춰 상대적으로 계산 | unverified |
| AS-07 | light/camera | light size, camera clipping이 scale에 맞고 geometry clipping 없음 | unverified |
| AS-08 | contact tolerance | assembly broad/narrow phase가 같은 상대 tolerance 의미 유지 | unverified |

### 4.7 DeliveryProfile 0.1

| ID | 경로 | `pass` 조건 | 금지 동작 | 초기 상태 |
|---|---|---|---|---|
| DL-01 | `autonomous_static_prop_v1` | 기존 `portable_gltf` terminal과 registry bytes/의미 유지 | v2 설정 역주입 | unverified |
| DL-02 | v2 `portable_gltf` | quality freeze 뒤 source에서 직접 GLB package/roundtrip/loss report | 다른 package를 복사해 성공 처리 | unverified |
| DL-03 | v2 `portable_fbx` | 같은 frozen source에서 직접 FBX package/roundtrip/loss report | GLB→FBX 변환 | unverified |
| DL-04 | v2 dual | source fingerprint 동일, 독립 plan/package ID/manifest/roundtrip/loss report | 한 포맷 approval을 다른 포맷에 재사용 | unverified |
| DL-05 | GLB 성공, FBX 실패 fixture | GLB evidence 불변, terminal에 format별 결과와 partial delivery 정책 기록 | 전체 성공 또는 기존 GLB 삭제 | unverified |
| DL-06 | clean import | bounds, dependency, semantic/material, GeometryIntent equivalence | exporter exit 0만으로 pass | unverified |
| DL-07 | material loss | 포맷별 unsupported feature와 portable approximation hash-bound | loss 숨김 | unverified |
| DL-08 | stale quality/source | delivery 전 fail-closed, 새 plan 요구 | 자동 재freeze/rebind | unverified |
| DL-09 | immutable package | 생성 후 추가/삭제/변조 모두 audit failure | overwrite/repair in place | unverified |
| DL-10 | `review_only` | package 없이 review manifest/PDF/receipt, `production_ready=false` | handoff eligible 또는 quality pass 위조 | unverified |
| DL-11 | passed IQ source closure | current ModelingPlan/SceneSpec/blend/build/material/shader/texture/geometry와 accepted promotion/survival receipt 전부 exact 결속 | summary 또는 일부 current source만으로 freeze 생성 | unverified |
| DL-12 | nested quality terminal | DeliveryTerminal 검증 중 full QualityTerminal validator 재호출 | hash만 맞춘 forged `quality_approved` terminal 수용 | unverified |
| DL-13 | non-pass quality terminal | `review_required`는 exact review bundle, no source freeze | DeliveryProfile `review_only`와 혼합 | host test |
| DL-14 | portable delivery terminal | exact quality/source/plan/review/results provenance | review binding 없는 completion | host test |

### 4.8 ControllerExecutor 0.1

| ID | FakeController 시나리오 | 기대 결과 | 초기 상태 |
|---|---|---|---|
| CE-01 | exact success | allowed output만 수용, completion marker와 exact hash 기록 | unverified |
| CE-02 | timeout | raw timeout receipt 뒤 AQ v2 session은 nonretryable `failed`, canonical write와 재호출 없음 | unverified |
| CE-03 | partial output | assignment incomplete failure, 부분 output 격리 | unverified |
| CE-04 | malicious extra file | 전체 결과 거부, extra path와 digest 기록 | unverified |
| CE-05 | stale input/output hash | `orchestration_artifact_conflict` 또는 전용 stale reason으로 거부 | unverified |
| CE-06 | absolute/`..`/symlink path escape | write 전 또는 adoption 전 거부, 외부 file-set 불변 | unverified |
| CE-07 | repeated identical failure | failure fingerprint 반복 후 bounded terminal, 무한 retry 없음 | unverified |
| CE-08 | crash after staging | receipt에 맞는 recover/quarantine만 수행, completed receipt overwrite 없음 | unverified |
| CE-09 | cancellation | 이후 action 중단, immutable evidence 보존, resume 금지 | unverified |
| CE-10 | duplicate action/event | idempotent no-op 또는 explicit rejection, budget 이중 소비 없음 | unverified |
| CE-11 | receipt chain splice | previous hash/sequence/input mismatch로 전체 chain 거부 | unverified |
| CE-12 | optional Codex/App Server 미탐지 | adapter `experimental_unverified`/disabled, API 추측 없음 | unverified |
| CE-13 | waiting no-output 재호출 | 동일 request/execution 유지, state와 모든 budget counter 불변 | 새 request/attempt 또는 budget 소비 | unverified |
| CE-14 | waiting 뒤 output adoption | advance/run이 assignment/input/profile/protected source를 exact rehash하고 같은 workspace output만 채택 | stale output 또는 waiting 중 canonical mutation 수용 | unverified |
| CE-15 | state-chain semantic splice/rollback | initial/transition/input/source/producer/provenance delta/budget을 재구성해 거부 | sequence/hash만 맞춘 phase splice나 budget rollback 수용 | unverified |

Controller는 immutable snapshot과 allowed output directory만 받고 canonical job root를 직접
쓰지 못한다. supervisor가 exact file allowlist와 hash를 검증한 뒤에만 staging으로 채택한다.
`autonomy-v2-run`은 global action budget, timeout, cancellation과 중복 action 방지를 갖는 bounded
loop여야 하며 무한 `while`은 실패다.

## 5. 실제 Blender 5.0.1 gate matrix

아래 표는 activation에 필요한 Blender acceptance bundle이다. 현재 존재하는 opt-in test는
`tests/test_aq_v02_geometry_blender.py`,
`tests/test_aq_v02_delivery_geometry_blender.py`,
`tests/test_autonomy_v2_candidate_validation_blender.py`,
`tests/test_aq_v02_delivery_executor_blender.py`,
`tests/test_geometry_intent_v02_reachability.py`,
`tests/test_material_graph_runtime.py`,
`tests/test_material_authoring_blender_v02.py`,
`tests/test_autonomous_quality_benchmarks_v02.py`의 fixed probe와 기존 AQ/V0.7~V0.9
gate에 분산되어 있다. 과거 초안의 `tests/test_aq_v02_blender.py` 단일 파일과 그 node 이름은
구현된 public test가 아니다. 환경 변수는 실기동 opt-in일 뿐 skip을 성공으로 바꾸지 않는다.

공통 준비:

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm blender-compat
$env:CBM_RUN_AQ_V02_GEOMETRY_SMOKE = "1"
$env:CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE = "1"
$env:CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE = "1"
$env:CBM_RUN_AQ_V02_DELIVERY_EXECUTOR_BLENDER_E2E = "1"
$env:CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE = "1"
$env:CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE = "1"
$env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE = "1"
$env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE = "1"
```

| ID | activation bundle | acceptance 역할 이름 | 필수 evidence | 현재 activation 판정 |
|---|---|---|---|---|
| B-01 | GeometryIntent survival | 현행 geometry/delivery/candidate Blender tests | 8 fixture의 단계별 report, GLB/FBX 동등성 | bounded synthetic pass; 모든 조합 일반화 금지 |
| B-02 | MaterialGraph compile | 현행 MaterialGraph Blender smoke | compiled blend, inventory, graph hash, negative no-output | passed |
| B-03 | wood | 현행 fixed material-family smoke | master material, neutral render, raw PBR, direction/scale/variance | partial: fixed smoke passed; canonical master/neutral 별도 |
| B-04 | signage/decal | 현행 fixed material-family smoke | source/font hash, placement, alpha/padding, baked channels | partial: fixed smoke passed; canonical preview 별도 |
| B-05 | crystal/emissive | 현행 fixed material-family smoke | master/portable 비교와 feature-loss report | partial: fixed smoke passed; runtime parity 없음 |
| B-06 | AQ v2 GLB | delivery executor Blender E2E | quality freeze, direct GLB, clean import, loss report | bounded synthetic pass |
| B-07 | AQ v2 FBX | delivery executor Blender E2E | 같은 품질 source의 direct FBX, clean import, loss report | bounded synthetic pass |
| B-08 | dual delivery | delivery executor Blender E2E | independent plan/package/receipt와 동일 source fingerprint | bounded synthetic pass |
| B-09 | review bundle | supervisor/quality terminal tests | package 없음, review-only flags와 immutable receipt | passed |
| B-10 | interruption/resume | controller/delivery crash-adoption tests | staged recovery, no duplicate action, chain 연속성 | host passed; App Server 미검증 |
| B-11 | V0.7~V0.9 chain | root smoke scripts | V0.7 GLB/FBX/OBJ, V0.8, V0.9/handoff receipts | passed |

현재 gate가 연결하는 AQ v2 opt-in Blender test의 실행 표면은 다음과 같다.

```powershell
$env:CBM_RUN_AQ_V02_GEOMETRY_SMOKE = "1"
$env:CBM_RUN_AQ_V02_DELIVERY_GEOMETRY_SMOKE = "1"
$env:CBM_RUN_AQ_V02_CANDIDATE_VALIDATION_SMOKE = "1"
$env:CBM_RUN_AQ_V02_DELIVERY_EXECUTOR_BLENDER_E2E = "1"
$env:CBM_RUN_GEOMETRY_INTENT_V02_REACHABILITY_SMOKE = "1"
$env:CBM_RUN_MATERIAL_GRAPH_BLENDER_SMOKE = "1"
$env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE = "1"
$env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE = "1"
uv run pytest -q `
  tests/test_aq_v02_geometry_blender.py `
  tests/test_aq_v02_delivery_geometry_blender.py `
  tests/test_autonomy_v2_candidate_validation_blender.py `
  tests/test_aq_v02_delivery_executor_blender.py `
  tests/test_geometry_intent_v02_reachability.py `
  tests/test_material_graph_runtime.py::test_material_graph_compiles_reopens_and_inventories_in_blender_5 `
  tests/test_autonomous_quality_benchmarks_v02.py::test_v02_fixed_blender_probe_smoke `
  tests/test_material_authoring_blender_v02.py::test_fixed_material_families_compile_reopen_and_render_in_blender_5
```

MaterialAuthoring의 현재 fixed Blender smoke는 다음과 같다. 이 smoke는 B-03~B-05의 일부
compile/reopen/render evidence만 제공하며 canonical neutral/reference preview와 dual delivery를
완결하지 않는다.

```powershell
$env:CBM_RUN_MATERIAL_AUTHORING_BLENDER_SMOKE = "1"
uv run pytest -q tests/test_material_authoring_blender_v02.py
```

현재 저장소에는 `run_aq_v02_gates.ps1`/`.sh`가 없다. 기존 AQ와 Blender evidence를 실행하는
현행 script는 다음이며, 이 하나만으로 B-01~B-10을 전부 충족했다고 간주하지 않는다.

```powershell
.\scripts\run_autonomous_quality_gates.ps1 -RunBlender
```

```bash
./scripts/run_autonomous_quality_gates.sh --run-blender
```

B-11의 현행 exact Windows 명령은 다음과 같다.

```powershell
.\scripts\run_v09_gates.ps1
```

각 Blender node는 단순 pytest 결과 외에 `<AQ_V02_OUTPUT_ROOT>/blender/<gate-id>/`에
`gate_result.json`, `input_manifest.json`, `output_manifest.json`을 원자적으로 publish해야
한다. `gate_result.json`에는 exact argv, Blender/Python version, input hash, job-relative 또는
gate-root-relative output path, output hash, result, warning, limitation을 기록한다. Blender가
없거나 version이 5.0.1이 아니거나 test가 skip되면 `blender_verified`가 아니라
`unverified`다.

## 6. Deterministic benchmark와 품질 향상 판정

### 6.1 Synthetic benchmark case

`examples/autonomous_quality_benchmarks_v02/manifest.json`에는 외부 다운로드 없이 다음 10개
case를 고정한다.

| case | ground truth 핵심 | 의도적 perturbation | 기대 metric 방향 |
|---|---|---|---|
| simple_hard_surface_box | sharp/bevel/UV/normal | bevel·camera 오차 | contour, normal, scale 개선 |
| curved_loft | known profiles/loops | profile scale·segment 오차 | contour/semantic 개선 |
| swept_handle | known path/frame | handle offset/twist | landmark/semantic/multi-view 개선 |
| boolean_panel | cutout/material group | opening 누락 | critical semantic과 contour 개선 |
| ornate_multi_part_prop | primary/supporting/decorative IDs | critical part 누락·장식 이동 | critical 우선, decorative warning |
| multi_material_prop | face assignment | slot swap | material/face coverage 개선 |
| wood_object | grain axis/physical scale | uniform 또는 잘못된 축 | variance/direction/scale 개선 |
| signage_decal_object | exact text/image/UV rect | 잘못된 crop/placement | semantic boundary/material 개선 |
| emissive_crystal_prop | emission/transmission intent | emission 누락 | material axis 개선, portable loss 보존 |
| small_static_assembly | contact/BVH/semantic placement | floating/penetration | structure/contact 개선 |

각 case는 정답 SceneSpec/Blend, reference beauty/silhouette/object ID, observed semantic masks,
known camera, perturbed candidate, expected metric direction과 모든 source hash를 가진다. AQ v2가
정답 data를 authoring 입력으로 직접 읽는 leakage test도 포함한다.

### 6.2 비교군과 기록 항목

동일 reference, camera, mask, budget과 deterministic seed로 다음을 각각 새 격리 run에서
실행한다.

- V0.9 standard initial
- AQ v1 initial best
- AQ v2 initial best
- AQ v2 final best

모든 비교는 contour precision/recall/F-score, edge distance, semantic ID별 IoU/boundary,
critical missing count, silhouette, landmark error, five-view structure, topology, UV, material,
build/render/iteration/rollback count, termination reason, package result와 execution duration을
기록한다. 품질 향상 판정은 hard gate·critical metric 비회귀 후 manifest가 정한 meaningful
gain을 만족하고, 동일 source/camera/budget 비교가 재현될 때만 허용한다. 단일 weighted score
상승만으로는 향상을 주장하지 않는다.

기존 module entry point는 v1 manifest용이다. v02는 전용 CLI를 사용한다.

```powershell
uv run python -m codex_blender_modeler.autonomy_benchmarks.v02_cli `
  --manifest examples/autonomous_quality_benchmarks_v02/manifest.json `
  --output <NEW_REPORT>
```

현재 opt-in Blender benchmark exact 명령:

```powershell
uv run python -m codex_blender_modeler.autonomy_benchmarks.v02_cli `
  --manifest examples/autonomous_quality_benchmarks_v02/manifest.json `
  --output <NEW_BLENDER_REPORT> `
  --run-blender
```

2026-08-11 결과는 host `10/10`, 선언된 Blender probe `2/2`,
`human_review_status=not_reviewed`다. 이 fixture 결과를 실제 production run이나 사람 승인으로
재분류하지 않는다.

실제 사람이 contact sheet를 검토한 별도 identity와 receipt가 없으면
`human_review_status=not_reviewed`다. project-local reference가 권리·license manifest를 충족하지 못하면
synthetic 결과만 보고하고 실제 reference benchmark는 `unverified`로 남긴다.

## 7. Legacy 및 AQ v1 회귀 matrix

새 테스트는 legacy artifact를 제자리 migration하거나 기존 profile의 의미를 바꾸지 않는다.

| ID | 보존 대상 | focused 회귀 | 필수 판정 | 초기 상태 |
|---|---|---|---|---|
| LR-01 | standard workflow | `tests/test_v08_orchestration.py`, `tests/test_v08_public_surface.py` | 기존 승인/agent 경계와 state transition golden 동일 | unverified |
| LR-02 | `background_exterior` | `tests/test_v08_background_quality.py`, `tests/test_v08_artifact_lifecycle.py` | canonical QA 1회, review delivery 정책과 lifecycle 불변 | unverified |
| LR-03 | AQ v1 | 기존 AQ focused suite와 v1 gate script | `autonomous_static_prop_v1=verified_active`, terminal 의미·portable GLTF 불변 | unverified |
| LR-04 | V0.7 GLB/FBX/OBJ | `tests/test_v07_*.py`, `tests/test_v071_*.py`, gate script | exact approval, package/roundtrip/raw PBR 불변 | unverified |
| LR-05 | V0.8 workflow | `tests/test_v08_*.py` | legacy request/plan/state load와 completion fingerprint 불변 | unverified |
| LR-06 | V0.9 production/handoff | `tests/test_v09_*.py` | dispatcher/controller/handoff approval·audit 경계 불변 | unverified |
| LR-07 | external intake | `tests/test_external_static_asset_intake.py` | no placeholder SceneSpec, source/normalization/package hash 불변 | unverified |
| LR-08 | InteriorScope | `tests/test_v072_interior_scope.py`, `tests/test_interior_qa.py` | opt-in exact approval과 disabled default 불변 | unverified |
| LR-09 | V0.6 direct score | `tests/test_visual_qa.py` golden + 새 AQ v2 parity test | 기존 값과 score version exact 일치 | unverified |
| LR-10 | public CLI/MCP/Schema | 기존 public-surface 및 Schema fixture | 제거·rename·자동 migration 없음 | unverified |

현행 AQ v1 regression exact 명령:

```powershell
.\scripts\run_autonomous_quality_gates.ps1 `
  -OutputRoot (Join-Path $AqRoot "aq-v1-regression") `
  -SkipLegacyGates
```

현행 V0.7~V0.9 chained regression exact 명령:

```powershell
.\scripts\run_v09_gates.ps1
```

기존 Blender AQ v1까지 포함하는 명령은 다음과 같으며 실제로 실행하지 않으면 LR-03은
`unverified`다.

```powershell
.\scripts\run_autonomous_quality_gates.ps1 `
  -OutputRoot (Join-Path $AqRoot "aq-v1-blender-regression") `
  -RunBlender
```

## 8. 전체 실행 순서와 exact commands

아래 1~6은 현재 파일명에 맞춘 검증 순서다. 실제로 실행한 결과만 verification에 기록한다.

### 8.1 dependency와 contract focused gate

```powershell
uv sync --frozen --extra dev --extra vision
uv run pytest -q `
  --basetemp (Join-Path $AqRoot "pytest-contract") `
  tests/test_aq_v02_geometry.py `
  tests/test_integrated_quality_v02_metrics.py `
  tests/test_integrated_quality_v02_ranking.py `
  tests/test_integrated_quality_v02_service.py `
  tests/test_material_graph_runtime.py `
  tests/test_material_authoring_v02.py `
  tests/test_material_authoring_schemas_v02.py `
  tests/test_material_authoring_blender_v02.py `
  tests/test_advanced_material_handoff_v02.py `
  tests/test_autonomy_v2_contracts.py `
  tests/test_autonomy_v2_planner.py `
  tests/test_autonomy_v2_controller_bridge.py `
  tests/test_autonomy_v2_candidate_validation.py `
  tests/test_autonomy_v2_candidate_validation_blender.py `
  tests/test_autonomy_v2_material_phase.py `
  tests/test_autonomy_v2_quality_binding.py `
  tests/test_autonomy_v2_quality_terminal.py `
  tests/test_autonomy_v2_delivery_service.py `
  tests/test_autonomy_v2_delivery_executor.py `
  tests/test_autonomy_v2_supervisor_public.py `
  tests/test_autonomy_v2_supervisor_delivery.py `
  tests/test_controller_executor_v02.py `
  tests/test_autonomous_quality_benchmarks_v02.py `
  tests/test_aq_v02_schema_registry.py `
  tests/test_repository_catalog.py `
  tests/test_repository_summary_generator.py `
  tests/test_ci_workflows.py
```

### 8.2 lint, Schema, instruction 및 문서/registry parity

```powershell
uv run ruff check .
uv run python scripts/generate_schemas.py
git diff --exit-code -- schemas
uv run python scripts/check_agent_instructions.py
uv run python scripts/generate_repository_summary.py --check
git diff --check
```

`scripts/check_agent_instructions.py`와 `scripts/generate_repository_summary.py`는 현재 구현되어
있다. summary `--check`가 drift를 보고하면 generated projection을 임의로 무시하지 않는다.
instruction gate는 root AGENTS 최대 12 KiB, 모든 root→leaf 합산 최대 28 KiB, sentinel 규칙,
충돌, dangling docs link를 검사한다.

### 8.3 deterministic benchmark

```powershell
uv run pytest -q tests/test_autonomous_quality_benchmarks_v02.py
```

### 8.4 전체 Python 회귀

```powershell
uv run pytest --basetemp (Join-Path $AqRoot "pytest-full")
```

### 8.5 실제 Blender와 legacy chain

```powershell
uv run cbm doctor
uv run cbm blender-compat
.\scripts\run_autonomous_quality_gates.ps1 -RunBlender
.\scripts\run_v09_gates.ps1
```

### 8.6 최종 working-tree 형식 검사

```powershell
git diff --check
```

CI에서는 `python-ci.yml`이 Python `3.11`을 명시하고 AQ v1/v2 deterministic benchmark, AQ v2
host/schema/public/catalog/controller/material contract, 8.1~8.4와 AGENTS/docs/registry parity를
`pull_request`, `push`,
`workflow_dispatch`에서 수행한다. `blender-smoke.yml`은 `workflow_dispatch`와
`self-hosted`, `windows`, `blender5` label에서 8.5의 Blender 항목을 수행한다. runner가 없으면
workflow는 `not-run/unverified`이며 성공 badge나 verification 문서가 이를
`blender_verified`로 표시하면 실패다.

## 9. Completion traceability matrix

아래 24개 항목은 하나라도 `fail` 또는 `unverified`이면 AQ 0.2 전체를 구현 완료 또는
`autonomous_static_prop_v2=verified_active`로 표시할 수 없다.

| # | 완료 기준 | 필수 gate/evidence | 초기 판정 |
|---:|---|---|---|
| 1 | standard/background/AQ v1 불변 | LR-01~03, state transition golden, v1 registry snapshot | unverified |
| 2 | legacy MeshPayload readable | MP-01, no-write digest | unverified |
| 3 | V03 UV/sharp/crease/smoothing/material이 compiled candidate까지 유지 | GI-01~06, B-01 단계별 survival receipt | unverified |
| 4 | package metadata 또는 검증된 시각·기하 동등성 | GI-11, DL-06, 포맷별 loss report | unverified |
| 5 | AGENTS root/combined 한도 | `check_agent_instructions.py` JSON 결과 | unverified |
| 6 | CI가 Python/Schema/docs/AGENTS 검사 | 실제 CI run URL/ID와 artifact | unverified |
| 7 | 기존 V0.6 direct score 불변 | IQ-13, LR-09 golden | unverified |
| 8 | IQ 0.2가 contour/semantic metric을 실제 사용 | IQ-01~04 및 benchmark ranking provenance | unverified |
| 9 | unavailable/advisory/forged hard finding에 pass authority 없음 | IQ-06~09, IQ-15 음성 fixture | unverified |
| 10 | MaterialGraph가 whitelist Blender compiler와 연결 | MG-01~09, B-02 compiled `.blend` | unverified |
| 11 | signage/decal/wood가 uniform 256보다 공간 detail 보유 | MA-02~07, B-03~04 neutral evidence | unverified |
| 12 | 모든 texture provenance/license 기록 | MA-01~13 manifest completeness | unverified |
| 13 | `autonomous_static_prop_v1` 불변 | DL-01, LR-03 public/terminal regression | unverified |
| 14 | v2 quality terminal/delivery 분리와 nested 검증 | DL-02~12, frozen-source receipt | unverified |
| 15 | 같은 source에서 GLB/FBX 직접 생성 | DL-02~04, B-06~08 exporter provenance | unverified |
| 16 | 포맷별 clean import/loss report | DL-06~07, B-06~08 | unverified |
| 17 | Unity/Unreal project write 없음 | 사전·사후 destination root digest 또는 미접근 evidence | unverified |
| 18 | controller가 allowed output 밖 쓰기와 stale waiting adoption 거부 | CE-04~06, CE-14, 외부 root digest | unverified |
| 19 | infinite loop/duplicate/no-output budget 소비와 state splice 차단 | CE-07, CE-09~10, CE-13~15, action-budget receipt | unverified |
| 20 | 실제 품질 향상은 benchmark evidence가 있을 때만 주장 | benchmark comparison manifest와 verification 문구 parity | unverified |
| 21 | 전체 pytest/Ruff 통과 | 8.2, 8.4 exact logs | unverified |
| 22 | 가능한 환경에서 실제 Blender gate 통과 | B-01~11 전체 `blender_verified` | unverified |
| 23 | README/registry/verification이 코드와 일치 | repository summary `--check`, latest verification JSON | unverified |
| 24 | 미검증 adapter/profile이 experimental/disabled | registry/public surface/README parity와 음성 fixture | unverified |

## 10. 최종 fail-closed 규칙

- host test만 통과한 기능은 `contract_verified`를 넘지 않는다.
- Blender gate 중 하나라도 skip/not-run이면 실제 Blender 전체 통과를 주장하지 않는다.
- GLB 성공은 FBX 성공을 의미하지 않으며, dual delivery는 두 포맷의 독립 evidence를 요구한다.
- clean import 없이 exporter 성공만 있는 package는 실패다.
- MaterialGraph contract가 유효해도 compiled `.blend`, node inventory와 dependency hash가 없으면
  Blender compiler는 `unverified`다.
- reference benchmark가 없으면 synthetic contract/metric 방향성만 보고하며 실제 reference
  품질 향상은 `unverified`다.
- advisory/generated/inferred evidence는 observed direct evidence를 대체하거나 단독 pass authority를
  갖지 않는다.
- package failure를 quality failure로, quality pass를 delivery success로 재분류하지 않는다.
- test gate는 Unity/Unreal 프로젝트를 열거나 수정하지 않는다. Advanced Material Handoff의
  destination plan은 derived JSON일 뿐 runtime parity가 아니다.
- 기존 `autonomous_static_prop_v1`, legacy package, workflow, user workspace를 수정해 테스트를
  통과시키지 않는다.
- 전체 gate가 실제로 통과하기 전 `autonomous_static_prop_v2`는
  `disabled_experimental` 또는 `experimental_unverified` 상태를 유지한다.

실제 실행 날짜, host/Blender version, exact command, 결과, evidence path/hash와 남은 제한은
`VERIFICATION_AQ_V02_KO.md`에만 기록한다. 이 계획 문서의 `unverified` 표를 실행 결과처럼
수정하거나, 계획 자체를 성공 증거로 인용하지 않는다.

## 11. Material Closure additive regression

AQ v2 focused gate에는 다음을 additive하게 포함한다.

- closure projection과 request/assignment/completion map equality, reduced map rejection
- source binding → graph rebind → final closure의 순환 없는 replay
- existing MaterialPlan snapshot 또는 strict current absence
- approval 전 missing dependency, reference, UV/surface-detail, budget/rollback failure 차단
- actual Blender 5.0.1 shadow compile과 neutral preview가 canonical을 바꾸지 않음
- explicit appearance approval의 1회 consumption과 재사용/stale 거부
- fixed controller의 allowed-output confinement와 기존 host promotion 위임
- promotion 실패 rollback 뒤 attempt/canonical consistency, IQ 미진입
- raw AQ state와 combined material status가 모두 보이며 terminal session을 재개하지 않음
- 기존 AQ v2 evidence가 additive completion field 없이도 기존 의미로 읽힘
- AQ v2/ImageGen profile이 계속 `disabled_experimental`

정상 fixture의 approval/controller/promotion 각각 1회 assertion은 fixture가 제공한 specialized user
decision이 있을 때만 적용한다. current incident dry-run은 approval/controller/promotion 모두 0인
별도 행이며 `approval_pending` 또는 strict framework-blocked가 유일한 올바른 preapproval terminal이다.
