# Codex Built-in ImageGen Texture Provider 0.1.0 테스트 계획

> 이 문서는 검증 범위와 판정 기준을 정의한다. 실제 명령, 환경, 수치와 산출물은 실행 후에만
> `VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md`에 기록한다. fake, host-only, Blender와 실제
> Codex 내장 ImageGen 결과를 서로 대체하지 않는다.

## 1. 기준선과 회귀

- `git status --short`
- `uv sync --frozen --extra dev --extra vision`
- `uv run ruff check .`
- `uv run pytest`
- `uv run cbm doctor`
- `uv run cbm blender-compat`
- `uv run python scripts/check_agent_instructions.py`
- `uv run python scripts/generate_repository_summary.py --check`
- `scripts/run_autonomous_quality_gates.ps1` 또는
  `scripts/run_autonomous_quality_gates.sh`
- relevant Blender, V0.7, V0.8, V0.9 gates
- `git diff --check`

기준선 실패와 신규 실패를 분리한다. Blender runner, 실제 Codex tool 또는 destination runtime이
없으면 `unavailable`/`not_run`으로 남기고 pass로 기록하지 않는다.

기존 AQ gate가 다음 host-contract test를 포함하는지 검사한다. 별도의 평행 gate나 CI job을
만들지 않는다.

- `tests/test_codex_imagegen_core.py`
- `tests/test_codex_imagegen_security.py`
- `tests/test_codex_imagegen_schemas.py`
- `tests/test_autonomy_v2_codex_image_planner.py`
- `tests/test_autonomy_v2_codex_image_overlay.py`
- `tests/test_autonomy_v2_codex_image_phase_service.py`
- `tests/test_codex_image_material_authoring_v021.py`
- `tests/test_codex_imagegen_public_surface.py`

CI에서는 `.github/workflows/python-ci.yml`의 기존 `Run AQ 0.2 host contracts` step이 위 8개
파일을 실행하는지 확인한다. 실제 Codex 내장 ImageGen은 CI에서 호출하지 않는다.

## 2. schema와 strict contract

- core `0.1.0` 10종 schema와 checked-in JSON Schema parity
- `ImageToMaterialAdoption 0.2.0` parity
- MaterialAuthoring `0.2.1` companion model round trip
- unknown field, coercion, non-finite number 거부
- normalized repository-relative POSIX path와 exact SHA-256
- duplicate path/artifact/provenance/ID 거부
- session/workflow/dispatch/profile/provider identity splice 거부
- legacy V0.4~V0.9, AQ 0.1/0.2 evidence가 자동 migration되지 않음

## 3. provider 보안과 금지 의존성

- profile은 기본 `disabled_experimental`
- 두 explicit opt-in 없이 planner 거부
- `OPENAI_API_KEY`, OpenAI SDK, image API client, HTTP endpoint/URL dependency 부재
- repository task spawning, daemon, app-exit continuation claim 부재
- project MCP allowlist에 image API/network tool을 추가하지 않음
- provider/candidate/completion이 canonical material 또는 destination write 권한을 갖지 않음
- direct output role은 `base_color`, `decal_rgb`, `emission`, `opacity_source`만 허용
- generated normal/roughness/metallic/height/displacement/AO/tangent vector 직접 채택 거부

소스 문자열 검사는 false positive를 피하면서 실행 가능한 API/SDK/credential path가 없는지
확인한다. Codex-managed built-in tool과 repository MCP/network authority를 같은 것으로 취급하지
않는다.

## 4. assignment와 보호 inventory

- plan item, profile, immutable budget, base state, reference image exact binding
- exact signage text가 provider prompt에 포함되면 거부
- prompt UTF-8 SHA-256과 assignment self digest 검증
- candidate 수, quality tier, raster size와 aspect ratio 상한
- canonical staging path와 candidate filename 고정
- session overlay subtree만 제외한 protected job inventory hash
- assignment 이후 canonical/input/evidence 변경 시 completion 전에 fail-closed
- path escape, link, reparse point, special file, extra output 거부

## 5. ControllerExecutor lifecycle

