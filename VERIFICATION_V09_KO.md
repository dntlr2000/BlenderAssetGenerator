# V0.9 로컬 검증 기록

> 이 문서의 `reports/v07_smoke/`, `reports/v08_smoke/`, `reports/v09_smoke/` 경로는 당시
> 로컬 실행 위치이며 배포 저장소의 영구 의존성이 아니다. 최신 compact snapshot은
> `verification/evidence/v07_20260811/`, `verification/evidence/v08_20260811/`,
> `verification/evidence/v09_20260811/`에 있다.

검증 일자: 2026-07-26

프로젝트: `0.9.0`

Stabilization / Destination Handoff contract: `0.9.0`

이 문서는 실제 실행 결과만 기록한다. 실행하지 않은 운영체제, Blender 버전과 목적 엔진은 계획과 관계없이 `unverified` 또는 `unsupported`로 유지한다. V1.0 승격은 현재 중단되어 있다.

## 2026-08-09 `desktop_in_session` Production Controller 검증

Asset Production Dispatcher의 기존 `client_mediated` 기본 경로를 유지하면서, 현재
Codex Desktop 작업이 controller 역할을 맡는 명시적 `desktop_in_session` 실행 모드를
추가했다. 이 모드는 외부 task API나 binding을 요구하지 않지만
`approval_isolation=workflow_contract_only`로 기록되며 per-task MCP/shell enforcement를
주장하지 않는다.

검증 결과:

| 검사 | 결과 |
|---|---|
| production/public-surface targeted pytest | 36 passed |
| Schema parity와 CLI/MCP surface subset | 9 passed |
| 전체 Python 회귀 | 939 passed, 6 skipped |
| Ruff | passed |
| PowerShell V0.9 gate script 구문 | passed |
| Git Bash V0.9 gate script 구문 | passed |
| `git diff --check` | passed |

격리 temporary workspace 테스트는 다음을 확인했다.

- `desktop_in_session` dispatch가 `ready_in_session`에서 시작하고 external task binding 없이
  `resume_host → delegate_read_only → controller_author` 경계로 진행한다.
- 상태·launch·prompt가 `workflow_contract_only`, tool-profile 미강제와 별도 task 미생성을
  일관되게 보고한다.
- desktop dispatch에 external binding을 시도하면 fail-closed로 거부한다.
- 알 수 없는 controller mode는 reference 복사나 job 생성 전에 거부한다.
- 기존 `client_mediated` dispatch는 exact client task/profile binding이 없으면 production
  write와 host advance를 계속 거부한다.
- 두 모드 모두 기존 V0.8 assignment input fingerprint, completion marker, single-writer
  lock, generic/specialized approval과 V0.9 postflight 계약을 공유한다.

이번 변경은 controller launch/진입 계약만 바꾸므로 Blender 실기동 package gate는 다시
실행하지 않았다. V0.9 PowerShell·shell gate에는 두 모드를 함께 검사하는 isolated
non-Blender production smoke를 추가했으며, 실제 Blender 형상·재질·package 검증은 기존
V0.7/V0.8 gate와 전체 회귀 범위를 그대로 유지한다.

## 현재 검증 결과

| 항목 | 결과 |
|---|---|
| 전체 Python 회귀 | 389/389 통과 |
| Ruff 전체 저장소 | 통과 |
| Python compile check | 통과 |
| doctor | Repository / Workspace / Blender / Codex 모두 OK |
| Blender compatibility | 5.0.1, `BLENDER_EEVEE`, AgX, GLB/FBX/OBJ 성공 |
| V0.8 regression smoke | 통과 |
| V0.7 full portable-asset regression | GLB/FBX/OBJ 3 profile 통과 |
| isolated V0.9 destination handoff gate | 통과 |
| destination handoff audit | `1/1 valid`, 오류·경고 0 |
| stability/export/handoff PDF | 생성과 exact-hash sidecar 검증 통과 |
| optional interior multi-view QA | Blender 5.0.1 실기동, 4 view × 7 pass, PDF와 V0.9 audit 통과 |

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

## 선택적 실내 다각도 QA 검증

