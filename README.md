# BlenderAssetGenerator V0.9.0

레퍼런스 이미지, 직교 도면, 치수와 사용자 피드백을 재현 가능한 Blender 정적 자산으로 변환하는 Codex 작업 저장소입니다. V0.9는 V0.8까지의 분석·형상·재질·Visual QA·portable package·workflow를 보존하면서 환경 증거, 읽기 전용 workspace audit, single-worker queue, 명시적 controller 실행 모드를 가진 production dispatch/controller와 Codex Destination Handoff를 추가합니다. Autonomous Quality Extension(AQ) `0.1.0`은 이 프로젝트 `0.9.0` 위에서 새 정적 소품에만 명시적으로 선택하는 병렬 production/controller overlay이며 V1.0 승격이 아닙니다. AQ v2 `0.2.0`은 여기에 더해진 additive experimental overlay이며 profile은 아직 `disabled_experimental`입니다.

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
| External Static Asset Intake | `0.9.0` |
| Asset Production Dispatch / Controller | `0.9.0` |
| Autonomous Quality / Integrated Quality | `0.1.0` opt-in companion |
| Autonomous Quality v2 / Integrated Quality 0.2 | `0.2.0` additive overlay; `disabled_experimental` |
| SceneSpec V03 structural derivative | `0.3.0` opt-in, canonical 기본값은 `0.2.0` |
| 실제 검증 환경 | Windows 11, Python 3.14.6, Blender 5.0.1/Python 3.11.13, EEVEE |
| AQ 구현 전 Python 기준선 | 945 passed, 6 skipped; Ruff passed |
| AQ post-change 최종 회귀 | 1145 passed, 20 skipped, 8 warnings in 149.21s; Ruff passed |
| AQ 통합 gate | exit 0; focused 195 passed, 2 skipped; Blender 14 passed |
| AQ v2 최신 전체 회귀 | 1350 passed, 39 skipped, 8 warnings; profile은 비활성 유지 |
| AQ v2 통합 gate | focused 397 passed, 17 skipped, 8 warnings; Blender 30 passed, 6 warnings; V0.7/V0.8/V0.9 gates passed |

Blender 4.x용 feature-probe fallback은 유지하지만 현재 통합 저장소의 실제 Blender 실행 기준선은 5.0.1입니다. macOS, Linux, 다른 Python/Blender 조합은 실제 V0.9 gate가 수행되기 전까지 `unverified`입니다.

## 구현 범위

- 결정론적 reference diagnostics와 카메라 가정
- concept 및 measured 작업, auxiliary view와 constraint residual
- primitive, custom mesh, profile extrusion, revolve, curve와 terrain
- optional interior의 exact-hash scope 승인과 fail-closed 검증
- MaterialPlan, whitelisted Blender shader recipe, texture manifest와 bake contract
- 정확히 7개 고정 카메라 패스를 사용하는 Visual QA
- canonical 점수를 바꾸지 않는 bounded camera·semantic shape companion과 V0.4 5-view geometry review
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
- 수동 제작 `.blend`/`.fbx`/`.glb`를 exact-hash static source로 등록해 V0.7/V0.9에 연결하는 External Static Asset Intake
- 레퍼런스·사용 목적·content scope·목적지 힌트로 새 V0.8 workflow와 `client_mediated` 또는 명시적 `desktop_in_session` controller bundle을 준비하는 Asset Production Dispatcher
- controller-only canonical write, 최대 3개의 read-only advisory subagent, allowlist-only controller MCP profile과 hash-chained advance receipt
- semantic hierarchy, transform, material/PBR, LOD/Collider와 목적지 import 계약
- 목적지 프로젝트를 수정하기 전에 `import_plan.json`과 사용자 승인을 요구하는 안전 프롬프트
- authoritative JSON을 기반으로 한 build, material, QA, export, full PDF 보고서
- 새 `standard` production dispatch 위에서만 동작하는 bounded
  `autonomous_static_prop_v1`: reference evidence, 격리 후보 탐색, 네 축 Integrated Quality,
  exact policy authorization, portable GLB 또는 non-production review bundle

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
│  ├─ production/                    V0.9 client-mediated dispatch와 single-writer controller
│  ├─ reference_evidence/            AQ mask 후보와 camera hypothesis companion
│  ├─ structural_geometry/           opt-in SceneSpec V03와 derived-only migration
│  ├─ material_graph/                whitelist-only material graph companion
│  ├─ integrated_quality/            AQ 네 축 품질과 hard gates
│  ├─ autonomy/                      AQ profile, budget, authorization와 supervisor
│  ├─ autonomy_benchmarks/           deterministic AQ benchmark runner
│  ├─ handoff/                       V0.9 hash-bound destination handoff
│  ├─ external_intake/               V0.9 external static source contract
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

기본 `standard` 정책은 프록시·재질·패키지와 모든 전문 승인 경계를 유지합니다. 다만 새 `revise_asset` workflow는 `candidate_review`가 기본이어서 RevisionPlan 사전 승인을 생략하고, 격리된 후보를 build·QA한 뒤 canonical 승격 직전에 한 번만 exact decision SHA-256 승인을 받습니다. 실내·실측·리깅이 필요 없는 단순 배경 외관은 작업 계획 전에 `background_exterior`를 명시적으로 선택할 수 있습니다. 사용자는 PowerShell을 실행할 필요 없이 Codex에 다음처럼 요청하면 됩니다.

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

## 3차원 조립 일관성

