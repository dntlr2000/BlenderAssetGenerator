# v0.4 패키지 검증 기록

## 이 패키지 제작 환경에서 완료한 검사

- Python 단위 테스트: 18개 통과
- Ruff 정적 검사: 통과
- Python bytecode compile check: 통과
- sdist/wheel build: 통과
- `measured_box` example import 및 Pillow reference analysis smoke test: 통과
- 실제 부유섬 PNG를 이용한 새 작업 생성 및 reference analysis smoke test: 통과
- 중복 `job_id` 무변경 거부: 통과
- OpenCV provider import/line-analysis smoke test: 통과
- `uv.lock`의 package registry/파일 URL: 공개 PyPI 형식으로 정리

## 로컬 Blender에서 반드시 실행할 검사

이 패키지 제작 환경에는 Blender 실행 파일이 없으므로 v0.4 전체본의 실제 `.blend` 생성은 여기서 실행하지 못했습니다. 프로젝트에는 사용자가 v0.2에서 확인한 Blender 5.0.1 호환성 수정 사항을 반영했으며, 각 설치 환경에서는 다음 gate를 통과해야 합니다.

```powershell
.\scripts\run_v04_gates.ps1
```

최소 완료 조건:

- `cbm blender-compat`: `ok: true`
- runtime Blender version: `5.0.1`
- render engine: `BLENDER_EEVEE`
- geometry_showcase build/render/inspect/validate 통과
- GLB/OBJ/FBX export 통과
- measured_box constraint 3건 통과

실제 로컬 gate가 끝나기 전에는 해당 설치를 “v0.4 Blender 5.0.1 통합 검증 완료”로 표시하지 않습니다.
