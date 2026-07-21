# V0.7.4 최적화 사전 검토 게이트 검증 기록

검증일: 2026-07-20  
환경: Windows, Blender 5.0.1, `BLENDER_EEVEE`, AgX Medium High Contrast

## 검증 범위

V0.7.4는 V0.7.3의 derived-only 최적화와 패키징 앞에 다음 게이트를 추가합니다.

```text
preflight
→ review_plan.json
→ optimization_review.json
→ exact SHA-256 approval
→ single-use approval consumption
→ derived optimization
```

검증은 사용자 작업인 `first_reference_test`가 아니라 격리된 `geometry_showcase` smoke workspace에서 수행했습니다.

## 정적 검증

- pytest: 335/335 통과
- Ruff: 통과
- JSON Schema parity: 통과
- CLI 공개 명령: `asset-plan`, `asset-plan-approve`, 승인 해시가 필요한 `asset-optimize` 확인
- MCP allowlist: 계획·승인·실행 도구 확인
- post-approval plan 변경 거부 테스트: 통과
- single-use approval 재사용 거부 테스트: 통과

## Blender 호환성

- Blender: 5.0.1
- Render engine: `BLENDER_EEVEE`
- Color management: `AgX - Medium High Contrast`
- GLB/FBX/OBJ smoke export: 모두 통과
- Python exception propagation과 MCP stdin 격리: 기존 게이트 유지

## 사전 검토 결과

`portable_gltf`와 `fbx_interchange`는 다음 기본 정책을 명시적으로 보고했습니다.

- LOD0 보존
- LOD1 ratio 0.60, minimum silhouette IoU 0.98
- LOD2 ratio 0.30, minimum silhouette IoU 0.95
- `compound` collision
- 현재 compound 구현은 source object별 bounds box 한 개
- destination runtime switching과 물리 비용은 미검증으로 표시

`obj_legacy`는 LOD와 collision이 비활성화된 상태를 보고했습니다.

세 run 모두 다음을 확인했습니다.

- review 전 optimized 디렉터리 미생성
- `review_plan.json` SHA-256과 approval 일치
- profile, preflight, source fingerprint 결합
- 승인 1회 소비
- `optimization_plan.json` complete
- `asset_cost_report.json` ok
- canonical unchanged

## 패키징과 clean import

| Profile | Package | Round trip | Bounds max error | Semantic coverage | Material coverage |
|---|---|---:|---:|---:|---:|
| `portable_gltf` | GLB | 통과 | 0 m | 1.0 | 1.0 |
| `fbx_interchange` | FBX | 통과 | 약 0.000001 m | 1.0 | 1.0 |
| `obj_legacy` | OBJ | 통과 | 약 0.000001 m | 형식 손실로 이름 기반/미지원 | 1.0 |

패키지 metadata에는 다음 승인 증거가 함께 복사되고 receipt hash로 보호됩니다.

- `review_plan.json`
- `optimization_review.json`
- `optimization_approval.json`
- `optimization_plan.json`
- `execution_plan.json`

## PDF 보고서

격리 export PDF는 11페이지로 생성됐고 다음 항목의 텍스트 추출을 확인했습니다.

- `Pre-optimization LOD and Collider Review`
- `Plan SHA-256`
- `Collision strategy`
- `Approval consumed`

PDF SHA-256:

```text
cd7a9126c83ce7426224ac6209160176b3a269919acedacf4c74bcac417e412c
```

PDF와 smoke workspace는 derived 검증 산출물이며 canonical 프로젝트 입력으로 사용하지 않습니다.

## 결론

V0.7.4의 사전 검토·해시 승인·single-use 실행 게이트는 Blender 5.0.1에서 세 engine-neutral profile의 최적화, 재질 변환, 패키징, clean import, PDF 생성까지 통과했습니다. 목적 엔진별 LOD switch distance, runtime draw call, physics cost, prefab/actor 재조립은 V0.8 destination adapter가 실제로 선택되고 검증될 때까지 미확정입니다.
