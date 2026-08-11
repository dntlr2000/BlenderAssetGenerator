# Packaging and Destination Handoff

V0.7 operates only on run-owned derivatives and never mutates canonical authoring data. Each format has an exact profile, preflight, review plan, approval, source fingerprint, package manifest, dependency hashes, cost/loss evidence, and clean-import roundtrip. GLB, FBX, and OBJ outcomes are independent; one format cannot borrow another format's pass.

Preserve raw PBR channels and explicit packing semantics. A package is accepted only when contained relative paths, dependencies, imported bounds, and declared semantic/material coverage pass. Review-only output is not a package.

Destination Handoff starts only from an accepted supported package, has its own exact plan-hash approval, and never writes a destination project. Package/handoff recursive file enumeration must agree under Windows long-path handling. Never add files after immutable finalization or claim engine/runtime parity.

Primary rules: CBM-INV-028..035, CBM-INV-041..044, CBM-INV-053, CBM-INV-055..066, CBM-INV-078, CBM-INV-080, CBM-INV-096, CBM-INV-117, CBM-INV-149..150, CBM-INV-162..170, CBM-INV-181..185, CBM-INV-192.

