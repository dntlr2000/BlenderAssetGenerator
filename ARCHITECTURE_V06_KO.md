# V0.6 아키텍처 — Material, Shader & Visual QA Core

## 버전 계약

| 계층 | 버전 | 역할 |
|---|---:|---|
| 프로젝트 | `0.6.0` | 통합 기능 범위 |
| SceneSpec | `0.2.0` | geometry, transform, assignment, camera |
| Reference/Constraint | `0.4.0` | 이미지 진단, 카메라 가정, 실측 residual |
| Material/Shader/Texture/Bake | `0.5.0` | 재질 제작과 portable 출력 |
| Render pass/Visual QA/Approval | `0.6.0` | 비교 근거와 승인형 수정 |

SceneSpec을 확장하지 않고 별도 계약을 참조하므로 승인된 V0.2/V0.4 geometry를 다시 마이그레이션하지 않습니다.

## 데이터 흐름

```text
immutable input
  → reference analysis / camera solution
  → modeling plan
  → SceneSpec 0.2 + geometry payloads
  → build / preview / inventory / validation / constraints
  → MaterialPlan + ShaderRecipe
  → procedural or authored TextureManifest
  → UV policy + Blender shader graph
  → material inspection / swatches / optional Cycles bake
  → fixed-camera 7-pass render
  → direct reference QA
  → approval-required revision candidates
  → explicit single-use approval
  → one revision / rebuild / convergence
  → accept or restore baseline
```

## 사람용 보고서 projection

```text
canonical JSON reports + approved images
    ↓ read-only collection
source fingerprint and per-file SHA-256
    ↓
ReportLab PDF
    ├─ output/pdf/<job>/<scope>_report.pdf
    └─ output/pdf/<job>/<scope>_report.manifest.json
```

PDF 계층은 canonical 데이터를 읽기 전용으로 투영하는 단방향 계층입니다. PDF 내용을 SceneSpec, MaterialPlan, QA approval 또는 RevisionPlan으로 다시 역직렬화하지 않습니다.

생성은 임시 파일을 완성한 뒤 원자적으로 교체합니다. manifest에는 job-relative source path, 크기, 개별 SHA-256, 결합 source fingerprint, PDF SHA-256과 선택한 QA run ID를 기록합니다. 기본 출력 경로는 활성 workspace와 함께 격리되어 smoke 작업이 사용자 보고서를 덮어쓰지 않습니다.

## V0.5 호스트 계약과 Blender 런타임

호스트 Python은 Pydantic 모델과 JSON Schema로 계약을 검증합니다. Blender 하위 프로세스는 Pydantic에 의존하지 않고 제한된 JSON loader만 사용합니다.

```text
analysis/material_plan.json
materials/<id>/shader_recipe.json
textures/<id>/texture_manifest.json
bakes/<id>/<profile>/bake_manifest.json
```

MaterialPlan이 없으면 `build_scene.py`는 기존 SceneSpec 재질을 그대로 생성합니다. 계획이 있으면 stable material ID로 ShaderRecipe와 TextureManifest를 검증해 적용합니다. plan의 모든 SceneSpec material coverage, job/material ID, 경로 containment, mapping, source type, image hash와 색 공간이 일치해야 합니다.

지원 런타임은 의도적으로 제한합니다.

- portable Principled surface
- whitelisted Noise → ColorRamp/Roughness/Bump procedural 계층
- Base Color, Roughness, Metallic, Normal, Height/Bump, Emission image 채널
- UV, Object, Generated mapping
- procedural triplanar의 Object 좌표 근사

임의 Python, 임의 Blender 노드 그래프, plan/recipe mapping 불일치, image/hybrid triplanar, 공유 이미지의 서로 다른 색 공간 요구는 빌드 전에 거부합니다.

## 결정론적 Texture provider

Pillow provider는 9개 재질 family preset과 seed로 periodic multi-octave 값을 계산해 6채널 PBR 이미지를 만듭니다. 결과에는 provider/version/model/prompt/seed와 채널별 SHA-256이 기록됩니다. 네트워크나 외부 이미지 모델을 사용하지 않으므로 반복 테스트가 가능합니다.

이 provider는 구조와 런타임 검증용 합성 재질입니다. 레퍼런스에서 고품질 재질을 복원하는 생성 모델을 의미하지 않습니다.

## UV와 베이크

`mapping.mode="uv"`인 메시만 UV 처리를 요청합니다. 지정 UV가 있으면 보존하고, 없으면 Blender Smart UV operator의 실제 지원 인자를 feature-probe해 생성합니다. 다른 mapping은 UV를 강제하지 않습니다.

