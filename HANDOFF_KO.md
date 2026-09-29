# Reference-fidelity 종료 인계 — v0.9.1

2026-09-30. 사용자는 재평가의 **A안: 장기 개선 작업 종료**를 선택했다. 이 문서는 다시 개발하거나 캠페인을 실행하라는 지시가 아니다. 다음 작업은 별도 사용자 지시가 있어야 한다.

## 고정 버전과 사용 범위

| 항목 | 기준 |
| --- | --- |
| 프로젝트 릴리스 | **v0.9.1**, 로컬 annotated tag `v0.9.1` |
| 마지막 형상 기능 수정 | `f55e739ec072b40dc2ed9c408292899087ca7ccb` |
| 이전 종료 태그 | `codex/reference-fidelity-closeout-20260930` → 위 f55 commit. 그대로 보존 |
| 이번 릴리스 차이 | 버전 표시, 0.9.0/0.9.1 producer 호환성, 종료·재개 문서. 새 형상 기능 없음 |
| 계약 버전 | SceneSpec 0.2.0, V0.4~V0.9 및 AQ/IQ companion 버전 유지 |
| AQ v2 상태 | `disabled_experimental`. 새 Activation 또는 실행 baseline 발행 없음 |
| 배포 | 로컬 commit/tag로 고정. GitHub push는 별도 지시 사항 |

정확한 릴리스 commit/tag와 이번 검사·정리 기록은 [릴리스 증거](reports/reference_fidelity_closeout/v0.9.1/RELEASE_RECEIPT.json)에 있다. 과거 f55의 Blender 검증을 새 릴리스에서 다시 실행했다고 표현하지 않는다. 사용자 원본·canonical·QA·approval·package·receipt·history·terminal은 정리 대상에서 제외했다.

기본 Standard 방식으로 기존 기능과 완성 자산을 활용할 수 있다. 전체 5자산 캠페인 성공을 일반 자산 제작의 선행조건으로 강제하지 않는다. 새 요청의 실제 형상·외관 문제를 기준으로 작업 범위를 정한다.

## 왜 개선을 시작했는가

기존 파이프라인도 reference 분석, 형상·재질 저작, 실제 Blender 렌더, package와 clean import를 수행할 수 있었다. 이전 Standard 목재는 이번과 같은 reference로 입체적인 보와 나뭇결을 표현하고 FBX 납품을 마쳤으며, 과거 Standard Plastic·Cloth에는 인간 beauty/package 수용도 있다. 기존 결과 전체가 나빴다는 뜻은 아니다.

직접 계기는 일부 AQ 실험에서 **높은 QA 점수와 잘못된 부피·단면이 함께 나타난 것**이다. Wood가 얇은 판과 막대처럼 보이는데 direct score 약 0.989347로 기술적 production/package/import를 마쳤다. 윤곽·bbox 중심 평가가 두꺼운 보의 부피, 파손 단면, 부품 관계를 놓쳤다. Rust 절곡·관 구조와 Crystal의 주요 부피에도 결함이 있었다.

사용자가 겪는 손실은 그럴듯한 정면 결과를 받고도 회전·편집·납품 과정에서 구조 오류를 발견해 다시 만드는 것이다. 이 개선은 점수를 올리거나 검사를 많이 하는 것이 아니라, 실제 결함을 발견하고 원인에 맞게 고쳐 더 쓸 만한 자산을 얻기 위해 시작했다.

## 원래 목표와 종료 판단

```mermaid
flowchart LR
    A[Reference 관찰·불확실성] --> B[부피·단면·부품 관계 가설]
    B --> C[구조 우선 저작]
    C --> D[실제 렌더·source-bound finding]
    D --> E[구조·국소·재질별 수정]
    E --> F[같은 조건 전후 개선]
    F --> G[Package·독립 clean import]
    G --> H[기술·시각·인간 판정 분리]
```

최종 목표는 다섯 reference 모두에서 관찰 기준 충족과 실제 시각 개선을 입증하고 재현 가능한 납품을 확보한 뒤 Activation을 평가하는 것이었다. 기술 통과, 실제 시각 개선, 인간 beauty·package·Activation 수용은 각각 별개다. 검사·렌더·수정 횟수는 품질 KPI가 아니다.

평가 누락 방지와 일부 실제 개선·버그 수정의 이득은 확인했다. 그러나 기존 사용 방식 대비 **평균 품질·시간·비용의 충분한 우월성은 미입증**이다. 예산·승인·증거 연결과 재시작 비용이 커졌고, 사용자는 이를 근거로 A를 선택했다. 투입 비용 때문에 추가 작업을 자동 정당화하지 않는다.

