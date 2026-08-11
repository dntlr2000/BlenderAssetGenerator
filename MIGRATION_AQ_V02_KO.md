# Autonomous Quality 0.2 마이그레이션 설계

## 1. 문서 상태

이 문서는 Autonomous Quality 0.2 Harness Reliability & Fidelity Extension의 현재
하위 호환 구현과 향후 활성화 마이그레이션 설계를 함께 설명한다. AQ 0.2 companion,
`autonomous_static_prop_v2`, DeliveryProfile과 ControllerExecutor의 strict host 계약은 현재
공유 트리에 구현되어 있다. 2026-08-11에는 host/full 회귀, bounded Blender synthetic fixture,
독립 GLB+FBX clean import와 V0.7~V0.9 root smoke가 통과했다. 이것이 profile 활성화, 사람 승인,
임의 reference 품질 또는 destination runtime 검증을 뜻하지는 않는다.

- 현재 프로젝트 버전은 0.9.0으로 유지한다.
- canonical SceneSpec은 0.2.0으로 유지한다.
- 기존 AQ 0.1, autonomous_static_prop_v1, standard, background_exterior의 의미와 공개 표면을
  변경하지 않는다.
- AQ 0.2와 autonomous_static_prop_v2는 별도 opt-in companion 경로다.
- v2는 현재 disabled_experimental이며, supporting-client closed loop, controller sandbox/tool
  attestation, 실제 reference human review, destination runtime parity의 네 활성화 경계를 검증하기
  전에는 verified_active로 표시하지 않는다. canonical material preview lifecycle, 원격 CI와
  cross-platform matrix는 별도의 추가 미검증 제한이다.
- 이 문서는 지원됨, 검증됨, 통과함을 증명하는 verification evidence가 아니다.

실제 구현 상태와 실행 결과는 `VERIFICATION_AQ_V02_KO.md`에 실행한 명령, 환경, 결과,
경고와 제한을 근거로 별도 기록한다.

## 2. 마이그레이션 목표와 비목표

마이그레이션의 목표는 기존 계약과 증거를 그대로 읽을 수 있게 보존하면서, 새 품질·형상
의도·재질 저작·전달·controller 기능을 버전이 명시된 companion으로 병렬 추가하는 것이다.

다음은 마이그레이션 목표다.

1. 기존 Project 0.9.0과 V0.4부터 V0.9까지의 공개 계약을 제자리에서 변경하지 않는다.
2. 기존 SceneSpec 0.2.0과 derived-only SceneSpec V03 0.3.0의 경계를 보존한다.
3. AQ 0.1과 Integrated Quality 0.1 loader가 기존 증거를 계속 읽게 한다.
4. autonomous_static_prop_v1의 현재 의미, 출력 범위와 registry 상태를 보존한다.
5. AQ 0.2 전용 계약은 schema_version과 profile ID로 명시적으로 dispatch한다.
6. legacy evidence 변환이 필요한 경우 immutable plan, exact SHA-256 확인, 별도 apply와 receipt를
   사용한다.
7. 품질 확정과 GLB, FBX 또는 review-only 전달을 분리한다.
8. 기존 desktop-in-session 경계를 보존하면서 별도 ControllerExecutor를 추가할 수 있게 한다.
9. autonomy/service.py의 공개 facade를 보존하며 내부 책임을 단계적으로 분리한다.

다음은 비목표다.

- Project 1.0 승격
- canonical SceneSpec을 0.3.0으로 자동 교체
- 기존 AQ 세션, V0.8 workflow, production dispatch 또는 package의 소급 재작성
- 기존 사용자 승인 파일을 v2 PolicyAuthorization으로 변환
- architecture, environment, measured 또는 interior profile 활성화
- Unity, Unreal 또는 다른 목적지 프로젝트 수정
- destination runtime parity 주장
- arbitrary Blender Python, shader graph, shell 또는 network 권한 추가
- 검증되지 않은 profile이나 controller adapter의 활성 상태 승격

## 3. 하위 호환 기준선

