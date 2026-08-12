# Codex Built-in ImageGen Texture Provider 0.1.0 검증 기록

> 상태: 이 문서는 core `0.1.0`의 2026-08-11~12 실행 이력을 보존하고, 2026-08-13 additive
> Material Loop 경계를 덧붙인다. 과거 수치는 당시 tree의 사실이며 최신 전체 회귀 합계로
> 재분류하지 않는다. profile은 계속 `disabled_experimental`이다.

## 1. 검증 범위와 판정 경계

- 프로젝트 버전은 `0.9.0`, canonical SceneSpec은 `0.2.0`으로 유지한다.
- 새 provider/profile은 `autonomous_static_prop_v2_codex_imagegen`이며 상태는
  `disabled_experimental`이다. 기존 `autonomous_static_prop_v2`의 별도 opt-in overlay일 뿐
  기본 경로나 세 번째 모델링 파이프라인이 아니다.
- repository 코드는 ImageGen을 직접 호출하지 않는다. ControllerExecutor가 immutable assignment와
  허용된 staging 경로를 게시하고, 현재 Codex desktop task가 built-in ImageGen을 호출한 뒤 결과를
  그 경계 안으로 전달한다.
- 이 기능 경로에는 OpenAI API, OpenAI SDK, API key, HTTP client/provider, endpoint literal이 없다.
  provider는 `credential_scope=none`, `billing_scope=codex_usage`이고 profile도
  `network_required=false`, `api_key_required=false`, `autonomous_daemon=false`,
  `continuation_after_app_exit=false`, `repository_can_spawn_codex_task=false`를 보고한다.
- 생성 픽셀은 staging 후보일 뿐이다. canonical MaterialAuthoring V0.5, destination project,
  portable package 또는 승인 상태를 직접 쓰지 않는다.
- core `adopt`의 public 실행 경계는 MaterialAuthoring `0.2.1` staging receipt 뒤 overlay
  `status=adopted`, `next_action=controller_promotion_required`다. 이 core history를 completed 또는
  canonical promotion으로 재분류하지 않는다.
- 별도 additive Material Loop는 exact staging chain에서 controller/host promotion, actual
  `MaterialPhaseReceiptV2`와 IQ 경계까지 연결한다. 이 경로의 실행 결과는
  `VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md`가 권위 원본이다.
- 관련 설계와 실행 절차는 [아키텍처](ARCHITECTURE_CODEX_IMAGEGEN_PROVIDER_KO.md),
  [시작 안내](GETTING_STARTED_CODEX_IMAGEGEN_PROVIDER_KO.md),
  [마이그레이션](MIGRATION_CODEX_IMAGEGEN_PROVIDER_KO.md),
  [테스트 계획](TEST_PLAN_CODEX_IMAGEGEN_PROVIDER_KO.md)을 기준으로 한다.

## 2. 구현 전 기준선

아래 수치는 이 기능을 넣기 전의 회귀 기준선이며 최종 구현 결과와 합치거나 덮어쓰지 않는다.

| 명령 | 구현 전 결과 |
|---|---|
| `uv sync --frozen --extra dev --extra vision` | passed |
| `uv run pytest` | `1351 passed, 39 skipped, 8 warnings in 191.55s` |
| `uv run ruff check .` | `All checks passed!` |
| `uv run cbm doctor` | passed |
| `uv run cbm blender-compat` | Blender `5.0.1`, Python `3.11.13`, EEVEE, GLB/FBX/OBJ smoke passed |
| `python scripts/check_agent_instructions.py` | root `7764` bytes, files `11`, invariants `192` |

## 3. 2026-08-12 core `0.1.0` 재실행 이력

