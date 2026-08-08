# 새 레퍼런스 자산 단계별 검증 프롬프트

이 문서는 새 레퍼런스 이미지를 제공한 뒤 사용자가 Codex 채팅에 복사해 입력할 수 있는 실사용 프롬프트 모음입니다. 현재 저장소의 V0.4~V0.9 계약과 CLI를 기준으로 하며, 각 단계의 승인 경계를 유지합니다.

기계 판정의 원본은 JSON 계약과 보고서입니다. PDF는 사용자가 검토하기 쉬운 파생 보고서이며 JSON을 대체하지 않습니다.

이미 완성된 수동 제작 `.blend`/`.fbx`/`.glb`를 가져오는 작업은 레퍼런스 이미지
프롬프트가 아니라 [External Static Asset Intake 가이드](EXTERNAL_STATIC_ASSET_INTAKE_KO.md)를
사용합니다.

## 사용 방법과 placeholder

`text` 코드 블록은 Codex 채팅에 붙여 넣는 프롬프트입니다. 문서 안의 `powershell` 블록은 구현된 CLI 표면을 확인하기 위한 운영자 참고이며, 일반 사용자는 Codex가 MCP 또는 저장소 명령을 대신 실행하도록 요청할 수 있습니다. 다만 InteriorScope처럼 계약상 interactive 수동 입력만 허용된 전용 승인은 Codex가 대신 승인할 수 없습니다.

| Placeholder | 교체할 값 | 예시 |
|---|---|---|
| `<JOB_ID>` | 새 자산의 고유 lowercase job ID | `temple_validation_01` |
| `<REFERENCE_PATH>` | 기본 레퍼런스 이미지의 절대 경로 | `E:\References\temple.png` |
| `<MODE>` | `concept` 또는 `measured` | `concept` |
| `<REFERENCE_CONTENT_SCOPE>` | `full_reference` 또는 `primary_object_only` | `primary_object_only` |
| `<TARGET_SUBJECT>` | 오브젝트 전용 범위에서 만들 대상의 명확한 설명 | `이미지 중앙의 노란 잠수 자동차` |
| `<EXECUTION_POLICY>` | `standard` 또는 `background_exterior` | `standard` |
| `<DELIVERY_SCOPE>` | 빠른 경로의 `preview_only` 또는 `portable_package` | `preview_only` |
| `<WORKFLOW_ID>` | Codex가 보고한 V0.8 workflow ID | 실제 보고값 |
| `<STEP_ID>` | V0.8 workflow가 보고한 현재 agent/review step ID | 실제 보고값 |
| `<QA_RUN_ID>` | Codex가 보고한 V0.6 QA run ID | 실제 보고값 |
| `<REGISTRATION_ID>` | semantic reference mask candidate의 고유 registration ID | `maskset-01` |
| `<MANIFEST_SHA256>` | 등록할 mask candidate manifest의 정확한 SHA-256 | 실제 보고값 |
| `<CANDIDATE_ID>` | 적용을 검토할 V0.6 후보 ID | 실제 보고값 |
| `<TRIAL_ID>` | standard candidate review의 격리 trial ID | 실제 보고값 |
| `<DECISION_SHA256>` | candidate review decision manifest의 정확한 SHA-256 | 실제 보고값 |
| `<CONVERGENCE_SESSION_ID>` | Codex가 보고한 optional standard V0.6 convergence session ID | 실제 보고값 |
| `<TARGET_DIRECT_SCORE>` | 계획할 direct score 목표. 현재 점수보다 낮을 수 없음 | `0.78` |
| `<TARGET_SILHOUETTE_IOU>` | 계획할 silhouette IoU 목표. 현재 값보다 낮을 수 없음 | `0.80` |
| `<ALLOWED_TARGET_IDS>` | 자동 후보 선택을 허용할 existing semantic ID 목록 | Codex가 보고한 실제 ID |
| `<MAX_ITERATIONS>` | bounded convergence 반복 상한. `1`~`5` | `3` |
| `<MINIMUM_ITERATION_GAIN>` | iteration별 최소 direct-score 개선량 | `0.005` |
| `<RUN_ID>` | Codex가 보고한 V0.7 optimization run ID | 실제 보고값 |
| `<PLAN_SHA256>` | 현재 계획 파일의 정확한 SHA-256 | 실제 보고값 |
| `<PROFILE_ID>` | `fbx_interchange` 또는 `portable_gltf` | `fbx_interchange` |
| `<PACKAGE_ID>` | 생성하거나 검증할 package ID | 실제 보고값 |
| `<HANDOFF_ID>` | 생성할 Destination Handoff ID | 실제 보고값 |
| `<OPTIONAL_VIEW_PATH>` | 추가 정면·측면·평면도 파일의 절대 경로 | `E:\References\temple_front.png` |
| `<OPTIONAL_DIMENSIONS>` | 단위와 허용 오차를 포함한 치수 목록 | `전체 폭 12.0 m, 허용 오차 0.02 m` |
| `<VIEW_KIND>` | `front`, `right`, `top`, `blueprint`, `cad` 중 하나 | `front` |
| `<SCOPE_SHA256>` | InteriorScope draft의 정확한 SHA-256 | 실제 보고값 |
| `<ARTIFACT_FINGERPRINT>` | V0.8 approval 대기 상태가 보고한 정확한 artifact fingerprint | 실제 보고값 |
| `<INPUT_FINGERPRINT>` | agent step이 요구한 정확한 input fingerprint | 실제 보고값 |
| `<MATERIAL_ID>` | 안정적인 material ID | 실제 보고값 |
| `<CONVERSION_ID>` | V0.7 material conversion ID | 실제 보고값 |
| `<PROBE_ID>` | V0.9 environment probe ID | 실제 보고값 |
| `<AUDIT_ID>` | V0.9 workspace audit ID | 실제 보고값 |
| `<REPORT_ID>` | V0.9 stability PDF report ID | 실제 보고값 |
| `<DESTINATION_HINT>` | 선택적인 목적지 설명. 지원을 뜻하지 않음 | `Unity 6 계열 프로젝트 검토 예정` |
| `<GEOMETRY_REVISION_REQUEST>` | 다시 고칠 큰 실루엣·비율·중형 구조 설명 | 사용자의 실제 요청 |
| `<INTERIOR_REQUEST>` | 허용할 층·공간·가구 범위와 제외 대상 | 사용자의 실제 요청 |
| `<REVISION_REQUEST>` | V0.6 후보로 달성할 국소 수정 목적 | 사용자의 실제 요청 |

교체 예:

```text
교체 전:
- job_id: <JOB_ID>
- reference_path: <REFERENCE_PATH>
- mode: <MODE>

교체 후:
- job_id: temple_validation_01
- reference_path: E:\References\temple.png
- mode: concept
```

`<OPTIONAL_DIMENSIONS>`처럼 현재 작업에 없는 값은 문장째 삭제합니다. Codex가 보고하지 않은 ID나 SHA-256을 추측해서 채우지 마세요.

## 반드시 지킬 기본 원칙

- 새로운 자산은 항상 새로운 lowercase job ID를 사용합니다. 유효 형식은 `[a-z0-9][a-z0-9_-]{0,63}`입니다.
- `floating_island`, `geometry_showcase`, `measured_box`, `first_reference_test`는 예약된 example ID이므로 새 작업에 사용하지 않습니다.
- 단일 이미지의 기본값은 `concept` mode입니다. 정사영 도면이나 명시적 치수가 처음부터 있으면 `measured`를 선택합니다.
- `standard` 경로에서는 프록시 승인 전 재질, 최적화, package 또는 export를 진행하지 않습니다. `background_exterior`는 1.1의 명시적인 immutable fast plan에서만 일반 프록시 승인을 생략합니다.
- 실내는 기본 비활성화입니다. 명시적 요청, InteriorScope draft, 정확한 hash의 수동 승인이 모두 있어야 합니다.
- 보이지 않는 형상은 복원된 사실이 아니라 `inferred`로 기록합니다.
- 단일 카메라의 화면상 오프셋은 숨은 좌우·깊이 위치의 증거가 아닙니다. 새 ModelingPlan은 `spatial_v1` 자산 로컬 축과 부착 관계를 기록하고 V0.4에서 검사합니다.
- V0.6 점수는 완성도 백분율이 아닙니다. 고정 카메라에서 산출된 비교 지표일 뿐입니다.
- 큰 실루엣, 비율, 구조가 잘못됐으면 V0.4 authoring으로 돌아갑니다.
- 이미 맞는 큰 형상을 유지하면서 국소적인 유사도 오차만 고칠 때 V0.6 guarded revision을 사용합니다.
- V0.7은 run-owned 파생 결과만 만들며 canonical SceneSpec, geometry payload, authoring `.blend`, source texture를 변경하지 않습니다.
- V0.9는 필수 모델링 단계가 아니라 read-only audit와 선택적 Destination Handoff 계층입니다. 외형을 개선하지 않습니다.
- Unity, Unreal 또는 다른 엔진의 runtime parity를 검증 없이 주장하지 않습니다.
- “이후 전부 승인” 같은 포괄적 승인은 InteriorScope, V0.6 revision, V0.7 optimization, Destination Handoff의 전용 exact-hash 승인을 대체하지 못합니다.
- 새 `standard revise_asset`의 기본 전략은 `candidate_review`입니다. RevisionPlan 사전 승인을 생략하고 격리된 before/after build·QA 뒤 exact decision SHA-256 승격 승인 한 번을 받습니다. `manual_guarded`는 기존 후보별 사전 승인과 1회 적용을 명시적으로 유지하며, bounded convergence는 별도 opt-in입니다. 일반적인 “전부 승인”은 어느 전문 승인도 아닙니다.
- bounded convergence는 default 3회, hard maximum 5회이며 목표에 도달할 때까지 무제한 실행하지 않습니다. 카메라, 재질, custom-mesh geometry, generated-target-only와 계획 밖 ID·경로는 자동 권한 밖입니다.
- `standard`가 기본 실행 정책입니다. `background_exterior`는 실내·실측·리깅·게임 로직이 없는 정적 배경 외관에만 작업 계획 전에 명시적으로 선택합니다.
- 빠른 경로도 다른 파이프라인이 아닙니다. 동일한 V0.4~V0.7 계약을 쓰되 일반 검토만 줄이고 전용 exact-hash 승인은 유지합니다.
- 레퍼런스의 모델링 범위는 실행 정책과 별개입니다. `full_reference`는 기존
  전체 장면 동작이고, `primary_object_only`는 명시한 `<TARGET_SUBJECT>`와
  구조적으로 연결되거나 필요한 부품만 허용합니다.
- `primary_object_only`에서는 독립 지형, 바닥, 바위, 식생, 잔해, 소품,
  배경판과 대기 효과를 제외합니다. 대상이 모호하면 job 생성 전에 확인합니다.
- content scope와 target subject는 job 생성 후 바꾸지 않습니다. 같은
  reference를 다른 범위로 만들려면 새 job ID를 사용합니다.

---

## 1. 가장 짧은 시작 프롬프트

이미지를 첨부하거나 `<REFERENCE_PATH>`를 제공한 뒤 아래 프롬프트를 붙여 넣습니다. V0.8 orchestration은 host step과 승인 경계를 관리하지만, agent-authored SceneSpec을 자동으로 승인하지 않습니다.

### 1A. 원하는 오브젝트만 프록시로 만들기

```text
현재 저장소의 V0.8 orchestration을 사용해 새 레퍼런스에서 원하는
오브젝트의 프록시까지만 만들어줘.

- job_id: <JOB_ID>
- reference_path: <REFERENCE_PATH>
- mode: <MODE>
- reference_content_scope: primary_object_only
- target_subject: <TARGET_SUBJECT>
- execution_policy: standard

<TARGET_SUBJECT> 본체와 구조적으로 붙거나 기능상 필요한 부품만 포함해.
독립된 지형, 바닥, 바위, 식생, 잔해, 주변 소품, 배경판, 대기 효과는
모델링하지 마. ModelingPlan에는 primary/supporting/context 역할을,
SceneSpec에는 모든 객체의 qa_role:primary 또는 qa_role:supporting을
명시하고 context 객체가 들어가면 completion을 기록하지 마.

plan_short_workflow로 새 job과 workflow를 계획하고 다음까지만 진행해:
reference analysis → camera solution → modeling plan → proxy SceneSpec
→ build → render → inspect → validate → proxy approval 대기.

대상이 모호하면 job을 만들기 전에 멈춰서 확인할 내용을 보고해.
V0.5 이후 단계로 자동 진행하지 마.
```

