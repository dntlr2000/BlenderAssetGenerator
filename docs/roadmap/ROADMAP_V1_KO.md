# BlenderAssetGenerator V1.0 로드맵

## AQ North Star

지원 범위 안의 새 정적 소품 작업은 최초 사용자 요청 한 번으로 시작하며, 사용자가 최초 요청에서
허용한 scope, budget, provider 및 delivery 범위 안에서는 routine user approval 없이 production
delivery 또는 review terminal까지 진행되어야 합니다.

Dependency closure, provenance, manifest, path rebinding, preflight, technical retry, controller retry,
rollback과 deterministic identity normalization은 사용자 승인 대상이 아닙니다. 추가 사용자 결정은
최초 권한 범위를 벗어나는 실제 scope, reference, target, budget, delivery, provider 또는 destination
write 변경과 reference evidence로 해결할 수 없는 중요한 디자인 선택에만 요구합니다.

모든 신규 마일스톤과 계약은 “정상 작업의 사용자 승인 수를 줄이는가, 유지하는가, 늘리는가?”와
“늘린다면 왜 사용자만 판단할 수 있는 결정인가?”에 대한 답과 exact evidence를 기록해야 합니다.
새 기술 edge case가 발견됐다는 이유만으로 사용자 승인 계약을 추가하지 않습니다.

이 문서는 BlenderAssetGenerator의 V1.0 개발 로드맵과 그 이력을 보존합니다. 현재 고정 버전은 `0.9.1`이며 reference-fidelity 장기 개선은 사용자 선택 A안으로 종료했습니다. E(동일 clean baseline 5자산 실제 성공)와 F(delivery·인간 판정·Activation 재평가)는 미완료입니다. 후속 개발이나 캠페인은 별도 사용자 지시가 필요하며 [인계 문서](../HANDOFF_KO.md)를 우선합니다. 아래 과거 진행 상태와 `0.9.0` 검증 결과는 당시 이력입니다. 구현된 기능과 계획된 기능을 구분하고, 각 단계의 책임·진입 조건·완료 조건·되돌아가기 규칙을 정의합니다.

로드맵은 구현 사실을 대신하지 않습니다. 어떤 단계가 `완료`로 바뀌려면 해당 버전의 코드, JSON 계약, 테스트 계획, 실제 Blender 통합 게이트와 검증 기록이 함께 존재해야 합니다.

## 현재 1차 완성 판정 기준

프로젝트 `0.9.0` 당시 기술 코어와 Standard skill orchestration은 구현·실자산 검증을 마쳤습니다.
그러나 이 문서에서 말하는 **1차 완성**은 프로젝트 버전 승격이나 모든 확장 기능의 완료가 아니라,
최초 사용자 요구였던 다음 두 사용자 진입 경로를 지원 범위 안에서 재현 가능하게 닫는 것을 뜻합니다.

```text
Standard
한 번의 standard-asset-cycle 호출
→ V0.4 형상
→ V0.5 재질
→ V0.6 QA
→ 선택적 V0.7 package
→ 기존 exact 사용자 승인 경계와 안전한 재개 유지

AQ local-only
한 번의 aq-one-prompt-orchestrator 호출
→ reference
→ geometry
→ material/closure
→ Integrated Quality
→ production delivery 또는 usable review terminal
→ 정상 범위의 추가 사용자 결정 0, technical user approval 0
```

Standard는 두 실제 자산의 composite run과 GLTF clean import를 통과했으므로 선언된 품질·형식 한계
안에서 1차 완료로 분류합니다. AQ v2는 계약, adapter, policy, recovery와 실제 자산 실행 증거가
존재하고, B8 canary에서 machine-passed IQ 뒤 exact human `needs_revision`을 append-only usable review
terminal로 닫는 경계까지 검증했습니다. 이후 C655 기준선에서 서로 다른 reference 5개가
One-Prompt, production delivery와 clean import를 모두 통과했지만 rust·wood·crystal의 내부 구조와
재질 가시성이 평탄하게 붕괴해도 contour 중심 IQ가 통과하는 framework 결함이 확인됐습니다. 이 결함
수정은 다시 source 변경이므로 B8이나 C655 결과를 새 기준선의 캠페인 실적으로 소급 계산하지 않습니다.
fixed-camera 내부 가시성 gate를 포함한 `7359ce7` 기준선에서는 canary의 production GLTF/clean import를
검증했으나, 5개 실행 중 정상 terminal은 `1/5`였습니다. Rusted scrap은 delivery tangent 오류,
Wood·Crystal은 Windows 긴 재질 경로 오류 이후 cancelled, Laser는 legacy modifier 계약 위반과
누락된 adapter 종료 증거를 남겼습니다. 후속 `f6830b7` clean baseline은 16개 검증 receipt를 통과했고
5개 adapter trace를 모두 닫았지만 정상 terminal은 여전히 `1/5`였습니다. Rust는 실제 형상·재질이
유지된 GLB의 UV/법선 반올림 경계에서 실패했고, Wood·Crystal은 남아 있던 build provenance 긴 경로
읽기에서 취소됐으며, Laser는 하부 음영역을 채운 형상으로 contour hard gate에 막혔습니다.
후속 `42aa7c7` clean baseline도 검증 receipt 16개를 통과했고, 실제 캠페인은 Plastic·Rust·Laser의
production GLTF/clean import를 포함한 정상 terminal `3/5`, adapter trace closure `5/5`로 닫혔습니다.
Wood·Crystal은 build와 IQ를 통과했으나 portable material conversion의 긴 shader 경로 읽기에서
failed/blocked로 종료됐습니다. 모든 과거 결과는 그대로 보존합니다. 당시에는 **8-B의 portable 경로
보완과 새 기준선 준비 단계**였습니다. 경로 수정 뒤 두 자산의 격리 delivery에서 드러난 숨겨진 연결부
접선 문제도 새 후보에서 보완해 실제 GLB clean import·형상 보존·고정 카메라 지표 사전 검증을
통과했습니다. 이 격리 결과는 다음 기준선의 캠페인 실적이 아니며, 당시 수정 후 outcome은 `0/5`였습니다.
AQ는 계속 1차 완료 전이고, 이번 5개 beauty의 exact human quality disposition과 Activation도
완료되지 않았습니다.

2026-09-05 당시 `5e5b172`/`aq-first-completion-5e5b172-fix3`는 기술적으로 production/package terminal
`5/5`이며 새 beauty 인간 판정은 `0/5`입니다. 이 사실로 위 과거 실패를 재분류하지 않습니다.
목재의 판상 생성, contour/bbox 중심 QA의 누락, 시각 지적과 실제 재저작 사이의 단절을 확인했으므로
캠페인 반복·Activation 추진은 보류하고 **8-B 앞단의 reference 충실도 생성·평가·수정 루프 개선**을
진행했습니다. 새 공통 계약/host 수정 경로와 실제 Blender fixture multi-round vertical을 구현·검증했습니다.
격리 목재는 attempt09에서 고정 관찰 4/4와 attempt08 대비 `improved`를 기록했고, exact 승인 범위의
external-intake normalization, V0.7 optimization, 512px CPU portable PBR 변환, immutable static-payload
GLB 및 fresh clean import를 완료했습니다. 이어 같은 공통 authoring/finding/re-entry 경로를 Plastic, Rust,
Crystal, Laser에 자산별 서비스 코드 분기 없이 전이해 다섯 reference 모두 source-bound 비인간 비교에서
실제 개선을 입증했습니다. Crystal과 Laser는 초안의 구조 결함을 V0.4 re-entry로 실제 수정했습니다.
당시 전체 host 회귀, actual Blender AQ gate, V0.9 package/handoff gate와 과거 16개 anchor 불변 audit까지
통과해 A/B/C/D를 닫았습니다. 이 격리 evidence는 새 clean-baseline 캠페인 실적이나 인간 수락이 아닙니다.
기술적 5/5를 시각적 5/5로 간주하지 않습니다. 당시 개발 실증 근거는
[Reference Fidelity 검증 기록](../../VERIFICATION_REFERENCE_FIDELITY_KO.md)을 따릅니다.

AQ 1차 완성의 고정 지원 범위는 Windows 11, Blender `5.0.1`, `primary_object_only` 정적 소품,
local/procedural PBR와 engine-neutral portable GLTF입니다. Codex ImageGen, destination project write,
Unity/Unreal runtime parity, signage/decal, 별도 bake-bound dependency-rich material, architecture,
interior, rig와 animation은 해당 capability를 현재 profile scope에 명시적으로 포함하고 독립 검증하기
전까지 이 1차 완료 범위에서 제외합니다. 제외된 capability는 local-only base Activation의 필수 성공
지표로 소급 계산하지 않습니다.

`production delivery`와 `usable review terminal`은 서로 다른 정상 terminal입니다. exact
`needs_revision` disposition은 actionable review evidence, 닫힌 adapter route/receipt, 미해결 technical
next action 0건과 canonical 무결성을 만족할 때 usable review terminal이 될 수 있지만 visual acceptance,
package 또는 production readiness를 뜻하지 않습니다. `blocked`, `failed`, pending approval와 단순
`running` projection은 usable terminal로 계산하지 않습니다. revision budget이 끝난 review terminal을
같은 evidence로 무한 반복하지 않습니다.

## 1. 버전과 작업 단계의 의미

이 프로젝트에는 세 종류의 버전이 함께 존재합니다.

1. **프로젝트 버전**: 현재 통합 저장소의 기능 수준입니다. 현재 값은 `0.9.1`입니다.
2. **데이터 계약 버전**: SceneSpec, MaterialPlan, Visual QA, portable asset처럼 독립적으로 유지되는 JSON 계약 버전입니다.
3. **작업 단계**: 한 자산이 분석·형상·재질·QA·패키징을 오가는 제작 단계입니다.

현재 계약은 다음과 같습니다.

| 계약 | 버전 | 역할 |
|---|---:|---|
| Geometry SceneSpec | `0.2.0` | 형상, transform, 카메라, semantic ID |
| Reference/Constraint | `0.4.0` | 이미지 진단, 카메라 가정, 실측 잔차 |
| Optional InteriorScope | `0.1.0` | 명시적 실내 범위, hash 승인, fail-closed 검증 |
| Material/Shader | `0.5.0` | 재질, 셰이더, 텍스처, 베이크 |
| Visual QA | `0.6.0` | 고정 카메라 증거, 점수, 후보, 승인, 복구 |
| Portable static asset | `0.7.0` | preflight, 최적화, 패키지, round trip |
| Workflow orchestration | `0.8.0` | 짧은 요청 라우팅, 상태, 재개, 승인 경계 |
| Stabilization evidence | `0.9.0` | 환경 증거, 읽기 전용 감사, queue, release report |
| Codex Destination Handoff | `0.9.0` | package-bound 조립·재질 계약과 안전한 목적지 import prompt |
| External Static Asset Intake | `0.9.0` | 수동 제작 static source의 inspection, exact 승인, normalized authoring derivative와 V0.7 연결 |
| Autonomous Quality / Integrated Quality | `0.1.0` | 새 standard 정적 소품을 위한 opt-in supervisor와 네 축 companion quality evidence |
| Autonomous Quality v2 / Integrated Quality 0.2 | `0.2.0` | additive experimental overlay; profile은 `disabled_experimental` |
| AQ Approval Envelope | `0.3.0` | exact RootAuthorizationV2 companion, routine policy authority, approval budget와 telemetry |
| AQ One-Prompt Supervisor | `0.1.0` | geometry → material → IQ → delivery/review의 bounded current-task orchestration |
| Codex Built-in ImageGen companion | core `0.1.0`, adoption `0.2.0`, MaterialAuthoring `0.2.1` | current-task image candidate overlay; `disabled_experimental` |
| SceneSpec V03 structural derivative | `0.3.0` | canonical `0.2.0`을 바꾸지 않는 opt-in derived 구조 형상 계약 |
| GLB numerical geometry survival | corner `0.1.0`, report `0.2.0` | 기존 exact 비교를 보존하는 Blender 5.0.1 전용 all-corner 수치 증명; historical report 자동 재분류 없음 |

현재 V0.9 저장소에서 V0.4 형상 작업을 다시 수행하는 것은 프로젝트를 다운그레이드하는 일이 아닙니다. 최신 저장소 안에서 이전 제작 단계를 다시 실행하는 정상적인 반복 작업입니다.

용어는 다음처럼 구분합니다.

- **canonical contract state**: immutable input, SceneSpec, geometry payload, constraints, MaterialPlan, ShaderRecipe와 TextureManifest처럼 설계를 다시 생성할 수 있는 정식 계약입니다.
- **verified source build**: canonical contract의 현재 fingerprint와 일치하는 파생 `.blend`입니다. QA·베이크·V0.7 preflight의 검증된 실행 입력이지만 직접 편집하는 설계 원본은 아닙니다.
- **derived run artifacts**: render, report, bake, QA run, optimization, material conversion, package와 PDF입니다.
- **단계 재진입 또는 rework**: 사용자가 의도적으로 V0.4 같은 authoring 단계로 돌아가 설계를 변경하는 정상 작업입니다.
- **rollback**: V0.6 적용 중 비개선·constraint regression·실패가 발생해 archived baseline을 트랜잭션적으로 복구하는 안전 동작입니다.
- **software downgrade**: 예전 프로젝트 코드를 다시 설치하거나 checkout하는 행위이며 일반적인 rework에는 필요하지 않습니다.

## 2. 전체 마일스톤

```text
V0.1  Primitive Proxy & Harness
  ↓
V0.2  Geometry Core
  ↓
V0.3  Reference Analysis + Camera
  ↓
V0.4  Reference & Measured Core
  ↓
V0.5  Material, UV, Texture & Shader Core
  ↓
V0.6  Visual QA + Guarded Revision Loop
  ↓
V0.7  Engine-neutral Portable Static Asset Core
  ↓
V0.8  Short-Prompt Automation + Job Orchestration
  ↓
V0.9  Stabilization + Codex Destination Handoff
  ↓
AQ 0.1  Optional Autonomous Quality overlay (프로젝트 버전 불변)
  ↓
AQ 0.2  Additive experimental quality/delivery harness (비활성)
  ↓
AQ 0.3  Approval Envelope + One-Prompt Supervisor (비활성)
  ↓
AQ Base First-Completion Closure  Terminal/KPI 정합성 + current-baseline 5개 캠페인
  ↓
ImageGen 0.1  Optional current-Codex texture companion (비활성)
  ↓
V1.0  Integrated Reference-to-Asset Pipeline (승격 중단)
```

