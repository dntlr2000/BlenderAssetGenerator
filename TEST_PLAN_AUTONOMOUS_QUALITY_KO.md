# Autonomous Quality Extension 0.1.0 테스트 계획

## 1. 목적과 판정 원칙

이 계획은 AQ `0.1.0`이 기존 프로젝트 `0.9.0`의 안전 경계를 약화하지 않으면서 실제로
동작하는지 검증한다. 코드나 schema 존재만으로 통과 처리하지 않는다.

- machine-readable JSON/receipt가 권위 원본이다.
- expected negative fixture는 의도한 hard failure가 관찰돼야 성공이다.
- unavailable evidence는 pass 또는 0점으로 바꾸지 않는다.
- Blender 실행이 필요한 항목은 Blender 5.0.1 실기동 증거 없이는 `unverified`다.
- 사용자 workspace, 기존 package, history, receipt를 gate 성공용으로 수정하지 않는다.
- reconstruction 품질 향상은 동일 reference/camera의 before/after 측정 없이는 주장하지 않는다.

## 2. 기준선

2026-08-10 구현 전 기준선:

- `uv run pytest`: `945 passed, 6 skipped`
- `uv run ruff check .`: 통과
- `uv run cbm doctor`: Repository/Workspace/Blender/Codex 모두 OK
- `uv run cbm blender-compat`: Blender `5.0.1`, EEVEE, GLB/FBX/OBJ smoke 통과

최종 post-change 전체 결과는 기준선과 별도로 기록한다. 기준선 통과를 새 구현 회귀 통과로
대체해서는 안 된다.

## 3. Gate matrix

### Gate A — strict contract와 Schema parity

- 모든 AQ contract가 `extra="forbid"`, non-finite rejection을 사용한다.
- SHA-256, immutable ID, producer/version, created_at, source fingerprint를 검증한다.
- absolute path, Windows path, `..`, symlink escape를 거부한다.
- checked-in Draft 2020-12 JSON Schema와 Pydantic schema가 동일하다.
- SceneSpec `0.2.0`은 그대로 유지되고 V03 `0.3.0`은 병렬이다.
- Reference/Integrated Quality/MaterialGraph/Structural/Assembly/Topology/Autonomy 버전이
  모두 `0.1.0`으로 분리된다.

대상:

```text
tests/test_autonomous_quality_schemas.py
tests/test_autonomous_structural_geometry.py
tests/test_reference_evidence_aq.py
tests/test_integrated_quality_aq.py
tests/test_material_graph_aq.py
tests/test_assembly_topology_aq.py
```

### Gate B — Reference Evidence

- Pillow-only 후보 생성 및 optional OpenCV fallback
- mask 후보 1~3개, 연속 rank, exact byte/hash/size binding
- bbox/area/edge/border/symmetry/shadow/reflection/confidence 범위
- perspective와 orthographic camera 가설 동시 보존
- ambiguity와 underconstrained 기록
- canonical camera 무변경
- interrupted staging quarantine와 완결 run atomic adoption
- tampered mask/summary/run_result 거부

### Gate C — Structural Geometry와 SceneSpec V03

- loft open/closed, unequal resampling, cap, winding, stable face ordering
- sweep straight/curved/closed, transported frame, scale/twist, zero-length rejection
- Boolean tree union/difference/intersection, acyclic/full tree, empty/non-manifold 처리
- multi-loop outer/hole, winding, containment, self-intersection 거부
- `linear_instance_v1` whitelist와 arbitrary GN graph 거부
- GeometryIntent index·policy validation
- deterministic mesh serialization
- explicit hash-bound `0.2 → 0.3` migration helper
- full V03 structural assignment을 candidate-owned recipe/mesh/receipt/`.blend`로 materialize
- materialized payload를 참조하는 path-backed V02 candidate compile과 canonical 무변경
- 기존 SceneSpec `0.2.0` regression

### Gate D — Blender structural materialization

Blender 5.0.1 격리 디렉터리에서 다음 다섯 kind를 실제 `.blend`와 mesh payload로 만든다.

- loft
- sweep
- multi_loop_extrude
- boolean_tree
- geometry_nodes_template / `linear_instance_v1`

