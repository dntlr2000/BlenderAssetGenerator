# 2026-10-08 소스 체크포인트 반영 및 정리 후보 검토

- 대상 프로젝트: `E:\Playground\BlenderAssetGenerator`
- 입력: `C:\Users\Woosik\Downloads\BAG_Current_Source_Checkpoint_20261008.zip`
- 작업 ID: `bagcp-261008-5a25f0af`
- 검증·롤백 증거: `E:\CodexValidation\bagcp-261008-5a25f0af\evidence`
- 격리 검증 경로: `E:\CodexTemp\bagcp-261008-5a25f0af\repo`

## 입력 구조와 반영 범위

압축은 프로젝트 전체 복제본이 아니라 기준 커밋에 적용할 overlay이다. 압축 최상위에는
안내용 `README.md`, `CHECKPOINT_MANIFEST.json`, `EXPECTED_FINAL_TREE.json`과
`overlay/`가 있다. 최상위 안내 README는 프로젝트 README로 복사하지 않는다.

| 항목 | 확인 결과 |
| --- | --- |
| 압축 엔트리 | 327개: 안내·매니페스트 3개 + overlay 파일 324개 |
| 기존 파일 수정 | 96개 |
| 체크포인트 신규 파일 | 228개 |
| 삭제 지시 | 0개 |
| 추가 유지 문서 | 이 보고서 1개 |
| 최종 변경 경로 | 325개: 수정 96개 + 추가 229개 |
| 최종 추적 파일 수 | 1,774개 |

소스 115개, 테스트 98개, 스키마 61개, 문서 37개, 스크립트 6개, 프롬프트 2개,
설정·ignore 2개와 생성 투영 파일 3개가 원래 overlay에 포함된다.
형상 부착/relief, authored material identity split, paired revision, authored UV/atlas,
LOD/optical volume 및 관련 QA·납품 계약이 주요 변경 범위다.

검사 당시 브랜치는 `Dots`, 작업 트리와 index는 깨끗했으며 기준 커밋과 정확히 일치했다.
모든 overlay 파일의 SHA-256, Git blob, 기준 파일과 최종 전체 경로·모드를 검사했다.
경로 탈출, 중복/대소문자 충돌, 링크 엔트리 및 매니페스트에 없는 파일을 검사했다.

- ZIP SHA-256: `b4adc9727a0f62b8bf600ac802452372c2f8a6eaead82987f62adf19447d6cb1`
- 기준 커밋: `634de794d7694457b5e6a5bfd4a24ea75f1bc4b6`
- 기준 tree: `b23bace0a76419d6fdcd869cad71dc4634544d4c`
- 원본 overlay 재현 tree: `738b53baf55db74cf76e269a09a89a9e9c9517bb`

최종 tree는 아래 Windows 보정과 이 보고서 때문에 원본 overlay tree와 다르다.
실제 반영 파일 해시와 최종 tree는 외부 증거 `applied-update.json`에 기록한다.
README, REPOSITORY_TREE, FILE_MANIFEST는 의도한 파일을 index에 올린 뒤 공식 생성기로
재생성한다. 최종 변경만 stage하며 커밋·push는 하지 않는다.

프로젝트 버전 0.9.1과 SceneSpec 0.2.0을 유지한다. `.env`, `cbm.toml`, `pyproject.toml`,
`uv.lock`, `AGENTS.md`를 보존하며, 사용자 workspaces/input·승인·히스토리·기존 산출물은
반영 대상에 포함하지 않는다. 기존 작업을 로드하거나 마이그레이션하지 않는다.
`.codex/config.toml`의 변경은 체크포인트가 선언한 도구 13개 추가이며, 임의 실행 권한을
추가하는 변경은 아니다. 공개 CLI/MCP, 스키마 투영, 문서 및 기존 계약과의 연결을 검토했다.

## 로컬에서 확인하고 보정한 사항

1. **안정적인 파일을 변경된 파일로 오인하는 Windows ctime 비교**:
   `authored_split_runtime._bounded_file`에서 path stat과 descriptor fstat의 ctime 의미가
   다른 환경을 확인했다. 두 API 간에는 파일 ID·크기·수정시각을 비교하고, 각 API의 전체
   메타데이터는 읽기 전후로 각각 비교한다. 해시·바이트 한도·경로 차단·파일 변경 감지는
   유지했다. 안정된 ctime 차이와 실제 descriptor ctime 변경을 구분하는 회귀 테스트를 추가했다.