- dedicated `codex_imagegen` phase profile과 exact input roles
- `allowed_tools=[imagegen]` controller capability와 repository MCP allowlist 분리
- execution-owned input snapshot, output map와 receipt inventory
- desktop 첫 호출 no-output → `waiting_for_output`
- waiting 재호출에서 request/workspace/invocation/budget 중복 없음
- 현재 task가 exact output을 채운 뒤 same-request resume/adoption
- request/result/profile/started/invocation/completed/published receipt 전체 replay
- partial, empty, extra, wrong hash, stale output와 duplicate completion 거부
- timeout/failure/cancel과 retry 권한을 구분
- app 종료를 background automation이나 완료로 해석하지 않음

## 6. budget과 terminal

- total generation 4, candidate 3, refinement 1, assignment당 generation 3
- draft 1024, final 2048, assignment/total elapsed cap
- started generation 이후 reconstructed usage와 double-spend 방지
- waiting 상태 재검사 시 budget 불변
- 자동 budget 확대·새 assignment·새 generation 금지
- `adopted`, local fallback, review, user image, failed, cancelled terminal
- terminal에도 모든 candidate와 quality report가 남음
- capacity/size/elapsed 거부는 controller 호출 없이 plan item의 exact fallback으로 terminalize
- final `timeout|failed|rejected`는 plan fallback, `cancelled`는 cancellation, waiting은 재개 유지
- terminal의 plan item/runtime trigger/controller request/result exact binding과 선게시 crash adoption
- tampered terminal 거부, fallback 재호출·generation budget 이중 소비 없음

## 7. completion·candidate·selection

- PNG decode, format, dimension, alpha와 prompt echo
- completion의 controller kind/execution/source kind 정직성
- fake와 built-in completion 교차 위조 거부
- candidate가 assignment/completion/controller request/controller result를 exact bind
- candidate 최대 3개, deterministic single selection
- selected/rejected/ineligible decision이 모든 후보를 정확히 한 번 포함
- 실제 review artifact가 없으면 `human_reviewed=false`

## 8. raster quality

결정론적 검사는 다음을 양성·음성 fixture로 검증한다.

- exact PNG dimensions
- spatial luminance variation
- decal/opacity alpha extractability
- border contamination proxy
- opposite-edge seam RMSE proxy
- emission energy/variation
- wood gradient anisotropy advisory

unwanted object/text, style, semantic background와 exact-text 시각 부재는 로컬 metric으로 검출
가능하다고 주장하지 않는다. 이 항목은 non-hard `unscorable`로 남아야 하며 deterministic pass를
human/semantic pass로 재분류하지 않는지 검사한다.

## 9. MaterialAuthoring 0.2.1

- selection/evidence/quality/adoption exact artifact chain
- source V0.5 MaterialPlan, UV identity와 AssetScaleContext 재검증
- base-color/decal/emission/opacity direct role과 strategy/family compatibility
- low-frequency lighting normalization의 bounded policy
- selected source와 parameter hash에 결속된 local height/normal/roughness/optional AO
- OpenGL +Y normal, constant metallic과 channel color-space 규칙
- output root containment, atomic publication, existing run refusal
- spatial deviation, offset-edge RMSE, wood grain-axis 판정
- staging-only manifest/receipt와 canonical unchanged
- public finalize 뒤 overlay `status=adopted`, `next_action=controller_promotion_required`
- staging receipt가 base AQ resume, overlay `completed` 또는 canonical promotion을 만들지 않음
- actual `MaterialPhaseReceiptV2`와 companion adoption/receipt의 exact controller-input binding이
  없는 상태에서 material promotion/IQ/package로 진행하지 않음

## 10. exact signage text

- exact user text UTF-8 digest 재계산
- exact text가 ImageGen prompt에 없는지 검사
- project-local bitmap font JSON과 TTF/OTF hash binding
- glyph 누락, rect overflow, font escape/tamper 거부
- `unknown_text`/`inferred_placeholder`가 text/font/glyph를 갖거나 rasterize하면 거부
- composition output과 receipt가 exact text/font/source에 결속됨

## 11. fake controller scope

`FakeCodexImagegenController`는 deterministic PNG로 success, partial, wrong output, budget,
duplicate와 crash-resume를 비용 없이 검증한다. 이 결과는 반드시
`fake_for_tests`/`deterministic_fake`로 남아야 한다.

Fake PNG로 core, MaterialAuthoring 또는 Blender gate가 통과해도 다음을 증명하지 않는다.

- 실제 Codex 내장 ImageGen 호출
- prompt adherence 또는 semantic content quality
- 사람 reference review
- production activation

## 12. Blender 5.0.1

