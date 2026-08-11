# ControllerExecutor 0.1 안내

## 1. 목적

ControllerExecutor `0.1.0`은 AQ 0.2의 agent-authored candidate 작업을 canonical source와
분리된 output directory에서 수행하고, host가 exact input/output을 검증한 뒤에만 채택하기 위한
bounded protocol이다. controller에 사용자 승인, canonical write, shell 또는 destination project
write 권한을 주는 기능이 아니다.

현재 host protocol, fake adapter, `desktop_in_session` adoption, execution-owned 격리 workspace와
음성 fixture가 구현되어 있다. geometry와 material output의 strict validation/promotion 및 이후
caller-supplied IQ→delivery supervisor 연결도 host/Blender synthetic fixture에서 검증됐다. 저장소가
새 Codex task를 생성하거나 optional Codex App Server를 직접 호출하는 기능은 없다.

## 2. capability 상태 확인

```powershell
uv run cbm controller-executor-status
```

Codex/MCP에서는 `get_controller_executor_status`를 사용한다. 현재 catalog의 의미는 다음과 같다.

| controller kind | 상태 | 의미 |
|---|---|---|
| `desktop_in_session` | `available` | 현재 Codex task가 allowed output을 공급하면 host가 exact 검증 후 채택 가능 |
| `fake_for_tests` | `test_only` | success/timeout/failure/partial/extra/crash 음성 fixture용 |
| `optional_codex_app_server` | `unavailable` | 공식 interface가 주입되지 않았으며 repository가 API를 추측하지 않음 |

공식 interface ID와 callable을 supporting client가 주입하더라도 optional App Server adapter는
실기동·sandbox evidence가 완성되기 전 `experimental_unverified`다. 모든 controller에서
`repository_can_spawn_codex_task=false`다. 즉 `desktop_in_session`은 현재 task가 만든 output을
검증해 채택하는 **adopt-only** 모드다.

## 3. protocol 객체

### 3.1 `PhaseToolProfile`

phase별로 다음을 고정한다.

- allowed/forbidden tool 이름
- allowed input role
- allowed output path
- `canonical_write_authority=supervisor_only`
- `network_access=denied`
- `destination_project_write=false`
- sandbox attestation

`repository_path_validation_only`는 repository host가 path와 hash를 검사한다는 뜻이다. 외부
client의 실제 OS/container sandbox를 증명하지 않는다. supporting client가 별도 enforcement를
증명한 경우에만 `supporting_client_enforced`를 기록할 수 있다.

### 3.2 `ControllerExecutionRequest`

request는 assignment, immutable inputs, exact tool profile, output root, allowed output list,
선택적 expected output hashes, timeout과 invocation budget `1`을 고정한다. 모든 allowed output은
정확히 output root의 descendant여야 한다.

### 3.3 `ControllerResult`

결과 status는 다음 중 하나다.

- `completed`
- `waiting_for_output`
- `timeout`
- `failed`
- `rejected`
- `cancelled`

`completed`는 allowed output이 모두 존재하고 extra/partial이 없으며 exact inventory hash가
일치할 때만 가능하다. 결과는 항상 `canonical_unchanged=true`다.

## 4. phase profile catalog

현재 pure Python catalog는 Blender나 MCP server를 import하지 않고 다음 phase를 제공한다.

| profile | 허용 역할 | 대표 허용 도구 | output 성격 |
|---|---|---|---|
| `reference_readonly` | reference/workflow 조회 | capability와 workflow state 조회 | 없음 |
| `geometry_authoring` | assignment/reference/camera/baseline | delegated step record | isolated modeling plan/SceneSpec candidate/completion |
| `material_authoring` | assignment/scene/scale/material baseline | delegated step record | isolated material candidate/completion |
| `quality_readonly` | quality input/camera/reference | integrated quality 상태 조회 | 없음 |
| `delivery` | source freeze/delivery plan | production status/advance | supervisor가 소유한 기존 delivery 경계 |
| `handoff_plan` | package/roundtrip/material loss | production status 조회 | destination write 없음 |
| `admin_audit` | session/receipt chain | production status/workspace audit | audit evidence |

