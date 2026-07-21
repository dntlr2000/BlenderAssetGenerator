---
name: texture-baking
description: Prepare deterministic PBR texture manifests and bake contracts for GLTF or Unity without changing approved geometry.
---

# Texture baking

1. Require approved geometry, material plan, shader recipes, and an explicit UV mapping for export baking.
2. Validate Base Color as sRGB and all data channels as Non-Color.
3. Record resolution, real-world scale, texel density, provider/model/seed, source hashes, and license provenance.
4. Keep generated maps inside `textures/<material-id>/`; never modify input evidence.
5. Preserve an existing requested UV set or use the bounded Smart UV fallback; do not claim authored seams or atlas quality.
6. Bake only effects that the target profile cannot reproduce directly.
7. V0.6 produces separate Base Color, Roughness, Metallic, Normal, and Emission channels with hashes. V0.7 may preserve those channels and derive glTF ORM with explicit provenance; do not claim engine-specific smoothness or mask packing.
8. Validate missing files, UV coverage/range, degenerate faces, normal convention, and implemented profile compatibility.
9. Do not claim Unity, Unreal, or another engine's parity from V0.7 engine-neutral packaging; require an explicitly selected adapter and an actual target-engine import test.
