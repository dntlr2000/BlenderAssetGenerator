# V0.9 Stabilization & Codex Destination Handoff 아키텍처

V0.9는 새로운 모델링 알고리즘을 대량 추가하는 단계가 아니다. V0.8까지의 분석, 형상, 재질, QA, portable package, workflow를 그대로 보존하면서 설치 환경과 작업 증거를 감사하고, 실패를 재현하며, 제한된 로컬 queue로 기존 workflow를 안전하게 이어 간다. 새 reference를 client-created Codex task와 single-writer controller에 연결하는 Asset Production Dispatcher를 제공하고, 검증된 V0.7 package를 다른 프로젝트의 Codex가 안전하게 해석할 수 있도록 hash-bound 전달 계약을 생성하는 Codex Destination Handoff도 포함한다.

## 계약 경계

| 계층 | 계약 버전 | V0.9 처리 |
|---|---:|---|
| Geometry SceneSpec | `0.2.0` | 변경 없음 |
| Reference / Constraint | `0.4.0` | 변경 없음 |
| InteriorScope | `0.1.0` | 변경 없음 |
| Material / Shader | `0.5.0` | 변경 없음 |
| Visual QA | `0.6.0` | 변경 없음 |
| Portable static asset | `0.7.0` | 변경 없음 |
| Workflow orchestration | `0.8.0` | 변경 없음 |
| Stabilization evidence | `0.9.0` | 신규 |
| Codex Destination Handoff | `0.9.0` | 신규 |
| External Static Asset Intake | `0.9.0` | 신규 static-only source route |
| Asset Production Dispatch / Controller | `0.9.0` | 신규 client-mediated orchestration layer |

V0.9는 오래된 정상 job을 자동 변환하지 않는다. 호환 가능한 계약은 그대로 읽고, 인식할 수 없거나 손상된 계약은 audit finding으로 남긴다.

## 구성 요소

```text
src/codex_blender_modeler/stabilization/
├─ models.py       strict 0.9 contracts
├─ locks.py        expiring O_EXCL queue writer lock
├─ service.py      environment probe, workspace audit, local queue
└─ pdf_report.py   exact JSON hashes에서 파생되는 stability PDF

src/codex_blender_modeler/handoff/
├─ models.py       strict handoff·destination import 계약
├─ service.py      plan, immutable envelope 생성, 검증과 status
└─ pdf_report.py   authoritative handoff JSON에서 파생되는 PDF

src/codex_blender_modeler/external_intake/
├─ models.py       strict intake·approval·manifest·receipt·validation 계약
└─ service.py      safe inspection, exact 승인, 정규화, provenance와 status

src/codex_blender_modeler/production/
├─ models.py       strict dispatch·launch·binding·assignment·state·receipt 계약
├─ prompting.py    exact hash를 포함한 controller task prompt
├─ service.py      dispatch, binding, controller advance, postflight audit
└─ validation.py   launch profile, receipt chain과 stale/tamper 검증
```

새 스키마는 다음과 같다.

```text
schemas/
├─ environment_probe.schema.json
├─ workspace_audit.schema.json
├─ local_workflow_queue.schema.json
├─ queue_attempt_receipt.schema.json
├─ queue_lock.schema.json
└─ stability_report_manifest.schema.json

schemas/
├─ destination_handoff_plan.schema.json
├─ destination_handoff_manifest.schema.json
├─ destination_handoff_validation.schema.json
├─ destination_context.schema.json
├─ assembly_manifest.schema.json
├─ material_mapping.schema.json
├─ import_checklist.schema.json
├─ destination_import_plan.schema.json
├─ destination_import_receipt.schema.json
├─ destination_import_validation.schema.json
└─ handoff_report_manifest.schema.json

schemas/
├─ asset_production_dispatch_request.schema.json
├─ delegated_production_controller_plan.schema.json
├─ codex_task_launch_manifest.schema.json
├─ asset_production_dispatch_plan.schema.json
├─ codex_task_binding.schema.json
├─ codex_task_binding_receipt.schema.json
├─ delegated_work_assignment.schema.json
├─ delegated_production_advance_receipt.schema.json
├─ delegated_production_state.schema.json
├─ production_convergence_binding.schema.json
└─ production_postflight_audit_receipt.schema.json
```

