# Skill Orchestration 0.1 검증 기록

## 최종 판정

2026-08-27 기준 Skill Orchestration 소스 기준선과 두 실제 Standard 자산 E2E는
`passed_with_declared_quality_and_format_limits`다. `actual_standard_composite_asset_verified=true`로
투영한다. AQ는 진입 준비성만 `ready`이며 `actual_aq_skill_adapter_asset_verified=false`,
`autonomous_static_prop_v2=disabled_experimental`을 유지한다.

원본 stdout과 자산별 exact hash ledger는
[`verification/evidence/skill_orchestration_standard_20260826/`](verification/evidence/skill_orchestration_standard_20260826/)
에 보존한다.

## Fresh 실행 결과

| 명령/게이트 | 결과 |
| --- | --- |
| `uv sync --frozen --extra dev --extra vision` | 51 packages, exit 0 |
| `uv run ruff check .` | 통과; sandbox의 보존 scratch 접근 경고와 clean host retry 모두 기록 |
| Skill Orchestration/MaterialManifest/V0.5/candidate review/V0.8 집중 pytest | sandbox `WinError 5` attempt 보존 후 host retry `180 passed` |
| `uv run pytest` | `1987 passed, 63 skipped, 8 warnings` |
| `uv run cbm doctor` | Repository/Workspace/Blender/Codex 모두 OK |
| `uv run cbm blender-compat` | Blender 5.0.1, Python 3.11.13, GLB/FBX/OBJ 통과 |
| `python scripts/check_agent_instructions.py` | 18 files, 192 invariants 통과 |
| `uv run python scripts/generate_repository_summary.py --write/--check` | 별도 intended-tree index에서 통과; 실제 index 변경 0 |
| `uv run pytest tests/test_repository_summary_generator.py` | top-level status 계약 실패 보존·수정 후 `6 passed` |
| `scripts/run_v07_gates.ps1` | exit 0; 전체 pytest `1987/63/8`, GLB/FBX/OBJ package+clean import 3/3 |
| `scripts/run_v08_gates.ps1` | exit 0; 전체 pytest `1987/63/8`, preview/portable fixture 계약 통과 |
| `scripts/run_v09_gates.ps1` | exit 0; 전체 pytest `1987/63/8`, Blender package/clean import/handoff/queue/audit 통과 |
| `scripts/run_autonomous_quality_gates.ps1 -SkipFullRegression -SkipLegacyGates` | `915 passed, 26 skipped, 8 warnings`; activation/campaign 0 |

전체 pytest와 AQ 집중 게이트의 8개 warning은 Pillow `mode` deprecation이다. V0.7 형식별
roundtrip warning은 선언된 포맷 손실/간접 검증 경계이며 failed check는 0이다.
첫 generator 시도는 system Python의 project dependency 부재로 실패했고 frozen `uv` 환경에서
재시도해 통과했다. 첫 projection 회귀는 허용 enum보다 넓은 top-level status를 발견해 실패했으며,
상태를 공개 계약의 `passed`로 고치고 세부 한계는 `final_verification.status`에 유지했다.

## 실제 Standard 자산 E2E

### `item_plastic_standard_canary_01`

- 분류: **accepted Standard canary with declared silhouette limitation**
- run `item-plastic-standard-canary-01-run`, terminal `completed`
- final state SHA-256 `28dec62d2a10f03643910c089b4616fc442d7795fa69cc4b023e2dd8d13dbfa5`
- V0.6 direct score `0.744321 → 0.795028`, silhouette IoU `0.674717 → 0.718917`
- 잔존 finding `direct.global_silhouette` high. 사용자가 exact request
  `3ea78a47aed5d8d007490a369e745367ba7534f2d6a77a17e36dff5e5d4f30f3`에 대해 수용했다.
- canonical SceneSpec `3ed91596…`, MaterialPlan `e9d4c0af…`, Blend `a70be15f…`
- package manifest `4833a6ff…`, GLB `a2b10b23…`, roundtrip `083fb7ef…`
- clean import 1 passed / 6 warnings / 0 failed, semantic/material coverage 1.0,
  bounds max error 0.0 m
