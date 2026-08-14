# Autonomous Quality 0.2 시작 안내

## 1. 현재 상태

Autonomous Quality(AQ) 0.2는 기존 `standard` 제작 흐름 위에 놓이는 병렬 companion
계층이다. 프로젝트 버전은 계속 `0.9.0`, canonical SceneSpec은 계속 `0.2.0`이며,
기존 `autonomous_static_prop_v1`, `standard`, `background_exterior`의 의미를 바꾸지 않는다.

현재 profile 상태는 **`disabled_experimental`**이다. host/full 회귀, Blender 5.0.1 synthetic
geometry/material fixture, 같은 quality-approved source의 독립 GLB+FBX clean import와 V0.7~V0.9
root smoke는 통과했다. 다만 다음 활성화 경계는 아직 완결되지 않았다.

- Codex Desktop supporting client가 controller별 sandbox/allowlist를 집행하는 실제 attestation
- repository가 별도 Codex task를 생성하는 경로 또는 optional Codex App Server 실기동
- 임의 사용자 reference의 일반 품질 향상과 실제 human review
- 실제 목적지 runtime import/material parity

profile blocker와 별개로 canonical material master/neutral/reference preview의 전체 lifecycle,
원격 GitHub/self-hosted CI run, cross-platform matrix도 아직 미검증 제한으로 남아 있다.

따라서 이 문서는 실험 계약을 살펴보고 격리된 새 job을 계획하는 방법을 설명한다. AQ 0.2가
현재 기본 제작 모드이거나 production-ready라고 해석하면 안 된다.

## 2. 적용 범위

현재 v2 planner가 받는 범위는 다음으로 고정된다.

- 새 정적 hard-surface 또는 static prop
- `concept` mode
- `primary_object_only`
- 명시적인 `target_subject`
- underlying execution policy `standard`
- controller mode `desktop_in_session` 또는 `client_mediated`
- delivery request `review_only`, `portable_gltf`, `portable_fbx`

실내, 건축, 환경 전체, 실측/청사진, rig, skinning, animation, gameplay, CAD/B-Rep,
engine-specific project write는 이 profile의 권한 밖이다. 단일 이미지의 가려진 면과 절대 치수는
계속 `inferred`이며 recovered truth가 아니다.

## 3. 먼저 읽을 문서

1. `GETTING_STARTED_KO.md` — 현재 V0.4~V0.9 기본 흐름
2. `ARCHITECTURE_AQ_V02_KO.md` — AQ 0.2 계약과 상태 모델
3. `CONTROLLER_EXECUTOR_KO.md` — controller 격리와 권한 경계
4. `QUALITY_BENCHMARK_KO.md` — metric이 증명하는 것과 증명하지 않는 것
5. `MATERIAL_AUTHORING_KO.md` — local material companion과 fixed Blender/미검증 품질 경계
6. `DELIVERY_PROFILES_KO.md` — review/GLB/FBX 전달과 V0.7 승인
7. `MIGRATION_AQ_V02_KO.md` — 명시적 plan/apply, no auto migration
8. `VERIFICATION_AQ_V02_KO.md` — 실제 실행 결과와 남은 미검증 항목
9. `GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md` — 선택적 built-in ImageGen companion

## 4. 공개 상태 확인

사용자는 PowerShell을 직접 실행하지 않고 Codex에 “AQ v2 profile과 controller 상태를 읽기
전용으로 확인해”라고 요청할 수 있다. Codex/MCP 공개 도구는 다음과 같다.

- `get_autonomy_v2_profile_status`
- `list_autonomy_v2_delivery_profiles`
- `get_autonomy_v2_state`
- `advance_autonomous_quality_v2`
- `run_autonomous_quality_v2`
- `cancel_autonomous_quality_v2`
- `get_controller_executor_status`

CLI를 사용하는 개발자는 현재 구현된 명령만 사용한다.

```powershell
uv run cbm autonomy-v2-profile-status
uv run cbm autonomy-v2-delivery-profiles
uv run cbm controller-executor-status
```

