# Offline adaptive profile authoring

These optional offline authoring modules produce numeric data. They do not change
production schemas, canonical jobs, controllers, geometry, or approval paths. It
has no Blender, NumPy, callback, shell, or external-execution dependency. All
implementation dependencies are Python's standard library. Tests use the
already installed pytest/ruff environment.

## Use-ready sampler

```python
from codex_blender_modeler.adaptive_sweep_authoring import adaptive_sample, catmull_rom_spans

rows = [
    (0.0, 0.0, 0.0, 0.15, 0.10),
    (0.5, 0.0, 0.2, 0.20, 0.15),
    (1.0, 0.1, 0.1, 0.12, 0.08),
]
spans = catmull_rom_spans(rows)
result = adaptive_sample(
    spans,
    center_tolerance=0.005,
    width_tolerance=0.004,
    height_tolerance=0.004,
    feature_stations=[0.375],
)
sampled_rows = [(*s.center, s.width, s.height) for s in result.samples]
data = result.to_dict()
```

Import from this directory during offline staging. A future source copy may
place the module behind a normal host-only Python import after its own review;
it does not need a new CLI/MCP tool or an arbitrary-script execution hook.

The rows use `(x, y, z, width, height)` in consistent world units. Width and
height may mean radii or full dimensions, but the caller must retain that
meaning. For existing volume recipes they mean radii. Parameter stations for
the converter are author-row indices `0, 1, ...`, not arc length or X position.
The caller must resolve aperture positions expressed in other coordinates to
this parameter before declaring them as features.

`catmull_rom_spans` converts the uniform Catmull–Rom segment `a,b,c,d` to cubic
controls `b, b+(c-a)/6, c-(d-b)/6, c`. Ends repeat the terminal author row, as the
earlier recipe did. Conversion arithmetic uses exact rational input values;
controls are then rounded once to floats. The sampler certifies those explicit
returned cubic controls, not another implementation's floating arithmetic.

All author rows and requested feature stations survive. To author an actual
tangent corner, provide `corner_indices=[...]`: the adjacent handles use their
own segment's secant so no tangent is smoothed through that corner. This is an
explicit shape-authoring change, not an inference from the angle. All input
cubic boundaries are preserved even without corner flags. A spatially closed
route keeps its last endpoint; downstream seam construction owns deduplication.

Every width/height control must be strictly positive. This conservatively proves
positive profiles over the whole segment. A curve with a negative handle can
still be positive, but this implementation intentionally refuses it rather than
adding a root solver or silently applying the historical radius clamp. An
explicit `profile_mode="linear"` uses positive piecewise-linear dimension
profiles. It is an author-selected alternative, not an automatic fallback.

## What the error evidence proves

For every accepted interval, the exact source cubic is compared to the line
through the emitted float endpoint values, at the same parameter. The line is
degree-elevated into four Bezier controls. Subtracting it from the source cubic
gives four residual controls. Bernstein weights are nonnegative and sum to one,
so the maximum residual-control Euclidean norm bounds centerline error for
every parameter. Maximum absolute residual controls similarly bound width and
height errors. This is a whole-cubic control-hull argument, not a finite-probe
acceptance heuristic. It can be conservative, especially for changing speed
along a nearly straight path; it does not minimize sample count globally.

Subdivision uses exact `Fraction` de Casteljau operations. Acceptance compares
exact squared norms and exact scalar values with the exact float tolerances.
Reported errors are rounded outward. Chord endpoints use the floats actually
returned, so rounding error is included. The chosen split parameter is also a
representable float, and its exact ratio is used for subdivision. There is no
quietly rounded parameter interval hidden in the proof.

The returned evidence includes each interval's error bounds, source span,
parameter interval and adaptive depth; maxima; required stations; a hash of
the normalized source/limits; evaluated-interval count; forced/adaptive splits;
and sample count. JSON output is deterministic for the same inputs. Timings in
the separate comparison artifact are observations, not deterministic output or
a performance guarantee.

