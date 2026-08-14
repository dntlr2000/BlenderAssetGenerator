# Crystalgun AQ v2 Material Framework Incident

> 이 문서는 job-specific 사고 기록이다. 범용 source, schema 또는 공통 prompt의 입력값으로
> 사용하지 않는다. 기존 workspace evidence는 수정하지 않으며 machine JSON과 exact hash가
> 이 문서보다 우선한다.

## 1. verified identity와 terminal 경계

- job: `item_crystalgun_full_0`
- workflow: `wf-20260813t025616z-c828dba3`
- dispatch: `dispatch-20260813t025616z-b6cc8e1f`
- historical AQ session: `aqv2-20260813t050847825044z-1232d4a0`
- profile: AQ v2 + Codex ImageGen overlay, 둘 다 `disabled_experimental`
- reported state: sequence 0011, `authoring / running / validate_candidate`
- actual current state: sequence 0012, `terminal / cancelled / none`

| state evidence | bytes | SHA-256 |
|---|---:|---|
| `states/0011.json` | 6,361 | `cb21d5d2b1eb52fcbe19ddaf93d9cf340a04d5b1b6e949a0f61ad2d38aee340b` |
| `states/0012.json` | 6,937 | `f5ae240650d316ed6121338c834941288591ecaf70b80af3e034af2879bcb9a8` |
| `cancellation.json` | 1,443 | `724ba06e05e3cc3dfab7c722470fdcf844ad342f04a30e90aa2e12a6e9cc5e8b` |

`states/0012.json`은 framework-blocked 사유로 이미 종료됐다. 구현과 recovery 실행은 이
terminal state를 resume하거나 append하지 않았다. 다음 companion evidence가 old session 아래
별도 immutable path에 게시됐다.

| companion evidence | bytes | SHA-256 |
|---|---:|---|
| `material_framework_failures/material-closure-stabilization-20260814/state_discrepancy.json` | 3,362 | `d62634f5ee2340d813626f8247d757d13a4e9bae5f2935ae824e621718e53334` |
| `material_framework_failures/material-closure-stabilization-20260814/report.json` | 7,215 | `596d0cadbf13c413fa14e4505f6adb121c782745c5cb2a7689db6f7e54eb30bc` |
| run-owned canonical snapshot | 2,821 | `dca8b5eaa38e1d09732b0d95155fcda64709a00b5f3675a3c6b5bd3266fd61d4` |
| strict MaterialPlan absence | 1,665 | `3d72bf893fd91dcf80586ab661e6248b52a8e88e2bf2ab5b89f0a7778fbdeffc` |

## 2. canonical and derived evidence

Verified canonical hashes:

- SceneSpec: `ef7cadec41a56a10701c10ea623fb6367dc05cb34acc39f8d360b8752fe77ab8`
- ModelingPlan: `52779a95bd5bf4f87b55cd6481d55c8e50efcaca79e7c16973682314b1a4b225`
- Blend: `5def13d76012b0c9747dce6ef016799550bca74a9e5f2e3bccf6b7ed8a9ebe5a`
- canonical MaterialPlan: absent

Old session의 current build provenance는 다른 candidate SceneSpec와 현재 없는 candidate
MaterialPlan을 가리켰다. rollback receipt는 실행 당시의 복구는 증명하지만 현재 derived report의
freshness나 MaterialPlan 존재를 증명하지 않는다. 새 recovery는 canonical bytes를 fresh 관찰한
run-owned evidence만 사용했다.

Latest historical successful rollback은
`material_phase/completion_binding_repair_0010/rollback_receipt.json`, 10,992 bytes,
SHA-256 `67157cd616367399a1e9c17381be48f289c362831b039407e98a068bbc963314`다.
이는 새 repair source binding의 exact restoration baseline일 뿐 old session 실행 권한이 아니다.

## 3. old retries와 approval reality

Approved MCD retry는 preflight에서 controller 전에 차단됐고 controller/Blender/canonical write를
하지 않았다. 뒤이어 생성된 MGB retry plan은 `awaiting_user_approval`이며 approval 파일이 없다.
둘 다 state 0011에 결속돼 current 0012에서 실행할 수 없다.

| evidence | bytes | SHA-256 | 관찰 상태 |
|---|---:|---|---|
| MCD `mcdcr01/plan.json` | 5,054 | `c7ade1549ed68bf0b564c4da8eb6fb249a80da18d535fdfd1cd9311ad106ca18` | stale plan |
| MCD `mcdcr01/approval.txt` | 2,164 | `b55647df504a3c361bd9b45d0d1c2104673f55ed653b4f856b35ae6e90e30e61` | historical approval only |
| MCD `mcdcr01/preflight_receipt.json` | 8,195 | `c80a48c7be16f9fa9bc0f0d0fc109d9dae5c3f866c632c8823f066bd9189bd1d` | blocked before controller |
| MGB `mgbcr01/plan.json` | 6,117 | `5407ca00f0a6c0a25eb219e7962e017c234bf00eeb1659f0cd2c877b224ec5a7` | stale, approval absent |
| MGB derivative receipt | 3,109 | `d66693c3fb9468195c2974a95fa59b57aa46f4673e907b75a87d6972d3782602` | derivative evidence only |
| MGB candidate graph | 5,654 | `dc4cee056cd75a82c564461047556d3677b57af5d7fd3fe19e9be2dc139d1b8b` | non-canonical candidate |

Append-only supersession은 실제 게시됐다.

