# AQ Approval Envelope 0.3 테스트 계획

## 1. 판정 원칙

machine-readable JSON과 exact file hash가 권위다. 구현 존재, unit fixture, representative benchmark,
실제 Blender 실행, 실제 사용자 품질 검증은 서로 다른 결과로 기록한다. 실행하지 않은 gate는
`unverified`, 환경상 의도적으로 제외된 gate는 `skipped`로 남긴다.

테스트가 synthetic `approved_by=user`를 만들더라도 기존 approval validator의 mechanism 검증일 뿐
실제 사용자 결정 증거가 아니다. 신규 autonomous fixture는 user approval을 합성하지 않는다.

## 2. contract/schema gate

각 신규 계약에 다음을 확인한다.

- `extra=forbid`, `strict=true`, `allow_inf_nan=false`, `frozen=true`
- unknown field, string→number coercion, NaN/Infinity 거부
- timezone 없는 timestamp 거부
- absolute path, drive path, backslash, `.`, `..`, empty segment 거부
- SHA-256, ID, job/workflow/dispatch/session 형식 검증
- exact RootAuthorization/profile/envelope/budget binding
- checked-in Draft 2020-12 schema와 Pydantic `model_json_schema()` equality
- source, profile, predecessor, budget, artifact bytes의 stale/tamper 거부

## 3. envelope 계획과 compatibility

- explicit delegation이 없으면 autonomous/checkpointed envelope 생성 거부
- initial request SHA-256과 RootAuthorization original request SHA-256 불일치 거부
- requested delivery가 root 범위를 넘으면 거부
- provider scope, gate kind, bounded transformation과 cap 중복/초과 거부
- envelope가 없는 기존 session은 `legacy_without_envelope`이며 파일 생성·migration 없음
- `RootAuthorizationV2` schema와 serialization golden fixture가 변경되지 않음
- `standard`, `background_exterior`, AQ v1과 기존 AQ v2 public regression 통과

## 4. deterministic policy engine

각 routine gate의 passed/failed eligibility fixture를 만든다. controller/LLM supplied `eligible=true`를
신뢰하지 않고 host가 artifact bytes와 current canonical snapshot으로 결과를 재계산해야 한다.

공통 음성 case:

- target bytes 변경, path escape, wrong job/session/root/profile/envelope
- expired/cancelled root 또는 envelope
- unauthorized gate/provider/delivery/transformation
- budget rollback 또는 cap 초과
- missing/duplicate predecessor receipt
- 이미 소비된 authorization 재사용
- eligibility report 변경 뒤 authorize
- authorization publication 후 target/canonical 변경
- user approval 또는 `approved_by=user` 필드 합성 시도
- technical failure category를 approval factory에 전달

## 5. bounded transformation gate

### 5.1 geometry/parameter

object set/target/scope 유지, allowlist-only diff, constraint non-regression, measurable metric improvement,
rollback baseline과 preflight를 모두 통과한 case만 eligible이어야 한다. geometry/UV/reference/target
drift와 regression은 실패한다.

`bounded_parametric_revision` controller promotion은 eligibility 발행과 atomic replacement 직전에 exact
mutable baseline을 전조건으로 재검사한다. 적용 뒤 decision publication은 이미 변경된 baseline에 같은
전조건을 반복하지 않고, exact geometry validation receipt·controller target·candidate SceneSpec과 현재
canonical ModelingPlan/SceneSpec/Blend 일치를 적용 후 조건으로 검사한다. 일반 authorization replay는
동일 시점에 계속 stale로 실패해야 하며, rejected/rolled-back/technical-failed는 원 canonical SHA를
보존해야 한다.

### 5.2 material identity split

- exact clone, paired SceneSpec/ModelingPlan-only diff, exclusive assignment 통과
- object/geometry/topology/transform/dimensions/UV/reference/appearance 불변
- shadow Blender, invariant report, rollback archive와 authority refresh 준비
- 기본 4 및 hard max 8 cap
- policy authority adapter와 specialized user approval adapter 각각 성공
- 두 authority 동시 제출, wrong gate, stale candidate, reuse 거부
- policy authorization이 `MaterialIdentitySplitRootScopeApproval`로 serialize되지 않음
- 기존 explicit approval transaction/crash/rollback regression 통과

### 5.3 material promotion

closure, rebinding, UV/detail preflight, shadow compile, neutral preview, semantic/reference evidence,
critical regression 0, threshold와 rollback baseline의 AND gate를 검사한다. 하나라도 누락되면
policy authorization을 만들 수 없다. 결과는 human-reviewed가 아니라 evidence-based로 기록한다.

### 5.4 delivery

동일한 quality source freeze에서 GLB/FBX exact optimization plan별 authorization을 만든다. 기존 V0.7
user approval path와 신규 AQ policy path를 각각 실행하고, mixed authority/reuse/new format/source
supersession을 거부한다. package와 clean-import evidence가 없으면 completed terminal을 금지한다.

## 6. technical failure gate

dependency closure, manifest, path rebinding, hash projection, serialization, completion map, stale
projection, controller packaging, rollback archive와 deterministic normalization fixture마다 다음을
assert한다.

