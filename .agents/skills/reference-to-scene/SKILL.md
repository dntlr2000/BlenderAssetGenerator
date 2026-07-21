---
name: reference-to-scene
description: Analyze reference images, concept art, isometric scenes, or product photos and convert visible evidence into SceneSpec v0.2 geometry recipes after v0.4 reference diagnostics without inventing false dimensions.
---

# Reference to SceneSpec

1. Run/read v0.4 reference analysis and then identify whether each image is orthographic, weak-perspective, or perspective.
2. Divide it into semantic zones and repeated asset families.
3. Record normalized image coordinates for important regions.
4. Separate observed evidence from inferred hidden geometry.
5. Estimate only ratios unless a scale anchor exists.
6. Choose a simple coordinate frame and fixed comparison camera.
7. Select the simplest recipe matching each shape: primitive, profile extrude, revolve, curve, terrain, then custom mesh.
8. Author `analysis/scene_spec.json` using stable semantic IDs.
9. Put large mesh payloads under `geometry/` and reference them from SceneSpec.
10. Start with large proxy masses; avoid detail until silhouette and layout are validated.
11. Assign confidence values and document ambiguity.
12. Never claim engineering-grade accuracy from concept art alone.
13. Exclude interior geometry by default, including hidden rooms and unrequested floors. Exterior facade helpers may remain exterior-only when they are not represented as interior objects.
14. Author `.interior` semantic IDs or explicit interior tags only when the user requested that scope and the exact current `architecture/interior_scope.json` SHA-256 has a matching user approval; stay inside its prefixes, levels, spaces, furnishing, and evidence limits.
