# Skill Orchestration 0.1 아키텍처

## 목적

Skill Orchestration `0.1.0`은 프로젝트 `0.9.0` 위에 추가되는 사용자·추적 계층입니다. 기존 V0.8 workflow와 AQ v2 One-Prompt가 실행 순서, 승인, promotion, rollback, budget의 유일한 권위를 계속 가집니다. 스킬 계층은 그 상태를 읽고 다음 단계 지침을 고르며, 선택 근거와 실행 전후 상태를 불변 증거로 남깁니다.

```text
사용자 최초 요청
  ├─ standard-asset-cycle
  │    └─ V0.8 child workflow(s)
  └─ aq-one-prompt-orchestrator
       └─ AQ v2 One-Prompt session

각 호출
  → snapshotted registry/bundle
  → exact state 기반 route decision
  → 기존 host 실행
  → immutable execution receipt
```

## 공개 진입점

- `standard-asset-cycle`: V0.4 형상, V0.5 재질, V0.6 QA, 선택적 V0.7 package를 하나의 복합 run으로 관리합니다.
- `aq-one-prompt-orchestrator`: 기존 AQ v2 One-Prompt를 reference, geometry, material candidate, material closure, quality, delivery, recovery 단계로 투영합니다. AQ v2는 계속 `disabled_experimental`입니다.

나머지 21개 스킬은 단계/호환성 스킬입니다. 기존 13개 스킬 이름과 독립 호출 의미는 유지됩니다. Standard용 사용자 승인 스킬은 AQ route에 포함되지 않습니다.

## 레지스트리와 invocation authority

`.agents/skills/registry.json`이 skill ID, 상태, 실행 mode, dependency, route key, 허용 MCP 도구의 source of truth입니다. 진입 스킬 호출은 레지스트리에 선언된 transitive dependency만 허용합니다. 실행 중 임의 스킬을 추가할 수 없습니다.

계획 시 다음을 `workspaces/<job>/skill_runs/<run-id>/`에 복사합니다.

- exact registry snapshot
- bundle에 포함된 각 `SKILL.md`와 supporting resource
- `SkillBundleManifest`

resume은 live `.agents/skills/`가 아니라 이 snapshot을 재검증합니다. snapshot이 변경되면 fail-closed입니다.

## Standard composite

지원 goal은 다음과 같습니다.

- `new_asset_to_qa`
- `polish_existing_to_qa`
- `material_refresh_to_qa`
- `qa_repair_cycle`
- `full_cycle_to_package`

새 자산 기본 흐름은 기존 V0.8 `full + preview_only`를 사용하므로 V0.4→V0.5→V0.6을 한 workflow에서 수행하고 V0.7은 추가하지 않습니다. 기존 자산은 목적에 따라 immutable child workflow를 연결합니다.

`smart`는 geometry 전후의 exact snapshot에서 material ID/assignment, localized surface detail, UV fingerprint, MaterialPlan 존재 여부를 비교해 `MaterialImpactReport`를 게시합니다. 변경 없음이 입증될 때만 V0.5를 건너뛰며 V0.6은 항상 다시 실행합니다. 비교 불가 상태는 V0.5 필요로 fail-closed합니다. `force_all`은 V0.4/V0.5/V0.6을 모두 새로 수행합니다.

`qa_repair_cycle`은 QA 뒤 자동 수정하지 않습니다. 해당 QA run의 candidate·RevisionPlan·소비된 user approval·application report와 선택적 convergence를 다시 검증한 `GuardedRevisionContinuation`이 현재 SceneSpec 결과 hash와 일치할 때만 같은 composite가 새 QA child를 계획합니다. 단순 SceneSpec 파일 변경은 continuation 권한이 아닙니다. 기본 revision budget은 1, 최대 5입니다.

V0.9 read-only audit는 skill bundle, adapter state, route/receipt chain과 guarded continuation의 모든 exact artifact를 검증합니다. 종료되지 않은 skill run이 있는 job은 workspace archive 대상이 아닙니다.

## AQ route

AQ adapter는 current `AutonomyStateV2`, `next_action`, exact controller result/tool profile, material closure companion을 읽어 하나의 route만 선택합니다.

- reference: `collect_reference`
- geometry: geometry controller/validation
- material: material controller/validation
- closure: closure-bound material controller evidence
- quality: IQ 실행 또는 review terminal
- delivery: source freeze, plan, V0.7 boundary, terminal
- recovery: technical/genuine escalation 또는 blocked/failed/cancelled terminal

technical recovery는 user approval을 만들지 않습니다. policy authorization은 user approval로 표시되지 않습니다. repository는 Codex task를 만들거나 앱 종료 뒤 실행을 주장하지 않습니다.

## 권위 분리

`SkillRouteDecision`과 `SkillExecutionReceipt`에는 `canonical_write_authority=false`, `approval_authority=false`가 고정됩니다. 실제 쓰기는 기존 V0.8/AQ host path만 수행합니다. 이 companion은 CBM-INV-045..066, 101..112, 157..192와 root safety sentinel을 그대로 적용하며 과거 evidence를 migration하거나 재분류하지 않습니다.
