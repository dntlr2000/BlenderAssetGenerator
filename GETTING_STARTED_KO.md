# BlenderAssetGenerator 빠른 시작

현재 프로젝트 버전은 V0.7입니다. 설치, 재질·텍스처·셰이더, Visual QA, 정적 자산 최적화와 portable package 사용법은 [GETTING_STARTED_V07_KO.md](GETTING_STARTED_V07_KO.md)를 따르세요.

기존 V0.4 Geometry/Reference/Measured와 V0.5/V0.6 기능은 V0.7에 포함되며 SceneSpec 계약은 계속 `0.2.0`입니다. 격리된 V0.7 호환성 및 회귀 검증은 다음 명령으로 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_v07_gates.ps1
```
