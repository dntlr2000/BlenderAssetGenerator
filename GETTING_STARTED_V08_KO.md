# V0.8 빠른 시작

## 1. 환경 확인

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm workflow-adapters
```

`workflow-adapters`에서 현재 검증된 목적지는 `engine_neutral`이다. Unity/Unreal은 아직 adapter가 없으므로 명시해도 portable package에서 정지한다.

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
