# Skill Orchestration 0.1 마이그레이션

## 호환성 원칙

이 변경은 data migration이 아닙니다. 프로젝트는 `0.9.0`, canonical SceneSpec은 `0.2.0`, V0.8 workflow는 `0.8.0`으로 유지됩니다. 기존 job, workflow, AQ session, approval, receipt, terminal과 13개 기존 skill은 수정되지 않습니다.

## 기존 사용자

- 기존 개별 skill 호출은 계속 사용할 수 있습니다.
- 전체 Standard 흐름은 새 `$standard-asset-cycle`을 선택합니다.
- AQ v2 One-Prompt를 단계별 trace와 함께 운용할 때만 `$aq-one-prompt-orchestrator`를 선택합니다.
- 이미 시작한 workflow/AQ session을 새 skill run으로 소급 포장하지 않습니다. 새 요청 또는 명시적으로 새 composite plan을 생성한 시점부터 적용합니다.

## skill 작성자

새 skill을 추가하려면 다음을 모두 동기화해야 합니다.

1. `.agents/skills/<id>/SKILL.md`
2. `.agents/skills/registry.json`의 mode, role, dependencies, unique route keys, exact allowed tools
3. 필요한 경우 strict schema/model과 host route
4. CLI/MCP/`.codex/config.toml` public surface
5. registry DAG, route uniqueness, path/hash, schema parity, public allowlist test

진입 스킬을 임의로 추가하면 안 됩니다. 현재 public pair 변경은 별도 architecture review가 필요합니다.

## rollback

source rollback 요청 시 Skill Orchestration source, registry, schemas, docs, public surface를 함께 되돌려야 합니다. 이미 만들어진 `skill_runs/`는 immutable historical evidence이므로 삭제하거나 이전 의미로 재분류하지 않습니다. 기존 V0.8/AQ evidence는 이 companion과 독립적으로 유지됩니다.