현재 smoke는 materialization, non-empty mesh, stable semantic ID를 검증한다. 모든 형상에 대해
beauty render 또는 최종 production topology를 증명하는 것은 아니다.

### Gate E — Scale, shading, Assembly BVH, Topology/UV

- 같은 cube를 0.1m, 1m, 10m로 생성
- shortest-dimension 2% bevel이 0.002m, 0.02m, 0.2m인지 확인
- normalized dimensions/vertex hash와 evaluated topology 동일성
- flat/sharp/smoothing/bevel 정책 증거
- Blender BVH contact와 penetration fixture
- `game_ready_lowpoly` topology pass fixture
- UV overlap을 포함한 topology fail fixture
- 모든 topology profile 이름과 hard failure/warning 분리

대상:

```text
tests/test_autonomous_quality_blender_evidence.py
tests/test_autonomous_structural_geometry_blender.py
```

### Gate F — MaterialGraph와 material candidate round

- base channel과 ordered layers
- image/vertex/semantic/curvature/position mask
- sRGB/Non-Color channel 규칙과 physical scale
- normal/displacement, bake, neutral/reference lighting
- arbitrary node/Python, 근거 없는 전역 detail, localized repeat 거부
- workflow-owned material scaffold/authored candidate 분리
- exact completion, candidate 평가·ranking, policy promotion receipt
- 기본 최대 2회의 서로 독립된 material round와 예산/선행 candidate 재결속
- canonical MaterialPlan을 agent가 직접 덮어쓰지 않음
- 기존 V0.5 material validation 회귀

대상:

```text
tests/test_material_graph_aq.py
tests/test_autonomy_material_rounds_aq.py
기존 tests/test_v05_*.py 관련 회귀
```

### Gate G — Integrated Quality

- 기존 V0.6 `overall_direct_score` exact 보존
- reference/structural/material/production 네 축 독립성
- required evidence unavailable 시 `unscorable`
- hard gate 우선, blocking finding과 reentry
- threshold는 profile configurable이며 완성도 백분율이 아님
- provenance/profile/source를 status 조회 때 다시 hash
- report JSON/PDF/manifest atomic publish와 tamper 거부
- candidate ranking이 hard gate → regression → meaningful gain → Pareto → 최소 변경 순서

### Gate H — Root/Policy Authorization

- 최초 요청 exact text hash, primary reference, launch/binding 결속
- job/workflow/dispatch/profile/budget/scope/target/output exact binding
- changed profile/reference/target/source는 stale
- `authorization_source=preauthorized_profile`
- `decided_by=autonomy_policy_engine`
- exact gate target, +1 action accounting, single-use consumption, predecessor chain
- 최초 authorization persist 직후 reload/full validation과 file hash identity 재확인
- InteriorScope, destination import, budget 확대, network, arbitrary code 거부
- 기존 user approval artifact 위조 없음
- `autonomous_static_prop_v1`만 registry active, 향후 프로필은 disabled

### Gate I — 후보, budget, cycle, promotion

- initial 후보 최대 3, controller-only outputs, adviser write 금지
- candidate completion과 evaluation exact input/output binding
- build/inspect/validate/low-resolution QA
- hard-gate/비회귀/meaningful-gain에 따른 best-known 선택
- archive + atomic canonical promotion + receipt
- canonical conflict, candidate tamper, stale completion fail-closed
- default/hard budget과 global action cap
- duplicate, A-B-A, A-B-C-B, 반복 change direction, plateau
- non-improvement/regression 미승격 또는 rollback
- cycle/plateau/repeated failure/budget 종료 시 best-known review routing, pass 위조 금지

### Gate J — lock, interruption, retry

- 같은 host의 expired lock이라도 owner PID가 죽었다는 증거가 있을 때만 복구
- live/unknown/remote owner와 legacy 불명확 lock 탈취 거부
- transition/reference/candidate staging 복구 또는 quarantine
- terminal intent와 final terminal의 재구성
- canonical write 전 timeout/process interruption만 동일 input 최대 1회 retry
- schema/validation/topology/deterministic Blender 오류 non-retry
- 같은 failure fingerprint 반복 시 terminal
- host attempt intent/failure/terminal receipt chain 검증

