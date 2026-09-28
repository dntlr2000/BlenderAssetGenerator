# Reference Fidelity 0.1/0.2 — disabled-experimental companion

## Reference mask seed와 부품 전체 크기 증거

`ModelingHypothesisV01.reference_mask_seed_evidence`는 명시적으로 선택하는
`ReferenceMaskSeedEvidenceV01` (`0.1.0`) 동반 계약이다. 내부 foreground 표본은 hypothesis의
정확한 `observed` observation에 결속하고, SceneSpec의 부품 전체 `EvidenceSpec.bbox_norm`과
분리한다. seed의 confidence가 높아도 V0.6 semantic bbox 비교에 사용하지 않는다.

저작 사전 검사는 reference hash, job/source/object, primary/supporting 범위, 전체 관찰 영역 안의
seed 포함 관계를 확인한다. seed 대상의 semantic 비교는 ModelingPlan의 전체 부품 bbox를 유지해야
한다. AQ는 동일 hypothesis에 결속된 seed를 render 예약 전에 검증하고, QA mask manifest에
seed 계약과 digest를 기록한다. 실제 review에서도 hypothesis·mask bytes·manifest를 다시 확인한다.
명시적 seed의 stale/unknown/범위 오류나 segmentation 실패는 fallback 없이 중단한다.

동반 계약이 없는 과거 hypothesis와 Standard/AQ QA는 기존 seed 선택과 fallback 의미를 유지한다.
SceneSpec 0.2.0, 기존 V0.6 request/report, CLI/MCP 도구와 allowlist는 변경하지 않는다. 과거 QA를
새 seed 계약으로 다시 계산하거나 수정하지 않는다. 캠페인의 고정 seed 계약을 바꾸는 경우에는
새 clean source/baseline/scope와 해당 exact 승인이 필요하다.

## 선택적 reference trimap 제약 0.2

`ReferenceMaskSeedEvidenceV02` (`0.2.0`)는 원본만으로 관찰한 foreground/background
제약이 필요한 새 hypothesis에서 명시적으로 선택한다. 기존 `0.1.0`과 companion 부재의
seed·fallback·직렬화 의미는 그대로다. 색이 같은 물체와 그림자는 내부 foreground 표본만으로
구별되지 않을 수 있으므로, 이 경우 원본 reference SHA, trimap PNG SHA, 정확한 해상도,
content scope와 subject IDs, 양쪽 label의 observed observation을 함께 고정한다.

trimap은 단일 grayscale PNG로 `0=확실한 배경`, `85=배경 추정`, `170=물체 추정`,
`255=확실한 물체`만 허용한다. 최대 4096×4096이며 실제 reference와 크기가 같아야 한다.
관찰한 label 영역과 foreground seed core는 실제 trimap label과 일치해야 한다.
primary-object 범위 밖의 foreground, 다른 source/subject, stale hash, unknown version,
다른 label 값이나 해상도 변경은 render 예약 전에 거부한다. geometry 또는 render silhouette에서
제약을 역으로 만들면 안 된다. 제약으로 강제한 표본의 일치는 독립적인 시각 검증이 아니다.

기존 host가 난수 seed 0, GrabCut 5회로 처리하고 확실한 label을 보존한다. 명시적 제약 실패에
fallback은 없으며, enclosed-hole fill로 background label을 덮지 않는다. 각 QA run은 원본
trimap bytes의 별도 snapshot과 exact manifest를 보존한다. review는 hypothesis·source·trimap·
run snapshot·output mask를 다시 검증하고 다른 회차 snapshot을 거부한다. 이전 QA mask나
direct score를 다시 계산하지 않는다. CLI/MCP 명령·allowlist와 SceneSpec 0.2.0은 동일하고,
새 제약은 geometry·promotion·예산·인간 승인 권한을 주지 않는다.

trimap 계약 통과는 경계의 의미적 정확성을 증명하지 않는다. uncertain band와 전체 윤곽을
reference에서 독립적으로 검증한 뒤 새로운 비교 조건으로 고정해야 한다. 실제 자산 수정은
여전히 같은 조건의 일곱 Blender pass와 source-bound finding·paired comparison이 필요하다.

## 구조 수정 후 이전 quality source 보존