2. **Windows 긴 경로**: 공통 attachment 읽기, authored binary 읽기와 immutable publish의
   실제 I/O에 기존 `native_io_path`를 사용했다. 260자를 넘는 경로의 읽기·해시 검증·신규 게시·
   같은 바이트 재사용·다른 바이트 덮어쓰기 거부를 검사했다. Blender 실행으로 이 문제가
   나타났던 authored material continuation과 GLB clean import도 다시 통과했다.
3. **테스트 fixture 이식성**: conversion artifact 상대경로를 POSIX 표기로 만들고, 긴 경로
   fixture의 생성 및 spy에도 실제 native I/O를 적용했다. junction 거부 시험의 mock은
   lexical/extended 경로를 같은 파일로 인식하도록 고쳤다. 차단·검증 assertion은 유지했다.
4. replay 스크립트의 공백만 들어 있는 두 줄을 정리했다.

소스 추가·수정 메서드에는 기능 주석/docstring을 두었다. 변경 내역은
`local-compatibility-fixes.diff`와 `final-update.diff`로 원본 overlay와 구분하여 보존한다.

## 실행 검증과 한계

Windows에서 Python 3.14.6, Blender 5.0.1 (`a3db93c5b259`)을 사용했다.
검증마다 `TEMP`/`TMP`, uv/Ruff cache, Blender 사용자 경로와 workspace를 작업 전용 E: 경로에
지정했다. sandbox의 경로 접근 제한으로 실패한 최초 실행은 통과로 계산하지 않았다.
후속 검증은 승인된 일반 사용자 실행 문맥에서 별도 로그로 수행했다.

| 실행 | 관찰 결과 |
| --- | --- |
| `uv sync --frozen --extra dev --extra vision` | 격리 복사본 의존성 준비 성공; 현재 프로젝트 dry-run도 변경 불필요 |
| Ruff·agent 지침·incident literal·catalog·diff 검사 | 원본의 trailing whitespace 보정 후 통과; 최종 stage 후 다시 검사 |
| Python/JSON schema 검증 | Python 825개 syntax, schema 451개 meta, model projection 447개 일치 |
| 전체 pytest 1회 | **4,828 passed, 28 failed, 165 skipped**, 5,021개, 약 24분 |
| Windows I/O 보정 회귀 | **41 passed, 12 deselected**; 제외된 보안 시나리오는 전체 실행 실패 기록에 남음 |
| UV/revision fixture 보정 후 관련 시험 | **82 passed, 3 deselected**; junction 모사 거부 시험 포함 |
| 실제 Blender 신규 경로 | **15 passed**: authored split 2개, contour/profile relief 12개, LOD 1개 |
| `cbm doctor`, `cbm blender-compat` | 통과; GLB/FBX/OBJ exporter 실제 실행 |
| 기존 geometry_showcase 예제 | import/build/render/inspect/validate 통과; 16 mesh, 12 family, 4 material; 대표 렌더 확인 |

전체 실행의 28개 실패 중 3개는 위 fixture 보정 후 관련 시험에서 통과했다.
나머지 **25개는 미통과 상태**로 남긴다. 21개는 symlink 생성 권한 부족(WinError 1314),
4개는 읽는 중인 파일을 테스트가 replace/unlink하려 할 때 Windows가 먼저 차단하는
문제(WinError 5/32)였다. 권한 설정을 변경하거나 assertion을 제거하거나 skip 처리해서
통과시키지 않았다. 따라서 **전체 pytest green 또는 모든 보안 부정 시험 통과를 주장하지 않는다.**
최종 수정 후 전체 suite를 다시 실행한 결과가 아니라, 최초 전체 실행과 명시한 후속 시험의
조합이다. 실제 symlink 교체 시나리오는 해당 권한·파일 공유 조건을 갖춘 환경에서 재검증이 필요하다.

165 skipped에는 opt-in/native 조건 등이 포함되며 통과 수에 넣지 않는다. 별도 실행한
15개 Blender 시험만 실제 native 검증으로 표시한다. 생산 자산의 외관 승인, package 승인,
Unity/Unreal 실행 또는 전체 V0.7–V0.9/AQ 게이트 통과를 의미하지 않는다.
이전 기록과 새 기록을 재분류하지 않았다.

## 기존 프로젝트의 정리 후보

