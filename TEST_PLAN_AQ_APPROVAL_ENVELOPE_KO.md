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

테스트 통과는 profile 자동 활성화가 아니다. local-only activation은 one-prompt actual E2E,
실제 자산 5개 이상, additional decision 0 목표, technical approval 0, safe terminal 100%, corruption 0과
rollback integrity의 별도 review를 요구한다. ImageGen overlay는 실제 built-in invocation과 semantic/
material benchmark가 추가로 필요하다.
