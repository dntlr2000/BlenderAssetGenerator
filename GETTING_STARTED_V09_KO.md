# V0.9 빠른 시작

V0.9는 V0.8 workflow 위에 read-only audit, 환경 증거, single-worker queue, PDF 보고서, 두 가지 명시적 실행 모드를 가진 Asset Production Dispatcher/Controller와 Codex Destination Handoff를 추가한다. 기존 SceneSpec, 재질, QA와 V0.7 package 계약은 그대로 유지된다.

직접 제작한 정적 `.blend`/`.fbx`/`.glb`는
[External Static Asset Intake](EXTERNAL_STATIC_ASSET_INTAKE_KO.md)로 exact-hash source를
등록한 뒤 같은 V0.7 package와 V0.9 audit/handoff 경로를 사용할 수 있다.

## 1. 설치 및 백업

업데이트 전 저장소와 외부 workspace를 백업하거나 Git 기준점을 만든다. V0.9는 자동 migration을 수행하지 않으므로, 기존 job을 복사해 확인한 뒤 원본을 유지하는 방식이 안전하다.

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm blender-compat
```

`blender-compat`만 실제 Blender 프로세스를 실행한다. `stability-probe`는 그 결과를 hash로 참조한다.

## 2. 환경 증거 생성

```powershell
uv run cbm stability-probe --probe-id probe-local-001
```

결과:

```text
reports/v09/environment/probe-local-001/environment_probe.json
```

OS나 Blender가 감지됐다는 사실만으로 지원됐다고 판단하지 않는다. 실제 gate가 통과한 조합만 검증 기록에 넣는다.

## 3. workspace audit

External Static Asset Intake job에서는 audit가 source/dependency, plan, consumed approval,
normalization receipt, normalized `.blend`, material contract와 build fingerprint를
읽기 전용으로 재검증한다. stale 또는 tampered intake를 자동 수리하거나 SceneSpec으로
변환하지 않는다.

특정 job만 감사:

```powershell
uv run cbm workspace-audit `
  --job-id first_reference_test `
  --audit-id audit-first-reference-001
```

전체 workspace 감사:

```powershell
uv run cbm workspace-audit --audit-id audit-all-001
```

Audit는 파일을 수정하거나 migration하지 않는다. `failed`라면 JSON의 `findings`에서 code, relative path, 영향과 권장 조치를 확인한다. 실내 QA가 존재하면 strict `0.6.0` plan/approval/source inventory/render manifest/report/candidate/latest 계약, 상대 경로, 개별 hash와 stale source binding도 읽기 전용으로 검사한다.

선택적 V0.6 bounded convergence 세션이 있으면 audit는 initial
SceneSpec/build/constraint snapshot, exact plan/approval, QA·candidate·build receipt
chain, before/after constraint evidence, terminal JSON과 PDF sidecar를 함께
검증합니다. `visual_convergence_status=valid`는 해당 세션의 historical evidence가
온전하다는 뜻이며 현재 모델의 품질 합격이나 재실행 승인이 아닙니다.
신규 실행 binding이 없는 legacy partial plan은 status-only evidence로 취급되므로
승인하거나 재개하지 말고 current direct QA에서 새 plan을 작성합니다.

## 4. PDF 보고서

```powershell
uv run cbm stability-report-pdf `
  --probe-id probe-local-001 `
  --audit-id audit-first-reference-001 `
  --report-id stability-first-reference-001
```

PDF와 sidecar:

```text
output/pdf/v09/stability-first-reference-001/
├─ stability_report.pdf
└─ stability_report.manifest.json
```

판정의 원본은 PDF가 아니라 sidecar가 가리키는 strict JSON이다.

## 5. 기존 workflow를 queue로 진행

먼저 V0.8 workflow가 존재해야 한다.

```powershell
uv run cbm queue-enqueue <job-id> <workflow-id> `
  --priority 50 --max-attempts 3
