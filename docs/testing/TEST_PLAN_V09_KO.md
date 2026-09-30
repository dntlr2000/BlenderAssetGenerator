# V0.9 테스트 계획

V0.9 완료 판정은 Python contract test만으로 내리지 않는다. 이전 계약 회귀, failure boundary, 개인정보 보호, immutable evidence, Blender 5.0.1 실기동과 PDF 시각 검사를 함께 확인한다.

## Gate 1 — 계약과 공개 표면

- 모든 `0.9.0` Pydantic model과 checked-in JSON Schema parity
- unknown field 거부와 relative-path 검증
- CLI command 등록
- MCP allowlist와 capability version
- 프로젝트 `0.9.0`, workflow `0.8.0`, 기존 contract version 유지
- production dispatch/controller의 strict `0.9.0` Schema 11개 parity
- `production-dispatch`, `production-bind-task`, `production-status`, `production-advance`, `production-complete-step` CLI와 `create_asset_production_dispatch`, `bind_asset_production_task`, `get_asset_production_dispatch_status`, `advance_delegated_production_controller`, `record_delegated_production_step` MCP 표면
- `client_mediated` launch manifest의 allowlist-only controller MCP profile, forbidden approval/retry tools와 shell-denial policy
- 명시적 `desktop_in_session` launch의 무바인딩 시작, `workflow_contract_only` disclosure와 client-profile 비주장

## Gate 2 — environment probe

- 기존 Blender compatibility JSON hash 검증
- Blender version과 executable basename 추출
- missing/invalid/stale evidence를 경고 또는 실패로 구분
- repository, workspace와 외부 source absolute path 비노출
- probe ID overwrite 및 traversal 거부

## Gate 3 — workspace audit

정상 사례:

- V0.9 job
- 읽을 수 있는 compatible legacy job
- immutable source hash 일치
- 유효한 workflow latest pointer
- 유효한 optional interior QA latest/hash/source binding
- convergence가 없는 job의 `not_requested`
- current plan-only 또는 approved convergence session의 `active`
- exact plan/approval/iteration/QA/PDF chain을 가진 terminal convergence session의 `valid`
- terminal 뒤 별도 canonical revision 또는 auxiliary input 추가에도 원래 input map과 historical chain이 intact이면 `valid`
- 비어 있지 않은 exact initial input map과 신규 activation binding이 없는 legacy partial plan은 실행 가능으로 오인하지 않고 status-only warning

음성 사례:

- source hash mismatch 또는 missing source
- path/link escape
- 손상 JSON과 unknown contract version
- dangling workflow pointer
- 손상·stale interior QA contract 또는 latest pointer
- active convergence의 input, canonical SceneSpec, current QA 또는 candidates drift
- 신규 convergence의 initial SceneSpec/build/constraint snapshot 누락 또는 hash mismatch
- strict host-safety envelope 누락, Schema 불일치, plan·approval의 envelope hash mismatch 또는 public path-limit의 권한 확대
- source/result build provenance의 SceneSpec·camera binding 불일치
- source→result build에서 SceneSpec hash 외 geometry/material/shader/texture 계약 변경
- iteration 간 QA/candidate/build chain splice
- before/after constraint evidence 변조 또는 receipt regression count 위조
- terminal convergence의 원래 input hash 변경
- missing/noncontiguous receipt, previous-receipt hash 불일치 또는 orphan iteration entry
- modified selection, RevisionPlan, authorization, result SceneSpec, result QA 또는 result candidates
- terminal score/high-finding/receipt set 불일치
- terminal JSON 없이 남은 cancellation receipt, final snapshot 또는 PDF artifact
- receipt 없는 staging이 남아 있는데 취소·terminal 처리됐거나 terminal evidence와 staging이 동시에 존재함
- legacy/status-only 세션이 `execution_eligible=true`로 잘못 분류되거나 `next_action`이 승인·실행을 권고함
- convergence PDF source 누락, hash mismatch 또는 source fingerprint 불일치
- scan limit 초과
- audit output overwrite
- production launch, tool profile, task-binding receipt, advisory assignment, advance receipt chain 또는 postflight receipt 변조
- production dispatch와 bound V0.8 workflow plan/state의 stale 또는 mismatched binding
- production advance의 직전 after와 다음 before 불일치, snapshot byte 변조, sequence gap,
  previous-receipt hash 불일치, latest after와 current state 불일치 또는
  job/workflow/dispatch/controller/dispatch-plan identity 변조

