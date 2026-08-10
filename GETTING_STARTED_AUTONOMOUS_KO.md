# Autonomous Quality Extension 0.1.0 시작 가이드

> 최신 계약, CLI/MCP 표면과 검증 결과는
> [Autonomous Quality 최신 시작 가이드](GETTING_STARTED_AUTONOMOUS_QUALITY_KO.md)와
> [검증 기록](VERIFICATION_AUTONOMOUS_QUALITY_KO.md)을 우선한다. 이 문서는 짧은 Codex
> 요청 예시와 운영 흐름을 함께 보존한다.

## 1. 먼저 알아둘 점

AQ는 기존 `standard` workflow 위에서 제한된 정적 소품을 후보 탐색부터 portable GLB 또는
review bundle까지 조율하는 실험 기능이다. 새 모델링 파이프라인이 아니며 V1.0 출시를
의미하지 않는다.

현재 사용할 수 있는 profile은 하나뿐이다.

```text
autonomous_static_prop_v1
```

다음 조건을 모두 만족할 때만 사용한다.

- 새 reference로 만드는 새 job
- `concept` mode
- 이미지에서 명확히 지정할 수 있는 한 개의 primary object
- `primary_object_only`
- static hard-surface 또는 일반 static prop
- engine-neutral `portable_gltf`
- interior, measured/blueprint, rig, animation, gameplay가 필요 없음
- 목적지 프로젝트를 직접 수정하지 않음
- 외부 network provider나 임의 Blender/Python/node graph가 필요 없음

환경, 건축, 실측 자산용 profile은 registry에만 있고 `disabled_experimental`이다.

## 2. 권장 사용법: Codex에 한 번 요청

사용자가 PowerShell을 직접 실행할 필요는 없다. 저장소를 연 Codex에 reference 이미지를
첨부하거나 절대 경로를 알려 주고 아래 형식으로 요청한다.

```text
Autonomous Quality 0.1.0의 autonomous_static_prop_v1로 새 정적 소품을 제작해.

- 새 job ID: <JOB_ID>
- reference: <REFERENCE_PATH>
- target_subject: <TARGET_SUBJECT>
- 목적: <PURPOSE>
- reference_content_scope: primary_object_only
- output: engine-neutral portable_gltf
- controller mode: desktop_in_session
- destination handoff envelope: 필요 없음

최초 요청의 exact text와 reference hash에 RootAuthorization을 결속하고,
underlying workflow는 standard로 유지해. Reference Evidence, 최대 3개 initial candidate,
허용된 structural/parametric/material 예산, Integrated Quality를 순서대로 진행해.
routine gate는 exact PolicyAuthorization으로만 처리하고 사용자 승인이라고 기록하지 마.

품질을 통과하면 V0.7 portable GLB와 clean-import roundtrip까지 수행해.
통과하지 못하거나 증거가 unscorable이면 production package라고 부르지 말고
review-only bundle을 생성해. Interior, 실측, rig/animation/gameplay, 외부 provider,
목적지 프로젝트 수정이 필요해지면 범위를 넓히지 말고 중단 이유를 보고해.

controller-authored assignment에서 멈추면 현재 Codex 세션이 그 exact assignment에 지정된
파일만 작성한 뒤 다음 AQ action을 계속해. 각 advance는 한 action만 실행하고 모든
receipt와 hash를 검증해. 기존 job이나 immutable evidence는 변경하지 마.
```

예시:

```text
Autonomous Quality 0.1.0의 autonomous_static_prop_v1로 새 정적 소품을 제작해.

- 새 job ID: radio_prop_01
- reference: C:/references/table_radio.png
- target_subject: 탁상 라디오 본체와 구조적으로 붙은 손잡이/노브
- 목적: 배경 소품으로 사용할 engine-neutral static asset
- reference_content_scope: primary_object_only
- output: engine-neutral portable_gltf
- controller mode: desktop_in_session
- destination handoff envelope: 필요 없음

최초 요청을 RootAuthorization으로 고정하고 허용된 예산 안에서만 진행해.
품질 pass면 clean-import package, 아니면 review-only bundle로 종료해.
```

`<JOB_ID>`는 `[a-z0-9][a-z0-9_-]{0,63}`에 맞는 새 ID여야 한다. 같은 ID로 다른
reference를 덮어쓰면 안 된다.

## 3. Codex가 수행하는 실제 흐름

