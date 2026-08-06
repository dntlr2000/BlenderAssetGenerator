# V0.8 로컬 검증 기록

## 2026-08-05 V0.4 다각도 geometry review 최종 검증

새로 계획되는 V0.8 geometry workflow가 단일 preview 시점에서 끝나지 않도록
asset-local five-view host evidence와 실제 agent visual-review 단계를 추가했다.
canonical V0.6 fixed-reference QA의 비교 카메라, direct score와 정확히 7개 pass는
변경하지 않았다.

검증 결과:

| 항목 | 결과 |
|---|---|
| 통합 targeted 회귀 | 281/281 통과 |
| 전체 Python 회귀 | 871 통과, 4 skip |
| Ruff | 통과 |
| Schema 생성·parity | 통과 |
| Blender 5.0.1 실제 multiview smoke | 1/1 통과, 5 views × 4 passes = 20 PNG |
| geometry workflow 순서 | `validate → five-view host → agent visual review → PDF/gate` |
| 시점·패스 | asset-local 5 views × 4 passes = 20 PNG |
| agent 판정 | 다섯 beauty/wireframe을 모두 소비하고 exact plan/manifest/report hash에 결속 |
| target 선택 | 모든 primary/supporting 및 root/attached의 합집합 |
| occlusion 경계 | per-view unseen은 advisory, all-view disappearance만 structural actionable |
| reference likeness | 보정된 per-view reference가 없어 `unscorable` |
| revision 권한 | recommendation only, 자동 승인·적용 없음 |
| one-shot guarded revision | authored `spatial_v1`에서 baseline/result five-view regression veto·rollback |
| bounded convergence | authored `spatial_v1` plan/run fail-closed; legacy/non-spatial fixed-camera 경로 유지 |
| legacy | 기존 job/plan 자동 migration 없음, evidence 부재 시 omit/not-applicable |
| PDF | 다각도 이미지 포함, machine-readable JSON/hash가 authoritative |
| 실제 사용자 job 변경 | 없음 |

최종 격리 증거:

- V0.8: `reports/v08_smoke/001845103-15940/`
- V0.7: `reports/v07_smoke/20260805T001117719Z-40540/`
- background preview: `completed / delivered_for_review`, `quality_status=unscorable`
- portable continuation: `completed`, FBX clean-import round trip `passed`
- V0.7 package round trip: FBX/GLB/OBJ 모두 `passed`

실행한 targeted 명령:

```powershell
uv run pytest -q tests/test_qa_multiview_sanity.py `
  tests/test_qa_structural_regression.py `
  tests/test_auto_revision.py `
  tests/test_auto_revision_service.py `
  tests/test_visual_convergence_service.py `
  tests/test_v08_orchestration.py `
  tests/test_v08_artifact_lifecycle.py `
  tests/test_pdf_reporting.py `
  tests/test_v06_schemas.py `
  tests/test_qa_diagnostic_models.py `
  tests/test_qa_diagnostic_service.py `
  tests/test_qa_camera_geometry_attribution.py
