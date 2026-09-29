> 2026-09-30 프로젝트 보존용 열람본. 아래 평가는 당시 f55/0.9.0 상태의 기록이며 v0.9.1 검증으로 재분류하지 않습니다. 최신 종료·재개 기준은 [HANDOFF_KO.md](../../HANDOFF_KO.md)에 있습니다. 원본의 내용은 보존하고 링크만 프로젝트 보존본으로 연결했습니다.

# 보존된 실제 이미지로 보는 성과와 한계

이번에는 이미지 생성·수정·렌더·QA를 실행하지 않았다. 아래는 기존 파일을 직접 열어 본 조사이며 인간 beauty 수용을 기록하지 않는다. 원본은 복제하거나 재분류하지 않았다. [본문](E:/Playground/BlenderAssetGenerator/reports/reference_fidelity_closeout/v0.9.1/archive/rf-reassessment-20260929-run01/REPORT_KO.md)

## Plastic: 기존에도 사용 가능한 결과가 있었고, 후속 결과에서 보이는 이득도 있다

세대 간 같은 reference SHA-256: `ef1a06d053cbf414b986d5488dd8d5c4b4a61b9387489fb957816feec167cc52`.

### Reference

![Plastic reference](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p/input/reference.png)

### 이전 Standard canary

![이전 Standard Plastic](E:/Playground/BlenderAssetGenerator/workspaces/item_plastic_standard_canary_01/qa/runs/v08-d33330a6-qa/passes/beauty.png)

입체적인 파란 플라스틱 몸체와 테두리를 이미 갖고 있다. 다만 reference보다 윤곽과 테두리가 각지고 단순하며 사진의 마모·긁힘은 적다. 당시 사용자는 남은 silhouette 한계를 명시적으로 수용했고 package도 승인했다. 지금의 다른 기준으로 그 수용을 취소하거나 실패로 바꾸지 않는다.

### 직전 ab39 결과의 실제 BEFORE

![ab39 Plastic 재질 수정 전](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p/qa/runs/candidate-01/passes/beauty.png)

### 직전 ab39 결과의 실제 AFTER

![ab39 Plastic 재질 수정 후](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_ab39_01p/qa/runs/material-01/passes/beauty.png)

ab39 내부 BEFORE/AFTER는 동일 geometry·camera·lighting·renderer 조건이다. 몸체와 테두리의 푸른색 불일치를 완화했고, 넓고 연속적인 회색 마모 띠를 불규칙한 국소 마모로 바꿨다. paired proof는 이 제한된 재질 개선을 뒷받침한다. 개별 긁힘 위치·빈도, 마모 폭, 사진의 거친 느낌은 여전히 정확히 같지 않다. 이는 완전한 사진 복원이 아니다.

이전 Standard와 ab39 AFTER 사이에는 reference 외곽과 테두리 형태에 더 가까워 보이는 이득이 있다. 그러나 조명·배경·카메라·형상 저작 노력·수정 이력이 다른 결과이므로 **코드 버전만 바꿔 얻은 통제된 개선량**으로 계산하지 않는다. 더 나은 결과 하나가 있어도 긴 전체 개발 비용을 정당화하는 평균 효율은 별도로 입증해야 한다.

| 정확한 ab39 artifact | SHA-256 |
| --- | --- |
| BEFORE beauty | `878ec8f33d6d9efd8776f7c0d306cde10a69d0769adf053a064ebd76f59ab703` |
| AFTER beauty | `77666d151f967211f8c614df6463821fa8d1b59f81fee65a49b47b09d2b4b637` |
| native paired comparison | `c930e5c8861ed8d2d8d0a6480a3f0425ed2f99d532bb1017276ccaebfe037c07` |
| package manifest | `698f5b755223f5f448d65ed6d30cd098506aaea5c804e02ec6d714fbac4b6a81` |
| clean import | `b91e6e2aad6de599f1666a9f48beac3fde6d4667b05f7c66447b8e94511116a9` |

[Plastic 결과와 정확한 package/import 링크](E:/Playground/BlenderAssetGenerator/reports/reference_fidelity_closeout/v0.9.1/archive/rf1001-20260929/evidence/plastic/RESULT_KO.md). IQ 점수는 전후 0.982965로 같았다. 개선 판단의 근거는 점수 증가가 아니라 실제 이미지·finding·조건 결속이다. 이 자동/agent 판단은 인간 acceptance가 아니다.

## Wood: 문제가 있었던 AQ 결과를 기존 방식 전체로 일반화하면 안 된다

