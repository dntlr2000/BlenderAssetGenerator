# V0.7 portable static-asset optimization planning prompt

Use only an approved canonical SceneSpec, fresh Blender build, current material contracts, and immutable V0.5 bake evidence. Do not edit canonical geometry, materials, textures, input evidence, camera, or semantic IDs.

1. Select one engine-neutral profile: `portable_gltf`, `fbx_interchange`, or `obj_legacy`.
2. Declare `static_prop`, `static_environment`, or `static_architecture` and explain the choice.
3. Freeze source provenance: SceneSpec, external geometry, source `.blend`, embedded build fingerprint, MaterialPlan, and TextureManifest hashes.
4. Run read-only preflight before proposing derived work.
5. For every semantic mesh family, record:
   - inclusion or exclusion;
   - required LOD levels and conservative triangle ratios;
   - silhouette-critical or topology exceptions;
   - collision strategy;
   - UV0 preservation/generation and UV1 requirement;
   - stable material-ID preservation;
   - expected format loss or uncertainty.
6. Keep all optimized files below one immutable `optimization/runs/<run-id>/` directory.
7. Preserve raw PBR channels. Treat packed textures as derived outputs with explicit source-channel mappings.
8. If any required authoring material uses object/generated/triplanar mapping or a non-portable Blender graph, plan one explicit run-owned material conversion after optimization. Bind it to the exact source/profile/run hashes and preserve the canonical graph unchanged.
9. Select a consolidation policy explicitly. Batch only equal semantic IDs, ordered material IDs, LOD levels, UV signatures, and optional spatial cells. Preserve triangle totals and per-source LOD ceilings.
10. Declare optional static cost budgets and whether they are `off`, `warning`, or `fail`. Treat estimated draw calls as material-slot proxies rather than destination-runtime measurements.
11. Remove only profile-authorized loose geometry, duplicate material slots, or exact duplicate colliders in the derived scene. Report repeated meshes and AABB overlap candidates without deleting render geometry or claiming internal/coplanar face proof.
12. Require `asset_cost_report.json` before packaging and include its warnings, unverified checks, and budget results in the export PDF.
13. Stop on failed preflight, stale provenance, a fail-enforced cost budget, or a requested canonical edit. Do not disguise those failures as optimization warnings.

The result must be a schema-valid AssetProfile and OptimizationPlan. It authorizes derived static-asset artifacts only and does not imply approval for engine-specific import, runtime shader conversion, rigging, animation, or canonical model changes.
