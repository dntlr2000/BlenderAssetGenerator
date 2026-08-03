# Quick reference model workflow

The user supplied an image and a short modeling request. Follow repository defaults rather than asking for a long prompt.

1. Choose a unique lowercase job ID; never reuse an existing job for a different image.
2. Create the job and run deterministic reference analysis.
3. Read `reference_analysis.json` and `camera_solution.json`.
4. Populate `modeling_plan.json` with observed/inferred semantic objects.
   Use `assembly_consistency_policy=spatial_v1`, one asset-local assembly frame, explicit assembly
   roles, and parent-local relationships for attached structural or functional parts. For
   manufactured or bilateral assets, declare center-plane, coaxial, containment, and contact
   intent where applicable. A side-specific relationship needs an orthogonal/multiview/blueprint
   source or explicit user-authored requirement; visibility in one side/oblique image is not
   hidden-depth side evidence. Otherwise use an inferred center-plane/coaxial intent and never copy
   a 2D screen offset into an unseen lateral/depth coordinate.
5. Author a proxy SceneSpec using stable IDs and evidence boxes.
   Before authoring, classify small surface-attached marks in the ModelingPlan. Keep shallow,
   non-structural details out of SceneSpec geometry and route them to V0.5 texture channels or a
   baked decal; keep silhouette, structural, transparent, and gameplay parts as geometry.
   Preserve every assembly relationship ID and satisfy it in the declared parent-local frame.
6. Build, render, inspect, and validate through MCP.
7. Do not texture or export unless requested.
8. Return the preview path, object families, assumptions, and uncertainties.
   Report inferred hidden-axis placement separately from observed geometry.