새로 저작되는 ModelingPlan은 비교 카메라의 2D 투영만 맞추지 않고
`assembly_consistency_policy=spatial_v1` 계약을 사용합니다. 자산 고유의 길이축,
좌우축, 수직축을 선언하고 각 부품을 `root`, `attached`, `free_standing`으로
분류한 뒤 필요에 따라 중심면, 동축, 포함, 접촉, 양측 대칭 관계를 기록합니다.

따라서 단일 사선 이미지에서 트리거나 레버처럼 기능상 중심에 있어야 할 부품이
화면상 한쪽에 보인다는 이유만으로 숨은 좌우축까지 옆면으로 복사되지 않습니다.
명시적인 정면·측면·평면도, 청사진, 치수 또는 사용자 지시가 있을 때만
`side_specific` 관계를 사용합니다. Blender `inspect`와 `validate`는 실제 평가된
geometry bounds를 자산 로컬 meter frame에서 검사하며, 위반 시 V0.5 재질 단계로
넘어가기 전에 V0.4 형상 저작으로 되돌립니다.

이 검사는 정적 3D 배치의 타당성 근거입니다. 실제 작동 간극, 운동학, 제조 가능성,
내부 기구 또는 단일 이미지에서 보이지 않는 면의 진실성을 증명하지는 않습니다.
기존 `legacy_unbound` ModelingPlan은 계속 읽을 수 있지만 공간 검증 완료로
간주하지 않습니다.

## V0.4 다각도 형상 검토

새로 계획되는 V0.8 프록시·상세·배경 형상 workflow와 `spatial_v1` 형상 수정
workflow는 `build → render → inspect → validate` 뒤에 V0.4 다각도 형상 검토를
추가합니다. host 단계는 ModelingPlan의 자산 로컬 축에서 임시 `front`, `right`,
`top`, `rear`, `oblique` 카메라를 만들고, 각 시점마다 `beauty`, `silhouette`,
`object_id`, `wireframe`의 정확히 4개 패스, 총 20개 이미지를 렌더합니다. 임시
카메라는 authoring `.blend`에 저장되지 않으며 canonical V0.6 비교 카메라도
바꾸지 않습니다.

대상은 모든 `primary`/`supporting` 객체와 모든 `root`/`attached` 객체의 합집합입니다.
따라서 primary 또는 supporting인 `free_standing` 부품도 빠지지 않습니다. 한 시점에서
가려진 객체는 다른 시점과 함께 보라는 advisory이고, 모든 시점에서 사라졌거나 필수
assembly 관계가 실패한 경우에만 구조적 V0.4 판단 근거가 됩니다.

host가 `plan.json`, `render_manifest.json`, `report.json`을 만들고 나면 별도 agent
단계가 다섯 시점의 `beauty`와 `wireframe`을 실제로 모두 읽어야 합니다. 그 결과는
exact plan·manifest·report SHA-256에 결속된 `visual_review.json`이며, 시점 간 형상
일관성, 비율, 방향, 조립, 명백한 topology artifact를 기록합니다. 보정된 각도별
레퍼런스가 없으므로 측면·후면 유사도는 계속 `unscorable`입니다. 결과는 bounded
parametric V0.4 수정이나 수동 재설계 검토를 권고할 수 있지만 수정 승인이나 적용
권한은 만들지 않습니다.

새로 저작된 `spatial_v1` 자산의 수동 1회 guarded revision과 bounded convergence는
적용 전후에 같은 다섯 시점 구조 evidence를 다시 만듭니다. bounded session은 initial
five-view terminal을 계획·승인에 결속하고, 각 iteration receipt와 V0.9 audit에 새
result terminal 및 구조 비교 hash를 기록합니다. 구조 상태, 필수 관계, 전 시점
가시성 또는 agent geometry review가 나빠지면 그 iteration을 rollback합니다.
legacy/non-spatial 경로는 이 guard를 `not_applicable`로 유지합니다. 기존 job과 이미
계획된 workflow는 자동 migration하지 않으며 evidence가 없으면 보고서에서 omit,
`not_applicable` 또는 unavailable로 표시합니다. PDF는
다각도 이미지를 포함하는 검토 보조물이고 machine-readable JSON과 그 hash가 권위
있는 기록입니다.

## V0.6 카메라·형상·조립 보조 진단

새로 계획되는 V0.8 QA workflow는 canonical `qa.run` 뒤에 run-owned
`qa.diagnostics` 단계를 추가합니다. 이 단계는 기존 `overall_direct_score`를
재계산하지 않고, canonical 외관 QA의 beauty, silhouette, object ID, material ID,
normal, depth, wireframe 정확히 7개 패스 계약도 바꾸지 않습니다. 과거 workflow와
companion evidence가 없는 legacy job은 계속 읽을 수 있으며 PDF에는 unavailable로
표시됩니다.

### 명시적 semantic reference mask 등록

객체별 contour·PCA 지표를 사용하려면 새 evidence를 canonical manifest에 직접 쓰지
않고 registration-owned candidate로 작성한 뒤 exact SHA-256으로 승격합니다.

```text
analysis/masks/
├─ registrations/<registration-id>/
│  ├─ manifest.json
│  ├─ masks/<semantic-id>.png
│  └─ promotion_receipt.json
└─ semantic_manifest.json

history/qa_semantic_masks/<previous-manifest-sha256>.json
```