| supersession evidence | bytes | SHA-256 |
|---|---:|---|
| MCD retry receipt | 2,297 | `0b969cb74ba1d6c9955329a8ff1f8b71b9ce0ceb846f1a5261097014c699c864` |
| MGB approval absence | 1,474 | `cf027e7e99b199ef277e0f8c188140a111c37061174c324d47102d2d93de4dd2` |
| MGB retry receipt | 2,356 | `5deb4f6a9e44f65cb88cf86fc1a76f8ccfa396eb2c7b259f9861e9326ca6e01b` |

어떤 old approval도 새 controller authority로 재사용되지 않았다.

## 4. framework root cause

Controller request, assignment/completion과 host validator가 하나의 authoritative dependency
closure에서 projection되지 않았다. material/graph dependency와 path rebinding을 controller 뒤에
발견해 기술적 repair에 사용자 승인을 반복 요청했고, controller/build/promotion budget을 소모한
뒤 rollback했다.

이는 당시 asset quality failure가 아니라 framework preflight failure였다. Stabilization은
graph-derived closure, host-only rebinding, canonical-write-free comprehensive preflight와
specialized approval-before-controller 경계를 추가한다.

## 5. job-specific source archive와 executable 제거

두 recovery module은 incident ID, semantic prefix, fixed hashes/execution/retry ID와 범용 기능을
함께 포함했다. 현재 working bytes를 먼저 다음 job-local archive에 exact copy로 보존했다.

```text
history/framework_failure_source/crystalgun-material-closure-source-inventory-20260814/
```

| archived artifact | bytes | SHA-256 |
|---|---:|---|
| `10cf774430b19b60-surface_detail_runtime_manifest_repair.py` | 207,103 | `10cf774430b19b6003ccddc4291b00e6203218b2c2ab0adf6e5f980ee1f57f6e` |
| `de633c1cef0b8638-surface_detail_spatial_recovery.py` | 108,267 | `de633c1cef0b8638297b88d6056a66fa5001a9429722ec21bd390ab0a98a3197` |
| `inventory.json` | 2,837 | `5a8ef7715a8a0935fc67505d1778e59894386aa7ebf18133940408b5375233cf` |

Inventory publication 뒤 두 job-specific files는 executable common source tree에서 제거됐다.
범용 기능은 generic Material Closure contracts/services/tests가 담당한다. Archive는 historical
evidence이며 executable framework나 새 권한으로 로드하지 않는다.

## 6. repair session lineage

세 repair attempts는 distinct append-only session이다.

| session | terminal attempt evidence | 결과 |
|---|---|---|
| `material-repair-20260814t032452821z-7c29a841` | `dd29f42651a88625da6272b889134c42739e9d4263d0672001c143d70187cc88` | Windows CRLF/LF rebound-byte mismatch, `closure_failed` |
| `material-repair-20260814t040900000z-retry01` | `d00bceee4139e5f1b4a7cfa0091a5841bfc8745cced4f86aa4eb248239553ce5` | rollback restoration artifact identity mismatch, `closure_failed` |
| `material-repair-20260814t041500000z-retry02` | `a17820f0e23b6f6fe55077731d74c9249d8e394afb94fa3a388c872aed836c93` | coverage check, `preflight_failed` |

Old AQ session, first repair와 retry01을 retry02로 잇는 session supersession도 게시됐다.

| source session supersession | bytes | SHA-256 |
|---|---:|---|
| old AQ → retry02 | 1,758 | `3e1c8e8677ad8ed1b8bd15956625f72978ba5bd1a6ede00eb257afdc45f2e64d` |
| first repair → retry02 | 1,874 | `2327a95242f35e3f72fb91220e39377956ef12965bbe49827255a3fbc1aa42f4` |
| retry01 → retry02 | 1,872 | `115d8af43e8ac01ed3bdc3d571f97113e4da821cf1dcf732fed38b7ac638cf32` |

Supersession은 source session을 resume하거나 그 state chain을 변경하지 않는다.

## 7. retry02 exact outcome

Retry02는 exact rollback observation에 이미 기록된 artifact identities를 재사용하고 closure를
게시했다.

| artifact | bytes | SHA-256 |
|---|---:|---|
| dependency closure | 89,089 | `70115e5ad14865ba8438a49497a1df782eb9ed0d5854ffbf85393532b77c364d` |
| dependency closure receipt | 24,797 | `374e1455a3e6e6f7e48ecb6090a6d198d273a3f507d1c0e53eb9743fa624e063` |
| preflight failure | 1,818 | `c5b3d5409793577ed25f0003a86fea19596c2eb6543f54d58b1ab22164f61c37` |
| framework failure report | 4,923 | `f5e6feb7fada0e572043352acfbbf9d1c54fef2b3d6e876e2002c15ec0ecf96d` |

Exact issue:

```text
candidate MaterialPlan lacks image-backed UV coverage for detail.crystal.facet_lines
```

이 결과는 closure/rebinding publication 뒤 material coverage 검사에서 fail closed됐다. Blender
shadow compile/neutral preview, approval, controller, promotion, rollback, canonical write와 IQ는
모두 0이다. canonical SceneSpec/ModelingPlan/Blend hashes는 2절과 동일하고 MaterialPlan은 계속
absent다.

## 8. 현재 recovery 판정

- generic framework의 early-failure/canonical-preservation 경계는 이 incident dry-run에서 확인됐다.
- Crystalgun candidate가 material preflight를 통과했다는 주장은 거짓이다.
- approval request를 만들 조건인 neutral preview가 없으므로 사용자 appearance approval을
  요청하거나 합성하지 않는다.
- 다음 시도는 네 ModelingPlan surface-detail 요구를 모두 image-backed UV evidence로 닫는 새
  candidate와 새 closure/preflight가 필요하다.
- actual user-approved controller/promotion, `MaterialPhaseReceiptV2`, IQ 0.2와 production package는
  실행되지 않았다.
