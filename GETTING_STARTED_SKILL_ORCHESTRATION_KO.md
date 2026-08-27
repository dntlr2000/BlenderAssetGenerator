# Skill Orchestration 시작 가이드

## 1. 카탈로그 확인

```powershell
uv run cbm skill-catalog
```

MCP에서는 `get_skill_catalog`을 사용합니다. 이 호출은 run이나 권한을 만들지 않습니다.

## 2. 새 Standard 자산을 QA까지

```powershell
uv run cbm standard-asset-cycle-plan `
  "이 레퍼런스로 정적 소품을 QA까지 제작해줘" `
  --job-id example-prop `
  --goal new_asset_to_qa `
  --reference .\reference.png

uv run cbm standard-asset-cycle-run example-prop <run-id>
```

agent 저작 또는 approval에서 멈추면 기존 V0.8 surface로 exact completion/approval을 기록한 뒤 다음 명령을 실행합니다.
상태 응답의 `current_skill_route`는 현재 V0.8 state hash에 대응하는 다음 단계 skill을 표시하지만, 그 자체로 실행·승인 권한을 만들지는 않습니다.

```powershell
uv run cbm standard-asset-cycle-resume example-prop <run-id>
```

진입 스킬 호출 자체는 proxy, detail, material, QA, optimization 또는 revision 승인이 아닙니다.

## 3. 기존 자산 개선

```powershell
uv run cbm standard-asset-cycle-plan `
  "현재 형상과 재질을 점검하고 QA까지 개선해줘" `
  --job-id existing-prop `
  --goal polish_existing_to_qa `
  --stage-policy smart
```

모든 단계를 강제로 새로 수행하려면 `--stage-policy force_all`을 사용합니다. package까지 필요할 때만 `--goal full_cycle_to_package`를 선택합니다. 이 goal은 exact `qa.review` 뒤 표시되는 `quality_disposition fingerprint`에 대해 `accepted` 또는 `needs_revision`을 별도로 기록해야 하며, 그 뒤에도 V0.7 optimization-plan approval은 별도로 유지됩니다.

## 4. QA repair cycle

`qa_repair_cycle`은 첫 QA를 수행한 뒤 existing guarded revision boundary에서 멈춥니다. 표시된 동일 QA run에서 exact candidate 선택, user approval, apply를 기존 V0.6 명령으로 처리한 뒤 composite를 resume합니다. consumed approval과 application report가 현재 SceneSpec 결과 hash에 정확히 결합될 때만 새 QA가 계획됩니다.

## 5. AQ One-Prompt adapter

AQ v2는 비활성 experimental profile이므로 delegation과 opt-in을 둘 다 명시해야 합니다.

```powershell
uv run cbm aq-one-prompt-skill-plan `
  "이 레퍼런스의 정적 소품을 자율 제작해줘" `
  --reference .\reference.png `
  --target-subject prop `
  --deliveries portable_gltf `
  --delegate-routine-actions `
  --enable-v2
```

```powershell
uv run cbm aq-one-prompt-skill-run <job-id> <run-id> --enable-v2
uv run cbm aq-one-prompt-skill-resume <job-id> <run-id> --enable-v2
```

controller output, IQ submission, genuine consolidated escalation, budget 또는 terminal에서 멈춥니다. 앱이 종료되면 실행도 끝나며 같은 task에서 상태를 다시 검증해 resume해야 합니다.

## 6. 상태·trace·취소

```powershell
uv run cbm standard-asset-cycle-status <job-id> <run-id>
uv run cbm aq-one-prompt-skill-status <job-id> <run-id>
uv run cbm skill-trace <job-id> <run-id>
```

취소는 미래 실행만 중지하고 evidence는 삭제하지 않습니다.

```powershell
uv run cbm standard-asset-cycle-cancel <job-id> <run-id> --reason "요청 변경"
uv run cbm aq-one-prompt-skill-cancel <job-id> <run-id> --reason "요청 변경" --enable-v2
```
