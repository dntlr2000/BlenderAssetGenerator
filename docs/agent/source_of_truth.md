# Source of truth and compatibility

## Evidence hierarchy

1. workspaces/<job>/input/ — immutable user evidence.
2. analysis/reference_analysis.json and analysis/camera_solution.json — deterministic diagnostics and camera assumptions.
3. analysis/modeling_plan.json — semantic decomposition, content scope, assembly and surface-detail policy.
4. architecture/interior_scope.json plus exact approval — optional interior boundary; absence means disabled.
5. analysis/scene_spec.json — canonical geometry, assignment, and camera contract.
6. analysis/masks/semantic_manifest.json plus registration receipt/history — optional QA mask evidence, never geometry authority.
7. analysis/material_plan.json, materials/, textures/ — approved material/shader/texture contracts.
8. constraints/constraints.json — measured requirements.
9. geometry/ — referenced deterministic geometry payloads.
10. qa/runs/ and qa/convergence/ — immutable exterior QA and optional bounded-convergence evidence.
11. qa/interior/runs/ — separate approval-bound interior QA.
12. asset_profiles/ — engine-neutral delivery policy.
13. optimization/runs/ — run-owned derived optimization evidence.
14. exports/packages/ — immutable portable packages and receipts.
15. workflows/ — immutable V0.8 orchestration evidence.
16. production/dispatches/ — immutable V0.9 dispatcher/controller evidence.
17. production/autonomy/ — opt-in AQ roots, candidates, authorizations, transitions, and terminals.
18. reference_evidence/ and reports/integrated_quality/ — AQ companions, not replacements for canonical QA/source contracts.
19. structural_migrations/ — explicit derived SceneSpec V03 plans/copies/receipts, never canonical.
20. production/material_identity_split/ — paired planning, shadow preapproval, specialized approval,
    guarded transaction and post-apply continuation evidence; never a substitute for canonical files.
21. reports/v09/ — privacy-safe probe and read-only audit evidence.
22. .cbm/queue/ — operational single-worker state, never canonical asset source.
23. blend files, renders, PDFs, bakes, and exports — derived artifacts, never the canonical fix.

For job_kind external_static_asset, intake/external_asset_manifest.json and its exact source, dependency, approval, normalization, validation, blend, material, and shader hashes replace the reference-analysis/SceneSpec branch. It never creates a placeholder SceneSpec.

## Version dispatch

Project is 0.9.0 and canonical SceneSpec is 0.2.0. Derived-only SceneSpec V03 is 0.3.0. Material Identity Split is an additive `0.1.0` companion and does not change either version. Existing V0.4–V0.9 and AQ/IQ 0.1 loaders retain their meaning. Companion contracts select strict loaders by exact schema_version and profile/session binding; absence is not automatic migration.

Relevant exact rules: CBM-INV-001..019, CBM-INV-025..035, CBM-INV-045..048, CBM-INV-059..066, CBM-INV-099, CBM-INV-107..112, CBM-INV-134, CBM-INV-145..150, CBM-INV-166, CBM-INV-174..192.
