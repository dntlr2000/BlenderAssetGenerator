# Material Closure Stabilization 0.1.0 evidence index

This compact index records the verification performed on 2026-08-14 KST. It does not copy or replace
authoritative job-local machine JSON. Exact incident paths and hashes are documented in
[`CRYSTALGUN_FRAMEWORK_INCIDENT_KO.md`](../../../CRYSTALGUN_FRAMEWORK_INCIDENT_KO.md); scope and
interpretation are documented in
[`VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md`](../../../VERIFICATION_MATERIAL_CLOSURE_STABILIZATION_KO.md).

## Executed gates

### Pre-implementation full baseline

```powershell
uv run pytest
```

Result: `1600 passed, 58 skipped, 8 warnings`.

This is the compatibility baseline after the minimal workspace-archive lazy-import repair. It predates
the Material Closure implementation and is not the final implementation-postdating full regression.

### Recorded focused Material Closure host aggregate

```powershell
uv run pytest -q --basetemp .gate-tmp\closure-all-final `
  tests/test_material_closure_contracts.py `
  tests/test_material_closure_service.py `
  tests/test_material_closure_aq_integration.py `
  tests/test_material_closure_schemas.py `
  tests/test_material_closure_controller_repair.py `
  tests/test_material_closure_incident_service.py `
  tests/test_material_closure_public.py `
  tests/test_material_retry_supersession.py `
  tests/test_no_job_specific_framework_literals.py `
  tests/test_ci_workflows.py
```

Result: `138 passed, 1 skipped in 9.57s`. A later expanded host selection after the final P1 fixes
passed `165 tests` with `4` environment-gated skips; the full repository result below is authoritative.

The skipped test is the environment-gated actual Blender node, which was run separately below. Earlier
125/1 and 87/1 focused runs were intermediate overlapping selections and are superseded by this final
focused result rather than added to it.

### Actual Blender 5.0.1 preapproval boundary

```powershell
$env:CBM_RUN_MATERIAL_CLOSURE_BLENDER_SMOKE='1'
uv run pytest -q --basetemp E:\cbm-material-closure-blender-final-20260814 `
  tests/test_material_closure_service.py::test_complete_preflight_runs_actual_blender_5_and_stops_before_approval
```

Result: `1 passed in 13.76s` (`14.9s` wall time).

The test executed the complete closure/preflight path, an isolated full-scene Blender 5.0.1 shadow
build and a real neutral PNG. It asserted unchanged canonical SceneSpec, ModelingPlan and Blend,
continued canonical MaterialPlan absence, and zero approval, consumption, controller, promotion,
rollback, MaterialPhaseReceipt, IQ and destination effects.

### Supporting checks

The following completed successfully for the then-current implementation:

- Ruff over the changed source/scripts/tests scope
- `python scripts/check_no_job_specific_framework_literals.py`
- `python scripts/check_agent_instructions.py` — 16 instruction files / 192 invariants
- `python scripts/generate_schemas.py --check`
- generic JSON LF/hash regression — 38 passed

The final full-repository results are recorded below.

## Crystalgun retry02 evidence summary

Historical AQ head remains `0012 / terminal / cancelled / none`. Retry02 is
`material-repair-20260814t041500000z-retry02`.

| Evidence | SHA-256 | Result |
|---|---|---|
| dependency closure | `70115e5ad14865ba8438a49497a1df782eb9ed0d5854ffbf85393532b77c364d` | published |
| closure receipt | `374e1455a3e6e6f7e48ecb6090a6d198d273a3f507d1c0e53eb9743fa624e063` | published |
| preflight failure | `c5b3d5409793577ed25f0003a86fea19596c2eb6543f54d58b1ab22164f61c37` | `preflight_failed` |
| attempt state | `a17820f0e23b6f6fe55077731d74c9249d8e394afb94fa3a388c872aed836c93` | sequence 1, `preflight_failed` |

Exact issue:

```text
candidate MaterialPlan lacks image-backed UV coverage for detail.crystal.facet_lines
```

This was an honest approval-before-controller failure. Blender preflight, neutral preview, appearance
approval, controller, promotion, rollback, canonical write and IQ were all zero. Canonical hashes
remained:

- SceneSpec `ef7cadec41a56a10701c10ea623fb6367dc05cb34acc39f8d360b8752fe77ab8`
- ModelingPlan `52779a95bd5bf4f87b55cd6481d55c8e50efcaca79e7c16973682314b1a4b225`
- Blend `5def13d76012b0c9747dce6ef016799550bca74a9e5f2e3bccf6b7ed8a9ebe5a`
- canonical MaterialPlan absent

The exact source inventory and two archived job-specific recovery source hashes are in the incident
document. Source archive/deletion and old retry/session supersessions were completed append-only.

## Explicitly unverified or not run

- actual user-authorized MaterialAppearanceApproval success and single-use consumption
- actual one-shot fixed controller success and canonical promotion
- real `MaterialPhaseReceiptV2` and IQ 0.2 transition
- authorized post-promotion failure/rollback end-to-end execution
- ImageGen plus localized-detail actual Blender fixture
- crystal plus emission plus alpha actual Blender fixture
- fresh built-in ImageGen invocation or human material-quality review
- chained V0.7–V0.9 regression
- accepted GLB/FBX production package and destination runtime parity

Neither experimental profile was activated.

## Final repository checks

- `uv sync --frozen --extra dev --extra vision`: passed; 51 packages checked.
- `uv run pytest -q --basetemp E:\cbm-material-closure-full-final-20260814`:
  `1750 passed, 62 skipped, 8 warnings in 276.29s`.
- `uv run ruff check .`: passed.
- `uv run cbm doctor`: passed; repository, workspace, Blender and Codex checks were OK.
- `uv run cbm blender-compat`: passed with Blender 5.0.1 and GLB/FBX/OBJ smoke checks.
- `uv run python scripts/check_agent_instructions.py`: passed with root 7,764 bytes,
  16 instruction files and 192 legacy invariants.
- `uv run python scripts/check_no_job_specific_framework_literals.py`: passed.
- `uv run python scripts/generate_schemas.py --check`: passed.
- A temporary copy of the Git index was populated only with the audited intended paths; the authoritative
  generator then wrote and rechecked `README.md`, `REPOSITORY_TREE.txt` and `FILE_MANIFEST.sha256` with
  `OK: repository catalog and generated projections are current`. The real Git index tree remained
  unchanged (`432400586081740bff3d19eb7ee84770ba8f2fbf`).
- `git diff --check`: passed; Git reported line-ending conversion notices only.
