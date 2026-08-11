# Material Authoring 0.1 사용·계약 안내

## 1. 역할과 현재 상태

Material Authoring `0.1.0`은 기존 V0.5 `MaterialPlan`, `ShaderRecipe`,
`TextureManifest`, `BakeManifest`를 대체하지 않는 run-owned companion이다. exact V0.5
contract와 UV/scale evidence를 입력으로 받아 로컬에서 deterministic raw PBR candidate를 만들고,
그 provenance와 알려진 손실을 immutable receipt로 남긴다.

현재 run-owned companion의 범위는 **host-side deterministic authoring**이다. 별도 isolated
Blender 5.0.1 smoke에서 wood, metal, signage/decal, emissive, crystal 다섯 family의 fixed
Principled compile·save/reopen·render receipt가 `5 passed`로 확인됐다. 이 smoke는 원본
authoring manifest를 바꾸지 않으며 manifest의 master/preview 상태는 계속 `not_run`이다.
reference-matched render, family별 고급 master graph, package appearance와 destination parity는
아직 검증하지 않았다. 따라서 생성된 manifest의 기본 status는 `unverified` 또는
`review_required`이며 `completed`나 일반 Blender parity를 주장하지 않는다.

새 companion용 전용 CLI/MCP 명령은 아직 없다. 기존 공개 V0.5 명령인
`material-scaffold`, `validate-material-contracts`, `generate-procedural-textures`,
`bake-materials`, `inspect-materials`, `render-material-swatches`의 의미는 변하지 않는다.

AQ v2의 별도 `material_phase_service`는 material controller가 격리 output으로 낸 exact
MaterialPlan, MaterialGraph와 completion marker를 strict 검증한다. whitelist graph를 실제로
compile하고 canonical V0.5 plan을 compare-and-swap으로 archive/promotion한 뒤 Blender scene을
rebuild·inspect·validate해 fresh provenance를 발행한다. 2026-08-11 host-focused supervisor gate에서
geometry promotion 다음 material phase와 IQ 대기 전환이 통과했다. 별도의 실제 Blender evidence는
fixed MaterialGraph compile smoke이며 전체 material-promotion E2E로 재분류하지 않는다. 이 경로도 caller가 공급할 IQ
report나 사용자 승인을 합성하지 않으며 companion manifest의 `not_run` 상태를 소급 변경하지 않는다.

이 promotion이 이후 passed IQ와 source freeze에 사용되려면 current canonical MaterialPlan,
ShaderRecipe, TextureManifest, rebuilt blend/build provenance와 accepted material promotion receipt가
모두 exact input/source map에 포함돼야 한다. 이전 material candidate나 receipt summary만 가리키는 IQ,
또는 accepted promotion 뒤 material/shader/texture가 바뀐 IQ는 stale로 거부한다. geometry promotion
receipt와 GeometryIntent survival도 같은 source closure의 별도 필수 항목이다.

## 2. 불변 조건

- canonical V0.5 contract와 source texture를 수정하지 않는다.
- output은 `material_authoring/runs/<run-id>/` 아래의 새 immutable bundle이다.
- 모든 입력과 출력은 job-relative POSIX path, byte size, SHA-256으로 결속한다.
- absolute path, `..`, backslash, drive path와 output overwrite를 거부한다.
- `MaterialAuthoringRequest.canonical_write_authority=false`다.
- `destination_write_authority=false`, `runtime_parity_verified=false`다.
- normal output은 portable OpenGL `+Y` convention을 명시한다.
- Base Color와 Emission은 `srgb`, 나머지 raw PBR channel은 `non_color`다.
- Blender master intent와 portable approximation은 서로 다른 evidence다.

## 3. 입력 계약

한 request는 다음을 exact하게 고정한다.

- `job_id`, `workflow_id`, `run_id`, stable `material_id`
- 하나 이상의 V0.5 source contract, 그중 반드시 `v05-material-plan`
- exact `AssetScaleContext 0.1.0`
- exact UV identity와 이를 증명하는 inventory artifact
- authoring strategy 하나와 그 strategy 전용 payload 하나
- resolution selector input과 선택적 8192 authorization
- neutral/reference preview 정책
- output root `material_authoring/runs/<run-id>`

UV identity에는 semantic ID, UV set, ordered polygon-corner count, UV fingerprint와 texel
density가 들어간다. service는 cached 값만 믿지 않고 exact evidence를 다시 읽어 scale context와
UV fingerprint가 current인지 확인한다.

## 4. 전략 목록