Material Closure는 이전 quality submission의 canonical alias와 receipt-owned immutable snapshot을
구분한다. `candidate_blend`, `authoring_blend`, `scene_spec`, `material_plan`의 역사적 alias만 정확한
material promotion receipt와 reentry snapshot의 hash·크기·bytes를 함께 확인한 후 closure 내부에서
해결한다. 이미 immutable snapshot 경로이면 그대로 유지한다. 같은 bytes를 가진 임의 복제본,
다른 round, 변조된 snapshot은 허용하지 않는다. 원본 submission·QA·receipt와 현재 canonical 파일은
수정하지 않으며, 이 호환성 처리는 새로운 승인이나 campaign 성공을 의미하지 않는다.

프로젝트는 `0.9.0`, canonical SceneSpec은 `0.2.0`이다. 이 기능은 reference 관찰과 실제 렌더를
연결하는 별도 계약이다. 기존 V0.6/IQ 점수, 인간 quality disposition, package acceptance 또는
Activation의 의미를 바꾸지 않는다. 구현과 실자산 입증 상태는
[검증 기록](../VERIFICATION_REFERENCE_FIDELITY_KO.md)을 함께 읽는다.

## 적용 범위

- Standard: 공통 관찰·저작·평가·비교를 advisory로 사용한다. 기존 `manual_guarded`, candidate review,
  exact geometry/material/QA/package 승인 경계가 canonical 변경을 통제한다.
- AQ: 새 autonomous Envelope 세션에만 `AQQualityRevisionLoopV01` 또는 additive
  `AQQualityRevisionLoopV02`를 초기 geometry 이전에 명시적으로 bind한다. 기존 세션,
  checkpointed/interactive 세션, 이미 종료된 세션은 자동 변환하지 않는다.
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
2. `StructureAuthoringV01`은 V03 loft/sweep 등의 strict recipe와 authored ModelingPlan을 연결한다.
   명시적인 MeshPayload 0.2 경로에서는 [triangulated_shell](triangulated_shell.md)로 연결된
   닫힌 삼각형 표면과 corner UV를 데이터로 저작할 수 있다. 직접 `custom_mesh` 제출,
   임의 코드 실행, legacy 0.1 materialization이나 과거 evidence 변환 권한은 추가하지 않는다.
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
   submission과 시각 평가를 비terminal로 기록한다. 신규 attempt는 IQ finding ID도 별도 prefix로 결속하며,
   이미 기록된 visual-only attempt의 경로는 소급 변경하지 않는다. 후속 회차에는 exact paired comparison이 필요하다.
6. V0.1 host는 시각·IQ 결함에서 더 엄격한 legacy route를 유지한다. V0.2의 `causal_v2`는 fixed-camera
   visibility를 source-bound 시각 finding의 정확한 route에 연결하고, chamfer가 이미 통과한 채 boundary
   F-score가 `meaningful_gain_min` 이내로 부족한 contour만 bounded parametric으로 분류한다. 큰 contour,
   시각적으로 확인된 구조 결함과 일반 semantic IQ 결함은 계속 structural이다. 시각 finding이 없으면
   visibility 부족을 구조 권한으로 추정하지 않고 evidence-required로 중단한다. 두 버전 모두 수정 계획·
   source snapshot·reservation을 먼저 게시하고 기존 controller/build/closure/atomic promotion/rollback을 재사용한다.
   `bounded_parametric_revision`의 eligibility는 canonical 변경 전 조건이다. host는 atomic promotion 직전에
   이를 다시 검사하고, 적용 뒤에는 이미 변경된 mutable alias에 같은 전조건을 재적용하지 않는다. 대신 exact
   geometry receipt, controller target, candidate SceneSpec과 현재 canonical ModelingPlan/SceneSpec/Blend가 모두
   일치하는 적용 후 조건으로 single-use decision을 검증한다. rejected/rolled-back/technical-failed 결과는 계속
   적용 전 canonical SHA 보존을 요구한다.
7. 관찰 조건과 현재 exact IQ가 모두 충족되면 `quality_ready`로 기존 source-freeze/delivery 경계에 돌아간다.
   이 상태가 인간 accepted 또는 production package를 의미하지는 않는다. 최종 IQ submission 교체도 거부한다.
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

