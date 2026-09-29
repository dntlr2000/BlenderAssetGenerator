# Skill Orchestration 0.1 instructions

- This package is an additive adapter over V0.8 workflows and AQ v2 One-Prompt. It never becomes a canonical asset writer.
- Persist exact skill-registry and skill-resource snapshots before routing a run. Resume from the snapshots, not mutable live skill files.
- A top-level skill invocation authorizes only the registry-declared transitive dependency bundle. Never widen that bundle dynamically.
- Route and execution receipts are projections. They never create, replace, infer, or consume user approval or AQ policy authorization.
- Standard composite execution must preserve every V0.8 agent, generic approval, specialized approval, failed-retry, cancellation, and package boundary.
- A QA repair continuation requires exact source-QA, candidate, plan, consumed approval, application, and applicable convergence evidence; a SceneSpec hash change alone is never authority.
- AQ routing must preserve the existing One-Prompt state, budget, assignment, profile status, and current-task lifetime. Technical recovery never becomes a user approval request.
- Reject unknown, duplicate, cyclic, stale, tampered, linked, escaped, or incomplete registry/run evidence.
- Do not migrate or rewrite historical workflows, AQ sessions, skill runs, receipts, or terminals.

<!-- RULE_POLICY project_skill=explicit_user_opt_in -->
<!-- RULE_POLICY user_changes=preserve -->
<!-- RULE_POLICY project_version=0.9.1 -->
