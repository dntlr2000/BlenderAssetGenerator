# AQ Approval KPI 0.3

## 1. 목적

승인 최소화는 README 문구가 아니라 session event와 immutable receipt에서 다시 계산 가능한
machine-readable KPI로 판정한다. 품질 점수, 사용자 만족도, runtime parity와 approval count는 서로
다른 지표다.

## 2. 필수 counter

사용자 계층:

```text
initial_user_requests
additional_user_decisions
geometry_user_approvals
material_user_approvals
delivery_user_approvals
scope_user_approvals
budget_user_approvals
destination_user_approvals
technical_user_approval_requests
```

정책·실행 계층:

```text
routine_policy_authorizations
technical_policy_repairs
controller_invocations
canonical_promotions
rollbacks
imagegen_generations
quality_evaluations
delivery_runs
quality_terminals
delivery_terminals
```

terminal 계층:

```text
terminal_type
total_elapsed_actions
budget_consumed
canonical_corruption_count
```

counter는 연결된 request/decision/authorization/receipt/state/terminal artifact의 unique ID와 exact
hash에서 계산한다. duplicate retry나 동일 artifact 재조회는 새 event가 아니다.

## 3. mode별 acceptance

### autonomous

```text
initial_user_requests == 1
additional_user_decisions == 0
technical_user_approval_requests == 0
terminal_type in {production_delivery, review_bundle}
canonical_corruption_count == 0
```

genuine escalation은 안전한 terminal이지만 zero-additional-decision success 분모와 분자를 별도로
기록한다.

### checkpointed

```text
initial_user_requests == 1
additional_user_decisions <= 3
technical_user_approval_requests == 0
canonical_corruption_count == 0
```

### interactive

기존 behavior의 event/approval count와 회귀가 일치해야 한다. approval 감소 목표를 적용해 기존 exact
승인 의미를 바꾸지 않는다.

## 4. regression 지표

다음 중 하나라도 발생하면 approval-policy regression이다.

- `technical_user_approval_requests > 0`
- 하나의 escalation 시점에 request가 둘 이상
- 같은 authorization의 소비가 둘 이상
- policy authorization이 user approval로 분류됨
- initial delegation이 future candidate approval로 분류됨
- review bundle이 production delivery로 집계됨
- canonical corruption 또는 rollback 뒤 hash 불일치

## 5. 대표 benchmark manifest

최소 다섯 case를 다음 category로 유지한다.

| case | 핵심 capability | 기대 terminal |
|---|---|---|
| procedural metal/plastic | local procedural material | production 또는 review |
| localized decal/signage | exact text/local composition | production 또는 genuine escalation if text absent |
| detailed wood | spatial local derivation | production 또는 review |
| crystal/emission/alpha | mixed portable loss evidence | production 또는 review |
| shared material split | bounded identity split | production 또는 review |

가능하면 decorative weapon, transparent/opaque mix, mechanical assembly, user image texture와 ImageGen
hybrid를 추가한다. 각 case는 representative/synthetic/actual source 분류, human review 상태와 Blender
실행 상태를 별도 필드로 가진다.

## 6. aggregate KPI

```text
zero_additional_decision_rate
  = autonomous production/review sessions with additional_user_decisions=0
    / eligible autonomous production/review sessions

technical_approval_free_rate
  = sessions with technical_user_approval_requests=0 / all benchmark sessions

safe_terminal_rate
  = production + review + genuine escalation + framework-blocked terminals
    / started sessions

canonical_integrity_rate
  = sessions with canonical_corruption_count=0 / started sessions
```

분모가 0이면 pass나 100%로 만들지 않고 `unscorable`로 기록한다. cancelled test fixture와 intentional
failure injection은 normal-success KPI와 별도 cohort다.

## 7. activation review 기준

local-only AQ v2 activation review에는 one-prompt actual E2E, 실제 자산 5개 이상, zero-additional-
decision 목표, technical approval 0, safe terminal 100%, canonical corruption 0과 rollback 무결성이
필요하다. Unity runtime parity는 local-only activation의 필수 지표가 아니다.

ImageGen overlay는 initial scope/budget 준수, 실제 built-in ImageGen E2E, semantic review 경계,
material benchmark와 불필요한 호출 억제 지표가 추가로 필요하다. 이 문서의 representative fixture
통과만으로 profile을 활성화하지 않는다.

## 8. 현재 대표 fixture 상태

2026-08-15 구현 전에는 신규 telemetry contract, event replay와 최소 5개 approval benchmark가
`unverified`였다. 2026-08-16 focused gate에서 contract/schema/KPI/public surface 묶음은
`25 passed`했고, 현재 repository에는
`benchmarks/aq_approval_kpi/representative_asset_runs.json`이 있으며 필수 5개 유형과 ImageGen hybrid를
합친 6개 대표 asset, autonomous 6회와 checkpointed 1회의 총 7개 run counter를 기록한다.

이 manifest는 `fixture_kind=representative_contract_fixture`,
`measurement_method=deterministic_contract_validation`, `actual_asset_e2e_verified=false`,
`real_blender_execution_verified=false`, `human_review_performed=false`, `activation_evidence=false`를
고정한다. 따라서 deterministic contract/KPI acceptance는 verified지만 실제 사용자 자산의
one-prompt 최종 품질,
production activation 또는 사람 검토를 증명하지 않는다. 실행된 테스트 수치와 남은 `unverified`는
`VERIFICATION_AQ_APPROVAL_ENVELOPE_KO.md`를 권위로 한다.
