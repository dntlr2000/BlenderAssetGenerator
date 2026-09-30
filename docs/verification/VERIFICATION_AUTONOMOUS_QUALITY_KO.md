# Autonomous Quality Extension 0.1.0 검증 기록

## 1. 현재 판정

기록일: `2026-08-10`

Windows 11, Python 3.14.6, Blender 5.0.1에서 AQ 전체 gate와 기존 V0.7~V0.9 chained
regression이 통과했다. 코드 registry의 `autonomous_static_prop_v1`만 `verified_active`로
판정한다. 나머지 autonomy profile은 계속 `disabled_experimental`이다.

이 판정은 프로젝트를 V1.0으로 승격하거나 일반 release-ready, arbitrary reference의
before/after 품질 향상, cross-platform 또는 Unity/Unreal runtime parity를 인증하지 않는다.

## 2. 검증 환경

| 항목 | 확인값 |
|---|---|
| OS | Microsoft Windows 11 Home |
| host/uv Python | 3.14.6 |
| Blender | 5.0.1 |
| Blender Python | 3.11.13 |
| render engine | `BLENDER_EEVEE` |
| 프로젝트 버전 | 0.9.0 |
| AQ/Integrated Quality/companion 계약 | 0.1.0 |
| derived-only SceneSpec V03 | 0.3.0 |
| canonical SceneSpec | 0.2.0 |

`uv run cbm doctor`는 Repository/Workspace/Blender/Codex 모두 OK였다.
`uv run cbm blender-compat`는 Blender 5.0.1, Blender Python 3.11.13, EEVEE와
GLB/FBX/OBJ export compatibility를 통과했다.

## 3. 구현 전 기준선

AQ 변경 전 기준선은 다음과 같다.

```text
uv run pytest
→ 945 passed, 6 skipped

uv run ruff check .
→ passed

uv run cbm doctor
→ Repository / Workspace / Blender / Codex: OK

uv run cbm blender-compat
→ Blender 5.0.1, EEVEE, GLB/FBX/OBJ compatibility smoke: passed
```

이 수치는 아래 post-change 결과와 별도 기록이다. 기준선을 새 기능 회귀 통과로 재사용하지
않았다.

## 4. 최종 post-change 결과

| 검증 | 최종 결과 |
|---|---|
| 전체 pytest | `1145 passed, 20 skipped, 8 warnings in 149.21s` (`1165 collected`) |
| 전체 Ruff | `All checks passed!` |
| doctor | Repository/Workspace/Blender/Codex OK |
| Blender compatibility | Blender 5.0.1/Python 3.11.13/EEVEE, GLB/FBX/OBJ passed |
| AQ focused gate | `195 passed, 2 skipped, 8 warnings in 16.98s` |
| 실제 Blender AQ 묶음 | `14 passed, 6 warnings in 352.03s` |
| AQ benchmark | `8/8` expectation matched, Blender structural case 3개 실행 |
| AQ 통합 gate | exit code 0 |
| V0.7/V0.8/V0.9 chained regression | passed |

AQ 통합 gate portable evidence root:

```text
verification/evidence/aq_v1_20260810
```

원 실행은 격리된 외부 basetemp를 사용했지만 해당 임시 경로를 영구 의존성으로 유지하지
않는다. benchmark, 성공 package/roundtrip/handoff terminal closure, 비통과 review bundle의
바이트 동일 snapshot을 위 저장소 상대 경로에 보존했다. raw pytest stdout과 전체 basetemp는
보존하지 않았으므로 새 설치의 최신 통과 주장은 gate 재실행이 필요하다. 사용자 workspace나
canonical evidence를 gate 성공용으로 변경하지 않았다.

## 5. 핵심 계약과 host 검증

최종 focused/전체 회귀는 다음을 포함했다.

- strict Pydantic contract와 checked-in JSON Schema parity
- Reference Evidence와 camera hypothesis의 exact input SHA-256/provenance 결속
- AQ `0.1.0` authoritative top-level envelope의 schema-required 필드와 strict nested provenance
- 인위적인 AQ `0.1.0` empty/partial envelope 거부; 기존 V0.x contract 호환성은 변경 없음
- candidate-owned build/inventory/validation/ModelingPlan/effective SceneSpec/assembly/topology
  evidence와 8개 named candidate hard gate
- hard-gate → regression → meaningful gain → Pareto → 최소 변경 순위의 controller/evaluator
  일치
- first-use PolicyAuthorization persist → reload → root/profile/budget/target/dependency/
  predecessor/single-use/file-hash identity 재검증
