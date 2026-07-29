# V0.8 Short-Prompt Automation & Job Orchestration 아키텍처

## 목표

V0.8은 V0.4~V0.7 기능을 새로 대체하지 않는다. 사용자의 짧은 요청을 보수적으로 분류하고, 필요한 기존 단계들을 순서화하며, 중단·재개·승인·실패를 파일 기반 상태로 관리한다.

```text
짧은 요청
→ 의도 라우팅
→ 목적지 해석
→ 불변 WorkflowPlan
→ 결정론적 host 단계 실행
→ agent 판단 또는 사용자 승인에서 정지
→ 현재 파일 hash로 상태 재구성
→ 재개
```

Geometry SceneSpec은 `0.2.0`, 재질은 `0.5.0`, QA는 `0.6.0`, portable asset은 `0.7.0`을 유지한다. V0.8은 별도 `0.8.0` workflow 계약만 추가한다.

## 의도 라우팅

지원 의도는 다음 여덟 가지다.

| intent | 의미 | 안전한 기본 종료점 |
|---|---|---|
| `new_asset` | 새 레퍼런스로 새 자산 생성 | 프록시 승인 |
| `revise_asset` | 기존 자산의 제한 수정 | 재빌드·검증 |
| `add_measured_view` | 정면/측면/평면/청사진 추가 | 재분석 |
| `interior_scope` | 명시적으로 요청한 실내 범위 | 별도 InteriorScope 승인 |
| `material_authoring` | V0.5 재질·셰이더 작성 | swatch 승인 |
| `visual_qa` | V0.6 직접 비교와 수정 후보 | QA 검토 |
| `interior_visual_qa` | 승인된 실내의 별도 다각도 구조 검사 | exact camera-plan 승인 뒤 QA 검토 |
| `portable_package` | V0.7 최적화·포터블 패키지 | 최종 패키지 승인 |

새 레퍼런스는 항상 새 `job_id`를 사용한다. 기존 job에 다른 primary reference를 넣는 것은 거부한다. 기존 job 요청이 두 의도에 동시에 해당하거나 어떤 의도인지 불분명하면 추측하지 않고 명시적 `--intent`를 요구한다.

## 레퍼런스 내용 범위

`reference_content_scope`는 `execution_policy` 및 `delivery_scope`와 독립된
job-level 계약이다.

- `full_reference`: 하위 호환 기본값이며 관련 환경까지 허용한다.
- `primary_object_only`: 명시적 `target_subject`와 primary/supporting
  구성요소만 허용한다.

object-only workflow는 agent 지시만 신뢰하지 않는다. ModelingPlan의
`scope_role`과 SceneSpec의 `qa_role:primary|supporting`을 host가 검증하고,
context 역할이나 독립 지형·식생·배경 semantic이 들어오면 build provenance
생성 전에 실패한다. content scope와 target은 request, plan, state와
`job.json`에 보존되며, 기존 job에서 변경할 수 없다.

V0.6 reference mask는 object-only job에서 관찰된 primary/supporting evidence
bbox의 합집합으로 제한된다. 따라서 주변 지형이 reference foreground에
포함돼도 주 피사체 점수를 왜곡하지 않는다. 대상 evidence가 없거나 모호하면
전체 장면 점수를 대신 만들지 않고 unscorable 또는 사용자 확인 상태로 남긴다.

## 실행 정책과 종료 범위

V0.8은 모델링 파이프라인을 둘로 복제하지 않는다. 동일한 V0.4~V0.7 host/agent 계약 위에 다음 두 필드를 직교 정책으로 추가한다.

- `execution_policy`: `standard` 또는 명시적 opt-in인 `background_exterior`
- `delivery_scope`: 빠른 경로에서 사용자가 계획 전에 확정하는 `preview_only` 또는 `portable_package`; `standard`에서는 기존 `scope`와 intent로부터 effective 값이 내부 기록됨
- `fast_quality_policy`: 새 빠른 경로의 `review_delivery_v2`; 실행 완료와 품질 합격을 분리하고 legacy plan에는 없을 수 있는 optional 필드

정책 값은 `WorkflowRequest`, `IntentRouting`, `WorkflowPlan`,
`WorkflowState`에 보존된다. 기존 V0.8 JSON에 `fast_quality_policy`가 없으면
기존 eligibility 차단 규칙을 사용하는 legacy evidence로 읽으며 파일을
재작성하거나 이전 blocked workflow를 재분류하지 않는다.

