# Reference Fidelity 0.1 — disabled-experimental companion

프로젝트는 `0.9.0`, canonical SceneSpec은 `0.2.0`이다. 이 기능은 reference 관찰과 실제 렌더를
연결하는 별도 계약이다. 기존 V0.6/IQ 점수, 인간 quality disposition, package acceptance 또는
Activation의 의미를 바꾸지 않는다. 구현과 실자산 입증 상태는
[검증 기록](../VERIFICATION_REFERENCE_FIDELITY_KO.md)을 함께 읽는다.

## 적용 범위

- Standard: 공통 관찰·저작·평가·비교를 advisory로 사용한다. 기존 `manual_guarded`, candidate review,
  exact geometry/material/QA/package 승인 경계가 canonical 변경을 통제한다.
- AQ: 새 autonomous Envelope 세션에만 `AQQualityRevisionLoopV01`을 초기 geometry 이전에 명시적으로
  bind한다. 기존 세션, checkpointed/interactive 세션, 이미 종료된 세션은 자동 변환하지 않는다.
- optional companion이 없는 AQ는 기존 nonpass → review terminal 경로를 유지한다.
- Codex 시각 평가는 인간 승인이 아니며 canonical writer도 아니다. source/receipt/policy를 재검증한
  기존 host promotion만 canonical을 변경할 수 있다.
- 단일 reference에 없는 면은 추정이다. 추가 시점은 생성 자산의 일관성 근거이며 실제 숨은 면 복원
  또는 관측하지 않은 multi-view reference match를 뜻하지 않는다.

## 계약과 실행 순서

`관찰/불확실성 → 3D 가설 → 구조 저작 → 실제 렌더 → 결함 → 해당 단계 수정 → 같은 조건 전후 비교`

1. `ModelingHypothesisV01`에서 reference SHA, 관찰 영역/landmark, 관찰·추정 구분, 부피/단면/부품 관계,
   카메라 가설, 필수 관찰 항목과 비교 방법을 고정한다. candidate bbox를 기대값으로 역사용하지 않는다.
   얇은 sheet/shell, 단일 물체와 균일 재질에 불필요한 다부품·두께·디테일을 강제하지 않는다.
   적용 제외는 가설에서 이유와 함께 선언하며 평가자가 임의로 요구 사항을 지울 수 없다.
2. `StructureAuthoringV01`은 기존 V03 loft/sweep 등의 strict recipe와 authored ModelingPlan을 연결한다.
   새 opt-in geometry promotion도 같은 observation coverage, `spatial_v1`, assembly, camera 검사를 실행한다.
   controller에는 loop/hypothesis와 후속 회차의 exact finding·이전 패스가 읽기 전용 assignment 입력으로 전달된다.
   과거 후보는 명시적 비교/수정 시작점일 뿐 신규 reference의 sequence별 source replay 생성기가 아니다.
3. `RenderEvidenceV01`은 실제 일곱 V0.6 패스, request/report/manifest, SceneSpec, 중첩 geometry payload,
   build source와 실제 비교 조건을 묶는다. geometry/material snapshot은 다음 회차에서 canonical 경로가
   바뀌어도 읽을 수 있다. SceneSpec-only 직접 재질 dependency는 legacy build fingerprint로 보장됐다고
   소급 주장하지 않고 supplemental source로 구분한다.
4. `VisualFindingSetV01`은 feature별 기대/실제 모습, confidence, 대상 semantic/face-group, image ROI와
   사용한 패스를 기록한다. 누락/낮은 신뢰는 `missing_evidence`이며 bbox나 디테일 점수로 상쇄하지 않는다.
   방향성 재질은 새 `DirectionalMappingEvidenceV01`과 `DirectionalMaterialPreflightV01`으로 exact
   texture manifest·coordinate binding·image-plane extent·runtime scale을 먼저 결속한다. 이 검사는
   빈/반대 방향/단일 주기 band와 실제로 샘플되는 tile 범위 부족을 Blender 전에 차단하지만 reference
   similarity나 인간 판정을 대신하지 않는다. legacy `procedural_wood_v1` 바이트는 고정하고, additive
   `procedural_wood_v2`가 명시적인 2D fibre axis와 비단일주기 deterministic channel을 제공한다.
