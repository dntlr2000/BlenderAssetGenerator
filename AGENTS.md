# Codex Blender Modeler v0.9.0 — Repository Instructions

## Local collaboration rules

1. Every method added or changed by Codex must include a brief functional description as a comment or docstring.
2. When rollback is requested, Codex owns source rollback. Harmless logs and intermediate artifacts remain unless they cause a real problem; explain the exact file, reason, impact, and requested permission before deleting or changing them.
3. For every feature addition or modification, review compatibility with related code paths.
4. Do not use a project skill unless the user explicitly asks for that skill.

## Mission

Turn reference images, orthographic views, dimensions, and user feedback into reproducible Blender assets. The user should be able to attach an image and give a short request. Internal analysis artifacts, SceneSpec, geometry payloads, constraints, Blender files, renders, and reports provide the detailed workflow behind that short request.

## Source of truth hierarchy

1. `workspaces/<job>/input/` — immutable user evidence.
2. `analysis/reference_analysis.json` and `analysis/camera_solution.json` — deterministic diagnostics and camera assumptions.
3. `analysis/modeling_plan.json` — semantic decomposition plan.
4. `architecture/interior_scope.json` and its hash-bound approval — optional user-authorized interior boundary; absence means interiors are disabled.
5. `analysis/scene_spec.json` — canonical geometry, assignment, and camera design contract.
6. `analysis/masks/semantic_manifest.json` plus its exact registration receipt/history — optional explicit per-semantic reference-mask evidence for V0.6 diagnostics; never geometry or revision authority.
7. `analysis/material_plan.json`, `materials/`, and `textures/` — approved material, shader, and texture contracts.
8. `constraints/constraints.json` — measured requirements.
9. `geometry/` — referenced deterministic geometry payloads.
10. `qa/runs/<run-id>/` — immutable exterior fixed-camera QA evidence and revision candidates. Optional `qa/convergence/<session-id>/` evidence contains exact-plan-approved standard-only bounded convergence sessions and never grants fast-lane or V0.7 authority.
11. `qa/interior/runs/<run-id>/` — immutable, approval-bound multi-view interior QA evidence; never a replacement for exterior reference QA.
12. `asset_profiles/<profile-id>.json` — engine-neutral static-asset delivery policy.
13. `optimization/runs/<run-id>/` — immutable preflight, cost, consolidation, LOD, collision, UV, and optimized-scene evidence.
14. `exports/packages/<profile-id>/<package-id>/` — immutable portable packages and receipts.
15. `workflows/<workflow-id>/` — immutable V0.8 requests, routes, plans, exact approvals, agent completion markers, attempts, and reconstructed state.
16. `reports/v09/` — immutable privacy-safe environment probes and read-only workspace audit evidence.
17. `.cbm/queue/` — operational V0.9 single-worker queue state and immutable attempt receipts; never a canonical asset source.
18. `.blend`, renders, reports, bakes, and exports — derived artifacts; never edit them as the canonical fix.

The project version is `0.9.0`. The geometry SceneSpec contract remains `0.2.0` so existing v0.2 workspaces can be reused without rewriting approved geometry. Optional InteriorScope contracts use `0.1.0`, material contracts remain `0.5.0`, QA contracts remain `0.6.0`, portable static-asset contracts use `0.7.0`, orchestration contracts use `0.8.0`, and stabilization evidence uses `0.9.0`.

## Default behavior for short requests

When the user attaches a new reference and says something like “이 이미지로 3D 모델 만들어줘”:

1. Create a new unique lowercase `job_id`; never reuse an existing job for a different asset.
2. Default to `concept` mode unless orthographic drawings, blueprints, or explicit dimensions are present.
3. Run `analyze_reference` before authoring SceneSpec.
4. Read the generated reference analysis and camera solution.
5. Create a semantic modeling plan, then a proxy SceneSpec.
6. Build → render → inspect → validate.
7. Stop at proxy approval unless the user explicitly asks for detail, textures, or export.
8. Treat hidden sides as `inferred`; never present them as recovered truth.
9. Do not create rooms, corridors, stairs, ceilings, furnishings, or any other interior geometry unless the user explicitly requests an interior and approves the exact InteriorScope hash.

For a revision of the current asset, keep the same job ID and use the guarded revision flow. Do not call `create_job` again.

## Non-negotiable invariants