| 기준선 | 마이그레이션 정책 | v2에서의 역할 |
|---|---|---|
| Project 0.9.0 | 버전 유지, 제자리 변경 금지 | AQ 0.2 companion을 담는 현재 프로젝트 버전 |
| SceneSpec 0.2.0 | canonical 계약 유지 | v1과 v2의 canonical geometry 입력 |
| SceneSpec V03 0.3.0 | derived-only 의미 유지 | optional structural candidate와 명시적 derived migration |
| Reference/Constraint 0.4.0 | 기존 loader와 의미 유지 | v2 companion metric의 authoritative source가 될 수 있음 |
| Material/Shader/Texture 0.5.0 | canonical 계약 유지 | 새 material companion 결과의 host 검증 및 promotion 대상 |
| Visual QA 0.6.0 | report와 overall direct score 유지 | Integrated Quality 0.2가 인용하는 기존 authoritative evidence |
| Portable Asset 0.7.0 | 승인, package, roundtrip 계약 유지 | v2 delivery가 호출하는 기존 format-specific 기반 |
| Workflow 0.8.0 | standard와 background_exterior 의미 유지 | AQ v2가 소급 변조하지 않는 기존 orchestration 경로 |
| Stabilization/Handoff 0.9.0 | audit와 handoff 승인 경계 유지 | roundtrip을 통과한 format별 package의 선택적 후속 단계 |
| AQ/IQ 0.1.0 | loader와 기존 evidence 의미 유지 | autonomous_static_prop_v1 전용 legacy 경로 |
| autonomous_static_prop_v1 | profile 의미와 현재 registry 상태 유지 | 기존 portable_gltf 고정 경로 |
| standard | 기본 실행 정책과 모든 승인 경계 유지 | AQ v2가 대체하지 않음 |
| background_exterior | fast-lane 정책과 품질/delivery 구분 유지 | AQ v2가 대체하거나 자동 전환하지 않음 |

기존 registry에 기록된 autonomous_static_prop_v1의 verified_active 표시는 그대로 보존한다.
다만 이 설계 문서가 그 상태를 새로 검증했다는 뜻은 아니다. 기존 세션과 package는 생성 당시의
profile, schema, source hash, 승인과 receipt로 해석하며 새 규칙으로 재평가하거나 재분류하지
않는다.

## 4. companion 버전과 dispatch

AQ 0.2의 신규 companion 버전은 다음과 같다.

| companion | 버전 | 기존 계약과의 관계 |
|---|---:|---|
| MeshPayload | 0.2.0 | 기존 0.1 payload를 계속 읽으며 per-loop UV와 geometry intent를 확장 |
| GeometryIntentSurvivalReport | 0.1.0 | 단계별 형상 의도 생존을 기록하는 파생 evidence |
| IntegratedQuality | 0.2.0 | V0.6 score를 바꾸지 않는 품질 companion |
| MaterialGraphRuntime | 0.1.0 | whitelist-only graph compile evidence |
| MaterialAuthoring | 0.1.0 | 고급 로컬 저작 strategy와 provenance companion |
| AdvancedMaterialHandoff | 0.1.0 | format별 portable approximation과 손실 companion |
| DeliveryProfile | 0.1.0 | 품질 확정과 전달 포맷 선택을 분리하는 계약 |
| ControllerExecutor | 0.1.0 | 격리 실행 assignment/result 계약 |
| Autonomy | 0.2.0 | autonomous_static_prop_v2 세션 계약 |

dispatch는 필드 존재 추측이나 디렉터리 이름 추론이 아니라 exact schema_version, profile ID,
session plan과 registry entry를 함께 사용해야 한다.

1. AQ 0.1과 autonomous_static_prop_v1은 기존 v1 loader와 service 경로로 보낸다.
2. AQ 0.2와 autonomous_static_prop_v2는 새 companion loader와 v2 service 경로로 보낸다.
3. MeshPayload 0.1은 기존 vertex UV 의미로 읽고, 0.2는 strict loop, edge, smoothing 및 source
   intent 규칙으로 읽는다.
4. version이 없거나 조합이 모순되면 최신 버전으로 가정하지 않는다.
5. 알려지지 않은 version/profile은 fail-closed로 거부한다. 실행에 필요한 binding이 부족한
   legacy evidence는 상태 조회와 audit만 허용하고 approve, resume, repair 또는 promotion에
   사용하지 않는다.
6. loader는 읽는 과정에서 파일을 다시 저장하거나 version을 올리지 않는다.
7. v1 evidence의 serialization, hash, producer ID와 terminal 판단을 v2 구현 편의를 위해 바꾸지
   않는다.

이 dispatch는 새 companion이 없는 기존 job도 정상이라는 원칙을 유지한다. companion 부재만으로
legacy standard, background_exterior 또는 AQ v1 job을 stale이나 failed로 만들지 않는다.

## 5. 자동 migration 금지

다음 동작은 migration authority가 아니다.

