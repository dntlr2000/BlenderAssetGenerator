# Bounded planar cubic chain sampling

This is an opt-in, pure Python host helper. It accepts explicitly authored planar
cubic Bézier controls and emits point tuples usable as existing path data. It
does not add a SceneSpec, schema, runtime setting, approval surface or workflow.
Existing callers and default behavior remain unchanged; use is explicitly opt-in.

## API

```python
from codex_blender_modeler.structural_geometry.cubic_bezier_sampling import (
    CubicBezierSpan, SamplingLimits, sample_cubic_bezier_chain,
)

result = sample_cubic_bezier_chain(
    [CubicBezierSpan("route:0", ((0., 0.), (0., 1.), (1., 1.), (1., 0.)))],
    tolerance=0.001,
    limits=SamplingLimits(
        max_depth=24, max_points_per_span=4096,
        max_total_points=4096, max_work=16384,
    ),
)
path = result.points
serialized_path = result.float32_points
```

`result.spans` preserves a normalized immutable copy of the authored controls.
Every `result.segments` entry retains the original `span_index` and `span_id`,
the exact dyadic `parameter_start`/`parameter_end` in that span's [0,1] domain,
the two indices into both returned paths, the subdivision depth and two exact
reduced integer ratios `source_bound_squared`/`float32_bound_squared`.
For ratio `(n,d)`, the continuous squared distance is no greater than `n/d`.
Ratios avoid a misleading rounded-down floating display of the bound. They
are ordinary JSON-compatible data after dataclass serialization. `work_count`
records the actual number of visited subcurves.

Parameters are local source parameters, not arc length. For a source spline
knot interval [a,b], a caller can evaluate support at `a+t*(b-a)` using the
retained span identity. The helper never certifies that support interpolation.

## Why the bound covers the continuous curve

Each cubic is a convex combination of its four controls for every parameter
in [0,1]. Distance to a closed line segment is a convex function, so the
maximum of the four control-to-segment distances bounds distance from every
curve point to that segment. Segment distance clamps the projection to the
finite endpoints; using the infinite supporting line would miss reversals and
overshoots.

Subdivision uses exact rational de Casteljau arithmetic on the exact binary64
input values. The split source curve is therefore unchanged. For each leaf,
the four rational controls are tested against each actual emitted chord:
first binary64 coordinates, then `struct.pack`/`unpack` binary32 coordinates.
Squared distances and the squared tolerance are compared as exact rationals.
There is no floating epsilon or finite-probe acceptance. The returned exact
squared ratios are bound to the returned controls, intervals and coordinates.

The helper additionally requires each exact curve endpoint to be within
tolerance of its own emitted vertex in both representations. Failure means
that required vertex representation cannot meet this contract; it is not a
proof that every other possible sampling schedule is impossible.

## Scope and coordinate space

The guarantee is directed source-curve-to-corresponding-chord distance. It does
not establish parameterwise correspondence, arc length, reference fidelity,
topology, nonintersection, width, 3D support or mesh validity. No 3D API is added
because the current path consumer is planar and its 3D support is a separate
construction. A long flat span may emit just two points; consumers that need
stations for support or width variation must author suitable source spans.

Pass controls in the final coordinate system being certified. A pixel-space
float32 certificate does not certify later affine XZ mapping, translations,
unit conversion, support projection, extrusion or mesh serialization. The
Crystal demonstration converts the spline to final XZ meter-space controls
before sampling. Its rounding difference from SciPy is measured separately;
the exact certificate covers the converted binary64 cubic controls only.

Authored span endpoints are never smoothed or simplified. Shared joins occur
once and must match exactly as binary64 bytes, including signed zero. Constant
spans are rejected explicitly. A nonconstant closed span can subdivide into
nonzero chords. Any still-collapsed chord at the caller's depth cap reports
`depth_exhausted`; collapse does not prove global precision impossibility.

## Limits and refusals

All four limits are required explicitly. Fixed hard caps are 128 spans, 24
subdivision levels, 4096 points per span, 4096 points for the chain and 16384
visited subcurves. Coordinates have magnitude at most 1e6. Tolerance is finite
and in (0,1e6], in the same units as the controls. Numeric inputs are built-in
ints or floats, never booleans, strings, NaN or infinity. Materialized bounded
containers must be exact built-in lists or tuples; subclasses, generators and
custom sequences are rejected before traversal. Inputs must be exact
`CubicBezierSpan` and `SamplingLimits` instances. IDs are unique nonblank built-in
strings of at most 128 characters, without subclasses. This prevents overridden
iteration, attribute or hash methods from escaping the bounded pure-data contract.

A visited subcurve performs at most eight exact point-to-segment distance
tests and one midpoint subdivision. Input float exponent sizes, coordinate
range and maximum depth bound rational operand sizes. Work, depth, per-span
point and total point exhaustion all raise `CurveSamplingError`, whose stable
`reason` and optional `span_id` identify the refusal. No exception exposes a
partial path and no fallback emits underresolved geometry. There are distinct
reasons for endpoint precision refusal and nonfinite output. A valid bound is
never evidence that a downstream shell or sweep accepts the path.

## Validation and integration

The source delta is one module. Tests and this documentation are additive.
The task-local test conftest extends only the current interpreter's package
search path to use this file next to unchanged MAIN modules; it is not runtime
integration. `scripts/run_checks.py` saves each exact command, source hashes,
exit code, stdout, timestamps and isolated temp directory in a new receipt.

Focused tests exercise a cubic that passes the previous quarter/mid/three-
quarter probes despite exceeding its tolerance at t=1/3, loops, inflections,
reversals, cusps, long straight spans, translation/rescaling, exact threshold
comparisons, original endpoint bits, actual float32 bytes, signed-zero joins,
all independent budgets, invalid inputs, deterministic output and refusal
instead of collapsed stations. Independent dense sampling is corroboration,
not the proof. Recipe-side conversion uses the already available system SciPy;
the core and its tests use MAIN's existing environment without new dependencies.

Before integration, copy only the additive source/tests/docs through the
parent's reviewed source-delta process. Do not overwrite previous receipts,
edit the frozen authoring recipe, change public imports/settings, or infer asset
or human acceptance from passing helper tests. No native Blender claim is made
by this helper's pure-data tests.
