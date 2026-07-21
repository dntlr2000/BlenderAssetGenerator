# 선택적 실내 범위와 승인 가이드

## 목적

BlenderAssetGenerator `0.7.2`의 실내 기능은 건물 모델링의 기본 단계가 아닙니다. Codex는 사용자가 외관, 건물 또는 3D 모델을 요청했다는 이유만으로 방, 복도, 계단, 천장, 가구나 보이지 않는 층을 임의로 만들면 안 됩니다.

실내 authoring은 다음 두 조건을 모두 만족할 때만 허용됩니다.

1. 사용자가 실내 구현을 명시적으로 요청하고 그 정확한 경계를 `InteriorScope 0.1.0`에 기록합니다.
2. 사용자가 현재 scope 파일의 SHA-256을 확인한 뒤 정확히 그 hash에 대한 승인을 남깁니다.

Geometry SceneSpec은 계속 `0.2.0`입니다. 실내 안전 경계는 기존 SceneSpec을 확장하거나 기존 workspace를 마이그레이션하는 대신 별도 계약으로 관리됩니다.

## 기본 상태

다음 파일이 없으면 정상적인 기본 상태입니다.

```text
workspaces/<job>/architecture/interior_scope.json
```

이 상태는 `default_disabled`이며 다음 의미를 갖습니다.

- exterior-only job은 추가 파일 없이 기존 방식으로 동작합니다.
- Codex는 실내 구조를 제안하거나 생성하지 않습니다.
- SceneSpec에 명시적인 interior ID나 tag가 들어오면 로드와 빌드 전에 거부됩니다.
- 창 뒤의 간단한 backing, door reveal, window recess와 외벽 두께 같은 facade helper는 실내로 명명하거나 tag하지 않는 한 허용됩니다.

`interior-scope-status`는 읽기 전용이므로 기본 상태를 확인해도 `architecture/` 폴더나 계약 파일을 만들지 않습니다.

```powershell
uv run cbm interior-scope-status <job-id>
```

## 계약 파일

실내 기능을 요청한 job은 다음 파일을 사용합니다.

```text
workspaces/<job>/
├─ architecture/
│  ├─ interior_scope.json
│  └─ interior_scope.approval.json
├─ analysis/
│  └─ scene_spec.json
├─ history/
│  └─ architecture/
└─ reports/
   └─ interior_scope_validation.json
```

- `interior_scope.json`: 사용자가 요청한 정책, semantic prefix, level, space, furnishing과 근거 경계입니다.
- `interior_scope.approval.json`: 현재 scope bytes의 SHA-256에 결합된 사용자 승인입니다.
- `scene_spec.json`: 실제 정적 실내 형상을 포함할 수 있는 기존 geometry 설계 원본입니다.
- `history/architecture/`: 명시적으로 scope를 교체할 때 이전 계약과 승인을 보존합니다.
- `interior_scope_validation.json`: 기계가 읽는 검증 결과입니다.

scope와 approval이 존재하면 해당 hash는 build provenance에도 포함됩니다. 따라서 승인 경계를 바꾼 뒤 이전 `.blend`를 최신 빌드로 오인할 수 없습니다.

## 정책

| 정책 | 용도 | 필수 evidence status |
|---|---|---|
| `disabled` | 명시적으로 실내를 사용하지 않음 | `not_applicable` |
| `visible_only` | 레퍼런스에서 직접 보이는 실내만 생성 | `observed` |
| `proxy` | 사용자가 허용한 범위의 추정·저밀도 실내 | `inferred` 또는 `authored` |
| `measured` | 도면·치수 근거가 있는 실내 | `measured` |
| `authored` | 사용자가 설계해 달라고 요청한 새 실내 | `authored` |

furnishing은 `none`, `proxy`, `detailed` 중 하나입니다. `none`이면 가구 tag가 있는 interior object는 거부됩니다. `measured` scope는 SceneSpec도 `mode: measured`여야 합니다.

`visible_only`는 가려진 방을 추정해 채우는 정책이 아닙니다. 해당 실내 객체의 모든 evidence가 `observed`여야 합니다. `proxy`와 `authored`도 승인된 prefix·level·space 밖의 구조를 추가할 권한은 주지 않습니다.

## 1. 범위 초안 만들기

사용자가 실내를 명시적으로 요청한 후에만 scope를 만듭니다. 예를 들어 레퍼런스에서 보이는 1층 로비 구조만 구현하고 가구는 제외하려면 다음처럼 실행합니다.

