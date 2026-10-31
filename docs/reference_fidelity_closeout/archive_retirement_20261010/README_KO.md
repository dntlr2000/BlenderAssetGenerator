# 과거 scratch 보관소 폐기 기록 — 2026-10-10~11

사용자는 과거 검증을 이어서 진행할 계획이 없어 용량을 확보하려고 `E:\CodexValidation\bag-v091-scratch-archive-20260930-run01` 폴더의 삭제를 명시적으로 요청했다. 이 결정은 과거 검증 결과의 취소·재분류나 reference-fidelity 캠페인의 재개가 아니다.

## 범위와 보존 사유

삭제 대상은 위의 단일 외부 보관소다. 이 보관소는 2026-09-30에 프로젝트의 과거 `.b/.t/.tmp` 임시 산출물을 외부로 복사한 자료이며 현재 프로젝트의 제작 소스·실제 workspace가 아니다. 프로젝트 소스, 원본 reference, canonical, QA, approval, package, terminal과 다른 보관소는 삭제 범위에 포함하지 않는다.

아래 파일은 삭제 전에 원본과 SHA-256 일치를 확인한 최소 이력 사본이다. 원본 경로·수치·판정은 바꾸지 않았다. Git에서도 원본 바이트를 유지한다.

- [이전 완료 receipt](completion-receipt.json): 당시 정리 범위·검사·보존량을 설명한다.
- [복사 요약](copy-summary.json), [삭제 적용 요약](apply-summary.json): 당시 복사와 프로젝트 사본 제거를 구분한다.
- [메타데이터 압축 기록](metadata-compression-receipt.json): 당시 manifest 압축의 이력을 남긴다.
- [과거 링크 locator](historical-evidence-locator.json): 역사 문서의 `.b/fid` 링크 13개가 무엇을 가리켰는지 남긴다.
- [이번 폐기 목적과 보존 해시](retirement-intent.json): 현재 요청·Git 기준·보존 사본의 해시를 기록한다.

**이 파일들은 과거 이력 요약이며 완전한 복원용 백업이 아니다.** 보관소 삭제 후 그 안의 payload, 대형 manifest, 원본 로그·복원 검사 파일은 사라진다. 위 receipt와 locator에 남은 옛 절대경로도 더 이상 사용 가능한 링크가 아니다. 동일한 검증을 재현하려면 별도로 남아 있는 소스·입력·환경을 다시 확인해야 하며, 이 보관소만으로는 복원할 수 없다. 역사 문서와 machine JSON의 옛 경로·hash를 수정해 남아 있는 것처럼 보이게 하지 않는다.

## 실제 삭제 결과

삭제는 **2026-10-11 00:00:16~00:03:20 KST**에 완료했다. 대상 폴더는 없어졌으며 삭제 오류·잔여 항목은 0개다. [실제 삭제 receipt](deletion-receipt.json), [삭제 전 전체 크기 조사](target-inventory-longpath.json), [경로·프로세스·보존 해시 점검](delete-preflight.json)을 함께 보존한다.

| 항목 | 결과 |
| --- | ---: |
| 삭제한 일반 파일 | 718,358개 |
| 삭제한 디렉터리(대상 루트 포함) | 564,111개 |
| 삭제 파일 논리 크기 | **6,646,902,689 B = 6.647 GB = 약 6.19 GiB** |
| 삭제 직전 E: 여유 공간 | 95,102,222,336 B |
| 삭제 직후 E: 여유 공간 | 103,471,734,784 B |
| 삭제 구간 여유 공간 관측 증가 | **8,369,512,448 B = 8.370 GB = 약 7.79 GiB** |
| 원본 바이트로 보존한 이전 요약/locator | 5파일, 28,156 B |
| ACL·소유권 변경 / 링크 대상 접근 | 0회 / 0회 |
| 다른 과거 폴더 삭제 | 0회 |

논리 길이는 디스크 할당량이 아니다. 여유 공간 증가는 삭제 구간의 관측값으로 NTFS 메타데이터·할당 회수와 다른 작업의 디스크 활동도 포함할 수 있으며, 전체 8.370 GB를 일반 파일 길이의 합계로 해석하면 안 된다. 이번에 남긴 소형 정리 기록의 보존 비용은 별도다. 과거 프로젝트 scratch 정리의 확보량은 이번 수치에 합산하지 않았다.

삭제 전에 대상과 상위 경로가 일반 디렉터리인지 확인했고, 전체 조사에서 링크·읽기 오류·읽기 전용 파일은 모두 0개였다. 첫 읽기는 Windows 긴 경로 제한 때문에 일부 누락됐으므로 삭제 판단에 쓰지 않았으며, 긴 경로를 지원하는 재조사의 완전한 값을 사용했다. 그 재조사는 당시 완료 receipt의 전체 크기와 일치했다(당시 집계에 제외됐던 완료 receipt 12,510 B 포함).

현재 source·설정·실제 workspace·보고서·production·workspace_archive에서 보관소 이름을 직접 참조하는 파일은 발견되지 않았다. 이는 문자열 참조 조사 결과이며 새 자산 제작 전체의 실행 검증을 뜻하지 않는다. 보호된 자산/소스 경로에는 삭제 명령을 적용하지 않았다.

## 문서와 후속 정리

[인계 문서](../../HANDOFF_KO.md), [저장공간 안내](../STORAGE_ORGANIZATION_KO.md), [문서 목차](../../README.md)의 현재 링크를 이 기록으로 연결했다. 원래 역사 receipt 안의 옛 경로는 그대로 두고 이 문서에서 폐기 상태를 설명한다.

추가 후보의 실제 용량·보존 조건은 [추가 정리 후보](../CLEANUP_CANDIDATES_20261010_KO.md)에 있다. 이번 작업은 이 후보들의 삭제 권한을 만들지 않는다. 새 캠페인·source 변경·commit·push·tag 이동은 수행하지 않는다.

## 검사 범위와 관측한 제한

현재 CLI를 Python 모듈로 실행한 `python -m codex_blender_modeler.cli doctor`는 repository/workspace/Blender/Codex 경로 확인을 통과했다. 별도 `cbm.exe doctor` 직접 실행은 `uv trampoline failed to canonicalize script path`로 실패했다. launcher의 문제는 이번 정리에서 수정하지 않았으며 삭제와의 인과관계를 확인한 것은 아니다. 성공한 모듈 호출과 실패한 launcher 호출을 모두 기록한다. 전체 pytest·Blender 제작·새 package/import를 실행한 결과로 확대하지 않는다.

프로젝트 지침의 192개 invariant, 현재 안내의 로컬 링크 75개, 이전 보존 사본 5개의 SHA-256, repository summary 및 Git whitespace 검사를 확인했다. 원본 JSON의 CRLF를 유지하기 위해 이 보존 폴더의 Git 속성에만 CRLF 허용을 명시했고 다른 공백 검사는 유지했다. 자세한 실행 기록은 [이번 작업 증거](E:/CodexValidation/bag-archive-retirement-20261010-run01/evidence/)에 남긴다. 이번에 작성한 임시 helper는 실행 증거로 보존한 뒤 고유 `E:\CodexTemp` 작업 폴더에서 정리한다.