5. `QualityAttemptV01`은 현재 source state, geometry/material receipt tuple, 동일 V0.6를 사용하는 IQ
   submission과 시각 평가를 비terminal로 기록한다. 후속 회차에는 exact paired comparison이 필요하다.
6. host가 결함 종류와 잔여 예산에서 route를 선택한다. 수정 계획·source snapshot·reservation을 먼저
   게시하고 원래 controller/build/closure/atomic promotion/rollback 경로를 재사용한다.
7. 관찰 조건이 충족되면 `quality_ready`로 기존 IQ/source-freeze/delivery 경계에 돌아간다. 이 상태가
   IQ pass, 인간 accepted 또는 production package를 의미하지는 않는다. 최종 IQ submission 교체도 거부한다.
8. 정체·예산 소진은 typed fidelity review bundle/terminal로 보존한다. 기존 IQ 결과를 nonpass로
   다시 쓰거나 인간 `needs_revision`을 대신 생성하지 않는다.

| 결함 | 선택되는 경로 |
|---|---|
| 큰 부피·단면·silhouette·부품 관계 | structural reentry, V0.4 재저작 |
| 국소 치수/위치 | bounded parametric, topology/부품/회전 변경 금지 |
| 재질·결 방향·색·거칠기 | material revision, 기존 geometry receipt를 유지하고 새 material receipt 선택 |
| 카메라 가설 | calibration hold; camera만 바꾸어 개선으로 계산하지 않음 |
| 필수 관찰 미측정 | evidence-required hold 또는 동일 증거의 제한된 보충 |
| topology·UV | 해당 technical recovery 경계; 승인 문제로 전환하지 않음 |

재질 결함의 정체를 structural reentry로 자동 승격하지 않는다. 수정 전략은 진단된 경로 안에서 바꾸며,
국소/재질 전략 변경도 같은 1회 strategy-switch 및 공용 local 예산을 소비한다. 구조 결함을 rails/noise/
디테일 증량으로 숨기는 것은 해결이 아니다.

## 예산과 재개

companion의 최대값은 최초 후보 후 structural `3`, shared local `2`, strategy switch `1`이다.
이 최대값은 기존 AQ root budget을 확대하지 않는다. 예를 들어 root structural `2`이면 loop `3`은 bind할 수 없다.
Material rounds, builds, materializations, QA/IQ, promotions와 action budget도 각각 충족해야 한다.
모든 관찰이 optional/N-A인 checklist는 새 AQ loop에 bind할 수 없다.

`RevisionCostV01`은 materialization/build/QA/closure/diagnostic view/promotion을 분리한다. 구조 수정은
geometry와 material 재build/promotion, 갱신된 closure와 다음 QA를 모두 예약해야 한다. source를 복사하기
전 비용을 검사한다. 최소 materialization 비용도 현재 object 수로 산정한다(6객체라면 1회가 아니라 6회).
원장과 회차 번호는 단조 증가하고 rename/resume/child 생성으로 초기화하지 않는다.
새 loop는 V0.6 렌더 비용을 별도 `QualityRenderReservationV01` 원장에 예약하며 IQ counter와 합쳐 root
quality budget을 검사한다. 이 원장을 무시하고 기존 base counter만 실행 총비용으로 보고하면 안 된다.

동일 입력 technical render retry는 최대 1회다. report가 이미 완성된 같은 run은 새 렌더/과금 없이
exact source와 report를 재검증하여 이어받는다. report 이전 실패는 보존하고 허용된 새 retry run만 실행한다.
중간 source/plan/reservation 뒤 crash는 같은 계획을 재검증해 채택하며 두 번 과금하지 않는다.

AQ가 아닌 격리 개발 preview의 기본 상한은 6회다. 전역 상수를 늘리거나 새 job으로 초기화하지 않는다.
추가 실증이 명시적으로 허용되면 `DevelopmentPreviewBudgetExtensionV01`이 exact job, SceneSpec SHA,
primary/retry run ID에 `+2`를 묶는다. 첫 슬롯의 `DevelopmentPreviewAttemptOutcomeV01`이
`technical_failure`일 때만 byte-identical source의 두 번째 슬롯을 쓸 수 있다. 정상 beauty가 생성된 뒤의
미관 재시도에는 사용할 수 없다. 이 계약은 인간 판정, package acceptance, campaign 또는 Activation 권한이 아니다.

