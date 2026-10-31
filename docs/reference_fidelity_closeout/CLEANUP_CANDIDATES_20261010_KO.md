# 추가 저장공간 정리 후보 — 2026-10-10~11

이번 표는 **조사 결과이며 삭제 승인이 아니다**. 이번에 실제로 삭제하도록 요청받은 것은 [별도 scratch 보관소](archive_retirement_20261010/README_KO.md) 하나뿐이다. 아래 과거 자료는 그대로 유지한다.

## 조사 기준

현재 소스는 `Dots` 브랜치의 `ca81eb719dd499d043ce4877c3153dcde489e25a`다. `E:\CodexValidation`·`E:\CodexTemp`의 BlenderAssetGenerator/reference-fidelity 관련 작업 폴더와, [10월 8일 검사](../verification/BAG_CHECKPOINT_UPDATE_20261008_KO.md)에 이미 나온 프로젝트 후보를 다시 측정했다. 다른 프로젝트의 검증 폴더와 공용 temp 루트 전체는 조사·정리 대상으로 확대하지 않았다.

크기는 일반 파일의 **논리 길이**이며 GB는 1,000,000,000 bytes다. NTFS 할당량·하드링크·필수 증거 보존량 때문에 실제 회수량과 다를 수 있다. 폴더 전체 크기를 삭제 가능한 크기로 단정하지 않는다. 긴 경로를 지원하는 읽기 방식으로 재조사한 최종값을 사용했고 링크 대상을 따라가지 않았다.

## 용량과 보존 비용을 고려한 후보

| 후보와 정확한 경로 | 현재 측정 크기 | 권장 처리와 선행 조건 |
| --- | ---: | --- |
| 과거 smoke 검증 복제본: 프로젝트 `reports/v07_smoke`, `reports/v08_smoke`, `reports/v09_smoke` | **2,526,401,116 B, 2.526 GB**, 27,748파일 | 용량상 최우선 조사. 각 run의 최종 receipt·실패 재현·문서 참조 원본을 먼저 분리한 뒤 중복 workspace/build/render를 선별한다. 세 루트 일괄 삭제는 권하지 않는다. |
| `E:\CodexValidation\bag-v091-residual-cleanup-20260930-run01` | **969,425,356 B, 0.969 GB**, 161,217파일 | 이번 폐기 대상과 별개의 과거 임시파일 보관소. 남겨 둔 48개 임시 루트를 제거할 때 보존한 자료다. 복원 계획이 없다면 다음 폐기 후보로 적합하다. 완료 receipt·매핑 요약·삭제 사유를 먼저 남기고, payload 복원 능력의 폐기를 별도로 결정한다. |
| `E:\CodexTemp\rfd928\uv-cache` | **259,610,906 B, 0.260 GB**, 4,117파일 | 재다운로드 가능한 패키지 캐시 후보. 현재 UV_CACHE_DIR·공유 사용자·실행 중 uv/설치 작업과 하드링크를 확인한 뒤 해당 cache 경로만 정리한다. 과거에 공유 여부 미확인으로 남긴 항목이다. |
| `E:\CodexTemp\rfs929-plateau\uv-cache` | **259,738,402 B, 0.260 GB**, 4,129파일 | 위와 동일. 두 cache의 합계는 **519,349,308 B**이나 같은 환경과 파일을 공유하면 그만큼 공간이 늘지 않을 수 있다. |
| `E:\CodexValidation\rf-winding-fix-20260929-run01\evidence\cleanup-plan.json` | **94,494,560 B, 94.49 MB** | 폴더 전체 삭제 대신 이 대형 목록의 무손실 압축 후보. 원본·압축 해시와 복원 가능성을 확인하고 소비 문서의 경로를 갱신해야 한다. 공통 결함 재현·수정 검증 자료는 보존한다. 실제 압축 절감량은 아직 측정하지 않았다. |
| `E:\CodexValidation\bag-five-assets-20260930-5f74dbca\evidence\asset-inventory.json` 및 `asset-inventory-selected.json` | **71,116,735 B, 71.12 MB** | 대형 조사 목록의 압축 또는 중복 확인 후보. 작은 summary·bundle receipt·transfer index는 남긴다. 아래 자산 ZIP을 함께 삭제하지 않는다. |
| 프로젝트 `src/`, `tests/`, `scripts/` 아래 `__pycache__` 41곳 | **20,967,123 B, 20.97 MB** | 재생성 가능한 bytecode. 사용 중인 Python/Blender와 Git 추적 여부를 다시 확인한 뒤 개별 경로를 정리할 수 있으나 확보 효과는 작다. |