V0.2는 `initial_pipeline_reserve`를 필수로 받아 최초 geometry materialization/build, material closure,
QA/IQ와 두 canonical promotion의 최소 비용을 명시한다. host는 이 reserve와 전체 revision `cost_limit`을
합산해 root builds/material rounds/quality/promotions 안에 모두 들어가는지 bind 전에 검사한다. 따라서
이론상 회차 수가 남아 있어도 실제 closure나 promotion 비용을 감당할 수 없는 loop는 첫 geometry 전에
fail closed한다. V0.1의 이미 발행된 예산 의미와 bytes는 그대로 유지한다.

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
primary/retry run ID에 `+2`를 묶는다. 과거 directional-wood 계약은 기존 의미로 계속 읽는다. 신규 자산의
구조 보정은 asset-neutral 계획 함수가 SceneSpec과 recursive geometry/material dependency closure를 함께
묶고, 전체 Python implementation fingerprint 및 Blender 5.0.1 executable hash도 포함한 scope SHA-256을
먼저 제시한다. 그 exact hash의 사용자 승인 뒤에만 동일 계약을 발행하며, 승인 뒤 source·nested payload·
구현·Blender 중 하나라도 바뀌면 실행 전에 fail closed한다. 첫 슬롯의 `DevelopmentPreviewAttemptOutcomeV01`이
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
| `aq-geometry-preflight JOB SESSION --modeling-plan PATH --scene-spec-v03 PATH [--structure-authoring PATH]` | `preflight_aq_geometry_authoring` | 제출 전 source/후보 계약과 실제 object 비용 검사 |

### Geometry authoring preflight 0.1

새 reference-fidelity 캠페인은 immutable controller 요청 전에 staging 후보를 검사한다.
`GeometryAuthoringPreflightV01`은 현재 AQ state, RootAuthorization, budget, reference/diagnostics,
기존 canonical source, 선택한 StructureAuthoring 및 두 후보의 exact hash를 결합한다.
QA role 누락·충돌·ModelingPlan 불일치와 material/source/geometry/camera 계약을 최종 host와 같은
검사로 확인한다. 실제 object별 materialization, candidate build, controller, promotion 비용은
기존 root/round reserve에 대조하며 보고서가 예산을 소비하거나 예약하지는 않는다.

CLI/MCP는 보고서를 반환할 뿐 파일이나 controller 요청을 만들지 않는다. CLI는 후보 오류 또는
예산 부족 보고서에도 JSON을 출력하고 exit 1을 반환한다. stale/hash/path/권한 문제는 별도 예외로
거절하며 후보 작성 오류로 재분류하지 않는다. 보고서는 shape·render·quality 통과 증거가 아니다.

캠페인 adapter는 보고서를 새 staging 파일로 보존하고 `geometry_authoring_preflight` kind의
artifact를 필수로 받는 `submit_preflighted_geometry_candidate_v2`를 사용한다. 이 host helper는
기존 desktop controller 경로를 호출한다. 요청 생성 직전에 보고서를 재계산하고 모든 dependency를
기존 read-only assignment 입력으로 결합하며, 두 output hash를 실제 후보에 고정한다.
resume은 기존 pending request와 그 입력·출력 hash를 재사용한다. 최종 host의 controller receipt,
source, geometry, Blender 및 atomic promotion 검증은 계속 필수다.

기존 request/profile/schema에는 companion을 자동 추가하지 않는다. 새로 제출된 후보의 데이터
계약 실패만 `CandidateContractInvalid`를 통해 `schema_serialization` 및
`job_local_candidate_error`로 종료한다. budget exhaustion은 별도 분류를 유지하고, 기존
terminal/history는 수정하지 않는다. 닫힌 session의 이름 변경·재제출·예산 환급 권한도 생기지 않는다.

회귀는 `test_aq_geometry_preflight.py`와 기존 후보/예산 검사에 있으며 두 AQ gate에 포함된다.
기존 Blender candidate smoke에는 preflight를 거치는 별도 실행을 추가했다. 이 검증은 캠페인의
실제 시각 개선이나 인간 beauty/package/Activation 수용과 별도로 보고한다.

경로는 job-relative contained path이며 exact 해시를 검사한다. MCP project allowlist는 controller phase
authority가 아니다. material closure의 이미 고정된 입력 multiset은 늘리지 않는다. 최신 스킬 변경은
과거 `skill_runs` snapshot을 바꾸지 않는다. 실제 CLI optional flag는 해당 `--help`가 소유한다.

## 현재 제한과 남은 입증

### 명시적 유한 funding epoch (2026-09-09)

새 실행은 host planner의 선택 인자 `fidelity_budget_plan`으로 `FidelityBudgetEpochV01`을 고정할 수 있다.
이때만 budget 0.3.0과 `AQQualityRevisionLoopV03` 또는 명시적 조명 companion V0.4를 함께 선택한다.
AQ state/RootAuthorization은 0.2.0,
SceneSpec은 0.2.0, 프로젝트는 0.9.0을 유지한다. 기존 budget/loop의 bytes와 기본 CLI/MCP 동작은
변경하지 않는다. 공개 budget reader는 정확한 0.2/0.3 버전을 dispatch하며 알 수 없는 버전은 거절한다.

