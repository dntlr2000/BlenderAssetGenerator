# Operational workflow reference

This document preserves the detailed operational sections formerly embedded in the root AGENTS.md. The compact root instruction file requires agents to read the relevant section before acting. Stable CBM-INV rules in invariant_catalog.md take precedence if a summary here is ambiguous.

## v0.4 reference-analysis workflow

1. Inspect job metadata and all source hashes.
2. Run `analyze_reference` with `provider=auto`.
3. Review:
   - `analysis/reference_analysis.json`
   - `analysis/camera_solution.json`
   - `analysis/diagnostics/*_edges.png`
   - `analysis/masks/*_content.png`
4. Use diagnostics as evidence, not as ground truth. The basic provider measures image bounds, content bounds, edge density, symmetry, and dominant colors. The optional OpenCV provider adds line-angle diagnostics.
5. Populate `analysis/modeling_plan.json` with semantic objects and an explicit small surface-detail policy before SceneSpec authoring.
6. Separate observed and inferred geometry, record confidence, and route non-structural shallow marks to `surface_details` instead of individual meshes.

## Geometry strategy order

Choose the least complex recipe that preserves visible evidence:

1. `primitive`
2. `profile_extrude`
3. `revolve`
4. `curve`
5. `terrain`
6. `custom_mesh`

Use modifier stacks for mirror symmetry, bevel, subdivision, thickness, arrays, decimation, remeshing, and booleans.

## Measured-mode workflow

Use measured mode when explicit dimensions, orthographic views, or blueprints exist.

1. Add views with `add_view`; never recreate the job.
2. Initialize `constraints/constraints.json`.
3. Encode dimensions using semantic IDs and explicit tolerances.
4. Build and inspect the Blender scene.
5. Run `evaluate_constraints` against `reports/scene_inventory.json`.
6. Report requested value, actual value, residual, tolerance, missing targets, and under-constrained degrees of freedom.
7. A passing structural validation does not imply a passing dimensional constraint report.
8. v0.4 evaluates constraints but does not silently solve arbitrary CAD systems. Use residuals to produce a guarded RevisionPlan.

## Optional interior opt-in workflow

Interior generation is never part of the default exterior-building workflow. Use this workflow only after the user explicitly asks for an interior.

1. Keep the job exterior-only while `architecture/interior_scope.json` is absent; that absence is a valid `default_disabled` state and must not create files by itself.
2. Create a draft with `cbm interior-scope-init` or the whitelisted MCP tool `initialize_interior_scope`. Record the user's exact request, policy, allowed/excluded semantic prefixes, optional levels/spaces, furnishing boundary, and evidence status.
3. Show the scope and its SHA-256 to the user. The draft does not authorize any interior object.
4. Only after an explicit user decision, instruct the user to run `cbm interior-scope-approve` manually with the exact current scope hash and a non-empty approval note. The command requires typing the complete `APPROVE <sha256>` phrase interactively and is intentionally not exposed through MCP.
5. Author interior SceneSpec objects only inside the approved namespace. Use `.interior` IDs or explicit interior tags plus `level:<id>` and `space:<id>` locators when those lists are constrained.
6. Run `interior-scope-validate` before build. Job-local SceneSpec loading also enforces the boundary, so disabled, unapproved, stale, excluded, or out-of-scope interiors must fail closed.
7. Replacing a scope archives the previous scope and approval, invalidates the old hash-bound authorization, and requires a new explicit approval before further interior authoring.
8. Facade helpers that support an exterior view may remain exterior-only; do not relabel them as rooms or use them to imply a complete interior.

Supported policies are `visible_only`, `proxy`, `measured`, and `authored`; `disabled` is the safe default. An interior request authorizes only static geometry within its exact boundary, never hidden floors, unrequested rooms, furnishings, engine logic, or gameplay systems.

## Required build workflow

