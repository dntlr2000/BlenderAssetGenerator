# Autonomous Quality 0.2 검증 기록

## 1. 판정 시점과 범위

- 재확인 날짜: `2026-08-11`
- 프로젝트 버전: `0.9.0`
- canonical SceneSpec: `0.2.0`
- AQ v2 contract: `0.2.0`
- profile: `autonomous_static_prop_v2`
- profile 상태: **`disabled_experimental`**
- Blender: `5.0.1`
- Blender bundled Python: `3.11.13`

이 문서의 2~9절은 2026-08-11 shared-tree snapshot에서 실제로 실행한 host, Blender와 legacy gate
결과를 보존한다. 2026-08-13 additive Codex ImageGen Material Loop 후속 경계는 10A절에 분리한다.
기존 사용자 workspace, package, canonical evidence와 workflow receipt는 수정하지 않았다. 아래
synthetic fixture의 성공은 임의 reference 자산의 품질 향상, 사람의 승인, GitHub Actions 실행,
Unity/Unreal import 또는 runtime parity를 증명하지 않는다.

판정 언어:

- `passed`: 아래 명령이 exit code 0으로 끝나고 해당 gate의 machine evidence가 생성됨
- `skipped`: opt-in이 아니거나 해당 fixture에 적용되지 않아 실행되지 않음
- `unverified`: 필요한 실기동 또는 외부 evidence를 이번 검증에서 만들지 않음
- `disabled_experimental`: 구현과 일부 실기동 검증이 있어도 production profile로 활성화하지 않은 상태

## 2. 현재 구현 snapshot

| 영역 | 실행한 검증 | 현재 판정 |
|---|---|---|
| AQ v2 plan/state/advance/run/cancel | focused 및 full pytest | host passed; profile disabled |
| geometry controller candidate | host 음성 gate + Blender V03 vertical-loft build/promotion | synthetic fixture passed |
| material controller candidate | strict graph/plan 검증, canonical promotion, rebuild/inspect/validate | focused gate passed |
| Integrated Quality 0.2 | exact global/semantic PNG host 재계산, metric/ranking/terminal 검증 | host passed; 실제 reference 일반 품질 향상은 미검증 |
| MaterialGraphRuntime | 20-template strict/negative host gate + Blender compile/reopen/inventory | synthetic fixture passed |
| MaterialAuthoring 0.1 | host/schema + fixed family Blender smoke | synthetic fixture passed; canonical neutral/reference preview는 별도 상태 |
| ControllerExecutor | execution-owned 격리, full-lifecycle exact adoption, tamper/crash/auth/timeout | host passed; Desktop는 adopt-only, App Server 미검증 |
| state-chain validation | initial/transition/input/source/producer/provenance delta/budget reconstruction | host passed |
| quality terminal | hard-finding gate binding; passed freeze; needs_revision/unscorable bundle; blocked는 둘 다 없음 | host passed |
| DeliveryProfile 0.1 | host review-only terminal + 독립 GLB/FBX production/roundtrip | review-only host passed; dual delivery synthetic Blender passed |
| v02 benchmark | 10 host case + 선언된 2 Blender case | `10/10`, Blender `2/2`; `human_review=not_reviewed` |
| legacy V0.7/V0.8/V0.9 | 각 root smoke | passed |

현재 supervisor가 검증한 실제 상태 흐름은 다음과 같다.

```text
geometry controller output
→ strict geometry validation/promotion
→ material controller output
→ strict material validation/promotion
→ caller-supplied Integrated Quality 0.2 report
→ quality terminal
→ delivery review/approval boundary
→ delivery executor
→ nested delivery terminal validation
```

Supervisor가 IQ report를 임의로 합성하거나 사용자 대신 V0.7 승인을 만들지는 않는다.

P0 후속 검증은 다음 fail-closed 경계를 추가로 확인했다.

- waiting no-output 재호출은 같은 request/execution을 유지하고 state/budget을 소비하지 않음
- waiting 중 protected canonical source mutation은 adoption 전에 거부
- state chain의 phase splice, provenance 교체와 budget rollback 거부
- global/semantic PNG bytes에서 metric·gate·finding·reentry·outcome을 host가 재계산하고 forged score 거부
- typed raw receipt 없는 required scored landmark/multi-view는 pass authority 없이 fail-closed
- authoritative IQ hard finding은 exact failed required gate에 결속
- passed IQ는 current canonical authoring source와 필수 `geometry_candidate_validation_receipt` 및
  `material_phase_receipt`에 결속
