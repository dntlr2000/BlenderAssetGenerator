# Known limitations

This handoff is an engine-neutral static-asset delivery contract.

## Excluded scope
- Unity or Unreal Editor automation
- engine prefab, actor, or runtime material graph creation
- runtime parity claims
- CAD B-Rep
- rigging, skinning, and animation
- gameplay logic
- unapproved destination project changes

## Format losses
- Height/displacement is represented only through the baked tangent-space normal channel.
- Procedural and master-shader detail is resolution-bounded by the derived atlas bake.
- The five-channel contract does not include an opacity texture; alpha is scalar-only.

## Unverified items
- destination engine, version, and render pipeline
- destination runtime material and shader parity
- destination import axis and unit behavior until import validation
- destination instancing, draw calls, physics, and LOD selection behavior
- interchange file metadata beyond export-operator evidence
- clean-import warning: Axis conversion is declared by the export operator but file metadata was not independently inspected; imported bounds provide indirect evidence only.
- clean-import warning: Meter units and unit scale are declared by the export operator but file metadata was not independently inspected; imported numeric bounds provide indirect evidence only.
- clean-import warning: Custom split-normal equivalence is not verified; runtime face-normal validity is checked instead.
- clean-import warning: Exported tangent vector equivalence is not verified; V0.7 checks only whether a finite basis can be recomputed from the imported UV set.
- clean-import warning: UV loop-to-vertex association could not be verified for: product.body__LOD0, product.body__LOD0__COLLIDER, product.body__LOD1, product.body__LOD2
- clean-import warning: UV coordinate summary preservation could not be verified for: product.body__LOD0, product.body__LOD1, product.body__LOD2

Blender procedural master shaders are not assumed to survive interchange. Use only the portable channels recorded in material_mapping.json unless the destination plan explicitly authors an approved replacement.
