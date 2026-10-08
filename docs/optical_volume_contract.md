# Experimental constant optical-volume contract

This opt-in addition accepts ShaderRecipe `0.5.1` with an explicit `volume`
companion `0.1.0`. Legacy `0.5.0` remains the default, rejects the new field, and
serializes exactly its old field set. Absent portable volume factors likewise
serialize without a new null field. There is no automatic migration, new CLI,
callback, arbitrary node graph, controller authority or destination-project write.

The initial subset requires a constant/image Principled glass or standard-PBR
surface, positive constant transmission, metallic zero, alpha one, and IOR 1–3.
Procedural recipe layers and source metallic/opacity textures are refused for
this subset. Other existing material routes retain their prior behavior.

All volume fields are explicit: `schema_version`, `thickness_factor`,
`attenuation_distance`, and `attenuation_color`. Thickness is positive and in
mesh-coordinate units. Distance is positive in world units, or null for
unbounded distance. Color has three positive components no greater than one.
Thickness and finite distance stay in `[1e-6,1e6]`; color components stay in
`[1e-6,1]`. This deliberately bounded subset does not approximate invalid data,
accept booleans/strings/nonfinite values, or silently clamp values. A scalar
thickness is an author estimate, not a measured angle-dependent optical path.
A shared material spanning unlike component thicknesses must disclose that loss.

## Native transport and inspection

Only pinned Blender 5.0.1 is supported for this experimental graph. The builder
creates a constant `Thickness` socket on the exporter-recognized glTF material
group plus a connected Volume Absorption node. Its exact serialized contract is
retained in native material metadata. Before conversion/export, actual sockets,
active surface/volume links and constant transmission/alpha are verified. Portable
conversion preserves the factors and builds the same fixed graph. Export reads
actual GLB/glTF material records and compares thickness, attenuation, IOR, exact
transmission, metallic zero and opaque alpha with the pinned float32 socket
projection. Constant thickness and transmission cannot acquire texture modulation.
Each exported object is followed through its reachable node, mesh and primitive
material references, including exact triangle counts. Missing or reassigned optical
objects, unexpected optical users, skins, animations and morph targets fail closed.
No exported GLB is patched. FBX/OBJ output with an assigned opted-in volume is
refused before writing an asset. Unused/orphan materials do not activate opt-in.

Every opted-in object must use one homogeneous volume material. Original used
material slots must agree with actual evaluated material ownership; evaluated
material IDs are resolved through their original owner rather than pointer equality.
Geometry-Nodes-added or changed optical assignments cannot escape inspection.
Transforms are refreshed before inspection and must be rigid, positive-handed and
unit-scale. Object/mesh animation, shape keys and armature transport are refused.
Raw glTF export refuses the mixed shape-key branch; portable packages require
stored materialized meshes without modifiers, matching their `export_apply=False`
serialization path. These restrictions avoid silently mis-scaling mesh-unit thickness
or validating an evaluated solid while exporting a different stored surface.

Actual evaluated world-coordinate triangles undergo exact-position seam reconstruction without
asset mutation, the existing closed connected outward-manifold validator and
bounded exact crossing inspection. Limits remain 4,096 triangles per object,
25,000 total opted-in triangles and 32,768 exact crossing pairs per object. Exhaustion
fails closed. `validate_export_roundtrip.py` repeats the serialized factor/usage
checks and inspects actual clean-import material graphs and closed boundaries.
The pinned importer may multiply a metallic-roughness texture by a constant zero;
that exact zero product is accepted while an uncancelled metallic texture is not.
These checks remain separate from destination-renderer validation.

This checks the documented boundary; it does not replace the
stronger independent complete-solid/root-contact proof, prove optical containment
between nested objects, or establish mechanical strength.

## Explicit limits and independent evidence

The [Khronos specification](https://github.com/KhronosGroup/glTF/blob/main/extensions/2.0/Khronos/KHR_materials_volume/README.md)
distinguishes a thin wall from a nonzero-thickness volume. A ray tracer may use
actual path lengths while a rasterizer uses the approximate thickness input.
Blender 5.0.1's existing importer can show refractive-looking Principled transport
even when the volume extension is absent. Therefore adding volume semantics can
be pixel-identical in Cycles and is never counted alone as a visual improvement.
Color/density translation is the pinned Blender importer/exporter convention;
precise cross-renderer absorption equivalence is not asserted.

Unity glTFast currently documents volume/IOR as planned and transmission as an
approximation in its [official feature list](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/blob/main/Packages/com.unity.cloud.gltfast/Documentation~/features.md).
This documentation check is not a Unity test. A conventional PBR fallback must be
a distinct source-authored artifact with its own exact hashes, clean import and
matched views. Neither extension presence nor a Cycles render grants engine
parity, aesthetic acceptance or production package acceptance.

Tests cover host/native/JSON-schema agreement, legacy serialization, malformed
and unsupported values, portable factor preservation, actual graph construction,
conversion, raw GLB factors, independent import, tampered-socket rejection and
open-boundary rejection. Complete asset source/F32/UV/TBN/root/package evidence
remains a separate obligation.
