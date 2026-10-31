# 사각형 중심 저작과 Cloth·Rock·Wood 검증 — 2026-11-01

## 결과와 적용 범위

시작 소스는 `Dots`의 `28b6c2c5257fc8a512edfc079e0a761f47c59e7c`이며 작업 시작 시 Git은 clean이었다.
프로젝트 버전은 0.9.1, canonical SceneSpec은 0.2.0으로 유지했다. 기존 방패, 과거 캠페인,
사용자 reference, 기존 job·approval·package·terminal은 변경하지 않았다. commit/push는 수행하지 않았다.

새 `polygon_shell`은 제한된 삼각형·사각형 데이터로 편집 원본을 만든다. 기존
StructuralGeometryCandidate → MeshPayload 0.2 → SceneSpec 0.2 `custom_mesh` 경로를 사용하며,
임의 Blender Python이나 새로운 CLI/MCP 실행 권한을 추가하지 않는다.

세 자산 모두 편집용 `.blend`의 사각형 보존과 독립 GLB import를 확인했다.
**사각형 비율 통과를 시각 품질 완료로 해석하지 않는다.** Cloth의 주요 접힘 구조는 확인했으나,
Rock·Wood는 아래에 남긴 형태·면 비틀림 한계가 있다. 정해진 후보 상한에서 종료했다.
Production package, 인간 beauty·package 수용, Activation 적격성은 이 검증의 결과가 아니다.

## 구현

| 영역 | 변경 내용 | 유지한 경계 |
|---|---|---|
| 원본 저작 | `polygon_shell`의 닫힌 outward tri/quad shell, 원본 코너 UV 보존 | 기존 `triangulated_shell`과 MeshPayload 0.1 의미 유지 |
| 검사 표현 | 실제 Blender loop triangle을 원본 면·코너에 대응시키는 `mesh_triangle_view` 0.1 | 원본 payload를 삼각형 payload로 덮어쓰지 않음 |
| 접합 검사 | surface/solid-root attachment intent 0.2에서만 polygon source와 view를 명시 선택 | 0.1은 triangle-only, single-slot·세계 좌표·무수정 형상 조건 유지 |
| 무결성 | source/view exact hash, 분할 후 triangle 예산, stage/package의 원본·view 봉인 | 과거 receipt 자동 migration 없음 |
| 직렬화 | polygon-shell의 실제 Blender 대각선을 파생 export 메시에서 유지 | author `.blend`는 수정하지 않음 |
| 토폴로지 | marked polygon 객체의 authored/evaluated 면 수·면적 비율·퇴화·경계·winding·부피·warp | object-local 진단이며 품질 점수가 아님 |

새 schema 4개와 기존 structural union·builder registry·repository catalog를 동기화했다.
CLI/MCP 진입점과 allowlist를 추가하거나 확대하지 않았다. 새 코드의 메서드에는 기능 설명을 붙였다.
세부 계약은 [polygon_authoring.md](polygon_authoring.md)를 따른다.

상세 winding·warp 검증 범위는 tri/quad 메시다. 임의 modifier가 n-gon을 만들었을 때의
fallback은 면 수·면적 등 제한된 통계이며, 모든 n-gon에서 같은 수준의 진단을 보증하지 않는다.
이번 Cloth Subdivision 결과는 실제 사각형 메시로 검증했다.

## 보존된 검증 자산

공통 evidence 루트:
`E:\CodexValidation\quad-authoring-20261101-run01\evidence`

각 job은 그 아래 `workspaces/quad_<asset>_20261101`이다. 최종 선택은 canonical 승인이 아니라
검증용 후보 선택이다. 최초 canonical authoring은 기존 write-lock 경로를 사용했고, 후속 후보는
독립 staging snapshot으로 보존했다.

| 자산 | 선택 | 원본 사각형 / 전체 면 | 사각형 면적 비율 | 최대 quad warp | GLB import |
|---|---:|---:|---:|---:|---|
| Cloth | v002 | 2,480 / 2,480 (100%) | 100% | 8.26° | 통과 |
| Rock | v003 | 1,934 / 1,938 (99.79%) | 99.90% | 81.88° | 통과 |
| Wood | v003 | 1,824 / 1,824 (100%) | 100% | 52.75° | 통과 |

