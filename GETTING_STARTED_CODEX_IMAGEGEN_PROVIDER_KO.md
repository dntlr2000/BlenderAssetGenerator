# Codex Built-in ImageGen Texture Provider 0.1.0 시작 가이드

> 현재 profile은 **`disabled_experimental`**이다. 이 가이드는 격리된 새 job에서 실험 계약을
> 사용하는 방법을 설명할 뿐 production-ready 또는 verified-active 지원을 선언하지 않는다.
> 실제 실행 범위는 `VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md`를 따른다.

## 1. 먼저 알아둘 점

이 기능은 AQ host가 직접 image API를 호출하는 provider가 아니다.

1. AQ host가 strict assignment와 허용 output 경로를 게시한다.
2. 현재 열려 있는 Codex 작업이 assignment를 읽는다.
3. 현재 작업이 Codex 내장 `$imagegen`으로 PNG를 만든다.
4. host가 exact completion을 검증하고 후보 하나를 선택한다.
5. 선택된 pixels는 MaterialAuthoring staging candidate로만 이어진다.
6. staging receipt 뒤 overlay는 `adopted` / `controller_promotion_required`에서 멈춘다.

- API key, OpenAI SDK, 외부 HTTP provider를 사용하지 않는다.
- 이미지 생성 사용량은 별도 API billing이 아니라 현재 Codex 앱 사용량 범위에 속한다.
- repository는 새 Codex task를 만들지 않는다.
- Codex 앱을 닫으면 생성은 계속되지 않는다.
- output이 없으면 `waiting_for_controller`에서 멈추고 같은 request로만 재개한다.
- ImageGen output은 완성 PBR texture set이 아니다.

| 구분 | `autonomous_static_prop_v2` | `autonomous_static_prop_v2_codex_imagegen` |
|---|---|---|
| 기본 의미 | local-only AQ v2 | base AQ v2 위의 optional image companion |
| 상태 | `disabled_experimental` | `disabled_experimental` |
| 이미지 생성 | 없음 | 현재 Codex task의 built-in `$imagegen` |
| provider 실행 주체 | 해당 없음 | controller-mediated, repository host 아님 |
| 앱 종료 | base workflow도 독립 daemon 아님 | generation은 대기하고 자동 계속되지 않음 |
| material write | 기존 controller-only promotion | staging receipt까지만; promotion 연결은 미배선 |
| 자동 migration | 없음 | 없음 |

## 2. 먼저 읽을 문서

1. `GETTING_STARTED_AQ_V02_KO.md` — base AQ v2의 실험 상태와 승인 경계
2. `ARCHITECTURE_CODEX_IMAGEGEN_PROVIDER_KO.md` — 권한, state, evidence 구조
3. `CONTROLLER_EXECUTOR_KO.md` — request-owned workspace와 resume
4. `MATERIAL_AUTHORING_KO.md` — local PBR derivation과 exact text
5. `TEST_PLAN_CODEX_IMAGEGEN_PROVIDER_KO.md` — fake/actual/Blender 검증 분리
6. `MIGRATION_CODEX_IMAGEGEN_PROVIDER_KO.md` — no auto migration
7. `VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md` — 실제 실행 결과

## 3. 적합한 요청과 부적합한 요청

적합한 예:

- 고유한 목재 base-color/grain 후보
- 간판의 배경·테두리·장식
- 패널 그래픽과 장식 문양
- 발광 패턴
- 크리스탈의 색·발광 패턴
- reference-guided planar texture patch 후보

기존 local procedural 전략이 더 적합한 예:

- 단순 금속, 고무, 균일 도장
- exact signage 문구 자체
- authoritative normal/roughness/height/AO map
- geometry나 executable content
- destination-ready material 또는 package

## 4. 새 실험 plan 만들기

기존 session을 변환하지 말고 새 격리 AQ v2 job을 사용한다. planner에는 reference, target
subject, delivery, target material/semantic role, generation intent, direct output role, prompt
template, candidate 수와 image size를 제공한다.

두 opt-in은 모두 필요하다.

