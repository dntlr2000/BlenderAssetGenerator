# BlenderAssetGenerator V1.0 로드맵

이 문서는 BlenderAssetGenerator가 현재 프로젝트 `0.9.0`에서 V1.0까지 발전하는 공식 개발 로드맵입니다. 구현된 기능과 계획된 기능을 구분하고, 각 단계의 책임·진입 조건·완료 조건·되돌아가기 규칙을 정의합니다.

로드맵은 구현 사실을 대신하지 않습니다. 어떤 단계가 `완료`로 바뀌려면 해당 버전의 코드, JSON 계약, 테스트 계획, 실제 Blender 통합 게이트와 검증 기록이 함께 존재해야 합니다.

## 1. 버전과 작업 단계의 의미

이 프로젝트에는 세 종류의 버전이 함께 존재합니다.

1. **프로젝트 버전**: 현재 통합 저장소의 기능 수준입니다. 현재 값은 `0.9.0`입니다.
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
| Codex Built-in ImageGen companion | core `0.1.0`, adoption `0.2.0`, MaterialAuthoring `0.2.1` | current-task image candidate overlay; `disabled_experimental` |
| SceneSpec V03 structural derivative | `0.3.0` | canonical `0.2.0`을 바꾸지 않는 opt-in derived 구조 형상 계약 |

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
| AQ 0.1 | `autonomous_static_prop_v1`만 검증된 opt-in 병렬 확장 | autonomy/integrated quality/companion contracts `0.1.0`; 프로젝트는 `0.9.0` 유지 |
| AQ 0.2 | 선택된 fixture와 gate를 통과했으나 비활성 실험 단계 | `autonomous_static_prop_v2` `disabled_experimental`; 프로젝트는 `0.9.0` 유지 |
| ImageGen 0.1 | controller-mediated companion 구현, 활성화는 별도 검증 대기 | `autonomous_static_prop_v2_codex_imagegen` `disabled_experimental`; 프로젝트는 `0.9.0` 유지 |
| Material Closure 0.1 | additive stabilization 구현·local regression, authorized success 미검증 | dependency closure/preflight/promotion companion; 프로젝트 `0.9.0` 유지 |
| Material Identity Split 0.1 | generic framework와 실제 승인 전 shadow 검증 완료, apply 승인 대기 | paired scope-change companion; 프로젝트 `0.9.0`/SceneSpec `0.2.0` 유지 |
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

프로젝트 `0.7.3`에서 V0.8 orchestration에 앞서 V0.4 형상 authoring 경계에 별도 `InteriorScope 0.1.0`을 도입했고, V0.7 derived asset 계층에 안전한 배칭·cleanup·cost budget evidence를 추가했습니다. 이 경계는 현재 `0.8.0`에서도 유지됩니다. `architecture/interior_scope.json`이 없으면 실내 정책은 `disabled`이고, 외관 요청은 외관만 생성합니다. 사용자가 실내를 명시적으로 요청한 경우에도 scope 초안만으로는 충분하지 않으며, `architecture/interior_scope.approval.json`이 현재 scope의 SHA-256과 정확히 일치해야 승인된 prefix·level·space·furnishing 범위 안에서만 정적 실내 형상을 작성할 수 있습니다.

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

**상태: 프로젝트 `0.9.0` 위의 opt-in 확장. V1.0 승격 근거로 자동 해석하지 않습니다.**

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
`0.9.0`, canonical SceneSpec은 `0.2.0` 그대로입니다.**

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

상세 설계·실행·검증 경계는 [AQ 0.2 아키텍처](ARCHITECTURE_AQ_V02_KO.md),
[시작 가이드](GETTING_STARTED_AQ_V02_KO.md), [테스트 계획](TEST_PLAN_AQ_V02_KO.md),
[검증 기록](VERIFICATION_AQ_V02_KO.md)을 따릅니다.

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

