# AQ 0.2 DeliveryProfile 안내

## 1. 목적과 상태

DeliveryProfile `0.1.0`은 AQ v2의 quality 판정과 format별 생산 결과를 분리한다. 하나의
quality-approved source freeze에서 review-only, GLB 또는 FBX 전달을 각각 계획하고, 한 format의
성공·실패가 다른 format이나 quality 판정을 덮어쓰지 않게 한다.

현재 v2 profile 전체는 `disabled_experimental`이다. profile mapping, source freeze,
format별 V0.7 review binding, public terminal supervisor와 nested terminal validator가 구현됐다.
2026-08-11 synthetic Blender fixture에서는 같은 freeze의 GLB+FBX 독립 production 및 양쪽
clean-import round trip이 통과했다. 이 bounded fixture는 실제 사람의 production 승인, 임의 자산의
시각 품질이나 destination runtime parity를 증명하지 않는다.

## 2. profile catalog

```powershell
uv run cbm autonomy-v2-delivery-profiles
```

Codex/MCP는 `list_autonomy_v2_delivery_profiles`를 사용한다.

| public delivery | V0.7 asset profile | primary file | package | handoff 후보 |
|---|---|---|---|---|
| `review_only` | 없음 | 없음 | 생성하지 않음 | 아님 |
| `portable_gltf` | `portable_gltf` | `.glb` | exact approval과 roundtrip 필요 | valid package일 때만 가능 |
| `portable_fbx` | `fbx_interchange` | `.fbx` | exact approval과 roundtrip 필요 | valid package일 때만 가능 |

기존 `obj_legacy` V0.7 profile은 regression surface로 남지만 AQ v2 delivery 선택지는 아니다.
`portable_fbx`는 public role 이름을 추가한 것이며 기존 V0.7 profile ID를 rename하지 않는다.

## 3. 요청 규칙

- 한 plan 안의 delivery profile은 중복될 수 없다.
- `review_only`는 portable profile과 함께 요청할 수 없다.
- GLB와 FBX는 각각 독립 `run_id`, `package_id`를 가진다.
- 처음 root authorization에 없는 format을 실행 중 추가할 수 없다.
- `destination_hint`는 inert advisory data이며 write authority가 아니다.
- generic AQ authorization은 V0.7 approval 또는 handoff approval을 대체하지 않는다.

CLI planner 예시:

```powershell
uv run cbm autonomy-v2-plan `
  --reference <REFERENCE_PATH> `
  --target-subject "<TARGET_SUBJECT>" `
  --deliveries portable_gltf,portable_fbx `
  --enable-v2 `
  "<REQUEST>"
```

이 명령은 disabled profile에 대한 명시적 실험 plan만 만든다. exporter, optimizer, package,
roundtrip 또는 destination handoff를 실행하지 않는다.

## 4. quality source freeze

portable delivery 전에는 `QualityApprovedSourceFreeze`가 필요하다. freeze는 다음 exact
artifact를 묶는다.

- hard-gate `passed`인 Integrated Quality 0.2 report
- report가 사용한 exact camera와 reference/candidate evidence
- current canonical ModelingPlan
- canonical SceneSpec과 authoring blend
- build provenance
- MaterialPlan, ShaderRecipe, TextureManifest
- external geometry payload
- GeometryIntent survival evidence
- exact `geometry_candidate_validation_receipt`와 `material_phase_receipt`
- 현재 V0.7 source fingerprint

service는 exact global/semantic reference·candidate PNG를 path/hash/kind로 유일하게 찾고 실제
bytes에서 contour·semantic metric을 다시 계산한다. 이어서 gates, findings,
`revision_reasons`, reentry와 outcome을 host builder로 재생성해 caller report 전체와 equality를
검사한다. canonical source fingerprint가 바뀌거나 artifact hash/size가 달라지면 freeze와 delivery는
fail-closed한다. typed raw receipt가 없는 required scored landmark/multi-view는 pass authority가 없다.

authoritative hard finding은 exact required gate의 `failed` outcome에 결속해야 한다. passed IQ의
source/input map은 위 canonical authoring artifact와 promotion/survival evidence의 전체 current
closure를 포함해야 하며, summary field나 과거 receipt로 누락 source를 보완할 수 없다.

IQ outcome `passed`만 freeze를 만들 수 있다. `needs_revision|unscorable`은
`review_required` terminal과 exact review bundle으로 끝나고, `blocked`는 bundle/freeze 없는 blocked
terminal로 끝난다. 어떤 branch도 package-ready로 재분류하지 않는다.

`QualityTerminalV2`도 결과에 따라 서로 다른 exact evidence를 요구한다.

- `quality_approved`: Integrated Quality report와 source freeze를 모두 provenance에 결속한다.
- `review_required`: source freeze 없이 exact review bundle을 provenance에 결속한다.
- `blocked` 또는 `failed`: source freeze와 review bundle을 성공 증거처럼 가질 수 없다.

따라서 non-pass의 `review_required` quality terminal은 아래의 DeliveryProfile `review_only`와
동일하지 않다. non-pass terminal은 delivery planning으로 진행하지 않는다.

## 5. format별 review와 승인

delivery plan 이후 portable profile마다 기존 V0.7 host service가 별도 review를 만든다.

```text
portable_gltf
  → asset profile portable_gltf
  → 독립 optimization run/review_plan.json
  → exact optimization-plan SHA-256 사용자 승인 대기

