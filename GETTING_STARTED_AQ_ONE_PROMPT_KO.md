# AQ One-Prompt 시작 안내

## 1. 현재 상태

AQ Approval Envelope `0.3.0`과 One-Prompt Supervisor `0.1.0`은 기존 AQ v2 위의 additive
experimental companion이다. 프로젝트는 `0.9.0`이며 두 v2 profile은 계속
`disabled_experimental`이다. 이 경로는 새 정적 hard-surface/static prop, concept,
`primary_object_only`, current-task controller와 engine-neutral review/GLB/FBX 범위만 대상으로 한다.

## 2. mode 선택

- `autonomous`: 최초 허용 범위의 routine gate를 host policy가 처리한다. 목표는 추가 사용자 결정 0회다.
- `checkpointed`: geometry/material/delivery checkpoint를 합쳐 최대 3회다.
- `interactive`: 기존 AQ v2형 approval 경계를 유지한다.

technical repair, closure, path/hash rebinding, deterministic normalization, controller system retry와
rollback은 어느 mode에서도 사용자 approval이 아니다.

## 3. 최초 요청에 포함할 내용

한 번의 요청에서 다음을 명확히 고정한다.

- primary reference와 target subject
- `primary_object_only` scope
- 실행 budget
- 허용 provider (`local_only` 또는 명시적 Codex built-in ImageGen)
- 요청 delivery (`review_only`, `portable_gltf`, `portable_fbx`)
- routine approval 없이 진행하고 품질 미달 시 review bundle로 끝내도 된다는 delegation
- destination project를 수정하지 않는다는 경계

예시:

```text
첨부한 이미지의 휴대용 비상 라디오만 새 정적 소품으로 만들어줘.
scope는 primary_object_only, target은 portable emergency radio로 고정해.
AQ v2 autonomous experimental mode를 사용하고, 최초 범위와 기본 예산 안에서는 중간 routine
approval 없이 geometry, material, IQ와 요청한 portable_gltf까지 진행해. 품질 기준을 통과하지
못하면 current best와 finding을 review bundle로 종료해. provider는 local_only이며 새 reference,
target, budget, delivery 또는 destination write가 필요할 때만 결정을 하나로 모아 물어봐.
목적지 프로젝트는 수정하지 말고, 앱이 닫히면 상태만 보존한 뒤 같은 session에서 재개해.
```

이 문구는 미래 candidate를 미리 승인하는 것이 아니다. exact action마다 host가 eligibility를
재계산하고 single-use policy authorization을 발행한다.

## 4. 개발자용 계획과 상태

```powershell
uv run cbm autonomy-v2-one-prompt-plan `
  --reference <REFERENCE_PATH> `
  --target-subject "portable emergency radio" `
  --approval-mode autonomous `
  --deliveries portable_gltf `
  --provider-scopes local_only `
  --delegate-routine-actions `
  --enable-v2 `
  "<EXACT_REQUEST>"

uv run cbm autonomy-v2-one-prompt-status <JOB_ID> <SESSION_ID>
uv run cbm autonomy-v2-one-prompt-run <JOB_ID> <SESSION_ID> --enable-v2
uv run cbm autonomy-v2-one-prompt-resume <JOB_ID> <SESSION_ID> --enable-v2
uv run cbm autonomy-v2-one-prompt-cancel <JOB_ID> <SESSION_ID> --reason "<REASON>" --enable-v2
```

실제 공개 signature는 구현·검증 기록을 권위로 한다. status는 read-only이고 run/resume은 hard action
budget을 넘지 않는다.

## 5. controller 대기

`waiting_for_controller`이면 supervisor가 request-owned assignment와 exact allowed outputs를 게시한
상태다. 현재 Codex task가 그 output을 만들고 host가 request/input/profile/source를 다시 검증한 뒤
같은 session을 resume한다. repository가 새 task를 spawn하지 않는다.

Codex 앱이 닫히면 실행도 중단된다. state, budget, evidence와 assignment는 보존되지만 background
continuation은 없다. 다시 열었을 때 같은 request/workspace/source가 current인 경우에만 resume한다.

## 6. 사용자에게 다시 묻는 경우

다음 실제 결정만 `AQV2ConsolidatedEscalationRequest` 하나로 제시한다.

- scope/reference/target/budget/delivery/provider 확장
- destination project write
- reference로 해결할 수 없는 중요한 디자인 ambiguity
- exact text, rights/license 결정

결정하지 않으면 current best review bundle로 종료할 수 있다. technical error를 approval 문구로
표현하지 않는다.

## 7. terminal 읽기

- `production_delivery`: IQ passed, 요청 format package와 clean import가 exact evidence로 완료
- `review_bundle`: quality 미달, plateau, budget, unscorable 또는 non-critical issue의 review 종료
- `genuine_escalation`: 최초 authority 밖 사용자 결정 하나가 필요
- `blocked`: 반복 불가능한 framework failure와 report 존재

review bundle은 production package가 아니다. policy authorization은 user approval이 아니다.

## 8. telemetry

```powershell
uv run cbm aq-approval-telemetry <JOB_ID> <SESSION_ID>
uv run cbm aq-escalation-status <JOB_ID> <SESSION_ID>
```

autonomous 성공 telemetry는 initial request 1, additional decision 0, technical approval 0,
canonical corruption 0과 production/review terminal을 보여야 한다. 설명 문구가 아니라 JSON counter를
판정 원본으로 사용한다.

## 9. legacy session

Approval Envelope가 없는 기존 AQ v2 session은 새 mode로 변환되지 않는다. 기존 user approval과
정지 경계를 그대로 사용한다. Crystalgun historical Identity Split에도 새 policy authority를 소급
적용하지 않는다.
