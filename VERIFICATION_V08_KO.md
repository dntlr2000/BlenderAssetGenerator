# V0.8 로컬 검증 기록

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
| Python 회귀 | 411/411 통과 |
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

빠른 실행 정책은 프록시·상세·재질·QA의 일반 검토 gate를 계획에서
생략하지만, agent-authored 계약의 completion marker와 V0.7 optimization
plan의 exact-hash 전용 승인은 유지한다. 직접 레퍼런스 QA는 한 번만
수행하고 생성형 QA target과 자동 revision은 사용하지 않는다. QA에서
큰 누락, 카메라 위험 또는 실측 위험이 발견되면
`requires_standard_workflow`로 중단하며 완료로 처리하지 않는다.

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
