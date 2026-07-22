# V0.9 로컬 검증 기록

검증 일자: 2026-07-22

프로젝트: `0.9.0`

Stabilization / Destination Handoff contract: `0.9.0`

이 문서는 실제 실행 결과만 기록한다. 실행하지 않은 운영체제, Blender 버전과 목적 엔진은 계획과 관계없이 `unverified` 또는 `unsupported`로 유지한다. V1.0 승격은 현재 중단되어 있다.

## 현재 검증 결과

| 항목 | 결과 |
|---|---|
| 전체 Python 회귀 | 380/380 통과 |
| Ruff 전체 저장소 | 통과 |
| Python compile check | 통과 |
| doctor | Repository / Workspace / Blender / Codex 모두 OK |
| Blender compatibility | 5.0.1, `BLENDER_EEVEE`, AgX, GLB/FBX/OBJ 성공 |
| V0.8 regression smoke | 통과 |
| V0.7 full portable-asset regression | GLB/FBX/OBJ 3 profile 통과 |
| isolated V0.9 destination handoff gate | 통과 |
| destination handoff audit | `1/1 valid`, 오류·경고 0 |
| stability/export/handoff PDF | 생성과 exact-hash sidecar 검증 통과 |

전체 진입 gate의 첫 실행은 Python/Ruff/doctor, Blender compatibility와 V0.7/V0.8 upstream 회귀를 통과한 뒤 V0.9 smoke fixture의 64px atlas/8px margin 설정에서 중단됐다. 이는 제품 코드 문제가 아니라 기존 V0.7 material conversion이 정상적으로 거부한 잘못된 smoke fixture였다. Fixture를 기존 검증 기준인 1024px/16px로 교정한 뒤 upstream 결과를 재사용해 `-SkipV08 -SkipCompatibility`로 V0.9 고유 handoff/audit/PDF gate를 다시 실행했고 통과했다. 생략 옵션을 사용한 재실행만으로 upstream 지원을 주장하지 않으며, 앞선 동일 실행의 통과 증거와 합쳐 판정한다.

## 지원 매트릭스

| 대상 | 상태 | 근거 |
|---|---|---|
| Windows 11 / AMD64 | verified | V0.9 회귀와 격리 handoff gate 통과 |
| Python 3.14.6 host | verified | 380 tests와 CLI gate 통과 |
| Blender 5.0.1 | verified | EEVEE, AgX, export와 clean-import gate 통과 |
| `portable_gltf` destination handoff | verified | 실제 Blender package·round trip·handoff 통합 gate |
| `fbx_interchange` destination handoff | contract_verified | 실제 V0.7 FBX clean import + host handoff 계약 회귀 |
| Blender 4.x | partially_verified | feature fallback unit test; V0.9 실기동 없음 |
| macOS | unverified | 실행 환경 없음 |
| Linux | unverified | 실행 환경 없음 |
| Unity automatic adapter | unsupported | Codex handoff만 구현; editor/runtime 실행 없음 |
| Unreal automatic adapter | unsupported | Codex handoff만 구현; editor/runtime 실행 없음 |
| custom engine automatic adapter | unsupported | Codex handoff만 구현; destination 검증 없음 |

## 구현된 V0.9 검증 표면

- strict `0.9.0` environment, audit, queue, receipt, lock와 PDF manifest 계약
- privacy-safe environment probe와 bounded read-only workspace audit
- one-writer/one-worker local workflow queue와 explicit failed retry
- exact JSON hash 기반 stability PDF와 sidecar
- GLB/FBX만 허용하는 Destination Handoff plan/generate/validate/status
- passed clean-import round trip과 exact package manifest에 묶인 immutable envelope
- semantic hierarchy, transforms, pivot, material/PBR, LOD와 Collider 조립 계약
- destination import plan/receipt/validation schema와 non-executing safe Codex prompt
- V0.8 optional `destination.handoff` step 및 exact completion marker
- V0.9 audit, export/full PDF와 stability PDF의 handoff 상태 투영
- isolated PowerShell/POSIX gate script

## 최신 실제 실행 증거

```text
V0.9 destination handoff smoke:
reports/v09_smoke/20260722T061636771Z-43492/

Environment probe:
reports/v09/environment/probe-20260722t061636771z-43492/environment_probe.json

Handoff workspace audit:
reports/v09/audits/handoff-audit-20260722t061636771z-43492/workspace_audit.json

Stability PDF:
output/pdf/v09/stability-20260722t061636771z-43492/stability_report.pdf
```

Environment evidence:

- OS: Windows 11, AMD64
- host Python: 3.14.6
- Blender: 5.0.1
- render engine: `BLENDER_EEVEE`
- color look: `AgX - Medium High Contrast`
- compatibility GLB/FBX/OBJ: 성공
- `destination_handoff` feature: enabled