This does **not** certify a complete swept surface, a camera-space pixel error,
frame transport, tangent/normal quality, cross-section angular tessellation,
cap triangulation, self-intersection, topology, float32 materialization, or visual
quality. A smooth frame can rotate between stations even when centerline error
is small. Changing finite-difference tangents, arc estimates, or aperture
positions because sample density changed may change the downstream surface.
Those are separate authoring and validation concerns. The existing explicit
mesh validator and supported native checks remain required.

## Finite work and failure

- Explicit list/tuple inputs only; no generators, callables, unknown numbers,
  booleans, NaN, infinity, oversized integers, or silent coercion
- At most 128 cubics, 256 declared features, 4,096 output samples, adaptive
  depth 24 per forced interval, and 16,384 interval evaluations
- Coordinates, dimensions, parameter values and tolerances are finite and
  bounded by 1,000,000 in magnitude; dimensions/tolerances are positive
- Cubics must be ordered, have positive parameter length, share exact boundary
  parameters, and match all five endpoint components exactly
- Budget or float-parameter-resolution exhaustion raises `SamplingError`
  without returning partial or uncertified data

Required feature splits are counted separately and bounded by the input limit.
All cubic boundaries are required; this tool never removes author intent to
meet a triangle budget. Very tight tolerances can fail because returned floats
cannot represent an interior point accurately enough.

## Recorded comparisons

`sampling_evidence.json` uses generic data and a common 0.005 world-unit bound.
The uniform baseline is the first passing member of the documented tested
grids (1,2,3,4,6,8,12,16,24,32,48,64 chords per span), not an alleged optimum.

| Generic case | Adaptive stations | Passing uniform stations |
|---|---:|---:|
| Straight taper | 2 | 2 |
| Sharp corner | 3 | 3 |
| Localized bend | 13 | 37 |
| 3D bend | 29 | 33 |
| Width/height bulge | 33 | 25 |

The profile bulge illustrates that dyadic adaptation is not always cheaper
than a hand-selected uniform step count. The benefit is spending geometry on
actual authored curve/profile variation under explicit error limits. At 12
section vertices, the localized-bend estimate is 308 triangles versus 884,
including polygon-triangulated end caps. `estimated_ring_cost` is a topology
formula, not a generated or validated mesh. The previous volume recipe adds
cap-center vertices and therefore has different exact cap counts.

`authored_rows_evidence.json` reads four literal row sets from attempt17 using
AST literal extraction only. It does not import or execute that build script.
Its source bytes and helper bytes are hashed. It compares the underlying
positive cubic profiles without any clamping or automatic mode changes.

| Current authored rows | Fixed 3 stations/segment | Adaptive at .005 | Fixed-3 witnessed center error, at least |
|---|---:|---:|---:|
| Body | 16 | 25 | .010934 |
| Upper | 19 | 31 | .008694 |
| Crest | 22 | 40 | .021665 |
| Lower | 13 | 22 | .019495 |

The table's fixed count is `3 * spans + 1`, so the column describes three
chords per segment rather than three total points. Exact rational point
witnesses show all four fixed-three centerlines exceed every .003/.005/.006
tolerance tested; this conclusion is stronger than merely having a conservative
upper bound above tolerance. The artifact also stores the true upper bounds and
adaptive counts at all three tolerances. These are curve/profile measurements,
not triangle-quality or camera-pixel claims.

## Narrow integration path

1. Keep approved numeric author rows, features, units, semantic IDs and profile
   mode explicit in the existing host's bounded candidate-authoring data
2. In an isolated future source copy, call this pure helper from an ordinary
   host-owned authoring function. Serialize rows and evidence into a new staging
   candidate. No callbacks, Python snippets, arbitrary paths, or controller
   execution authority enter the input contract
