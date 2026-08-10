# Autonomous Quality Extension 0.1.0 아키텍처

## 1. 상태와 범위

Autonomous Quality Extension(AQ)은 프로젝트 `0.9.0` 위에 병렬로 추가된 실험 계층이다.
프로젝트 버전과 기존 V0.4~V0.9 공개 계약 버전을 바꾸지 않으며, 이 기능만으로 저장소를
V1.0이라고 부르지 않는다.

| 계약 | 버전 | 관계 |
|---|---:|---|
| Project | `0.9.0` | 유지 |
| SceneSpec | `0.2.0` | 기존 canonical 계약 및 legacy/path-backed AQ build 입력 |
| SceneSpec V03 | `0.3.0` | 구조 형상용 병렬 opt-in 계약 |
| Reference Evidence | `0.1.0` | V0.4 companion evidence |
| Integrated Quality | `0.1.0` | V0.6/V0.7 companion quality evidence |
| MaterialGraphSpec | `0.1.0` | V0.5 companion material graph 계약 |
| Structural Geometry | `0.1.0` | SceneSpec V03 형상·의도 materializer 계약 |
| Assembly/Topology companion | `0.1.0` | 기존 검사에 추가되는 좁은 범위 증거 |
| Autonomy | `0.1.0` | standard production/controller 위의 supervisor |

코드 registry에서 `autonomous_static_prop_v1`만 `verified_active`이며 나머지 세 프로필은
`disabled_experimental`이다. 2026-08-10 Windows 11/Blender 5.0.1 검증으로 이 한 profile의
bounded package/review 경로는 통과했지만, registry 상태와 저장소 전체 출시 검증은 별개다.
exact 환경·경로·hash와 미검증 범위는 `VERIFICATION_AUTONOMOUS_QUALITY_KO.md`를 기준으로
판단한다.

## 2. 기존 파이프라인과의 관계

AQ는 세 번째 독립 모델링 파이프라인이 아니다. 새 작업을 만들 때 기존 V0.9 production
dispatch를 생성하고, 그 아래 실행 정책을 항상 `standard`로 고정한 뒤 자율 supervisor를
덧씌운다.

```text
최초 사용자 요청 + primary reference + target_subject
  → standard V0.8 workflow / V0.9 production dispatch
  → RootAuthorization + immutable profile/budget
  → Reference Evidence
  → workflow-owned initial/structural/parametric candidates
  → controller-only policy promotion
  → 기존 standard V0.4~V0.7 단계
  → Integrated Quality
     ├─ accepted  → V0.7 portable_gltf + clean-import → 선택적 handoff envelope
     └─ non-pass → review-only bundle
```

- 기존 `standard`와 `background_exterior`의 승인, retry, package 의미를 변경하지 않는다.
- AQ 세션은 `primary_object_only`, 명시적 `target_subject`, `concept`, 정적 소품만 허용한다.
- 기존 WorkflowApproval, InteriorScopeApproval, V0.6 revision approval, V0.7
  OptimizationApproval, Destination Handoff approval을 사용자 승인인 것처럼 합성하지 않는다.
- AQ의 `PolicyAuthorization`은 현재 profile이 허용한 routine gate에 대한 기계 결정이다.

## 3. 주요 모듈

```text
src/codex_blender_modeler/
├─ reference_evidence/       # 마스크 후보, 카메라 가설, immutable run
├─ structural_geometry/      # SceneSpec V03, mesh math, scale context, migration helper
├─ material_graph/           # whitelist-only MaterialGraphSpec
├─ integrated_quality/       # 4축 품질, hard gate, Pareto/lexicographic ranking
├─ autonomy/                 # profile, authorization, budget, candidates, worker, reporting
├─ autonomy_benchmarks/      # deterministic host/선택적 Blender benchmark runner
└─ blender_scripts/
   ├─ builders/              # loft/sweep/boolean/multi-loop/GN materializer
   ├─ assembly/              # broad/narrow/semantic companion evidence
   └─ topology/              # profile별 hard failure/warning 평가
```

공개 진입점은 `cli.py`, `mcp_server.py`와 프로젝트 MCP allowlist에 추가되었다. 임의
Python, 임의 Blender 스크립트, 임의 node graph 실행 표면은 추가하지 않았다.

