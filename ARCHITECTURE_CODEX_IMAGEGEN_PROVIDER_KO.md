# Codex Built-in ImageGen Texture Provider 0.1.0 아키텍처

> 구현 상태: 계약과 host-side lifecycle은 구현되어 있지만 profile은
> **`disabled_experimental`**이다. 이 문서는 지원·활성화를 선언하지 않는다. 실제로 실행한
> 테스트, fake fixture와 Codex 내장 ImageGen 실사용 증거는
> `VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md`가 권위 원본이다.
> 기존 core `0.1.0` 위에는 native adoption/normalization, semantic ranking과 AQ material/IQ 연결을
> 제공하는 additive Material Loop companion이 구현되어 있다. 이 companion도 profile을 활성화하거나
> 기존 evidence를 migration하지 않는다.

## 1. 목적

Codex Built-in ImageGen companion은 AQ 0.2가 제한된 이미지 생성 assignment를 게시하고,
**현재 열려 있는 Codex 작업**이 내장 `$imagegen` 도구로 후보 PNG를 만든 뒤, repository host가
그 결과를 검증·평가·선택하여 MaterialAuthoring의 staging candidate로 연결하는 선택적 overlay다.

기존 `autonomous_static_prop_v2`는 계속 local-only다. 이 companion은 프로젝트 버전
`0.9.0`, canonical SceneSpec `0.2.0`, V0.4~V0.9, AQ 0.1, AQ 0.2와 기존
MaterialAuthoring 계약의 의미를 바꾸지 않는다.

## 2. 명시적 비목적

저장소는 다음 권한이나 실행 경로를 갖지 않는다.

- `OPENAI_API_KEY` 또는 다른 provider credential
- OpenAI Python SDK, `client.images.generate`, `client.images.edit`
- HTTP endpoint/URL을 직접 호출하는 이미지 provider
- API별 과금 또는 credential rotation 계약
- 새 Codex task 생성, background daemon, 앱 종료 뒤 자동 실행
- ImageGen 결과를 완성 PBR set 또는 canonical MaterialPlan으로 직접 쓰기
- arbitrary Blender Python, node graph, shell, callback, driver, destination-project write

`network_required=false`는 **repository가 네트워크 provider를 호출하지 않는다**는 계약이다.
내장 ImageGen의 서비스 실행은 Codex가 관리하는 현재 작업의 도구 경계이며 repository의 API
client가 아니다. 비용 의미도 API billing이 아니라 `billing_scope=codex_usage`로 구분된다.

## 3. 세 개의 분리된 권한 표면

이 기능에서 이름이 비슷하지만 서로 대체할 수 없는 표면은 다음과 같다.

1. `autonomous_static_prop_v2_codex_imagegen`
   - AQ v2 위의 별도 overlay profile이다.
   - `disabled_experimental`, explicit opt-in, canonical write 없음이 고정된다.
2. ControllerExecutor phase profile `codex_imagegen`
   - 현재 Codex controller가 해당 request-owned workspace에서 내장 `imagegen`만 사용하도록
     assignment/input/output 범위를 고정한다.
   - `repository_path_validation_only`는 host path/hash 검증이며 외부 OS sandbox attestation이
     아니다.
3. MCP server registry와 `.codex/config.toml` project allowlist
   - 내장 ImageGen은 project MCP tool이 아니다.
   - 따라서 MCP allowlist에 이미지 API나 HTTP tool을 추가하는 것으로 활성화하지 않는다.

어느 한 표면의 등록이나 availability도 다른 표면의 승인, provider 활성화 또는 canonical
promotion 권한을 만들지 않는다.

## 4. 별도 profile과 opt-in

provider profile의 고정 경계는 다음과 같다.

- `base_profile=autonomous_static_prop_v2`
- `execution_mode=controller_mediated`
- `controller_mode=desktop_in_session`
- `provider_id=codex_builtin_gpt_image_v1`
- `credential_scope=none`
- `network_required=false`
- `api_key_required=false`
- `repository_can_spawn_codex_task=false`
- `autonomous_daemon=false`
- `canonical_material_write=false`
- `destination_project_write=false`