- [전체 재평가와 파이프라인](docs/reference_fidelity_closeout/REASSESSMENT_KO.md)
- [GitHub 대비 변경 가치·비용 검토](docs/reference_fidelity_closeout/CHANGE_REVIEW_KO.md)
- [실제 시각 자료와 비교의 한계](docs/reference_fidelity_closeout/VISUAL_EVIDENCE_KO.md)
- [원래 단계별 목표](ROADMAP_V1_KO.md), [개발 실증](VERIFICATION_REFERENCE_FIDELITY_KO.md), [구현 설명](docs/reference_fidelity.md)

## 어느 단계에서 멈췄는가

| 단계 | 종료 시 상태 |
| --- | --- |
| A: QA 누락과 잘못된 통과 조건 재현 | 개발 실증 완료 |
| B: 대표 Wood 구조 재저작·수정 루프 | 격리 개발 실증 완료. 일반적인 우월성·인간 수용과 다름 |
| C: Plastic/Rust/Wood/Crystal/Laser 전이 | fixture·비교 실증 존재. 현 baseline 5자산 납품 성공과 다름 |
| D: Standard/AQ·과거 증거·승인·복구·package 호환 | 기존 검증 근거 보존 |
| E: clean source·새 baseline의 5자산 실제 성공 | **미완료** |
| F: delivery·인간 판정·Activation 재평가 | **미완료** |

마지막 공통 기능 수정 f55는 `build_multi_loop_side_mesh`에서 outer CCW·hole CW 정규화 후 내부 측벽을 중복 반전하던 오류와 Y축 변환 방향을 바로잡았다. 과거 payload를 자동 고치지 않았다. 당시 Python 2,605 passed / 105 skipped, Blender 5.0.1 방향·접합 19 fixture 및 V0.7~V0.9 검증이 있다. AQ 최초 timeout 실패와 같은 소스의 해당 node 재검증 통과는 모두 보존한다. 이것은 Rust 완성 렌더가 아니다.

| 자산 | 마지막 보존 결과 | 남은 문제 |
| --- | --- | --- |
| Plastic | ab39에서 실제 색/마모 paired improvement, 정상 production, GLTF package·clean import 완료 | 새로 만들지 않는다. 인간 beauty/package/Activation 미기록. 다른 baseline 실적 자동 승계 불가 |
| Rust | ab39 실제 QA·finding 후 중단. native state 0007은 `running / quality / run_integrated_quality` | 관 내부 winding 수정의 실제 자산 재검증 없음. `hollow-upper-pipe`, `folded-sheet-volume`, `rust-metal-distribution` 미해결 |
| Wood | 과거 Standard package, 후속 best-known·review terminal 보존 | 파손 단면·풍화 표현, 반복 정체·예산 소진 이력 |
| Crystal | 과거 production·개발 실증 보존 | 주요 구조 finding과 수정 예산 부족 이력. 현재 성공으로 승계하지 않음 |
| Laser | 과거 production/인간 수용 package와 별도 기술 실패 이력 보존 | 과거 성공·실패·후속 수정을 구분. 새 캠페인 실행 없음 |

Plastic: `aq_rf_ab39_01p` / `aqv2-20260929t015114075784z-a16a0f35`.
Rust: `aq_rf_ab39_02r1` / `aqv2-20260929t072456688907z-c6aa698d`.
Rust [state 0007](workspaces/aq_rf_ab39_02r1/production/autonomy_v2/aqv2-20260929t072456688907z-c6aa698d/states/0007.json) SHA-256: `b488ad0858a588f8414de30022dfbf19586086e6ebd9799c77684e6a6143a0c4`.

행정적인 캠페인 종료와 native terminal은 다르다. Rust state를 cancelled/completed로 직접 편집하지 않았다. 이번 릴리스 작업은 후보·QA·promotion·delivery를 재개하지 않았다.

## 소스 연결 제약과 비용

부모 계약 `1001de3434c20a9c195ee9daf29da0f8eff65ca98ba72cb3a99d4f826dba0274`는 `ab39d9bfc8d456e1356c9042f896a9baedc46566`에 결속돼 있다. f55나 v0.9.1에 승인 재사용이 불가능하다. 기존 successor는 같은 reference 집합과 자산별 최소 1 slot, predecessor의 exact outcome을 요구한다. Plastic 잔여 slot은 0이고 Rust의 exact outcome은 없다. 잔여 build 수만으로 해결할 수 없어 멈췄다.