uv run cbm queue-status
uv run cbm queue-run --max-entries 1 --max-host-steps 1
```

정상적으로 agent 저작이나 승인 단계에서 멈추면 entry는 `waiting`이다. Queue는 승인이나 modeling plan을 대신 만들지 않는다.

실패한 entry의 같은 host step을 다시 시도하기로 사용자가 결정한 경우에만:

```powershell
uv run cbm queue-requeue <entry-id> --retry-failed
uv run cbm queue-run --max-entries 1
```

Queue dispatch만 취소하려면:

```powershell
uv run cbm queue-cancel <entry-id> --reason "user cancelled dispatch"
```

이는 underlying V0.8 workflow를 취소하지 않는다.

## 5A. Asset Production Dispatcher와 Delegated Controller

새 레퍼런스, 사용 목적, 모델링 범위와 목적지 힌트를 한 번에 전달하려면 Asset
Production Dispatcher를 사용할 수 있다. 기본 실행 정책은 `standard`이며
`background_exterior`는 실내·실측·rig·animation·gameplay가 없는 적격 정적 외관에만
명시적으로 선택한다.

```powershell
uv run cbm production-dispatch `
  --request "새 레퍼런스를 engine-neutral static package까지 단계적으로 제작" `
  --reference <reference-path> `
  --purpose "<asset-purpose>" `
  --job-id <job-id> `
  --mode concept `
  --content-scope full_reference `
  --policy standard `
  --ctrl-mode client_mediated `
  --profile portable_gltf `
  --dest-kind unspecified
```

`--ctrl-mode`의 기본값은 `client_mediated`다. 별도 supporting-client bridge 없이 현재
Codex Desktop 작업이 controller를 맡게 하려면 사용자가 명시적으로
`--ctrl-mode desktop_in_session`을 선택한다. 이 선택은 immutable dispatch evidence에
기록되며 나중에 같은 dispatch를 다른 모드로 바꿀 수 없다.

```powershell
uv run cbm production-dispatch `
  --request "현재 Codex 작업에서 새 정적 자산 제작을 단계적으로 조율" `
  --reference <reference-path> `
  --purpose "<asset-purpose>" `
  --job-id <job-id> `
  --policy standard `
  --ctrl-mode desktop_in_session `
  --profile portable_gltf
```

두 모드 모두 새 V0.8 workflow와 다음 immutable evidence를 준비한다.

`client_mediated`의 생성 직후 상태는 `status=prepared`,
`next_action=bind_client_task`이다. Supporting client가 아래 exact profile을 실제로
강제하고 task binding receipt를 만든 뒤에만 host/agent 작업을 진행할 수 있다.
`desktop_in_session`은 `launch_status=ready_in_session`이고 별도 binding 없이 현재
workflow 경계부터 시작한다. 상태와 launch manifest에는
`approval_isolation=workflow_contract_only`와 tool-profile 미강제 경고가 항상 남는다.

```text
workspaces/<job-id>/production/dispatches/<dispatch-id>/
├─ dispatch_request.json
├─ controller_plan.json
├─ codex_task_prompt.md
├─ task_launch_manifest.json
├─ dispatch_plan.json
├─ controller_state.json
├─ optional task_binding_receipt.json
├─ optional convergence_binding.json
├─ assignments/
├─ advances/
└─ final postflight_audit_receipt.json
```

`controller_state.json`은 편의용 current projection이며 immutable workflow, dispatch와
receipt evidence를 대체하지 않는다.

다음 binding 절차는 `client_mediated`에서만 사용한다. Codex Desktop/App 같은 supporting client가 `codex_task_prompt.md`로 실제 task를 만든다.
그 client는 launch manifest의 `controller_mcp_allowlist`만 노출하고,
`controller_forbidden_mcp_tools`의 approval/retry 도구와 동등한 shell 명령을 거부해야
한다. 실제로 이 정책을 강제한 경우에만 task를 bind한다.

```powershell
uv run cbm production-bind-task <job-id> <dispatch-id> `
  --controller-id <controller-id> `
  --external-task-id <client-task-id> `
  --confirm-tool-profile `
  --tool-profile-sha256 <exact-controller-tool-profile-sha256>
```

Binding receipt는 exact launch manifest, task prompt와 controller-tool-profile SHA-256 및
client enforcement attestation에 결속된다. 이 profile hash는 MCP allowlist, 금지된
approval/retry surface, shell policy와 `required_client_capabilities` 목록을 함께 묶는다.
이 attestation은 task나 사용자를 인증하거나 어떤 승인 권한을 부여하지 않는다.