모든 사례에서 canonical 파일 byte hash가 바뀌지 않아야 한다.

## Gate 3A — terminal workspace archive/restore

정상 사례:

- `completed`와 `cancelled` V0.8 workflow의 exact request/plan/state/latest binding
- immutable plan 발행 뒤 same-volume atomic directory rename
- 전체 directory/file inventory, SHA-256, byte size와 count가 plan/receipt에서 일치
- archive 중 active job loader가 fail closed하고 restore 뒤 기존 loader가 다시 성공
- archive→restore round trip에서 `job.json`, `input/`과 전체 tree digest 불변
- rename 뒤 receipt 발행 전 중단을 exact destination tree로 한 번만 crash-adopt
- 동일 plan/receipt 재호출의 idempotent 검증

음성 사례:

- `planned`, `running`, `waiting_for_agent`, `waiting_for_approval`, `blocked` 또는 workflow 없음
- `--allow-failed` 없는 failed workflow
- active local queue entry, transient `*.lock.json`, non-terminal production dispatch
- AQ/AQ v2 session이 존재하지만 전용 terminal closure가 검증되지 않은 job
- workspace/archive root 중첩, 다른 볼륨, symlink/junction/reparse tree entry
- plan 이후 source byte 추가·변경, plan/receipt digest 변조
- source와 destination 동시 존재 또는 둘 다 없음
- archive entry 수동 변경 뒤 restore/receipt replay

공개 표면은 `workspace-archive-candidates`, `workspace-archive`, `workspace-restore`,
`workspace-relocation-resume` CLI만 제공한다. Canonical job relocation은 host 관리 작업이므로
일반 MCP controller 도구 권한에는 추가하지 않는다.

## Gate 4 — queue와 복구

- existing workflow만 enqueue
- job/workflow active duplicate 거부
- `max_concurrency=1`
- agent/review/approval에서 `waiting`
- live lock 거부, expired lock archive 복구
- lease와 immutable attempt receipt
- deterministic failure 후 자동 retry 없음
- explicit `--retry-failed` token 한 번만 소비
- max attempts, queue cancellation, underlying workflow 보존

## Gate 4A — Asset Production Dispatcher와 Delegated Controller

격리 CLI smoke는 새 dispatch 생성, exact client profile binding, host 진행과 첫
read-only advisory assignment, production-aware workspace audit까지 확인한다. 아래의
controller-authored completion, receipt chain과 terminal postflight 항목은 isolated
temporary workspace 단위·통합 테스트에서 검증한다. CLI smoke가 실제 agent 산출물이나
기존 승인을 합성해 terminal 상태를 만들지는 않는다.

정상 사례:

- 새 reference·purpose·content scope로 새 V0.8 `new_asset` workflow와 dispatch bundle 생성
- `standard` 기본과 명시적 `background_exterior` 선택 유지
- launch manifest가 repository task 미생성, client-mediated 경계, 상대 경로와 exact hash 기록
- controller MCP는 정확한 allowlist만 갖고 approval/retry 도구와 동등한 shell command는 금지
- supporting-client enforcement 확인 없이는 task binding 거부
- binding receipt가 dispatch plan, launch, prompt와 controller-tool-profile SHA-256에 결속
- `desktop_in_session`은 `ready_in_session`에서 바로 현재 workflow 경계를 반환하고 external task binding을 거부
- desktop mode의 상태·prompt·Schema가 `workflow_contract_only`와 tool-profile 미강제를 일관되게 노출
- desktop mode도 exact input fingerprint, single-writer lock, 모든 V0.8 승인/failed-retry 경계를 그대로 보존
- agent 경계에서 exact read-only assignment 생성, subagent write allowlist가 비어 있음
- controller만 선언된 V0.8 agent output을 작성하고 exact input fingerprint로 완료
- 반복 no-op reconcile은 `state.json`/`latest.json` bytes와 mtime, state SHA-256,
  `updated_at`을 보존하고 실제 권위 evidence 변화에서만 새 state를 기록
- 모든 advance receipt가 전후 workflow state bytes와 previous receipt SHA-256에 결속되고,
  직전 after SHA-256이 다음 before SHA-256과 같으며 마지막 after가 현재 state와 일치
