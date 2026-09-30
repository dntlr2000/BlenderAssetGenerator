# External Static Asset Intake 사용 가이드

`External Static Asset Intake`는 이 저장소가 생성하지 않은 수동 제작 정적 모델을
새로운 CBM job으로 받아들여, 기존 V0.7 engine-neutral package와 선택적 V0.9
Codex Destination Handoff로 연결하는 V0.9 계약입니다.

```text
외부 .blend / .fbx / .glb
→ 읽기 전용 Blender 5 inspection
→ immutable source copy와 exact intake plan
→ 사용자 plan SHA-256 승인
→ static authoring derivative 정규화
→ V0.7 preflight / optimization / portable PBR bake / package
→ clean-import round trip
→ 선택적 V0.9 audit / Destination Handoff
```

이 경로는 레퍼런스 이미지에서 형상을 새로 설계하는 V0.4/V0.6 파이프라인을
우회하는 것이 아니라, 이미 제작된 형상을 별도의 신뢰 가능한 source contract로
등록하는 경로입니다. 존재하지 않는 SceneSpec을 만들어 내지 않습니다.

## 1. 지원 범위

지원 입력:

- Blender 5에서 열 수 있는 `.blend`
- Blender 5 importer가 읽을 수 있는 `.fbx`
- 하나의 파일에 dependency가 결합된 `.glb`
- render-visible `MESH`와 평가 가능한 `CURVE`
- 정적 hierarchy, transform, UV layer와 Blender material node graph
- 한 객체에 여러 material이 있는 경우 material별 single-material semantic submesh 분리
- `.blend`의 unit scale 또는 importer가 정규화한 단위를 meter로 변환

지원하지 않는 입력:

- `.gltf`와 외부 `.bin` sidecar 조합: 먼저 `.glb`로 묶어야 함
- armature, rig, skinning, action, NLA, driver와 animation
- gameplay logic와 engine-specific prefab/actor/material graph
- linked-library geometry
- 누락된 image dependency
- movie 또는 image-sequence texture
- OSL Script node와 명시적인 Blender object pointer에 의존하는 material graph
- CAD B-Rep와 destination runtime parity 검증

숨겨진 render object, camera, light와 정적 전달에 필요하지 않은 source datablock은
normalized authoring derivative에 포함되지 않습니다. 원본 파일 자체는 수정하지
않습니다.

## 2. 신뢰 및 승인 경계

Intake planning은 원본 경로를 Blender 5의 `--disable-autoexec` 상태로 읽습니다.
inspection 전후 원본 SHA-256이 같을 때만 source와 발견된 image dependency를 새 job의
`input/external_asset/` 아래에 복사합니다. 복사본도 같은 SHA-256인지 확인합니다.

계획에는 다음 항목이 고정됩니다.

- source와 dependency 상대 경로 및 SHA-256
- source format과 meter 변환 scale
- source object/material 이름
- stable semantic ID와 material ID
- parent/child 관계와 QA role
- multi-material partition index
- preserved master shader와 portable bake 정책
- blocker, warning과 알려진 손실

계획 생성만으로 정규화를 승인하지 않습니다. 사용자가 보고된 exact plan SHA-256을
승인해야 하고, 승인은 한 번만 소비됩니다. 일반적인 “전부 승인” 지시는 이 전용
hash 승인을 대신하지 않습니다.

## 3. PowerShell 없이 Codex에 요청하기

새로운 lowercase job ID를 사용하고 다음 프롬프트를 Codex에 입력합니다.

```text
<SOURCE_PATH>의 수동 제작 모델을 External Static Asset Intake로 점검해.

- 새 job_id: <JOB_ID>
- static asset만 허용해.
- 원본은 읽기 전용 immutable evidence로 취급해.
- 외부 파일에서 임의 Python, Blender script, driver 또는 OSL을 실행하지 마.
- plan_external_static_asset_intake를 사용해 inspection과 intake plan까지만 생성해.
- source format, 원본/복사본 SHA-256, 단위→meter scale,
  포함/제외 object, semantic ID, material ID, hierarchy,
  multi-material 분리, dependency, blocker와 알려진 손실을 보고해.
- exact plan ID와 plan SHA-256을 보여주고 정규화 전 내 승인을 기다려.
- V0.7 optimization이나 package는 아직 시작하지 마.
```