- 기본 최대 2회의 material round와 strict canonical MaterialPlan promotion
- duplicate, A-B-A, A-B-C-B, repeated direction, plateau, repeated failure와 budget 종료
- quality non-pass/bounded termination의 best-known review routing
- package repair의 fresh `-aqrNN` ID와 format-only/collision 제한
- Windows 장경로 package/handoff generation과 V0.9 postflight의 동일 recursive digest
- terminal IQ/profile/provenance/package/roundtrip/review/handoff nested revalidation

unavailable material 또는 production evidence는 pass가 아니라 `unscorable`로 유지됐다.

## 6. SceneSpec V03와 실제 Blender structural 검증

AQ structural assignment는 legacy 3-output V02 경로와 optional full SceneSpec V03 경로를
모두 통과했다. V03 경로는 모든 structural object를 candidate-owned recipe, mesh, receipt와
`.blend` evidence로 materialize하고 기존 build가 읽는 path-backed V02 candidate로 compile한
뒤에만 평가한다. exact promotion 전 canonical SceneSpec은 바뀌지 않았다.

실제 Blender 묶음에는 다음 structural materialization이 포함됐다.

- loft
- sweep
- multi-loop extrusion
- boolean tree
- whitelisted `linear_instance_v1` Geometry Nodes
- scale/shading, Assembly BVH와 Topology/UV companion
- legacy V02 candidate build
- quality-pass package/roundtrip/handoff terminal
- review-only terminal

`SceneSpec V03` public plan/apply는 exact plan SHA-256에 결속된 derived copy/receipt만 만들며
canonical `analysis/scene_spec.json`을 승격하지 않는 회귀도 통과했다.

## 7. deterministic benchmark

권위 report:

```text
verification/evidence/aq_v1_20260810/autonomous_quality_benchmark.json
SHA-256: 0946535b3e148ddc159248ef0bc14aac2c3388fce33715dcdfe9056efa0adb39
```

8개 case 모두 expected outcome과 일치했다. Blender는 manifest가 지정한 structural case
3개만 실행했다.

- `tapered_loft`
- `curved_sweep`
- `boolean_panel`

`topology_uv_failure`는 의도한 hard failure가 관찰됐기 때문에 benchmark pass다. 이
benchmark는 contract, 결정론과 materialization fixture이며 reference-image reconstruction의
before/after 유사도나 예술적 완성도를 측정하지 않는다.

## 8. quality-pass package, roundtrip과 handoff terminal

성공 job/session:

```text
job: aq_full_box
session: aq-20260810t065207677077z-26250066
root: verification/evidence/aq_v1_20260810/aq_full_box
```

| evidence | workspace-relative path | SHA-256 |
|---|---|---|
| terminal | `production/autonomy/aq-20260810t065207677077z-26250066/terminal.json` | `02b9ec22b7083bd6da7ede57b605716eb3b7b4bba362e6af7bfb86fc41cc203c` |
| final IQ | `production/autonomy/aq-20260810t065207677077z-26250066/integrated_quality/final/integrated_quality_report.json` | `58cd55c8c9dfcefe576d0021cde36ac617c66f4b61451ff84624adc07c1ad835` |
| package manifest | `exports/packages/portable_gltf/v08-f3830cf3-package/package_manifest.json` | `bde51602fefa67b888c04b7333a3661b44076f35bd957526d662aff55744810b` |
| roundtrip | `optimization/runs/v08-f3830cf3/roundtrip/v08-f3830cf3-package/roundtrip_validation.json` | `4ae8bc9f0680f3a77b3e0b886e08155c5251f6bab05cf653b3798a6e8d5a1925` |
| handoff manifest | `exports/destination_handoffs/portable_gltf/v08-f3830cf3-package/v08-f3830cf3-handoff/codex_handoff/handoff_manifest.json` | `1c8ef0cc605c93079fc6bc4171ac59aa52002a45d3fcf7ff6a8b6e671a83d67a` |

terminal은 `quality_passed` / `quality_target_reached`다. package 결과:

- `asset.glb`: SHA-256
  `7e2c658f920291e4cd37a799281dbabbbe076981e6f2f1734d6f12a7ac2f6cd3`,
  338,712 bytes
- manifest file count: 33
- missing dependency: 0
- absolute path: 0
- raw PBR와 derived ORM 보존
- imported bounds relative error: 0
- semantic identity coverage: 1.0
- material identity coverage: 1.0
- fresh clean-import roundtrip: passed
- package-bound Destination Handoff: generated and validated
- destination project write: 없음

