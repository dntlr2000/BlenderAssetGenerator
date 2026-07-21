---
name: texture-authoring
description: Plan and generate coherent PBR or procedural materials after geometry approval, preserving texel density, UV scale, and material identity across revisions.
---

# Texture authoring

- Do not texture unapproved proxy geometry unless the user explicitly asks.
- Choose procedural materials for scalable/repeating surfaces and image textures for unique art direction.
- Record real-world texture scale or texel density.
- Produce a texture manifest with channel paths, color spaces, UV set, tiling, and generation prompt/version.
- Base color must not contain baked lighting unless intentionally stylized.
- Normal maps use non-color data; roughness and metallic use non-color data.
- Preserve material IDs when regenerating textures.
- Render material swatches before applying expensive high-resolution textures to the full scene.