- job 또는 session load
- workspace audit
- autonomy plan/run/status
- build, QA, optimization 또는 package preflight
- production dispatch 또는 controller 실행
- handoff plan/generate/validate
- README, registry 또는 manifest 생성

이 동작들은 legacy version을 발견해도 canonical, candidate, package, approval, receipt 또는 profile을
자동 변환하면 안 된다. migration이 필요한 경우 현재 작업을 안전하게 중지하고 필요한 source,
목표 version, 손실 가능성, 새 output과 승인 지점을 보고해야 한다.

기존 blocked, failed, cancelled 또는 completed 세션을 v2 정책으로 바꾸지 않는다. v2를 사용하려면
원본 evidence를 그대로 둔 채 새 ID와 새 immutable root/session plan을 만들어야 한다.

## 6. 명시적 migration plan과 apply

### 6.1 plan 단계

plan은 read-only 분석이다. 최소한 다음을 exact 값으로 기록하는 immutable machine-readable
artifact를 계획한다.

- migration ID와 plan schema version
- source job/session/profile과 source schema version
- 모든 입력의 repository-relative path와 SHA-256
- 목표 companion version과 선택한 변환기 ID/version
- 유지되는 필드, 새로 파생되는 필드와 변환하지 못하는 필드
- 알려진 손실, underconstrained 항목과 review-required finding
- 생성 예정인 run-owned candidate, report, history와 receipt 경로
- canonical 변경 여부와 변경 가능한 정확한 역할
- 예상 public surface 및 registry 영향
- stale 판정 조건, rollback 경계와 적용 전 검증 목록

plan은 candidate 또는 최종 package를 canonical로 승격하지 않는다. 사용자는 보고된 plan 파일의
exact SHA-256을 별도로 확인하고 해당 plan에 한정된 apply를 승인해야 한다. 일반 production 요청,
기존 workflow 승인, V0.7 승인 또는 포괄적인 사전 승인은 migration plan 승인을 대신하지 못한다.

### 6.2 apply 단계

apply는 다음 순서를 따라야 한다.

1. 공유 job write lock을 획득한다.
2. lock 획득 후 plan, source, registry와 approval을 다시 읽고 exact SHA-256을 재검증한다.
3. approval의 목적, plan hash, single-use 상태와 허용 output을 검증한다.
4. run-owned staging에 candidate를 만들고 strict target schema로 다시 load한다.
5. source와 target의 의미 보존, 손실 보고, path containment와 dependency hash를 검증한다.
6. 검증된 artifact만 원자적으로 게시한다.
7. 이전 canonical을 교체해야 하는 별도 승인 경로가 존재하는 경우에만 exact history snapshot과
   compare-and-swap을 사용한다. AQ 0.2 기본 migration은 기존 canonical SceneSpec을 교체하지
   않는다.
8. source hash, plan hash, approval hash, candidate hash, 결과 hash, 변환기 ID, 시간과 결과를
   immutable apply receipt에 기록한다.
9. 사용한 승인은 재사용할 수 없게 소비 상태를 기록한다.

stale source, 변조된 plan/candidate, 예상 밖 output 또는 validation failure가 발생하면 apply는
fail-closed로 끝난다. 기존 plan이나 승인을 고쳐서 재사용하지 않고 새 migration ID, plan과 승인을
만든다.

## 7. SceneSpec과 MeshPayload migration

canonical SceneSpec 0.2.0은 v2에서도 바뀌지 않는다. SceneSpec V03 0.3.0의 기존 public
migration은 derived copy와 receipt를 만드는 의미를 유지하며 canonical promotion 명령으로
확대하지 않는다.

MeshPayload 0.1에서 0.2로의 변환은 별도 derived payload migration으로 계획한다.

- 원래 payload와 exact source geometry intent를 보존한다.
- vertex UV만 있는 경우 loop UV를 topology로 결정적으로 확장할 수 있을 때만 파생한다.
- UV seam, split normal, crease, bevel weight, material face group 또는 smoothing 의도를 evidence
  없이 발명하지 않는다.
- topology와 loop 순서가 모호하거나 source binding이 stale이면 review-required 또는 failure로
  끝낸다.
- 0.2 payload는 새 candidate/build에서 선택적으로 사용하며 기존 0.1 파일을 overwrite하지
  않는다.
- migration 성공은 Blender build, optimized source, GLB/FBX clean import까지 형상 의도가
  생존했다는 뜻이 아니다. GeometryIntentSurvivalReport와 실제 gate가 별도로 필요하다.