candidate는 현재 primary reference와 SceneSpec의 exact hash, observed semantic ID,
같은 크기의 비어 있지 않은 binary PNG를 검증해야 합니다. 승격은 candidate JSON bytes를
그대로 보존하고, 기존 canonical manifest가 있으면 전용 history에 보관합니다.

```powershell
uv run cbm qa-semantic-masks-register <job-id> `
  --registration-id <registration-id> `
  --manifest-sha256 <exact-candidate-manifest-sha256>
uv run cbm qa-semantic-masks-status <job-id>
```

동등한 allowlisted MCP 도구는 `register_semantic_reference_masks`와
`get_semantic_reference_mask_status`입니다. 상태는 `current`, `legacy_current`,
`absent`, `stale`, `invalid` 중 하나입니다. `absent`인 full-reference 작업만 bbox-only
degraded fallback을 허용합니다. 유효한 receipt가 없는 과거 manifest는 읽기 호환을
위해 `legacy_current`로 표시되고, 존재하지만 stale/invalid인 manifest는 fail-closed
처리합니다. `primary_object_only`의 canonical request mask가 없거나 stale이면 fallback
점수를 만들지 않습니다. 등록은 QA evidence publication일 뿐 어떤 수정·최적화 승인도
아닙니다.

```text
qa/runs/<qa-run-id>/diagnostics/camera-geometry-v1/
├─ bundle_manifest.json                 # 성공한 exact attempt를 가리키는 terminal bundle
└─ attempts/
   ├─ attempt-001/                      # 실패해도 덮어쓰지 않는 immutable evidence
   │  ├─ request.json
   │  ├─ report.json
   │  ├─ role_map.json
   │  ├─ camera_probes/
   │  │  ├─ plan.json
   │  │  ├─ render_manifest.json
   │  │  └─ renders/
   │  └─ semantic_masks/
   │     ├─ source_manifest.json
   │     ├─ source/                    # exact registered mask byte snapshots
   │     └─ rendered/
   └─ attempt-002/                      # 명시적 재시도 때만 생성
```

성공한 bundle이 있으면 같은 diagnostic ID를 다시 실행하지 않습니다. Blender 실패나
동시 source 변경처럼 terminal bundle 전에 중단되면 기존 attempt를 보존한 채 같은
명령의 명시적 재시도가 다음 `attempt-NNN`을 만들 수 있습니다. 성공한 한 attempt의
exact path/hash만 root `bundle_manifest.json`에 결속됩니다.
diagnostic attempt는 당시 canonical semantic manifest와 mask bytes를 run-owned snapshot으로
복사합니다. 이후 정상적인 새 mask 승격은 완료된 attempt를 stale로 만들지 않지만,
attempt-owned snapshot 변경은 terminal bundle 검증을 실패시킵니다.

bounded camera probe는 작은 yaw, pitch, framing, distance, target 변화가 오차를
설명하는지 확인하는 advisory evidence입니다. `primary_object_only`에서는 exact
canonical VisualQARequest subject mask만 사용하고, 그 외에는 명시적
primary/supporting semantic mask가 있을 때만 union을 만듭니다. 두 근거가 없으면
기존 observed semantic bbox 비교로 되돌아가며 bbox에서 silhouette mask를 만들지
않습니다. exact primary silhouette IoU 개선은 bbox가 거의 같아도 각도 차이의
근거가 될 수 있지만 카메라를 변경할 권한은 만들지 않습니다.
기본 `--max-camera-probes 12`는 중립 baseline과 별개인 12개 delta를 뜻하므로 총 13개
probe record가 생성됩니다. delta는 yaw ±7.5°, pitch ±5°, projection scale 0.9/1.1,
distance scale 0.9/1.1, target X/Y offset ±0.05입니다.

완료된 canonical QA run에 이 보조 진단을 실행하는 공개 CLI/MCP는 다음과 같습니다.

```powershell
uv run cbm qa-diagnose <job-id> `
  --qa-run-id <qa-run-id> `
  --diagnostic-id camera-geometry-v1 `
  --max-camera-probes 12 `
  --assembly-multiview `
  --render-engine eevee `
  --render-device auto
```

allowlisted MCP 도구는 `run_visual_diagnostics`입니다. 결과의 attribution은
`camera`, `geometry`, `assembly`, `mixed`, `ambiguous`, `unscorable` 중 하나인 보조
분류일 뿐 canonical V0.6 점수, 정확히 7개인 pass manifest, 카메라, SceneSpec 또는
revision 승인 상태를 바꾸지 않습니다.

명시적 semantic mask 쌍이 있을 때만 객체별 mask IoU, normalized centroid error,
area ratio, boundary F-score, symmetric contour distance와 PCA undirected axis error를
계산합니다. PCA axis는 180도 방향을 구분하지 못하므로 실제 facing은 ModelingPlan의
signed longitudinal/lateral/vertical frame과 directed `axis_alignment`로 검증합니다.
`axis_clearance`는 방향이 명시된 축 간격과 횡방향 overlap을 검사하며 facing 판정이
아닙니다. `required_assembly_checks`는 관계 ID가 아니라
`position|axis|orientation|clearance` 검사 카테고리 목록이며, 실제 관계의 stable ID는
`assembly_relationships`에 별도로 보존됩니다. 마스크가 없으면 이 객체별 지표는
degraded/unscorable이며 bbox 정밀도로 대체하지 않습니다.

같은 5-view host 진단을 workflow 밖에서 별도로 실행할 때는 다음 공개 표면을
사용할 수 있습니다.

