# Autonomous Quality Extension 0.1.0 시작 가이드

## 1. 이 기능의 위치

Autonomous Quality Extension(AQ)은 프로젝트 `0.9.0` 위에 명시적으로 선택하는 실험
overlay다. 기존 `standard` workflow를 내부 실행 경로로 사용하며, 별도의 세 번째 모델링
파이프라인이나 V1.0 승격이 아니다. 기존 `standard`와 `background_exterior`의 기본 동작,
승인, retry와 package 의미는 바뀌지 않는다.

현재 활성 profile은 하나뿐이다.

```text
autonomous_static_prop_v1
```

다음 조건을 모두 만족하는 새 작업에 사용한다.

- 새 unique lowercase job ID와 새 primary reference
- `concept` mode
- `primary_object_only`
- 이미지에서 명확히 지정할 수 있는 한 개의 `target_subject`
- static hard-surface 또는 일반 static prop
- engine-neutral `portable_gltf`
- 목적지 프로젝트를 직접 수정하지 않음

다음은 이 profile의 범위 밖이다.

- interior와 interior QA
- measured/blueprint/constraint 작업
- rig, skinning, animation, gameplay
- engine-specific prefab/actor 또는 destination-project write
- external network provider
- arbitrary Blender Python, arbitrary node graph 또는 shell authority
- CAD/B-Rep 지원 주장
- reference, content scope 또는 target subject 교체
- 실행 중 budget 확대

`autonomous_environment_v1`, `autonomous_architecture_v1`,
`autonomous_measured_asset_v1`은 registry에 있더라도 `disabled_experimental`이다.

## 2. 권장 사용법: Codex에 한 번 요청

일반 사용자는 PowerShell을 직접 실행할 필요가 없다. 저장소를 연 Codex에 reference
이미지를 첨부하거나 경로를 알려 주고 다음 프롬프트를 사용한다.

```text
Autonomous Quality Extension 0.1.0의 autonomous_static_prop_v1으로 새 정적 소품을 제작해.

- 새 job ID: <JOB_ID>
- primary reference: <REFERENCE_PATH>
- target_subject: <TARGET_SUBJECT>
- 사용 목적: <PURPOSE>
- reference_content_scope: primary_object_only
- output: engine-neutral portable_gltf
- controller mode: desktop_in_session
- destination handoff envelope: 요청하지 않음

최초 요청의 exact text, primary reference SHA-256, 새 standard workflow/production dispatch,
profile과 immutable budget을 RootAuthorization에 결속해. Reference Evidence와 최대 3개
initial candidate를 만들고, 허용된 structural/parametric/material 예산 안에서만 평가해.
각 routine gate는 exact single-use PolicyAuthorization으로 처리하되 사용자 승인이라고
기록하지 마. Integrated Quality의 네 축과 hard gate를 평가하고 단일 weighted score만으로
후보를 승격하지 마.

품질을 통과하면 V0.7 portable GLB, raw PBR, fresh clean-import roundtrip과 terminal
verification까지 완료해. 품질 미달, unscorable 또는 bounded 종료이면 production package라
부르지 말고 best-known candidate의 review-only bundle을 생성해. 범위 밖 요구, stale/tampered
evidence, 비허용 host failure가 나오면 자동으로 범위를 넓히거나 budget을 늘리지 말고 exact
중단 이유를 보고해.

controller assignment 경계에서는 현재 Codex가 assignment에 선언된 workflow-owned 파일만
작성한 뒤 다음 action을 계속해. canonical 입력, 기존 job, 과거 package와 immutable receipt를
덮어쓰거나 자동 migration하지 마.
```

예시:

```text
Autonomous Quality Extension 0.1.0의 autonomous_static_prop_v1으로 새 정적 소품을 제작해.

- 새 job ID: desk_radio_aq01
- primary reference: C:/references/desk_radio.png
- target_subject: 탁상 라디오 본체와 구조적으로 붙은 손잡이·노브
- 사용 목적: 배경용 engine-neutral static prop
- reference_content_scope: primary_object_only
- output: engine-neutral portable_gltf
- controller mode: desktop_in_session
- destination handoff envelope: 요청하지 않음

최초 요청과 reference hash에 결속된 기본 budget 안에서만 진행해. IQ 통과면 clean-import
package, 아니면 review-only bundle로 종료하고 exact JSON/PDF evidence 경로를 보고해.
```

`<JOB_ID>`는 `[a-z0-9][a-z0-9_-]{0,63}`에 맞아야 한다. 기존 job ID나 예약 example ID를
재사용하지 않는다.