SceneSpec, geometry payload와 authoring blend 사이의 변환은 각각 별도 hash와 receipt를 가져야
한다. 하나의 migration receipt를 전체 production chain의 검증으로 재사용하지 않는다.

## 8. AQ v1에서 v2로의 profile/session migration

autonomous_static_prop_v1 session을 제자리에서 v2로 바꾸는 migration은 허용하지 않는다.
기존 v1 root authorization, policy authorization, candidate, transition, terminal, package와 handoff
evidence는 생성 당시 계약으로 영구 보존한다.

v2를 사용하려면 다음과 같이 새 세션을 계획한다.

1. 기존 canonical source를 read-only 입력으로 선택한다.
2. source SceneSpec, build provenance, material, QA, constraints와 package 관련 exact hash를 새 root
   authorization에 결속한다.
3. 새 authoring/quality profile과 허용 delivery profile을 명시한다.
4. destination hint, output scope, tool profile, action/build/render/iteration budget을 명시한다.
5. 기존 사용자 승인 파일을 복사하거나 PolicyAuthorization으로 변환하지 않는다.
6. 필요한 v2 gate마다 새 exact target과 제한된 authorization을 사용한다.

v2 root authorization은 최소한 authoring profile, quality profile, 허용 delivery profile 집합,
실제로 요청한 delivery profile 집합, 목적지 hint, output scope, budget과 immutable source map을
구분해야 한다. profile을 수정해 허용 semantic ID, operation, material 권한, format 또는 budget을
넓힐 수 없으며 확대가 필요하면 새 root plan과 authorization을 요구한다.

architecture, environment, measured와 interior profile은 registry에 정의가 추가되더라도 이번
버전에서 활성화하지 않는다. 해당 scope가 발견되면 v2 static-prop 경로가 임의로 처리하지 않고
기존 승인 경계 또는 restricted scope로 라우팅한다.

## 9. quality terminal과 delivery profile migration

### 9.1 기존 v1 보존

v1의 portable_gltf 고정 의미와 기존 V0.7 package 절차는 유지한다. 기존 profile ID,
optimization plan, approval, package ID, manifest, roundtrip과 handoff를 rename하거나 새 delivery
계약으로 재작성하지 않는다.

기존 V0.7 asset profile public ID도 유지한다.

- portable_gltf
- fbx_interchange
- obj_legacy

### 9.2 v2 delivery 분리 설계

v2 DeliveryProfile 0.1.0은 다음 public 역할을 계획한다.

| v2 delivery role | 기존 기반과의 연결 | production package | handoff eligibility |
|---|---|---:|---:|
| portable_gltf | 기존 portable_gltf profile을 사용 | roundtrip 성공 시 예 | 성공한 package만 가능 |
| portable_fbx | 기존 fbx_interchange profile에 명시적으로 mapping | roundtrip 성공 시 예 | 성공한 package만 가능 |
| review_only | preview, JSON, PDF review bundle | 아니오 | 아니오 |

portable_fbx는 기존 fbx_interchange ID를 rename하지 않는다. DeliveryProfile registry가 역할과
기존 V0.7 profile의 mapping을 명시한다. OBJ 회귀는 유지하지만 AQ v2의 초기 delivery 선택으로
자동 포함하지 않는다.

quality terminal은 source quality 상태를 먼저 종결하고 delivery는 그 이후 별도 run으로 수행한다.
설계상 `quality_approved` terminal만 exact source freeze를 가지며, `review_required` terminal은
source freeze 대신 exact review bundle을 결속한다. `blocked`와 `failed`를 review delivery나
package-ready로 migration하지 않는다. DeliveryProfile의 `review_only`는 quality-approved freeze
이후 package 없이 evidence를 전달하는 선택지이므로 non-pass review terminal과 다르다. 동일한
quality-approved source에서 GLB와 FBX를 모두 요청할 수 있지만 다음 규칙을 지켜야 한다.

- 각 format은 별도 delivery plan, run ID, package ID, manifest, dependency receipt, roundtrip,
  loss report와 terminal을 갖는다.
- 각 format의 V0.7 exact optimization-plan SHA-256 사용자 승인을 독립 검증하고 single-use로
  소비한다. policy authorization이나 generic AQ completion은 이를 대신하지 않는다.
