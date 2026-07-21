# V0.8 테스트 계획

## 목적

V0.8 검증은 “짧은 요청이 무조건 완성 자산을 만든다”를 증명하는 것이 아니다. 요청을 올바른 기존 단계로 라우팅하고, 승인·신선도·재개 경계를 우회하지 않으며, 기존 V0.4~V0.7 기능을 깨뜨리지 않았음을 검증한다.

## Gate 1 — Python과 계약

```powershell
uv run pytest
uv run ruff check .
```

필수 항목:

- V0.8 Pydantic 모델과 checked-in JSON Schema 일치
- 모든 계약 `additionalProperties: false`
- project `0.8.0`과 workflow `0.8.0`
- SceneSpec `0.2.0`, Material `0.5.0`, QA `0.6.0`, Portable `0.7.0` 유지
- CLI 명령과 MCP allowlist 공개

## Gate 2 — 라우팅과 job 격리

- 새 레퍼런스가 새 job의 `new_asset`으로 라우팅됨
- 기존 job은 primary reference hash가 같아도 명시적 `new_asset`을 파일 생성 전에 거부함
- 새 작업 기본 scope가 `proxy_only`
- 기존 job에 다른 primary reference를 넣으면 파일 변경 전에 거부
- 기존 job의 모호한 요청은 명시적 intent 요구
- auxiliary view는 staging 뒤 `add_view`로 승격
- 서로 다른 job과 workflow의 파일 경로가 격리됨

## Gate 3 — 상태와 신선도

- request/route/plan 불변성
- 같은 파일을 다시 읽어 상태를 결정론적으로 재구성
- agent completion이 plan/input/output hash와 일치할 때만 완료
- dependency 또는 output 변경 시 completion이 stale
- 일반 승인이 현재 artifact fingerprint와 일치할 때만 완료
- stale 승인과 marker가 다음 단계를 열지 않음

## Gate 4 — 실패·잠금·재개

- live lock이 concurrent writer를 거부
- expired lock은 이력 보존 후 복구
- running attempt가 남으면 `InterruptedAttempt`로 종료
- host 실패가 고유 receipt에 기록됨
- 명시적 `--retry-failed` 없이는 재시도되지 않음
- retry 시 기존 attempt를 보존하고 새 attempt 생성
- 취소가 기존 산출물을 삭제하지 않음
- 취소된 workflow 재개 거부

## Gate 5 — 승인 경계

- 프록시·상세·swatch·QA·최종 package 일반 승인
- InteriorScope 일반 승인 대체 불가
- V0.6 visual revision 일반 승인 대체 불가
- V0.7 optimization 일반 승인 대체 불가
- optimization plan이 LOD/collider 설정을 표시한 뒤 exact hash 승인을 기다림

## Gate 6 — 목적지 경계

- engine-neutral adapter만 available
- Unity/Unreal/custom은 unsupported
- 미지원 목적지가 portable package terminal boundary를 유지
- engine prefab/actor, runtime shader, runtime collision/LOD parity를 성공으로 기록하지 않음

## Gate 7 — V0.7 Blender 회귀

격리된 `geometry_showcase`로 다음을 재검증한다.

```text
material → build → render → inspect → validate
→ V0.7 preflight
→ LOD/collider plan 표시
→ exact hash approval
→ optimize
→ GLB/FBX/OBJ package
→ clean-import round trip
→ export PDF
```

기존 `first_reference_test`는 자동 gate에 사용하지 않는다.

## 완료 조건

- 전체 Python test 통과
- Ruff 통과
- V0.8 isolated smoke workflow 생성·분석·중지 성공
- V0.7.4 Blender 5.0.1 isolated gate 회귀 통과
- 사용자 workspace와 canonical authoring 파일 변경 없음
- 미지원 adapter를 지원된 것처럼 보고하지 않음