## Asset Production Dispatcher와 Delegated Controller

Dispatcher는 새 레퍼런스와 사용 목적, content scope, delivery profile 및 목적지 힌트를
받아 새 V0.8 `new_asset` workflow와 V0.9 launch bundle을 함께 만든다. `standard`가
기본이며 `background_exterior`는 명시적 opt-in이다. 빠른 경로는 initial dispatch에서
Destination Handoff를 포함하지 않고 passed package 뒤에 별도 handoff 경계를 사용한다.

```text
user objective + immutable reference
→ new V0.8 workflow
→ immutable dispatch/controller/launch contracts
→ supporting client creates the Codex task
→ exact task binding receipt
→ one controller action at a time
   ├─ deterministic V0.8 host step
   ├─ read-only advisory assignment
   ├─ existing approval/failure boundary
   └─ controller-authored exact agent output
→ completed workflow
→ optional standard V0.6 bounded convergence
   ├─ exact convergence plan + binding
   ├─ external exact plan-hash approval
   ├─ at most one full Blender iteration per advance
   └─ terminal evidence or rollback
→ exact-state-bound read-only V0.9 postflight audit receipt
```

`task_launch_manifest.json`은 `client_mediated`, `task_created_by_repository=false`를
명시한다. 또한 allowlist-only `controller_mcp_allowlist`, 금지할 approval/retry MCP
목록, `approval_and_retry_commands_denied` shell 정책과 client enforcement requirement를
기록한다. Supporting client는 실제 task 생성·재개, MCP allowlist와 shell/tool 제한을
제공해야 한다. `task_binding_receipt.json`은 exact launch manifest, task prompt,
controller-tool-profile SHA-256과 `client_tool_policy_enforced=true` attestation을 하나의
immutable dispatch plan에 결속한다. 이 profile digest는 MCP allow/deny 목록과 shell
정책뿐 아니라 launch가 요구한 exact client capability 목록도 포함한다.

Controller allowlist는 `get_asset_production_dispatch_status`,
`advance_delegated_production_controller`, `record_delegated_production_step` 세 MCP 도구로
고정된다. Dispatch 생성·task binding·approval·failed retry·queue dispatch는 controller
밖의 소유 표면이다.

Controller가 유일한 canonical writer다. Subagent는 최대 3개의 병렬 read-only reviewer
역할만 수행하며 write allowlist는 비어 있다. Assignment는 exact workflow plan과 input
fingerprint, 읽을 artifact와 controller expected output을 결속한다. Controller가 이를
종합해 현재 V0.8 step이 선언한 output만 작성한 뒤 기존 completion marker를 기록한다.

Controller는 generic checkpoint, InteriorScope, interior-camera, guarded/candidate-review,
V0.7 optimization, Destination Handoff 또는 failed retry 승인을 생성·추론·대체하지 않는다.
`bounded_after_v06` dispatch에서도 Controller는 completed preview에서 exact convergence
plan만 만들고 `visual_convergence_plan`에서 멈춘다. 기존 V0.6 승인 표면에 exact plan
승인이 생긴 뒤에만 iteration을 실행하며, 한 advance에서 full Blender iteration은 최대
한 번이다. 각 advance는 이전 receipt SHA-256, 전후 workflow state bytes, dispatch plan과
선택적인 convergence progress artifact를 결속하는 immutable chain이다.

Bounded production은 `standard + preview_only` V0.8 workflow를 baseline historical
evidence로 보존한다. 승인된 convergence가 canonical SceneSpec을 합법적으로 승격한 뒤에는
그 baseline workflow를 다시 reconcile해 stale로 변조하지 않는다. 대신
`convergence_binding.json`이 initial QA, exact plan과 workflow-state fingerprint를 결속하고,
postflight는 terminal convergence directory와 binding을 다시 검증한다. authored
`spatial_v1`은 initial/result five-view 구조 비회귀를 매 iteration의 필수 veto로 사용한다.
Terminal은 target reached뿐 아니라 plateau, manual-only, rollback 또는 budget 종료일 수
있으므로 production completion은 목표 품질 달성 주장과 분리된다. V0.7 package와 handoff는
이후 새 standard workflow에서 별도 exact 승인을 받아야 한다.