| strategy | material family | 실제 host 동작 | 핵심 제한 |
|---|---|---|---|
| `uniform_portable_fallback_v1` | `uniform_fallback` | 기존 V0.5 256×256 channel bytes를 그대로 채택 | 고품질 spatial detail로 간주하지 않음 |
| `user_image_pbr_v1` | `user_image_pbr` | exact user image를 지정 tier로 local resample | source 권리·UV·colorspace 필요 |
| `localized_decal_v1` | `signage_decal` | image 또는 exact local text를 bounded UV rect에 rasterize | 모르는 문구를 발명하지 않음 |
| `planar_reference_patch_v1` | `planar_reference_patch` | source crop을 네 corner로 deterministic rectification | 관찰/추정·corner provenance 필요 |
| `procedural_wood_v1` | `wood` | seed와 물리 scale에 결속된 local PBR tile 생성 | Blender grain axis/neutral preview 미검증 |
| `procedural_metal_v1` | `metal` | bounded metallic/roughness/brushed normal 생성 | 근거 없는 scratch를 추가하지 않음 |
| `emissive_pattern_v1` | `emissive` | source-bound emission/opacity pattern 생성 | 실제 bloom/runtime emission 아님 |
| `crystal_portable_approximation_v1` | `crystal` | portable base/roughness/normal/emission/opacity 근사 생성 | transmission/absorption/refraction 보존 안 됨 |

`uniform_portable_fallback_v1`은 기존 V0.5 candidate enum이나 bytes의 의미를 바꾸지 않는다.
companion mapping이 legacy strategy `portable_pbr_v05`를 이 이름으로 설명할 뿐이다.

## 5. user image PBR

지원 channel은 다음과 같다.

- `base_color`
- `roughness`
- `metallic`
- `normal`
- `height`
- `occlusion`
- `opacity`
- `emission`

각 image는 contained relative path, SHA-256, byte size, width, height, colorspace, license ID,
rights status와 provenance를 가진다. 모든 channel은 동일한 UV identity를 사용해야 한다.
normal source는 `opengl_y_plus` 또는 `directx_y_minus`를 명시하며, DirectX 입력은 local host가
portable OpenGL `+Y`로 변환하고 limitation에 기록한다.

`rights_status=unknown`은 bytes 사용을 숨기지 않고 limitation으로 유지한다. 채널이 선택된
resolution과 다르면 deterministic resample 사실과 전후 dimensions를 manifest에 남긴다.

## 6. localized decal과 planar patch

### 6.1 decal text

text evidence는 다음 셋 중 하나다.

- `exact_user_text`
- `unknown_text`
- `inferred_placeholder`

오직 `exact_user_text`만 rasterize할 수 있다. outline text는 exact project-local TTF/OTF,
deterministic bitmap text는 exact project-local bitmap-font JSON을 요구한다. OS font나 network
font를 탐색하지 않는다. 알 수 없는 glyph와 문구를 대신 만들어 넣지 않는다.

decal은 normalized UV rect, clip mode, alpha, roughness, normal/emission parameter와 2~128px
mip padding을 가진다. RGB bleed와 alpha edge를 분리해 padding하며, placement와 source/font hash를
output provenance에 넣는다.

### 6.2 planar patch

planar patch는 exact source image, 네 source corner, target UV rect, crop/rectification 정책,
semantic ID와 observed/inferred 상태를 결속한다. corner 순서나 rect가 잘못되면 fail-closed한다.
자동 검출 결과를 observed truth로 승격하지 않는다.

## 7. scale과 texture resolution

selector 입력은 material family, mapping kind, projected pixel footprint, target texel density,
longest object dimension, package byte budget와 선택적 requested tier를 고정한다.

일반 tier는 다음과 같다.

```text
256, 512, 1024, 2048, 4096
```

selector는 scale recommendation, projected footprint와 package budget 중 안전한 상한을 적용한다.
4096 초과는 묵시적으로 허용되지 않는다. 현재 별도 authorization이 허용하는 유일한 초과 tier는
8192이며, 다음을 모두 만족해야 한다.

- selector input의 exact SHA-256과 일치
- `authorized_pixels=8192`
- purpose `material_authoring_resolution_above_4096`
- `authorized_by=user`
- request가 그 exact authorization artifact를 참조

authorization이 없거나 stale하면 8192 request는 거부한다. profile budget은 authorization보다
우선하여 더 낮은 tier로 제한할 수 있다.

## 8. 출력 구조와 판독

```text
material_authoring/runs/<run-id>/
├─ request.json
├─ material_authoring_manifest.json
├─ material_authoring_receipt.json
└─ textures/
   ├─ base_color.png
   ├─ roughness.png
   ├─ metallic.png
   ├─ normal.png
   └─ ...
```

