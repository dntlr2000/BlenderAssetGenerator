# Standard Skill Orchestration 실제 자산 기준선 — 2026-08-26

이 묶음은 현재 소스 게이트와 두 Standard 자산의 실제 사용자 승인 E2E를 함께 결속한다.
최종 판정은 `passed_with_declared_quality_and_format_limits`다. 상세 해시와 실행 결과는
[`standard_asset_evidence.json`](standard_asset_evidence.json), 원본 stdout은 [`logs/`](logs/)에 있다.

## 소스 및 격리 게이트

| 검사 | 결과 |
| --- | --- |
| `uv sync --frozen --extra dev --extra vision` | 51 packages, exit 0 |
| Ruff | sandbox/host 모두 통과; sandbox는 보존된 접근 불가 scratch 경고 기록 |
| 집중 pytest | sandbox `WinError 5` attempt 보존 후 host retry `180 passed` |
| 전체 pytest | `1987 passed, 63 skipped, 8 warnings` |
| doctor / Blender compatibility | Blender 5.0.1, Blender Python 3.11.13, GLB/FBX/OBJ 통과 |
| agent instruction checker | 18 files, 192 invariants 통과 |
| V0.7 / V0.8 / V0.9 격리 게이트 | 모두 exit 0; 각 게이트의 전체 pytest도 `1987/63/8` |
| AQ readiness gate | `915 passed, 26 skipped, 8 warnings`; profile 비활성 유지 |
| repository projection | system Python dependency 실패 보존 후 frozen `uv` write/check 통과 |
| repository summary 집중 회귀 | top-level status 계약 실패 `5/1` 보존·수정 후 `6 passed` |

## 실제 Standard 자산

| 자산 | 최종 상태 | 품질 | 패키지 |
| --- | --- | --- | --- |
| `item_plastic_standard_canary_01` | completed, exact human acceptance/final approval | score `0.744321→0.795028`, IoU `0.674717→0.718917`; `direct.global_silhouette` high 수용 | manifest `4833a6ff…`, clean import 1/6/0, coverage 1.0, bounds error 0 |
| `collectible_cloth_01` | completed, exact human acceptance/final approval | score `0.861737→0.862142`, IoU `0.784956→0.812281`; `direct.global_silhouette` medium 수용 | manifest `866e70cc…`, clean import 1/6/0, coverage 1.0, bounds error 0 |

플라스틱은 **accepted Standard canary with declared silhouette limitation**이며 완벽한 quality pass로
재분류하지 않는다. 천 자산의 fresh V0.6은 정확히 7개 canonical pass와 2/2 surface-detail binding을
검증했다. 별도 post-material 5-view/20-pass assembly는 구조 통과와 시각적 coherence만 확인한
advisory이며 reference similarity는 `unscorable`이다.

## 잔존 한계와 AQ 진입 판정

- 천 evaluated UV mesh에는 이전 수용 상태와 동일한 degenerate UV triangle 1,152개가 남는다.
- 두 GLB clean import에는 axis/units metadata, custom normal/tangent equivalence, UV association/summary에
  관한 6개 경고가 각각 남는다.
- AQ readiness는 `ready`다. 다만 AQ v2는 계속 `disabled_experimental`이고 실제 AQ 자산 실행,
  profile activation, campaign 생성, AQ Blender 실행은 모두 0이다.
- AQ 실제 실행에는 별도 명시적 opt-in과 exact asset/session authority가 필요하다.
- Unity/Unreal runtime parity는 검증하지 않았고 destination project를 수정하지 않았다.

원본 로그는 기술 실패 attempt와 로컬 실행 경로를 감사 가능하게 그대로 보존한다. 따라서 이 신규
묶음의 stdout에는 절대 호스트 경로가 포함될 수 있지만, 이를 portable package 경로나 destination
지원 증거로 해석하지 않는다.