### 3.1 계획

`plan_autonomous_quality` MCP가 다음을 만든다.

- 새 `standard` workflow와 V0.9 production dispatch
- `quality_gate_profile.json`
- immutable `budget.json`, `profile.json`, `root_authorization.json`, `plan.json`
- `desktop_in_session` controller binding
- 최초 immutable state

`autonomy-plan`은 기존 job을 이어가는 명령이 아니다. 항상 새 job에 사용한다.

### 3.2 Reference Evidence

Pillow와 설치된 경우 OpenCV를 사용해 최대 3개 mask 후보와 perspective/orthographic
camera hypothesis를 만든다. 결과는 다음에 저장된다.

```text
reference_evidence/runs/<RUN_ID>/
```

이 단계는 canonical camera를 자동 변경하지 않는다. 보이지 않는 후면, 내부, 절대 깊이는
계속 inferred/underconstrained다.

### 3.3 후보 작성과 선택

controller는 workflow-owned candidate 폴더에 ModelingPlan, camera hypothesis, SceneSpec을
작성한다. host가 build/inspect/validate/low-resolution QA를 수행한다. 최대 3개 initial
candidate를 비교하고 다음 순서로 최선을 고른다.

legacy assignment는 SceneSpec `0.2.0`을 사용한다. structural assignment는 선택적으로 full
SceneSpec V03 `0.3.0`을 candidate-owned recipe/mesh/receipt/`.blend`로 materialize하고 기존
build용 path-backed V02 candidate로 compile할 수 있다. exact promotion 전 canonical은
변경하지 않는다.

```text
hard gate → regression → meaningful gain → Pareto → 최소 변경량
```

승격은 exact candidate hash에 결속된 `structural_candidate_promotion`
PolicyAuthorization으로만 수행한다.

### 3.4 제한된 반복

기본 budget:

| 항목 | 기본값 |
|---|---:|
| initial candidates | 3 |
| structural rounds / candidates per round | 2 / 2 |
| parametric iterations | 3 |
| material rounds | 2 |
| package repair | 1 |
| Blender builds | 12 |
| quality evaluations | 8 |
| canonical promotions | 5 |
| global actions | 64 |

budget은 RootAuthorization에 결속되며 실행 중 확대되지 않는다. duplicate, plateau,
oscillation, repeated failure를 감지하면 무한 반복하지 않는다. 안전한 best-known evidence가
있으면 production pass가 아닌 review-only bundle로 라우팅한다.

### 3.5 기존 standard production과 material

승격된 candidate는 기존 standard V0.4~V0.7 흐름으로 들어간다. routine proxy/detail/material
acknowledgement는 profile 범위 안에서 PolicyAuthorization을 사용할 수 있다. V0.5
`material.author`는 workflow-owned material candidate를 만들고 strict host promotion을
거친다. 활성 profile은 기본 최대 2회의 material round만 허용한다.

PolicyAuthorization은 최초 저장 직후에도 다시 읽어 exact root/profile/budget/target,
dependency, predecessor, single-use 상태와 파일 hash identity를 모두 검증한 뒤에만 side
effect를 실행한다.

InteriorScope, destination project import, reference/scope/target 변경은 자동 승인 대상이
아니다.

### 3.6 최종 품질과 종료

Integrated Quality는 다음 네 축을 별도 평가한다.

- reference alignment
- structural integrity
- material fidelity
- production readiness

기존 V0.6 direct score는 그대로 보존되며 완성도 백분율이 아니다.

성공 종료:

```text
Integrated Quality accepted
→ exact V0.7 policy gate
→ derived optimization
→ portable GLB package
→ fresh clean-import roundtrip
→ quality_passed terminal
```

검토 종료:

```text
needs revision / unscorable / bounded termination
→ best-known candidate 보존
→ exports/review_bundles/<BUNDLE_ID>/
→ review_required terminal
```

review bundle은 production-ready package가 아니며 Destination Handoff 입력으로 사용할 수
없다.

## 4. 상태를 확인하는 Codex 요청

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID> 상태를 읽기 전용으로 확인해.
exact plan/profile/root authorization/receipt chain을 다시 검증하고,
현재 phase, next_action, budget 사용량, best-known candidate, quality 상태,
package 또는 review bundle 경로를 보고해. 상태를 진행시키거나 파일을 수정하지 마.
```

계속 진행:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를 최대 8 action만 진행해.
각 action은 독립 lock/receipt를 사용하고 controller boundary 또는 terminal에서 멈춰.
scope, target, reference, budget을 변경하지 마.
```

