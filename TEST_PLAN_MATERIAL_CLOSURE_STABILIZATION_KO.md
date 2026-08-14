# AQ v2 Material Closure Stabilization 0.1.0 테스트 계획

## 1. 판정 언어

Contract-only, host-tested, actual Blender 5.0.1, historical incident dry-run, user-approved
promotion과 destination parity를 분리한다. 실행하지 않은 항목은 `unverified`다.

## 2. contract와 collector

- 요청된 strict 0.1.0 contract schema parity와 unknown-field 거부
- normalized relative POSIX path, exact hash, identity/session 결속
- recursive ShaderRecipe/TextureManifest/channel/reference/mask 수집
- duplicate/conflicting path, case collision, link/escape, stale/missing bytes 거부
- material/object/UV/surface-detail mismatch 거부
- closure entry/order/input SHA 결정성
- request/assignment/completion/closure immutable projection equality
- reduced completion map 거부
- source binding → rebind plan/receipt/derivative → final closure 순서의 순환 dependency 부재
- existing canonical MaterialPlan observation과 byte-identical run-owned snapshot의 쌍 검증
- canonical MaterialPlan absence의 current state/SceneSpec/Blend/parent fingerprint 검증
- procedural/manual-image/ImageGen source mode별 필수 root와 cross-chain identity 검증

## 3. graph rebinding과 approval impact

- canonical SceneSpec와 request-owned MaterialPlan path/hash만 파생
- layer/channel/mask/material ID/shader 값 변경 거부
- source graph 불변과 derivative exact receipt
- path-only change는 `no_visual_change`
- texture, UV placement, shader parameter change는 `appearance_change`
- object/material/reference/scope change는 `scope_change`
- 동일 bytes/preview approval 반복 생성 금지와 stale approval 거부

## 4. preflight와 실패 경계

성공 fixture:

- procedural metal/plastic
- ImageGen 또는 deterministic image + localized detail
- crystal + emission + alpha

승인 전에 차단할 fixture:

- missing ShaderRecipe/TextureManifest/channel/reference/mask
- stale graph provenance
- UV mapping/placement conflict
- missing surface-detail coverage
- exhausted preflight/controller/promotion budget
- missing rollback baseline

실패 assertion은 approval 0, controller invocation 0, canonical promotion 0, exact failure
report 존재, canonical unchanged다.

## 5. Blender 5.0.1

별도 opt-in gate에서 actual Blender 5.0.1로 graph compile, full-scene shadow build,
inspect/validate, assignment/UV/node inventory와 neutral preview를 실행한다. fake ImageGen은
actual built-in ImageGen 품질 검증이 아니다.

## 6. promotion과 rollback

정상 fixture는 material approval/controller invocation/canonical promotion이 각각 1회이고
rollback 0, real `MaterialPhaseReceiptV2`, IQ boundary를 요구한다. 강제 post-promotion Blender
실패는 exact MaterialPlan-or-absence, Blend/inventory/validation/build provenance 복구,
rollback receipt와 `MaterialAttemptState=rollback_completed`, IQ 미진입을 검증한다.

Controller integration fixture는 fixed exact-adoption controller가 실제 `ControllerExecutor`
isolation에서 request-owned MaterialPlan/graph/completion만 만들고, request map == assignment map
== completion map == closure projection을 만족하는지 확인한다. caller-authored ControllerResult나
canonical direct write fixture로 이를 대체하지 않는다.

## 7. incident와 호환성

- 기존 Crystalgun session은 읽기 전용으로 재검증
- state `0011` 보고와 실제 terminal head 차이를 discrepancy report로 결속
- 승인된 MCD retry와 미승인 MGB plan을 별도로 supersede
- 기존 geometry hash 재사용 dry-run은 canonical write 0
- standard/background/AQ v1/AQ v2/ImageGen/V0.7~V0.9 회귀
- known incident literal gate는 source/schema/common prompt만 검사하고 tests/incident docs를
  명시적으로 제외

## 7A. acceptance matrix

| fixture | approval | controller | promotion | rollback | 핵심 판정 |
|---|---:|---:|---:|---:|---|
| procedural metal/plastic 성공 | 1 | 1 | 1 | 0 | ShaderRecipe/manifest 전체 closure, receipt, IQ boundary |
| image + localized detail 성공 | 1 | 1 | 1 | 0 | image/mask/reference/UV/coverage current |
| crystal/emission/alpha 성공 | 1 | 1 | 1 | 0 | emission/opacity graph와 portable limitation 보존 |
| dependency/UV/preflight 실패 | 0 | 0 | 0 | 0 | strict failure + framework report, canonical unchanged |
| post-promotion Blender 실패 | 1 | 1 | 1 attempt | 1 | exact baseline 복구, consistency true, IQ 미진입 |
| current incident dry-run | 0 | 0 | 0 | 0 | 새 repair session, approval 전 strict pass 또는 strict blocked |

성공 assertion의 `1`은 실제 사용자가 current candidate에 내린 specialized decision을 exact하게
관찰한 authorized run에서만 충족된다. Test code가 user identity나 approval bytes를 합성한 흐름은
성공 판정으로 인정하지 않는다. 실제 incident 행에는 current user approval이 없으므로 성공
promotion과 분리한다.

## 7B. public/compatibility matrix

- CLI 12개와 MCP 12개의 parameter/return schema 및 capability/catalog 동등성
- public surface가 arbitrary output path, approval 합성, ControllerResult 합성, canonical/destination
  direct write를 거부
- 기존 standard, background_exterior, AQ v1, AQ v2 raw state, ImageGen Material Loop와
  V0.7/V0.8/V0.9 evidence loader 의미 보존
- 두 experimental profile이 `disabled_experimental`인지 확인

## 8. 실행 순서

1. `uv sync --frozen --extra dev --extra vision`
2. contract/collector/projector/rebinding/preflight focused pytest
3. job-specific literal checker
4. schema generator와 parity
5. Ruff, 전체 pytest, doctor, blender-compat, instruction checker
6. AQ/ImageGen focused gates
7. actual Blender fixture와 Crystalgun dry-run
8. 가능한 V0.7~V0.9 chained gate
9. repository projection generator와 `git diff --check`

각 단계의 명령, timestamp, exit code와 count는 검증 문서에 실제 실행 후에만 옮긴다. focused
fixture 통과를 실제 자산, built-in ImageGen, human review, accepted package 또는 destination parity로
확대 해석하지 않는다.

2026-08-14 현재 actual result는 별도
[검증 기록](VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)을 따른다. 특히 current incident는
coverage 검사에서 `preflight_failed`로 멈췄고 Blender/preview/approval/controller/promotion은
실행되지 않았다. 이 결과는 본 계획의 authorized success 및 chained V0.7–V0.9 항목을 충족하지
않는다.

## 11. scope-change companion 회귀

공유 material identity 때문에 localized detail ownership이 닫히지 않는 경우 Material Closure가
빈 binding이나 느슨한 사용자 승인으로 통과하지 않는지 검증한다. 별도 Material Identity Split
suite는 paired SceneSpec/ModelingPlan exact diff, semantic clone, target-object exclusivity, 실제 Blender
승인 전 shadow, specialized root-scope approval, single-use apply, crash recovery와 post-apply stale
authority refresh를 검증한다. 이 suite의 synthetic approval은 mechanism-only이며 실제 자산 approval로
재사용하지 않는다.
