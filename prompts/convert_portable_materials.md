# V0.7.1 run-owned portable material conversion prompt

Convert one explicit optimization run's approved authoring materials into portable PBR evidence. Do not modify the canonical SceneSpec, geometry payloads, MaterialPlan, ShaderRecipe, TextureManifest, source images, or canonical `.blend`.

1. Require one exact job ID, AssetProfile ID, optimization run ID, and new conversion ID.
2. Recompute and verify source, profile, execution-plan, optimized-scene, and embedded build fingerprints before creating output.
3. Reject failed/incomplete optimization runs, stale fingerprints, an existing conversion ID, and any path outside the run-owned conversion directory.
4. Build shared non-overlapping portable atlas UVs in derived objects only. Preserve stable semantic and material IDs and keep original UV data when the profile requires it.
5. Bake portable Base Color, Roughness, Metallic, Normal, and Emission channels with explicit color space, resolution, margin, Blender version, render device, and output hashes.
6. Record mapping transformations and any unverifiable overlap, texel-density, transparency, transmission, procedural, or format fidelity as warnings or known losses; never fabricate a pass.
7. Rewire only the derived portable scene to whitelisted image-based PBR materials and save the exact output scene hash.
8. Emit one schema-valid `PortableMaterialConversionManifest 0.7.0` bound to the selected source/profile/run and conversion ID.
9. Stop before package creation. A package must select this exact conversion explicitly with `--material-conversion-id`.

The conversion authorizes derived static-asset artifacts only. It does not authorize canonical edits, engine-specific shader reconstruction, rigging, animation, or runtime parity claims.
