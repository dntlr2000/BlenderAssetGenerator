# Skill Orchestration 0.1 테스트 계획

## 계약·레지스트리

- 12개 strict Pydantic model ↔ checked-in Draft 2020-12 schema parity
- 정확히 두 entry skill
- dependency 존재, DAG, mode 격리, route uniqueness
- skill/resource path containment, regular-file, front-matter ID 일치
- registry allowed tool이 MCP server와 project allowlist에 모두 존재

## snapshot·trace

- 계획 시 registry와 transitive bundle snapshot 생성
- live skill 변경 뒤에도 snapshot 기반 resume
- snapshot/route/source-state/receipt hash 변경 시 fail-closed
- receipt sequence와 predecessor SHA-256 연속성
- path escape, symlink/reparse, missing resource, duplicate receipt 거부

## Standard

- 새 자산 `full + preview_only`가 QA review를 포함하고 portable step은 제외
- agent/generic/specialized approval에서 정지
- failed step은 `retry_failed=true` 없이 재시도하지 않음
- `smart` MaterialImpactReport의 assignment/surface-detail/UV/MaterialPlan 판정
- `force_all`의 V0.5 강제 실행
- material 변경 뒤 fresh QA
- guarded revision의 source QA, candidate, plan, consumed approval, application/convergence, 전후 SceneSpec hash와 QA iteration 1..5 budget
- consumed `qa.review` 뒤 별도 exact human quality disposition, stale fingerprint 거부, accepted 전 V0.7 미생성, exhausted needs_revision safe terminal
- direct 개선·silhouette 비회귀 candidate가 오직 stale V0.5 surface-detail binding 때문에 nonpromotable일 때만 exact state hash·무승격승인·unchanged canonical을 검증한 manual guarded reroute, 동일 QA 연산 승인, fresh V0.5/V0.6 강제
- full-cycle V0.7 approval과 clean-import boundary 보존
- cancel은 child/trace evidence를 삭제하지 않음

## AQ

- default disabled, explicit delegation과 experimental opt-in 필요
- state/controller profile별 unique route
- material candidate와 closure 분리
- technical failure가 user approval request를 만들지 않음
- controller/IQ/genuine escalation/current-task stop
- same plan/state/budget/assignment snapshot resume
- delivery/review/blocked/failed/cancelled terminal 의미 보존

## 회귀·실행 환경

집중 테스트 뒤 V0.8, Approval Envelope, One-Prompt, Material Closure/Identity Split, public catalog 회귀를 수행합니다. 그 뒤 전체 Ruff/pytest/doctor/blender-compat/instruction/catalog/diff gate를 실행합니다. Blender quality claim은 Blender 5.0.1 실제 실행 receipt 없이는 하지 않습니다.
