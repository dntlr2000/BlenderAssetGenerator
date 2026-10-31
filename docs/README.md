# 문서 안내 — v0.9.1

현재 사용·종료 상태는 [HANDOFF_KO.md](HANDOFF_KO.md), 기본 사용법은 [빠른 시작](guides/GETTING_STARTED_KO.md)을 먼저 읽습니다.

Reference-fidelity 장기 개선은 A안으로 종료됐습니다. 보존된 개발·검증 기록은 자동 재개 지시나 새로운 품질·인간 수용 판정이 아닙니다.

문서 재배치, 외부 증거 위치, 실제 정리량과 남긴 자료는 [저장공간 정리·복원 안내](reference_fidelity_closeout/STORAGE_ORGANIZATION_KO.md)를 참조하세요. 로컬 외부 증거는 GitHub clone에 포함되지 않습니다.

2026-10-10~11의 [과거 scratch 보관소 폐기 기록](reference_fidelity_closeout/archive_retirement_20261010/README_KO.md)과 [추가 정리 후보·측정 용량](reference_fidelity_closeout/CLEANUP_CANDIDATES_20261010_KO.md)을 확인하세요. 폐기한 보관소의 옛 locator는 이력용이며 복원 가능한 백업이 아닙니다.

| 분류 | 위치 |
| --- | --- |
| 현재 사용 안내 | [guides](guides/) |
| 구조 설명 | [architecture](architecture/) |
| 단계별 계획 | [roadmap](roadmap/) |
| 마이그레이션 설명 | [migration](migration/) |
| 사람이 읽는 실행 프롬프트 예시 | [prompts](prompts/) |
| 시험 계획·지표 정의 | [testing](testing/) |
| 과거 검증 기록 | [verification](verification/) |
| 과거 사건·검토 기록 | [history](history/) |
| 종료·재평가 기록 | [reference_fidelity_closeout](reference_fidelity_closeout/) |
| 에이전트 지침 | [agent](agent/README.md) |

## 역사 원본 위치 예외

다음 두 원본은 변경하지 않은 machine verification locator가 참조하므로 저장소 루트에 보존합니다. 현재 문서의 진입점은 이 인덱스입니다.

- [Reference-fidelity 개발 실증 원본](../VERIFICATION_REFERENCE_FIDELITY_KO.md)
- [Skill orchestration 검증 원본](../VERIFICATION_SKILL_ORCHESTRATION_KO.md)

전체 원경로·현재 경로는 [문서 이동표](DOCUMENT_RELOCATION_KO.md)에 있습니다. 과거 버전·날짜·검증 결과는 현재 v0.9.1 실적으로 재분류하지 않습니다.


## 2026-10-20 과거 workspace 정리

③·④의 실제 삭제와 보존 예외는 [정리 결과](reference_fidelity_closeout/WORKSPACE_CLEANUP_20261020_KO.md), 삭제하지 않은 ②의 모델·QA·PDF·snapshot 용량은 [상세 분석](reference_fidelity_closeout/WORKSPACE_CATEGORY2_STORAGE_20261020_KO.md)을 참조하세요.


## 2026-10-21 완료 자산 폐기

사용자의 새 보존 기준에 따라 완료 작업 46개(48,162파일, 7.198 GB)를 실제 폐기했다. 실패·보류·알려진 시각 결함·완료 불명확 자산 19개와 공유 소비 기록은 유지했다. 완료 모델·package 전체는 복원할 수 없으며 원본 reference와 최소 이력만 외부에 보존했다. 앞선 표의 보존·복원 설명은 각 기록 날짜의 상태다. [실제 삭제 목록·현재 보존 목록·무결성 검증](reference_fidelity_closeout/WORKSPACE_COMPLETED_RETIREMENT_20261021_KO.md)을 따른다.

- [Quad-dominant polygon authoring](polygon_authoring.md): polygon sources, inspection views and bounded Cloth/Rock/Wood validation.
- [사각형 저작 구현·3자산 검증 결과](QUAD_AUTHORING_VALIDATION_KO.md): 최종 원본·GLB·실제 관찰·한계·비용과 검증 기록.
