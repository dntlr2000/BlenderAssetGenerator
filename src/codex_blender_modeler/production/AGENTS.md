# Production subsystem instructions

Before editing this directory, read:

- [Autonomy and controller safety](../../../docs/agent/autonomy_safety.md)
- [Approvals and authorization](../../../docs/agent/approvals_and_authorization.md)
- [Evidence hashing and history](../../../docs/agent/evidence_hashing_and_history.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

Normative focus: CBM-INV-157..179 and CBM-INV-187..192.

The delegated controller is the sole canonical writer; assignments and external controllers are bounded candidate producers or advisers. Preserve exact launch, binding, phase-profile, source, transition, postflight, and receipt chains. desktop_in_session is workflow-contract-only, not an attested sandbox. Server tools, project-enabled tools, and phase profiles are distinct.

