# BlenderAssetGenerator V0.9.0

레퍼런스 이미지, 직교 도면, 치수와 사용자 피드백을 재현 가능한 Blender 정적 자산으로 변환하는 Codex 작업 저장소입니다. V0.9는 V0.8까지의 분석·형상·재질·Visual QA·portable package·workflow를 보존하면서 환경 증거, 읽기 전용 workspace audit, single-worker queue와 Codex Destination Handoff를 추가합니다.

> 설계 원본은 `.blend`가 아니라 `workspaces/<job>/` 아래의 immutable 입력과 versioned JSON 계약입니다. `.blend`, 렌더, PDF, 최적화 장면과 export package는 검증 가능한 파생 산출물입니다.

## 현재 상태

| 항목 | 현재 계약 또는 상태 |
|---|---|
| 프로젝트 | `0.9.0` |
| Geometry SceneSpec | `0.2.0` |
| Reference / Constraint | `0.4.0` |
| Optional InteriorScope | `0.1.0` |
| Material / Shader | `0.5.0` |
| Visual QA | `0.6.0` |
| Portable static asset | `0.7.0` |
| Workflow orchestration | `0.8.0` |
| Stabilization evidence | `0.9.0` |
| Codex Destination Handoff | `0.9.0` |
| 실제 검증 환경 | Windows, Python 3.14.6, Blender 5.0.1 |
| 최신 Python 회귀 | 411 tests passed, Ruff passed |

Blender 4.x용 feature-probe fallback은 유지하지만 현재 통합 저장소의 실제 Blender 실행 기준선은 5.0.1입니다. macOS, Linux, 다른 Python/Blender 조합은 실제 V0.9 gate가 수행되기 전까지 `unverified`입니다.

## 구현 범위

- 결정론적 reference diagnostics와 카메라 가정
- concept 및 measured 작업, auxiliary view와 constraint residual
- primitive, custom mesh, profile extrusion, revolve, curve와 terrain
- optional interior의 exact-hash scope 승인과 fail-closed 검증
- MaterialPlan, whitelisted Blender shader recipe, texture manifest와 bake contract
- 정확히 7개 고정 카메라 패스를 사용하는 Visual QA
- 승인된 InteriorScope를 위한 별도 다각도 실내 QA, semantic visibility와 contact sheet
- semantic ID 기반 revision candidate와 single-use 승인·rollback
- exact plan SHA-256을 한 번 승인해 기본 3회·최대 5회의 국소 수정을 제한적으로 반복하는 선택적 standard Visual QA convergence, iteration receipt, terminal JSON/PDF와 V0.9 audit
- engine-neutral GLB, FBX, OBJ 정적 자산 preflight·최적화·package·clean-import round trip
- 짧은 요청의 deterministic intent routing, 상태 재구성, 잠금, 재개, 취소와 승인 대기
- 명시적으로 선택하는 배경 외관용 `background_exterior` 빠른 실행 정책과 `preview_only`/`portable_package` 종료 범위
- privacy-safe 환경 probe와 bounded read-only workspace audit
- 기존 V0.8 workflow만 처리하는 single-worker local queue와 immutable attempt receipt
- exact environment/audit JSON hash에 묶인 V0.9 stability PDF와 sidecar
- passed clean-import package에만 생성되는 hash-bound Codex Destination Handoff
- semantic hierarchy, transform, material/PBR, LOD/Collider와 목적지 import 계약
- 목적지 프로젝트를 수정하기 전에 `import_plan.json`과 사용자 승인을 요구하는 안전 프롬프트
- authoritative JSON을 기반으로 한 build, material, QA, export, full PDF 보고서

현재 구현하지 않았거나 지원을 주장하지 않는 범위:

- Unity prefab, Unreal actor 또는 특정 엔진 API를 직접 호출하는 자동 Destination Adapter
- rig, skinning, animation과 캐릭터용 topology
- 모든 CAD 형식의 실제 parsing과 B-Rep 변환
- 단일 이미지에서 보이지 않는 후면·내부·절대 치수의 정답 복원
- multi-worker 또는 distributed scheduler와 완성된 cross-platform release matrix

