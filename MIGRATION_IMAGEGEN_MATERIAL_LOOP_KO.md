# Codex ImageGen 0.2 Material Loop 마이그레이션 정책

## 1. 불변 기준선

Material Loop는 기존 artifact를 제자리에서 업그레이드하는 migration이 아니다.

- Project `0.9.0`, canonical SceneSpec `0.2.0` 유지
- ImageGen core `0.1.0`, ImageToMaterialAdoption `0.2.0`, MaterialAuthoring `0.2.1` 의미 유지
- 기존 V0.4~V0.9, AQ 0.1/AQ v2 evidence 읽기 의미 유지
- 두 v2 profile 모두 `disabled_experimental`
- blocked, failed, cancelled, waiting 또는 과거 completed 기록을 재분류하지 않음

## 2. 새 companion 선택

새 material-loop session은 exact profile/session binding과 두 explicit opt-in을 사용한다. 기존
ImageGen overlay status를 문서나 수동 JSON 편집으로 material-loop state로 바꾸지 않는다. bridge는
현재 source closure에서 새 plan/controller input/initial state를 게시한다.

## 3. 과거 ImageGen evidence

과거 completion, selection, terminal, adoption, MaterialAuthoring receipt와 overlay state는 immutable
history다. 새 run은 필요한 artifact를 exact input으로 참조할 수 있지만 과거 state를 현재 state로
복사하거나 수정하지 않는다.

보존된 actual PNG를 재사용할 때는 다음을 따른다.

1. 원본 bytes를 새 unique native-output adoption receipt에 결속한다.
2. 필요하면 그 adoption receipt를 재귀적으로 결속하는 새 normalization plan/receipt를 만든다.
3. normalized bytes를 처음부터 새 core assignment 후보로 사용한다.
4. core completion/selection 뒤 새 `CodexImageNativeCorePreparationReceipt 0.1.0`으로 normalized-to-core exact
   byte identity와 전체 artifact chain을 결속한다.
5. current-task semantic review와 ranking을 새로 기록한다.

이 과정은 fresh ImageGen invocation이 아니며 과거 completion/selection을 normalized derivative에
소급 적용하지 않는다.

## 4. native-size mismatch 처리

기존 core `0.1.0` exact dimension 규칙을 완화하지 않는다. 크기가 다른 native output은 immutable
`original.png`로 보존하고 새 additive plan/receipt로 deterministic derivative를 만든다. silent
stretch나 이미 선택된 source의 in-place resize는 금지한다. 허용되지 않는 aspect policy는
`review_required`로 남긴다.

native-fed core selection은 bridge 전에 canonical preparation receipt를 요구한다. 과거 core contract나
selection JSON에 새 필드를 삽입하지 않고 additive receipt가 assignment, adoption/original,
normalization, completion/candidate/quality/selection을 결속한다. native 경로가 아닌 legacy selection은
receipt 부재만으로 migration 대상이나 실패로 재분류하지 않는다.

## 5. MaterialAuthoring와 V0.5

기존 MaterialAuthoring `0.2.1` request/manifest/receipt와 texture bytes는 수정하지 않는다. 특히
`staging_only=true`, `canonical_v05_unchanged=true`,
`blender_compilation_status=not_run`을 actual compile pass로 바꾸지 않는다. 새 normalized companion,
V0.5 bridge, exact-adoption Blender shadow preflight와 host compile/preview evidence는 각각 별도 immutable
artifact로 추가한다. preflight는 원래 receipt를 수정하거나 `ControllerResult`/canonical write를
만들지 않는다.

canonical MaterialPlan이 없으면 그 부재를 exact `CodexImageV05CanonicalMaterialAbsence` evidence로
기록한다. 존재/부재 baseline이 바뀌면 기존 bridge는 stale이며 새 bridge가 필요하다.

## 6. selection과 semantic evidence