3. Have the existing mesh-authoring path consume the rows with its explicit
   frame, seam, cap, aperture, and radial-section policy. Full 3D sweeps need a
   supported explicit mesh constructor; the existing profiled-relief helper is
   a more restricted route/section contract and is not a universal 3D adapter
4. Emit the existing `TriangulatedShellGeometry`/MeshPayload representation and
   run its normal topology/embedding, native storage and visual checks. Preserve
   exact candidate/evidence hashes. Promotions remain the existing guarded
   host/controller action, after applicable authorization and validation

No existing runtime/compiler/registry/schema was modified to make this staging
artifact appear supported. There is no production or visual acceptance claim.

## Reproduce

Use the existing interpreter:

```sh
PY=/workspace/scratch/c51bd2eae1b7/recovery_20261001/runtime_recovery/repository/.venv/bin/python
$PY -m pytest -q -p no:cacheprovider --basetemp=./test_tmp test_adaptive_sweep.py test_radial_profile.py
$PY record_evidence.py
$PY compare_authored_rows.py
```

Tests include independent exact Bernstein probes, midpoint-aliasing curves,
width-only/height-only bulges, sharp corners, feature ordering/deduplication,
closed endpoints, deterministic data/hashes, Catmull conversion, invalid input,
all work limits, tiny errors, rounding floors and parameter-resolution failure.
Probe tests corroborate the implementation; the mathematical control-hull
acceptance test supplies the whole-interval guarantee.

## Explicit radial profiles

`radial_profile.py` is a separate small pure authoring helper. It validates and
evaluates the supplied profile rather than substituting a Gaussian or any
other analytic shape:

```python
from codex_blender_modeler.radial_detail_authoring import RadialProfile

profile = RadialProfile(((0.0, 1.0), (0.25, 0.1), (0.5, 0.8), (1.0, 0.0)))
assert profile.height_at(0.25) == 0.1
assert profile.height_at(0.5) == 0.8
assert profile.height_at(1.0) == 0.0
assert profile.height_at(2.0) == 0.0
heights = profile.heights_at([0.0, 0.25, 0.5, 0.75, 1.0])
```

Knots are `(radius, height)` in caller-declared consistent units. The helper
does not choose a radius scale, amplitude, normalization, or image convention.
For each interval it evaluates `h0*(1-s)+h1*s` where
`s=t*t*(3-2*t)` and `t=(radius-r0)/(r1-r0)`. It returns authored knot values
exactly and exact `0.0` outside support. The mathematical piecewise profile has
zero derivatives at all knots, making C1 joins and a C1 zero outer tail. Ordinary
float evaluation is used here; it does not add an exact arithmetic error
certificate or a material/render guarantee.

Accepted data is 2..128 explicit knots with finite strictly increasing
nonnegative radii, finite signed heights, and final height exactly zero. Signed
heights support grooves; heights are not silently normalized or rectified.
A radius-zero center may have nonzero height. An annular profile beginning at
a positive radius must have zero initial height so its inner zero region joins
continuously. The absolute numeric envelope is 1,000,000. Queries are finite,
nonnegative radial distances in that envelope; batches are explicit arrays of
at most 4,096 entries. Invalid data raises `ValueError` without fallback.

Future integration is a narrow replacement of the existing fixed profile
evaluation with this validated numeric evaluation, explicitly passing the
authored `radial_profile_knots`. It must retain the compiler's documented radius
and amplitude conventions and add a semantic fixture distinguishing its
authored multiple peaks/valleys from a Gaussian. The frozen compiler has not
been changed here. Material/raster code, bump interpretation and native output
still need their own integration tests in the future source copy.

The combined 73-test suite covers ignored-knot/Gaussian-tail regressions,
quarter-point smoothstep values (distinct from linear interpolation), all
authored knots, signed/flat/annular profiles, endpoint continuity/zero slope,
nonfinite and malformed knots, input-copy isolation and bounded batches, in
addition to the sampler cases above.
