# Bounded shared-material atlas validation

Existing `spatial_v1` material contracts may use one shared texture atlas without
splitting stable material identities. This is a narrow exception to the existing
single-parent rule, selected only by every affected `SurfaceDetailDecision` using
`uv_strategy: material_atlas`. No schema, approval, default policy or old artifact
is migrated.

The exception requires all of the following:

- Every actual material consumer has explicit bindings. Extra, missing, duplicated
  or ambiguous users and material identities are rejected
- Each parent has one normalized `uv_rect` cell; multiple detail bindings for the
  same parent must agree on its cell. Cells of different parents cannot overlap
- Current path-backed custom-mesh payloads supply explicit UVs. Legacy vertex-UV,
  strict Standard loop-UV, and strict MeshPayload 0.2 loop-UV dialects are supported
  under their existing contracts. Other builders and ambiguous multi-material
  V02 payloads retain the shared-material refusal
- Host validation reconstructs the exact ordered polygon-corner fingerprint from
  current mesh data, with Blender float32 storage semantics. It requires all used
  UV corners inside the parent's cell, inset by at least two source texels. Since
  the cell is convex, polygon UV interpolation remains in the same cell. Merely
  declaring disjoint rectangles cannot prove this condition
- All bound raster channels must decode to the declared atlas dimensions. Native
  inspection independently checks actual loaded image dimensions; an inflated
  resolution cannot shrink the required source-texel inset
- Existing native inventory hash checks remain required. Native material
  inspection independently measures both source and evaluated UV footprints,
  catches modifier-induced escape, and verifies actual image/identity-UV graph
  bindings. Missing native evidence is not replaced by host declarations
- Material fidelity reporting applies the same current-source proof and includes
  the mesh payload bytes in its input hash map

Missing/stale hashes, nonfinite UVs, unsupported versions, linked payload paths,
out-of-cell occupancy, incomplete coverage, overlapping cells and ambiguous
material users remain failures. Single-parent and legacy-unbound behavior is
unchanged.

This establishes bounded UV ownership, not artwork accuracy, texel density,
texture quality at every mip level, arbitrary filtering behavior, physical
attachments, clean-import equivalence or final human acceptance. It does not
approve any source or material change. Actual reference comparison, native
inspection, portable conversion and clean import remain separate evidence.