붙어 있는 바퀴·문·범퍼·지붕·손잡이는 `supporting`으로 포함할 수 있지만,
옆의 나무·바위·도로·건물·바닥은 독립된 context이므로 제외합니다.

### 1B. 전체 장면을 프록시로 만들기

아래 기존 프롬프트는 `full_reference` 기본값을 사용합니다.

```text
현재 저장소의 V0.8 orchestration을 사용해 새 레퍼런스 자산의 프록시까지만 만들어줘.

- job_id: <JOB_ID>
- reference_path: <REFERENCE_PATH>
- mode: <MODE>
- reference_content_scope: full_reference

먼저 job ID가 유효하고 고유한지, 예약된 example ID가 아닌지 확인해.
다음 현재 CLI 형태로 workflow를 계획해:
uv run cbm workflow-plan --request "새 레퍼런스 프록시 검증"
--job-id <JOB_ID> --reference-path <REFERENCE_PATH>
--intent new_asset --scope proxy_only --mode <MODE>

생성된 workflow ID를 확인하고 workflow-resume으로 상태를 진행해.

다음 범위까지만 수행해:
reference analysis
→ camera solution
→ modeling plan
→ proxy SceneSpec
→ build
→ render
→ inspect
→ validate
→ build PDF 또는 preview 검토 자료 생성
→ proxy approval 대기

agent-authored step에서는 현재 input fingerprint에 결속된 산출물과 completion marker를 사용해.
단일 이미지에서 보이지 않는 부분은 inferred로 기록하고 실제 치수를 안다고 주장하지 마.

프록시 승인 전에는 V0.5 재질·텍스처·셰이더, V0.6 Visual QA,
V0.7 최적화·package·export, V0.9 handoff를 시작하지 마.
마지막에는 workflow ID, 현재 정지 단계, preview와 PDF 경로,
validation 결과, proxy approval에 필요한 step ID와 artifact fingerprint를 보고해.
```

### 1.1 선택적 배경 외관 빠른 시작

실내가 필요 없는 단순 배경 건물·장식물이고 사용자가 중간 검토를 최소화하려는 경우에만 사용합니다. 아래 프롬프트는 PowerShell 실행을 사용자에게 요구하지 않고 Codex가 공개 MCP 표면을 사용하게 합니다.

```text
현재 저장소의 V0.8 orchestration으로 <REFERENCE_PATH>의 새 레퍼런스를 처리해.

- job_id: <JOB_ID>
- execution_policy: background_exterior
- delivery_scope: preview_only
- mode: concept
- intent: new_asset
- scope: auto
- destination_kind: engine_neutral
- include_destination_handoff: false

plan_short_workflow를 위 값으로 호출하고 후속 host/agent 단계를 MCP로 진행해.
하나의 중간 상세 외관 SceneSpec을 작성한 뒤 최대 2회의 bounded pre-QA fit,
build, render, inspect, validate, asset-local 5-view host render와 실제 agent visual review,
V0.5 로컬 결정론적 재질·셰이더,
V0.6 canonical 직접 reference QA 정확히 1회, machine quality JSON,
QA PDF와 통합 PDF 생성까지 진행해.

프록시·상세·swatch·QA의 일반 승인만 생략해.
InteriorScope, measured view, guarded revision, optimization plan과 handoff의
전용 승인을 추론하거나 생성하지 마.
외부 texture/image provider, generated QA target, 자동 revision,
실내, rig, animation, gameplay와 engine-specific 변환은 사용하지 마.

완료하면 status=completed, milestone=delivered_for_review,
quality_status=passed|needs_revision|unscorable, standard workflow 권장 여부,
workflow ID, preview, 직접 QA JSON, quality JSON,
다각도 plan/manifest/report/visual-review JSON, QA PDF·통합 PDF와 각 sidecar 경로를
보고해. 다각도 review 권고를 자동 approval이나 revision 적용으로 해석하지 마.
high-severity visual finding은 숨기지 말고 needs_revision으로 전달해.
primary evidence가 신뢰 불가능하면 unscorable로 전달하고 품질 합격을 주장하지 마.
실내·실측·rig·animation·gameplay·engine-specific 요구나 unsafe ambiguity처럼
실제 scope·안전 경계를 벗어나는 위험이 발견될 때만 agent completion을 기록하지
말고 requires_standard_workflow로 멈춘 뒤 별도 standard workflow가 필요한
이유를 보고해.
```

처음부터 engine-neutral package까지 필요하면 종료 범위만 바꿉니다.

```text
<REFERENCE_PATH>의 새 정적 배경 외관을 <JOB_ID>로 만들고
engine-neutral <PROFILE_ID> package까지 준비해.

plan_short_workflow를 다음 값으로 호출해:
- execution_policy: background_exterior
- delivery_scope: portable_package
- mode: concept
- profile_id: <PROFILE_ID>
- destination_kind: engine_neutral
- intent: new_asset
- scope: auto
- include_destination_handoff: false

일반 중간 검토는 생략하되 V0.7 preflight 뒤 review_plan.json,
optimization_review.json과 현재 review_plan의 정확한 SHA-256을 계산해 보고하고 멈춰.
내가 그 exact hash를 승인하기 전에는 optimize, package와 round trip을 실행하지 마.
승인 뒤에는 derived optimization, immutable package, clean-import round trip,
export/full PDF까지 진행하고 canonical SceneSpec, geometry, authoring blend와
source texture가 바뀌지 않았음을 확인해.
```

완료된 빠른 preview를 나중에 package로 확장할 때도 기존 workflow를 고치지 않습니다.

```text
현재 <JOB_ID>의 완료된 background_exterior preview가 package 확장 조건을
충족하는지 읽기 전용으로 확인해.
충족하면 같은 job에 새 immutable V0.8 workflow를
intent=portable_package, execution_policy=background_exterior,
delivery_scope=portable_package, profile_id=<PROFILE_ID>로 계획해.
V0.7 exact optimization-plan 승인에서 멈추고 기존 preview workflow는 변경하지 마.
```

### 1.2 빠른 경로와 표준 단계별 프롬프트의 관계

`background_exterior`를 사용하더라도 V0.4~V0.6 구현이 생략되는 것은 아닙니다. 사용자가 단계 1, 2, 2A, 5, 6의 프롬프트와 일반 승인을 각각 반복 입력하지 않아도 하나의 immutable workflow가 같은 계약을 제한된 범위에서 순서대로 실행하는 방식입니다.

| 선택 | 사용자가 먼저 붙여 넣을 프롬프트 | 내부에서 수행되는 범위 | 추가로 필요한 사용자 승인 |
|---|---|---|---|
| `standard` | 아래 단계 0~11에서 필요한 프롬프트 | 요청한 각 단계를 승인 경계별로 수행 | 프록시·상세·재질·QA 검토와 모든 전문 승인. 단, 새 revise_asset은 기본 candidate_review로 plan 사전 승인 대신 최종 decision 승격 승인 1회 |
| `background_exterior + preview_only` | 1.1의 빠른 preview 프롬프트 하나 | V0.4 중간 상세 외관, bounded pre-QA fit, build/render/inspect/validate, 5-view host/agent geometry review, V0.5 로컬 재질, V0.6 직접 QA 1회, quality JSON, 통합 PDF | 일반 프록시·상세·swatch·QA 승인 없음; multiview agent completion은 유지 |
| `background_exterior + portable_package` | 1.1의 빠른 package 프롬프트 하나 | 위 preview 범위와 V0.7 preflight·최적화·package·round trip | V0.7 optimization-plan의 exact SHA-256 승인 |

빠른 preview 완료 후 V0.9 audit는 필요할 때 별도로 실행합니다. Destination Handoff도 통과한 V0.7 package를 대상으로 별도 계획과 exact-hash 승인을 사용합니다.

### 1.3 Artifact lifecycle 충돌이 보고될 때

새 fast workflow는 material scaffold와 authored candidate를 workflow-owned
경로에 따로 만들고, strict host promotion으로만 canonical MaterialPlan을
갱신합니다. 사용자는 이 내부 단계 때문에 PowerShell을 직접 실행할 필요가
없습니다.

`orchestration_artifact_conflict`가 보고되면 다음 프롬프트를 사용합니다.

```text
<JOB_ID>의 workflow <WORKFLOW_ID>가
orchestration_artifact_conflict로 차단된 이유를 읽기 전용으로 점검해.
기존 workflow, completion marker, attempt receipt와 canonical 파일은 수정하지 마.
이 충돌을 requires_standard_workflow나 QA 품질 문제로 재분류하지 마.
예상된 downstream supersession인지, 계획되지 않은 canonical/source 변조인지
exact artifact path와 SHA-256으로 구분해 보고해.
기존 blocked workflow는 복구하지 말고, 안전하면 수정된 lifecycle 계약을 쓰는
새 workflow의 요청·종료 범위·승인 경계만 제안한 뒤 내 확인을 기다려.
```

기존 blocked workflow에는 새 계약을 소급 적용하지 않습니다. 새 workflow부터
scaffold/authored candidate, promotion receipt, exact QA run, workflow-owned PDF와
derived snapshot을 사용합니다.

다음 중 하나라도 해당하면 빠른 경로를 선택하지 않고 `standard`를 사용합니다.

- 정면·측면·평면도, 청사진 또는 실제 치수를 함께 사용해야 함
- 실내, rig, skinning, animation, gameplay 또는 engine-specific 결과가 필요함
- 중요 전경 자산이거나 단계별 미술 검토가 필요함
- 외부 texture/image provider 또는 generated QA target이 필요함
- 여러 번의 V0.6 guarded revision을 계획하고 있음
- 빠른 QA가 `needs_revision` 또는 `unscorable`이고 사용자가 실제 외형 개선을
  계속하려 함

작업 생성 전에 어느 정책이 적절한지만 확인하려면 다음 프롬프트를 사용합니다.

```text
아직 새 job, workflow 또는 산출물을 만들지 말고
<REFERENCE_PATH>와 내 요청을 읽기 전용으로 검토해.

다음 중 하나를 권장해:
- execution_policy=standard
- execution_policy=background_exterior, delivery_scope=preview_only
- execution_policy=background_exterior, delivery_scope=portable_package

단일 concept reference인지, static exterior인지,
실내·실측·rig·animation·gameplay·외부 provider 요구가 없는지 확인하고
권장 정책, 종료 범위, 판단 근거, 생략되는 일반 승인,
여전히 필요한 전용 exact-hash 승인을 보고해.
검토가 끝날 때까지 create_job이나 plan_short_workflow를 호출하지 마.
```

빠른 경로가 `requires_standard_workflow`로 차단되면 기존 workflow를 수정하거나
실패 재시도로 우회하지 않습니다. 단순한 high visual finding은 이 차단 사유가
아니며 completed delivery의 `quality_status=needs_revision`으로 남습니다.

완료된 빠른 preview의 품질 상태를 검토하려면 다음 프롬프트를 사용합니다.

```text
<JOB_ID>의 완료된 background_exterior workflow <WORKFLOW_ID>를 읽기 전용으로 검토해.
quality report, exact V0.6 QA run, QA PDF와 combined PDF의 hash binding을 확인해.
execution status와 quality_status를 분리해서 보고하고,
primary/supporting/decorative/ground_background finding과
recommended standard revision target을 요약해.
quality_status가 needs_revision 또는 unscorable여도 기존 workflow를
blocked로 재분류하거나 자동 revision을 적용하지 마.
내가 외형 개선을 요청할 때 사용할 별도 standard workflow 계획만 제안해.
```

```text
<JOB_ID>의 background_exterior workflow <WORKFLOW_ID>가
requires_standard_workflow로 차단된 이유를 읽기 전용으로 검토해.

기존 빠른 workflow, QA run과 canonical evidence는 변경하지 마.
차단 finding과 machine report 경로를 먼저 보고하고,
같은 job의 current evidence를 입력으로 사용하는 새 immutable standard workflow의
intent, scope, 첫 승인 경계와 예상 단계를 제안해.
내가 전환 계획을 확인하기 전에는 새 workflow를 생성하거나 canonical 파일을 수정하지 마.
```

## 2. 전체 파이프라인 조율 프롬프트