portable_fbx
  → asset profile fbx_interchange
  → 독립 optimization run/review_plan.json
  → exact optimization-plan SHA-256 사용자 승인 대기
```

`DeliveryReviewBinding`은 각 review plan artifact, exact plan SHA-256, run/package identity와
`next_action=request_exact_v07_optimization_approval`을 기록한다. 사용자 승인 필요 값은 항상
`true`이며 generic root authorization은 승인으로 소비되지 않는다.

테스트가 사용하는 `approved_by=user` artifact는 exact approval 소비·stale·single-use 규칙을
검증하기 위한 synthetic fixture다. 사람의 실제 대화형 승인을 받았다고 기록하거나 production
승인으로 재사용하지 않는다.

승인이 없으면 다음을 수행하지 않는다.

- derived optimization
- LOD/collider/UV/batching 생성
- export
- package manifest 생성
- clean-import validation

profile, source, preflight, review plan이나 source freeze가 달라지면 이전 approval을 재사용하지
않고 새 run/review를 만든다.

## 6. 독립 생산 원칙

GLB와 FBX를 서로 변환하지 않는다.

```text
동일한 exact quality source freeze
├─ derived GLB optimization/export/package/roundtrip
└─ derived FBX optimization/export/package/roundtrip
```

각 format result는 approval, package manifest, roundtrip validation, material loss와 선택적
handoff manifest를 독립적으로 결속한다. completed portable result는 적어도 approval, package와
validation evidence가 모두 있어야 하며 `production_ready=true`여야 한다.

aggregate terminal은 format별 결과를 숨기지 않는다.

- 모두 completed: `completed`
- 일부 completed, 일부 failed: `partial`
- 모두 failed: `failed`
- 유일한 result가 review-only: `review_only`

한 format의 failure가 freeze, 다른 package 또는 canonical source를 overwrite하지 않는다.

`DeliveryTerminalV2`는 exact quality terminal, source freeze, delivery plan, 모든 format result를
provenance에 결속한다. portable result가 하나라도 있으면 그 plan의 모든 portable request와
동일 identity/source freeze를 가진 exact `DeliveryReviewBinding`도 필수다. review-only result만
있는 terminal은 반대로 V0.7 review binding을 주장할 수 없다. result 순서, delivery ID, profile,
package/roundtrip/loss/survival artifact가 plan과 다르면 terminal 발행은 fail-closed한다.

DeliveryTerminal의 nested validator는 참조된 QualityTerminal bytes/hash만 확인하지 않고 full
QualityTerminal validation을 호출한다. IQ hard-gate binding, current source closure와 source freeze를
다시 검증하므로 forged `quality_approved` terminal은 downstream package가 완성돼도 거부된다.

public supervisor는 approval이 없으면 `await_v07_approval`에서 멈춘다. exact unused approval이
있으면 format별 executor를 호출하고, completed evidence chain이 이미 존재하는 crash recovery에서는
그 exact chain만 채택한다. 사용된 approval과 불완전하거나 변조된 chain으로 재실행하지 않는다.

## 7. `review_only`

`review_only`는 **이미 quality-approved source freeze를 가진 세션**에서 quality/report evidence만
사용자에게 전달하는 DeliveryProfile 종료 범위다. IQ non-pass의 `review_required` quality
terminal과 혼동하면 안 된다.

- V0.7 asset profile 없음
- optimization run/package ID 없음
- package 없음
- clean-import 없음
- `production_ready=false`
- Destination Handoff 대상 아님

따라서 review PDF나 JSON이 있다는 이유로 engine-neutral package가 있다고 말하면 안 된다.

## 8. package와 clean import

portable result는 기존 V0.7 불변 조건을 그대로 따른다.

- canonical SceneSpec, geometry, authoring blend, V0.5 contracts와 source texture 불변
- run-owned derived optimization
- raw PBR channel 보존
- immutable package manifest와 모든 relative file SHA-256
- absolute/escaping path 없음
- dependency closure
- imported bounds와 semantic/material coverage
- format별 clean-import round trip

GLB의 ORM은 계속 `R=occlusion`, `G=roughness`, `B=metallic`이다. FBX material
reconstruction은 destination-specific이며 shader parity를 주장하지 않는다. export success만으로
clean import나 runtime parity를 대신하지 않는다.

## 9. Destination Handoff와 Advanced Material Handoff

V0.9 Destination Handoff는 passed package에 대한 별도 plan/hash approval/generate/validate/audit
흐름이다. AQ v2 delivery completion은 handoff 승인이 아니다.

Advanced Material Handoff는 authoring receipt를 바탕으로 Unity URP/HDRP channel mapping과
known loss를 설명하는 advisory JSON companion이다. 다음을 하지 않는다.

- package나 texture를 destination project로 복사
- Unity Editor 실행
- Material/Shader Graph 생성
- Prefab/Actor 생성
- runtime parity 주장

Advanced plan은 `destination_write_performed=false`, `runtime_parity_verified=false`를 유지하고,
destination 변경 전 사용자 승인이 필요하다고 기록한다.

## 10. destination hint의 의미

v2 root authorization이 허용하는 hint는 다음과 같다.

- `engine_neutral`
- `unity_urp`
- `unity_hdrp`
- `custom_unverified`

hint는 목적지에서 검토할 conversion/loss 계획을 고르는 데이터다. 엔진, 버전, render pipeline을
탐지했다는 뜻이 아니며 importer 지원을 검증하지 않는다. 실제 destination Codex는 package를
immutable evidence로 읽고 project를 분석한 뒤 별도 import plan과 사용자 승인을 받아야 한다.

## 11. 실패·rollback 모델

| 실패 | 처리 |
|---|---|
| IQ report가 non-pass 또는 tampered | freeze 생성 금지 |
| IQ hard finding이 failed required gate에 결속되지 않음 | quality terminal/freeze 생성 금지 |
| IQ source map이 current canonical/promotion closure를 누락 | freeze와 delivery 생성 금지 |
| canonical/source fingerprint 변경 | delivery plan/review 중단, 새 freeze 필요 |
| 한 format V0.7 approval 누락/stale | 해당 format만 승인 대기/실패 |
| optimizer/exporter failure | 해당 run evidence 보존, canonical 변경 없음 |
| package dependency 누락 | success 금지 |
| clean import failure | package accepted 금지 |
| handoff hash mismatch | handoff 생성/validation 실패, package 수정 없음 |

부분 성공을 전체 성공으로 재분류하지 않는다. 실패한 package 또는 completed receipt를 제자리
수리하지 말고 새 run/package/handoff ID로 다시 계획한다.

## 12. 현재 검증 경계

host tests에서 확인된 범위:

- strict profile mapping
- review-only와 portable 조합 거부
- same-freeze 독립 run/package identity
- source freeze tamper/canonical supersession 탐지
- IQ 0.2 passed report 결속
- format별 review가 V0.7 exact approval에서 멈춤
- non-pass quality terminal의 exact review-bundle 결속과 source-freeze 금지
- portable terminal의 exact quality/source/plan/review/result 결속
- terminal의 completed/partial/failed/review-only 계산
- destination/runtime parity false 불변
- supervisor의 approval 대기, format별 실행, crash adoption과 nested terminal 재검증
- full QualityTerminal nested validation과 forged quality-approved terminal 거부

실제 Blender synthetic fixture에서 확인된 범위:

- 하나의 exact quality freeze에서 직접 파생한 GLB delivery와 clean import
- 같은 freeze에서 독립적으로 직접 파생한 FBX delivery와 clean import
- 두 format의 독립 review/run/package/source provenance와 no cross-conversion
- GeometryIntent/material loss/survival과 crash adoption
- package 없는 `review_only` terminal

이번 문서 최종화에서 확인하지 않은 범위:

- 실제 사용자가 대화형으로 승인한 production V0.7 plan
- 임의 사용자 자산의 GLB/FBX 품질 또는 importer별 surface parity
- Unity/Unreal import/runtime 결과
- package-bound Destination Handoff의 실제 목적지 재조립
- Codex Desktop/App Server가 controller output부터 자율 생산하는 실행

이 미검증 항목이 남아 있으므로 `autonomous_static_prop_v2`와 관련 experimental delivery는
계속 `disabled_experimental`이다.
