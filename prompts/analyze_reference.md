# Task: Convert analyzed references into canonical SceneSpec v0.2

You are working inside Codex Blender Modeler project v0.4.

Read:

- `AGENTS.md`
- the `reference-analysis`, `reference-to-scene`, and `blender-build` skills
- job metadata
- `analysis/reference_analysis.json`
- `analysis/camera_solution.json`
- `analysis/modeling_plan.json` when present
- `schemas/scene_spec.schema.json`

Inspect attached images and produce a complete SceneSpec JSON as the final response.

Requirements:

- Output JSON only as the final response, conforming to the schema.
- Geometry schema remains `0.2.0`, meters, +Z up, and -Y camera-forward.
- Preserve the exact job ID and immutable source records.
- Use deterministic diagnostics as evidence, not as metric truth.
- Use stable semantic object and material IDs.
- Populate or respect the semantic modeling plan before final SceneSpec authoring.
- New authored plans must use `assembly_consistency_policy=spatial_v1`, define one asset-local
  `assembly_frame`, classify every object with an assembly role, and record stable-ID
  `assembly_relationships` for attached structural or functional components.
- For manufactured or bilaterally symmetric assets, use parent-local `center_plane`, `coaxial`,
  `bbox_containment`, and `surface_contact` relationships as supported by evidence. Examples such
  as triggers, levers, handles, or wheels illustrate functional parts; never infer assembly policy
  from an object name alone.
- For elongated or directional attached parts, declare signed 3D `axis_alignment` relations and
  `axis_clearance` where an axial gap matters. When full facing must be constrained, use two
  feasible directed-axis relations with distinct subject axes, a common target space, the same
  reference object for `reference_local`, and approximately orthogonal target directions within
  their summed angular tolerances. A 2D silhouette/PCA axis cannot prove a 180-degree direction.
- Every attached object must list its mandatory check categories (`position`, `axis`,
  `orientation`, or `clearance`) in `required_assembly_checks` so missing supporting relations fail
  closed.
- Use `side_specific` only when an orthogonal/multiview/blueprint source or an explicit
  user-authored requirement establishes a side. Seeing a part in one side or oblique image is not
  hidden-depth side evidence. Bind observed/measured relationships to exact source IDs; otherwise
  a bilateral manufactured functional part defaults to an `inferred` center-plane/coaxial intent
  with confidence rather than copying a 2D screen offset into the hidden lateral/depth axis.
- Populate `surface_detail_policy` and classify visible small surface-attached details before
  SceneSpec authoring. Route shallow windows, seams, labels, rivets, painted panels, and repeated
  marks to `surface_details` when they do not affect silhouette, structure, gameplay, or physical
  transparency. Keep geometry-worthy parts in `objects`.
- Never create a SceneSpec object for an ID routed through `surface_details`. Record its parent,
  target material, PBR channels, UV strategy, observed bbox, and confidence instead.
- First reproduce silhouette, proportions, camera framing, and semantic layout; defer decoration.
- Choose the least complex deterministic geometry recipe:
  - `primitive` for simple masses;
  - `profile_extrude` for front/side outlines with depth;
  - `revolve` for rotational symmetry;
  - `curve` for roads, pipes, rails, cables, trim, and branches;
  - `terrain` for height fields and broad natural surfaces;
  - `custom_mesh` only when other recipes cannot preserve the silhouette.
- Prefer mirror, bevel, subdivision, array, and boolean modifiers over dense vertices.
- Store large custom meshes under `workspaces/<job>/geometry/` and reference job-relative paths.
- Use generators for repeated separate objects.
- Evidence boxes must be normalized `[x_min, y_min, x_max, y_max]`.
- Distinguish observed and inferred geometry with confidence.
- In concept mode, use ratios and a nominal scene size; do not claim real dimensions.
- In measured mode, obey scale anchors and `constraints/constraints.json`; report unresolved degrees of freedom.
- Use camera-solution fields as a scaffold, not an unquestionable solution.
- Keep hidden-side reconstruction assumptions explicit.
- Preserve the ModelingPlan assembly frame, relationship IDs, subject/reference IDs, evidence,
  confidence, and each object's `required_assembly_checks` in SceneSpec authoring. Satisfy
  `axis_alignment`, `axis_clearance`, and the other relations in the declared parent-local frame
  rather than optimizing only the reference-camera projection.

The caller appends job-specific paths and metadata.