```powershell
uv run cbm qa-assembly-sanity-plan <job-id> --run-id <run-id>
uv run cbm qa-assembly-sanity-run <job-id> `
  --run-id <run-id> `
  --plan-sha256 <exact-plan-sha256>
```

같은 역할의 allowlisted MCP 도구는 `plan_assembly_multiview_sanity`와
`run_assembly_multiview_sanity`입니다. `front`, `right`, `top`, `rear`, `oblique`
각각은 정확히 4개 구조 패스를 만들고 signed assembly-axis, projection,
depth-order와 required relationship을 확인하지만 레퍼런스 유사도는 항상
`unscorable`입니다. 실제 시각 판정이 필요하면 렌더 생성에서 멈추지 말고 다섯
시점의 beauty/wireframe을 읽은 agent `visual_review.json`도 작성·검증해야 합니다.
camera probe와 5-view 결과 모두 기존 V0.6 revision, convergence, InteriorScope,
V0.7 optimization 또는 Destination Handoff 승인을 대신하지 않습니다.

`qa-assembly-sanity-run`의 plan hash는 실행할 immutable 구조 계획을 exact하게
결속하는 값입니다. 보정된 정면·측면·평면·후면 reference가 없는 한 five-view를
reference match로 해석하거나 유사도 점수를 만들지 않습니다.

```text
<JOB_ID>의 current authored spatial_v1 형상을 V0.4 다각도 검토해.
asset-local front/right/top/rear/oblique 임시 카메라에서 시점별 4개 구조 패스를
만들고, 모든 primary/supporting 및 root/attached ID가 대상인지 확인해.
렌더 생성만으로 검토 완료라고 하지 말고 다섯 beauty/wireframe을 실제로 읽어
exact plan·manifest·report hash에 결속된 visual_review.json을 작성해.
시점 간 형상·비율·방향·조립·topology 문제와 V0.4 수정 또는 재설계 검토 권고를
보고하되, 보정되지 않은 측면·후면 유사도를 채점하거나 수정을 자동 승인·적용하지 마.
JSON 경로와 hash, 이미지가 포함된 PDF 경로를 함께 보고해.
```

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

`portable_package`를 선택하면 같은 빠른 제작 단계 뒤 V0.7로 이어지지만, LOD·Collider·cleanup 설정이 들어 있는 정확한 optimization plan SHA-256 승인은 생략하지 않습니다. V0.7 review는 `approve / revise_asset / revise_profile / cancel`을 제시합니다. `needs_revision`이면 외형·실루엣 수정을 위한 `revise_asset`을 권고하고, LOD·Collider·consolidation·UV·texture·budget 변경은 `revise_profile`로 분리합니다. 두 수정 선택 모두 자동 전환이나 승인이 아니며 새 run과 review가 필요합니다.

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

Agent가 작성해야 하는 modeling plan, SceneSpec, material plan 또는 revision plan에서는 workflow가 정상적으로 멈춥니다. 해당 산출물을 작성·검증한 뒤 현재 fingerprint와 함께 completion marker를 남겨야 다음 단계가 열립니다. `standard`는 프록시·재질 swatch·QA·package의 일반 승인을 유지합니다. 새 standard `revise_asset`만 기본 `candidate_review`에서 RevisionPlan 사전 사용자 승인을 생략하고 격리 평가 뒤 승격 승인 하나를 사용합니다. `background_exterior`는 계획에서 일반 gate만 생략하며, agent completion과 V0.7 optimization 같은 전용 exact-hash 승인은 그대로 유지합니다.

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

위 요청은 기본적으로 다음 순서로 진행됩니다.

```text
workflow-owned RevisionPlan 작성
→ baseline/candidate 격리 build·inspect·validate
→ 같은 카메라의 exact 7-pass direct QA
→ optional constraint와 spatial_v1 five-view 비회귀 검사
→ before/after PDF와 decision_manifest.json
→ exact decision SHA-256 승인 대기
→ 승인된 candidate만 canonical로 1회 승격·재빌드
```

카메라 변경, semantic 추가·삭제, custom-mesh vertex 편집, 재질 변경 또는 큰 재설계는 이 경로에서 거부됩니다. 그 경우 `--revision-strategy manual_guarded`를 명시하거나 V0.4 authoring으로 돌아갑니다. 이미 생성된 legacy workflow에는 새 기본값을 소급 적용하지 않습니다.

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

기본 `standard` `revise_asset` 경로는 후보를 먼저 격리 평가하고 canonical 승격 직전에
exact decision SHA-256을 한 번 승인하는 `candidate_review`입니다. 명시적
`manual_guarded`는 기존 후보별 사전 승인과 1회 적용을 유지합니다. 이미 큰 형상과
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

현재 ModelingPlan이 authored `spatial_v1`이면 계획 시 fresh initial five-view terminal을
만들고, 각 실행에서 result terminal을 새로 만들어 non-regression을 확인합니다.
five-view evidence를 만들거나 검증할 수 없으면 fail-closed되며 manual one-shot 또는
V0.4 authoring 재진입을 안내합니다. legacy/non-spatial 자산은 기존 fixed-camera
bounded convergence 계약을 그대로 사용합니다.

PowerShell을 직접 실행할 필요는 없습니다. Codex에 다음처럼 요청하면
`plan_visual_convergence` MCP 도구로 계획만 만들고 exact hash 승인에서
멈춥니다.

