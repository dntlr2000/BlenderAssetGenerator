# v0.4 빠른 시작 — Blender 5.0.1

## 1. 새 폴더에 설치

v0.2 위에 덮어쓰지 말고 새 폴더에 압축을 풉니다.

```text
E:\Playground\
├─ BlenderAssetGenerator-v02\
└─ BlenderAssetGenerator-v04\
```

## 2. 환경 복사

```powershell
Copy-Item ..\BlenderAssetGenerator-v02\.env .\.env
```

또는 `.env.example`을 복사한 후 Blender 5.0.1 경로를 지정합니다.

```dotenv
BLENDER_BIN=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe
CODEX_BIN=codex
CBM_BLENDER_TIMEOUT=900
```

## 3. 의존성

```powershell
uv sync --extra dev --extra vision
uv run cbm doctor
```

OpenCV가 필요 없으면:

```powershell
uv sync --extra dev
```

## 4. Blender 호환성 gate

```powershell
uv run cbm blender-compat
```

완료 조건:

- `ok: true`
- Blender `5.0.1`
- render engine `BLENDER_EEVEE`
- GLB/OBJ/FBX smoke export 성공

## 5. geometry core 회귀

```powershell
uv run cbm import-example geometry_showcase
uv run cbm build geometry_showcase
uv run cbm render geometry_showcase
uv run cbm inspect geometry_showcase
uv run cbm validate geometry_showcase
```

이 예제는 geometry 6종과 modifier 8종 전체의 declared/applied provenance를 검증합니다.

승인된 실제 작업 구조 회귀와 stdio MCP Cycles/GPU까지 확인하려면:

```powershell
uv run cbm import-example first_reference_test
uv run cbm build first_reference_test
uv run cbm render first_reference_test
uv run cbm inspect first_reference_test
uv run cbm validate first_reference_test
uv run python scripts/verify_v04_regressions.py
uv run python scripts/run_v04_mcp_regressions.py --render-engine cycles --render-device gpu
```

## 6. 새 이미지 테스트

```powershell
uv run cbm new building_001 --image E:\References\building.png --mode concept
uv run cbm analyze-reference building_001
uv run cbm status building_001
```

Codex에서 이미지와 함께:

```text
$quick-reference-model을 사용해 building_001의 레퍼런스를 분석하고
프록시 SceneSpec을 작성한 뒤 build → render → inspect → validate를 실행해.
텍스처와 export는 하지 말고 승인 대기해.
```

## 7. 두 번째 이미지 작업

항상 새로운 ID를 사용합니다.

```powershell
uv run cbm new temple_001 --image E:\References\temple.png --mode concept
uv run cbm analyze-reference temple_001
```

같은 ID 재사용은 코드가 거부하므로 첫 작업이 덮어써지지 않습니다.

## 8. 기존 자산 수정

새 job을 만들지 않습니다.

```powershell
uv run cbm plan-revision building_001 "중앙 탑 높이만 15% 높여"
uv run cbm apply-revision building_001
uv run cbm build building_001
uv run cbm render building_001
uv run cbm validate building_001
```

## 전체 검증을 한 번에 실행

Windows PowerShell:

```powershell
.\scripts\run_v04_gates.ps1
```

OpenCV 설치를 생략하려면 `-SkipVision`, export 검사를 생략하려면 `-SkipExports`,
GPU MCP 회귀를 생략하려면 `-SkipMcpCycles`를 사용합니다. 기본 실행은 Python 검사,
Blender 5 호환성 probe, Geometry Core 8종 modifier, measured pass/fail, authored plan,
승인된 실제 작업 구조, stdio MCP Cycles/GPU를 순서대로 검증합니다.

## 작은 표면 디테일 분류

새 ModelingPlan은 창문 무늬, 이음선, 리벳, 라벨, 얕은 패널처럼 외곽과 구조를
바꾸지 않는 항목을 `surface_details`로 분리합니다. 이 ID는 SceneSpec geometry에
동시에 존재할 수 없습니다. 반대로 실루엣, 구조, gameplay 또는 실제 투명 개구부에
필요한 부품은 정상 geometry object로 유지합니다.

V0.4에서는 분류와 geometry 중복 방지만 수행합니다. 실제 UVMap PBR 맵 결속은
V0.5에서 완료하며, 상세 계약은 [표면 디테일 분류 가이드](SURFACE_DETAIL_ROUTING_KO.md)를
참조합니다.

## 단일 시점 자산의 3차원 조립 검증

새로 작성하는 ModelingPlan은 `assembly_consistency_policy=spatial_v1`을 사용합니다.
자산 로컬의 길이축·좌우축·수직축과 root를 먼저 선언하고, 각 semantic object를
`root`, `attached`, `free_standing`으로 분류합니다. 부착 부품에는 적용 가능한
`center_plane`, `coaxial`, `bbox_containment`, `surface_contact`, `bilateral_pair`
관계를 기록합니다.

단일 측면 또는 사선 레퍼런스의 화면상 오프셋은 숨은 좌우·깊이 위치의 증거가
아닙니다. 좌우 대칭 제품의 트리거, 레버, 손잡이, 바퀴, 축 같은 기능 부품은
다른 근거가 없으면 중심면 또는 공통 축에 있다고 `inferred`로 기록합니다.
정사영 뷰, 청사진, 치수 또는 명시적인 사용자 요구가 실제 비대칭을 뒷받침할
때만 `side_specific`을 사용합니다.

`build → inspect → validate`는 ModelingPlan hash를 `.blend`에 결속하고 실제 평가된
geometry bounds를 root 로컬 meter frame에서 검사합니다. 필수 관계가 실패하면
재질·텍스처 단계로 넘어가지 말고 V0.4 SceneSpec을 수정합니다. 이 결과는 정적
배치 검증이며 실제 동작 간극, 운동학, 제조 가능성 또는 보이지 않는 면의 정답을
증명하지 않습니다.