```text
standard
└─ 기존 proxy/detail/material/QA/package 일반 검토와 전용 승인 유지

background_exterior + preview_only
└─ reference analysis
   → modeling plan
   → workflow-owned 중간 크기 외형 SceneSpec candidate
   → bounded pre-QA fit diagnostic 최대 2회
   → 선택 candidate strict validation 및 canonical promotion 최대 1회
   → build/render/inspect/validate
   → 로컬 결정론적 material/shader
   → canonical 직접 reference QA 정확히 1회
   → execution/quality 분리 report
   → 통합 PDF
   → delivered_for_review

background_exterior + portable_package
└─ 위 제작 흐름
   → V0.7 preflight/review
   → exact optimization-plan 승인
   → derived optimization/package/clean-import
   → 통합 PDF
```

빠른 경로의 적격 범위:

| 허용 | 제외 |
|---|---|
| 새 lowercase job ID | 기존 job을 새 자산으로 덮어쓰기 |
| `concept` 단일 primary reference | measured, blueprint, 치수, 보조 view |
| 정적 외관 배경·장식물 | 실내, rig, animation, gameplay |
| whitelisted procedural/local 512 px 재질 | 외부 image/texture provider |
| 직접 Visual QA 정확히 1회 | generated target, 자동 revision |
| engine-neutral preview/package | Unity/Unreal/custom runtime parity |

빠른 geometry agent는 proxy와 detail로 canonical SceneSpec을 두 번 교체하지 않고,
하나의 제한된 중간 상세 SceneSpec을 workflow-owned initial candidate로 작성한다.
host는 최대 두 번의 저해상도 primary-only fit diagnostic으로 제한된 카메라
후보만 비교하고, 점수가 실제로 개선된 strict candidate만 canonical
SceneSpec으로 한 번 promotion한다. 각 candidate, 변경 경로, metric, 선택/rollback
이유와 promotion receipt는 exact hash로 보존된다. 이 fit은 canonical V0.6 QA
run이 아니며 semantic/material ID, custom-mesh vertex 또는 실내를 바꾸지 않는다.

조건을 벗어나는 scope·안전 위험을 발견하면
`requires_standard_workflow`를 보고하고 completion marker를 남기지 않는다.
반면 직접 QA의 high visual finding은 workflow 실행 실패가 아니다. exact
quality report가 `passed`, `needs_revision`, `unscorable` 중 하나로 분류하고,
QA JSON/PDF와 combined PDF가 만들어졌다면 `preview_only`는
`completed` / `delivered_for_review`로 종료한다. 이는 delivery 성공일 뿐
`needs_revision` 또는 `unscorable` 자산의 품질 합격을 뜻하지 않는다.

완료된 빠른 preview를 나중에 package로 확장할 때는 preview workflow ID, plan SHA-256, terminal completion fingerprint, QA run ID, canonical-source fingerprint와 embedded build fingerprint를 새 request에 결속한다. V0.7 시작 전 전용 host prerequisite가 이를 다시 검사하므로, preview 뒤 SceneSpec·재질·build 또는 관련 정책이 바뀌면 package workflow는 fail-closed로 중단된다.

## 목적지 해석

의도와 목적지는 별도로 해석한다. 현재 검증된 adapter는 V0.7의 engine-neutral static-asset package뿐이다.

- `engine_neutral`: 사용 가능
- `unity`, `unreal`, `custom`: 아직 미지원
- 미지원 목적지가 명시되면 V0.7 portable package까지만 생성하고 adapter 부재를 기록
- engine prefab/actor, runtime shader, 물리·LOD runtime 비용은 구현됐다고 주장하지 않음

## 저장 구조

```text
workspaces/<job>/workflows/
├─ latest.json
├─ locks/
├─ stale_locks/
└─ <workflow-id>/
   ├─ request.json
   ├─ routing.json
   ├─ plan.json
   ├─ state.json
   ├─ inputs/
   ├─ artifacts/
   │  ├─ g/                        SceneSpec fit/role/promotion evidence
   │  ├─ m/                        material candidate/promotion evidence
   │  ├─ s/                        shared derived output snapshots
   │  └─ pdf/                      workflow-owned PDF와 sidecar
   ├─ completions/
   ├─ approvals/
   └─ attempts/<step-id>/<attempt-id>.json
```

