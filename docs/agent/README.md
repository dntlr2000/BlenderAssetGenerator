# Agent instruction map

The root AGENTS.md contains repository-wide sentinels. Leaf AGENTS.md files narrow the reading set without weakening the root. Before editing a subsystem, read the leaf file and its linked guides.

## Normative layers

1. Root sentinels: absolute repository rules.
2. invariant_catalog.md: exact CBM-INV-001..192 compatibility text.
3. Topic guides: practical cross-indexes into the invariant catalog.
4. Leaf AGENTS.md: subsystem-specific required reading and checks.
5. workflow_reference.md: preserved operational procedures.

A lower layer may narrow authority but may not broaden it. RULE_POLICY declarations are machine-checked; duplicate keys must have identical values.

## Topic routing

| Work | Required guide |
|---|---|
| canonical inputs, versions, evidence roles | source_of_truth.md |
| plans, approvals, authorization, promotion | approvals_and_authorization.md |
| hashes, immutable history, snapshots, receipts | evidence_hashing_and_history.md |
| Blender builders, subprocesses, render/build provenance | blender_execution.md |
| optimization, packages, roundtrip, handoff | packaging_and_handoff.md |
| AQ, production dispatch, controller, phase tools | autonomy_safety.md |
| tests, CI, verification claims, registries | testing_and_verification.md |
| step-by-step V0.4–V0.9 procedures | workflow_reference.md |

The invariant catalog carries the original English rule text to avoid translation drift. Topic guides may be concise but must reference stable RULE_ID ranges.

