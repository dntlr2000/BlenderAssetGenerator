# Autonomous Quality Extension 0.1.0 마이그레이션 정책

## 1. 결론

AQ는 기존 job을 자동 migration하지 않는다. SceneSpec `0.2.0`, Reference/Constraint
`0.4.0`, Material/Shader `0.5.0`, Visual QA `0.6.0`, Portable Asset `0.7.0`, Workflow
`0.8.0`, Production/Stabilization/Handoff `0.9.0` 증거는 원본 그대로 유지한다.

Autonomy, Reference Evidence, Integrated Quality, MaterialGraph, Structural Geometry,
Assembly/Topology companion `0.1.0`은 opt-in 병렬 계약이다. 새 디렉터리나 companion
artifact가 없는 legacy job도 정상이며, 그 부재만으로 audit 실패가 되지 않는다.

## 2. 호환성 표

| 자산/계약 | 기존 읽기 | 자동 변환 | AQ 기본 경로 |
|---|---:|---:|---|
| SceneSpec `0.2.0` | 예 | 아니오 | canonical 및 legacy candidate/build 입력 |
| SceneSpec V03 `0.3.0` | 병렬 loader/helper | 아니오 | optional AQ structural candidate와 별도 derived migration |
| V0.4~V0.9 JSON | 예 | 아니오 | 기존 standard workflow가 사용 |
| legacy job without AQ | 예 | 해당 없음 | 기존 동작 유지 |
| legacy approval/receipt | 예 | PolicyAuthorization으로 변환 금지 | 기존 의미 유지 |

기존 `standard`와 `background_exterior`의 default SceneSpec은 `0.2.0`이다. AQ profile을
선택했다고 해서 `0.3.0`으로 바뀌지 않는다.

## 3. SceneSpec V03의 현재 구현 범위

`structural_geometry.migration`에는 다음 strict helper가 있다.

- `create_v03_migration_plan(source)`
- `apply_v03_migration_plan(source, candidate, plan)`

plan은 source `0.2.0`과 candidate `0.3.0`의 exact hash를 결속한다. 현재 자동 변환은 기존
필드의 의미를 보존하고 geometry intent companion을 명시하는 제한된 변환이다. V03
structural candidate는 loft/sweep/boolean/multi-loop/GN recipe를 deterministic mesh
payload와 `.blend`로 materialize할 수 있다.

중요한 현재 경계:

- 공개 CLI `scene-spec-v03-migration-plan` / `scene-spec-v03-migration-apply`와 동등 MCP
  `plan_scene_spec_v03_migration` / `apply_scene_spec_v03_migration`이 제공된다.
- AQ legacy assignment는 `SceneSpec 0.2.0`을 strict load한다. optional structural assignment는
  full V03 candidate를 candidate-owned recipe/mesh/receipt/`.blend`로 materialize한 뒤 기존
  build가 읽는 path-backed V02 candidate로 compile한다.
- V03 materializer가 legacy canonical SceneSpec을 자동 교체하지 않는다.
- apply 명령도 `structural_migrations/<migration-id>/applied/scene_spec_v03.derived.json`과
  exact receipt만 생성하며 `analysis/scene_spec.json`을 변경하지 않는다.
- 따라서 사용자는 기존 job에서 “AQ를 켜면 canonical이 V03으로 자동 migration된다”고
  가정하면 안 된다. runtime candidate materialization과 public derived migration은 모두
  canonical promotion과 별개다.

## 4. 현재 공개된 명시적 derived migration 절차

현재 공개 표면은 canonical promotion이 아닌 derived migration이다.

1. canonical SceneSpec `0.2.0` 파일과 strict model representation의 SHA-256을 읽는다.
2. `scene-spec-v03-migration-plan`이 source/candidate file hash를 포함한 immutable plan과
   strict `0.3.0` candidate를 새 run-owned 디렉터리에 만든다.
3. 사용자는 보고된 migration plan file의 exact SHA-256을 확인한다.
4. `scene-spec-v03-migration-apply --exact-plan-sha256 <SHA256>`가 source, plan, candidate
   hash를 다시 검증한다.
5. 적용은 derived `0.3.0` copy와 receipt를 원자적으로 게시한다.
6. 동일 migration ID 재사용, stale source/candidate/plan, 잘못된 hash는 fail-closed다.
7. canonical SceneSpec, authoring `.blend`, geometry와 기존 workflow는 바뀌지 않는다.

개발·진단용 CLI 예시는 다음과 같다. 일반 AQ 실행에 필수 단계는 아니다.

```powershell
uv run cbm scene-spec-v03-migration-plan <JOB_ID> <MIGRATION_ID>
uv run cbm scene-spec-v03-migration-apply <JOB_ID> <MIGRATION_ID> `
  --exact-plan-sha256 <EXACT_PLAN_SHA256>
