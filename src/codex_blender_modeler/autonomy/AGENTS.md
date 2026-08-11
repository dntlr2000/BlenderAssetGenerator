# Autonomy subsystem instructions

Before editing this directory, read:

- [Autonomy and controller safety](../../../docs/agent/autonomy_safety.md)
- [Approvals and authorization](../../../docs/agent/approvals_and_authorization.md)
- [Evidence hashing and history](../../../docs/agent/evidence_hashing_and_history.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

Normative focus: CBM-INV-101..112 and CBM-INV-175..192.

Preserve AQ 0.1 and autonomous_static_prop_v1 serialization, hashes, producer IDs, budgets, transitions, and terminal meaning. New companion versions dispatch explicitly; they never rewrite v1 evidence. Candidate, material, quality, package, review, recovery, and controller phases remain bounded and exact-evidence driven. Only strict promotion services may replace canonical state.