uv run pytest -q
uv run ruff check .
$env:CBM_RUN_BLENDER_ASSEMBLY_SMOKE='1'
uv run pytest -q tests/test_blender_assembly_runtime.py -k host_multiview_render_smoke
```

이 기록은 plan/manifest/report/agent-review의 hash binding, workflow 순서, PDF 수집,
one-shot rollback과 legacy 경계를 검증한 회귀 결과다. 새로운 실제 reference 자산을
Blender로 끝까지 제작해 측면·후면 유사도나 미적 품질을 검증했다는 뜻은 아니다.

## 2026-07-28 레퍼런스 오브젝트 전용 범위 검증

새 job에 실행 정책과 독립적인 `reference_content_scope`를 추가했다.
기존 동작은 `full_reference` 기본값으로 유지하고,
`primary_object_only`는 명시적 `target_subject` 및
primary/supporting 역할이 있는 객체만 허용한다.

검증 결과:

| 항목 | 결과 |
|---|---|
| content-scope·reference-mask·workflow targeted | 58/58 통과 |
| 전체 Python 회귀 | 436/436 통과 |
| Ruff | 통과 |
| Schema 재생성과 계약 테스트 | 통과 |
| legacy/standard 기본값 | `full_reference`, 기존 build provenance shape 유지 |
| object-only CLI smoke | job/request/plan/state 모두 동일 scope와 target 보존 |
| object-only SceneSpec context 차단 | build 전 fail-closed |
| object-only V0.6 reference mask | 관찰된 primary/supporting evidence bbox로 제한 |
| V0.8 격리 orchestration gate | 통과 |
| V0.7 GLB/FBX/OBJ clean-import 회귀 | 모두 통과 |
| 실제 사용자 job 변경 | 없음 |

격리 증거:

- V0.8: `reports/v08_smoke/192534942-46932/`
- V0.7: `reports/v07_smoke/20260727T192113549Z-46932/`
- object-only plan:
  `reports/object_scope_smoke/20260727T192740236Z/`

텍스트 target이 모호한 이미지에서 자동으로 정확한 대상 mask를 복원한다고
주장하지 않는다. 이 경우 job 생성 전에 대상 설명을 구체화해야 하며,
향후 사용자가 제공하는 명시적 mask/bbox 입력은 별도 계약으로 검토한다.

## 2026-07-27 execution/quality 분리와 bounded fit 최종 검증

새로 계획되는 `background_exterior` workflow에
`fast_quality_policy=review_delivery_v2`를 적용했다. 기존 blocked workflow와
사용자 job은 수정·재개·재분류하지 않았다.

검증 환경:

- Project: `0.9.0`
- Workflow contract: `0.8.0`
- Blender: `5.0.1`
- Render engine: `BLENDER_EEVEE`

검증 결과:

| 항목 | 결과 |
|---|---|
| targeted quality/lifecycle/orchestration/PDF/Schema | 65/65 통과 |
| 전체 Python 회귀 | 431/431 통과 |
| Ruff | 통과 |
| Schema generation/parity | 통과 |
| 단순 isolated quality fixture | `passed`, review delivery 완료 |
| 복잡 isolated quality fixture | `needs_revision`, high finding 보존, review delivery 완료 |
| 불충분 evidence fixture | `unscorable`, 품질 합격 비주장 |
| pre-QA fit | refinement 최대 2회, 개선 candidate만 promotion, 비개선 baseline 유지 |
| 실제 Blender fast preview | `completed` / `delivered_for_review` |
| 실제 smoke quality | `unscorable`, standard workflow 권장 |
| canonical QA | 정확히 1 run, 정확히 7 pass |
| generated target / automatic revision / external provider | 없음 / 없음 / 없음 |
| scope·안전 위험 회귀 | `requires_standard_workflow` 유지 |
| artifact/candidate tampering 회귀 | `orchestration_artifact_conflict` 유지 |
| fast portable approval 경계 | exact V0.7 optimization-plan SHA-256에서 정지 |
| V0.7 GLB/FBX/OBJ clean-import round trip | 모두 `passed`, 오류 0 |
| 기존 사용자 job 변경 | 없음 |

최종 격리 게이트:

- V0.8: `reports/v08_smoke/163329903-19304/`
- V0.7: `reports/v07_smoke/20260727T163054181Z-19304/`

실제 fast preview는 direct score `0.875507`을 기록했지만 primary role/reference
evidence를 신뢰할 수 없어 `quality_status=unscorable`로 정직하게 분류했다.
이는 `status=completed`가 품질 합격을 뜻하지 않는다는 새 상태 모델을 실제
Blender run에서 확인한 결과다.

pre-QA fit은 workflow-owned SceneSpec candidate, role map, attempt evidence와
promotion receipt를 exact hash로 묶는다. 최종 quality report는 canonical
SceneSpec, embedded build, canonical QA request model, seven-pass manifest,
role map과 fit report를 다시 검사한다. 시각적 high finding은
`needs_revision`이지만 preview 실행을 막지 않는다. InteriorScope, measured
constraint, rig/animation/gameplay, engine-specific 요구와 unsafe ambiguity는
계속 `requires_standard_workflow`이며, unexpected source/candidate/receipt
변조는 `orchestration_artifact_conflict`다.

## 2026-07-27 artifact lifecycle 충돌 수정 검증

새로 계획되는 workflow에 material candidate/promotion, shared-derived snapshot,
exact QA run과 workflow-owned PDF lifecycle을 적용했다. 기존 blocked workflow는
수정·재개·재시도하지 않았다.

검증 환경:

- Project: `0.9.0`
- Workflow contract: `0.8.0`
- Blender: `5.0.1`
- Render engine: `BLENDER_EEVEE`

검증 결과:

| 항목 | 결과 |
|---|---|
| targeted lifecycle/Schema/material 회귀 | 56/56 통과 |
| 전체 Python 회귀 | 416/416 통과 |
| Ruff | 통과 |
| Schema generation/parity | 통과 |
| fast `preview_only` 실제 lifecycle | `completed` / `delivered_for_review` |
| 직접 QA | 정확히 1 run, 7 pass, generated target 없음 |
| 자동 revision / external provider | 없음 / 없음 |
| fast `portable_package` 승인 경계 | exact V0.7 plan SHA-256에서 정지 |
| 승인 fixture 뒤 FBX package/round trip | 통과 |
| V0.7 GLB/FBX/OBJ round trip 회귀 | 전부 통과 |
| 기존 사용자 job 변경 | 없음 |

최종 격리 게이트:

- V0.8: `reports/v08_smoke/095354909-16296/`
- V0.7: 같은 통합 gate가 생성한 최신 `reports/v07_smoke/` run

예상된 downstream supersession은 이전 step의 실행 시점 snapshot과 receipt를
보존한다. 예상하지 않은 canonical/source 변경은 계속 stale 또는
`orchestration_artifact_conflict`로 차단한다.
이 lifecycle 검증 뒤 추가된 `review_delivery_v2` 정책에서는 high-severity
visual finding을 `needs_revision`으로 전달한다. `requires_standard_workflow`는
constraint/measured 또는 제외된 scope·안전 위험에만 사용한다.

## 2026-07-27 배경 외관 빠른 실행 정책 추가 검증

기존 `standard` 정책을 기본값으로 유지하면서, 명시적으로만 선택되는
`background_exterior` 실행 정책과 `preview_only` / `portable_package`
종료 범위를 같은 V0.8 오케스트레이션에 추가했다.

- Project: `0.9.0`
- Workflow contract: `0.8.0`
- Blender: `5.0.1`

검증 결과:

| 항목 | 결과 |
|---|---|
| Python 회귀 | 416/416 통과 |
| Ruff | 통과 |
| V0.8 격리 smoke | 통과 |
| `standard` 계획 회귀 | 통과 |
| 빠른 preview 계획 | 통과 |
| 빠른 portable package 계획 | 통과 |
| V0.7 GLB round trip | `passed`, 오류 0 |
| V0.7 FBX round trip | `passed`, 오류 0 |
| V0.7 OBJ round trip | `passed`, 오류 0 |

격리 산출물:

- V0.8: `reports/v08_smoke/20260727T064220084Z-47384/`
- V0.7: `reports/v07_smoke/20260727T063910186Z-47384/`

이 절은 최초 fast-lane baseline의 역사적 검증 기록이다. 이후
`review_delivery_v2`가 high visual finding 처리와 pre-QA fit을 보완했다.
빠른 실행 정책은 프록시·상세·재질·QA의 일반 검토 gate를 계획에서
생략하지만, agent-authored 계약의 completion marker와 V0.7 optimization
plan의 exact-hash 전용 승인은 유지한다. 직접 레퍼런스 QA는 한 번만
수행하고 생성형 QA target과 자동 revision은 사용하지 않는다. 현재 정책은
큰 시각 차이를 `needs_revision`으로 전달하고, 실측·실내 등 실제 scope 위험만
`requires_standard_workflow`로 중단한다.

이번 smoke는 새 정책의 계약·라우팅·계획·승인 경계를 격리 환경에서
검증한 것이다. 실제 신규 레퍼런스 자산의 agent-authored SceneSpec,
재질 및 시각 품질을 무인 완성했다고 주장하는 검증은 아니다.

## 2026-07-20 기존 V0.8 baseline 기록

검증 일자: 2026-07-20  
프로젝트: `0.8.0`  
Workflow contract: `0.8.0`  
Blender: `5.0.1`

## 실행 명령

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_v08_gates.ps1 -SkipVision

# PDF 승인 단계가 추가된 최종 V0.8 오케스트레이션만 재검증
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_v08_gates.ps1 -SkipV07 -SkipVision
```

