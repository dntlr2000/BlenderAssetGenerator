# AQ Approval Envelope 0.3 검증 기록

## 1. 구현 전 기준선

- 기준 날짜: `2026-08-15 KST`
- branch: `main`
- 시작 worktree: clean
- project: `0.9.0`
- canonical SceneSpec: `0.2.0`
- AQ v2/IQ: `0.2.0`
- Blender: `5.0.1`
- profile 상태: `autonomous_static_prop_v2`, `autonomous_static_prop_v2_codex_imagegen`
  모두 `disabled_experimental`

| 기준선 gate | 실제 결과 |
|---|---|
| `uv sync --frozen --extra dev --extra vision` | passed |
| full pytest, repository-local short basetemp | `1808 passed, 63 skipped, 1 failed, 8 warnings` |
| full pytest 유일 실패 | `test_multiview_job_outside_repo`; mandatory repo-local basetemp가 test의 outside-repo 전제를 충족하지 않음 |
| Ruff | passed |
| doctor | Repository/Workspace/Blender/Codex OK |
| Blender compatibility | Blender 5.0.1/Python 3.11.13/EEVEE, GLB/FBX/OBJ passed |
| instruction checker | passed; root 8,013 bytes, AGENTS 17, invariants 192 |
| AQ v2 focused | `189 passed, 5 skipped` |
| Material Closure focused | `135 passed, 1 skipped` |
| Material Identity Split focused | `53 passed, 1 skipped` |
| ImageGen Material Loop focused | `220 passed, 5 skipped` |
| actual Blender opt-in baseline bundle | `35 passed, 1 skipped, 10 failed` |

actual Blender baseline 실패는 구현 전 상태로 분리한다.

- structural geometry 1건: legacy custom-mesh loop UV fixture가 explicit
  `standard_custom_mesh payload_kind`를 제공하지 않음
- ImageGen material loop/delivery 9건: `MaterialClosurePromotionBoundaryV2` detection이 Material Loop
  assignment의 `canonical_write_authority=material_phase_service_only`를 closure boundary로 잘못
  분류함

이 기준선 실패를 신규 기능의 post-change 실패나 통과로 재분류하지 않는다.

## 2. 구현 전 코드 사실 확인

| 항목 | 판정 |
|---|---|
| AQ v1 routine policy authorization | verified in current code |
| RootAuthorizationV2에 approval mode/envelope 없음 | verified |
| AQ v2가 controller/IQ/specialized/V0.7 경계에서 정지 | verified |
| Material Closure approval-before-preflight 차단 | verified |
| Identity Split explicit specialized approval | verified |
| v2/ImageGen profile disabled | verified |
| repository task spawn 없음 | verified |
| desktop_in_session current-task adopt model | verified |
| Standard/Background/AQ v1 보존 필요 | normative |

## 3. 구현 후 계약·정책 검증

- 검증 날짜: `2026-08-16 KST`
- `uv sync --frozen --extra dev --extra vision`: passed, 51 packages 확인
- Approval Envelope/One-Prompt contract, schema, KPI, public surface, framework literal focused:
  `25 passed`
- 최종 AQ/Closure/Identity Split/ImageGen/공개 표면 focused gate:
  `845 passed, 26 skipped, 8 warnings`, exit code 0
- Material Closure focused: `136 passed, 1 skipped`
- Material Identity Split focused: `54 passed, 1 skipped`
- 선택한 ImageGen Material Loop focused 9개 파일: `114 passed, 4 skipped`
- Ruff: exit code 0, `All checks passed`
- instruction checker: passed; root 9,057 bytes, AGENTS 17, invariants 192
- `cbm doctor`: Repository/Workspace/Blender/Codex OK
- `cbm blender-compat`: Blender `5.0.1`, Python `3.11.13`, EEVEE, GLB/FBX/OBJ passed
- `git diff --check`: passed
- repository summary generator: `OK: repository catalog and generated projections are current`

다음 구현 항목은 위 focused test와 strict schema parity test로 검증했다.

- Approval Envelope/Policy Profile/Budget strict contract와 Draft 2020-12 schema
- 13개 routine gate registry, host eligibility, single-use policy authorization/decision receipt
- 모든 technical failure category의 user-approval factory 거부
- explicit user authority와 policy authority가 분리된 identity-split/material/delivery adapter
- consolidated escalation과 decision budget
- one-prompt plan/run/status/resume/cancel, `waiting_for_controller`, same-session resume와 background
  execution claim 금지
- telemetry replay와 6개 대표 asset/7개 run KPI manifest
- CLI/MCP/config/catalog 공개 표면 parity
- envelope 없는 legacy session의 무변경 read와 interactive fallback

## 4. full regression 판정

최종 repository-local basetemp 전체 회귀는 다음과 같이 통과했다.

```text
1839 passed, 63 skipped, 8 warnings in 249.01s
exit code 0
```

최종 통과 전 두 전체 실행에서는 각각 다음 Windows host failure가 관찰됐다.

