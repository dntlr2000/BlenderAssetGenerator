# Optional world-area-weighted portable atlas

`asset-material-convert --uv-method validated_authored_uv_v1
--tile-strategy area_weighted_rect_v1` and the equivalent MCP arguments select an
additive allocation policy. The default `deterministic_grid` and its serialization
are unchanged. Weighted allocation is refused with `smart_project`.

The existing exact `authored_uv_source` inspection supplies source world matrices,
vertices, loops, triangle corners and stable identities. No second layout companion
is needed: native execution and both host proof validators independently recompute
the rectangles from that same hash-bound inspection and conversion policy. Native
scalar proxies reuse the already resolved per-object tiles, avoiding a complete
allocation for every proxy; other callers retain the allocator fallback. Both host
validators still independently recompute and reject changed bounds. Source
and converted scenes are still inspected under the existing Blender 5.0.1 contract.

The allocator measures world-space triangle surface area with Decimal precision 64
and round-half-even arithmetic. It orders by descending area and the existing stable
object identity key. Recursive, capacity-constrained integer bisections prefer
balanced area groups, the longer rectangle axis, then minimum allocation error and
fixed axis/index ties. Every resulting cell keeps the full requested margin on all
four edges and at least one interior pixel on both axes. Integer coordinates divided
by the power-of-two resolution give exact dyadic bounds. Impossible capacity,
ambiguous identities, invalid/degenerate geometry and unsupported policies fail;
there is no geometry repair or margin reduction.

Weighted v1 accepts 64–8192 power-of-two atlases, margins 1–1024, at most 256 objects
and one million source triangles total, within the existing per-object inspection
bounds. These are resource/eligibility limits, not changes to the existing geometry,
tangent, overlap or source-authority thresholds.

Weights do not compensate for UV chart whitespace, aspect ratio, view importance or
reference detail density. Thus allocated pixels need not yield uniform effective
texel density or visual equivalence. All five raw channels still use the same atlas
resolution; this feature does not omit constant channels or bypass conversion.

The original source UVs remain unchanged. Each target receives only the existing
positive affine map into its new rectangle. The unchanged source/target triangle
overlap, float32 reconstruction and tangent checks still apply. Scalar proxy coverage
is recomputed against the weighted rectangles, and still makes no claim about normal
raster coverage or export/import tangent fidelity. Fresh native conversion, clean
import and appearance review remain necessary.