1. Verify job status and modeling capabilities.
2. Ensure reference analysis exists.
3. Author/update SceneSpec and geometry payloads.
4. Run `build_scene`.
5. Run `render_preview`.
6. Run `inspect_scene`.
7. Run `validate_scene`.
8. In measured mode, run `evaluate_constraints`.
9. Report changed IDs, assumptions, Blender version, selected engine, validation status, and remaining uncertainty.

## v0.5 material, texture, and shader workflow

1. Start only after geometry, semantic IDs, assignments, and comparison camera are approved.
2. Create `analysis/material_plan.json` and one whitelisted ShaderRecipe per stable material ID.
3. Record observed/inferred properties, mapping mode, real-world scale, texture strategy, export profiles, and bake requirements.
4. Keep Base Color in sRGB and all data channels in Non-Color space.
5. Generated textures must record provider, version/model, prompt, seed, channel hashes, and rights notes; never overwrite without an explicit flag.
6. Generate or preserve UV only when `mapping.mode=uv`; do not silently UV-project Object/Generated/triplanar materials.
7. Build from SceneSpec plus the optional material plan; absence of a plan must preserve the legacy SceneSpec appearance.
8. Run host contract validation, Blender material inspection, and fixed sphere/plane swatch renders.
9. Separate Blender master shaders from GLTF-safe baked outputs and future engine-adapter inputs. V0.6 writes separate portable channels; V0.7 may derive glTF ORM but does not claim Unity/Unreal packing.
10. Do not bake or replace approved material identities before swatch approval.
11. Rebuild after changing SceneSpec, external geometry/heightmap, MaterialPlan, ShaderRecipe, TextureManifest, or an image channel; stale scenes must be rejected before baking.
12. For each non-omitted ModelingPlan surface detail, require an authored UVMap image/hybrid TextureManifest with the exact detail ID and planned channels before material build.
13. For a new localized detail, build and inspect the UV-mapped parent first, bind the detail to the current ordered polygon-corner UV fingerprint and one bounded placement, then regenerate and rebuild. One local procedural generation request handles one exact spatial detail; author separate bounded outputs when multiple details need different placements.
14. Run `validate_material_fidelity` after contract validation and before swatch approval. Treat `failed` as a host-integrity failure, `warning` as review evidence, and `passed` only as passing the implemented deterministic checks.
15. `inspect_materials` must verify the applied Blender image-node extension, `UVMap -> identity Mapping -> Image Texture` topology, parent material assignment, material exclusivity, and current UV hash for spatial bindings.

## v0.6 visual QA and revision workflow

1. Freeze the input hashes, SceneSpec hash, camera fingerprint, resolution, renderer, and QA run ID.
2. Verify embedded build provenance and the actual Blender camera, then render exactly beauty, silhouette, object ID, material ID, normal, depth, and wireframe from that camera.
3. Compare the reference mask and observed semantic evidence directly before using beauty or generated-target evidence.
4. Persist request, pass manifest, report, and candidates under `qa/runs/<run-id>/`.
5. Stop at suggestions by default. `cbm.toml` uses `revision_mode = "suggest"` and one maximum iteration.
6. Compile only explicitly selected candidates. Executable candidates remain `approval_required`; custom-mesh payload edits and generated-target-only suggestions remain manual.
7. Never create approval implicitly. Apply only a matching single-use user approval.
8. Rebuild, re-render, re-inspect, re-validate, and reevaluate constraints after application.
9. Keep canonical replacement and every verification step inside the rollback boundary; restore and rebuild the archived baseline on non-improvement, per-ID constraint regression, or verification failure.
10. If an external QA target is used, preserve the exact prompt text and provider/model/version/seed/output provenance with the run.
11. A newly planned standard `revise_asset` defaults to isolated `candidate_review`: author and evaluate the bounded candidate first, then ask once for the exact promotion decision SHA-256. Use `manual_guarded` when the request falls outside that envelope. For repeated eligible standard revisions, the user may instead request one bounded convergence plan from a current direct QA run.
12. Show the target direct score, target silhouette IoU, allowed and locked semantic IDs, path/operation/delta rules, minimum gain, confidence threshold, per-iteration budgets, hard iteration limit, stop conditions, non-empty exact input-map status, host-safety-envelope path/SHA-256, and exact plan SHA-256. Planning must not modify canonical geometry.
13. Stop until the user approves that exact plan hash. After approval, host policy may select only eligible direct-reference candidates inside the immutable envelope and does not require another user approval for each accepted iteration.
14. Keep texture-routed surface details out of geometry candidates. Report their manifest coverage separately; route missing pixels to V0.5 and newly discovered silhouette/structural needs to V0.4.
14. Do not change global `qa.revision_mode`, enable `automatic_revision`, use a generated target as authority, or widen the envelope during a session. Any such need terminates for manual review.
15. Persist every iteration receipt and terminal machine report under `qa/convergence/<session-id>/`, generate its hash-bound PDF projection, and report whether both targets were reached or the exact reason the bounded session stopped. Process at most one full Blender iteration per host/MCP invocation and use the status response's execution flags and `next_action` to approve, continue, recover, or finalize.

