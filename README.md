# BlenderAssetGenerator V0.9.0

레퍼런스 이미지, 직교 도면, 치수와 사용자 피드백을 재현 가능한 Blender 정적 자산으로 변환하는 Codex 작업 저장소입니다. V0.9는 V0.8까지의 분석·형상·재질·Visual QA·portable package·workflow를 보존하면서 환경 증거, 읽기 전용 workspace audit, single-worker queue와 release-candidate 보고 계층을 추가합니다.

> 설계 원본은 `.blend`가 아니라 `workspaces/<job>/` 아래의 immutable 입력과 versioned JSON 계약입니다. `.blend`, 렌더, PDF, 최적화 장면과 export package는 검증 가능한 파생 산출물입니다.

## 현재 상태

| 항목 | 현재 계약 또는 상태 |
|---|---|
| 프로젝트 | `0.9.0` |
| Geometry SceneSpec | `0.2.0` |
| Reference / Constraint | `0.4.0` |
| Optional InteriorScope | `0.1.0` |
| Material / Shader | `0.5.0` |
| Visual QA | `0.6.0` |
| Portable static asset | `0.7.0` |
| Workflow orchestration | `0.8.0` |
| Stabilization evidence | `0.9.0` |
| 실제 검증 환경 | Windows, Python 3.14.6, Blender 5.0.1 |
| 최신 Python 회귀 | 374 tests passed, Ruff passed |

Blender 4.x용 feature-probe fallback은 유지하지만 현재 통합 저장소의 실제 Blender 실행 기준선은 5.0.1입니다. macOS, Linux, 다른 Python/Blender 조합은 실제 V0.9 gate가 수행되기 전까지 `unverified`입니다.

## 구현 범위

- 결정론적 reference diagnostics와 카메라 가정
- concept 및 measured 작업, auxiliary view와 constraint residual
- primitive, custom mesh, profile extrusion, revolve, curve와 terrain
- optional interior의 exact-hash scope 승인과 fail-closed 검증
- MaterialPlan, whitelisted Blender shader recipe, texture manifest와 bake contract
- 정확히 7개 고정 카메라 패스를 사용하는 Visual QA
- semantic ID 기반 revision candidate와 single-use 승인·rollback
- engine-neutral GLB, FBX, OBJ 정적 자산 preflight·최적화·package·clean-import round trip
- 짧은 요청의 deterministic intent routing, 상태 재구성, 잠금, 재개, 취소와 승인 대기
- privacy-safe 환경 probe와 bounded read-only workspace audit
- 기존 V0.8 workflow만 처리하는 single-worker local queue와 immutable attempt receipt
- exact environment/audit JSON hash에 묶인 V0.9 stability PDF와 sidecar
- authoritative JSON을 기반으로 한 build, material, QA, export, full PDF 보고서

현재 구현하지 않았거나 지원을 주장하지 않는 범위:

- Unity prefab, Unreal actor 또는 특정 엔진의 runtime shader adapter
- rig, skinning, animation과 캐릭터용 topology
- 모든 CAD 형식의 실제 parsing과 B-Rep 변환
- 단일 이미지에서 보이지 않는 후면·내부·절대 치수의 정답 복원
- multi-worker 또는 distributed scheduler와 완성된 cross-platform release matrix

명시적 목적지 adapter가 없으면 V0.8은 V0.7 engine-neutral portable package에서 정상 종료합니다.

## 핵심 저장소 구조

```text
BlenderAssetGenerator/
├─ AGENTS.md                         프로젝트 불변 규칙
├─ .codex/                           프로젝트 MCP 설정
├─ .agents/skills/                   명시적으로 요청할 때만 사용하는 작업 스킬
├─ schemas/                          versioned JSON Schema
├─ prompts/                          agent 저작 단계용 프롬프트
├─ src/codex_blender_modeler/
│  ├─ analysis/                      V0.4 reference diagnostics
│  ├─ constraints/                   measured residual 평가
│  ├─ materials/, texturing/, baking/
│  ├─ qa/                            V0.6 비교와 후보 생성
│  ├─ optimization/, packaging/      V0.7 derived portable asset
│  ├─ orchestration/                 V0.8 workflow state machine
│  ├─ stabilization/                 V0.9 probe, audit, queue, PDF
│  └─ blender_scripts/               whitelisted Blender background scripts
├─ examples/                         geometry_showcase, measured_box 등
├─ tests/                            계약·음성·회귀 테스트
├─ reports/                          격리 gate, V0.9 probe와 audit 증거
├─ output/pdf/v09/                   exact-hash stability PDF
└─ workspaces/<job>/                 자산별 canonical 및 derived 상태
```

## 설치와 환경 확인

`.env`에서 `BLENDER_BIN`을 실제 Blender 실행 파일로 지정합니다.

```powershell
uv sync --frozen --extra dev --extra vision
uv run cbm doctor
uv run cbm blender-compat
uv run cbm workflow-adapters
```

`workflow-adapters`의 검증된 기본 목적지는 `engine_neutral`입니다. Unity 또는 Unreal이 표시되더라도 실제 adapter 검증 전에는 지원된 것으로 취급하지 않습니다.

## V0.8 짧은 요청 workflow

새 자산은 고유한 소문자 `job_id`와 primary reference로 시작합니다.

```powershell
uv run cbm workflow-plan `
  --request "이 이미지로 수정 가능한 정적 3D 프록시를 만들어줘" `
  --job-id temple_asset `
  --reference-path E:\References\temple.png