첫 확장 primary가 정상 완료되어 그 retry가 닫힌 뒤 실제 표현 전략을 바꿔야 하면,
`DevelopmentPreviewBudgetExtensionV02`가 prior extension/outcome, 변경된 SceneSpec, 중첩 mesh/texture
dependency closure, build fingerprint, 전체 Python package와 locked project input의 implementation
fingerprint, Blender 5.0.1 executable SHA/version 및 새 primary/retry run ID를 exact scope SHA에 묶는다.
승인 후 해당 실행 코드나 Blender binary가 바뀌면 reservation 전에 fail-closed한다. 닫힌 retry를
재사용하지 않으므로 누적 authorized cap은 10이어도 실제 최대 reservation은 9다. V02 역시 exact scope 승인 전에는 발행되지 않으며
canonical/human/package/campaign/Activation 권한을 부여하지 않는다.

V02 primary가 정상 beauty로 닫힌 뒤에도 서로 다른 구조/재질 결함이 남으면
`DevelopmentPreviewBudgetExtensionV03`이 그 완료 outcome과 변경된 combined candidate를 다시 exact
scope에 묶는다. 완료된 과거 V02의 runtime fingerprint는 당시 실행 증거로 보존하고, 이후 코드 변경 때문에
과거 원장 자체를 unreadable로 만들지 않는다. 대신 V03의 현재 implementation/build/Blender binding을
발행·reservation·완료 직전에 각각 검사한다. V03도 primary 1회와 beauty 전 동일 입력 technical retry
1회뿐이며, 닫힌 이전 retry 두 개를 되살리지 않아 누적 authorized cap 12와 실제 최대 reservation 10을
구분한다.

V03 primary의 실제 source-bound 평가가 `material_revision`을 요구하면
`DevelopmentPreviewBudgetExtensionV04`가 그 exact findings/evaluation, 이전·신규 후보의
`UVSpatialPreservationV01`, 동일 structural source/mesh와 새 material dependency closure를 함께 묶는다.
공간 형상·pose·camera·reference 및 stable material/object assignment가 같아야 하며, geometry 변경은 이
경로에서 거절한다. V04도 material primary 1회와 beauty 전 동일 입력 technical retry 1회만 허용한다.
닫힌 이전 retry 세 개는 재사용하지 않아 누적 authorized cap 14와 실제 최대 reservation 11을 구분한다.
이 exact 개발-preview 권한은 canonical write, 인간 판정, package, campaign 또는 Activation 권한이 아니다.

image-backed normal/height는 `procedural.normal_strength`, `procedural.bump_strength`,
`procedural.bump_distance`를 Blender runtime control로 사용한다. 이 값은 manifest load 때 유한성·안전
범위와 intended scale을 검사한다. image channel의 과거 `strength` 필드는 runtime node 제어로 소급
해석하지 않는다. 기존 manifest 의미를 바꾸지 않고, 새 후보가 소비되는 제어값을 명시하도록 한다.

같은 route와 strategy에서 같은 결함이 두 평가에 계속 남으면, 다른 작은 결함이 개선됐더라도 전략 변경을
요구한다. 허용된 변경 후 정체하거나 해당 route의 예산이 없으면 best-known evidence를 보존하고 중단한다.
수정·렌더·검증·`needs_revision` 횟수는 시각 개선 KPI가 아니다.

이미 기록한 `evidence_required` attempt에는 같은 source/camera/IQ/일곱 패스에서 누락했던 관찰만 1회
append-only로 보충할 수 있다. 기존 defect/satisfied 판단의 변경, 다른 pixels 또는 예산 초기화는 금지한다.
이는 새 candidate 개선이 아니고 계측 보충이다. 새 시점/새 reference/카메라 변경이 필요한 경우 이 API를
우회로로 쓰지 않고 실제 증거/범위 협의 경계에서 멈춘다.

## 공개 host surface

