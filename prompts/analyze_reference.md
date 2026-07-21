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

The caller appends job-specific paths and metadata.