| 검증 | 당시 결과 |
|---|---|
| 전체 Ruff/pytest 회귀 | `ruff check .`: passed; `pytest -ra -p no:cacheprovider --basetemp C:\Users\Woosik\AppData\Local\Temp\cbf12z`: `1438 passed, 44 skipped, 8 warnings in 221.75s` |
| ImageGen host focused/schema/security/negative 회귀 | 8개 전용 파일: `86 passed, 5 skipped in 38.78s`; schema parity 포함 |
| AQ v2 host/Blender 관련 gate | host `485 passed, 22 skipped, 8 warnings in 92.82s`; Blender `34 passed, 6 warnings in 507.21s`; benchmark 0.1 `8/8`와 Blender 3건, benchmark 0.2 `10/10`과 Blender 2건 |
| Blender 5.0.1 fake 4-family smoke | `wood`, `signage_decal`, `emissive`, `crystal`: `4 passed in 12.89s` |

별도로 확인된 환경 진단은 다음과 같다.

- `uv run cbm doctor`: passed.
- `uv run cbm blender-compat`: Blender `5.0.1`, Python `3.11.13`, EEVEE와
  GLB/FBX/OBJ smoke passed.
- instruction checker: root `7764` bytes, files `12`, invariants `192`, passed.
- V0.7/V0.8/V0.9 chained gate: 모두 passed. evidence roots는 각각
  `reports/v07_smoke/20260811T174519354Z-7176`,
  `reports/v08_smoke/174855132-7176`,
  `reports/v09_smoke/20260811T175034879Z-7176`이다.
- 최종 명령 로그와 benchmark JSON은
  `reports/codex_imagegen_final_20260812`에 보존했다.
- `tests/test_v08_artifact_lifecycle.py`를 짧은 pytest basetemp로 실행한 결과:
  `13 passed in 36.23s`.
- 의도적으로 매우 긴 pytest basetemp를 쓴 진단 실행은 Windows `MAX_PATH` 영향을 노출했다.
  따라서 그 실행의 실패 수를 제품 회귀 결과로 재분류하지 않았고, 위 최종 전체 회귀는 짧은
  basetemp로 별도 재실행한다. 이 기록은 임의의 초장문 경로 지원을 주장하지 않는다.

## 4. 구현 표면

구현된 public surface는 다음과 같다.

- CLI 5종: `codex-imagegen-status`, `codex-imagegen-plan`, `codex-imagegen-run`,
  `codex-imagegen-select`, `codex-imagegen-adopt`.
- MCP 5종: `get_codex_imagegen_status`, `plan_codex_imagegen`, `run_codex_imagegen`,
  `select_codex_imagegen`, `adopt_codex_imagegen`.
- strict JSON Schema 16종: provider profile, plan/budget/assignment/completion/candidate,
  generated-image evidence, quality/selection/terminal/adoption, AQ overlay,
  MaterialAuthoring `0.2.1` request/manifest/receipt, exact-signage-text evidence.
- MaterialAuthoring `0.2.1` companion: generated direct channel과 source-bound local
  deterministic derivation을 구분하고 모든 산출물을 staging-only로 유지한다.
- ControllerExecutor bridge: immutable input snapshot, exact output allowlist, hash/size 검증,
  append-only result와 crash/resume/replay 경계를 사용한다.
- generated pixel의 direct role은 `base_color`, `decal_rgb`, `emission`, `opacity_source`만
  허용한다. `normal`, `roughness`, `metallic`, `height`, `displacement`, `occlusion`,
  tangent-space data는 직접 채택하지 않고 local deterministic derivation 또는 constant로 만든다.
- immutable 기본 budget은 전체 generation 4, 후보 3, refinement 1, assignment당 generation 3이며
  실행 중 자동 확대하지 않는다.

2026-08-13 additive Material Loop는 기존 core CLI/MCP 5개를 유지한 채 별도 CLI 9개/MCP 9개를
추가한다. native adoption/normalization, non-human semantic/ranking, bridge plan/status/run, isolated
Blender exact-adoption preflight, host promotion/resume와 AQ/IQ continue 표면이다. preflight는
ControllerResult/canonical/destination write를 만들지 않으며 어느 표면도 API 호출, semantic
observation 작성, approval 작성, canonical 직접 write나 destination write를 제공하지 않는다.
native-derived core selection은 별도 `CodexImageNativeCorePreparationReceipt`가 adoption/original,
normalization과 기존 core completion/candidate/quality/selection을 exact byte identity로 결속하지만
core `0.1.0` schema나 과거 evidence를 수정하지 않는다.