베이크는 승인된 `.blend`를 읽고 그래프 변경을 저장하지 않은 채 Cycles에서 다음 채널을 출력합니다.

`build_scene`은 SceneSpec, 외부 geometry/heightmap payload, MaterialPlan, ShaderRecipe,
TextureManifest, image channel의 canonical fingerprint를 `.blend` custom property에
고정합니다. `bake_materials`는 현재 계약 fingerprint와 source `.blend` SHA-256을
베이크 전에 대조하므로 계약 파일 또는 payload 변경 후 재빌드를 생략할 수 없습니다.
각 BakeManifest는 source recipe/plan/manifest/channel/geometry/blend 해시와 전체 build
fingerprint를 보존합니다.

```text
Base Color, Roughness, Metallic, Normal, Emission
```

모든 출력은 job-local 경로와 SHA-256을 갖습니다. 다중 재질 메시, UV 없는 재질, 비-UV mapping은 조용히 근사하지 않고 명시적으로 실패합니다. V0.6은 profile packing을 하지 않습니다. V0.7은 engine-neutral glTF ORM과 raw-channel package를 추가하지만 Unity/Unreal 전용 packing은 대상 엔진 확인 뒤 별도 adapter로 남깁니다.

## V0.6 고정 카메라 패스

`render_qa_passes.py`는 원본 `.blend`를 canonical source로 바꾸지 않고 고정 카메라에서 다음 패스를 생성합니다.

```text
beauty, silhouette, object_id, material_id, normal, depth, wireframe
```

각 패스의 경로, SHA-256, 해상도, encoding, Blender 버전, 엔진/device, camera fingerprint, SceneSpec hash, build fingerprint와 semantic color map을 manifest에 기록합니다. 공개 계약은 7개 종류를 정확히 한 번씩 요구합니다.

QA 시작 전 현재 SceneSpec·외부 geometry·재질 계약의 canonical fingerprint와 `.blend`
custom property를 대조합니다. 실제 Blender 카메라의 투영, 위치, 시선 방향, 렌즈,
ortho scale, 해상도도 SceneSpec과 비교하므로 SceneSpec이나 payload를 바꾸고
재빌드하지 않은 오래된 장면으로 QA 후보를 만들 수 없습니다.

## 직접 비교와 생성 target

직접 비교는 reference content mask와 rendered silhouette의 IoU, 전체 bbox 중심·크기, observed semantic bbox의 중심·크기 오차를 계산합니다. 이 결과만 `overall_direct_score`의 근거가 됩니다.

외부 이미지 생성 결과를 사용할 때 reference는 내용 근거, preview는 카메라/프레이밍 근거입니다. 저장소의 existing-file adapter가 절대 경로와 선택적 allowed root를 검증하고 run 내부로 복사합니다. 실제 prompt 텍스트와 provider/model/version/seed/prompt/output hash를 보존합니다.

생성 target 비교는 edge IoU, 8×8 색상 블록, RGB histogram으로 별도 finding만 만듭니다. 이 finding은 `generated_target`만 근거로 가지며 suggestion이 없고, 직접 점수와 revision candidate 수를 바꾸지 않습니다.

## 승인과 복구

```text
VisualQAReport
  → RevisionCandidates (approval_required/manual_required)
  → selected candidates
  → RevisionPlan (unapproved)
  → explicit hash-bound approval
  → apply once
  → build/render/inspect/validate/constraints/direct QA
  → improved: accept
  → no improvement/regression/error: archived SceneSpec restore + rebuild
```

카메라와 관계없는 semantic ID는 잠깁니다. generated-target-only 제안, custom mesh payload 변경, 불명확한 parent/array 구조는 자동 경로로 적용하지 않습니다. 입력 이미지는 어느 단계에서도 수정하지 않습니다.

archive, 승인 소비, 임시 명세 생성, canonical 교체, 보고서 기록과 후속 검증은 하나의
예외/rollback 경계에 있습니다. constraint 비회귀는 총 실패 수가 아니라 stable
constraint ID별 status, tolerance와 residual/tolerance 비율로 판정합니다.

## Blender 5.0.1 호환성

- EEVEE enum 실제 적용 순서로 feature probe
- Principled node/socket 이름 기반 탐색과 fallback
- UV, bake, render pass operator 인자 feature probe
- `--python-exit-code 1`, `stdin=DEVNULL`
- GLB/OBJ/FBX exporter fallback

Blender 4.x fallback 코드는 유지하지만 V0.5/V0.6 신규 UV·shader·bake·7-pass 스크립트의 실기동 기준 환경은 Blender 5.0.1입니다.
