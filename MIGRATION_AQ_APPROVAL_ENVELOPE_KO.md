# AQ Approval Envelope 0.3 migration 정책

## 1. 원칙

Approval Envelope는 기존 AQ v2 evidence를 바꾸는 migration이 아니라 새 session에만 선택적으로 붙는
companion이다. loader, audit, status, controller, package, report 또는 one-prompt 명령은 과거 evidence를
자동 작성·보완·재분류하지 않는다.

## 2. session 호환 행렬

| session | 읽기 | 새 policy authority | 처리 |
|---|---|---|---|
| AQ v1 | 기존 의미 그대로 | 없음 | 기존 `PolicyAuthorization 0.1.0` 경로 유지 |
| 기존 AQ v2, envelope 없음 | 기존 의미 그대로 | 없음 | `legacy_without_envelope`; 기존 경계 유지 |
| 새 AQ v2 + interactive envelope | 가능 | profile이 허용한 좁은 기술 정책만 | 기존 사용자 승인 중심 경계 유지 |
| 새 AQ v2 + checkpointed envelope | 가능 | routine/technical gate | 사용자 checkpoint 최대 3회 |
| 새 AQ v2 + autonomous envelope | 가능 | exact eligible routine gate | genuine escalation만 사용자 대기 |
| cancelled/expired/tampered session | read-only audit | 없음 | fail-closed |

Envelope가 없는 session에 `interactive` 값을 써 넣지 않는다. absence는 mode가 아니라 historical
contract 상태다.

## 3. 기존 authority 보존

- `RootAuthorizationV2`를 수정하거나 재발행하지 않는다.
- 기존 user approval을 policy authorization으로 변환하지 않는다.
- 기존 policy authorization을 user approval로 변환하지 않는다.
- `approved_by=user`를 합성하지 않는다.
- specialized Identity Split approval과 AQ bounded policy authority는 서로 다른 artifact/kind/path다.
- V0.7 `OptimizationApproval`과 AQ v2 delivery policy authority는 서로 다른 artifact/kind/path다.
- generic approval이나 initial delegation은 미래 exact candidate 승인이 아니다.

## 4. 신규 session 계획

새 envelope는 다음을 모두 확인한 뒤 create-once로 게시한다.

1. exact `RootAuthorizationV2` artifact의 path/hash/size
2. root가 active이고 만료되지 않음
3. 최초 request SHA-256 일치
4. 실제 요청에서 routine approval-free 진행, requested delivery 자동 진행, quality 미달 review 종료의
   명시적 delegation이 관찰됨
5. mode, provider, delivery, routine gate와 cap이 root/profile 범위 안
6. 새 policy profile과 approval budget의 exact hash

기존 root를 포함한 모든 support artifact는 snapshot을 고쳐 쓰지 않고 reference로 결속한다.

## 5. status와 resume

status는 envelope 존재 여부와 exact validity를 읽기 전용으로 보고한다. stale/tampered envelope를
absence나 interactive로 완화하지 않는다. one-prompt resume은 같은 session, root, envelope, policy,
budget, state, assignment와 protected source inventory를 재검증한다.

앱 종료는 migration이나 cancellation이 아니다. host process는 중단되고 evidence는 그대로 남는다.
다음 실행은 persisted state에서 명시적으로 resume한다.

## 6. Crystalgun

현재 Crystalgun Material Identity Split ApprovalRequest는 Approval Envelope 이전 계약으로 생성됐다.
새 authority를 소급 적용하거나 canonical apply를 자동 실행하지 않는다. 기존 specialized explicit
user approval 경계를 유지한다.

`HistoricalSessionAutonomyEligibilityReport`는 다음 가상 질문만 read-only로 답한다.

- 미래 autonomous envelope의 bounded identity-split 조건을 만족했는가
- 어떤 routine gate/policy가 필요했는가
- genuine user decision이 필요했는가
- historical authority를 사용할 수 없는 이유

보고서는 ApplyIntent, approval consumption, canonical write 또는 session state를 만들지 않는다.

## 7. rollback

신규 companion publication 중 실패하면 아직 게시되지 않은 temporary file만 정리하고 기존 evidence는
건드리지 않는다. 게시된 immutable request/report/authorization/receipt는 history로 보존한다.
canonical transaction failure는 기존 archive/rollback 경계를 사용하며 성공 evidence를 제자리 수정하지
않는다.

## 8. 제거/비활성화

기능 flag나 profile이 비활성 상태여도 기존 envelope evidence는 읽을 수 있어야 한다. 비활성화는 새
authorization 발행을 중단할 뿐 history를 삭제하거나 old session을 다른 mode로 재분류하지 않는다.