자동 Destination Adapter는 목적 엔진·버전·렌더 파이프라인이 확정된 뒤 V1.1 이후 범위입니다. 현재는 V0.7 package 뒤에 선택적으로 Codex Destination Handoff를 생성하고, 목적지 프로젝트의 Codex가 먼저 import plan을 작성하도록 전달합니다.

## 핵심 저장소 구조

```text
BlenderAssetGenerator/
├─ AGENTS.md                         프로젝트 불변 규칙
├─ .codex/                           프로젝트 MCP 설정
├─ .agents/skills/                   명시적으로 요청할 때만 사용하는 작업 스킬
├─ schemas/                          versioned JSON Schema
├─ prompts/                          agent 저작 단계용 프롬프트
├─ src/codex_blender_modeler/
│  ├─ analysis/                      V0.4 reference diagnostics
│  ├─ constraints/                   measured residual 평가
│  ├─ materials/, texturing/, baking/
│  ├─ qa/                            V0.6 외관 비교와 후보 생성
│  ├─ auto_revision/                 V0.6 one-shot revision과 bounded convergence
│  ├─ interior_qa/                   V0.6 실내 다각도 구조 검사
│  ├─ optimization/, packaging/      V0.7 derived portable asset
│  ├─ orchestration/                 V0.8 workflow state machine
│  ├─ handoff/                       V0.9 hash-bound destination handoff
│  ├─ stabilization/                 V0.9 probe, audit, queue, PDF
│  └─ blender_scripts/               whitelisted Blender background scripts
├─ examples/                         geometry_showcase, measured_box 등
├─ tests/                            계약·음성·회귀 테스트
├─ reports/                          격리 gate, V0.9 probe와 audit 증거
├─ output/pdf/v09/                   exact-hash stability PDF
└─ workspaces/<job>/                 자산별 canonical 및 derived 상태
```

## 설치와 환경 확인

`.env`에서 `BLENDER_BIN`을 실제 Blender 실행 파일로 지정합니다.

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm blender-compat
uv run cbm workflow-adapters
```

`workflow-adapters`의 검증된 기본 목적지는 `engine_neutral`입니다. Unity 또는 Unreal이 표시되더라도 실제 adapter 검증 전에는 지원된 것으로 취급하지 않습니다.

## V0.8 짧은 요청 workflow

새 자산은 고유한 소문자 `job_id`와 primary reference로 시작합니다.

기본 `standard` 정책은 기존 승인 경계를 그대로 유지합니다. 실내·실측·리깅이 필요 없는 단순 배경 외관은 작업 계획 전에 `background_exterior`를 명시적으로 선택할 수 있습니다. 사용자는 PowerShell을 실행할 필요 없이 Codex에 다음처럼 요청하면 됩니다.

레퍼런스에서 무엇을 만들지는 실행 정책과 별도의
`reference_content_scope`로 선택합니다.

- `full_reference`(기본값): 주 피사체와 관련 주변 환경을 함께 모델링합니다.
- `primary_object_only`: 명시한 `target_subject`와 그 대상에 구조적으로 붙거나
  기능상 필요한 부품만 모델링합니다. 독립 지형, 바닥, 바위, 식생, 소품,
  배경판과 대기 효과는 제외합니다.

이 선택은 새 job을 계획하기 전에 확정하며 job 생성 후에는 변경할 수 없습니다.
같은 이미지라도 전체 장면 버전과 오브젝트 전용 버전은 서로 다른 job으로
만들어야 합니다. `primary_object_only`에서는 modeling plan과 SceneSpec 역할을
검증하고, V0.6도 전체 전경이 아니라 관찰된 주 피사체 영역으로 마스크를
제한합니다.

```text
새 레퍼런스 <REFERENCE_PATH>로 <JOB_ID> 작업을 시작해.
reference_content_scope=primary_object_only,
target_subject="이미지 중앙의 자동차"로 계획해.
자동차 본체와 구조적으로 연결된 바퀴·문·범퍼만 포함하고,
독립된 지형·바닥·바위·식생·잔해·배경은 모델링하지 마.
```

```text
새 레퍼런스 <REFERENCE_PATH>로 <JOB_ID> 작업을 시작해.
V0.8 plan_short_workflow를 execution_policy=background_exterior,
delivery_scope=preview_only로 계획하고 MCP 도구로 진행해.
실내, 치수 추정, 외부 이미지 provider, 생성 타깃, 자동 수정은 사용하지 마.
최대 2회의 bounded pre-QA fit 뒤 한 번의 canonical 직접 Visual QA와
machine quality JSON, QA PDF, 통합 PDF까지 완료해.
status=completed, milestone=delivered_for_review와
quality_status=passed|needs_revision|unscorable를 따로 보고해.
시각적 high finding은 needs_revision으로 전달하고, 실제 scope·안전 조건을
벗어날 때만 requires_standard_workflow로 멈춰.
```

`portable_package`를 선택하면 같은 빠른 제작 단계 뒤 V0.7로 이어지지만, LOD·Collider·cleanup 설정이 들어 있는 정확한 optimization plan SHA-256 승인은 생략하지 않습니다.

```text
새 레퍼런스 <REFERENCE_PATH>로 <JOB_ID> 배경 외관 자산을 만들어
engine-neutral FBX package까지 준비해.
execution_policy=background_exterior, delivery_scope=portable_package,
profile_id=fbx_interchange로 V0.8 workflow를 계획하고 MCP로 진행해.
V0.7 review_plan의 정확한 SHA-256 승인이 필요해지면 반드시 멈춰서 보고해.
```

```powershell
uv run cbm workflow-plan `
  --request "이 이미지로 수정 가능한 정적 3D 프록시를 만들어줘" `
  --job-id temple_asset `
  --reference-path E:\References\temple.png
```

