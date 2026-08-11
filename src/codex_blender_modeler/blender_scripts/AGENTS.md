# Blender-script subsystem instructions

Before editing this directory, read:

- [Blender execution](../../../docs/agent/blender_execution.md)
- [Source of truth](../../../docs/agent/source_of_truth.md)
- [Packaging and handoff](../../../docs/agent/packaging_and_handoff.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

Normative focus: CBM-INV-003..024, CBM-INV-028..044, CBM-INV-113..150, and CBM-INV-189.

Blender modules execute only validated whitelist contracts. Do not add arbitrary code paths. Preserve meter/axis semantics, stable IDs, loop UVs, material indices, normals/smoothing, geometry intent, build provenance, temporary-camera isolation, and deterministic failure behavior. bpy-dependent modules must never be imported by Python-only registry or CI checks.