```text
codex_imagegen_allowed=true
allow_disabled_experimental=true
```

사용자 요청 예시는 다음과 같다.

```text
첨부 reference로 새 static prop AQ v2 job을 만들고,
autonomous_static_prop_v2_codex_imagegen 실험 overlay를 명시적으로 사용해줘.
대상 material은 wood-body, semantic role은 wood-grain,
intent는 generated_image_procedural_hybrid_v1,
직접 역할은 base_color, 후보는 1개, 1024x1024 low quality로 제한해.
exact text는 ImageGen prompt에 넣지 말고 local fallback도 유지해.
```

planner는 base `autonomous_static_prop_v2` plan을 그대로 만들고 sibling
provider-profile/budget/plan/overlay evidence를 추가한다. `profile_status`는 계속
`disabled_experimental`이고 override 사용 사실이 결과에 남는다.

### 4.1 상태를 읽는 법

정적 capability 조회는 `codex_imagegen_status()`, session 상태 조회는
`get_codex_image_phase_status(job_root, session_id)`가 담당한다. 조회는 provider를 활성화하거나
overlay를 만들지 않으며 prompt bytes나 generated pixels를 status에 노출하지 않는다.

session status에서 확인할 핵심 필드는 다음과 같다.

- profile과 `evidence_status=disabled_experimental`
- current sequence/phase/status/next action
- `controller_required=true`와 `waiting_for_controller`
- immutable budget limits, reconstructed usage와 remaining
- latest assignment/completion/controller result/selection/adoption/terminal artifact 요약
- completion/selection/terminal outcome
- material staging 뒤 `status=adopted`, `next_action=controller_promotion_required`
- `repository_can_spawn_codex_task=false`
- `autonomous_daemon=false`, `continuation_after_app_exit=false`
- `actual_codex_imagegen_execution_verified=false`

마지막 필드는 fake와 실제 completion을 분류하는 개별 evidence와 별개로, profile 전체가 아직
verified-active가 아니라는 보수적 status다. 실제 built-in PNG가 존재해도 이 값을 문서나 수동
편집으로 바꾸지 않는다.

### 4.2 공개 CLI와 MCP

현재 구현된 CLI는 다음 다섯 개다.

```powershell
uv run cbm codex-imagegen-status
uv run cbm codex-imagegen-status --job-id <JOB_ID> --session-id <SESSION_ID>
uv run cbm codex-imagegen-plan "<REQUEST>" `
  --reference <REFERENCE_PATH> `
  --target-subject <TARGET_SUBJECT> `
  --target-material-ids <MATERIAL_IDS> `
  --semantic-roles <SEMANTIC_ROLES> `
  --prompt-template-id <PROMPT_TEMPLATE_ID> `
  --deliveries review_only `
  --output-roles base_color `
  --generation-intent generated_image_procedural_hybrid_v1 `
  --candidate-count 1 `
  --quality-level low `
  --image-width 1024 `
  --image-height 1024 `
  --aspect-ratio square `
  --enable-v2 `
  --allow-disabled-experimental
uv run cbm codex-imagegen-run <JOB_ID> <SESSION_ID> --prompt-file <PROMPT_FILE>
uv run cbm codex-imagegen-select <JOB_ID> <SESSION_ID>
uv run cbm codex-imagegen-adopt <JOB_ID> <SESSION_ID>
uv run cbm codex-imagegen-adopt <JOB_ID> <SESSION_ID> `
  --exact-text-evidence <CONTAINED_EXACT_TEXT_EVIDENCE_JSON>
uv run cbm codex-imagegen-adopt <JOB_ID> <SESSION_ID> `
  --material-request <CONTAINED_MATERIAL_REQUEST_JSON>
