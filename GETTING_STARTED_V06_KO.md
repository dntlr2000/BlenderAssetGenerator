# V0.6 빠른 시작 — Material, Shader & Visual QA

## 1. 환경 확인

프로젝트 루트의 `.env`에 Blender 5.0.1 경로를 지정합니다.

```dotenv
BLENDER_BIN=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe
CODEX_BIN=codex
CBM_BLENDER_TIMEOUT=900
```

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm blender-compat
```

전체 회귀와 V0.5/V0.6 smoke를 한 번에 실행하려면:

```powershell
.\scripts\run_v06_gates.ps1
```

## 2. 재질 계약 초기화

Geometry와 카메라가 승인된 작업에만 재질 단계를 추가합니다.

```powershell
uv run cbm material-scaffold first_reference_test
uv run cbm validate-material-contracts first_reference_test
```

생성 파일:

```text
analysis/material_plan.json
materials/<material-id>/shader_recipe.json
reports/material_contract_validation.json
```

`material-scaffold`는 SceneSpec 재질의 현재 외형을 별도 계약으로 옮깁니다. 입력 이미지와 SceneSpec은 바꾸지 않으며 기존 계약이 있으면 `--overwrite` 없이는 거부합니다.

## 3. 결정론적 PBR 생성과 연결

지원 preset을 먼저 확인합니다.

```powershell
uv run cbm material-presets
```

실제 material ID를 `analysis/material_plan.json`에서 고른 뒤 6채널 PBR 세트를 생성합니다.

```powershell
uv run cbm generate-procedural-textures first_reference_test mat.rock.dark `
  --preset rock `
  --resolution 512 `
  --seed 606 `
  --scale-m 1.5 `
  --uv-set UVMap `
  --prompt "dark weathered volcanic rock"
```

기본 채널은 Base Color, Roughness, Metallic, Normal, Height, Emission입니다. 생성기는 오프라인 Pillow 기반이며 seed, provider, prompt, 각 파일 SHA-256을 TextureManifest에 기록합니다.

`--uv-set UVMap`은 다음 빌드에서 해당 재질 사용 메시의 기존 `UVMap`을 보존하거나 없으면 Smart UV를 생성합니다. 투영형 재질에는 `Object` 또는 `Generated`를 사용할 수 있지만 export bake에는 `UVMap`이 필요합니다.

별도로 만든 job-local manifest는 다음처럼 연결할 수 있습니다.

```powershell
uv run cbm attach-texture-manifest first_reference_test mat.rock.dark `
  --manifest textures/mat.rock.dark/texture_manifest.json
```

## 4. 빌드·재질 검사·swatch

```powershell
uv run cbm validate-material-contracts first_reference_test
uv run cbm build first_reference_test
uv run cbm render first_reference_test
uv run cbm inspect-materials first_reference_test
uv run cbm render-material-swatches first_reference_test --size 512
```

검사는 stable material ID, 노드 연결, 이미지 경로·hash·색 공간, UV 범위와 퇴화 면, texel-density 추정을 보고합니다.

## 5. Portable PBR 베이크

승인된 `.blend`와 UV 재질에서 Cycles로 5채널을 베이크합니다.

베이크 도구는 `.blend`에 기록된 SceneSpec, 외부 geometry/heightmap payload,
MaterialPlan, ShaderRecipe, TextureManifest, 실제 texture channel 해시를 현재 파일과
비교합니다. 이 중 하나를 수정한 뒤 `build`를 다시 실행하지 않으면 stale scene 오류로
베이크를 거부합니다. 완료된 `bake_manifest.json`에는 이 입력 해시와 source `.blend`
해시가 함께 기록됩니다.

```powershell
uv run cbm bake-materials first_reference_test `
  --profile gltf_pbr `
  --resolution 1024 `
  --material-id mat.rock.dark
