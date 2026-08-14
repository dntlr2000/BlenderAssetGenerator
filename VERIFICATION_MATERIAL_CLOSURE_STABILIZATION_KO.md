# AQ v2 Material Closure Stabilization 0.1.0 검증 기록

> 기준 시각: 2026-08-14 KST. 이 문서는 실제 실행 결과와 immutable evidence가 확인된
> 범위만 기록한다. 구현 존재, fixture 성공, historical source 재사용과 actual production
> promotion은 서로 다른 판정이다.

## 1. 구현 전 baseline

| 검사 | 실제 결과 |
|---|---|
| `uv sync --frozen --extra dev --extra vision` | passed |
| 최초 전체 pytest | workspace archive 순환 import로 collection error |
| 최소 lazy-import 호환 수정 뒤 collect-only | 1,658 tests collected |
| 최소 수정 뒤 전체 pytest | 1,600 passed, 58 skipped, 8 warnings |
| `uv run ruff check .` | passed |
| `uv run cbm doctor` | passed |
| `uv run cbm blender-compat` | passed, Blender 5.0.1 / GLB+FBX+OBJ smoke |
| agent instruction checker | passed, 12 instruction files / 192 invariants |
| schema generator `--check` | passed |
| repository summary `--check` | 당시 pre-existing `REPOSITORY_TREE.txt`/`FILE_MANIFEST.sha256` drift |

순환 import 수정은 archive validator의 production service import를 실행 시점으로 옮겼으며
contract나 archive 의미를 변경하지 않았다. 위 전체 pytest는 Material Closure 구현 전
baseline이므로 신규 기능의 최종 full-regression 결과가 아니다.

## 2. Material Closure focused 검증

| 영역 | 실제 결과 | 판정 범위 |
|---|---|---|
| recorded focused aggregate | 138 passed, 1 skipped, 9.57s | contracts, service, AQ integration, schema, controller repair, incident, public surface, retry supersession, literal gate, CI wiring |
| generic JSON LF/hash regression | 38 passed | Windows에서도 atomic JSON이 LF bytes와 exact hash를 보존 |
| public surface | CLI 12 / MCP 12 focused checks passed | surface 등록·schema/capability 동등성의 host test 범위 |
| no-job-specific-literal gate | passed | executable source/schema/common prompt 대상 |
| source/scripts/tests Ruff | passed | 구현과 관련 gate 범위 |
| schema generator `--check` | passed | 신규 strict schema projection 포함 |
| agent instruction checker | passed, 16 instruction files / 192 invariants | 신규 leaf instruction 포함 |

중간 focused 실행의 125/1 및 87/1은 기록된 138/1에 대체됐으며 합산하지 않는다. 이후 P1
보강을 포함한 확대 host 선택은 165 passed, 4 skipped였고, 최종 authoritative 전체 회귀는
`1750 passed, 62 skipped, 8 warnings in 276.29s`로 통과했다.

## 3. actual Blender 5.0.1 승인 전 경계

실행 node:

```text
tests/test_material_closure_service.py::test_complete_preflight_runs_actual_blender_5_and_stops_before_approval
```

최종 재실행 결과는 `1 passed in 13.76s`다. supported Blender 5.0.1로 full
closure/preflight/shadow scene과
neutral PNG를 실제 생성·검증했다. 실행 전후 canonical SceneSpec, ModelingPlan과 Blend는
동일했고 canonical MaterialPlan은 계속 absent였다.

이 gate의 권위 경계는 다음과 같다.

- appearance approval: 0
- approval consumption: 0
- controller invocation: 0
- promotion/rollback/`MaterialPhaseReceiptV2`: 0
- IQ/destination/package: 0

따라서 이는 approval-before-controller 메커니즘의 actual Blender 증거이지, 사람 승인,
production material promotion, material quality 또는 delivery 증거가 아니다.

## 4. Crystalgun append-only recovery 결과

historical AQ head는 `states/0012.json`, `terminal / cancelled / none`으로 유지됐다. old AQ
session을 resume하거나 state를 append하지 않았다. discrepancy/failure, approved MCD retry
supersession, MGB approval-absence/supersession과 세 session supersession이 별도 immutable
evidence로 게시됐다.

두 job-specific executable recovery source는 exact bytes를 job-local history에 먼저 보존하고
inventory를 게시한 뒤 공통 source tree에서 제거했다.

| artifact | bytes | SHA-256 |
|---|---:|---|
| source inventory | 2,837 | `5a8ef7715a8a0935fc67505d1778e59894386aa7ebf18133940408b5375233cf` |
| archived runtime-manifest repair | 207,103 | `10cf774430b19b6003ccddc4291b00e6203218b2c2ab0adf6e5f980ee1f57f6e` |
| archived spatial recovery | 108,267 | `de633c1cef0b8638297b88d6056a66fa5001a9429722ec21bd390ab0a98a3197` |

