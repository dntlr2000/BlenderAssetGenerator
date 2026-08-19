# Skill Orchestration 0.1 검증 기록

## 현재 확인된 결과

- 구현 전 관련 기준선: V0.8/AQ Approval Envelope/One-Prompt/activation readiness 관련 `181 passed`
- Skill Orchestration + V0.8/AQ/Material Closure/V0.9 집중 회귀: `170 passed, 2 skipped`
- 전체 회귀: `1947 passed, 63 skipped, 8 warnings`
- 공식 AQ host/smoke 게이트: `914 passed, 26 skipped, 8 warnings`; AQ 0.1/0.2 고정 벤치마크 생성 완료
- 공식 V0.9 격리 게이트: 전체 회귀 `1947 passed, 63 skipped, 8 warnings` 후 Blender 패키지, clean import, handoff, production dispatch, queue, audit, stability report 통과
- `uv run ruff check .`, `uv run cbm doctor`, agent instruction checker, schema drift 검사: 통과
- Blender compatibility: Blender `5.0.1`, Python `3.11.13`, GLB/FBX/OBJ smoke export 통과
- skill-creator quick validation: 신규 사용자 진입/단계 스킬 `10/10` 통과
- registry: 23 skills, public entrypoint 2, dependency DAG valid
- 새 Standard plan fixture: QA review 포함, portable phase 없음
- Standard first-run fixture: V0.8 agent authoring boundary에서 정지
- run-owned SKILL.md snapshot tamper: fail-closed
- AQ adapter default opt-in 부재: job 생성 전 거부
- AQ activation readiness contract: `disabled_experimental`, activation/campaign 생성 0건

첫 V0.9 게이트 시도는 저장소 내부 기본 pytest 임시 경로가 Windows 경로 한도를 넘겨 `WinError 206`으로 실패했다. V0.9 Windows/POSIX 게이트가 짧고 고유한 저장소 내부 `--basetemp`를 사용하도록 보완했고, 계약 테스트와 전체 게이트 재실행이 통과했다.

## 아직 주장하지 않는 결과

- 실제 Blender 5.0.1로 한 Standard 전체 자산의 V0.4→V0.5→V0.6→V0.7 완료
- 실제 AQ v2 material closure/IQ/delivery E2E
- 사람의 시각 품질 acceptance
- AQ v2 profile activation 또는 `verified_active` 승격
- Unity/Unreal destination runtime parity

V0.9 게이트의 Blender 실행은 격리된 `geometry_showcase` fixture에 대한 패키징·handoff 메커니즘 증거다. Standard 복합 스킬 또는 AQ adapter가 실제 사용자 자산의 시각 품질을 끝까지 달성했다는 증거로 재분류하지 않는다. 테스트 fixture나 과거 activation-readiness report를 새 source baseline 또는 human acceptance로 재사용하지 않는다.
