# Exact delegated five-asset technical completion (0.1.0)

This optional host-issued companion records an expressly delegated assistant decision
without pretending it is a V0.7 user approval or an AQ policy authorization. It is
unavailable unless the caller explicitly opts in. It grants no arbitrary-code,
canonical-write, destination-write, human beauty, final-package acceptance, or
Activation authority. Existing `OptimizationApproval` stays **0.7.0** with
`approved_by: "user"`; its model, schema, history and serialization are unchanged.
The AQ 0.1/0.3 policy paths retain their existing bindings and are not borrowed.

## Exact scope and finite reserve

`DelegatedOptimizationScopeV01` snapshots two supplied UTF-8 artifacts byte-for-byte:
(1) the original user delegation and (2) the separate explicit confirmation of this
contract extension. Each has an exact supplied SHA-256. Callers must supply the real
conversation evidence; a model-generated summary or fixture text is not approval.
The host does not interpret arbitrary text as permission. The caller remains
responsible for having the user's explicit authorization before invoking issuance.

The scope contains exactly five distinct runtime-declared job IDs and immutable
primary-reference SHA-256 identities, a task-context ID, and an explicit timezone-aware
expiry no more than seven days after issuance. No task/job/reference identifiers are
hardcoded in reusable code. The host verifies the owning job's actual immutable input
through the existing contained input resolver. The other four entries are the declared
closed task boundary; each owning job verifies its own reference when used.

Each job's scope has at most three nonrefundable ordinal reservations. Each reservation
binds one exact run and one immutable grant hash. Lost or altered canonical claims are
checked against preserved run-owned grant/claim snapshots before further issuance.
Failed, interrupted or consumed grants are not reset or refunded. An ordinary technical
retry uses a fresh run/plan and a remaining ordinal. Exhaustion or expiry is a visible
stop; do not rename a scope to reset it. A task binding keyed independently by the two
exact source-text hashes pins the first scope, preventing renamed/reimported copies of
that same authorization from replenishing the reserve.

## Host flow and public parity

1. Stage unchanged source-text files inside the owning job, outside `input/`. Supply
   their exact paths and SHA-256 values, the five identities as `allowed_assets_json`,
   `task_context_id`, `expires_at`, and
   `extension_confirmation="explicit_user_confirmation"` to
   `asset-delegation-create` / `create_portable_asset_delegation`. Explicitly pass
   `enable_delegated_authority=true` (CLI `--enable-delegated-authority`). This publishes
   `optimization/delegations/<id>/scope.json` plus exact text snapshots. A scope alone
   does not authorize an unknown future artifact.
2. Run the ordinary profile, preflight and review-plan host path. Call
   `asset-plan-delegate` / `delegate_portable_asset_optimization` with the exact current
   run ID, review-plan SHA-256, scope path/SHA-256, a truthful delegated technical
   decision note, and opt-in. It validates the candidate SceneSpec bytes, built Blend,
   complete source fingerprint, immutable reference, profile, preflight and review;
   then reserves an ordinal and publishes `optimization_delegated_authorization.json`.
   The actor is `delegated_assistant`, not `user` or `policy_engine`.
3. Direct execution uses `asset-optimize` / `optimize_portable_asset` with the exact
   plan SHA-256, exact delegated grant path/SHA-256 and opt-in. No grant is discovered
   automatically. An immutable `optimization_delegated_consumption.json` is created
   with exclusive creation under the host job lock **before** Blender side effects.
   A failure retains the consumed receipt and cannot replay that grant.
4. A current Standard workflow can instead select the grant explicitly using
   `asset-delegation-bind-workflow` / `bind_portable_asset_delegation_workflow`. Supply
   its exact workflow-plan SHA-256, currently waiting optimization-gate input fingerprint,
   run ID, grant SHA-256 and opt-in. The additive binding snapshots the existing plan and
   request; it never edits or reclassifies them. Native reconciliation marks only the
   exact optimization gate as delegated; native optimize/package routing consumes the
   same grant under the verified workflow lock. Generic notes and final approval gates
   retain their existing meaning. AQ and `background_exterior` are not adapters for this
   companion. A workflow-bound grant cannot be consumed through an unrelated direct call.
5. Direct `asset-package` / `build_portable_package` requires the exact explicit run and
   delegated grant SHA-256. Only `portable_gltf` / GLB with `full_evidence` is supported.
   Lean `static_payload`, FBX and OBJ fail closed. Current source/profile/expiry are
   revalidated before new packaging; the ordinary material-conversion and clean-import
   gates remain required. A sealed `delegated_package_authority_manifest.json` records
   `final_human_acceptance=false` and `grants_execution_authority=false`.
6. `asset-delegation-validate-package` / `validate_portable_package_delegation` validates
   a copied/extracted full-evidence directory without any original workspace access.
   It verifies package receipts, internal grant/claim/scope/text/consumption bindings,
   exact reviewed/completed/execution-plan semantics and optional workflow snapshots.
   This is **authority-integrity validation only**; the result explicitly reports
   `clean_import_validated=false`. It does not create authority or claim a Blender import.
   Run and retain a separate actual supported-Blender clean import before claiming it.

These public MCP tools are separate from phase/controller allowlists; no controller or
arbitrary execution capabilities were added. Mutable canonical files and user inputs
are never written by the companion.

## History, audit and portable proof

New side effects require current source, profile, reference and unexpired scope.
Already consumed/read-only proofs instead validate recorded issuance/consumption
and publication timestamps against the scope and exact retained profile/quality
snapshots. Later legitimate source/profile revisions or expiry do not retroactively
invalidate completed history. Mutation of the immutable plan, review, scope, grant,
receipt or snapshots still fails closed. Audit and reports never mint or consume grants.

A full-evidence package contains the original text bytes, scope, grant, ordinal claim,
task binding, consumption, retained profile/quality evidence, and any explicitly bound
workflow snapshots. It remains a technical result pending the separate human decision.
Copying it preserves evidence, not execution eligibility. Ordinary host validation also
checks canonical authority; relocated integrity validation deliberately grants no
execution or final acceptance.

## Verification boundary

Blender-free tests cover legacy compatibility, exact public/schema parity, tampering,
stale active sources, immutable history after expiry/supersession, partial/mixed/dangling
proof, symlink/reparse containment, scope renaming, deleted/altered claim reserves,
concurrent single-use consumption, failure without refund, native Standard binding,
relocated proof and rehashed malformed execution evidence. These fixture tests never
approve a production asset and do not substitute for actual Blender/package gates.