1. Never modify source files under `workspaces/*/input/`.
2. Never claim absolute dimensional accuracy from one uncalibrated perspective image.
3. Use meters, a right-handed coordinate system, +Z up, and -Y camera-forward.
4. Every modeled entity must have a stable semantic ID; preserve it across revisions.
5. Archive the previous SceneSpec before replacement.
6. Make the smallest change satisfying a revision request.
7. Prefer deterministic recipes, constraints, arrays, curves, booleans, and modifiers over hand edits.
8. Validate silhouette and proportions before detail or textures.
9. Use whitelisted MCP tools; do not expose arbitrary Blender Python execution.
10. Store large vertex arrays under `geometry/`, not inline in SceneSpec.
11. New jobs must use lowercase IDs matching `[a-z0-9][a-z0-9_-]{0,63}`.
12. `floating_island`, `geometry_showcase`, `measured_box`, and `first_reference_test` are reserved example IDs.
13. Never overwrite a job or view implicitly. Replacing an auxiliary view requires explicit approval.
14. Blender subprocesses must use `--python-exit-code 1` and `stdin=DEVNULL` so MCP stdio is isolated.
15. Blender render engine selection must be feature-probed: `BLENDER_EEVEE`, then `BLENDER_EEVEE_NEXT`.
16. SceneSpec `0.2.0` remains the geometry contract; V0.5 material and V0.6 QA data use separate versioned contracts.
17. Shader graphs must be produced from whitelisted recipes; never expose arbitrary Blender Python or arbitrary node execution.
18. Direct reference evidence and measured constraints outrank beauty-render or generated-image judgments.
19. Generated QA targets are advisory, cached with provenance, and can never independently authorize a revision.
20. The default manual Visual QA revision path requires exact candidate selection and a hash-bound, single-use user approval before application. An optional standard-only bounded convergence session may replace per-iteration user candidate approvals only after the user approves the exact immutable convergence-plan SHA-256; host selection remains limited to the approved semantic IDs, path families, operations, deltas, confidence threshold, iteration budgets, fixed camera, and direct-reference evidence.
21. A manual visual revision is accepted only when fixed-camera direct score improves and measured constraints do not regress. Every automatic convergence iteration must also reach the approved minimum direct-score gain, preserve or improve silhouette IoU, and preserve measured constraints; otherwise restore the archived SceneSpec and rebuild.
22. QA and baking require a fresh `.blend` whose embedded build fingerprint matches the current SceneSpec, external geometry payloads, material contracts, and texture channels.
23. Fixed-camera QA must validate the actual Blender camera and contain exactly seven pass kinds: beauty, silhouette, object ID, material ID, normal, depth, and wireframe.
24. Revision rollback protection begins before canonical SceneSpec replacement; compare measured regressions by stable constraint ID, status, tolerance, and residual-to-tolerance ratio.
25. Machine-readable JSON contracts and reports remain authoritative. Generated PDFs are derived human-readable summaries and must never be parsed back into SceneSpec, material, QA, approval, or revision decisions.
26. Every PDF report must have a sidecar manifest containing its PDF SHA-256, source fingerprint, job-relative source paths, and individual source hashes. Do not expose absolute source paths or secrets inside the PDF appendix.
27. When handing a material inspection, Visual QA, or combined review to the user, generate the matching PDF scope and link it alongside—not instead of—the canonical JSON evidence.
28. V0.7 never mutates the canonical authoring `.blend`, SceneSpec, geometry payloads, material contracts, or source textures; optimization operates only in a run-owned derived directory.
29. Every portable-asset run is bound to the exact source fingerprint, embedded build fingerprint, asset profile, and run ID. Reject stale or changed inputs instead of silently rebuilding from a different source.
30. Asset profiles are engine-neutral. Do not claim Unity, Unreal, or another runtime's import parity until that target and adapter are explicitly selected and tested.
31. Preserve raw PBR channels in every package. Packed textures are derived outputs with explicit channel mappings; glTF ORM means `R=occlusion`, `G=roughness`, and `B=metallic`.
32. LODs, colliders, UV1, packed textures, and export scenes are derived artifacts. Stable semantic IDs and material IDs must remain traceable to the canonical source.
33. Portable-package completion requires an immutable package manifest with relative paths, file hashes, no missing dependencies, and no absolute paths.
34. A package is not accepted until a clean-import round trip verifies format, imported bounds tolerance, semantic/material identity coverage, and dependencies. Axis/unit handling is evidenced by export-operator declarations plus imported-bounds checks; file metadata remains unverified unless a separate inspector confirms it.
35. V0.7 supports static assets only. Never imply rig, skinning, animation, engine prefab, engine material graph, or runtime shader support.
36. Interior authoring is opt-in. If `architecture/interior_scope.json` is absent, the effective policy is `disabled` and every explicit interior object must be rejected.
37. An enabled InteriorScope is only a draft until `architecture/interior_scope.approval.json` matches its exact SHA-256. Approval is manual interactive CLI only; Codex must never infer or self-record approval from a general modeling request.
38. Interior objects must use honest semantic IDs/tags and stay within approved prefixes, levels, spaces, furnishing policy, and evidence status. The validator normalizes case and treats common room namespaces such as `.room`, `.corridor`, `.hallway`, and `.lobby` as interiors even when `.interior` is omitted.
39. Exterior-only facade helpers such as window backing, door reveals, recesses, and exterior wall thickness are allowed without an InteriorScope when they are not tagged or named as interiors.
40. V0.7.4 interior support is static geometry only. Interactive doors, navigation, gameplay volumes, engine-specific room systems, light baking, and runtime interior shaders remain deferred.
41. Derived batching may join only objects with the same stable semantic ID, material-ID sequence, LOD level, UV-layer signature, and optional spatial cell. Never batch across semantic families.
42. Derived cleanup may remove loose geometry, duplicate material slots, and exact duplicate colliders only. AABB overlap findings, internal faces, coplanar faces, and repeated-mesh instance groups are advisory until a stronger verifier or destination adapter exists.
43. `asset_cost_report.json` is the authoritative V0.7.4 cost and cleanup record. Estimated draw calls are material-slot proxies, never measured destination-runtime draw calls.
44. Consolidation must preserve total triangles and per-source LOD budgets. Cost-budget enforcement may warn or fail the derived run, but must never rewrite canonical authoring data.
45. V0.8 routes short requests deterministically. Ambiguous existing-job requests must fail closed and require an explicit intent instead of guessing.
46. A new primary reference always creates a unique job. An existing job may never start `new_asset`, even with the same primary-reference hash; use `revise_asset`. Different primary references are rejected, and auxiliary views use the staged `add_view` workflow.
47. Workflow request, route, and plan files are immutable. State is reconstructed from exact current artifact hashes, completion markers, specialized approvals, and attempt receipts.
48. Agent-authored steps require an exact input/output-bound completion marker. A changed dependency or output makes that marker stale.
49. Generic workflow approvals never replace InteriorScope, V0.6 revision, or V0.7 optimization approvals. Every specialized approval remains exact-hash, single-purpose, and fail-closed.
50. Deterministic host failures do not retry automatically. Retry only the current failed step after an explicit `--retry-failed` request; preserve every prior attempt receipt.
51. An expired workflow lock may be archived and recovered, but a live lock must reject concurrent writers. Any abandoned running attempt is finalized as interrupted before a fresh attempt starts.
52. Cancellation stops future workflow execution without deleting canonical or derived evidence. A cancelled workflow cannot be resumed.
53. Unity, Unreal, and custom destinations remain unsupported until a validated adapter exists. V0.8 may fall back to the V0.7 engine-neutral package boundary but must report that boundary explicitly.
54. Budget fields bound host steps, QA iterations, texture resolution, triangles, and external-provider calls. Exhaustion must stop or wait; it must never silently expand scope.
55. Before optimization, generate `review_plan.json` and `optimization_review.json` and show the user the exact LOD, collider, consolidation, and known-unverified settings. Planning must not create optimized meshes, LODs, colliders, UVs, packages, or exports.
56. V0.7 optimization requires a matching `optimization_approval.json` bound to the exact review-plan SHA-256. Approval is explicit and single-use; calling `asset-optimize` alone never implies approval.
57. If the profile, preflight report, source fingerprint, review, or plan changes after review, reject approval or execution and start a new optimization run. Never silently carry approval forward.
58. Present `approve`, `revise_asset`, `revise_profile`, and `cancel` as the pre-optimization choices. Use `revise_asset` for geometry, silhouette, proportion, or semantic corrections through a new immutable standard workflow; use `revise_profile` only for LOD, collider, consolidation, UV, texture, or budget policy changes. Either revision path requires a fresh preflight and review before asking again.
59. V0.9 workspace audits are bounded and read-only. They may detect compatibility, tampering, dangling receipts, path escapes, and interrupted state, but must never repair, migrate, delete, or rewrite canonical evidence.
60. Environment probes report detected facts and existing compatibility evidence only. Detection never implies support for an untested operating system, Blender version, Python runtime, destination engine, or adapter.
61. V0.9 reports persist repository-relative paths only. Absolute host paths, secrets, and raw external source locations must not enter machine reports or PDF appendices.
62. The local workflow queue accepts existing V0.8 workflows only, uses one writer and one execution lease, and never creates jobs, writes agent-authored contracts, synthesizes approvals, or bypasses specialized gates.
63. Queue dispatch is single-worker and bounded. It stops at agent, generic review, specialized approval, cancellation, budget, or failure boundaries and records one immutable receipt per attempt.
64. Failed workflow steps are never retried automatically. A queue re-dispatch requires an explicit single-use failed-retry token and must still obey the V0.8 attempt contract.
65. V0.9 does not auto-migrate legacy jobs. A compatible legacy contract remains readable; an incompatible contract is reported and requires a separately reviewed migration or rebuild plan.
66. A V0.9 stability PDF is a derived projection of exact environment-probe and workspace-audit JSON hashes. It cannot change a release status or replace machine-readable evidence.
67. Interior QA is a separate optional V0.6 evidence path. It requires a current approved InteriorScope and at least one validated interior semantic object; exterior-only jobs must remain unchanged.
68. Before interior QA rendering, generate an exact camera plan and stop for an approval bound to its SHA-256. The approval is single-use and may select only views already present in that exact plan.
69. Every approved interior QA view must render the exact seven-pass set. Use temporary cameras and temporary visibility isolation only; never save those changes back to the authoring `.blend`.
70. Interior semantic visibility is an evidence-coverage ratio, not a completeness or quality percentage. Without explicitly mapped interior references, report reference comparison as unavailable and keep all generated candidates manual-only.
71. Interior QA contact sheets and PDFs are derived review aids. The plan, approval, source inventory, render manifest, report, candidates, latest pointer, and their hashes remain authoritative.
72. V0.8 `standard` remains the default execution policy. `background_exterior` is an explicit opt-in policy for new, unmeasured, static, exterior concept assets and for package-only continuation of an eligible existing exterior job.
73. Select `preview_only` or `portable_package` when planning `background_exterior`. The immutable workflow request, route, plan, and reconstructed state must all preserve the exact selected policy and delivery scope.
74. `background_exterior` may omit only generic proxy, detail, material-swatch, QA-review, and final-package acknowledgements. It never bypasses InteriorScope, interior-QA camera-plan, guarded visual-revision, measured-view replacement, V0.7 optimization-plan, or destination-handoff approvals.
75. A background fast-lane geometry pass authors one bounded moderate-detail SceneSpec once. It must not chain proxy and detail replacements of the same canonical SceneSpec or claim that micro-detail, hidden structure, or runtime behavior was recovered.
76. Background materials are limited to whitelisted node-procedural recipes or local deterministic `cbm_pillow_procedural` maps at no more than 512 px. External providers, generated QA targets, and automatic V0.6 revisions are disabled.
77. Background Visual QA runs exactly one canonical direct-reference seven-pass comparison in suggest-only mode. Its score is evidence, not a completion percentage, and its candidates are never applied implicitly. High-severity visual findings classify review quality as `needs_revision`; they do not by themselves block a structurally successful `preview_only` delivery.
78. `background_exterior + portable_package` must still stop at the exact V0.7 optimization-plan SHA-256 approval. Package creation and clean-import round trip remain mandatory, while the omitted generic final acknowledgement does not certify destination-runtime parity.
79. If an agent discovers measured requirements, interiors, rigging, animation, gameplay, engine-specific work, unsafe ambiguity, or another excluded condition, stop with `requires_standard_workflow` and do not record that agent step as complete. Create a new immutable `standard` workflow after user review; never mutate the existing fast plan into standard mode.
80. A completed background preview may be continued to a portable package only through a separate immutable workflow on the same job. Bind that continuation to the exact preview workflow, plan SHA-256, terminal completion fingerprint, QA run, canonical-source fingerprint, and embedded build fingerprint; reverify them before V0.7 starts. Never rewrite the completed preview workflow or treat a combined PDF as a specialized approval.
81. `requires_standard_workflow` is a non-retryable blocked outcome reserved for actual scope or safety boundaries such as interiors, measured/constraint work, rigging, animation, gameplay, engine-specific requests, unsafe ambiguity, or canonical changes forbidden by the fast policy. Preserve its machine report and create a new immutable `standard` workflow after review; never use it merely because visual similarity is poor.
82. New V0.8 plans must separate workflow-owned agent candidates from canonical promotion. Material scaffold and authored candidates live under `workflows/<workflow-id>/artifacts/m/`; only a strict host promotion may replace `analysis/material_plan.json`, archive the previous canonical file, and write an immutable promotion receipt.
83. Agent completion markers bind to the exact workflow-owned candidate hash. A valid downstream canonical promotion must not retroactively stale the scaffold or authored completion marker.
84. Shared derived paths such as `blender/scene.blend`, `renders/preview.png`, inventory, validation, and report outputs require immutable workflow snapshots or run receipts containing their exact execution-time SHA-256. Expected downstream supersession preserves the earlier receipt; an unplanned source change remains fail-closed.
85. A fast workflow binds QA completion to its exact planned `qa/runs/<run-id>/` evidence. `qa/latest.json` is only a convenience pointer and can never determine historical workflow freshness.
86. Workflow PDFs and sidecars use workflow-owned paths. A later report for the same job must not make an earlier completion stale; machine-readable JSON remains authoritative.
87. Distinguish `orchestration_artifact_conflict` from `requires_standard_workflow`. The former is an unexpected ownership, source, candidate, snapshot, receipt, or fingerprint conflict and never justifies an automatic standard conversion; the latter is reserved for actual scope or safety risk.
88. Existing immutable blocked workflows are historical evidence. Lifecycle fixes apply only to newly planned workflows and never resume, retry, complete, or rewrite an older blocked plan.
89. Users may request V0.8 planning and execution through Codex/MCP without running PowerShell. This convenience never weakens agent completion, specialized approval, or tamper-detection rules.
90. New background fast plans use `fast_quality_policy=review_delivery_v2`. Workflow completion and quality acceptance are separate: a successful `preview_only` run ends at `completed` / `delivered_for_review`, while `quality_status` is independently `passed`, `needs_revision`, or `unscorable`.
91. Before material authoring and final V0.6 QA, run at most two workflow-owned low-resolution pre-QA fit refinements. Fit may adjust only the bounded comparison camera and other explicitly whitelisted parametric paths, selects only a measured improvement, records every candidate and receipt hash, and promotes the selected SceneSpec at most once.
92. Pre-QA fit is initial authoring refinement, not a V0.6 QA run. It cannot add or delete semantic IDs, edit custom-mesh vertices, create interiors, change material IDs, call external providers, generate QA targets, or perform post-QA revision.
93. Background QA role classification is workflow-owned and backward-compatible. Prefer explicit `qa_role:primary|supporting|decorative|ground_background` tags, then deterministic semantic and parent fallbacks. Ground/background pixels must not contribute to the primary silhouette score.
94. Primary high findings require `quality_status=needs_revision` and a standard-workflow recommendation; supporting highs remain important; decorative highs are warnings; ground/background findings are separate environment evidence. Unreliable primary evidence yields `unscorable`, never an invented pass.
95. Every completed background preview writes an exact hash-bound machine quality report plus QA and combined PDFs whose first page exposes any non-passing quality. PDFs remain derived projections and can never replace the JSON evidence.
96. A `needs_revision` or `unscorable` background preview may continue to V0.7 review. The exact optimization review must carry its quality status, primary findings, decorative warnings, limitations, and standard-workflow recommendation. A `needs_revision` review recommends `revise_asset` without auto-switching, auto-cancelling, or auto-approving any workflow; only the user’s exact V0.7 plan-hash approval may authorize packaging.
97. Reference content scope is independent of V0.8 execution policy. New jobs default to `full_reference`; `primary_object_only` requires an explicit target subject and permits only the primary subject plus structurally attached or necessary supporting parts.
98. In `primary_object_only`, independent terrain, ground, vegetation, rocks, props, backdrops, and atmospheric context are excluded even if visible in the source image. Every SceneSpec object must carry an explicit primary/supporting QA role, and contextual roles must fail closed before build.
99. Reference content scope and target subject are immutable job evidence. Changing either means creating a new job; it must never be silently converted during revision, fast-lane continuation, QA, or packaging.
100. Object-only V0.6 comparison must derive its reference mask from observed primary/supporting evidence rather than the full reference foreground. Ambiguous targets or missing observed subject evidence are unscorable or require clarification, never a fabricated full-scene score.
101. Standard suggest/one-shot revision remains the default. Bounded visual convergence is explicit opt-in, standard-only, and unavailable inside `background_exterior`; the fast lane still performs exactly one canonical direct QA and never applies a post-QA revision automatically.
102. One exact convergence-plan approval authorizes only that session, with three iterations by default and a hard maximum of five. It is never an unbounded “until perfect” approval and never authorizes a path, target, operation, delta, or budget omitted from the exact plan.
103. Convergence locks the comparison camera and material identities. Generated-target-only evidence, custom-mesh geometry edits, manual-required candidates, interiors, material edits, and arbitrary code execution remain outside the automatic envelope.
104. Every convergence iteration must write an exact candidate selection, compiled RevisionPlan, host-policy execution authorization, result SceneSpec snapshot, result QA/candidate hashes, and an immutable hash-chained receipt. A live job write lock must prevent concurrent manual revision, convergence, or workflow writers.
105. A convergence session stops on target reached, plateau, no eligible candidates, manual-only work, iteration budget, constraint regression, cancellation, stale/tampered evidence, or host failure. Non-improving or regressing iterations roll back instead of consuming further authority.
106. Convergence plan approval never replaces InteriorScope, interior-QA camera-plan, V0.7 optimization, Destination Handoff, generic workflow, or any other specialized approval. It does not authorize package creation or engine-specific work.
107. V0.9 audit treats active convergence sessions as current-state evidence and completed sessions as historical immutable evidence. Later canonical work or added auxiliary inputs may supersede a completed session without invalidating its intact original input map and receipt chain; changing an original input or immutable session artifact remains invalid.
108. Every newly executable convergence plan binds a non-empty exact `initial_input_hashes` map, the initial SceneSpec, QA report and candidates, build fingerprint and provenance, the host-safety-envelope hash, and the optional measured-constraint snapshot. Legacy partial plans that lack any of these bindings are status/audit-only and must never be approved, resumed, repaired, or rewritten in place.
109. Convergence receipts bind source/result QA, candidates, build provenance, base/result SceneSpec snapshots, and exact before/after constraint evidence. Recompute score gain, silhouette non-regression, constraint regressions, and source-to-result build-contract continuity instead of trusting receipt summary fields.
110. Convergence never edits InteriorScope-classified objects or material identities. The strict `visual_convergence_host_safety_envelope.schema.json` contract is hash-bound into the plan and approval, and approval-time and run-time host policy must be re-derived from immutable source evidence. Public CLI/MCP path limits may only narrow that host envelope; editing a plan cannot broaden allowed IDs, custom-mesh eligibility, path/operation/delta limits, or material permissions.
111. Process at most one full Blender convergence iteration per host/MCP invocation. Long-running work uses recoverable staging and publishes an immutable numbered iteration only after its receipt is complete; a later call may recover an interrupted stage but must never overwrite a completed receipt.
112. Re-read and re-hash the exact plan and approval after acquiring the shared job write lock and before canonical promotion or terminalization. Receipt-less iteration staging must be recovered by one convergence-run invocation before cancellation or terminalization; terminal evidence combined with receipt-less staging is invalid. Orphan cancellation, final snapshot, PDF, or incomplete iteration evidence must block replay rather than silently reopening consumed authority.
113. New modeling plans must explicitly classify small surface-attached details. Shallow windows, seams, labels, rivets, painted panels, and repeated marks belong in `surface_details` when they do not affect silhouette, structure, gameplay, or physical transparency; geometry-worthy parts remain normal modeling objects.
114. A texture-routed surface-detail ID must never also exist as a SceneSpec object. Its parent object and target material must exist and remain stable, and a changed non-empty surface-detail plan participates in the Blender build fingerprint.
115. Every non-omitted surface detail requires an authored UVMap image/hybrid TextureManifest that lists its exact stable ID in `surface_detail_ids` and contains every planned PBR channel. A coverage claim is not pixel-level proof and must not be fabricated.
116. V0.6 reports surface-detail contract coverage separately from geometry similarity. Missing or incorrect pixels return to V0.5 material/texture authoring; a newly discovered silhouette or structural requirement returns to V0.4 geometry authoring.
117. `baked_decal` means portable PBR maps, not an engine-specific runtime decal graph. V0.7 may preserve or derive those maps but still cannot claim destination shader parity.
118. Newly authored V0.5 plans use `surface_detail_binding_policy=spatial_v1`. A non-omitted surface detail must bind one exact detail ID to one parent object, one exclusive material, the current ordered polygon-corner UV fingerprint, a bounded `uv_rect` or hash-bound mask, explicit image-backed PBR channels, strength, and non-repeating clamp/clip sampling. Legacy unbound plans remain readable but never become spatially verified by inference.
119. Spatial image channels must use the exact `UVMap` through identity Mapping and non-repeating image sampling. Procedural variation, when present in a hybrid material, uses a separate scaled coordinate path and must not move or repeat localized detail pixels.
120. Clean or stylized surfaces must default to neutral maps. Do not invent full-field black seams, panel grids, bands, grooves, scratches, or strong normal relief from a generic preset. If the intended face or UV placement is not supported by current evidence, keep the clean fallback and return the detail to V0.5 authoring review instead of painting it globally.
121. `reports/material_fidelity_validation.json` is the authoritative deterministic V0.5 fidelity report. It checks channel hashes, suspicious dark-line/noise/normal signatures, spatial ownership, current UV bindings, and other machine evidence; it is not a material-reference similarity score and cannot prove that an authored UV rectangle selects the semantically correct face. Swatch, preview, and direct-reference review remain required.
122. Every newly authored standard or background ModelingPlan uses `assembly_consistency_policy=spatial_v1`, one asset-local longitudinal/lateral/vertical frame, and an explicit assembly role for every semantic object. Legacy `legacy_unbound` plans remain readable but must never be reported as spatially verified.
123. A single reference-camera screen offset never proves lateral or depth placement. Bilaterally symmetric manufactured assets must keep applicable functional or structural parts on an inferred center plane or common axis unless an orthogonal view, blueprint, measured source, or explicit user-authored requirement proves a side-specific arrangement.
124. Attached parts require stable parent-local assembly relationships such as `center_plane`, `coaxial`, `bbox_containment`, `surface_contact`, or evidenced `side_specific`. Classify relationships from structural evidence rather than semantic names alone; examples such as a trigger, lever, handle, wheel, axle, or guard illustrate the rule but do not grant unsupported mechanical truth.
125. Build, inspect, and validate bind the exact spatial ModelingPlan hash and evaluate live geometry bounds in the root object's translation-and-rotation-only orthonormal meter frame. A required assembly failure blocks structural validation before material authoring.
126. Fixed-camera V0.6 similarity, pre-QA fit, and convergence may not override a current assembly relationship. A proposed lateral/depth change that conflicts with spatial assembly evidence returns to V0.4 authoring instead of becoming an automatic visual revision.
127. Assembly bbox checks are broad static-placement evidence only. They do not prove triangle-level contact, moving-part clearance, kinematics, manufacturability, weapon function, or the hidden-side truth of a single image.
128. V0.6 camera/geometry/assembly companion diagnostics never recalculate, replace, or improve the canonical `VisualQAReport.overall_direct_score`. Canonical exterior QA still validates the actual Blender camera and contains exactly the seven required pass kinds.
129. Bounded camera probes are advisory, noncanonical evidence. They must leave the authoring `.blend`, SceneSpec, material contracts, canonical camera, and approval state unchanged and can never authorize a camera or geometry revision.
130. Primary-subject silhouette probe scoring requires an exact hash-bound mask: use the canonical VisualQARequest mask only for `primary_object_only`, or a run-owned union of explicit primary/supporting semantic masks. Without either source, preserve the legacy observed-bbox fallback and never fabricate a mask from bboxes.
131. Per-part mask IoU, normalized centroid error, area ratio, boundary F-score, symmetric contour distance, and PCA axis evidence require explicit semantic reference masks. Missing or stale masks produce degraded, unscorable, or fail-closed evidence instead of inferred precision.
132. PCA orientation is an undirected 2D axis and cannot distinguish a 180-degree reversal. Directed `axis_alignment` relationships verify facing; `axis_clearance` verifies signed axial separation plus transverse overlap. Hidden-axis placement also requires the signed 3D assembly frame and each object's declared `required_assembly_checks`.
133. Five-view assembly sanity (`front`, `right`, `top`, `rear`, `oblique`) is structural evidence only. Its reference-similarity status remains `unscorable`; visibility, projection, depth-order, or assembly findings are not a reference match score and do not authorize revisions.
134. Legacy jobs and workflows without companion diagnostics remain readable and report the companion as unavailable. New diagnostic planning applies only to newly created workflows and never rewrites or retroactively completes historical evidence.
135. Companion diagnostics do not bypass generic workflow review, guarded V0.6 revision approval, bounded-convergence approval, InteriorScope, interior-QA camera approval, V0.7 optimization approval, or Destination Handoff approval.
136. New explicit semantic reference masks are published only from `analysis/masks/registrations/<registration-id>/manifest.json` after exact candidate-hash, current SceneSpec/reference-hash, observed semantic-evidence, and binary PNG validation. Promotion preserves the candidate bytes at `analysis/masks/semantic_manifest.json`, archives a prior canonical manifest under `history/qa_semantic_masks/`, and writes an immutable promotion receipt.
137. Semantic-mask registration and read-only status publish QA evidence only. They create or consume no workflow, guarded-revision, convergence, InteriorScope, interior-QA, V0.7 optimization, or Destination Handoff approval. A diagnostic snapshots the exact manifest and mask bytes into its own attempt so a later valid promotion does not stale historical evidence, while any attempt-snapshot mutation invalidates its terminal bundle.
138. Newly planned standard proxy/detail/revision and background geometry flows render an exact workflow-owned exterior geometry review from temporary `front`, `right`, `top`, `rear`, and `oblique` cameras before geometry approval or material authoring. Root-only authored `spatial_v1` assets are eligible; an attached child is not required.
139. A geometry multi-view host step is not visual inspection by itself. The following agent step must read every beauty and wireframe image, bind `visual_review.json` to the exact plan/manifest/structural-report hashes, and classify cross-view shape coherence, proportions, orientation, assembly, and obvious topology artifacts.
140. Five-view cameras use asset-local directions and independently auto-fit the current bounds. They do not preserve one identical world-space pose across revisions and do not prove side/rear reference likeness. Without calibrated per-view reference contracts, every noncanonical view remains reference-similarity `unscorable`.
141. Ordinary single-view occlusion is advisory and cannot by itself demand V0.4 redesign. All-view semantic disappearance, required assembly failures, or explicit agent-observed cross-view geometry defects may recommend bounded V0.4 revision or manual redesign review, but never authorize a canonical change.
142. Geometry-review workflow outputs bind all twenty exact pass images, the three host terminal JSON files, and the agent visual-review JSON. A PDF that explicitly names an assembly-sanity run must fail closed when that terminal or any image is missing, stale, or hash-mismatched.
143. Manual approved one-shot V0.6 geometry revisions on authored `spatial_v1` assets capture exact baseline and result five-view structural terminals. Required-check worsening, all-view visibility loss, structural-status worsening, or geometry-review outcome worsening vetoes acceptance and triggers the existing rollback boundary.
144. The manual revision multi-view guard is structural non-regression evidence, not an additional similarity score. Legacy/non-spatial plans remain readable and report the guard as `not_applicable`. New authored `spatial_v1` assets must fail closed before bounded-convergence planning or execution until each iteration's immutable plan, receipt, and audit contracts bind equivalent baseline/result multi-view evidence; use the manual one-shot guarded revision path meanwhile.
145. Existing immutable workflows and QA runs are historical evidence and are not retroactively amended. New five-view workflow planning, agent visual reading, and structural revision guards apply to newly planned work or newly executed eligible manual revisions only.

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
11. Keep the candidate-by-candidate one-shot flow as the default. For repeated standard revisions only, the user may request one bounded convergence plan from a current direct QA run.
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
- Prefer `plan-revision` + `apply-revision` over full SceneSpec regeneration.
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
7. Preserve InteriorScope, visual-revision, and optimization approvals as their existing specialized contracts; orchestration cannot synthesize them.
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
- Interior safety: `uv run cbm interior-scope-status <job>` and `uv run cbm interior-scope-validate <job>`
- Human-readable report: `uv run cbm report-pdf <job> --scope build|material|qa|export|full`
- PDF verification: validate PDF text/pages and sidecar hashes, then render representative pages for visual inspection
- V0.9 evidence: `uv run cbm stability-probe`, `uv run cbm workspace-audit`, and `uv run cbm stability-report-pdf`

## File ownership

- `input/`: immutable user evidence
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
- `reports/v09/`: repository-owned environment probes and read-only workspace audits with relative paths only
- `.cbm/queue/`: operational single-worker queue, locks, leases, and immutable dispatch receipts; never canonical asset data
- `output/pdf/v09/`: derived V0.9 stability PDFs and exact source-hash sidecars
