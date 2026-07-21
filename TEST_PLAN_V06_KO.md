# V0.6 통합 테스트 계획

## Gate 0 — Python과 공개 표면

```powershell
uv run pytest
uv run ruff check .
uv run cbm --help
uv run cbm doctor
```

완료 조건: 전체 테스트·Ruff 통과, V0.5/V0.6 CLI 표시, MCP 서버 import와 whitelist 일치.

## Gate 1 — V0.4 회귀

```powershell
.\scripts\run_v04_gates.ps1
```

Geometry 6종, modifier 8종, reference analysis, measured residual, 실제 작업 회귀, stdio MCP, Blender 5.0.1 GLB/OBJ/FBX export가 유지되어야 합니다.

## Gate 2 — Material/Shader/Texture 계약

격리된 smoke workspace에서 다음을 실행합니다.

```powershell
uv run cbm material-scaffold geometry_showcase
uv run cbm generate-procedural-textures geometry_showcase mat.blue `
  --preset rock --resolution 128 --seed 606 --uv-set UVMap --overwrite
uv run cbm validate-material-contracts geometry_showcase
uv run cbm build geometry_showcase
```

완료 조건:

- SceneSpec과 입력 hash 불변
- plan/recipe/manifest coverage와 ID 일치
- 6개 이미지 hash와 색 공간 일치
- UVMap 보존 또는 Smart UV 생성
- Principled image/normal/bump/emission 연결 정상
- 동일 seed 재생성 결과 hash 동일

## Gate 3 — Blender 재질 검사·swatch·베이크

```powershell
uv run cbm inspect-materials geometry_showcase
uv run cbm render-material-swatches geometry_showcase --size 256
uv run cbm bake-materials geometry_showcase --profile gltf_pbr `
  --resolution 128 --material-id mat.blue
```

완료 조건:

- node/output/image 오류 0
- image color space와 파일 hash 일치
- sphere/plane swatch hash 생성
- Cycles 5채널 베이크 complete
- 모든 bake output 64자리 SHA-256 일치
- source `.blend`의 shader graph를 저장 변경하지 않음
- recipe/manifest/texture/geometry 변경 후 rebuild 없는 stale bake 거부
- BakeManifest의 source blend/build/material fingerprint 재검증

UV 경고는 객체별로 보고하며 성공으로 숨기지 않습니다. 다중 객체 atlas와 profile packing은 검사 범위가 아닙니다.

## Gate 4 — Fixed-camera 7패스

```powershell
uv run cbm analyze-reference geometry_showcase
uv run cbm visual-qa geometry_showcase
```

완료 조건: beauty, silhouette, object ID, material ID, normal, depth, wireframe의 동일 해상도·hash·camera fingerprint·SceneSpec hash·build fingerprint 생성. 정확히 7개가 아니면 manifest를 거부하며, SceneSpec 변경 후 rebuild를 생략한 stale QA도 거부합니다. 실제 Blender 카메라 값은 SceneSpec 카메라와 일치해야 합니다.

## Gate 5 — Direct QA와 advisory target

완료 조건:

- reference/preview/mask/pass/SceneSpec hash 재검증
- silhouette IoU와 bbox 오차 계산
- observed semantic ID별 오차 기록
- `qa/runs/<run-id>` immutable snapshot
- 생성 target 없이 정상 완료
- 생성 target을 사용해도 direct score/candidate 수 불변
- target의 실제 prompt와 provider/model/version/seed/output provenance 기록
- generated-target-only finding은 suggestion 없음, confidence 0.35 이하

## Gate 6 — 승인형 수정과 복구

단위·통합 fixture에서 다음을 검사합니다.

1. 직접 근거가 있는 제한된 transform 후보만 생성
2. 모든 실행 가능 후보가 `approval_required`
3. compile은 승인 파일을 만들지 않음
4. 정확한 후보 ID와 exact hash만 사용자 승인
5. 승인 1회 소비 후 재사용 거부
6. locked ID와 camera 변경 거부
7. 개선 시 accept
8. canonical 교체 이후 보고서 쓰기·검증 예외도 SceneSpec 복구와 재빌드
9. stable constraint ID별 status와 residual/tolerance 악화 시 rollback
10. 입력 이미지 hash 불변

실제 사용자 자산에는 후보를 자동 승인하지 않습니다.

## Gate 7 — stdio MCP

```powershell
uv run python scripts/run_v06_mcp_regressions.py
```

완료 조건: preset 조회, PBR 생성/연결, material validate, Blender build, Cycles bake, material inspect/swatch, direct QA가 실제 stdio MCP 경로에서 종료됩니다. Blender 자식 프로세스는 MCP stdin을 상속하지 않습니다.

## Gate 8 — 사람용 PDF 보고서

1. `material`, `qa`, `full` scope PDF 생성
2. PDF 파일과 sidecar manifest 생성 확인
3. PDF SHA-256과 manifest 기록 일치
4. 모든 source path가 job-relative이며 절대 경로가 노출되지 않음
5. source fingerprint가 같은 입력에서 결정론적으로 유지됨
6. PDF 생성 전후 canonical JSON과 입력 이미지 SHA-256 불변
7. 선택한 QA run ID와 실제 보고서 내용 일치
8. 선택적 자료가 없을 때 허위 성공 대신 unavailable/warning 표시
9. 한국어 텍스트, 표, swatch, QA 이미지의 페이지 잘림 여부를 렌더링으로 검사

## 전체 실행

```powershell
.\scripts\run_v06_gates.ps1
```

V0.6 smoke는 `reports/v06_smoke/workspaces`를 사용하므로 사용자의 canonical workspace를 재질 테스트용으로 변경하지 않습니다.