출력된 workflow ID로 상태를 확인하고 결정론적 host 단계를 진행합니다.

```powershell
uv run cbm workflow-status temple_asset
uv run cbm workflow-resume temple_asset <workflow-id>
```

Agent가 작성해야 하는 modeling plan, SceneSpec, material plan 또는 revision plan에서는 workflow가 정상적으로 멈춥니다. 해당 산출물을 작성·검증한 뒤 현재 fingerprint와 함께 completion marker를 남겨야 다음 단계가 열립니다. `standard`는 프록시·재질 swatch·QA·package의 일반 승인을 유지합니다. `background_exterior`는 계획에서 그 일반 gate만 생략하며, agent completion과 V0.6 revision·V0.7 optimization 같은 전용 exact-hash 승인은 그대로 유지합니다.

새 workflow의 V0.5 재질 단계는 scaffold와 authored candidate를
`workflows/<workflow-id>/artifacts/m/` 아래에서 서로 다른 불변 산출물로
관리합니다. 검증된 host promotion만 canonical
`analysis/material_plan.json`을 교체하고 promotion receipt를 남깁니다.
`.blend`, preview, inventory, validation, QA latest pointer와 PDF처럼 정상적인
후속 단계가 갱신할 수 있는 결과는 실행 시점 hash가 workflow snapshot/receipt에
보존됩니다. 따라서 예상된 downstream supersession은 과거 completion을 stale로
만들지 않지만, 계획되지 않은 SceneSpec·MaterialPlan·source 변경은 계속
fail-closed입니다.

새 fast workflow는 material 전에 최대 두 번의 workflow-owned 저해상도 fit
diagnostic을 수행합니다. 이 단계는 primary 역할의 화면 점유율·bbox·실루엣을
근거로 제한된 카메라 후보만 비교하고, 개선된 후보만 strict validation 뒤
canonical SceneSpec으로 한 번 승격합니다. semantic/material ID, custom-mesh
vertex, 실내와 외부 provider는 건드리지 않으며 canonical V0.6 QA run 수에도
포함되지 않습니다.

이 pre-QA fit은 아래의 optional standard convergence와 다른 기능입니다.
`background_exterior` 안에서는 canonical 직접 QA를 정확히 한 번만 실행하고
post-QA 후보를 자동 적용하지 않습니다. 반복적인 QA↔revision이 필요하면
review delivery 뒤 별도의 `standard` 작업에서 사용자가 수렴 계획을 검토해야
합니다.