- FBX는 exact quality-approved Blender source에서 직접 export한다. GLB를 FBX로 변환하지 않는다.
- 한 format 실패가 quality-approved source나 다른 format의 성공 package를 무효화하지 않는다.
- 실패한 format은 partial 또는 failed로 남기며 성공으로 합성하지 않는다.
- review_only bundle은 production package, clean-import evidence 또는 handoff source로 표현하지
  않는다.
- portable aggregate terminal은 exact quality terminal, source freeze, delivery plan,
  `DeliveryReviewBinding`과 모든 format result를 결속한다. 이 binding을 legacy filename 또는
  summary만으로 추정하지 않는다.
- destination hint는 inert data다. engine adapter 선택, destination write 또는 runtime parity
  authority가 아니다.

현재 supervisor/executor는 quality-approved source freeze에서 review-only terminal 또는 format별
V0.7 approval 대기/실행/terminal 재검증까지 연결한다. synthetic Blender fixture에서 GLB와 FBX가
서로를 변환 source로 사용하지 않고 독립 package/clean import를 만드는 경로가 통과했다. fixture의
`approved_by=user` artifact는 승인 소비 규칙을 시험하는 입력이며 실제 human approval evidence가
아니다.

passed IQ를 새 delivery 계약으로 옮길 때는 current canonical ModelingPlan, SceneSpec, blend, build,
material/shader/texture/geometry와 accepted geometry/material promotion receipts 및 survival evidence의
전체 exact closure가 필요하다. legacy summary나 terminal status만으로 source freeze를 만들지 않는다.
`QualityApprovedSourceFreeze`는 `geometry_candidate_validation_receipt`와
`material_phase_receipt`를 필수 필드로 가지며 receipt-free v2 freeze는 허용하지 않는다. global 및
semantic mask metric도 실제 PNG bytes에서 host가 다시 계산한 report만 freeze authority를 가진다.
DeliveryTerminal validator는 QualityTerminal full validator를 nested 호출하므로 forged
`quality_approved` projection을 migration source로 사용할 수 없다.

AdvancedMaterialHandoff artifact를 package에 포함하려면 package file set과 manifest가 immutable로
확정되기 전에 생성·검증·hash binding해야 한다. 완료된 package나 handoff 폴더에 나중에 파일을
추가하지 않는다. format별 package가 clean import와 handoff preflight를 통과한 뒤에만 기존 V0.9
exact-hash handoff 계획·승인 절차로 이어간다.

## 10. ControllerExecutor migration

기존 desktop_in_session과 client_mediated 실행 모드의 의미와 public surface는 유지한다. 새
ControllerExecutor 0.1.0은 이를 제거하거나 이름을 바꾸는 대체물이 아니라 assignment와 result를
엄격히 감싸는 additive protocol이다. `desktop_in_session`은 repository가 task를 생성하는 모드가
아니라 현재 task가 공급한 output을 exact 검증해 채택하는 adopt-only 모드다.

계획된 구현 역할은 다음과 같다.

- DesktopInSessionController: 기존 in-session 동작을 감싸고 exact assignment/output marker와
  hash를 검증한다. 현재 경계를 실제 sandbox 또는 global allowlist attestation으로 과장하지
  않는다.
- FakeControllerForTests: 정상, timeout, partial output, stale hash, path escape와 malicious extra
  file을 결정적으로 검증한다.
- OptionalCodexAppServerController: 설치 환경에서 공식 interface가 실제 탐지되고 실기동 검증된
  경우에만 연결한다. API나 명령을 추측하지 않으며 그 전에는 experimental_unverified다.

controller migration의 불변 조건은 다음과 같다.

1. controller는 canonical job root를 직접 수정하지 않는다.
2. immutable input snapshot, 정확한 allowed output paths, phase tool profile과 timeout만 받는다.
3. assignment는 RootAuthorization, session, source hashes, phase profile hash와 budget에 결속한다.
4. isolated workspace 밖의 파일, symlink/reparse escape, 예상하지 않은 extra output, stale/partial
   output을 거부한다.
5. supervisor가 strict validation 뒤 job-owned staging으로 복사하고, 별도 promotion service만
   canonical 변경을 수행한다.
6. controller completion marker는 사용자 승인이나 specialized authorization을 합성하지 않는다.
7. 무한 action loop를 허용하지 않는다. invocation/action budget, timeout, cancellation, duplicate
   action 차단과 crash recovery receipt가 필요하다.
8. waiting no-output 재호출은 동일 request/execution workspace를 유지하고 state/budget을 소비하지
   않는다. waiting 중 protected source가 바뀌면 기존 output을 채택하지 않는다.