## 4. 실제 증거 구조

작업별 핵심 경로는 다음과 같다.

```text
workspaces/<job-id>/
├─ reference_evidence/runs/<run-id>/
│  ├─ masks/
│  ├─ reference_evidence.json
│  ├─ camera_hypothesis_set.json
│  ├─ reference_evidence_summary.md
│  └─ run_result.json
├─ reports/integrated_quality/
│  ├─ profiles/<run-id>.json
│  ├─ runs/<run-id>/
│  │  ├─ integrated_quality_report.json
│  │  ├─ integrated_quality_report.pdf
│  │  └─ integrated_quality_report.manifest.json
│  └─ latest.json                       # 편의 포인터일 뿐 권위 원본 아님
├─ production/autonomy/<session-id>/
│  ├─ quality_gate_profile.json
│  ├─ budget.json
│  ├─ profile.json
│  ├─ root_authorization.json
│  ├─ plan.json
│  ├─ controller_binding.json           # desktop_in_session이면 계획 시 생성
│  ├─ candidates/<candidate-id>/
│  ├─ mr/                               # immutable material round evidence
│  ├─ policy_authorizations/
│  ├─ promotions/
│  ├─ host_attempts/
│  ├─ transitions/<sequence>/
│  ├─ integrated_quality/<stage>/
│  ├─ state.json                        # 재구성 가능한 mutable projection
│  ├─ terminal_intent.json
│  └─ terminal.json
└─ exports/review_bundles/<bundle-id>/
   ├─ best_candidate.blend
   ├─ preview.glb
   ├─ renders/
   ├─ integrated_quality_report.json
   ├─ unresolved_findings.json
   ├─ iteration_history.json
   ├─ candidate_comparison.json
   ├─ next_manual_actions.md
   ├─ review_bundle_manifest.json
   ├─ review_bundle_receipt.json
   ├─ review_bundle_report.pdf
   └─ review_bundle_report.manifest.json
```

`state.json`, `latest.json`, PDF는 판단 원본이 아니다. exact artifact SHA-256, immutable
transition state, receipt, authorization, manifest가 권위 원본이다.

## 5. Reference Evidence와 카메라 가설

`reference_evidence`는 기존 `analysis/reference_analysis.json`과
`analysis/camera_solution.json`을 대체하지 않는 companion이다.

- Pillow 경로는 항상 사용 가능하다.
- OpenCV가 있으면 adaptive threshold, bounded GrabCut, line/vanishing cue를 추가한다.
- 전경 mask 후보는 최대 3개이며 bbox, area, edge agreement, border contact, symmetry,
  shadow/reflection likelihood와 confidence를 기록한다.
- 카메라는 perspective와 orthographic 가설을 함께 보존하고, focal/ortho 값, pose,
  가능한 intrinsic/distortion, 근거와 ambiguity를 기록한다.
- 선택된 값은 staging 가설이지 recovered truth가 아니다.
- 현재 `CameraHypothesisSet`은 `canonical_camera_mutated=false`,
  `canonical_promotion_allowed=false`로 발행된다. 실제 canonical camera 변경은 candidate
  평가와 별도 promotion 경계를 통과해야 한다.
- 끊긴 staging은 덮어쓰지 않고 `interrupted_staging`으로 보존하며, 완결된 run만 최종
  디렉터리로 원자적 채택한다.

외부 ML 또는 네트워크 provider는 core dependency가 아니다. optional advisory 결과는
provenance와 함께 기록되더라도 단독 승인 근거가 될 수 없다.

## 6. Geometry, scale, shading

SceneSpec V03은 기존 여섯 geometry kind에 다음 형상을 병렬 추가한다.

- `loft`: 서로 다른 section vertex 수의 결정론적 resampling, cap, correspondence/twist
- `sweep`: 2D profile, 3D path, transported frame, scale/twist track
- `boolean_tree`: `UNION`, `DIFFERENCE`, `INTERSECT`의 닫힌 선언형 tree
- `multi_loop_extrude`: outer loop, hole loop, depth, cap, side wall
- `geometry_nodes_template`: whitelist의 `linear_instance_v1`만 허용