이 프롬프트는 최종 목표를 선언하지만 무인 일괄 실행을 승인하지 않습니다. Codex는 현재 단계의 승인 경계마다 멈춰야 합니다.

```text
새 자산 <JOB_ID>를 최종 engine-neutral static-asset package까지
단계적으로 검증하도록 V0.8 workflow를 계획해.

- reference_path: <REFERENCE_PATH>
- mode: <MODE>
- portable profile 목표: <PROFILE_ID>
- 선택적 목적지 힌트: <DESTINATION_HINT>

다음 현재 CLI 형태를 사용해 intent=new_asset, scope=full로 계획하되,
실제 요청 문장에는 전체 단계가 승인 경계형이라는 점을 포함해:
uv run cbm workflow-plan --request "승인 경계형 전체 static-asset 검증"
--job-id <JOB_ID> --reference-path <REFERENCE_PATH>
--intent new_asset --scope full --mode <MODE> --profile <PROFILE_ID>

다음 경계를 절대로 한 번에 통과하지 마:

1. V0.4 proxy geometry 작성·검증과 5-view host/agent review 후 proxy approval
2. V0.4 detail geometry 작성·검증과 5-view host/agent review 후 detail approval
3. V0.5 MaterialPlan, ShaderRecipe, swatch, material PDF 후 material approval
4. V0.6 직접 Visual QA와 QA PDF 후 QA review
5. standard revise_asset은 기본 candidate_review로 격리 before/after 평가 후 exact decision SHA-256 승격 승인 1회
5A. camera/material/custom-mesh/redesign처럼 candidate envelope 밖이면 explicit manual_guarded 후보/plan 승인
5B. 수정 승인이 반복될 때에만 선택적으로 standard bounded convergence plan을 만들고 exact plan SHA-256 승인
6. V0.7 preflight와 review plan 후 exact plan SHA-256 승인
7. V0.7 package와 clean-import round trip 후 portable final review
8. 선택적으로 V0.9 read-only audit
9. passed package가 있을 때만 선택적으로 Destination Handoff plan과 exact-hash 승인

현재 단계에서 수행 가능한 host step만 실행하고,
agent-authored artifact 또는 승인 단계에 도달하면 멈춰서
workflow ID, 단계 ID, 입력·산출물 fingerprint, 검토 파일,
정확히 필요한 다음 승인이나 작업을 보고해.

generic workflow approval로 InteriorScope, V0.6 revision 또는 convergence plan,
V0.7 optimization 또는 Destination Handoff 승인을 대신하지 마.
Unity/Unreal 전용 import, prefab/actor, engine material graph 또는 runtime parity는 범위 밖이다.
```

---

## 3. 단계별 복사 프롬프트

### 단계 0 — 환경과 호환성 사전 확인

이 단계는 read-only입니다. `blender-compat`는 보고서를 새로 쓰므로 여기서는 실행하지 않고 기존 compatibility evidence만 확인합니다.

```text
새 자산 <JOB_ID> 작업 전 read-only 사전 점검을 해줘.
아직 job, workflow, 보고서 또는 다른 파일을 생성·수정하지 마.

1. 현재 디렉터리가 저장소 루트인지 확인해.
2. uv run cbm doctor를 실행해 Repository, Workspace, Blender, Codex 상태를 확인해.
3. 기존 Blender compatibility evidence를 읽어 Blender 5.0.1 전체 검증과
   BLENDER_EEVEE 선택 증거가 current인지 확인해.
4. 기존 evidence가 없거나 stale이면 blender-compat를 자동 실행하지 말고
   별도 실행이 필요하다고 보고해.
5. workspaces/<JOB_ID>와 관련 workflow가 이미 존재하는지 확인해.
6. <JOB_ID>가 lowercase 형식이고 예약된 example ID가 아닌지 확인해.
7. <REFERENCE_PATH>가 읽을 수 있는 이미지인지 확인하되 복사하지 마.

마지막에는 pass/warn/fail, 발견한 충돌, 생성될 첫 파일,
다음 단계 진입 가능 여부만 보고해.
```

호환성 evidence를 새로 만들기로 별도 결정한 경우에만 사용할 명령:

```powershell
uv run cbm blender-compat --smoke-exports
```

### 단계 1 — 새 job과 V0.4 레퍼런스 분석

`<MODE>`는 단일 이미지면 보통 `concept`, 정사영·치수가 처음부터 있으면 `measured`입니다.

```text
<REFERENCE_PATH>를 immutable primary evidence로 사용해
새 job <JOB_ID>의 V0.4 프록시를 만들어줘.

- mode: <MODE>
- 보이지 않는 형상: inferred
- 단위: meters
- +Z up, -Y camera-forward

V0.8 workflow-plan을 다음 현재 CLI 형태로 생성하고
고유 job 생성부터 proxy approval 대기까지 조율해.
uv run cbm workflow-plan --request "V0.4 새 자산 프록시 검증"
--job-id <JOB_ID> --reference-path <REFERENCE_PATH>
--intent new_asset --scope proxy_only --mode <MODE>

필수 작업:
1. 입력 파일 복사와 SHA-256 기록
2. analyze-reference 실행
3. reference_analysis.json과 camera_solution.json 검토
4. stable semantic ID를 가진 modeling_plan.json 작성
   - assembly_consistency_policy=spatial_v1, asset-local 길이/좌우/수직축과 root 기록
   - 모든 object의 assembly_role 분류 및 attached object의 parent-local 관계 기록
   - 중심 부품은 center_plane/coaxial, 포함·장착 부품은 bbox_containment/surface_contact 사용
   - side_specific은 정사영·청사진·치수 또는 명시적 사용자 근거가 있을 때만 사용
   - 한쪽 사선 이미지의 2D 위치를 숨은 좌우·깊이 좌표로 그대로 복사하지 않음
   - 작은 창문 무늬, 이음선, 리벳, 라벨, 얕은 패널과 반복 마크를 먼저 분류
   - 실루엣·구조·gameplay·물리적 투명성에 필요하지 않으면 surface_details로 기록
   - 각 surface detail의 parent, material, PBR channel, UV 전략, bbox와 confidence 기록
5. SceneSpec 0.2.0 proxy 작성
   - surface_details로 분류한 ID를 개별 geometry object로 중복 생성하지 않음
6. build → render → inspect → validate
7. build scope PDF 또는 preview를 사용자 검토용으로 제시

SceneSpec과 modeling plan은 현재 input fingerprint에 결속된
agent-authored artifact로 처리하고 completion marker를 기록해.
카메라 가정과 underconstrained 항목을 명시해.

validation이 통과해도 프록시가 승인됐다고 간주하지 마.
재질, Visual QA revision, 최적화, package, export를 시작하지 말고
workflow ID, preview/PDF, semantic ID 목록, validation 결과,
입력 SHA-256, proxy approval용 step ID와 artifact fingerprint를 보고한 뒤 멈춰.
```

### 단계 2 — V0.4 외형 상세화

프록시를 승인한 뒤 큰 실루엣과 중형 구조를 개선합니다.

```text
승인된 <JOB_ID> 프록시를 기준으로 V0.4 외형 상세화 패스를 수행해.

잠금:
- 승인된 비교 카메라와 렌더 해상도
- 기존 stable semantic ID
- 기존 assembly_frame과 assembly relationship ID·근거·허용 오차
- nominal scene size의 기준
- 사용자가 변경을 요청하지 않은 객체 위치
- immutable input

우선순위:
1. 전체 실루엣과 주요 비율
2. 큰 덩어리 사이의 깊이·높이 관계
3. 레퍼런스에서 보이는 중형 구조
4. geometry.kind와 modifier의 적합성
5. 메시 유효성

미세 문양, 고밀도 subdivision, 재질로 가릴 디테일,
보이지 않는 내부 구조를 임의로 만들지 마.
이미 surface_details로 분류한 항목을 별도 메시로 되돌리지 마.
필요한 경우 이전 SceneSpec을 history에 보존하고 canonical SceneSpec 또는
geometry payload를 최소 범위로 수정해.

수정 후 build → render → inspect → validate를 실행하고
build scope PDF 또는 preview를 갱신해.
변경한 semantic ID, geometry.kind, 전후 dimensions/vertex/polygon 수,
카메라와 변경하지 않은 ID 보존 여부, assembly validation 결과를 보고해.
고정 카메라 실루엣을 더 닮게 만들더라도 중심면·동축·포함·접촉 관계를
위반하지 마. 필수 assembly 관계가 실패하면 상세 형상 승인 대기 전에
V0.4 SceneSpec을 최소 수정해 다시 검증해.
상세 형상 승인 대기 상태에서 멈추고 V0.5 이후로 넘어가지 마.
```

큰 외형 문제가 뒤늦게 발견됐을 때 재진입:

```text
<JOB_ID>의 후속 단계 결과를 보니 큰 외형이 만족스럽지 않다.
V0.6 국소 후보 적용으로 억지로 맞추지 말고 V0.4 authoring으로 돌아가
다음 문제를 수정할 계획부터 작성해:

<GEOMETRY_REVISION_REQUEST>

현재 카메라, semantic ID, canonical/derived 구분을 조사하고
영향받을 SceneSpec 경로와 geometry payload, downstream material/QA/package의
stale 범위를 먼저 보고해. 승인되지 않은 변경은 수행하지 마.

계획 검토 후 허용된 canonical geometry만 최소 수정하고
build → render → inspect → validate를 다시 실행해.
기존 V0.5~V0.9 산출물을 삭제하거나 성공으로 재사용하지 말고 stale로 보고해.
새 상세 형상 승인 대기 상태에서 멈춰.
```

### 단계 2A — 새 workflow의 V0.4 다각도 형상 검토

새로 계획되는 프록시·상세·배경 형상 workflow는 `validate` 뒤, PDF나 다음 단계 전에
이 검토를 포함합니다. 사용자가 직접 `.blend`를 열지 않아도 Codex가 렌더 생성에서
멈추지 않고 실제 다섯 시점을 읽었는지 확인하려면 다음 프롬프트를 사용합니다.

```text
<JOB_ID>의 current authored spatial_v1 V0.4 geometry를 workflow-owned 다각도
형상 검토로 확인해.

먼저 current SceneSpec, ModelingPlan, authoring blend와 embedded build fingerprint를
검증해. 모든 ModelingPlan scope_role=primary|supporting과
assembly_role=root|attached의 합집합을 target으로 사용해. primary/supporting인
free_standing 객체도 누락하지 마.

asset-local assembly frame의 임시 front, right, top, rear, oblique 카메라에서
각각 beauty, silhouette, object_id, wireframe의 정확히 4개 pass를 렌더해.
임시 카메라를 authoring .blend에 저장하거나 canonical V0.6 비교 카메라를 바꾸지 마.

plan.json, render_manifest.json, report.json과 20개 PNG의 path/hash를 검증한 뒤
렌더 생성만으로 완료 처리하지 마. 다섯 시점의 beauty와 wireframe을 실제로 모두
읽고 cross-view shape coherence, proportion, orientation, assembly와 명백한 topology
artifact를 판정해. exact plan, render manifest, structural report SHA-256에 결속된
GeometryMultiviewVisualReview 0.6.0 visual_review.json을 작성해.

한 시점에서만 보이지 않는 ID는 occlusion advisory로 보고 다른 시점과 함께 판단해.
모든 시점에서 사라진 target 또는 필수 assembly 관계 실패만 구조적 V0.4 재진입
근거로 사용해. 보정된 각도별 reference가 없으므로 측면·후면 likeness는
unscorable로 유지해.

결과가 warning이면 bounded parametric V0.4 revision 또는 additional evidence를,
error이면 manual redesign review를 권고할 수 있지만 어떤 geometry도 자동 승인·적용하지 마.
outcome, v04_reentry, finding별 view/target/action, automatic_revision_authorized=false,
권위 있는 JSON 경로/hash와 다각도 이미지가 포함된 PDF 경로를 보고해.
```

이미 생성된 run을 변경 없이 다시 보고받을 때:

```text
<JOB_ID>의 geometry multiview run <RUN_ID>을 read-only로 검토해.
plan.json, render_manifest.json, report.json, visual_review.json의 exact hash binding과
5 views × 4 passes 완전성을 먼저 검증해. 다섯 beauty/wireframe을 실제로 읽은
review인지, target이 primary/supporting 및 root/attached 합집합인지 확인해.

per-view occlusion advisory와 all-view structural failure를 구분하고, cross-view
finding, V0.4 parametric revision 또는 manual redesign-review 권고, limitation을
요약해. 보정되지 않은 시점의 유사도 점수나 자동 승인·적용을 주장하지 말고,
machine JSON/hash가 authoritative이며 PDF는 이미지가 포함된 review aid라고 명시해.
어떤 canonical 파일도 수정하지 마.
```

기존 job이나 이미 만들어진 workflow plan에는 이 단계가 없을 수 있으며 자동으로
소급 추가하지 않습니다. 해당 경우에는 omit, `not_applicable` 또는 unavailable로
보고하고 새 immutable workflow가 필요한지 제안만 합니다.

### 단계 3 — 선택적 멀티뷰·청사진·치수

추가 자료가 없으면 이 단계를 건너뜁니다. `add-view`는 기존 job을 재생성하지 않지만 `concept`를 자동으로 `measured`로 바꾸지도 않습니다.

추가 정면·측면·평면도 등록:

```text
<JOB_ID>에 보조 뷰를 안전하게 추가할 계획을 확인해.

- view kind: <VIEW_KIND>
- view path: <OPTIONAL_VIEW_PATH>
- scale anchors 또는 치수: <OPTIONAL_DIMENSIONS>

기존 같은 kind의 view가 있는지 먼저 확인해.
없으면 uv run cbm add-view <JOB_ID> --kind <VIEW_KIND>
--image <OPTIONAL_VIEW_PATH>를 사용하고, 이미 있으면 --replace를 임의로 사용하지 말고 멈춰.

추가 후 입력 SHA-256과 job metadata를 보고하고 analyze-reference를 다시 실행해.
기존 job mode가 concept이면 add-view가 mode를 자동 변경하지 않았음을 명시하고,
measured 정확도가 검증됐다고 주장하지 마.
새 evidence 때문에 camera/modeling plan/SceneSpec에서 재검토할 항목을 보고한 뒤 멈춰.
```

Measured constraints 작성과 평가:

```text
<JOB_ID>의 명시적 도면·치수를 measured evidence로 검토해.

치수 요구사항:
<OPTIONAL_DIMENSIONS>

1. job mode와 등록된 source view, scale anchor를 확인해.
2. constraints/constraints.json이 없으면 uv run cbm init-constraints <JOB_ID>로 초기화해.
3. stable semantic ID를 대상으로 dimension, location, distance,
   align, equal_dimension 중 현재 구현된 constraint만 작성해.
4. 요청값, 단위 m, tolerance, evidence source를 명시해.
5. 최신 scene을 build/inspect한 뒤 uv run cbm evaluate-constraints <JOB_ID>를 실행해.
6. constraint ID별 requested, actual, residual, tolerance, status를 보고해.
7. depth, 가려진 부분, 대응점 부족 등 underconstrained 항목을 따로 보고해.

V0.4는 임의의 CAD 제약을 자동으로 완전 해결하는 솔버가 아니다.
실패 residual을 성공으로 바꾸거나 SceneSpec을 임의 수정하지 말고
필요한 guarded revision 계획을 제안한 뒤 승인 대기 상태로 멈춰.
```

### 단계 4 — 선택적 실내

> **외관 자산이면 이 단계를 건너뜁니다. InteriorScope가 없다는 것은 정상적인 `default_disabled` 상태입니다.**

실내가 필요한 경우에만:

```text
<JOB_ID>에 대해 사용자가 명시적으로 요청한 실내 범위만 draft로 작성해.

실내 요청:
<INTERIOR_REQUEST>

uv run cbm interior-scope-status <JOB_ID>로 현재 상태를 확인한 뒤,
uv run cbm interior-scope-init <JOB_ID>의 실제 지원 옵션만 사용해
policy, allowed/excluded semantic prefix, level, space,
furnishing boundary, evidence status를 명시한 draft를 만들어.

아직 실내 geometry를 만들지 마.
draft 경로, scope SHA-256, 허용·제외 범위, inferred/authored 항목,
사용자가 직접 실행해야 할 승인 명령을 보고하고 멈춰.
포괄적인 모델링 승인이나 workflow approval을 InteriorScope 승인으로 간주하지 마.
```

Codex가 보고한 정확한 hash와 승인 메모로 사용자가 직접 실행:

```powershell
uv run cbm interior-scope-approve <JOB_ID> --scope-sha256 <SCOPE_SHA256> --approval-note "사용자가 검토한 실내 범위 승인"
```

명령은 대화형으로 전체 `APPROVE <SCOPE_SHA256>` 문구를 다시 요구합니다. 승인 후에는 아래 프롬프트를 사용합니다.

```text
<JOB_ID>의 InteriorScope approval이 현재 draft의 <SCOPE_SHA256>과 정확히 일치하는지 확인해.
uv run cbm interior-scope-validate <JOB_ID>를 먼저 통과시켜.
승인된 prefix, level, space, furnishing policy 안의 static interior geometry만 작성하고
범위 밖 방, 복도, 가구, gameplay logic를 만들지 마.
수정 후 build → render → inspect → validate와 interior-scope-validate를 다시 실행하고
실내 범위 승인 대기 상태에서 멈춰.
```

### 단계 5 — V0.5 재질·텍스처·셰이더

```text
<JOB_ID>의 V0.5 material, texture, shader authoring을 시작해.

먼저 상세 geometry, stable semantic/material ID, 비교 카메라가 승인됐는지 확인해.
승인되지 않았거나 build fingerprint가 stale이면 재질 작업을 시작하지 마.

1. 필요하면 uv run cbm material-scaffold <JOB_ID>를 사용해 계약 뼈대를 생성해.
2. analysis/material_plan.json과 material별 ShaderRecipe 0.5.0을 작성해.
3. observed/inferred 표면 성질, mapping mode, real-world scale,
   UV 필요 여부와 texel-density 전략을 기록해.
4. base_color, normal, metallic, roughness, occlusion,
   emission, opacity 중 필요한 raw PBR 채널을 분리해 보존해.
   ModelingPlan의 non-omitted surface_details마다 실제 디테일이 포함된 UVMap
   image/hybrid TextureManifest를 만들고 exact surface_detail_ids와 요구 채널을 기록해.
   새 plan은 surface_detail_binding_policy=spatial_v1을 유지해.
   먼저 current scene inventory에서 parent object의 ordered polygon-corner UV fingerprint를
   확인하고, 각 detail을 parent semantic ID, 전용 material ID, exact UV hash,
   bounded uv_rect 또는 hash-bound mask, image-backed channel, strength,
   wrap=clamp에 결속해. 국소 디테일용 image texture에는 identity UV mapping을 사용하고,
   procedural noise가 필요하면 별도의 scaled coordinate path를 사용해.
   깨끗한 stylized 표면에 레퍼런스 근거 없는 검은 seam, panel grid, band, groove,
   scratch 또는 강한 normal relief를 전체 재질 패턴으로 추가하지 마.
   맵에 실제 디테일을 만들지 못했다면 coverage를 주장하지 말고 대기 또는 명시적
   omission으로 보고해.
5. Base Color는 sRGB, data channel은 Non-Color로 설정해.
6. Blender master shader와 portable/bake 결과를 분리해.
7. Blender 5에서 runtime feature probe가 가능한 whitelisted recipe만 사용해.
8. uv run cbm validate-material-contracts <JOB_ID>를 실행해.
9. 최신 build 뒤 uv run cbm inspect-materials <JOB_ID>와
   uv run cbm validate-material-fidelity <JOB_ID>를 실행해.
   fidelity warning은 숨기지 말고 swatch 검토 항목으로 보고해. 이 검사가 UV placement의
   의미상 정확성이나 레퍼런스 material match를 증명한다고 주장하지 마.
10. uv run cbm render-material-swatches <JOB_ID>를 실행해.
11. uv run cbm report-pdf <JOB_ID> --scope material로
    canonical JSON과 swatch를 투영한 material PDF를 생성해.

Unity, Unreal 또는 임의 엔진의 material graph로 자동 변환하지 마.
portable 결과는 raw PBR 의미와 알려진 bake loss만 기록해.
MaterialPlan, ShaderRecipe, texture manifest, validation JSON,
swatch와 PDF 경로를 보고하고 swatch 승인 대기 상태에서 멈춰.
```

### 단계 6 — V0.6 직접 Visual QA

```text
<JOB_ID>에 대해 직접 reference evidence를 우선하는 V0.6 Visual QA를 수행해.

QA run ID는 <QA_RUN_ID>를 사용해.
1. current SceneSpec/material/texture hash와 embedded build fingerprint를 확인해.
2. 실제 Blender 비교 카메라가 승인된 카메라와 일치하는지 확인해.
3. uv run cbm visual-qa <JOB_ID> --run-id <QA_RUN_ID>를 실행해
   정확히 다음 7개 pass를 생성해:
   beauty, silhouette, object_id, material_id, normal, depth, wireframe.
4. reference mask와 observed semantic evidence를 직접 비교해.
   surface-detail contract coverage는 geometry 유사도와 별도로 보고하고,
   이 항목을 geometry revision candidate로 만들지 마.
5. machine-readable request, pass manifest, visual report,
   revision_candidates.json을 qa/runs/<QA_RUN_ID>/ 아래에 보존해.
6. uv run cbm report-pdf <JOB_ID> --scope qa --qa-run-id <QA_RUN_ID>로 QA PDF를 생성해.

점수를 완성도 백분율로 설명하지 말고 지표 구성과 한계를 보고해.
standalone QA 자체는 revision_mode=suggest 경계에서 멈추고 후보를 자동 승인·적용하지 마.
큰 실루엣 문제는 V0.4 재진입 대상으로 분리하고,
V0.6 후보는 국소적이고 안전하게 주소 지정 가능한 수정만 남겨.
작은 표면 무늬가 빠졌거나 잘못 보이면 V0.5 texture/material revision으로 분리해.
기존 자산을 실제로 고칠 때는 단계 7의 standard candidate_review를 기본으로 제안해.
후보 반복 자체를 한 bounded 세션으로 묶어야 하면 자동 시작하지 말고,
단계 7B의 별도 standard bounded convergence 계획 선택지도 보고해.

생성 이미지 기반 target은 이번 실행에서 기본적으로 사용하지 마.
별도로 요청될 경우에도 advisory evidence로만 기록하고
직접 reference, measured constraint, semantic landmark보다 우선하지 마.
QA run ID, direct score, 주요 finding, 후보 ID, JSON/PDF 경로를 보고해.
```

선택적 생성 이미지 target을 추가로 시험할 때:

```text
<JOB_ID>의 기존 직접 QA를 유지한 채 생성 이미지 기반 target을 보조 근거로만 추가해.
먼저 cbm.toml의 image_model_qa 기능 상태를 확인해.
현재 기본값처럼 비활성화돼 있으면 설정을 임의 변경하거나 provider 호출을 하지 말고
별도 활성화·provider 검증이 필요하다고 보고해.
provider/model/version/seed, exact prompt, 입력·출력 hash를 기록하고 캐시해.
generated target 단독 finding은 revision 실행 후보로 승인하지 마.
직접 reference 점수와 충돌하면 직접 evidence를 우선하고 차이를 보고해.
```

#### 단계 6A — 선택적 실내 다각도 QA

> **승인된 InteriorScope와 실제 실내 geometry가 있을 때만 사용합니다. 외관 자산은 이 단계를 건너뜁니다.**

카메라 계획과 exact hash를 먼저 검토:

```text
<JOB_ID>의 승인된 실내만 별도 다각도 구조 QA로 검사해.

먼저 current InteriorScope approval, SceneSpec, embedded build fingerprint,
interior-scope validation과 interior semantic ID가 모두 current인지 확인해.
외관 고정 카메라 QA와 이 실행을 섞지 마.

plan_interior_qa를 사용해 profile=standard, resolution=512,
bounded max_views로 공간별 임시 카메라 계획만 작성해.
아직 렌더하거나 authoring .blend를 저장하지 마.

다음을 보고해:
- QA run ID <QA_RUN_ID>
- 공간·level별 대상 semantic ID
- view ID, 위치, target과 목적
- 전체 view 수와 예상 7-pass 이미지 수
- source fingerprint
- exact plan SHA-256 <PLAN_SHA256>
- 알려진 사각지대와 제한

semantic visibility는 완성도나 유사도 점수가 아님을 명시해.
현재 매핑된 실내 레퍼런스가 없으면 reference comparison은 unavailable로 계획해.
exact plan hash 승인 대기 상태에서 멈춰.
```

