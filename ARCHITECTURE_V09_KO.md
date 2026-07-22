# V0.9 Stabilization & Codex Destination Handoff 아키텍처

V0.9는 새로운 모델링 알고리즘을 대량 추가하는 단계가 아니다. V0.8까지의 분석, 형상, 재질, QA, portable package, workflow를 그대로 보존하면서 설치 환경과 작업 증거를 감사하고, 실패를 재현하며, 제한된 로컬 queue로 기존 workflow를 안전하게 이어 간다. 여기에 검증된 V0.7 package를 다른 프로젝트의 Codex가 안전하게 해석할 수 있도록 hash-bound 전달 계약을 생성하는 Codex Destination Handoff를 포함한다.

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
```

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
- 링크나 junction을 통한 source path escape
- interrupted/temp evidence와 scan limit

Audit는 읽기 전용이다. migration, repair, delete, SceneSpec 재작성 또는 `.blend` 재생성을 수행하지 않는다. 결과는 `reports/v09/audits/<audit-id>/workspace_audit.json`에 immutable하게 저장된다.

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

## PDF projection

`stability-report-pdf`는 정확한 environment probe와 workspace audit ID를 받아 다음을 만든다.

```text
output/pdf/v09/<report-id>/
├─ stability_report.pdf
└─ stability_report.manifest.json
```

Sidecar는 PDF SHA-256, source fingerprint, repository-relative source paths, 각 JSON의 SHA-256과 byte size를 보존한다. PDF는 사람이 읽는 표현일 뿐이며 release 판정, migration 또는 revision 입력으로 다시 파싱하지 않는다.

## 실패와 복구 모델

- Audit failure: 데이터를 고치지 않고 finding과 영향만 보고한다.
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

자동 Destination Adapter는 목적 엔진·버전·렌더 파이프라인이 확정된 뒤 V1.1 이후 범위다. V1.0 승격은 현재 중단되어 있으며, V0.9 완료는 engine-neutral GLB/FBX package, clean-import round trip, hash-bound Codex Destination Handoff와 기존 V0.7~V0.9 회귀 통과를 기준으로 판정한다.
