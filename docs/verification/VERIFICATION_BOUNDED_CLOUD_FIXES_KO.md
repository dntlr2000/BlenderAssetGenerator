# BAG 원시 export와 한글 보고서의 제한적 수정 검증

2026-09-30. 기준 소스는 `634de794d7694457b5e6a5bfd4a24ea75f1bc4b6`이다.
이번 작업은 사용자가 승인한 공통 소스의 제한적 개선과 대표 자산 전후 검증이다.
종료된 5자산 reference-fidelity 캠페인, source-bound 승인, 예산, baseline,
Activation 및 과거 증거의 의미는 바꾸지 않는다. Commit과 push는 하지 않았다.

## 확인한 문제와 수정

### 원시 GLB와 GLTF에서 활성 modifier가 빠지는 문제

`blender_scripts/export_scene.py`는 Blender glTF exporter의 `export_apply`를
지정하지 않아 기본값 `False`로 export했다. 따라서 생성된 `.blend`에 남아 있는
bevel·array 등의 평가 형상이 원시 GLB/GLTF에서 빠졌다. CLI `cbm export`, MCP
`export_scene`, AQ review preview가 이 경로를 공유한다.

정적 mesh는 `export_apply=True`로 내보낸다. FBX와 OBJ는 이미 modifier를 적용하는
기존 기본값을 유지한다. V0.7 production은 먼저 평가 mesh를 파생 복사한 뒤
별도 exporter를 사용하므로 그 코드와 `export_apply=False`는 바꾸지 않았다.

glTF의 apply 옵션은 shape-key export를 막는다. 기존 morph 동작을 보존하기 위해
`bpy.data.objects` 전체에서 shape key가 발견되면 이전 `False` 동작을 유지하고
경고한다. 다른 scene과 collection 원본도 보수적으로 포함하며, 연결되지 않은
shape-key object도 fallback을 유발할 수 있다. CLI는 경고를 출력하고 MCP는
그 경우에만 `warnings` 필드를 추가한다. 일반 응답과 명령 인자는 그대로다.

Subdivision의 viewport/render level이 다르면 viewport 평가 형상과 최종 렌더
형상이 다를 수 있다. 이번 수정은 render-level 정책을 바꾸지 않는다.

### Linux 한글 PDF 후보 글꼴이 보고서를 중단시키는 문제

수정 전 전체 Python 검사에서 57개가 실패했고, 같은 57개 node를 변경하지 않은
기준 소스에서 다시 실행해 모두 재현했다. 설치된 `NotoSansCJK-Regular.ttc`가
PostScript outline을 사용하지만 ReportLab `TTFont`는 이를 지원하지 않았다.
첫 존재 후보를 읽다가 멈춰, 이미 마련된 후속 Korean font/CID fallback에
도달하지 못하고 review·workflow 검사까지 연쇄 실패했다.

이 결함은 원시 export 수정과 별개다. ReportLab의 글꼴 읽기 단계에서 발생한
`TTFError`만 처리하고 다음 후보 또는 기존 Korean CID fallback을 사용한다.
이 오류에는 ReportLab이 변환한 일부 파일 읽기 오류도 포함된다. 글꼴 등록이나
실제 PDF 생성 오류, hash 및 보고서 검증 실패를 통째로 숨기지 않는다.

## 같은 crown 소스로 확인한 export 보존 효과

원본 `.blend`의 SHA-256은
`ea04dab9492e0616a32b9e54b243bb004a76aeee37e26565a9259f10866025bf`이며
모든 검사 전후 동일하다. 형상 저작, 카메라, 조명, 재질은 수정하지 않았다.

| 항목 | 기존 원시 GLB | 수정 원시 GLB | 평가된 원본 |
| --- | ---: | ---: | ---: |
| 전체 triangle | 50,678 | 65,014 | 65,014 |
| crown.band | 2,048 | 8,192 | 8,192 |
| crown.base | 2,048 | 10,240 | 10,240 |
| 원본 oriented triangle fingerprint 일치 mesh | 24/26 | 26/26 | 26/26 |