single-candidate core selection의 기존 의미는 유지한다. 후보가 둘 이상인 새 companion run은 모든
후보에 current-task semantic review와 exact ranking evidence를 요구한다. 일부 후보의 evidence가
없는 과거 run을 임의 default score로 채우지 않고 `review_required`로 멈춘다.

새 다중 후보 selection receipt는 bridge plan, controller input과 promotion receipt에 동일하게
결속한다. 과거 selection에 receipt를 합성하거나, 다중 후보 receipt를 single-candidate legacy
selection의 증거로 재사용하지 않는다.

non-human semantic observation은 사람 검토로 변환되지 않는다. 과거 deterministic `passed`도 새
semantic pass로 자동 승격하지 않는다.

## 7. controller와 promotion

staging evidence를 `exact_adoption`으로 자동 선택하지 않는다. 원래 `staging_only`/compile
`not_run` 의미는 보존한 채 exact candidate bytes의 별도
`CodexImageV05ExactAdoptionPreflightReceipt`가 실제 Blender shadow compile을 통과한 경우에만
`exact_adoption` bridge에 결속할 수 있다. 이 receipt가 없으면 `controller_authored_completion`을
사용하거나 required evidence가 마련될 때까지 멈춘다.

ControllerExecutionRequest/Result는 기존 ControllerExecutor contract를 사용한다. handwritten/fake
result를 production evidence로 가져오지 않는다. actual `MaterialPhaseReceiptV2`가 없으면 base AQ를
IQ로 진행할 수 없다. canonical promotion은 host material phase service만 수행하며 conflict 또는
failure는 기존 rollback receipt를 사용한다.

## 8. state와 recovery

overlay, material-loop와 base AQ state는 별도 append-only chain이다. recovery는 missing publication을
동일 exact predecessor와 bytes로 adopt할 수 있지만 history를 고치지 않는다. SceneSpec, MaterialPlan,
UV, generated source, native core-preparation receipt, authorization, controller input 또는 predecessor가 바뀌면 기존 plan/state는
stale다.

과거 `completed_companion` 표현을 새 terminal로 재작성하지 않는다. 현행 새 terminal은 IQ pass에
`quality_approved`를 사용하며 material promotion만 끝난 상태와 구분한다.

## 9. IQ와 delivery

새 companion도 기존 QualityApprovedSourceFreeze와 DeliveryProfile contract를 그대로 사용한다.
review-only는 package가 아니고 GLB/FBX는 각각 exact V0.7 approval이 필요하다. 승인 없는 raw
export/clean-import test evidence를 package manifest, accepted delivery 또는 production terminal로
migration하지 않는다.

generic AQ authorization, test fixture 또는 과거 approval을 새 optimization plan hash의 사용자
승인으로 바꾸지 않는다.

## 10. public surface와 rollback

기존 ImageGen core 5개 CLI/MCP는 유지하고 Material Loop 9개 CLI/MCP를 additive하게 추가한다. 아홉
번째 표면은 `codex-imagegen-material-exact-adoption-preflight` /
`preflight_codex_imagegen_material_exact_adoption`이며 isolated Blender shadow compile만 수행한다.
기존 이름, 인자와 response 의미를 제거하거나 rename하지 않는다. registry/config와 schema는 exact
version으로 dispatch한다.

소스 rollback 요청이 있으면 이번 companion의 source/schema/tests/docs/registry 변경을 정확히
되돌리되 사용자 workspace와 immutable evidence는 삭제하거나 재작성하지 않는다. harmless logs와
staging은 실제 충돌·민감정보·용량 문제가 있을 때만 exact 영향과 권한을 설명한 뒤 처리한다.

## 11. 활성화 정책

코드, fixture, documentation 또는 한 번의 actual source reuse는 activation migration이 아니다.
별도 실제 reference corpus, 사람 평가, supporting-client/App Server execution, 장기 반복과 destination
runtime evidence 없이는 profile을 `verified_active`로 바꾸지 않는다.
