# Explicit paired Standard revision

An existing asset can select a paired SceneSpec/ModelingPlan revision through
`plan_workflow`, CLI `workflow-plan`, or MCP `plan_short_workflow`. This is an
additive opt-in on `execution_policy=standard`, `intent=revise_asset`, and
`revision_strategy=manual_guarded`. Ordinary revisions and historical requests keep
their existing meaning; omitted paired fields are not serialized.

Prepare a new candidate ModelingPlan in a contained job-relative `analysis/` path, for example
`analysis/candidates/revision_modeling_plan.json`, then pass that exact path and the
SHA-256 of its bytes:

```text
cbm workflow-plan --job-id example_asset --intent revise_asset \
  --revision-strategy manual_guarded --request "Apply the bounded paired revision" \
  --paired-modeling-plan-path analysis/candidates/revision_modeling_plan.json \
  --paired-modeling-plan-sha256 <exact-candidate-sha256>
```

Both parameters are required together. Planning checks the existing candidate and
hash before publishing workflow evidence. The candidate is immutable after binding;
do not use the canonical ModelingPlan as the candidate or edit the candidate in place.
All revision steps retain the same pair. `revision.author` declares the candidate as
`revision.candidate_modeling_plan` with `immutable_run` lifecycle. It also freezes the
exact candidate SceneSpec and geometry dependency binding. The author never promotes
canonical ModelingPlan bytes.

The normal exact `revision.approval` boundary authorizes the paired binding. It does
not create a second approval type or infer authority from the planning request.
`revision.apply` archives the source pair and promotes the approved pair through the
guarded host transaction. Its `revision.modeling_plan` artifact uses
`workflow_snapshot` lifecycle, with source `analysis/modeling_plan.json` and an
immutable snapshot under `workflows/<workflow-id>/artifacts/s/`. The existing source
ModelingPlan hash remains the plan's pre-apply contract; pending build and review
steps check the exact promoted candidate after apply.

The paired path preserves existing scope, policy, semantic membership, required
assembly relations, references, and all other bounded transaction invariants. A
candidate that needs a broader change fails closed. Neither candidate review,
background workflows, inferred `auto` intent, missing jobs, incomplete pairs, stale
hashes, links, escaped paths, nor an interrupted transaction gain authority from these
options.

An interrupted paired transaction can use the exact immutable intent SHA-256 for
rollback, or finalization of an already committed pair:

```text
cbm workflow-recover-paired-revision example_asset <workflow-id> \
  --intent-sha256 <exact-transaction-intent-sha256>
```

MCP `recover_paired_workflow_revision` accepts `job_id`, `workflow_id`, and
`intent_sha256` and returns the immutable rollback or finalization receipt. An uncommitted pair is
restored only from exact archives. If canonical commit succeeded but the workflow
receipt was interrupted, recovery validates the committed pair and finishes only
its derived report/snapshots/host receipt, without writing the canonical pair again.
Recovery consumes the transaction once, retains all evidence, and never reapplies it. A new revision
workflow and exact approval are required for a later apply.

These are workflow and transaction contracts. Unit tests do not establish Blender
render quality, reference fidelity, material quality, or human acceptance.

The additive `0.1.0` companion contracts have generated schemas for
`PairedModelingPlanBinding`, `PairedTransactionIntent`, `PairedCommitReceipt`, and
`PairedRollbackReceipt`. The binding records a field-by-field normalized diff and
exact original/candidate byte hashes. Observation files, job metadata, all immutable
inputs, and the recursive geometry closure remain hash-bound. Existing required
relations remain unchanged; new relations and detail declarations are appended.

Partial transactions block ordinary canonical loading, build provenance and
canonical SceneSpec replacement until explicit recovery. Committed history retains
its original input fingerprint after subsequent legitimate work; pending descendants
still require the exact committed pair, observation sources and geometry closure.

The successful `revision.apply` host receipt also fingerprints the immutable
`revision.paired_transaction` receipt. Before host finalization, a committed journal
still requires its exact live pair; it cannot make a mixed source/candidate state
readable. Receipt byte tampering remains a conflict after workflow completion.

If a technical interruption occurs before the immutable intent is published, neither
canonical file nor approval consumption changes. The existing explicit
`resume_workflow(..., retry_failed=True)` path may retry the same exact approved
candidate; its failed attempt remains in history. Once intent exists, ordinary retry
cannot replay promotion and the exact recovery boundary applies instead.

Blender build provenance uses the standard-library-only
`paired_revision_runtime` reader. It validates the same existing intent, original
author/approval fingerprints, exact host receipt inventory and snapshots, and
unfinalized current-pair hashes without importing orchestration or Pydantic into
Blender. Its schema reader accepts only the fixed generated reader contracts and
local fragment references; unknown validation rules fail closed. Host authoring,
apply, recovery, authority and serialization remain unchanged.

## Read-only historical observation locators

A preserved ModelingPlan may contain the historical locator
`workspaces/<same-job-id>/analysis/reference_analysis.json` or its uniform Windows
backslash spelling; the corresponding camera filename is `camera_solution.json`.
The paired evidence reader resolves only those two exact same-job aliases to ordinary
job-local analysis files when the historical literal has no competing file. A valid
existing POSIX-relative locator retains its original literal meaning. Foreign aliases,
mixed separators, traversal, drive/UNC roots, competing Windows aliases and linked
ancestors remain ineligible. Generic candidate/dependency path validation is unchanged.

The original ModelingPlan bytes and locator strings remain frozen in the paired binding.
Only the new `preserved_sources` hash map uses the resolved normalized job-relative key,
as its existing schema requires. Validation resolves the same source again and rejects
any changed bytes. No canonical file, prior receipt, schema version, source observation,
transaction authority or historical acceptance is migrated or rewritten by this reader.

## Optional solid-root intent revision

The [guarded solid-root companion](guarded_solid_root_attachment_revision.md) adds
an explicit exact intent path/hash and a versioned three-file transaction for
previously registered built jobs. Initial registration remains immutable; absent
opt-in keeps the two-file behavior above.