- final package approval fingerprint `8a361cd0da7310292e325e909a2b9c030de3e7c3456713cb279c2e1aa60a64f5`

이 자산은 사용자 수용 한계를 포함한 canary이며 완벽한 quality pass로 재분류하지 않는다.

### `collectible_cloth_01`

- run `collectible-cloth-01-final-kpi-r1`, 정확히 한 번의 bounded `manual_guarded` revision 뒤 terminal `completed`
- final state SHA-256 `b1379cd51e5e4ca3f07c55bfd63a03c40a66d92535bed0fdd92a6629fe4d83ba`
- canonical SceneSpec `b61f7fea…`, geometry payload `2e0c4b6f…`, fresh MaterialPlan `85a5b01d…`,
  Blend `38634299…`, TextureManifest `fe8f3adf…`
- fresh V0.6 run `v08-984ec6b0-qa`: direct score `0.861737 → 0.862142`
  (`+0.000405`), silhouette IoU `0.784956 → 0.812281` (`+0.027325`)
- 정확히 7 canonical pass, surface-detail binding 2/2, QA warnings 0
- 잔존 finding `direct.global_silhouette` medium. 사용자가 exact request
  `d44875814eebc79cdda46ca957c8d1f7554e8282bf9e160d45f10dd7bd8b7ef0`에 대해 수용했다.
- post-material assembly `v06-984ec6b0-post-material-assembly`: 5 views/20 passes,
  structural passed, visually coherent, advisory unscorable, V0.4 re-entry 없음
- package manifest `866e70cc…`, GLB `a79c91f6…` (6,444,204 bytes), roundtrip `458bff05…`
- clean import 1 passed / 6 warnings / 0 failed, semantic/material coverage 1.0,
  bounds max error 0.0 m, missing dependency/absolute escaped path 0
- final package approval fingerprint `26fce62ce1cbd1075b310bc4aa455108b72c166577537f5cb1210e8f42d247bf`

천 자산은 evaluated UV mesh의 degenerate UV triangle 1,152개를 이전 수용 상태와 동일한 한계로
유지한다. package sandbox attempt 2회가 OpenImageIO Windows temp 접근 오류로 실패했고, immutable
attempt를 보존한 exact host retry 3번째가 성공했다. 이는 기술 retry이며 사용자 승인으로 계산하지 않는다.

## Roundtrip 및 범위 한계

두 실제 GLB roundtrip은 각각 다음 6개 warning을 유지한다.

1. axis metadata를 독립 검사하지 않아 imported bounds만 간접 증거로 사용
2. unit metadata를 독립 검사하지 않아 numeric bounds만 간접 증거로 사용
3. custom split-normal 동등성 미검증
4. tangent vector 동등성 미검증
5. UV loop-to-vertex association 미검증
6. UV coordinate summary preservation 미검증

clean-scene import, exact package-manifest binding, semantic/material coverage와 bounds는 통과했다.
이 결과는 rig/animation/CAD B-Rep 또는 Unity/Unreal runtime parity를 증명하지 않으며 destination
project를 수정하지 않았다.

## AQ 진입 준비성

판정은 `ready`다. 근거는 fresh source/Blender/V0.7/V0.8/V0.9/AQ contract 게이트 통과와 두
human-reviewed Standard package lineage다. 그러나 AQ 스킬과 실제 AQ 자산은 이번 Goal에서 실행하지
않았다. profile activation `false`, campaign 생성 `false`, AQ Blender 실행 `false`이며 AQ v2는 계속
`disabled_experimental`이다. 실제 AQ 시작에는 별도 명시적 opt-in과 exact asset/session authority가
필요하다.

V0.9 격리 smoke의 fixture approval은 production 사용자 승인도, 재사용 가능한 권위도 아니다.
과거 Material Closure/Identity Split/ImageGen 증거의 미검증 경계 역시 그대로 유지한다.
