# Codex ImageGen 0.2 Material Loop 테스트 계획

> 이 문서는 검증 항목을 정의한다. 실행하지 않은 명령을 pass로 기록하지 않으며 실제 결과는
> [검증 기록](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)에만 남긴다.

## 1. 판정 기준

- Project `0.9.0`, canonical SceneSpec `0.2.0` 유지
- 두 v2 profile은 `disabled_experimental` 유지
- fake, historical actual source reuse, current-task non-human review와 human review를 분리
- host-only, Blender 5.0.1, package acceptance와 destination parity를 분리
- 기존 MaterialAuthoring `0.2.1` `not_run` receipt bytes 불변
- synthetic approval을 실제 사용자 승인으로 기록하지 않음

## 2. strict contract와 schema

모든 신규 model에 대해 checked-in Draft 2020-12 schema parity, `extra=forbid`, non-finite 거부,
exact version dispatch와 roundtrip을 검사한다. negative fixture는 다음을 포함한다.

- wrong job/workflow/dispatch/session/profile identity
- stale input digest, source fingerprint, SHA-256 또는 byte size
- absolute/backslash/escaped/link/reparse path
- duplicate ID, path, candidate, dependency 또는 transition
- unknown version과 legacy evidence의 묵시적 promotion
- controller input, bridge, binding, preview, promotion, state와 terminal envelope mismatch
- canonical MaterialPlan baseline과 exact absence evidence의 충돌

## 3. native adoption과 normalization

- native source fresh decode/hash와 allowed-root containment
- original bytes 보존, overwrite와 pre-existing mismatch 거부
- pass-through, center crop, contain-pad, tile crop
- requested operation, source/target aspect, crop/padding, resampler, colorspace/alpha 기록
- silent stretch와 허용 밖 aspect ratio 거부 또는 `review_required`
- output/receipt 사이 crash adoption과 tamper 거부
- 1254×1254 native → immutable original → 64×64 normalized → 기존 core completion 연결
- native-original normalization receipt의 exact adoption-receipt 결속과 recursive replay
- 누락, 다른 assignment/original 결속과 adoption/normalization tamper 거부
- `CodexImageNativeCorePreparationReceipt`의 adoption/original/normalization부터
  completion/candidate/generated-image/quality/selection까지 full closure
- normalized image와 copied core generated image의 exact byte identity, candidate/ordinal/role/target-size 검증
- native-fed selection의 preparation receipt 누락/orphan/mismatch 거부와 legacy non-native absence 허용
- core contract가 수정되지 않았다는 receipt 불변값 검증
- 과거 selection에 post-hoc derivative를 소급 결속하는 시도 거부

## 4. semantic review와 selection

- 12개 canonical semantic category의 exact order와 aggregate outcome 재계산
- `human_reviewed=false`, `observed_reference_truth=false` 불변
- forbidden text/object/boundary만 제한된 hard failure 가능
- family/role, wood grain, decal, emissive/crystal, tile, hotspot, perspective 관찰
- unavailable/advisory를 deterministic pass로 변환하지 않음
- single-candidate core behavior 회귀
- multi-candidate마다 exact semantic review와 ranking evidence 필수
- 누락 또는 unresolved 후보 하나라도 있으면 전체 `review_required`
- file hard gate → deterministic quality → semantic → role → repair cost → stable ID 순서
- 가장 높은 deterministic score가 hard-fail이면 다음 eligible 후보 선택
- stale candidate/report/review/ranking/core-selection binding 거부
- 다중 후보 companion selection receipt가 bridge/controller/promotion까지 동일하게 결속되는지 확인
- 다중 후보의 receipt 누락과 single-candidate의 companion receipt 가장 거부

## 5. bridge와 ControllerExecutor

- adopted staging chain에서 exact bridge/controller input/state 게시
- AQ authorization/plan/profile/budget/state와 SceneSpec/geometry/build fresh rehash
- ImageGen, native adoption/normalization/core preparation, semantic, MaterialAuthoring, V0.5
  companion 전체 closure
- output root 아래 정확히 `material_plan.json`, `material_graph.json`, `completion.json`
- extra/missing/empty/escaped output, wrong producer와 handwritten result 거부
- `controller_authored_completion` same-request waiting/resume
- `exact_adoption` expected output hash와 exact V0.5 preflight receipt 필수
- exact MaterialPlan/MaterialGraph/dependency bytes를 isolated shadow로 복사해 실제 Blender compile
- shadow compile report와 정확히 여덟 compiler artifact의 path/hash/identity recursive replay
- preflight의 idempotent adoption과 input/report/artifact tamper 거부
- preflight가 `ControllerResult`, canonical write 또는 destination write를 만들지 않음
- 원래 staging-only/`blender_compilation_status=not_run` V0.5 receipt bytes와 의미가 그대로 유지됨
- preflight 없는 exact-adoption과 authored-completion의 preflight 가장 거부
- partial result, completed result와 lifecycle receipt crash recovery
- protected source mutation, duplicate invocation와 budget 재소비 거부

## 6. host material promotion과 preview