- `1835 passed, 63 skipped, 1 failed`: V0.7.2 fixture의 `create_job()` 디렉터리
  `os.replace`가 `PermissionError`를 반환했고 exact node 격리 재실행은 `1 passed`였다.
- `1834 passed, 63 skipped, 2 failed`: QA multi-view와 V0.9 audit fixture에서 같은
  `create_job()` `PermissionError`가 재현됐다. 앞 실행에서 실패한 V0.7.2 node는 이 실행에서
  통과했다.

서로 다른 세 generic fixture에서 같은 atomic workspace publication 실패가 재현되어
`FrameworkChangeJustification` 기준상 `reusable_missing_capability`로 분류했다. public contract,
schema 또는 approval type은 추가하지 않았다. `workspace.create_job()`의 private staging→final
directory publication만 0.05초/0.15초의 최대 두 번 재시도를 허용한다. source staging이 사라지거나
destination이 나타나거나 세 번째 시도도 실패하면 원래 `PermissionError`를 유지하고 fail-closed한다.

관련 focused 검증은 다음을 포함해 `11 passed`였다.

- 첫 publication denial 뒤 exact staging bytes로 성공
- persistent denial의 총 세 번 시도 제한, final job 미생성, private staging 정리
- QA multi-view, V0.7.2 Interior Scope, V0.9 audit 재현 node
- repository-local basetemp 안에서 logical external repository boundary를 주입한 workspace test

보존 중인 `.codex_test` fixture가 전역 Ruff 대상에 포함된 gate 실패도 한 번 관찰됐다. 중간 산출물은
삭제하지 않고 `.t`, `.codex_test`, `.codex_tmp`를 Git/Ruff source scan에서 제외했다. 이후 전체 Ruff와
AQ focused gate가 exit code 0으로 통과했다.

## 5. 실제 Blender 5.0.1 판정

- 전체 opt-in Blender 묶음: `45 passed, 1 skipped, 6 warnings in 826.54s`, exit code 0.
- supported executable `Blender 5.0.1`을 실제 실행했으며 구조 형상, AQ 후보, material graph,
  material authoring, ImageGen material loop/delivery, Material Closure preflight와 Material Identity
  Split shadow-build 경계를 포함했다.
- 구현 전 실패 10건은 legacy `loop_uvs: null` 호환, Closure boundary marker의 exact 분류,
  ImageGen neutral-preview의 job-local short staging과 exact long-path adoption으로 해소됐다.
- Closure와 Identity Split 경로는 실제 Blender 실행 뒤 canonical apply 전 해당 승인/권한 경계에서
  정지했다.
- 최종 `cbm blender-compat`는 Blender `5.0.1`, Python `3.11.13`, EEVEE와 GLB/FBX/OBJ smoke
  export를 모두 통과했다.

전체 opt-in bundle은 verified다. 다만 이는 repository fixture 기반 Blender 검증이며 실제 사용자
reference에서 One-Prompt geometry→material→IQ→GLB/FBX를 완주한 실행은 아니다.

## 6. 대표 KPI와 historical evidence

`benchmarks/aq_approval_kpi/representative_asset_runs.json`은 6개 대표 contract asset과 autonomous
6회/checkpointed 1회의 총 7개 run을 검증한다. autonomous run은 additional decision 0, technical
approval 0, safe production/review terminal, corruption 0이며 checkpointed run은 additional decision
3 이하, technical approval 0이다. 이 manifest는 실제 자산/실제 Blender/human review/activation
evidence가 아님을 필드로 고정한다.

Crystalgun historical analysis는 append-only read-only report로 생성했다.

```text
job: item_crystalgun_full_0
session: aqv2-20260813t050847825044z-1232d4a0
path: production/autonomy_v2/aqv2-20260813t050847825044z-1232d4a0/
      historical_analysis/historical-eligibility-c7cbbb8460f718843d8c51d4.json
sha256: 6f70568bbeefe94048fee60bdbdf205e444f186276d66cf03d418b1d690fbb37
```

미래 bounded identity-split 조건은 통과하고 추가 사용자 결정은 필요하지 않았을 것으로 평가됐지만,
historical envelope/retroactive authority/approval reclassification/canonical apply는 모두 false다.

## 7. 계속 unverified인 항목

- 실제 reference에서 geometry→material→IQ→GLB/FBX까지 완주한 One-Prompt E2E
- 실제 자산 5개 이상의 approval-minimization KPI와 human review
- 실제 Codex built-in ImageGen invocation과 actual-source material loop
- 앱 종료 뒤 background execution. 구현은 이를 제공하거나 주장하지 않는다.
- Unity/Unreal runtime parity와 destination project write
- profile activation review

## 8. 주장 제한

contract/host fixture 통과를 실제 사용자 품질 검증으로 표현하지 않는다. representative fixture의
추가 결정 0은 policy mechanism KPI이며 arbitrary reference의 예술적 완성도나 production activation
증거가 아니다. 실제 Codex built-in ImageGen invocation, human review, Unity/Unreal runtime parity와
앱 종료 후 background execution은 별도 evidence 없이는 `unverified`다.