`material_authoring_manifest.json`은 strategy, family, exact sources, scale, resolution,
raw channels, Blender master intent, preview states, known losses와 source-to-output digest를 가진다.
`material_authoring_receipt.json`은 request, manifest, 모든 output과 sorted bundle digest를
결속한다.

현재 local authoring service의 상태 해석은 다음과 같다.

- channel이 생성됨: `status=unverified`
- unknown/inferred text 등으로 channel을 만들 수 없음: `status=review_required`
- Blender master compile과 neutral preview까지 exact evidence로 통과한 미래 경로만
  `status=completed`를 주장할 수 있음

별도 `blender_smoke_receipt.json`의 `status=passed`는 fixed isolated fixture가 exact raw
channels를 읽고 제한된 Principled graph를 compile·reopen·render했다는 뜻이다. 이 receipt는
원본 manifest의 `blender_compilation_status=not_run` 또는
`neutral_studio_status=not_run`을 소급 변경하지 않는다.

receipt의 `status=published`는 immutable host bundle이 게시됐다는 뜻이다. 재질 품질 합격,
Blender compile 성공 또는 destination parity라는 뜻이 아니다.

## 9. neutral preview와 reference preview

두 preview는 목적이 다르다.

- neutral studio: 재질 자체의 channel, roughness, normal, opacity, scale을 통제된 조명에서 확인
- reference matched: 원본 장면과 비슷한 조명·카메라에서 사용 맥락을 보조 확인

reference preview가 좋아도 neutral studio evidence를 대체할 수 없다. 현재 authoring manifest는
두 preview를 canonical authoring 단계에서 실행하지 않으므로
`neutral_studio_status=not_run`, reference가 요청됐다면
`reference_matched_status=not_run`으로 정확히 기록한다. 별도 fixed Blender smoke render를
canonical neutral/reference preview로 재분류하지 않는다.

## 10. Advanced Material Handoff

Advanced Material Handoff `0.1.0`은 완전한 authoring receipt와 manifest를 다시 hash 검증한 뒤
Unity URP 또는 HDRP용 **advisory JSON plan**을 만든다.

```text
exports/advanced_material_handoffs/<plan-id>/
├─ advanced_material_handoff_request.json
├─ unity_urp_material_plan.json 또는 unity_hdrp_material_plan.json
└─ advanced_material_handoff_receipt.json
```

plan에는 raw channel→destination property mapping, roughness→smoothness 변환, packing channel,
preferred shader family, unsupported feature, known loss와 검토 작업이 들어간다. crystal의
transmission/IOR/absorption, Shader Graph 창작과 runtime 결과는 보존됐다고 주장하지 않는다.

이 service는 파일을 destination project로 복사하지 않고 Unity를 실행하지 않으며 material을
생성하지 않는다. 모든 contract와 receipt에서 다음이 유지된다.

```text
status=advisory_plan
destination_write_performed=false
runtime_parity_verified=false
user_approval_required_before_destination_changes=true
```

## 11. 실패와 재개

다음 상황은 성공으로 보정하지 않는다.

- source V0.5/scale/UV/image hash 또는 size 변경
- path escape, 누락 dependency, output root 재사용
- channel duplicate, 잘못된 color space 또는 normal convention
- strategy와 payload 불일치
- 알 수 없는 text를 exact로 위장
- 4K 초과인데 exact authorization 없음
- authoring receipt와 advanced handoff manifest/output bundle 불일치

immutable run이 실패하면 같은 폴더를 수리하거나 overwrite하지 말고 source 문제를 해결한 뒤 새
`run_id` 또는 새 `plan_id`를 사용한다. canonical V0.5 contract를 gate 성공용으로 수정하지 않는다.

AQ v2 material candidate promotion 중 rebuild/inspect/validate가 실패하면 이전 canonical
MaterialPlan과 blend를 exact archive에서 복원하고 rollback receipt를 남긴다. controller output이나
completion marker만으로 canonical 성공을 주장하지 않는다.

## 12. 현재 남은 제한

- 다섯 family의 fixed Blender compile/reopen/render smoke는 통과했지만 family별 고급 master
  graph가 local authoring manifest lifecycle에 연결되지는 않았다.
- canonical neutral/reference Blender preview와 실제 bake/package quality는 `unverified`다.
- TTF/OTF deterministic rendering은 설치 환경 차이를 별도 검증해야 한다.
- procedural wood/metal의 object-basis 방향 일치와 seam 품질은 Blender evidence가 필요하다.
- crystal portable maps는 transmission/refraction/volume을 보존하지 않는다.
- Advanced Material Handoff는 Unity URP/HDRP advisory 계획일 뿐 importer나 adapter가 아니다.
- package, clean import와 destination runtime parity는 각각 V0.7과 검증된 destination adapter의
  별도 evidence가 필요하다.
