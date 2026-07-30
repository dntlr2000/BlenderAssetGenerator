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

## Gate 6A — 선택적 bounded standard convergence

사용자 job이 아닌 isolated temporary workspace에서 다음을 검사합니다.

1. current direct QA report/candidates/SceneSpec으로 plan을 만들고 planning 전후 canonical hash가 동일함
2. exact plan SHA-256 승인 전 `run` 거부
3. 기본 3회, hard maximum 5회와 group/candidate/changed-ID budget 검증
4. allowed/locked semantic ID, path family, operation, absolute/relative delta와 minimum confidence 검증
5. generated-target-only, manual-required, custom-mesh geometry, camera, material과 plan 밖 후보 거부
6. selected candidate bundle, compiled RevisionPlan과 host-policy authorization exact hash 결속
7. accepted iteration은 minimum direct-score gain, silhouette IoU 비회귀와 stable-ID constraint 비회귀를 모두 만족
8. score 비개선, IoU 악화와 constraint regression은 baseline restore/rebuild 후 terminal rollback
9. iteration directory가 `001..N`으로 연속이고 receipt previous-hash chain이 정확함
10. result SceneSpec snapshot, source/result QA report와 candidates, selection, plan, authorization hash 보존
11. target, plateau, no candidate, manual review, budget, cancel, stale/tampered와 host failure 종료 상태
12. terminal `convergence_report.json`, PDF와 sidecar가 exact iteration evidence에 결속
13. manual one-shot apply, convergence와 V0.8 workflow가 같은 job write lock에서 경쟁하면 승인 소비 전에 fail-closed
14. active session의 input/SceneSpec/QA/candidate drift는 차단하고 completed session은 후속 canonical 작업 때문에 소급 stale 처리하지 않음
15. legacy one-shot revision과 `background_exterior`의 exact-one-QA/no-auto-revision 회귀 통과
16. 신규 실행 binding이 없는 legacy partial plan은 status/audit만 허용하고 approve/run은 fail-closed
17. initial SceneSpec, candidates, build provenance/fingerprint와 optional constraint snapshot 변조 차단
18. 연속 iteration 사이 source/result QA, candidate bundle과 build fingerprint splice 차단
19. source→result build에서 승인된 SceneSpec hash 외 geometry/material/shader/texture/camera 계약 변경 차단
20. exact before/after constraint snapshot으로 regression count와 acceptance를 재계산하고 receipt 숫자 위조 차단
21. terminal JSON 삭제 뒤 남은 cancellation receipt, final snapshot 또는 PDF evidence가 재실행을 차단
22. 취소 receipt가 exact plan, approval, canonical SceneSpec과 current QA/build에 결속됨
23. 실내 semantic object는 승인된 InteriorScope가 있더라도 자동 convergence 대상에서 제외
24. plan 파일 편집으로 material/custom-mesh/locked-ID 또는 host delta 정책을 완화할 수 없음
25. 한 번의 host/MCP 호출은 bounded iteration 하나만 처리하고 다음 호출에서 안전하게 재개
26. 중단된 미완료 staging은 completed receipt와 구분해 복구하며 immutable completed evidence는 덮어쓰지 않음
27. 비어 있거나 누락된 `initial_input_hashes`는 legacy status-only로 분류하고 `execution_eligible=false`, 누락 binding과 차단 사유를 보고하며 approve/run을 거부
28. strict `visual_convergence_host_safety_envelope.schema.json` 검증, plan·approval의 exact envelope SHA-256 결속, unknown field와 변조·권한 확대 차단
29. CLI의 repeatable `--path-limit-json`과 MCP의 `path_limits`가 host envelope를 좁히는 요청만 허용하고 경로·연산·delta 권한 확대는 거부
30. receipt 없는 staging이 있으면 `next_action=invoke_run_to_recover`를 보고하고 복구 전 취소·terminalization을 거부하며, terminal과 staging의 동시 존재를 integrity failure로 판정

이 gate는 global `qa.revision_mode` 또는 `automatic_revision`을 변경하지 않습니다.
한 exact plan 승인은 해당 세션의 iteration만 허용하며 InteriorScope, V0.7,
Destination Handoff 권한을 만들지 않습니다.

## Gate 7 — stdio MCP

```powershell
uv run python scripts/run_v06_mcp_regressions.py
```

완료 조건: preset 조회, PBR 생성/연결, material validate, Blender build, Cycles bake, material inspect/swatch, direct QA가 실제 stdio MCP 경로에서 종료됩니다. `plan_visual_convergence`, `approve_visual_convergence`, `run_visual_convergence`, `get_visual_convergence_status`, `cancel_visual_convergence`가 allowlist에 존재하고 exact-plan 경계를 보존해야 합니다. Blender 자식 프로세스는 MCP stdin을 상속하지 않습니다.

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
10. bounded convergence PDF가 terminal JSON, exact plan/approval, 모든 iteration support artifact와 final QA hash에 결속
11. convergence PDF 누락 재생성은 source integrity가 모두 current일 때만 허용

## Gate 9 — 선택적 실내 다각도 QA

승인된 InteriorScope를 가진 격리 fixture에서 다음을 검사합니다.

1. scope가 없거나 disabled/draft/stale이면 계획 생성 전 fail-closed
2. interior semantic object가 없으면 외관 객체를 대신 선택하지 않고 거부
3. `minimal`, `standard`, `thorough` camera 방향 수와 64-view 상한
4. source inventory, plan, approval, render manifest, report, candidates와 latest strict schema
5. exact plan SHA-256과 선택 view 부분집합 승인만 허용
6. 승인 single-use와 stale SceneSpec/scope/build binding 거부
7. 승인된 각 view의 정확한 seven-pass set과 immutable hashes
8. temporary camera/isolation 뒤 authoring `.blend`와 canonical hash 불변
9. semantic visibility를 완성도나 reference score로 보고하지 않음
10. 매핑된 interior reference가 없으면 comparison `unavailable`
11. revision candidate가 모두 manual-only
12. beauty/object-ID/wireframe contact sheet와 QA PDF/sidecar 생성
13. V0.8 `interior_visual_qa` specialized approval gate
14. V0.9 read-only audit의 strict contract/hash/latest 검사

## 전체 실행

```powershell
.\scripts\run_v06_gates.ps1
```

V0.6 smoke는 `reports/v06_smoke/workspaces`를 사용하므로 사용자의 canonical workspace를 재질 테스트용으로 변경하지 않습니다.