| 단계 | 상태 | 저장소에서의 위치 |
|---|---|---|
| V0.1 | 역사적 프로토타입 | 현재 저장소에서 별도 배포하지 않음 |
| V0.2 | 구현 완료, 계약 유지 | SceneSpec `0.2.0`과 geometry builders |
| V0.3 | 구현 완료, V0.4에 통합 | reference analysis와 camera solution |
| V0.4 | 구현 완료, V0.7.3에서 선택적 실내 안전 경계 보강 | reference/constraint `0.4.0`, InteriorScope `0.1.0` |
| V0.5 | 구현 완료, V0.6 통합본에 포함 | material/shader `0.5.0` |
| V0.6 | 구현 및 로컬 검증 완료 | QA/revision `0.6.0` |
| V0.7 | V0.7.4 최적화 사전 검토·승인 및 Blender 5 통합 검증 | portable asset `0.7.0` |
| V0.8 | 구현 및 로컬 계약 검증 완료 | workflow orchestration `0.8.0`, 프로젝트 `0.8.0` |
| V0.9 | 수정된 로컬 범위 구현·회귀·Blender 5 handoff gate 완료 | stabilization/handoff `0.9.0`, 프로젝트 `0.9.0` |
| AQ 0.1 | `autonomous_static_prop_v1`만 검증된 opt-in 병렬 확장 | autonomy/integrated quality/companion contracts `0.1.0`; 현재 프로젝트 `0.9.1` |
| AQ 0.2 | 선택된 fixture와 gate를 통과했으나 비활성 실험 단계 | `autonomous_static_prop_v2` `disabled_experimental`; 현재 프로젝트 `0.9.1` |
| AQ 0.3 | additive approval-policy/one-prompt 계약과 adapter/policy recovery 구현, R5D exact beauty/package acceptance와 B8 post-IQ review terminal 검증; 과거 42aa 기준선 정상 terminal `3/5`, trace closure `5/5` 보존 | reference-fidelity A안 종료, A~D 개발 실증 보존·E/F 미완료. 과거 성공·실패와 인간 판정을 새 baseline으로 승계하지 않으며 별도 재개 지시 전 새 캠페인을 실행하지 않음; `autonomous_static_prop_v2` `disabled_experimental`, 현재 프로젝트 `0.9.1` |
| ImageGen 0.1 | controller-mediated companion 구현, bounded benchmark entry machine decision은 `GO` | AQ base 1차 완성과 분리된 optional overlay이며 별도 재개 결정 대상; `autonomous_static_prop_v2_codex_imagegen` `disabled_experimental`, 현재 프로젝트 `0.9.1` |
| Material Closure 0.1 | additive stabilization 구현·local regression; constant/local-only material promotion은 당시 실제 자산 5/5 통과, 기존 crystal dependency closure는 identity preflight에서 안전 실패, 새 authorized bake-bound closure는 입력 부재로 미실행 | dependency closure/preflight/promotion companion; 현재 프로젝트 `0.9.1` |
| Material Identity Split 0.1 | generic framework와 실제 승인 전 shadow 검증 완료 이력 보존; 당시 apply 승인 대기였으며 이 로드맵은 apply 실행 권한이 아님 | paired scope-change companion; 현재 프로젝트 `0.9.1`/SceneSpec `0.2.0` 유지 |
| V1.0 | 승격 중단 | 재개 결정과 아래 범위 재검토 전에는 사용 금지 |

## 3. V0.1 — Primitive Proxy & Harness

### 목표

Codex, SceneSpec, Blender background process와 MCP를 연결하여 반복 가능한 최소 파이프라인을 증명합니다.

### 핵심 범위

- 단일·다중 레퍼런스 작업 폴더
- primitive 기반 SceneSpec
- Blender build, render, inspect, validate
- `.blend`, GLB, FBX, OBJ 출력
- immutable input과 작업별 격리

### 완료 기준

- 같은 SceneSpec에서 재빌드 가능한 Blender 장면 생성
- Blender Python 예외와 timeout을 정상 실패로 보고
- 작업 ID별 입력과 산출물 경로 격리

V0.1은 현재 운영 대상이 아니라 이후 단계가 의존하는 역사적 하네스 마일스톤입니다.

## 4. V0.2 — Geometry Core

### 목표

기본 도형 프록시를 넘어 편집 가능한 로우·미드폴리 형상을 결정론적으로 생성합니다.

### 핵심 범위

- `primitive`, `custom_mesh`, `profile_extrude`, `revolve`, `curve`, `terrain`
- `bevel`, `mirror`, `subdivision`, `solidify`, `array`, `decimate`, `remesh`, `boolean`
- 큰 정점 배열을 `geometry/` payload로 분리
- stable semantic ID와 material ID
- ID·경로 기반 guarded RevisionPlan과 전후 diff

### 완료 기준

- 6종 geometry recipe와 8종 modifier의 Blender 통합 검증
- SceneSpec을 canonical source로 유지하고 `.blend` 수동 편집에 의존하지 않음
- 기존 ID를 보존한 최소 수정과 재빌드 가능

Geometry SceneSpec은 이후 프로젝트에서도 `0.2.0`으로 유지합니다. 계약 변경이 필요하면 명시적 migration과 이전 계약 회귀 테스트가 먼저 필요합니다.

## 5. V0.3 — Reference Analysis + Camera

### 목표

Codex가 이미지를 보고 곧바로 SceneSpec을 추측하지 않도록 결정론적 진단과 카메라 가정을 별도 근거로 만듭니다.

### 핵심 범위

- 이미지 해시, 크기, content bounds, edge density, symmetry, dominant colors
- 선택적 OpenCV line-angle 진단
- `camera_solution.json`의 projection, azimuth, elevation, focal/ortho 가정
- `modeling_plan.json`의 의미 객체 분해와 권장 geometry recipe
- observed, inferred, underconstrained 구분

V0.3은 별도 프로젝트로 유지하지 않고 V0.4에 통합합니다. 사용자는 보통 이를 `V0.4 모델링 단계의 레퍼런스 분석`이라고 부르면 됩니다.

### 완료 기준

- 동일 입력에서 진단 결과가 안정적으로 재생성됨
- 단일 이미지에서 알 수 없는 깊이·후면·절대 치수를 확정값으로 기록하지 않음
- SceneSpec 작성 전에 modeling plan과 카메라 가정이 존재함

## 6. V0.4 — Reference & Measured Core

### 목표

레퍼런스 분석, 카메라 가정, 멀티뷰, 실제 치수와 constraint residual을 형상 제작 과정에 연결합니다.

### 핵심 범위

- 안전한 `add_view`와 명시적 view replacement
- `dimension`, `location`, `distance`, `align`, `equal_dimension`
- Blender inventory 기준 actual, residual, tolerance, status 계산
- concept와 measured 작업의 명확한 구분
- 분석만 다시 실행했을 때 승인된 SceneSpec과 geometry를 변경하지 않는 비파괴성
- 요청하지 않은 실내를 만들지 않는 default-disabled InteriorScope와 exact-hash 승인 경계

### 완료 기준

- V0.2 geometry 회귀 통과
- reference analysis, camera solution, modeling plan 생성
- 통과·실패 constraint를 정확히 구분하고 실패를 자동으로 숨기지 않음
- 실제 사용자 작업에서 입력, semantic ID, 카메라와 승인된 구조 보존
- scope가 없거나 draft/stale인 상태, 또는 승인된 prefix·level·space 밖의 실내 객체를 SceneSpec 로드와 빌드 전에 거부

V0.4는 임의의 CAD 제약을 자동 해결하는 완전한 비선형 솔버가 아닙니다. 잔차는 guarded revision의 근거이며 자동 설계 변경 권한이 아닙니다.

### 선택적 실내 구조 보강

프로젝트 `0.7.3`에서 V0.8 orchestration에 앞서 V0.4 형상 authoring 경계에 별도 `InteriorScope 0.1.0`을 도입했고, V0.7 derived asset 계층에 안전한 배칭·cleanup·cost budget evidence를 추가했습니다. 이 경계는 현재 프로젝트 `0.9.1`에서도 유지됩니다. `architecture/interior_scope.json`이 없으면 실내 정책은 `disabled`이고, 외관 요청은 외관만 생성합니다. 사용자가 실내를 명시적으로 요청한 경우에도 scope 초안만으로는 충분하지 않으며, `architecture/interior_scope.approval.json`이 현재 scope의 SHA-256과 정확히 일치해야 승인된 prefix·level·space·furnishing 범위 안에서만 정적 실내 형상을 작성할 수 있습니다.

이 보강은 SceneSpec `0.2.0`을 변경하지 않습니다. 실내 객체는 기존 stable semantic ID와 tag를 이용해 분류하며, facade backing·door reveal·window recess·외벽 두께처럼 외관을 지지하는 형상은 실내로 명명하거나 tag하지 않는 한 계속 허용합니다. interactive door, navigation, gameplay volume, 목적 엔진별 room system과 runtime shader는 V1.1 이후 목적지별 통합 범위입니다.

## 7. V0.5 — Material, UV, Texture & Shader Core

### 목표

이미지 맵만 생성하는 것이 아니라 재질의 물리적 의미, Blender master shader, portable PBR 출력 계약을 분리해 관리합니다.

### 핵심 범위

- MaterialPlan, ShaderRecipe, TextureManifest, BakeManifest
- stable material ID와 observed/inferred 재질 특성
- whitelisted Blender 5 호환 shader recipe
- sRGB Base Color와 Non-Color data channel 검증
- UV 보존·생성, texel scale, procedural texture provider
- sphere/plane swatch, runtime node inspection, Cycles bake
- Blender master shader와 portable PBR channel 분리

### 완료 기준

- geometry 승인 후에만 재질 authoring 시작
- 누락 텍스처, 잘못된 color space, 끊어진 노드와 stale build 차단
- 재질별 swatch와 material PDF를 사용자에게 제공
- 셰이더 효과의 portable 손실과 bake 필요성을 명시

`Material authoring 완료`는 계약·그래프·texture·inspection·swatch가 준비된 상태입니다. `Portable bake 완료`는 선택한 전달 profile이 bake를 요구할 때만 추가로 판정합니다.

V0.5 기능은 V0.6 통합본에 포함되어 있으며 별도 V0.5 프로젝트를 설치하지 않습니다.

## 8. V0.6 — Visual QA + Guarded Revision Loop

### 목표

구조적 성공과 시각적 유사도를 구분하고, 레퍼런스 대비 오차를 stable semantic ID에 연결하여 승인된 변경만 적용합니다.

### 핵심 범위

- 정확히 7개 고정 카메라 패스: beauty, silhouette, object ID, material ID, normal, depth, wireframe
- reference mask, silhouette, bounds, semantic evidence의 직접 비교
- 이미지 생성 모델 결과를 provenance가 있는 advisory target으로 가져오는 선택적 adapter
- 승인된 InteriorScope를 공간별 4/6/8방향에서 격리 렌더하는 선택적 실내 다각도 QA
- 실내 view마다 동일한 7개 pass, semantic visibility, topology/overlap finding과 contact sheet
- revision candidates, exact candidate compile, hash-bound single-use approval
- 적용 후 rebuild, rerender, constraint 비회귀, score 개선 확인
- 검증 실패 또는 비개선 시 canonical SceneSpec 자동 복구

### 완료 기준

- direct reference evidence가 beauty 또는 생성 target보다 항상 우선
- 생성 target 단독 후보는 자동 적용 불가
- 모든 실행 후보가 명시적 사용자 승인을 요구
- 승인하지 않은 path가 바뀌지 않음
- 수정 후 direct score 개선과 constraint 비회귀를 모두 만족
- 실내 QA 카메라는 exact plan hash 승인 뒤에만 생성되고 authoring `.blend`에 저장되지 않음
- 매핑된 실내 레퍼런스가 없으면 유사도 점수를 만들지 않고 manual-only 후보만 보고함

QA 점수는 완성도 백분율이나 사람의 최종 품질 승인이 아닙니다. 큰 실루엣·카메라·객체 분해 문제가 발견되면 V0.6의 작은 후보를 반복하기보다 V0.4 형상 작업으로 되돌아갑니다.

`QA 실행 완료`는 7패스와 report/candidate가 생성된 상태일 뿐 수정 승인이 끝났다는 뜻이 아닙니다. `QA 승인 완료`는 사용자가 결과를 승인했거나, 승인된 revision이 점수 개선과 constraint 비회귀를 통과한 상태입니다.

실내 QA는 외관 고정 카메라 QA의 대체물이 아니라 선택적 보완 계층입니다. `semantic_visibility_fraction`은 승인된 view 집합에서 semantic ID가 보였는지를 나타내는 coverage이며 완성도 백분율이 아닙니다. 실내의 실제 유사도를 비교하려면 향후 view별로 명시적으로 매핑된 내부 레퍼런스와 별도 승인 계약이 필요합니다.

## 9. V0.7 — Engine-neutral Portable Static Asset Core

### 목표

승인된 Blender 자산을 canonical authoring 데이터에 손대지 않고 다른 도구나 엔진으로 전달할 수 있는 정적 자산 패키지로 만듭니다.

### 핵심 범위

- engine-neutral AssetProfile: `portable_gltf`, `fbx_interchange`, `obj_legacy`
- verified source build `.blend`의 read-only topology preflight
- run-owned optimized scene, LOD, collider, UV1
- semantic/material/LOD/UV-safe derived batching과 제한된 loose/material/collider cleanup
- before/after static cost, budget, repeated mesh와 overlap 후보를 기록하는 immutable cost report
- run-owned portable UV atlas와 raw PBR channel 변환
- glTF ORM을 명시적 파생 출력으로 생성하고 raw channel 보존
- atomic immutable package와 모든 파일 hash
- 절대·escaping path와 누락 dependency 차단
- fresh Blender clean-import round trip
- bounds, semantic/material coverage와 알려진 format loss 기록
- export PDF와 source-hash sidecar

### 완료 기준

- source/profile/run/build fingerprint가 정확히 결합됨
- preflight 실패를 경고나 통과로 바꾸지 않음
- canonical SceneSpec, geometry, material, texture와 verified source build `.blend` 무변경
- batching 전후 triangle 합계와 source instance별 LOD budget 보존
- AABB overlap, internal/coplanar face와 runtime draw call을 검증된 사실처럼 보고하거나 자동 삭제하지 않음
- package overwrite 거부, dependency 누락과 절대 경로 0건
- primary format clean import와 profile별 bounds/identity 기준 통과

