# Validated authored UV conversion v1

Portable material conversion has an explicit optional `uv_method="validated_authored_uv_v1"` (`asset-material-convert --uv-method validated_authored_uv_v1`, or the matching MCP argument). The default remains `smart_project`; old conversion plans/manifests omit the additive fields and retain their previous meaning. Workflow and AQ callers remain on that default unless they explicitly pass the new method. CLI/MCP resolution defaults remain 1024; the host and atlas policy defaults remain 2048. Margin remains 16. The method does not increase texture budgets or change the existing deterministic equal-object grid.

For a 2048/16 run, select those values explicitly:

```sh
cbm asset-material-convert JOB --run-id RUN --conversion-id NEW_ID \
  --resolution 2048 --margin-px 16 --uv-method validated_authored_uv_v1
```

The mode requires Blender 5.0.1 both when converting and when loading the conversion for packaging. A fixed read-only inspector reopens the exact optimized blend before conversion, and reopens the saved converted blend after conversion. The host retains `authored_uv_source.json`, binds its SHA-256 in the conversion plan, and publishes the independently recomputed `authored_uv_proof.json` referenced by the manifest. Full-evidence packages copy both proof files into metadata. Legacy loading does not acquire a Blender requirement.

The strict 0.1.0 proof binds exact input/output blend bytes, the conversion plan, every derived object/material identity, ordered full-precision vertex/polygon/corner topology, Blender loop-triangle enumeration, every original UV layer, and sampled source layers. The original layout layer is `cbm_uv_set` for UV-mapped materials, or the original render UV layer for object/triplanar materials. This layout selection is separate from shader sampling: explicit source selections are preserved, and implicit image vectors, Texture Coordinate UV outputs, empty UV Map nodes and tangent Normal Map nodes are pinned to their actual original render UV layer before the atlas becomes active. Object coordinate references and transforms are not rewritten in this mode.

Each object's source occupied bounds is mapped with positive independent U/V scale and translation into its existing tile. Target interval endpoints are explicitly rounded inward to representable float32 values before the affine map; coordinates are never individually clamped, wrapped, repaired or repacked. The proof records both requested tile bounds and actual mapping bounds. Host and runtime verify actual stored float32 values against the exact reconstruction, preserve each triangle's orientation and test every triangle interior. The proof fingerprints ordered binary64 UV values and ordered unsigned triangle indices with versioned big-endian encodings; complete snapshots use sorted-key compact finite JSON without rounding.

The overlap predicate uses an adaptive orientation test with exact rational fallback. Shared edges/points are allowed; any positive-area overlap, however small, is ineligible. No adjacency, island or material exception skips interior intersections. The sweep broad phase selects its axis deterministically and fails closed on triangle, candidate-pair or active-sweep limits. Resource limits and malformed evidence never become zero-overlap success. Source repeat layouts within an object are ineligible for this mode, not general asset defects; the legacy converter remains available.

The mode refuses shared mesh datablocks, a pre-existing `CBMPortableAtlas` layer, missing/ambiguous UV selections, active modifiers, animation/shape keys, nested shader groups, script/attribute/tangent nodes and linked Geometry Tangent sampling. It preserves all original UV layers and refuses unsupported sampling rather than guessing. Native and export-like tangent probes run on the unchanged mesh or a disposable copy; no source geometry repair or serialization normalization is permitted. Exact topology, stored UVs and original layers are checked after these probes and again after saving/reopening the blend.


The sole shader-group exception is the constant optical-volume Thickness metadata
node owned by the material's intact explicit optical contract. The existing native
optical validator must pass first. Its group must be the exact local ShaderNodeTree
pattern with one float Thickness input, no outputs, no internal nodes or links, no
parent links and no animation/drivers. Added interface panels or sockets, linked
libraries and library overrides are refused. The generated group name may carry
Blender's numeric datablock collision suffix, but neither that name nor an arbitrary
renamed group grants eligibility. An ordinary material copy may share the same
validated empty metadata tree. Every other GROUP remains unsupported, including
unused or nested sampling graphs. This exception adds no sampling binding and does
not alter old no-volume inspection bytes, UV gates, geometry limits, proof schemas,
optical geometry checks or package authority.

`tests/test_authored_uv_optical_metadata.py` covers the narrow structural predicate
and calls `tests/fixtures/authored_uv_optical_metadata_probe.py` with `BLENDER_BIN`.
The native fixture exercises hostile native graphs, source UV pinning and actual
five-channel Cycles baking, portable material conversion and serialized optical
factors. Setting `AUTHORED_UV_BASELINE_RUNTIME` to an independently frozen old runtime
also checks byte-identical complete no-volume inspection output.

Loading for packaging rehashes all bound files, strictly parses/recomputes the proof, compares public tile/material records, and independently reopens source and target blends. Missing, stale, rehashed-but-inconsistent, unknown-version or changed snapshots fail closed. This is controlled host/Blender measurement with ordinary immutable hashes, not cryptographic trusted execution; replacing the complete trusted root/runner/artifact chain is outside that attestation. The proof covers the converted blend. It does not prove exported/imported UV survival, pixel or mipmap padding, absence of texture bleed, thin-line fidelity, lossless appearance, visual acceptance, or destination-engine behavior. Independent format export/clean-import and quality gates remain required.

`tests/test_authored_uv_proof.py` covers exact geometric and float32 predicates. `tests/test_authored_uv_conversion.py` covers public contracts, strict recomputation and tampering. The bounded `tests/blender_authored_uv_fixture.py` fixture tests actual two-layer patterned color and non-neutral tangent-normal baking, source preservation, refused graph/mesh collisions and legacy repeat-layout compatibility under Blender 5.0.1.

## Additive scalar bake coverage evidence

Fresh conversions additionally evaluate Base Color, Roughness, Metallic and Emission over temporary UV-domain rectangles using the same inverse-affine source coordinates and existing target tiles. This supplies real source-shader values even for subtexel charts that contain no raster sample center. Resolution, margin, equal tiles, actual geometry and all actual UV layers stay unchanged. This is one fixed-resolution shader evaluation, not supersampling, pixel painting or source reauthoring.

The current scalar dependency allowlist is deliberately small: explicit UV Map, Mapping, flat Image Texture, Value and RGB nodes. Other connected dependencies, including position, object, geometry and unsupported procedural sources, fail eligibility. Unused original layers remain preserved. A referenced second layer must obey one exact rational affine relation at every ordered source loop; both binary64 conversion and stored Float2 proxy corners must represent its extrapolation exactly. Non-affine seams, conflicting repeated coordinates and approximately affine layers are refused.

An independent white-emission mask proves that the proxy raster covers every bilinear-support pixel of each tile. The host recomputes rectangles and cross-layer relations, reads the exact mask bytes, and binds the four scalar output hashes. Legitimately black colors and zero emission are allowed. This is proxy raster coverage plus bound bake execution; a white mask alone is not independent mathematical proof of arbitrary shader output correctness.

The optional strict `authored_uv_scalar_bake.json` companion (schema 0.1.0, method `uv_domain_scalar_v1`) and its `authored_uv_coverage.png` mask are copied into full-evidence package metadata. New execution requires this companion; historical conversions without it retain their original UV-only interpretation and do not acquire a scalar-coverage claim.

Normal is baked on the actual original mesh with scalar proxies excluded from rendering. It is never copied or flattened through the scalar path. Scalar coverage does not establish subtexel normal coverage, source-to-atlas frame equality, or exported/imported tangent-basis fidelity. Those limits remain explicit and require separate visual/material assessment; scalar coverage never grants package acceptance.
