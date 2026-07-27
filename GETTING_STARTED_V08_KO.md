# V0.8 빠른 시작

## 1. 환경 확인

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm workflow-adapters
```

`workflow-adapters`에서 현재 검증된 목적지는 `engine_neutral`이다. Unity/Unreal은 아직 adapter가 없으므로 명시해도 portable package에서 정지한다.

## 1.1 PowerShell 없이 실행 정책 선택하기

일반 자산은 `execution_policy=standard`가 기본값이다. 실내·실측·리깅·애니메이션·게임 로직이 필요 없는 새 정적 배경 외관만 명시적으로 `background_exterior`를 선택한다. 이것은 별도 모델링 파이프라인이 아니라 같은 V0.4~V0.7 단계를 보수적으로 축약한 V0.8 실행 정책이다.

| 선택 | 종료 범위 | 생략되는 일반 검토 | 반드시 남는 경계 |
|---|---|---|---|
| `standard` | 기존 `scope` 규칙 | 없음 | 기존 일반·전용 승인 전체 |
| `background_exterior + preview_only` | 재질·직접 QA·통합 PDF | 프록시, 상세, swatch, QA 일반 승인 | agent completion; 별도 전용 작업은 별도 workflow와 exact-hash 승인 |
| `background_exterior + portable_package` | V0.7 package와 round trip | 위 일반 승인과 최종 package 일반 승인 | 정확한 V0.7 optimization-plan 승인 |

이미지를 첨부한 Codex 대화에서 다음 내용을 복사해 사용할 수 있다. Codex가 `plan_short_workflow`와 후속 MCP 도구를 호출하므로 사용자가 PowerShell 명령을 직접 실행할 필요가 없다.

```text
<REFERENCE_PATH>의 새 레퍼런스로 <JOB_ID> 배경 외관 자산을 만들어줘.
V0.8 workflow를 intent=new_asset, scope=auto,
execution_policy=background_exterior, delivery_scope=preview_only,
mode=concept, destination_kind=engine_neutral,
include_destination_handoff=false로 계획해.
V0.4 분석과 중간 크기 외형 1회 작성, V0.5 로컬 결정론적 재질,
V0.6 직접 reference QA 1회와 통합 PDF까지만 MCP로 진행해.
실내, measured input, rig, animation, gameplay, 외부 provider,
생성 QA target과 자동 revision은 사용하지 마.
완료하면 status=completed, milestone=delivered_for_review와
preview/PDF 경로를 보고해.
조건을 벗어나는 문제가 발견되면 completion marker를 기록하지 말고
requires_standard_workflow로 멈춰서 이유를 설명해.
```

직접 QA에서 high-severity direct-reference 또는 constraint 문제가 하나라도 발견되면 post-QA eligibility report가 `ok=false`와 `requires_standard_workflow`를 기록하고 통합 delivery를 차단한다. 이 상태는 같은 fast plan의 재시도 대상이 아니며 새 `standard` workflow를 계획해야 한다. 낮은 점수 자체를 완성도 백분율이나 자동 수정 승인으로 해석하지 않는다.

패키지까지 필요한 경우에는 시작할 때 종료 범위를 바꾼다.

```text
<REFERENCE_PATH>의 새 레퍼런스로 <JOB_ID> 정적 배경 외관을 만들고
engine-neutral FBX package까지 준비해줘.
intent=new_asset, scope=auto,
execution_policy=background_exterior,
delivery_scope=portable_package,
profile_id=fbx_interchange, destination_kind=engine_neutral,
include_destination_handoff=false로 V0.8 workflow를 계획해.
일반 중간 승인만 생략하고, V0.7 optimization review와
정확한 review_plan SHA-256 승인이 필요해지면 반드시 멈춰서 보고해.
승인 전에는 optimize, package, round trip을 실행하지 마.
```

이미 `background_exterior + preview_only`가 완료된 동일 job을 나중에 package로 확장할 때는 기존 workflow를 변경하지 않고 새 immutable workflow를 만든다.
새 package workflow는 완료된 preview의 workflow/plan/terminal/QA run과
canonical source/build fingerprint에 결속되며 V0.7 시작 전에 다시 검증한다.

```text
완료된 <JOB_ID> 배경 preview를 canonical 변경 없이
engine-neutral FBX package로 확장해줘.
새 V0.8 workflow를 intent=portable_package,
execution_policy=background_exterior,
delivery_scope=portable_package,
profile_id=fbx_interchange로 계획해.
V0.7 optimization plan의 정확한 SHA-256 승인에서 멈춰.
```

`background_exterior`는 사용자의 포괄적 “전부 승인” 문장을 전용 승인으로 해석하지 않는다. InteriorScope, interior QA camera plan, V0.6 후보 적용, V0.7 optimization plan과 destination handoff는 각 계약의 exact-hash 승인 규칙을 그대로 따른다. Destination Handoff는 빠른 workflow 안에 포함할 수 없으며, 통과한 package를 대상으로 별도 표준 handoff 흐름을 계획한다.

## 2. 새 이미지로 프록시 workflow 만들기

```powershell
uv run cbm workflow-plan `
  --request "이 이미지로 수정 가능한 3D 프록시를 만들어줘" `
  --job-id temple_asset `
  --reference-path E:\References\temple.png
```

출력의 `workflow_id`를 기록한다. 같은 값은 다음에서도 확인할 수 있다.