상태 출력의 `verified_active=false`와 `disabled_experimental`을 성공 또는 지원으로 바꾸어
해석하지 않는다. `desktop_in_session=available`은 현재 Codex task가 격리 output을 작성한 뒤
host가 채택할 수 있다는 뜻이며, 저장소가 새 Codex task를 생성할 수 있다는 뜻이 아니다.

## 5. 실험 계획 만들기

### 5.1 Codex에 요청할 때

다음 정보를 한 번에 제공한다.

- 새 reference 파일
- 구체적인 대상 오브젝트 이름
- 용도
- 원하는 delivery 하나 또는 GLB+FBX 둘
- 실험 v2 profile을 사용한다는 명시적 동의

예시 요청:

```text
첨부한 이미지에서 휴대용 비상 라디오만 대상으로 새 정적 소품 job을 계획해줘.
reference content scope는 primary_object_only, target subject는 portable emergency radio로 고정해.
Autonomous Quality 0.2가 disabled_experimental이고 Desktop controller는 adopt-only이며 실제
reference 품질과 App Server가 미검증이라는 경계를 그대로 보고해. 이 새 job에 한해서 실험 계획
생성을 허용할게.
delivery는 portable_gltf와 portable_fbx를 각각 독립적으로 요청하되 V0.7 exact plan hash
승인 전에는 package를 만들지 마. 목적지 프로젝트는 수정하지 마.
```

### 5.2 CLI를 사용하는 개발자

`--enable-v2`가 없으면 planner는 fail-closed한다. 다음은 계획 생성이며 모든 후속 승인이나
delivery 성공을 뜻하지 않는다.

```powershell
uv run cbm autonomy-v2-plan `
  --reference <REFERENCE_PATH> `
  --target-subject "portable emergency radio" `
  --deliveries portable_gltf,portable_fbx `
  --controller-mode desktop_in_session `
  --destination-hint engine_neutral `
  --enable-v2 `
  "새 정적 소품을 primary_object_only 범위로 제작"