AQ skill adapter도 같은 선택 인자를 One-Prompt host로 전달하고 새 session의 exact skill bundle을
함께 고정한다. CLI `aq-one-prompt-skill-plan --fidelity-budget-plan <JSON>`과 MCP
`plan_aq_one_prompt_skill(fidelity_budget_plan_path=...)`는 이 엄격한 proposal을 읽는다.
생략 시 기존 동작을 유지하며, 파일 자체가 자율 위임·experimental opt-in·인간 artifact 승인을 대체하지 않는다.

| 단계 | materialization | build | closure | QA/IQ 예산 | promotion |
|---|---:|---:|---:|---:|---:|
| 초기 저작 | 초기 object 상한 N | 3 | 1 | 3 | 2 |
| structural/parametric 1회 | 수정 object 상한 R | 3 | 1 | 3 | 2 |
| material 1회 | 0 | 2 | 1 | 3 | 1 |

build는 geometry build와 material graph compile/rebuild를 포함하며 전체 Blender 프로세스 수가 아니다.
closure 1회는 별도 preflight ledger의 Blender 6회(compile/build/inspect/validate/material inspect/neutral preview)를
뜻한다. 새 epoch는 전체 `6 × (1 + S + P + M)`회 한도를 하나의 session-wide `MaterialPreflightBudget`에
정확히 결속한다. 이 예산은 AQ build를 빌리지 않고, 승인·promotion·appearance·retry authority를 부여하지 않는다.
실패한 closure는 소비량을 보존하며 추가 무제한 retry를 만들지 않는다. QA/IQ 3은 정상 render 1,
IQ 1, 동일 입력의 실패 render에만 허용되는 retry 1이다. 성공한 render를 retry로 다시 실행하지 않는다.
structural S는 최대 3, parametric P와 material M은 합계 최대 2다. 총 build 한도는
`N + 3 + (S + P) × (R + 3) + 2M`이며 기존 Approval Envelope 상한 64 안에 들어야 한다.
R은 초기 N을 커버해야 한다. 최초 후보나 변경 전략의 실제 object 수가 예약보다 크면 policy/Blender 전에
거절한다. 후보를 단순히 자잘한 object로 늘리거나 구조 결함을 재질로 숨겨 비용 검사를 통과시키지 않는다.

계약은 같은 reference SHA의 모든 기존 AQ v2 session을 job 이름과 무관하게 읽고, 검증된 state/예약 chain,
session 및 closure JSON inventory digest, 별도 preflight 소비량, 관측·예약된 소비량을 함께 보존한다. 새 epoch는 과거 합계에 명시된 유한
분량을 더한다. 옛 terminal은 재개하지 않으며 새 이름만으로 epoch를 재사용하거나 active epoch와 병행할 수
없다. 계획 이후 과거 session이 추가·변경되면 active 실행은 다음 효과 전에 fail-closed한다.
같은 결함·전략이 두 번 정체되면 남은 경로 예산 안에서 한 번 전략을 바꾸고, 소진 시 best-known attempt와
remaining finding을 review evidence로 보존한다. 예약 뒤 crash는 exact ledger를 이어받고 중복 청구하지 않는다.

funding proposal은 승인이 아니다. 새 캠페인에서는 clean source manifest/baseline/readiness와 함께 exact
scope에 이 계약을 결속한 뒤 사용자 승인을 받아야 한다. 기존 campaign 실적이나 human beauty/package/
Activation acceptance를 새 budget으로 승계하지 않는다.

### 고정 카메라 비교 조명 companion (2026-09-19)

`AQQualityRevisionLoopV04`는 V0.3의 동일한 funding·reservation·receipt·정체 한도를 유지하면서
`comparison_lighting_profile="camera_studio_v1"`과 `lighting_implementation_sha256`을 필수로 고정한다.
V0.1–V0.3과 Standard의 기본 조명은 바꾸지 않는다. 기존 bind CLI/MCP는 exact loop JSON으로
선택하며 새로운 도구·shell·Blender Python·임의 광원 설정 권한을 추가하지 않는다.

