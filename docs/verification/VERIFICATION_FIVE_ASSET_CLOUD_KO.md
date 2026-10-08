# Plastic·Rust·Wood·Crystal·Laser 클라우드 검증

기준 소스는 `634de794d7694457b5e6a5bfd4a24ea75f1bc4b6`이며 commit/push 없이
기존 제한적 export/PDF 수정 위에서 검증한다. 왕관은 이번 다섯 자산의 판정 근거에서 제외한다.
원본 reference·canonical·승인·소비·receipt·history·package는 변경하지 않는다.

## 추가로 확인하고 고친 공통 문제

Windows에서 작성된 job metadata의 역슬래시 상대경로는 Linux에서 문자 그대로 해석됐다.
별도 `CBM_WORKSPACE_ROOT`로 옮긴 hash-identical 입력도 기본 저장소 경로에서 찾으므로
reference 분석·V0.6 QA·관련 보고서가 원본 이미지를 찾지 못했다.

`resolve_job_input_path`는 immutable input에 한해서 소유 job/input/파일명과 기록된
SHA-256을 확인한 뒤 현재 job의 동일 입력을 읽는다. 원래 machine JSON은 다시 쓰지 않는다.
다른 job, traversal·모호한 경로, hash 누락/변경, symlink·Windows reparse point는
재배치 근거가 되지 않는다. 원래 위치의 native input도 제공된 hash가 있으면 확인한다.
Hash가 없는 기존 native-contained 입력의 읽기 호환성은 유지하되 재배치는 허용하지 않는다.
일반 metadata 경로, 승인·source-manifest·budget·receipt의 경로 해석은 변경하지 않는다.

공통 입력 reader, reference 분석, semantic mask, multiview, PDF reference 수집 및
읽기 전용 workspace audit에 같은 경계를 적용한다. 거부된 경로를 audit에서 다시
일반 경로로 해석하여 통과시키지 않는다. 보고서 경고에는 절대 호스트 경로를 넣지 않는다.

새 Standard `manual_guarded` 수정에는 host가 정확한 후보 SceneSpec와 외부 geometry
dependency bytes를 묶는 immutable revision payload binding을 만든다. 승인 대기 전,
승인 시점, apply 진입 및 writer lock 안의 canonical 교체 직전에 같은 closure를 확인한다.
외부 파일·link·case collision·변조·mutable output 참조는 실패하며 완료된 과거 기록을
현재 파일로 다시 해석하지 않는다. 기존 workflow와 AQ 권한은 변경하지 않는다.
Geometry payload 결속은 UV 변경에 따른 material 재진입이나 최종 package 수용 승인을
대신하지 않는다. 검토용 `preview_revision_plan`은 native apply와 동일한 후보를 쓰기 없이 만든다.

서로 다른 부품에 같은 전체 물체 bbox를 복제한 경우에는 숫자와 기존 finding을 보존하며
관측 근거의 모호성을 별도 표시한다. 해당 bbox에서 만든 transform 제안과 자동 reference
축 수용·convergence를 막는다. 독립적인 부품 관측이 없는 부분은 관측되지 않았다고 표시하며,
관측된 일부 부품의 점수를 전체 자산 수용으로 해석하지 않는다.

`primary_object_only`에서 불완전한 observed bbox의 합집합이 원래 foreground를 잘라내면
새 mask/report를 발행하기 전에 거부한다. 명시적으로 선택한 ReferenceMaskSeedEvidenceV03은
기존 V0.2 trimap에 별도의 hash-bound 전체 물체 범위 companion을 추가한다. 첫 profile은
원본 RGBA alpha를 host가 다시 계산해 bbox와 pixel 수를 확인하는 범위다. 기존 V0.1/V0.2,
SceneSpec 0.2와 V0.6 보고서 bytes는 자동 변경하지 않는다. Alpha가 있는 여러 물체 사진의
foreground가 전부 선택한 물체라는 뜻은 아니며, 분리된 단일 대상인지 독립 확인해야 한다.

## 실제 자료와 판정 분리

- 여섯 ZIP과 transfer index를 클라우드에서 byte/SHA-256/CRC 확인 후 복원
- 4,435개의 고유 보존 파일, 9개 저작 job, 5개 reference 및 7개 역사 package
- Native schema/build dependency 9/9, package manifest·209개 payload·현재 source binding 7/7 확인
- 새 clean import 6/7 통과. 원래 Laser canary의 tangent 실패는 그대로 재현되며,
  승인된 R5D recovery와 후속 Laser package는 통과한다. 과거 실패를 성공으로 바꾸지 않는다
- Package roundtrip의 legacy `ok`와 완전한 UV/normal/tangent-vector 동등성은 구분한다
- 같은 unchanged source의 새 build/렌더/원시 GLB/import 및 별도 V0.6 QA는 새 진단 증거다
- 현재 generator로 오래된 recipe를 다시 materialize한 winding 수리 후보는 격리된 미승인 후보다
  canonical promotion·새 최적화·인간 package 수용 또는 AQ Activation의 승인이 아니다

완료 Plastic은 다시 저작하지 않는다. 복사한 오래된 `.blend`가 외부 Windows texture
locator를 유지하여 missing image가 되는 경우, 동일 canonical·material·texture bytes로
파생 diagnostic blend만 다시 만든다. 실제 geometry fingerprint와 input hash를 비교하며,
이 환경 복원을 새 reference-fidelity 개선으로 계산하지 않는다.

## 검증 기록

실제 명령·새 렌더·source/input hash·자산별 단계 판정·과거 대비 비교 조건 및
최종 회귀 결과는 이번 외부 검증 패킷의 machine receipt를 따른다. 미실행/실패/제한은
통과에 포함하지 않는다. Linux Blender 5.0.1 실행은 Windows self-hosted 인증이나
엔진 프로젝트 테스트를 대신하지 않는다. 기존 source-bound AQ 계약을 재개하지 않는다.

Payload binding 수정까지 포함한 고정 소스의 전체 Python 회귀는 2,708 passed,
109 skipped, 기존 Pillow 경고 8개였으며, 통합 후 관련 회귀도 152 passed, 1 skipped였다.
초기 V0.7–V0.9 실행은 export/PDF 수정 당시 고정 소스에 대한 별도 증거로 유지한다.
후속 입력 reader와 revision guard 수정까지 그 실행이 포함했다고 주장하지 않는다.

QA 신뢰성 및 명시적 전체 물체 범위 수정까지 포함한 다음 고정 소스는 2,773 passed,
109 skipped, 기존 경고 8개를 기록했다. Main 통합 뒤 관련 148개 회귀도 통과했다.
실제 Crystal V0.3 실행에서는 원본 alpha의 267,103개 foreground pixel을 모두 유지했고,
이전 형상과 7개 pass의 decoded pixels가 동일했다. 새 수치 0.900830/IoU 0.853212는
근거 해석을 바로잡은 결과이며 형상 개선율이 아니다. 13개 중 8개만 observed인 한계와
미일치한 낮은 fin lobe, 미승인 형상·재질·package 경계는 별도 검토 패킷에 남긴다.