9. state chain은 initial/transition/input/source/producer/provenance delta와 monotonic budget을
   재구성하며 phase splice와 rollback을 migration 가능한 history로 인정하지 않는다.

production/controller phase tool profile은 기존 전체 CLI/MCP 표면을 제거하지 않고 더 좁은 실행
권한을 부여하는 별도 registry다. reference_readonly, geometry_authoring, material_authoring,
quality_readonly, delivery, handoff_plan, admin_audit 같은 profile은 exact 허용 도구, 파일 역할,
canonical write, network 및 destination write 정책과 profile hash를 가져야 한다.

## 11. service facade migration

`autonomy/service.py`는 한 번에 재작성하지 않는다. 기존 public import, 함수 signature,
CLI/MCP 호출, serialization과 v1 hash behavior를 유지한다. 현재 v2 책임은 별도
`autonomy_v2/planner.py`, `controller_bridge.py`, `candidate_validation_service.py`,
`material_phase_service.py`, `quality_terminal_service.py`, `delivery_service.py`,
`delivery_executor.py`, `supervisor_service.py`, `transitions.py`에 추가되어 v1 facade와 분리됐다.

다음은 v1 facade를 더 작게 분리할 때의 목표 모듈이며 현재 모두 존재한다고 가정하지 않는다.

- session_service.py
- candidate_phase_service.py
- material_phase_service.py
- promotion_service.py
- quality_terminal_service.py
- package_terminal_service.py
- review_terminal_service.py
- recovery_service.py
- controller_bridge.py
- transitions 패키지

마이그레이션 순서는 다음과 같다.

1. 현재 facade의 public symbol과 테스트가 직접 사용하는 사실상 호환 symbol을 inventory한다.
2. 기존 transition 입력/출력, producer ID, JSON serialization과 hash의 golden fixture를 고정한다.
3. side effect가 없는 state transition부터 pure function으로 추출한다.
4. 파일 IO, Blender 실행, lock, authorization 소비와 promotion은 service/executor에 남긴다.
5. 한 책임씩 추출한 뒤 facade에서 같은 이름과 signature로 delegate하고 회귀를 실행한다.
6. v1은 기존 구현 경로를 유지하고 v2 dispatch만 새 모듈을 선택하게 한다.
7. 모든 추출이 검증되기 전까지 service.py facade를 제거하지 않는다.

순수 transition은 current state, event와 immutable evidence를 입력으로 받아 next state를 계산할 뿐,
파일을 쓰거나 승인을 소비하거나 Blender를 실행해서는 안 된다. 동일 v1 입력이 리팩터링 전후에
다른 state, reason code, artifact map 또는 terminal을 만들면 migration failure다.
v2 reconstructed state도 predecessor hash만 검사하지 않는다. producer와 provenance prefix/delta,
source/input closure 및 budget monotonicity가 일치해야 하며 중간 phase를 끼워 넣거나 과거 source로
되돌린 chain은 legacy 호환으로 허용하지 않는다.

## 12. CLI, MCP, allowlist와 registry 호환

기존 public CLI/MCP 명령은 제거, rename 또는 의미 변경하지 않는다. 현재 AQ v2 status,
delivery-profile listing, plan/status/advance/run/cancel, ControllerExecutor status와 SceneSpec V03
migration plan/apply가 additive하게 등록되어 있다. `advance`와 `run`은 controller output,
caller-supplied IQ 또는 exact V0.7 approval이 없으면 해당 경계에서 정지하며 승인을 자동 생성하지
않는다. MaterialAuthoring companion 전용 CLI는 별도 public surface가 아니다.

새 public surface를 추가할 때 다음 순서를 지켜야 한다.

1. service와 strict request/response model 구현
2. CLI와 MCP가 동일한 validation 및 reason code를 사용하도록 연결
3. public schema와 registry 생성
4. phase tool profile에 필요한 최소 도구만 등록
5. .codex allowlist에는 실제 desktop 사용이 검증된 항목만 명시적으로 추가
6. CLI help, MCP registry, allowlist, README와 generated summary parity 검증

MCP server에 도구가 존재하는 것과 .codex global allowlist 또는 controller phase profile에 허용되는
것은 별개의 사실이다. 새 도구를 server에 등록했다는 이유로 모든 controller에 자동 허용하지
않는다. 기존 도구를 registry 정리 과정에서 삭제하지 않는다.

## 13. AGENTS, CI와 문서/registry migration

