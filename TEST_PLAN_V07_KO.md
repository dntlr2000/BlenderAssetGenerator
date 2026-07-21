# V0.7.3 통합 테스트 계획

## Gate 0 — Python, schema, public surface

```powershell
uv run pytest
uv run ruff check .
uv run cbm --help
uv run cbm doctor
```

완료 조건:

- 전체 unit/schema test와 Ruff 통과
- 프로젝트 `0.7.3`, SceneSpec `0.2.0`, InteriorScope `0.1.0`, material `0.5.0`, QA `0.6.0`, portable asset `0.7.0` 공개
- V0.7 CLI/MCP whitelist와 실제 handler 일치
- `portable_asset_core=true` 구성 로딩

### Gate 0.1 — Optional InteriorScope safety

```powershell
uv run pytest tests/test_v072_interior_scope.py
uv run cbm interior-scope-status <exterior-job-id>
```

완료 조건:

- scope가 없는 legacy/exterior job은 파일 생성 없이 `default_disabled`이고 exterior SceneSpec을 계속 로드
- scope 없이 interior ID/tag가 있거나 enabled scope가 draft/stale이면 SceneSpec 로드와 빌드 전에 거부
- 현재 scope SHA-256에 결합된 사용자 approval과 허용 prefix·level·space 안의 정적 interior object만 통과
- excluded prefix, 미승인 level/space, furnishing 위반, visible-only inferred evidence와 measured-mode mismatch를 거부
- facade backing, door reveal, recess와 exterior wall thickness를 interior로 오분류하지 않음
- scope/approval 변경이 build provenance를 변경하고 canonical SceneSpec·geometry를 직접 수정하지 않음

## Gate 1 — Blender 5 compatibility

```powershell
uv run cbm blender-compat
```

완료 조건: Blender 5.0.1, EEVEE enum, color management, Python exception propagation, stdio isolation, GLB/FBX/OBJ smoke exporter가 실제 runtime에서 통과합니다.

## Gate 2 — 격리된 V0.5/V0.6 회귀

매 실행 새로 만든 `CBM_WORKSPACE_ROOT`에 `geometry_showcase`를 import합니다. 사용자 workspace의 job은 읽거나 수정하지 않습니다.

```powershell
uv run cbm import-example geometry_showcase
uv run cbm material-scaffold geometry_showcase
uv run cbm generate-procedural-textures geometry_showcase mat.blue `
  --preset rock --resolution 128 --seed 707 --uv-set UVMap --overwrite
uv run cbm validate-material-contracts geometry_showcase
uv run cbm build geometry_showcase
uv run cbm render geometry_showcase
uv run cbm inspect geometry_showcase
uv run cbm validate geometry_showcase
uv run cbm bake-materials geometry_showcase `
  --profile gltf_pbr --resolution 128 --material-id mat.blue
```

완료 조건: canonical build fingerprint가 current material/texture inputs와 일치하고 V0.5 bake가 complete입니다. 이 gate는 Visual QA revision을 실행하지 않습니다.

## Gate 3 — AssetProfile과 preflight

```powershell
uv run cbm asset-profile-init geometry_showcase `
  --profile portable_gltf --asset-kind static_environment
uv run cbm asset-preflight geometry_showcase `
  --profile portable_gltf --run-id v07-gltf-smoke-run
```

완료 조건:

- AssetProfile schema/version/profile-format binding 통과
- current source/blend/build fingerprint 고정
- semantic mesh family별 topology/bounds/triangle evidence 생성
- canonical SceneSpec, source blend, material contracts, texture channels hash 불변
- failed preflight가 있으면 다음 gate를 명시적으로 중단

## Gate 4 — Derived optimization

```powershell
uv run cbm asset-plan geometry_showcase `
  --profile portable_gltf --run-id v07-gltf-smoke-run
uv run cbm asset-plan-approve geometry_showcase `
  --run-id v07-gltf-smoke-run `
  --plan-sha256 <optimization-review-plan-sha256> `
  --approval-note "격리 V0.7.4 gate 계획 승인"
uv run cbm asset-optimize geometry_showcase `
  --profile portable_gltf --run-id v07-gltf-smoke-run `
  --approved-plan-sha256 <optimization-review-plan-sha256>
```

완료 조건:

- complete OptimizationPlan
- source/profile hash가 preflight와 일치
- run-owned optimized `.blend` 생성
- LOD, collision, UV, static asset cost report schema 통과
- 신규 profile의 semantic/material/LOD/UV-safe batching과 legacy profile의 `mode=none` fallback 확인
- batching 전후 total triangle 동일, source instance별 LOD ceiling 유지
- loose geometry·duplicate material slot·exact duplicate collider만 허용된 cleanup으로 기록
- repeated mesh와 AABB overlap은 advisory로 남고 internal/coplanar face 자동 삭제 없음
- before/after object, material-slot, draw-call proxy, triangle, collider 지표와 budget 판정 일관성
- warning budget은 보고서에 유지되고 fail budget은 derived run 실패
- 측정하지 않은 LOD silhouette와 UV overlap/texel density는 `partially_verified`로 표시되고 통과값을 만들지 않음
- stable semantic/material identity 보존
- canonical authoring files hash 불변
- 원본과 derived output path가 겹치지 않음

## Gate 5 — Portable material conversion, preservation과 packing

```powershell
uv run cbm asset-material-convert geometry_showcase `
  --profile portable_gltf `
  --run-id v07-gltf-smoke-run `
  --conversion-id v071-gltf-materials `
  --resolution 128 `
  --margin-px 8
