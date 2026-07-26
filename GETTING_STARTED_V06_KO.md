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

## 9. 승인형 1회 수정

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
