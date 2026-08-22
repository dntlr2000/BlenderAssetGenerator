# Packaging and Destination Handoff

V0.7 operates only on run-owned derivatives and never mutates canonical authoring data. Each format has an exact profile, preflight, review plan, approval, source fingerprint, package manifest, dependency hashes, cost/loss evidence, and clean-import roundtrip. GLB, FBX, and OBJ outcomes are independent; one format cannot borrow another format's pass.

Preserve raw PBR channels and explicit packing semantics. A package is accepted only when contained relative paths, dependencies, imported bounds, and declared semantic/material coverage pass. Review-only output is not a package.

`asset-package --content-mode static_payload` is an additive lean-delivery projection for an exact profile that already disables derived levels and uses no physics proxy strategy. It preserves the full optimization/material evidence outside the package through a hash-only `package_provenance.json`, requires `--exclude-colliders`, names the primary asset from the job ID, strips base-level delivery markers from the serialized model, embeds a staging clean-import result, and writes `checksums.sha256`. The default `full_evidence` package remains unchanged. A static payload must fail closed if disabled-feature filenames or serialized settings reappear.

`asset-package-accept` is the host-only terminal acknowledgement for a package created outside a still-current V0.8 package step, including an immutable technical-recovery candidate. It consumes the user's exact package-manifest and post-publication round-trip hashes only after revalidating package receipts, source freshness, clean-import identity, bounds, and semantic/material coverage. The resulting run-owned acceptance receipt is single-use, does not alter package bytes, does not rewrite or reuse an older workflow gate, and performs no destination-project write.

Destination Handoff starts only from an accepted supported package, has its own exact plan-hash approval, and never writes a destination project. Package/handoff recursive file enumeration must agree under Windows long-path handling. Never add files after immutable finalization or claim engine/runtime parity.

Primary rules: CBM-INV-028..035, CBM-INV-041..044, CBM-INV-053, CBM-INV-055..066, CBM-INV-078, CBM-INV-080, CBM-INV-096, CBM-INV-117, CBM-INV-149..150, CBM-INV-162..170, CBM-INV-181..185, CBM-INV-192.