```text
technical_user_approval_requests == 0
user approval artifact count == 0
policy repair count는 실제 repair가 수행된 경우에만 증가
controller invocation은 필요 없으면 0
복구 불가 시 framework report + blocked/review terminal
```

transient controller system retry는 같은 candidate/request/workspace에서 최대 1회다. 다른 candidate나
새 authority를 묵시적으로 만들지 않는다.

## 7. escalation gate

허용 reason 외 값은 거부한다. reference replacement와 delivery expansion처럼 같은 시점에 알려진
결정은 하나의 request와 하나의 decision payload로 묶는다. 개별 approval request count는 0이어야
한다. 미결정 branch는 current best review bundle로 종료할 수 있어야 한다.

## 8. One-Prompt 시나리오

요청의 A~J acceptance 시나리오를 다음처럼 고정한다.

| ID | 시나리오 | 핵심 assertion |
|---|---|---|
| A | procedural autonomous → IQ → GLB | additional decision 0, technical approval 0 |
| B | bounded identity split → apply → material → IQ | user scope approval 0, policy auth 1, geometry/UV unchanged |
| C | initial ImageGen 허용 | scope expansion 0, additional approval 0 |
| D | ImageGen 미허용 | local fallback 또는 consolidated escalation 하나 |
| E | checkpointed | geometry/material/delivery decision 합계 ≤3, technical 0 |
| F | closure technical failure | user approval 0, framework evidence 존재 |
| G | reference+delivery scope expansion | consolidated request 1, 개별 approval 0 |
| H | promotion 뒤 Blender failure | automatic rollback, canonical restored, user approval 0 |
| I | waiting controller 중 중단/재개 | state/budget/assignment 동일, background claim false |
| J | envelope 없는 legacy session | retroactive authority 0, 기존 explicit 의미 유지 |

## 9. telemetry/KPI benchmark

최소 다섯 representative static-prop case를 실행한다.

1. procedural metal/plastic
2. localized decal/signage
3. detailed wood
4. crystal + emission + alpha
5. shared material bounded identity split

각 report의 counter를 source event/receipt 수에서 다시 계산한다. caller-supplied 합계만 신뢰하지
않는다. autonomous case는 initial 1, additional 0, technical 0, safe terminal, corruption 0을 요구한다.
checkpointed는 additional ≤3, technical 0이다. fixture는 실제 사용자 품질 benchmark와 구분한다.

## 10. public surface와 security

- CLI help와 MCP 함수/signature/config allowlist 동등성
- status/telemetry는 read-only
- policy authorize는 passed current eligibility만 수용
- one-prompt run/resume은 hard action cap 적용
- 어느 surface도 user approval, arbitrary canonical write, destination write, API/SDK/key, task spawn을 제공하지 않음
- source/schema/common docs에 job-specific ID/hash/semantic prefix/execution ID literal 없음

## 11. 실행 순서

1. 신규 contract/schema focused
2. policy/eligibility/authorization/consumption focused
3. envelope/telemetry/escalation/one-prompt focused
4. identity-split/material/delivery adapter focused
5. public/catalog/instruction/literal/summary parity
6. existing AQ v2, Material Closure, Identity Split, ImageGen focused regression
7. full pytest와 Ruff
8. doctor, Blender compatibility, instruction checker, schema check, repository summary check
9. 가능한 실제 Blender 5.0.1 bounded gate
10. `git diff --check`

## 12. 활성화 판정

테스트 통과는 profile 자동 활성화가 아니다. local-only activation은 같은 clean baseline의 서로 다른
primary reference 5개, actual One-Prompt/skill-adapter E2E, additional decision 0 목표, technical approval
0, corruption 0, rollback integrity와 exact human disposition을 요구한다. 5개 중 최소 1개는 portable
GLTF package와 clean-import round trip을 통과해야 한다.

Activation focused gate는 추가로 다음을 검증한다.

- strict production candidate index와 normal campaign outcome index가 서로 다른 계약일 것
- adapter/One-Prompt/RootAuthorization/telemetry/reference binding이 stale·tampered·mismatched일 때 제외될 것
- Blender 5.0.1 7-pass manifest와 disposition beauty가 exact하게 같을 것
- production은 `accepted`, usable review는 `needs_revision` disposition만 허용할 것
- duplicate reference outcome은 ambiguous로 fail-closed할 것
- historical `reconciled_failed_recovery`는 campaign 성공으로 계산하지 않을 것
- local blocker, excluded capability와 future limitation을 서로 다른 machine field로 유지할 것
- exact `HumanLocalActivationAcceptance`가 없으면 publication-ready가 되지 않을 것
- publication writer가 exact clean baseline과 readiness hash를 재검증하고 acceptance를 한 번만 소비할 것
- publication 파일이 untracked/modified/invalid이면 profile은 계속 disabled로 fail-closed할 것
- 고정 publication이 current `HEAD`에 추적된 뒤에만 exact activation evidence와 함께 `verified_active`일 것

ImageGen overlay는 실제 built-in invocation과 semantic/material benchmark가 추가로 필요하며 base
local-only 5개 캠페인의 필수 capability가 아니다.