보고된 계획을 승인한 뒤 1회 실행:

```text
<JOB_ID>의 실내 QA run <QA_RUN_ID>,
exact camera plan SHA-256 <PLAN_SHA256>의 1회 실행을 승인한다.

현재 plan, scope approval, SceneSpec과 build fingerprint가
보고 당시와 정확히 일치하는지 먼저 확인해.
일치하지 않으면 stale로 보고하고 실행하지 마.

approve_interior_qa_plan으로 정확한 계획을 승인한 뒤
run_interior_qa를 한 번만 실행해.
각 승인 view에서 beauty, silhouette, object_id, material_id,
normal, depth, wireframe의 정확히 7개 pass를 확인해.

authoring .blend, canonical SceneSpec, geometry, material 계약과 source texture를
변경하지 않았는지 hash로 확인해.
공간·view별 semantic visibility, topology finding, advisory overlap,
unseen ID와 manual-only candidate를 보고해.

report-pdf의 qa scope와 interior QA run ID를 사용해
beauty/object-ID/wireframe contact sheet가 포함된 PDF를 생성해.
매핑된 내부 레퍼런스가 없으면 임의의 유사도 점수를 만들지 마.
수정 후보를 자동 적용하지 말고 검토 대기 상태로 멈춰.
```

#### 단계 6B — 선택적 semantic reference mask 등록

객체별 contour·orientation 진단이 필요할 때만 사용합니다. 등록은 QA evidence를
publish하는 절차이며 geometry 수정이나 사용자 승인을 대신하지 않습니다.

먼저 candidate만 준비하고 exact hash에서 멈춥니다.

```text
<JOB_ID>의 current primary reference와 SceneSpec을 기준으로
객체별 semantic reference mask candidate를 준비해.

- registration_id: <REGISTRATION_ID>
- observed primary/supporting semantic ID만 포함
- candidate 경로는 analysis/masks/registrations/<REGISTRATION_ID>/manifest.json
- 각 mask는 같은 reference 크기의 nonempty binary PNG
- mask path는 해당 registration의 masks/ 아래만 사용
- current primary reference와 SceneSpec SHA-256을 exact하게 결속

analysis/masks/semantic_manifest.json은 직접 수정하지 마.
candidate와 모든 mask를 strict validation한 뒤 candidate manifest의 exact SHA-256,
포함 semantic ID, source ID, confidence, path/hash, limitation을 보고하고 등록 전 멈춰.
```

보고된 hash를 검토한 뒤 등록할 때:

```text
<JOB_ID> semantic mask registration <REGISTRATION_ID>의
exact candidate manifest SHA-256 <MANIFEST_SHA256>을 등록해.

register_semantic_reference_masks로 exact hash를 다시 확인한 뒤에만 promotion하고,
promotion receipt와 이전 canonical history 여부를 보고해.
이후 get_semantic_reference_mask_status를 호출해
current|legacy_current|absent|stale|invalid 중 정확한 상태를 보고해.

등록을 revision, convergence, workflow, InteriorScope, V0.7 optimization 또는
Destination Handoff 승인으로 해석하지 마. 어떤 geometry나 material도 변경하지 마.
```

diagnostic은 등록된 canonical manifest를 그대로 참조하지 않고 exact manifest와 mask
bytes를 attempt-owned snapshot으로 보존합니다. 나중에 새 등록을 정상 승격해도 완료된
diagnostic은 유지되지만, attempt snapshot 자체가 바뀌면 fail-closed입니다.

#### 단계 6C — 선택적 외관 camera/geometry/assembly companion

canonical 직접 QA 결과에서 카메라 오차와 3D 형상·조립 오차를 구분하기 어려울 때만
사용합니다. 이 단계는 기존 점수나 7개 pass를 바꾸는 두 번째 QA가 아닙니다.

```text
<JOB_ID>의 완료된 canonical V0.6 QA run <QA_RUN_ID>에 대해
camera/geometry/assembly companion diagnostics를 실행해.

먼저 request, VisualQAReport, 정확히 7개인 pass manifest, SceneSpec과 build
fingerprint가 모두 current인지 hash로 확인해. current가 아니면 실행하지 마.

allowlisted run_visual_diagnostics를 다음 경계로 호출해:
- qa_run_id: <QA_RUN_ID>
- diagnostic_id: camera-geometry-v1
- max_camera_probes: 12
- include_multiview_sanity: true
- render_engine: eevee
- render_device: auto

여기서 12는 neutral baseline을 제외한 delta 수이며 baseline까지 총 13개 probe
record다. 12개 delta는 yaw ±7.5°, pitch ±5°, projection scale 0.9/1.1,
distance scale 0.9/1.1, target X/Y offset ±0.05다.

bounded camera probe, explicit semantic-mask shape metric, current signed 3D assembly
evidence와 가능한 경우 five-view structural sanity만 생성해.
canonical overall_direct_score, 원래 7개 pass, camera, SceneSpec, authoring blend,
material 계약과 approval 상태는 변경하지 마.

per-part contour와 PCA orientation은 current explicit semantic reference mask가
있는 ID에만 계산해. mask가 없으면 bbox 정밀도로 꾸며내지 말고 degraded 또는
unscorable로 보고해. PCA는 180도 facing을 판별하지 못한다고 명시하고,
방향성은 axis_alignment와 axis_clearance 근거를 따로 보고해.
required_assembly_checks는 관계 ID가 아니라 position|axis|orientation|clearance 검사
카테고리로 해석하고, 실제 관계 stable ID는 assembly_relationships에서 보존됐는지 확인해.

attribution은 camera, geometry, assembly, mixed, ambiguous, unscorable 중 무엇인지와
confidence·근거·한계를 보고해. five-view는 front/right/top/rear/oblique 구조
증거일 뿐, 보정된 동일 각도 reference가 없으므로 similarity는 unscorable로 유지해.
어떤 revision 후보도 승인하거나 적용하지 말고 검토 상태에서 멈춰.

마지막에 terminal bundle 경로, 성공 attempt-NNN, 모든 source hash,
기존 canonical direct score가 unchanged인지, legacy/unavailable 항목을 보고해.
```

동등한 공개 CLI는 다음과 같습니다. 일반 사용자는 위 프롬프트로 Codex/MCP 실행을
요청할 수 있습니다.

```powershell
uv run cbm qa-diagnose <JOB_ID> `
  --qa-run-id <QA_RUN_ID> `
  --diagnostic-id camera-geometry-v1 `
  --max-camera-probes 12 `
  --assembly-multiview `
  --render-engine eevee `
  --render-device auto
```

terminal bundle 전에 Blender 실패가 발생한 경우에만 사용하는 재시도 프롬프트:

```text
<JOB_ID>의 QA run <QA_RUN_ID>, diagnostic camera-geometry-v1 실패를 조사해.
root bundle_manifest.json이 아직 없고 canonical QA/SceneSpec/build source가 current이며,
기존 attempts/attempt-NNN이 변경되지 않았는지 먼저 확인해.

실패가 재시도 가능한 host/Blender 오류라면 같은 diagnostic ID를 정확히 한 번 다시
실행해 다음 attempt-NNN을 만들고, 이전 failure evidence는 보존해.
source drift, stale pass, mask tampering이면 재시도하지 말고 fail-closed 원인을 보고해.
성공한 exact attempt만 terminal bundle에 결속하고 revision은 수행하지 마.
```

companion과 별개로 five-view 구조 sanity만 실행하려면 먼저 plan만 만들고 exact hash를
검토합니다.

```text
<JOB_ID>의 current spatial_v1 ModelingPlan과 fresh authoring blend를 읽어
qa-assembly-sanity-plan으로 <RUN_ID>의 five-view 구조 계획만 만들어.
front, right, top, rear, oblique view와 대상 ID, source fingerprint,
exact plan SHA-256 <PLAN_SHA256>을 보고하고 아직 렌더하지 마.
```

보고된 exact plan을 실행할 때:

```text
<JOB_ID>의 assembly sanity run <RUN_ID>을 exact plan SHA-256 <PLAN_SHA256>에
결속해 1회 실행해. qa-assembly-sanity-run에는 반드시 --plan-sha256
<PLAN_SHA256>을 전달하고, plan 또는 source가 달라지면 Blender를 실행하지 마.

authoring blend를 저장하지 말고 view별 beauty, silhouette, object_id, wireframe과
visibility, projection, depth-order, signed assembly evidence만 보고해.
동일 각도의 보정 reference가 없으므로 reference_comparison_status=unscorable를
유지하고 geometry revision이나 다른 specialized approval로 해석하지 마.
```

### 단계 7 — standard 기본 candidate review

이 단계는 새 `standard revise_asset`의 기본값입니다. 계획과 적용을 별도로 먼저
승인하지 않고, canonical을 건드리지 않는 격리 평가까지 진행한 다음 실제 승격
직전에 한 번만 승인합니다.

#### 7-1. 격리 candidate 작성·평가

```text
<JOB_ID>의 <REVISION_REQUEST>를 새 immutable standard revise_asset workflow로 계획해.
revision_strategy=candidate_review 기본값을 사용해.

workflow-owned RevisionPlan을 작성하고 exact completion marker를 기록한 뒤,
canonical SceneSpec과 authoring blend를 변경하지 않은 상태에서 다음을 진행해:
- baseline/candidate SceneSpec snapshot
- 각각의 isolated build, inspect, validate
- 같은 고정 카메라의 정확히 7개 pass direct QA
- measured constraint가 있으면 전후 residual 비교
- ModelingPlan이 authored spatial_v1이면 전후 five-view 구조 비회귀 비교
- changed semantic ID/path와 before/after 값
- candidate_review_report.pdf와 sidecar

camera, material, semantic 추가·삭제, custom-mesh vertex/payload와 큰 redesign은
candidate_review에 넣지 말고 manual_guarded 또는 V0.4 re-entry가 필요하다고 보고해.

평가 뒤 canonical을 그대로 둔 채 <TRIAL_ID>, promotable 여부,
direct score와 silhouette IoU 전후, constraint/structure 결과,
decision_manifest.json 경로와 exact SHA-256 <DECISION_SHA256>을 보고하고 멈춰.
내가 그 exact decision hash를 승인하기 전에는 promotion하지 마.
```

#### 7-2. exact decision 1회 승격

```text
<JOB_ID>의 candidate review <TRIAL_ID>,
decision_manifest.json SHA-256 <DECISION_SHA256>의 canonical 승격 1회를 승인한다.

approve_candidate_review_promotion으로 exact decision과 current source hash를
다시 검증해. promotable이 아니거나 source/trial/PDF binding이 stale이면
승인·승격하지 말고 정확한 원인을 보고해.

일치할 때만 single-use approval을 기록하고 workflow를 재개해 candidate를
canonical SceneSpec으로 compare-and-swap 승격한 뒤 build, inspect, validate해.
최종 rebuild나 validation이 실패하면 baseline SceneSpec을 복구·재빌드하고
rolled_back receipt를 보고해. 성공하면 promotion receipt, 최종 SceneSpec/build
fingerprint, 변경 ID/path와 다음 권장 단계를 보고해.
```

### 단계 7A — 명시적 manual guarded 후보 승인과 1회 적용

카메라·재질·semantic membership·custom-mesh vertex 또는 큰 재설계처럼 기본
candidate envelope 밖의 변경, 혹은 기존 사전 승인형 절차를 원할 때만
`revision_strategy=manual_guarded`를 명시합니다.

#### 7A-1. 후보와 계획 SHA-256 검토

```text
<JOB_ID>의 QA run <QA_RUN_ID>에서 후보 <CANDIDATE_ID>를 검토해.

후보가 direct reference 또는 measured evidence에 근거하는지,
semantic ID와 변경 경로가 실행 가능한지,
큰 외형 authoring 문제나 generated-target-only 제안이 아닌지 확인해.

안전한 후보라면 uv run cbm qa-compile-revision <JOB_ID> <QA_RUN_ID>
--candidate-id <CANDIDATE_ID> --request "<REVISION_REQUEST>"으로
single-use revision plan을 compile하되 승인 파일은 만들지 마.

revision_plan.json, revision_compile_report.json,
base SceneSpec SHA-256, candidates SHA-256, plan SHA-256,
operation별 before/after와 잠긴 경로를 보고하고 멈춰.
사용자가 <PLAN_SHA256>과 후보를 명시적으로 승인하기 전에는 적용하지 마.
```