최종 postflight receipt는 audit 도중 workflow/convergence evidence가 변하지 않았는지와
모든 terminal artifact를 원자적으로 확인한다.

이 계층은 supporting client를 보안 sandbox로 대체하지 않는다. 저장소는 launch/binding/
assignment/receipt 변조를 fail-closed로 검출할 수 있지만, 스스로 Codex task를 생성·인증할
수 없고 client가 허용한 임의 shell을 악성 controller가 우회 사용하는 것까지 막는다고
보장하지 않는다.

## External Static Asset Intake

외부에서 직접 제작한 `.blend`, `.fbx`, `.glb` 정적 자산은 SceneSpec을 꾸며 내지
않고 별도 source route로 들어온다. 원본은 auto-execution을 끈 Blender 5 검사와
전후 SHA-256 확인을 거쳐 새 job의 immutable evidence로 복사된다. 이미지
dependency도 job-relative 경로와 exact hash로 결속한다. `.gltf`는 sidecar 의존성
경계가 모호하므로 현재 지원하지 않는다.

```text
untrusted external source
→ safe read-only inspection
→ workflow-owned intake plan
→ exact plan SHA-256 approval
→ meter-normalized script-free authoring derivative
→ strict intake validation
→ existing V0.7 optimization/package/roundtrip
→ optional V0.9 Destination Handoff
```

Inspection은 armature, action, NLA, driver, linked geometry, 누락 이미지,
OSL Script node와 movie/sequence texture를 blocker로 처리한다. 정규화는 render-visible
evaluated static mesh/curve만 보존하고 multi-material object를 material별 단일-material
semantic submesh로 나눈다. hierarchy, stable semantic/material ID, UV와 source unit
conversion은 manifest에 기록한다.

정규화된 `.blend`에는 원래 Blender master material graph를 보존하지만 portable
계약은 이를 destination shader로 간주하지 않는다. V0.7 material conversion이 raw
PBR channel로 bake하고 package/roundtrip evidence에 묶는다. 따라서 전달되는 것은
원본 shader parity가 아니라 보존된 master authoring graph와 검증 가능한 portable
PBR 결과다.

Windows의 깊은 package/handoff 경로는 native extended-length I/O로 읽고 복사한다.
이는 legacy 260-character 제한만 우회하며, 상대 경로 containment, symlink/junction,
dependency와 SHA-256 검사를 완화하지 않는다.

## Codex Destination Handoff

V0.7 package manifest는 package에 선언되지 않은 파일을 허용하지 않고 package 자체가 immutable하므로, handoff를 원본 package 내부에 덧붙이지 않는다. 생성기는 passed round-trip package를 byte-for-byte 복제한 별도 이동 가능 봉투를 만든다.

```text
exports/destination_handoffs/<profile>/<package-id>/<handoff-id>/
├─ package/                         exact V0.7 package copy
├─ evidence/
│  ├─ roundtrip_validation.json
│  └─ roundtrip_evidence.json
├─ codex_handoff/
│  ├─ handoff_manifest.json
│  ├─ destination_context.json
│  ├─ assembly_manifest.json
│  ├─ material_mapping.json
│  ├─ import_checklist.json
│  ├─ codex_import_prompt.md
│  ├─ known_limitations.md
│  ├─ schemas/
│  ├─ handoff_report.pdf
│  └─ handoff_report.manifest.json
└─ destination_handoff_validation.json
```

생성 전에는 package manifest, 모든 package receipt, clean-import round trip과 evidence hash를 다시 확인한다. GLB와 FBX만 허용하고 OBJ는 handoff 대상에서 거부한다. 생성 중 원본 package snapshot을 전후 비교하며, canonical SceneSpec·geometry·authoring `.blend`·source texture는 읽거나 복사 근거로만 사용하고 수정하지 않는다.

`handoff_manifest.json`은 정확한 package manifest SHA-256, primary model, texture, semantic/material identity, assembly/material mapping, LOD/Collider, prompt와 전체 envelope receipt를 결속한다. 경로는 package-relative POSIX path만 허용하며 absolute path, traversal, symlink·junction 같은 link-like entry와 누락 dependency는 실패한다.