예시 값:

```text
<SOURCE_PATH> = E:\Assets\manual_temple.blend
<JOB_ID> = manual_temple_intake_01
```

계획을 검토한 뒤 승인할 때:

```text
<JOB_ID> External Static Asset Intake의
plan <PLAN_ID>, SHA-256 <PLAN_SHA256>을 승인한다.

approve_external_static_asset_intake로 exact approval을 기록한 뒤
normalize_external_static_asset → validate_external_static_asset_intake를 실행해.
원본 source, copied input, plan과 dependency는 수정하지 마.

완료 후 다음을 보고해:
- normalized authoring blend
- external asset manifest와 normalization receipt
- semantic/material coverage
- meter 변환 결과
- material master graph 보존 상태
- V0.7 preflight 준비 여부
- 남은 blocker 또는 limitation
```

계획이 `blocked`라면 승인하지 않습니다. 원본 제작 파일에서 문제를 고친 뒤 다른
새 job ID로 다시 intake합니다. 기존 blocked job의 plan이나 hash를 고쳐 쓰지 않습니다.

## 4. 개발자용 CLI

사용자는 이 명령을 직접 실행할 필요가 없으며 Codex/MCP로 동일한 작업을 요청할 수
있습니다. CLI 표면은 다음과 같습니다.

```powershell
uv run cbm external-intake-plan <JOB_ID> <SOURCE_PATH> `
  --plan-id <PLAN_ID>

uv run cbm external-intake-approve <JOB_ID> `
  --plan-id <PLAN_ID> `
  --plan-sha256 <PLAN_SHA256> `
  --approval-note "Reviewed static-only mapping and known losses."

uv run cbm external-intake-normalize <JOB_ID> `
  --plan-id <PLAN_ID> `
  --plan-sha256 <PLAN_SHA256>

uv run cbm external-intake-validate <JOB_ID>
uv run cbm external-intake-status <JOB_ID>
```

MCP allowlist에는 다음과 같은 동일 역할의 도구만 공개됩니다.

```text
plan_external_static_asset_intake
approve_external_static_asset_intake
normalize_external_static_asset
validate_external_static_asset_intake
get_external_static_asset_intake_status
```

임의 Blender/Python 코드를 실행하는 입력 표면은 추가하지 않습니다.

## 5. 산출물 구조

```text
workspaces/<job-id>/
├─ input/external_asset/
│  ├─ source.blend | source.fbx | source.glb
│  └─ dependencies/                    exact-hash image dependency copies
├─ intake/
│  ├─ plans/<plan-id>/
│  │  ├─ inspection.json
│  │  ├─ plan.json
│  │  ├─ approval.json
│  │  └─ contracts/
│  │     ├─ material_plan.json
│  │     └─ m/<material-id>/shader_recipe.json
│  ├─ external_asset_manifest.json
│  ├─ normalization_evidence.json
│  ├─ normalization_receipt.json
│  └─ validation.json
├─ analysis/material_plan.json
├─ materials/<material-id>/shader_recipe.json
└─ blender/scene.blend                  normalized static authoring derivative
```

`external_asset_manifest.json`은 이 경로의 canonical source contract입니다.
`analysis/scene_spec.json`을 만들지 않습니다. `blender/scene.blend`는 원본을 직접
수정한 파일이 아니라 승인된 mapping으로 생성된 immutable authoring derivative입니다.

## 6. 형상과 hierarchy 정규화

정규화는 다음만 수행합니다.

- evaluated static mesh를 고정
- source unit scale을 meter 좌표로 변환
- object scale 적용
- hierarchy와 world transform 보존
- UV layer 보존
- stable semantic ID 및 material ID 기록
- multi-material mesh를 material별 semantic submesh로 분리
- source script, 다른 scene, action과 불필요 datablock 제거
- copied image dependency를 normalized `.blend` 안에 pack

multi-material 분리는 V0.7 portable atlas가 material identity를 명확히 추적하게 하기
위한 derived 정규화입니다. source 파일의 topology나 object 구조는 바꾸지 않습니다.

현재 role 분류는 가장 큰 render object를 `primary`로 두고, 이름에 근거한 context를
`decorative` 또는 `ground_background`으로 보수적으로 분류합니다. 잘못된 의미 분류가
있으면 intake plan을 승인하지 말고 원본 object 이름 또는 향후 명시적 mapping 입력을
정리한 새 job을 사용합니다.