profile을 계획하려면 ImageGen overlay opt-in과 `disabled_experimental` 허용을 둘 다 명시해야 한다.
단순 status 조회나 기존 AQ v2/legacy artifact 로딩은 이를 활성화하지 않는다.

## 5. 현재 task의 built-in ImageGen 실제 증거

machine-readable 수동 검증 기록은 다음 두 파일이다.

- [생성·선택 검증 기록](reports/codex_imagegen_manual_20260811/manual_codex_assisted_validation.json)
- [MaterialAuthoring staging 검증 기록](reports/codex_imagegen_manual_20260811/manual_codex_assisted_material_validation.json)

두 기록의 범위는 `isolated_material_boundary_fixture_not_full_production_session`이다. 전체 production
session이나 package acceptance 증거로 확대 해석하지 않는다.

### 5.1 첫 64×64 할당: 불일치 이력 보존

- job: `codex-imagegen-actual-20260811`
- session: `aqv2-20260811t144145597263z-4a00f8f2`
- immutable assignment: `64×64`, `quality_level=low`, candidate 1개.
- 현재 task의 첫 built-in ImageGen 출력:
  `C:\Users\Woosik\.codex\generated_images\019f5f6c-86f9-7432-bd81-c38e61a8c566\exec-dc9ce010-0f6d-439e-91a3-993126578c16.png`
- 실제 출력: `1254×1254`, `2,199,075` bytes,
  SHA-256 `3645ad7598662cbd1648b3291074234a77bd240e3261790378cda424699cb8a3`.
- 이 파일은 호스트 측 원본으로 보존되지만 크기 불일치 때문에 assignment/completion provenance
  graph에는 편입되지 않았다.
- 결과 크기가 assignment와 일치하지 않았으므로 이를 completion/candidate/adoption으로 꾸미지 않았다.
  ControllerExecutor result는 `waiting_for_output`, `outputs=[]`, 누락 output 2개로 남아 있다.

이 기록은 실패 또는 불일치 history를 고쳐 쓰지 않는다는 정책의 실제 사례다.

### 5.2 두 번째 1254×1254 할당: 선택까지 완료

- job: `codex-imagegen-actual2-20260811`
- session: `aqv2-20260811t144337688199z-457ecbb1`
- assignment SHA-256:
  `147c75b488eb2b417b9f59a04e0ee863c3af0b4a06027bd206c3a5cf25f74e58`.
- assignment: `1254×1254`, `quality_level=medium`, base-color surface swatch 1개,
  canonical/destination write authority 모두 `false`.
- 현재 task가 호출한 built-in ImageGen 원본:
  `C:\Users\Woosik\.codex\generated_images\019f5f6c-86f9-7432-bd81-c38e61a8c566\exec-e9661e84-0393-4c1c-b50d-c30eaf99adc7.png`.
- 원본은 보존되어 있으며 `1254×1254`, `2,484,395` bytes,
  SHA-256 `82ce3d6efc85cef6aa3e166f007f0509c97dc698b378ffd7e7262eb1cc33372f`다.
- 선택된 staging path:
  `production/autonomy_v2/aqv2-20260811t144337688199z-457ecbb1/codex_imagegen/assignments/material-00/staging/candidate-00.png`.
- deterministic quality outcome은 `passed`, score는 `0.7426595353495635`, selection은
  `selected`, `human_reviewed=false`다.
- PNG 크기, spatial detail, border contamination proxy, opposite-edge seam proxy는 통과했다.
  alpha는 없는 base-color라 advisory다. unwanted object/text, style, background 검사는 로컬에서
  `unscorable`이며 `semantic_checks_authoritative=false`다.

