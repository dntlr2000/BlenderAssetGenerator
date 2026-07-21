---
name: blueprint-calibration
description: Calibrate dimensions and cameras from orthographic drawings, blueprints, dimension lines, CAD exports, or multi-view references for measured modeling.
---

# Blueprint calibration

- Confirm units and drawing scale.
- Prefer explicit dimension lines over pixel measurements.
- Align front/right/top views to a common origin and axis convention.
- Record at least one absolute scale anchor per independent view.
- Correct crop, rotation, and perspective before measuring.
- Solve camera intrinsics/extrinsics when perspective views are used.
- Encode dimensional constraints in `constraints/constraints.json`, with SceneSpec holding the geometry parameters.
- Run `evaluate_constraints` and report residual error and inconsistent dimensions instead of silently averaging.
- Keep a list of under-constrained degrees of freedom.
