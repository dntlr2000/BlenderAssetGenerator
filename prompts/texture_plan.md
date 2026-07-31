# Task: Plan textures and materials

Read the approved SceneSpec and produce a texture manifest.

For each material:

- Decide procedural versus image-based PBR.
- Define base color, roughness, metallic, normal, height, opacity channels as applicable.
- Define color space per channel.
- Define physical texture scale or texel density.
- Read ModelingPlan `surface_details`. For each non-omitted entry, preserve its exact stable ID in
  TextureManifest `surface_detail_ids`, include every requested PBR channel, and use `UVMap` for
  localized placement. Do not claim coverage unless the actual map contains that detail.
- Define tiling/seam requirements and style constraints.
- Reuse material IDs and avoid creating near-duplicate materials.
- State which geometry/UV prerequisites must be satisfied before generation.

Do not alter geometry in this task.
