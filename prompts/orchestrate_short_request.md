# V0.8 short-request orchestration

Use the repository V0.8 workflow contracts to route the user's short request. Do not skip an agent-authored contract or a user approval.

1. Create or select the correct isolated job without replacing primary evidence.
2. Plan the workflow with the narrowest intent and scope that satisfy the request.
3. Read `state.json` and execute only the exact current action.
4. For an agent step, author only the declared canonical artifact, validate it, and record the exact input/output-bound completion marker.
5. For a generic approval, generate and show the matching PDF alongside canonical JSON evidence and the exact fingerprint; never self-approve.
6. For InteriorScope, V0.6 visual revision, or V0.7 optimization, use the existing specialized approval flow.
7. Resume deterministic host steps only. Use failed-step retry only after the cause is corrected and the user authorizes retry.
8. Stop at an unsupported destination boundary and deliver the engine-neutral package without claiming engine parity.
9. Report the workflow ID, current state, next action, completed checkpoints, warnings, and remaining approvals.

# Three-dimensional assembly consistency

For every newly authored standard or background ModelingPlan, use
`assembly_consistency_policy=spatial_v1`. Define one asset-local `assembly_frame`, classify object
assembly roles, and record stable parent-local relationships for attached structural or functional
parts. Center-plane, coaxial, containment, contact, signed `axis_alignment`, `axis_clearance`, and
each attached object's check-category `required_assembly_checks` must survive SceneSpec authoring and later
detailed revisions. When full 3D facing must be constrained, use two feasible directed-axis
relations with distinct subject axes, one target space, the same reference for `reference_local`,
and approximately orthogonal target directions within their summed angular tolerances; a 2D
silhouette/PCA axis cannot prove a 180-degree direction.
`side_specific` requires an orthogonal/multiview/blueprint source or an
explicit user-authored requirement; visibility in one side/oblique image is not hidden-depth side
evidence. Bind observed/measured evidence to exact source IDs. Otherwise use inferred
center-plane/coaxial intent and never turn a 2D screen-space offset into an unobserved depth/lateral
coordinate.

# V0.6 companion diagnostics

Keep canonical Visual QA at the exact seven-pass direct-reference contract and never recalculate
its score through companion evidence. For newly authored semantic reference masks, write only a
registration-owned candidate, report its exact SHA-256, and use the allowlisted registration/status
surface; never write `analysis/masks/semantic_manifest.json` directly. Diagnostics consume their
own exact manifest/mask snapshots. Camera attribution, semantic contours, PCA axes, and five-view
assembly sanity are advisory and must not synthesize, consume, or apply any approval or revision.

# Surface-attached detail routing

During ModelingPlan authoring, explicitly separate geometry-worthy parts from small surface detail.
Use `surface_details` for shallow non-structural windows, seams, labels, rivets, painted panels, and
repeated marks. Never emit one SceneSpec object per texture-routed mark. V0.5 must bind those IDs to
portable UVMap PBR channels before material build, while V0.6 reports their coverage separately
from geometry similarity.

# Optional AQ v2 Codex ImageGen material loop

Enter `autonomous_static_prop_v2_codex_imagegen` only after an explicit disabled-profile opt-in and
current AQ v2 geometry promotion. Use the current Codex task's built-in ImageGen capability only;
never add an API provider, create a task, or claim background continuation. Preserve native bytes,
normalize through an exact derivative, require non-human semantic evidence and multi-candidate
ranking closure, and bind any native-fed core selection through
`CodexImageNativeCorePreparationReceipt`.

Do not reinterpret the V0.5 staging receipt's compile-`not_run` status. Exact adoption requires a
separate actual-Blender shadow preflight for the exact bytes; otherwise use bounded controller-authored
completion. Run only the existing ControllerExecutor and host material promotion service. Keep
`material_promoted`, IQ `quality_approved`, V0.7 approval, package acceptance, and destination parity
as separate boundaries. Stop at `review_required`, `blocked`, or `waiting_for_v07_approval` without
synthesizing approval, human review, package evidence, or destination writes.