- 기존 `validate_and_promote_material_controller_result_v2` 실제 호출
- MaterialGraph whitelist compile과 dependency/normalized inventory 재검증
- material/semantic ID scope, color space, UV/texel density, OpenGL normal과 channel source 결속
- canonical MaterialPlan compare-and-swap, archive, Blender rebuild/inspect/validate
- actual `MaterialPhaseReceiptV2`와 promotion companion exact binding
- fixed neutral preview 설정과 render hash; compiler `rendered=false` 오인 거부
- compile/build/CAS 실패와 rollback, rollback failure evidence
- pre-write failure terminal과 post-write rollback 구분
- 동일 promotion receipt idempotent adoption과 duplicate promotion 차단

## 7. state, recovery와 IQ

- `controller_promotion_required → promoting_material → material_promoted → waiting_for_quality`
- passed IQ만 `quality_approved`; non-pass는 `review_required|blocked|failed|cancelled`
- base AQ `material_candidate_validated → run_integrated_quality`
- overlay/base predecessor, sequence, provenance delta와 monotonic budget 재구성
- status의 exact controller request/result, delivery progress와 remaining budget
- promotion/state, base-state/terminal, IQ/companion-terminal 사이 crash recovery
- actual current `MaterialPhaseReceiptV2`, preview, generated/derived evidence 필수
- host-recomputed IQ gate와 forged/stale receipt/freeze 거부
- `needs_revision|unscorable` review evidence와 blocked freeze 금지
- base quality terminal이 먼저 게시된 뒤 public continue 재호출의 idempotent companion 복구

## 8. delivery

- `review_only`는 package가 아닌 terminal
- 같은 quality freeze에서 GLB/FBX 독립 V0.7 review 생성
- exact OptimizationApproval이 없으면 `waiting_for_v07_approval`
- approval 없이 production `package_asset` 호출 거부
- raw exporter → Blender clean import → geometry/material survival은 test-only mechanism으로 분리
- mechanism root에 package manifest, production-ready result 또는 delivery terminal을 만들지 않음
- GLB를 FBX source로, FBX를 GLB source로 쓰지 않음
- format별 material loss, normal/UV/material identity 확인
- destination write와 runtime parity는 항상 별도 `false`/`unverified`

## 9. 실제 Blender 5.0.1 fixture

fake source 네 family를 각각 실행한다.

- `wood`
- `signage_decal`
- `emissive`
- `crystal`

각 family에서 실제 host promotion, actual `MaterialPhaseReceiptV2`, fixed preview와 IQ 경계를
검사한다. delivery fixture는 quality-approved source에서 V0.7 review까지 진행한 뒤 승인이 없어
`waiting_for_v07_approval`인지 확인한다. 이어 별도 test-only raw exporter로 GLB/FBX를 각각 만들고
fresh Blender clean import를 실행한다. 후자는 mechanism evidence일 뿐 approval/package/terminal
성공으로 합산하지 않는다.

별도 `review_only` fixture는 package 없는 종료만 검증한다.

## 10. historical actual source fixture

보존된 actual source SHA-256
`82ce3d6efc85cef6aa3e166f007f0509c97dc698b378ffd7e7262eb1cc33372f`를 새 unique run의 native input으로
채택한다. 과거 completion, selection, MaterialAuthoring receipt나 overlay state를 migration하지
않는다.

검사 범위:

- immutable native adoption과 normalization
- current-task non-human semantic observation
- semantic outcome `review_required`
- canonical MaterialPlan baseline 불변
- promotion, IQ, package와 terminal이 생성되지 않음

이 fixture는 fresh ImageGen invocation도, human review도 아니다.

## 11. 보안과 public surface

- codex_imagegen package의 OpenAI SDK, requests/httpx/aiohttp/socket/urllib와 endpoint literal 부재
- API key/credential/environment-variable 요구 부재
- CLI 9개와 MCP 9개의 name/signature/registry/config parity
- opt-in required mutation, read-only status semantics
- native-normalize `adopt|prepare|execute` public dispatch
- exact-adoption-preflight가 actual Blender shadow compile만 수행하고 controller/canonical/destination
  authority를 노출하지 않는지 확인
- semantic status가 observation을 작성하지 않는지 확인
- public surface가 approval, canonical direct write나 destination write를 노출하지 않는지 확인

## 12. 회귀와 최종 gate

작은 focused test부터 다음 순서로 실행한다.

```powershell
uv sync --frozen --extra dev --extra vision
uv run ruff check .
uv run pytest <material-loop-focused-files>
uv run pytest
uv run cbm doctor
uv run cbm blender-compat
uv run python scripts/check_agent_instructions.py
uv run python scripts/generate_repository_summary.py --check
git diff --check
```

추가로 관련 AQ v2 host/Blender gate, ImageGen core/fake Blender gate와 V0.7~V0.9 chained regression을
실행한다. Windows path assertion이 필요한 test는 충분히 짧은 격리 `--basetemp`를 사용하되 실제
장경로 code path는 전용 fixture로 별도 검증한다.

## 13. 완료 판정

최종 판정은 다음을 모두 구분해 기록해야 한다.

- host contract passed
- actual Blender 5.0.1 passed
- fake family 결과
- historical actual source의 review boundary
- review-only 결과
- approval 없는 raw delivery mechanism 결과
- full repository/legacy gate 결과
- human review, production approval, package acceptance와 destination parity의 미검증 상태

fixture 통과만으로 profile을 활성화하지 않는다.
