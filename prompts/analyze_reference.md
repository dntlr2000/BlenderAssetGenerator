# Task: Convert analyzed references into canonical SceneSpec v0.2

You are working inside Codex Blender Modeler project v0.9.1.

Read:

- `AGENTS.md`
- relevant project skills only when explicitly requested by the user, as required by `AGENTS.md`
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
- Deterministic image analysis is a scaffold, not completed three-dimensional interpretation.
  Inspect the actual reference pixels. Classify visible boundaries as outer silhouette,
  material/color boundary, raised or recessed surface detail, occlusion, or an actual opening.
  Identify which structural owner continues behind each occluder before tracing separate parts.
  Use existing plan evidence, descriptions and confidence fields; do not invent schema fields.
- Record observed overlap order separately from inferred thickness, back surfaces and mounting
  depth. A single image does not determine unique hidden geometry or measured dimensions.
  Preserve observed openings and free tips; do not fill them to simplify the assembly.
- An observed continuous surface needs a continuous carrier or a supported seam across its
  visible width and depth. Independently extruded outlines, matching bounding boxes, one contact
  point, and a supported centerline cannot establish this. Identify the complete intended root
  or attachment footprint and its supporting owner, including lateral edges and interior gaps.
  State intentional modular separation or optical/open surfaces explicitly instead of treating
  every disconnected mesh as a defect.
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
- Before detailed material work or delivery preparation for a volumetric reconstruction, inspect a
  cheap provisional blockout in the reference view, an oblique view, exact side, exact top, rear,
  and clay. Record the actual diagnostic settings and each major part's local section/depth
  hypothesis in existing notes and confidence fields. Side/top views are diagnostics of inferred
  construction, not additional observed references or canonical V0.6 score inputs.
- Reject a blockout that merely applies a common extrusion depth to a drawing when the intended
  asset needs rounded, tapered, or otherwise distinct component volumes. Do not impose an
  arbitrary minimum depth on a legitimate plaque, sheet, or user-requested relief. Resolve visible
  separation, implausible sections, and unintended material-boundary scallops before expensive
  material/optimization stages; test counts or front silhouette agreement cannot replace this
  visual authoring decision. Preserve intentional cutouts and free tips.
- Also establish the broad cross-sections visible in highlights, occlusions and creases. A flat
  silhouette plate is not a completed volume merely because its front projection matches.
  Prefer shared owner geometry for continuous carved relief. For a separate attached relief,
  derive its full underside from the owner surface rather than setting independent tube depths.
  A supported height-field owner can use the reusable reference assembly construction path in
  `docs/reference_assembly_generation.md`; arbitrary surfaces remain outside that path's proof.
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
- Freeze original-reference critical foreground regions and intended openings before comparing
  candidates. Never shrink sure regions around candidate errors. When the optional attachment
  companion is explicitly selected, retain exact source, camera and region evidence and prove
  the whole declared patches on actual native, converted and clean-imported geometry. Historical
  absence is unverified; stale, failed or unsupported supplied evidence cannot be a pass.
- Inspect front, oblique, rear and clay closeups after construction. Check continuous seams,
  broad relief, root insertion, normals and intended openings independently of the global
  silhouette score. Report geometry, objects/primitives and texture costs; use the existing
  supported material/export route and preserve final human visual review as a separate decision.
- Preserve the ModelingPlan assembly frame, relationship IDs, subject/reference IDs, evidence,
  confidence, and each object's `required_assembly_checks` in SceneSpec authoring. Satisfy
  `axis_alignment`, `axis_clearance`, and the other relations in the declared parent-local frame
  rather than optimizing only the reference-camera projection.

The caller appends job-specific paths and metadata.
