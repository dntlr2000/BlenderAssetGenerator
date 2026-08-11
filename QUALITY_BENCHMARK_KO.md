# Autonomous Quality 0.2 품질 Benchmark 안내

## 1. 무엇을 검증하는가

AQ 0.2 benchmark는 고정된 camera와 synthetic raster recipe에서 candidate가 의도한 방향으로
개선될 때 contour·silhouette·semantic metric도 같은 방향으로 움직이는지 검증한다. 외부 asset
또는 image provider 없이 exact manifest와 seed로 재현되며, 모든 reference/stage artifact를
SHA-256으로 결속한다.

이 benchmark는 다음을 증명하지 않는다.

- 임의 reference 이미지에서 실제 3D 모델이 더 아름답거나 사실적임
- 사람이 품질을 승인함
- Blender topology, modifier, material 또는 bake가 정확함
- GLB/FBX package나 clean-import round trip이 통과함
- Unity/Unreal runtime parity
- V1.0 출시 준비 완료

host report의 `ok=true`는 manifest가 선언한 **synthetic metric 방향성**을 만족했다는 뜻이다.
production quality pass나 human review가 아니다.

## 2. 현재 fixture

authoritative manifest는 다음 파일이다.

```text
examples/autonomous_quality_benchmarks_v02/manifest.json
```

manifest는 외부 download를 금지하고 `human_review_status=not_reviewed`로 고정한다. 10개 범주는
다음과 같다.

| case | host fixture가 보는 것 | 주장하지 않는 것 |
|---|---|---|
| `simple_hard_surface_box` | body/latch contour와 semantic 위치 | bevel/normal의 실제 Blender 품질 |
| `curved_loft` | loft/cap silhouette 방향 | 실제 loft topology |
| `swept_handle` | handle/grip 위치와 contour | 3D sweep frame/twist 생존 |
| `boolean_panel` | panel/inset mask | Boolean modifier 결과 |
| `ornate_multi_part_prop` | primary/supporting/decorative coverage | 장식 디테일의 예술 품질 |
| `multi_material_prop` | semantic part mask | face material assignment 실기동 |
| `wood_object` | object part 위치 | grain/shader realism |
| `signage_decal_object` | board/decal/pole 위치 | decal pixel/bake 품질 |
| `emissive_crystal_prop` | crystal/base/decorative shape | emission/transmission rendering |
| `small_static_assembly` | assembly part 배치 | contact/BVH/physics 정확도 |

각 case는 known orthographic camera, deterministic reference recipe와 다음 네 stage를 가진다.

```text
v09_initial
aq_v1_initial
aq_v2_initial
aq_v2_final
```

이 이름은 실제 V0.9/AQ v1/AQ v2 production run을 수행했다는 뜻이 아니다. manifest가 비교를
위해 만든 synthetic stage label이며 execution duration도 `deterministic_fixture_model`이다.

## 3. 평가 metric

각 stage에서 다음을 계산한다.

- `silhouette_iou`
- `contour_boundary_f_score`
- `contour_chamfer_norm`
- `mean_semantic_iou`
- `minimum_critical_semantic_iou`

expected direction은 단일 aggregate score가 아니라 metric별로 선언한다. 예를 들어 final로 갈 때
IoU와 boundary F-score는 증가하고 normalized chamfer는 감소해야 한다. hard/critical semantic
finding은 높은 평균에 묻히지 않아야 한다.

IQ 0.2 authoritative hard finding은 benchmark label이나 높은 severity 문자열만으로 성립하지 않는다.
exact required gate ID, 그 gate의 `failed` outcome과 authoritative input hash에 결속해야 한다.
통과했거나 누락된 gate에 hard finding을 삽입한 report는 expected direction이 맞아도 거부된다.

reference와 candidate artifact에는 known camera, beauty, silhouette, object ID와 semantic mask의
exact path/hash/size가 포함된다. 생성된 image가 observed user reference를 대신하는 것은 아니다.

## 4. host benchmark 실행

AQ v1과 v2 benchmark entry point는 분리되어 있다. 기존
`python -m codex_blender_modeler.autonomy_benchmarks`는 v1 의미를 유지하고, v2는 다음 전용 CLI를
사용한다.

```powershell
uv run python -m codex_blender_modeler.autonomy_benchmarks.v02_cli `
  --manifest examples/autonomous_quality_benchmarks_v02/manifest.json `
  --output <AQ_V02_BENCHMARK_REPORT>
```

v1 entry point에 v02 manifest를 넘기거나 v1 성공을 v02 결과로 기록하면 안 된다. 출력 report와
sibling `artifacts/`는 새 격리 경로를 사용하며 기존 evidence를 overwrite하지 않는다.

contract와 byte determinism을 검증하는 focused pytest는 다음과 같다.

```powershell
uv run pytest -q tests/test_autonomous_quality_benchmarks_v02.py
```

test는 `run_benchmark_manifest_v02(...)`를 격리 `tmp_path`에서 직접 호출한다. CLI와 runner는
output 파일과 sibling `artifacts/`가 이미 있으면 overwrite하지 않고 실패한다. report를 다시
만들 때 기존 report나 artifact를 삭제해 재사용하지 않는다.