고수준 planner는 `codex_imagegen_allowed=true`와
`allow_disabled_experimental=true`를 둘 다 요구한다. 상태 조회나 기존 AQ session 로드는
overlay를 암묵적으로 만들지 않는다. 현재 builder는 activation evidence를 합성하지 않으며
`disabled_experimental` profile만 만든다.

## 5. 권위 흐름

```text
AQ v2 base plan + active root authorization
→ geometry candidate validation/promotion 완료
→ base state: authoring/running/execute_controller
→ immutable ImageGen provider profile + budget + plan
→ append-only overlay 초기화
→ immutable assignment 게시
→ dedicated ControllerExecutionRequest + request-owned workspace
→ waiting_for_controller
→ 현재 Codex task가 built-in ImageGen 실행
→ controller workspace에 exact PNG + completion.json 작성
→ ControllerExecutor가 exact allowed set만 canonical staging에 게시
→ ControllerResult 전체 lifecycle replay
→ host completion adoption
→ candidate/evidence/quality reports
→ deterministic single selection
→ ImageToMaterialAdoption 0.2.0
→ MaterialAuthoring 0.2.1 staging candidate
→ overlay status=adopted, next_action=controller_promotion_required
→ additive Material Loop bridge/controller input
→ ControllerExecutor material completion
→ host-only material promotion + actual MaterialPhaseReceiptV2
→ neutral preview + base AQ resume
→ IQ 0.2 quality_approved | review_required | blocked
→ 기존 review_only 또는 V0.7 exact approval 경계
```

ImageGen completion, quality pass와 selection은 서로 다른 증거다. 그 어느 것도 사용자 승인,
canonical material promotion, package acceptance 또는 Destination Handoff 승인이 아니다. core
`adopt`는 MaterialAuthoring `0.2.1` staging receipt에서 계속 멈춘다. 이후 진행은 별도 Material Loop
bridge가 exact chain을 다시 결속해 기존 host promotion/IQ authority에 위임할 때만 가능하다.

## 6. 저장 구조와 append-only state

overlay는 base AQ v2 state를 덮어쓰지 않고 다음 run-owned subtree를 사용한다.

```text
production/autonomy_v2/<session_id>/
├─ codex_imagegen/
│  ├─ provider-profile.json
│  ├─ budget.json
│  ├─ plan.json
│  ├─ overlay/states/<sequence>.json
│  ├─ assignments/<assignment_id>/
│  │  ├─ assignment.json
│  │  ├─ staging/candidate-00.png
│  │  ├─ staging/completion.json
│  │  ├─ evidence/
│  │  ├─ selection.json
│  │  ├─ companion-selection.json
│  │  ├─ adoption.json
│  │  ├─ evidence/native-core-preparation-<ordinal:02d>.json
│  │  └─ native_outputs/<native_output_id>/{original.png,receipt.json}
│  ├─ native_normalizations/<normalization_id>/{plan.json,normalized.png,receipt.json}
│  ├─ material_loop/previews/<preview_id>/
│  └─ controller_executions/codex-imagegen-<assignment_id>/
└─ codex_image_material_loop/
   ├─ bridge_plan.json
   ├─ controller_input.json
   ├─ states/<sequence>.json
   ├─ promotion_receipt.json
   └─ terminal.json

evidence/image_material_preflights/<identity>/
├─ receipt.json
└─ shadow_job/
   ├─ <exact V0.5 plan/graph/dependencies>
   └─ compile/<compile report + compiler artifacts>
```

실제 후보 수에 따라 `candidate-01.png`, `candidate-02.png`가 추가될 수 있다. overlay state는
predecessor hash와 단조 증가 budget usage를 갖는다. 조회와 전이는 initial state부터 chain을
재구성하며 중간 state 삽입, provenance 교체, budget 감소와 history 수정을 거부한다.

