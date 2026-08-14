# Material Identity Split 0.1.0 compact evidence

이 index는 실제 자산에 대한 승인 전 shadow 검증과 generic framework test 범위만 기록한다.
workspace 원본 evidence를 복사하거나 실제 사용자 승인을 대신하지 않는다.

## 실제 run

- job: `item_crystalgun_full_0`
- planning root: `history/material_identity_split_plans/material-identity-split-20260814t080212787z-scope01`
- successful run: `material-identity-split-preapproval-20260814t132423938z-scope02`
- status: `framework_ready_for_explicit_scope_approval`
- Blender: `blender.exe`, version `5.0.1`, process count `3`
- shadow root: `production/material_identity_split/material-identity-split-preapproval-20260814t132423938z-scope02/preapproval/shadow`

첫 run `material-identity-split-preapproval-20260814t115059465z-scope01`은 shadow derivative의
Windows path가 정확히 260자가 되어 Blender 내부 file lookup이 실패했다. source와 derivative
bytes/hash는 `\\?\` native read에서 일치했다. 실패 evidence는 immutable 보존했고 approval,
consumption, intent, canonical write는 모두 0이었다. generic compact derivative path 회귀를 추가한
뒤 새 scope02 run만 실행했다.

## successful artifact ledger

| artifact | SHA-256 | bytes |
|---|---|---:|
| `plan.json` | `5ac662dd63c9b0ffdf2ddf7ec68db46e065d08e2cb925c0fd576d3dacf79bce3` | 10,679 |
| historical candidate SceneSpec | `e0559b1fe55ec7a8a001b4841480a7c76c7f5cc68960182782c216e92b5027e2` | 18,277 |
| `planning/candidate_modeling_plan.json` | `1c7707369d8ac199d0f95998c72bce9d9cc22faa1eae9f53f36d29ff2b982cc4` | 18,385 |
| `planning/modeling_plan_diff_report.json` | `dae11b9300bc2b6007f83edc824b09f68edcda05699254f8663a613969754218` | 2,608 |
| `preapproval/request.json` | `c4a9f5f1fbd27f43a8c59bdcee8d156259d36a9258ab2c3c26af7ac44b9db17a` | 3,372 |
| `preapproval/report.json` | `344d8856be793e499506bfe8281c1d1c1ba8ef507d1cae7924dfc61486958a3e` | 3,685 |
| `preapproval/shadow_build_receipt.json` | `3f72f77f27afd477a085713864ca6f3ca322e2f0a718be09099d9c668c259561` | 6,007 |
| `preapproval/invariant_report.json` | `6f106512dc00c16de16d6295a12f48387003861bb1d3957c9e64f33d7facfe1d` | 3,474 |
| `approval_request.json` | `047dc95ff4f7ceb9097aaa945d8c5bf7c017dd5f69de33b9fcdcf69aa317384a` | 9,842 |
| `states/0002.json` | `dcb6f6d3fa342a3cc09114f2c72eab4c8445005365de4c33231920737cd37bb9` | 4,988 |
| shadow Blend | `7b0e14fe5d78f1c03494f85d5c2283541dd27abdce4e1dcea5ce5899efc46048` | 119,055 |
| shadow SceneInventory | `8b539b68c975fbb0b690e382a87cca3691cebaef5326853eab1c4f17502074e0` | 52,179 |
| shadow validation | `4f5fea8c554561592d59340f3bc148acada30536b0eef53205d3c366ec9669e6` | 25,573 |

PreapprovalReport, ShadowBuildReceipt, InvariantReport는 모두 `passed`이고 ApprovalRequest는
`eligible_for_explicit_user_scope_approval`이다. ApprovalRequest 자체는 user approval이 아니다.

## canonical non-mutation

| canonical | before/after SHA-256 | bytes |
|---|---|---:|
| `analysis/scene_spec.json` | `ef7cadec41a56a10701c10ea623fb6367dc05cb34acc39f8d360b8752fe77ab8` | 17,551 |
| `analysis/modeling_plan.json` | `52779a95bd5bf4f87b55cd6481d55c8e50efcaca79e7c16973682314b1a4b225` | 16,780 |
| `blender/scene.blend` | `5def13d76012b0c9747dce6ef016799550bca74a9e5f2e3bccf6b7ed8a9ebe5a` | 116,632 |
| `analysis/material_plan.json` | absent | 0 |

## authority and downstream counts

| boundary | count |
|---|---:|
| ApprovalRequest | 1 |
| actual user approval | 0 |
| approval consumption | 0 |
| ApplyIntent | 0 |
| canonical write | 0 |
| new repair session | 0 |
| controller | 0 |
| promotion | 0 |
| MaterialPhaseReceiptV2 | 0 |
| IQ | 0 |
| package | 0 |
| destination write | 0 |

## executed verification so far

- identity-split contract/service focused: `10 passed, 1 skipped`
- authority/transaction/schema/public focused after recovery hardening: `50 passed`
- crash/recovery/post-apply mechanism: `15 passed`
- official CI/AQ identity-split focused aggregate: `53 passed, 1 skipped in 2.74s`
- guarded commit/apply-crash/rollback-crash/retry transaction suite: `17 passed in 1.97s`
- actual Blender scope02 command: exit `0`, status
  `framework_ready_for_explicit_scope_approval`, 3 processes
- actual opt-in Blender regression: `1 passed in 8.02s`
- full repository pytest: `1809 passed, 63 skipped, 8 warnings in 319.09s`
- Ruff: `All checks passed!`
- schema parity, job-specific literal isolation and instruction hierarchy: passed
- doctor: Repository/Workspace/Blender/Codex `OK`
- Blender compatibility: `CBM_COMPAT_OK`; GLB/FBX/OBJ smoke export passed
- repository projection: intended-tree temporary index `--write`/`--check` passed
- `git diff --check`: exit `0`; line-ending notices only

실제 user-approved apply, post-apply publication과 downstream material repair는 실행하지 않았으며
production evidence로 주장하지 않는다.