V0.7은 정적 자산만 지원합니다. 특정 Unity/Unreal 버전의 import parity, engine material graph, prefab/actor, runtime shader, rig, skin과 animation을 주장하지 않습니다.

## 10. V0.8 — Short-Prompt Automation + Job Orchestration

**상태: 구현 완료. 공개 `0.8.0` 계약, CLI/MCP 도구, 격리 gate가 추가됐으며 V0.7.4 Blender 회귀 검증을 유지합니다.**

### 목표

사용자가 이미지와 짧은 요청을 주면 현재의 V0.4~V0.7 기능을 올바른 순서와 승인 경계로 조율하고, 중단된 작업을 안전하게 재개합니다.

### 구현 범위

1. **Intent routing**
   - 새 자산 생성
   - 기존 자산 수정
   - measured view 추가
   - 명시적 실내 범위 생성·승인·수정
   - 재질 작업
   - QA 재검사
   - portable package 생성
2. **Job state machine**
   - `created`
   - `analyzed`
   - `proxy_ready`
   - `geometry_approved`
   - `interior_scope_waiting` 또는 `interior_scope_approved`
   - `material_ready`
   - `qa_review`
   - `portable_ready`
   - `delivered_for_review`
   - `completed`, `waiting_for_approval`, `failed`
3. **Idempotent resume**
   - 완료된 단계의 exact fingerprint 확인
   - stale 단계만 재실행
   - 실패 지점부터 재개
   - 동일 요청의 중복 산출물 방지
4. **Approval orchestration**
   - proxy, interior scope hash, detailed geometry, material swatch, QA candidate, final package 승인 분리
   - 미래 후보에 대한 포괄 승인 금지
   - approval-required 단계를 짧은 요청으로 우회하지 못하게 함
5. **Operational controls**
   - 시간, 해상도, 폴리곤, QA iteration과 외부 provider budget
   - 단계별 `off`, `suggest`, `approve` 정책
   - status, resume, cancel과 실패 원인 보고
6. **Destination handoff selection**
   - 기본 종료 경계는 V0.7 engine-neutral package
   - 사용자가 요청한 GLB/FBX workflow에서만 optional Codex Destination Handoff 추가
   - handoff는 prompt와 조립 계약만 생성하고 목적지 프로젝트를 직접 수정하지 않음
   - Unity, Unreal 또는 기타 엔진을 기본값으로 추정하지 않음
   - 자동 Destination Adapter는 목적지가 확정된 뒤 V1.1 이후 범위
7. **Background exterior execution policy**
   - `standard` 기본값과 명시적 `background_exterior` opt-in 분리
   - planning 시 `preview_only` 또는 `portable_package` 종료 범위 확정
   - 단일 unmeasured static exterior에 한해 일반 proxy/detail/swatch/QA 승인을 축약
   - 빠른 경로에서도 V0.7 exact optimization-plan 승인은 유지
   - 로컬 결정론적 512 px 이하 재질, 직접 QA 1회, generated target·auto revision·외부 provider 금지
   - 조건 이탈 시 `requires_standard_workflow`로 중지하고 기존 immutable plan은 변경하지 않음

`background_exterior`는 두 번째 모델링 파이프라인이나 새 계약 버전이 아닙니다. 동일한 SceneSpec, MaterialPlan, QA와 V0.7 package 계약을 사용하는 V0.8 실행 정책이며, 사용자가 수동 검토 비용을 줄이는 대신 허용 범위와 자동 반복을 더 좁게 제한합니다.

### Artifact freshness 모델

파일 존재 여부만으로 완료를 판정하지 않고 다음 세 축을 독립적으로 기록합니다.

| 축 | 상태 |
|---|---|
| 무결성 | `valid`, `corrupt`, `missing` |
| 현재성 | `current`, `superseded` |
| 검증성 | `verified`, `partially_verified`, `unverified` |

과거 QA나 package는 canonical state가 바뀌어도 결합된 과거 fingerprint에 대해서는 `valid`일 수 있습니다. 다만 현재 설계를 대표하지 않으므로 `superseded`로 표시합니다.

### 실행 안전성 구현

- 한 job에 대한 명시적 write lock과 stale lock 복구
- 각 step의 input/output hash, attempt, 시작·종료 시각과 실행 버전 기록
- 실패 재시도 시 이전 attempt를 덮어쓰지 않음
- agent 저작 출력은 기존 단계의 canonical 위치와 schema를 검증하고 exact input/output completion marker를 남김
- 결정론적 host 단계는 unique attempt receipt와 bounded resume를 사용하며 실패 자동 재시도를 금지
- CLI와 MCP가 동일한 orchestration service와 상태 계약 사용
- immutable QA, optimization과 package ID의 재사용·overwrite 금지

### 완료 기준과 V0.9 잔여 검증

- “이 이미지로 정적 3D 모델을 만들어줘”가 새 job으로 안전하게 라우팅됨
- 다른 이미지에 기존 job ID를 재사용하지 않음
- 기존 자산 수정은 create가 아니라 revision으로 라우팅됨
- 멀티뷰 추가는 `add_view`로 라우팅됨
- 외관 요청은 실내 생성으로 라우팅되지 않고, 명시적 실내 요청도 exact scope hash 승인 전에는 authoring을 시작하지 않음
- 모든 canonical 변경이 archive, fingerprint와 승인 경계를 통과함
- 프로세스 중단 후 재개해도 완료된 immutable run을 손상시키지 않음
- concept, add-view, revision, material-only, QA-only, portable-only plan이 기존 단계의 approval 경계를 보존
- background preview/package plan이 일반 검토만 생략하고 전용 exact-hash 승인을 보존
- background 정책이 measured, interior, runtime, external-provider 요청을 job 생성 전에 거부
- 기존 V0.2~V0.7 workspace를 재작성하지 않고 상태를 재구성함
- host failure, 명시적 retry, interrupted attempt, 동시 실행과 stale lock 복구 테스트 통과
- 더 넓은 failure injection, junction escape, 장기 queue와 운영체제별 복구는 V0.9에서 확대

V0.8은 새로운 범용 3D 복원 알고리즘을 의미하지 않습니다. 이미 검증된 분석·형상·재질·QA·패키징 기능을 일관되게 조율하는 단계입니다.

## 11. V0.9 — Stabilization + Codex Destination Handoff

**상태: 수정된 로컬 완료 기준 구현 및 Windows 11/Blender 5.0.1 격리 gate 완료. V1.0 승격은 중단되어 있습니다.**

### 목표

기존 V0.8까지의 자산 계약을 안정화하고, passed V0.7 engine-neutral package를 다른 목적지 프로젝트의 Codex가 안전하게 해석할 수 있는 hash-bound 조립·재질·import 계약으로 전달합니다. 목적 엔진 API를 직접 호출하지 않습니다.

### 구현된 안정화 범위

- 기존 Blender compatibility JSON을 hash로 참조하는 privacy-safe environment probe
- immutable input hash, contract readability/version, workflow pointer, handoff binding과 path escape를 검사하는 bounded read-only workspace audit
- exact terminal workflow만 동일 볼륨 `workspace_archive/`로 원자 이동하고 plan/receipt/tree
  digest로 복원하는 reversible workspace archive (`failed`는 명시적 opt-in, active/AQ는 거부)
- 기존 V0.8 workflow만 실행하는 one-writer/one-worker local queue
- execution lease, immutable attempt receipt, live/expired lock 처리와 explicit failed retry
- 권위 변화가 없는 reconcile의 state/latest byte·SHA·timestamp 안정성과, production advance의
  exact before/after snapshot 및 `previous.after == next.before == current-tail` 계보 검증
- exact probe/audit source hash에 묶인 stability PDF와 sidecar
- strict `0.9.0` JSON Schema, CLI/MCP allowlist와 격리 PowerShell/POSIX gate
- 기존 V0.2~V0.8 계약을 재작성하지 않는 compatibility 정책과 수동 migration 원칙
- 외부 `.blend`/`.fbx`/`.glb`의 safe-mode inspection, immutable dependency copy,
  meter 정규화, exact-hash approval과 V0.7/V0.9 provenance를 제공하는 선택적
  External Static Asset Intake

### 구현된 Codex Destination Handoff 범위

- `portable_gltf`와 `fbx_interchange` package만 허용하고 OBJ는 거부
- matching `passed` clean-import round trip과 exact package manifest SHA-256 요구
- 원본 package를 변경하지 않는 별도 immutable movable envelope
- 모든 package/texture/handoff 파일의 relative path, SHA-256와 dependency 검증
- semantic ID, hierarchy, local transform, material assignment, 반복 instance, pivot, LOD와 Collider 조립 계약
- base color, normal, metallic, roughness, occlusion, emission, opacity와 glTF ORM 의미를 보존하는 material mapping
- Blender procedural shader bake 여부와 알려진 손실 기록
- package metadata를 untrusted data로 취급하고 임의 코드 실행을 금지하는 목적지 Codex prompt
- 목적지 변경 전에 `import_plan.json`과 exact 사용자 승인을 요구하고 완료 후 receipt/validation을 요구하는 schema
- V0.8 optional `destination.handoff` agent step과 exact package/handoff completion marker
- V0.9 workspace audit, export/full PDF와 stability PDF에 handoff 생성·검증 상태 표시

### V0.9 완료 기준

- engine-neutral FBX/GLB package 생성 계약과 V0.7 clean-import round trip 유지
- complete assembly/material handoff 계약과 safe destination Codex prompt
- handoff manifest가 exact package/handoff hashes에 결속됨
- canonical SceneSpec, geometry, authoring `.blend`, source texture와 원본 package 변경 0건
- V0.8 workflow 연결과 V0.9 audit/PDF/gate 연결
- 기존 V0.7~V0.9 회귀 통과
- 테스트한 범위와 미검증 목적지 runtime을 명확하게 분리

### 현재 완료 범위에서 제외

- Unity Editor 또는 Unreal Editor 자동 실행
- Prefab/Actor, 목적 엔진 material graph와 runtime shader 자동 생성
- engine runtime parity 주장
- CAD B-Rep, rig, skinning과 animation
- macOS/Linux와 Blender 4.x 실기동 지원 주장
- 공개 배포, installer, code signing과 cross-platform release matrix
- 다양한 실제 자산의 장기 benchmark와 분산 scheduler

위 항목은 현재 V0.9 미완성으로 취급하지 않는다. 특히 자동 Destination Adapter는 목적 엔진·버전·렌더 파이프라인이 확정된 뒤 V1.1 이후 별도 마일스톤에서 구현·검증한다.

V0.9 queue는 의도적으로 `max_concurrency=1`이다. 테스트하지 않은 Blender, 운영체제 또는 엔진을 지원한다고 표시하지 않습니다.

## 11A. Autonomous Quality Extension 0.1.0 — 선택적 병렬 확장

**상태: 현재 프로젝트 `0.9.1` 위의 opt-in 확장. V1.0 승격 근거로 자동 해석하지 않습니다.**

AQ는 기존 단계나 실행 정책을 교체하지 않습니다. 새 `concept`,
`primary_object_only`, 명시적 target의 정적 소품에 `autonomous_static_prop_v1`을 선택하면
새 `standard` V0.8 workflow/V0.9 production dispatch 위에서만 supervisor가 동작합니다.
기존 `standard`와 `background_exterior`의 승인, retry, package와 terminal 의미는 그대로
유지합니다.

```text
exact request/reference/target
→ RootAuthorization + immutable profile/budget
→ local Reference Evidence
→ workflow-owned initial/structural/parametric/material candidates
→ exact single-use PolicyAuthorization
→ Integrated Quality four-axis gate
   ├─ accepted → V0.7 portable GLB + fresh clean import → quality_passed
   └─ non-pass/unscorable/bounded stop → review-only bundle → review_required
```

구현된 범위:

- 최대 3개의 local foreground mask 후보와 perspective/orthographic camera hypothesis
- SceneSpec `0.3.0`의 loft, sweep, boolean tree, multi-loop extrusion과 whitelisted GN 구조
  materializer
- 기존 V0.6 direct score를 바꾸지 않는 reference/structure/material/production 네 축 IQ
- hard gate, unavailable=`unscorable`, meaningful gain, Pareto/lexicographic 최소 변경 선택
- immutable budget, duplicate/oscillation/plateau/repeated-failure 종료와 best-known 보존
- V0.5 workflow-owned material candidate와 strict host promotion
- 기본 최대 2회의 material round, first-use authorization 저장 후 reload/full validation
- final IQ/package/roundtrip 또는 review bundle을 재검증하는 terminal verifier
- immutable package-ID 충돌 또는 format-only roundtrip failure만 대상으로 하는 기본 1회
  derived package repair
- deterministic host 및 선택적 Blender benchmark
- Windows 장경로 package/handoff 재귀 digest parity와 변조 fail-closed

`preauthorized_profile`은 사용자가 미래 artifact를 승인했다는 뜻이 아닙니다. 최초 요청과
profile에 결속된 routine gate를 policy engine이 exact artifact마다 다시 검증하는 기계
권한입니다. InteriorScope, interior-QA camera plan, destination import plan,
reference/content scope/target 변경, budget 확대, external provider, engine-specific write와
임의 코드는 계속 자동화할 수 없습니다.

SceneSpec V03 public plan/apply는 explicit exact plan hash를 사용하지만 canonical migration이
아닙니다. `structural_migrations/<migration-id>/`에 derived copy와 receipt만 게시하고 기존
`analysis/scene_spec.json`은 `0.2.0`으로 유지합니다. AQ structural assignment는 선택적으로
full V03 candidate를 candidate-owned mesh/receipt/`.blend`로 materialize하고 기존 build가 읽는
path-backed V02 candidate로 compile할 수 있지만, exact promotion 전 canonical은 바뀌지
않으며 legacy job도 자동 migration하지 않습니다.

품질 통과 package는 raw PBR channel, relative dependency와 fresh clean-import roundtrip을
요구합니다. package repair도 새 passed roundtrip 없이는 acceptance를 만들지 않습니다.
품질 미달 review bundle은 사람이 확인할 best-known 산출물이지만
`production_ready=false`, `destination_handoff_eligible=false`이고 production package 또는
Destination Handoff 입력이 아닙니다.

현재 비목표와 제한:

- arbitrary reference 전반에서 품질 향상을 보장하는 일반화 benchmark
- interior, measured asset, environment용 active autonomy profile
- rig, animation, gameplay 또는 destination engine 자동 import
- generated target나 external ML provider를 자동 승인 근거로 사용
- SceneSpec V03 derived copy의 canonical 승격
- V1.0 또는 cross-platform/runtime parity 주장