assignment는 생성 시 job inventory를 hash한다. 해당 session의 `codex_imagegen/` subtree만
제외하고 다른 job file set/hash가 바뀌면 completion adoption 전에 실패한다. input이나 기존
evidence를 gate 통과용으로 수정하지 않는다.

## 7. ControllerExecutor와 중단·재개

ControllerExecutor는 canonical job root를 controller에 넘기지 않는다. assignment와 immutable
inputs를 request-owned workspace로 복제하고, 선언된 output leaf만 수집한다. 다음은 모두
fail-closed다.

- path escape, symlink/junction/reparse point
- 누락·추가·빈 output 또는 잘못된 PNG/hash/dimension
- stale assignment, prompt echo, budget snapshot, base state
- request/profile/result/receipt/state-chain splice
- partial 또는 duplicate completion
- protected source inventory 변경

`desktop_in_session` 첫 호출에 output이 없으면 `waiting_for_output`/`waiting_for_controller`를
기록한다. Codex 앱을 닫으면 작업은 진행되지 않는다. 다음 호출은 새 request, workspace,
generation 또는 budget을 만들지 않고 **동일한 request-owned workspace를 재검증해 resume**한다.
완료된 result는 ControllerExecutor의 started/invocation/completed/published receipt와 저장된 result
bytes 전체를 다시 재구성해야 채택된다.

여기서 core `run` resume은 ImageGen ControllerExecutor request의 output 채택까지만 뜻한다.
MaterialAuthoring `0.2.1` receipt가 게시된 뒤 core overlay는 `status=adopted`,
`next_action=controller_promotion_required`에서 멈춘다. additive Material Loop의 `bridge-run`,
`promote`, `resume`, `continue`는 이 상태를 exact input으로 받아 별도 append-only state를 진행한다.
base AQ 전이는 actual `MaterialPhaseReceiptV2`가 생성된 뒤 기존 transition service를 통해서만
수행되며 core overlay history를 `completed`로 고쳐 쓰지 않는다.

## 8. 계약과 버전

Codex ImageGen core는 strict `0.1.0` companion이다.

- `CodexBuiltinImageProviderProfile`
- `CodexImageGenerationBudget`
- `CodexImageGenerationPlan`
- `CodexImageGenerationAssignment`
- `CodexImageGenerationCompletion`
- `CodexGeneratedImageEvidence`
- `CodexImageGenerationCandidate`
- `CodexImageGenerationQualityReport`
- `CodexImageGenerationSelection`
- `CodexImageGenerationTerminal`

채택 receipt는 `ImageToMaterialAdoption 0.2.0`, local material companion은
`MaterialAuthoring 0.2.1`, AQ overlay state는 `0.1.0`이다. strict 모델은 unknown field,
coercion, non-finite number를 거부하고 repository-relative POSIX path, exact SHA-256,
session/workflow/profile/provenance binding을 요구한다. 기존 evidence의 auto migration은 없다.

Material Loop는 native output adoption/normalization, semantic review, candidate ranking/selection
receipt, V0.5 bridge/normalized companion와 exact-adoption Blender shadow preflight, material
bridge/controller/promotion/preview/state/terminal을 별도 strict `0.1.0` contract로 추가한다. native
normalization receipt는 native original의 adoption receipt를 재귀 결속한다.
`CodexImageNativeCorePreparationReceipt`는 그 chain을 core completion/candidate/quality/selection과
exact byte identity로 이어 bridge/controller/promotion까지 유지한다. 다중 후보 selection receipt도
같은 세 경계에 유지된다. `exact_adoption`은 원래 staging-only/compile
`not_run` 의미를 바꾸지 않으며 별도 actual Blender preflight가 없으면 거부된다.

## 9. 허용 intent와 direct pixels

허용 generation intent는 다음 다섯 가지다.

- `generated_surface_swatch_v1`
- `generated_decal_art_v1`
- `generated_emission_pattern_v1`
- `reference_guided_texture_patch_v1`
- `generated_image_procedural_hybrid_v1`

