# V0.9 로컬 검증 기록

검증 일자: 2026-07-21  
프로젝트: `0.9.0`  
Stabilization contract: `0.9.0`

이 문서는 실제 실행 결과만 기록한다. 실행하지 않은 운영체제, Blender 버전과 목적 엔진은 계획과 관계없이 `unverified` 또는 `unsupported`로 유지한다.

## 현재 검증 결과

| 항목 | 결과 |
|---|---|
| V0.9 targeted Python tests | 16/16 통과 |
| 전체 Python 회귀 | 374/374 통과 |
| Ruff 전체 저장소 | 통과 |
| doctor | Repository / Workspace / Blender / Codex 모두 OK |
| Blender compatibility | 5.0.1, `BLENDER_EEVEE`, AgX, GLB/FBX/OBJ 성공 |
| V0.8 regression smoke | 통과 |
| V0.7 full portable-asset regression | GLB/FBX/OBJ 3 profile 통과 |
| isolated queue/audit/PDF gate | 통과 |
| stability PDF visual inspection | 2페이지 render 및 육안 검사 통과 |

## 지원 매트릭스

| 대상 | 상태 | 근거 |
|---|---|---|
| Windows 11 / AMD64 | verified | V0.9 전체 회귀와 격리 gate 통과 |
| Python 3.14.6 host | verified | 374 tests와 CLI gate 통과 |
| Blender 5.0.1 | verified | EEVEE, AgX, export와 clean-import gate 통과 |
| Blender 4.x | partially_verified | feature fallback unit test; V0.9 실기동 없음 |
| macOS | unverified | 실행 환경 없음 |
| Linux | unverified | 실행 환경 없음 |
| Unity adapter | unsupported | engine-neutral package boundary만 구현 |
| Unreal adapter | unsupported | engine-neutral package boundary만 구현 |

## 구현된 V0.9 검증 표면

- strict `0.9.0` environment, audit, queue, receipt, lock, PDF manifest 계약
- privacy-safe environment probe
- bounded read-only workspace audit
- one-writer/one-worker local workflow queue
- explicit failed retry와 immutable dispatch receipt
- exact JSON hash 기반 stability PDF와 sidecar
- isolated PowerShell/POSIX gate script

## 실제 실행 증거

```text
V0.9 smoke:
reports/v09_smoke/20260721T153720485Z-43732/

V0.8 regression smoke:
reports/v08_smoke/20260721T153716005Z-43732/

V0.7 full portable-asset smoke:
reports/v07_smoke/20260721T154207874Z-5764/
```

V0.9 environment evidence:

- probe ID: `probe-20260721t153720485z-43732`
- OS: Windows 11, AMD64
- host Python: 3.14.6
- Blender: 5.0.1
- render engine: `BLENDER_EEVEE`
- color look: `AgX - Medium High Contrast`
- compatibility GLB/FBX/OBJ: 성공

Queue/audit smoke는 기존 V0.8 workflow를 한 번만 dispatch한 뒤 `waiting_for_agent`에서 정상 정지했다. `max_concurrency=1`, attempt receipt 1개, absolute workspace path 0건, audit `passed`를 확인했다.

V0.7 full regression의 clean-import 결과:

| Profile | Status | Warnings | Failed | Bounds max error | Semantic / material coverage |
|---|---|---:|---:|---:|---:|
| `portable_gltf` | passed | 6 | 0 | `0.0 m` | `1.0 / 1.0` |
| `fbx_interchange` | passed | 8 | 0 | `0.000001 m` | `1.0 / 1.0` |
| `obj_legacy` | passed | 10 | 0 | `0.000001 m` | `1.0 / 1.0` |

경고는 기존 V0.7에서 문서화된 format, axis/unit metadata inspector, custom normal/tangent/UV 의미 손실이며 실패로 숨기지 않았다.

## `first_reference_test` read-only audit

- audit ID: `audit-first-reference-v09-final`
- scanned files: 1,276
- immutable sources: 1/1 verified
- status: `passed`
- migration status: `compatible_legacy`
- 원본 project metadata: `0.4.0`
- canonical 또는 derived job 파일 변경: 없음

이는 legacy metadata를 그대로 보존하면서 현재 계약으로 읽을 수 있다는 뜻이다. V0.9가 job을 0.9 형식으로 migration했다는 뜻이 아니다.

## PDF 검증

최종 실제-job 보고서:

- PDF: `output/pdf/v09/stability-first-reference-v09-final/stability_report.pdf`
- sidecar: `output/pdf/v09/stability-first-reference-v09-final/stability_report.manifest.json`
- PDF SHA-256: `5f6955bb8bf507a8ac6f3deacdd2a7d672fc0d8dffd786df529bc81be7859cbb`
- source fingerprint: `17c879ffc1ef8a9169c8f7bcd070e3a7769fa6afa67aaa0de8e9c3a7eac0856c`
- embedded font: `malgun.ttf`
- rendered pages: 2

Poppler PNG render에서 한글, status card, 표, finding, source appendix, footer를 확인했다. clipping, overlap, literal markup과 absolute source path는 없었다.

## 남은 검증 및 한계

- 다양한 실제 자산의 장기 resume benchmark
- macOS/Linux와 여러 Blender 버전 실기동
- process kill 시점별 더 넓은 failure injection
- 목적 엔진 adapter와 runtime parity
- CAD B-Rep 입력과 solver

결론: **V0.9 stabilization core는 Windows 11, Python 3.14.6, Blender 5.0.1에서 로컬 release-candidate gate를 통과했다.** macOS/Linux, Blender 4.x 실기동, 목적 엔진 adapter와 실제 자산 장기 benchmark는 검증되지 않았으므로 V1.0 완료로 표시하지 않는다.