두 모드의 Controller는 다음 공개 표면으로 상태를 읽고 한 번에 한 안전 행동씩 진행한다.

```powershell
uv run cbm production-status <job-id> <dispatch-id>
uv run cbm production-advance <job-id> <dispatch-id> `
  --controller-id <controller-id>
uv run cbm production-complete-step <job-id> <dispatch-id> `
  --controller-id <controller-id> `
  --step-id <step-id> `
  --input-fingerprint <exact-input-fingerprint> `
  --note "controller authored the exact declared outputs"
```

Controller만 canonical writer다. 최대 3개의 subagent는 read-only advisory 결과만
돌려주고 파일 write allowlist를 받지 않는다. 일반·전문 승인, InteriorScope,
candidate-review/guarded/convergence, V0.7 optimization, Destination Handoff plan과 failed
retry는 각각의 기존 소유 표면에서 별도로 처리한다. Controller는 그 승인을 만들거나
retry를 수행하지 않고, 승인 evidence가 생긴 뒤 다음 `production-advance`에서 상태만
재검증한다. Workflow 완료 후에는 exact terminal state에 묶인 V0.9 read-only postflight
audit receipt를 생성해야 최종 완료다.

`desktop_in_session`은 편의 실행 모드이지 approval-isolated sandbox가 아니다. 현재
작업이 approval/retry 도구에 기술적으로 접근할 수 있더라도, exact hash나 실패 step에
대한 새 사용자 메시지가 없으면 해당 도구를 호출해서는 안 된다. Initial production
요청, 포괄적 승인 또는 목표 점수는 InteriorScope, convergence, V0.7 optimization,
Destination Handoff와 failed retry 승인을 대체하지 않는다.

V0.6 QA 뒤의 bounded 개선 반복까지 같은 production task에서 조율하려면 새 dispatch에
`--convergence bounded_after_v06`, direct-score 목표, silhouette-IoU 목표와 최대 반복 수를
명시한다. 이 모드는 `standard` 전용이고 최초 V0.8 workflow를 `preview_only`로 끝낸다.

```powershell
uv run cbm production-dispatch `
  --request "새 레퍼런스를 V0.6 bounded convergence까지 제작" `
  --reference <reference-path> `
  --purpose "<asset-purpose>" `
  --job-id <job-id> `
  --mode concept `
  --content-scope full_reference `
  --policy standard `
  --ctrl-mode desktop_in_session `
  --convergence bounded_after_v06 `
  --target-direct 0.78 `
  --target-iou 0.80 `
  --min-gain 0.005 `
  --conv-iters 3 `
  --no-handoff
```

Preview workflow가 완료되면 Controller는 `convergence_binding.json`과 exact convergence
plan을 한 번 생성하고 `visual_convergence_plan` 전문 승인에서 멈춘다. 사용자가 기존
`approve_visual_convergence` 표면으로 그 exact plan SHA-256을 승인한 뒤에만 Controller가
iteration을 진행한다. `production-advance` 한 번은 full Blender iteration을 최대 한 번만
실행하거나 복구한다. authored `spatial_v1` 자산은 매 iteration마다 fresh result five-view
구조 evidence가 initial five-view보다 회귀하지 않아야 하며, 회귀하면 rollback한다.

이 delivery의 terminal은 목표 달성뿐 아니라 plateau, manual-only, rollback, budget 또는
기타 정직한 종료 사유일 수 있다. Production 완료는 "목표 품질 달성"과 같은 뜻이 아니다.
V0.7 package나 Destination Handoff가 필요하면 convergence terminal 뒤에 새 standard
workflow를 만들고 각각의 exact 승인을 다시 받아야 한다.

일반 사용자는 같은 역할의 MCP 도구를 Codex에 요청할 수 있으므로 PowerShell을 직접
실행할 필요가 없다. `desktop_in_session`은 이 사용 방식을 위한 모드이며 외부 task API가
필요하지 않다. 다만 per-task MCP/shell 제한을 강제하지 않으므로 안전성은 immutable
workflow 계약, exact fingerprint, single-writer lock, 승인 정지와 postflight audit에
한정된다. 더 강한 controller 도구 격리가 필요하면 `client_mediated`와 이를 실제로
강제하는 supporting client를 사용해야 한다.

## 6. Codex Destination Handoff

Handoff는 `portable_gltf` 또는 `fbx_interchange` package의 clean-import round trip이 `passed`인 경우에만 만들 수 있다. 원본 package 내부를 수정하지 않고 별도의 이동 가능 envelope를 만든다.

먼저 exact plan을 생성한다.

```powershell
uv run cbm handoff-plan <job-id> `
  --profile portable_gltf `
  --package-id <package-id> `
  --handoff-id <handoff-id>
```