- public AQ v2 reference action → V0.9 geometry assignment → desktop ControllerExecutor
  waiting/adoption → AQ `validate_candidate` 경로가 production anchor 우회 없이 통과
- completed workflow에서 atomic read-only V0.9 postflight receipt 생성
- postflight warning은 보존하고 failure는 production acceptance 차단
- 명시적 `standard + bounded_after_v06` dispatch가 최초 workflow를 V0.6
  `preview_only`에서 완료하고 exact convergence plan/binding을 한 번만 생성
- Controller가 `visual_convergence_plan` exact SHA-256 승인에서 멈추며 그 승인을
  생성·추론하지 않음
- 외부 exact 승인 뒤 Controller advance 한 번당 full Blender convergence iteration을
  최대 한 번만 실행 또는 복구
- authored `spatial_v1` iteration은 fresh initial/result five-view 구조 비교를 결속하고,
  구조 비회귀는 유지하며 regression은 canonical rollback 후 terminal 처리
- convergence terminal JSON/PDF와 immutable session directory가 postflight receipt에
  exact hash로 결속되고, V0.7 package는 별도 새 workflow로 남음

승인·안전 경계:

- generic approval, InteriorScope, interior QA, candidate-review decision, guarded/convergence, V0.7 optimization과 Destination Handoff exact approval을 합성하지 않음
- failed host step을 `production-advance`가 재시도하지 않음
- `background_exterior` dispatch가 initial Destination Handoff를 포함하지 않음
- `background_exterior + bounded_after_v06`와 bounded convergence + initial handoff 거부
- subagent는 advisory output만 반환하며 controller-only writer contract를 바꾸지 않음

음성 사례:

- false client enforcement attestation, stale launch/profile/prompt 또는 reused binding
- changed dispatch/workflow plan, assignment input, receipt bytes 또는 receipt-chain splice
- task/controller identity mismatch와 live controller lock 충돌
- execution-mode 불일치, desktop dispatch의 위조 task binding, client dispatch의 binding 누락
- unenforced client를 verified sandbox로 잘못 주장함
- missing/wrong convergence-plan approval, convergence binding/plan/terminal evidence tampering
- spatial five-view evidence 생성 실패 또는 result 구조 regression을 quality pass로 오인

모든 사례에서 source input, canonical SceneSpec, geometry, material, authoring `.blend`와 기존
approval evidence는 test fixture가 명시적으로 authoring하는 현재 step 외에는 바뀌지 않아야
한다. Supporting client의 실제 task 생성과 OS-level tool/shell sandbox는 별도 client
integration evidence가 없으면 `contract_verified` 이상으로 주장하지 않는다.

## Gate 5 — Codex Destination Handoff

정상 사례:

- `portable_gltf` 또는 `fbx_interchange` package와 matching `passed` round trip
- exact plan SHA-256으로 single-use handoff 생성
- source package의 byte-for-byte copy와 생성 전후 package snapshot 동일
- package manifest, primary model, texture, semantic/material, assembly와 prompt hash 결속
- LOD/Collider, pivot, transform, hierarchy와 raw PBR 의미 기록
- glTF ORM `R=occlusion`, `G=roughness`, `B=metallic` 기록
- 모든 envelope path가 relative POSIX path이고 모든 파일에 SHA-256 receipt 존재
- 목적지 import plan/receipt/validation schema와 safe prompt 포함
- handoff PDF와 sidecar가 exact JSON source hash에 결속

음성 사례:

- failed, missing 또는 stale round trip
- package receipt mismatch, missing/untracked dependency 또는 source package 변경
- OBJ profile
- absolute/traversal path 또는 link-like package entry
- reused handoff/plan ID와 stale plan hash
- prompt 안전 규칙 또는 필수 placeholder 누락

모든 사례에서 canonical SceneSpec, geometry, authoring `.blend`, source texture와 원본 V0.7 package hash가 바뀌지 않아야 한다.

## Gate 6 — PDF 보고서

- exact probe/audit strict-load
- PDF SHA-256과 source fingerprint sidecar
- source별 relative path, SHA-256와 byte size
- absolute path 비노출
- same report ID overwrite 거부
- 2페이지 이상, 텍스트 추출 가능
- representative page PNG render와 육안 clipping/overlap/한글 검사

