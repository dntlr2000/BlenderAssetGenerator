# Material Identity Split 0.1.0 마이그레이션 정책

## 1. additive only

기존 SceneSpec, ModelingPlan, Blend, MaterialPlan, approval, Material Closure, AQ state와 실패 session은
자동 변환하지 않는다. identity split은 exact planning evidence와 새 run ID가 있을 때만 선택한다.

## 2. historical evidence

과거 실패 run은 수정하거나 resume하지 않는다. preapproval 실패 원인을 generic code에서 해결해도
새 run ID로 plan/preapproval을 다시 게시한다. 동일 bytes publication만 exact-adopt할 수 있다.

## 3. approval migration 금지

RootAuthorizationV2, workflow approval, technical retry approval, MaterialAppearanceApproval을
`MaterialIdentitySplitRootScopeApproval`로 변환하지 않는다. specialized approval은 사용자의 새 명시적
결정과 exact ApprovalRequest에만 결속한다.

## 4. apply 이후

identity split 적용 뒤 기존 material closure, graph rebinding, preview, absence, controller projection은
stale이다. 새 post-apply authority refresh를 source로 후속 material repair를 시작하며, 새 material
appearance bytes에는 별도 MaterialAppearanceApproval이 필요하다.

## 5. 활성화

project `0.9.0`, SceneSpec `0.2.0`, experimental profile 상태는 바뀌지 않는다. 이 companion의
존재만으로 AQ v2, ImageGen overlay 또는 Standard ImageGen을 활성화하지 않는다.

