# V0.6 로컬 검증 기록

검증 환경: 2026-07-15, Windows, Blender 5.0.1, Python 3.14.6(호스트), Blender Python 3.11.13.

## 결과 요약

| 게이트 | 결과 |
|---|---|
| Python 테스트 | 131/131 통과 |
| Ruff | 통과 |
| doctor | Repository / Workspace / Blender / Codex 모두 OK |
| Blender compatibility | 5.0.1, `BLENDER_EEVEE`, AgX Medium High Contrast |
| Export smoke | GLB / OBJ / FBX 통과 |
| V0.4 Geometry/Measured 회귀 | 통과 |
| Cycles stdio MCP 회귀 | OPTIX GPU에서 3개 작업 통과 |
| V0.5 PBR/UV/Shader | 6 source 채널과 Blender image graph 검증 통과 |
| V0.5 Cycles bake | 5 portable 채널과 SHA-256 검증 통과 |
| V0.6 render pass | 7/7 패스와 hash 검증 통과 |
| Build freshness | SceneSpec·geometry·재질 계약 변경 후 stale QA/bake 거부 통과 |
| 승인형 복구 | canonical 교체 이후 예외 rollback, ID별 constraint 비회귀 테스트 통과 |
| V0.6 stdio MCP | 새 material/texture/bake/QA 도구 통과 |
| Advisory target adapter | exact prompt 보존, direct score/candidate 불변 |
| 사람용 PDF 보고서 | build/material/qa/full 생성, source manifest와 PDF SHA-256 검증 통과 |

## V0.4 회귀

- `geometry_showcase`: geometry 6종, modifier 8종, validation 오류·경고 0.
- `measured_box`: 통과 제약과 의도적 실패 제약을 구분하고 residual을 기록.
- `first_reference_test`: 입력 SHA-256과 SceneSpec SHA-256 유지, 40 semantic family, 63 mesh instance, validation `ok: true`.
- Cycles MCP: NVIDIA RTX 5070 Laptop GPU / OPTIX, build→render→inspect→validate 통과.

기계 보고서:

- `reports/blender_compatibility.json`
- `reports/v04_completion_regression.json`
- `reports/v04_mcp_regression.json`

## V0.5 재질·텍스처·셰이더

격리된 `reports/v06_smoke/workspaces/geometry_showcase`에서 다음을 실제 실행했습니다.

1. MaterialPlan/ShaderRecipe 생성
2. `rock`, seed 606, 128×128 PBR source 6채널 생성
3. `mat.blue`에 TextureManifest 연결
4. UVMap 보존/Smart UV 처리
5. Blender 5 Principled image graph 생성
6. material inspection과 sphere/plane swatch 렌더
7. Cycles CPU에서 Base Color/Roughness/Metallic/Normal/Emission 베이크
8. manifest와 모든 출력 SHA-256 재검증

빌드 provenance에는 SceneSpec, 카메라, 외부 custom mesh/heightmap, MaterialPlan,
ShaderRecipe, TextureManifest, 실제 texture channel hash가 포함됩니다. Blender 5.0.1
실기동 테스트에서 fresh build의 5채널 bake는 성공했고, ShaderRecipe를 바꾼 뒤
재빌드하지 않은 bake는 출력 생성 전에 stale scene 오류로 거부됐습니다.

직접 게이트는 128×128, stdio MCP 게이트는 64×64 베이크를 통과했습니다. 최종 smoke 보고서는 4개 material, 연결된 texture 1개, source channel 6개, bake output 5개를 확인합니다.

Material inspection의 10개 경고는 예제의 다른 재질 객체가 UV를 요구하지 않아 active UV가 없거나, 반복/Remesh 결과가 0..1 범위 밖 또는 퇴화 UV를 가진다는 진단입니다. 오류는 0이며 선택한 `mat.blue` bake는 완료됐습니다. 이 경고는 Smart UV가 최종 atlas/seam 설계를 대체하지 않는다는 현재 경계를 보여 줍니다.

## V0.6 Visual QA

격리 smoke에서는 7개 패스를 모두 생성하고 hash를 확인했습니다.

```text
beauty, silhouette, object_id, material_id, normal, depth, wireframe
```

`first_reference_test`의 최종 직접 QA 결과:

- run ID: `20260714T174051.664098Z-7cb9b86a3c08`
- direct score: `0.452164`
- finding: 52개
- revision candidate: 30개
- candidate path: `transform.location`, `transform.scale`
- applicability: 전부 `approval_required`
- 자동 승인·적용: 0건

이 QA는 현재 canonical build fingerprint와 `.blend`에 저장된 fingerprint를 대조하고,
실제 Blender 카메라의 투영·위치·방향·렌즈·ortho scale·해상도도 SceneSpec과 비교한
뒤 실행됐습니다. manifest는 정확히 7개 패스를 요구합니다.

점수는 현재 알고리즘의 비교 지표이며 완성도 퍼센트나 사람의 품질 승인을 뜻하지 않습니다.

외부 이미지 adapter smoke는 기존 로컬 preview를 fixture로 사용해 provider 경계를 실제 실행했습니다. target은 `generated/advisory_only`로 기록됐고, exact prompt가 run 내부에 보존됐으며 direct score와 candidate 수는 변하지 않았습니다. 이는 외부 image-generation API 자체의 품질 검증이 아닙니다.

## V0.6 stdio MCP

실제 stdio transport에서 다음 공개 도구를 확인했습니다.

```text
get_material_presets
generate_procedural_textures
attach_texture_manifest
validate_material_contracts
build_scene
bake_materials
inspect_materials
render_material_swatches
generate_pdf_report
run_visual_qa
compile_visual_revision
approve_visual_revision
apply_approved_visual_revision
```

PBR 생성, Blender build, Cycles bake, material inspect/swatch, direct QA가 모두 종료됐으며 Blender 자식 프로세스의 MCP stdin 상속 정체는 재발하지 않았습니다.

`generate_pdf_report`는 실제 stdio MCP 목록과 호출 경로에서도 확인했습니다.

기계 보고서:

- `reports/v06_completion_regression.json`
- `reports/v06_mcp_regression.json`
- `reports/v06_advisory_target_regression.json`

## 사람용 PDF 보고서

`first_reference_test`의 기존 canonical JSON과 렌더 증거를 변경하지 않고 다음 PDF를 생성했습니다.

| 범위 | 페이지 | source 수 | 경고 |
|---|---:|---:|---:|
| build | 2 | 8 | 0 |
| material | 5 | 22 | 0 |
| qa | 4 | 15 | 0 |
| full | 9 | 37 | 0 |

각 PDF 옆의 `.manifest.json`에는 PDF SHA-256, 개별 source SHA-256, 결합 source fingerprint와 선택한 QA run ID가 기록됩니다. source 경로는 job-relative이며 외부 또는 hash가 바뀐 시각 증거는 보고서에서 제외됩니다.

PDF는 Poppler로 모든 페이지를 PNG로 렌더링한 뒤 한글, 표, 재질 swatch, reference/preview, 고정 카메라 7패스와 페이지 잘림을 육안 검사했습니다. PDF는 사용자 검토용 파생 산출물이며 기계 검증이나 수정 승인 원본으로 사용하지 않습니다.

## 남은 제한

- 실제 외부 ImageGen 호출과 모델 품질은 저장소가 인증 정보를 내장하지 않으므로 별도 표면에서 실행해야 합니다.
- 자동 UV는 기본 Smart UV이며 seam authoring, multi-object atlas, retopology는 지원하지 않습니다.
- bake 결과는 별도 portable 채널입니다. Unity ORM/smoothness packing과 실제 Unity import는 V0.7 범위입니다.
- image/hybrid triplanar는 아직 실행하지 않으며 procedural triplanar는 Object 좌표 근사입니다.
- Blender 4.x fallback 코드는 유지하지만 V0.5/V0.6 신규 스크립트는 현재 Blender 5.0.1에서만 실기동 검증했습니다.
- 단일 이미지의 가려진 면·실제 깊이·절대 치수는 계속 inferred입니다.

## 2026-07-30 선택적 bounded convergence 추가 검증

기존 candidate-by-candidate guarded revision을 기본값으로 유지하면서,
`standard` 작업에서만 exact plan SHA-256을 한 번 승인해 제한된 국소 수정 반복을
허용하는 convergence session을 추가 검증했습니다.

