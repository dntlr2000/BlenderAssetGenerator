# v0.4 로컬 테스트 계획

## Gate A — Python 및 구조

```powershell
uv sync --frozen --extra dev --extra vision
uv run pytest
uv run ruff check .
uv run cbm doctor
```

예상: Python 테스트 전체 통과, Ruff 통과, Blender/Codex 경로 OK.

## Gate B — Blender 5.0.1 API

```powershell
uv run cbm blender-compat
```

확인:

- Blender 5.0.1
- `BLENDER_EEVEE`
- Python exception propagation
- stdin isolation
- GLB/OBJ/FBX smoke export

## Gate C — v0.2 Geometry Core 회귀

```powershell
uv run cbm import-example geometry_showcase
uv run cbm build geometry_showcase
uv run cbm render geometry_showcase
uv run cbm inspect geometry_showcase
uv run cbm validate geometry_showcase
uv run cbm export geometry_showcase --format glb
uv run cbm export geometry_showcase --format obj
uv run cbm export geometry_showcase --format fbx
```

`validation.json`의 `declared_modifier_kinds`와 `applied_modifier_kinds`에는 다음 8종이
모두 있어야 합니다.

```text
bevel, mirror, subdivision, solidify, array, decimate, remesh, boolean
```

## Gate D — v0.4 measured constraints

```powershell
uv run cbm import-example measured_box
uv run cbm analyze-reference measured_box --projection ortho
uv run cbm build measured_box
uv run cbm render measured_box
uv run cbm inspect measured_box
uv run cbm validate measured_box
uv run cbm evaluate-constraints measured_box
```

예상 constraint 결과: 3개 모두 pass.

또한 authored `modeling_plan.json`은 비어 있지 않아야 하며 observed/inferred 객체를
구분해야 합니다. `scripts/verify_v04_regressions.py`는 실제 inventory를 대상으로
통과 제약 1개와 의도적으로 실패하는 제약 1개를 평가해 residual/status 분류를 검사합니다.

## Gate E — 승인된 실제 작업 구조 회귀

```powershell
uv run cbm import-example first_reference_test
uv run cbm analyze-reference first_reference_test
uv run cbm build first_reference_test
uv run cbm render first_reference_test
uv run cbm inspect first_reference_test
uv run cbm validate first_reference_test
uv run python scripts/verify_v04_regressions.py
```

입력·SceneSpec·geometry payload 해시, 40개 semantic family, 63개 생성 mesh,
vertex/polygon 기준과 고정 카메라가 승인 baseline과 일치해야 합니다.

## Gate F — stdio MCP + Cycles/GPU

```powershell
uv run python scripts/run_v04_mcp_regressions.py --render-engine cycles --render-device gpu
```

세 예제 모두 `build_scene → render_preview → inspect_scene → validate_scene`을 실제
stdio MCP로 실행하며 Blender 5.0.1, `CYCLES`, `GPU`, backend/device를 보고합니다.

## Gate G — 새 실제 이미지

```powershell
uv run cbm new building_001 --image E:\References\building.png --mode concept
uv run cbm analyze-reference building_001
```

Codex 프롬프트:

```text
$quick-reference-model을 사용해 building_001을 프록시 모델링해.
reference_analysis와 camera_solution을 먼저 읽고,
SceneSpec 작성 후 build → render → inspect → validate를 실행해.
텍스처와 export는 하지 말고 승인 대기해.
```

## 성공 기준

- 새 이미지 작업끼리 경로가 격리됨
- duplicate job ID가 파일 변경 없이 거부됨
- MCP build가 stdin 정체 없이 종료됨
- scene inventory에 Blender 버전, 엔진, look, world bbox가 기록됨
- 구조 validation과 measured constraint evaluation이 별도로 보고됨

## 자동 실행

Windows PowerShell에서는 다음 한 줄로 Gate A~F를 실행할 수 있습니다.

```powershell
.\scripts\run_v04_gates.ps1
```

GPU가 없는 환경에서 구조 게이트만 실행하려면 `-SkipMcpCycles`를 사용합니다. 새 실제
레퍼런스의 품질 평가는 Gate G에서 별도로 수행합니다.