실행 완료와 품질 합격은 분리됩니다. QA evidence와 보고서 생성이 정상이면
high visual finding이 있어도 preview는 `completed` / `delivered_for_review`로
끝날 수 있습니다. 별도 `quality_status`는 `passed`, `needs_revision`,
`unscorable` 중 하나이고, non-passing 결과는 standard revision을 권장하되
품질 합격으로 표시하지 않습니다. primary, supporting, decorative,
ground/background 역할을 구분하며 ground/background는 primary silhouette에서
제외됩니다.

차단 원인도 구분됩니다. 실내·실측/constraint·rig·animation·gameplay·
engine-specific 요구 같은 실제 범위·안전 위험은 `requires_standard_workflow`,
예상하지 않은 소유권 또는 fingerprint 충돌은
`orchestration_artifact_conflict`, Blender 예외와 timeout은 일반 host
failure입니다. 이전에 차단된 workflow는 자동 복구되지 않으며 이 계약은 새로
계획한 workflow부터 적용됩니다.

기존 job은 reference hash가 같아도 `new_asset`으로 다시 시작할 수 없습니다.

```powershell
uv run cbm workflow-plan `
  --request "중앙 탑 높이만 10% 높여줘" `
  --job-id temple_asset `
  --intent revise_asset
```

완전한 사용 예와 승인·재개 명령은 [V0.8 빠른 시작](GETTING_STARTED_V08_KO.md)을 따릅니다.

Portable workflow 뒤에 전달 계약까지 포함하려면 GLB 또는 FBX profile에서 선택 플래그를 사용합니다. 이 단계는 목적지 프로젝트를 수정하지 않습니다.

```powershell
uv run cbm workflow-plan `
  --request "승인된 정적 자산을 portable package와 Codex handoff로 준비해줘" `
  --job-id temple_asset `
  --intent portable_package `
  --profile portable_gltf `
  --include-destination-handoff
```

## 선택적 standard V0.6 수렴 세션

기본 `standard` 경로는 계속 후보별 exact 승인과 1회 적용입니다. 이미 큰 형상과
비교 카메라가 승인됐고 같은 종류의 국소 수정 승인이 반복될 때만 bounded
convergence를 선택할 수 있습니다. 사용자는 current direct QA run에서 생성된
계획의 목표 direct score·silhouette IoU, 허용 semantic ID, path/operation/delta
한계, minimum gain, candidate confidence와 iteration budget을 확인하고 exact plan
SHA-256을 한 번 승인합니다. 기본 상한은 3회이고 하드 상한은 5회입니다.
신규 plan은 non-empty exact input hash map, initial candidates, build
fingerprint/provenance, strict host-safety-envelope SHA-256과 optional constraint
snapshot에도 정확히 결속됩니다. 이 binding이 없는 legacy partial plan은
historical status/audit 전용이며 승인·실행하지 않고 current direct QA에서 새
plan을 작성합니다.

PowerShell을 직접 실행할 필요는 없습니다. Codex에 다음처럼 요청하면
`plan_visual_convergence` MCP 도구로 계획만 만들고 exact hash 승인에서
멈춥니다.

```text
<JOB_ID>의 current direct QA run <QA_RUN_ID>을 기준으로
standard bounded Visual QA convergence 계획만 작성해.
목표 direct score와 silhouette IoU, 허용 semantic ID, path/delta 규칙,
minimum gain, confidence와 모든 iteration budget을 보고해.
strict host-safety-envelope 경로/SHA-256과 non-empty exact input map 상태도 보고해.
canonical SceneSpec은 아직 수정하지 말고 exact plan SHA-256 승인에서 멈춰.
```