2026-08-10 Windows 11/Python 3.14.6/Blender 5.0.1에서 전체 pytest, Ruff, 실제 AQ Blender
package/review terminal, benchmark와 chained V0.7~V0.9 gate가 통과했습니다. 이 판정은
`autonomous_static_prop_v1`의 명시된 범위에만 적용됩니다. 기준선 결과나 contract fixture,
이 검증만으로 일반 release-ready, 임의 reference의 before/after 품질 향상, cross-platform
또는 destination runtime parity를 주장하지 않습니다. exact 결과는
`VERIFICATION_AUTONOMOUS_QUALITY_KO.md`를 따릅니다.

## 11B. Autonomous Quality Extension 0.2 — 비활성 실험 확장

**상태: `autonomous_static_prop_v2`는 `disabled_experimental`입니다. 프로젝트 버전은
`0.9.1`, canonical SceneSpec은 `0.2.0` 그대로입니다.**

AQ 0.2는 AQ 0.1과 기존 V0.7~V0.9 경로를 바꾸지 않고 geometry·material controller 후보를
각각 검증·승격한 뒤 외부 Integrated Quality 0.2 제출 경계로 진행합니다. `needs_revision`과
`unscorable`은 exact review bundle에서 끝나고, `blocked`는 bundle/freeze 없는 blocked terminal로,
pass는 exact source freeze를 만든 뒤 `review_only` 또는 포맷별 V0.7 plan hash를 사용자가 정확히
승인한 GLB/FBX delivery로만 이어집니다.

```text
geometry candidate/promotion
→ material candidate/promotion
→ external IQ 0.2 submission
→ quality_approved freeze, review_required bundle, 또는 blocked terminal
→ review_only 또는 exact-approved GLB / FBX delivery
```

ControllerExecutor는 execution-owned workspace, exact input snapshot, declared output와
request-bound receipt만 교환하며 canonical job root를 controller에 제공하지 않습니다. 공개
`plan`, `status`, `advance`, bounded `run`, `cancel` CLI/MCP가 추가됐지만 approval 합성,
임의 코드, destination write 또는 기존 증거 migration 권한을 주지 않습니다.

desktop wait의 resume는 새 execution을 만들지 않고 동일 request/workspace만 대상으로 합니다.
`advance`/`run`은 exact output이 나타난 뒤 request·result·profile·receipt와 시작 시 protected job
inventory를 다시 확인하며, 변경·중복·stale replay 또는 budget 재소비는 fail-closed입니다. state
chain은 모든 predecessor 전이와 monotonic budget을 재구성할 수 있어야 합니다.

execution-root/adoption result recovery는 전체 executor lifecycle과 exact stored result bytes를
재구성하며, 직접 side effect 전에 active·미만료 RootAuthorization과 exact plan/profile/budget을
재검증합니다. AQ v2 timeout은 bounded retry 대기가 아니라 nonretryable failed terminal입니다.

IQ 0.2 quality freeze는 제출 당시 값을 신뢰하지 않고 exact global/semantic PNG bytes에서 metric과
decision을 host가 재계산한 뒤 현재 canonical source와 필수
`geometry_candidate_validation_receipt`/`material_phase_receipt`에 결속됩니다. typed raw receipt가
없는 required scored landmark/multi-view는 pass authority가 없고, authoritative hard finding은 pass를 차단하며, nested
`QualityTerminalV2` 검증은 IQ report, source freeze 또는 review bundle과 내부 artifact hash까지
재검증합니다.

2026-08-12 Material Loop 이전 통합 snapshot은 전체 pytest `1438 passed, 44 skipped, 8 warnings`, AQ focused gate
`485 passed, 22 skipped, 8 warnings`, 실제 Blender gate `34 passed, 6 warnings`, 그리고 V0.7/V0.8/V0.9 gate
통과입니다. 실제 Blender 범위는 선택된 structural/material fixture와 같은 freeze에서 각각
직접 생성한 synthetic GLB+FBX dual-delivery fixture입니다. 다음 항목이 남아 있으므로 profile을
활성화하지 않습니다.

- Codex App Server 또는 supporting-client의 end-to-end closed loop 실행·격리 attestation
- 다양한 실제 reference에 대한 사람의 품질 판정과 장기 benchmark
- Unity, Unreal 또는 custom destination의 runtime import/material parity

cross-platform release matrix, canonical material preview lifecycle, 원격 CI run과 일반화된
asset-quality 향상 주장은 profile blocker와 별개로 남은 추가 미검증 제한입니다.

### 2026-08-29 실제 reference 5개 One-Prompt 캠페인

서로 다른 weathered plastic, rusted metal, weathered wood, crystal/emission,
shared-material hard-surface reference 5개로 `aq-one-prompt-orchestrator`를 실행했습니다.
Reference, Geometry controller와 실제 Blender 승격, Material controller/graph compile/Blender 승격,
V0.6 7-pass와 IQ 0.2까지는 모두 도달했습니다. 추가 사용자 결정과 technical user approval request,
canonical corruption은 각각 0건이었습니다.

최초 실행의 V0.6 direct score는 `0.400147`~`0.547703`, IQ boundary F-score는
`0.017883`~`0.086636`이었고 5개 모두 required contour hard gate에서 `blocked`됐습니다. 또한
ControllerExecutor protected inventory와 adapter orphan route 결함을 실제로 재현했습니다.

이후 route/receipt exact recovery, terminal projection reconciliation, `skill_runs/` ownership 분리와
orphan policy authorization recovery를 보강하고 동일 reference를 V0.4 structural re-entry한 R2
캠페인을 실행했습니다. R2 V0.6 direct score는 `0.959022`~`0.991305`, IQ boundary F-score는
`0.642257`~`1.000000`입니다. plastic/wood/crystal/laser 4개는 IQ pass와 source freeze를 게시했고
`plan_delivery`에서 정지했으며, rust 1개는 boundary F hard gate로 safe blocked terminal이 됐습니다.
새 adapter route/receipt는 5/5 닫혔고 pending route, 추가 사용자 결정, technical user approval,
canonical corruption은 모두 0입니다.

portable GLTF delivery/clean-import의 단일 wood canary를 실행했지만 R2 source freeze에 approved
ShaderRecipe가 없어 package 생성 전에 fail-closed 종료했습니다. 실제 beauty는 0.08 m 얇은 silhouette
proxy여서 volumetric assembly와 surface fidelity가 production 품질에 미달하며, exact R2 beauty 5개에
대한 별도 human disposition도 모두 `needs_revision`으로 기록했습니다. future volumetric beauty에는 이
판정을 재사용하지 않습니다.

이후 같은 reference 5개를 depth-bearing R5 후보로 fresh 실행했습니다. Geometry/Material/V0.6/IQ는
5/5 도달했고 adapter route/receipt도 5/5 terminal로 닫혔지만, IQ pass/source freeze는 crystal 1/5뿐이며
plastic/rust/wood/laser는 required contour hard gate에서 `blocked`됐습니다. crystal delivery는 Approval
Envelope 0.3 packaging parser 결함을 재현해 technical terminal로 끝났습니다.

같은 wood reference의 R6/R7/R8 fresh canary를 통해 package-local GLTF temporary ACL과 clean-import UV
serializer tolerance 결함을 수정했습니다. R8은 exact ShaderRecipe와 source freeze에서 portable GLTF
package 26개 파일, absolute path 0, missing dependency 0, round-trip clean import와 geometry survival을
통과해 `production_ready=true`로 완료했습니다. 이 결과는 단일 local GLTF canary이며 destination parity
증거가 아닙니다.

signage/decal은 isolated immutable input이 없고, dependency-rich texture/bake closure는 새 job에 이전할
별도 authorization과 bake contract가 없어 실행하지 않았습니다. 현재 volumetric candidate 5개의 exact
human disposition도 0/5입니다. profile은 계속 `disabled_experimental`이며 activation 판정은 NO-GO입니다.
정확한 자산·session·점수·KPI·결함과 다음 실행 조건은
[AQ One-Prompt 실제 reference 5개 캠페인 검증](../verification/VERIFICATION_AQ_ONE_PROMPT_5_ASSET_CAMPAIGN_KO.md)에
기록합니다.

2026-08-31 후속 Stage 9 준비 R1~R4에서는 R3 exact beauty 5개를 모두 `needs_revision`으로
기록한 뒤 material-identity R4를 fresh 실행했습니다. R4는 IQ/source freeze 4/5, rust blocked 1/5,
V0.7 승인 대기 4/5였고, 사용자는 review request
`37443f12078e8c2d152647115c3271cd7c4da30fa1ef0e04c524eb18d0ffb7d6`의 exact beauty 5개도
모두 `needs_revision`으로 기록했습니다. Wood의 contour `1.0`이 V0.6 high missing finding을 가린
coverage gap과 Laser의 flat-relief 한계를 확인했으므로, 다시 5개를 반복하지 않고 신규 policy-bound
V0.6 finding bridge와 bounded beveled-relief/composition capability를 단일 Laser canary로 분리
검증했습니다.

clean commit `6572b22d45dba610e3b69468bedf4e2b34c6296c`와 tree
`c4e3ff480db0f5e52f1994471eca0572a4e2e774`에서 source manifest
`activation-source-26f37fa8e845482a5309e11e`, baseline
`activation-baseline-4de9c955ee1e3716a4b14b49`를 게시했습니다. 첫 R5 Laser는 18개 object가
고정 `total_blender_builds=14`를 초과해 실제 materialization 전에 safe technical terminal로 닫혔고,
canonical corruption과 technical user approval request는 0입니다. 그 terminal을 exact binding한 R5B는
R4의 10개 관측 panel을 beveled relief로 바꾼 11-object 범위에서 geometry 12 + material 2의 예산을
정확히 사용해 V0.6 direct `0.972529`, silhouette IoU `0.968892`, IQ boundary F `0.878565`,
chamfer `0.002242`로 pass/source freeze에 도달했습니다. exact beauty
`c497f6751f3918d1665efe6c7ab5ab313388de0630eb75437f6996aa76f7cafd`는 `needs_revision` 1/1로
기록됐고, R5B는 delivery unauthorized 상태를 유지합니다. Production assembly detail을 고정 예산 안에
보완한 R5C composition canary는 V0.6 direct `0.932642`, IQ boundary F `0.627697`에서 safe
`blocked`됐고 exact beauty
`b0193e2b7a3893913e05dc1ee6a5de261ce09dc256c727a01ebb98ad030651b1`가
`needs_revision`으로 기록됐습니다. 같은 immutable reference의 bounded perspective compensation을 적용한
R5D는 V0.6 direct `0.946730`, IQ boundary F `0.816738`로 IQ/source freeze에 도달했고 exact beauty
`b538f7acc0ff84c427dd5a70b7268e89696cc2955b6e5e33868493049575e6ec`가 `accepted`로
기록됐습니다.

사용자는 R5D portable GLTF 최적화 계획 SHA-256
`65c13c1e2ccacaa056ad40b5bbe5ec8d4ffe2cfe4bd6a3a27b16dda74acecd95`를 exact
승인했습니다. 원래 host delivery는 immutable failed state/terminal로 종료됐고, append-only R01~R06은
n-gon tangent, adapter signature, Windows GLTF temp path, serialization topology와 UV fingerprint 경계
결함을 각각 분리했습니다. R06 package는 26개 파일, absolute path 0, missing dependency 0, clean-import
round-trip pass를 기록했고 R07 evidence-only revalidation은 geometry survival `known_loss`와
`technical_package_validated=true`를 기록했습니다.

2026-09-01 사용자는 technical package `r5d-recovery-r06-gltf`의 manifest SHA-256
`2ddcfd0e2125871e22282a3a4fd9558364bbfc673d6a8a71806e5821f0b97257`과 post-publication
round-trip SHA-256 `227783a4065df4283027e5ae94c91206d84c71dd2bf91df1e622913bc0bd620c`를
exact package acceptance 대상으로 승인했습니다. Host는 둘을 재검증한 뒤 single-use acceptance
`package.acceptance.2ddcfd0e2125871e22282a3a`를 소비했고, acceptance JSON의 file SHA-256은
`c6ad1650ef9ada5e2017381da942dbad35a9222352bb599baaeba526e5cab1df`입니다. 기록은
`canonical_unchanged=true`, `destination_project_modified=false`, clean import/bounds pass와 semantic/material
coverage `1.0/1.0`을 보존합니다. 원래 failed state SHA-256
`8cd9e923fc60b5e69dc7de6af06c70005a1634471f74cc071e9a1b0b6a45d621`와 delivery terminal SHA-256
`5c116036df12c868aebf68167332178771a264179df7e5a351a272ead51312ae`는 변하지 않았고, R07의
historical `host_delivery_adopted=false`도 소급 수정하지 않습니다. 따라서 portable GLTF package-level
acknowledgement는 닫혔지만 destination write, runtime parity 또는 profile Activation 권한은 생기지 않았습니다.
기존 R1~R07 machine evidence와 disposition은 고쳐 쓰지 않습니다.

2026-09-02 clean commit `84e585898fe44dcd85f24f2093892813b889f79c`에 결속된 B8 plastic-shard
canary는 IQ pass/source freeze와 `delivery_pending`까지 진행한 뒤 review request SHA-256
`731ac8f5bdf86e10da416d19d7c751cdaeada954f6a1c066a62aa4fef52c00d4`의 Beauty SHA-256
`82038452582297511a04669a415dc8e68b5ee5338d823415be2886ec08c367e0`가 exact
`needs_revision`으로 기록됐습니다. 이 실행은 기존 machine IQ를 낮춰 쓰지 않고 새
`human-quality-review-bundle` SHA-256
`54b25a95c31185adc72adbb397d28c93f4cf126ef6a9bf7af08eac3083e0bcca`와 AQ state
`review_required`, One-Prompt/skill adapter `review_bundle` terminal로 닫혔습니다. delivery run과
production package는 0이며 canonical source는 변하지 않았습니다. Activation의 strict usable-review
검증도 exclusion 0으로 통과했습니다.

B8은 동시에 machine-passed IQ 이후 human non-pass를 닫는 계약이 없었던 framework 결함을 발견한
canary입니다. 새 append-only contract, policy-before-state 정상 경로, exact interrupted-close recovery,
CLI/MCP/skill resume 및 Activation projection을 구현했으므로 소스가 baseline
`activation-baseline-ce171a5174e9d2e2409adb96`와 달라졌습니다. 따라서 B8은 결함 재현과 수정 검증의
역사적 증거로만 보존하며 새 Activation campaign의 1/5로 세지 않습니다.