AGENTS 계층화는 asset evidence migration이 아니다. 루트의 절대 불변 규칙을 보존하고 상세 규칙을
하위 AGENTS와 `docs/agent/`에 배치했다. `scripts/check_agent_instructions.py`가 size,
root-to-leaf 합산, RULE_ID coverage와 상충을 검사한다.

GitHub Python CI와 선택적 self-hosted Blender smoke는 additive하다. runner가 없거나 workflow를
실행하지 않았으면 not-run 또는 unverified로 기록하고 통과로 간주하지 않는다. CI 도입이 기존
workspace, package 또는 receipt를 재생성하거나 migration할 권한을 주지 않는다.

README, REPOSITORY_TREE, FILE_MANIFEST와 profile/CLI/MCP/delivery 목록은 pure repository
registry에서 결정적으로 생성·검사한다. `generate_repository_summary.py --check`는 drift를
보고할 뿐 자동 asset migration을 하지 않는다. generated 문서 drift를 고치는 작업과 immutable
asset evidence migration을 섞지 않는다.

## 14. rollback과 failure model

| 실패 시점 | fail-closed 처리 | 보존/rollback | 재시도 조건 |
|---|---|---|---|
| unknown 또는 모순된 schema/profile | 실행·promotion 거부 | 원본 그대로, status/audit-only 가능 | 지원 loader 또는 새 explicit plan 필요 |
| source가 plan 이후 변경됨 | stale migration으로 중지 | source와 기존 artifact 무변경 | 새 migration ID와 plan/승인 |
| plan, approval 또는 candidate 변조 | orchestration/artifact conflict로 중지 | 변조 전 immutable evidence와 finding 보존 | 기존 승인 재사용 금지, 새 plan 필요 |
| staging 생성 실패 | canonical publish 금지 | incomplete staging과 failure receipt 보존 | 원인 수정 후 새 plan; 자동 성공 분류 금지 |
| strict schema/semantic validation 실패 | apply 실패 | 기존 canonical과 package 무변경 | 손실/입력 검토 후 새 plan |
| canonical promotion compare-and-swap 실패 | promotion 금지 또는 exact archive로 복원 | history, attempt와 rollback receipt 보존 | lock/source 재검토와 새 authorization |
| controller timeout/partial/extra/path escape | controller output 전체 거부 | isolated attempt와 receipt 보존, canonical 무변경 | AQ v2 timeout은 nonretryable failed terminal; partial/extra/escape도 자동 retry 없음 |
| waiting 중 protected source 변경 | 같은 execution output adoption 거부 | waiting request/workspace와 tamper evidence 보존 | 새 current plan/session 필요 |
| state phase splice/provenance 또는 budget rollback | chain 전체 current-state 사용 거부 | 원본 immutable states 보존 | 제자리 repair 금지, 새 session 필요 |
| forged IQ hard finding/source closure/quality terminal | freeze와 delivery terminal 거부 | IQ/terminal/package evidence 보존, canonical 무변경 | exact current IQ/terminal 재생성 |
| GLB 또는 FBX delivery 실패 | 해당 format만 failed/partial | quality freeze와 다른 성공 package 보존 | 새 format-specific plan/approval |
| clean-import roundtrip 실패 | package acceptance와 handoff 금지 | export와 failure evidence는 보존 | source/profile 수정 후 새 V0.7 review |
| handoff preflight/validation 실패 | handoff current/valid 주장 금지 | package와 기존 handoff evidence 보존 | package를 덮어쓰지 않고 새 handoff ID |
| service facade golden regression | 배포/활성화 중지 | 사용자 workspace/evidence 무변경 | source refactor rollback 후 재검증 |
| cancellation | 미래 action 중지 | 이미 게시된 immutable evidence 보존 | cancelled session 재개 금지, 새 session 필요 |

rollback은 evidence 삭제가 아니다. 이전 canonical을 교체하는 승인된 promotion이 있었다면 exact
history snapshot으로만 복원하고 rollback receipt를 남긴다. 완료된 receipt, package, QA run,
session 또는 handoff를 덮어쓰지 않는다.

코드 리팩터링 회귀는 소스 변경을 rollback하는 문제이며 사용자 job을 gate 성공용으로 수정해서
숨기지 않는다. harmless log와 isolated attempt는 실제 문제를 일으키지 않는 한 보존한다.

## 15. 단계별 도입 순서

1. 기존 v1 loader, public surface, serialization과 state transition golden baseline을 고정한다.
2. strict companion schemas와 version dispatch를 추가하되 v2 profile은 disabled_experimental로
   둔다.