## 3. 실제 자동 실행 흐름

```text
새 요청과 reference
→ new standard V0.8 workflow + V0.9 production dispatch
→ RootAuthorization + profile + immutable budget
→ local Reference Evidence
→ workflow-owned initial candidates (최대 3)
→ bounded structural/parametric candidates
→ V0.5 workflow-owned material candidates (기본 최대 2 round)
→ Integrated Quality
   ├─ accepted
   │  → exact V0.7 policy authorization
   │  → derived optimization
   │  → portable GLB + raw PBR
   │  → fresh clean-import roundtrip
   │  → terminal verifier
   │  → quality_passed
   └─ non-pass / unscorable / bounded stop
      → best-known candidate 보존
      → review-only bundle
      → terminal verifier
      → review_required
```

Reference Evidence는 Pillow를 기본으로 쓰고 OpenCV가 있으면 bounded segmentation과
line/vanishing cue를 추가한다. mask와 camera hypothesis는 staging evidence이며 recovered
truth가 아니다. 단일 이미지의 후면, 내부와 절대 깊이는 계속 inferred 또는
underconstrained다.

legacy candidate assignment는 SceneSpec `0.2.0`을 사용한다. optional structural assignment는
full SceneSpec V03 `0.3.0`을 candidate-owned recipe/mesh/receipt/`.blend`로 materialize하고,
기존 build 경로가 읽는 path-backed V02 candidate로 compile한다. exact promotion 전 canonical
SceneSpec은 변경하지 않는다.

후보 선택 순서는 hard gate → regression → minimum meaningful gain → Pareto → 변경 path 수
→ 변경량 → stable candidate ID다. 최선 후보 하나만 exact PolicyAuthorization 아래에서
승격하며 best-known evidence는 별도로 보존한다.

기본 예산은 initial candidate 3, structural round 2×2, parametric iteration 3, material
round 2, package repair 1, Blender build 12, quality evaluation 8, canonical promotion 5,
global action 64다. 실행 중 확대되지 않는다. duplicate, A-B-A, A-B-C-B, 반복 변경 방향,
plateau와 반복 failure를 감지하면 제한 없이 계속하지 않는다. 안전한 best-known evidence가
있으면 pass를 발명하지 않고 review-only bundle로 라우팅한다.

## 4. 승인과 자동화 경계

`PolicyAuthorization`의 고정 의미는 다음과 같다.

```text
authorization_source = preauthorized_profile
decided_by = autonomy_policy_engine
single_use = true
```

이는 사용자 승인 파일이 아니다. 최초 요청에 결속된 profile이 허용한 routine gate인지
exact artifact마다 다시 판정한 결과다. candidate promotion, bounded convergence,
material candidate promotion, QA acknowledgement, V0.7 optimization plan, final package
acknowledgement와 최초 요청에 포함한 package-bound handoff envelope plan을 처리할 수 있다.

처음 만든 PolicyAuthorization도 저장 직후 다시 읽어 root/profile/budget, exact target,
dependency, predecessor, single-use 상태와 authorization file SHA-256 identity를 전부
검증한다. first-use artifact라고 검증을 생략하지 않는다.

다음 경계는 대체하지 못한다.

- InteriorScope와 interior-QA camera plan
- destination project import plan과 실제 목적지 수정
- reference, content scope 또는 target subject 변경
- profile hard limit 또는 budget 확대
- external provider, engine-specific write와 arbitrary code

기존 workflow approval, V0.6 guarded revision approval, V0.7 optimization approval,
Destination Handoff approval을 AQ authorization으로 변환하지 않는다. 기존 blocked,
cancelled, failed workflow도 새 정책으로 재분류하거나 자동 resume하지 않는다.

## 5. Integrated Quality 해석

Integrated Quality `0.1.0`은 기존 Visual QA `0.6.0`을 대체하지 않는다. 기존
`overall_direct_score`를 exact하게 보존하면서 다음 네 축을 독립 평가한다.

- reference alignment
- structural integrity
- material fidelity
- production readiness

threshold는 profile별 gate 값이며 범용 완성도 백분율이 아니다. 필요한 evidence가 없으면
`unscorable`이고, 0점이나 pass를 발명하지 않는다. JSON이 판단 원본이며 PDF는 사람이 읽는
projection이다.

## 6. production package와 review bundle

`quality_passed`에는 final IQ accepted만으로 부족하다. exact V0.7 source와 optimization,
immutable package manifest, raw PBR dependency, fresh passed clean-import roundtrip, bounds,
semantic/material identity와 terminal hash chain이 모두 일치해야 한다.