조명은 고정 카메라 location·target에서만 유도한 중립 3개 area light와 world다. geometry bounding box를
사용하지 않으므로 형상 수정만으로 비교 조명이 달라지지 않는다. 카메라 거리의 제곱으로 광원 에너지를,
거리로 광원 크기를 정하며 candidate의 재질값이나 QA 점수로 조정하지 않는다. 선택은 초기 geometry 전
loop binding에서 고정하고, 구현 hash가 바뀌면 새 render 예약 전에 거절한다.

렌더 subprocess의 임시 scene에만 적용하고 canonical Blend를 저장하지 않는다. 실제 광원의 위치·방향·
에너지·크기·색, world, color management 및 구현 hash를 comparison conditions에 남긴다. host는
source-bound review 제출과 재검증에서 이 값을 카메라로 재산정해 검증한다. 이름만 동일한 profile,
다른 camera/회차의 조건, 누락된 기록, 바뀐 구현을 통과 근거로 사용하지 않는다.

이 companion은 조명 보정 효과나 재질 품질을 자동 통과시키지 않는다. 기존 조명과 새 조명 사이의 비교는
형상·재질의 전후 개선 쌍이 아니다. 새로운 조명을 선택한 비교에서는 BEFORE와 AFTER 양쪽을 같은 정책과
조건으로 실제 렌더해야 한다. 이미 성공한 렌더를 technical retry로 다시 실행할 수 없고, 닫힌 AQ terminal을
재개하거나 미소비 슬롯을 재사용할 수 없다. source 변경 뒤에는 새 clean baseline·유한 scope·exact 승인
경계를 지킨다. 검증용 합성 panel의 밝기 개선은 5자산 시각 개선이나 인간 수용으로 계산하지 않는다.

재질 closure의 새 회차는 명시적 0.2.0 source binding·graph rebinding plan·receipt를 사용할 수 있다.
기존 0.1.0 singleton binding은 그대로 읽으며 자동 변환하지 않는다. 나머지 closure 계약과 AQ v2,
SceneSpec 버전은 유지한다. 새 binding은 같은 session의 `bindings/<binding_id>/` 아래에서 source
AQ state, 예상 execution ID, 최신 geometry receipt와 필요한 최신 material promotion receipt를
고정한다. 관찰 snapshot과 source binding은 회차마다 새 경로를 사용한다. 재질 promotion으로 Blend가
달라졌다면 해당 host receipt·Blend snapshot·inventory·build provenance가 현재 canonical과 일치해야
한다. 이후 geometry가 다시 변경됐으면 과거 material receipt로 새 geometry를 덮어 설명할 수 없다.
회차 이름을 바꿔도 session-wide closure 예산과 AQ lifetime 사용량은 이어진다.

collector는 기존 plan profile과 엄격히 파생된 execution profile을 모두 검증한다. 파생 profile은 같은
session·단계·도구 권한을 유지하고, 선언된 output 경로에 해당 execution ID만 삽입해야 한다. Geometry
receipt의 controller request와 material completion의 예상 execution ID도 동일해야 한다. 새 회차의
receipt 혼합, stale source, 임의 경로·권한 확대는 Blender 전에 차단한다. controller 다음 상태에서는
이미 완료된 preflight를 이력으로 읽을 수 있지만, 새 실행·승인 검사는 현재 source state를 요구한다.

geometry 사전 검사에는 현재 canonical SceneSpec뿐 아니라 존재하는 `blender/scene.blend`의 exact
binding도 포함한다. 최초 저작의 파일 부재는 그대로 유지하며, 사전 검사 이후 Blend의 생성·변경·소실은
제출 또는 desktop resume에서 차단한다. 과거의 불완전한 immutable 요청을 보정하거나 재개하지 않는다.
구조 수정 빌드의 명시적 `scene_spec_only` provenance는 같은 모드로 재계산한다. 남아 있는 과거
MaterialPlan을 새 geometry Blend에 이미 적용된 재질로 해석하지 않는다. closure는 geometry-only
관찰과 최신 geometry receipt의 build payload·canonical Blend 일치를 추가로 요구하며, geometry 이후의
material promotion receipt를 geometry-only 관찰과 혼합할 수 없다. 알 수 없는 모드는 추론하지 않는다.
이 검사는 source의 기술적 일관성만 증명하며 visual finding이나 appearance authority를 대체하지 않는다.

후속 Material Closure 0.2는 exact reentry의 이전 QualitySubmission을 변경하지 않고 읽는다. 그 제출의
canonical Blend alias는 같은 attempt·material receipt·reserved source snapshot의 bytes가 모두 일치할 때만
보관 snapshot으로 수집하며, 현재 canonical Blend도 별도 exact input으로 유지한다. VisualFindingSet에
결속된 일곱 render는 PNG bytes로 검증한다. 다른 임의 파일에 JSON 검사를 생략하거나 다른 회차의
snapshot을 대신 적용하지 않는다. 최초 회차와 기존 0.1 source binding의 의미는 유지한다.