생성 pixels가 직접 제공할 수 있는 역할은 `base_color`, `decal_rgb`, `emission`,
`opacity_source`뿐이다. 다음은 ImageGen output을 authoritative channel로 직접 채택할 수 없다.

- `normal`, `roughness`, `metallic`
- `height`, `displacement`, `occlusion`
- tangent-space vector data

MaterialAuthoring 0.2.1은 선택된 source SHA-256, UV identity, physical scale context와 bounded
derivation policy를 묶어 low-frequency lighting normalization, height, OpenGL +Y normal,
roughness, optional occlusion과 constant metallic을 로컬에서 만든다. 각 channel은 algorithm ID,
parameter digest, source hashes와 output hash를 가진다. 따라서 생성 이미지 한 장을 “완성 PBR
texture set”이라고 부르지 않는다.

## 10. exact signage text

정확한 간판 문구는 provider prompt에서 제외하고 exact UTF-8 hash로만 결속한다. 배경, 테두리,
장식 후보는 ImageGen이 만들 수 있지만 glyph는 project-local deterministic rasterizer가 합성한다.

- outline text: hash-bound project-local TTF/OTF
- bitmap text: strict project-local bitmap-font JSON
- `exact_user_text`: 별도 `ExactSignageTextEvidenceV021 0.2.1`과 font가 모두 있을 때만 rasterize
- `unknown_text` 또는 `inferred_placeholder`: text/font를 가질 수 없고 glyph를 만들지 않음

OS font나 네트워크 font를 암묵적으로 사용하지 않는다. exact text가 provider output에 우연히
포함됐는지에 대한 의미론 판정은 로컬 픽셀 metric만으로 증명할 수 없으므로 별도 검토 대상이다.

## 11. 예산과 종료

기본 immutable budget은 다음 상한을 가진다.

| 항목 | 기본 상한 |
|---|---:|
| 전체 generation | 4 |
| 보존 후보 | 3 |
| edit/refinement | 1 |
| assignment당 generation | 3 |
| draft | `low`, 최대 1024×1024 |
| final | `medium`, 최대 2048×2048 |
| assignment timeout | 900초 |
| 전체 elapsed | 3600초 |

예산은 자동 확대되지 않는다. generation terminal outcome은 `adopted`, `local_procedural_fallback`,
`review_required`, `user_image_required`, `failed`, `cancelled` 중 하나이며 기존 후보와 quality
report를 삭제하지 않는다. `adopted` generation terminal이 있어도 overlay 자체는
`controller_promotion_required`에서 멈출 수 있으며, 이는 base AQ나 전체 workflow 완료가 아니다.

assignment가 capacity, size 또는 elapsed budget 때문에 시작될 수 없으면 controller를 호출하지 않고
선택된 plan item의 exact fallback으로 terminalize한다. final ControllerResult의 `timeout`, `failed`,
`rejected`도 그 fallback을 사용하고 `cancelled`는 cancellation으로 닫는다. `waiting_for_output`만
동일 request 재개 상태로 남는다. 새 terminal 필드 `plan_item_id`, `runtime_trigger`,
`controller_request`, `controller_result`는 additive이며, 선게시 terminal의 crash recovery는 canonical
bytes와 전체 모델 equality를 재검증한다. 기존 필드가 없는 0.1 evidence의 읽기 의미는 바꾸지 않는다.

## 12. 품질과 선택의 정확한 의미

host가 결정론적으로 검사하는 범위는 PNG decode/dimension, luminance variation, alpha
extractability, border proxy, opposite-edge seam proxy, emission luminance와 wood gradient
anisotropy다. hard gate가 통과한 후보 중 하나를 점수·ID 기반 deterministic ordering으로
선택하며 나머지는 rejected/ineligible evidence로 보존한다. single-candidate core 의미는 유지한다.
후보가 둘 이상인 Material Loop run은 모든 후보의 current-task semantic review와 exact ranking
evidence를 요구하며, 누락/unresolved 후보가 있으면 전체를 `review_required`로 둔다. 해소된 후보는
file hard gate, deterministic quality, semantic outcome, material-role suitability, repair cost, stable
candidate ID 순서로 비교한다.

