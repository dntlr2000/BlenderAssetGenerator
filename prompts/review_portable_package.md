# V0.7 portable package review prompt

Review one explicit profile, optimization run ID, and immutable package ID. Do not select a different latest run when an exact ID was supplied. Do not modify or regenerate canonical SceneSpec, geometry, material contracts, source textures, or the package under review.

Check the following authoritative JSON evidence before presenting the PDF:

1. AssetProfile and exact source/profile fingerprints.
2. MeshPreflightReport status, warnings, and declared exceptions.
3. OptimizationPlan completion plus LOD, collision, and UV manifests.
4. Exact PortableMaterialConversionManifest identity, source/profile/run binding, atlas evidence, raw PBR preservation, and every packed texture's channel mapping, color space, dimensions, and hash.
5. ExportPackageManifest primary format, relative paths, dependency counts, file hashes, semantic/material IDs, known losses, and warnings.
6. RoundTripValidation format import, units/axis normalization, bounds tolerance, identity coverage, UV/normal/tangent, texture, and dependency checks.
7. Canonical source invariance across preflight, optimization, package, and validation.

Evidence priority:

```text
canonical source hashes
→ machine-readable profile/preflight/manifests
→ clean-import round trip
→ derived human-readable PDF
```

Never claim Unity, Unreal, or another runtime's import or shader parity from Blender round-trip evidence alone. Report the destination as unresolved unless the user explicitly selected and separately validated an engine adapter.

Generate the `export` PDF scope alongside the canonical JSON paths and summarize: pass/fail, blockers, warnings, known losses, package location, profile/run/package IDs, and recommended engine-adapter checks.
