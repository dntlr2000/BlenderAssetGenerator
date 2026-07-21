# Codex Blender Modeler — Starter Repository

레퍼런스 이미지·청사진을 **구조화된 SceneSpec**으로 바꾸고, Codex가 Blender를 안전하게 조작하여 모델을 생성·검증·수정하도록 만든 시작 저장소입니다.

> 핵심 원칙: `.blend` 파일이 아니라 `workspaces/<job>/analysis/scene_spec.json`을 설계의 원본(source of truth)으로 사용합니다. 모든 수정은 이 명세를 바꾸고 Blender를 재생성하거나 패치하는 방식으로 수행합니다.

## 1. 포함된 것

- `AGENTS.md`: Codex가 항상 따라야 할 프로젝트 규칙
- `.agents/skills/`: 이미지 분석, 청사진 보정, Blender 빌드, 텍스처, 시각 검증 스킬
- `.codex/config.toml`: 프로젝트 범위 Blender MCP 서버 설정
- `src/codex_blender_modeler/`: CLI, Codex 실행기, Blender 실행기, MCP 서버
- `src/codex_blender_modeler/blender_scripts/`: Blender background-mode 빌드·렌더·검사·검증·내보내기 스크립트
- `schemas/`: SceneSpec, 수정 요청, 검증 보고서 JSON Schema
- `prompts/`: 분석·수정·텍스처·검증 프롬프트
- `examples/floating_island/`: 첨부 이미지와 저해상도 프록시 명세 예제

## 2. 권장 환경

- Git
- Codex CLI
- Blender 4.x 계열
- Python 3.11+
- `uv` 패키지 매니저

Blender는 자체 Python을 포함하므로, 일반 Python 환경과 Blender Python 환경을 섞지 않습니다. 일반 환경은 오케스트레이션과 MCP에, Blender 내장 Python은 `bpy` 실행에 사용합니다.

## 3. 설치

### macOS / Linux

```bash
git init
cp .env.example .env
# .env에서 BLENDER_BIN을 실제 Blender 실행 파일로 지정
./scripts/bootstrap.sh
uv run cbm doctor
codex
```

### Windows PowerShell

```powershell
git init
Copy-Item .env.example .env
# .env에서 BLENDER_BIN을 실제 blender.exe 경로로 지정
./scripts/bootstrap.ps1
uv run cbm doctor
codex
```

Codex를 처음 실행하면 로그인하고 저장소 신뢰 여부를 확인합니다. 저장소 루트에서 실행해야 `AGENTS.md`, `.agents/skills`, `.codex/config.toml`이 함께 적용됩니다. 연결 확인은 `codex mcp list`, Codex TUI 안에서는 `/mcp`로 합니다.

## 4. 가장 빠른 사용법

### A. 제공된 예제 프록시를 바로 Blender로 만들기

```bash
uv run cbm import-example floating_island
uv run cbm build floating_island
uv run cbm render floating_island
uv run cbm validate floating_island
uv run cbm export floating_island --format glb
```

결과:

```text
workspaces/floating_island/
├── input/reference.png
├── analysis/scene_spec.json
├── blender/scene.blend
├── renders/preview.png
├── reports/scene_inventory.json
├── reports/validation.json
└── exports/scene.glb
```

### B. 새 레퍼런스 이미지로 시작하기

```bash
uv run cbm new my_asset --image /absolute/path/reference.png --mode concept
uv run cbm analyze my_asset
uv run cbm build my_asset
uv run cbm render my_asset
uv run cbm validate my_asset
```

단일 이미지에서 실제 치수는 확정할 수 없으므로, 가능한 경우 정면·측면·평면도와 기준 치수를 함께 넣습니다. `--view`는 반복해서 사용할 수 있습니다.

```bash
uv run cbm new kiosk \
  --image /path/perspective.png \
  --mode measured \
  --view front=/path/front.png \
  --view right=/path/right.png \
  --view top=/path/top.png \
  --scale-anchor "front overall width = 2.4 m" \
  --scale-anchor "overall height = 1.8 m"
```

지원 입력 종류는 `front`, `right`, `top`, `blueprint`, `cad`입니다. CAD 파일은 현재 메타데이터 원본으로 보존되며, DXF/SVG 파서는 확장 지점입니다.

### C. Codex 대화형으로 직접 사용하기