#### 7A-2. 특정 후보의 1회 적용

```text
<JOB_ID>의 QA run <QA_RUN_ID>에서 후보 <CANDIDATE_ID>와
compiled plan SHA-256 <PLAN_SHA256>의 1회 적용을 승인한다.

먼저 현재 revision_plan.json의 SHA-256이 <PLAN_SHA256>과 정확히 일치하고,
base SceneSpec과 candidate binding이 current인지 확인해.
불일치하면 승인·적용하지 말고 stale로 보고해.

현재 cbm.toml의 qa.revision_mode가 suggest이면 설정을 임의 변경하지 말고,
qa-approve-revision 실행에는 approve 또는 auto 정책이 필요하다고 보고한 뒤 멈춰.
별도의 명시적 정책 변경 승인이 이미 기록된 경우에만 계속해.

일치하면 현재 구현의 qa-approve-revision으로 exact candidate approval을 기록하고
qa-apply-approved를 1회만 실행해.

적용 뒤 반드시:
- build → render → inspect → validate
- 기존 measured constraint가 있으면 evaluate-constraints
- 동일 카메라의 새 Visual QA
- direct score의 minimum improvement 확인
- semantic ID, 카메라, 승인되지 않은 경로 보존 확인
- ModelingPlan이 authored spatial_v1이면 적용 전 baseline과 적용 후 result의
  fresh front/right/top/rear/oblique 구조 evidence 비교

직접 점수가 개선되지 않거나 constraint regression,
validation 실패, all-view visibility loss 또는 required assembly regression이 있으면
자동 rollback과 baseline rebuild를 확인해.
승인된 후보 밖의 변경을 유지하지 마.
최종적으로 accepted 또는 rolled_back 상태, 전후 점수,
변경 경로, constraint 비교, multiview_status와 structural regression 보고서 경로를 알려줘.
```

`qa-approve-revision` CLI는 plan hash 인자를 받지 않습니다. 따라서 Codex가 먼저 `<PLAN_SHA256>`을 현재 파일 hash와 대조한 뒤, CLI가 current plan/candidate binding으로 승인 파일을 만들게 해야 합니다.

### 단계 7B — 선택적 bounded V0.6 수렴 세션

이 단계는 한 candidate review가 아니라 여러 국소 direct-reference 반복을 하나의 exact 승인 세션으로 묶어야 할 때만 선택합니다. 기본 경로는 단계 7의 candidate review이고, 명시적 기존 one-shot은 단계 7A입니다. `background_exterior` fast lane, custom-mesh 정점 편집, 재질 수정, 실내, generated-target-only 후보, 측정 제약을 무시하는 수정에는 사용할 수 없습니다. 현재 bounded convergence session은 단계 7/7A의 five-view structural veto에 결속되지 않았습니다. 따라서 authored `spatial_v1` 자산에서는 plan/run이 fail-closed되며 단계 7의 candidate review 또는 단계 7A manual one-shot을 사용해야 합니다. legacy/non-spatial 자산만 기존 fixed-camera bounded 경로를 사용할 수 있습니다.

#### 7B-1. 계획만 생성하고 exact SHA-256 검토

```text
<JOB_ID>의 current direct QA run <QA_RUN_ID>을 기준으로
선택적 standard bounded visual convergence 가능 여부를 먼저 확인해.

ModelingPlan이 authored spatial_v1이면 five-view iteration evidence가
plan/receipt/audit에 결속되지 않았으므로 session을 만들지 말고,
단계 7의 candidate review 또는 단계 7A manual one-shot guarded revision을 안내한 뒤 멈춰.
legacy/non-spatial일 때만 아래 bounded plan을 작성해.

- session_id: <CONVERGENCE_SESSION_ID>
- target_direct_score: <TARGET_DIRECT_SCORE>
- target_silhouette_iou: <TARGET_SILHOUETTE_IOU>
- allowed_target_ids: <ALLOWED_TARGET_IDS>
- max_iterations: <MAX_ITERATIONS>
- minimum_iteration_gain: <MINIMUM_ITERATION_GAIN>

먼저 current SceneSpec, fixed camera, direct QA report/candidates,
measured constraint baseline과 source/build fingerprint를 검증해.
plan_visual_convergence를 사용하되 canonical SceneSpec이나 Blender 파일은
아직 수정하지 마.

계획에는 정확한 입력 hash, 허용 semantic ID, 허용 경로·연산·delta,
최소 candidate confidence, iteration/candidate/changed-ID budget,
direct score와 silhouette IoU 목표, constraint non-regression 규칙,
material/custom-mesh/interior/generated-target 제외를 명시해.
`initial_input_hashes`는 비어 있지 않은 exact relative-path→SHA-256 map으로
기록하고, strict `visual_convergence_host_safety_envelope.schema.json`을
통과한 host safety envelope의 경로와 exact SHA-256도 계획에 결속해.
CLI의 반복 가능한 `--path-limit-json` 또는 MCP의 `path_limits`를 쓸 때는
host envelope의 경로·연산·delta 권한을 좁히는 데만 사용하고 확대하지 마.
initial candidates SHA-256, initial build fingerprint/provenance SHA-256,
constraint 존재 여부와 snapshot SHA-256도 함께 보고해.

이 실행 binding이 없는 legacy partial plan이면 승인 가능한 것처럼 보고하지 말고,
status-only historical evidence임을 알린 뒤 current direct QA에서 새 plan이
필요하다고 보고해.

기본 3회, 절대 최대 5회를 넘기지 마.
계획 파일 경로와 exact plan SHA-256을 보고하고 승인 대기 상태로 멈춰.
이 계획 승인은 InteriorScope, V0.7 optimization,
Destination Handoff 또는 다른 specialized approval을 대신하지 않는다.
```

#### 7B-2. exact plan 승인 후 bounded 실행

```text
<JOB_ID>의 convergence session <CONVERGENCE_SESSION_ID>,
exact plan SHA-256 <PLAN_SHA256>의 bounded 실행을 승인한다.

현재 계획 hash, initial QA run, SceneSpec, camera, source/build fingerprint와
constraint baseline이 모두 current인지 먼저 확인해.
ModelingPlan이 authored spatial_v1이면 이 승인을 소비하거나 iteration을 시작하지 말고
다각도 evidence 미결속 오류와 candidate review/manual one-shot 경로를 보고해.
일치할 때만 approve_visual_convergence로 이 exact plan을 승인하고
run_visual_convergence를 실행해.

각 iteration에서 plan envelope 안의 direct-reference candidate만 선택하고,
result SceneSpec, revision authorization, 전후 수치와 exact hash receipt를 남겨.
새 fixed-camera 7-pass QA의 direct score가 최소 gain 이상 개선되고
silhouette IoU와 constraint가 regression하지 않을 때만 결과를 유지해.
비개선, regression 또는 검증 실패면 해당 iteration을 rollback하고 종료해.
legacy/non-spatial bounded session에는 five-view baseline/result 비교를 적용하지 말고
multiview veto가 `not_applicable`임을 terminal limitation에 명시해.

목표 달성, plateau, 실행 가능한 후보 없음, manual-only 후보,
budget 소진, stale/tampering, constraint regression, 취소 또는 host failure에서
자동으로 멈춰. 승인 범위를 넓히거나 최대 5회를 넘기지 마.

완료 후 terminal JSON, PDF와 sidecar manifest,
iteration별 receipt, 최종 score/IoU/constraint,
accepted·rolled_back 변경과 terminal reason을 보고해.
`run_visual_convergence` 한 번의 호출에서는 full Blender iteration을 최대 1회만
처리해. 세션이 active이면 current receipt와 `next_action`을 보고하고,
`invoke_run_again`, `invoke_run_to_recover`, `invoke_run_to_finalize` 중 보고된
행동에 따라 같은 exact approval 범위에서 다음 호출로 안전하게 재개해.
V0.7로 자동 진입하지 말고 다음 사용자 결정을 기다려.
```

#### 7B-3. 상태 확인 또는 명시적 취소

```text
<JOB_ID> convergence session <CONVERGENCE_SESSION_ID>을 read-only로 확인해.
get_visual_convergence_status를 사용해 계획·승인·iteration·terminal evidence의
current hash와 상태를 보고하고 어떤 파일도 수정하지 마.
특히 `execution_eligible`, `status_only_legacy`, `execution_block_reason`,
`execution_binding_gaps`, `next_action`을 그대로 보고해.
legacy partial plan은 status/audit-only이며 새 승인·실행·수리 대상으로 제안하지 마.
```

```text
<JOB_ID> convergence session <CONVERGENCE_SESSION_ID>의 남은 반복을 취소한다.
먼저 get_visual_convergence_status로 상태를 확인해.
receipt 없는 staging 또는 `status=recovery_required`이면 아직 취소하지 말고
`run_visual_convergence`를 정확히 한 번 호출해 staging을 복구한 뒤 결과를 보고해.
terminal evidence와 staging이 동시에 있으면 integrity failure로 보고하고
취소나 재실행으로 덮어쓰지 마.
복구가 끝나고 취소 가능한 current active session일 때만
cancel_visual_convergence를 사용해 명시적인 취소 사유를 기록하고,
이미 accepted된 iteration evidence와 canonical 결과는 임의로 되돌리지 마.
취소 terminal JSON/PDF와 sidecar, immutable cancellation_receipt.json의
경로와 SHA-256을 보고해.
```

### 단계 8 — V0.7 최적화 사전 검토

이 프롬프트는 계획만 만들며 최적화, LOD, collider, package를 생성하지 않습니다.

```text
<JOB_ID>의 V0.7 portable static-asset 사전 검토만 수행해.

- profile: <PROFILE_ID>
- 목표 형식: FBX 또는 GLB 중 profile에 해당하는 하나

먼저 canonical validation, material identity, build fingerprint,
필요한 V0.6 승인 상태가 current인지 확인해.

현재 구현의 asset-profile-init, asset-preflight, asset-plan을 사용해
새 immutable run <RUN_ID>의 다음 내용을 계획해:
- LOD가 실제로 필요한지와 단계별 triangle ratio
- Collider 필요 여부, strategy와 budget
- loose geometry·duplicate material slot 등 허용된 cleanup
- semantic-safe consolidation과 batch 경계
- triangle budget과 draw-call proxy budget
- UV0/UV1 및 raw PBR channel 보존
- packed texture가 있으면 channel mapping
- format loss와 아직 검증되지 않은 항목

preflight failed finding이 있으면 계획 승인으로 넘어가지 말고 멈춰.
통과하면 review_plan.json과 optimization_review.json의 경로,
exact plan SHA-256 <PLAN_SHA256>, 예상 비용, 알려진 손실을 보고해.

아직 asset-plan-approve, asset-optimize, material conversion,
package 또는 export를 실행하지 마.
사용자에게 approve, revise_asset, revise_profile, cancel 네 선택을 요청하고 멈춰.
직접 QA가 needs_revision이면 recommended_decision=revise_asset과 이유를 표시해.
revise_asset은 외형·실루엣·비율·semantic 구조 수정용이고,
revise_profile은 LOD·Collider·consolidation·UV·텍스처·budget 변경 전용이야.
어느 선택도 자동 실행하지 말고 현재 portable workflow를 standard로 변조하지 마.
```

### 단계 9 — V0.7 승인된 최적화·패키징

```text
<JOB_ID>의 V0.7 run <RUN_ID>, profile <PROFILE_ID>,
review plan SHA-256 <PLAN_SHA256>을 승인한다.

현재 profile, preflight, source fingerprint, review plan hash가
승인 시점과 정확히 일치하는지 확인해.
일치하지 않으면 stale 승인을 만들거나 실행하지 말고 새 review를 요구해.

일치하면:
1. asset-plan-approve로 exact single-use approval 기록
2. asset-optimize를 approved plan SHA-256으로 실행
3. profile이 요구할 때만 asset-material-convert 실행
4. immutable package <PACKAGE_ID> 생성
5. package manifest의 모든 relative path와 SHA-256 검증
6. fresh Blender clean-import round trip 실행
7. bounds, dependency, semantic/material coverage 판정
8. report-pdf --scope export로 export PDF 생성

canonical SceneSpec, geometry, authoring blend, source texture는 변경하지 마.
optimized scene, cost report, package manifest, roundtrip validation,
PDF 경로와 canonical hash 불변 여부를 보고해.
round trip이 pass하지 않으면 package를 accepted로 표시하지 마.
```

