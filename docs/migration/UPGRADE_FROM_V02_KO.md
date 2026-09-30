# v0.2 → v0.4 이동

## 권장 방식

v0.4 전체 ZIP은 패치가 아니라 독립 프로젝트입니다. v0.2 위에 덮어쓰지 않습니다.

1. v0.4를 새 폴더에 풉니다.
2. v0.2의 `.env`를 복사합니다.
3. 필요한 `workspaces/<job>` 폴더를 복사합니다.
4. v0.4에서 검사합니다.

```powershell
Copy-Item ..\BlenderAssetGenerator-v02\.env .\.env
Copy-Item ..\BlenderAssetGenerator-v02\workspaces\first_reference_test `
  .\workspaces\first_reference_test -Recurse

uv sync --extra dev --extra vision
uv run cbm doctor
uv run cbm blender-compat
uv run cbm status first_reference_test
```

## SceneSpec 호환성

v0.4는 geometry SceneSpec `0.2.0`을 그대로 사용합니다. 기존 다음 파일은 변환 없이 재사용할 수 있습니다.

```text
analysis/scene_spec.json
geometry/*.mesh.json
input/*
textures/*
```

기존 `.blend`, preview, report, export는 보존할 수 있지만 v0.4에서 다시 build/render/inspect/validate하는 것이 권장됩니다.

## v0.2 로컬 호환성 패치

v0.4에는 사용 중 발견한 다음 수정이 이미 반영되어 있습니다.

- `BLENDER_EEVEE` → `BLENDER_EEVEE_NEXT` feature probe
- AgX fallback
- inspect runtime metadata
- `--python-exit-code 1`
- `stdin=subprocess.DEVNULL`
- OBJ modern/legacy operator fallback

따라서 v0.2의 수정된 `src/`를 v0.4에 복사하지 마세요.

## 기존 작업에 v0.4 분석 추가

```powershell
uv run cbm analyze-reference first_reference_test
```

이 명령은 기존 SceneSpec과 geometry를 변경하지 않고 다음 파일만 추가합니다.

```text
analysis/reference_analysis.json
analysis/camera_solution.json
analysis/modeling_plan.json
analysis/diagnostics/
analysis/masks/
```

## 주의

v0.4부터 새 작업 ID는 소문자만 허용됩니다. 기존 mixed-case v0.2 작업은 읽을 수 있지만, 새 작업은 Windows 경로 충돌을 막기 위해 소문자를 사용합니다.