수동 기록은 `current_codex_task_invoked_builtin_imagegen=true`,
`repository_invoked_imagegen=false`, `openai_api_sdk_key_used=false`를 명시한다. 반면 repository의
candidate/material contract는 호스트 호출을 독립적으로 증명할 수 없으므로
`actual_codex_imagegen_execution_verified=false`를 유지한다. 이 둘은 서로 다른 증거 경계이며
후자의 값을 임의로 `true`로 올리지 않는다.

### 5.3 실제 source의 로컬 PBR staging

선택된 SHA와 정확히 binding된 MaterialAuthoring `0.2.1` 실행 결과는 다음과 같다.

- run: `actual-codex-image-material-run`.
- 당시 구현 snapshot의 수동 기록에 남은 public orchestration result: `completed`; manifest status:
  `candidate_ready`.
- 1024×1024 channel 7개: `base_color`, `height`, `metallic`, `normal`, `occlusion`,
  `opacity`, `roughness`.
- `base_color`만 generated direct channel이다. `height`, `normal`, `occlusion`, `roughness`는
  동일 source SHA에 묶인 local deterministic derivation이고, `metallic`, `opacity`는 local
  constant다.
- manifest는 `staging_only=true`, `canonical_v05_unchanged=true`,
  `canonical_write_performed=false`, `destination_write_performed=false`,
  `blender_compilation_status=not_run`, `human_reviewed=false`를 기록한다.
- receipt:
  `material_authoring/codex_imagegen/runs/actual-codex-image-material-run/receipt.json`,
  SHA-256 `d0e11a62ee9c1f8f433c1af2bfee896ae57e159c2838a0c3b8004910ddb996e8`.
- generation terminal:
  `production/autonomy_v2/aqv2-20260811t144337688199z-457ecbb1/codex_imagegen/terminal.json`,
  SHA-256 `adf07bfb21fbbbc480248aee6404a914abc38072d2f9fb97d1901c057672d5cd`.

위 `completed` 값은 hardening 전 구현 snapshot에서 생성된 immutable 수동 이력이다. 기록을
삭제하거나 현재 값으로 고쳐 쓰지 않는다. 최종 코드는 같은 staging receipt 뒤
`status=adopted`, `next_action=controller_promotion_required`를 반환하고 base AQ를 자동 재개하지
않는다. 따라서 이 과거 JSON과 generation terminal을 현재 overlay 완료, canonical material
promotion, IQ 또는 package 완료 증거로 재분류하지 않는다.

## 6. Fake backend, quality 및 음성 검증

아래 항목은 deterministic fake/host test 범위다. 최종 합산 판정은 3절의 focused 재실행
결과를 따른다.

- fake controller는 실제 ImageGen 또는 네트워크를 호출하지 않고 동일 schema와 staging 경계를
  재현한다.
- partial output, extra output, duplicate completion, 잘못된 hash, 생성 후 size/hash 변경,
  escaped/nonportable path가 fail-closed인지 검사한다.
- crash/resume/replay가 이미 기록된 request/result 및 nested evidence를 다시 검증하고 history를
  덮어쓰지 않는지 검사한다.
- quality는 exact PNG dimensions, spatial detail, alpha extractability, border/seam proxy,
  output-role 제한을 검사한다. opacity source는 RGBA alpha가 있어야 hard gate를 통과하고 RGB만
  있으면 실패한다.
- semantic advisory는 검증할 수 없을 때 `passed`로 가장하지 않고 `unscorable`로 남긴다.
- schema/registry 테스트는 새 `0.1.0` 및 MaterialAuthoring `0.2.1` 조합만 허용하고 unknown 조합,
  legacy exact-set 오염 및 자동 migration을 거부한다.
- security 테스트는 `codex_imagegen` package의 `openai`, `requests`, `httpx`, `aiohttp`, `socket`,
  `urllib` import와 `http://`/`https://` endpoint literal을 거부한다. dependency manifest에도
  OpenAI SDK를 추가하지 않았다.