- DeliveryTerminal 검증이 nested full QualityTerminal validator를 호출해 forged approval terminal 거부
- execution/adoption result 복구는 full executor lifecycle과 exact stored bytes를 재검증
- direct side effect는 active·미만료 RootAuthorization과 exact plan/profile/budget을 재검증하며,
  AQ v2 timeout은 nonretryable failed terminal로 끝남

## 3. focused AQ 0.2 host gate

실행 표면:

```powershell
$aqGateRoot = Join-Path $env:TEMP "aqg-final-v02-p0-20260811"
.\scripts\run_autonomous_quality_gates.ps1 `
  -OutputRoot $aqGateRoot `
  -RunBlender `
  -SkipFullRegression `
  -SkipLegacyGates
```

위 명령은 원 실행의 temp leaf를 유지한 설치 위치 독립 재현형이다. 영구 검증 근거는 해당
machine-local temp root가 아니라 아래 repository-relative evidence root다.

host-focused 결과:

```text
397 passed, 17 skipped, 8 warnings
exit code: 0
```

실제 Blender 묶음 결과:

```text
30 passed, 6 warnings
exit code: 0
```

evidence root:

```text
verification/evidence/aq_v2_20260811
```

17 host skip은 opt-in Blender node 또는 조건부 fixture다. 별도의 `-RunBlender` 묶음에서 Blender
node 30개가 실행되어 통과했지만, host skip 자체를 pass로 재분류하지 않는다.

## 4. 전체 Python 회귀와 정적 검사

실행 명령과 결과:

```powershell
$fullBasetemp = Join-Path $env:TEMP "cbm-aqv2-full-final-20260811"
uv run --no-cache pytest -q "--basetemp=$fullBasetemp"
```

```text
1350 passed, 39 skipped, 8 warnings
exit code: 0
```

```powershell
uv run ruff check .
```

```text
All checks passed!
exit code: 0
```

39 skip은 선택적 Blender/환경 fixture이며 전체 Python 회귀의 실패는 아니다. 동시에 모든 선택적
실기동이 수행됐다는 뜻도 아니다.

## 5. 환경과 instruction 검증

실행 명령:

```powershell
uv run cbm doctor
uv run cbm blender-compat
uv run python scripts/check_agent_instructions.py
```

결과:

- `doctor`: passed
- `blender-compat`: Blender `5.0.1`, Python `3.11.13`, passed
- instruction hierarchy: root `7,764 bytes`, AGENTS `11`개, 최대 root+leaf `8,603 bytes`,
  legacy invariant `192`개와 digest
  `d6d4a5b6c982c601f20bb95969e340d75e78a33e478fac26454e3281c167a865` 검사 passed

instruction checker 통과는 현재 repository 규칙의 정적 일관성을 증명한다. 실제 Codex supporting
client가 phase allowlist와 OS sandbox를 집행했다는 runtime attestation은 아니다.

## 6. AQ v02 benchmark

host-only와 Blender opt-in을 각각 새 output에 실행했다.

```powershell
uv run python -m codex_blender_modeler.autonomy_benchmarks.v02_cli `
  --manifest examples/autonomous_quality_benchmarks_v02/manifest.json `
  --output <NEW_REPORT>

uv run python -m codex_blender_modeler.autonomy_benchmarks.v02_cli `
  --manifest examples/autonomous_quality_benchmarks_v02/manifest.json `
  --output <NEW_BLENDER_REPORT> `
  --run-blender