3. explicit migration plan/apply와 failure receipt를 isolated fixture에서 검증한다.
4. MeshPayload 0.2와 GeometryIntent survival evidence를 candidate부터 clean import까지 연결한다.
5. Integrated Quality 0.2와 MaterialGraph/MaterialAuthoring companion을 추가한다.
6. AQ v2 quality terminal과 DeliveryProfile을 분리하고 review-only, GLB, FBX 독립 실패를 검증한다.
7. ControllerExecutor fake/desktop wrapper를 연결하고 output containment와 crash recovery를 검증한다.
8. service facade를 한 책임씩 추출하며 매 단계 v1 golden 및 public CLI/MCP 회귀를 실행한다.
9. Python CI, optional Blender smoke와 registry/document parity 검사를 추가한다.
10. 전체 legacy 및 v2 gate 결과를 verification 문서에 실제 결과로 기록한다.
11. 모든 필수 gate가 실제 통과한 경우에만 autonomous_static_prop_v2의 활성 상태 변경을 별도
    검토한다. 일부 gate가 없거나 실패하면 disabled_experimental 또는 experimental 상태를
    유지한다.

각 단계는 독립적으로 rollback 가능해야 한다. 후속 단계가 실패해도 기존 standard,
background_exterior, AQ v1과 V0.7부터 V0.9 evidence를 migration 대상으로 삼지 않는다.

## 16. 활성화 전 검증 기준

AQ v2 활성화 판단에는 최소한 다음 증거가 필요하다.

- legacy Project 0.9.0 및 SceneSpec 0.2.0 fixture load
- MeshPayload 0.1/0.2 loader와 explicit migration plan/apply
- standard, background_exterior와 AQ v1 state/hash golden 회귀
- V0.7 GLB/FBX/OBJ package와 clean-import 회귀
- V0.8 workflow, V0.9 audit/production/handoff 회귀
- v2 quality-pass, review-only, GLB, FBX와 dual-delivery isolated 시나리오
- format-specific 실패가 다른 delivery와 quality freeze를 오염시키지 않는지 검증
- ControllerExecutor 정상/timeout/partial/extra/path escape/stale/crash-resume 검증
- service facade 전후 public import, CLI/MCP와 transition parity
- schema/Pydantic, registry/README, MCP/allowlist와 repository summary parity
- Ruff와 전체 pytest
- 가능한 환경에서 Blender 5.0.1 geometry, material, package와 roundtrip gate

contract test만 통과한 기능을 Blender_verified로 표시하지 않는다. synthetic fixture 결과를 임의
reference 자산의 일반 품질 향상으로 표현하지 않는다. 실제 reference benchmark가 없는 metric, material
strategy, controller adapter와 delivery 조합은 unverified 또는 experimental로 남긴다.

## 17. 현재 검증 상태

2026-08-11 현재 상태는 다음과 같다.

- `autonomous_static_prop_v2`: `disabled_experimental`
- AQ v2 profile/planner/state/advance/run/cancel과 strict companion Schema: host/full 회귀 통과
- MeshPayload 0.2 explicit migration과 compiler/survival: bounded Blender synthetic 경로 통과
- Integrated Quality 0.2 metric/ranking/reentry: host 구현됨; 실제 reference 일반 향상 미검증
- MaterialGraphRuntime: host contract와 fixed Blender compile/reopen/inventory fixture 통과
- MaterialAuthoring: local deterministic 8 strategy와 fixed Blender family smoke 통과; canonical master/neutral preview 상태는 별도
- DeliveryProfile: review-only 및 같은 freeze의 독립 GLB+FBX clean import synthetic fixture 통과
- ControllerExecutor: execution-owned fake/desktop adoption 통과; Desktop는 adopt-only, optional App Server는 unavailable/experimental 경계
- service facade: v1 유지, v2 별도 modules 추가; 목표 v1 세분화는 완료로 주장하지 않음
- legacy: V0.7/V0.8/V0.9 root smoke 통과; 기존 evidence 의미와 migration 없음
- CI/registry: scripts와 workflow 정의 구현됨; 실제 GitHub/self-hosted Blender run은 별도 증거 필요

이 문서는 기존 v1 자산을 v2로 변환할 권한을 제공하지 않는다. 기존 standard,
background_exterior, `autonomous_static_prop_v1`과 V0.7~V0.9 승인 경계는 그대로 사용한다.
새 v2 계획은 명시적 experimental opt-in을 요구하며 기존 session을 자동 migration하지 않는다.
