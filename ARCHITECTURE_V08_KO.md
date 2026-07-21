# V0.8 Short-Prompt Automation & Job Orchestration 아키텍처

## 목표

V0.8은 V0.4~V0.7 기능을 새로 대체하지 않는다. 사용자의 짧은 요청을 보수적으로 분류하고, 필요한 기존 단계들을 순서화하며, 중단·재개·승인·실패를 파일 기반 상태로 관리한다.

```text
짧은 요청
→ 의도 라우팅
→ 목적지 해석
→ 불변 WorkflowPlan
→ 결정론적 host 단계 실행
→ agent 판단 또는 사용자 승인에서 정지
→ 현재 파일 hash로 상태 재구성
→ 재개
```

Geometry SceneSpec은 `0.2.0`, 재질은 `0.5.0`, QA는 `0.6.0`, portable asset은 `0.7.0`을 유지한다. V0.8은 별도 `0.8.0` workflow 계약만 추가한다.

## 의도 라우팅

지원 의도는 다음 일곱 가지다.

| intent | 의미 | 안전한 기본 종료점 |
|---|---|---|
| `new_asset` | 새 레퍼런스로 새 자산 생성 | 프록시 승인 |
| `revise_asset` | 기존 자산의 제한 수정 | 재빌드·검증 |
| `add_measured_view` | 정면/측면/평면/청사진 추가 | 재분석 |
| `interior_scope` | 명시적으로 요청한 실내 범위 | 별도 InteriorScope 승인 |
| `material_authoring` | V0.5 재질·셰이더 작성 | swatch 승인 |
| `visual_qa` | V0.6 직접 비교와 수정 후보 | QA 검토 |
| `portable_package` | V0.7 최적화·포터블 패키지 | 최종 패키지 승인 |

새 레퍼런스는 항상 새 `job_id`를 사용한다. 기존 job에 다른 primary reference를 넣는 것은 거부한다. 기존 job 요청이 두 의도에 동시에 해당하거나 어떤 의도인지 불분명하면 추측하지 않고 명시적 `--intent`를 요구한다.

## 목적지 해석

의도와 목적지는 별도로 해석한다. 현재 검증된 adapter는 V0.7의 engine-neutral static-asset package뿐이다.

- `engine_neutral`: 사용 가능
- `unity`, `unreal`, `custom`: 아직 미지원
- 미지원 목적지가 명시되면 V0.7 portable package까지만 생성하고 adapter 부재를 기록
- engine prefab/actor, runtime shader, 물리·LOD runtime 비용은 구현됐다고 주장하지 않음

## 저장 구조

```text
workspaces/<job>/workflows/
├─ latest.json
├─ locks/
├─ stale_locks/
└─ <workflow-id>/
   ├─ request.json
   ├─ route.json
   ├─ plan.json
   ├─ state.json
   ├─ inputs/
   ├─ completions/
   ├─ approvals/
   └─ attempts/<step-id>/<attempt-id>.json
```

`request.json`, `route.json`, `plan.json`은 불변이다. `state.json`은 권위 있는 설계 원본이 아니라 현재 파일·hash·영수증을 다시 읽어 만든 projection이다.

## 단계 실행 모델

각 단계는 다음 실행 방식 중 하나를 가진다.

- `host`: 스키마 검증, 분석, Blender 명령, 패키징처럼 결정론적으로 호출 가능한 단계
- `agent`: 모델링 계획, SceneSpec, 재질 계획처럼 시각 판단과 저작이 필요한 단계
- `approval`: 프록시, 상세 메시, swatch, QA, 최종 패키지에 대한 일반 사용자 검토
- `specialized_approval`: InteriorScope, V0.6 revision, V0.7 optimization의 기존 exact-hash 승인
- `manual`: 검증된 목적지 adapter가 없는 종료 경계

일반 workflow 승인은 specialized approval을 대체할 수 없다.

사람이 결과를 확인하는 프록시, 상세 메시, 재질, QA, portable package gate 앞에는 기존 canonical JSON과 렌더를 투영한 PDF와 sidecar manifest를 생성한다. PDF는 읽기용이며 상태 판정과 승인은 계속 JSON/hash를 기준으로 한다.

## 신선도와 완료 판정

단계 완료는 파일 존재만으로 판정하지 않는다.

1. 입력 dependency의 완료 fingerprint를 계산한다.
2. 요구 산출물의 존재, 스키마, SHA-256을 검사한다.
3. agent completion marker가 현재 plan/input/output과 정확히 일치하는지 확인한다.
4. approval이 현재 artifact fingerprint와 정확히 일치하는지 확인한다.
5. 하나라도 바뀌면 해당 완료를 `stale`로 바꾸고 후속 단계를 다시 실행하지 않는다.

`integrity`, `currentness`, `verification`은 서로 다른 필드로 기록하여 “파일이 읽힌다”와 “현재 입력에서 만들어졌다”를 혼동하지 않는다.

## 재개, 실패, 잠금

- host 실행마다 고유 attempt receipt를 먼저 `running`으로 기록한다.
- 성공과 실패 모두 같은 receipt에 종료 시각과 결과를 기록한다.
- 실패 단계는 자동 재시도하지 않는다.
- 원인을 해결한 뒤 `--retry-failed`를 명시해야 현재 실패 단계 하나만 새 attempt로 재시도한다.
- 이전 프로세스가 남긴 `running` receipt는 `InterruptedAttempt`로 종료한 뒤 새 attempt를 시작한다.
- job별 live lock은 동시 writer를 거부한다.
- TTL이 지난 유효 lock만 이력으로 보존하고 복구한다.
- 취소는 산출물을 삭제하지 않으며 취소된 workflow는 재개할 수 없다.

## 승인 경계

일반 승인 gate:

- `proxy_geometry`
- `detailed_geometry`
- `material_swatches`
- `qa_review`
- `final_package`

기본 workflow PDF 위치:

```text
workspaces/<job>/reports/pdf/proxy_report.pdf
workspaces/<job>/reports/pdf/detail_report.pdf
workspaces/<job>/reports/pdf/material_report.pdf
workspaces/<job>/reports/pdf/qa_report.pdf
workspaces/<job>/reports/pdf/portable_report.pdf
```

전용 승인 gate:

- `interior_scope`: 현재 scope SHA-256과 수동 interactive 승인
- `visual_revision`: 선택 candidate와 단일 사용 approval
- `optimization`: 표시된 LOD/collider/consolidation plan SHA-256 승인

V0.8은 승인을 생성하거나 추론하지 않는다.

## 안전 경계

- short request만으로 실내를 생성하지 않음
- short request만으로 V0.6 수정 후보를 적용하지 않음
- short request만으로 LOD/collider 기본값을 최적화에 적용하지 않음
- 외부 이미지 생성 provider budget 기본값은 0
- canonical SceneSpec, geometry, 재질 및 입력은 각 기존 단계의 규칙대로만 변경
- `first_reference_test` 같은 기존 사용자 작업은 V0.8 gate에서 사용하지 않음

## V0.9로 넘기는 범위

V0.8은 orchestration core를 제공하지만 다음은 V0.9 안정화 범위다.

- 다중 작업 queue와 장기 scheduler
- Windows/macOS/Linux 및 Blender 지원 매트릭스 확대
- Unity/Unreal adapter 실기동 검증
- 다양한 실제 자산 benchmark와 성공률 통계
- upgrade/migration 자동화와 release candidate 검증
