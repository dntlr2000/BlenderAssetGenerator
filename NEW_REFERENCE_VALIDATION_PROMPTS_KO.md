# 새 레퍼런스 자산 단계별 검증 프롬프트

이 문서는 새 레퍼런스 이미지를 제공한 뒤 사용자가 Codex 채팅에 복사해 입력할 수 있는 실사용 프롬프트 모음입니다. 현재 저장소의 V0.4~V0.9 계약과 CLI를 기준으로 하며, 각 단계의 승인 경계를 유지합니다.

기계 판정의 원본은 JSON 계약과 보고서입니다. PDF는 사용자가 검토하기 쉬운 파생 보고서이며 JSON을 대체하지 않습니다.

## 사용 방법과 placeholder

`text` 코드 블록은 Codex 채팅에 붙여 넣는 프롬프트입니다. `powershell` 코드 블록은 사용자가 터미널에서 직접 실행해야 하는 명령입니다. 특히 InteriorScope 승인은 Codex가 대신 실행할 수 없습니다.

| Placeholder | 교체할 값 | 예시 |
|---|---|---|
| `<JOB_ID>` | 새 자산의 고유 lowercase job ID | `temple_validation_01` |
| `<REFERENCE_PATH>` | 기본 레퍼런스 이미지의 절대 경로 | `E:\References\temple.png` |
| `<MODE>` | `concept` 또는 `measured` | `concept` |
| `<WORKFLOW_ID>` | Codex가 보고한 V0.8 workflow ID | 실제 보고값 |
| `<STEP_ID>` | V0.8 workflow가 보고한 현재 agent/review step ID | 실제 보고값 |
| `<QA_RUN_ID>` | Codex가 보고한 V0.6 QA run ID | 실제 보고값 |
| `<CANDIDATE_ID>` | 적용을 검토할 V0.6 후보 ID | 실제 보고값 |
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
- 프록시 승인 전에는 재질, 최적화, package 또는 export를 진행하지 않습니다.
- 실내는 기본 비활성화입니다. 명시적 요청, InteriorScope draft, 정확한 hash의 수동 승인이 모두 있어야 합니다.
- 보이지 않는 형상은 복원된 사실이 아니라 `inferred`로 기록합니다.
- V0.6 점수는 완성도 백분율이 아닙니다. 고정 카메라에서 산출된 비교 지표일 뿐입니다.
- 큰 실루엣, 비율, 구조가 잘못됐으면 V0.4 authoring으로 돌아갑니다.
- 이미 맞는 큰 형상을 유지하면서 국소적인 유사도 오차만 고칠 때 V0.6 guarded revision을 사용합니다.
- V0.7은 run-owned 파생 결과만 만들며 canonical SceneSpec, geometry payload, authoring `.blend`, source texture를 변경하지 않습니다.
- V0.9는 필수 모델링 단계가 아니라 read-only audit와 선택적 Destination Handoff 계층입니다. 외형을 개선하지 않습니다.
- Unity, Unreal 또는 다른 엔진의 runtime parity를 검증 없이 주장하지 않습니다.
- “이후 전부 승인” 같은 포괄적 승인은 InteriorScope, V0.6 revision, V0.7 optimization, Destination Handoff의 전용 exact-hash 승인을 대체하지 못합니다.

---

## 1. 가장 짧은 시작 프롬프트

이미지를 첨부하거나 `<REFERENCE_PATH>`를 제공한 뒤 아래 프롬프트를 붙여 넣습니다. V0.8 orchestration은 host step과 승인 경계를 관리하지만, agent-authored SceneSpec을 자동으로 승인하지 않습니다.