```powershell
uv run cbm workflow-status temple_asset
```

첫 host 단계를 실행한다.

```powershell
uv run cbm workflow-resume temple_asset <workflow-id>
```

기본 scope는 `proxy_only`이므로 V0.4 분석, modeling plan과 SceneSpec 저작, build/render/inspect/validate를 거쳐 프록시 승인에서 멈춘다. Agent 단계는 Codex가 산출물을 작성한 뒤 현재 `input_fingerprint`로 completion marker를 남겨야 한다.

```powershell
uv run cbm workflow-complete-step temple_asset <workflow-id> `
  --step-id geometry.modeling_plan `
  --input-fingerprint <state에 표시된 값> `
  --note "Modeling plan authored from current reference diagnostics"
```

프록시를 실제로 확인한 뒤에만 현재 gate fingerprint를 승인한다.

승인 전에 `workspaces/temple_asset/reports/pdf/proxy_report.pdf`와 대응 manifest가 생성된다. PDF는 사람이 읽기 위한 보고서이며 승인 fingerprint는 canonical JSON과 렌더 hash를 포함한 workflow state에서 가져온다.

```powershell
uv run cbm workflow-approve temple_asset <workflow-id> `
  --step-id geometry.proxy_approval `
  --artifact-fingerprint <state에 표시된 값> `
  --approval-note "프록시 실루엣과 객체 분리를 승인"
```

## 3. 기존 작업에 명시적 의도 사용하기

기존 `job_id`에는 같은 reference를 다시 지정하더라도 `new_asset`을 사용할 수 없다. 현재 자산의 변경은 반드시 `revise_asset`을 사용하고, 독립된 새 자산은 새로운 고유 `job_id`로 생성한다.

### 형상 수정

```powershell
uv run cbm workflow-plan `
  --request "중앙 탑 높이만 10% 높여줘" `
  --job-id temple_asset `
  --intent revise_asset
```

V0.8은 RevisionPlan 저작까지 조율하지만 V0.6/V0.2의 전용 승인 없이 canonical 변경을 적용하지 않는다.

### 보조 시점 추가

```powershell
uv run cbm workflow-plan `
  --request "정면도를 추가해 다시 분석해줘" `
  --job-id temple_asset `
  --reference-path E:\References\temple_front.png `
  --intent add_measured_view `
  --view-kind front
```

새 이미지는 먼저 workflow staging에 복사된다. host 단계가 실행될 때만 기존 `add_view` 안전 규칙을 통해 canonical input으로 승격된다.

### 재질 또는 QA

```powershell
uv run cbm workflow-plan --request "재질과 셰이더를 구성해줘" `
  --job-id temple_asset --intent material_authoring

uv run cbm workflow-plan --request "레퍼런스 기준 Visual QA를 실행해줘" `
  --job-id temple_asset --intent visual_qa
```

승인된 InteriorScope의 실내만 여러 각도에서 검사하려면 별도 의도를 사용한다.

```powershell
uv run cbm workflow-plan `
  --request "승인된 실내만 여러 각도에서 구조 QA해줘" `
  --job-id temple_asset `
  --intent interior_visual_qa
```

이 workflow는 scope validation → interior QA plan에서 시작하고 `interior_qa_plan` 전용 승인 gate에서 멈춘다. exact plan SHA-256 승인 뒤에만 선택된 view마다 7개 pass를 렌더하고 QA PDF review로 진행한다. 일반 workflow approval은 카메라 계획 승인을 대신하지 않으며, 임시 카메라나 visibility 상태를 authoring `.blend`에 저장하지 않는다.

## 4. V0.7 최적화와 FBX 패키지

```powershell
uv run cbm workflow-plan `
  --request "엔진 중립적인 FBX 패키지를 준비해줘" `
  --job-id temple_asset `
  --intent portable_package `
  --profile fbx_interchange
```

이 workflow는 preflight 뒤 LOD, collider, cleanup, consolidation, budget 설정을 `optimization_review.json`으로 보여준다. 다음 전용 명령으로 exact plan SHA-256을 승인하기 전에는 optimize를 실행하지 않는다.

```powershell
uv run cbm asset-plan-approve temple_asset `
  --run-id <run-id> `
  --plan-sha256 <review-plan-sha256> `
  --approval-note "표시된 LOD와 Collider 설정을 승인"
```

Unity나 Unreal을 요청해도 해당 adapter가 검증되기 전에는 이 engine-neutral package까지만 진행한다.

## 5. 상태 재구성, 실패 재시도, 취소

```powershell
uv run cbm workflow-reconcile temple_asset <workflow-id>
```

host 단계가 실패하면 먼저 오류 원인을 수정한다. 자동 retry는 없다.

```powershell
uv run cbm workflow-resume temple_asset <workflow-id> --retry-failed
```

향후 실행만 중단하고 증거는 보존하려면:

```powershell
uv run cbm workflow-cancel temple_asset <workflow-id> `
  --reason "사용자 요청으로 현재 workflow 종료"
```

취소된 workflow는 재개하지 않는다. 같은 자산의 새 요청은 새 workflow로 계획한다.

## 6. 전체 게이트

```powershell
.\scripts\run_v08_gates.ps1
```

V0.8 orchestration만 빠르게 검사하고 이미 검증된 V0.7 Blender gate를 생략하려면:

```powershell
.\scripts\run_v08_gates.ps1 -SkipV07
```