게이트는 기존 `workspaces/first_reference_test`를 사용하지 않았다. 다음 격리 경로에서만 smoke 작업을 수행했다.

- V0.7 회귀: `reports/v07_smoke/20260720T144136434Z-27412/`
- V0.8 orchestration 최종 smoke: `reports/v08_smoke/20260720T173415567Z-38612/`

## Python과 공개 계약

| 항목 | 결과 |
|---|---|
| pytest | 358/358 통과 |
| Ruff | 통과 |
| doctor | Repository / Workspace / Blender / Codex 모두 OK |
| V0.8 schema parity | 통과 |
| CLI 공개 명령 | 통과 |
| MCP allowlist | 통과 |

V0.8 전용 검증에는 새 job 격리, 기존 primary reference 재사용 거부, `add_view`, agent marker 신선도, 일반 승인 hash, cancel, live/stale lock, 실패 재시도, interrupted attempt, 미지원 목적지 fallback, 모호한 intent 거부가 포함됐다.

`first_reference_test` 격리 검증에서 기존 job과 동일한 reference에 명시적 `new_asset`을 허용하는 경로가 발견되어 보완했다. 현재는 reference hash와 무관하게 기존 job의 `new_asset`을 파일 생성 전에 거부하고 `revise_asset` 또는 새 `job_id`를 요구한다.