최종 소스 회귀에서는 Blender image API가 `\\?\` extended temp path를 직접 받지 못하는 별도 경계를
발견해, GLTF image encoding을 process temp 아래의 짧은 고유 normal-path staging root에서 실행하도록
보완했습니다. package-local output과 canonical source는 바뀌지 않습니다. 공식 V0.7 gate는 전체
`2021 passed / 65 skipped`와 portable GLTF/FBX/OBJ clean import를 통과했고, AQ gate는 focused
`935 passed / 26 skipped`, 실제 Blender `47 passed / 1 skipped`, AQ 0.1/0.2 benchmark
`8/8`과 `10/10`을 통과했습니다. 이 기술 회귀 통과도 R06 package의 사후 host acceptance나 profile
Activation 권한을 생성하지 않습니다.

상세 설계·실행·검증 경계는 [AQ 0.2 아키텍처](../architecture/ARCHITECTURE_AQ_V02_KO.md),
[시작 가이드](../guides/GETTING_STARTED_AQ_V02_KO.md), [테스트 계획](../testing/TEST_PLAN_AQ_V02_KO.md),
[검증 기록](../verification/VERIFICATION_AQ_V02_KO.md)을 따릅니다.

## 11C. Codex Built-in ImageGen Texture Provider 0.1.0 — 비활성 선택 확장

이 companion은 AQ v2의 geometry candidate validation/promotion이 완료된 material 시작점에서 제한된 visual source 후보를
얻기 위한 별도 overlay다. 기존 `autonomous_static_prop_v2` local-only profile을 바꾸지 않으며
신규 `autonomous_static_prop_v2_codex_imagegen`도 **`disabled_experimental`** 상태다.

구현 범위:

- current Codex task가 읽는 strict plan/assignment와 immutable generation budget
- built-in ImageGen만 허용하는 controller-mediated request-owned workspace
- exact PNG/completion, ControllerResult와 protected source inventory 재검증
- append-only overlay state와 app-exit 후 same-request resume
- plan-item capacity fallback과 final controller result를 exact request/result-bound terminal로 종료
- direct base-color/decal/emission/opacity-source만 허용하는 image evidence
- deterministic raster hard gates와 single-candidate core selection
- exact local signage text composition
- selected source-bound local PBR derivation을 위한 MaterialAuthoring `0.2.1`
- fake controller와 actual built-in ImageGen evidence 분리
- status/plan/run/select/two-mode adopt CLI와 동등 MCP host surface

2026-08-13 additive Material Loop 구현 범위:

- native PNG immutable adoption, adoption-receipt-bound deterministic normalization과
  `CodexImageNativeCorePreparationReceipt`의 exact normalized-to-core completion/selection closure
- current-task `human_reviewed=false` semantic review
- 모든 후보의 exact ranking evidence를 요구하고 bridge/controller/promotion까지 receipt를 결속하는
  companion-only multi-candidate precedence
- V0.5 normalized/bridge evidence와 exact canonical MaterialPlan absence
- strict bridge plan/controller input/binding과 append-only companion state/terminal
- V0.5 staging-only/compile-not-run 의미를 보존하는 actual Blender shadow preflight와 preflight 없는
  `exact_adoption` 거부
- `controller_authored_completion`의 exact three-file ControllerExecutor lifecycle
- 기존 host material service의 MaterialGraph compile, canonical CAS, Blender rebuild/rollback
- actual `MaterialPhaseReceiptV2`, fixed neutral preview, base AQ resume와 IQ `0.2.0` 경계
- bridge/status/run, exact-adoption-preflight, promote/resume, native-normalize, semantic-status와
  continue CLI 9개/MCP 9개

영구 안전 경계:

- repository-side API key, OpenAI SDK, external HTTP image provider와 API billing 없음
- repository task spawning, background daemon과 app-exit continuation 없음
- provider의 canonical MaterialPlan, Blender scene 또는 destination-project 직접 write 없음
- generated normal/roughness/height/AO를 authoritative channel로 직접 채택하지 않음
- ImageGen completion/selection이 material promotion, V0.7 approval 또는 package 승인이 아님
- core staging receipt는 base AQ를 자동 재개하지 않음; Material Loop도 actual host receipt 전에는 전진 금지
- material promotion과 IQ pass는 분리하며 IQ pass에만 `quality_approved` 사용
- semantic observation, human review, V0.7 approval과 destination parity 합성 없음

현재 활성화하지 않는 이유:

- built-in ImageGen의 일반 prompt/reference 품질과 반복 가능성을 한정된 smoke 밖으로 확대할 수 없음
- unwanted object/text와 style/background semantic alignment는 local metric에서 `unscorable`
- 사람 review, generalized material quality와 destination runtime parity가 별도 증거를 요구함
- fixed fake/Blender fixture와 실제 built-in smoke는 서로 다른 verification scope임
- fake four-family host/Blender material-IQ mechanism은 actual ImageGen 품질 증거가 아님
- historical actual source reuse는 fresh invocation이 아니며 non-human semantic review가
  `review_required`여서 promotion 전에 멈춤
- approval 없는 raw GLB/FBX clean import는 production package acceptance가 아님
- actual user-approved V0.7 production package와 destination runtime은 미검증

향후 활성화 검토에는 exact controller capability/smoke evidence, semantic review 정책, 실제 자산
corpus의 material/Blender/package 검증과 명시적 profile 정책 변경이 필요하다. migration, README 문구
또는 한 번의 성공으로 `verified_active`를 합성하지 않는다.

상세 내용은 [ImageGen 아키텍처](../architecture/ARCHITECTURE_CODEX_IMAGEGEN_PROVIDER_KO.md),
[시작 가이드](../guides/GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md),
[테스트 계획](../testing/TEST_PLAN_CODEX_IMAGEGEN_PROVIDER_KO.md),
[마이그레이션 정책](../migration/MIGRATION_CODEX_IMAGEGEN_PROVIDER_KO.md),
[검증 기록](../verification/VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md),
[Material Loop 아키텍처](../architecture/ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md)와
[Material Loop 검증](../verification/VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다. 실제 current-task 요청은
[Material Loop 프롬프트 모음](../prompts/IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md)에서 profile opt-in, native 원본
보존, semantic `human_reviewed=false`, host-only promotion과 approval/package 정지 경계를 함께 사용한다.

## 12. V1.0 — Integrated Reference-to-Asset Pipeline

**상태: 승격 중단. 재개 시 제품 범위와 아래 완료 기준을 다시 검토하기 전에는 V1.0으로 표시하지 않습니다.**

### 제품 목표

하나의 저장소에서 레퍼런스, 직교 도면, 치수와 사용자 피드백을 재현 가능한 정적 Blender 자산과 검증된 portable package로 변환합니다.

```text
input evidence
→ reference/camera analysis
→ modeling plan and constraints
→ proxy and detailed geometry
→ material, texture and shader
→ fixed-camera QA and guarded revision
→ portable optimization and package
→ optional hash-bound Codex Destination Handoff
```

### 사용자 경험

기본 생성:

```text
이 이미지로 정적 3D 모델을 만들어줘.
보이지 않는 부분은 추정으로 구분하고 프록시 승인에서 멈춰.
```

수정:

```text
중앙 탑만 15% 높이고 나머지는 유지해줘.
```

재질:

```text
레퍼런스에 맞는 재질과 셰이더를 만들고 swatch 승인을 기다려.
```

전달:

```text
이 승인된 정적 자산을 FBX와 raw PBR sidecar로 검증해서 패키징해줘.
```

### 필수 완료 기준

#### 입력과 분석

- single reference, multi-view, blueprint와 explicit dimensions의 지원 경계가 명확함
- observed, measured, inferred, authored 상태를 구분함
- 입력 원본과 모든 추가 view의 hash와 교체 이력을 보존함
- 카메라와 절대 치수를 알 수 없을 때 underconstrained로 보고함

#### 형상과 수정

- stable semantic ID와 canonical SceneSpec으로 재빌드 가능
- 지원 geometry recipe와 modifier가 실제 Blender에서 검증됨
- 사용자 수정이 승인된 ID/path만 변경함
- 큰 외형 수정은 V0.4 workflow로, 국소 QA 보정은 V0.6 workflow로 라우팅됨
- topology 품질과 format 손실을 숨기지 않음
- 실내는 기본 비활성화이며 사용자 요청과 현재 InteriorScope hash 승인이 모두 있는 범위만 생성함
- facade helper와 실제 interior semantic object를 구분하고, 승인되지 않은 방·층·가구를 추가하지 않음

#### 재질과 셰이더

- Blender master shader와 portable PBR 의미를 분리함
- texture provider의 모델/버전/prompt/seed/hash/권리 정보를 기록함
- color space, UV, texel scale, bake와 stale scene을 검증함
- 특정 엔진 셰이더를 portable package와 동일하다고 주장하지 않음

#### QA와 안전

- 직접 reference·실측 근거가 생성 이미지보다 우선함
- 7개 고정 카메라 pass와 direct report를 재현함
- exact candidate와 single-use approval 없이는 canonical 수정 불가
- 비개선·constraint regression·검증 실패 시 자동 복구함
- QA 점수를 사람의 품질 승인이나 진실 확률로 표현하지 않음

#### 최적화와 전달

- canonical authoring 데이터를 수정하지 않는 derived optimization
- raw PBR 보존, immutable package, dependency와 absolute path 검사
- clean import 후 bounds와 profile이 선언한 identity coverage 검증
- 목적 엔진 미지정 시 engine-neutral package에서 정상 종료
- 요청 시 package-bound Codex Destination Handoff를 생성하고 목적지 Codex가 import plan과 사용자 승인을 거치도록 함
- 자동 Destination Adapter나 runtime parity를 V1.0 core 완료 조건으로 간주하지 않음

#### 운영과 문서

- 짧은 요청, 긴 요청, 재개, 실패 복구와 승인 대기 상태가 일관됨
- 지원 환경의 clean install과 전체 게이트가 문서대로 재현됨
- machine JSON이 authoritative이고 PDF는 읽기 전용 projection임
- 모든 공개 계약, migration, known limitations와 rollback 절차가 문서화됨

V1.0에서 호환 변경이 없는 기존 계약은 버전 번호를 억지로 `1.0.0`으로 올리지 않습니다. 예상 버전 구조는 다음과 같습니다.

```text
Project                 1.0.0
Geometry SceneSpec      0.2.0
Reference/Constraint    0.4.0
Material/Shader         0.5.0
Visual QA               0.6.0
Portable Asset          0.7.0
Workflow Orchestration  0.8.0
Stabilization Evidence  0.9.0
Destination Handoff     0.9.0
```

### CAD 명칭 사용 조건

V1.0을 `Reference/CAD-to-Asset`이라고 부르려면 파일을 단순 보관하는 수준이 아니라 실제로 파싱하고 geometry/constraint로 변환하는 CAD 경로가 검증되어야 합니다.

- 최소 한 종류의 2D vector/blueprint 형식
- 최소 한 종류의 3D CAD interchange 형식 또는 명시적으로 검증된 외부 adapter
- 단위, 축, layer/object identity와 누락 feature 보고
- clean import와 실제 형상·치수 검증

현재 V0.9 core에는 실제 CAD parsing과 B-Rep 변환이 없으므로 V1.0의 공식 목표 명칭은 `Reference-to-Asset`으로 제한합니다. 향후 사용자가 CAD 범위를 명시적으로 선택하고 위 조건을 구현·검증한 경우에만 `Reference/CAD-to-Asset` 명칭을 다시 검토합니다.

## 13. 단계 되돌아가기와 stale 전파

작업 단계는 일방통행이 아닙니다. 마음에 들지 않는 형상이나 재질을 발견하면 현재 저장소를 유지한 채 해당 authoring 단계로 돌아갑니다.

| 변경한 canonical 입력 | 반드시 다시 확인하거나 생성할 단계 |
|---|---|
| reference 또는 auxiliary view | V0.3 분석 → V0.4 형상 → V0.5 → V0.6 → V0.7 |
| camera solution 또는 modeling plan | SceneSpec 검토 → build → V0.6 → V0.7 |
| SceneSpec 또는 `geometry/` | build/inspect/validate → V0.5 영향 검사 → V0.6 → V0.7 |
| InteriorScope 또는 scope approval | 실내 contract 검증 → build provenance 확인 → build/inspect/validate → 필요한 경우 V0.5 → V0.6 → V0.7 |
| MaterialPlan/ShaderRecipe/TextureManifest/image channel | rebuild → material inspect/swatch/bake → V0.6 → V0.7 |
| constraints | constraint solution과 모든 revision acceptance 재평가 |
| 승인된 V0.6 revision | build → material 영향 검사 → 새 QA run → 새 V0.7 run |
| V0.7 profile 또는 derived plan | 해당 optimization/conversion/package/round trip만 새 run으로 생성 |
| V0.7 package 또는 round-trip evidence | 기존 handoff를 stale로 표시하고 새 plan/handoff ID로 재생성 |

규칙:

1. 이전 canonical SceneSpec은 `history/`에 보존합니다.
2. 이전 QA, optimization과 package는 immutable evidence로 남깁니다.
3. stale 산출물을 덮어쓰거나 최신 결과처럼 표시하지 않습니다.
4. 변경 후에는 새로운 run ID, conversion ID와 package ID를 사용합니다.
5. source fingerprint가 달라지면 이전 V0.7 package를 재사용하지 않습니다.
6. 카메라 변경 후에는 과거 QA score를 동일 기준의 개선량으로 비교하지 않습니다.
7. package manifest 또는 round-trip hash가 달라지면 이전 Destination Handoff를 최신 전달물로 사용하지 않습니다.

## 14. 영구적인 한계와 비목표

V1.0도 단일 이미지에서 다음을 복원된 사실로 보장할 수 없습니다.

- 보이지 않는 후면과 내부 구조
- 사용자가 요청하지 않은 실내 공간, 층, 가구와 동선
- 실제 절대 깊이와 치수
- 가려진 부품
- 원 제작자의 topology와 construction history
- 사진 밖의 구조

이 값은 `inferred` 또는 `authored`로 표시하고 추가 view, dimension 또는 사용자 지시로 보완합니다.

V1.0 core의 기본 범위는 정적 자산입니다. 다음은 별도 명시적 확장 없이는 범위 밖입니다.

- 캐릭터 rig와 skin
- animation과 motion retargeting
- arbitrary organic character reconstruction
- Unity prefab 또는 Unreal actor의 무조건적 생성
- 모든 엔진에서 동일하게 동작하는 runtime shader
- 목적 엔진·버전·렌더 파이프라인 검증 전 자동 Destination Adapter 실행
- 모든 CAD 형식의 완전한 B-Rep 호환
- 이미지 한 장에서 완벽한 digital twin 생성

## 15. 문서와 릴리스 규칙

각 새 마일스톤은 최소한 다음 파일을 갖습니다.

```text
ARCHITECTURE_Vxx_KO.md
GETTING_STARTED_Vxx_KO.md
TEST_PLAN_Vxx_KO.md
VERIFICATION_Vxx_KO.md
```

추가 규칙:

- `ARCHITECTURE`는 데이터 흐름, 계약, 안전 경계와 비목표를 정의합니다.
- `GETTING_STARTED`는 깨끗한 설치부터 실제 사용까지 재현 가능한 명령을 제공합니다.
- `TEST_PLAN`은 정상·음성·회귀·Blender 통합 게이트를 정의합니다.
- `VERIFICATION`은 실제 환경, 날짜, 결과와 남은 미검증 항목을 기록합니다.
- 계획 문서만 존재하는 기능을 README의 구현 범위에 넣지 않습니다.
- 실제 검증 전에는 지원 버전이나 목적 엔진 parity를 주장하지 않습니다.

## 16. 현재 구현의 근거 문서

- [저장소 개요와 공개 기능](../../README.md)
- [저장소 작업 규칙과 source-of-truth](../../AGENTS.md)
- [V0.4 아키텍처](../architecture/ARCHITECTURE_V04_KO.md)
- [V0.4 테스트 계획](../testing/TEST_PLAN_V04_KO.md)
- [선택적 실내 범위와 승인](../guides/INTERIOR_SCOPE_KO.md)
- [V0.6 아키텍처](../architecture/ARCHITECTURE_V06_KO.md)
- [V0.6 테스트 계획](../testing/TEST_PLAN_V06_KO.md)
- [V0.6 로컬 검증 기록](../verification/VERIFICATION_V06_KO.md)
- [V0.7 아키텍처](../architecture/ARCHITECTURE_V07_KO.md)
- [V0.7 테스트 계획](../testing/TEST_PLAN_V07_KO.md)
- [V0.7.3 로컬 통합 검증 기록](../verification/VERIFICATION_V073_KO.md)
- [V0.7.4 최적화 사전 검토](../history/V074_PRE_OPTIMIZATION_REVIEW_KO.md)
- [V0.7.4 Blender 5 검증 기록](../verification/VERIFICATION_V074_KO.md)
- [V0.8 아키텍처](../architecture/ARCHITECTURE_V08_KO.md)
- [V0.8 빠른 시작](../guides/GETTING_STARTED_V08_KO.md)
- [V0.8 테스트 계획](../testing/TEST_PLAN_V08_KO.md)
- [V0.8 검증 기록](../verification/VERIFICATION_V08_KO.md)
- [V0.9 아키텍처](../architecture/ARCHITECTURE_V09_KO.md)
- [V0.9 빠른 시작](../guides/GETTING_STARTED_V09_KO.md)
- [V0.9 테스트 계획](../testing/TEST_PLAN_V09_KO.md)
- [V0.9 검증 기록](../verification/VERIFICATION_V09_KO.md)
- [Autonomous Quality 0.2 아키텍처](../architecture/ARCHITECTURE_AQ_V02_KO.md)
- [Autonomous Quality 0.2 시작 가이드](../guides/GETTING_STARTED_AQ_V02_KO.md)
- [Autonomous Quality 0.2 테스트 계획](../testing/TEST_PLAN_AQ_V02_KO.md)
- [Autonomous Quality 0.2 마이그레이션 정책](../migration/MIGRATION_AQ_V02_KO.md)
- [Autonomous Quality 0.2 검증 기록](../verification/VERIFICATION_AQ_V02_KO.md)
- [ControllerExecutor 격리 경계](../guides/CONTROLLER_EXECUTOR_KO.md)
- [AQ 0.2 delivery profile](../guides/DELIVERY_PROFILES_KO.md)
- [AQ 0.2 material authoring](../guides/MATERIAL_AUTHORING_KO.md)
- [AQ 0.2 quality benchmark](../guides/QUALITY_BENCHMARK_KO.md)
- [Codex Built-in ImageGen 아키텍처](../architecture/ARCHITECTURE_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 시작 가이드](../guides/GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 테스트 계획](../testing/TEST_PLAN_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 마이그레이션 정책](../migration/MIGRATION_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 검증 기록](../verification/VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex ImageGen Material Loop 아키텍처](../architecture/ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 시작 가이드](../guides/GETTING_STARTED_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 실사용 프롬프트 모음](../prompts/IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md)
- [Codex ImageGen Material Loop 테스트 계획](../testing/TEST_PLAN_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 마이그레이션 정책](../migration/MIGRATION_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 검증 기록](../verification/VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Material Closure Stabilization 아키텍처](../architecture/ARCHITECTURE_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 테스트 계획](../testing/TEST_PLAN_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 마이그레이션 정책](../migration/MIGRATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 검증 기록](../verification/VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 프롬프트 모음](../prompts/MATERIAL_CLOSURE_STABILIZATION_PROMPTS_KO.md)
- [Material Identity Split 아키텍처](../architecture/ARCHITECTURE_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 테스트 계획](../testing/TEST_PLAN_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 마이그레이션 정책](../migration/MIGRATION_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 검증 기록](../verification/VERIFICATION_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 프롬프트 모음](../prompts/MATERIAL_IDENTITY_SPLIT_PROMPTS_KO.md)
- [AQ Approval Envelope 아키텍처](../architecture/ARCHITECTURE_AQ_APPROVAL_ENVELOPE_KO.md)
- [AQ Approval Envelope 테스트 계획](../testing/TEST_PLAN_AQ_APPROVAL_ENVELOPE_KO.md)
- [AQ Approval Envelope 마이그레이션 정책](../migration/MIGRATION_AQ_APPROVAL_ENVELOPE_KO.md)
- [AQ Approval Envelope 검증 기록](../verification/VERIFICATION_AQ_APPROVAL_ENVELOPE_KO.md)
- [AQ One-Prompt 시작 가이드](../guides/GETTING_STARTED_AQ_ONE_PROMPT_KO.md)
- [AQ Approval KPI](../testing/AQ_APPROVAL_KPI_KO.md)
- [AQ One-Prompt 실제 reference 5개 캠페인 검증](../verification/VERIFICATION_AQ_ONE_PROMPT_5_ASSET_CAMPAIGN_KO.md)

현재 V0.9는 environment probe, read-only audit, reversible terminal workspace archive,
single-worker queue, strict schemas, stability PDF와 Codex Destination Handoff를 구현했습니다.
실제 gate와 지원 매트릭스 결과는 `VERIFICATION_V09_KO.md`에만 기록합니다. Handoff는 목적지
import 계획용 계약이지 자동 engine adapter나 runtime parity 증거가 아닙니다.

## 17. 과거 실행 순서와 재개 시 검토 조건

아래는 당시 실행 순서와 조건을 보존한 기록입니다. 2026-09-30 A안 종료 이후의 자동 실행 계획이 아닙니다.
현재 중단 위치·완료 결과·기존 소비와 소스 연결 제약은 [인계 문서](../HANDOFF_KO.md)를 우선합니다.

```text
0. 2026-08-29 최초 reference 5개 캠페인 증거 고정 [완료]
   - Geometry/Material 5/5, IQ blocked 5/5, fail-closed와 결함 증거 보존
