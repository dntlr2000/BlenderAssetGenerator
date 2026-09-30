# V0.7.3 로컬 통합 검증 기록

> 이 문서의 `reports/v07_smoke/` 경로는 당시 로컬 실행 위치이며 배포 저장소의 영구
> 의존성이 아니다. 최신 compact V0.7 snapshot은 `verification/evidence/v07_20260811/`에
> 있다.

검증일: 2026-07-20  
프로젝트: `0.7.3`  
Portable contract: `0.7.0`

## 검증 환경

- Windows / PowerShell
- Blender `5.0.1`
- Blender Python `3.11.13`
- Host Python `3.14.6`
- EEVEE enum: `BLENDER_EEVEE`
- Color management: `AgX - Medium High Contrast`

Host와 Blender의 Python ABI가 다르므로 Blender 프로세스에 host Pydantic binary를 주입하지 않습니다. SceneSpec과 InteriorScope는 CLI/MCP host에서 검증하고, Blender의 provenance 수집 경로는 표준 라이브러리 기반 runtime 계약만 사용하도록 분리했습니다.

## 자동 검증 결과

```text
pytest: 330 passed
Ruff: All checks passed
doctor: Repository / Workspace / Blender / Codex OK
Blender compatibility probe: GLB / FBX / OBJ smoke export passed
```

전체 격리 게이트:

```text
reports/v07_smoke/20260720T073540378Z-7700/
```

이 gate는 새 `CBM_WORKSPACE_ROOT`와 `geometry_showcase`만 사용했습니다. `first_reference_test`와 기존 사용자 workspace는 읽거나 수정하지 않았습니다.

## V0.7.3 비용·배칭 결과

| Profile run | LOD0 objects | Draw-call proxy | LOD0 triangles | Batches | 결과 |
|---|---:|---:|---:|---:|---|
| `v07-gltf-smoke-run` | 16 → 12 | 16 → 12 | 6512 → 6512 | 3 | passed |
| `v07-fbx-smoke-run` | 16 → 12 | 16 → 12 | 6512 → 6512 | 3 | passed |
| `v07-obj-smoke-run` | 16 → 12 | 16 → 12 | 6512 → 6512 | 1 | passed |

반복 기둥 `demo.instance_post`만 동일 semantic ID, material ID, LOD와 UV signature 안에서 배칭됐습니다. GLB/FBX는 LOD0/1/2 세 배치, LOD가 없는 OBJ profile은 LOD0 한 배치입니다. LOD0 object와 material-slot/draw-call proxy는 25% 줄었고 triangle은 보존됐습니다.

세 cost report 모두 다음을 기록했습니다.

```text
ok: true
canonical_unchanged: true
exact repeated-mesh groups: 1
AABB overlap candidates after optimization: 5
unverified: internal_face_classification, runtime_draw_calls,
            destination_engine_instancing
```

AABB finding은 실제 face 교차 증명이 아니므로 자동 삭제하지 않았습니다. 반복 mesh도 목적 엔진 adapter가 정해지기 전에는 instancing 후보로만 기록했습니다.

## Package와 round trip

- `portable_gltf`: immutable GLB package와 clean import passed
- `fbx_interchange`: immutable FBX package와 clean import passed
- `obj_legacy`: immutable OBJ package와 clean import passed; format 고유 semantic/custom-property 손실은 warning으로 유지
- 세 package 모두 `metadata/asset_cost_report.json` snapshot 포함
- absolute path 0, missing dependency 0
- imported bounds tolerance 통과
- raw PBR channel 보존 및 profile별 derived packing 통과

Export PDF:

```text
reports/v07_smoke/20260720T073540378Z-7700/output/pdf/
  geometry_showcase/export_report.pdf
  geometry_showcase/export_report.manifest.json
```

PDF manifest는 package 안의 `asset_cost_report.json` hash를 source evidence로 포함합니다. PDF는 derived presentation artifact이며 JSON 판정을 대체하지 않습니다.

## 남은 한계

- Draw-call 수는 material-slot proxy이며 실제 Unity, Unreal 또는 다른 runtime 측정값이 아닙니다.
- Internal/coplanar hidden face와 정확한 mesh intersection 제거는 아직 구현하지 않았습니다.
- Repeated mesh instancing은 목적 엔진 adapter가 선택된 뒤 검증해야 합니다.
- AABB overlap 후보 5건은 broad-phase 보고이며 오류로 단정하지 않습니다.
- 넓은 환경의 실제 공간 컬링 효율은 검증하지 않았습니다. 분산 자산에는 `by_spatial_cell`을 우선 검토하고 목적 엔진 adapter에서 측정해야 합니다.
- V0.7.3은 static asset만 지원합니다. Rig, skin, animation, prefab/actor와 runtime shader는 범위 밖입니다.

## 판정

V0.7.3의 engine-neutral derived cleanup, semantic-safe batching, static cost report, budget 계약, package 포함, PDF projection과 Blender 5.0.1 통합 경로는 로컬 검증을 통과했습니다.