중단 후 안전한 재개:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를 안전하게 재개해.
먼저 receipt-less staging, terminal intent, receipt chain과 source hash를 검증해.
완료 receipt를 재실행하거나 retry authority를 새로 만들지 말고 최대 8 action만 진행해.
```

취소:

```text
job <JOB_ID>의 Autonomous Quality session <SESSION_ID>를
"<CANCELLATION_REASON>" 사유로 취소해. 미래 action만 중단하고 canonical 및 immutable
evidence는 삭제하거나 롤백하지 마.
```

## 5. 선택적 destination handoff envelope

계획 시 사용자가 명시적으로 요청한 경우에만 package-bound handoff envelope plan을 routine
gate로 처리할 수 있다. 이 기능은 package 증거와 exact plan에 결속된 전달 자료만 만든다.

- Unity/Unreal/custom destination project에 파일을 쓰지 않는다.
- destination import plan과 실제 import는 목적지 Codex/사용자 승인 경계다.
- runtime shader/material parity를 주장하지 않는다.
- review bundle에는 handoff envelope를 만들지 않는다.

## 6. CLI 명령: 개발·진단용

일반 사용자는 Codex/MCP 요청을 권장한다. 다음 명령은 자동화 검증이나 문제 진단 시 사용할
수 있는 현재 공개 표면이다.

Profile:

```powershell
uv run cbm autonomy-profile-status
uv run cbm autonomy-profile-status --profile-id autonomous_static_prop_v1
```

새 계획:

```powershell
uv run cbm autonomy-plan "<EXACT_REQUEST>" `
  --reference "<REFERENCE_PATH>" `
  --target-subject "<TARGET_SUBJECT>" `
  --job-id <JOB_ID> `
  --controller-mode desktop_in_session `
  --no-handoff-envelope
```

상태와 진행:

```powershell
uv run cbm autonomy-status <JOB_ID> <SESSION_ID>
uv run cbm autonomy-advance <JOB_ID> <SESSION_ID>
uv run cbm autonomy-run <JOB_ID> <SESSION_ID> --max-actions 8
uv run cbm autonomy-resume <JOB_ID> <SESSION_ID> --max-actions 8
uv run cbm autonomy-cancel <JOB_ID> <SESSION_ID> --reason "<REASON>"
```

`client_mediated`를 선택한 경우에만 외부 task와 exact tool-profile hash binding이 필요하다.

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

생략한 evidence는 자동 추정되지 않고 해당 축이 `unscorable`이 될 수 있다.

## 7. 자주 만나는 중단 상태

| 상태 | 의미 | 조치 |
|---|---|---|
| `waiting_for_controller` | exact assignment의 controller output 필요 | 현재 Codex가 지정된 파일만 작성 후 advance |
| `unscorable_evidence` | 필수 품질 증거 부족 | review bundle 확인, 필요한 증거를 standard에서 작성 |
| `restricted_scope_required` | interior/실측/engine-specific 등 범위 밖 | AQ를 넓히지 말고 별도 standard 계획 |
| `stale_or_tampered` | source/profile/candidate/receipt hash 불일치 | 자동 수리 금지, 원인 audit |
| `host_failure` | non-retryable 또는 반복 host 오류 | failure receipt와 staging 검토 |
| `completed_review_bundle` | bounded 실행 완료, 품질 미승인 | manual action 문서 검토 |
| `quality_target_reached` | package와 roundtrip까지 품질 승인 | package manifest/terminal 확인 |

## 8. 현재 검증 경계

2026-08-10 Windows 11/Python 3.14.6/Blender 5.0.1에서 전체 pytest/Ruff, AQ focused gate,
실제 quality-pass package/roundtrip/handoff terminal, review-only terminal, benchmark와
V0.7~V0.9 chained gate가 통과했다. 이 검증은 `autonomous_static_prop_v1`의 bounded 범위에만
적용되며 arbitrary reference의 before/after 품질 향상이나 destination runtime parity를
뜻하지 않는다. exact 수치·경로·hash와 남은 제한은
`VERIFICATION_AUTONOMOUS_QUALITY_KO.md`를 확인한다.