목적지 프롬프트는 package 내용을 untrusted data로 취급한다. 목적지 Codex는 엔진·버전·렌더 파이프라인을 탐지한 뒤 파일 변경 전에 `import_plan.json`을 작성하고 승인을 받아야 한다. 승인 후에만 import·재조립을 수행하고 `import_receipt.json`과 `import_validation.json`을 남긴다. Blender master shader의 직접 이전, runtime parity, Unity/Unreal API 호출은 보장하지 않는다.

V0.8 workflow에서는 GLB/FBX portable package의 최종 승인 뒤 선택적인 `destination.handoff` agent step으로 연결한다. Completion marker는 exact package와 handoff output hash에 결속된다. V0.9 audit와 stability/full PDF는 handoff의 current/valid 상태를 표시하지만 자동으로 repair하지 않는다.

## 환경 probe

`stability-probe`는 현재 OS, architecture, Python, 프로젝트와 계약 버전, Blender executable의 파일명, 기존 `reports/blender_compatibility.json`의 hash와 판정을 기록한다.

중요한 경계:

- Blender를 실행하는 명령은 `blender-compat`이며, `stability-probe`는 기존 증거만 읽는다.
- 감지 결과는 지원 선언이 아니다.
- absolute repository/workspace/source 경로는 JSON에 저장하지 않는다.
- 실제 실행하지 않은 macOS, Linux, Blender 또는 목적 엔진은 `unverified`다.

## workspace audit

`workspace-audit`는 지정 job 또는 workspace를 bounded scan한다.

검사 대상:

- job ID와 metadata의 일치
- immutable source의 존재, containment와 SHA-256
- known contract의 JSON readability와 version compatibility
- workflow `latest.json`의 dangling pointer
- optional interior QA `latest.json`의 plan/approval/source/render/report/candidate hash binding과 stale source
- optional standard Visual QA convergence의 plan/approval, contiguous iteration receipt와 support-artifact hash chain
- active convergence session의 current input/SceneSpec/QA/candidate/build/constraint freshness
- initial SceneSpec, build provenance와 optional constraint snapshot exact binding
- source/result QA·candidate·build lineage와 SceneSpec 외 build-contract 불변
- exact before/after constraint evidence에서 재계산한 regression count와 acceptance
- terminal convergence report, final QA metrics/high findings, historical input map과 PDF sidecar source binding
- orphan cancellation/final/PDF evidence와 terminal replay 시도
- 링크나 junction을 통한 source path escape
- interrupted/temp evidence와 scan limit
- production dispatch의 launch/profile/task-binding/assignment/advance/postflight receipt hash chain과 stale workflow binding

Audit는 읽기 전용이다. migration, repair, delete, SceneSpec 재작성 또는 `.blend` 재생성을 수행하지 않는다. 결과는 `reports/v09/audits/<audit-id>/workspace_audit.json`에 immutable하게 저장된다.

실내 QA가 존재하면 audit는 최신 pointer가 가리키는 모든 파일을 strict `0.6.0` 계약으로 읽고 job-relative path, exact plan binding과 source freshness를 확인한다. Finding을 이유로 카메라 계획, `.blend`나 canonical geometry를 자동 수정하지 않는다.

convergence가 존재하면 job과 workspace summary에 session count,
valid-session count와 `not_requested|active|valid|invalid` 상태를 기록한다. Active
session은 현재 immutable input set, canonical SceneSpec, current exact QA와
candidate bundle, build provenance와 optional constraint snapshot이 plan/receipt
chain에 그대로 묶여 있어야 한다. Planning만
완료된 세션도 current source가 달라지면 invalid다.

Terminal session은 현재 canonical asset을 다시 승인하는 상태가 아니라 immutable
historical evidence다. Audit는 plan에 저장된 원래 input-file hash map, exact
approval, contiguous receipts와 selection/RevisionPlan/authorization/base/result
SceneSpec, source/result QA와 candidates, source/result build provenance,
before/after constraint snapshot, terminal report와 PDF sidecar를 검증한다.
완료 뒤 추가된 auxiliary input이나 별도 authoring revision은 원래 파일과
iteration chain이 보존된 경우 historical session을 invalid로 바꾸지 않는다.
반대로 원래 input 파일이나 session-owned artifact가 바뀌면 invalid다. 원래
파일별 map이 없는 compatible legacy terminal session은 aggregate fingerprint로
읽되 후속 파일 추가와 원본 변경을 구분할 수 없다는 warning을 남긴다.
신규 initial binding이 없는 legacy active/partial plan은 historical status-only로
분류하며 승인이나 실행 가능한 상태로 보고하지 않는다.