FBX 하나만 원하는 경우:

```text
<JOB_ID>에는 FBX만 필요하다.
profile은 fbx_interchange만 사용하고 동일 run에서 GLB/OBJ package를 추가 생성하지 마.
V0.7 review plan과 exact SHA-256 승인을 먼저 받고,
승인 뒤 FBX package, raw PBR sidecar, manifest,
clean-import round trip, export PDF까지만 수행해.
Unity/Unreal import parity는 주장하지 마.
```

GLB 하나만 원하는 경우:

```text
<JOB_ID>에는 GLB만 필요하다.
profile은 portable_gltf만 사용하고 동일 run에서 FBX/OBJ package를 추가 생성하지 마.
V0.7 review plan과 exact SHA-256 승인을 먼저 받고,
승인 뒤 GLB package, 보존된 raw PBR 채널과 필요한 glTF ORM,
manifest, clean-import round trip, export PDF까지만 수행해.
목적지에 GLB importer가 있다고 가정하지 마.
```

### 단계 10 — V0.9 workspace audit

V0.9 audit는 외형, 재질, topology 또는 package를 개선하는 단계가 아닙니다.

```text
<JOB_ID>에 대해 V0.9 read-only 안정성 점검을 수행해.

1. uv run cbm stability-probe --probe-id <PROBE_ID>로
   탐지된 환경과 기존 compatibility evidence hash를 기록해.
2. uv run cbm workspace-audit --job-id <JOB_ID> --audit-id <AUDIT_ID>로
   stale hash, 누락 파일, path escape, dangling receipt,
   interrupted state, package/handoff binding을 검사해.
3. JSON 결과의 warning과 failure를 그대로 유지해.
4. canonical 또는 derived 파일을 자동 수리, migration, 삭제, 재분류하지 마.
5. uv run cbm stability-report-pdf --probe-id <PROBE_ID>
   --audit-id <AUDIT_ID> --report-id <REPORT_ID>로 PDF를 생성해.

probe JSON, audit JSON, PDF와 sidecar manifest 경로,
pass/warn/fail, 다음에 사람이 판단할 항목을 보고해.
PDF를 machine evidence 대신 사용하지 마.
```

### 단계 11 — 선택적 Destination Handoff

clean-import round trip을 통과한 FBX 또는 GLB package가 있을 때만 사용합니다. 이 단계는 목적지 프로젝트를 수정하거나 package를 외부로 복사하지 않습니다.

계획:

```text
<JOB_ID>의 passed V0.7 package를 위한 Codex Destination Handoff 계획을 작성해.

- profile: <PROFILE_ID>
- package ID: <PACKAGE_ID>
- handoff ID: <HANDOFF_ID>
- optional destination hint: <DESTINATION_HINT>

먼저 package manifest와 roundtrip validation이 current/pass인지 확인해.
실패하거나 stale이면 handoff를 만들지 말고 필요한 V0.7 단계만 보고해.

유효하면 uv run cbm handoff-plan <JOB_ID> --profile <PROFILE_ID>
--package-id <PACKAGE_ID> --handoff-id <HANDOFF_ID>
--destination-hint "<DESTINATION_HINT>"를 사용해 계획만 작성해.

package manifest SHA-256, handoff plan 경로와 exact SHA-256 <PLAN_SHA256>,
primary model, texture/material/assembly/LOD/Collider 전달 범위,
format loss와 목적지에서 검증할 항목을 보고하고 승인 대기 상태로 멈춰.
아직 handoff-generate를 실행하지 마.
```

정확한 plan 승인 후:

```text
<JOB_ID>의 Destination Handoff <HANDOFF_ID>,
plan SHA-256 <PLAN_SHA256> 생성을 승인한다.

현재 handoff plan과 package manifest binding을 다시 확인하고,
일치할 때만 handoff-generate를 실행해.
그 뒤 handoff-validate와 <JOB_ID> 대상 workspace-audit을 수행해.

원본 package와 canonical 파일은 변경하지 말고,
목적지 프로젝트를 수정하거나 외부로 복사하지 마.
Unity/Unreal/custom engine 지원을 검증 없이 주장하지 마.

handoff folder, validation 결과, package manifest SHA-256,
handoff manifest SHA-256, 모든 handoff 파일 hash,
목적지 Codex가 사용할 codex_import_prompt.md의 repository-relative 위치를 보고해.
```

---

## 4. 승인 응답 템플릿

Codex가 실제로 보고한 ID, fingerprint, SHA-256만 채웁니다.

프록시 승인:

```text
<JOB_ID> workflow <WORKFLOW_ID>의 proxy 결과를 승인한다.
approval 대상 단계 <STEP_ID>와 artifact fingerprint <ARTIFACT_FINGERPRINT>가
현재 상태와 정확히 일치할 때만 기록하고 다음 단계로 진행해.
```

상세 형상 승인:

```text
<JOB_ID>의 현재 V0.4 상세 형상, 카메라와 semantic ID 구성을 승인한다.
현재 build fingerprint를 기준선으로 기록하고
V0.5 material authoring을 계획한 뒤 승인 경계에서 다시 멈춰.
```

Material/swatch 승인:

```text
<JOB_ID>의 현재 MaterialPlan, ShaderRecipe, material validation과 swatch를 승인한다.
현재 단계 <STEP_ID>와 material artifact fingerprint
<ARTIFACT_FINGERPRINT>가 일치할 때만 기록해.
이 승인은 V0.6 revision이나 V0.7 optimization 승인을 대신하지 않는다.
```

V0.6 특정 후보 승인:

```text
<JOB_ID> QA run <QA_RUN_ID>의 후보 <CANDIDATE_ID>,
compiled plan SHA-256 <PLAN_SHA256>의 1회 적용을 승인한다.
현재 hash와 binding이 다르면 적용하지 말고 stale로 보고해.
```

Standard candidate review 승격 승인:

```text
<JOB_ID> candidate review <TRIAL_ID>의
decision_manifest.json SHA-256 <DECISION_SHA256>에 한해 canonical 승격 1회를 승인한다.
current source와 모든 baseline/candidate QA·constraint·structure binding이 다르면
승인하지 말고 stale로 보고해. 승격 뒤 final validation 실패 시 baseline을 복구해.
```

선택적 V0.6 bounded convergence 승인:

```text
<JOB_ID> convergence session <CONVERGENCE_SESSION_ID>의
exact plan SHA-256 <PLAN_SHA256>에 한해 최대 <MAX_ITERATIONS>회의
bounded direct-reference 반복 실행을 승인한다.
현재 plan/input/QA/camera/constraint binding이 다르면 승인하지 말고 stale로 보고해.
계획에 잠긴 semantic ID, 경로, 연산, delta와 budget 밖의 수정은 수행하지 마.
```

실내 다각도 QA 계획 승인:

```text
<JOB_ID> 실내 QA run <QA_RUN_ID>의
exact camera plan SHA-256 <PLAN_SHA256>을 승인한다.
현재 scope/source/build binding이 일치할 때만 single-use 승인을 기록하고,
계획에 포함된 view만 1회 렌더해.
이 승인은 geometry 수정 권한이 아니다.
```

기본 `revision_mode=suggest`에서 실제 적용으로 전환할 때의 별도 정책 승인:

```text
<JOB_ID> QA run <QA_RUN_ID>의 위 exact 후보 1회 적용에 한해
cbm.toml의 qa.revision_mode를 suggest에서 approve로 변경하는 것을 승인한다.
max_revision_iterations=1은 유지하고 auto mode로 넓히지 마.
적용과 검증이 끝나면 revision_mode를 suggest로 복구하고
설정 전후와 복구 결과를 보고해.
```

V0.7 review에서 asset 수정으로 돌아가는 선택:

```text
<JOB_ID>의 현재 V0.7 run <RUN_ID>은 승인하지 말고 revise_asset을 선택한다.
현재 portable workflow를 standard로 변조하거나 optimization approval을 만들지 마.
QA의 primary finding과 권장 semantic ID를 근거로 새 immutable standard
revise_asset workflow 계획만 작성하고, guarded revision의 exact 승인 지점에서 멈춰.
수정·rebuild·동일 카메라 QA가 완료된 뒤에는 기존 V0.7 run을 재사용하지 말고
새 run ID로 preflight와 review를 다시 수행해.
```

V0.7 exact plan 승인:

```text
<JOB_ID> V0.7 run <RUN_ID>, profile <PROFILE_ID>의
review plan SHA-256 <PLAN_SHA256>을 승인한다.
현재 source/profile/preflight/review binding이 일치할 때만
single-use optimization approval을 기록하고 실행해.
```

Handoff exact plan 승인:

```text
<JOB_ID> package <PACKAGE_ID>의 Destination Handoff <HANDOFF_ID>,
plan SHA-256 <PLAN_SHA256> 생성을 승인한다.
현재 package manifest binding이 일치할 때만 generate와 validate를 수행해.
```

InteriorScope는 위 텍스트 승인으로 충분하지 않습니다. 단계 4의 대화형 CLI에서 정확한 `<SCOPE_SHA256>`을 직접 입력해야 합니다.

---

## 5. 실패 및 재개 프롬프트

### Agent-authored artifact 대기

```text
<JOB_ID> workflow <WORKFLOW_ID>가 agent-authored artifact에서 대기 중이다.
workflow-status와 workflow-reconcile로 정확한 step ID와 input fingerprint를 확인해.
요구된 계약만 작성·검증하고 output hash를 보고해.
현재 input fingerprint <INPUT_FINGERPRINT>와 다르면 completion marker를 쓰지 마.
완료 뒤 현재 step만 표시하고 다음 승인 경계에서 멈춰.
```

### Approval 대기

```text
<JOB_ID> workflow <WORKFLOW_ID>가 approval 대기 중이다.
어떤 전문 승인 또는 generic review인지 구분하고,
검토 파일, exact artifact fingerprint/SHA-256, 승인 시 다음 동작을 보고해.
내 승인 없이 workflow-approve나 전문 승인 명령을 실행하지 마.
generic approval로 InteriorScope, QA revision, bounded convergence plan,
V0.7 optimization을 우회하지 마.
```

### Stale fingerprint

```text
<JOB_ID>의 stale fingerprint 원인을 read-only로 추적해.
변경된 입력과 이전/current SHA-256, stale이 된 downstream artifact를 보고해.
기존 completion/approval을 current로 재분류하거나 canonical 파일을 자동 복구하지 마.
새 artifact 또는 새 review/approval이 필요한 정확한 단계에서 멈춰.
```

### Blender build 실패

```text
<JOB_ID>의 Blender build 실패를 진단해.
Blender 로그, Python exit code, SceneSpec validation, geometry path,
build fingerprint를 확인하고 canonical data 문제와 runner/API 문제를 구분해.
실패를 성공으로 처리하거나 .blend를 손으로 고치지 마.
최소 수정 계획과 영향 파일을 먼저 보고하고 승인 대기 상태로 멈춰.
```

### Material validation 실패

```text
<JOB_ID>의 material validation 실패를 진단해.
MaterialPlan, ShaderRecipe, TextureManifest, channel path/hash,
color space, mapping/UV, Blender node inspection을 대조해.
geometry나 source texture를 임의 수정하지 말고
문제가 있는 material ID와 계약 경로, 최소 수정안을 보고해.
validation이 통과하기 전에는 swatch 승인이나 V0.6 QA로 넘어가지 마.
```

### QA 비개선 rollback

```text
<JOB_ID> QA run <QA_RUN_ID>의 적용 결과가 비개선 또는 regression으로 보고됐다.
convergence와 rollback_report를 확인하고 archived baseline SceneSpec이 복원됐는지,
baseline rebuild/render/inspect/validate가 성공했는지 검증해.
실패한 후보를 accepted로 재분류하지 마.
남은 문제를 V0.4 authoring과 새 V0.6 후보 중 어디로 돌려야 하는지 보고해.
```

### Bounded convergence plateau·manual-only·rollback