첫 repair session은 Windows newline byte mismatch를 append-only `closure_failed`로 기록했고,
retry01은 rollback restoration identity mismatch를 별도 `closure_failed`로 기록했다. 두 session과
old AQ session은 retry02로 supersede됐고 기존 파일은 수정하지 않았다.

최종 repair dry-run session은 `material-repair-20260814t041500000z-retry02`다. 정확한 결과는 다음과
같다.

| artifact/result | bytes | SHA-256 또는 값 |
|---|---:|---|
| dependency closure | 89,089 | `70115e5ad14865ba8438a49497a1df782eb9ed0d5854ffbf85393532b77c364d` |
| closure receipt | 24,797 | `374e1455a3e6e6f7e48ecb6090a6d198d273a3f507d1c0e53eb9743fa624e063` |
| preflight failure | 1,818 | `c5b3d5409793577ed25f0003a86fea19596c2eb6543f54d58b1ab22164f61c37` |
| attempt state | 4,506 | `a17820f0e23b6f6fe55077731d74c9249d8e394afb94fa3a388c872aed836c93` |
| state | — | `preflight_failed` |
| exact issue | — | `candidate MaterialPlan lacks image-backed UV coverage for detail.crystal.facet_lines` |

이 실패는 Blender shadow compile 이전의 material coverage 검사에서 발생했다. 해당 session의
Blender preflight, neutral preview, approval, controller, promotion, rollback, canonical write와 IQ
진입은 모두 0이다. canonical hashes도 다음과 같이 유지됐다.

- SceneSpec: `ef7cadec41a56a10701c10ea623fb6367dc05cb34acc39f8d360b8752fe77ab8`
- ModelingPlan: `52779a95bd5bf4f87b55cd6481d55c8e50efcaca79e7c16973682314b1a4b225`
- Blend: `5def13d76012b0c9747dce6ef016799550bca74a9e5f2e3bccf6b7ed8a9ebe5a`
- canonical MaterialPlan: absent

따라서 current Crystalgun recovery는 `approval_pending`까지 통과한 결과가 아니다. framework가
누락 coverage를 권한 소비 전에 차단하고 canonical을 보존한 fail-closed 결과다. 다음 시도는
coverage가 완전한 새 candidate, 새 closure/preflight/preview를 요구하며 기존 approval을 재사용할
수 없다.

## 5. 현재 판정 대장

| 영역 | 상태 |
|---|---|
| strict contract/schema 및 generic closure/rebinding | focused host tests passed |
| preapproval actual Blender shadow compile/neutral preview | one procedural fixture passed |
| specialized approval publisher rejection boundary | focused host tests passed; actual user-approved success unverified |
| approval/controller/promotion one-shot success | unverified; authorized user decision 없음 |
| rollback injection/state consistency mechanism | focused host tests passed; authorized end-to-end promotion failure unverified |
| job-specific source inventory/generalization | complete, exact archive/inventory 게시 후 executable source 제거 |
| Crystalgun repair dry-run | strict `preflight_failed`; canonical-write-free 차단 verified |
| Crystalgun material approval/promotion/`MaterialPhaseReceiptV2`/IQ | not_run |
| ImageGen + localized-detail actual Blender fixture | unverified |
| crystal + emission + alpha actual Blender fixture | unverified |
| V0.7–V0.9 chained regression | not_run |
| implementation 후 최종 full pytest | passed: 1,750 passed, 62 skipped, 8 warnings |
| final Ruff/doctor/blender-compat | passed; Blender 5.0.1, GLB/FBX/OBJ smoke |
| instruction/literal/schema checks | passed: 16 files/192 invariants; no job literal; schema parity |
| final repository projection parity | temporary audited index 기준 authoritative `--write`/`--check` passed; 실제 Git index 불변 |

## 6. 해석 제한과 후속 기록

- fake ImageGen fixture와 historical PNG reuse는 fresh built-in ImageGen 실행 증거가 아니다.
- shadow compile과 neutral preview는 canonical promotion, human material review 또는
  `MaterialPhaseReceiptV2`가 아니다.
- preflight failure는 material quality failure가 아니며 Crystalgun 자산의 외관을 판정하지 않는다.
- full authorized success, `MaterialPhaseReceiptV2`, IQ, accepted GLB/FBX package와 destination
  runtime parity는 evidence가 생기기 전까지 주장하지 않는다.
- 최종 full pytest/Ruff/doctor/blender-compat/instruction/literal/schema 결과는 위와 같이 통과했다.
  repository projection은 audited temporary index에서 `--write` 뒤 `--check`를 통과했고 실제 Git
  index tree는 바뀌지 않았다. 최종 `git diff --check`도 line-ending notice 외 오류 없이 통과했다.

Compact tracked index는
[`verification/evidence/material_closure_stabilization_20260814/README.md`](verification/evidence/material_closure_stabilization_20260814/README.md)에
기록한다. Job-local JSON이 권위이고 이 문서는 그 내용을 대체하지 않는다.