| 자원 | 계약 상한 | 부모 예약 | 미예약 잔여 |
| --- | ---: | ---: | ---: |
| 후보 | 9 | 2 | 7 |
| AQ build | 261 | 36 | 225 |
| 별도 closure | 186 | 42 | 144 |
| QA | 93 | 21 | 72 |
| promotion | 52 | 11 | 41 |
| delivery | 9 | 2 | 7 |

후보 잔여는 Plastic 0, Rust 1, 나머지 각 2다. 예약은 실제 사용과 다르며 미사용 예약을 환급하지 않는다. Rust state QA counter 0과 실제 7-pass QA 1회가 함께 존재한다. 실제 실행 비용을 0으로 만들지 않는다. 전체 계보·추가 자원은 [feasibility 원본 보존본](reports/reference_fidelity_closeout/v0.9.1/archive/rf-winding-fix-20260929-run01/evidence/successor-feasibility.json)에 있다.

## 성과를 섞지 않는 기준

- 과거 fix3의 기술 5/5 production/package/import, 24632의 Plastic·Rust 성공은 그대로 보존한다.
- ab39의 Plastic은 기술·paired improvement 1/5, 해당 캠페인의 인간 beauty/package/Activation 각각 0/5다.
- f55 baseline은 자산 실행 0/5였다. v0.9.1에서는 새 자산 캠페인이나 baseline을 만들지 않았다. 이것을 누적 성과 0/5라고 설명하지 않는다.
- 과거 Standard/R5D 인간 수용을 현재 캠페인에 승계하지 않는다. scope 승인·자동 policy·릴리스 고정·종료 결정은 인간 품질 수용이 아니다.

## 보존·정리와 향후 재개 절차

문서는 이 프로젝트를 기본 위치로 사용한다. [정리 결과와 제외 항목](docs/reference_fidelity_closeout/CLEANUP_RESULT_KO.md), [보존 복사본과 SHA-256 매핑](reports/reference_fidelity_closeout/v0.9.1/project-preservation.json), [검증 복제본 보존 매핑](reports/reference_fidelity_closeout/v0.9.1/clone-preservation.json)을 먼저 확인한다. 원래 machine JSON의 절대경로는 바꿔 쓰지 않았다. 삭제한 검증 scratch는 검증된 source bundle·lock·명령으로 필요할 때 재현하는 자료이며 운영 workspace가 아니다.

1. 별도 사용자 요청의 목적부터 확인한다. 이 종료 결정을 무효로 보고 예전 5자산 캠페인을 자동 재개하지 않는다.
2. 현재 AGENTS.md, Git/tag/status, 프로세스, 계약·state·receipt 해시를 읽기 전용으로 확인한다. 사용자 변경을 보존한다.
3. 이 문서와 cleanup receipt의 실제 보존 위치를 읽는다. 삭제된 임시 경로를 여전히 실행 가능한 경로로 가정하지 않는다.
4. 완료 Plastic 및 기존 package를 활용한다. 보존한 전후 소스를 일부러 악화시키거나 처음부터 재제작하지 않는다.
5. 실제 사용자가 겪는 문제만 구조·국소·재질 중 원인에 맞게 좁힌다. 공통 소스 수정과 예산 증액은 별도 지시 없이 기본 0이다.
6. 기존 host·권한·잔여 자원 안에서 가능한지 확인한다. source 연결 제약이 남으면 보고하고 멈춘다. 새 parent·epoch·baseline이나 JSON 편집으로 우회하지 않는다.
7. 캠페인 실행을 명시적으로 요청받은 경우에만 `aq-one-prompt-orchestrator`를 사용한다. 실행 승인 후 실제 렌더 → finding → 원인별 수정 → 동일 조건 비교 → terminal → package/import를 수행한다.
8. 효과가 없거나 한도를 소진하면 최선 결과와 남은 finding을 보존한다. 자동 판정을 인간 수용으로 기록하지 않는다.

재개 요청 예시:

> 프로젝트의 HANDOFF_KO.md와 현재 AGENTS.md를 먼저 읽고, 내가 이번에 요청하는 실제 자산 문제만 조사해. v0.9.1 태그·기존 결과·계약·소비·cleanup receipt를 재검증하고, 완료 Plastic을 재작성하거나 전체 5자산 캠페인을 자동 재시작하지 마. 기존 경로와 권한 안의 최소 작업 및 중단 조건을 제시해.