```text
<JOB_ID>의 current direct QA run <QA_RUN_ID>을 기준으로
standard bounded Visual QA convergence 가능 여부를 먼저 확인해.
ModelingPlan이 authored spatial_v1이면 fresh initial five-view terminal을 계획에
결속하고, 각 iteration의 result terminal과 structural comparison을 필수로 해.
그 evidence를 만들 수 없을 때만 manual one-shot guarded revision을 안내해.
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

## External Static Asset Intake

이 저장소 밖에서 직접 만든 `.blend`, `.fbx` 또는 `.glb` 정적 모델도 새 lowercase
job으로 등록할 수 있습니다. 원본은 Blender 5 safe mode에서 읽기 전용 검사하고,
source/dependency SHA-256, meter 변환, semantic/material mapping과 알려진 손실을 담은
immutable plan을 먼저 만듭니다. 사용자가 exact plan hash를 승인한 뒤에만 script와
animation을 제거한 normalized authoring `.blend`를 생성합니다.

이 경로는 가짜 SceneSpec을 만들지 않습니다. Blender master material은 normalized
`.blend`에 보존하고, V0.7에서 실제 graph를 portable raw PBR로 bake한 뒤 package와
clean-import round trip을 수행합니다. 목적 엔진 shader parity는 여전히 검증하지
않습니다. 자세한 절차는 [External Static Asset Intake 가이드](EXTERNAL_STATIC_ASSET_INTAKE_KO.md)를
참조하세요.

## Asset Production Dispatcher와 Delegated Controller

새 레퍼런스의 경로, 사용 목적, 모델링 범위와 선택적 목적지 힌트를 한 번에 주면
`production-dispatch`가 새 V0.8 `new_asset` workflow와 다음 controller launch bundle을
준비합니다.

```text
workspaces/<job-id>/production/dispatches/<dispatch-id>/
├─ dispatch_request.json
├─ controller_plan.json
├─ codex_task_prompt.md
├─ task_launch_manifest.json
├─ dispatch_plan.json
├─ controller_state.json             derived current projection
├─ optional task_binding_receipt.json
├─ optional convergence_binding.json
├─ assignments/
├─ advances/
└─ final postflight_audit_receipt.json
```

실행 모드는 다음 두 가지이며 기본값은 계속 `client_mediated`입니다.

| 모드 | 시작 상태 | 보안 경계 |
|---|---|---|
| `client_mediated` | `prepared / bind_client_task` | supporting client가 exact MCP/shell profile을 강제·attest한 뒤에만 실행 |
| `desktop_in_session` | `ready_in_session`에서 현재 Codex 작업이 바로 controller 역할 | 별도 task binding 없음; `workflow_contract_only`이며 도구 격리를 주장하지 않음 |

`client_mediated`에서는 저장소가 prompt와 manifest를 준비할 뿐 Codex 작업을 직접
만들거나 인증했다고 주장하지 않습니다. Supporting client가 실제 작업을 만들고 exact
controller profile을 강제한 뒤 binding receipt를 생성해야 합니다. 반면
`desktop_in_session`은 사용자가 해당 모드를 명시적으로 선택한 immutable dispatch에서만
활성화되며, 현재 작업이 production MCP를 통해 한 단계씩 진행합니다. 두 모드 모두 기존
generic/specialized exact 승인과 failed-retry 경계를 그대로 유지합니다.

Controller만 canonical 파일을 쓸 수 있습니다. Subagent는 최대 3개의 read-only
advisory 작업만 병렬로 수행하고 write allowlist를 받지 않습니다. Controller는 기존
V0.8 host와 agent 단계를 순차적으로 진행하며 generic review, InteriorScope, V0.6
revision/convergence/candidate decision, V0.7 optimization, Destination Handoff와 failed
retry 경계에서 그대로 멈춥니다. Workflow 완료 뒤에는 exact state에 결속된 V0.9
read-only postflight audit까지 수행합니다.

반복 승인을 줄이는 목적이면 새 dispatch에서 `standard`와
`--convergence bounded_after_v06`를 명시하고 direct score·silhouette IoU 목표를
함께 지정할 수 있습니다. 이 경로의 V0.8 workflow는 V0.6 `preview_only`에서 끝나며,
controller가 exact convergence plan을 만든 뒤 그 SHA-256 승인에서 한 번 멈춥니다.
승인 후 각 `production-advance`는 전체 Blender iteration을 최대 한 번만 실행하거나
복구합니다. target reached, plateau, rollback, manual-only, budget 또는 failure terminal
뒤 V0.9 postflight까지 완료하지만 품질 목표 달성을 보장하지는 않습니다. accepted
convergence가 canonical SceneSpec을 바꿀 수 있으므로 V0.7 package와 Destination
Handoff는 검토 후 새 immutable standard workflow에서 시작합니다.

공개 CLI 표면은 `production-dispatch --ctrl-mode <mode>`, `production-bind-task`, `production-status`,
`production-advance`, `production-complete-step`입니다. 같은 역할의 MCP 도구를 이용하면
일반 사용자가 PowerShell을 직접 실행할 필요는 없습니다. `production-bind-task`는
`client_mediated` 전용입니다. `desktop_in_session`은 별도 API나 supporting-client bridge
없이 현재 Codex Desktop 작업에서 사용할 수 있지만, 저장소 계약만으로 악성
controller의 shell 우회를 막는 모드는 아닙니다.

```text
create_asset_production_dispatch
bind_asset_production_task
get_asset_production_dispatch_status
advance_delegated_production_controller
record_delegated_production_step
```

`client_mediated` controller task의 allowlist에는 상태 조회, advance, exact step
completion의 마지막 세 도구만 들어갑니다. `desktop_in_session`에서도 이 세 도구를
진행 표면으로 사용하지만 allowlist enforcement attestation은 없으며, exact 승인 도구는
사용자의 해당 hash 승인 메시지가 있은 뒤에만 별도 소유 표면으로 호출해야 합니다.

## 선택적 Autonomous Quality 0.1.0

AQ는 기존 `standard`와 `background_exterior` 정책을 바꾸는 새 기본 모드가 아닙니다.
`autonomous_static_prop_v1`을 명시적으로 선택한 새 `concept` +
`primary_object_only` 정적 소품 job에만 새 `standard` workflow/production dispatch 위로
적용됩니다. Interior, measured/blueprint, rig, animation, gameplay, destination-project write,
external provider와 임의 Python/Blender/node graph 실행은 이 profile 밖입니다.

```text
exact initial request + primary reference + target subject
→ RootAuthorization와 immutable profile/budget
→ local Reference Evidence와 최대 3개 initial candidate
→ bounded structural/parametric/material rounds(기본 material round 2회)
→ Integrated Quality(reference/structure/material/production)
   ├─ accepted → V0.7 portable GLB → fresh clean import → quality_passed
   └─ non-pass/unscorable/bounded stop → review-only bundle → review_required