승인된 `InteriorScope 0.1.0`과 정적 실내 semantic object를 가진 격리 fixture `interior_qa_smoke_01`에서 실제 Blender 5.0.1을 실행했다. 이 fixture는 사용자 workspace와 `first_reference_test`를 사용하지 않았다.

```text
isolated workspace:
tmp/interior_qa_smoke_workspaces/

job:
interior_qa_smoke_01

run:
blender5-smoke-001
```

| 항목 | 결과 |
|---|---|
| Blender / renderer | `5.0.1` / `BLENDER_EEVEE` |
| scope/build/geometry validation | 통과 |
| camera profile | `minimal`, 4방향 |
| exact plan SHA-256 | `bfd62b924c6442996ae6187bae7fe1b7c88f33e151a7569994bed1b8e6d76821` |
| approval | exact hash, single-use, `consumed` |
| render passes | 4 views × 정확히 7 kinds = 28 |
| semantic visibility | `1.0`, 대상 6 ID, unseen 0 |
| reference comparison | `unavailable`; 구조·가시성 evidence만 보고 |
| revision candidates | 0, 지원 후보는 항상 manual-only |
| contact sheets | beauty, object ID, wireframe 생성·육안 검사 |
| V0.9 workspace audit | 47 files, 1 job, warning/failed 0, `passed` |
| QA PDF | 3 pages, warning 0, 모든 페이지 PNG 시각 검사 |
| QA PDF SHA-256 | `ece77690f77bc68ec8e95fe7eef65a19d92866d8e1b6fdc17649ca03a3a46f3f` |

PDF 표지, 공간별 coverage, 세 종류 contact sheet와 source appendix에서 한글, 표 경계, clipping과 overlap을 확인했다. PDF 텍스트에는 실내 다각도 QA 절이 존재하고 외관 QA 누락 안내가 섞이지 않음을 검사했다.

Python 회귀는 신규 계약, scope fail-closed, exact approval/single-use, 7-pass 실행, PDF, canonical hash 불변, V0.8 specialized gate와 MCP allowlist를 포함해 `389/389` 통과했다.

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

## 2026-07-30 bounded convergence audit 추가 검증

V0.9 read-only workspace audit가 optional V0.6 convergence의 active current-state
evidence와 terminal historical evidence를 구분하도록 확장했습니다.

추가 회귀는 다음을 포함합니다.

- active session의 request, render manifest, 정확히 7개 pass, reference, mask,
  beauty, report와 candidates hash 검증
- terminal plan/approval, contiguous receipt와 support artifact chain 검증
- 신규 terminal의 final SceneSpec snapshot과 모든 QA provenance 필수화
- 진짜 legacy plan의 `legacy_unverifiable` warning 보존
- new-to-legacy evidence downgrade, pass tamper, 거짓 target reason과
  manual-review flag 불일치 거부
- 완료 뒤 추가 view는 verified historical addition으로 허용하되, 원래 input이나
  immutable session artifact 변경은 실패 처리

격리 V0.6 smoke workspace의 실제 terminal session을 V0.9 audit로 검사한 결과:

```text
reports/v09/audits/convergence-exact-20260730t141041z/workspace_audit.json
```

| 항목 | 결과 |
|---|---|
| scanned jobs | 1 |
| convergence sessions | 1 |
| valid convergence sessions | 1 |
| warning / failed jobs | 0 / 0 |
| audit status | `passed` |
| audit JSON SHA-256 | `340d868b77a38f5f4d528df1fd40d1df566af73ad44a00e9a01781c2c2229d34` |

감사는 세션을 resume, repair, cancel하거나 새 승인을 만들지 않았고 사용자
workspace 대신
`reports/v06_convergence_smoke/20260730T141041062Z/workspaces/`의 격리 fixture만
읽었습니다.

## 2026-07-30 최종 V0.9 isolated Blender 5.0.1 회귀

convergence hardening과 portable glTF UV0 검증 보강을 모두 포함한 최종 게이트:

```text
reports/v09_smoke/20260730T151958075Z-28320/
```

