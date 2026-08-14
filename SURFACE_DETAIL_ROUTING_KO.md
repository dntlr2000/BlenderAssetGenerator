# 작은 표면 디테일의 메시·텍스처 분류

이 문서는 창문 무늬, 이음선, 리벳, 라벨, 얕은 패널처럼 물체 표면에 붙어 있는
작은 디테일을 불필요한 개별 메시로 만들지 않기 위한 현재 계약을 설명합니다.
SceneSpec 버전은 계속 `0.2.0`이며, 분류 정보는 ModelingPlan `0.4.0`의 선택적
하위 계약으로 저장됩니다.

## 판단 기준

| 조건 | 기본 표현 |
|---|---|
| 외곽 실루엣을 바꿈 | V0.4 geometry object |
| 하중·결합·두께 등 구조적 의미가 있음 | V0.4 geometry object |
| 충돌·상호작용·게임플레이에 필요함 | V0.4 geometry object |
| 실제 유리판·개구부처럼 물리적 투명성이 필요함 | V0.4 geometry object |
| 색·거칠기·금속성·발광 차이만 있음 | `texture_channels` |
| 국소적인 창문 무늬·라벨·얕은 패널·반복 마크 | `baked_decal` |
| 최종 화면에서 의미 있게 보이지 않음 | 명시적 `omit` |

`baked_decal`은 목적 엔진의 런타임 decal을 뜻하지 않습니다. Blender master shader와
별개로 Base Color, Roughness, Metallic, Normal, Height, Opacity, Emission 같은
portable PBR 이미지에 평탄화된 결과를 뜻합니다.

## V0.4 ModelingPlan

새 분석 scaffold에는 `surface_detail_policy`가 포함됩니다. Codex는 SceneSpec을 쓰기
전에 `objects`와 `surface_details`를 구분해야 합니다.

```json
{
  "surface_detail_policy": {
    "mode": "texture_preferred",
    "default_representation": "texture_channels",
    "prefer_texture_for_repeated_details": true,
    "max_texture_projected_size_px": 128,
    "max_texture_relief_m": 0.01,
    "geometry_required_conditions": [
      "silhouette",
      "structural",
      "gameplay",
      "physical_transparency"
    ],
    "notes": []
  },
  "surface_details": [
    {
      "id": "detail.window.side_rows",
      "label": "painted side windows",
      "parent_object_id": "vehicle.body.cabin",
      "representation": "baked_decal",
      "source_ids": ["reference"],
      "bbox_norm": [0.22, 0.30, 0.68, 0.49],
      "target_material_id": "mat.vehicle.body",
      "channels": ["base_color", "roughness", "normal"],
      "uv_strategy": "material_atlas",
      "projected_size_px": 48,
      "estimated_relief_m": 0.003,
      "repeated_count": 6,
      "silhouette_affecting": false,
      "structural": false,
      "gameplay_relevant": false,
      "physical_transparency_required": false,
      "evidence_status": "observed",
      "confidence": 0.9,
      "notes": []
    }
  ]
}
```

`surface_details`의 ID는 SceneSpec `objects`에 동시에 존재할 수 없습니다. 부모 객체와
대상 material ID는 SceneSpec에 실제로 존재하고 서로 연결되어야 합니다. 실루엣,
구조, gameplay 또는 물리적 투명성 플래그가 참인 항목은 이 목록에서 거부되며 정상
geometry object로 계획해야 합니다.

## V0.5 MaterialPlan과 TextureManifest

텍스처로 분류된 항목은 material scaffold의 해당 material note에 자동으로 표시됩니다.
최종 authored MaterialPlan은 `image` 또는 `hybrid` 전략을 사용해야 하며, localized
detail은 안정적인 `UVMap`을 사용해야 합니다.

TextureManifest에는 실제로 포함한 ID와 그 공간 결속을 기록합니다. 새 authoring plan의
`surface_detail_binding_policy`는 `spatial_v1`이며, 단순 ID 목록만 있는
`legacy_unbound` manifest는 호환 로딩만 가능하고 spatial verification을 통과하지 않습니다.

```json
{
  "schema_version": "0.5.0",
  "material_id": "mat.vehicle.body",
  "uv_set": "UVMap",
  "intended_scale_m": 1.0,
  "resolution": [1024, 1024],
  "source_type": "image",
  "channels": {
    "base_color": {
      "source": "image",
      "path": "base_color.png",
      "color_space": "sRGB"
    },
    "roughness": {
      "source": "image",
      "path": "roughness.png",
      "color_space": "Non-Color"
    },
    "normal": {
      "source": "image",
      "path": "normal.png",
      "color_space": "Non-Color"
    }
  },
  "surface_detail_ids": ["detail.window.side_rows"],
  "surface_detail_bindings": [
    {
      "detail_id": "detail.window.side_rows",
      "parent_object_id": "vehicle.body",
      "material_id": "mat.vehicle.body",
      "uv_set": "UVMap",
      "uv_layout_sha256": "<CURRENT_ORDERED_POLYGON_CORNER_UV_SHA256>",
      "placement": {
        "mode": "uv_rect",
        "uv_rect": [0.12, 0.28, 0.42, 0.54]
      },
      "channels": ["base_color", "roughness", "normal"],
      "strength": 0.65,
      "wrap": "clamp"
    }
  ]
}
```

