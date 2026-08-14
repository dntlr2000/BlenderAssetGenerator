# Codex ImageGen 0.2 Material Loop 검증 기록

> 재확인 날짜: `2026-08-13`. 이 문서는 실제 실행 범위를 fake, historical actual source,
> approval-free mechanism과 production authority로 분리한다. 아래 값은 같은 날짜의 최종 로컬
> 실행 결과이며 GitHub-hosted/self-hosted CI 실행으로 해석하지 않는다.

## 1. 기준선과 상태

- Project: `0.9.0`
- canonical SceneSpec: `0.2.0`
- AQ v2 / IQ: `0.2.0`
- Codex Built-in ImageGen core: `0.1.0`
- Material Loop contract: additive `0.1.0`
- Blender verification target: `5.0.1`
- `autonomous_static_prop_v2`: `disabled_experimental`
- `autonomous_static_prop_v2_codex_imagegen`: `disabled_experimental`
- human review: `not_performed`
- destination runtime parity: `unverified`

기존 provider 검증의 `reports/codex_imagegen_manual_20260811`과 generated source는 수정하지 않았다.
과거 ImageGen `0.1.0`/MaterialAuthoring `0.2.1` 기록은 당시 staging 경계의 역사이며 이번 full-loop
결과로 소급 재분류하지 않는다.

## 2. 구현된 연결

현재 code surface에서 확인한 연결은 다음과 같다.

- native source adoption → immutable original → adoption-receipt-bound deterministic normalization
  → `CodexImageNativeCorePreparationReceipt 0.1.0` → 기존 core completion/selection의 recursive closure와
  exact normalized-to-core byte identity
- current-task non-human semantic review와 bridge/controller/promotion-bound companion-only
  multi-candidate ranking/selection receipt
- V0.5 normalized/bridge evidence와 exact canonical-material absence
- exact bridge/controller input, ControllerExecutor request/result와 lifecycle recovery
- staging-only/compile-not-run V0.5 의미를 보존하는 별도 actual Blender shadow preflight와
  preflight 없는 `exact_adoption` 차단
- host MaterialGraph compile, canonical CAS, Blender rebuild/validate와 actual
  `MaterialPhaseReceiptV2`
- neutral preview, promotion companion, base AQ resume와 IQ `0.2.0` boundary
- terminal `quality_approved|review_required|blocked|failed|cancelled`
- 기존 review-only/V0.7 delivery supervisor 경계
- 기존 ImageGen core 표면과 별도 Material Loop CLI 9개/MCP 9개

## 3. historical actual built-in source

재사용한 보존 source:

- path:
  `C:\Users\Woosik\.codex\generated_images\019f5f6c-86f9-7432-bd81-c38e61a8c566\exec-e9661e84-0393-4c1c-b50d-c30eaf99adc7.png`
- dimensions: `1254×1254`
- bytes: `2,484,395`
- SHA-256: `82ce3d6efc85cef6aa3e166f007f0509c97dc698b378ffd7e7262eb1cc33372f`
- historical evidence root: `reports/codex_imagegen_manual_20260811`

이번 작업은 이 PNG를 새 unique run의 immutable input으로 채택했으며 fresh ImageGen invocation을
수행하지 않았다. current Codex task의 observation은 non-human이고 repeat/tile suitability가 충분히
해소되지 않아 semantic outcome은 `review_required`다. 따라서 canonical MaterialPlan baseline을
바꾸지 않고 promotion 전에 멈췄다.

정확한 주장:

- native adoption/normalization/core-preparation과 current-task semantic-review boundary: 검증됨
- fresh built-in ImageGen invocation: 수행하지 않음
- human review: 수행하지 않음
- actual-source canonical promotion/MaterialPhaseReceipt/IQ/package: 수행하지 않음
- 과거 MaterialAuthoring `0.2.1` receipt의 `blender_compilation_status=not_run`: 그대로 보존

해당 focused test의 구현 중간 실행 기록은 `1 passed`였다. 최종 Material Loop 묶음은 아래
대장의 실제 기록을 따른다.

## 4. fake four-family material/IQ 범위

`wood`, `signage_decal`, `emissive`, `crystal`은 명시적으로 deterministic fake source다. 실제
Blender 5.0.1을 사용하는 fixture가 각 family에서 host material promotion, actual
`MaterialPhaseReceiptV2`, preview와 IQ 경계를 실행했다. 이는 contract와 Blender mechanism
evidence이며 actual ImageGen, general material quality 또는 human approval이 아니다.

최종 실제 Blender material→IQ 실행은 네 family 모두 통과했다.

```text
4 passed in 101.63s
verification/evidence/imagegen_material_loop_20260813
```

## 5. review-only와 approval-free delivery

별도 actual Blender `review_only` fixture는 package 없는 종료를 통과했다.

```text
1 passed in 55.24s
verification/evidence/imagegen_material_loop_20260813
```

네 fake family의 portable delivery 검증은 실제 사용자 OptimizationApproval을 합성하지 않는다.
각 flow는 V0.7 review를 만든 뒤 `waiting_for_v07_approval`에서 멈추며 production `package_asset`은
approval 부재를 거부해야 한다. 그 뒤 별도 test-only mechanism root에서 raw GLB/FBX exporter와 fresh
Blender clean import, geometry/material survival만 검사한다.

```text
5 passed, 1 skipped in 345.23s (review-only 1 + fake family 4; actual-source env unset)
verification/evidence/imagegen_material_loop_20260813
```

이 mechanism evidence에는 다음 주장을 할 수 없다.

- 사용자가 특정 V0.7 plan hash를 승인함
- immutable production package가 accepted됨
- production-ready delivery result 또는 completed delivery terminal이 생성됨
- Destination Handoff 또는 Unity/Unreal runtime parity가 검증됨

