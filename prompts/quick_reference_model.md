# Quick reference model workflow

The user supplied an image and a short modeling request. Follow repository defaults rather than asking for a long prompt.

1. Choose a unique lowercase job ID; never reuse an existing job for a different image.
2. Create the job and run deterministic reference analysis.
3. Read `reference_analysis.json` and `camera_solution.json`.
4. Populate `modeling_plan.json` with observed/inferred semantic objects.
5. Author a proxy SceneSpec using stable IDs and evidence boxes.
   Before authoring, classify small surface-attached marks in the ModelingPlan. Keep shallow,
   non-structural details out of SceneSpec geometry and route them to V0.5 texture channels or a
   baked decal; keep silhouette, structural, transparent, and gameplay parts as geometry.
6. Build, render, inspect, and validate through MCP.
7. Do not texture or export unless requested.
8. Return the preview path, object families, assumptions, and uncertainties.
