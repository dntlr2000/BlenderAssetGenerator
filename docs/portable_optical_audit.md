# Exact GLB optical semantics audit

`packaging.optical_audit.inspect_glb_optical_materials(data, expected_sha256=...)`
is an opt-in, read-only host utility. It consumes immutable actual GLB bytes and an
independently expected digest. It does not import a renderer, access external
textures, write a job, grant approval, or replace package/clean-import gates.
Existing schemas, CLI/MCP surfaces, canonical serialization and predicates are
unchanged.

## Why this evidence is separate

A convincing Blender render does not prove that the exported material declares
thick-volume optics. glTF transmission can describe a thin wall. Nonzero
`KHR_materials_volume.thicknessFactor` declares a volume boundary; its use also
requires closed manifold geometry. Thickness textures are estimates for
rasterizers, while ray tracers can use actual path lengths. The audit reports
serialized factors and texture references without pretending to measure those
path lengths or verify the geometry. See the primary [Khronos volume
specification](https://github.com/KhronosGroup/glTF/blob/main/extensions/2.0/Khronos/KHR_materials_volume/README.md).

The returned material mode distinguishes no supported transport, thin-wall
transmission, declared volume transmission, and volume without the supported
transmission route. The result retains IOR, attenuation distance/color, thickness,
exact texture-info records, and extension declarations. Missing attenuation
distance is represented by JSON null plus an explicit unbounded flag; a literal
null in the input is rejected. Texture modulation is unevaluated. The audit covers
all serialized materials, not a claim that every material is visible or assigned
in the active scene.

Every result explicitly marks actual import, destination support, geometry,
rendered refraction, and acceptance authority as unverified/false. A thin-wall
result is useful negative evidence when the requested quality calls for volume
refraction; it is not a blanket rejection of intentionally thin glass.

## Bounded, fail-closed input

The utility accepts only `bytes`, a matching lowercase SHA-256, a complete GLB2
header and one JSON plus optional BIN chunk. It rejects unsupported chunk layouts,
truncation, ambiguous duplicate keys, nonfinite/interpreted out-of-range scalars,
coerced numbers, malformed texture references and inconsistent extension
requirements. Limits are 64 MiB total, 16 MiB JSON, 4,096 materials, 65,536 texture records
and 256 extension names. It is a narrowly scoped audit, not a complete glTF
validator; unrelated mesh/accessor/image semantics remain outside its claim.

## Importer-aware use

Review the exact target importer/version/render pipeline before promising optics.
Unity's current [glTFast feature documentation](https://github.com/Unity-Technologies/com.unity.cloud.gltfast/blob/main/Packages/com.unity.cloud.gltfast/Documentation~/features.md)
labels volume and IOR as planned and documents transmission approximations,
including layered-transparency limitations in the URP opaque-texture path. These
are documentation findings checked on 2026-10-03, not an executed Unity test.
A separate conservative PBR fallback may be useful, but must retain its own exact
artifact, matched-camera images, loss disclosure and clean-import evidence.
Never relabel a Cycles render as Unity-verified or silently hide the fallback's
loss of physical refraction.

Tests cover literal defaults and scalar boundaries, zero-thickness volume,
unsupported transport, texture uncertainty, exact digest binding, malformed
containers, duplicate keys, unknown/required extension consistency and absence
of fabricated engine or acceptance claims.