`request.json`, `routing.json`, `plan.json`은 불변이다. `state.json`은 권위 있는 설계 원본이 아니라 현재 파일·hash·영수증을 다시 읽어 만든 projection이다.

## 단계 실행 모델

각 단계는 다음 실행 방식 중 하나를 가진다.

- `host`: 스키마 검증, 분석, Blender 명령, 패키징처럼 결정론적으로 호출 가능한 단계
- `agent`: 모델링 계획, SceneSpec, 재질 계획처럼 시각 판단과 저작이 필요한 단계
- `approval`: 프록시, 상세 메시, swatch, QA, 최종 패키지에 대한 일반 사용자 검토
- `specialized_approval`: InteriorScope, interior QA camera plan, V0.6 revision, V0.7 optimization의 기존 exact-hash 승인
- `manual`: 검증된 목적지 adapter가 없는 종료 경계

일반 workflow 승인은 specialized approval을 대체할 수 없다.

사람이 결과를 확인하는 프록시, 상세 메시, 재질, QA, portable package gate 앞에는 기존 canonical JSON과 렌더를 투영한 PDF와 sidecar manifest를 생성한다. PDF는 읽기용이며 상태 판정과 승인은 계속 JSON/hash를 기준으로 한다.

## 신선도와 완료 판정

단계 완료는 파일 존재만으로 판정하지 않는다.

1. 입력 dependency의 완료 fingerprint를 계산한다.
2. 요구 산출물의 존재, 스키마, SHA-256을 검사한다.
3. agent completion marker가 현재 plan/input/output과 정확히 일치하는지 확인한다.
4. approval이 현재 artifact fingerprint와 정확히 일치하는지 확인한다.
5. 하나라도 바뀌면 해당 완료를 `stale`로 바꾸고 후속 단계를 다시 실행하지 않는다.

`integrity`, `currentness`, `verification`은 서로 다른 필드로 기록하여 “파일이 읽힌다”와 “현재 입력에서 만들어졌다”를 혼동하지 않는다.

### Artifact lifecycle과 canonical promotion

V0.8은 artifact를 다음 lifecycle로 구분한다.

- `canonical`: 현재 job의 설계 원본. 예상하지 않은 변경은 stale/tampering으로 차단
- `workflow_snapshot`: 공유 derived path를 실행 시점 hash로 복제한 불변 증거
- `immutable_run`: QA run, optimization run, package처럼 처음부터 run-owned인 증거

V0.5 fast material 흐름은
`material.scaffold → material.author → material.promote`로 구성된다. Scaffold와
authored candidate는 서로 다른 workflow-owned 디렉터리에 있고 agent completion은
authored candidate의 exact hash를 사용한다. `material.promote`만 strict contract
validation 뒤 canonical MaterialPlan을 교체하며 이전 canonical history,
candidate hash, 전후 canonical hash, workflow/step/input fingerprint를
promotion receipt에 기록한다.

`.blend`, preview, inventory, validation과 같은 공유 derived path는 host attempt가
끝날 때 workflow snapshot으로 보존된다. 계획된 successor가 공유 path를 갱신하면
이전 snapshot/receipt는 당시 실행 증거로 계속 current이다. 반대로 successor가
아닌 외부 변경이나 현재 prerequisite의 source mismatch는
`orchestration_artifact_conflict`로 fail-closed한다. 단순히 공유 파일을
fingerprint 계산에서 제외하지 않는다.

QA completion은 `qa/latest.json`이 아니라 계획에 고정된 exact
`qa/runs/<run-id>/` 디렉터리에 결속된다. Workflow PDF도
`workflows/<workflow-id>/artifacts/pdf/` 아래에 있어 후속 workflow 보고서와
충돌하지 않는다.

차단 원인과 품질 결과는 machine-readable하게 구분한다.

- `requires_standard_workflow`: constraint/measured, interior, rig, animation,
  gameplay, engine-specific 요구, unsafe ambiguity 등 실제 범위·안전 위험
- `orchestration_artifact_conflict`: 예상하지 않은 artifact ownership 또는
  source/fingerprint 충돌
- `host_failure`: Blender 예외, timeout 등의 실행 실패
- `quality_status=needs_revision`: primary/supporting high visual finding이 있지만
  review evidence delivery는 완료됨