```text
<JOB_ID> convergence session <CONVERGENCE_SESSION_ID>의 terminal evidence를 조사해.
terminal reason이 target_reached, plateau, no_eligible_candidates,
manual_review_required, iteration_budget_exhausted, constraint_regression,
stale_or_tampered, cancelled 또는 failed 중 무엇인지 정확히 구분해.

iteration별 direct score, silhouette IoU, constraint 비교,
accepted 또는 rolled_back receipt와 최종 canonical SceneSpec hash를 보고해.
rollback된 iteration을 accepted로 바꾸거나 plan envelope를 자동 확대하지 마.
큰 외형 문제나 custom-mesh 수정이 남으면 V0.4 authoring 또는
후보별 수동 V0.6 revision으로 되돌릴 것을 제안하고 멈춰.
```

### Bounded convergence stale·tampering·불완전 세션

```text
<JOB_ID> convergence session <CONVERGENCE_SESSION_ID>의
stale 또는 tampering 원인을 read-only로 추적해.
계획이 결속한 input, initial QA, SceneSpec, camera, candidate,
iteration receipt와 현재 hash를 비교해.

누락·변경된 exact evidence와 영향받은 iteration을 보고하고,
기존 plan/approval/receipt를 current로 재분류하거나 다시 쓰지 마.
새 current QA와 새 session plan이 필요하면 그 경계까지만 제안해.
```

### V0.7 preflight 실패

```text
<JOB_ID> V0.7 run <RUN_ID>의 preflight failed finding을 조사해.
canonical authoring data는 수정하지 말고 finding별 semantic ID,
topology/transform/normal/material/UV/budget 근거를 보고해.
V0.4 또는 V0.5에서 고쳐야 할 항목과 단순 warning을 구분해.
failed 상태에서는 review approval, optimize, package를 실행하지 마.
```

### Clean-import roundtrip 실패

```text
<JOB_ID> package <PACKAGE_ID>의 clean-import roundtrip 실패를 분석해.
package manifest hash, dependency, imported bounds, axis/unit declaration,
semantic/material coverage와 format loss를 확인해.
package 파일을 덮어쓰거나 pass로 재분류하지 마.
새 V0.7 run/profile review가 필요한지 보고하고 승인 대기 상태로 멈춰.
```

### V0.9 audit warning/failure

```text
<JOB_ID>의 V0.9 audit <AUDIT_ID> warning/failure를 설명해.
audit는 read-only이므로 자동 repair, migration, 삭제를 하지 마.
각 finding의 evidence path, severity, 영향 범위,
canonical/derived/operational 분류와 별도 조치 필요 여부를 보고해.
```

### 중단된 V0.8 workflow 재개

```text
<JOB_ID> workflow <WORKFLOW_ID>를 안전하게 재개할 수 있는지 확인해.
먼저 workflow-status와 workflow-reconcile을 실행해
live/expired lock, interrupted attempt, stale marker,
현재 첫 incomplete step을 보고해.

변경되지 않은 current evidence는 재생성하지 말고
uv run cbm workflow-resume <JOB_ID> <WORKFLOW_ID>로 현재 단계부터 재개해.
failed host step이면 사용자 승인 없이 --retry-failed를 사용하지 마.
agent 또는 approval 경계에 도달하면 정상 정지로 처리해.
```

실패한 host step의 1회 재시도를 별도로 승인할 때:

```text
<JOB_ID> workflow <WORKFLOW_ID>의 현재 failed host step 1회 재시도를 승인한다.
기존 attempt receipt를 보존하고
uv run cbm workflow-resume <JOB_ID> <WORKFLOW_ID> --retry-failed를 실행해.
다른 단계로 건너뛰거나 실패를 성공으로 재분류하지 마.
```

---

## 6. 단계별 완료 체크리스트

| 단계 | 필수 입력 | 주요 산출물 | 사용자 검토 자료 | 승인 필요 여부 | 다음 단계 | 재진입 조건 |
|---|---|---|---|---|---|---|
| 0 환경 점검 | 저장소, `<JOB_ID>`, `<REFERENCE_PATH>` | read-only 상태 보고 | doctor, 기존 compatibility evidence | 없음 | 1 | evidence 누락·stale 해결 후 |
| 빠른 배경 preview | 새 단일 concept reference, `background_exterior`, `preview_only` | 중간 상세 외관, bounded fit, V0.4 5-view host/agent review, 로컬 재질, 직접 QA, quality report | preview, multiview JSON/이미지, 직접 QA/quality JSON, QA·통합 PDF | 일반 단계 승인 없음; multiview agent completion은 유지 | `status=completed`, `milestone=delivered_for_review`, 독립 quality status 또는 별도 package workflow | scope 위험은 `standard`; geometry review 권고는 선택적 standard revision |
| 빠른 배경 package | 새 단일 concept reference 또는 current fast preview, `background_exterior`, `portable_package` | 위 preview 증거와 quality warning, 승인된 V0.7 최적화, package, roundtrip | quality JSON, optimization review/hash, export PDF, roundtrip JSON | V0.7 optimization-plan exact-hash 승인 1회 | `status=completed` | profile/source/quality binding 변경 또는 roundtrip 실패 |
| 1 V0.4 프록시 | 새 ID, reference, mode | job, reference analysis, camera solution, modeling plan, proxy SceneSpec, `.blend`, 5-view host/agent review | preview, multiview JSON/이미지, build PDF, validation JSON | 프록시 승인; geometry review 자체는 승인 아님 | 2 또는 3 | 실루엣·분해 또는 cross-view 구조가 부정확할 때 |
| 2 V0.4 상세 형상 | 승인된 프록시 | 상세 SceneSpec/geometry, 새 build, 5-view host/agent review | preview, 변경 ID/수치, multiview JSON/이미지, build PDF | 상세 형상 승인; review 권고는 자동 적용 아님 | 3, 4 또는 5 | 큰 외형·중형 구조·cross-view topology 불만족 시 언제든 |
| 3 멀티뷰·치수 | 추가 뷰 또는 명시 치수 | source hash, 갱신 분석, constraints, residual report | 뷰 목록, constraint JSON/PDF | canonical 수정 전 승인 | 2 또는 5 | 새 도면·치수 추가, residual 실패 |
| 4 선택적 실내 | 명시적 실내 요청 | InteriorScope draft/approval/validation, 승인 범위 geometry | scope JSON/hash, build preview | 수동 exact-hash 승인 | 5 | 범위 변경 시 새 scope·승인 |
| 5 V0.5 재질 | 승인된 geometry/camera | MaterialPlan, ShaderRecipe, TextureManifest, swatches | material JSON, swatch, material PDF | material/swatch 승인 | 6 | geometry/material hash 변경, validation 실패 |
| 6 V0.6 QA | fresh build, 고정 카메라 | 7 passes, QA report, candidates | direct score, pass 이미지, QA PDF | 후보 적용 전 필요 | 7 또는 8 | 새 geometry/material/build |
| 6A 선택적 실내 QA | 승인된 InteriorScope, interior geometry, fresh build | exact camera plan, view별 7 passes, coverage/report/candidates | contact sheets, interior QA PDF, plan hash | camera plan exact-hash 승인 | 7 또는 8 | scope/SceneSpec/build 변경, unseen 공간 재계획 |
| 6B 선택적 외관 companion | completed canonical QA run, current source hashes | immutable attempts, terminal bundle, camera/shape/assembly attribution, optional five-view evidence | diagnostic JSON, attribution·limitation, structural views | revision 승인 없음; standalone five-view run은 exact plan hash 필요 | 7 또는 8 | terminal 전 retryable host 실패는 다음 attempt, source drift는 새 current QA |
| 7 V0.6 candidate review | standard revise request, current canonical asset | 격리 baseline/candidate build·7-pass QA·optional constraint·5-view 비교, decision/PDF, promotion receipt | 전후 점수·silhouette·constraint·구조·변경 경로 | exact decision SHA-256 승격 승인 1회 | 6 또는 8 | non-promotable이면 새 revision/V0.4, envelope 밖이면 7A |
| 7A manual guarded revision | QA run, 후보, compiled plan | 기존 approval, 적용·rollback; spatial_v1이면 전후 5-view veto | 전후 점수·constraint·구조 비교·변경 경로 | 후보+plan exact 사전 승인 | 6 또는 8 | 비개선·구조 regression은 rollback, 큰 문제는 2 |
| 7B 선택적 bounded convergence | legacy/non-spatial standard job, current direct QA, 목표 점수·IoU, 허용 ID와 budget | exact plan/approval, iteration receipts, terminal JSON/PDF; authored spatial_v1은 plan/run 거부 | plan envelope/hash, iteration별 전후 점수·IoU·constraint와 multiview limitation | convergence plan exact-hash 승인 1회 | 6, 8 또는 종료 | spatial_v1은 수동 7, plateau·manual-only·큰 외형은 2 또는 수동 7, stale이면 새 QA/plan |
| 8 V0.7 review | 승인된 canonical asset, profile | preflight, review plan, optimization review | exact plan hash, 비용·손실, revise_asset 권고 | `approve/revise_asset/revise_profile/cancel` | 9 또는 standard revision | profile/source/preflight 변경, QA needs_revision |
| 9 V0.7 package | approved exact plan | optimized scene, cost report, FBX/GLB package, manifest, roundtrip | export PDF, roundtrip JSON | exact plan 승인 및 final review | 10 또는 11 | roundtrip 실패, package stale |
| 10 V0.9 audit | current workspace/package | probe, audit JSON, stability PDF | warning/failure 목록 | 수리에는 별도 승인 | 선택적 11 또는 종료 | 환경·workspace 변경 |
| 11 Handoff | passed FBX/GLB package | handoff contracts, validation, 목적지 prompt | handoff report, hashes, prompt 위치 | exact handoff plan 승인 | 목적지 Codex 검토 | package/handoff binding 변경 |

## 현재 범위의 제한

- V0.4는 single-view의 보이지 않는 면과 실제 깊이를 복원된 진실로 만들지 못합니다.
- V0.4 constraints는 residual을 평가하지만 임의의 CAD B-Rep 또는 비선형 제약을 자동 완전 해결하지 않습니다.
- V0.4 five-view geometry review는 여러 각도에서 형상·조립·topology 일관성을 보는 구조 근거입니다. 한 시점의 occlusion은 advisory이고, 보정된 각도별 reference가 없으면 측면·후면 likeness는 `unscorable`입니다. 결과는 V0.4 parametric revision 또는 manual redesign review를 권고할 수 있지만 자동 승인·적용하지 않습니다.
- V0.6 direct score와 generated target은 사람의 미적 승인이나 metric accuracy를 대체하지 않습니다.
- V0.6 companion attribution은 카메라·형상·조립 원인 후보를 분류하는 보조 근거입니다. explicit semantic mask가 없으면 객체별 contour/orientation은 채점하지 않으며, 보정된 측면 reference가 없는 five-view는 구조적 evidence일 뿐 similarity는 `unscorable`입니다.
- V0.6 candidate review는 existing-object의 제한된 parametric 수정만 격리 평가하며 direct score, silhouette, constraint와 authored spatial_v1 five-view 비회귀를 통과한 candidate만 최종 승격 대상으로 제시합니다. 큰 authoring 문제, custom-mesh 정점, 재질과 실내는 V0.4/V0.5 또는 manual guarded 범위입니다.
- V0.6 bounded convergence는 계획된 direct-reference 국소 수정만 기본 3회, 절대 최대 5회 수행하며 목표 달성을 보장하지 않습니다. 큰 authoring 문제, custom-mesh 정점, 재질, 실내와 manual-only 후보는 자동 범위 밖입니다. authored `spatial_v1`은 five-view iteration 증거가 결속되기 전까지 plan/run이 fail-closed되며 candidate review 또는 수동 one-shot을 사용합니다. legacy/non-spatial만 기존 fixed-camera bounded 경로를 유지합니다.
- 실내 semantic visibility는 승인된 다각도에서 ID가 보이는지 나타낼 뿐 실내 완성도나 레퍼런스 유사도를 뜻하지 않습니다.
- V0.7은 static asset, engine-neutral FBX/GLB package 범위입니다. Rig, skinning, animation, prefab/actor, runtime shader는 포함하지 않습니다.
- V0.9 Destination Handoff는 목적지 Codex를 위한 계약과 안전한 import prompt를 생성할 뿐 목적지 엔진을 실행하거나 프로젝트를 수정하지 않습니다.
- 현재 문서는 Unity/Unreal 자동 adapter나 V1.1 이후 기능이 구현된 것으로 가정하지 않습니다.