```

완료 조건:

- canonical SceneSpec, source `.blend`, MaterialPlan, ShaderRecipe, source TextureManifest hash 불변
- conversion이 exact source/profile/run fingerprint와 optimized scene hash에 결합
- object/generated/triplanar authoring mapping이 run-owned shared atlas로 변환
- material별 atlas/output provenance와 Blender runtime 기록
- V0.5 raw bake channel byte/hash 보존
- Base Color/Emission은 sRGB, data channel은 Non-Color
- glTF ORM은 `R=occlusion`, `G=roughness`, `B=metallic`
- 누락 ORM source는 명시적 default만 사용
- 같은 입력/해상도에서 packed PNG hash 결정론적
- low-level evidence와 canonical TexturePackManifest 역할이 분리됨

## Gate 6 — Atomic portable package

```powershell
uv run cbm asset-package geometry_showcase `
  --profile portable_gltf `
  --run-id v07-gltf-smoke-run `
  --material-conversion-id v071-gltf-materials `
  --package-id v07-gltf-smoke-package
```

완료 조건:

- GLB primary file과 package manifest 생성
- path는 모두 job-relative이며 traversal/absolute path 0
- missing dependency 0
- 모든 receipt의 byte size와 SHA-256 일치
- existing package ID overwrite 거부
- staging 실패 시 complete package로 승격되지 않음
- package 전후 canonical source hash 불변

## Gate 7 — Clean-import round trip

```powershell
uv run cbm asset-validate geometry_showcase `
  --profile portable_gltf `
  --package-id v07-gltf-smoke-package `
  --bounds-tolerance-m 0.0001
```

완료 조건:

- fresh Blender process import 성공
- primary package hash 재검증
- exporter 축·단위 선언과 imported bounds 검사; 파일 내부 축·단위 metadata를 직접 읽지 못한 형식은 `unverified` 경고 유지
- profile expectation에 맞는 semantic/material coverage
- UV/normal/tangent/texture/dependency finding 구조화
- summary count, status, `ok`가 개별 check와 일치
- validation ID/package ID/run ID 정확히 연결

동일한 격리 workspace에서 `fbx_interchange`와 `obj_legacy`도 각기 다른 run/package ID로 Gate 3~7을 반복합니다. Generic exporter smoke가 아니라 V0.7 profile → optimization → immutable package → clean import 전체 경로를 실제로 통과해야 합니다. OBJ의 custom semantic property 손실은 profile의 known loss로 평가하며 허위 보존으로 보고하지 않습니다.

## Gate 8 — PDF export scope

```powershell
uv run cbm report-pdf geometry_showcase `
  --scope export `
  --optimization-run-id v07-gltf-smoke-run `
  --package-id v07-gltf-smoke-package
```

완료 조건:

- PDF와 sidecar manifest 생성
- profile/preflight/optimization/LOD/collision/UV/texture/package/roundtrip 자료 표시
- cost/cleanup/batching/budget과 미검증 runtime/internal-face 항목 표시
- warning과 known loss를 pass로 오인하지 않음
- 모든 source path job-relative, source/PDF hash 일치
- PDF 생성 전후 canonical 및 package JSON hash 불변
- 대표 페이지 렌더에서 한국어, 표, 긴 ID/path 잘림 없음

## Gate 9 — Negative and compatibility cases

Unit/fixture에서 다음을 검사합니다.

1. stale source/build fingerprint 거부
2. profile/plan/package ID mismatch 거부
3. output traversal과 absolute path 거부
4. duplicate artifact/semantic/material ID 거부
5. failed preflight 이후 optimization 거부
6. missing texture dependency와 changed raw hash 거부
7. wrong ORM channel mapping 거부
8. immutable run/package overwrite 거부
9. invalid bounds tolerance 거부
10. OBJ known semantic loss를 허위 보존으로 보고하지 않음
11. missing/stale/mismatched material conversion ID 거부
12. conversion ID와 output overwrite 거부
13. missing/draft/stale InteriorScope approval과 승인 범위 밖 interior object 거부
14. scope가 없는 exterior-only legacy job과 facade helper의 회귀 없음

## 전체 격리 실행

```powershell
.\scripts\run_v07_gates.ps1
```

Linux/macOS:

```bash
./scripts/run_v07_gates.sh
```

스크립트는 timestamp/process별 새 `reports/v07_smoke/<run>/workspaces`를 사용하고 smoke output을 자동 삭제하지 않습니다. 실제 사용자 자산 검증은 별도 승인과 명시적 job ID로 수행합니다.

## V0.7 완료 판정

다음을 모두 만족해야 V0.7 local verified로 기록합니다.

```text
[ ] Python/schema/Ruff/public surface 통과
[ ] InteriorScope default-disabled, exact-hash approval과 scope boundary 음성 테스트 통과
[ ] Blender 5.0.1 compatibility 통과
[ ] isolated geometry/material/bake 회귀 통과
[ ] read-only preflight 통과
[ ] derived optimization manifests 통과
[ ] static cost report, safe batching, cleanup, budget gate 통과
[ ] raw PBR 보존과 profile packing 통과
[ ] immutable package 통과
[ ] GLB/FBX/OBJ profile별 immutable package와 clean-import round trip 통과
[ ] export PDF와 sidecar 검증 통과
[ ] canonical source hash 불변
```

Engine-specific import는 V0.7 완료 조건이 아닙니다. 대상 엔진이 정해진 뒤 별도 adapter와 실제 runtime 검증을 수행합니다.
