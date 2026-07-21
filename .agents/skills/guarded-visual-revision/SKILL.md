---
name: guarded-visual-revision
description: Convert V0.6 QA findings into hash-bound, user-approved, single-use SceneSpec revisions and verify convergence.
---

# Guarded visual revision

1. Start from a persisted VisualQAReport and exact SceneSpec/camera hashes.
2. Suggestions from a generated target alone are always manual review items.
3. Restrict executable candidates to whitelisted SceneSpec paths and mark them `approval_required`; external custom-mesh payload changes require manual work.
4. Lock the comparison camera and every unrelated object/material ID.
5. Compile only explicitly selected candidates into the existing RevisionPlan contract.
6. Require an explicit, hash-bound, single-use user approval before application.
7. Archive the prior SceneSpec, apply once, rebuild, rerender with the same camera, and reevaluate constraints.
8. Accept the revision only if direct-reference score improves and measured constraints do not regress; otherwise report rollback required.
