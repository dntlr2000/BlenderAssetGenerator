# AQ v2 Material Closure Stabilization 0.1.0 마이그레이션 정책

## 1. 자동 migration 금지

기존 AQ state, retry plan/approval, controller request/result, promotion intent, rollback,
ImageGen/MaterialAuthoring evidence는 immutable history다. 새 contract 필드를 과거 JSON에
삽입하거나 상태를 재분류하지 않는다.

## 2. legacy와 stabilized attempt

과거 material execution은 원래 schema/version 의미로 계속 읽는다. 새 stabilized attempt만
exact profile/session binding을 통해 closure, rebinding, comprehensive preflight, candidate
neutral preview와 MaterialAppearanceApproval을 요구한다. 기존 post-promotion neutral preview와
V0.5 exact-adoption graph preflight는 새 preapproval full-scene evidence로 재해석하지 않는다.

## 3. job-specific recovery source

현재 working bytes와 tracked baseline을 먼저 `JobSpecificRecoverySourceInventory`에 결속하고,
필요하면 job-local `history/framework_failure_source/`에 exact copy를 보존한다. 범용 기능이
새 module과 tests로 대체된 뒤에만 executable source에서 incident literal을 제거한다. 역사
receipt나 workspace script copy는 검사 실패를 숨기기 위해 수정하지 않는다.

2026-08-14 incident recovery는 이 순서를 실제 적용했다. 두 source의 working bytes를 job-local
history와 exact inventory에 먼저 게시한 뒤 executable common source에서 제거했다. 상세 path와
hash는 [incident 기록](CRYSTALGUN_FRAMEWORK_INCIDENT_KO.md)에 한정하며 archive를 실행 가능한
legacy adapter로 다시 로드하지 않는다.

## 4. historical session supersession

terminal session은 재개하거나 append transition하지 않는다. current state, framework failure,
retry plan, approval 또는 explicit approval absence를 결속한 companion supersession receipt를
새 immutable path에 게시한다. 기존 approval은 historical이며 새로운 controller authority가
아니다.

Crystalgun의 verified head는 `0012 / terminal / cancelled / none`이다. 따라서 보고된 `0011`
뒤에 blocked state를 새로 append하거나 old session을 resume하지 않는다. approved MCD retry와
approval이 없던 MGB retry는 서로 다른 receipt로 처리하고, 후자는 strict
`MaterialRetryApprovalAbsence`를 먼저 결속한다. 2026-08-14 실행에서는 두 retry supersession과
approval absence, old AQ/failed-repair session supersessions가 실제 게시됐다. 이 사실은 기존
approval의 authority를 되살리거나 terminal state를 변경하지 않는다.

## 5. material repair session

새 unique repair session은 old session의 exact terminal/failure evidence, canonical geometry,
reference, UV fingerprint, scope와 latest successful rollback에 결속한다. geometry/source hash가
다르면 자동 계속하지 않는다. 새 session은 material-only candidate/preflight까지만 진행하고,
appearance approval 없이는 controller나 promotion으로 가지 않는다.

## 6. rollback과 derived-state inconsistency

기존 rollback receipt는 그 실행 시점의 exact 복구 evidence로 보존한다. 현재 canonical과
restored derived report가 불일치하면 report를 덮어쓰지 않고 discrepancy/consistency evidence를
추가한다. 새 repair preflight는 current canonical에서 derived evidence를 다시 생성한다.

## 7. stabilized publication 순서

```text
current canonical observation 또는 strict MaterialPlan absence
→ run-owned baseline/source binding
→ host graph rebind plan + derivative + receipt
→ final graph-derived closure + receipt
→ canonical snapshot + consistency report
→ bounded full preflight + actual neutral preview
→ approval pending
```

승인 전 단계는 canonical-write-free다. appearance 승인 이후에도 fixed controller는
request-owned staging만 쓰고, 기존 host promotion/rollback authority가 최종 canonical을 쓴다.
legacy controller completion은 additive closure field가 없더라도 원래 의미로 읽을 수 있으나,
새 stabilized attempt에는 exact closure binding이 필수다.

각 화살표는 앞 gate가 통과했을 때만 진행한다. 2026-08-14 current repair는 final closure 뒤
surface-detail coverage 검사에서 `preflight_failed`로 멈췄으므로 Blender shadow compile,
neutral preview와 approval pending에 도달하지 않았다. Migration 정책은 이 fail-closed 결과를
성공으로 재분류하지 않는다.

## 8. 활성화와 다음 로드맵

이 migration은 `standard`, `background_exterior`, AQ v1을 Material Closure로 자동 전환하지
않고 AQ v2/ImageGen profile도 활성화하지 않는다. Standard ImageGen companion은 stabilization,
current repair preapproval dry-run, 실제 자산 3종 regression과 specialized approval/rollback
consistency가 검증된 뒤 별도 additive 작업으로 시작한다.

## 9. material identity split은 migration이 아니다

기존 material ID를 자동 rename하거나 old TextureManifest/ShaderRecipe를 새 identity의 evidence로
재분류하지 않는다. Object assignment 또는 material identity 추가가 필요한 `scope_change`는
Material Identity Split `0.1.0`의 exact paired candidate와 별도 root-scope 승인으로만 진행한다.
실제 apply 후에는 새 canonical bytes에 대해 Material Closure source, closure, preflight, preview와
MaterialAppearanceApproval을 다시 만든다. Legacy closure/evidence는 원래 의미로 계속 읽되 current
post-split authority로 자동 승격하지 않는다.