package 단계의 자동 복구는 기본 한 번이며 다음 두 경우만 허용된다.

- 계획한 immutable package ID가 이미 존재하는 충돌
- roundtrip report의 실패 category가 오직 `format`인 export metadata 불일치

복구는 fresh `-aqrNN` package ID를 사용하고 failure → plan → attempt → receipt를 보존한다.
새 clean-import roundtrip이 통과해야만 받아들인다. material, bounds, dependency, Blender,
unknown error, stale 또는 tampered canonical source는 자동 복구하지 않는다.

Windows 장경로 package와 handoff는 generation/manifest/validation/V0.9 postflight가 같은
package-relative recursive file set을 hash한다. 정상 directory evidence의 hash parity를
보장하되 누락, 추가, path escape와 변조는 계속 fail-closed다.

`review_required` bundle은 best-known `.blend`, preview GLB, representative renders, exact IQ
JSON, unresolved findings, iteration history, candidate comparison, manual action과 PDF/sidecar를
제공한다. 그러나 다음 값이 고정된다.

```text
production_ready = false
destination_handoff_eligible = false
```

review bundle을 production package, clean-import 통과 자산 또는 Destination Handoff 입력으로
사용하지 않는다.

## 7. 상태 확인, 계속, 재개와 취소

Codex에 상태만 요청:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를 읽기 전용으로 검증해.
exact root/profile/budget, transition/attempt/authorization chain, current phase, next_action,
budget usage, best-known candidate, final IQ, package/roundtrip 또는 review bundle을 보고해.
상태를 진행하거나 파일을 수정하지 마.
```

bounded 계속 실행:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를 최대 8 action만 계속해.
각 action은 별도 lock과 immutable receipt를 사용하고 controller assignment 또는 terminal에서
멈춰. scope, target, reference와 budget을 변경하지 마.
```

중단 후 재개:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를 안전하게 재개해.
먼저 receipt-less staging, terminal intent, transition chain과 source hash를 검증해.
완료 action을 재실행하거나 retry authority를 합성하지 말고 최대 8 action만 진행해.
```

취소:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를 "<REASON>" 사유로 취소해.
미래 action만 중단하고 canonical과 immutable evidence는 삭제·복구·재분류하지 마.
```

## 8. 개발·진단용 CLI

일반 사용자는 위 Codex/MCP 경로를 권장한다. 현재 공개 CLI는 다음과 같다.

```powershell
uv run cbm autonomy-profile-status --profile-id autonomous_static_prop_v1

uv run cbm autonomy-plan "<EXACT_REQUEST>" `
  --reference "<REFERENCE_PATH>" `
  --target-subject "<TARGET_SUBJECT>" `
  --job-id <JOB_ID> `
  --controller-mode desktop_in_session `
  --no-handoff-envelope

uv run cbm autonomy-status <JOB_ID> <SESSION_ID>
uv run cbm autonomy-advance <JOB_ID> <SESSION_ID>
uv run cbm autonomy-run <JOB_ID> <SESSION_ID> --max-actions 8
uv run cbm autonomy-resume <JOB_ID> <SESSION_ID> --max-actions 8
uv run cbm autonomy-cancel <JOB_ID> <SESSION_ID> --reason "<REASON>"
```

`client_mediated`를 사용할 때만 exact external controller task binding이 필요하다.

```powershell
uv run cbm autonomy-bind <JOB_ID> <SESSION_ID> `
  --external-task-id <TASK_ID> `
  --external-host-id <HOST_ID> `
  --tool-profile-sha256 <SHA256>
```

독립 Integrated Quality companion:

```powershell
uv run cbm integrated-quality-run <JOB_ID> `
  --run-id <RUN_ID> `
  --qa-report <JOB_RELATIVE_QA_JSON> `
  --validation <JOB_RELATIVE_VALIDATION_JSON> `
  --material-validation <JOB_RELATIVE_MATERIAL_JSON> `
  --material-fidelity <JOB_RELATIVE_FIDELITY_JSON> `
  --mesh-preflight <JOB_RELATIVE_PREFLIGHT_JSON> `
  --roundtrip <JOB_RELATIVE_ROUNDTRIP_JSON>

uv run cbm integrated-quality-status <JOB_ID> --run-id <RUN_ID>
```

동등한 allowlisted MCP 표면:

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
```

## 9. 선택적 SceneSpec V03 derived migration

