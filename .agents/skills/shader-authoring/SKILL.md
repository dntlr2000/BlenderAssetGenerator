---
name: shader-authoring
description: Author Blender 5-compatible, whitelisted ShaderRecipe v0.5 graphs with portable surface semantics and explicit fallbacks.
---

# Shader authoring

1. Read the approved material plan and author one stable recipe per material under `materials/<material-id>/shader_recipe.json`.
2. Analyze metallic response, roughness variation, transmission, alpha, emission, coat, subsurface, anisotropy, normal or displacement needs, and layer masks.
3. Address Principled inputs by semantic socket names and probe fallbacks at runtime; never depend on a numeric socket index.
4. Use only the whitelisted recipe layers. Reject arbitrary Blender Python and arbitrary node execution.
5. Record mapping scale and every inferred property. Do not invent complex effects unsupported by the reference.
6. Treat Blender master graphs as source material and declare when an export-safe bake is required.
7. Verify EEVEE first and Cycles when requested, then inspect nodes, images, color spaces, alpha, and swatch renders.
8. A graph that builds without errors is not visually approved until its swatches are reviewed.