Export/full PDF는 newest valid handoff를 선택된 package에 결속해 표시하고, stability PDF는 audit의 handoff count/valid count와 convergence session count/valid count를 표시한다. Handoff와 convergence PDF도 machine JSON의 파생 보고서이며 판단 입력으로 다시 읽지 않는다.

## Gate 6A — External Static Asset Intake

Host 계약:

- 새 job과 `.blend`/`.fbx`/`.glb` source만 허용하고 `.gltf`와 기존 job은 거부
- source/dependency exact copy와 SHA-256, plan candidate, material/shader mapping 검증
- exact intake-plan hash approval의 single-use 소비
- source, candidate, normalized blend와 receipt 변조를 fail-closed 탐지
- SceneSpec을 생성하지 않고 `source_kind=external_static_asset` provenance 사용
- legacy SceneSpec `SourceProvenance` fixture는 계속 로딩
- V0.9 audit가 current intake를 통과시키고 stale/tampered intake를 실패 처리

Blender 5.0.1 opt-in smoke:

- auto-execution disabled 상태로 직접 만든 `.blend` fixture 검사
- source `scale_length=0.01`을 meter authoring derivative로 정규화
- multi-material mesh를 stable single-material semantic submesh로 분리
- text/action/armature 제거와 one-scene sanitization evidence
- material identity, hierarchy와 UV 보존
- V0.7 `portable_gltf` optimization, portable PBR conversion, package 생성
- clean-import round trip의 semantic/material coverage `1.0 / 1.0`

Handoff와 audit 회귀:

- 외부 source hierarchy/material mapping을 assembly/material handoff에 투영
- external manifest, normalization receipt와 validation을 package metadata로 snapshot
- Windows 260자를 넘는 schema/receipt 경로도 읽되 containment/link/hash 검증 유지
- 원본 source, normalized authoring blend와 package가 후속 audit/handoff에서 변경되지 않음

## Gate 7 — V0.8/V0.7 회귀와 Blender

- 전체 `pytest`, Ruff, doctor
- 실제 Blender compatibility probe
- V0.8 isolated workflow regression
- V0.8 optional `destination.handoff` step이 exact package approval 뒤에 위치하고 output completion marker가 hash-bound인지 확인
- V0.9 production dispatcher/controller가 기존 V0.8 approval과 V0.7/V0.9 handoff 경계를 보존하고 final postflight audit에서만 완료되는지 확인
- V0.6 manual one-shot revision 기본 경로와 optional exact-plan bounded convergence 공개 표면·job-lock·strict path-limit narrowing 회귀
- 한 host/MCP 호출당 full Blender iteration 최대 1회, receipt 없는 staging 복구 후에만 취소·terminalization, terminal+staging audit failure 회귀
- `background_exterior`가 계속 canonical QA 1회, generated target 없음, post-QA automatic revision 없음으로 종료되는지 확인
- V0.7 portable asset 회귀와 실제 GLB package clean-import를 격리 smoke workspace에서 실행
- EEVEE feature probe, AgX, `stdin=DEVNULL`, `--python-exit-code 1`
- compatibility smoke export의 GLB/FBX/OBJ

## 실행 명령

```powershell
uv run pytest
uv run ruff check .
uv run cbm doctor
uv run cbm blender-compat
.\scripts\run_v09_gates.ps1
```

V0.9 gate의 smoke workspace는 `reports/v09_smoke/<run-id>/workspaces/`다. 기존 사용자 job을 변경해서 gate를 통과시키지 않는다. Gate는 source package manifest hash를 handoff 생성 전후 비교하고 audit에서 handoff `1/1 valid`를 요구한다.

## 지원 매트릭스 판정

각 조합은 다음 셋 중 하나로만 기록한다.

- `verified`: 실제 전체 관련 gate 통과
- `partially_verified`: contract/fallback만 검사하거나 일부 gate만 통과
- `unverified`: 실기동 증거 없음

감지됐거나 코드 fallback이 있다는 이유로 `verified`로 올리지 않는다. Codex Destination Handoff 검증은 목적지 import 계획에 필요한 계약과 prompt의 안전성을 뜻하며 Unity, Unreal, custom engine의 자동 adapter 또는 runtime parity 검증을 뜻하지 않는다.