## Optional multi-view interior QA workflow

Use this separate V0.6 path only when an approved InteriorScope already contains validated static interior geometry.

1. Validate that the current scope approval, SceneSpec, build fingerprint, and interior semantic IDs are current.
2. Inspect the authoring scene read-only and group interior targets by approved `level:` and `space:` locators.
3. Create a bounded `minimal`, `standard`, or `thorough` temporary-camera plan and show its exact SHA-256 to the user.
4. Stop until the user approves that exact plan hash and optional subset of existing view IDs.
5. Consume the approval once, render exactly seven passes per selected view, and leave the authoring `.blend` unchanged.
6. Report per-view and per-space semantic visibility, topology findings, advisory AABB overlaps, limitations, and manual-only candidates.
7. Generate beauty, object-ID, and wireframe contact sheets plus a hash-bound QA PDF for human review.
8. Do not invent an interior similarity score when no interior reference has been mapped. Add mapped-reference comparison only as a separately reviewed future contract.
9. A geometry correction still requires its own guarded authoring or revision approval; an interior QA plan approval authorizes rendering only.

## v0.7 portable static-asset workflow

1. Begin only after the canonical geometry, material identities, build provenance, validation, and any required V0.6 QA approval are complete.
2. Initialize one job-owned `AssetProfile 0.7.0`: `portable_gltf`, `fbx_interchange`, or `obj_legacy`.
3. Run read-only topology preflight against the canonical `.blend`. Record topology, transform, normal/tangent, material, UV, and budget findings without editing the source.
4. Stop when preflight has failed findings. Warnings must remain visible in the machine report and PDF; do not relabel them as passes.
5. Create one immutable draft `review_plan.json` bound to the exact source/profile/preflight hashes and generate `optimization_review.json` with exact LOD and collider settings, bounded estimates, limitations, and decision choices.
6. Show that review and plan SHA-256 to the user. Stop without optimization until the user chooses `approve`, `revise_asset`, `revise_profile`, or `cancel`.
7. On `revise_asset`, leave the reviewed run unapproved and create a new immutable standard revision workflow; after rebuild and QA, start a fresh V0.7 run. On `revise_profile`, explicitly update only delivery policy and start a fresh preflight/review run. On approval, persist one exact, hash-bound, single-use `optimization_approval.json`.
8. Execute only the approved run and consume its approval before Blender starts. Produce an optimized scene plus deterministic LOD, collision, UV, and `StaticAssetCostReport 0.7.0` manifests under `optimization/runs/<run-id>/`.
9. Apply only profile-authorized derived cleanup and semantic-safe consolidation. Preserve triangles, semantic/material traceability, and report every batch, cleanup action, advisory instance group, and overlap candidate.
10. Stop when a fail-enforced cost budget is exceeded. Warning-enforced budgets remain visible in JSON and PDF and must not be relabeled as passes.
11. Preserve stable semantic and material IDs across derived LOD/collision objects. Record any format loss explicitly.
12. Package raw PBR channels and any profile-required derived packing. `portable_gltf` may derive glTF ORM while preserving every available raw channel; FBX/OBJ use raw sidecars.
13. Build one immutable package atomically under `exports/packages/<profile-id>/<package-id>/`. Refuse overwrite and reject absolute or escaping paths.
14. Clean-import the primary package file into a fresh Blender process and produce `RoundTripValidation 0.7.0`.
15. Accept only when dependency checks pass, bounds remain within tolerance, and semantic/material coverage matches the profile's declared capabilities.
16. Generate the `export` PDF scope alongside—not instead of—the profile, review plan, review, approval, preflight, cost, optimization, package, and round-trip JSON evidence.
17. Defer engine-specific import settings, prefab/actor creation, material reconstruction, and runtime shader conversion until the destination engine is explicitly chosen.

