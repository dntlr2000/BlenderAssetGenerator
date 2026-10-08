# Continuous projected centerline coverage

`structural_geometry.support_coverage.inspect_projected_centerline_coverage(points, *, support_vertices, support_triangles)` is a read-only, opt-in host inspection utility. It accepts explicit `(X, Z)` centerline controls, existing mesh-style `(X, Y, Z)` vertex arrays, and indexed triangular faces. It introduces no schema, CLI/MCP operation, callback, approval state or automatic authoring rule. Existing geometry and prior receipts remain unchanged.

The result answers one narrow question: does the union of the support triangles projected onto XZ contain every point along every supplied centerline segment? It does not establish coverage of a ribbon's width, Y contact, solid intersection, mechanical support, appearance or whether a deliberate bridge is appropriate. Support triangles far away in Y can satisfy this projection test. A negative result provides review evidence; it never changes the model or prohibits bridging automatically.

## Exact intervals, not samples

Each source finite coordinate is interpreted as its exact binary floating-point value. The utility clips every segment against each projected triangle's closed half-planes with rational arithmetic and unions the resulting closed parameter intervals. Inclusive exact bounding boxes skip only disjoint pairs. Triangle seams and shared outer edges count as coverage. A valid vertical 3D triangle whose XZ projection is a segment retains that line coverage. Degenerate 3D triangles are unsupported.

For centerline segment `i`, parameter `t` denotes `points[i] + t*(points[i+1]-points[i])`, where `0 <= t <= 1`. Uncovered intervals contain:

- `segment_index`
- `t_start` and `t_end`, exact rational strings such as `3/8` or `1`
- `start_inclusive` and `end_inclusive`

Interior gap endpoints lie on closed support, so their inclusion flags are false. An unsupported original path endpoint has its inclusion flag true. Parse the strings with `fractions.Fraction` when exact follow-on calculations are needed. Converting them to float can hide a tiny gap; the returned exact strings do not. Neither an epsilon nor a sampling step closes a gap.

An available result has `availability="available"`, a Boolean `passed`, and a complete `uncovered_intervals` list. An unavailable result has `availability="unavailable"`, `passed=None`, `uncovered_intervals=None`, and an explicit reason. Unsupported or exhausted evidence is never converted to a pass or a fabricated coverage failure.

## Bounded domain

Inputs must be explicit lists or tuples. Centerlines have 2–129 points and no zero-length segment. Support arrays have 3–65,536 finite bounded vertices and 1–131,072 three-index triangles. Coordinates stay within the existing ±1,000,000-meter envelope. Triangle indices must be distinct in range; 3D triangle area must be nonzero under exact predicates. Support need not be closed or manifold, and overlapping/repeated support faces simply participate in the union.

The product `(centerline_points - 1) * support_triangles` may not exceed 131,072. This bounds the complete Cartesian scan, including pairs rejected by bounding boxes, before any geometric work. `segment_triangle_pairs_considered` records that product; `exact_triangle_clips` records the pairs that reached clipping. Oversized inputs, unbounded iterators, malformed data, nonfinite values, unsupported degeneracy and exhausted workload return unavailable evidence.

## Precision and source binding

The utility inspects the supplied coordinates without rounding, repairing or sampling them. To review a native Blender or exported model, pass that model's actual coordinates and triangles. A read-only float32 roundtrip of authoring data is a useful separate storage check, but it is not an inspection of an independently loaded GLB. A one-float32-ULP gap is retained. A source gap that disappears when coordinates are rounded has different source and rounded coverage results; neither result replaces the other.

For the baseline-informed Crystal case, the audit reconstructs each ribbon's centerline as the mean XZ of its contiguous profile station vertices; those authored profiles have symmetric lateral coordinates. Support is the union of each semantic owner's non-modeled subsolids, fan-triangulated in disclosed polygon order. The reconstructed centerline and source SHA-256 are recorded in the audit. This derivation is specific to that fixture and is not hidden behavior in the general utility.

## Measured failure and regression

The preserved `attempt_06` lower-fin vein had supported endpoints yet crossed a cutout between them. Its extracted 130-vertex/256-triangle owner support and actual centerline are retained in `tests/fixtures/profiled_centerline_cutout_crystal.json`, labeled baseline-informed and bound to the original source hash. Exact coverage identifies the interior missing interval. The complete attempt_06 audit finds two uncovered modeled centerlines, including this one.

The corrected attempt_07 audit finds all 51 modeled scroll/vein centerlines continuously covered in source coordinates. This result is limited to projected centerlines; it does not claim ribbon-width support or replace the independent native attachment/intersection review. Synthetic tests cover complete support, triangle seams, external boundaries, multiple segments, arbitrarily tiny rational gaps, float32 source gaps, malformed data and finite-work refusal.