`GeometryIntent`는 face group, sharp/crease edge, bevel weight, UV seam, smoothing,
topology/subdivision/LOD intent를 별도 표현한다. `AssetScaleContext`는 local/assembly bounds,
shortest dimension, projected pixel size와 texel density를 근거로 ratio와 absolute override를
해석한다.

AQ initial candidate는 기존 `SceneSpec 0.2.0`만 받는 legacy 3-output assignment와 full
`SceneSpec V03 0.3.0`을 함께 주는 structural assignment를 모두 읽는다. V03 경로에서는
strict mirror와 materializer가 모든 structural object를 candidate-owned recipe, mesh,
receipt와 `.blend` 증거로 만든 뒤 기존 build가 읽을 수 있는 하나의 path-backed V02
SceneSpec candidate로 compile한다. 평가와 exact promotion 전에는 canonical
`analysis/scene_spec.json`을 변경하지 않는다.

공개 migration 표면은 이 runtime candidate 경로와 별개다. canonical을 교체하지 않고
run-owned `0.3.0` derived copy와 receipt만 만든다. 따라서 모든 candidate가 V03을 반드시
사용한다거나 migration apply가 canonical SceneSpec을 승격한다는 주장은 하지 않는다.

## 7. MaterialGraphSpec와 V0.5 material round

`MaterialGraphSpec 0.1.0`은 기존 MaterialPlan/ShaderRecipe `0.5.0`을 대체하지 않는다.
base channel, ordered layer, image/vertex/semantic/curvature/position mask, 물리 texture scale,
color space, normal/displacement, bake, neutral/reference lighting 계약을 strict model로
검증한다. arbitrary node execution과 근거 없는 전역 패널선·홈·스크래치, localized detail의
반복 sampling을 거부한다.

AQ의 실제 V0.5 연결은 workflow-owned material scaffold/authored candidate를 생성하고,
exact completion과 평가 후 `material_candidate_promotion` PolicyAuthorization으로 V0.8
authored output에 승격하는 material round다. 최종 canonical MaterialPlan promotion은 기존
standard host 절차가 담당한다. MaterialGraphSpec은 현재 companion 계약과 fixture가
검증된 상태이며 모든 material round의 필수 canonical 입력으로 강제되지는 않는다. 활성
profile의 기본 material round 예산은 2회이며, 각 round는 앞선 exact candidate/evaluation과
예산을 다시 결속한다.

## 8. Assembly와 topology companion

Assembly companion은 세 층을 구분한다.

1. broad phase: bbox containment, alignment, overlap, coaxial 관계
2. narrow phase: evaluated mesh/BVH 또는 bounded sample 기반 contact, distance, penetration
3. semantic phase: required contact, insertion/clearance, bilateral/center-plane 관계

이 증거는 기구 작동, 제조 가능성, 숨은 내부 구조의 진실을 증명하지 않는다.

Topology companion profile은 `static_prop_closed`, `static_prop_open`,
`game_ready_lowpoly`, `highpoly_bake_source`, `modular_architecture`, `terrain`이다. 각
profile이 non-finite, degenerate, self-intersection, winding/normal, loose/boundary,
triangle/ngon, UV0/overlap/padding/texel density, tangent, subdivision, LOD, roundtrip 검사를
hard failure 또는 warning으로 분류한다. unavailable은 pass로 변환하지 않는다.

## 9. Integrated Quality와 후보 순위

기존 `VisualQAReport.overall_direct_score`의 값과 의미를 바꾸지 않는다. 새 report는
다음 네 축을 독립 보존한다.

- `reference_alignment`
- `structural_integrity`
- `material_fidelity`
- `production_readiness`

기본 static-prop profile threshold는 각각 `0.78`, `1.0`, `0.90`, `1.0`이며 범용 완성도
백분율이 아니다. 필요한 증거가 없으면 `unscorable`이다. hard gate, blocking reason,
legacy V0.6 direct score, provenance, 권장 reentry를 JSON에 보존한다.

후보 선택 순서는 다음과 같다.

```text
hard-gate 상태
→ critical regression 수
→ minimum meaningful gain 충족 여부
→ Pareto front
→ 변경 path 수
→ 변경량
→ stable candidate ID
```

