# Blender 5.0.1 호환성 설계

## 반영된 실패 사례

### 렌더 엔진 enum

Blender 5.0.1에서 `BLENDER_EEVEE_NEXT`가 거부되는 문제를 막기 위해 버전 문자열 대신 실제 enum 설정을 probe합니다.

```text
BLENDER_EEVEE
BLENDER_EEVEE_NEXT
```

### MCP stdio 상속

MCP 서버의 열린 stdin을 Blender 자식 프로세스가 상속해 정체되는 문제를 막기 위해:

```python
stdin=subprocess.DEVNULL
```

### Python 예외 성공 오인

Blender background Python 예외를 비정상 종료로 전달하도록:

```text
--python-exit-code 1
```

### Export operator

OBJ는 modern `bpy.ops.wm.obj_export`를 우선 사용하고 legacy operator를 fallback으로 둡니다.

## 검사 명령

```powershell
uv run cbm blender-compat
```

결과:

```text
reports/blender_compatibility.json
reports/compat_exports/compat.glb
reports/compat_exports/compat.obj
reports/compat_exports/compat.fbx
```

이 probe가 통과한 뒤 geometry_showcase 전체 파이프라인을 실행해야 합니다. API probe 통과만으로 geometry builder 전체 호환을 주장하지 않습니다.
