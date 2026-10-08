# Efficient contour relief authoring

`structural_geometry.contour_relief` is a host-side data helper. It produces the existing `TriangulatedShellGeometry`; it adds no geometry schema, CLI/MCP tool, execution hook, material authority, or promotion path. Existing guarded candidate authoring and materialization remain required.

Use it for a plate, a shell with a rounded edge and planar core, or a narrow structural rail. Keep broad silhouettes, physical openings, attachments, rails and bezels as authored geometry. Shallow engraving and color/normal detail belong in the existing bounded surface-detail/material workflow. A rounded edge with a planar core does not reproduce an inflated dome and is not automatically a reference-quality improvement.

## Functions

- `build_contour_prism(points, *, depth, center_y=0.0)` makes a closed concave prism with minimal planar caps
- `build_contour_relief_shell(points, *, depth, bevel_width, bevel_depth, max_chord_error, center_y=0.0, inset_points=None)` makes a closed shell with elliptical bevels on both sides
- `build_relief_ribbon(points, *, width, depth, bevel_width, bevel_depth, max_chord_error, center_y=0.0)` makes an open-route, butt-ended structural ribbon

Points are asset-local `(x, z)` in meters; negative Y faces the reference camera. Width may be a scalar or a matching sequence. Shell bevel width may likewise be a per-corner sequence so a thin tip can have an explicitly smaller bevel. Depth and bevel depth are positive; bevel depth must be less than half the depth. `inset_points` is an optional same-count, same-order authored inner contour and overrides automatic inset construction. Its validity is checked, not inferred. There are no callbacks or arbitrary surface functions.

The original contour is retained exactly. No smoothing, simplification, resampling, automatic width clamping, or corner deletion occurs. Author curved contours with a separately measured projection tolerance and retain important sharp/attachment controls. Self-intersections, repeated points, overlapping rails, collapsed/reversed inset bands and invalid cap triangulations fail visibly. Reduce the explicitly authored local bevel width, supply valid inset controls, or use a prism when the intended tip cannot support the selected bevel.

## Error and triangle cost

For each bevel vertex, the authored cross section follows a quarter ellipse from the exact outer boundary to the explicit inner contour. For N contour points and S segments per bevel, the closed shell has `2*N*(S+1)` vertices and `4*N*(S+1)-4` triangles. Each planar cap always has N−2 triangles, independent of its area. A prism has `2*N` vertices and `4*N-4` triangles.

The requested `max_chord_error` is a metric error bound relative to that authored ruled elliptical bevel. Let R be the largest bevel ellipse radius, D the conservative geometric twist bound described below, and delta the angle step. The helper requires:

`R * (1 - cos(delta/2)) + D * sin(delta)/4 <= max_chord_error`

The first term bounds elliptical chord approximation; the second bounds triangulation of potentially twisted ruled strips. For each outer edge e and corresponding inner edge f, start with `|f-e|`. When `e dot f >= 0`, additionally bound it by `|cross(e,f)|/q`, where q is the shortest length of `e+t*(f-e)` for t in [0,1]. Use the smaller valid bound, then take the maximum across edges. At each fixed Y, triangulation introduces one kink into the straight ruled slice; the nonnegative dot product keeps its projection within the slice. This removes tangential shortening from coplanar bands without ignoring actual nonplanarity. Reversed edge directions retain the full conservative bound.

The error does not describe a source image, a dome, or a different modeling recipe. Reducing error generates additional bevel rings while retaining the same outline and cap surface. Independent dense sampling of a square fixture with depth .41m, width .06m, bevel depth .071m and error .0015m found .001039m maximum error at 92 triangles, compared with 524 triangles under the earlier parameter-space-only bound.

Input is limited to 512 contour controls or 256 ribbon route controls before quadratic boundary/band predicates. Ear clipping also stops after 1,048,576 point tests. Output refinement respects the existing shell limit of 65,536 vertices and 131,072 triangles. Exhaustion rejects the request without returning a partial shell or dropping controls. These are local helper implementation bounds, not changes to AQ authorization or resource budgets.

## Identity, faces, UVs and shading

The result is the existing strict closed-shell object. Original outer points occupy the first N front vertices and next N rear vertices, in the original order, for both clockwise and counterclockwise input. Those anchor indices are stable across error settings. The first N−2 faces are front-cap triangles and the next N−2 are rear-cap triangles. Remaining faces connect bevel and side rings. Inner-ring indices depend on refinement and must not be reused as if topology were unchanged.

No UVs, materials, sharp edges or smoothing intent are invented. Bind these through existing geometry intent and material authoring. The caller can use cap-first ordering to preserve planar shading and distinguish bevel/side faces. Boundary attachment/seam anchors are available, but the helper does not import or migrate an existing mesh's UVs or semantic assignments.

## Validation

Pure tests cover both contour windings, concave brackets, forked rails, organic plates, exact and near-collinear anchors, scale changes, thin tips, explicit insets, boundary stability, positive closed volume, cap-area coverage, measured bevel chord error, deterministic output and fail-closed invalid inputs. Opt-in tests materialize six representative fixtures through the unchanged fixed Blender builder and revalidate the emitted geometry and identity.

Run `pytest tests/test_contour_relief.py`. For native evidence, select supported Blender 5.0.1 via `BLENDER_BIN` and run `CBM_RUN_AUTONOMOUS_GEOMETRY_SMOKE=1 pytest tests/test_contour_relief_blender.py`. The latter is opt-in, not evidence of destination-engine parity or final visual acceptance.