단일 weighted score만으로 canonical 후보를 승격하지 않는다. 최선 후보 한 개만 exact
PolicyAuthorization 아래 원자적으로 승격한다.

## 10. 권한, 예산, state machine

`RootAuthorization`은 최초 요청 text hash, primary reference, production binding,
job/workflow/dispatch, profile, scope/target/output, allowed gates, prohibited scopes와 budget을
결속한다. `PolicyAuthorization`은 다음 고정 값을 가진다.

```text
authorization_source = preauthorized_profile
decided_by = autonomy_policy_engine
single_use = true
```

매 gate에서 root/profile/budget/target artifact와 이전 authorization chain을 다시 검증한다.
새 authorization도 최초 저장 직후 reload하고 root/profile/budget, exact target, dependency,
predecessor, single-use 상태와 authorization file hash identity를 모두 재검증한 뒤에만 side
effect를 실행한다. `approved_by=user`를 기록하지 않는다. 허용 routine gate에는 candidate
promotion, bounded convergence, material promotion, QA acknowledgement, V0.7 optimization
plan, final package acknowledgement와 요청된 package-bound handoff envelope plan이 포함된다.

InteriorScope, interior QA camera plan, destination project import plan, reference/scope/target
변경, budget 확대, external provider, engine-specific write, arbitrary code는 profile로 승인할
수 없다.

기본 budget은 initial 3, structural round 2×2, parametric 3, material 2, package repair 1,
Blender build 12, quality evaluation 8, canonical promotion 5, global action 64다. 모델 hard
cap은 각각 4, 3×3, 5, 3, 2, 18, 12, 8, 128 이하로 제한한다. 실행 중 확대하지 않는다.

각 `autonomy-advance`/MCP advance는 lock 아래 action 하나만 실행한다. `autonomy-run`은
호출당 명시된 `max_actions`까지만 반복하고 controller boundary 또는 terminal에서 멈춘다.
duplicate, A-B-A, A-B-C-B, 동일 변경 방향·metric 반복, plateau와 동일 failure를 감지한다.
안전한 best-known evidence가 있으면 cycle, plateau, repeated failure와 budget 종료는
production pass로 재분류하지 않고 review bundle/`review_required`로 라우팅한다.

## 11. candidate promotion과 복구

candidate는 `production/autonomy/<session>/candidates/` 아래에서 build/inspect/validate와
low-resolution QA를 거친다. controller만 assignment가 요구한 ModelingPlan, camera
hypothesis, SceneSpec을 쓸 수 있다. adviser는 canonical write 권한이 없다.

각 candidate는 build, inventory, validation, ModelingPlan, effective SceneSpec, assembly,
topology와 quality provenance를 run-owned로 보존한다. 8개 named candidate hard gate가 실제
failure와 structural score를 계산하며 material/production evidence가 아직 없으면 pass가
아니라 `unscorable`이다. 후보 선택과 controller promotion은 같은 hard-gate → Pareto →
minimum-gain 규칙을 사용한다.

승격은 canonical hash 재검증 → 이전 파일 history 보존 → candidate atomic replace →
candidate/canonical hash 검증 → promotion receipt 순서다. best-known evaluation은 별도
보존한다. non-improvement나 regression은 승격 대상이 되지 않는다.

명백한 timeout/process interruption은 canonical write 전에 같은 input으로 최대 1회만
재시도할 수 있다. schema/validation/constraint/topology/deterministic Blender 오류는 자동
retry하지 않는다. host attempt intent/failure/terminal receipt가 exact input과 budget을
결속하고 반복 failure는 terminal이 된다.

lock은 만료만으로 탈취하지 않는다. 동일 host에서 owner PID가 확실히 종료된 경우에만
복구하며, incomplete staging은 삭제하지 않고 quarantine한다.

## 12. package, 제한적 복구와 review bundle

최종 Integrated Quality가 accepted이고 V0.7 package/roundtrip evidence까지 일치해야
`quality_passed` terminal을 만들 수 있다. 결과는 `portable_gltf`, raw PBR channel,
relative dependency, fresh clean-import roundtrip을 요구한다. 선택적 handoff envelope는
package에 결속되며 목적지 프로젝트를 수정하지 않는다.

