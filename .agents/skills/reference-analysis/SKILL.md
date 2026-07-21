---
name: reference-analysis
description: Generate and interpret deterministic image diagnostics and camera assumptions before SceneSpec authoring.
---

# Reference analysis

- Run `analyze_reference` once sources are registered.
- Inspect content bounds, edge map, symmetry, dominant colors, source kinds, scale anchors, line clusters, and projection confidence.
- Do not promote heuristics to measurements.
- Record unresolved camera distance, principal point, depth scale, and hidden surfaces.
- Use explicit user hints to lock projection, focal length, azimuth, or elevation.
- Populate `modeling_plan.json` with objects and geometry strategy before SceneSpec.
