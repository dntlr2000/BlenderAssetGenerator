# AQ Activation Readiness 0.1

AQ Activation Readiness `0.1.0`은 `autonomous_static_prop_v2`를 활성화하지 않는
additive `disabled_experimental` companion이다. 프로젝트 버전 `0.9.0`, canonical
SceneSpec `0.2.0`, 기존 AQ v1/v2 evidence 의미는 변경하지 않는다.

## 계약 계층

```text
clean Git checkpoint
  -> ActivationSourceManifest 0.1.0
  -> final validation receipts
  -> ActivationBaseline 0.1.0
  -> explicit candidate registry
  -> ActivationAssetEligibilityReport 0.1.0
  -> ActivationAssetCandidateIndex 0.1.0
  -> ActivationReadinessReport 0.1.0
```

`HumanActivationAcceptance`는 위 baseline, candidate index, distinct primary-reference
SHA-256 집합, profile/version, operation, reviewer, expiry와 single-use 의미를 exact하게
결속한다. 이는 routine `PolicyAuthorization`이 아니며 서로 대체할 수 없다.

## Source checkpoint

`ActivationSourceManifest`는 clean commit과 Git tree, canonical Git blob bytes, schema,
controller/promotion 구현, profile registry, `uv.lock`, Python/uv, dependency-resolution
receipt, Blender 5.0.1 executable/version receipt를 결속한다. `workspaces`, `reports`,
`test_runs`, pytest/uv cache와 audit-only 경로는 제외 이유를 기록한다. 알 수 없는
untracked class는 자동 제외하지 않고 실패시킨다.

## Asset 집계

집계기는 filesystem 전체를 검색하지 않는다. 호출자가 제공한 authoritative registry의
exact eligibility report만 읽는다. test/copy/shadow/preflight/staging/recovery/audit/review
evidence와 failed/blocked/cancelled/nonterminal, stale/tampered/unbound, 다른 baseline의
evidence는 machine-readable reason과 함께 제외한다.

기본 asset identity는 primary-reference content SHA-256이다. 동일 hash의 revision은 한
group으로 묶으며, 유일한 eligible canonical representative가 없거나 terminal success가
충돌하면 group 전체를 `ambiguous`로 제외한다.

## 쓰기 권한 경계

서비스는 immutable manifest, baseline, eligibility, index, readiness evidence만
`reports/activation_readiness/` 아래에 create-once로 쓴다. 다른 source 경로와
`workspaces/*/input`은 출력 대상으로 거부한다. canonical job state, profile registry
상태, campaign, package 또는 destination을 쓰는 API는 제공하지 않는다.
CLI/MCP/controller profile에도 profile activation writer를 노출하지 않는다.

가능한 readiness 결과는 다음뿐이다.

- `ready_for_campaign_but_not_activated`
- `source_checkpoint_required`
- `validation_blocked`

어떤 결과도 production activation 또는 human acceptance를 합성하지 않는다.