1. One-Prompt/skill adapter와 policy recovery P0 보강 [완료]
   - orphan route exact recovery와 terminal projection reconciliation
   - adapter evidence와 controller protected inventory 소유 경계 분리
   - orphan policy authorization exact reuse/technical-failed closure
2. 같은 5개 reference의 V0.4 structural re-entry [완료]
   - R2 V0.6 direct `0.959022`~`0.991305`
   - 기존 실패 job/state/route/receipt는 불변 보존
3. 동일 reference 5개 One-Prompt R2 재캠페인 [IQ 경계까지 완료]
   - IQ pass/source freeze 4/5, rust safe blocked 1/5
   - adapter route/receipt closure 5/5, pending route 0
   - 추가 사용자 결정 0, technical approval 0, canonical corruption 0
   - pass 4개는 delivery 판단을 위해 `plan_delivery`에서 정지
4. R2 human quality disposition [완료]
   - 제시된 exact beauty SHA-256 5개 모두 `needs_revision`
   - machine IQ outcome과 분리하며 future volumetric candidate에 재사용하지 않음
5. 동일 reference volumetric R5 캠페인 [완료, 품질 기준 미달]
   - Geometry/Material/V0.6/IQ 5/5, adapter terminal 5/5
   - IQ pass/source freeze 1/5, required hard-gate blocked 4/5
   - crystal delivery technical failure는 새 parser 회귀로 고정
6. wood portable GLTF delivery/clean-import canary [R8 통과]
   - R6 package-local temporary ACL 실패와 R7 UV serializer sensitivity 실패 보존
   - R8 exact ShaderRecipe/source freeze/package/round-trip/survival 통과
   - 26개 파일 hash 일치, absolute path 0, missing dependency 0, canonical unchanged
7. 검증 가능한 activation coverage 마감 [R5D visual 및 exact package acceptance 완료]
   - Stage 9 준비 R1/R2는 safe technical terminal, R3와 R4 exact beauty는 각각 `needs_revision` 5/5 기록 완료
   - R4는 historical IQ pass/source freeze 4/5, rust blocked 1/5이며 R4 disposition set은 future beauty에 재사용하지 않음
   - Wood high direct finding을 policy-bound IQ 입력으로 연결하는 bridge와 bounded beveled-relief geometry capability 검증 완료
   - R5 18-object Laser는 고정 build budget 초과를 실제 Blender materialization 전에 fail-closed하고 adapter terminal까지 닫음
   - R5B 11-object Laser는 geometry/material/V0.6/IQ/source freeze 통과, 추가 사용자 결정 0,
     technical approval 0, canonical corruption 0으로 `await_v07_approval`에 도달했으나 exact
     `needs_revision`으로 delivery 진입을 중단
   - R5B review request `6c7e4270501b50cd6223b4f716439ba0bfa333bfde7898887c0af4ce2a9caf0b`와
     beauty `c497f6751f3918d1665efe6c7ab5ab313388de0630eb75437f6996aa76f7cafd`는 exact
     `needs_revision`으로 기록 완료; V0.7, budget expansion, activation 권한은 생성하지 않음
   - 동일 material의 2~32개 구조 operand를 기존 strict `boolean_tree`의 균형 `EXACT UNION` 한 개로
     합성하는 helper를 추가했으며, 여섯 분리 부품/한 materialization/여섯 connected component를 실제
     Blender 5.0.1로 검증
   - R5C material-identity composition은 고정 budget 안에서 실행했지만 IQ boundary F `0.627697` 및
     exact `needs_revision`으로 종료; perspective mismatch를 별도 원인으로 고정
   - R5D bounded perspective compensation은 IQ/source freeze와 exact beauty `accepted`에 도달했고,
     exact V0.7 optimization plan 승인도 기록 완료
   - 원래 host delivery 실패 terminal은 불변 보존; R01~R06 technical recovery와 R07 evidence-only
     revalidation을 거친 `r5d-recovery-r06-gltf`는 package/round-trip/geometry-survival 기술 검증 통과
   - exact manifest/round-trip 승인 뒤 single-use package acceptance
     `package.acceptance.2ddcfd0e2125871e22282a3a`가 소비되어 단일 Laser package 폐루프 완료
   - acceptance는 원래 failed AQ terminal이나 R07을 소급 변경하지 않고 destination write/profile Activation도
     승인하지 않음
   - 새 clean source checkpoint의 Registry/Eligibility/Index/Readiness가 Stage 9 진입과 AQ base NO-GO를
     별도 machine decision으로 재평가하기 전에는 profile 상태를 변경하지 않음
   - isolated immutable signage/decal reference와 별도 authorization이 필요한 dependency-rich Material Closure는
     누락을 숨기지 않고 명시적 input/authority blocker로 이월
8. clean commit ActivationSourceManifest/Baseline 재생성과 machine reassessment [완료]
   - source commit `9759cd4d380cb1c9a1ec0e2085e08a8c35e2657c`
   - current source manifest `activation-source-d6390b6bea77e86b54adce38`
   - current baseline `activation-baseline-6b01a9e911e0c573d60e30ab`
   - current candidate index `activation-index-d76aac7a953c0dd9f217e6ef`, eligible distinct asset `0/5`
   - current readiness `activation-readiness-13169fe71f12974fae1d609d`, status `validation_blocked`, blocker 9개
   - R5D는 이전 baseline `activation-baseline-79b982b0609008542b4ed754`에서 시작했고 원래 AQ delivery
     terminal이 `failed`이므로 새 baseline candidate로 소급 재결속하거나 완료로 재분류하지 않음
   - R5D exact beauty와 technical recovery package acceptance는 별도 append-only 성공 증거로 보존
   - `stage9-overlay-decision-e211057a1fc0ec605e748f84`는 ImageGen overlay의 bounded benchmark entry만
     `GO`, AQ base Activation은 `NO_GO`, campaign 생성은 `false`로 판정
   - 해당 decision의 `unresolved_local_framework_defects=0`은 선언된 R5D delivery-recovery 범위의 판정이며,
     이후 확인된 skill-run/current-summary cross-projection 부채까지 닫았다는 뜻이 아님