| 검증 | 결과 |
|---|---|
| 전체 Python 회귀 | 602/602 통과 (`76.15s`) |
| convergence/V0.9 집중 회귀 | 150/150 통과 |
| Schema 재생성 및 parity 집중 검사 | 5/5 통과 |
| Ruff | 전체 저장소 통과 |
| CLI | plan/approve/run/status/cancel 5개 help와 공개 호출 확인 |
| MCP | 5개 공개 메서드 구현·allowlist·wrapper 회귀 통과 |
| V0.6 Blender host gate | Blender 5.0.1 build/material/bake/7-pass QA/PDF 통과 |
| V0.8 isolated gate | standard·background fast plan과 package approval 경계 통과 |
| V0.9 isolated gate | GLB package·clean-import·handoff·audit·stability PDF 통과 |

실제 QA가 생성하는 sortable run ID는 대문자 `T`와 `Z`를 포함합니다.
초기 smoke에서 convergence 전용 소문자 ID 검증이 이 정상 run ID를 거부하는
문제를 발견했고, session ID와 QA run ID 계약을 분리해 수정했습니다. 또한
`VisualQAReport.request_sha256`이 request 파일 hash가 아니라 canonical contract
hash라는 기존 V0.6 의미를 convergence 감사가 정확히 해석하도록 보강했습니다.

격리된 `geometry_showcase`의 실제 7-pass QA를 사용한 exact terminal smoke:

```text
workspace:
reports/v06_convergence_smoke/20260730T141041062Z/workspaces/geometry_showcase/

session:
exact-smoke-20260730t141041z

initial QA:
20260730T141113.483990Z-0cc1d59d53c9
```

| 증거 | 값 |
|---|---|
| exact plan SHA-256 | `f926969039c32b4c27759e68b7f2e217c55aacb7599bdc1e844be6a108a05d7d` |
| approval SHA-256 | `5e1548d521690b663c4036d58f22d4d8ef3278571f66bc33a322893daf24f9fb` |
| host safety envelope SHA-256 | `6a30f993f28865623657b3e60ff8afc968bc71a3deb4dfda9c444d3e9f493c89` |
| 종료 이유 | `target_reached` |
| accepted / rolled back | `0 / 0` |
| canonical SceneSpec 전후 SHA-256 | 동일: `0cc1d59d53c9f0105174a748bced459826e526e4c8f7cb3b5b712b22cd15d158` |
| terminal JSON SHA-256 | `0995cb66e945a24e459847f9db080a50638d73ed94e3adf55f68d40b3cea8638` |
| PDF SHA-256 | `38440ed6fe20eba3b3210b626da727d046310946b9135deaf379b71a7f52ba8d` |
| PDF manifest SHA-256 | `3d4f0ed3c83125e798230c69446cf94969ed1c98022cee0f239126ad76ba6f4a` |

terminal PDF 2개 페이지를 Poppler로 PNG 렌더한 뒤 한글, 표, 경로 wrapping,
clipping과 overlap을 확인했습니다. 결함은 없었습니다. 이 smoke는 initial direct
score와 silhouette 목표가 이미 충족된 경우 exact 승인 뒤 canonical 형상을 바꾸지
않고 안전하게 terminalize하는 계약을 검증합니다. 실제 개선 iteration의
accept/rollback, plateau, constraint regression, 취소, tampering, concurrent writer,
receipt-less staging 복구, status-only legacy와 fast-workflow 소유 QA 거부는 isolated
service fixture에서 검증했습니다.

제한 사항:

- convergence는 목표 달성을 보장하지 않으며 기본 3회, 하드 상한 5회입니다.
- 카메라, 재질, custom-mesh vertex, 실내, generated-target-only와 계획 밖 경로는
  자동 권한 밖입니다.
- `background_exterior`의 단일 canonical QA는 initial convergence QA로 재사용할 수
  없습니다. review delivery 뒤 별도 `standard` direct QA가 필요합니다.
- 이번 실제 Blender terminal smoke는 eligible 후보가 없는 안전 종료를 검증했습니다.
  Blender가 실제 형상을 수정하는 accepted iteration은 deterministic host service와
  rollback fixture로 검증했으며 별도 사용자 자산에는 실행하지 않았습니다.
