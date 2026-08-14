# Material-closure subsystem instructions

Before editing this directory, read:

- [Approvals and authorization](../../../docs/agent/approvals_and_authorization.md)
- [Evidence hashing and history](../../../docs/agent/evidence_hashing_and_history.md)
- [Autonomy and controller safety](../../../docs/agent/autonomy_safety.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

Material Closure 0.1.0 is an additive, fail-closed companion layer. Keep it generic:
never embed a job, semantic, session, execution, retry, sequence, or artifact hash from
an incident. Collect and project exact declared dependencies deterministically. Host-owned
repairs may only change declared path/hash provenance; they never change material semantics
or synthesize approval. Only the existing authorized promotion path may write canonical
state, and historical evidence is append-only.