```

derived V03 copy를 canonical로 승격하는 공개 절차는 구현하지 않았다. 향후 승격 기능을
추가한다면 별도 승인, staging build/inspect/validate, history archive, rollback과 회귀
검증이 필요하며 현재 apply 명령의 의미를 바꾸면 안 된다.

현재 public plan/apply만으로 외부 geometry payload, `.blend` materialization, interior,
assembly, material 또는 surface-detail roundtrip까지 검증됐다고 간주하지 않는다. 구조
builder 실기동은 별도 structural materialization gate의 책임이다.

## 5. 기존 job을 AQ로 이어가기

AQ는 새 standard production dispatch를 만드는 신작 정적 소품 경로로 설계됐다. 현재
`autonomy-plan`은 다음 조건을 요구한다.

- 새 unique lowercase job ID
- `concept`
- `primary_object_only`
- 명시적 `target_subject`
- static hard-surface 또는 일반 static prop
- primary reference exact SHA-256
- underlying execution policy `standard`
- output profile `portable_gltf`
- `autonomous_static_prop_v1`

기존 job/workflow를 AQ로 제자리 변조하는 public migration 명령은 없다. 기존 자산은 기존
standard workflow로 유지하거나, 별도 검토된 migration/intake 경로를 사용해야 한다.

다음 요구는 AQ opt-in 범위를 벗어난다.

- interior 또는 interior QA
- measured/blueprint/constraint
- rig, skinning, animation, gameplay
- engine-specific prefab/actor 또는 destination project write
- external network provider
- arbitrary Blender Python/node graph
- CAD/B-Rep 지원 주장
- reference/scope/target 교체
- profile hard limit 확대

## 6. 승인과 authorization 보존

- 과거 WorkflowApproval, RevisionApproval, OptimizationApproval, InteriorScopeApproval,
  HandoffApproval을 PolicyAuthorization으로 변환하지 않는다.
- PolicyAuthorization을 `approved_by=user`로 기록하지 않는다.
- 각 authorization은 exact root/profile/budget/gate target에 결속되고 single-use다.
- 처음 저장한 authorization도 즉시 reload한 뒤 dependency, predecessor, single-use와 파일
  hash identity까지 full validation해야 side effect를 허용한다.
- 기존 blocked/cancelled/failed workflow를 새 policy로 재분류하거나 자동 resume하지 않는다.
- AQ 세션 cancellation은 미래 action만 중단하고 기존 canonical/immutable evidence를
  삭제하지 않는다.

## 7. Material과 quality companion

MaterialGraphSpec `0.1.0`은 MaterialPlan/ShaderRecipe `0.5.0`을 대체하지 않는다. 기존
material workflow는 그대로 읽으며 AQ material round가 만든 candidate도 strict host
promotion을 거쳐 기존 canonical 위치로 들어간다. `autonomous_static_prop_v1`은 기본 최대
2회의 material round를 허용하지만 MaterialGraphSpec을 mandatory canonical input으로 만들지
않는다.

IntegratedQualityReport `0.1.0`은 VisualQAReport `0.6.0`을 바꾸지 않는다. legacy direct
score를 그대로 인용하고, 새 네 축과 hard gate를 companion으로 기록한다. 기존 job에 IQ가
없으면 그 job의 과거 V0.6 증거가 무효가 되는 것이 아니다.

## 8. rollback과 recovery

- canonical promotion 직전에 source hash를 다시 검증한다.
- 이전 canonical은 history에 보존한다.
- candidate의 non-improvement/regression 또는 compare-and-swap 실패는 canonical을
  교체하지 않거나 exact archive/best-known으로 복원한다.
- 완결 transition/receipt를 덮어쓰지 않는다.
- incomplete staging은 삭제하지 않고 `interrupted_staging`으로 옮긴다.
- timeout/process interruption만 canonical write 전에 동일 input으로 최대 1회 retry한다.
- schema/validation/topology/deterministic Blender 오류는 자동 retry하지 않는다.
- cycle, plateau, repeated failure 또는 budget 종료 시 안전한 best-known evidence가 있으면
  review-only bundle로 라우팅하며 quality pass나 추가 budget을 합성하지 않는다.

Windows 장경로 package/handoff는 generation과 V0.9 postflight가 같은 package-relative
recursive digest를 사용한다. 이는 정상 evidence의 hash parity를 위한 호환 수정이며 실제
누락·추가·escape·stale·tamper 검사는 약화하지 않는다. standalone structural materializer의
임의 260자 초과 경로 제한까지 제거한 것은 아니다.

## 9. 호환성 검증 체크리스트

전체 migration/compatibility 판정에는 다음이 필요하다.

```text
[ ] 기존 SceneSpec 0.2 fixture 로딩
[ ] 기존 build/render/inspect/validate
[ ] standard/background workflow 회귀
[ ] manual V0.6와 bounded convergence 회귀
[ ] V0.7 package/roundtrip 회귀
[ ] V0.9 production/audit/handoff 회귀
[ ] legacy job without AQ audit
[ ] V03 strict round trip와 explicit plan hash test
[ ] V03 공개 plan/apply derived-only와 canonical 무변경
[ ] V03 Blender materialization
[ ] 기존 user approval 의미 불변
[ ] post-change 전체 pytest/Ruff
```

현재 완료 여부는 `VERIFICATION_AUTONOMOUS_QUALITY_KO.md`를 확인한다. 공개 migration은
derived-only로 제한되며 legacy canonical 승격은 여전히 구현·검증 범위 밖이다.
