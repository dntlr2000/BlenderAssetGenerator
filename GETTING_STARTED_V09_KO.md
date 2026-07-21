# V0.9 빠른 시작

V0.9는 V0.8 workflow 위에 read-only audit, 환경 증거, single-worker queue와 release-candidate PDF 보고서를 추가한다. 기존 SceneSpec, 재질, QA, package 계약은 그대로 유지된다.

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

Audit는 파일을 수정하거나 migration하지 않는다. `failed`라면 JSON의 `findings`에서 code, relative path, 영향과 권장 조치를 확인한다.

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

## 6. 전체 V0.9 gate

```powershell
.\scripts\run_v09_gates.ps1
```

Gate는 Python/Ruff/doctor, Blender compatibility, V0.8 regression, 격리 workflow와 queue, audit/privacy, stability PDF를 검증한다. 사용자 job 대신 `reports/v09_smoke/` 아래의 격리 workspace를 사용한다.

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