독립 clean import 후 26개 mesh, 3개 material, PBR 값, world bounds와 나머지
24개 mesh가 보존됐다. Triangle 위치·winding 비교 양자화는 1e-6 m이다.
동일한 source camera·light·world의 렌더에서 원본 대비 RGB 평균 절대오차는
0–255 척도 약 1.597에서 0.000205로 줄었다.

Triangle 수 증가 자체가 품질 KPI는 아니다. 여기서는 원본에 이미 있던 두 bevel이
export에서 사라지지 않음을 교차 확인하는 수치다. 렌더 오차 역시 reference와의
미적 유사도나 인간 수용이 아니라 평가 원본 보존을 입증한다.

## 회귀 검증 범위

- Blender 5.0.1에서 GLB/GLTF/FBX/OBJ를 각각 export하고 별도 프로세스로 clean import
- Bevel, array, mirror, subdivision, solidify, decimate, 비활성 bevel,
  이미 적용된 bevel, bevel+array stack 및 수정 없는 mesh
- 평가 triangle·위치·signed volume, UV 존재와 material coverage 및 source hash
- 두 scene에 걸친 shape-key fallback, morph 이름·변위·값, 명시적 경고
- CLI/MCP 경고 전달과 기존 FBX/OBJ 호출 인자
- 독립 한 bone·armature+bevel·단순 이동 animation fixture의 전후 보존 확인
- 별도의 한글 PDF 실제 생성·렌더 열람과 글꼴 오류 경계 검사

UV 좌표나 모든 split-normal 값을 일반적인 모든 asset에서 보증하는 검사는 아니다.
Rig probe는 기존 동작에 대한 제한 회귀이며 rig/animation 지원 선언이 아니다.
최종 실행 결과는 다음과 같다. 정확한 명령과 파일 hash는 동봉 검증 receipt와
로그를 따른다.

| 검사 | 결과 |
| --- | --- |
| 최종 전체 Python | 2,634 passed / 109 skipped / 8 기존 Pillow deprecation warnings |
| 실제 Blender를 포함한 raw export 집중 검사 | 16 passed |
| PDF reporting 집중 검사 | 24 passed |
| 기존 실패 node의 무수정 baseline 재현 | 57/57 같은 실패 |
| Ruff, agent instructions, repository projections, Git whitespace | 통과 |
| doctor, Blender 5.0.1 compatibility 및 GLB/OBJ/FBX smoke | 통과 |

Windows self-hosted 전체 V0.7–V0.9 gate와 5자산 실제 campaign은 실행하지 않았다.
Python의 skipped 항목이나 단일 rig fixture를 통합 Blender/platform pass로
계산하지 않는다.

## 남은 한계와 중단선

실제 3쪽 한글 PDF는 생성되고 한글 음절은 읽히지만, 비내장 CID 글꼴의 Poppler
대체 렌더에서 가운데점 U+00B7이 누락 glyph 상자로 보였다. 수정하지 않은 기존
renderer의 CID 경로로 같은 payload를 렌더해 세 쪽 모두 pixel-identical임을
확인했다. 기존 typography 한계이며 깔끔한 PDF 표시까지 통과했다고 주장하지
않는다. 기존 `CBM_PDF_FONT_PATH`로 호환되는 한글 TrueType font를 지정할 수 있다.

기존 crown의 8개 point 저작, 5개 gemstone의 inward winding 및 잘못 저작된
semantic bbox는 그대로 남았다. 이것들은 이번 조사에서 공통 exporter의 결함과
구분한 자산 저작 문제다. 이전 버전이나 현재 BAG의 평균 품질 우월성은 주장하지 않는다.

이번 자료는 원시 export mechanism과 보고서 생성에 관한 검증이다. Production
package, 형식별 package acceptance, 인간 beauty 수용 또는 Activation을 만들지
않는다. AQ review는 여전히 production package가 아니다. 새 campaign·계약·예산
증액·canonical promotion·승인 기록을 만들지 않았다.

사용자 컴퓨터의 필요한 행정 증거 7개와 관련 locator를 클라우드로 복사해 ZIP과
각 파일의 크기·SHA-256·CRC를 검증했다. 삭제된 과거 scratch를 재구성하지 않았고
원래 machine JSON 안의 경로·hash도 수정하지 않았다. 현재 수정과 검증은 클라우드
소스, Blender 및 이미 보존한 crown만으로 재현할 수 있다.