8-A. AQ Base First-Completion Closure [완료]
   - R5D 원래 failed AQ terminal과 과거 skill receipt를 수정하지 않고, exact recovery/package acceptance를
     연결하는 append-only skill-run terminal projection을 추가하여 `running/await_v07_approval` 잔류를 해소 [완료]
   - `verification/latest_summary.json`의 historical Standard snapshot과 최신 project/AQ projection을 분리하고,
     실제 AQ skill-adapter 실행·캠페인·current test count를 authoritative evidence에서 다시 계산 [완료]
   - 엄격한 production-package candidate index는 유지하고, production delivery와 usable review terminal을
     함께 세는 별도 campaign outcome projection을 추가 [완료]
   - local-only required blocker, 현재 지원 범위에서 제외된 capability, destination/future limitation을
     서로 다른 machine-readable 분류로 투영 [완료]
   - supporting-client closed-loop와 controller sandbox/tool-policy attestation을 future limitation으로 분리하고,
     `desktop_in_session` 자체를 sandbox 증거로 사용하지 않음 [완료]
   - exact `ready_for_profile_publication`과 clean baseline을 재검증하고 single-use human acceptance를 소비하는
     고정 source publication writer를 구현; untracked/modified publication은 Activation으로 인정하지 않음 [완료]
   - B8에서 확인된 machine-passed IQ 이후 human `needs_revision` 경계를 별도 append-only review bundle,
     policy/state recovery, One-Prompt/skill terminal과 Activation usable-review 검증으로 닫음 [완료]
   - 기존 두 Standard 실제 자산은 공통 orchestration/host 변경의 focused regression 대상으로 재확인하되,
     새 Standard 자산 캠페인은 공통 의미가 바뀌거나 회귀가 발견되지 않는 한 1차 완성 선행 조건으로 추가하지 않음 [완료]
   - focused schema/policy/projection/negative gate, 전체 pytest, Ruff, doctor, Blender compatibility,
     실제 Blender 5.0.1 gate, V0.7~V0.9/AQ gate와 `git diff --check`를 통과했고 이 변경을 clean
     source commit으로 고정 [완료]
8-B. reference 충실도 생성·평가·수정 루프 개선 후 fresh current-baseline 5-reference campaign [A안 종료: A~D 개발 실증 보존, E/F 미완료; 별도 재개 지시 전 실행 중단]
   - 2026-09-16: exact material-context continuation 승인 후 추가 preflight는 통과했지만 Windows 경로
     처리 오류로 controller 출력 전에 failed terminal이 됐다. canonical SceneSpec/Blend는 보존됐다.
     sequence 2–5는 시작하지 않았고 새 baseline의 production/시각 개선/인간 수용 실적은 모두 0/5다.
     이 terminal을 재개하지 않는다. 공통 수정의 전체 회귀·clean commit 후 새 source manifest,
     baseline, readiness와 exact scope를 준비하며 새로운 scope 승인은 별도로 받는다.
   - 2026-09-09 재검증에서 47e3928 캠페인의 실제 개선은 1/5, 인간 수용은 0/5다. 기존 terminal과
     approval/package/history를 보존하며 Activation 적격으로 재분류하지 않는다.
   - Laser의 실제 21-object 후보는 materialization 21 + geometry build 1을 요구했으나 root build 상한은
     14였다. 후보/현재 입력 검증은 통과했고 Blender·canonical promotion 이전에 예산 예외가 발생했다.
     source `3956274`는 이를 policy 발행 전 job-local candidate-budget failure로 분류하고 receipt가 있는
     crash continuation에서는 exact 적용 후 증거를 재사용한다.
   - 새 선택형 funding epoch는 structural 최대 3, shared local/material 최대 2, strategy switch 1을
     실제 materialization/build/closure/QA/promotion 비용과 함께 고정한다. 동일 reference의 과거 소비량은
     additive lifetime 합계에 남기며 이름 변경, 이미 소비한 epoch 재사용과 concurrent epoch를 거절한다.
   - 새 전체 회귀와 Blender/V0.7~V0.9/AQ gate를 통과한 clean source에서 manifest → baseline → readiness →
     exact scope를 다시 작성한다. scope SHA 승인 전 새 캠페인은 시작하지 않는다. sequence 1의 정상 terminal,
     source 불변·canonical corruption 0·실제 paired improvement·중대 구조 결함 없음 확인 후에만 2~5를 연다.
   - A: 기존 실패 evidence를 변경하지 않고 높은 contour/bbox 점수와 잘못된 부피의 공존을 재현;
     정상 volumetric/shell/sheet/cloth/균일 재질 positive control과 missing evidence/명시적 N/A를 구분
   - 관찰·불확실성/3D 가설, 구조 우선 저작, source-bound nonhuman finding, 실제 bounded reentry,
     회차별 source/receipt 및 사전 비용 예약을 공통 경로로 연결 [구현·host 회귀·실제 Blender fixture AQ vertical 완료]
   - 실제 vertical은 initial geometry/material/7-pass QA → structural policy re-entry → 새 geometry/material/
     7-pass QA → paired comparison/회차별 receipt → 필수 hard-gate `blocked` terminal을 검증; 고정
     `defect/satisfied` fixture 입력을 실제 reference quality나 human disposition으로 세지 않음
   - B: 목재 1개에서 결함 인식 → 구조 재저작 → 실제 비교를 먼저 입증; top/side/end 연결 체적,
     불규칙 depression과 방향성 목재 재질을 고정 관찰 4/4로 확인했다. raw GLB의 procedural 재질 손실은
     별도 보존했고 exact 승인된 V0.7 파생 최적화, 512px CPU portable PBR 변환, static-payload package와
     fresh clean import까지 완료했다. post-import beauty와 human/package acceptance는 생성하지 않음 [완료]
   - legacy `procedural_wood_v1` bytes를 고정하고 비단일주기 `procedural_wood_v2`, typed mapping evidence 및
     exact direction/periodicity/sampled-span preflight를 추가; Blender 5.0.1 compile fixture도 reference
     quality 증거가 아님. 규칙적 stripe가 남은 attempt02는 render하지 않고 보존했으며, 불규칙 grain과
     비평탄 height/normal/roughness를 추가한 append-only attempt03를 exact scope
     `b4afc73df9896148cbef62b972483e2a4844b78cc69e2366e8fe105aa46fd6af`로 실행했다. Blender 5.0.1
     일곱-pass는 정상 완료했고 longitudinal/end grain은 실제로 개선됐지만, source-bound review는 홈의
     과도한 규칙성과 어두운 smooth surface를 major finding으로 남겨 `needs_revision`/
     `next_action=structural_reentry`로 닫았다. 기술 완료나 direct score 유지로 B를 완료 처리하지 않음
   - attempt04는 전체-scale section loft의 좁고 비대칭인 세 depression, low-frequency worn section,
     밝고 거친 Wood v2 파라미터를 결합해 image-only preflight를 통과했지만 per-vertex UV seam staging
     mesh의 coincident split boundary 때문에 실행 전에 superseded했다. strict MeshPayload 0.2 전환에서
     legacy cap의 0면적 triangle 46개도 발견했으며 attempt05/06 준비 실패는 Blender·preview budget 없이 보존함
   - attempt07은 기존 polygon-corner UV와 source-hash closure를 재사용해 closed two-manifold와 0 degenerate
     face를 만들었지만, 공통 compiler의 inward side winding 위에 outward cap을 수동 결합해 shared-edge
     orientation 320개가 불일치했다. proposal `4bad8cf9abfc491b894ae3d83a45be48890198055ac6586308fc4273498c359b`은
     승인·발행·실행 전에 superseded함
   - 공통 `build_loft_mesh`는 기존 fan이 유효하면 bytes를 유지하고, dense resampling으로 0면적 cap이 생길 때만
     convex section 내부 center를 추가한다. section Newell normal과 first→last progression이 반대이면 face
     winding만 반전해 vertex index·face 순서를 보존하면서 outward orientation을 맞춘다. host focused 23/23과
     실제 Blender 5.0.1 structural smoke 12/12를 통과함
   - attempt08은 attempt04의 exact StructureAuthoring을 수정된 공통 compiler로 다시 컴파일하고 MeshPayload 0.2
     loop UV를 source topology/winding 그대로 결합했다. SceneSpec SHA
     `db111ebd0a263c20ef553e39ec1012078d31ad8bf6fe8244bccc798c81a5044d`, MeshPayload SHA
     `513d5473181a2e3ce51a55c6f6c7da51dce43fb8e2c2b228ce149d420026eefa`, preflight SHA
     `75eeafaf08ec06fdec01e83ff819d2f34c21508727214ab0e623919bff57add3`, spatial audit SHA
     `c110b406c7a22310a00146339f979986b09800e59bd1a29e2abe4c84d453b2b9`이다. 4,320 edge가 incidence 2,
     orientation balance 0이며 8,640 loop UV를 가진다. 완료된 V02 outcome·새 dependency/runtime를 결속한
     V03 scope `ec090247635b469f0fb90782c5654247c3713eeaeae1533f09a4d031aa07cf26`을 승인받아 primary
     `structural_material_attempt08`을 실행했다. Blender 5.0.1 build와 일곱-pass QA는 retry 없이 완료됐고
     beauty SHA는 `2f6b30e6f601649b9eaf9ea136156b26e3743fb207ed6a07a05a7636ad0f9435`다. source-bound
     evaluation은 4개 중 3개 충족, `needs_revision`, `next_action=material_revision`; attempt03 대비
     `longitudinal-cracks` 해소와 `partially_improved`를 기록했다. 이는 인간 disposition이나 canonical/package/
     campaign/Activation 권한이 아님
   - 성공한 V03 primary 뒤 identical-input technical retry는 닫혔다. attempt08에서 image channel `strength`가
     Blender runtime control이 아니었던 계약 누락을 확인해, image-backed normal/height도 명시적
     `procedural.normal_strength`/`bump_strength`/`bump_distance`를 loader에서 검증하도록 보완했다. 과거
     channel 의미는 소급 변경하지 않음
   - 동일 spatial geometry/pose/camera/reference 위에서 contrast·knot·roughness와 runtime normal/bump만
     변경한 append-only attempt09 candidate는 directional preflight와 spatial audit를 통과했다. V04 exact
     scope `0f650030829c32f085e1a48648d1a84d4a66aae0738717d8f085e01e723d2e98` 승인 뒤 extension과
     primary를 한 번 소비했고, Blender 5.0.1 일곱-pass beauty
     `e03dbf968acc61e279ad39dd94714ff204ae5f325951a477aa620cbfb9d29297`를 생성했다. source-bound
     evaluation `91728ddafe19b530ad74a71893fcd294116c1ce70b522593ace4558d1a64a2ba`는 고정 관찰 4/4
     `visually_satisfied`, attempt08→09 comparison
     `41a24ddf2c27e7261c439832889f00f9970cdcf1664fd34dcdd36e2a4b73ad46`는
     `directional-wood-surface` 해소·신규 회귀 없음의 `improved`다. 이는 인간 disposition이나
     canonical/package/campaign/Activation 권한이 아니며 성공한 primary 뒤 retry는 닫힘
   - 완료된 과거 extension은 당시 runtime 증거로 계속 읽되, 새 active extension만 현재 runtime과
     재검증하도록 호환성 결함을 보완함
   - 당시 full host 2238/73 skipped, AQ focused 1141/32 skipped, 실제 Blender 56/1 skipped gate와 별도 loft
     host 23/23, 실제 Blender structural 12/12를 수정된 compiler 및 V04/runtime-control 기준으로 확인했다.
     attempt08의 구조 개선은
     별도 source-bound visual comparison으로만 기록하며 human disposition으로 세지 않음
   - C: 목재는 전체 5자산 목표를 축소한 것이 아니다. Plastic/Rust/Crystal/Laser 네 reference에도 자산별
     서비스 코드 분기 없이 전이했고, source-bound paired comparison에서 모두 실제 개선을 기록했다.
     이 결과는 clean-baseline campaign outcome이나 human disposition이 아님 [완료]
   - D: Standard/AQ 공통 회귀, SceneSpec 0.2/기존 승인·복구·package 및 과거 evidence 불변성을 당시 full
     pytest, actual Blender AQ/V0.9 gate와 16-anchor audit로 통합 확인했다. 새 companion 없는 과거 AQ 동작은
     유지하고, actual Blender vertical에서 발견한 긴 material promotion 경로 결함은 native long-path I/O로
     수정한 뒤 gate 전체를 재실행해 통과함 [완료]
   - E 준비 중 `07efa1a` Plastic structure-07은 실제 shell/rim/notch와 direct `.770792→.924653` 개선을
     만들었지만 wear finding이 남았고, IQ contour/visibility hard finding은 V0.4 structural reentry를 요구했다.
     visual-only attempt가 `material_revision`을 선택한 공통 결함을 발견해 D를 재개방했다. 신규 attempt는 exact
     IQ finding을 `iq:` ID로 결속하고 visual/IQ 중 더 엄격한 route를 고르며, 과거 attempt의 bytes/의미는 유지한다.
     full host **2245 passed/73 skipped**, AQ focused **1147 passed/32 skipped**, actual Blender **56 passed/1 skipped**
     게이트로 수정 경로를 재검증했다. 해당 Plastic 실행은 source 변경 전 개발 증거이므로 새 E campaign 1/5로 세지 않음 [완료]
   - clean source `b617baea8d91d9ff0a107cb2c79fa68946e4aad2`와 exact scope
     `9593f9188b64119b8a01b23e06c81ef6405a3493876abe20ae3f1d7fbcf7022d`에서 sequence 1 Plastic
     canary만 실행했다. 구조 회차는 broad bowed shell, integrated ribs와 asymmetric notch를 만들고 direct
     `.924653→.945003`, silhouette IoU `.908298→.949274`로 개선했지만, surface wear가 실제 beauty에
     충분히 나타나지 않았다. source-bound 시각 평가는 `material_revision`을 요구했고 인간 disposition은
     `not_recorded`로 남겼다.
   - 같은 회차 IQ는 contour boundary F `.790048 < .8`와 fixed-camera interior-edge retention
     `.336239 < .35` 때문에 `blocked`였다. V0.1 strictest routing이 두 항목을 다시 structural로 합쳐 이미
     소비한 structural/strategy budget 때문에 `review_required` terminal로 안전하게 닫혔다. canonical
     corruption은 0, rollback은 복구됨, destination write는 없으며 조건부 sequence 2~5는 실행하지 않았다.
   - 이 canary는 기술 terminal이 정상이어도 결함 원인과 수정 단계가 어긋나면 campaign gate를 통과할 수
     없음을 확인한 negative evidence다. 기존 terminal을 재개·재분류하지 않고, additive
     `AQQualityRevisionLoopV02`에만 `causal_v2`를 추가했다. chamfer가 통과하고 boundary F 부족분이
     `meaningful_gain_min` 이내인 contour는 parametric, fixed-camera visibility는 exact source-bound visual
     route, 원인이 특정되지 않으면 evidence-required로 보낸다. 큰 contour/실제 구조 finding과 V0.1은
     기존 structural 의미를 유지한다.
   - V0.2 bind는 `initial_pipeline_reserve + revision cost_limit`을 root builds/material rounds/quality/
     promotions와 합산해 첫 geometry 전에 검사한다. 따라서 회차 숫자는 남았지만 material closure나
     promotion 비용이 없는 이번과 같은 구성은 새 세션에서 실행 전에 차단한다. 이 보완은 source 변경이므로
     b617 canary나 그 scope를 재사용하지 않는다. full host 2257/73 skipped, AQ focused 1156/32 skipped,
     실제 Blender 56/1 skipped 및 16-anchor audit를 통과했으며 clean commit 후 새 baseline/scope로 E를 재시작한다.
   - clean source `e37f230096303adef5b91e96b62dd6ebda0690b8`와 exact scope
     `f8e8a7f2c419ed825054e56a332c386495642b28c530b081e09889ff60733cc8`에서 두 번째 E sequence 1
     Plastic canary를 실행했다. initial geometry/material과 실제 일곱-pass/IQ까지 통과한 뒤 causal V0.2는
     contour deficit을 `parametric_revision`으로 정확히 선택했다. 첫 local correction은 새 geometry를
     Blender로 검증했으나, atomic promotion 뒤 PolicyDecisionReceipt가 mutable controller baseline을
     적용 전 조건으로 다시 검사해 정상 변경을 stale로 오인했다. host는 canonical SceneSpec/ModelingPlan/
     Blend를 원 SHA로 rollback하고 technical-failed decision과 terminal을 append-only로 보존했으며,
     sequence 2~5는 열지 않았다.
   - 이 결함은 authority 확대나 후보 우회가 아니라 policy precondition/postcondition 순서 문제로 수정한다.
     적용 전 authorization replay는 계속 exact controller/source 조건을 요구하고, 적용 후
     `bounded_parametric_revision`은 exact geometry receipt·controller target·candidate와 현재 canonical
     세 파일이 일치할 때만 single-use `applied` decision을 허용한다. 실패 e37f230 terminal과 기존 scope는
     재개·재사용하지 않으며, full 회귀와 새 clean commit/baseline/scope 뒤 sequence 1부터 다시 시작한다.
   - 실제 기술·시각 개선·인간 disposition을 별도 집계; 검증/수정/needs_revision 횟수를 품질 KPI로 세지 않음
   - 같은 결함·전략의 정체는 경로에 맞는 전략 변경 또는 bounded review로 종료; material 정체를
     geometry/장식 증량으로 해결하지 않으며 재개/새 child로 예산을 초기화하지 않음
   - E의 새 clean source/Baseline/Readiness/canary+나머지 4개는 B/C/D 통과 뒤로 이동; 아래 과거 기록과
     운영 조건은 보존하되 지금 즉시 재캠페인을 지시하는 순서로 읽지 않음
   - C655 source에서 서로 다른 reference 5개가 One-Prompt, IQ pass, production GLTF package와 clean import를
     기술적으로 5/5 완료했으나 exact human disposition 전 검토에서 contour-only/internal-detail collapse가
     반복 확인됨; 이 evidence는 orchestration/delivery 회귀 근거로 보존하되 Activation outcome으로 세지 않음
   - IQ 0.2에 exact reference/beauty/reference-mask/candidate-mask/camera-bound fixed-camera interior
     visibility gate를 additive하게 추가하고 새 AQ plan에만 필수화; historical policy/report 기본 의미는 유지
   - readiness `4d6a521e1bc68f445362dd98fede8c3c2280f6a82ba8252943f4708ccefcfc4f`의 735 캠페인은
     canary 정상 terminal/source 불변성 확인 후 2~5를 실행했으나 정상 terminal `1/5`로 종료
   - Plastic은 production delivery/GLTF clean import 통과; Rust는 tangent 오류로 delivery failed;
     Wood·Crystal은 긴 재질 경로 오류 뒤 cancelled; Laser는 legacy bevel 계약 위반으로 base failed,
     기존 adapter에는 route/receipt `3/2`의 interrupted cancellation 증거가 남음
   - 기존 job을 재개·재분류하지 않고 source의 긴 경로 I/O, 마지막 action/예외 terminal publication,
     cancel-route recovery와 파생 LOD의 exact angle smoothing 갱신을 보완
   - 새 후보는 실제 AQ candidate contract 검사부터 시작: Rust의 occluded connector를 국소 곡선으로
     재저작하고 Laser의 unsupported legacy bevel은 명시적 sharp-edged geometry로 대체; 참조 형상과
     최종 품질의 동등성을 주장하지 않으며 실제 V0.6/IQ 및 exact human review로 다시 판정
   - 후속 f683 clean baseline은 16개 검증 receipt를 통과했으나 정상 terminal `1/5`로 종료;
     모든 adapter route/receipt는 4/4로 닫혔고 실행 중 source·helper·reference 불변성을 확인
   - Rust의 GLB 수치 경계는 기존 exact 비교를 보존하는 별도 strict report 0.2로 검증:
     모든 유일한 triangle/corner의 위치·UV·unit normal을 대조하며 topology/material/winding,
     원본 blend/GLB hash, run/package/source binding을 완화하지 않음; historical failed는 그대로 유지
   - Wood·Crystal의 build provenance에 남은 긴 경로 I/O를 보완하고 302~306자 실제 shader 경로로
     독립 full build/reopen 검증; 원본 cancelled session이나 input은 수정하지 않음
   - Laser의 receiver shell/frame에 가려진 관측 음영역을 새 후보로 복원; 같은 reference/camera와
     기준에서 contour 0.759→0.952, 고정 카메라 내부 가시성 세 채널과 33개 LOD tangent probe 통과;
     이 격리 결과는 full IQ/source freeze/package 또는 human quality acceptance가 아님
   - 42aa clean baseline의 공식 검증 receipt 16개를 통과한 뒤 canary 및 같은 baseline의 2~5 실행 완료:
     Plastic·Rust·Laser 정상 production GLTF/clean import, Wood·Crystal portable shader 경로 실패;
     정상 terminal 3/5, 모든 adapter route/receipt 4/4, 실제 beauty 5개, source/reference 불변성 확인
   - 남은 portable host/Blender runtime/optimization loader의 경로 I/O를 보완하되 hash·schema·containment,
     기존 모델 검증, tangent 및 형상 보존 기준은 유지; 실제 short/deep GLB·FBX delivery 회귀 2개 통과
   - Wood·Crystal은 격리 delivery에서 확인된 숨겨진 sweep 연결부의 접선 퇴화를 새 V0.4 후보에서 국소
     곡선으로 보완; 기존 semantic/material ID·camera·reference와 나머지 형상 보존, 원본 job은 변경하지 않음
   - 두 수정 후보는 실제 Blender GLB bake/package/clean import와 all-corner 형상 보존 검증을 통과;
     같은 contour/visibility 기준도 통과했지만 full AQ IQ나 human acceptance로 취급하지 않음
   - isolated preflight/diagnostic은 campaign outcome 또는 승인으로 세지 않음; 상세 근거는
     VERIFICATION_AQ_ONE_PROMPT_5_ASSET_CAMPAIGN_KO.md의 14~16절에 기록
   - gate/source 변경을 full regression과 실제 Blender gate로 고정한 clean commit에서 새
     ActivationSourceManifest/Baseline/Readiness를 생성한 뒤 아래 canary와 5-reference 조건을 다시 적용
   - 본 보완의 clean commit에서 새 ActivationSourceManifest/Baseline/Readiness를 생성하고 profile은 계속
     `disabled_experimental`로 유지
   - B8 historical canary는 framework 수정 전 baseline의 1/5로 재사용하지 않고, 새 clean baseline에서
     서로 다른 reference 중 1개를 `aq-one-prompt-orchestrator` canary로 다시 실행
   - canary 뒤 framework/source 변경이 없고 아래 기준을 모두 만족하면 같은 baseline의 campaign #1로 계산하고
     나머지 4개를 실행; framework/source가 바뀌면 새 baseline에서 영향받은 campaign을 다시 시작
   - 각 자산은 initial request 1, 추가 사용자 결정 0 목표, technical user approval 0, adapter route terminal,
     canonical corruption 0, rollback 무결성, 실제 Blender 실행과 exact human quality disposition을 충족
   - 정상 결과는 production delivery 또는 actionable usable review terminal이어야 하며, required hard-gate
     `blocked`, technical `failed`, pending approval와 `running` projection은 성공 terminal에 포함하지 않음
   - 동일 evidence의 `needs_revision`을 자동 재사용하거나 무한 반복하지 않고 bounded budget의 review terminal로 종료
   - 최소 한 자산은 IQ pass/source freeze, portable GLTF package와 clean-import round trip을 통과