| CLI | MCP | 역할 |
|---|---|---|
| `fidelity-evidence JOB RUN OUTPUT [--scene-snapshot PATH]` | `capture_reference_fidelity_evidence` | 실제 QA source snapshot |
| `fidelity-evaluate JOB REVIEW OUTPUT` | `evaluate_reference_fidelity` | nonhuman finding 평가 |
| `fidelity-material-preflight JOB IMAGE MAPPING AXIS DOMAIN SPAN OUTPUT` | `preflight_directional_material` | 방향/단일주기/mapping local 사전검사 |
| `fidelity-compare JOB BEFORE AFTER OUTPUT` | `compare_reference_fidelity` | 고정 조건 전후 비교 |
| `aq-quality-loop-bind JOB SESSION PLAN` | `bind_aq_quality_revision_loop` | 새 exact session opt-in |
| `aq-quality-render JOB SESSION RUN` | `render_aq_reference_fidelity` | 비용 예약 + 일곱 패스 + 재개 |
| `aq-quality-attempt JOB SESSION REVIEW SUBMISSION` | `submit_aq_quality_attempt` | 비terminal 현재 회차 평가 |
| `aq-quality-supplement JOB SESSION REVIEW` | `supplement_aq_quality_evidence` | 같은 증거의 누락 관찰 1회 보충 |
| `aq-structural-reentry JOB SESSION STRATEGY COST` | `begin_aq_structural_reentry` | structural-only wrapper |
| `aq-quality-reentry JOB SESSION STRATEGY COST` | `begin_aq_quality_reentry` | 진단된 structural/local/material route |

경로는 job-relative contained path이며 exact 해시를 검사한다. MCP project allowlist는 controller phase
authority가 아니다. material closure의 이미 고정된 입력 multiset은 늘리지 않는다. 최신 스킬 변경은
과거 `skill_runs` snapshot을 바꾸지 않는다. 실제 CLI optional flag는 해당 `--help`가 소유한다.

## 현재 제한과 남은 입증

- typed observation/coverage와 source-bound nonhuman visual review가 구현된 것이며, arbitrary reference에서
  depth·landmark·part pose를 자동 복원하거나 자동 정답 판별하는 모델이 추가된 것은 아니다.
- camera 기본 가설은 측정이라고 표시하지 않는다. 자동 calibration/re-render-both 실행 경로는 아직 없다.
- 추가 시점 artifact는 consistency-only로 읽는다. required IQ landmark/multiview를 flag만 켜서 통과시키지 않는다.
- 실제 개발 목재 preview는 AQ root/policy loop 실행 증거가 아니다. 별도 고정 fixture에서 실제 Blender
  multi-round geometry/material/quality/structural-policy-reentry/terminal vertical은 통과했지만, fixture의
  `defect/satisfied` 입력은 배선 검증용이다. 대표 목재는 별도 exact attempt09에서 고정 관찰 4/4와
  attempt08 대비 `improved`를 기록했으며, 이는 비인간 시각 평가이지 AQ campaign 또는 인간 수락이 아니다.