## Destination Handoff 통합 결과

실제 `geometry_showcase`에서 V0.7 `portable_gltf` optimization/material conversion/package/clean import를 수행한 뒤 handoff를 생성했다.

```text
reports/v09_smoke/20260722T061636771Z-43492/workspaces/geometry_showcase/
exports/destination_handoffs/portable_gltf/
v09-handoff-smoke-package/v09-handoff-smoke/
```

| 항목 | 결과 |
|---|---|
| validation | `passed`, `ok: true` |
| checks | 9 passed, warning 0, failed 0 |
| envelope files | 47 |
| missing dependencies | 0 |
| absolute paths | 0 |
| source package current | true |
| canonical unchanged | true |
| source package unchanged | true |
| handoff manifest SHA-256 | `a94d39e4e7732ad737263653c2626ffab890198e1b94b3dc12bd9347145888ab` |
| package manifest SHA-256 | `3d79d529685ac262acd2e8bc4085d1720cdd19b146c265907348b832a20352e5` |
| roundtrip SHA-256 | `9c8f8673e3ffd1ffb3662e82dc85e7d54cd84355c7cc0a96407e209190e5b22a` |

Workspace audit는 130개 파일, 1개 job, handoff `1/1 valid`, warning/failed job 0을 보고했다. 원본 V0.7 package manifest hash는 handoff 생성 전후 동일했다.

Handoff PDF:

- PDF SHA-256: `87276f40fb59a1b1b8feb63e50e60d305b9534cbcd291b29d4a51f5d16acbe22`
- sidecar SHA-256: `ac6cede27dea10bc96986bafeae3a839be1d36f71b04244e9f4a0723a1ab242c`
- 4개 전 페이지를 PNG로 렌더해 표 경계, 줄바꿈, clipping과 overlap을 육안 검사함

Stability PDF:

- PDF SHA-256: `4e21a3cf8a525f5bea81b572a44bf30fe651c9adb60d64f1005c444e496b6cfb`
- source fingerprint: `80bcbdb57069a1bf8b3517a83e3dceed9d58e0c01934879e90cb84a5b76a920a`
- handoff audit source SHA-256: `339b1e275ff181330a7cd04cd6ce1f29eaec74ffb61ee365630193719a43059c`
- 2개 전 페이지를 PNG로 렌더해 한글, status card, handoff `1/1`, source table과 footer를 육안 검사함

시각 검사 렌더는 `reports/v09_smoke/20260722T061636771Z-43492/pdf_visual_check/`에 보존했다. 여섯 페이지 모두 clipping, overlap 또는 깨진 글꼴이 없었다.

PDF는 machine JSON의 파생 산출물이며 상태 판정이나 destination import 결정의 원본이 아니다.

## 기존 회귀 증거

```text
V0.8 regression smoke:
reports/v08_smoke/20260721T153716005Z-43732/

V0.7 full portable-asset smoke:
reports/v07_smoke/20260721T154207874Z-5764/
```

V0.7 clean-import 결과:

| Profile | Status | Warnings | Failed | Bounds max error | Semantic / material coverage |
|---|---|---:|---:|---:|---:|
| `portable_gltf` | passed | 6 | 0 | `0.0 m` | `1.0 / 1.0` |
| `fbx_interchange` | passed | 8 | 0 | `0.000001 m` | `1.0 / 1.0` |
| `obj_legacy` | passed | 10 | 0 | `0.000001 m` | `1.0 / 1.0` |

경고는 기존 V0.7에서 문서화된 format, axis/unit metadata inspector, custom normal/tangent/UV 의미 손실이며 실패로 숨기지 않았다. OBJ package는 V0.7 legacy output으로 유지하지만 Destination Handoff 입력으로는 거부한다.

## 남은 한계와 이후 범위

- 다양한 실제 자산의 장기 resume benchmark
- macOS/Linux와 Blender 4.x 실기동
- process kill 시점별 더 넓은 failure injection
- destination engine에서의 실제 import와 runtime parity
- Unity/Unreal/custom automatic Destination Adapter
- CAD B-Rep, rig, skinning과 animation
- 공개 배포, 설치 프로그램과 코드 서명

결론: **V0.9는 수정된 로컬 완료 기준인 engine-neutral GLB/FBX package, clean-import round trip, complete assembly/material handoff, safe destination Codex prompt, hash-bound manifest, V0.8 workflow 연결, V0.9 audit/PDF/gate 연결과 기존 V0.7~V0.9 회귀를 충족했다.** 이는 목적 엔진 자동 adapter나 runtime parity의 완료를 뜻하지 않는다. V1.0 승격은 사용자의 지시에 따라 중단된 상태이며 자동 Destination Adapter는 목적지가 확정된 뒤 V1.1 이후에 검토한다.
