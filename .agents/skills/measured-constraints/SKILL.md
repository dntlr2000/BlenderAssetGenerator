---
name: measured-constraints
description: Encode dimensions and alignment requirements, evaluate them against Blender inventory, and turn residuals into minimal revisions.
---

# Measured constraints

1. Initialize `constraints/constraints.json`.
2. Use semantic IDs from SceneSpec and `__scene__` for an overall bounding dimension.
3. Add tolerances explicitly; do not imply zero-tolerance manufacturing accuracy.
4. Build and inspect before evaluation.
5. Run `evaluate_constraints` and review every failed or missing result.
6. Use a guarded RevisionPlan for corrections.
7. Rebuild, inspect, and re-evaluate until accepted or under-constrained.
8. Report residuals in meters and distinguish dimensional validation from visual similarity.