```

출력된 workflow ID로 상태를 확인하고 결정론적 host 단계를 진행합니다.

```powershell
uv run cbm workflow-status temple_asset
uv run cbm workflow-resume temple_asset <workflow-id>
```

Agent가 작성해야 하는 modeling plan, SceneSpec, material plan 또는 revision plan에서는 workflow가 정상적으로 멈춥니다. 해당 산출물을 작성·검증한 뒤 현재 fingerprint와 함께 completion marker를 남겨야 다음 단계가 열립니다. 프록시, 재질 swatch, Visual QA 수정과 V0.7 optimization은 각각의 승인 경계를 유지합니다.

기존 job은 reference hash가 같아도 `new_asset`으로 다시 시작할 수 없습니다.

```powershell
uv run cbm workflow-plan `
  --request "중앙 탑 높이만 10% 높여줘" `
  --job-id temple_asset `
  --intent revise_asset
```

완전한 사용 예와 승인·재개 명령은 [V0.8 빠른 시작](GETTING_STARTED_V08_KO.md)을 따릅니다.

## V0.9 안정화 표면

```powershell
uv run cbm stability-probe --probe-id probe-local-001
uv run cbm workspace-audit --audit-id audit-local-001
uv run cbm stability-report-pdf `
  --probe-id probe-local-001 `
  --audit-id audit-local-001 `
  --report-id stability-local-001
```

Audit는 canonical job을 repair하거나 migration하지 않습니다. Queue는 이미 계획된 V0.8 workflow만 한 번에 하나씩 진행하고 agent 또는 승인 경계에서 멈춥니다. 전체 사용법은 [V0.9 빠른 시작](GETTING_STARTED_V09_KO.md)을 따릅니다.

## 단계별 제작 흐름

```text
immutable input
→ V0.4 reference/camera analysis and geometry
→ optional measured constraints / interior scope
→ V0.5 material, texture and shader
→ V0.6 fixed-camera QA and guarded revision
→ V0.7 derived optimization and portable package
→ V0.8 orchestration, resume and approval boundaries
→ V0.9 stabilization evidence and release gates
```

작업 단계는 일방통행이 아닙니다. 형상이 마음에 들지 않으면 현재 저장소를 유지한 채 V0.4 authoring으로 돌아가고, 국소적인 레퍼런스 오차는 V0.6 guarded revision으로 처리합니다. canonical 입력이 바뀌면 이후 build, QA와 package는 stale 상태가 되며 새 run ID로 재검증합니다.

## 안전 원칙

- `workspaces/*/input/`은 수정하지 않습니다.
- 단일 uncalibrated 이미지에서 절대 치수나 보이지 않는 구조를 복원했다고 주장하지 않습니다.
- 모든 모델링 객체와 재질은 stable semantic ID를 유지합니다.
- interior는 기본 비활성화이며 exact scope hash 승인 전에는 생성하지 않습니다.
- `.blend`를 canonical 수정 수단으로 사용하지 않습니다.
- 생성 이미지 기반 QA target은 보조 근거이며 단독으로 revision을 승인하지 못합니다.
- V0.7은 canonical authoring 데이터를 수정하지 않고 run-owned derived directory에서만 최적화합니다.
- 일반 workflow 승인은 InteriorScope, Visual QA revision 또는 optimization의 전용 승인을 대체하지 못합니다.

전체 규칙은 [AGENTS.md](AGENTS.md)를 따릅니다.

## 테스트

빠른 Python·정적 검사:

```powershell
uv run pytest
uv run ruff check .
uv run cbm doctor
```

현재 통합 gate:

```powershell
.\scripts\run_v09_gates.ps1
```

V0.9 안정화만 진단하고 V0.8 회귀를 별도 실행한 경우에만:

```powershell
.\scripts\run_v09_gates.ps1 -SkipV08
```

실제 검증 결과는 [V0.9 검증 기록](VERIFICATION_V09_KO.md)에 있습니다. 테스트하지 않은 운영체제, Blender 버전, 엔진 또는 adapter는 지원된 것으로 표시하지 않습니다.

## 문서 안내

- [V1.0 공식 로드맵](ROADMAP_V1_KO.md)
- [V0.9 아키텍처](ARCHITECTURE_V09_KO.md)
- [V0.9 빠른 시작](GETTING_STARTED_V09_KO.md)
- [V0.9 테스트 계획](TEST_PLAN_V09_KO.md)
- [V0.9 검증 기록](VERIFICATION_V09_KO.md)
- [V0.8 아키텍처](ARCHITECTURE_V08_KO.md)
- [V0.8 빠른 시작](GETTING_STARTED_V08_KO.md)
- [V0.8 테스트 계획](TEST_PLAN_V08_KO.md)
- [V0.8 검증 기록](VERIFICATION_V08_KO.md)
- [V0.7 portable asset 아키텍처](ARCHITECTURE_V07_KO.md)
- [V0.7.4 최적화 승인 경계](V074_PRE_OPTIMIZATION_REVIEW_KO.md)
- [선택적 실내 범위](INTERIOR_SCOPE_KO.md)
- [Blender 5 호환성](BLENDER_5_COMPATIBILITY_KO.md)
- [변경 기록](CHANGELOG.md)

V0.9는 release-candidate 기반을 구현하지만 아직 cross-platform 또는 목적 엔진 parity를 의미하지 않습니다. 실제 V1.0 승격 전에는 남은 지원 매트릭스, 실제 자산 benchmark, release blocker와 공개 계약 동결을 완료해야 합니다.