현재 로컬 검사만으로는 다음 의미론을 판정할 수 없다.

- unwanted object/content
- unwanted text/content
- prompt style alignment
- semantic background alignment
- exact text가 시각적으로 존재하지 않는다는 보증

이 항목은 non-hard `unscorable` advisory로 기록된다. 따라서 deterministic `passed`나
`selection_eligible=true`는 **의미론적 무결성이나 사람 검토를 증명하지 않는다**. 실제 사람이
exact review artifact를 만들지 않았다면 `human_reviewed=false`를 유지한다.

여러 후보의 derived contact sheet를 만들 수 있지만 source PNG를 바꾸거나 사람 review를
합성하지 않는다. selection과 quality report의 machine JSON이 계속 권위 원본이다.

## 13. fake와 실제 ImageGen 증거

`FakeCodexImagegenController`는 deterministic PNG로 정상·부분·경로·hash·budget·duplicate·resume
경계를 검증하는 test-only backend다. fake completion은
`controller_kind=fake_for_tests`, `execution_scope=deterministic_fake`,
`source_kind=deterministic_fake`로 기록된다.

실제 내장 ImageGen completion은 `controller_kind=desktop_in_session`,
`execution_scope=codex_built_in`, `source_kind=codex_builtin_generated_image`로 분리된다. fake gate,
local MaterialAuthoring 또는 Blender smoke가 통과해도 실제 `$imagegen` 실행으로 재분류하지 않는다.

## 14. Material Loop와 delivery 경계

MaterialAuthoring output은 계속 `material_authoring/codex_imagegen/runs/<run_id>/`의 staging-only
candidate다. core `adopt`는 그 receipt를 overlay에 결속하고 `status=adopted`,
`next_action=controller_promotion_required`에서 정지한다.

additive Material Loop는 이 exact chain을 controller input으로 결속하고 기존 host material service를
통해 actual `MaterialPhaseReceiptV2`, fixed neutral preview, base AQ resume와 IQ 경계까지 진행할 수
있다. bridge나 controller가 canonical material을 직접 쓰지는 않는다. 현행 terminal은 material
promotion과 IQ pass를 구분하며 IQ pass에만 `quality_approved`를 사용한다.

delivery는 기존 AQ v2 profile을 재사용한다. `review_only`는 package가 아니고 portable GLB/FBX는
각각 exact V0.7 plan-hash user approval이 필요하다. 승인 전 상태는
`waiting_for_v07_approval`이며 raw exporter/clean-import mechanism test를 production package나
completed terminal로 재분류하지 않는다. GLB 성공은 FBX 성공을 뜻하지 않고 destination project는
수정하지 않으며 runtime parity는 별도 미검증이다.

Material Loop의 상세 contract와 public 9 CLI/9 MCP는
[Material Loop 아키텍처](ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md)를 따른다.

## 15. Material Closure source binding

Material Closure source mode `imagegen`은 provider core를 바꾸지 않고 exact evidence consumer로
사용한다. provider profile, assignment, completion, generated image, native normalization
plan/receipt, semantic review, selection, adoption과 MaterialAuthoring request/manifest/receipt 전체를
typed root로 요구한다. `additional_evidence_paths`는 필수 typed root를 대신할 수 없다.

provider completion이 유효해도 reference, graph provenance, ShaderRecipe, TextureManifest,
channel/mask, UV/surface-detail, rollback baseline이 closure에 없으면 material approval로 진행하지
않는다. ImageGen pixels의 허용 role과 local PBR derivation 정책은 그대로 유지한다.

이 연동은 built-in ImageGen invocation authority, task 생성/재개, API/SDK/HTTP provider 또는
profile activation을 추가하지 않는다. fake/historical/current-task evidence 분류도 바꾸지 않으며
`autonomous_static_prop_v2_codex_imagegen`은 계속 `disabled_experimental`이다.
