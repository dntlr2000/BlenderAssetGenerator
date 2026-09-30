# Material Identity Split 0.1.0 테스트 계획

## 1. contract와 schema

- strict model, unknown field/version, path/hash/size mismatch를 거부한다.
- 18개 identity-split schema와 model mapping, Draft 2020-12, `additionalProperties=false`를 확인한다.
- create-once publication은 identical exact-adopt만 허용하고 conflict/link/escape를 거부한다.

## 2. paired candidate

- SceneSpec은 material identity 2개와 assignment 2개 외의 변경을 거부한다.
- ModelingPlan은 대응 detail target 2개 외의 변경을 거부한다.
- source/clone appearance projection drift, 신규 identity 공유, retained assignment 변경을 거부한다.
- 보존 detail의 channel contract가 달라지면 stale failure로 멈춘다.

## 3. authority

- ApprovalRequest가 user approval이 아님을 확인한다.
- generic approval, MaterialAppearanceApproval, rejected/stale/spliced approval은 apply를 열지 못한다.
- user decision 원문 bytes SHA와 timestamp, exact request/candidate/diff/preapproval binding을 요구한다.
- 동일 approval은 하나의 substantive ApplyIntent와 하나의 consumption에만 결속한다.

## 4. preapproval와 실제 Blender

- canonical currentness, paired diff, clone/assignment와 geometry/UV/reference invariant를 검사한다.
- Blender 5.0.1 build/inspect/validate 3회와 output receipt를 확인한다.
- passed 세 evidence가 모두 없으면 ApprovalRequest를 게시하지 않는다.
- 긴 run ID에서도 compact derivative path가 legacy Windows 한계를 넘지 않는지 검사한다.
- 실제 fixture는 canonical hash/size와 MaterialPlan 부재가 동일하고 후속 authority count가 0인지 확인한다.

## 5. apply, crash, recovery

- lock이 intent consumption, archive, canonical replace보다 먼저인지 검사한다.
- SceneSpec/ModelingPlan/Blender/invariant/ApplyReceipt 전후 6개 apply crash point와 rollback 중
  crash point를 주입한다.
- rollback 도중 crash는 `recovery_required`로 보존하고 exact recovery만 허용한다.
- 부분 canonical 상태에서 이전 precondition currentness를 잘못 요구하지 않는다.
- recovery retry는 1회이며 approval 재소비와 새 intent 생성은 0이다.
- success는 paired commit 또는 exact rollback 하나로만 끝난다.

## 6. post-apply와 compatibility

- 새 SceneInventory, BuildProvenance, MaterialPlan absence, canonical snapshot과 geometry continuation을
  run-owned immutable evidence로 게시한다.
- 기존 closure/preflight/preview를 current로 재사용하지 않는다.
- standard/background/AQ/ImageGen legacy evidence와 SceneSpec 0.2.0 의미를 유지한다.
- CLI/MCP/config/capability/CI/AQ gate projection과 incident-literal checker를 함께 검증한다.

실제 user approval이나 production apply를 test fixture의 승인으로 대체하지 않는다. 실제 자산
검증은 ApprovalRequest에서 멈추며 apply/post-apply 성공은 authorized evidence가 생기기 전까지
미검증이다.