```bash
codex --image workspaces/my_asset/input/reference.png \
  'Use $reference-to-scene. Analyze this reference, create or update analysis/scene_spec.json for job my_asset, then use the Blender MCP tools to build, render, inspect, and validate it. Do not claim real-world dimensional accuracy unless a scale anchor exists.'
```

Codex 안에서는 다음처럼 요청합니다.

```text
$visual-qa를 사용해 현재 preview.png와 reference.png를 비교해.
중앙 광장은 유지하고, 화산 지형의 높이만 20% 낮춰.
변경 전 SceneSpec을 history에 보존한 뒤 build → render → validate를 실행해.
```

### D. 사용자 피드백 반영

```bash
uv run cbm revise floating_island \
  "도시 구역의 고층 건물은 유지하되 도로 폭을 15% 넓히고, 다른 구역은 바꾸지 마."
uv run cbm build floating_island
uv run cbm render floating_island
uv run cbm validate floating_island
```

`revise`는 기존 명세를 `history/`에 보존한 뒤 전체 SceneSpec을 새 버전으로 교체합니다. 객체 ID가 유지되므로 변경 범위를 추적하기 쉽습니다.

## 5. 권장 제작 순서

1. **입력 고정**: 원본 이미지·청사진은 수정하지 않고 해시와 메타데이터를 기록
2. **측정 가능성 판정**: concept / measured 모드 결정
3. **카메라·좌표·스케일 보정**: 기준 치수, 소실점, 정사영 여부 기록
4. **프록시 모델**: 큰 덩어리와 실루엣부터 생성
5. **시각 검증**: 동일 카메라로 렌더해 영역·실루엣·비율 비교
6. **상세 모델**: 반복 모듈, 곡선, 부울, Geometry Nodes로 세분화
7. **텍스처**: 형상 승인 후 PBR 또는 절차형 재질 생성
8. **수정 루프**: 사용자 요청 → 명세 패치 → 빌드 → 렌더 → 검증
9. **내보내기**: `.blend`, `.glb`, 필요 시 `.usd` 등

## 6. 정확도에 대한 현실적인 구분

- `concept` 모드: 단일 이미지 기반의 시각적·비례적 재현. 가려진 부분과 절대 치수는 추정값입니다.
- `measured` 모드: 다중 뷰, 정면/측면/평면도, 치수선 또는 알려진 길이가 있을 때 제약식으로 복원합니다.
- 실제 제작·건축·기계 설계 수준의 정확도가 필요하면 최소한 정사영 뷰와 하나 이상의 절대 치수, 가능하면 CAD/DXF/SVG 입력을 추가해야 합니다.

## 7. MCP 보안 원칙

이 저장소의 MCP 서버는 임의의 Blender Python 실행 도구를 노출하지 않습니다. `build_scene`, `render_preview`, `inspect_scene`, `validate_scene`, `export_scene`처럼 허용된 작업만 제공합니다. 실험용으로 임의 코드 실행을 추가할 수 있지만, 프로덕션에서는 권장하지 않습니다.

## 8. 자동 텍스처

기본 구현은 SceneSpec의 `shader`와 PBR 파라미터를 사용해 Blender 절차형/Principled 재질을 만듭니다. 이미지 기반 텍스처 생성 서비스를 붙이려면 `textures/manifest.json` 계약을 지키는 provider를 추가하십시오.

필수 채널 권장:

```text
base_color.png
roughness.png
metallic.png
normal.png
height.png          # 선택
opacity.png         # 선택
texture_manifest.json
```

텍스처를 생성하기 전에 모델 UV와 실제 texel density 목표를 명세에 고정하는 것이 중요합니다.

## 9. 테스트

이 스타터는 Python 단위 테스트와 Ruff 정적 검사를 통과했습니다. 실제 Blender 빌드는 Blender가 설치된 로컬 환경에서 확인해야 합니다.

```bash
uv run pytest
uv run ruff check .
```

Blender가 설치된 환경에서는:

```bash
uv run cbm build floating_island
uv run cbm validate floating_island
```

## 10. 다음 확장 지점

- SAM 계열 마스크, 깊이 추정, 선분·소실점 검출
- 다중 뷰 카메라 캘리브레이션과 bundle adjustment
- Geometry Nodes 자산 라이브러리
- 이미지 생성 API 기반 seamless PBR texture provider
- CLIP/DINO 계열 시각 유사도와 edge/depth loss
- 작업 큐와 GPU Blender worker
- 웹 UI에서 영역 클릭 → 객체 ID 매핑 → 자연어 수정