승인 뒤에는 Codex가 `approve_visual_convergence`와
`run_visual_convergence`를 사용합니다. 각 iteration은 direct score가 승인된
최소량 이상 개선되고 silhouette IoU와 measured constraint가 비회귀일 때만
accept됩니다. 아니면 baseline을 복구하고 plateau·constraint regression·manual
review 등의 정확한 이유로 종료합니다. generated-target-only 후보, 카메라,
재질, custom-mesh geometry와 계획 밖 ID/경로는 자동 권한 밖입니다.
CLI의 repeatable `--path-limit-json`과 MCP의 `path_limits`는 host 기본 규칙보다
좁은 path/operation/delta만 요청할 수 있으며 자동 권한을 넓히지 못합니다.
한 번의 host/MCP 실행은 전체 Blender 반복을 최대 한 번만 처리하고, active
세션은 같은 exact approval과 immutable receipt chain을 검증한 뒤 다음 호출에서
이어갑니다. 중단된 작업은 staging evidence를 보존한 채 먼저 baseline
복구를 수행하며 completed iteration을 덮어쓰지 않습니다.
상태 응답의 `execution_eligible`, `status_only_legacy`,
`execution_block_reason`, `execution_binding_gaps`와 `next_action`을 따라
승인·계속·복구·종료합니다. Receipt-less staging이 있으면 취소나
terminalization보다 `run_visual_convergence` 1회 복구가 먼저이며,
terminal evidence와 receipt-less staging이 함께 있으면 integrity failure입니다.

이 exact plan 승인은 해당 세션의 per-iteration 후보 승인만 대체합니다.
InteriorScope, V0.7 optimization, Destination Handoff 또는 package 승인을
대체하지 않으며, 목표에 도달하지 못해도 iteration budget을 자동으로 늘리지
않습니다. 완료 시 authoritative `convergence_report.json`, iteration hash chain,
사용자용 PDF와 sidecar가 `qa/convergence/<session-id>/` 아래에 남습니다.

## V0.9 안정화 표면

```powershell
uv run cbm stability-probe --probe-id probe-local-001
uv run cbm workspace-audit --audit-id audit-local-001
uv run cbm stability-report-pdf `
  --probe-id probe-local-001 `
  --audit-id audit-local-001 `
  --report-id stability-local-001
```

Audit는 canonical job을 repair하거나 migration하지 않습니다. Queue는 이미 계획된 V0.8 workflow만 한 번에 하나씩 진행하고 agent 또는 승인 경계에서 멈춥니다. 전체 사용법은 [V0.9 빠른 시작](GETTING_STARTED_V09_KO.md)을 따릅니다.

Passed round-trip package에 대해 전달 봉투를 만들려면 먼저 계획을 생성하고 그 정확한 SHA-256을 확인합니다.

```powershell
uv run cbm handoff-plan <job-id> `
  --profile portable_gltf `
  --package-id <package-id> `
  --handoff-id <handoff-id>

uv run cbm handoff-generate <job-id> `
  --handoff-id <handoff-id> `
  --plan-sha256 <exact-plan-sha256>

uv run cbm handoff-validate <job-id> `
  --profile portable_gltf `
  --package-id <package-id> `
  --handoff-id <handoff-id>