별도 Blender gate가 있는 경우 fake completion 또는 명시적으로 분류된 실제 completion을 입력으로
decal, wood hybrid, emission, crystal 계열의 graph compile/reopen/render를 검사한다. GLB와 FBX를
검사한다면 같은 approved source에서 독립 생성·clean import하고 material-loss evidence도 포맷별로
분리한다.

fixed `probe_codex_image_material_v021.py`는 deterministic fake completion/adoption으로 분류된
wood, signage, emissive와 crystal whitelist를 compile·reopen·render·rehash한다. 각 family가 실제로
실행됐는지는 verification 기록에서 따로 표시하며 probe의 존재를 pass로 계산하지 않는다.

기존 manual self-hosted `.github/workflows/blender-smoke.yml`은 새 job을 만들지 않고 AQ gate를
경유한다. `CBM_RUN_CODEX_IMAGE_MATERIAL_BLENDER_SMOKE=1`일 때 정확히
`tests/test_codex_image_material_authoring_v021.py::test_fake_core_adoption_compiles_in_blender_5`를
추가 실행한다. 이 test는 strict deterministic Fake smoke이고, receipt의
`actual_codex_imagegen_execution_verified=false`를 유지해야 한다.

Blender compile이 통과해도 generated pixels의 의미론적 정확성, 실제 ImageGen 실행 또는 destination
runtime parity와 package acceptance는 증명하지 않는다.

## 13. 실제 Codex 내장 ImageGen smoke

실제 smoke는 현재 Codex 작업이 exact assignment를 읽고 built-in `$imagegen`을 호출해야 한다.

1. profile/budget/plan/assignment와 ControllerExecutionRequest를 게시한다.
2. request-owned assignment snapshot의 prompt, size, role과 forbidden text를 확인한다.
3. `$imagegen`으로 한 assignment의 PNG를 생성한다.
4. 허용된 local source root에서 controller workspace output으로 복사한다.
5. completion을 마지막에 작성하고 same request를 resume한다.
6. ControllerResult, completion, candidate, quality, selection/adoption evidence를 rehash한다.
7. MaterialAuthoring `0.2.1` staging receipt 뒤 `adopted` / `controller_promotion_required` 정지를
   확인한다.
8. 최종 prompt, generated source의 분류, repository staging path와 artifact hash를 기록한다.

이 smoke는 fake evidence와 별도 경로·controller kind로 남긴다. 사람이 보지 않았다면
`human_reviewed=false`이고, 한 장의 smoke로 일반 품질이나 profile 활성화를 주장하지 않는다.

## 14. 공개 표면과 문서 parity

- Python exports, CLI, MCP tool schema와 repository catalog
- CLI `codex-imagegen-status/plan/run/select/adopt`와 동등 MCP 5종
- adopt prepare-only options와 contained MaterialAuthoring request finalize mode의 상호 배타성
- `.codex/config.toml`은 host lifecycle만 허용하고 image API/network authority는 없음
- profile status의 `disabled_experimental`/`verified_active=false`
- CLI/MCP invalid path, stale hash, missing opt-in 음성 테스트
- README, CHANGELOG, ROADMAP, architecture/getting-started/migration/verification 링크
- generated schema, repository tree와 manifest parity

## 15. 완료 판정

전체 pytest/Ruff, doctor, Blender compatibility, instruction checker, repository summary와 관련
AQ/V0.7~V0.9 gate가 실제로 통과해야 한다. 실행하지 않은 명령은 `not_run`, 환경상 불가능한
항목은 `unavailable`, 사람이 검토하지 않은 항목은 `not_reviewed`다. 실제 내장 ImageGen smoke가
없으면 fake/contract 구현은 검증할 수 있어도 provider를 `verified_active`로 바꿀 수 없다. 실제
core `0.1.0` smoke만으로는 actual `MaterialPhaseReceiptV2`나 exact controller-input binding을
주장할 수 없다. 2026-08-13 additive Material Loop는 별도 strict bridge와 기존 host promotion으로
fake-controller fixture의 actual receipt/IQ 경계를 검증했지만, historical actual source는 current-task
`review_required`에서 멈췄다. 따라서 fresh built-in ImageGen full material promotion, human-approved
package 완료를 주장하거나 profile을 활성화할 수 없다. 정확한 후속 범위는
`TEST_PLAN_IMAGEGEN_MATERIAL_LOOP_KO.md`와 `VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md`를 따른다.
