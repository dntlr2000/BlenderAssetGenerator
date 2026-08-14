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
- If the source is a Codex ImageGen companion candidate, bind its immutable native adoption,
  normalization, core preparation, semantic review, and exact selection evidence. Accept direct
  pixels only for `base_color`, `decal_rgb`, `emission`, or `opacity_source` roles.
- Derive normal, roughness, metallic, height, displacement, AO, and tangent data locally; never label
  an ImageGen pseudo-PBR image as an authoritative channel. Compose exact signage text locally from
  hash-bound font evidence.

Do not alter geometry in this task.

For a candidate that will enter Material Closure `0.1.0`, do not hide a required channel, mask,
reference, coverage image, or UV prerequisite in prose. Declare contained relative paths and stable
material/detail IDs so the host graph collector can discover every exact dependency. A missing or stale
dependency must block the later preapproval preflight; never mark it optional merely to complete the
manifest. This task does not perform graph rebinding, approval, controller execution, or canonical
promotion.