roundtrip warning은 axis/unit metadata의 독립 inspector 부재, custom split-normal/tangent
equivalence와 일부 UV association의 미검증을 숨기지 않는다. passed는 clean import와 명시된
검증 범위의 성공이지 destination runtime parity가 아니다.

## 9. review-only terminal

검토 job/session:

```text
job: aq_review_box
session: aq-20260810t065903952936z-2bb7e15e
root: verification/evidence/aq_v1_20260810/aq_review_box
```

| evidence | workspace-relative path | SHA-256 |
|---|---|---|
| terminal | `production/autonomy/aq-20260810t065903952936z-2bb7e15e/terminal.json` | `254cd7c87d288a714c05fa98e48993c5fae65f6cae4d01874ffb411c2baf094d` |
| final IQ | `exports/review_bundles/aq-20260810t065903952936z-2bb7e15e-review/integrated_quality_report.json` | `7e72cbadbd108dd958bfebdda9b47acc1915aa21ba27c371dd08fb9b83d378ed` |
| review manifest | `exports/review_bundles/aq-20260810t065903952936z-2bb7e15e-review/review_bundle_manifest.json` | `b30441e0a0f98ac9584f2e619520d430c8b5d3cef9f8ce239fab83c800ec2df6` |

terminal은 `review_required` / `global_budget_exhausted`다. review manifest는
`production_ready=false`, `destination_handoff_eligible=false`이며 package와 handoff는
생성되지 않았고 roundtrip도 없다. budget 종료가 quality pass로 변조되지 않고 best-known
evidence와 manual action으로 라우팅되는 경로를 실제 Blender 실행으로 검증했다.

## 10. 기존 V0.7~V0.9 chained regression

AQ gate 안에서 다음 legacy gate가 모두 통과했다.

```text
historical 2026-08-10 raw roots: not distributed
portable AQ 0.1 execution record: verification/evidence/aq_v1_20260810/README.md
newest portable legacy regression snapshots: verification/evidence/v07_20260811/,
  verification/evidence/v08_20260811/, verification/evidence/v09_20260811/
```

- V0.7: GLB/FBX/OBJ package와 roundtrip regression
- V0.8: standard/background workflow regression
- V0.9: read-only audit, production/controller와 Destination Handoff gate

기존 workflow, approval, receipt, blocked state와 canonical SceneSpec `0.2.0`은 자동 migration,
resume, retry 또는 재분류되지 않았다.

## 11. 남아 있는 제한과 미검증 항목

1. arbitrary reference 자산의 동일 camera before/after 품질 향상 benchmark는 없다.
2. `autonomous_static_prop_v1` 외 environment/architecture/measured profile은 검증·활성화하지
   않았다.
3. 단일 이미지의 후면, 내부, 절대 깊이는 recovered truth가 아니라 inferred다.
4. MaterialGraphSpec `0.1.0`은 companion이며 모든 material round의 mandatory canonical
   입력이 아니다.
5. standalone structural materializer의 임의 260자 초과 Windows 경로는 제한이 남는다.
   package/handoff 장경로 hash parity 수정과는 별개다.
6. package repair는 package-ID collision과 format-only roundtrip 실패만 처리한다.
7. cycle의 change-direction 분류와 changed-path tie-break는 보수적인 coarse heuristic이다.
8. `desktop_in_session`은 현재 Codex가 exact assignment를 작성할 수 있게 하지만 enforcing
   supporting-client sandbox나 task allowlist attestation을 제공하지 않는다.
9. full Blender fault-injection interruption/resume E2E는 별도 미검증이다. unit/host receipt와
   recovery 회귀는 통과했다.
10. macOS/Linux, Blender 4.x 실기동, Unity/Unreal/custom destination import와 runtime
    material/shader parity는 검증하지 않았다.
11. derived SceneSpec V03의 canonical 승격은 공개 기능이 아니며 자동 migration도 없다.
12. benchmark와 fixture 결과를 실제 소품의 예술적 완성도 또는 일반 성공률로 확대 해석할
    수 없다.

## 12. 판정 요약

검증된 것은 Windows 11/Blender 5.0.1에서의 `autonomous_static_prop_v1` bounded contract,
후보/authorization/material/quality 흐름, quality-pass portable GLB/roundtrip/handoff terminal,
review-only terminal과 기존 V0.7~V0.9 회귀다. 프로젝트는 계속 `0.9.0`, AQ는 `0.1.0`,
canonical SceneSpec은 `0.2.0`이며 V1.0 승격은 별도 release 판단이 필요하다.
