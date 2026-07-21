# BlenderAssetGenerator V1.0 로드맵

이 문서는 BlenderAssetGenerator가 현재 프로젝트 `0.7.3`에서 V1.0까지 발전하는 공식 개발 로드맵입니다. 구현된 기능과 계획된 기능을 구분하고, 각 단계의 책임·진입 조건·완료 조건·되돌아가기 규칙을 정의합니다.

로드맵은 구현 사실을 대신하지 않습니다. 어떤 단계가 `완료`로 바뀌려면 해당 버전의 코드, JSON 계약, 테스트 계획, 실제 Blender 통합 게이트와 검증 기록이 함께 존재해야 합니다.

## 1. 버전과 작업 단계의 의미

이 프로젝트에는 세 종류의 버전이 함께 존재합니다.

1. **프로젝트 버전**: 현재 통합 저장소의 기능 수준입니다. 현재 값은 `0.7.3`입니다.
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

현재 V0.7 저장소에서 V0.4 형상 작업을 다시 수행하는 것은 프로젝트를 다운그레이드하는 일이 아닙니다. 최신 저장소 안에서 이전 제작 단계를 다시 실행하는 정상적인 반복 작업입니다.

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
V0.9  Stabilization + Release Candidate
  ↓
V1.0  Integrated Reference/CAD-to-Asset Pipeline
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
| V0.9 | 계획 | 아직 release candidate 없음 |
| V1.0 | 계획 | 아래 완료 기준 충족 전에는 사용 금지 |

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

프로젝트 `0.7.3`은 V0.8 orchestration에 앞서 V0.4 형상 authoring 경계에 별도 `InteriorScope 0.1.0`을 유지하고, V0.7 derived asset 계층에 안전한 배칭·cleanup·cost budget evidence를 추가합니다. `architecture/interior_scope.json`이 없으면 실내 정책은 `disabled`이고, 외관 요청은 외관만 생성합니다. 사용자가 실내를 명시적으로 요청한 경우에도 scope 초안만으로는 충분하지 않으며, `architecture/interior_scope.approval.json`이 현재 scope의 SHA-256과 정확히 일치해야 승인된 prefix·level·space·furnishing 범위 안에서만 정적 실내 형상을 작성할 수 있습니다.

이 보강은 SceneSpec `0.2.0`을 변경하지 않습니다. 실내 객체는 기존 stable semantic ID와 tag를 이용해 분류하며, facade backing·door reveal·window recess·외벽 두께처럼 외관을 지지하는 형상은 실내로 명명하거나 tag하지 않는 한 계속 허용합니다. interactive door, navigation, gameplay volume, 목적 엔진별 room system과 runtime shader는 향후 목적지 adapter 범위입니다.

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
- revision candidates, exact candidate compile, hash-bound single-use approval
- 적용 후 rebuild, rerender, constraint 비회귀, score 개선 확인
- 검증 실패 또는 비개선 시 canonical SceneSpec 자동 복구

### 완료 기준

- direct reference evidence가 beauty 또는 생성 target보다 항상 우선
- 생성 target 단독 후보는 자동 적용 불가
- 모든 실행 후보가 명시적 사용자 승인을 요구
- 승인하지 않은 path가 바뀌지 않음
- 수정 후 direct score 개선과 constraint 비회귀를 모두 만족

QA 점수는 완성도 백분율이나 사람의 최종 품질 승인이 아닙니다. 큰 실루엣·카메라·객체 분해 문제가 발견되면 V0.6의 작은 후보를 반복하기보다 V0.4 형상 작업으로 되돌아갑니다.

`QA 실행 완료`는 7패스와 report/candidate가 생성된 상태일 뿐 수정 승인이 끝났다는 뜻이 아닙니다. `QA 승인 완료`는 사용자가 결과를 승인했거나, 승인된 revision이 점수 개선과 constraint 비회귀를 통과한 상태입니다.

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
6. **Destination adapter selection**
   - 목적지가 확인된 경우에만 adapter capability 탐색
   - 지원 adapter가 없으면 V0.7 engine-neutral package에서 정상 종료
   - Unity, Unreal 또는 기타 엔진을 기본값으로 추정하지 않음

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
- 기존 V0.2~V0.7 workspace를 재작성하지 않고 상태를 재구성함
- host failure, 명시적 retry, interrupted attempt, 동시 실행과 stale lock 복구 테스트 통과
- 더 넓은 failure injection, junction escape, 장기 queue와 운영체제별 복구는 V0.9에서 확대

V0.8은 새로운 범용 3D 복원 알고리즘을 의미하지 않습니다. 이미 검증된 분석·형상·재질·QA·패키징 기능을 일관되게 조율하는 단계입니다.

## 11. V0.9 — Stabilization + Release Candidate

**상태: 계획. V1.0 출시를 위한 검증과 범위 고정 단계입니다.**