다음 크기는 링크 대상을 따라가지 않고 측정한 일반 파일의 논리 크기다.
후보 분류는 삭제 승인이 아니며 **기존 프로젝트 파일은 이번 작업에서 삭제하지 않는다.**
전체 상세 목록은 외부 증거 `cleanup-inventory3.json`에 있다.

| 경로 | 측정 크기 | 판단 및 조건 |
| --- | --- | --- |
| `src/`, `tests/`, `scripts/` 아래 `__pycache__` 41개 | 20,967,123 bytes, 약 20.0 MiB | 우선 후보. 재생성 가능한 Python bytecode이며 추적 소스가 아니다. 사용 중인 Python/Blender가 없을 때 정리 가능 |
| `reports/v08_smoke`, `reports/v07_smoke`, `reports/v09_smoke` | 합계 약 2.35 GiB | 조건부 후보. 이전 검증 중간 산출물 비중이 크지만 문서·receipt 참조를 먼저 확인하고 필수 원본 증거를 분리해야 함 |
| `reports/` 전체 | 3,397,468,835 bytes, 약 3.16 GiB | 일괄 삭제 금지. 위 후보 외에도 승인/검증/재현에 필요한 자료가 섞임 |
| `output/` | 249,557,880 bytes, 약 238.0 MiB, 189파일 | 조건부 개별 검토. 최종 보고서일 수 있음. 검사한 PDF의 동일 해시 중복 그룹은 없었음 |
| `.codex_uv_cache/` | 1,762 bytes | 재생성 가능하지만 절감 효과가 거의 없음. 공유/사용 여부 확인 필요 |

다음 항목은 크기만으로 정리 대상으로 분류하지 않았다.

| 보존 경로 | 측정 크기 | 보존 이유 |
| --- | --- | --- |
| `workspaces/` | 13,696,179,243 bytes, 약 12.76 GiB | 사용자 입력·현재 작업·승인·불변 히스토리. 기존 scratch에 링크 1개도 있어 루트 일괄 정리 금지 |
| `workspace_archive/` | 3,456,458,830 bytes, 약 3.22 GiB | 완료 작업 및 재개/롤백용 불변 기록 |
| `.venv/` | 278,356,263 bytes, 약 265.5 MiB | 현재 동작 환경. 의존성 dry-run에서 그대로 사용 가능 |
| `verification/` | 10,271,180 bytes, 231 추적 파일 | 저장소가 관리하는 검증 증거 |
| `.codex-remote-attachments/` | 203,533 bytes, 1 추적 파일 | 추적되는 원본 첨부 |
| `.cbm/`, `production/` | 소량/빈 운영 디렉터리 | 파이프라인의 운영 경로로 보존 |

큰 reports 디렉터리를 지운 뒤 gate가 통과한다고 판단하거나, 오래된 작업을 새 정책으로
일괄 삭제해서는 안 된다. 실제 정리는 선택된 하위 경로별 참조·소유권·잠금 확인 후 진행한다.

## 롤백 및 이번 작업 임시 산출물 정리

`rollback-originals.zip`에 덮어쓰는 기존 96개 파일의 원래 바이트를 보관하고,
`baseline_target_sha256.json`과 `rollback-git-index.bin`으로 원래 식별정보/index를 보존한다.
`applied-update.json`은 추가·수정 파일별 최종 해시를 담는다. 롤백이 요청되면 이후 사용자
편집 여부를 먼저 대조하여 이번 변경만 되돌려야 한다. 전체 Git reset/clean을 사용하지 않는다.

이번 작업에서 만든 추출본, 검증 복사본, 전용 .venv/cache, 중복 렌더·pytest scratch는
필수 증거를 분리하고 프로세스·링크·소유권을 확인한 뒤 정리한다. 원본 ZIP과 기존 프로젝트
캐시는 정리 대상이 아니다. E: 작업 전용 루트 밖을 재귀 삭제하지 않는다.

보존 항목은 원본 archive 매니페스트, 반영/롤백 자료, 정확한 명령·버전·소스 식별정보,
전체 테스트와 후속 시험의 핵심 로그/XML, 문제 재현 정보, 대표 Blender 출력이다.
원래 증거 내용과 내부 실행 경로는 고치지 않고 `retained-evidence.json`에 보존 위치를 매핑한다.
최종 제거 용량·잔여 항목·이유는 외부 `cleanup-receipt.json`에서 확인한다.
