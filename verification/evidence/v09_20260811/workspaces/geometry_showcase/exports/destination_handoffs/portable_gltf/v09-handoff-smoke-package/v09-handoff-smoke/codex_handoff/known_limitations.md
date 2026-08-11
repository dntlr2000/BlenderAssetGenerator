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
- Object-space appearance was sampled against cbm_source_object before portable UV rewiring.
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
- clean-import warning: UV loop-to-vertex association could not be verified for: CBM_demo_instance_post__LOD0__BATCH0003, CBM_demo_instance_post__LOD1__BATCH0001, CBM_demo_instance_post__LOD2__BATCH0002, demo.boolean.block__LOD0, demo.boolean.block__LOD0__COLLIDER, demo.boolean.block__LOD1, demo.boolean.block__LOD2, demo.curve_pipe__LOD0, demo.curve_pipe__LOD0__COLLIDER... [truncated in handoff summary; full warning remains in round-trip evidence; sha256=933f91abb450da811889d96e1301904fe6ec76f895243127a6a918c37c6a34e2]
- clean-import warning: UV coordinate summary preservation could not be verified for: CBM_demo_instance_post__LOD0__BATCH0003, CBM_demo_instance_post__LOD1__BATCH0001, CBM_demo_instance_post__LOD2__BATCH0002, demo.boolean.block__LOD0, demo.boolean.block__LOD1, demo.boolean.block__LOD2, demo.curve_pipe__LOD0, demo.curve_pipe__LOD1, demo.curve_pipe__LOD2, demo.custom_pyra... [truncated in handoff summary; full warning remains in round-trip evidence; sha256=85b7312161fd27ec48de8cdbce851a2289f1507ebf40517d8fcf78860b1baa06]

Blender procedural master shaders are not assumed to survive interchange. Use only the portable channels recorded in material_mapping.json unless the destination plan explicitly authors an approved replacement.
