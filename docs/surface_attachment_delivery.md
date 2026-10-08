# Selected surface-attachment delivery checks

This additive companion verifies full selected attachment patches on complete actual
height-field solid components. It is a technical check, not visual, optimization,
package or human acceptance authority. Existing jobs without an explicit selection
and registration retain their former behavior and serialization.

## Initial selection

The documented host Python API is
`codex_blender_modeler.packaging.attachment.register_surface_attachment_intent(job_id,
intent_path=..., intent_sha256=...)`. No new CLI, MCP, phase-controller or arbitrary
execution surface is introduced. Call it once on a fresh unbuilt job after its exact
SceneSpec, geometry payloads and `AttachmentIntentV01` have been authored. The API
validates the contained intent, exact primary reference, canonical ModelingPlan
and source geometry, then performs the bounded full source-geometry preflight
before writing an immutable
`production/surface_attachment/registration.json` receipt and adds `attachment_intent`
plus `attachment_registration_sha256` to job metadata under the host job lock.

Source preflight evaluates explicitly predicted binary32 coordinates, records
`source_float32_prediction`, and leaves native/extraction verification false.
It can reject structural failures before material baking but cannot replace the
fresh actual-geometry checks. The registration is an input-selection latch, not approval. Receipt and metadata
must agree. Missing metadata, missing selector, missing receipt, changed hashes,
foreign identity and linked inputs fail. An exact interrupted initial metadata write
may resume only while the receipt still matches the original metadata hash. There is
no remove/reselect API, and built jobs cannot register or replay registration.
Wholesale deletion or replacement of all local history is outside this ordinary
local-file integrity contract; it is not an externally tamper-proof ledger.

There is no hash cycle: the intent binds original reference, ModelingPlan,
SceneSpec and mesh payload bytes; it does
not bind metadata, registration, build, optimization or package outputs. Build
provenance includes the selected intent and registration digest. The optional
`SourceProvenance.attachment_intent` is absent from legacy serialization and enters
the new source fingerprint and artifact enumeration when selected. Existing exact
source comparisons carry it through optimization, conversion and packaging.

## Supported initial geometry domain

- Strict MeshPayload 0.2, triangulated faces, one material slot per semantic mesh,
  identity SceneSpec transforms, no parent transform, generator or modifiers
- Existing exact source face groups identify owner front/back and subject
  upper/lower patches; no additional component identity field is required
- Every semantic used as a required owner/subject declares `static_prop_closed`
  and every actual connected component must be closed, consistently outward,
  positive-volume, a valid vertex-link manifold and free of improper self-contact
- Whole selected owner and subject components must be complete outward closed
  height-field solids: front/back domains coincide, all remaining sides project
  to zero area, no omitted or intervening boundary exists, and thickness is strictly
  positive in the projected interior. Exact zero-thickness silhouette closure is
  supported only after proving the entire affine zero locus lies on the exact
  outer/hole boundary. Interior zero points/edges, positive-area zero cells and
  negative thickness remain unverified; no tolerance or sampled exception applies.
- Multiple closed same-material components may share one semantic mesh. They are
  interpreted as explicit additive solids, without implicit Boolean subtraction.
  Open optical sheets require separate non-required semantic scope and receive no
  solid or mechanical-attachment claim

`required_full_patch` retains complete whole-subject upper/lower coverage and
positive embed, remaining material thickness and outward relief conditions.
`required_root_patch` instead checks positive depth-interval overlap across the
whole explicitly selected insertion region. In root mode the host derives the
complete owner/subject cap roles from exact signed projected winding, proves
the entire closed components, and separately requires root groups to be subsets
of the correct roles. The free part of a fin is not claimed to overlap its owner.
Both modes reject self-support through alternate group names: subject and owner
must have disjoint complete components when they share a semantic identity.

Source and actual triangles must match completely and unambiguously by oriented
positions and material identity. Source positions are rounded once to Blender's
binary32 storage values; actual unrounded world positions must equal those numeric
values exactly. No transform tolerance, nearest-owner match, vertex welding or
sample-based substitute is accepted. A shared source vertex must have one identical
actual position across all matched corners. Source grouping and winding are retained
for component recovery; every actual triangle of the selected semantic is accounted
for. Reports retain the exact position policy and measured maximum error (zero for a
passing current route).

Input limits are 8 MiB per bound file, 32 MiB combined selected mesh bytes, 16,384
vertices / 8,192 triangles per semantic, 25,000 total triangles, and 8,192 vertices /
4,096 triangles per component. An aggregate one-million broad-phase work budget
guards the actual embedding sweep, charging active-pair scans and heap
insertions/removals. Heap expiry avoids redundant scans of all surviving intervals;
the ordered closed-AABB pair set, exact contact predicates and per-component
32,768 exact-pair limit remain unchanged. Unknown,
oversize, ambiguous or exhausted work fails; it cannot become an omitted check.

