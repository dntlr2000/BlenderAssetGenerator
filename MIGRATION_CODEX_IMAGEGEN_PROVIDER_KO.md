# Codex Built-in ImageGen Texture Provider 0.1.0 마이그레이션 정책

> 이 기능은 기존 evidence의 migration이 아니라 새 session에서 명시적으로 선택하는 additive
> overlay다. profile은 **`disabled_experimental`**이고 자동 활성화되지 않는다.

## 1. 유지되는 기준선

다음 version/schema/profile의 bytes와 의미는 바뀌지 않는다.

- Project `0.9.0`, canonical SceneSpec `0.2.0`
- V0.4~V0.9 contracts와 SceneSpec V03 derived-only path
- `standard`, `background_exterior`
- AQ `0.1.0`, `autonomous_static_prop_v1`
- AQ v2 `0.2.0`, `autonomous_static_prop_v2` local-only behavior
- MaterialAuthoring `0.1.0`/`0.2.0` local strategies

Codex ImageGen은 exact companion version과
`profile_id=autonomous_static_prop_v2_codex_imagegen` binding으로만 dispatch한다. 계약 부재,
unknown version 또는 과거 evidence를 새 기능으로 추측하지 않는다.

## 2. 선택은 새 session에서만

고수준 planner는 다음 두 값을 동시에 요구한다.

- `codex_imagegen_allowed=true`
- `allow_disabled_experimental=true`

기존 AQ v2 session의 status 조회, load, audit 또는 run이 overlay를 만들지 않는다. 기존 session을
ImageGen profile로 in-place 전환하거나 `autonomous_static_prop_v2` plan/profile bytes를 수정하지
않는다. ImageGen이 필요하면 immutable input 범위를 유지한 새 격리 job/session 계획을 만든다.

## 3. 신규 계약의 additive version

- Codex ImageGen core evidence: `0.1.0`
- AQ v2 Codex Image overlay state: `0.1.0`
- `ImageToMaterialAdoption`: `0.2.0`
- MaterialAuthoring Codex-image companion: `0.2.1`

기존 MaterialAuthoring `0.2.0`을 `0.2.1`로 변환하지 않는다. `0.2.1`은 selected image evidence를
받는 별도 staging request/manifest/receipt이며 canonical V0.5 계약의 대체물이 아니다.

## 4. 저장 위치와 immutable history

provider profile, budget, plan, assignment, completion, candidate, quality, selection, adoption,
terminal과 overlay state는
`production/autonomy_v2/<session_id>/codex_imagegen/` 아래 append-only evidence로 남는다.
MaterialAuthoring output은 `material_authoring/codex_imagegen/runs/<run_id>/` 아래에 별도로 게시한다.

이전 candidate, rejected candidate, completion, receipt와 state를 삭제·덮어쓰기·수리하지 않는다.
같은 ID에 이미 exact bytes가 있으면 idempotent adoption만 허용하고 다른 bytes면 conflict다.

## 5. 중단과 재개

Codex Desktop이 닫히거나 output이 없으면 `waiting_for_controller`를 유지한다. 이는 daemon queue나
자동 retry가 아니다. 재개는 동일 assignment와 ControllerExecutionRequest의 request-owned
workspace를 사용하며 다음을 다시 검증한다.

- base AQ plan/profile/budget/root authorization와 현재 base state
- geometry promotion receipt
- provider profile와 immutable ImageGen budget
- assignment payload/prompt/source inventory
- ControllerExecutor tool profile, inputs, outputs와 receipt chain
- overlay predecessor chain과 monotonic budget usage

새 request, generation, output root 또는 budget 확대가 필요하면 기존 evidence를 고치지 말고 명시적
새 계획 경계를 사용한다.

## 6. material adoption과 rollback

ImageGen selection/adoption과 MaterialAuthoring 0.2.1 output은 canonical material promotion 전까지
staging이다. provider는 MaterialPlan이나 `.blend`를 직접 쓸 수 없다. 현재 공개 실행은 staging
receipt를 overlay에 결속한 뒤 `status=adopted`, `next_action=controller_promotion_required`에서
멈춘다. base AQ를 자동 재개하거나 overlay `completed`를 만들지 않는다.

향후 promotion에는 actual `MaterialPhaseReceiptV2`와 companion adoption/receipt를 exact
controller input으로 결속하는 새 배선과 검증이 먼저 필요하다. 기존 authorized material controller가
있다는 사실만으로 이 binding을 추측·합성·migration할 수 없다. 따라서 현재 companion의 full
material promotion, IQ와 package 경로는 미검증이다.

promotion 실패는 기존 exact archive/CAS rollback 경계를 사용하고 rollback receipt를 남긴다.
ImageGen evidence나 material run을 과거 성공으로 재분류하거나 history를 in-place repair하지 않는다.

기능 hardening 전 수동 검증 기록이 orchestration `completed`를 보고한 경우에도 그 JSON은 당시
구현 snapshot의 immutable history로 보존한다. 최신 reader가 그 파일을 현재 지원 경계의 완료
증거로 재분류하지 않으며, final code의 staging-only 정지 정책이 이후 신규 실행에 적용된다.

## 7. 외부 API/provider evidence 변환 금지

이 companion에는 credential, endpoint, URL, SDK client 또는 API billing contract가 없다. 과거
OpenAI API, 제3자 image service, 임의 HTTP download 또는 user-supplied provider evidence를
`codex_builtin_generated_image`로 변환하거나 신뢰하지 않는다.

fake evidence도 실제 내장 ImageGen evidence로 변환하지 않는다.

| 원본 | 유지되는 분류 |
|---|---|
| fake controller PNG | `fake_for_tests` / `deterministic_fake` |
| 현재 Codex built-in ImageGen | `desktop_in_session` / `codex_built_in` |
| user image | 기존 user-image provenance |
| 외부 API/provider | 이 companion 밖의 evidence |

## 8. 비활성화와 제거

profile이 `disabled_experimental`이거나 opt-in이 없으면 기존 local-only flow만 사용한다. overlay
파일이 없는 기존 job은 정상이다. 실험을 중단할 때도 canonical input이나 immutable history를
삭제하지 않고 `cancelled`, local fallback, review 또는 user-image-required terminal을 남긴다.

소프트웨어에서 기능을 제거하더라도 versioned evidence reader와 schema는 기존 기록의 의미를
보존해야 한다. profile 활성화는 별도 capability/smoke evidence와 정책 변경이 필요한 향후 작업이며
migration의 부수 효과가 아니다.

Terminal `0.1.0`의 `plan_item_id`, `runtime_trigger`, `controller_request`, `controller_result`는 additive
hardening 필드다. 새 capacity/final-controller terminal은 이를 필수 의미로 검증하지만, 필드가 없던
기존 0.1 evidence를 자동 보강·재분류·재작성하지 않는다.
