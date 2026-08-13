# Terminal workspace archive — 2026-08-13

이 디렉터리는 V0.9 reversible terminal workspace archive의 로컬 실행 요약이다. 원본
archive plan/receipt와 job tree는 Git 추적 대상이 아닌 동일 볼륨 `workspace_archive/`에
있으며, 이 요약은 그 machine evidence를 대체하지 않는다.

## 실행 결과

- exact terminal preflight 적격: `16`
- archive 완료 및 현재 tree 재검증: `16`
- 이동된 파일: `27,965`
- 이동된 디렉터리: `13,265` (각 job root 포함)
- 이동된 bytes: `3,456,425,516` (`3.219 GiB`)
- failed job archive: `0`
- 이동 후 남은 적격 job: `0`
- source/destination tree mismatch: `0`
- receipt replay failure: `0`

처음 상태 요약에서 `completed`였던 19개 중 production dispatch를 가진 다음 3개는
`production advance workflow-state lineage is broken`으로 fail closed되어 active workspace에
남았다.

- `collectible_plastic_01_desktop`
- `collectible_rock_01`
- `collectible_scrap_01`

`blocked`, agent/approval 대기, planned, workflow 근거 없음, AQ/AQ v2 job은 이동하지 않았다.
실제 `failed` 상태 job은 발견되지 않았으므로 `--allow-failed`도 사용하지 않았다.

## 검증 범위

- archive/restore/crash-adoption/tamper 집중: `6 passed, 1 symlink-capability skip`
- V0.9 contract/public surface 포함: `15 passed, 1 skipped`
- 기존 V0.9 audit/queue/production/catalog 회귀: `57 passed, 1 skipped`
- focused Ruff: 통과
- method docstring audit: 누락 `0`
- agent instruction checker: 통과

각 job의 receipt ID, receipt SHA-256, archive-relative path, tree SHA-256과 byte 수는
[manifest.json](manifest.json)에 기록했다. 복원에는 README가 아니라 local archive root의
exact receipt ID를 사용한다.