파생 package 단계에는 기본 한 번의 복구 예산이 있다. 복구 runtime은 실패한
`portable.package` 또는 `portable.roundtrip` attempt, 현재 V0.7 source fingerprint와
immutable repair plan을 exact hash로 결속한다. 자동 복구가 허용되는 경우는 다음 두
종류뿐이다.

- 이미 존재하는 immutable package ID와의 충돌: fresh `-aqrNN` package ID 사용
- roundtrip report의 실패 category가 오직 `format`인 export metadata 불일치

복구 결과도 새 package와 새 clean-import roundtrip이 모두 통과해야만 받아들인다.
material, bounds, dependency, Blender 예외, 알 수 없는 오류, canonical/source 변경은
자동 복구하지 않는다. 복구 실패나 예산 종료를 품질 통과로 바꾸지 않으며, package
acceptance에는 repair failure/plan/attempt/receipt chain이 그대로 남는다.

Windows 장경로에서는 package 생성, manifest, verifier와 production postflight가 native
extended-path 처리를 사용하되 같은 package-relative 재귀 file set을 digest한다. 따라서
정상 handoff directory가 서로 다른 hash 알고리즘 때문에 stale로 오판되지 않으며, 누락,
추가, path escape와 실제 변조는 계속 fail-closed다.

품질 미달·unscorable·예산 종료는 production package로 표시하지 않는다. immutable review
bundle에는 best blend, preview GLB, 대표 render, IQ JSON, unresolved finding, history,
comparison, manual action, PDF/sidecar와 receipt가 들어간다. manifest와 receipt에는
`production_ready=false`, `destination_handoff_eligible=false`가 고정된다.

terminal verifier는 최종 IQ JSON/manifest/PDF, profile/provenance, package/roundtrip 또는
review bundle의 exact nested dependency를 다시 검증한다. `quality_passed`와
`review_required` 증거는 상호 배타적이며, passing pre-production IQ만으로 review bundle을
만들거나 package를 통과 처리할 수 없다.

## 13. 공개 표면

CLI:

```text
autonomy-profile-status
autonomy-plan
autonomy-bind
autonomy-status
autonomy-advance
autonomy-run
autonomy-resume
autonomy-cancel
integrated-quality-run
integrated-quality-status
scene-spec-v03-migration-plan
scene-spec-v03-migration-apply
```

MCP:

```text
get_autonomy_profile_status
plan_autonomous_quality
bind_autonomy_controller
get_autonomy_state
advance_autonomous_quality
run_autonomous_quality
resume_autonomous_quality
cancel_autonomous_quality
run_integrated_quality
get_integrated_quality_status
plan_scene_spec_v03_migration
apply_scene_spec_v03_migration
```

## 14. 호환성 및 현재 경계

- 기존 SceneSpec `0.2.0`, V0.4~V0.9 JSON은 그대로 읽는다.
- legacy job은 AQ 증거가 없어도 정상이며 자동 migration하지 않는다.
- SceneSpec V03 migration은 공개 CLI/MCP에서 명시적으로 계획하고 exact plan SHA-256으로
  적용할 수 있다. 적용 결과는 `structural_migrations/<migration-id>/`의 derived copy와
  receipt이며 canonical `analysis/scene_spec.json`은 변경하지 않는다.
- structural builder, scale/BVH/topology, reference, IQ, authorization, 두 material round,
  review bundle, terminal verifier, package/handoff와 제한적 package repair가 focused 및
  isolated Blender gate에서 검증됐다.
- 실제 arbitrary reference에서 “품질이 향상됐다”는 before/after reconstruction benchmark는
  아직 없다. 제공 benchmark는 contract·결정론·materialization 검증이다.
- 2026-08-10 Windows 11/Python 3.14.6/Blender 5.0.1에서 post-change 전체 pytest/Ruff,
  AQ package/review terminal, benchmark와 V0.7/V0.8/V0.9 chained gate가 통과했다. 정확한
  숫자·경로·hash는 verification 문서에만 기록한다. 검증 범위를 넘어 일반 release-ready,
  cross-platform, destination runtime parity 또는 arbitrary-reference 품질 향상을 주장하지
  않는다.