phase allowlist, MCP server registry와 project-enabled `.codex/config.toml` allowlist는 서로 다른
집합이다. controller profile의 tool은 project-enabled tool의 부분집합이어야 하지만, MCP server의
모든 도구가 controller에 허용되는 것은 아니다.

다음 authority tool은 phase profile에서 금지된다.

- workflow, visual revision, V0.7, Destination Handoff 승인
- failed retry를 합성하는 도구
- arbitrary Blender Python
- shell command
- destination project write

## 5. `desktop_in_session` 흐름

```text
supervisor가 exact assignment/input/tool profile 게시
→ ControllerExecutionRequest 게시
→ desktop adapter 첫 검사: output 없음
→ status=waiting_for_output
→ 현재 Codex task가 execution-owned workspace의 allowed output만 작성
→ host가 request/input/profile을 다시 hash 검증
→ allowed set, 누락·추가 파일, optional expected hash 검사
→ exact ControllerResult 게시
→ supervisor가 별도 strict validation/promotion 결정
```

`waiting_for_output`은 failure도 completion도 아니다. current task가 output을 쓰는 행위와 host가
canonical candidate로 채택하는 행위는 분리된다.

public `autonomy-v2-advance`/`autonomy-v2-run`이 waiting session을 다시 호출할 때 새 request나 새
execution workspace를 만들지 않는다. 동일 request와 execution-owned workspace를 다시 읽고
assignment/input/profile/output set을 exact rehash한 뒤 completed output만 채택한다. output이 아직
없으면 같은 waiting state를 반환하며 state sequence, action budget, controller invocation budget을
증가시키지 않는다. waiting 사이에 canonical ModelingPlan/SceneSpec/blend, material contract 또는
그 밖의 protected job-root source가 바뀌면 output 유무와 관계없이 stale/tamper로 거부한다.

## 6. 출력 격리와 채택

각 invocation의 기본 namespace는 다음 역할을 가진다.

```text
production/autonomy_v2/<session-id>/controller_executions/<execution-id>/
├─ controller_workspace/
│  ├─ inputs/       # immutable snapshots
│  └─ outputs/      # exact allowed set
└─ controller_executor_evidence/
```

controller request에는 canonical job root 자체를 주지 않는다. output은 canonical
`analysis/scene_spec.json`, `analysis/material_plan.json` 또는 `blender/scene.blend`를 직접 가리킬
수 없다. host는 다음 순서로 fail-closed한다.

1. job root와 request path containment 검사
2. assignment/input/profile exact path·size·SHA-256 재검증
3. profile과 request의 allowed output set 일치 검사
4. output root 밖 파일과 symlink/escape 거부
5. partial, extra, stale, hash mismatch 거부
6. exact sorted output inventory digest 계산
7. result 게시
8. 별도 supervisor validation과 promotion

단순히 output file이 존재한다는 이유로 agent completion이나 canonical promotion을 만들지 않는다.
waiting request가 처음 결속한 protected source와 현재 source의 exact file set/hash도 adoption 전에
다시 비교한다. 동일 output bytes라도 source가 바뀌었으면 새 session/request 없이 채택할 수 없다.
execution-root `result.json`과 `adoption/result.json`이 이미 존재하는 복구에서도 request, input
snapshot, tool profile, output inventory, started/invocation/completed/published lifecycle receipts를
전부 재구성하고 저장된 result bytes와 exact equality를 요구한다. 직접 bridge 호출도 active·미만료
`RootAuthorizationV2`와 exact plan/profile/budget/phase-profile/delivery binding을 먼저 확인한다.

## 7. 실패 모델

| 상황 | 결과 | canonical 영향 |
|---|---|---|
| output 없음 | `waiting_for_output` | 없음 |
| raw executor timeout | `timeout`, receipt의 분류는 retryable일 수 있음 | 없음 |
| AQ v2 bridge timeout | 즉시 nonretryable `failed`, `next_action=none` | 없음 |
| controller exception/crash | `failed` | 없음 |
| 일부 파일만 존재 | `rejected` | 없음 |
| 허용되지 않은 extra file | `rejected` | 없음 |
| expected hash 불일치 | `rejected` | 없음 |
| immutable input/profile tamper | 실행 전 exception/fail-closed | 없음 |
| output path가 root 밖 | request validation failure | 없음 |
| cancel | 이후 invocation 중단, evidence 보존 | 없음 |

