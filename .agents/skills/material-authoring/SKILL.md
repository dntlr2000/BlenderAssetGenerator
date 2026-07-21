---
name: material-authoring
description: Plan stable V0.5 material identities, mappings, texture sources, and export profiles after geometry approval.
---

# Material authoring

1. Confirm geometry, camera, semantic IDs, and material assignments are approved before authoring.
2. Create `analysis/material_plan.json`; do not put the V0.5 material contract inside SceneSpec.
3. Preserve every SceneSpec material ID and explicitly mark observed versus inferred properties.
4. For each material, record shader family, mapping mode, real-world scale, texture strategy, export profiles, confidence, and assumptions.
5. Prefer procedural or reusable tiled sources for terrain and architecture; use unique image maps only where the evidence requires them.
6. Keep Blender master appearance separate from GLTF/Unity-safe output requirements.
7. For deterministic source maps, select a documented family preset and preserve provider/version/model/prompt/seed plus channel hashes in TextureManifest.
8. Validate material contracts and Blender node graphs, then render fixed sphere and plane swatches.
9. Stop for approval before baking or replacing approved material identities.