```

`review_only`는 portable profile과 함께 요청할 수 없다. delivery를 생략하면 CLI 기본값은
`portable_gltf`지만, 원하는 결과를 명시하는 편이 안전하다. `unity_urp` 또는 `unity_hdrp`
destination hint는 advisory 계획용 데이터일 뿐 Unity project write나 runtime parity를
허용하지 않는다.

## 6. 계획이 생성하는 경계

새 v2 계획은 기존 production dispatcher를 통해 새 `standard` workflow와 production dispatch를
만든 뒤, 다음 run-owned evidence를 추가한다.

```text
workspaces/<job-id>/production/autonomy_v2/<session-id>/
├─ profile.json
├─ budget.json
├─ root_authorization.json
├─ plan.json
├─ tool_profiles/
└─ states/0000.json
```

정확한 사용자 요청, primary reference hash, target subject, delivery profiles, controller mode,
budget, phase tool profiles가 immutable evidence에 결속된다. 계획 생성은 다음을 하지 않는다.

- canonical SceneSpec 또는 V0.5 contract 자동 변경
- 사용자 승인의 합성
- V0.7 optimization 승인 대체
- Destination Handoff 승인 대체
- destination project write

## 7. 실행과 controller 경계

AQ v2는 `autonomy-v2-advance`와 `autonomy-v2-run`을 제공한다. `advance`는 한 bounded action,
`run`은 budget 안의 여러 action을 수행한다. 둘 다 필요한 controller output, caller-supplied IQ
report 또는 specialized approval이 없으면 그 경계에서 정지한다. repository가 독립 Codex task를
생성하거나 optional Codex App Server를 실기동하는 표면은 없다.

```powershell
uv run cbm autonomy-v2-advance <JOB_ID> <SESSION_ID> --enable-v2
uv run cbm autonomy-v2-run <JOB_ID> <SESSION_ID> --enable-v2
# IQ 제출이 준비된 호출에서만 다음 옵션을 함께 지정한다.
uv run cbm autonomy-v2-advance <JOB_ID> <SESSION_ID> --quality-submission <PATH> --enable-v2
```

`desktop_in_session`에서는 현재 Codex session이 exact assignment와 immutable input snapshot을
읽고 execution-owned controller workspace의 허용 output에 결과를 작성한다. host는 다음을 모두 확인해야
채택한다.

- assignment, input, tool profile의 exact SHA-256
- output root containment와 허용 file set
- 누락·추가 파일 없음
- 선택적으로 요구된 output hash 일치
- controller 결과가 canonical write authority를 주장하지 않음

부분 output, extra file, stale input, timeout, tampering은 성공으로 보정하지 않는다.

waiting 상태에서 `advance`/`run`을 다시 호출해도 새 request나 새 execution workspace를 만들지
않는다. 같은 request/input/profile과 protected canonical source를 exact rehash해 output이 있을 때만
채택한다. output이 없으면 state sequence와 budget은 그대로다. 기다리는 동안 ModelingPlan,
SceneSpec, blend 또는 material source가 바뀌면 기존 output은 stale로 거부된다.
execution-root 또는 adoption result가 이미 있어도 full executor lifecycle과 stored result bytes를
다시 검증하며, active·미만료 RootAuthorization과 exact plan/profile/budget binding 없이는 direct
controller/delivery side effect를 시작하지 않는다. AQ v2 timeout은 재시도 대기가 아니라
nonretryable failed terminal이다.

현재 검증된 phase 순서는 다음과 같다.

```text
geometry output → strict build/promotion
→ material output → strict compile/rebuild/promotion
→ caller-supplied IQ 0.2 → quality terminal
→ delivery review/approval → delivery terminal
```

`run`이 IQ report를 생성하거나 V0.7 승인을 대신 만들지는 않는다.

## 8. quality와 delivery 분리

IQ 0.2의 `passed`만 quality-approved source freeze를 만들 수 있다. `needs_revision`과
`unscorable`은 exact review bundle을 가진 `review_required` quality terminal로 끝나며 portable
package 권한을 만들지 않는다. `blocked`는 bundle이나 source freeze 없이 `blocked` terminal로
끝난다. 어떤 실패 terminal도 review delivery를 성공한 것처럼 주장할 수 없다.

quality pass 후에도 portable delivery마다 별도 V0.7 review plan이 만들어지고 사용자는 각각의
exact optimization-plan SHA-256을 승인해야 한다.

authoritative hard finding은 pass를 차단하고 exact `failed` required gate에 결속돼야 한다. host는
global/semantic mask PNG bytes에서 metric과 전체 decision을 다시 계산한다. typed raw receipt가 없는
required scored landmark/multi-view는 pass authority가 없다. 또한 IQ source/input은 현재 canonical
ModelingPlan, SceneSpec, blend, build, material/shader/texture/geometry, exact
`geometry_candidate_validation_receipt`, `material_phase_receipt`와 survival evidence를 모두 가리켜야
한다. delivery terminal은 참조된 quality terminal의 full validator를 다시 호출하므로 status/hash만
위조한 `quality_approved` terminal은 사용할 수 없다.

```text
IQ needs_revision/unscorable
└─ review_required quality terminal + exact review bundle
   └─ source freeze/package/handoff 권한 없음

IQ blocked
└─ blocked quality terminal, review bundle/source freeze 없음

IQ passed
└─ quality_approved terminal + exact source freeze
   ├─ review_only delivery → package 없음, handoff 불가
   ├─ portable_gltf → V0.7 GLB review → exact approval → package → clean import
   └─ portable_fbx  → V0.7 FBX review → exact approval → package → clean import