8-C. AQ local-only Activation 재심사와 V0.9 1차 완성 closeout [미완료·재개 보류]
   - F 진입 전 5개 reference 모두의 실제 시각 개선을 exact paired evidence로 입증하고, 미해결 중대
     구조 오류가 없어야 함; QA가 나쁜 결과를 막는 것만으로 생성 능력 개선을 완료 처리하지 않음
   - distinct current-baseline campaign outcome 5/5와 production package 최소 1개를 별도 지표로 검증
   - exact human activation acceptance 없이는 profile status를 변경하지 않음
   - 모든 local-only 필수 조건과 single-use activation authority가 통과한 경우에만
     고정 `.codex/activation/autonomous_static_prop_v2.local.json`을 create-once로 생성하고 source commit으로
     고정한 뒤 `autonomous_static_prop_v2`의 좁은 지원 범위를 `verified_active`로 게시
   - 조건 미달이면 `disabled_experimental`을 유지하고 실패한 자산·framework·attestation blocker를 구분해
     1차 완성 미달 사유를 게시하며 과거 terminal이나 package를 재분류하지 않음
   - Standard 완료 범위, AQ 판정, known limitation, exact source/baseline/index/readiness와 실제 검증 결과를
     current aggregate와 closeout 문서에 동기화; 이는 프로젝트 `1.0.0` 승격이 아님
9. Codex ImageGen overlay one-prompt benchmark와 activation review [8-C 뒤로 연기]
   - 기존 `stage9-overlay-decision-e211057a1fc0ec605e748f84`의 bounded `GO`는 불변 machine evidence로 보존
   - `stage9`라는 artifact 이름은 생성 당시 로드맵 위치를 나타내는 historical ID이며 현재 실행 우선순위를 뜻하지 않음
   - AQ base Activation과 분리하고 `disabled_experimental`, explicit user opt-in과 별도 provider/budget authority 유지
   - 실제 built-in ImageGen 호출, immutable candidate provenance와 semantic/material evidence를 새 baseline에서 검증
   - 정확한 실행 상태는 run-owned `reports/activation_readiness/.../campaign_decision.json`과 새 campaign evidence가 소유
10. Standard Generated Texture Intake 0.1
   - 수동 생성 PNG의 immutable 등록·provenance·local PBR 연결
   - Full Standard ImageGen은 반복 assignment/provenance/후보/다중 사용자 workflow 병목이 입증될 때만 조건부
11. 실제 material benchmark와 기존 Crystalgun acceptance fixture
12. Unity URP material reconstruction
13. Architecture exterior / environment / measured 확장
14. Interior AQ
15. V1.0 승격 재심사
```

Material Closure와 Material Identity Split은 반복되는 top-level 제품 마일스톤이 아니라 Approval Envelope가
엄격한 전제 아래 호출하는 기반 capability입니다. constant/local-only material 통과는 dependency-rich
closure나 texture/bake 성공을 뜻하지 않습니다. 기존 Crystalgun ApprovalRequest에는 새 authority를
소급하지 않으며 canonical apply도 이 로드맵 변경으로 자동 실행하지 않습니다. `Standard Codex ImageGen
integration`은 필수 선행 항목이 아니며 좁은 `Standard Generated Texture Intake 0.1`을 별도 후속으로 유지합니다.

local-only AQ base Activation의 필수 지표는 8-B와 8-C가 정의합니다. destination runtime parity는
engine-neutral local-only Activation의 필수 지표가 아니라 future destination limitation입니다. ImageGen,
signage/decal과 bake-bound dependency-rich material도 1차 완성의 고정 profile scope에서 제외하는 동안에는
base success count를 막지 않습니다. 단, 현재 profile/schema가 그 제외 범위를 exact하게 표현하지 못한다면
이를 임의로 무시하지 않고 8-A에서 좁은 capability scope와 blocker 분류를 먼저 구현·검증해야 합니다.

현재 `activation-readiness-13169fe71f12974fae1d609d`가 destination parity 등을 blocker로 기록한 사실은
해당 immutable report의 역사적 의미로 보존합니다. 이 로드맵 문구만으로 report, profile status, user approval,
policy authority 또는 Activation을 변경하지 않습니다. 1차 완성의 `desktop_in_session` 범위는 의도적으로
`workflow_contract_only`이며 sandbox attestation을 주장하지 않습니다. supporting-client closed loop와
controller sandbox/tool-policy attestation은 future `client_mediated` capability의 미검증 한계로 분리하고,
그 한계를 local desktop base success count를 막는 필수 blocker로 사용하지 않습니다.

현재 프로젝트는 `0.9.1`이며 Stabilization과 Destination Handoff contract는 `0.9.0`, Workflow contract는 `0.8.0`으로 유지됩니다. 선택적 AQ/Integrated Quality와 companion 계약 `0.1.0`, 비활성 실험 AQ v2 `0.2.0`, Approval Envelope `0.3.0`, One-Prompt `0.1.0`, Codex Built-in ImageGen core `0.1.0`/MaterialAuthoring companion `0.2.1`/additive Material Loop `0.1.0`, Material Closure Stabilization `0.1.0`, Material Identity Split `0.1.0`, derived-only SceneSpec V03 `0.3.0`의 존재는 프로젝트 버전 승격이 아닙니다. V0.9와 각 companion 지원 표시는 실제 검증 기록 범위에 한정되며 V1.0 승격은 중단 상태입니다.

### 2026-09-28: reference-fidelity 유한 사전 위임 전환

반복 exact scope 승인을 선택적 부모 위임 계약 한 번으로 대체한다. 계약·host 검증·회귀를
완성하고 새 clean source/baseline 및 구체적인 추가 후보·수정·전체 실행 예산을 제시한 뒤
부모 hash의 확정을 받는다. 범위 안의 후속 scope와 루틴 실행은 자동 policy이며 인간 수용이
아니다. 기존 캠페인 결과·소비·approval은 유지하며 새 baseline 성공으로 승계하지 않는다.
5/5 실제 paired 개선과 별도 인간 판정이라는 최종 목표는 유지한다.
[계약 규칙](../fidelity_campaign_delegation.md)을 따른다.