- `quality_status=unscorable`: primary mask/role evidence를 신뢰할 수 없어 품질
  합격을 주장할 수 없지만 review evidence delivery는 완료됨

QA 역할은 SceneSpec `0.2.0`을 변경하는 새 필수 필드가 아니라 V0.8 run-owned
`BackgroundRoleMap`으로 분리한다. explicit `qa_role:*` tag를 우선하고 semantic,
parent, largest-observed fallback을 적용한다. `primary` high는 표준 수정 권장,
`supporting` high는 중요 finding, `decorative` high는 warning,
`ground_background`는 environment evidence이다. 마지막 역할은 primary
silhouette mask에서 제외되어 넓은 ground plane이 점수를 왜곡하지 않는다.

기존 V0.8 plan에는 새 lifecycle 필드가 없을 수 있다. 이 경우 legacy 규칙으로
읽으며 파일을 재작성하지 않는다. 이미 blocked인 workflow는 역사적 evidence로
보존하고, 수정된 lifecycle 계약은 새 workflow부터 사용한다.

## 재개, 실패, 잠금

- host 실행마다 고유 attempt receipt를 먼저 `running`으로 기록한다.
- 성공과 실패 모두 같은 receipt에 종료 시각과 결과를 기록한다.
- 실패 단계는 자동 재시도하지 않는다.
- 원인을 해결한 뒤 `--retry-failed`를 명시해야 현재 실패 단계 하나만 새 attempt로 재시도한다.
- 이전 프로세스가 남긴 `running` receipt는 `InterruptedAttempt`로 종료한 뒤 새 attempt를 시작한다.
- job별 live lock은 동시 writer를 거부한다.
- TTL이 지난 유효 lock만 이력으로 보존하고 복구한다.
- 취소는 산출물을 삭제하지 않으며 취소된 workflow는 재개할 수 없다.

## 승인 경계

일반 승인 gate:

- `proxy_geometry`
- `detailed_geometry`
- `material_swatches`
- `qa_review`
- `final_package`

기본 workflow PDF 위치:

```text
workspaces/<job>/reports/pdf/proxy_report.pdf
workspaces/<job>/reports/pdf/detail_report.pdf
workspaces/<job>/reports/pdf/material_report.pdf
workspaces/<job>/reports/pdf/qa_report.pdf
workspaces/<job>/reports/pdf/portable_report.pdf
```

전용 승인 gate:

- `interior_scope`: 현재 scope SHA-256과 수동 interactive 승인
- `interior_qa_plan`: 현재 scope/source/build에 묶인 exact multi-view camera plan 승인
- `visual_revision`: 선택 candidate와 단일 사용 approval
- `optimization`: 표시된 LOD/collider/consolidation plan SHA-256 승인

V0.8은 승인을 생성하거나 추론하지 않는다.

`background_exterior`는 일반 검토 영수증을 자동 생성하는 방식이 아니다. 빠른 계획에서 proxy/detail/swatch/QA/final-package 일반 gate 자체를 생략할 뿐이다. InteriorScope, interior-QA camera plan, guarded V0.6 revision, measured-view replacement, V0.7 optimization plan, destination handoff 같은 전용 exact-hash 승인은 생략하거나 일반 승인으로 대체할 수 없다.

## 안전 경계

- short request만으로 실내를 생성하지 않음
- short request만으로 실내 QA camera plan을 승인하거나 렌더하지 않음
- short request만으로 V0.6 수정 후보를 적용하지 않음
- short request만으로 LOD/collider 기본값을 최적화에 적용하지 않음
- 외부 이미지 생성 provider budget 기본값은 0
- canonical SceneSpec, geometry, 재질 및 입력은 각 기존 단계의 규칙대로만 변경
- `first_reference_test` 같은 기존 사용자 작업은 V0.8 gate에서 사용하지 않음

## V0.9로 넘기는 범위

V0.8은 orchestration core를 제공하지만 다음은 V0.9 안정화 범위다.

- 다중 작업 queue와 장기 scheduler
- Windows/macOS/Linux 및 Blender 지원 매트릭스 확대
- Unity/Unreal adapter 실기동 검증
- 다양한 실제 자산 benchmark와 성공률 통계
- upgrade/migration 자동화와 release candidate 검증