이전 개발 중 synthetic `approved_by=user` fixture를 사용한 dual-package 실행은 제품 승인 증거에서
제외했다. 그 진단 history는 지우지 않지만 최종 package acceptance로 인용하지 않는다.

## 6. targeted host/Blender evidence

최종 full gate 전에 관찰한 bounded 결과는 다음과 같다. 이 값은 최종 전체 합계가 아니다.

| 범위 | 실행 결과 |
|---|---|
| material-loop host bundle, lifecycle hardening 전 최신 기록 | `114 passed` |
| native adoption/normalization/V0.5 focused agent bundle | `59 passed, 5 skipped` |
| native 1254×1254 → 64×64 integration | passed |
| material graph Windows long-path compile | passed |
| package Windows long-path roundtrip focused | `4 passed, 1 skipped` |
| existing AQ v2 dual-delivery normal quantization regression | `1 passed in 26.24s` |
| existing GLB/FBX geometry-survival Blender regression | `1 passed in 6.10s` |
| actual-source semantic boundary | `1 passed in 11.38s` |
| instruction checker intermediate | passed; root `7764` bytes, files `12`, invariants `192` |

후속 lifecycle/ranking/public-surface 변경이 있으므로 최종 판정은 7절 결과만 사용한다.

## 7. 최종 검증 대장

아래 표는 2026-08-13 Material Loop 당시의 exact 결과를 보존한다. 실행되지 않은 항목은
`not_run`으로 남기며, 2026-08-14 Material Closure 전체 회귀와 혼합하지 않는다.

| 검증 | 최종 결과 |
|---|---|
| `uv sync --frozen --extra dev --extra vision` | passed; official AQ host run |
| `uv run ruff check .` | passed |
| Material Loop focused host/schema/security/public/recovery | `160 passed, 1 skipped in 19.49s` |
| 전체 `uv run pytest` | `1569 passed, 56 skipped, 8 warnings in 257.44s` |
| fake 4-family actual Blender material/IQ | `4 passed in 101.63s` |
| fake 4-family approval-free raw GLB/FBX clean import | full file `5 passed, 1 skipped in 345.23s` |
| historical actual source review boundary | `1 passed in 10.96s`; delivery-stop `1 passed in 14.81s`; `review_required` |
| actual Blender `review_only` | `1 passed in 55.24s` |
| AQ v2 focused/Blender gate | host `616 passed, 24 skipped, 8 warnings`; safe Blender split `42 passed, 1 skipped`; AQ 0.1 `8/8`, AQ 0.2 `10/10` |
| V0.7/V0.8/V0.9 chained regression | `not_run`: legacy opt-in fixtures synthesize user-approval semantics; ordinary host regressions are included in full pytest |
| `uv run cbm doctor` | passed |
| `uv run cbm blender-compat` | passed: Blender `5.0.1`, Python `3.11.13`, GLB/FBX/OBJ |
| instruction checker | passed: root `7764`, files `12`, invariants `192` |
| repository summary/schema/catalog/CI parity | passed: schema check, catalog/public/CI `59 passed`, alternate-index summary projection current |
| `git diff --check` | passed; line-ending notices only |

최종 evidence root와 command log:

```text
verification/evidence/imagegen_material_loop_20260813
verification/evidence/imagegen_material_loop_20260813/command-log.txt
```

## 8. public surface 판정

Material Loop additive public surface는 CLI 9개와 MCP 9개다. 기존 ImageGen core의 CLI 5개/MCP
5개는 그대로 유지된다. 최종 registry/config/help parity 결과는 7절에 기록한다.

Material Loop 명령은 native adoption/normalization, semantic status, bridge plan/status/run,
actual Blender shadow exact-adoption preflight, host promotion/resume와 one-step AQ/IQ continuation만
제공한다. preflight는 `ControllerResult`나 canonical/destination write를 만들지 않는다. 어느 표면도
ImageGen API 호출, semantic review 작성, user approval 작성, arbitrary controller output, canonical
직접 write나 destination write는 제공하지 않는다.

## 9. 최종 주장 제한

최종 gate가 통과하더라도 다음은 주장하지 않는다.

- profile activation 또는 production readiness
- fresh actual ImageGen invocation
- 사람의 semantic/material/art review
- actual user V0.7 approval이나 accepted production package
- arbitrary material family/reference에 대한 일반 품질 보장
- Unity, Unreal 또는 custom destination runtime parity
- rig, animation, gameplay, CAD B-Rep 또는 engine graph 지원

따라서 올바른 profile 상태는 계속 `disabled_experimental`이다.

## 10. 2026-08-14 Material Closure 후속 상태

Material Closure Stabilization은 기존 Material Loop 결과 뒤에 추가되는 별도 gate다. 이 문서의
2026-08-13 fake-family/historical-source/Blender 결과는 graph-derived full dependency closure,
comprehensive preapproval full-scene shadow compile, specialized appearance approval 또는 current
Crystalgun repair session의 통과 증거가 아니다.

현재 verified incident head는 `0012 / terminal / cancelled / none`이며 canonical MaterialPlan,
`MaterialPhaseReceiptV2`, rendered neutral preview, IQ와 user appearance approval이 없다. 따라서
existing retry 실행, current asset promotion과 delivery는 `not_run`이다. Append-only repair dry-run은
closure 뒤 image-backed UV coverage 누락으로 Blender/preview/approval/controller 전에
`preflight_failed`가 됐다. 한 procedural actual-Blender preapproval fixture는 통과했지만
ImageGen+localized 및 crystal/emission/alpha fixture와 authorized promotion은 `unverified`다. 상세
결과는 [Material Closure 검증 기록](VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md)에 기록한다.
Profile은 계속 `disabled_experimental`이다.