| 검증 | 결과 |
|---|---|
| 전체 Python | 602/602 통과 (`76.15s`) |
| Ruff | 전체 저장소 통과 |
| Schema 재생성·parity 집중 검사 | 5/5 통과 |
| package manifest SHA-256 | `26e1c29574a8fa46457c32c0ab072c9f08adcf13c8d2c0ebe2f02347dcbd346d` |
| export evidence SHA-256 | `90cb2e1fbc792df2c93060c010ef7cf3d7d1497b717a3df2e20811aad59540c1` |
| clean-import roundtrip | `passed`, `ok=true`, semantic/material coverage `1.0 / 1.0` |
| roundtrip JSON SHA-256 | `a70593dadad565ae429bdd957f6cb241d4852edd37372b657427fae516f835f3` |
| handoff validation | `ok=true`, `status=warning` |
| handoff validation SHA-256 | `6e7be1ff4e7324ffe2e459dff8f0adee775beb5706a55736bc500b6dcb6e7b68` |
| handoff audit | `passed`, SHA-256 `238ebde059b435d83f4e867ce10373bb6314ba4fda0a51e2b62bf1a8b3c3c848` |
| queue/workspace audit | `passed`, SHA-256 `4dce3124ab7c2aec79c00d1bad69101470451f33d864473f4f18b0a422a3bd12` |
| environment probe SHA-256 | `662f0be32102b7b615f5a97c6a486653ab99d712d987f870e375750e53b631cf` |
| stability PDF SHA-256 | `b03ba7509055ee2eedd823f7b9f7c3eb4827fb002f2275bf388896fcc95d78b8` |
| stability PDF manifest SHA-256 | `72eea3119318181fa97ea889d677c647a17bfec756e305473c482c755946605b` |

converted GLB의 portable atlas는 UV channel 0으로 승격되었고,
`verification_basis=gltf_material_textureinfo_texcoord0` 기준으로 16개
TextureInfo binding과 33개 textured primitive의 `TEXCOORD_0`을 검증했습니다.
normal texture가 있는 primitive는 tangent 존재도 확인했습니다. 잘못된
TextureInfo type, nonzero transform texCoord, 누락된 converted-material texture,
CLI/manifest/contract format 불일치는 fail-closed 실행형 음성 테스트로 검증했습니다.

`status=warning`은 실패를 성공으로 바꾼 것이 아닙니다. clean-import는 file-level
texture binding, imported UV0 bounds/area와 tangent readiness를 검증하지만,
topology-independent loop-to-vertex UV association의 완전 동일성이나 목적 엔진의
runtime parity는 증명하지 않습니다. 이 제한은 roundtrip JSON, DestinationContext,
known limitations와 handoff PDF에 보존됩니다.

## 2026-08-06 External Static Asset Intake 검증

수동 제작 static model을 SceneSpec 없이 V0.7/V0.9에 연결하는 별도 intake route를
검증했습니다. 사용자 job은 gate 성공용으로 변경하지 않았고, Python `tmp_path`와
`reports/v07_smoke`, `reports/v09_smoke`의 격리 evidence만 사용했습니다.

| 검증 | 결과 |
|---|---|
| 전체 Python 회귀 | `880 passed, 5 skipped` (`121.23s`) |
| Ruff | 전체 저장소 통과 |
| Schema 생성·parity | 전체 pytest에 포함되어 통과 |
| 실제 Blender 5 external `.blend` intake | `1 passed` (`9.70s`) |
| source unit 정규화 | `scale_length=0.01` → meters, 기대 bounds 통과 |
| multi-material 분리 | material별 stable single-material semantic submesh 확인 |
| sanitization | text/action/armature `0`, one scene, autoexec disabled |
| External → V0.7 GLB | optimize/material conversion/package 완료 |
| External GLB clean import | `ok=true`, semantic/material coverage `1.0 / 1.0` |
| V0.7 회귀 증거 | GLB/FBX/OBJ 세 profile 모두 `passed`, `ok=true` |
| 긴 Windows handoff path | receipt/validation/audit 회귀 통과 |
| V0.9 handoff audit | `passed`, handoff `1/1 valid` |