- `procedural_wood_v2`와 방향성 preflight의 unit 증거는 생성 패턴과 실행 전 차단 능력만 보여 준다.
  규칙적 stripe가 남은 실제 목재 attempt02는 render 전에 보존·중단했다. append-only attempt03는 exact
  scope 승인 뒤 Blender 5.0.1 same-camera 일곱-pass를 완료했고, glossy band에서 longitudinal/end grain으로
  명확히 나아졌지만 넓고 평행한 홈, 어두운 규칙성, 부족한 풍화·옹이·거칠기 때문에 source-bound
  evaluation은 여전히 `needs_revision`이다. 이는 인간 판정이나 B 완료가 아니다. 후속 attempt04의 더
  좁고 비대칭인 structural depressions와 밝은 dry-wood 파라미터는 image-only preflight까지만 통과했다.
  그 SceneSpec의 V03 proposal `b728e3a7826e8b9862ec86b4298ff91c9645cb77c9b3ad5cbecdf7716e0d70b6`은
  실행 전에 superseded됐다. MeshPayload 0.2 polygon-corner UV와 수동 center cap을 사용한 attempt07도
  closed two-manifold와 0 degenerate face였지만 shared-edge orientation 320개가 불일치해 proposal
  `4bad8cf9abfc491b894ae3d83a45be48890198055ac6586308fc4273498c359b`을 실행 전에 superseded했다.
  공통 loft compiler가 dense convex cap의 nondegenerate center fan과 first→last progression 기준 winding을
  처리하도록 수정한 뒤 동일 authoring을 재컴파일한 attempt08은 exact source topology, 4,320 edge의
  incidence 2/orientation balance 0, 8,640 loop UV와 image-only preflight를 통과했다. exact scope
  `ec090247635b469f0fb90782c5654247c3713eeaeae1533f09a4d031aa07cf26`의 primary 실제 preview도 완료됐고,
  구조 관찰 3/4를 충족했지만 방향성 목재 surface는 major `material_revision`으로 남았다. 동일 공간 형상
  위에서 대비·옹이·거칠기와 명시적 runtime normal/bump controls를 바꾼 material-only attempt09는 exact
  V04 scope `0f650030829c32f085e1a48648d1a84d4a66aae0738717d8f085e01e723d2e98` 승인 뒤
  Blender 5.0.1 일곱-pass를 완료했다. beauty `e03dbf968acc61e279ad39dd94714ff204ae5f325951a477aa620cbfb9d29297`의
  source-bound 비인간 evaluation은 고정 관찰 4/4 `visually_satisfied`, attempt08 대비 comparison은
  `directional-wood-surface` 해소·신규 회귀 없음의 `improved`다. attempt05/06 준비 실패는
  Blender·preview budget·canonical write 없이 append-only로 보존한다.
- `preview.py`는 AQ session 없는 격리 개발 job 전용이다. 기본 6회와 append-only exact extension chain을
  하나의 누적 원장으로 계산한다. 현재 목재 실증은 base 6 + V01 primary 1 + V02 primary 1 + V03 primary 1,
  합계 10회이며 네 successful primary 뒤의 technical retry는 모두 닫혔다. additive V04
  material-refinement extension SHA `4bff9b6e190d8b239aa70d7ae6915eaf207ade89693c987e8c6d07b1e782e6fe`는
  V03의 exact completion/review와 두 spatial audit, 변경 source 및 모든 dependency/runtime binding을
  검증해 한 번 발행·소비됐다. 닫힌 retry를 되살리거나 새 job으로 예산을 초기화하지 않는다.
- geometry 개선이 나머지 네 reference로 전이됐다는 증거, clean baseline의 새 five-asset 캠페인,
  실제 V0.7 bake/portable fidelity, package/human acceptance와 Activation은 별도 후속 조건이다.

## 검증

호스트 회귀는 `test_reference_fidelity*`, `test_quality_revision*`와 기존 AQ/Standard suite에 있다.
AQ gate 두 shell 버전에 같은 focused 목록을 등록하며, `test_reference_fidelity_aq_blender_vertical.py`는
실제 Blender opt-in에서 초기 회차와 구조 재진입 회차를 함께 실행한다. 이 fixture 통과는 실제 자산의
시각 품질이나 인간 수락을 뜻하지 않는다.
`scripts/audit_reference_fidelity_history.py --manifest tests/fixtures/reference_fidelity/historical_5e5b172.json`
은 지정된 16개 과거 anchor만 읽고 비교하며, 모든 workspace 파일의 보존을 증명하는 전체 snapshot은 아니다.
신규 baseline/campaign 진입은 [로드맵 8-B](../ROADMAP_V1_KO.md)의 순서와 성공 기준을 따른다.

2026-09-04 최신 검증은 full host `2236 passed, 73 skipped`, AQ focused `1140 passed, 32 skipped`,
실제 Blender 5.0.1 `56 passed, 1 skipped`다. AQ benchmark 0.1은 8/8, 0.2는 10/10 matched이며
후자의 `.t/aqg-v04-material` report SHA는
`d25c7ecc46caffd162c47e6623924ce06b69f75b1e9ae2975ad649c3fd0cd40a`다. 이 수치는 실제 5-reference
quality나 human acceptance가 아니다.

AQ/Blender v4 gate 뒤 추가한 implementation 및 Blender environment binding은 focused `13 passed`와
최신 full host에서 검증했다. 실행 코드, lock 입력, Blender binary/version이 달라지면 exact preview
reservation 전에 거절되며, 이는 기존 Blender smoke를 새 reference-quality 증거로 재분류하지 않는다.