```

결과:

- synthetic host case: `10/10 passed`
- manifest가 opt-in을 허용한 Blender case: `2/2 passed`
- external download: 사용하지 않음
- `human_review_status=not_reviewed`
- benchmark package/roundtrip: `not_run`
- report SHA-256: `7bf51bfb1a16a94537e2cb7db44602df1a82332779e0a91c1581fd53f715b271`
- manifest SHA-256: `76a6b313d8762546a468ff4524763f042ad4cebfac132656efa1e5dab6c0e1a2`

이 결과는 deterministic metric 방향성과 두 fixed Blender probe를 증명한다. 사람이 reference
contact sheet를 승인했다거나 GLB/FBX delivery가 benchmark 안에서 수행됐다는 뜻은 아니다.

## 7. dual GLB+FBX와 review-only 검증

`tests/test_aq_v02_delivery_executor_blender.py`가 하나의 exact quality freeze에서 두 format을
독립적으로 실행했다.

- GLB와 FBX가 서로를 변환 source로 사용하지 않음
- format별 V0.7 review, optimization run, package ID와 clean-import evidence 분리
- canonical source/freeze 불변
- geometry intent와 material loss/survival evidence 재검증
- completed chain의 crash adoption과 nested terminal validation
- forged `quality_approved` terminal은 nested QualityTerminal 재검증에서 거부

`review_only`의 package·handoff 없는 종결은 별도의 host supervisor test에서 검증했다. 이를
Blender dual-delivery fixture가 검증한 것으로 합쳐 기록하지 않는다.

테스트는 exact `approved_by=user` fixture를 입력으로 사용했지만, 이는 승인 검증 로직을 시험하는
synthetic artifact다. 실제 사람이 대화형으로 특정 production plan hash를 승인했다는 증거로
인용할 수 없다.

## 8. legacy V0.7~V0.9 회귀

각 root smoke는 새 격리 evidence root에서 통과했다.

| gate | 결과 | evidence root |
|---|---|---|
| V0.7 | passed | `verification/evidence/v07_20260811/` |
| V0.8 | passed | `verification/evidence/v08_20260811/` |
| V0.9 | passed | `verification/evidence/v09_20260811/` |

이 결과는 기존 V0.7 package, V0.8 workflow와 V0.9 production/handoff smoke가 이번 변경과 함께
동작했음을 보여준다. 기존 evidence를 v2로 migration하거나 의미를 바꾼 것은 아니다.

## 9. CLI/MCP 공개 표면

확인된 AQ v2 CLI:

- `autonomy-v2-profile-status`
- `autonomy-v2-delivery-profiles`
- `autonomy-v2-plan`
- `autonomy-v2-status`
- `autonomy-v2-advance`
- `autonomy-v2-run`
- `autonomy-v2-cancel`
- `controller-executor-status`

대응 MCP에는 `advance_autonomous_quality_v2`와 `run_autonomous_quality_v2`가 project allowlist에
포함된다. `advance`는 한 bounded action, `run`은 예산 안의 여러 bounded action을 수행하며
controller output, caller-supplied IQ와 specialized approval이 없으면 해당 경계에서 정지한다.

## 10. 남은 미검증 경계

다음은 이번 통과 결과가 증명하지 않는다.

- Codex Desktop가 별도 task를 생성해 controller output을 생산하는 repository-side 기능
- supporting-client가 실제 OS/container sandbox와 phase tool allowlist를 집행했다는 attestation
- optional Codex App Server 공식 interface의 실제 탐지·호출·복구
- 임의 사용자 reference에서의 일반 품질 향상 또는 human art approval
- canonical MaterialAuthoring master/neutral/reference preview의 전체 lifecycle
- typed raw landmark/multi-view receipt 기반 authoritative quality pass
- expanded MaterialGraph whitelist가 arbitrary graph 또는 일반 shader 품질을 보장한다는 주장
- 실제 사용자가 수행한 production V0.7 plan-hash 승인
- Unity/Unreal/custom destination import와 runtime material parity
- GitHub-hosted `python-ci.yml` 또는 self-hosted `blender-smoke.yml`의 원격 run

`desktop_in_session`은 현재 task가 허용 output을 제공했을 때 exact 검증 후 **채택**하는 모드다.
repository가 Codex Desktop task를 스스로 생성하거나 App Server를 호출한다는 뜻이 아니다.

## 10A. 2026-08-13 Codex ImageGen Material Loop 후속

base AQ v2의 의미를 바꾸지 않는 additive companion이 다음 경계를 연결한다.

```text
ImageGen/semantic/MaterialAuthoring staging closure
→ exact_adoption이면 isolated actual Blender shadow preflight
→ exact material ControllerExecutionRequest/Result
→ existing host material promotion
→ actual MaterialPhaseReceiptV2 + fixed preview
→ base AQ resume + IQ 0.2 terminal
```

shadow preflight는 기존 V0.5 staging-only/compile `not_run` receipt를 고치지 않고 exact candidate
bytes만 별도 compile한다. ControllerResult, canonical material 또는 destination write를 만들지 않으며,
다중 후보 selection receipt와 native provenance는 bridge/controller/promotion chain에서 계속 exact하게
결속되어야 한다. native-derived selection은 `CodexImageNativeCorePreparationReceipt`가
adoption/normalization부터 core completion/candidate/quality/selection까지 exact byte identity를
보존한다.

fake `wood`, `signage_decal`, `emissive`, `crystal` fixture는 actual Blender 5.0.1 host material/IQ
mechanism을 실행한다. historical actual built-in PNG는 fresh invocation이 아니라 새 unique native
run에 재사용했고, current-task non-human semantic review가 `review_required`여서 promotion 전에
멈췄다. 두 범위를 합치지 않는다.

delivery fixture는 user approval을 합성하지 않는다. V0.7 review 뒤
`waiting_for_v07_approval`에서 멈추고 production package 호출이 거부되는지 확인한다. 별도 raw
GLB/FBX clean import는 mechanism evidence이며 accepted package/completed terminal이 아니다. 최종
Material Loop 명령, 실행 합계, evidence root와 명시적 `not_run` 경계는
`VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md`를 따른다. 사용자가 current task에 붙여 넣는 안전한
시작·상태·resume 요청은 `IMAGEGEN_MATERIAL_LOOP_PROMPTS_KO.md`에 고정한다.

Material Loop 추가는 2026-08-11 AQ v2 결과를 고쳐 쓰거나 profile을 활성화하지 않는다. human
review와 destination runtime parity도 수행하지 않았다.

## 11. 최종 판정

AQ 0.2의 host 계약, 실제 Blender synthetic geometry/material probe, geometry→material→caller-supplied
IQ→quality terminal→delivery supervisor 흐름, 독립 GLB+FBX clean import와 V0.7~V0.9 회귀는 이번
검증에서 통과했다. benchmark도 host `10/10`, Blender `2/2`를 통과했다.

그러나 human review는 `not_reviewed`이고 Desktop controller는 adopt-only이며 optional App Server와
supporting-client sandbox는 검증되지 않았다. 따라서 `autonomous_static_prop_v2`의 올바른 상태는
계속 **`disabled_experimental`**이다. 기존 `autonomous_static_prop_v1`, `standard`,
`background_exterior`, SceneSpec `0.2.0`과 specialized approval 의미는 변하지 않는다.

2026-08-13 Material Loop 후속도 같은 결론을 바꾸지 않는다. companion profile
`autonomous_static_prop_v2_codex_imagegen` 역시 `disabled_experimental`이며 actual user approval,
production package 또는 destination parity를 주장하지 않는다.

## 12. 2026-08-14 Material Closure 후속 경계

Material Closure Stabilization `0.1.0`은 AQ v2 material path에 additive하게 구현됐다.
기존 2026-08-11/13 결과를 소급 변경하지 않으며, 이 문서의 기존 AQ v2 통과 count가 closure,
preapproval shadow compile, single-use appearance approval 또는 current Crystalgun repair를 검증한
것은 아니다.

Crystalgun의 verified raw head는 `0012 / terminal / cancelled / none`이다. canonical MaterialPlan,
real `MaterialPhaseReceiptV2`, rendered neutral material preview와 IQ 진입 evidence가 없고 사용자
appearance approval도 없다. Append-only supersession 뒤 새 repair dry-run은 dependency closure를
게시했지만 surface-detail coverage 검사에서 Blender/preview/approval/controller 전에
`preflight_failed`로 멈췄다. 따라서 old retry 실행, actual repair promotion, IQ와 package는
`not_run`이다. Recorded focused 138 passed/1 skipped, later expanded host 165 passed/4 skipped와
actual Blender 5.0.1 preapproval fixture 1 passed를
포함한 신규 결과와 남은 미검증 항목은
[Material Closure 검증 기록](VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)에만 추가한다.

이 후속 작업으로도 두 experimental profile의 판정은 계속 `disabled_experimental`이다.
