# BlenderAssetGenerator 빠른 시작

현재 프로젝트 버전은 `0.9.0`입니다. 설치, 안정화 audit, single-worker queue와 release-candidate gate는 [GETTING_STARTED_V09_KO.md](GETTING_STARTED_V09_KO.md)를 따르세요. 짧은 요청 workflow의 단계·승인 경계는 계속 [GETTING_STARTED_V08_KO.md](GETTING_STARTED_V08_KO.md)를 사용합니다.

단계별 상세 문서는 다음과 같습니다.

- 전체 현황과 기본 명령: [README.md](README.md)
- 새 레퍼런스 단계별 검증 프롬프트: [NEW_REFERENCE_VALIDATION_PROMPTS_KO.md](NEW_REFERENCE_VALIDATION_PROMPTS_KO.md)
- 작은 창문·라벨·이음선의 메시/텍스처 분류: [SURFACE_DETAIL_ROUTING_KO.md](SURFACE_DETAIL_ROUTING_KO.md)
- 안정화, workspace audit와 queue: [GETTING_STARTED_V09_KO.md](GETTING_STARTED_V09_KO.md)
- 재질·텍스처·셰이더와 Visual QA: [GETTING_STARTED_V06_KO.md](GETTING_STARTED_V06_KO.md)
- 정적 자산 최적화와 portable package: [GETTING_STARTED_V07_KO.md](GETTING_STARTED_V07_KO.md)
- 선택적 실내 범위와 승인형 다각도 QA: [INTERIOR_SCOPE_KO.md](INTERIOR_SCOPE_KO.md)
- V1.0까지의 공식 단계: [ROADMAP_V1_KO.md](ROADMAP_V1_KO.md)

실내는 기본 비활성화입니다. 건물 내부가 필요한 경우에만 scope draft → exact-hash approval → validation 절차를 수행하고, 별도 다각도 QA도 exact camera-plan hash 승인 뒤에만 실행합니다. Unity, Unreal 또는 다른 목적 엔진 adapter는 실제 환경 검증 전까지 지원된 것으로 취급하지 않습니다.

이 파일은 기존 링크를 위한 최신 진입점으로 유지합니다.
