# Exact native material swatch backend selection

The existing `workflow-resume` CLI and `resume_short_workflow` MCP tool accept
three additive optional arguments:

- `material_swatch_backend`: `eevee_auto` or `cycles_cpu` only.
- `material_swatch_input_fingerprint`: the exact current `material.swatches`
  step input fingerprint returned by native workflow status/reconciliation.
- `material_swatch_failed_attempt_sha256`: SHA-256 of the exact latest failed
  `attempts/material.swatches/*.json` receipt, required only for a failed retry.

CLI names use hyphens, for example `--material-swatch-backend cycles_cpu`.
A failed step still requires `--retry-failed` / `retry_failed=true` and the exact
latest host-failure receipt. A fresh ready swatch step requires the backend and
input fingerprint, and rejects failed-retry flags or invented failure evidence.
The selection is confined to that one currently ready step. It cannot select a
future step, approve materials, change an immutable plan, or replace any normal
contract, fidelity, build, inspection or review gate. Default calls and legacy
request/plan/state/attempt serialization are unchanged.

Under the native workflow write lock, the host checks exact plan, request,
predecessor input fingerprint, current source snapshots, recursive build
provenance, current Blend bytes and full material membership. It creates
`swatch_executions/<attempt-id>/selection.json` within the owning workflow and
renders every swatch into that new execution's directory. The Blender subprocess
requires its embedded build fingerprint to match before rendering. The host
rechecks current source/dependency bytes before publishing the derived manifest
and the ordinary success receipt. Failure preserves its selection and partial
render outputs and creates an ordinary failed attempt receipt. A later selection
must bind that new latest failure; it cannot replay an earlier receipt.

No existing swatches are adopted. Prior failed receipts and partial PNGs are
preserved, and a pre-existing derived swatch manifest is copied into the new
execution before replacement. The portable manifest records the actual renderer,
actual device, full material membership, every PNG hash, build fingerprint and
hash-bound backend-selection contract. Its normal workflow snapshot covers this
binding. Reconciliation verifies the selected contract, immutable workflow/failure
evidence and execution-owned PNG hashes without retroactively requiring current
canonical sources to equal historical sources.

`cycles_cpu` is a deliberate alternative render backend, not proof of visual
parity with EEVEE or a destination engine. It grants neither material appearance
approval nor human quality acceptance. Automatic fallback, GPU selection, arbitrary
renderer parameters, stale manifest adoption, plan mutation and terminal workflow
reopening are not supported by this option.