같은 reference SHA-256: `b1312fedd5c1cfab2c7a1c522157442b1a3c543398612e8d02d4672af7df8fc7`.

### Reference

![목재 reference](E:/Playground/BlenderAssetGenerator/workspaces/collectible_wood_03_standard/input/reference.png)

### 이전 Standard 결과

![이전 Standard 목재](E:/Playground/BlenderAssetGenerator/workspaces/collectible_wood_03_standard/qa/runs/standard-v06-r002/passes/beauty.png)

이미 보의 부피, 단면, 길이 방향 나뭇결이 표현돼 있다. 왼쪽 끝이 화면 밖으로 잘리고 형태가 단순화됐으며 사진과 외관이 완전히 같지는 않다. 그래도 “기존 파이프라인은 얇은 판밖에 만들지 못했다”는 주장에 대한 실제 반례다. 보존된 FBX package 33개 파일은 현재 해시와 일치하고 clean import는 passed다.

### 기술 통과 뒤 문제로 확인된 AQ 결과

![높은 direct score의 평면적인 AQ 목재](E:/Playground/BlenderAssetGenerator/workspaces/aq_first_completion_n03_fix3_03_weathered_wood_beam/qa/runs/aq-first-completion-n03-fix3-03-v06/passes/beauty.png)

reference의 윤곽을 따라가는 판과 가는 선형 부품에 가깝다. 목재 보의 부피·파손 단면·풍화 표면을 충분히 표현하지 못한다. direct score 약 0.989347이 이 결함을 부정하지 못한다. silhouette/bbox 중심 평가의 맹점을 보여준다.

### 나중에 만든 cutback 후보

![후속 Wood cutback 후보](E:/Playground/BlenderAssetGenerator/workspaces/aq_rf_24632c6c_03_wood_cutback/qa/runs/initial-fixed/passes/beauty.png)

flat AQ에 비해 실제 부피와 나뭇결이 보인다. 하지만 단면이 규칙적·관처럼 보이는 부분, 둥글고 매끈한 가장자리, reference와 다른 풍화 표현이 남았다. 이 후보는 구조 예산 소진으로 review terminal이며 production package가 아니다. 이 그림을 새로운 best-known으로 지정하지 않았고, 기존 `wood_cap`의 historical best-known 기록도 그대로다.

Standard·flat AQ·cutback은 동일 reference지만 카메라·조명·mask·형상 저작·실행 범위가 다르다. 각 direct score(약 0.802461 / 0.989347 / 0.984230)를 품질 순위로 읽거나 엄밀한 전후 개선율로 계산하지 않는다. **이전 Standard보다 cutback이 사용에 더 낫다는 결론은 미입증**이다.

### 격리 개발 비교와의 구분

`.b/fid`의 Wood 실증은 위 캠페인들과 별도다. 그 baseline_depfix는 상수 PBR로 정규화한 것이며 과거 V0.5 전체 외관을 그대로 재현한 baseline이 아니다. source-bound 비교에서 입체 형상·재질의 개선 또는 부분 개선이 기록됐고 일부 direct score는 오히려 내려갔다. 이 기록은 유용하지만 기존 Standard를 통제군으로 한 우월성 증거도, 현재 f55 baseline의 납품 성공도 아니다. [격리 개발 원본 기록](E:/Playground/BlenderAssetGenerator/VERIFICATION_REFERENCE_FIDELITY_KO.md)

## 이 비교가 말해 주는 것과 말하지 못하는 것

- 확인한 것: 이전에도 유용한 입체 자산·package·인간 수용이 있었고, 일부 AQ 자동화는 높은 점수로 부정확한 모델을 통과시켰다. 후속 Plastic에서는 국소적인 실제 개선이 있고 일부 결과는 이전보다 reference에 더 가까워 보인다.
- 확인하지 못한 것: 현재 방식이 일반적인 요청에서 평균적으로 더 낫거나 더 싸고 빠르다는 사실. 조명·카메라·저작 시간을 통제한 Standard 대 현행 비교가 없다.
- 인간에게 남는 판단: 확보된 결과 중 실제 용도에 적합한 것은 무엇인지. 현재 보고서의 시각 관찰은 beauty/package/Activation 수용을 만들지 않는다.

모든 이미지의 현재 해시와 크기는 [VISUAL_REFERENCES.json](E:/Playground/BlenderAssetGenerator/reports/reference_fidelity_closeout/v0.9.1/archive/rf-reassessment-20260929-run01/VISUAL_REFERENCES.json)에 기록했다. 새 렌더 비용은 0이다.
