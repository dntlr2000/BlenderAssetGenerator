# Explicit guarded solid-root attachment intent revision

This optional companion allows an existing, previously built solid-root `0.1.0`
job to revise source bytes while retaining its immutable initial registration.
It is restricted to existing Standard `revise_asset` / `manual_guarded` workflows
that already select an exact paired ModelingPlan. It grants no approval, native
geometry proof, package acceptance, mechanical-strength claim or visual acceptance.

## Exact request

Prepare a distinct contained `analysis/` candidate intent and candidate
ModelingPlan. Supply their physical byte hashes through `plan_workflow`, MCP
`plan_short_workflow`, or CLI `workflow-plan`:

```text
cbm workflow-plan --job-id example_asset --intent revise_asset \
  --revision-strategy manual_guarded --request "Apply the exact root-preserving revision" \
  --paired-modeling-plan-path analysis/candidates/model.json \
  --paired-modeling-plan-sha256 <exact-model-sha256> \
  --attachment-intent-path analysis/candidates/solid_root_intent.json \
  --attachment-intent-sha256 <exact-intent-sha256>
```

The Python and MCP names are `attachment_intent_path` and
`attachment_intent_sha256`. Both are required together and require the existing
`paired_modeling_plan_path` / `paired_modeling_plan_sha256` pair. Missing optional
fields remain omitted from legacy serialization. Ordinary two-file paired
requests and their `0.1.0` receipts are unchanged.

Only `source_scene`, `source_modeling_plan` and `source_geometry` may change.
Every other intent value stays exact, including all roots, IDs, radii, centers,
bounds, domain, required semantics/order, descriptions, minimum radius,
reference and camera hypothesis. Scene and ModelingPlan locators remain their
fixed canonical paths. Their new hashes must describe the exact prospective
SceneSpec serialization and exact staged ModelingPlan bytes, not the old live
files. Geometry uses real, contained, hashed candidate files and its complete
recursively bound source closure. No fake canonical staging or job reset occurs.

Planning checks the current selected intent and pins current job metadata.
Author completion computes both complete source-coordinate and predicted
binary32 closed-solid/embedding/root proofs with the existing caps and predicates.
The exact immutable candidate intent, proof reports, original registration,
prior selection/revision, old/new metadata hashes and revision record are bound
into `revision.payload_binding`, author output fingerprint and the existing
`revision.approval` fingerprint. Approval must be obtained through the existing
exact workflow boundary. Neither this API nor a passing proof fabricates it.

## History and atomic promotion

Each opted-in workflow owns an immutable
`production/surface_attachment/revisions/<workflow-id>/revision.json` record.
It links initial registration, previous revision/intent, next intent and the
original metadata hash. It identifies its workflow rather than embedding the
later approval/transaction hash, avoiding a hash cycle. The binding hashes the
record and the derived metadata; approval hashes the binding; the transaction
archives and hashes that exact authority chain.

The explicit `job.json` field `attachment_revision` points to this record.
Original `attachment_intent` and `attachment_registration_sha256` values stay
unchanged. No loading, audit, build or packaging operation discovers or repairs
an intent automatically.

The opted-in paired journal uses `0.2.0` and exactly three canonical targets:
`analysis/scene_spec.json`, `analysis/modeling_plan.json`, and `job.json`.
It preserves exact before/after archives and performs lock-owned compare-and-swap
for each target. Every intermediate write remains blocked for ordinary readers.
The same recovery API, with the exact transaction-intent SHA-256, restores all
three exact prior files or finishes an already committed host receipt without
reapplying. It refuses concurrent edits, replay, mixed versions and missing
archives. Failed/rolled-back attempts and all immutable records remain visible.

The Blender-safe stdlib readers validate initial registration, exact original
approval/evidence linkage, archived historical bytes, successful host snapshots,
and a bounded explicit revision chain (maximum 64 records). Every committed
attachment revision must occur in the selected ancestry: branches, omitted
successors, older-tip restoration, missing records, linked paths and cycles fail
closed. Current canonical source and metadata hashes must match the selected
commit. Build provenance adds `attachment_revision` only when explicitly selected.

Fresh native build/export and package proof remain independent requirements.
Synthetic transaction tests do not establish real asset quality or acceptance.

## Evidence resource bounds

The opt-in companion adds explicit history/evidence limits: 8 MiB per selected
artifact or attachment journal, 512 unique recursive geometry dependencies,
64 MiB of total bytes per historical geometry closure, 4,096 paired journals per
job inventory, and 64 committed records in the selected attachment chain.
Prospective chain capacity and recursive byte closure are checked before author
approval and again before apply. Streaming reads enforce byte limits before
JSON parsing. Legacy large SceneSpec/binding archives retain their prior read
behavior when their transaction is `0.1.0`; the fixed journal-envelope inventory
is bounded before scanning. These limits do not relax existing direct geometry,
triangle, embedded-solid, Float32 correspondence or root-predicate caps.