대상:

```text
tests/test_autonomy_worker.py
tests/test_autonomy_failure_recovery_aq.py
tests/test_autonomy_authorization_hardening.py
```

### Gate K — review bundle

- quality non-pass, unscorable 또는 bounded termination에서만 bundle 생성 가능
- passing pre-production IQ나 package failure alone을 review evidence로 오용하지 않음
- best blend, preview GLB, render, IQ, finding, history, comparison, manual action 포함
- JSON manifest/receipt와 PDF/sidecar hash 결속
- 기존 bundle overwrite 및 extra/unbound file 거부
- `production_ready=false`
- `destination_handoff_eligible=false`
- canonical authoring data 불변

### Gate K2 — terminal verifier와 package repair

- terminal intent, terminal state와 마지막 transition receipt exact binding
- final IQ JSON/manifest/PDF/profile/provenance 재검증
- `quality_passed`에서 package manifest와 passed roundtrip의 nested dependency 재검증
- `review_required`에서 review manifest/receipt/PDF sidecar와 non-production flag 재검증
- package terminal과 review terminal의 상호 배타성
- `portable.package`와 `portable.roundtrip` 실패만 repair 분류 대상으로 허용
- 기존 immutable package ID 충돌과 format-only roundtrip failure만 fresh ID로 복구
- repair failure/plan/attempt/receipt와 정확한 budget transition
- 새 clean-import roundtrip이 통과한 repair만 package acceptance 허용
- material/bounds/dependency/Blender/unknown failure와 canonical source 변경 fail-closed
- Windows 장경로 package/handoff generation과 V0.9 postflight의 동일 재귀 file-set digest
- 정상 directory hash parity와 누락·추가·escape·tamper 거부

대상:

```text
tests/test_autonomy_terminal_verifier_aq.py
tests/test_autonomy_production_budget_aq.py
tests/test_packaging_long_paths_aq.py
```

### Gate L — package success path

- final IQ accepted
- exact V0.7 optimization plan을 별도 PolicyAuthorization으로 소비
- derived optimization이 canonical authoring data를 변경하지 않음
- `portable_gltf` package와 raw PBR channel
- relative dependency와 file hashes
- fresh Blender clean-import roundtrip
- bounds, semantic/material identity와 dependency pass
- 요청한 경우 package-bound destination handoff envelope
- 목적지 프로젝트 write 없음

이 Gate는 후보 promotion smoke만으로 대체할 수 없다. 완전한 terminal package 경로의 Blender
실행과 evidence가 있어야 통과다.

### Gate M — 공개 CLI/MCP와 legacy 회귀

- 10개 AQ CLI 명령과 동등 MCP allowlist
- 별도 SceneSpec V03 plan/apply CLI와 동등 MCP가 derived copy만 만들고 canonical은 무변경
- `autonomy-advance` action 하나
- `autonomy-run/resume` bounded action cap
- status read-only, cancel evidence-preserving
- `standard`, `background_exterior`, InteriorScope, manual V0.6, bounded convergence, V0.7,
  V0.9 audit/handoff 동작 불변
- legacy V0.4~V0.9 JSON과 job 로딩

대상:

```text
tests/test_autonomous_quality_public_surface.py
tests/test_scene_spec_v03_migration_public.py
```

## 4. deterministic benchmark

`examples/autonomous_quality_benchmarks/manifest.json`은 외부 저작권 자산 없이 8개 case를
검사한다.

| case | host 검증 | Blender opt-in |
|---|---|---|
| simple_box | 기존 primitive 치수 | 없음 |
| tapered_loft | deterministic mesh | 있음 |
| curved_sweep | deterministic mesh | 있음 |
| boolean_panel | declarative tree | 있음 |
| small_assembly | bounded semantic contact | 없음 |
| height_grid_terrain | grid contract/count | 없음 |
| clean_material_graph | portable graph contract | 없음 |
| topology_uv_failure | UV0 hard failure 유지 | 없음 |

이 benchmark는 contract와 host math/materialization benchmark다. reference reconstruction의
before/after 유사도, 완성형 topology, 엔진 runtime parity를 측정하지 않는다.