상세 내용은 [ImageGen 아키텍처](ARCHITECTURE_CODEX_IMAGEGEN_PROVIDER_KO.md),
[시작 가이드](GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md),
[테스트 계획](TEST_PLAN_CODEX_IMAGEGEN_PROVIDER_KO.md),
[마이그레이션 정책](MIGRATION_CODEX_IMAGEGEN_PROVIDER_KO.md),
[검증 기록](VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md),
[Material Loop 아키텍처](ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md)와
[Material Loop 검증](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다. 실제 current-task 요청은
[Material Loop 프롬프트 모음](IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md)에서 profile opt-in, native 원본
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

- [저장소 개요와 공개 기능](README.md)
- [저장소 작업 규칙과 source-of-truth](AGENTS.md)
- [V0.4 아키텍처](ARCHITECTURE_V04_KO.md)
- [V0.4 테스트 계획](TEST_PLAN_V04_KO.md)
- [선택적 실내 범위와 승인](INTERIOR_SCOPE_KO.md)
- [V0.6 아키텍처](ARCHITECTURE_V06_KO.md)
- [V0.6 테스트 계획](TEST_PLAN_V06_KO.md)
- [V0.6 로컬 검증 기록](VERIFICATION_V06_KO.md)
- [V0.7 아키텍처](ARCHITECTURE_V07_KO.md)
- [V0.7 테스트 계획](TEST_PLAN_V07_KO.md)
- [V0.7.3 로컬 통합 검증 기록](VERIFICATION_V073_KO.md)
- [V0.7.4 최적화 사전 검토](V074_PRE_OPTIMIZATION_REVIEW_KO.md)
- [V0.7.4 Blender 5 검증 기록](VERIFICATION_V074_KO.md)
- [V0.8 아키텍처](ARCHITECTURE_V08_KO.md)
- [V0.8 빠른 시작](GETTING_STARTED_V08_KO.md)
- [V0.8 테스트 계획](TEST_PLAN_V08_KO.md)
- [V0.8 검증 기록](VERIFICATION_V08_KO.md)
- [V0.9 아키텍처](ARCHITECTURE_V09_KO.md)
- [V0.9 빠른 시작](GETTING_STARTED_V09_KO.md)
- [V0.9 테스트 계획](TEST_PLAN_V09_KO.md)
- [V0.9 검증 기록](VERIFICATION_V09_KO.md)
- [Autonomous Quality 0.2 아키텍처](ARCHITECTURE_AQ_V02_KO.md)
- [Autonomous Quality 0.2 시작 가이드](GETTING_STARTED_AQ_V02_KO.md)
- [Autonomous Quality 0.2 테스트 계획](TEST_PLAN_AQ_V02_KO.md)
- [Autonomous Quality 0.2 마이그레이션 정책](MIGRATION_AQ_V02_KO.md)
- [Autonomous Quality 0.2 검증 기록](VERIFICATION_AQ_V02_KO.md)
- [ControllerExecutor 격리 경계](CONTROLLER_EXECUTOR_KO.md)
- [AQ 0.2 delivery profile](DELIVERY_PROFILES_KO.md)
- [AQ 0.2 material authoring](MATERIAL_AUTHORING_KO.md)
- [AQ 0.2 quality benchmark](QUALITY_BENCHMARK_KO.md)
- [Codex Built-in ImageGen 아키텍처](ARCHITECTURE_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 시작 가이드](GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 테스트 계획](TEST_PLAN_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 마이그레이션 정책](MIGRATION_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex Built-in ImageGen 검증 기록](VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md)
- [Codex ImageGen Material Loop 아키텍처](ARCHITECTURE_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 시작 가이드](GETTING_STARTED_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 실사용 프롬프트 모음](IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md)
- [Codex ImageGen Material Loop 테스트 계획](TEST_PLAN_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 마이그레이션 정책](MIGRATION_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Codex ImageGen Material Loop 검증 기록](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)
- [Material Closure Stabilization 아키텍처](ARCHITECTURE_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 테스트 계획](TEST_PLAN_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 마이그레이션 정책](MIGRATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 검증 기록](VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)
- [Material Closure Stabilization 프롬프트 모음](MATERIAL_CLOSURE_STABILIZATION_PROMPTS_KO.md)
- [Material Identity Split 아키텍처](ARCHITECTURE_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 테스트 계획](TEST_PLAN_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 마이그레이션 정책](MIGRATION_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 검증 기록](VERIFICATION_MATERIAL_IDENTITY_SPLIT_KO.md)
- [Material Identity Split 프롬프트 모음](MATERIAL_IDENTITY_SPLIT_PROMPTS_KO.md)

현재 V0.9는 environment probe, read-only audit, reversible terminal workspace archive,
single-worker queue, strict schemas, stability PDF와 Codex Destination Handoff를 구현했습니다.
실제 gate와 지원 매트릭스 결과는 `VERIFICATION_V09_KO.md`에만 기록합니다. Handoff는 목적지
import 계획용 계약이지 자동 engine adapter나 runtime parity 증거가 아닙니다.

## 17. 현재 시점의 다음 순서

```text
1. Material Closure Stabilization local contract/regression sign-off — 2026-08-14 완료
   1A. Material Identity Split generic framework + Crystalgun preapproval — framework 준비 완료
   1B. 별도 사용자 root-scope 승인 뒤 guarded apply + post-apply authority refresh — 승인 대기
2. Crystalgun candidate coverage repair와 새 preapproval dry-run
3. 실제 자산 3종 이상의 material regression
4. Standard Codex ImageGen integration
5. 실제 material benchmark
6. Unity URP material reconstruction
7. AQ v2 local-only activation review
8. ImageGen overlay activation review
9. Architecture exterior / environment / measured 확장
10. V1.0 승격 재심사
```

각 단계는 앞 단계의 실제 evidence와 gate가 통과한 뒤에만 시작합니다. 1A/1B는 기존 1번과
2번 사이에 추가된 scope-change 선행 경계이며 기존 1→10 우선순위를 바꾸지 않습니다. 2026-08-14 현재
Material Closure contracts/public surface, 전체 `1750/62/8` 회귀와 한 actual Blender preapproval
fixture는 검증됐습니다. 다만 authorized controller/promotion/IQ success는 별도 권한 evidence가
없어 미검증입니다. Crystalgun retry02는 closure 뒤
`detail.crystal.facet_lines`의 image-backed UV coverage 누락으로 Blender/preview/approval 전에
`preflight_failed`가 됐습니다. 원인인 shared material identity를 완화하지 않고 분리하는 generic
Material Identity Split `0.1.0`과 actual Blender paired shadow preapproval은 통과했지만,
최종 저장소 회귀도 `1809 passed, 63 skipped, 8 warnings`로 통과했습니다. 그러나
ApprovalRequest는 승인이 아니므로 1B와 2번은 완료가 아닙니다.

특히 Standard ImageGen 통합은 Crystalgun approval-pending dry-run,
서로 다른 실제 자산 3종 이상의 material regression, specialized approval/rollback consistency가
모두 검증되기 전에는 시작하지 않습니다. Unity URP는 engine-neutral source package를 목적
엔진에서 재구성하는 별도 단계이며 현재 destination write나 runtime parity를 뜻하지 않습니다.
7번과 8번은 구현 존재가 아니라 별도 activation review이고, 두 experimental profile은 그때까지
계속 `disabled_experimental`입니다.

현재 프로젝트, Stabilization과 Destination Handoff contract의 최상위는 `0.9.0`이며 Workflow contract는 `0.8.0`으로 유지됩니다. 선택적 AQ/Integrated Quality와 companion 계약 `0.1.0`, 비활성 실험 AQ v2 `0.2.0`, Codex Built-in ImageGen core `0.1.0`/MaterialAuthoring companion `0.2.1`/additive Material Loop `0.1.0`, Material Closure Stabilization `0.1.0`, Material Identity Split `0.1.0`, derived-only SceneSpec V03 `0.3.0`의 존재는 프로젝트 버전 승격이 아닙니다. V0.9와 AQ/ImageGen/Material Closure/Material Identity Split 지원 표시는 각각의 실제 검증 기록 범위에 한정되며 V1.0 승격은 중단 상태입니다.
