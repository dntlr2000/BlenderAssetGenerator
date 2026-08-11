# V0.7 portable smoke evidence — 2026-08-11

이 snapshot은 최종 V0.7 smoke에서 생성된 `portable_gltf`, `fbx_interchange`, `obj_legacy`
각 package manifest와 clean-import roundtrip evidence/validation을 바이트 동일하게 보존한다.

절대 호스트 경로를 포함하던 사람용 PDF sidecar, 전체 run-owned optimization workspace와 source
`.blend`는 포함하지 않는다. 따라서 이 폴더는
당시 package/roundtrip machine evidence의 compact audit snapshot이며, 새 설치의 Blender 호환성을
대신 인증하지 않는다.