uv run cbm handoff-status <job-id>
```

원본 V0.7 package는 immutable이므로 handoff 파일을 그 안에 덧붙이지 않습니다. 대신 package를 byte-for-byte 복제한 독립 전달 봉투를 `exports/destination_handoffs/<profile>/<package-id>/<handoff-id>/`에 생성합니다.

## 단계별 제작 흐름

```text
immutable input
→ V0.4 reference/camera analysis and geometry
→ optional measured constraints / interior scope
→ V0.5 material, texture and shader
→ V0.6 fixed-camera QA and guarded revision
→ optional V0.6 approved multi-view interior QA
→ V0.7 derived optimization and portable package
→ V0.8 orchestration, resume and approval boundaries
→ optional V0.9 Codex Destination Handoff
→ V0.9 stabilization evidence and local gates
```

작업 단계는 일방통행이 아닙니다. 형상이 마음에 들지 않으면 현재 저장소를 유지한 채 V0.4 authoring으로 돌아가고, 국소적인 레퍼런스 오차는 V0.6 guarded revision으로 처리합니다. canonical 입력이 바뀌면 이후 build, QA와 package는 stale 상태가 되며 새 run ID로 재검증합니다.

## 작은 표면 디테일: 메시 또는 텍스처

새 작업은 V0.4 ModelingPlan에서 창문 무늬, 이음선, 리벳, 라벨, 얕은 패널과
반복 마크를 geometry와 분리합니다. 실루엣·구조·물리적 투명성·gameplay에 필요한
부분만 geometry로 유지하고, 나머지는 V0.5의 UVMap PBR 채널이나 baked decal로
전달합니다. TextureManifest는 실제로 포함한 exact surface-detail ID를 기록하며,
V0.6은 이 coverage를 geometry 유사도와 별도로 보고합니다.

자세한 계약과 예시는 [표면 디테일 분류 가이드](SURFACE_DETAIL_ROUTING_KO.md)를
참조하세요.

## 안전 원칙

- `workspaces/*/input/`은 수정하지 않습니다.
- 단일 uncalibrated 이미지에서 절대 치수나 보이지 않는 구조를 복원했다고 주장하지 않습니다.
- 모든 모델링 객체와 재질은 stable semantic ID를 유지합니다.
- interior는 기본 비활성화이며 exact scope hash 승인 전에는 생성하지 않습니다.
- 실내 QA도 exact camera-plan hash 승인 뒤에만 실행하며 임시 카메라를 authoring `.blend`에 저장하지 않습니다.
- 실내 semantic visibility는 검토 범위의 가시성이지 완성도나 레퍼런스 유사도 백분율이 아닙니다.
- `.blend`를 canonical 수정 수단으로 사용하지 않습니다.
- 생성 이미지 기반 QA target은 보조 근거이며 단독으로 revision을 승인하지 못합니다.
- standard bounded convergence는 exact plan 승인 안에서만 per-iteration 승인을 줄이며, 계획 밖 수정이나 다른 전문 승인을 허용하지 않습니다.
- V0.7은 canonical authoring 데이터를 수정하지 않고 run-owned derived directory에서만 최적화합니다.
- Handoff 생성은 원본 package와 canonical authoring 데이터를 변경하지 않고 모든 파일을 상대 경로와 SHA-256으로 결속합니다.
- 일반 workflow 승인은 InteriorScope, Visual QA revision 또는 optimization의 전용 승인을 대체하지 못합니다.

전체 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다.

## 테스트

빠른 Python·정적 검사:

```powershell
uv run pytest
uv run ruff check .
uv run cbm doctor
```

현재 통합 gate:

```powershell
.\scripts\run_v09_gates.ps1
```

V0.9 안정화만 진단하고 V0.8 회귀를 별도 실행한 경우에만:

```powershell
.\scripts\run_v09_gates.ps1 -SkipV08
```

실제 검증 결과는 [V0.9 검증 기록](VERIFICATION_V09_KO.md)에 있습니다. 테스트하지 않은 운영체제, Blender 버전, 엔진 또는 adapter는 지원된 것으로 표시하지 않습니다.

## 문서 안내

- [V1.0 공식 로드맵](ROADMAP_V1_KO.md)
- [V0.9 아키텍처](ARCHITECTURE_V09_KO.md)
- [V0.9 빠른 시작](GETTING_STARTED_V09_KO.md)
- [V0.9 테스트 계획](TEST_PLAN_V09_KO.md)
- [V0.9 검증 기록](VERIFICATION_V09_KO.md)
- [V0.8 아키텍처](ARCHITECTURE_V08_KO.md)
- [V0.8 빠른 시작](GETTING_STARTED_V08_KO.md)
- [V0.8 테스트 계획](TEST_PLAN_V08_KO.md)
- [V0.8 검증 기록](VERIFICATION_V08_KO.md)
- [V0.7 portable asset 아키텍처](ARCHITECTURE_V07_KO.md)
- [V0.7.4 최적화 승인 경계](V074_PRE_OPTIMIZATION_REVIEW_KO.md)
- [선택적 실내 범위와 다각도 QA](INTERIOR_SCOPE_KO.md)
- [Blender 5 호환성](BLENDER_5_COMPATIBILITY_KO.md)
- [변경 기록](CHANGELOG.md)

V0.9는 현재 정의된 로컬 범위에서 완료됐지만 cross-platform 또는 목적 엔진 runtime parity를 의미하지 않습니다. V1.0 승격은 현재 중단되어 있으며, 자동 Unity/Unreal/custom Destination Adapter는 V1.1 이후에 목적지가 확정된 다음 별도로 설계·검증합니다.