Rock의 삼각형 4개는 비볼록 파단 패치 2개의 분할 결과다. 관찰 파일에 해당 패치와 사유를 기록했다.
면 수를 늘려 비율만 높이는 방식은 사용하지 않았다. Cloth는 접힘 단면과 폭 방향 격자,
Rock은 공유 경계를 가진 상부·측면 패치, Wood는 길이 방향 띠와 끝단 패치를 사용했다.

| 자산 | 편집 원본 | 실제 비교 렌더 | GLB |
|---|---|---|---|
| Cloth | [author.blend](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_cloth_20261101/candidates/v002/author.blend) | [beauty.png](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_cloth_20261101/candidates/v002/qa/passes/beauty.png) | [cloth.glb](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_cloth_20261101/exports/validation_01/cloth.glb) |
| Rock | [author.blend](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_rock_20261101/candidates/v003/author.blend) | [beauty.png](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_rock_20261101/candidates/v003/qa/passes/beauty.png) | [rock.glb](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_rock_20261101/exports/validation_01/rock.glb) |
| Wood | [author.blend](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_wood_20261101/candidates/v003/author.blend) | [beauty.png](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_wood_20261101/candidates/v003/qa/passes/beauty.png) | [wood.glb](E:/CodexValidation/quad-authoring-20261101-run01/evidence/workspaces/quad_wood_20261101/exports/validation_01/wood.glb) |

각 export 폴더의 `clean_import/imported.blend`와 `report.json`이 독립 import 결과다.
모든 최종 파일의 정확한 SHA-256, source-bound finding, 비용은
[asset_results.json](E:/CodexValidation/quad-authoring-20261101-run01/evidence/asset_results.json)에 기록했다.

### 관찰과 한계

- Cloth: 네 층의 연속된 얇은 표면, 돌아 접히는 곡면, 앞쪽 간격을 확인했다. v001보다 v002의
  간격과 넓은 주름이 명확하다. 실제 Subdivision level 1 진단은 원본 2,480면을 보존하면서
  evaluated 9,920 사각형을 만들었다. 접힘은 여전히 이상화되어 있으며 직조·미세 주름은 범위 밖이다.
- Rock: v001의 과도하게 부드러운 반복 층을 줄이고 각진 외곽과 실제 높낮이를 확보했다.
  자연스러운 절단 분포는 부분 충족이며, flat shading에서 규칙적인 패치 행이 드러난다.
  일부 81.88° warped quad 때문에 좋은 편집 면 구성까지 완전히 입증했다고 보지 않는다.
- Wood: 길이에 수직인 과도한 물결을 줄이고 길이 방향 홈과 국소적인 상부 갈라짐을 남겼다.
  끝단 파손·갈라짐 분기는 단순하고 둥글며, 일부 끝단·홈 주변 quad warp가 52.75°다.
  나뭇결 텍스처·마모 색 변화는 범위 밖이다.

모든 최종 후보에서 열린 경계·비다양체 edge·edge winding conflict·퇴화 면은 0이었다.
기존 bounded exact triangle self-intersection 검사는 각각 4,960 / 3,872 / 3,648 triangles를
검사해 교차 0을 기록했다. 검사 한도나 pair budget은 늘리지 않았다. 이는 해당 표현에 대한
검사 결과이며 모든 가능한 변형·Subdivision 이후의 자기 교차 보증이 아니다.

실제 메시 복사본에서 중앙 띠 정점을 2 mm 이동하고 정확히 되돌리는 편집 진단도 수행했다.
이 진단은 편집 가능성의 제한된 실증이며 수작업 리토폴로지 품질이나 변형 리그 보증은 아니다.