Smoke 세부 크기는 `v07_smoke` 992,633,565 B, `v08_smoke` 1,053,234,982 B, `v09_smoke` 480,532,569 B다. 실제 검증 문서 여러 곳에서 이 경로를 참조하므로 이름이 smoke라는 이유만으로 모두 버리면 안 된다. 현재 표는 run별 삭제 적격성 검사를 대신하지 않는다.

## 용량만 보고 제거하지 않을 자료

| 자료 | 이번 측정값 | 보존 이유 |
| --- | ---: | --- |
| `E:\CodexValidation\bag-five-assets-20260930-5f74dbca` 전체 | 384,044,787 B | 5자산과 reference 전달 ZIP·receipt가 있다. 업로드 성공 기록은 있지만 bundle receipt의 `cloud_download_integrity`는 `pending`이다. 클라우드 사본을 독립 다운로드하여 hash 검증하지 않았으므로 업로드 기록만으로 로컬 ZIP을 버리지 않는다. |
| `E:\CodexValidation\bag-v091-archive-20260930-run01` | 185,769,756 B | 현재 인계 문서가 참조하는 릴리스·종료·소스 보존 사본. 이번 삭제 대상과 이름이 비슷하지만 다른 폴더다. |
| `E:\CodexValidation\bag-rf-shell-20260920` | 185,268,503 B | 이전 캠페인의 비교 전 소스와 검증 evidence가 섞여 있다. 정리하려면 최선 결과·비교 조건·소비 기록의 보존 여부를 따로 확인해야 한다. |
| 프로젝트 `output/` | 249,557,880 B | 최종 보고서일 수 있어 파일별 사용·납품 여부 확인이 필요하다. 루트 전체 삭제 후보로 삼지 않는다. |
| `E:\CodexValidation\rf-winding-fix-20260929-run01` 전체 | 103,538,200 B | 최소 재현·수정 검증은 유지하고 위 대형 cleanup 목록만 별도로 검토한다. |
| `E:\CodexValidation\bagcp-261008-5a25f0af` | 14,248,010 B | 최근 업그레이드의 검증·미통과 시험·rollback 증거다. 과거 scratch와 함께 삭제하지 않는다. |
| 프로젝트 `.codex_uv_cache/` | 1,762 B | 공유 여부 확인에 비해 회수량이 작아 우선순위가 없다. |
| `E:\CodexTemp\wf929a` | 일반 파일 0 B | 빈 디렉터리만 남아 용량 확보 효과가 없다. |

실제 `workspaces/`, `workspace_archive/`, 원본 reference, canonical, package, approval, terminal, `.git`, `.codex`, `.cbm`, `.venv`는 이번 정리 후보에 포함하지 않았다. 후보 조사로 과거 성공·소비·인간 수용 기록을 변경하지 않는다.

## 권장 순서와 다음 작업의 경계

1. 복원 계획을 폐기한 다른 scratch 보관소라면 `bag-v091-residual-cleanup-20260930-run01`의 최소 기록을 보존한 뒤 단독 폐기를 검토한다. 약 0.97 GB 규모로 범위가 명확하다.
2. 추가 용량이 필요하면 세 smoke 경로의 run별 보존·중복 목록을 만든다. 최대 조사 대상은 약 2.53 GB이며, 필요한 증거를 제외한 뒤에만 실제 삭제량을 확정한다.
3. 두 외부 uv-cache는 공유/사용 여부를 확인해 별도로 정리한다. 대형 JSON은 증거를 잃지 않는 무손실 압축을 우선 검토한다.
4. 선택한 후보마다 실행 직전 상태·절대경로·링크·사용 여부를 재확인한다. 이번 크기 관측을 미래 삭제의 자동 승인으로 사용하지 않는다.

세 smoke 폴더·잔여 보관소·두 uv-cache의 전체 논리 크기 합계는 **4,015,175,780 B, 약 4.02 GB**다. 이는 **조사 범위의 상한**이며 확보를 보장한 용량이 아니다. 실제 삭제 가능한 양은 보존할 파일과 공유 관계를 확인한 뒤 정한다.

측정 원본과 예외·재조사 기록은 [이번 조사 증거](E:/CodexValidation/bag-archive-retirement-20261010-run01/evidence/)의 `candidate-inventory.json`, `candidate-inventory-supplement-longpath.json`, `project-candidate-inventory.json`에 있다. 첫 조사에서 Windows 긴 경로 제한으로 누락된 값은 최종 크기로 사용하지 않는다.