SceneSpec V03 `0.3.0`은 일반 AQ 실행에 필수가 아니다. 기존 canonical SceneSpec은 계속
`0.2.0`이다. AQ structural candidate가 optional V03 runtime materialization을 사용하더라도
candidate-owned payload를 참조하는 V02 candidate로 compile한 뒤 exact promotion 경계를
거치며 canonical 계약 버전을 바꾸지 않는다.

명시적인 개발·진단 요청에서만 다음 공개 표면을 사용한다.

```powershell
uv run cbm scene-spec-v03-migration-plan <JOB_ID> <MIGRATION_ID>
uv run cbm scene-spec-v03-migration-apply <JOB_ID> <MIGRATION_ID> `
  --exact-plan-sha256 <EXACT_PLAN_SHA256>
```

동등 MCP는 `plan_scene_spec_v03_migration`과
`apply_scene_spec_v03_migration`이다.

첫 명령은 immutable plan과 strict V03 candidate를 만들고 exact plan file SHA-256을
보고한다. 둘째 명령은 source/plan/candidate hash를 재검증한 뒤 다음 경로에 derived copy와
receipt만 게시한다.

```text
workspaces/<JOB_ID>/structural_migrations/<MIGRATION_ID>/
```

이 명령은 canonical `analysis/scene_spec.json`, authoring `.blend`, geometry와 기존 workflow를
변경하지 않는다. derived V03 copy를 canonical로 승격하는 공개 절차는 현재 없다.

## 10. 주요 evidence 경로

```text
workspaces/<JOB_ID>/reference_evidence/runs/<RUN_ID>/
workspaces/<JOB_ID>/reports/integrated_quality/runs/<RUN_ID>/
workspaces/<JOB_ID>/production/autonomy/<SESSION_ID>/
workspaces/<JOB_ID>/production/autonomy/<SESSION_ID>/package_repairs/
workspaces/<JOB_ID>/exports/packages/portable_gltf/<PACKAGE_ID>/
workspaces/<JOB_ID>/exports/review_bundles/<BUNDLE_ID>/
workspaces/<JOB_ID>/structural_migrations/<MIGRATION_ID>/
```

`state.json`, `latest.json`과 PDF는 편의 projection이다. exact JSON, immutable transition,
authorization, receipt, manifest와 개별 file SHA-256이 권위 원본이다.

## 11. 남아 있는 제한

- 한 장의 이미지에서 보이지 않는 면, 내부와 절대 깊이를 복원된 사실로 보장하지 않는다.
- 제공 benchmark는 contract, 결정론과 materialization fixture다. 임의 reference 전반의
  시각 품질 향상이나 완성도를 증명하지 않는다.
- review bundle은 목적지 전달용 package가 아니다.
- Unity/Unreal/custom engine runtime parity와 자동 import를 주장하지 않는다.
- `desktop_in_session`은 workflow contract 경계를 유지하지만 per-task MCP/shell 제한을
  enforcing client처럼 보증하지 않는다.
- MaterialGraphSpec은 companion이며 모든 AQ material round의 필수 canonical 입력이 아니다.
- standalone structural materializer의 임의 260자 초과 Windows 경로 제한은 남아 있다.
  package/handoff 장경로 digest parity와는 별도다.
- package repair는 immutable package-ID collision과 format-only roundtrip 실패에 한정된다.
- cycle change-direction과 changed-path tie-break는 보수적인 coarse heuristic이다.
- full Blender fault-injection interruption/resume E2E는 아직 별도 미검증이다.
- macOS/Linux, Blender 4.x와 destination runtime import/parity는 검증하지 않았다.
- AQ 활성화가 legacy job을 migration하거나 과거 blocked workflow를 복구하지 않는다.
- 프로젝트 버전은 계속 `0.9.0`이며 V1.0 승격은 별도 결정과 release gate가 필요하다.

## 12. 2026-08-10 검증 상태

Windows 11/Python 3.14.6/Blender 5.0.1에서 전체 pytest `1145 passed, 20 skipped,
8 warnings`, Ruff/doctor/GLB-FBX-OBJ compatibility, AQ focused gate `195 passed, 2 skipped`,
실제 Blender AQ bundle `14 passed`, 8-case benchmark와 V0.7~V0.9 chained gate가 통과했다.
quality-pass package/roundtrip/handoff와 review-only terminal도 각각 exact hash로 검증됐다.

이 결과는 `autonomous_static_prop_v1`만 검증하며 arbitrary reference의 before/after 품질
향상을 보장하지 않는다. 상세 evidence는
`VERIFICATION_AUTONOMOUS_QUALITY_KO.md`를 따른다.