최초·최종 QA의 실제 camera fingerprint, 조명, world, 해상도, 색 관리 조건은 같았다.
Cloth v001의 Subdivision 보조 뷰는 두 모서리가 잘려 진단 한계로 남겼고, v002에서는
원래 QA 카메라 scale을 사용했다. 이 두 보조 뷰를 엄밀한 전후 비교로 계산하지 않았다.
형태 전후 비교는 동일 조건인 canonical beauty와 고정 관찰에 근거했다. IQ 점수를 품질 KPI로 사용하지 않았다.
최종 읽기 전용 [비교 조건 재확인](E:/CodexValidation/quad-authoring-20261101-run01/evidence/paired_render_conditions_audit.json)에서도
세 쌍의 실제 조명·world·색 관리·camera fingerprint·해상도가 일치했고, source 및 7-pass 해시를 확인했다.
기존 `asset_results.json`의 비교 조건 해시도 이 독립 재계산과 모두 일치한다.

## 입력과 재현

실측이 없는 concept 자산이다. 크기와 보이지 않는 면은 관찰된 사실이 아니라 가정이다.
기본 재질은 Cloth 베이지, Rock 회색, Wood 갈색이며 roughness 0.82 / metallic 0이다.

| 입력 | SHA-256 |
|---|---|
| `item_cloth.png` | `f6bb3c910565aaab9b6b16a876e96ae2b2aee09a5cfdf1c078ed42f8c33ca023` |
| `item_rock.png` | `796b8b8ffdc14c9420db139cde50eaffcd5ffd3472fba1464bf14c567de8000d` |
| `item_wood.png` | `b1312fedd5c1cfab2c7a1c522157442b1a3c543398612e8d02d4672af7df8fc7` |

`input/`에는 host가 복사한 reference, 후보별 폴더에는 관찰·recipe·MeshPayload·SceneSpec·
materialization report·build/inspect command·author blend·QA·diagnostics·finding을 보존했다.
원래 reference 파일은 변경하지 않았다. 이미지 생성 도구는 사용하지 않았다.

실행 Blender는 `C:\Program Files\Blender Foundation\Blender 5.0\blender.exe`, 버전은 5.0.1이다.
TEMP/TMP는 `E:\CodexTemp\quad-authoring-20261101-run01`, CBM_WORKSPACE_ROOT는 외부 evidence의
`workspaces`를 사용했다. 빌드·검사·export·import의 실제 command와 로그를 후보별로 보존했다.

Rock v003은 `scene_spec_corrected.json`이 최종 source다. 최초의 flat MeshPayload와
`shade_smooth=true` 충돌은 build 전 host가 거부했다. 원본 SceneSpec은 보존하고, smoothing
플래그만 false로 교정한 별도 파일·양쪽 해시·실행 스크립트를 남겼다. 형상 후보를 추가하지 않았다.

## 유한 비용

| 항목 | 실제 사용 | 허용 상한 |
|---|---:|---:|
| 형상 후보 | Cloth 2, Rock 3, Wood 3 = 8 | 9 (각 3) |
| canonical 7-pass 세트 | 8 (56장) | 9 |
| 중립 보조 진단 이미지 | 32 | 36 |
| 자산 GLB export·독립 import 쌍 | 3 | 6 |

자산용 materialization 8회, author build 시도 9회, inventory 시도 9회를 별도로 계상했다.
추가 build 1회는 Rock smoothing 충돌의 기술 교정이다. 추가 inventory 1회는 새 진단 모듈의
standalone import 경로 오류 수정 후 Cloth 원본을 재검사한 것이다. 최초 Cloth 준비의 잘못된
GeometryIntent 필드는 Blender 실행 전에 거부됐고, 같은 후보 슬롯에서 올바른 필드로 계속했다.
이 비용과 코드 회귀용 cube·legacy fixture·compatibility 검사는 구분한다.

## 코드 검증과 보존 상태

최종 전체 pytest 선택 실행은 **4,856 passed, 166 skipped, 25 deselected**였다(28분 8초).
제외한 25개는 수정 전 `28b6c2c`에서도 같은 테스트를 실행하여 모두 재현된 Windows
symlink 권한 및 열린 파일 교체 실패다. 환경 권한을 확대하거나 보안 검사를 약화하지 않았다.
따라서 이 25개는 현재 환경에서 미검증이며 **무조건적인 전체 suite 통과로 기록하지 않는다**.