V0.9 audit는 convergence를 resume, cancel, repair하거나 새로운 approval을 만들지
않는다. V0.9 local queue도 기존 V0.8 workflow 전용이므로 별도 V0.6 convergence
session을 실행하지 않는다.

## single-worker local queue

Queue는 새 작업 planner가 아니라 이미 존재하는 V0.8 workflow의 제한된 host-step dispatcher다.

```text
existing Workflow 0.8
→ queue-enqueue
→ single writer lock + execution lease
→ workflow-resume의 결정론적 host step
→ agent/review/specialized approval에서 정상 정지
→ immutable queue attempt receipt
```

안전 속성:

- `max_concurrency=1`
- job/workflow당 active entry 1개
- live lock은 동시 writer를 거부
- expired lock만 archive 후 복구
- 실패 자동 재시도 없음
- `--retry-failed`는 한 번만 소비되는 명시적 권한
- queue cancel은 underlying workflow를 취소하거나 파일을 삭제하지 않음
- generic queue 동작은 InteriorScope, Visual QA, V0.7 optimization 승인을 만들지 않음

Queue state는 workspace의 `.cbm/queue/` 아래에 있다. 이는 operational state이며 canonical 자산 계약이 아니다.

Production Controller는 queue와 별도다. Queue는 이미 존재하는 workflow의 deterministic
host step만 실행하지만, production layer는 새 workflow와 client launch bundle을 만들고
agent-authored 경계를 controller가 조율한다. 어느 쪽도 승인을 합성하거나 failed step을
자동 재시도하지 않는다.

## PDF projection

`stability-report-pdf`는 정확한 environment probe와 workspace audit ID를 받아 다음을 만든다.

```text
output/pdf/v09/<report-id>/
├─ stability_report.pdf
└─ stability_report.manifest.json
```

Sidecar는 PDF SHA-256, source fingerprint, repository-relative source paths, 각 JSON의 SHA-256과 byte size를 보존한다. PDF는 사람이 읽는 표현일 뿐이며 release 판정, migration 또는 revision 입력으로 다시 파싱하지 않는다.

Workspace audit가 convergence evidence를 발견하면 stability PDF는 valid/total
session count와 job별 상태를 투영한다. 이 표시는 audit JSON의 파생 결과이며
active session을 완료하거나 invalid session을 복구하지 않는다.

## 실패와 복구 모델

- Audit failure: 데이터를 고치지 않고 finding과 영향만 보고한다.
- Convergence audit failure: plan, approval, iteration evidence, QA 또는 PDF binding을 고치지 않고 invalid finding과 별도 새 session 필요 여부만 보고한다.
- Queue host failure: failed receipt를 남기고 explicit requeue를 기다린다.
- Process interruption: V0.8 workflow attempt와 queue lease를 기준으로 다음 실행에서 abandoned state를 식별한다.
- Live lock: 기다리거나 명시적으로 중단하며 덮어쓰지 않는다.
- Expired lock: 원본 lock evidence를 archive하고 새 lock을 획득한다.
- Budget/approval/agent boundary: 실패가 아니라 정상 waiting 상태다.

## V0.9의 비목표

- Unity, Unreal 또는 custom engine API를 직접 호출하는 자동 Destination Adapter
- 다중 worker나 distributed scheduler
- legacy contract 자동 migration
- 손상 job 자동 repair
- rig, skinning, animation
- CAD B-Rep parser와 solver
- cross-platform 지원 선언
- repository 단독 Codex task 생성·인증 또는 supporting client의 unenforced shell 우회 방지 보장

자동 Destination Adapter는 목적 엔진·버전·렌더 파이프라인이 확정된 뒤 V1.1 이후 범위다. V1.0 승격은 현재 중단되어 있으며, V0.9 완료는 engine-neutral GLB/FBX package, clean-import round trip, hash-bound Codex Destination Handoff와 기존 V0.7~V0.9 회귀 통과를 기준으로 판정한다.