```

`--target-material-ids`, `--semantic-roles`, `--output-roles`와 `--deliveries`는 comma-separated
값이다. `plan`의 두 opt-in은 기본 false다. `run`의 `--prompt-file`은 새 assignment를 게시할 때만
필요하고, 같은 waiting assignment를 재개할 때는 생략한다. `run`이라는 이름은 repository가
ImageGen을 호출한다는 뜻이 아니다. 첫 호출은 assignment/request/workspace를 만들고 보통
`waiting_for_output`을 반환한다. exact signage 문구가 있다면 신규 assignment 호출에
`--exact-text-value <TEXT>`를 별도로 주며, 이는 문구 hash와 prompt exclusion을 검증하는 guard이지
ImageGen에게 글자를 그리라는 옵션이 아니다.

동등한 MCP host surface는 다음과 같다.

- `get_codex_imagegen_status`
- `plan_codex_imagegen`
- `run_codex_imagegen`
- `select_codex_imagegen`
- `adopt_codex_imagegen`

MCP `run_codex_imagegen`은 신규 assignment에 `rendered_prompt_text`를 받으며 재개에서는 생략할 수
있다. status는 prompt를 반환하지 않는다.

첫 `codex-imagegen-adopt` 호출은 selected pixels를 위한 `ImageToMaterialAdoption 0.2.0`을 준비하고
`supply_material_authoring_v021_request`를 반환한다. 이 준비 호출에서만 선택적으로
`--material-strategy`, comma-separated `--direct-channels`, 그리고 assignment가 exact signage
hash를 가진 경우 `--exact-text-evidence`를 지정할 수 있다. 이 JSON은 strict
`ExactSignageTextEvidenceV021`이어야 하고 UTF-8 text SHA가 assignment의 `exact_text_sha256`과
정확히 같아야 한다. MCP의 동등한 prepare 인수는 `exact_text_evidence_path`다. 두 번째 호출은
job-contained `CodexImageMaterialAuthoringRequestV021`을 `--material-request`로 받아 local candidate와
receipt를 만들고 overlay를 `status=adopted`, `next_action=controller_promotion_required`로 둔 채
멈춘다. material request와 prepare-only 옵션을 한 호출에 섞으면 거부된다. 이 adoption은 base
material-authoring을 자동 재개하거나 canonical material promotion을 수행하지 않는다.

## 5. assignment를 게시할 수 있는 시점

ImageGen overlay는 base AQ geometry promotion이 끝난 material-authoring 시작점에서만 assignment를
게시한다. 현재 base state가 다음과 같아야 한다.

```text
phase=authoring
status=running
next_action=execute_controller
last provenance=geometry_candidate_validation_receipt
```

다른 phase, stale base state, 만료된 RootAuthorization 또는 다른 plan/profile/budget이면 중단한다.
assignment는 prompt와 exact hash, candidate output path, reference, budget snapshot과 protected job
inventory를 고정하지만 ImageGen을 직접 실행하지 않는다.

## 6. 현재 Codex 작업에서 생성하기

`desktop_in_session` controller를 실행하면 request와 workspace가 게시된다. 첫 호출에서 output이
없으면 정상적으로 대기한다.

```text
production/autonomy_v2/<SESSION_ID>/codex_imagegen/
controller_executions/codex-imagegen-<ASSIGNMENT_ID>/
```

현재 Codex 작업은 workspace의 assignment snapshot을 읽고 다음을 확인한다.

- exact `rendered_prompt_text`와 `prompt_sha256`
- `requested_candidate_count`
- exact width/height와 quality level
- `allowed_output_roles`
- forbidden content/text notes
- `candidate_output_paths`와 `completion_file_target`

목재 base-color assignment의 prompt file 예시는 다음처럼 visual source 한 장만 요구한다.

```text
Create one seamless 1024x1024 square base-color material swatch of fine-grained warm walnut wood.
Show only the flat surface texture, evenly diffuse-lit and color-neutral, with coherent horizontal
grain, restrained knots, and natural small-scale color variation. Make opposite edges tile cleanly.
No object, plank outline, frame, border, perspective, cast shadow, specular highlight, text, letters,
numbers, logo, signature, watermark, normal-map colors, roughness map, height map, or AO map.
```

이 prompt는 ImageGen pixels를 `base_color` 후보로만 요청한다. exact signage 문구, PBR 파생 map이나
완성 asset을 요청하지 않는다. assignment가 정한 intent/role/reference에 맞게 subject와 style만
바꾸고 금지 경계를 제거하지 않는다.

그 다음 built-in `$imagegen`을 실행한다. brand-new generation이면 임의 API client, shell downloader,
SDK나 HTTP endpoint를 사용하지 않는다. 생성된 local PNG는 controller helper가 허용 source root에서
request-owned output leaf로 복사하며 `completion.json`은 모든 PNG가 완전히 기록된 뒤 마지막에
쓴다. 이 고정 helper는 `copy_imagegen_png_and_write_completion(...)`이며 source root와 controller
workspace root를 모두 명시적으로 받아 containment를 검사한다. source PNG와 `output_roles`는
candidate 순서대로 정확히 하나씩 대응해야 한다.

helper는 다음을 거부한다.

- assignment snapshot mismatch
- source/output root escape 또는 link/reparse point
- candidate 수·파일명·dimension·role 불일치
- 기존 output overwrite
- extra 또는 partial output

## 7. 앱 종료와 resume

Codex 앱을 닫거나 현재 작업이 끝나면 repository가 대신 생성하지 않는다. 상태는
`waiting_for_controller`로 남는다.

재개할 때는 같은 job/session/assignment에서 controller를 다시 호출한다. host는 새 request를
만들지 않고 기존 workspace와 receipt를 재검사한다. output이 완전하면 same-request
`adopt_existing`/completion 경로를 사용하고, 불완전하거나 protected job이 바뀌었으면
fail-closed한다.

대기 중 다음을 하지 않는다.

- 새 assignment나 candidate path 생성
- generation/refinement budget 자동 증가
- 다른 output directory로 복사
- stale completion을 새 session evidence로 재사용

## 8. quality report 읽기

host hard gate는 PNG dimension, spatial variation, 필요한 alpha, border/seam proxy와 emission
usefulness를 검사한다. wood grain은 anisotropy advisory가 추가된다. hard gate를 통과한 후보 중
deterministic ordering으로 하나만 선택한다.

중요한 제한:

- unwanted object/text
- style/prompt alignment
- semantic background alignment
- exact signage text의 시각적 부재

위 항목은 현재 local pixel metric으로 판정하지 못해 non-hard `unscorable`이다. 따라서
`outcome=passed`와 `selection_eligible=true`만 보고 의미론적으로 맞다고 단정하지 않는다. 사람이
검토하지 않았다면 `human_reviewed=false`다.

## 9. exact signage text

ImageGen에는 배경과 장식만 맡긴다. exact 문구는 prompt에서 제외하고 project-local deterministic
rasterizer가 나중에 합성한다.

- `exact_user_text`: 별도 `ExactSignageTextEvidenceV021` JSON과 hash-bound bitmap-font JSON 또는
  TTF/OTF 필요
- `unknown_text`: glyph를 만들지 않음
- `inferred_placeholder`: placeholder 문자열도 rasterize하지 않음

OS font나 network font를 자동 선택하지 않는다. exact text가 font에 없거나 UV rectangle에 맞지
않으면 실패하며, 글자를 축약·번역·추측하지 않는다.
assignment에 exact-text hash가 없으면 prepare 단계의 text evidence 자체를 거부하고, hash가 있으면
evidence 누락·다른 문구·다른 immutable artifact를 모두 거부한다. 재개 시에는 기존 adoption에
결속된 동일 evidence를 다시 검증한다.

## 10. local PBR derivation

직접 허용되는 generated role은 다음 네 가지뿐이다.

| generated role | 직접 material 의미 |
|---|---|
| `base_color` | sRGB base color source |
| `decal_rgb` | local text composition 전 decal/background color |
| `emission` | sRGB emission source |
| `opacity_source` | non-color opacity source |

normal, roughness, metallic, height, displacement, occlusion은 직접 채택하지 않는다.
MaterialAuthoring 0.2.1이 selected source hash, UV identity, scale context와 bounded policy를 사용해
lighting normalization, height, OpenGL +Y normal, roughness, optional AO와 constant metallic을
로컬에서 만든다.

output은 다음 staging-only run에 저장된다.

```text
material_authoring/codex_imagegen/runs/<RUN_ID>/
├─ request.json
├─ manifest.json
├─ receipt.json
└─ textures/*.png
```

`candidate_ready`도 canonical promotion이나 Blender/destination 검증 완료를 뜻하지 않는다. public
adoption의 최종 반환은 `status=adopted`, `next_action=controller_promotion_required`이며 overlay
`completed` 또는 base AQ resume을 주장하지 않는다.

## 11. 기본 budget

| 항목 | 상한 |
|---|---:|
| 전체 generation | 4 |
| 후보 | 3 |
| edit/refinement | 1 |
| assignment당 generation | 3 |
| draft | low, 1024×1024 이하 |
| final | medium, 2048×2048 이하 |
| assignment timeout | 900초 |
| 전체 elapsed | 3600초 |

budget은 immutable하며 실행 중 자동 확대하지 않는다. 적합한 후보가 없거나 의미론 검토가
필요하면 local procedural fallback, `review_required`, `user_image_required` 또는 failure terminal로
끝낸다.

assignment가 capacity에 맞지 않으면 controller를 호출하지 않고 plan item에 저장된 fallback으로
끝난다. 실행이 이미 시작된 뒤 final result가 `timeout`, `failed`, `rejected`이면 같은 fallback,
`cancelled`이면 cancellation terminal을 기록한다. `waiting_for_output`은 terminal이 아니며 동일
request-owned workspace를 채운 뒤 재개한다. 이 경계에서 자동 budget 확대나 controller 재호출은 없다.

## 12. fake와 실제 결과 구분

| 구분 | controller kind | source kind | 의미 |
|---|---|---|---|
| fake | `fake_for_tests` | `deterministic_fake` | 계약·음성·resume·Blender fixture용 |
| 실제 built-in | `desktop_in_session` | `codex_builtin_generated_image` | 현재 Codex 작업이 `$imagegen`으로 만든 결과 |

Fake gate가 통과해도 실제 ImageGen 실행이 아니다. 반대로 실제 PNG를 한 번 생성했다고 해서
profile이 active가 되거나 일반 품질, human review, PBR completeness가 증명되지 않는다. 검증 문서에서
두 scope의 prompt, 경로, hash와 결과를 별도로 확인한다.

## 13. delivery 전에 확인할 것

- actual `MaterialPhaseReceiptV2`와 companion adoption/receipt의 exact controller-input binding
- material candidate의 exact receipt와 모든 source hash
- authorized material controller의 rebuild/inspect/validate/promotion evidence
- IQ 0.2 quality terminal 또는 review 경계
- delivery profile별 exact V0.7 optimization approval
- GLB/FBX 각각의 package manifest, material-loss와 clean-import evidence
- destination-specific import plan과 사용자 승인

ImageGen assignment/completion/selection은 package나 Destination Handoff 승인이 아니다. 이
companion은 현재 첫 번째 항목의 배선 전에서 멈추므로 full material promotion, IQ와 package는
검증되지 않았다. Unity, Unreal 또는 다른 destination project도 수정하지 않는다.

## 14. 문제가 생겼을 때

- `disabled_experimental`: 두 explicit opt-in을 확인하되 status를 active로 고치지 않는다.
- `waiting_for_controller`: 현재 Codex 작업과 동일 request-owned workspace인지 확인한다.
- `controller_promotion_required`: staging 성공 상태다. `completed`로 고치거나 base AQ를 수동
  재개하지 말고 향후 exact controller binding을 기다린다.
- source inventory mismatch: canonical/user evidence를 되돌리지 말고 원인을 확인한 뒤 새 session을
  계획한다.
- semantic `unscorable`: 자동 pass를 기대하지 말고 사람 검토, user image 또는 local fallback을
  선택한다.
- text/font failure: exact text와 project-local font evidence를 보완한다. provider에 글자를 다시
  그리게 하지 않는다.
- material quality failure: 기존 run을 overwrite하지 말고 bounded policy/source 문제를 고쳐 새
  `run_id`를 사용한다.