report의 핵심 필드는 다음과 같다.

- exact manifest/project/autonomy version
- case별 artifact와 metric
- expected direction result
- deterministic execution counters와 termination reason
- Blender status
- package/roundtrip status
- external download 사용 여부
- human review status
- claim-scope limitation

2026-08-11 실행에서는 host 10 case 모두 expected direction을 만족하고 byte-identical report
재생성을 확인했다. 결과는 `10/10 passed`, `human_review_status=not_reviewed`다. 정확한 명령과
실행 범위는 `VERIFICATION_AQ_V02_KO.md`를 따른다.

## 5. Blender opt-in

v02 runner의 `run_blender_smoke=True`는 manifest에서 `blender_smoke_supported=true`인 case만
fixed repository script로 실행한다. 현재 해당 case는 `simple_hard_surface_box`와
`curved_loft` 두 개다.

```powershell
$env:CBM_RUN_AQ_V02_BENCHMARK_BLENDER_SMOKE = "1"
uv run pytest -q `
  tests/test_autonomous_quality_benchmarks_v02.py::test_v02_fixed_blender_probe_smoke
```

전용 CLI에서 같은 bounded Blender case를 요청할 때만 `--run-blender`를 추가한다. 이 옵션은
arbitrary script를 선택하는 표면이 아니며 manifest가 선언한 fixed case만 실행한다.

Blender 실행은 `.blend`, render와 exact receipt를 요구한다. manifest가 지원하지 않는 case는
`not_applicable`, Blender를 요청하지 않으면 applicable case는 `not_requested`로 남는다. skip,
runner 부재, `not_requested`를 `passed`로 바꾸어 읽지 않는다.

2026-08-11 opt-in 실행에서 선언된 두 Blender case가 모두 통과했다(`2/2`). 이는 fixed script가
두 bounded synthetic case의 `.blend`, render와 receipt를 생성했다는 뜻이다. 나머지 8개 case는
manifest상 `not_applicable`이며 arbitrary reference 품질이나 human approval을 증명하지 않는다.
GitHub `blender-smoke.yml`은 별도의 수동 `workflow_dispatch`와
`self-hosted/windows/blender5` runner를 요구하며, local 통과를 원격 workflow 성공으로 바꾸어
기록하지 않는다.

## 6. package와 roundtrip 판독

현재 synthetic manifest의 모든 stage는 다음과 같다.

```text
package_status=not_run
package_format=none
roundtrip_status=not_run
```

따라서 host benchmark 성공을 GLB, FBX 또는 dual delivery 성공으로 인용하면 안 된다.
package/roundtrip은 V0.7 exact approval, exporter, immutable package manifest와 clean-import
evidence로 별도 검증한다.

benchmark report를 quality-approved source처럼 사용할 수도 없다. passed IQ delivery source는 current
canonical ModelingPlan/SceneSpec/blend/build/material/shader/texture/geometry와 accepted
geometry/material promotion receipts 및 survival evidence에 exact 결속돼야 한다.

## 7. tamper와 negative gate

strict contract는 다음을 거부한다.

- case payload를 바꾸고 `contract_sha256`을 갱신하지 않음
- unknown field 또는 arbitrary script 경로 삽입
- 필수 category 제거
- duplicate case/stage/semantic ID
- unsafe output path
- 기존 report/artifact root overwrite
- passed Blender status인데 exact Blender receipt가 없음
- package 미실행인데 format 또는 roundtrip pass를 주장

benchmark source를 바꿨다면 기존 report를 수정하지 않고 새 manifest version과 새 output root를
사용한다.

## 8. 실제 reference benchmark

현재 저장소의 v02 manifest는 synthetic benchmark다. 실제 project-local reference를 비교하려면
별도 manifest에 다음이 필요하다.

- 사용 권리와 provenance가 명확한 immutable reference
- exact camera와 mask registration evidence
- 동일 source, camera, budget과 policy
- 비교 run별 immutable artifact와 receipt
- 사람이 검토했다면 reviewer identity와 별도 receipt

이 증거가 없으면 `human_review_status=not_reviewed`와 실제 reference 품질
`unverified`를 유지한다. synthetic final이 1.0이라는 이유로 실제 자산의 quality target을
달성했다고 주장하지 않는다.

## 9. 권장 판정 문구

허용되는 요약:

```text
AQ 0.2 synthetic host benchmark에서 10개 fixture의 선언된 contour/semantic metric 방향성이
재현됐고, manifest가 선언한 fixed Blender probe 2개도 통과했다. 사람이 실제 reference 품질을
검토하지 않았고 benchmark의 package/roundtrip은 실행하지 않았다.
```

허용되지 않는 요약:

```text
AQ 0.2가 모든 모델링 품질을 향상했고 Blender 및 Unity 전달까지 검증됐다.
```

최종 활성화 판단은 benchmark 하나가 아니라 host contract, Blender, legacy regression,
delivery/roundtrip, instruction/registry drift와 문서 동기화 evidence 전체를 요구한다.
