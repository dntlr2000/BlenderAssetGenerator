# V0.5 material planning prompt

Use the approved SceneSpec, reference diagnostics, and preview. Preserve geometry, camera, transforms, semantic IDs, and existing material assignments.

For every material ID, produce a MaterialPlan v0.5 entry with:

- observed or inferred evidence and confidence;
- shader family and portable Principled surface behavior;
- UV, object, generated, or triplanar mapping with real-world scale;
- none, procedural, image, or hybrid texture strategy;
- exact coverage for every non-omitted `surface_details` entry. Localized details require a
  portable `UVMap` image/hybrid TextureManifest whose `surface_detail_ids` and PBR channels match
  the ModelingPlan decision;
- Blender EEVEE/Cycles and GLTF/Unity export profiles;
- whether baking is required and why.

Do not generate textures, edit SceneSpec, convert a texture-routed detail back into geometry, or
build arbitrary Blender nodes in this step. Blender master shaders may remain richer, but localized
surface details must also exist in portable flattened PBR maps rather than an engine-specific graph.

When an explicit Codex ImageGen material-loop companion is selected, treat its image only as a
source-bound `base_color`, `decal_rgb`, `emission`, or `opacity_source` candidate. Preserve its native
adoption/normalization/core-preparation and semantic-selection closure. Derive normal, roughness,
metallic, height, displacement, AO, and exact signage text through the existing local contracts.
MaterialAuthoring output remains staging evidence; do not claim canonical promotion, IQ pass, human
review, or package acceptance until their separate host receipts exist.