첫 전체 실행에서 나온 55개 실패 중 30개는 새 봉인 경로가 기존 partial report의 `intent`를
필수로 읽은 호환성 회귀였다. 해당 경계를 수정하고 최종 전체 실행에서 해결을 확인했다.
나머지 25개가 위 환경 실패다. 최초 실패 로그와 수정 전·후 소스 patch는 모두 남겼다.

| 검사 | 실행 결과·범위 |
|---|---|
| 새 polygon/legacy 접합 native 검사 | Blender 5.0.1 실제 build·저장·재열기·비평면 quad 삼각화 대응·GLB import 확인 |
| 최종 봉인 관련 focused 검사 | 76 passed, 1 Windows symlink 권한 실패; 해당 실패는 위 25개에 포함 |
| UV·재질·면 그룹·winding·hash·budget | 혼합 tri/quad, 두 대각선, stale/혼합 source, expanded triangle cap, late view 변조 거부 포함 |
| ruff / doctor | 통과 |
| Blender compatibility | 5.0.1 GLB·FBX·OBJ 실제 smoke 통과 |
| invariant / repository summary | 192개 invariant 및 생성 파일 일치 통과 |
| 관련 gate | 전체 Python의 V0.7–V0.9/AQ 관련 검사, framework literal, disabled-experimental Activation contract 통과 |
| AQ benchmark | v01 8개, v02 10개 통과; host-only이며 별도 Blender benchmark를 실행한 것은 아님 |

독립 V0.7–V0.9 PowerShell wrapper 전체를 별도로 반복 실행하지 않았다. 검증 명령·로그 해시와
정확한 제외 목록은 [software_validation.json](E:/CodexValidation/quad-authoring-20261101-run01/evidence/software_validation.json),
최종 테스트 원문은 [final-pytest.log](E:/CodexValidation/quad-authoring-20261101-run01/evidence/final-pytest.log)에 있다.
테스트 수는 시각 품질 성과로 계산하지 않는다.

필수 native 회귀 fixture는 파일별 SHA-256과 함께 `native_regression_final.zip` 및
`native_regression_evidence.zip`에 보존했다. 원래 임시 경로를 기록한 receipt는 수정하지 않았으며,
각 archive manifest가 원래 경로와 보관 위치를 연결한다. 최종 자산·reference·재현용 recipe·
소스 patch·대표 렌더·실패 분석 로그는 외부 evidence에 유지한다.

이번 작업에서 만든 `E:\CodexTemp\quad-authoring-20261101-run01` 안의 검증 복제본·테스트 출력·
전용 캐시 5,658개 단위를 정리했다. 논리 파일 크기 합계는 **4,465,646,596 bytes (4.47 GB)**,
삭제 구간에서 관측한 E: 가용량 증가는 **3,393,150,976 bytes (3.39 GB, 3.16 GiB)**다.
논리 크기 합과 볼륨 가용량 변화는 서로 다른 수치로 기록한다.

링크와 그 대상을 포함한 테스트 폴더 18개는 지침에 따라 남겼다. 남은 위치는 같은 임시 루트의
`p/`·`p2/`이며, 링크를 따라가지 않고 계산한 일반 파일 합계는 약 1.02 MB다. 링크 대상과
다른 작업·공유 캐시·프로젝트 원본은 삭제하지 않았다. 삭제 전후 최종 자산 및 두 native archive
해시가 일치함을 확인했다.

정확한 경로·삭제량·보존 사유는
[cleanup receipt](E:/CodexValidation/quad-authoring-20261101-run01/evidence/cleanup-receipt-20261031T182519342Z.json)에 있다.
이 receipt의 SHA-256은 `20b118e9f4570d1a797877a89f6f37bf40814cb408ea22a7a90b061f0586235a`다.
필수 증거와 자산은 위 `evidence` 아래 약 67 MB로 보존한다. 편집 원본 재사용, 실제 전후 비교,
독립 import, 호환성 실패 분석과 재현에 필요한 자료다.

최종 구현은 전체 회귀에 사용한 소스 patch와 일치하며, 그 이후에는 이 결과 문서와 생성 목록만
갱신했다. Git HEAD는 시작 commit 그대로이고 변경 45개 파일은 staged 상태로 남겼다.
commit·push·버전 변경이나 기존 캠페인 재개는 수행하지 않았다.