결과의 `handoff_plan.json`과 SHA-256을 검토한 뒤 동일 hash로 생성한다.

```powershell
uv run cbm handoff-generate <job-id> `
  --handoff-id <handoff-id> `
  --plan-sha256 <exact-plan-sha256>

uv run cbm handoff-validate <job-id> `
  --profile portable_gltf `
  --package-id <package-id> `
  --handoff-id <handoff-id>

uv run cbm handoff-status <job-id>
```

산출물:

```text
workspaces/<job-id>/exports/destination_handoffs/
└─ <profile>/<package-id>/<handoff-id>/
   ├─ package/
   ├─ evidence/
   ├─ codex_handoff/
   └─ destination_handoff_validation.json
```

사용자는 이 envelope 전체를 목적지 프로젝트로 이동한다. 목적지 Codex에는 `codex_handoff/codex_import_prompt.md`를 주고 `<PACKAGE_PATH>`, `<DESTINATION_PROJECT_ROOT>`, `<OPTIONAL_DESTINATION_HINT>`만 현재 환경에 맞게 해석하게 한다. 목적지 Codex는 import plan과 사용자 승인 전에는 프로젝트 파일을 수정하면 안 된다.

V0.8 portable workflow에 선택적으로 포함하려면 다음 플래그를 사용한다.

```powershell
uv run cbm workflow-plan `
  --request "승인된 정적 자산을 portable package와 Codex handoff로 준비해줘" `
  --job-id <job-id> `
  --intent portable_package `
  --profile portable_gltf `
  --include-destination-handoff
```

OBJ package는 handoff 대상이 아니며, Unity/Unreal/custom engine을 감지했다고 자동 지원이나 runtime parity를 주장하지 않는다.

## 7. 전체 V0.9 gate

```powershell
.\scripts\run_v09_gates.ps1
```

Gate는 Python/Ruff/doctor, Blender compatibility, V0.8 regression, 격리 workflow와 queue, real GLB package·clean import·handoff 생성/검증, audit/privacy, export/stability PDF를 검증한다. 사용자 job 대신 `reports/v09_smoke/` 아래의 격리 workspace를 사용한다.

이미 V0.8 회귀를 별도로 확인한 진단 실행에서만 선택적으로 생략한다.

```powershell
.\scripts\run_v09_gates.ps1 -SkipV08
```

`-SkipCompatibility` 결과로 Blender 지원을 주장하면 안 된다.
`-SkipV07`은 최근 V0.7 full gate 증거가 따로 있는 진단 실행에서만 사용한다.

## 업데이트와 migration 원칙

- V0.2~V0.8 canonical contract version은 바뀌지 않는다.
- 기존 정상 job은 in-place migration 없이 감사하고 재빌드할 수 있다.
- incompatible version은 자동 변경하지 않고 audit finding으로 남긴다.
- migration이 필요하면 원본 백업, 별도 복사본, 명시적 migration plan, 전후 hash와 회귀 검증이 먼저다.
- V0.9 queue나 audit 파일을 canonical SceneSpec의 대체물로 사용하지 않는다.
- 기존 production dispatch, task binding과 advance receipt는 새 정책으로 rewrite하거나 재결속하지 않는다. 변경된 계약은 새 dispatch부터 사용한다.

지원 범위와 실제 통과 결과는 [VERIFICATION_V09_KO.md](VERIFICATION_V09_KO.md)를 확인한다.