## 7. 셰이더와 텍스처 전달

normalized `.blend`에는 안전 검사를 통과한 Blender master material graph가 보존됩니다.
하지만 Blender node graph가 FBX/GLB나 목적 엔진에 그대로 전달된다고 가정하지
않습니다.

V0.7에서는 다음 절차를 사용합니다.

```text
preserved Blender master graph
→ run-owned portable material conversion
→ portable atlas와 raw PBR channel bake
→ package-relative texture와 mapping manifest
→ FBX/GLB package
→ clean-import material/UV/identity 검사
```

복잡한 procedural, transmission, volume, displacement와 engine-specific 표현은 bake나
교환 형식에서 손실될 수 있습니다. package와 handoff는 그 손실을 명시하지만 Unity,
Unreal 또는 다른 목적지의 실제 shader parity를 주장하지 않습니다.

## 8. V0.7 package로 이어가기

`external-intake-status`의 `ready_for_v07_preflight=true`와 intake validation `passed`를
확인한 뒤 일반 V0.7 review 경계를 사용합니다.

```text
<JOB_ID>의 valid External Static Asset Intake를 V0.7 package 대상으로 검토해.

먼저 intake status/validation과 exact source fingerprint를 재검증해.
<PROFILE_ID> profile로 read-only preflight와 optimization review만 생성해.
LOD, Collider, consolidation, UV, portable material bake, 예산과 알려진 손실을 보고해.
external manifest와 normalized blend hash를 source provenance에 포함해.
review plan ID와 exact SHA-256을 보여주고 내 승인을 기다려.
아직 optimize, material conversion, package 또는 export를 실행하지 마.
```

이후 V0.7 exact optimization-plan SHA-256 승인은 기존 절차와 동일합니다. 승인이
소비된 다음에만 derived optimization, material conversion, package와 clean-import
round trip을 실행합니다. 원본 외부 파일과 normalized authoring `.blend`는 최적화
결과로 덮어쓰지 않습니다.

## 9. V0.9 audit와 Destination Handoff

V0.9 workspace audit는 다음을 읽기 전용으로 확인합니다.

- intake plan/source/dependency/approval/receipt의 exact hash
- normalized `.blend`와 material contract의 current 상태
- source/build fingerprint
- stale, missing, path escape와 tampering
- V0.7 package 및 optional handoff binding

audit는 실패한 intake를 자동 수리하지 않습니다. passed clean-import FBX/GLB package가
있으면 기존 `handoff-plan → exact hash approval → generate → validate → audit` 절차로
Codex Destination Handoff를 만들 수 있습니다. Handoff는 목적지 프로젝트를 직접
수정하지 않고, 목적지 Codex가 먼저 `import_plan.json`을 작성하게 하는 계약입니다.

## 10. 기존 수동 모델을 수정해야 할 때

External Intake job에는 canonical SceneSpec이 없으므로 V0.4 guarded geometry revision을
자동 적용하지 않습니다. 형상, UV, hierarchy 또는 master material을 바꾸려면 원본
제작 파일에서 수정하고 새로운 job ID로 다시 intake합니다.

다음 변경은 기존 intake evidence를 in-place 수정해서 처리하면 안 됩니다.

- source mesh 또는 object hierarchy 변경
- material node graph 변경
- image dependency 교체
- source unit scale 변경
- semantic/material mapping 변경

V0.7 profile만 바꾸는 경우에는 원본 intake를 유지하고 새 preflight/review run을 만들 수
있습니다. package policy 변경과 source authoring 변경을 구분하세요.

## 11. 검증의 의미

Intake `validation=passed`는 source, plan, approval, normalized derivative와 contract가
서로 exact hash로 일치하고 V0.7 입력으로 사용할 수 있다는 뜻입니다. 미적 완성도,
올바른 topology, 목적 엔진 성능 또는 shader parity 점수가 아닙니다.

최종 전달에는 여전히 다음이 필요합니다.

- V0.7 read-only preflight
- 사용자 검토를 거친 exact optimization-plan 승인
- derived optimization과 portable material conversion
- immutable package manifest와 모든 file hash
- primary format clean-import round trip
- 필요할 때만 V0.9 Destination Handoff와 목적지 측 검증
