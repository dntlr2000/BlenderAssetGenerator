# V0.8 테스트 계획

## 목적

V0.8 검증은 “짧은 요청이 무조건 완성 자산을 만든다”를 증명하는 것이 아니다. 요청을 올바른 기존 단계로 라우팅하고, 승인·신선도·재개 경계를 우회하지 않으며, 기존 V0.4~V0.7 기능을 깨뜨리지 않았음을 검증한다.

## Gate 1 — Python과 계약

```powershell
uv run pytest
uv run ruff check .
```

필수 항목:

- V0.8 Pydantic 모델과 checked-in JSON Schema 일치
- 모든 계약 `additionalProperties: false`
- project `0.8.0`과 workflow `0.8.0`
- SceneSpec `0.2.0`, Material `0.5.0`, QA `0.6.0`, Portable `0.7.0` 유지
- CLI 명령과 MCP allowlist 공개

## Gate 2 — 라우팅과 job 격리

- 새 레퍼런스가 새 job의 `new_asset`으로 라우팅됨
- 기존 job은 primary reference hash가 같아도 명시적 `new_asset`을 파일 생성 전에 거부함
- 새 작업 기본 scope가 `proxy_only`
- 누락된 `reference_content_scope`는 legacy-compatible `full_reference`로 읽힘
- `primary_object_only`는 명시적 `target_subject` 없이는 job을 만들지 않음
- object-only scope와 target이 job/request/plan/state에 동일하게 보존됨
- 기존 job의 scope나 target 변경 요청은 새 job을 요구하며 fail-closed
- object-only authored ModelingPlan은 모든 객체의 primary/supporting 역할을 요구
- object-only SceneSpec은 context 및 역할 없는 객체를 build 전에 거부
- object-only V0.6 mask는 관찰된 primary/supporting evidence bbox로 제한됨
- 기존 job에 다른 primary reference를 넣으면 파일 변경 전에 거부
- 기존 job의 모호한 요청은 명시적 intent 요구
- 승인된 실내 다각도 요청은 `interior_visual_qa`로만 라우팅하고 외관 `visual_qa`와 구분
- auxiliary view는 staging 뒤 `add_view`로 승격
- 서로 다른 job과 workflow의 파일 경로가 격리됨
- `standard`가 생략된 legacy 요청·route·plan·state를 재작성 없이 읽음
- `background_exterior`가 명시적으로 선택된 경우에만 활성화됨
- `preview_only`와 `portable_package`가 request/route/plan/state에서 동일하게 보존됨
- 새 fast plan에 optional `fast_quality_policy=review_delivery_v2`가 기록됨
- legacy plan은 해당 필드가 없어도 기존 규칙으로 읽히고 재작성되지 않음

## Gate 3 — 상태와 신선도

- request/route/plan 불변성
- 같은 파일을 다시 읽어 상태를 결정론적으로 재구성
- agent completion이 plan/input/output hash와 일치할 때만 완료
- dependency 또는 output 변경 시 completion이 stale
- 일반 승인이 현재 artifact fingerprint와 일치할 때만 완료
- stale 승인과 marker가 다음 단계를 열지 않음
- material scaffold와 authored candidate가 서로 다른 workflow-owned 경로를 사용
- authored candidate 변경 뒤 canonical promotion을 해도 scaffold/author completion은 current
- material build가 공유 `.blend`를 갱신해도 앞선 geometry snapshot/receipt는 current
- 다른 workflow가 preview, PDF 또는 `qa/latest.json`을 갱신해도 exact 과거 receipt는 유효
- 계획되지 않은 SceneSpec 또는 canonical MaterialPlan 변경은 stale/blocked
- artifact ownership 충돌은 `orchestration_artifact_conflict`로 기록되고
  `requires_standard_workflow`로 잘못 분류되지 않음

## Gate 4 — 실패·잠금·재개

- live lock이 concurrent writer를 거부
- expired lock은 이력 보존 후 복구
- running attempt가 남으면 `InterruptedAttempt`로 종료
- host 실패가 고유 receipt에 기록됨
- 명시적 `--retry-failed` 없이는 재시도되지 않음
- retry 시 기존 attempt를 보존하고 새 attempt 생성
- 취소가 기존 산출물을 삭제하지 않음
- 취소된 workflow 재개 거부

## Gate 5 — 승인 경계

- 프록시·상세·swatch·QA·최종 package 일반 승인
- InteriorScope 일반 승인 대체 불가
- Interior QA exact camera-plan 일반 승인 대체 불가
- V0.6 visual revision 일반 승인 대체 불가
- V0.7 optimization 일반 승인 대체 불가
- optimization plan이 LOD/collider 설정을 표시한 뒤 exact hash 승인을 기다림

### Background exterior approval matrix

- `preview_only` plan에는 일반 승인과 portable 단계가 없음
- `portable_package` plan에는 일반 승인이 없고 `optimization_plan` 전용 승인만 정확히 1개 존재
- package/roundtrip은 optimization 승인 뒤에만 실행됨
- `portable.final_approval` 생략은 runtime parity 승인으로 해석되지 않음
- 빠른 경로는 InteriorScope, interior QA, visual revision, view replacement와 handoff 승인을 생성하거나 대체하지 않음

## Gate 5.1 — Background exterior 제한