## 5. 실행 명령

PowerShell 통합 gate:

```powershell
.\scripts\run_autonomous_quality_gates.ps1
```

전체 pytest를 생략한 개발용 focused gate:

```powershell
.\scripts\run_autonomous_quality_gates.ps1 -SkipFullRegression
```

구조 builder, scale/assembly/topology companion, initial candidate, package-success terminal과
review-only terminal Blender opt-in 포함:

```powershell
.\scripts\run_autonomous_quality_gates.ps1 -RunBlender
```

개별 scale/BVH/topology Blender companion만 다시 실행하려면 다음 opt-in을 사용할 수 있다.

```powershell
$env:CBM_RUN_AUTONOMOUS_QUALITY_BLENDER_SMOKE = "1"
uv run pytest -q tests/test_autonomous_quality_blender_evidence.py
```

Linux/macOS shell script는 개발 호환 표면으로 존재하지만 현재 프로젝트 공식 실기동 범위는
Windows 11/Blender 5.0.1이다.

```bash
./scripts/run_autonomous_quality_gates.sh --run-blender
```

명시적 개별 검사:

```powershell
uv run python scripts/generate_schemas.py
uv run pytest -q tests/test_autonomous_quality_schemas.py
uv run ruff check .
uv run pytest
uv run cbm doctor
uv run cbm blender-compat
uv run python -m codex_blender_modeler.autonomy_benchmarks `
  --manifest examples/autonomous_quality_benchmarks/manifest.json `
  --output <EMPTY_OUTPUT_DIR>/autonomous_quality_benchmark.json `
  --run-blender
git diff --check
```

benchmark output은 기존 파일을 덮어쓰지 않으므로 매번 비어 있는 새 경로를 사용한다.

## 6. 완료 기준

AQ를 전체 검증 완료로 표시하려면 다음이 모두 필요하다.

1. schema parity와 focused unit/host tests 통과
2. Blender 5 structural/scale/assembly/topology smoke 통과
3. isolated initial candidate build/evaluate/policy promotion 통과
4. quality-pass → V0.7 portable GLB → clean-import → terminal 통과
5. quality non-pass → review bundle terminal 통과
6. interrupted resume와 transient-only retry의 unit/host receipt 회귀 통과
7. 기존 V0.7/V0.8/V0.9 gates 통과
8. post-change 전체 pytest와 Ruff 통과
9. doctor/blender-compat 재확인
10. benchmark JSON 보존 및 한계 명시

현재 실제 결과와 미검증 항목은 `VERIFICATION_AUTONOMOUS_QUALITY_KO.md`에만 기록한다.

2026-08-10 Windows 11/Python 3.14.6/Blender 5.0.1 최종 기록:

```text
POST_CHANGE_PYTEST_RESULT=1145 passed, 20 skipped, 8 warnings in 149.21s; 1165 collected
POST_CHANGE_PYTEST_EVIDENCE=verification/evidence/aq_v1_20260810/README.md
POST_CHANGE_RUFF_RESULT=All checks passed
POST_CHANGE_DOCTOR_RESULT=Repository/Workspace/Blender/Codex OK
POST_CHANGE_BLENDER_COMPAT=Blender 5.0.1, Python 3.11.13, EEVEE, GLB/FBX/OBJ passed
POST_CHANGE_AQ_FOCUSED_GATE=195 passed, 2 skipped, 8 warnings in 16.98s; portable execution record above
POST_CHANGE_AQ_BLENDER_GATE=14 passed, 6 warnings in 352.03s; portable terminal snapshots above
POST_CHANGE_AQ_BENCHMARK=8/8 passed; Blender structural 3 cases
POST_CHANGE_V07_V08_V09_REGRESSION=passed in chained AQ gate
POST_CHANGE_AQ_GATE=exit 0; verification/evidence/aq_v1_20260810/
```

이 수치는 arbitrary reference reconstruction의 before/after 품질 향상을 뜻하지 않는다.
exact evidence path와 hash는 `VERIFICATION_AUTONOMOUS_QUALITY_KO.md`를 따른다.
full Blender fault-injection interruption/resume E2E는 별도 미검증으로 유지한다.
