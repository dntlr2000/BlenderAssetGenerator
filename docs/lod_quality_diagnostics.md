# Optional LOD quality: publication guard and post-export diagnostic

Optional reduced meshes retain the existing per-semantic-family/per-instance triangle
ceilings and profile silhouette floors. The standard defaults remain LOD1 ratio 0.6 /
IoU 0.98 and LOD2 ratio 0.3 / IoU 0.95. This change does not redistribute budgets,
relax thresholds, create approvals, or mutate canonical assets or existing records.

## New package publication

`package_asset` checks its already hash-verified `LODManifest` before creating the
staging package. Known recorded silhouette values below the selected profile floor
fail closed. A `verified` manifest containing any null silhouette value, foreign mesh
hash/path, or profile-inconsistent family/level coverage is rejected. These are new
publication checks, not changes to the legacy `LODManifest` loader or historical
package/clean-import validation.

Valid legacy null/partially-verified measurements remain unknown. New packages carry
an explicit optional-LOD-unverified warning. Package creation and clean import are
not evidence that silhouette floors passed. A profile that explicitly disables LODs
and has only LOD0 reports reduced-level checks as not applicable; its existing nullable
LOD0 quality fields are not rewritten.

Preflight also reports an advisory warning when a source instance has explicit clean
closed-topology evidence and a target cap below four triangles. This is the necessary
minimum for a closed nonzero-volume triangulated surface. The warning is conditional:
edge closure does not prove nonzero volume, and neither closure nor a triangle count
proves silhouette quality. Open or unknown topology is not treated as a proven volume.
The warning changes no profile, budget, source geometry, or approval decision.

## Explicit read-only post-export check

Run after an immutable `full_evidence` GLB package and its independent mask diagnostic
exist. The script supports a relocated package directory without relying on live job
state. Select the exact package manifest and, when available, both render JSON hashes:

```sh
uv run python scripts/check_exported_lod_quality.py \
  --package-manifest /path/to/package/package_manifest.json \
  --package-manifest-sha256 EXACT_PACKAGE_MANIFEST_SHA256 \
  --render-root /path/to/existing/mask_diagnostic \
  --render-plan-sha256 EXACT_PLAN_JSON_SHA256 \
  --render-manifest-sha256 EXACT_RENDER_MANIFEST_JSON_SHA256
```

Python callers can use
`codex_blender_modeler.packaging.lod_quality.inspect_exported_lod_quality` with the same
explicit parameters (paths are `Path` objects). The helper only reads; the script prints
one `schema_version: 0.1.0` read-only diagnostic JSON result to stdout. A caller may retain stdout as a fresh external diagnostic,
never insert it into an already finalized package. It is not a new native approval or
package contract and is not auto-discovered by package creation.

The checker verifies the existing strict package/profile/optimization/LOD snapshots,
exact receipt bytes, export-to-execution-plan/source/material-conversion binding, actual
GLB semantic/LOD mesh names, and supplied mask hashes. It recomputes alpha-mask IoUs;
it never trusts a separately supplied success summary. It uses the package profile's
unchanged floors. The recognized unversioned independent mask format has kind
`bounded_independent_exported_lod_silhouette_plan`, Blender declaration `5.0.1`, Workbench
flat opaque masks, fixed 1024-square RGBA PNGs, alpha threshold 128, and canonical,
front, right and top views. Unknown fields/versions are rejected. Cardinal camera axes
and rigid transforms must agree with their names, selected objects must exactly match
the actual GLB family/level, and every level must reuse its LOD0 camera.

The plan fields are exactly: kind, primary_asset_sha256, blender_version, engine,
geometry_only_flat_opaque_override, resolution, render_aa, mask_alpha_threshold,
minimum_reference_foreground_pixels, levels, profile_floors, scopes, views,
maximum_render_count, canonical_camera_matrix, canonical_camera_lens_mm,
orthographic_camera_basis and native_lod_manifest_unchanged. The render manifest fields
are exactly plan_sha256, records, elapsed_seconds and canonical_or_package_saved. Each
record has scope, view, level, selected_objects, camera, path and sha256; camera has
matrix_world (row-major 4x4), type, lens and ortho_scale. At most 64 semantic families
and optional individual-family scopes plus the mandatory whole_asset scope are supported.
The existing fixed renderer is not invoked or modified by this check.

| Diagnostic status | Exit | Meaning |
| --- | --- | --- |
| passed_for_declared_coverage | 0 | Every supplied planned comparison is scorable and meets its floor |
| not_applicable | 0 | Optional LODs explicitly disabled; no reduced-level comparisons or scores |
| failed | 1 | A measured mask or recorded legacy entry fails its unchanged floor |
| invalid_evidence | 1 | Input integrity, shape, source binding, or coverage is invalid |
| unverified | 2 | Evidence absent or any planned comparison unavailable |

Omit all three render arguments to explicitly report absent evidence. An enabled
profile remains unverified (or failed if it already records a measured failure); a
disabled profile returns not_applicable. Supplying only some arguments or attaching
reduced-level proof to a disabled profile is an error. Reference masks below 1024
foreground pixels and masks touching the frame remain unavailable even if identical.
An empty candidate against a scorable reference fails rather than disappearing from
coverage. One unavailable view can never turn into a passing all-planned result.

## Assurance and compatibility boundary

This is a post-export delivery-readiness diagnostic, not proof consumed before an
export exists. Its hashes establish integrity and self-consistency of supplied exact
masks; renderer provenance remains declared, not independently rerendered or attested.
A caller's separately retained actual Blender execution receipt is additional evidence.
Coherently fabricated masks cannot be authenticated by hashes alone. A successful check
is therefore labeled only `passed_for_declared_coverage`, with native verification and
publication/acceptance authority both false.

Whole-asset masks can conceal semantic-part errors through occlusion. The output records
whether every semantic family was separately included. Even complete isolated discrete
views do not prove all-view shape preservation, materials, internal topology, normals,
UV fidelity, or runtime LOD switching. No result populates legacy per-family IoU fields,
reclassifies a historical package, changes technical grant consumption, or creates human
beauty/package/Activation acceptance. Existing source, schema, CLI/MCP authority surfaces,
and clean-import meaning remain unchanged; this narrow read-only script is additive.