## Human-readable PDF reporting workflow

1. Generate PDFs only from existing canonical JSON reports and approved render evidence.
2. Use one of five scopes:
   - `build`: inventory, validation, constraints, and build provenance
   - `material`: material contracts, runtime inspection, swatches, and bake readiness
   - `qa`: fixed-camera scores, seven render passes, findings, and revision candidates
   - `export`: asset profile, preflight, LOD/collision/UV, texture packing, package receipt, and round-trip validation
   - `full`: combined build, material, QA, and portable-export review
3. Generate reports with `cbm report-pdf` or the whitelisted MCP tool `generate_pdf_report`.
4. Store default outputs under:
   - `output/pdf/<job>/<scope>_report.pdf`
   - `output/pdf/<job>/<scope>_report.manifest.json`
5. Missing optional evidence must be shown as unavailable or as a warning; never fabricate a passing result.
6. PDF generation must not modify inputs, SceneSpec, material contracts, QA runs, approvals, or machine-readable reports.
7. A PDF is a presentation artifact. Revisions must still target stable semantic IDs and canonical machine contracts.

## Revision rules

- Parse the request into target IDs, exact paths, operations, exclusions, and acceptance criteria.
- For new standard `revise_asset` workflows, prefer workflow-owned `candidate_review` so plan, isolated build, exact QA, optional constraints, and comparison PDF are produced before the single canonical-promotion decision.
- Use `plan-revision` + `apply-revision` through explicit `manual_guarded` for redesign, camera, material, semantic-membership, custom-mesh, or other changes outside the candidate envelope.
- Preserve all values not reached by approved operations.
- Rebuild from SceneSpec; do not hand-edit the `.blend` as the fix.
- Re-render with the same comparison camera.
- Report machine-generated before/after values.
- Never treat an image-model QA target as recovered truth or sufficient authorization.

## Blender compatibility gate

Before testing a new Blender installation, run `blender_compatibility_probe` or `uv run cbm blender-compat`. A supported run must report the Blender version, accepted EEVEE enum, color-management look, Python exception propagation, and optional GLB/OBJ/FBX smoke exports. Do not mark a Blender version as verified unless the actual runtime pipeline passed.

## v0.8 short-request orchestration workflow

