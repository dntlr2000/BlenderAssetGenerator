# Packaging subsystem instructions

Before editing this directory, read:

- [Packaging and handoff](../../../docs/agent/packaging_and_handoff.md)
- [Evidence hashing and history](../../../docs/agent/evidence_hashing_and_history.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

Normative focus: CBM-INV-028..035, CBM-INV-041..044, CBM-INV-055..058, CBM-INV-149..150, CBM-INV-181..185, and CBM-INV-192.

Never mutate canonical authoring data. Each format has independent exact source, plan, approval/authorization, package, loss, dependency, and clean-import evidence. Reject overwrite, missing files, links, absolute/escaping paths, stale inputs, and cross-format pass borrowing. Review bundles are not packages.

