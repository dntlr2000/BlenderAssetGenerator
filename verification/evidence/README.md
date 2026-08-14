# Portable verification evidence

이 디렉터리는 로컬 임시 경로에만 존재하던 Autonomous Quality 검증 증거 중
설치 후에도 감사할 가치가 있는 최소 묶음을 저장소 상대 경로로 보존한다.

- [`aq_v1_20260810/`](aq_v1_20260810/): AQ 0.1 최종 benchmark, 성공 terminal의 package·roundtrip·handoff
  직접 종속물, 비통과 terminal의 review bundle snapshot.
- [`aq_v2_20260811/`](aq_v2_20260811/): AQ 0.2 최종 benchmark와 두 Blender benchmark fixture receipt.
- [`v07_20260811/`](v07_20260811/): GLB·FBX·OBJ package manifest와 clean-import roundtrip snapshot.
- [`v08_20260811/`](v08_20260811/): standard/background workflow state, QA, FBX package·roundtrip snapshot.
- [`v09_20260811/`](v09_20260811/): production/desktop/queue state와 portable handoff·roundtrip snapshot.
- [`workspace_archive_20260813/`](workspace_archive_20260813/): terminal workspace의 동일 볼륨 이동·복구와 fail-closed
  production-lineage quarantine를 기록한 compact index.
- [`imagegen_material_loop_20260813/`](imagegen_material_loop_20260813/): ImageGen Material Loop host/Blender review-boundary와
  승인 없는 delivery mechanism 범위를 기록한 compact index.
- [`material_closure_stabilization_20260814/`](material_closure_stabilization_20260814/): graph-derived Material Closure, 실제 Blender 5.0.1
  승인 전 preflight, Crystalgun append-only recovery와 명시적 미검증 경계를 기록한 compact index.
- [`material_identity_split_20260814/`](material_identity_split_20260814/): shared material scope-change의 paired
  SceneSpec/ModelingPlan, 실제 Blender 5.0.1 shadow preapproval, ApprovalRequest와 zero-side-effect 경계를
  기록한 compact index.

원본 pytest basetemp, 캐시, 중간 실패 실행, 중복 `.blend`, 전체 render pass는 저장소에
복사하지 않았다. 따라서 이 묶음은 당시 pytest stdout 전체를 재현하는 archive가 아니다.
테스트 통과 수치는 각 버전 README와 검증 문서에 기록된 historical execution record이며,
현재 release를 다시 인증하려면 해당 gate를 새 격리 경로에서 재실행해야 한다.

모든 포함 파일은 원본에서 바이트 단위로 복사됐고, 저장소의
`FILE_MANIFEST.sha256`이 각 파일의 SHA-256을 결속한다. 이 디렉터리 내부에는 절대 호스트
경로를 기록하지 않는다.