raw executor의 retry 분류가 자동 재실행 권한을 만들지는 않는다. 현재 AQ v2 bridge는 timeout을
terminalize하며 새 invocation/attempt를 만들지 않는다. repeated-identical/transient budget 값도
사용자 승인이나 무제한 재시도를 허용하지 않는다.

## 8. AQ v2 연결

v2 plan은 다음 phase profile artifact를 미리 만들어 root authorization과 plan에 hash-bound한다.
기본 controller mode는 `desktop_in_session`; `client_mediated`도 planner 입력으로 허용된다.

v2 state는 immutable `states/0000.json`, `0001.json` 순서로 게시되고 predecessor digest를 가진다.
대표 state transition은 다음 역할이다.

```text
reference_ready → authoring/running
geometry_controller_required → authoring/waiting_for_controller
geometry_candidate_validated → material/running
material_controller_required → material/waiting_for_controller
material_candidate_validated → quality/running
caller-supplied IQ report validated → quality terminal
quality_passed → quality_approved/plan_delivery
quality_nonpassing → review_required terminal
delivery_planned → delivery_pending/await_v07_approval
delivery_finished → completed|partial|failed terminal
```

state transition은 pure model이고 side effect를 수행하지 않는다. filesystem lock, exact rehash,
controller execution과 terminal publication은 별도 service 책임이다.

상태 조회와 다음 action 선택 전에 validator는 initial state부터 전체 chain을 재구성한다. 각 state의
sequence/predecessor뿐 아니라 transition event, input/source map, producer, provenance delta와 budget
snapshot을 다시 계산한다. provenance는 이전 state의 prefix에 이번 transition의 선언된 delta만
추가할 수 있고 budget counter는 감소하거나 허용되지 않은 축에서 증가할 수 없다. 중간 phase state를
삽입한 splice, 이전 source로 되돌린 rollback 또는 producer/evidence 교체는 terminal summary가
그럴듯해도 거부한다.

Geometry completed output은 modeling plan, SceneSpec V03 candidate와 completion marker의 정확한 세
파일이어야 한다. Material completed output은 material plan, MaterialGraph candidate와 completion
marker의 정확한 세 파일이어야 한다. 각 service가 schema/scope/hash를 재검증하고 build 또는
rebuild를 거친 뒤 compare-and-swap promotion한다. controller completion만으로 promotion하지 않는다.

## 9. public surface의 현재 한계

현재 공개 CLI/MCP는 v2 plan/status/advance/run/cancel과 controller capability status를 제공한다.
`autonomy-v2-advance`는 한 action, `autonomy-v2-run`은 budget 안의 여러 action을 수행한다. 기존
AQ v1의 `autonomy-run`은 별도 명령이다. v2 `run`에도 repository-side task-spawn command는 없다.

따라서 ControllerExecutor와 supervisor 구현만으로 Desktop가 처음부터 output을 생산하는 완전 무인
제작을 주장할 수 없다. 특히 다음은 계속 별도 caller/사용자/host 경계다.

- Desktop task가 geometry/material allowed output을 실제로 작성하는 단계
- caller가 exact IQ 0.2 report를 공급하는 단계
- non-passing quality의 처리
- V0.7 exact optimization-plan SHA-256 승인
- Destination Handoff 승인
- destination project import와 검증

## 10. 보안·운영 체크리스트

- controller가 읽을 input role과 쓸 output path를 최소화한다.
- assignment에 absolute path나 shell/Python code를 넣지 않는다.
- metadata와 filename 문자열을 명령으로 실행하지 않는다.
- output adoption 전에 request와 모든 input을 다시 hash한다.
- `repository_path_validation_only`를 실제 sandbox attestation으로 과장하지 않는다.
- optional interface가 감지되지 않으면 API나 command를 추측하지 않는다.
- user workspace 또는 기존 evidence를 gate 성공용으로 수정하지 않는다.
- destination project root를 controller output으로 허용하지 않는다.

host/full 회귀와 synthetic Blender flow가 geometry→material→caller-supplied IQ→quality
terminal→delivery terminal 계약을 검증했다. external supporting-client containment, optional App
Server 실기동, 실제 사람이 승인한 production run과 repository-side task spawn은 계속
**unverified**다.