1. Normalize one short request into a `WorkflowRequest 0.8.0` without persisting absolute source paths.
2. Route exactly one intent: new asset, revision, measured view, interior scope, material authoring, Visual QA, or portable package. Reject ambiguous existing-job requests.
3. Resolve the destination separately. Unsupported Unity/Unreal/custom destinations stop at the engine-neutral portable-package boundary.
4. Persist immutable request, route, and step plan contracts under `workflows/<workflow-id>/`.
5. Execute only deterministic host steps. Generate the matching human-readable PDF projection before a generic review, then stop for agent-authored contracts, generic review, or specialized approval.
6. Bind every agent completion and generic approval to the exact plan and current input/output fingerprint.
7. Preserve InteriorScope, visual-revision, and optimization approvals as specialized contracts; orchestration cannot synthesize them. New standard revisions use one post-evaluation `candidate_review` promotion approval, while explicit `manual_guarded` keeps the legacy pre-application approval.
8. Reconcile after every step from current files and hashes. Mark changed evidence stale instead of treating it as completed.
9. Resume from the first incomplete step. Retry a failed host step only with explicit authorization and a new attempt receipt.
10. Cancellation preserves all evidence. Destination-specific reconstruction remains deferred until a validated adapter is selected and tested.
11. Keep `execution_policy=standard` unless the user explicitly chooses the background exterior fast lane before planning.
12. For `background_exterior`, resolve `delivery_scope` before creating the workflow: `preview_only` runs bounded pre-QA fit, one canonical direct QA, a machine quality report, and a combined review PDF; `portable_package` continues through V0.7 but still waits for the exact optimization-plan approval.
13. Skip generic review steps only by omitting them from the immutable fast-lane plan. Do not auto-create approval receipts or reinterpret a generic instruction as a specialized approval.
14. Keep fast-lane agent steps fail-closed. If the asset no longer meets the scope or safety eligibility boundary, report `requires_standard_workflow`, leave the current step incomplete, and propose a separate standard workflow. Visual similarity findings instead complete review delivery with an explicit quality outcome.

## v0.9 stabilization and release-candidate workflow

1. Run `stability-probe` to snapshot the detected host, project/contract versions, and the hash of existing Blender compatibility evidence without copying absolute paths.
2. Run `workspace-audit` against all jobs or one explicit job. Treat warnings and failures as evidence; do not repair or migrate during the audit. For bounded convergence, verify active current-state bindings and completed historical plan/approval/iteration/QA/PDF hash chains without rewriting them.
3. Generate `stability-report-pdf` only from the exact immutable probe and audit IDs. Keep its sidecar manifest and source hashes with the PDF.
4. Use the local queue only for already planned V0.8 workflows. Enqueue one active entry per job/workflow and keep `max_concurrency=1`.
5. Run one bounded queue dispatch. Stop normally at every agent-authored or approval boundary and preserve the V0.8 workflow state as authoritative.
6. Requeue a failed entry only after an explicit failed-step retry decision. Cancellation affects future queue dispatch only and does not cancel or delete the underlying workflow.
7. Run the V0.9 release gate from an isolated smoke workspace. Do not use a user job to make a failing gate appear green.
8. Record the exact verified environment and every unverified matrix cell. V0.9 is a release candidate, not proof of cross-platform or destination-engine parity.
9. For a new reference, Asset Production Dispatcher may prepare one new V0.8 workflow, immutable controller plan, allowlist-only client launch manifest, and controller prompt. Task creation remains a supporting-client action.
10. Bind a supporting-client task only after that client attests that it enforces the exact controller profile hash, including required client capabilities, the MCP allow/deny lists, and the approval/retry shell-command restriction.
11. Advance one controller action at a time. Run deterministic host work, issue read-only advisory assignments, stop at existing approvals or failures, and run the exact V0.9 postflight audit only after workflow completion.
12. Keep the V0.9 production controller distinct from the local queue. The queue dispatches existing workflows; it does not create production tasks, bind clients, or perform agent-authored steps.

## Material identity split workflow

1. Use this additive companion only when an exact plan splits a shared material identity without
   changing geometry, topology, transforms, parenting, dimensions, UV, reference, target or content
   scope.
2. Rehash current SceneSpec, ModelingPlan, Blend, strict MaterialPlan absence and all plan evidence.
3. Build paired candidate SceneSpec/ModelingPlan artifacts; permit only declared semantic-clone IDs,
   target-object assignments and matching detail target-material changes.
4. Run isolated Blender build, inspect and validate; publish invariant evidence and rehash canonical
   bytes before and after.
