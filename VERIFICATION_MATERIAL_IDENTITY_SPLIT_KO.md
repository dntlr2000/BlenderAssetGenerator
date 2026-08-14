# Material Identity Split 0.1.0 검증 기록

## 1. 검증된 범위

- strict contracts와 generated schema parity
- paired SceneSpec/ModelingPlan projection과 clone/assignment invariant
- specialized approval publisher 및 single-use ApplyIntent/consumption 경계
- guarded transaction ordering, 6개 apply crash point와 rollback 중 crash, exact rollback/retry 경계
- post-apply authority-refresh publication mechanism
- CLI/MCP/config/capability/CI/AQ gate projection
- 실제 Blender 5.0.1 isolated preapproval와 canonical non-mutation

## 2. 실제 승인 전 경계

실제 자산 실행은 preapproval report, shadow build receipt, invariant report와 ApprovalRequest를
create-once로 게시하고 `framework_ready_for_explicit_scope_approval`에서 멈췄다. Blender는 build,
inspect, validate를 각각 1회 실행했다. 실제 사용자 approval, consumption, ApplyIntent, canonical
write, repair session, controller, promotion, MaterialPhaseReceiptV2, IQ, package와 destination write는
모두 실행하지 않았다.

정확한 run ID, artifact SHA/size, canonical before/after와 zero-count 대장은
[portable evidence index](verification/evidence/material_identity_split_20260814/README.md)에 있다.

## 3. 해석 제한

ApprovalRequest는 승인 증거가 아니다. 실제 user-approved apply, committed transaction,
post-apply GeometryContinuationReceipt와 후속 material repair는 아직 production evidence로 검증되지
않았다. test-only synthetic approval과 crash fixture는 mechanism 검증일 뿐 실제 권한으로 재사용하지
않는다.

## 4. 최종 gate

| gate | 실제 결과 |
|---|---|
| full pytest | `1809 passed, 63 skipped, 8 warnings in 319.09s` |
| official identity-split focused | `53 passed, 1 skipped in 2.74s` |
| transaction commit/crash/rollback focused | `17 passed in 1.97s` |
| actual Blender opt-in node | `1 passed in 8.02s`; Blender `5.0.1`, 3 processes, 승인 이후 side effect `0` |
| Ruff | `All checks passed!` |
| schema generation parity | `scripts/generate_schemas.py --check` exit `0` |
| job-specific framework literal isolation | exit `0` |
| instruction hierarchy | `root=7764 bytes, files=17, invariants=192` |
| doctor | Repository, Workspace, Blender, Codex 모두 `OK` |
| Blender compatibility | `CBM_COMPAT_OK`; GLB/FBX/OBJ smoke export 성공 |
| repository projection | intended-tree 임시 index에서 `--write` 후 `--check` 통과 |
| `git diff --check` | exit `0`; line-ending 안내만 존재 |

첫 full 재검증에서 저장소 내부 상대 basetemp가 outside-repo fixture의 전제를 깨뜨린 1건과,
그 basetemp 안의 의도적 `AGENTS.md` 충돌 fixture가 instruction checker에 보인 1건이 각각
발견됐다. 제품 실패가 아니며 agent-owned basetemp를 승인받아 제거하고 저장소 밖 절대 basetemp에서
전체 suite를 다시 실행해 위 최종 결과를 얻었다.