```text
현재 저장소의 V0.8 orchestration을 사용해 새 레퍼런스 자산의 프록시까지만 만들어줘.

- job_id: <JOB_ID>
- reference_path: <REFERENCE_PATH>
- mode: <MODE>

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

1. V0.4 proxy geometry 작성·검증 후 proxy approval
2. V0.4 detail geometry 작성·검증 후 detail approval
3. V0.5 MaterialPlan, ShaderRecipe, swatch, material PDF 후 material approval
4. V0.6 직접 Visual QA와 QA PDF 후 QA review
5. V0.6 수정 후보가 선택되면 별도의 exact candidate/plan 승인
6. V0.7 preflight와 review plan 후 exact plan SHA-256 승인
7. V0.7 package와 clean-import round trip 후 portable final review
8. 선택적으로 V0.9 read-only audit
9. passed package가 있을 때만 선택적으로 Destination Handoff plan과 exact-hash 승인

현재 단계에서 수행 가능한 host step만 실행하고,
agent-authored artifact 또는 승인 단계에 도달하면 멈춰서
workflow ID, 단계 ID, 입력·산출물 fingerprint, 검토 파일,
정확히 필요한 다음 승인이나 작업을 보고해.

generic workflow approval로 InteriorScope, V0.6 revision,
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
5. SceneSpec 0.2.0 proxy 작성
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
필요한 경우 이전 SceneSpec을 history에 보존하고 canonical SceneSpec 또는
geometry payload를 최소 범위로 수정해.

수정 후 build → render → inspect → validate를 실행하고
build scope PDF 또는 preview를 갱신해.
변경한 semantic ID, geometry.kind, 전후 dimensions/vertex/polygon 수,
카메라와 변경하지 않은 ID 보존 여부를 보고해.
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
5. Base Color는 sRGB, data channel은 Non-Color로 설정해.
6. Blender master shader와 portable/bake 결과를 분리해.
7. Blender 5에서 runtime feature probe가 가능한 whitelisted recipe만 사용해.
8. uv run cbm validate-material-contracts <JOB_ID>를 실행해.
9. 최신 build 뒤 uv run cbm inspect-materials <JOB_ID>와
   uv run cbm render-material-swatches <JOB_ID>를 실행해.
10. uv run cbm report-pdf <JOB_ID> --scope material로
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
5. machine-readable request, pass manifest, visual report,
   revision_candidates.json을 qa/runs/<QA_RUN_ID>/ 아래에 보존해.
6. uv run cbm report-pdf <JOB_ID> --scope qa --qa-run-id <QA_RUN_ID>로 QA PDF를 생성해.

점수를 완성도 백분율로 설명하지 말고 지표 구성과 한계를 보고해.
기본 revision_mode=suggest 경계에서 멈추고 후보를 자동 승인·적용하지 마.
큰 실루엣 문제는 V0.4 재진입 대상으로 분리하고,
V0.6 후보는 국소적이고 안전하게 주소 지정 가능한 수정만 남겨.

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

### 단계 7 — V0.6 후보 승인과 1회 적용

#### 7-1. 후보와 계획 SHA-256 검토

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

#### 7-2. 특정 후보의 1회 적용

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

직접 점수가 개선되지 않거나 constraint regression,
validation 실패가 있으면 자동 rollback과 baseline rebuild를 확인해.
승인된 후보 밖의 변경을 유지하지 마.
최종적으로 accepted 또는 rolled_back 상태, 전후 점수,
변경 경로, constraint 비교와 보고서 경로를 알려줘.
```