## Blender 5 호환성과 V0.7 회귀

| 항목 | 결과 |
|---|---|
| Blender version | `5.0.1` |
| render engine | `BLENDER_EEVEE` |
| color management | `AgX - Medium High Contrast` |
| GLB compatibility export | 성공 |
| FBX compatibility export | 성공 |
| OBJ compatibility export | 성공 |
| V0.7 material conversion | 성공 |
| V0.7 export PDF + sidecar | 성공 |

세 portable profile의 optimization review와 exact plan approval을 모두 거친 뒤 package와 fresh Blender clean import를 검증했다.

| profile | LOD | collider | round trip | bounds max error | semantic/material coverage |
|---|---:|---|---|---:|---:|
| `portable_gltf` | enabled | compound | passed | `0.0 m` | `1.0 / 1.0` |
| `fbx_interchange` | enabled | compound | passed | `0.000001 m` | `1.0 / 1.0` |
| `obj_legacy` | disabled | none | passed | `0.000001 m` | `1.0 / 1.0` |

경고 수는 GLB 6, FBX 8, OBJ 10이었다. 이는 format별 material semantics, axis/unit metadata의 별도 inspector 부재, split normal/tangent/UV 대응의 제한처럼 기존 V0.7에서 문서화된 `partially_verified` 항목이다. 실패 항목은 0이었다.

V0.7 cost report도 `ok: true`, `canonical_unchanged: true`를 기록했다. `portable_gltf` smoke에서는 semantic-safe batching으로 LOD0 render object와 material-slot draw-call proxy가 16에서 12로 줄었고, LOD0 triangle 6,512개와 전체 derived triangle 12,532개는 유지됐다.

## V0.8 orchestration smoke

새 job `v08_proxy_smoke` 결과:

| 항목 | 결과 |
|---|---|
| workflow ID | `wf-20260720t173416z-84c55f59` |
| 분석 단계 | 완료 |
| milestone | `analyzed` |
| 현재 상태 | `waiting_for_agent` |
| 현재 단계 | `geometry.modeling_plan` |
| analyzer scaffold integrity | `valid` |
| analyzer scaffold verification | `partially_verified` |

초안 modeling plan은 구조적으로 유효하게 표시되지만 `stage=authored` 전에는 agent completion을 기록할 수 없음을 별도 테스트로 확인했다.

프록시 workflow에는 `build → render → inspect → validate` 뒤 `reports/pdf/proxy_report.pdf`와 sidecar manifest를 생성하는 단계가 포함되며, 그 PDF가 생성된 뒤에만 exact proxy approval gate가 열린다. 단위·통합 테스트에서는 실제 PDF와 sidecar 생성, PDF 이전 승인 금지, machine-readable JSON/hash 우선 규칙을 확인했다. 최신 smoke는 실제 모델링 계획을 에이전트가 작성해야 하는 정상 경계에서 멈췄으므로 PDF는 아직 생성되지 않은 것이 기대 결과다.

기존 `geometry_showcase`에 `portable_package`, `fbx_interchange`, destination `unity`를 명시한 계획은 다음과 같이 처리됐다.

- destination status: `unsupported`
- terminal boundary: `portable_package`
- workflow terminal approval: `portable.final_approval`
- 경고: 검증된 Unity adapter가 없으므로 V0.7 engine-neutral package에서 정지

따라서 V0.8은 Unity prefab, runtime shader, collider/LOD runtime parity를 구현했다고 주장하지 않는다.

## 남은 범위

V0.8 core와 Blender 5 회귀는 통과했지만 다음은 V0.9 범위로 남는다.

- 다양한 실제 자산을 이용한 장기 resume benchmark
- macOS/Linux 및 여러 Blender 버전 실기동 매트릭스
- process kill 시점별 더 넓은 failure injection
- 다중 job queue와 scheduler
- Unity/Unreal 또는 다른 목적지 adapter의 실제 import/runtime 검증

결론: **V0.8 orchestration core와 V0.7.4 Blender 5.0.1 회귀 검증 완료.**