재질 controller의 권한 소비 receipt는 host가 session lock 아래에서 exact request에 결속하고,
executor의 protected inventory를 만들기 전에 기록한다. controller callback은 선언된 staging
출력만 작성한다. Windows 확장 경로에서 host 경로를 역으로 추론하거나 controller 내부에서
receipt를 기록하지 않는다. desktop 대기와 출력 adoption은 같은 request·권한·예산을 재사용한다.
promotion은 source → waiting → completed의 정확한 state/receipt chain도 검증하며, 다른 request나
추가 회차를 섞지 않는다. controller 실패 뒤에는 기존 consumption과 실제 failed result를 반환하고
terminal 상태에서 권한을 다시 발행하지 않는다. 공개 CLI/MCP/schema와 기존 terminal 의미는 유지한다.

- typed observation/coverage와 source-bound nonhuman visual review가 구현된 것이며, arbitrary reference에서
  depth·landmark·part pose를 자동 복원하거나 자동 정답 판별하는 모델이 추가된 것은 아니다.
- camera 기본 가설은 측정이라고 표시하지 않는다. 자동 calibration/re-render-both 실행 경로는 아직 없다.
- 추가 시점 artifact는 consistency-only로 읽는다. required IQ landmark/multiview를 flag만 켜서 통과시키지 않는다.
- 실제 개발 목재 preview는 AQ root/policy loop 실행 증거가 아니다. 별도 고정 fixture에서 실제 Blender
  multi-round geometry/material/quality/structural-policy-reentry vertical은 통과했지만, fixture의
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
`test_aq_structural_closure_blender.py`는 canonical Blend 사전 결속, 실제 구조 promotion, 과거 QA와
현재 geometry를 포함한 full closure의 연결을 검증한다. 별도 closure Blender 예산, 정확한 resume,
stale snapshot/render와 mixed source 거절, 원본 파일 불변성도 같은 격리 fixture에서 검사한다.
Windows의 깊은 dependency 경로는 collector의 strict resolution과 파일 읽기에도 native I/O 경로를
사용한다. closure에는 기존 상대 경로만 기록하며 containment, link 거절과 정확한 byte 검증을 유지한다.
Blender의 고정 MaterialGraph compiler도 같은 native 경로 원칙을 사용해 긴 shadow 출력의 재조회와
artifact hash 수집을 지원한다. node whitelist와 상대 경로 report 계약은 그대로 유지한다.
Neutral swatch의 실제 저장과 shadow report/preview manifest 읽기에도 native I/O를 사용한다.
PNG decode·크기·해시 및 기존 renderer snapshot 검증은 유지한다.
Approval Envelope 회귀는 parametric controller 전조건이 atomic promotion으로 정상 소모된 뒤에는 exact
geometry receipt/current-canonical 적용 후 조건으로 전환되는지, 일반 authorization replay는 계속 stale로
차단되는지를 별도로 검사한다.
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

### 유한 캠페인 사전 위임 (2026-09-28)

사용자가 반복 scope 승인을 사전 위임으로 바꾸도록 명시했다. 선택적
`FidelityCampaignDelegationV01`의 exact hash를 한 번 확정한 뒤, 승인된 후보 수·
자산별 구조 3/local 2/전략 교체 1 한도·전체 비용 안의 후속 scope, 데이터 준비·수정,
렌더·QA·promotion·portable package 생성·clean import는 host policy로 자동 처리한다.
후속 scope마다 사용자 승인을 다시 요청하지 않는다. `AutonomyBudgetV04`가 이 부모
예약을 native AQ budget에 결속한다. 과거 V0.3 계약·소비·증거는 수정하지 않는다.

[계약 및 실제 검증 경로](fidelity_campaign_delegation.md)에 예약, crash/resume,
동일 reference 이름 변경 우회 차단, 고정 관찰, canary와 인간 판정 분리 규칙을 명시한다.
source가 바뀌면 새 baseline을 사용하며 과거 성공을 새 캠페인의 성공으로 재분류하지 않는다.
이 절은 사전 위임을 선택한 새 작업에 적용한다. 위의 날짜별 기존 exact scope 승인 기록과
legacy 승인 경로는 그 당시 의미를 그대로 보존한다.