최신 V0.7 회귀 evidence:

```text
reports/v07_smoke/20260806T073746751Z-251968/
```

최종 V0.9 isolated gate:

```text
reports/v09_smoke/20260806T084335038Z-148936/
reports/v09/audits/handoff-audit-20260806t084335038z-148936/workspace_audit.json
```

Audit 결과는 `scanned_file_count=131`, failed/warning job `0/0`, handoff
`1/1 valid`, 전체 status `passed`다. 함께 생성한 V0.9 파생 보고서는 다음과 같다.

```text
output/pdf/v09/stability-20260806t084335038z-148936/stability_report.pdf
output/pdf/v09/stability-20260806t084335038z-148936/stability_report.manifest.json
```

Stability PDF SHA-256은
`4a33438c33177fb8eb570038db0c62671ccb76b84fc31b438b4321e18a4ef2a6`이고
source fingerprint는
`d4401c731e033242e646adeb55edc8922b0ac788dade43109ea33c4421cc236b`다.

실기동 증거는 external `.blend` source와 portable GLB 전체 경로를 대상으로 한다.
External `.fbx`/`.glb` importer는 계약·호환 경로와 기존 Blender export/import
regression으로 검증했지만, 다양한 실제 제3자 파일 corpus 검증은 남아 있다.
Blender master graph는 normalized authoring derivative에 보존되며, 목적지 전달은
V0.7 derived raw PBR bake를 사용한다. Unity/Unreal/custom engine shader 또는 runtime
parity는 여전히 검증하거나 주장하지 않는다.

## 2026-08-09 Asset Production Dispatcher / Delegated Controller 검증

새 레퍼런스의 제작 목적과 전달 범위를 V0.8 workflow에 결속하고, 별도 Codex 작업에서
읽기 전용 보조 agent를 조율할 수 있는 V0.9 production 계층을 격리 workspace에서
검증했다. 저장소는 작업 생성에 필요한 prompt와 launch manifest만 준비하며 실제 Codex
작업 생성은 supporting client가 수행하는 `client_mediated` 방식이다.

| 검증 | 결과 |
|---|---|
| 전체 Python 회귀 | `925 passed, 6 skipped` (`204.27s`) |
| Ruff | 전체 저장소 통과 |
| production Schema 생성·parity | 통과 |
| CLI/MCP public surface와 allowlist | 통과 |
| 초기 dispatcher 상태 | `prepared` / `bind_client_task` |
| controller tool-profile 결속 | exact profile SHA-256 및 client enforcement 확인 |
| delegated assignment | `read_only_advisory`, canonical write allowlist 비어 있음 |
| V0.8 smoke | standard와 background workflow 회귀 통과 |
| V0.9 production smoke audit | `passed`, 1 job / 30 files |
| V0.7 GLB/FBX/OBJ package | 세 profile 모두 `complete` |
| V0.7 clean-import round trip | 세 profile 모두 `passed`, error 0 |

최신 격리 evidence:

```text
V0.8:
reports/v08_smoke/155931927-168844/

V0.9 dispatcher/controller and stabilization:
reports/v09_smoke/20260808T163313473Z-317296/
reports/v09/audits/production-audit-20260808t163313473z-317296/workspace_audit.json

V0.7 GLB/FBX/OBJ roundtrip:
reports/v07_smoke/20260808T164003045Z-251456/
```

V0.7 roundtrip의 format별 결과:

| Profile | Status | Warning | Failed |
|---|---|---:|---:|
| `portable_gltf` | `passed` | 6 | 0 |
| `fbx_interchange` | `passed` | 7 | 0 |
| `obj_legacy` | `passed` | 11 | 0 |

경고는 axis/unit metadata의 독립 검증 한계, custom split-normal/tangent/UV의
format별 검증 한계, FBX/OBJ material semantics 손실처럼 기존 V0.7에서 문서화한
범위다. raw PBR sidecar와 machine-readable package evidence가 계속 권위 원본이며,
경고를 목적 엔진 runtime parity로 오해해서는 안 된다.

