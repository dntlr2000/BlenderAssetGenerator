# Exterior refinement and exported texture semantics

These additive scripts support explicit staged asset studies. They do not write
canonical job state, grant approval, broaden a geometry recipe, or replace an
existing native validation or package gate.

## Bounded geometry/material primitives

`scripts/replay_exterior_surface_refinement.py` provides deterministic pure data
operations. Every changed geometry coordinate is checked against an explicit
maximum displacement and quantized to the same IEEE-754 binary32 precision used
by Blender. Faces and loop UVs are not accepted as outputs from these operators;
the caller preserves them and revalidates the current MeshPayload contract.

- `quadratic_depth_regularize` fits a full-rank quadratic from explicitly selected
  source samples in an orthonormal frame, then changes only explicitly weighted
  target depth coordinates. Zero weights lock selected boundaries. This can remove
  accidental high-frequency radial corrugation on a thin shell's inferred rear.
  It does not recover unseen geometry or authorize flattening observed structure.
- `fair_ring_profiles` rounds explicitly weighted ring cross-sections without
  changing longitudinal stations or array topology. Its applicability requires a
  known regular ring layout; it is not a generic automatic smoothing step.
- `normal_strength` attenuates tangent-normal slopes and renormalizes the field.
- `oxide_metal_response` uses an existing material mask to give conductive exposed
  metal a distinct response from porous dielectric oxide. Resulting physical
  parameters remain design hypotheses, not measurements from a photograph.

New data must be written into a new staged MeshPayload and paired SceneSpec,
source hashes, source geometry intent and material bindings. Any modifier must
be declared in the SceneSpec and rebuilt through the native BAG builder. Actual
F32/geometry/UV/material/export/import tests and matched camera/light views remain
required. Never patch a saved Blender model and omit the corresponding recipe.

## Embedded GLB normal audit

`scripts/audit_glb_texture_semantics.py` is read-only. It follows each material's
actual `normalTexture` pointer into the embedded image bytes. It checks container
extents and indices, image channel mode, normalized vector-field plausibility,
and optionally exact decoded RGB identity against a hash-bound expected map.
File/image names are deliberately not evidence of channel semantics.

The explicit expected-map JSON is a mapping from exact material names to objects
with `path` and `sha256`. A mismatched or stale source fails closed. A material
without a normal texture is merely absent from this channel domain unless a
normal map was expected. This is not a guarantee about all materials, UV coverage,
renderer appearance, or any game engine.

The 2026-10-03 actual-asset study exposed a raw export failure in a Wood authoring
material with a Normal Map feeding a Bump node. The raw glTF exporter referenced
the grayscale height image in `normalTexture`. Array normal/UV regression did not
detect this shader-image semantic error. The correct remedy is the existing
native BAG Cycles tangent-normal bake over the actual mesh, followed by explicit
portable material rebinding to that baked RGB normal. Keep the original normal,
height and authoring shader bytes as immutable sources. Do not rename, zero, or
discard the height image and call that preservation.

The regression suite includes grayscale data named `normal`, replicated-RGB
height data, valid normal pixels named `height`, exact expected-channel mismatch,
stale source bindings, malformed GLBs, invalid indices and bounded-geometry
negatives. Passing these tests cannot establish human appearance acceptance.