- 새 `concept` 자산의 단일 primary reference만 허용
- `measured`, scale anchor, auxiliary/replacement view, enabled interior, constraints는 fail-closed
- 외부 provider budget은 0, texture cap은 512, 직접 QA iteration은 정확히 1
- generated QA target과 자동 revision 단계가 plan에 없음
- geometry는 `geometry.background_author` 한 단계에서 canonical SceneSpec을 한 번만 작성
- 위험 발견 시 agent completion이 기록되지 않고 `requires_standard_workflow` 경계에서 멈춤
- high-severity visual finding은 `quality_status=needs_revision`으로 review delivery를
  완료하고 `requires_standard_workflow`로 변조하지 않음
- primary evidence를 신뢰할 수 없으면 `quality_status=unscorable`로 완료하고
  품질 합격을 주장하지 않음
- `requires_standard_workflow`는 interior, measured/constraint, rig, animation,
  gameplay, engine-specific 요구와 unsafe ambiguity 같은 실제 scope·안전 위험만 차단
- package continuation은 exact preview plan·terminal·QA run·source/build fingerprint를 V0.7 전에 재검증
- 기존 `standard` proxy smoke의 단계 순서와 승인 gate는 변하지 않음
- preview terminal은 `status=completed`, `milestone=delivered_for_review`로 구분됨
- 완료된 preview의 package 확장은 새 workflow의 `geometry.prerequisite`에서 시작하며 이전 workflow를 변경하지 않음
- 기존 job의 auxiliary view, enabled InteriorScope, interior semantic object와 constraints는 package fast lane에서 거부됨
- 외부 provider 또는 512 px 초과 image manifest는 material agent completion에서 거부됨
- `standard` 호출의 명시적 fast-only `delivery_scope`는 거부되고 legacy 누락 필드는 계속 읽힘

## Gate 5.2 — bounded pre-QA fit과 역할

- workflow-owned initial SceneSpec candidate와 run-owned role map 생성
- explicit `qa_role:*` tag를 우선하고 deterministic semantic/parent fallback 적용
- `primary`, `supporting`, `decorative`, `ground_background`를 구분
- ground/background object-ID mask는 primary silhouette와 bbox metric에서 제외
- baseline을 포함해 최대 3개 evidence, 즉 refinement 최대 2회
- 각 attempt가 candidate SHA-256, input fingerprint, 허용 변경 경로,
  before/after, metric, 선택/rollback 이유를 기록
- 개선된 strict candidate만 canonical SceneSpec으로 한 번 promotion
- 비개선 또는 diagnostic 실패 시 exact baseline canonical 유지
- semantic/material ID, custom-mesh vertex, InteriorScope와 material contract 불변
- fit diagnostic은 canonical QA run 수에 포함되지 않음
- 최종 QA run은 정확히 1개이고 pass는 정확히 7개

## Gate 5.3 — execution/quality delivery

- `passed`: 실행 완료, quality accepted, standard revision 권장 없음
- `needs_revision`: 실행 완료, quality 미합격, primary/supporting finding과 standard
  revision target 보존
- `unscorable`: 실행 완료, quality 미판정, 누락·불신 evidence와 권장 조치 보존
- 세 경우 모두 QA JSON, QA PDF/sidecar, combined PDF/sidecar 생성
- PDF 첫 페이지가 non-passing status를 숨기지 않음
- machine quality report가 exact source/build/QA/role/fit hash에 결속됨
- 계획되지 않은 SceneSpec, candidate, role map, promotion receipt 또는 QA evidence
  변경은 `orchestration_artifact_conflict`
- 후속 material build, preview, PDF와 latest pointer 교체는 완료된 상위 step을
  retroactive stale로 만들지 않음

## Gate 6 — 목적지 경계

- engine-neutral adapter만 available
- Unity/Unreal/custom은 unsupported
- 미지원 목적지가 portable package terminal boundary를 유지
- engine prefab/actor, runtime shader, runtime collision/LOD parity를 성공으로 기록하지 않음

## Gate 7 — V0.7 Blender 회귀

격리된 `geometry_showcase`로 다음을 재검증한다.

```text
material → build → render → inspect → validate
→ V0.7 preflight
→ LOD/collider plan 표시
→ exact hash approval
→ optimize
→ GLB/FBX/OBJ package
→ clean-import round trip
→ export PDF
```

`needs_revision` source quality도 V0.7 preflight/review까지 진행하되 review plan과
optimization review에 primary high, decorative warning, 제한과 standard
revision 권장을 포함해야 한다. 승인 없이는 optimize/package를 실행하지 않는다.

기존 `first_reference_test`는 자동 gate에 사용하지 않는다.

## 완료 조건

- 전체 Python test 통과
- Ruff 통과
- V0.8 isolated smoke의 실제 fast preview가
  `completed` / `delivered_for_review`로 종료
- isolated quality fixtures가 `passed`, `needs_revision`, `unscorable`을 각각 검증
- pre-QA fit refinement가 최대 2회이고 non-improvement rollback이 통과
- material scaffold → authored candidate → exact completion → canonical promotion
  → validation → material build/inspect/swatch/PDF 통과
- 정확히 한 번의 direct seven-pass QA, generated target 없음, 자동 revision 없음
- fast portable workflow가 exact V0.7 optimization-plan 승인에서 정지
- 승인 뒤 package와 clean-import round trip 통과
- 격리된 background preview/package plan smoke 통과
- V0.7.4 Blender 5.0.1 isolated gate 회귀 통과
- 사용자 workspace와 canonical authoring 파일 변경 없음
- 미지원 adapter를 지원된 것처럼 보고하지 않음