For potentially expensive nonconstant front/back overlays, strict global depth
separation can prove positive thickness after exact complete projected-domain
equality. Every affine cap value lies within its vertex extrema, so
`min(back) - max(front) > 0` is sufficient. The report explicitly labels the
resulting thickness interval as conservative global bounds, not attained extrema.
Closed topology, embedding, orientation, single-valued surfaces and all work limits
remain required. Equal/touching/overlapping depth ranges or unequal domains use
the existing exact overlay path. This whole-solid shortcut does not replace any
selected-root overlap measurement.

## Native and publication boundary

`inspect_surface_attachment_geometry.py` is a fixed stdlib/bpy-only Blender 5.0.1
reader. It freshly enumerates evaluated world-space triangles, material identities
and semantic identities from native, optimized or converted blends, or a factory
clean import of an actual GLB. It verifies exact artifact and embedded build/intent
identity. Ordinary `cbm_instance_index=0` is permitted; actual generated instances
remain unsupported. Existing raw geometry inspectors retain their old contract.

Before immutable publication, opted-in `full_evidence` GLB packaging freshly checks
native, converted and actual clean-import geometry. The same pure full-patch and
whole-solid proofs run over the actual coordinates at every stage. Failed exports
and inspection files remain in a unique run-owned attachment-check directory;
sealed package metadata receives the successful inspection results. The ordinary
official package clean-import check remains independently required afterward.

The pure evaluator intentionally cannot attest native extraction on caller-supplied
JSON. Only the fixed host invocation marks extraction verified after request/artifact
checks. The full source tree and trusted runner remain the ordinary local trust root.
This companion does not prove material optics, general pixel fidelity, engine behavior or
the meaning of an arbitrary hollow/non-height-field solid.

## Optional original-reference occupancy

An explicit `reference_region_evidence` artifact may select existing V0.3 mask
evidence. Its original reference, trimap and subject-extent bytes are rehashed
transitively by the stdlib native reader; no image or host-model libraries enter
Blender. Host validation checks the exact authored ModelingPlan and SceneSpec
primary/supporting membership, the original reference, seed/extent/trimap contracts,
and sure labels against the original RGBA alpha channel. Foreground sure pixels
require nonzero original alpha; background sure pixels require zero original alpha.
Uncertain labels remain outside this measurement.

The initial domain is an axis-aligned orthographic camera looking along +Y with
+Z up, AUTO sensor fit, square pixels and the original source resolution. The
bounded rasterizer projects all actual subject triangles onto that exact frozen
source grid, using exact predicates at pixel centres. It compares every sure
foreground/background pixel without resizing, dilation, gap filling or candidate
derived reference masks. A selected mismatch or invalid/stale/missing dependency
blocks publication; an omitted selection reports coverage as unverified.

Registration validates reference context before material work, while source
mechanical preflight remains explicitly predicted geometry. Call the documented
`inspect_stage` host API with `native_evaluated` immediately after the first build
and before baking to perform the early actual whole-asset check. Packaging freshly
repeats it for native, converted and clean-imported geometry, retaining projection
PNGs, the exact trimap and hash-bound reports in package metadata. The task-local
delivery driver provides fixed `attachment_register` and `attachment_inspect`
steps for that order; these do not add repository CLI/MCP commands.

Each completed inspection immediately seals its extraction, returned report and all
selected occupancy diagnostics. Missing selected diagnostics fail; existence never
decides whether to include them. Source and copied bytes are rehashed before and
after copying. The fixed host invocation retains an in-memory closure including
the summary and inspected artifacts, and the existing package service checks that
same closure immediately before publication. It never loads an alternative
caller-authored attestation from disk.

Coverage reports bind the exact source-camera fingerprint, all evidence hashes,
fresh geometry digest and extraction request. The host invocation alone attests
native origin; a pure adapter call cannot attest supplied geometry JSON. This is
mathematical source-grid occupancy, not beauty-render equality, optical fidelity,
inferred hidden geometry or human acceptance.

## Public schema effects

Two explicit companion schemas cover attachment intent and diagnostic patch
snapshots. The additive SourceProvenance field is projected into twelve existing
optimization, preflight, material-conversion, texture and package schemas. No legacy
schema version, approval actor or authority type changes. The host registration API
and fixed inspection evidence remain technical callable/runtime surfaces; they are
not added to public MCP/controller allowlists.
