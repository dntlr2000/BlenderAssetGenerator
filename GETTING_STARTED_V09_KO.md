# V0.9 빠른 시작

V0.9는 V0.8 workflow 위에 read-only audit, 환경 증거, single-worker queue, PDF 보고서와 Codex Destination Handoff를 추가한다. 기존 SceneSpec, 재질, QA와 V0.7 package 계약은 그대로 유지된다.

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

지원 범위와 실제 통과 결과는 [VERIFICATION_V09_KO.md](VERIFICATION_V09_KO.md)를 확인한다.
