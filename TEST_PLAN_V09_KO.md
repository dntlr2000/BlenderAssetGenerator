# V0.9 테스트 계획

V0.9 완료 판정은 Python contract test만으로 내리지 않는다. 이전 계약 회귀, failure boundary, 개인정보 보호, immutable evidence, Blender 5.0.1 실기동과 PDF 시각 검사를 함께 확인한다.

## Gate 1 — 계약과 공개 표면

- 모든 `0.9.0` Pydantic model과 checked-in JSON Schema parity
- unknown field 거부와 relative-path 검증
- CLI command 등록
- MCP allowlist와 capability version
- 프로젝트 `0.9.0`, workflow `0.8.0`, 기존 contract version 유지

## Gate 2 — environment probe

- 기존 Blender compatibility JSON hash 검증
- Blender version과 executable basename 추출
- missing/invalid/stale evidence를 경고 또는 실패로 구분
- repository, workspace와 외부 source absolute path 비노출
- probe ID overwrite 및 traversal 거부

## Gate 3 — workspace audit

정상 사례:

- V0.9 job
- 읽을 수 있는 compatible legacy job
- immutable source hash 일치
- 유효한 workflow latest pointer

음성 사례:

- source hash mismatch 또는 missing source
- path/link escape
- 손상 JSON과 unknown contract version
- dangling workflow pointer
- scan limit 초과
- audit output overwrite

모든 사례에서 canonical 파일 byte hash가 바뀌지 않아야 한다.

## Gate 4 — queue와 복구

- existing workflow만 enqueue
- job/workflow active duplicate 거부
- `max_concurrency=1`
- agent/review/approval에서 `waiting`
- live lock 거부, expired lock archive 복구
- lease와 immutable attempt receipt
- deterministic failure 후 자동 retry 없음
- explicit `--retry-failed` token 한 번만 소비
- max attempts, queue cancellation, underlying workflow 보존

## Gate 5 — PDF 보고서

- exact probe/audit strict-load
- PDF SHA-256과 source fingerprint sidecar
- source별 relative path, SHA-256와 byte size
- absolute path 비노출
- same report ID overwrite 거부
- 2페이지 이상, 텍스트 추출 가능
- representative page PNG render와 육안 clipping/overlap/한글 검사

## Gate 6 — V0.8/V0.7 회귀와 Blender

- 전체 `pytest`, Ruff, doctor
- 실제 Blender compatibility probe
- V0.8 isolated workflow regression
- V0.7 portable asset 회귀는 최근 검증 증거를 참조하되 release 전 별도 full gate로 재실행
- EEVEE feature probe, AgX, `stdin=DEVNULL`, `--python-exit-code 1`
- compatibility smoke export의 GLB/FBX/OBJ

## 실행 명령

```powershell
uv run pytest
uv run ruff check .
uv run cbm doctor
uv run cbm blender-compat
.\scripts\run_v09_gates.ps1
```

V0.9 gate의 smoke workspace는 `reports/v09_smoke/<run-id>/workspaces/`다. 기존 사용자 job을 변경해서 gate를 통과시키지 않는다.

## 지원 매트릭스 판정

각 조합은 다음 셋 중 하나로만 기록한다.

- `verified`: 실제 전체 관련 gate 통과
- `partially_verified`: contract/fallback만 검사하거나 일부 gate만 통과
- `unverified`: 실기동 증거 없음

감지됐거나 코드 fallback이 있다는 이유로 `verified`로 올리지 않는다. Unity, Unreal, custom adapter는 실제 import/runtime test 전에는 계속 unsupported다.