ordered polygon-corner UV hash는 polygon/loop 순서, vertex 위치와 UV의 exact binding을
나타냅니다. 뒤 단계에서 UV가 바뀌면 stale로 거부됩니다. `uv_rect` 대신 같은 texture
directory 안의 exact SHA-256 mask를 사용할 수 있습니다. spatial channel은 실제 image
channel이어야 하며, localized material은 parent 외 다른 object와 공유할 수 없습니다.

ID만 적고 실제 맵에 디테일을 만들지 않는 것은 허용되지 않습니다. Host 검증은 ID,
경로, hash, UV, node topology, sampling과 채널 계약을 확인하지만 `uv_rect`가 의미상
올바른 면을 골랐는지까지 자동 증명하지는 않습니다. swatch와 preview 검토는 계속
필요합니다. placement 근거가 불충분하면 전체 UV에 generic panel line이나 groove를
반복하지 말고 clean fallback을 유지합니다.

## V0.6 QA

`visual_qa_report.json`에는 `surface_detail_summary`가 추가됩니다. 이 값은 선언 수,
TextureManifest 결속 수, 생략 수, 실패 검사를 보여 줍니다. 작은 표면 디테일은
SceneSpec geometry 후보가 아니므로 자동 geometry revision 대상으로 만들지 않습니다.

- 맵에서 디테일이 빠졌거나 잘못 보이면 V0.5 material/texture revision으로 돌아갑니다.
- 실제 외곽이나 구조가 필요한 것으로 판명되면 V0.4 geometry authoring으로 돌아갑니다.
- coverage 수치는 픽셀 유사도나 모델 완성도 백분율이 아닙니다.

QA PDF와 material/build PDF는 `reports/surface_detail_validation.json`의 파생 요약을
표시합니다. 판단 원본은 계속 JSON입니다.

## CLI와 MCP

사용자가 PowerShell을 직접 실행할 필요는 없습니다. Codex는 다음 MCP 도구를 사용할
수 있습니다.

- `validate_surface_details`
- `get_surface_detail_status`
- `validate_material_fidelity`

CLI 대응 명령은 다음과 같습니다.

```powershell
uv run cbm validate-surface-details <JOB_ID>
uv run cbm surface-detail-status <JOB_ID>
uv run cbm validate-material-fidelity <JOB_ID>
```

## 호환성과 제한

- 기존 ModelingPlan에는 새 필드가 없어도 계속 로딩됩니다.
- 새 V0.8 workflow만 explicit policy를 completion 조건으로 요구합니다.
- 기존 SceneSpec `0.2.0`, Material `0.5.0`, QA `0.6.0`, orchestration `0.8.0`
  버전은 바뀌지 않습니다.
- ModelingPlan에 surface detail이 하나라도 있으면 그 exact hash가 build provenance에
  포함되어 stale build를 탐지합니다.
- 현재 local procedural provider는 레퍼런스의 창문 배치를 자동으로 복원하는 전용
  decal painter가 아닙니다. 실제 UV 배치와 이미지 맵 저작이 필요하며, 이를 수행하지
  못하면 coverage를 거짓으로 승인하지 말고 V0.5 대기 또는 명시적 omission으로 남깁니다.
- local provider는 서로 다른 placement를 가진 여러 detail을 한 output에 합치지 않습니다.
  각 detail을 별도 bounded output으로 만들거나 외부 authored atlas/mask를 사용해야 합니다.
- `reports/material_fidelity_validation.json`은 검은 선, 과도한 full-field variation,
  normal 이상, hash와 spatial ownership을 검사하는 결정론적 보조 증거입니다. 레퍼런스
  재질 유사도 점수나 pixel-level decal placement 증명으로 해석하지 않습니다.
- V0.7 package는 raw PBR 이미지를 보존하지만 특정 Unity/Unreal 셰이더 parity를
  주장하지 않습니다.

## Material Closure 승인 전 검사

새 stabilized material attempt는 ModelingPlan의 non-omitted `surface_details`를 closure와
preflight에서 다시 검증합니다. 각 detail은 stable detail/object/material ID, `image|hybrid`
strategy, `UVMap`, current UV layout fingerprint, requested channel, coverage ID, exact mask 또는
bounded `uv_rect`, wrap policy에 결속되어야 합니다.

candidate MaterialPlan/TextureManifest mapping과 다음이 하나라도 다르면 appearance approval 전에
fail closed합니다.

- object/material/detail ID 또는 coverage 부재
- procedural/none strategy로 localized detail을 거짓 충족
- requested PBR channel 또는 mask/image 누락
- UV set/fingerprint/rect/wrap 불일치
- geometry와 surface-detail이 같은 mark를 중복 소유
- reference나 placement provenance가 closure에서 누락

preflight가 coverage를 통과했다는 사실은 reference와 pixel-level 위치가 미적으로 승인됐다는 뜻이
아닙니다. actual neutral preview와 specialized appearance approval은 별도 경계이며, technical UV
binding/path repair에는 사용자 승인을 반복 요구하지 않습니다. UV나 placement bytes가 실제로
바뀌면 새 closure/preflight/preview/approval이 필요합니다.

2026-08-14 current incident dry-run은 non-omitted detail의 image-backed UV coverage가 없어 이 단계에서
`preflight_failed`로 멈췄습니다. Blender/preview/approval/controller/promotion은 실행되지 않았고,
이 early rejection을 appearance quality 판정으로 해석하지 않습니다.