```powershell
uv run cbm interior-scope-init building_job `
  --policy visible_only `
  --request "레퍼런스에서 직접 보이는 1층 로비 구조만 구현" `
  --allow-prefix building.interior.lobby `
  --exclude-prefix building.interior.lobby.staff_only `
  --level floor_1 `
  --space lobby `
  --furnishing none
```

중요한 점:

- 이 명령은 scope 초안만 만들며 SceneSpec이나 `.blend`를 변경하지 않습니다.
- 초안 상태는 `draft`이고 실내 제작 권한이 없습니다.
- enabled policy는 사용자의 정확한 요청과 최소 한 개의 `--allow-prefix`가 필요합니다.
- 같은 scope 파일을 암묵적으로 덮어쓰지 않습니다. `--overwrite`는 사용자가 교체 범위를 검토한 경우에만 사용합니다.

정책에 따른 기본 evidence status는 CLI와 MCP가 선택하지만 필요하면 `--evidence-status`로 명시할 수 있습니다.

## 2. 정확한 hash 검토와 승인

현재 scope와 SHA-256을 확인합니다.

```powershell
uv run cbm interior-scope-status building_job
```

사용자가 내용과 `scope_sha256`을 확인한 경우에만 사용자가 직접 터미널에서 다음을 실행합니다.

```powershell
uv run cbm interior-scope-approve building_job `
  --scope-sha256 <current-scope-sha256> `
  --approval-note "1층 로비의 관찰 가능한 구조만 승인"
