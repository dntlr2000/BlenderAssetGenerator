---
name: quick-reference-model
description: Handle a short image-plus-request workflow by creating an isolated job, running reference diagnostics, authoring a proxy SceneSpec, and validating Blender output.
---

# Quick reference model

Use this skill when the user attaches an image and gives a short modeling request.

1. Infer a descriptive lowercase job ID and verify it is unused.
2. Create the job in concept mode unless measured evidence exists.
3. Run `analyze_reference` and read both generated JSON artifacts.
4. Populate `modeling_plan.json` with stable semantic IDs.
5. Author a proxy SceneSpec using the least complex geometry recipe.
6. Treat hidden geometry as inferred and keep its confidence lower.
7. Run build, render, inspect, and validate through MCP.
8. Stop for approval after the proxy unless the user asked for more.
9. Never change project source code to compensate for bad job data.
10. On a new attached asset, never reuse the previous job ID.
11. Treat interiors as default-disabled. A short building or exterior request must not create an InteriorScope, rooms, corridors, stairs, ceilings, or furnishings.
12. If the user explicitly requests an interior, create only an exact InteriorScope draft and stop for approval of its current SHA-256; do not author interior SceneSpec objects before a matching user approval exists.