```

위의 non-pass review bundle과 DeliveryProfile의 `review_only` result는 다른 terminal이다. portable
delivery의 aggregate terminal은 exact quality terminal, source freeze, delivery plan, format별
result와 exact V0.7 review binding을 함께 결속해야 한다. public supervisor가 이 terminal을
발행하고 다시 nested validation한다.

GLB 성공은 FBX 성공을 뜻하지 않는다. 2026-08-11 synthetic Blender fixture에서는 같은 freeze의
두 package를 서로 변환하지 않고 생성해 각각 clean-import하는 경로가 통과했다. fixture에 포함된
exact approval artifact는 테스트 입력이며 실제 사람이 production plan을 승인했다는 뜻은 아니다.

## 9. 상태와 취소

```powershell
uv run cbm autonomy-v2-status <JOB_ID> <SESSION_ID>
uv run cbm autonomy-v2-advance <JOB_ID> <SESSION_ID> --enable-v2
uv run cbm autonomy-v2-run <JOB_ID> <SESSION_ID> --enable-v2
uv run cbm autonomy-v2-cancel <JOB_ID> <SESSION_ID> --reason "<REASON>"
```

상태 조회는 immutable `states/*.json`의 sequence와 predecessor hash를 재검증한다. 취소는 미래
action을 중단하지만 reference, canonical evidence, 이전 state와 attempt를 삭제하지 않는다.
cancelled session을 resume하거나 기존 evidence를 새 profile로 재분류하지 않는다.

재검증은 predecessor hash에서 끝나지 않는다. initial state부터 각 transition의 input/source,
producer, provenance delta와 budget이 단조롭게 이어지는지 재구성한다. phase state를 끼워 넣거나
provenance를 교체하거나 budget을 되돌린 chain은 조회와 실행 모두에서 거부된다.

## 9A. 선택적 Codex Built-in ImageGen overlay

`autonomous_static_prop_v2_codex_imagegen`은 기본 AQ v2 실행 모드가 아니라 별도
`disabled_experimental` companion이다. 기존 `autonomous_static_prop_v2`의 local-only 의미와
state를 수정하지 않고, geometry promotion 뒤 material-authoring 시작점에서만 sibling overlay를
사용한다.

계획에는 두 개의 명시적 opt-in이 모두 필요하다.

```text
codex_imagegen_allowed=true
allow_disabled_experimental=true
```

overlay는 현재 Codex task가 읽을 exact assignment와 ControllerExecutionRequest를 게시한다.
repository가 `OPENAI_API_KEY`, OpenAI SDK나 HTTP image provider를 사용하거나 새 Codex task를
만들지는 않는다. 앱이 닫히면 `waiting_for_controller`에서 멈추며, 재개는 같은
assignment/request/workspace와 protected source inventory를 다시 검사하는 동작이다.

직접 generated role은 `base_color`, `decal_rgb`, `emission`, `opacity_source`로 제한된다.
normal/roughness/metallic/height/AO는 selected source에 결속된 local deterministic MaterialAuthoring
`0.2.1` 처리로만 만든다. exact signage text도 provider prompt에서 제외하고 project-local font로
합성한다.

local raster quality는 dimension/detail/alpha/border/seam/emission을 검사하지만 unwanted
object/text와 style/background semantics는 non-hard `unscorable`이다. fake controller success를 실제
built-in ImageGen 실행이나 human review로 해석하지 않는다. core `0.1.0` 자체는 MaterialAuthoring
`0.2.1` staging receipt 뒤 overlay `status=adopted`,
`next_action=controller_promotion_required`에서 멈춘다.

2026-08-13 additive Material Loop `0.1.0`은 이 immutable core evidence를 다시 쓰지 않고 별도
bridge/controller closure로 existing host material promotion에 연결한다. native-original adoption과
normalization, `CodexImageNativeCorePreparationReceipt`, current-task semantic review,
multi-candidate selection, actual Blender exact-adoption shadow preflight 또는 bounded
controller-authored completion을 exact하게 결속한다. 기존 ControllerExecutor와
`material_phase_service`만 actual `MaterialPhaseReceiptV2`와 canonical promotion을 만들 수 있다.

성공 뒤 base AQ는 기존 transition service를 통해 IQ 경계로 재개된다. `material_promoted`는 IQ pass가
아니고, `quality_approved`도 V0.7 approval/package/destination 완료가 아니다. exact V0.7 사용자 승인이
없으면 `waiting_for_v07_approval`에서 멈춘다. 두 profile은 계속 `disabled_experimental`이다.

core workflow는 [ImageGen 시작 가이드](GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md), staging 이후는
[Material Loop 시작 가이드](GETTING_STARTED_IMAGEGEN_MATERIAL_LOOP_KO.md), 현재 Codex 작업에 붙여 넣는
요청은 [Material Loop 프롬프트 모음](IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md), 실제 확인 범위는
[ImageGen core 검증](VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md)과
[Material Loop 검증](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다.

## 10. 안전한 기본 선택

실제 자산 제작이 목적이면 현재는 기존 `standard` 또는 검증된
`autonomous_static_prop_v1`을 기본으로 사용한다. AQ 0.2는 다음 조건에서만 선택한다.

- 새 격리 job이다.
- 실험 상태와 제한을 받아들였다.
- host evidence와 Blender evidence의 차이를 검토할 수 있다.
- 각 V0.7/Destination Handoff 승인을 별도로 수행할 의사가 있다.
- 실패 시 기존 standard 흐름으로 새 계획을 세우며 v2 evidence를 제자리 수정하지 않는다.

실제 지원·활성화 여부의 판단 원본은 `VERIFICATION_AQ_V02_KO.md`와 machine-readable JSON
evidence다. PDF, README 문구 또는 synthetic benchmark 점수는 이를 대신하지 않는다.

## 11. Material Closure가 필요한 material 재개

새 stabilized AQ v2 material attempt에서는 old retry를 바로 실행하지 않는다. 먼저 combined status로
raw AQ state와 current canonical을 함께 확인하고, terminal session이면 별도
`material-repair-<timestamp>-<suffix>` plan을 만든다.

운영 순서는 다음 12개 CLI/MCP 동등 surface의 좁은 조합으로 표현된다.

```text
material-closure-plan / material-closure-status
material-graph-rebind
material-preflight-run / material-preflight-status / material-shadow-compile
material-state-consistency / material-framework-failure-status
material-retry-supersede
material-repair-session-plan / material-repair-session-run
material-appearance-approve
```

repair run은 geometry hash 확인, candidate, closure, rebind, preflight, shadow compile, preview까지
자동으로 수행할 수 있지만 사용자 결정 없이 approval을 만들지 않는다. 정상 preapproval 종료는
`approval_pending`이다. `material-appearance-approve`는 caller-authored exact decision을 current
preflight에 검증·게시할 뿐 self-approval 명령이 아니다. 실제 명령 등록과 gate 상태는
[Material Closure 검증 기록](VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)을 확인한다.

현재 Crystalgun historical session은 verified head가 `0012 / terminal / cancelled / none`이므로
이 경로로도 그 session을 resume하지 않는다. canonical MaterialPlan, MaterialPhaseReceiptV2,
neutral preview와 IQ evidence가 없으며 existing technical retry approval은 새 authority가 아니다.
2026-08-14 새 repair dry-run도 surface-detail coverage 검사에서 Blender/preview/approval/controller
전에 `preflight_failed`로 멈췄다. 따라서 새 coverage-complete candidate 없이 approve 또는 resume
명령으로 건너뛸 단계가 없다.

## 12. Shared material identity가 원인인 경우

Material Closure가 object assignment/material identity `scope_change`를 보고하면
`material-identity-split-plan`, `material-identity-split-preapproval`과 status/approval-request 조회로
paired candidate를 검증한다. 정상 자동 종료는 `framework_ready_for_explicit_scope_approval`이며
ApprovalRequest 자체는 승인이 아니다.

실제 사용자 결정이 별도 evidence로 제공되기 전에는 `material-identity-split-approve`, apply 또는
recover를 호출하지 않는다. 승인 후 apply가 성공해도 기존 material repair를 resume하지 말고 새
canonical observation/continuation에서 closure와 MaterialAppearanceApproval을 다시 만든다. 상세
운영 문구는 [Material Identity Split 프롬프트](MATERIAL_IDENTITY_SPLIT_PROMPTS_KO.md)를 따른다.