### 목표

새 기능 추가를 최소화하고 지원 환경, 데이터 호환, 복구, 실제 자산 품질과 문서를 출시 가능한 수준으로 고정합니다.

### 계획 범위

- 지원 운영체제, Blender, Python, Codex surface의 실제 검증 매트릭스
- 깨끗한 설치, 업데이트, workspace migration과 backup/restore
- Blender 5.x API 변화와 feature-probe 회귀
- concept 건물·환경·제품, measured blueprint와 복합 실제 작업 benchmark
- job 충돌, 동시 작업, timeout, 강제 종료, 손상 JSON, 누락 payload와 stale artifact 음성 테스트
- SceneSpec/Material/QA/Portable 계약의 forward/backward compatibility 정책
- 성능, 메모리, 폴리곤, 텍스처, 반복 횟수와 provider 비용 관측
- 전체 PDF와 machine JSON의 hash·경로·개인정보 검증
- 알려진 제한, 비목표와 지원하지 않는 입력의 명확한 오류
- 선택된 destination adapter가 있다면 실제 대상 엔진 import와 runtime 검증
- LOD 다중 시점 silhouette, UV overlap, texel density와 padding의 정량 검증
- 반복 실행 결과의 byte hash가 아니라 normalized inventory·score·manifest 의미 동등성 검증

### 예정 완료 기준

- 지원한다고 명시한 환경에서 전체 회귀 게이트 통과
- 실제 자산 benchmark의 실패·품질 지표와 재현 절차 공개
- 부분 실패가 성공으로 보고되지 않고 canonical 데이터 손상 0건
- clean install부터 engine-neutral package까지 사용자 문서만으로 재현 가능
- V1.0에서 동결할 공개 CLI, MCP, JSON Schema와 migration 정책 확정
- release blocker 0건, 알려진 제한 전부 문서화
- 연속·병렬 작업과 중간 장애 후 resume에서 orphan lock, staging, 잘못된 latest pointer 0건

테스트하지 않은 Blender, 운영체제 또는 엔진을 지원한다고 표시하지 않습니다.

## 12. V1.0 — Integrated Reference/CAD-to-Asset Pipeline

**상태: 계획. 아래 조건을 충족하기 전에는 V1.0으로 표시하지 않습니다.**

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
→ optional validated destination adapter
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
- 목적 엔진 지정 시 지원 adapter만 사용하고 실제 import/runtime evidence를 기록

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
```

### CAD 명칭 사용 조건

V1.0을 `Reference/CAD-to-Asset`이라고 부르려면 파일을 단순 보관하는 수준이 아니라 실제로 파싱하고 geometry/constraint로 변환하는 CAD 경로가 검증되어야 합니다.

- 최소 한 종류의 2D vector/blueprint 형식
- 최소 한 종류의 3D CAD interchange 형식 또는 명시적으로 검증된 외부 adapter
- 단위, 축, layer/object identity와 누락 feature 보고
- clean import와 실제 형상·치수 검증

지원 형식은 V0.8 설계 시 결정하고 V0.9에서 실제 환경으로 검증합니다. 이 조건을 충족하지 못하면 V1.0의 공식 명칭은 `Reference-to-Asset`으로 제한하고 CAD는 post-V1.0 범위로 이동해야 합니다.

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

규칙:

1. 이전 canonical SceneSpec은 `history/`에 보존합니다.
2. 이전 QA, optimization과 package는 immutable evidence로 남깁니다.
3. stale 산출물을 덮어쓰거나 최신 결과처럼 표시하지 않습니다.
4. 변경 후에는 새로운 run ID, conversion ID와 package ID를 사용합니다.
5. source fingerprint가 달라지면 이전 V0.7 package를 재사용하지 않습니다.
6. 카메라 변경 후에는 과거 QA score를 동일 기준의 개선량으로 비교하지 않습니다.

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

현재 V0.8은 코드·스키마·격리 orchestration gate와 V0.7.4 Blender 5.0.1 GLB/FBX/OBJ 회귀 결과를 `VERIFICATION_V08_KO.md`에 기록했습니다. V0.9 문서 동결 전에는 목적 엔진 adapter와 더 다양한 실제 자산 benchmark 결과를 별도 검증 기록으로 추가해야 합니다.

## 17. 현재 시점의 다음 순서

```text
현재 V0.8 orchestration 기준선 유지
→ V0.8 실제 작업 시나리오를 승인 경계별로 추가 검증
→ V0.9 지원 매트릭스와 실제 자산 benchmark
→ 공개 계약과 migration 동결
→ V1.0 release gate
```

V0.8 구현을 시작하기 전까지 현재 공개 기능의 최상위는 V0.7.3입니다. 이 문서는 미래 기능을 이미 구현된 것처럼 사용할 권한을 부여하지 않습니다.