```

생성 파일:

```text
bakes/<material-id>/gltf_pbr/
├─ base_color.png
├─ roughness.png
├─ metallic.png
├─ normal.png
├─ emission.png
└─ bake_manifest.json
reports/material_bakes.json
```

현재 `blender_eevee`, `blender_cycles`, `gltf_pbr` profile을 지원합니다. V0.6 결과는 별도 채널입니다. V0.7은 raw 채널을 보존하면서 glTF ORM을 파생할 수 있지만 Unity/Unreal 전용 packing과 실제 engine import는 별도 adapter 범위입니다.

## 6. 고정 카메라 Visual QA

먼저 `analyze-reference`, `build`, `render`가 완료되어야 합니다.

```powershell
uv run cbm visual-qa first_reference_test
```

한 번의 실행은 다음 불변 기록을 만듭니다.

```text
qa/runs/<run-id>/request.json
qa/runs/<run-id>/render_pass_manifest.json
qa/runs/<run-id>/passes/*.png
qa/runs/<run-id>/visual_qa_report.json
qa/runs/<run-id>/revision_candidates.json
qa/latest.json
```

직접 비교는 reference content mask, silhouette, object ID, SceneSpec의 observed evidence bbox를 사용합니다. beauty render나 생성 이미지에 형상 판정을 맡기지 않습니다.

## 7. 선택적 실내 다각도 QA

승인된 InteriorScope와 실제 interior semantic object가 있는 작업만 별도 실내 QA를 실행할 수 있습니다. 외관 작업은 이 단계를 건너뜁니다.

먼저 렌더 전 카메라 계획만 만들고 exact SHA-256을 확인합니다.

```powershell
uv run cbm interior-qa-plan <job-id> `
  --profile standard `
  --resolution 512 `
  --max-views 24
```

`minimal`, `standard`, `thorough`은 공간별로 각각 4, 6, 8개 방향을 제안합니다. 계획은 승인된 `level:`/`space:` 그룹과 semantic ID에 묶이며 이 단계에서는 렌더하거나 authoring `.blend`를 변경하지 않습니다.

사용자가 계획의 view 목록과 exact hash를 승인한 뒤:

```powershell
uv run cbm interior-qa-plan-approve <job-id> `
  --run-id <run-id> `
  --plan-sha256 <exact-plan-sha256> `
  --approval-note "표시된 실내 카메라 계획 승인"

uv run cbm interior-qa-run <job-id> `
  --run-id <run-id> `
  --approved-plan-sha256 <exact-plan-sha256>
```

각 view는 외관 QA와 동일한 정확히 7개 pass를 갖습니다. 다만 결과는 `qa/interior/runs/<run-id>/`에 분리되고 임시 카메라·isolation은 `.blend`에 저장되지 않습니다.

```powershell
uv run cbm report-pdf <job-id> `
  --scope qa `
  --interior-qa-run-id <run-id>
```

보고서의 semantic visibility는 여러 각도에서 대상 ID를 확인한 비율일 뿐 완성도나 레퍼런스 유사도 점수가 아닙니다. 매핑된 실내 레퍼런스가 없는 현재 구조에서는 reference comparison을 `unavailable`로 기록하고 모든 수정 후보를 manual-only로 남깁니다.

Codex는 같은 역할의 `plan_interior_qa`, `approve_interior_qa_plan`, `run_interior_qa`, `get_interior_qa_status` MCP 도구를 사용할 수 있으므로 사용자가 위 명령을 직접 실행할 필요는 없습니다. 단, exact plan hash에 대한 사용자 승인은 생략할 수 없습니다.

## 8. 외부 이미지 생성 결과를 보조 target으로 사용

기본값은 `image_model_qa = false`입니다. 명시적으로 활성화한 뒤, 외부 Codex/ImageGen 등의 표면에서 reference의 내용과 preview의 카메라·프레이밍을 이용해 이미지를 생성합니다. 정확히 사용한 prompt를 UTF-8 파일로 함께 보존합니다.

```powershell
uv run cbm visual-qa first_reference_test `
  --target-image E:\QA_Targets\first_reference_target.png `
  --target-prompt-file E:\QA_Targets\first_reference_target.prompt.txt `
  --target-model imagegen `
  --target-model-version <모델-버전> `
  --target-seed 1234 `
  --target-allowed-root E:\QA_Targets
```

target과 prompt는 QA run 내부로 복사되고 provider/model/version/seed/prompt hash/output hash가 기록됩니다. 저장소는 외부 서비스를 암묵적으로 호출하지 않습니다. 이 target은 저신뢰도 advisory finding만 만들며 직접 점수와 실행 후보 수를 바꾸지 않습니다.

## 9A. 승인형 1회 수정 — 기본 경로

기본 `revision_mode = "suggest"`에서는 후보만 생성합니다. 적용하려면 `cbm.toml`을 `approve`로 바꾸고 사용자가 정확한 후보 ID를 선택해야 합니다.

```powershell
uv run cbm qa-compile-revision first_reference_test <run-id> `
  --candidate-id <candidate-id> `
  --request "레퍼런스 직접 비교에서 확인된 비율 오차만 수정"

uv run cbm qa-approve-revision first_reference_test <run-id> `
  --candidate-id <candidate-id>

uv run cbm qa-apply-approved first_reference_test <run-id>
```

승인은 후보·계획·SceneSpec hash에 묶이고 한 번만 사용할 수 있습니다. 적용 후 build/render/inspect/validate/constraints/direct QA를 다시 실행합니다. 점수가 개선되지 않거나 오류·constraint 악화가 있으면 이전 SceneSpec을 복구하고 재빌드합니다.

## 9B. 선택적 bounded convergence — standard 전용

기본값은 계속 9A의 후보별 1회 승인입니다. 큰 형상과 비교 카메라는 이미
승인됐지만 비슷한 국소 수정 승인이 여러 번 반복될 때만 이 세션을 선택합니다.
`background_exterior` fast workflow 안에서는 사용할 수 없으며, 그 경로의
canonical 직접 QA 1회와 post-QA 자동 수정 금지 규칙은 그대로 유지됩니다.

일반 사용자는 PowerShell을 실행할 필요가 없습니다. Codex에 다음처럼 요청하면
`plan_visual_convergence` MCP 도구로 canonical 파일을 바꾸지 않은 채 계획만
작성합니다.

```text
<JOB_ID>의 current direct QA run <QA_RUN_ID>을 기준으로
standard bounded Visual QA convergence 계획만 작성해.

- target direct score: <TARGET_DIRECT_SCORE>
- target silhouette IoU: <TARGET_SILHOUETTE_IOU>
- allowed semantic IDs: <ALLOWED_TARGET_IDS>
- max iterations: 3

허용 path/operation/delta, minimum gain, confidence,
candidate group·candidate·changed-ID budget, locked ID와 stop 조건을 모두 보고해.
non-empty exact input hash map과 strict host-safety-envelope 경로/SHA-256도 보고해.
canonical SceneSpec은 수정하지 말고 exact plan SHA-256 승인에서 멈춰.
```

운영자용 CLI 표면은 다음과 같습니다. `--allowed-target-id`는 필요한 semantic
ID마다 반복할 수 있습니다. `--path-limit-json`도 strict JSON object로 반복할 수
있지만 host가 계산한 기본 path/operation/delta보다 좁은 권한만 요청할 수 있습니다.

```powershell
uv run cbm qa-convergence-plan <JOB_ID> <QA_RUN_ID> `
  --target-direct-score <TARGET_DIRECT_SCORE> `
  --target-silhouette-iou <TARGET_SILHOUETTE_IOU> `
  --allowed-target-id <SEMANTIC_ID> `
  --path-limit-json '{"path_family":"transform.location","allowed_operations":["add"],"max_absolute_delta":0.25}' `
  --max-iterations 3

uv run cbm qa-convergence-status <JOB_ID> <SESSION_ID>
```

계획에는 non-empty exact input map, initial SceneSpec/QA report, fixed camera와
scoring version, 목표, 허용·잠긴 ID, path/delta 규칙, candidate confidence,
per-iteration budget과 session-owned `host_safety_envelope.json`의 exact hash가
들어갑니다. Envelope는
`schemas/visual_convergence_host_safety_envelope.schema.json`으로 strict
검증됩니다. 기본 반복 수는 3, 하드 상한은 5입니다. 계획 자체는 canonical
SceneSpec이나 `.blend`를 수정하지 않습니다.

Codex가 보고한 exact plan SHA-256을 검토한 뒤에만 다음 승인을 사용합니다.

```text
<JOB_ID> convergence session <SESSION_ID>의
exact plan SHA-256 <PLAN_SHA256>을 승인한다.
현재 activation hash가 모두 일치할 때만 승인 기록 후 실행해.
```

동일한 운영자용 CLI:

```powershell
uv run cbm qa-convergence-approve <JOB_ID> <SESSION_ID> `
  --plan-sha256 <PLAN_SHA256> `
  --approval-note "검토한 bounded V0.6 convergence envelope 승인"

uv run cbm qa-convergence-run <JOB_ID> <SESSION_ID>
```

이 exact plan 승인은 해당 세션 안의 host-selected per-iteration 후보 승인만
대체합니다. 전역 `qa.revision_mode`를 `approve`/`auto`로 바꾸거나
`automatic_revision`을 켤 필요가 없습니다. 후보는 direct-reference evidence,
허용 semantic ID와 숫자 path/delta 안에 있어야 하며 카메라, 재질, custom-mesh
geometry, generated-target-only와 manual-required 후보는 자동 적용하지 않습니다.

각 iteration은 build/render/inspect/validate, constraint 재평가와 새 direct QA를
수행합니다. 승인된 minimum direct-score gain에 못 미치거나 silhouette IoU 또는
constraint가 악화되면 baseline SceneSpec을 복구하고 종료합니다. 목표 도달,
plateau, eligible candidate 없음, manual review, budget, regression, cancellation,
stale/tampered evidence 또는 host failure에서도 더 넓은 권한을 추론하지 않고
멈춥니다.

한 번의 `run_visual_convergence` 호출은 full Blender iteration을 최대 한 번만
수행합니다. 응답이 `active`이고 `next_action=invoke_run_again`이면 Codex가 같은
exact plan/approval을 다시 검증해 다음 iteration을 이어갑니다. 호출이 중단된
경우 다음 호출은 새 수정을 시작하지 않고 먼저 staging의 exact hash를 검증하고
baseline SceneSpec·build·QA 상태를 복구한 뒤 recovery 결과를 보고합니다.
그 다음 호출부터 새 iteration을 시작할 수 있습니다.

완료 결과는 다음 위치에 저장됩니다.

```text
qa/convergence/<session-id>/
├─ plan.json
├─ approval.json
├─ host_safety_envelope.json
├─ initial_scene_spec.json
├─ initial_build_provenance.json
├─ initial_constraints.json              # 제약 계약이 있을 때
├─ staging/<nnn>/                        # 현재 호출의 미완료 작업
├─ interrupted_attempts/<nnn>-<id>/      # 복구 후 보존한 중단 evidence
├─ iterations/<nnn>/base_scene_spec.json
├─ iterations/<nnn>/selection.json
├─ iterations/<nnn>/revision_plan.json
├─ iterations/<nnn>/authorization.json
├─ iterations/<nnn>/result_scene_spec.json
├─ iterations/<nnn>/result_build_provenance.json
├─ iterations/<nnn>/before_constraints.json
├─ iterations/<nnn>/after_constraints.json
├─ iterations/<nnn>/receipt.json
├─ cancellation_receipt.json             # 취소한 세션만
├─ final_scene_spec.json
├─ final_build_provenance.json
├─ convergence_report.json
├─ convergence_report.pdf
└─ convergence_report.manifest.json
```

새로 작성한 plan은 non-empty exact input hash map, initial candidates, build
fingerprint/provenance, host-safety-envelope와 현재 constraint 계약까지 exact
hash로 결속합니다. 이 신규 실행 binding이 없는 기존 partial plan은
조회·감사용 historical evidence로만 읽을 수 있고 승인하거나 재실행할 수
없습니다. 그런 세션은 수정하지 말고 current direct QA에서 새 convergence
plan을 작성합니다.
Host는 initial evidence에서 `host_safety_envelope.json`을 다시 계산해 exact
hash로 비교하므로 plan을 직접 고쳐 material, interior, custom-mesh 또는 locked
ID 권한을 추가할 수 없습니다.

상태 확인과 명시적 취소는 `get_visual_convergence_status`,
`cancel_visual_convergence` MCP 도구 또는 다음 CLI로 수행합니다.

상태 응답의 `execution_eligible`, `status_only_legacy`,
`execution_block_reason`, `execution_binding_gaps`를 먼저 확인합니다.
`next_action`은 `approve_exact_plan`, `invoke_run_again`,
`invoke_run_to_recover`, `invoke_run_to_finalize` 중 현재 허용되는 다음 host
행동을 나타냅니다. `recovery_required`이거나 receipt-less staging이 있으면
취소하거나 terminalize하지 말고 `qa-convergence-run`을 한 번 호출해 복구한 뒤
다시 상태를 확인합니다. Terminal evidence와 receipt-less staging이 함께 있으면
세션은 stale/tampered integrity failure입니다.

```powershell
uv run cbm qa-convergence-status <JOB_ID> <SESSION_ID>
uv run cbm qa-convergence-cancel <JOB_ID> <SESSION_ID> `
  --reason "사용자 검토를 위해 bounded session 중단"
```

수렴 세션 승인은 InteriorScope, 실내 QA 카메라, V0.7 optimization, package,
Destination Handoff 또는 engine-specific 작업의 승인이 아닙니다.

## 10. 사람용 PDF 보고서 만들기

재질 검사와 swatch가 끝난 뒤:

```powershell
uv run cbm report-pdf first_reference_test --scope material
```

Visual QA가 끝난 뒤:

```powershell
uv run cbm report-pdf first_reference_test `
  --scope qa `
  --qa-run-id latest
```

전체 검토 자료가 필요할 때:

```powershell
uv run cbm report-pdf first_reference_test --scope full
```

다른 경로로 저장하려면 `.pdf` 확장자를 가진 `--output` 경로를 지정합니다.

```powershell
uv run cbm report-pdf first_reference_test `
  --scope material `
  --output E:\Reports\first_reference_material.pdf
```

기본 출력은 활성 workspace 옆의 `output/pdf/<job>/` 아래에 저장됩니다. 같은 이름의 `.manifest.json`에는 PDF와 원본 JSON·이미지의 해시가 기록됩니다.

PDF는 재질 상태, 경고, swatch, QA 패스와 수정 후보를 사람이 검토하기 쉽게 정리한 결과입니다. 실제 수정과 자동 검증은 계속 `reports/`, `materials/`, `textures/`, `qa/runs/`의 JSON 계약을 기준으로 수행합니다.

## 11. 현재 경계

- 제한된 whitelisted Noise/replace 셰이더와 검증된 image-map 경로만 실행합니다.
- procedural triplanar는 Object 좌표 근사입니다. image/hybrid triplanar는 거부합니다.
- Smart UV는 자동 기본 unwrap이며 seam 설계, multi-object atlas, 고품질 retopology를 제공하지 않습니다.
- 동일 재질을 공유하는 여러 객체는 UV가 겹칠 수 있으므로 최종 atlas/packing 전에 검사해야 합니다.
- PBR provider는 결정론적 합성 생성기이지 레퍼런스 기반 고품질 재질 생성 모델이 아닙니다.
- Engine-neutral LOD, collider, raw/glTF packing과 clean-import round trip은 V0.7 범위입니다. Unity/Unreal 전용 import와 runtime material은 대상 엔진 확인 뒤 별도 adapter로 남습니다.
- 생성 이미지 target은 보조 QA이며 단일 이미지의 숨은 구조를 진실로 복원하지 않습니다.
- 실내 다각도 QA는 구조·가시성 검사이며 실내 레퍼런스가 없으면 유사도 점수를 만들지 않습니다.
- bounded convergence는 standard의 선택 기능이며 default one-shot 승인을 바꾸지 않습니다. exact plan의 최대 5회 밖으로 자동 확장하거나 background fast workflow에서 사용하지 않습니다.
- V0.4에서 `surface_details`로 분류한 작은 창문·라벨·이음선은 V0.5의 exact
  `TextureManifest.surface_detail_ids`와 UVMap PBR 채널로 결속합니다. V0.6은 이 상태를
  geometry 점수와 분리해 보고하며, 빠진 픽셀은 material/texture revision으로 되돌립니다.
