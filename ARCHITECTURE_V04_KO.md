# v0.4 아키텍처 — Reference & Measured Core

## 버전 선택

v0.4는 v0.3에 해당하는 레퍼런스 진단/카메라 scaffold와 v0.4에 해당하는 실측 제약 잔차 평가를 한 프로젝트에 포함합니다. Geometry SceneSpec은 `0.2.0`으로 유지하므로 승인된 v0.2 메시 설계를 그대로 가져올 수 있습니다.

## 저장소 계층

```text
codex-blender-modeler-v04/
├─ AGENTS.md                         # 짧은 요청을 전체 절차로 확장하는 저장소 규칙
├─ .agents/skills/                   # Codex 작업별 절차
│  ├─ quick-reference-model/
│  ├─ reference-analysis/
│  ├─ reference-to-scene/
│  ├─ measured-constraints/
│  ├─ blender-build/
│  ├─ visual-qa/
│  └─ texture-authoring/
├─ .codex/config.toml                # 프로젝트 범위 MCP 설정과 허용 도구
├─ prompts/                          # 구조화 출력 및 대화형 작업 프롬프트
├─ schemas/                          # SceneSpec/분석/카메라/제약 JSON 계약
├─ src/codex_blender_modeler/
│  ├─ analysis/                      # 이미지 진단과 카메라 scaffold
│  ├─ constraints/                   # 실측 제약 모델과 잔차 평가
│  ├─ blender_scripts/
│  │  ├─ compat.py                   # Blender 4/5 feature probe
│  │  ├─ builders/                   # 실제 geometry recipe 구현
│  │  ├─ build_scene.py
│  │  ├─ render_preview.py
│  │  ├─ inspect_scene.py
│  │  ├─ validate_scene.py
│  │  ├─ export_scene.py
│  │  └─ probe_compat.py
│  ├─ blender_runner.py              # background 실행, stdin 격리, 예외 전파
│  ├─ workspace.py                   # 원자적 job 생성과 입력 버전 관리
│  ├─ revision.py                    # ID/경로 기반 guarded revision
│  ├─ cli.py
│  └─ mcp_server.py
├─ examples/
│  ├─ geometry_showcase/             # v0.2 geometry 회귀
│  ├─ measured_box/                  # v0.4 제약 평가
│  ├─ first_reference_test/           # 승인된 실제 작업 구조 회귀
│  └─ floating_island/               # 콘셉트 장면 예시
├─ tests/
├─ scripts/
│  ├─ run_v04_gates.ps1              # Windows 전체 gate
│  ├─ run_v04_gates.sh
│  ├─ verify_v04_regressions.py       # modifier/constraint/plan/실제 작업 회귀
│  └─ run_v04_mcp_regressions.py      # stdio MCP Cycles/GPU 회귀
└─ workspaces/<job>/                 # 실제 작업별 격리된 데이터
```

## 작업별 파일 계약

```text
workspaces/<job>/
├─ job.json                          # 입력 목록, 해시, mode, scale anchor
├─ input/                            # 변경 금지 원본
│  ├─ reference.png
│  ├─ front.png
│  ├─ right.png
│  └─ top.png
├─ analysis/
│  ├─ reference_analysis.json        # 이미지 크기/경계/edge/symmetry/color/line
│  ├─ camera_solution.json           # 투영, 카메라 가정, 잠금/미결정 변수
│  ├─ modeling_plan.json             # semantic object 분해와 geometry 전략
│  ├─ scene_spec.json                # 정식 모델링 설계 원본
│  ├─ diagnostics/*_edges.png
│  └─ masks/*_content.png
├─ constraints/
│  └─ constraints.json               # 치수/위치/거리/정렬/동일 치수와 tolerance
├─ geometry/                         # 큰 custom mesh 등 외부 geometry payload
├─ history/                          # 이전 SceneSpec과 교체된 보조 시점
├─ blender/scene.blend               # 파생 산출물
├─ renders/preview.png               # 비교 카메라 렌더
├─ reports/
│  ├─ scene_inventory.json           # world bbox와 runtime metadata
│  ├─ validation.json                # 구조 검증
│  ├─ constraint_solution.json       # 실측 잔차
│  └─ revision_diff.json             # 승인된 수정 전후 값
├─ textures/
└─ exports/
```

## 데이터 흐름

```text
이미지/도면/치수
  → 원본 복사 + SHA-256
  → deterministic reference analysis
  → camera solution scaffold
  → Codex semantic modeling plan
  → SceneSpec 0.2 + geometry payload
  → Blender build
  → preview + world-space inventory
  → structural validation
  → measured constraint evaluation
  → guarded revision
```

## Blender 5.0.1 호환 경계

Blender 호출은 다음 세 지점에서 격리합니다.

1. `blender_runner.py`
   - `--python-exit-code 1`
   - `stdin=subprocess.DEVNULL`
   - timeout 및 stdout/stderr 캡처
2. `blender_scripts/compat.py`
   - `BLENDER_EEVEE`를 먼저 실제 적용
   - 실패 시 `BLENDER_EEVEE_NEXT`
   - AgX look과 투명 재질 API fallback
   - modern/legacy OBJ exporter fallback
3. `probe_compat.py`
   - Blender runtime/engine/look 기록
   - GLB/OBJ/FBX smoke export

API probe와 geometry 전체 파이프라인은 별도 gate입니다. `blender-compat`가 성공해도 `geometry_showcase` build/render/inspect/validate를 이어서 실행해야 합니다.

Geometry 회귀는 SceneSpec의 modifier 선언뿐 아니라 Blender 객체에 기록된
`cbm_declared_modifier_kinds`와 `cbm_applied_modifier_kinds`를 비교합니다. 파괴적으로
적용되어 live stack에 남지 않는 voxel remesh도 이 provenance로 검증합니다.

## v0.4 제약 평가의 의미

지원 계약:

- overall/object dimension
- semantic object center location
- object-to-object distance
- center/min/max alignment
- equal dimension
- per-constraint tolerance
- semantic family 또는 array instance 지정

v0.4는 Blender 결과를 측정해 residual을 계산합니다. 임의의 비선형 CAD 시스템을 자동으로 푸는 솔버는 아니며, 실패 residual을 `RevisionPlan`으로 바꿔 최소 수정하는 구조입니다.

## 새 기능을 추가할 위치

- 새로운 이미지 분석 provider: `analysis/`
- 새로운 geometry recipe: `blender_scripts/builders/` + SceneSpec 모델/스키마
- 새로운 제약 종류: `constraints/models.py`, `constraints/evaluator.py`, 스키마/테스트
- Blender API 버전 차이: `blender_scripts/compat.py`
- 새 MCP 동작: `mcp_server.py`의 명시적 whitelist
- 텍스처 자동화: 향후 `texturing/` provider 계층으로 추가
- 픽셀 기반 자동 QA: 향후 `qa/` render-pass/metric 계층으로 추가
