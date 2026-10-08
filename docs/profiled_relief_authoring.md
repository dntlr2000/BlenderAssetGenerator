# Explicit polygon-profile relief authoring

This opt-in, host-only helper emits the existing `TriangulatedShellGeometry` contract. It introduces no schema, CLI/MCP tool, Blender execution hook, canonical writer, approval, material policy, or automatic migration. Candidate authoring and native materialization keep their existing guarded boundaries. The prototype is baseline-informed: learning that shallow lips, ridges and troughs need actual shaped sections does not make its closed geometry equivalent to open direct-Blender ribbons, or establish visual parity.

```python
from codex_blender_modeler.structural_geometry.profiled_relief import (
    build_profiled_relief_ribbon,
)

shell = build_profiled_relief_ribbon(
    [(0.0, 0.0), (0.6, 0.2), (1.2, 0.25), (2.0, 0.0)],
    profile=[(-0.5, 0.5), (0.0, -0.5), (0.5, 0.5)],
    width=[0.08, 0.16, 0.12, 0.04],
    depth=[0.04, 0.08, 0.02, 0.01],
    center_y=[0.0, -0.03, -0.08, 0.02],
)
```

## Coordinates and explicit shape

The route is an open sequence of `(X, Z)` controls in asset-local meters. The section is a simple closed polygon in normalized `(lateral, Y)` coordinates, spanning exactly `[-0.5, 0.5]` on both axes; do not repeat its first point. Profile coordinates between those extrema are retained exactly. Negative Y faces the reference camera. The lateral frame is the left normal of the route direction, with a miter at a bend. Reversing the route reverses this lateral interpretation. Either section winding is accepted; output always winds outward.

`width` and `depth` are positive numbers or explicit positive per-station arrays. `center_y` is a finite number or a matching per-station array. These numeric controls support authored taper and sampled support-surface depths without callbacks. A zero-width or zero-depth apex is rejected. End caps are planar, butt-ended, and closed. This helper does not subtract a groove from another solid or merge intersecting assembly objects. A trough is a real concave section, with its own bottom and back faces; placement against another component is still assembly authoring.

Useful section examples:

- Triangular ridge: `[(-.5,.5), (0,-.5), (.5,.5)]`
- Five-point trough: `[(-.5,.5), (-.5,-.5), (0,-.1), (.5,-.5), (.5,.5)]`
- Chamfered ridge: `[(-.5,.5), (-.5,-.2), (-.2,-.5), (.2,-.5), (.5,-.2), (.5,.5)]`

Input corners remain geometric planes. Smoothing, materials and UVs stay caller intent. For `N` route stations and `P` section points, output has exactly `N*P` vertices and `2*N*P-4` triangles. A four-station triangular rail is 20 triangles; a four-station trough is 36. These counts describe a closed shell and include both end caps. Comparisons against open ribbons must report that topology difference.

## Ordering and numeric safety

Vertices are station-major, then the original profile order. The first `P-2` triangles cap the first station, the next `P-2` cap the last; remaining triangle pairs follow route segment then profile edge. Concave caps use the established deterministic ear clipper. The helper emits no UV data; stable face/vertex order makes explicit per-face palette or UV authoring possible.

The closed profile accepts 3–16 points; the open route accepts 2–128 stations. Maximum output is 2,048 vertices and 4,092 triangles. Explicit list/tuple arrays are required; unbounded iterators are rejected before traversal. Coordinates and dimensions remain inside the existing ±1,000,000-meter shell envelope. Footprint predicates normalize by the maximum route/dimension/Y-offset extent, with a `1e-10` degeneracy tolerance. The inherited shell validator additionally imposes its existing absolute triangle-area floor. Thus very small physical triangles may fail even when their normalized shape is valid.

Miters are limited to less than four times the half-width; cusps at or beyond that bound fail closed. Every footprint cell must be strictly convex, adjacent cells must be on opposite sides of their shared station edge, and nonadjacent cells must be disjoint without touching. This is deliberately conservative: wide turns that might be constructed through a more elaborate joint are refused rather than silently narrowed, beveled, or repaired.

Footprint checks alone do not certify the triangulation of a strongly tapered or concave section. The emitted triangles also undergo an inclusive AABB sweep and exact rational plane/clip predicates. Only an indexed common edge or vertex is permitted contact; self-crossings, interior overlap and non-indexed contact are rejected. The exact predicates reuse the existing standard-library `self_intersection_runtime`; that module has no `bpy` dependency. Each embedding pass permits at most 32,768 exact candidate-pair tests. Budget exhaustion is an error, never a clean pass. The bounded 4,092-triangle envelope also bounds the broad-phase pair scanning.

The same closed-shell and exact-embedding checks run on read-only float32-rounded coordinates before the original double-coordinate shell is returned. This detects native Blender storage collapse, winding loss and new intersections at large offsets or tiny dimensions. It does not promise identical double and native coordinates or a camera-space visual error bound. There is no repair or implicit increase in thickness. A caller changing vertices afterward invalidates this proof and must validate its changed geometry again. Assembly intersections with other objects are outside the helper's single-shell proof.

## Sparse faceted gem sections

Use existing `LoftGeometry` with `correspondence_policy="index"`, explicit sparse `LoftSection`s and flat shading for equal-edge section rings. Three four-point diamond sections yield a 20-triangle closed gem. No extra gem helper or contract is needed for that case.

The existing loft compiler resamples all sections at equal arc length, even when `resample_count` equals the original count. Equal-edge rings retain their corners; irregular unequal-edge rings generally do not. Do not describe that resampling as exact corner preservation. Where exact asymmetric facet anchors matter, author the existing explicit `TriangulatedShellGeometry`/mesh contract with deliberately chosen planes and triangles. This prototype does not modify loft behavior or silently change legacy fixtures.

## Verification boundary

Pure tests cover section/winding retention, concave troughs, width/depth/Y taper, scale changes, malformed inputs, finite work exhaustion, conservative bend refusal, exact improper contacts, float32 collapse, and both loft cases. Opt-in native tests materialize through the existing structural service with MeshPayload 0.2, then open each saved blend in Blender 5.0.1 and independently measure BMesh manifold/contiguous edges, vertex manifoldness, signed volume, triangle area and exact native self-intersection. Native BVH candidate counts are diagnostic, not a substitute for exact triangle classification. The helper validates topology; visual quality still needs the actual reference/camera comparison.
