---
name: standard-asset-cycle
description: Run one traceable Standard asset cycle across V0.4 geometry, V0.5 materials, V0.6 QA, and optional V0.7 delivery while preserving every approval boundary.
---

# Standard asset cycle

1. Use the Skill Orchestration 0.1 Standard plan surface once and preserve its run ID.
2. Accept only the fixed snapshotted dependency bundle recorded by the host registry.
3. Let the current V0.8 workflow state select the stage skill; never choose a later stage from prose alone.
4. For new assets, run the existing Standard full preview flow through QA and stop before packaging unless the selected goal includes delivery.
5. For existing assets, sequence immutable revision, material, QA, and optional portable workflows as required by the exact goal and stage policy.
6. In `smart` mode, use the exact MaterialImpactReport to decide whether V0.5 must rerun. In `force_all`, execute fresh V0.4, V0.5, and V0.6 stages.
7. Always rerun V0.6 after a canonical geometry or material change.
8. Stop at every agent, generic approval, specialized approval, failed-retry, budget, and cancellation boundary exposed by V0.8.
9. Never infer a user approval or retry authorization from this skill invocation.
10. Resume from the run-owned skill snapshots and receipt chain, even when live SKILL.md files later change.