Production bundle은 immutable dispatch/launch/controller 계약, client task binding,
hash-chained advance receipt, exact workflow-state snapshot, completion/approval/attempt
authority inventory와 postflight audit receipt를 보존한다. 정상 downstream derived
supersession과 외부 변조를 구분하고, path traversal·symlink·junction·dangling leaf 및
중첩 linked artifact는 fail-closed로 거부한다. 장시간 workflow lock은 TTL만으로 살아
있는 소유자를 탈취하지 않는다.

기존 V0.8 generic/specialized approval, InteriorScope, guarded revision, V0.7 exact
optimization-plan 승인과 Destination Handoff exact-hash 승인은 변경하거나 대체하지
않는다. Controller는 승인·retry 도구가 제외된 exact tool profile에 결속되어야 하며,
지원 client가 이 제한을 실제로 강제하지 않는 unrestricted shell/task 환경까지 저장소
단독으로 격리한다고 주장하지 않는다.

## 2026-08-09 bounded convergence와 production bridge 재검증

authored `spatial_v1` bounded convergence의 five-view 구조 veto와, explicit
`standard + bounded_after_v06` Asset Production Dispatch 연결을 추가한 뒤 전체 회귀와
격리 게이트를 다시 실행했다.

| 검증 | 결과 |
|---|---|
| 핵심 convergence/orchestration/production 회귀 | `281 passed` |
| 전체 Python 회귀 | `933 passed, 6 skipped` (`197.27s`) |
| Ruff | 전체 저장소 통과 |
| Schema 재생성·parity | 통과, production Schema 11개 |
| `git diff --check` | 오류 0, Windows line-ending 경고만 존재 |
| V0.8 isolated gate | 통과, Blender `5.0.1`, `BLENDER_EEVEE` |
| V0.9 isolated gate | 통과, production audit·GLB handoff·stability PDF 생성 |
| V0.7 GLB/FBX/OBJ gate | 세 profile package와 clean-import round trip 통과 |

최신 격리 evidence:

```text
V0.8 orchestration:
reports/v08_smoke/182516109-434504/

V0.9 dispatcher/controller, handoff and stabilization:
reports/v09_smoke/20260808T183031573Z-463724/

V0.7 three-format roundtrip:
reports/v07_smoke/20260808T183601045Z-347012/
```

V0.7 roundtrip 결과:

| Profile | Status | Warning | Failed | 최대 bounds 오차 |
|---|---|---:|---:|---:|
| `portable_gltf` | `passed` | 6 | 0 | `0.0 m` |
| `fbx_interchange` | `passed` | 7 | 0 | 약 `0.000001 m` |
| `obj_legacy` | `passed` | 11 | 0 | 약 `0.000001 m` |

신규 convergence 통합 테스트는 다음을 확인했다.

- bounded dispatch가 `standard + preview_only` V0.8 plan을 생성한다.
- completed preview 뒤 exact convergence plan과 immutable binding을 한 번만 만든다.
- Controller는 plan SHA-256을 스스로 승인하지 않고 `visual_convergence_plan`에서 멈춘다.
- 외부 exact 승인이 생긴 뒤 Controller 호출 한 번당 iteration은 최대 한 번이다.
- terminal convergence만 V0.9 postflight에 결속하며 V0.7 package는 새 workflow로 남는다.
- authored `spatial_v1`의 result five-view가 baseline보다 회귀하면 해당 iteration을
  rollback하고 `structural_regression`으로 종료한다.

다만 production convergence의 Controller 테스트는 격리된 deterministic fixture와
mocked convergence host 결과를 사용했다. V0.8/V0.9/V0.7 게이트는 실제 Blender 5.0.1
build/render/export/import를 통과했지만, 별도 client-mediated Codex task가 새로운 실제
레퍼런스를 authoring하고 exact approval 뒤 여러 convergence iteration을 끝까지 수행하는
실사용 E2E는 아직 별도 자산 검증 항목이다. 따라서 이번 결과는 controller 계약과
회귀 안정성의 검증이며 특정 자산의 목표 유사도 달성을 보장하지 않는다.