5. Publish only an ApprovalRequest and stop at `framework_ready_for_explicit_scope_approval`.
6. After a separate caller-authored explicit user decision, consume one approval into one ApplyIntent
   and replace SceneSpec/ModelingPlan/Blend together under the canonical host lock.
7. Commit, exact-rollback or stop `recovery_required`; allow at most one same-intent technical retry.
8. After commit, publish new canonical observations, MaterialPlan absence, snapshot and a
   non-synthetic geometry continuation. Rebuild downstream material closure and appearance approval
   from the new canonical state.

## Testing

- Dependencies: `uv sync --extra dev`
- Optional line analysis: `uv sync --extra dev --extra vision`
- Python: `uv run pytest`
- Static checks: `uv run ruff check .`
- Blender API probe: `uv run cbm blender-compat`
- Geometry demonstration: `uv run cbm import-example geometry_showcase`
- Build pipeline: build → render → inspect → validate → export
- V0.5/V0.6 integration: `scripts/run_v06_gates.ps1`
- V0.7 isolated portable-asset integration: `scripts/run_v07_gates.ps1`
- V0.8 orchestration and V0.7 regression: `scripts/run_v08_gates.ps1`
- V0.9 stabilization, V0.8 regression, and Blender compatibility: `scripts/run_v09_gates.ps1`
- External static intake: the V0.9 gate opt-in Blender smoke plus host tamper/audit tests
- Interior safety: `uv run cbm interior-scope-status <job>` and `uv run cbm interior-scope-validate <job>`
- Human-readable report: `uv run cbm report-pdf <job> --scope build|material|qa|export|full`
- PDF verification: validate PDF text/pages and sidecar hashes, then render representative pages for visual inspection
- V0.9 evidence: `uv run cbm stability-probe`, `uv run cbm workspace-audit`, and `uv run cbm stability-report-pdf`
- V0.9 production dispatch/controller: `uv run pytest tests/test_v09_production_dispatch.py`

## File ownership

- `input/`: immutable user evidence
- `intake/`: immutable external-static source, plan, exact approval, manifest, normalization receipt, and validation evidence; only for `job_kind=external_static_asset`
- `analysis/`: diagnostics, camera assumptions, modeling plan, canonical SceneSpec, material plan, and hash-promoted semantic reference-mask evidence
- `constraints/`: measured requirements
- `history/`: prior SceneSpecs and explicitly replaced input views
- `geometry/`: deterministic mesh/curve/height payloads
- `architecture/`: optional InteriorScope and exact hash-bound user approval; absent means interiors are disabled
- `materials/`: shader recipes and material-owned contracts
- `textures/`: authored or generated texture manifests and maps
- `qa/`: immutable exterior QA runs plus approval-bound `qa/interior/runs/` evidence, approvals, convergence, and rollback reports
- `asset_profiles/`: job-owned engine-neutral portable-delivery policy
- `optimization/`: immutable V0.7 preflight, plans, optimized scenes, LOD, collision, and UV evidence
- `optimized/`: optional derived convenience outputs; never canonical authoring inputs
- `exports/packages/`: immutable profile/package directories and machine-readable receipts
- `blender/`, `renders/`, `reports/`, `bakes/`, and non-package exports: derived artifacts
- `output/pdf/`: derived user-facing PDF reports and provenance manifests; never canonical inputs
- `workflows/`: immutable orchestration contracts, attempts, approvals, and derived state; never a replacement for canonical stage contracts
- `production/dispatches/`: immutable dispatcher, client-launch, task-binding, advisory assignment, controller-transition, and postflight-audit evidence; never a source of approval authority
- `reports/v09/`: repository-owned environment probes and read-only workspace audits with relative paths only
- `.cbm/queue/`: operational single-worker queue, locks, leases, and immutable dispatch receipts; never canonical asset data
- `output/pdf/v09/`: derived V0.9 stability PDFs and exact source-hash sidecars