```

`authorization_source=preauthorized_profile`은 사용자 승인 기록이 아니라 exact profile
범위 안의 routine gate를 결정한 policy authorization입니다. InteriorScope, interior-QA
camera plan, destination import plan, reference/scope/target 변경, budget 확대와 임의 실행은
대체하지 못합니다. 기존 workflow의 approval/receipt를 AQ authorization으로 변환하지도
않습니다. 새 authorization도 처음 저장한 직후 다시 읽어 root/profile/budget, exact target,
dependency, predecessor, single-use 상태와 파일 hash identity를 모두 검증한 뒤에만 side
effect를 허용합니다.

품질 통과는 기존 V0.6 direct score 하나로 결정하지 않습니다. direct score의 값과 의미를
보존하면서 reference alignment, structural integrity, material fidelity, production
readiness를 분리하고, unavailable evidence는 `unscorable`로 유지합니다. hard gate를
통과한 후보 중 비회귀·meaningful gain·Pareto·최소 변경 순서로 한 후보만 승격합니다.

V0.7 package 단계의 자동 복구는 일반 retry가 아닙니다. 기본 한 번의 예산 안에서 기존
immutable package ID 충돌 또는 format-only roundtrip 오류만 fresh `-aqrNN` package ID로
다시 만들 수 있습니다. 새 clean-import roundtrip까지 통과해야 받아들이며 material,
bounds, dependency, Blender, canonical/source 오류는 fail-closed입니다.

Windows 장경로 package/handoff 검증은 같은 package-relative 재귀 file set과 digest 규칙을
사용합니다. 따라서 생성 단계의 정상 directory evidence가 V0.9 postflight에서 다른 hash로
오판되지 않으며, 실제 추가·변조 파일은 계속 fail-closed로 탐지됩니다.

품질 미달 review bundle은 best-known `.blend`, preview GLB, representative render, exact IQ
JSON, unresolved findings, history/comparison, manual action과 PDF/sidecar를 제공하지만
`production_ready=false`, `destination_handoff_eligible=false`입니다. production package나
목적지 전달 자산으로 사용하면 안 됩니다.

SceneSpec `0.3.0`은 구조 형상용 별도 opt-in 계약입니다. AQ structural candidate는 선택적으로
full V03 assignment를 받아 모든 structural object를 candidate-owned payload/receipt/`.blend`
증거로 materialize한 뒤, 기존 build 경로가 읽는 path-backed `0.2.0` candidate로 compile할 수
있습니다. canonical 기본 계약은 계속 `0.2.0`입니다. 공개
`scene-spec-v03-migration-plan` / `scene-spec-v03-migration-apply`와 동등 MCP는 exact plan
hash에 결속된 derived copy와 receipt만 만들며 canonical SceneSpec `0.2.0`을 교체하지
않습니다.

일반 사용자는 PowerShell 대신 Codex/MCP로 요청할 수 있습니다. 실제 사용 범위와 종료
결과는 [AQ 시작 가이드](GETTING_STARTED_AUTONOMOUS_QUALITY_KO.md), 계약은
[AQ 아키텍처](ARCHITECTURE_AUTONOMOUS_QUALITY_KO.md)를 따릅니다.

## 실험적 Autonomous Quality 0.2

AQ v2 `autonomous_static_prop_v2`는 AQ 0.1이나 V0.9 계약을 교체하지 않는 additive overlay이며
현재 상태는 **`disabled_experimental`**입니다. 활성 지원을 주장하지 않은 채 다음의 bounded
production chain을 계약·host gate와 선택된 실제 Blender fixture로 검증합니다.

```text
geometry controller candidate → strict canonical geometry promotion
→ material controller candidate → strict canonical material promotion
→ external Integrated Quality 0.2 submission의 raw-mask host 재계산
→ quality_approved source freeze, review_required bundle 또는 blocked terminal
→ review_only 또는 포맷별 exact V0.7 approval
→ 동일 freeze에서 독립 GLB / FBX package + clean import
```

ControllerExecutor는 controller에 canonical job root를 넘기지 않고 execution-owned workspace의
exact input snapshot과 선언된 output만 교환합니다. path escape, symlink, extra output, hash mismatch,
stale/tampered receipt와 incomplete crash adoption은 fail-closed입니다. 공개 CLI/MCP 표면은
`plan`, `status`, 한 단계 `advance`, bounded `run`, `cancel`을 제공하지만 사용자 approval을
합성하거나 범위를 넓히지 않습니다.

`desktop_in_session`이 output을 기다리는 동안에는 `advance`/`run`이 새 요청이나 invocation을
만들지 않고 동일 request-owned workspace만 재검증해 resume합니다. 시작 시 기록한 protected job
inventory가 달라지거나 request/result/profile/state chain이 stale이면 adoption 전에 중단하며,
대기 재호출은 budget을 다시 소비하지 않습니다. 모든 state 전이는 predecessor와 monotonic budget을
재구성할 수 있어야 합니다.

execution-root/adoption recovery는 executor lifecycle과 저장된 result bytes를 끝까지 재구성하고,
직접 side effect는 active·미만료 RootAuthorization과 exact plan/profile/budget binding을 다시
검증합니다. raw executor timeout receipt와 달리 AQ v2 bridge의 timeout은 즉시 nonretryable
`failed` terminal로 끝납니다.

IQ 0.2는 exact global/semantic PNG bytes에서 contour·semantic metric과 gates/findings/outcome을
host가 다시 만들고 caller report 전체와 equality를 검사합니다. source freeze는 현재 canonical
bytes와 필수 `geometry_candidate_validation_receipt`/`material_phase_receipt`에 다시 결속됩니다.
authoritative hard finding이 하나라도 남으면 quality pass가 될 수 없으며, typed raw receipt가 없는
required scored landmark/multi-view는 pass authority가 없습니다. `QualityTerminalV2`는 IQ, freeze
또는 review bundle과 그 nested artifact hash를 끝까지 재검증합니다.

최신 검증은 전체 pytest `1350 passed, 39 skipped, 8 warnings`, AQ focused gate
`397 passed, 17 skipped, 8 warnings`, 실제 Blender 묶음 `30 passed, 6 warnings`와 V0.7/V0.8/V0.9 gate 통과를
기록합니다. 실제 Blender 검증은 선택된 structural/material fixture와 동일 frozen source에서
직접 만든 synthetic GLB+FBX dual-delivery fixture 범위입니다. Codex App Server 또는
supporting-client가 수행하는 완전한 closed loop, 사람의 reference 품질 판정, Unity/Unreal/custom
destination runtime parity는 아직 검증되지 않았으므로 profile은 계속 비활성입니다.

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
→ optional V0.9 client-mediated production controller and read-only advisers
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

새 V0.5 authoring은 `spatial_v1` 계약을 사용합니다. 국소 디테일은 단순히 ID만
나열하지 않고, 부모 semantic ID·전용 material ID·현재 ordered polygon-corner UV
fingerprint·`uv_rect` 또는 hash-bound mask·적용할 image-backed PBR channel에
결속됩니다. 이미지 노드는 `UVMap`과 identity Mapping을 사용하고 clamp/clip으로
반복을 막습니다. hybrid procedural noise는 별도의 좌표 경로를 사용하므로 국소
창문·이음선 픽셀이 전체 표면에 반복되지 않습니다.

`validate-material-fidelity`는 채널 해시와 검은 선, 과도한 전역 변이, 비정상 normal,
공유 재질 누출 위험을 결정론적으로 보고합니다. 이 검사는 UV rectangle이 의미상
정확한 면을 선택했다는 시각적 진실까지 증명하지 않으므로 material swatch와 preview
검토를 대체하지 않습니다. 기존 unbound TextureManifest는 계속 읽을 수 있지만 새
workflow의 spatial 검증을 통과한 것으로 승격되지 않습니다.

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
- standard `candidate_review`는 사전 RevisionPlan 승인을 한 번 줄일 뿐 exact 최종 승격 승인을 유지합니다. bounded convergence는 별도 exact plan 승인 안에서만 per-iteration 승인을 줄이며, 계획 밖 수정이나 다른 전문 승인을 허용하지 않습니다.
- V0.7은 canonical authoring 데이터를 수정하지 않고 run-owned derived directory에서만 최적화합니다.
- Handoff 생성은 원본 package와 canonical authoring 데이터를 변경하지 않고 모든 파일을 상대 경로와 SHA-256으로 결속합니다.
- 일반 workflow 승인은 InteriorScope, Visual QA revision 또는 optimization의 전용 승인을 대체하지 못합니다.
- Production Dispatcher는 `standard`를 기본으로 사용하며 `background_exterior`는 명시적 opt-in입니다. 어느 정책도 exact 전문 승인이나 failed retry 권한을 대신하지 않습니다.
- Production task의 실제 생성·인증과 controller MCP/shell 제한은 supporting client 책임입니다. 저장소는 정확한 allowlist·attestation·receipt를 검증하지만 unenforced shell을 보안 경계로 주장하지 않습니다.
- AQ의 profile authorization은 사용자 승인으로 기록되지 않으며 root/profile/budget/target
  hash에 결속된 single-use 기계 결정입니다. 범위 밖 요청이나 stale/tampered evidence는
  자동 승인하거나 budget을 늘리지 않고 중단합니다.
- AQ의 `quality_passed`는 final IQ, immutable package manifest와 fresh passed roundtrip을
  함께 요구합니다. `review_required` bundle은 production package나 Destination Handoff
  증거가 아닙니다.

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

선택적 AQ gate:

```powershell
.\scripts\run_autonomous_quality_gates.ps1 -RunBlender
```

AQ 구현 전 기준선은 `945 passed, 6 skipped`와 Ruff 통과입니다. 2026-08-10 post-change
전체 결과는 `1145 passed, 20 skipped, 8 warnings in 149.21s`(1165 collected;
portable snapshot `verification/evidence/aq_v1_20260810/`), Ruff `All checks passed`, doctor
OK, Blender 5.0.1 compatibility GLB/FBX/OBJ 통과입니다. AQ gate는 focused
`195 passed, 2 skipped, 8 warnings in 16.98s`, 실제 Blender 묶음
`14 passed, 6 warnings in 352.03s`, benchmark `8/8`과
V0.7~V0.9 chained regression을 포함해 exit 0으로 끝났습니다. 기준선 결과를 AQ 회귀
통과로 재사용하지 않습니다. exact 경로와 hash는
[AQ 검증 기록](VERIFICATION_AUTONOMOUS_QUALITY_KO.md)에 있습니다.

V0.9 안정화만 진단하고 V0.8 회귀를 별도 실행한 경우에만:

```powershell
.\scripts\run_v09_gates.ps1 -SkipV08
```

실제 검증 결과는 [V0.9 검증 기록](VERIFICATION_V09_KO.md)에 있습니다. 테스트하지 않은 운영체제, Blender 버전, 엔진 또는 adapter는 지원된 것으로 표시하지 않습니다.

## 문서 안내

- [V1.0 공식 로드맵](ROADMAP_V1_KO.md)
- [Autonomous Quality 0.1.0 아키텍처](ARCHITECTURE_AUTONOMOUS_QUALITY_KO.md)
- [Autonomous Quality 0.1.0 시작 가이드](GETTING_STARTED_AUTONOMOUS_QUALITY_KO.md)
- [Autonomous Quality 0.1.0 테스트 계획](TEST_PLAN_AUTONOMOUS_QUALITY_KO.md)
- [Autonomous Quality 0.1.0 마이그레이션 정책](MIGRATION_AUTONOMOUS_QUALITY_KO.md)
- [Autonomous Quality 0.1.0 검증 기록](VERIFICATION_AUTONOMOUS_QUALITY_KO.md)
- [Autonomous Quality 0.2 아키텍처](ARCHITECTURE_AQ_V02_KO.md)
- [Autonomous Quality 0.2 시작 가이드](GETTING_STARTED_AQ_V02_KO.md)
- [Autonomous Quality 0.2 테스트 계획](TEST_PLAN_AQ_V02_KO.md)
- [Autonomous Quality 0.2 마이그레이션 정책](MIGRATION_AQ_V02_KO.md)
- [Autonomous Quality 0.2 검증 기록](VERIFICATION_AQ_V02_KO.md)
- [ControllerExecutor 격리 경계](CONTROLLER_EXECUTOR_KO.md)
- [AQ 0.2 delivery profile](DELIVERY_PROFILES_KO.md)
- [AQ 0.2 material authoring](MATERIAL_AUTHORING_KO.md)
- [AQ 0.2 quality benchmark](QUALITY_BENCHMARK_KO.md)
- [Portable verification evidence](verification/evidence/README.md)
- [V0.9 아키텍처](ARCHITECTURE_V09_KO.md)
- [V0.9 빠른 시작](GETTING_STARTED_V09_KO.md)
- [V0.9 테스트 계획](TEST_PLAN_V09_KO.md)
- [V0.9 검증 기록](VERIFICATION_V09_KO.md)
- [External Static Asset Intake](EXTERNAL_STATIC_ASSET_INTAKE_KO.md)
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

<!-- CBM:REPOSITORY_SUMMARY:START -->
## Generated repository summary

- Catalog schema: 0.1.0
- Legacy builders: curve, custom_mesh, primitive, profile_extrude, revolve, terrain
- Structural builders: boolean_tree, curve, custom_mesh, geometry_nodes_template, loft, multi_loop_extrude, primitive, profile_extrude, revolve, sweep, terrain
- Active autonomy profiles: autonomous_static_prop_v1
- Experimental profiles: autonomous_static_prop_v2, autonomous_environment_v1, autonomous_architecture_v1, autonomous_measured_asset_v1
- Existing delivery outputs: portable_gltf, obj_legacy
- Experimental delivery roles: portable_fbx, review_only
- CLI commands: 115
- CLI registry SHA-256: 1ad4ce99dd8c4f728a8aaebe8400a5fb5f2eb730b1b1d2fd5a4e6f91ba495951
- MCP server tools: 110
- MCP server registry SHA-256: 5bb2ef0c7826088ffb8062a32d338187e8193cfa8fe85307d6260b9a7bc22c36
- Project-enabled MCP tools: 109
- Project-enabled MCP SHA-256: 701ed2b37569e18cfc9c6cc1f276e50673041182ba5d2d97757a3b7561fe0024
- Controller phase profiles: reference_readonly, geometry_authoring, material_authoring, quality_readonly, delivery, handoff_plan, admin_audit, delegated_controller_v1
- Delivery registry SHA-256: c7ca99c593982facf2c1673c489f53a9ef89965adb6a77474ffdca4970549acd
- Latest reported test count: 1350
- Verification summary: verification/latest_summary.json (passed)

Server registration, project enablement, and controller phase profiles are separate authorization surfaces. Experimental entries are not verified support.
<!-- CBM:REPOSITORY_SUMMARY:END -->