`qa-approve-revision` CLI는 plan hash 인자를 받지 않습니다. 따라서 Codex가 먼저 `<PLAN_SHA256>`을 현재 파일 hash와 대조한 뒤, CLI가 current plan/candidate binding으로 승인 파일을 만들게 해야 합니다.

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
사용자에게 approve, revise_profile, cancel 세 선택을 요청하고 멈춰.
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
generic approval로 InteriorScope, QA revision, V0.7 optimization을 우회하지 마.
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
| 1 V0.4 프록시 | 새 ID, reference, mode | job, reference analysis, camera solution, modeling plan, proxy SceneSpec, `.blend` | preview, build PDF, validation JSON | 프록시 승인 | 2 또는 3 | 실루엣·분해가 부정확할 때 |
| 2 V0.4 상세 형상 | 승인된 프록시 | 상세 SceneSpec/geometry, 새 build | preview, 변경 ID/수치, build PDF | 상세 형상 승인 | 3, 4 또는 5 | 큰 외형·중형 구조 불만족 시 언제든 |
| 3 멀티뷰·치수 | 추가 뷰 또는 명시 치수 | source hash, 갱신 분석, constraints, residual report | 뷰 목록, constraint JSON/PDF | canonical 수정 전 승인 | 2 또는 5 | 새 도면·치수 추가, residual 실패 |
| 4 선택적 실내 | 명시적 실내 요청 | InteriorScope draft/approval/validation, 승인 범위 geometry | scope JSON/hash, build preview | 수동 exact-hash 승인 | 5 | 범위 변경 시 새 scope·승인 |
| 5 V0.5 재질 | 승인된 geometry/camera | MaterialPlan, ShaderRecipe, TextureManifest, swatches | material JSON, swatch, material PDF | material/swatch 승인 | 6 | geometry/material hash 변경, validation 실패 |
| 6 V0.6 QA | fresh build, 고정 카메라 | 7 passes, QA report, candidates | direct score, pass 이미지, QA PDF | 후보 적용 전 필요 | 7 또는 8 | 새 geometry/material/build |
| 6A 선택적 실내 QA | 승인된 InteriorScope, interior geometry, fresh build | exact camera plan, view별 7 passes, coverage/report/candidates | contact sheets, interior QA PDF, plan hash | camera plan exact-hash 승인 | 7 또는 8 | scope/SceneSpec/build 변경, unseen 공간 재계획 |
| 7 V0.6 revision | QA run, 후보, compiled plan | approval, convergence 또는 rollback | 전후 점수·constraint·변경 경로 | 후보+plan exact 승인 | 6 또는 8 | 비개선은 rollback, 큰 문제는 2 |
| 8 V0.7 review | 승인된 canonical asset, profile | preflight, review plan, optimization review | exact plan hash, 비용·손실 | `approve/revise_profile/cancel` | 9 | profile/source/preflight 변경 |
| 9 V0.7 package | approved exact plan | optimized scene, cost report, FBX/GLB package, manifest, roundtrip | export PDF, roundtrip JSON | exact plan 승인 및 final review | 10 또는 11 | roundtrip 실패, package stale |
| 10 V0.9 audit | current workspace/package | probe, audit JSON, stability PDF | warning/failure 목록 | 수리에는 별도 승인 | 선택적 11 또는 종료 | 환경·workspace 변경 |
| 11 Handoff | passed FBX/GLB package | handoff contracts, validation, 목적지 prompt | handoff report, hashes, prompt 위치 | exact handoff plan 승인 | 목적지 Codex 검토 | package/handoff binding 변경 |

## 현재 범위의 제한

- V0.4는 single-view의 보이지 않는 면과 실제 깊이를 복원된 진실로 만들지 못합니다.
- V0.4 constraints는 residual을 평가하지만 임의의 CAD B-Rep 또는 비선형 제약을 자동 완전 해결하지 않습니다.
- V0.6 direct score와 generated target은 사람의 미적 승인이나 metric accuracy를 대체하지 않습니다.
- 실내 semantic visibility는 승인된 다각도에서 ID가 보이는지 나타낼 뿐 실내 완성도나 레퍼런스 유사도를 뜻하지 않습니다.
- V0.7은 static asset, engine-neutral FBX/GLB package 범위입니다. Rig, skinning, animation, prefab/actor, runtime shader는 포함하지 않습니다.
- V0.9 Destination Handoff는 목적지 Codex를 위한 계약과 안전한 import prompt를 생성할 뿐 목적지 엔진을 실행하거나 프로젝트를 수정하지 않습니다.
- 현재 문서는 Unity/Unreal 자동 adapter나 V1.1 이후 기능이 구현된 것으로 가정하지 않습니다.
