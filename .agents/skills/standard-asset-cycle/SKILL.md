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
10. For `full_cycle_to_package`, stop after exact `qa.review` completion for a separate hash-bound human quality disposition; only `accepted` may plan V0.7, while `needs_revision` may use only the remaining guarded revision budget.
11. Resume from the run-owned skill snapshots and receipt chain, even when live SKILL.md files later change.

The optional reference-fidelity companions can organize independently observed structure, nonhuman findings and exact before/after renders in new Standard work. They do not activate the AQ revision loop or replace V0.8/manual_guarded approvals. Route large volume/section/part-relation failures to V0.4 candidate authoring and renewed exact geometry review; reserve bounded V0.6 scalar revision for local errors. Preserve existing accepted Standard evidence and rerun affected V0.5/V0.6 stages after an approved change.
12. When an exact host failure must be superseded by geometry correction, use only the hash-bound guarded-geometry recovery option on the existing resume surface; preserve the failed child, do not retry it, route the fresh V0.4 child through `manual_guarded`, and create no technical user-approval request.
13. If an older untouched recovery child was incorrectly planned as `candidate_review` for custom-mesh redesign, bind its exact state hash, cancel it with an immutable receipt, and append one `manual_guarded` replacement through the same resume surface. Never reroute an attempted or completed candidate except an exact completed evaluation that improved direct score without silhouette regression, is nonpromotable solely because the geometry change stales authored V0.5 surface-detail bindings, has no promotion approval, and leaves the canonical baseline unchanged. Preserve that decision and cancellation receipt, require a new exact `detailed_geometry` approval for the same QA-candidate operations, then force fresh V0.5 and V0.6 evidence.
