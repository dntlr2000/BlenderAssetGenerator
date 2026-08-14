# V0.5 shader recipe prompt

Translate one approved material-plan entry into ShaderRecipe v0.5 using only whitelisted layers and semantic socket names.

Analyze base color, metallic, roughness, IOR, transmission, alpha, emission, coat, subsurface, anisotropy, surface relief, mapping scale, and layer masks. Separate observed properties from inferred ones. Prefer a small graph and record export-safe bake requirements. Do not emit Python or direct Blender node code.

For a later Material Closure `0.1.0` attempt, every graph provenance input, base/layer channel image,
mask, preview reference, MaterialPlan and ShaderRecipe dependency must use a contained relative path and
exact digest that the host collector can discover. Keep visual semantics independent of staging paths:
the host may later rebind only provenance path/hash pairs into a separate derivative. Do not hand-edit
the source graph for rebinding, omit a dependency from a controller map, create an approval, or write
canonical state in this planning task.