## 7. Exact signage text의 public binding

exact signage text는 ImageGen prompt의 글자를 신뢰하지 않고 project-local deterministic
rasterization으로만 합성한다.

- assignment에 `exact_text_sha256`가 없는데 exact-text artifact를 제공하면 거부한다.
- assignment에 hash가 있는데 artifact가 없으면 거부한다.
- artifact는 kind `exact-signage-text-evidence`, media type `application/json`, strict
  `ExactSignageTextEvidenceV021`이어야 한다.
- evidence의 `text_sha256`는 assignment의 `exact_text_sha256`와 정확히 일치해야 한다.
- CLI의 prepare-only `--exact-text-evidence`와 MCP의 `exact_text_evidence_path`도 같은 public
  validator를 경유한다. 잘못된 text evidence는 material request를 만들기 전에 실패한다.

이 검증은 글자 내용에 대한 사용자 승인, typography 품질 또는 destination runtime 렌더 parity를
대신하지 않는다.

## 8. Blender 검증과 남은 한계

기존의 정확한 fake wood node smoke는 Blender `5.0.1`에서 `1 passed in 4.12s`였다. 이는
고정 allowlist probe가 fake completion으로 만든 wood material graph를 compile/reopen하고 normalized
inventory를 확인한 기록이다. 이후 동일 테스트는 `wood`, `signage_decal`, `emissive`, `crystal`
4-family parametrization으로 확대되었고 네 family의 fixed fake Blender 실행은 통과했다. 당시 exact
결과는 3절에 기록한 `4 passed in 12.89s`다. Material Loop 후속 Blender 수치와 혼합하지 않는다.

fake Blender 통과는 다음을 증명하지 않는다.

- 위 5.2의 실제 generated source를 Blender에서 compile/render했다는 주장.
- generated pixels의 의미론적 정확성, 사람의 시각 검토 또는 일반적인 품질 향상.
- GLB/FBX 등 format별 immutable package manifest, clean-import, material-loss acceptance.
- Unity/Unreal을 포함한 destination runtime parity 또는 destination-ready 상태.

위 5절 historical actual-source manifest의 Blender 상태는 계속 `not_run`, package acceptance는
`not_run`, `human_reviewed=false`, destination runtime parity는 `unverified`다. 이 immutable
receipt를 새 companion compile 결과로 소급 수정하지 않는다.

## 9. 2026-08-13 Material Loop 후속 경계

additive companion은 actual `MaterialPhaseReceiptV2`와 ImageGen/adoption/MaterialAuthoring chain을
exact controller input으로 결속하는 배선을 구현했다. deterministic fake `wood`,
`signage_decal`, `emissive`, `crystal` fixture는 실제 Blender 5.0.1 host promotion과 IQ mechanism을
실행한다. fake 결과는 actual ImageGen이나 일반 품질 증거가 아니다.

5.2의 historical actual PNG는 새 unique native-adoption/normalization run에서 재사용했다. 이는
fresh ImageGen invocation이 아니다. current-task observation은 `human_reviewed=false`이며 repeat/tile
판단이 해소되지 않아 `review_required`에서 canonical promotion 전에 멈췄다. 따라서 5.3의 과거
staging bytes를 actual-source MaterialPhaseReceipt, IQ pass 또는 package로 재분류하지 않는다.

delivery 검증도 approval 경계를 보존한다. fake family는 V0.7 review 뒤
`waiting_for_v07_approval`에서 멈추며 별도 raw GLB/FBX clean-import는 test-only mechanism evidence다.
실제 사용자가 승인한 production package, completed delivery terminal 또는 destination parity를
주장하지 않는다. exact 최신 명령·수치·evidence root와 최종 repository gate placeholder는
[Material Loop 검증 기록](VERIFICATION_IMAGEGEN_MATERIAL_LOOP_KO.md)을 따른다.

이 제한과 사람 검토 부재 때문에 profile은 계속 `disabled_experimental`이다.