```

명령은 `APPROVE <current-scope-sha256>` 전체 문구를 대화형으로 다시 입력해야 완료됩니다. 승인 작업은 MCP allowlist에 포함되지 않으므로 Codex가 scope를 만들고 스스로 승인할 수 없습니다.

다음은 승인이 아닙니다.

- “건물 모델을 만들어줘” 같은 일반 요청
- scope 초안 생성
- 과거 scope에 대한 승인
- 다른 job의 승인
- hash가 생략되거나 일치하지 않는 승인
- QA 후보나 portable package에 대한 별도 승인

approval은 현재 scope hash와 전체 승인 snapshot이 같은 동안에만 유효합니다. scope를 교체하거나 수정하면 기존 approval은 `stale`이 되며 새 hash를 다시 승인해야 합니다.

## 3. SceneSpec에 실내 객체 작성

승인 뒤에도 각 interior object는 승인된 semantic boundary 안에 있어야 합니다.

```json
{
  "id": "building.interior.lobby.floor",
  "name": "Lobby Floor",
  "tags": [
    "interior",
    "interior_floor",
    "level:floor_1",
    "space:lobby"
  ]
}
```

실내 분류에 사용하는 명시적 표지는 다음과 같습니다.

- semantic ID의 점 구분 segment가 `interior`, `room`, `rooms`, `corridor`, `hallway`, `lobby`, `foyer`, `stairwell`, `basement`, `cellar`, `attic`인 경우
- `interior`, `room`, `corridor`, `interior_wall`, `interior_floor`, `interior_ceiling`, `interior_stair`, `interior_furniture` tag
- `interior:`로 시작하는 tag

ID segment와 tag 비교는 대소문자를 정규화하므로 `Interior`, `Room`처럼 표기해도 우회되지 않습니다.

scope가 level 또는 space 목록을 제한하면 각 객체에 `level:<id>` 또는 `space:<id>` locator가 필요합니다. 객체 ID는 `allowed_semantic_prefixes` 안에 있고 `excluded_semantic_prefixes` 밖에 있어야 합니다.

Codex가 interior marker를 빼서 검증을 우회하면 안 됩니다. 반대로 exterior wall, facade backing이나 window recess를 실제 room으로 오분류해서도 안 됩니다. 의미 ID와 tag는 형상의 실제 역할을 정직하게 나타내야 합니다.

## 4. 검증과 빌드

canonical SceneSpec을 명시적으로 검사합니다.

```powershell
uv run cbm interior-scope-validate building_job
uv run cbm build building_job
uv run cbm render building_job
uv run cbm inspect building_job
uv run cbm validate building_job
```

검증 명령은 다음 보고서를 씁니다.

```text
workspaces/building_job/reports/interior_scope_validation.json
```

다음 상태는 fail-closed입니다.

- scope가 없거나 `disabled`인데 interior object가 존재함
- enabled scope에 정확히 일치하는 user approval이 없음
- scope와 SceneSpec의 job ID가 다름
- object ID가 허용 prefix 밖이거나 제외 prefix 안에 있음
- 승인되지 않은 level 또는 space를 사용함
- 필요한 level/space locator가 없음
- furnishing이 `none`인데 interior furniture가 존재함
- furnishing이 `proxy`인데 `furnishing:detailed` 등 상세 가구 tag가 존재함
- `visible_only` 객체에 observed가 아닌 evidence가 있음
- `measured` scope인데 SceneSpec이 measured mode가 아님
- `measured` scope에 관찰 evidence 또는 승인 prefix를 대상으로 한 enabled constraint가 없음

enabled scope에 아직 interior object가 하나도 없으면 오류가 아니라 경고입니다. 이는 scope 승인과 실제 authoring을 분리하기 위한 정상적인 중간 상태입니다.

## MCP 대응

CLI와 같은 기능을 다음 whitelisted MCP 도구로 제공합니다.

| CLI | MCP |
|---|---|
| `interior-scope-init` | `initialize_interior_scope` |
| `interior-scope-approve` | 없음 — 사용자 수동 대화형 CLI 전용 |
| `interior-scope-status` | `get_interior_scope_status` |
| `interior-scope-validate` | `validate_interior_scope` |

MCP의 initialize는 승인이나 geometry 변경을 수행하지 않으며 approval 도구 자체를 노출하지 않습니다. Codex는 scope와 hash를 보고하고 사용자의 수동 CLI 승인을 기다려야 합니다.

## Scope 교체와 작업 되돌아가기

범위를 바꿔야 한다면 사용자가 변경 내용을 검토한 뒤 `interior-scope-init --overwrite`로 새 초안을 만듭니다. 이전 scope와 approval은 `history/architecture/`에 보존되고 현재 approval은 hash mismatch로 무효화됩니다.

그다음 순서는 다음과 같습니다.

```text
새 scope 작성
→ 새 scope hash 사용자 승인
→ SceneSpec의 실내 객체를 새 범위에 맞게 수정
→ interior validation
→ build / inspect / validate
→ 필요하면 material / QA / portable package 재실행
```

scope가 변경되면 build provenance도 바뀝니다. 과거 `.blend`, QA run, optimization과 package는 과거 근거로 남지만 현재 설계를 대표하는 산출물로 재사용하면 안 됩니다.

## 지원 범위와 비목표

현재 InteriorScope는 existing SceneSpec geometry recipe를 이용한 정적 건축 실내 경계입니다. 다음 기능은 포함하지 않습니다.

- interactive door나 창문 동작
- navigation mesh, AI path와 gameplay volume
- Unity prefab, Unreal actor나 목적 엔진별 room system
- light probe, lightmap bake와 reflection capture 배치
- runtime shader, streaming, occlusion portal과 level loading
- 사용자가 요청하지 않은 후면 방, 지하층, 상층과 가구 자동 생성
- 한 장의 외관 이미지에서 내부 구조를 복원된 사실로 주장하는 기능

목적 엔진이 정해지지 않은 상태에서는 정적 geometry와 portable material 의미만 유지합니다. 엔진별 동작과 전달 규칙은 목적지가 선택되고 실제 import/runtime 검증이 가능한 후속 adapter 단계에서 다룹니다.

## 짧은 요청을 해석하는 규칙

```text
"이 건물 이미지를 3D로 만들어줘"
→ exterior-only, InteriorScope 생성 없음

"창문 안쪽이 비어 보이지 않게 해줘"
→ facade helper로 해결 가능한지 먼저 판단, room 자동 생성 금지

"사진에 보이는 1층 로비도 만들어줘"
→ visible_only scope 초안 제안, hash 승인 대기

"도면 기준으로 1층과 2층 실내를 만들어줘"
→ measured scope 초안과 constraint 계획 제안, hash 승인 대기

"보이지 않는 방도 자연스럽게 설계해줘"
→ authored 또는 proxy scope로 경계·가구 수준을 구체화한 뒤 hash 승인 대기
```

핵심 원칙은 단순합니다. **실내 요청이 없으면 실내를 만들지 않고, 실내 요청이 있어도 사용자가 정확한 범위 hash를 승인하기 전에는 만들지 않습니다.**
