# Reference-derived assembly generation

This path separates reference interpretation, structural construction, and evidence about the actual exported model. It is Codex-assisted authoring through BAG's existing strict scene/material contracts. It is not automatic recovery of a unique three-dimensional object from one image.

## Interpret visible structure before tracing parts

The standard image analysis supplies masks, colors, edges and camera hints. Its ModelingPlan is intentionally a scaffold. Before authoring geometry, record which visible boundaries are silhouettes, material changes, overlaps or actual openings. Identify the solid that continues behind each occluder. Mark hidden thickness, unseen backs and mounting details as inferred.

Use the existing observation/hypothesis, semantic ModelingPlan and camera contracts. Record both positive occupied regions and negative openings from the original reference. Freeze reference-only trimap constraints before evaluating a candidate. Candidate masks must never determine their own reference targets.

Construct structural owners first. A set of independently traced component outlines is not a complete assembly: two outlines can meet at one point while leaving a long unintended slit. An observed continuous region needs a continuous carrier or an explicitly supported seam. Intended free tips, pendant separation and optical sheets retain their distinct meaning.

## Inspect inferred volume before detailed material work

A contact proof validates the geometry that was authored; it does not establish that the chosen
representation is a credible interpretation of the reference. Existing authoring guidance already
requires broad cross-sections and warns against a flat silhouette plate. Apply that guidance early:
render a low-cost blockout in the reference view, oblique, exact side, exact top, rear and clay, and
inspect the actual pixels before detailed materials, optimization or packaging. Keep the diagnostic
resolution/samples/version explicit; these views neither replace the canonical seven-pass V0.6
contract nor grant specialized execution or human visual approval.
This checkpoint addresses a missed authoring inspection; it does not guarantee reference fidelity.
When provisional canonical SceneSpec and ModelingPlan inputs satisfy its contract, reuse the
existing five-view assembly sanity companion and its source-bound settings. Verify directions
against the declared assembly frame: front/right/top/rear/oblique are frame-axis labels, so its
front need not be the reference-facing view. Its existing passes are beauty/silhouette/object_id/
wireframe; inspect clay through an additional existing render path, not a claimed new built-in
pass or canonical scoring protocol.

For each major component, record its local section axis, approximate width/depth relationship and
why its profile is rounded, tapered, faceted, hollow or intentionally thin. Use existing plan notes,
evidence and confidence fields. Separate observed contours/overlap order from inferred backs and
thickness. There is no generic minimum thickness: a real sheet, plaque or requested relief may be
correctly shallow. Conversely, increasing one global extrusion depth does not create appropriate
component volumes. Preserve recognizable cutouts and required joins while refining the sections.

A smoothly rounded solid can still admit valid front/back graph patches in a chosen frame. Reuse
those exact checks where naturally applicable, but do not flatten a back or distort a section to
fit the proof implementation. Overhangs, cavities or ambiguous layers outside its supported scope
remain unsupported until an appropriate separately reviewed construction/check exists. Do not
relax workload or geometric bounds to turn an unsuitable representation into a pass.

Persist a bounded authoring checkpoint with the source inputs, diagnostic geometry, settings and
views before starting a costly delivery cycle. Distinguish rejected blockouts, technically valid
intermediate packages and an actual accepted outcome. Dominant ridges and broad beveled trim may
still be necessary after the volume checkpoint; small ornament can follow or be consciously omitted.

## Choose continuous relief or a real separate attachment

For an observed carved or molded surface, prefer continuous owner geometry. The initial `structural_geometry.compose_owner_front.compose_owner_front` helper adds nonnegative piecewise-affine height profiles to an eligible closed owner. Each profile has an explicit ID, triangulated footprint and heights, with zero height on every boundary. Intersecting profiles add heights. The helper retains the complete requested area, coalesces only exactly coplanar cells and preserves the rear graph. It currently rejects inward displacement; a requested recess needs another supported construction, not a negative height mislabeled as a raised profile.

A boundary with zero displacement joins continuously to the unchanged owner graph. This avoids duplicate hidden undersides and does not need an artificial attachment between a part and itself. Broad shoulders and the channels between them establish volume; narrow ornament follows only after those cross-sections are credible in oblique clay views. Construction reports include analytic added volume, binary64/binary32 topology checks and actual costs; they cannot attest actual export or inferred reference meaning.

Separate objects remain appropriate for inserted fins, collars, linked pendants or visibly distinct inlay. An inferred lap or seat must have a meaningful structural role and explicit relationships on both sides. Keep material ownership truthful. Do not hide intersecting disconnected solids inside one semantic mesh just to lower the object count or bypass a whole-mesh topology check.

## Generate a separate attached relief from the owner

Use `structural_geometry.owner_relief.build_owner_relief` with an explicit triangulated footprint, outward relief height, front/back owner surfaces and bounded embedding. The exact overlay inserts intersections with owner triangles and derives every underside point from its owner. It refuses uncovered lateral area, ambiguous layers, inadequate remaining thickness and unsupported numerical/workload cases. It never silently shrinks a requested strip to fit.

The supported owner is a closed, embedded height-field solid in a signed axis frame. Front/back surfaces must cover the same domain with strictly positive interior separation; exact convergence at a silhouette or hole rim is allowed only after complete affine zero-locus boundary coverage is proved. Interior pinches, positive-area zero-thickness regions and negative separation are rejected. All other faces must be valid depth-parallel sides. Folded or overlapping sides, interior cavity shells and omitted intervening boundaries are not eligible. Arbitrary non-height-field surfaces need another validated construction strategy; they must not be relabeled as supported.

The returned shell uses the existing geometry representation. Keep complete owner, underside, outward surface and side face groups. Multiple closed same-material components may share a semantic mesh only when source-to-actual correspondence is complete and unambiguous. A material-face fragment must not be mislabeled as a closed volume.

When the complete rear graph has one exact constant depth, the validator can prove front/back domain equality by cancellation of their exact oriented boundary intervals, including holes and different triangulations. This avoids materializing an unnecessary cap overlay. It runs only after the unchanged closure, embedding, role and single-valued-surface checks. It preserves the same rational/work limits and derives thickness extrema from every front graph vertex. A nonconstant rear or unequal domain returns to the existing general overlay; this path neither changes geometry nor converts unsupported evidence into a pass.

The helper's binary32 simulation is preflight only. It does not replace real Blender build, export or import evidence.

## Distinguish exposed relief from an inserted root

`required_full_patch` proves the complete exposed relief with bounded embedding, positive remaining owner thickness and outward relief height. `required_root_patch` proves positive depth-interval overlap over an explicitly declared whole insertion region. It does not require a buried root to be exposed, and it makes no overlap claim about the free end of a fin. The two predicates must remain distinct.

The root test compares complete piecewise-affine front/back intervals in a signed axis frame, including every overlay vertex; it is not an endpoint or bounding-box test. A root selector may be a subset only after the host has proved the complete closed owner and subject components. Aliased face-group names cannot make one component support itself. Wrong owners, lateral uncovered slits, insufficient overlap, cavities, folded walls or omitted components are failures or unsupported evidence, never passes.

The optional `root_region` artifact selects a whole insertion region without adding delivered
triangles or changing topology. It is available only for `required_root_patch` and is mutually
exclusive with that entry's four face-group contact selectors. Its strict region file binds the
job, relation and signed frame to one original-derived polygon. Freeze the region before candidate
validation; correcting an inadequate region requires a separately preserved and reviewed revision,
never shrinking it around a failing model. One simple nonconvex polygon is supported; holes,
multiple rings, self-intersections, empty regions and unknown frames are refused.

The region file's existing `subject_lower` and `owner_front` face groups identify exact complete
components and must belong to the correct cap roles. These anchors do not select or reduce the
contact area. The host derives all four actual front/back cap surfaces, proves both complete closed
embedded height-field solids, then clips internally with exact binary-input rational arithmetic.
The domain remains the declared orthographic plane and signed height-field depth frame; no general
surface containment, perspective inference or free-fin overlap is claimed. Source preflight,
native evaluation, converted geometry and final clean import must all retain their separate checks.
Selected missing/stale/malformed region evidence blocks the route, and required snapshots remain
hash-bound through final package publication. Legacy absence is unverified for this new region
measurement; the existing face-group mode and its earlier evidence keep their meaning.

`structural_geometry.partition_heightfield.partition_heightfield_faces` introduces shared graph anchors and explicit root face groups while retaining the original affine surfaces. It preserves complete coverage, projected area, orientation, closed topology and the declared serialization bounds. Construction and validation work limits apply to all candidate scans; exhausting a limit must return no partial success. Never trim a failing footprint or split an owner solely to avoid those checks.

The overlay calculations are exact before serialization. Newly inserted floating-point coordinates need not have mathematically identical domains to the original rational input: retain measured finite-precision differences, revalidate binary32 and inspect the actual exported geometry. Do not describe unchanged authored footprint inputs as exact equality of serialized meshes. Complete-component eligibility and output-generation limits are separate; construction success does not waive a later inspection capacity limit.

## Check the actual result at both structural scales

The optional attachment companion binds exact source inputs and full declared patches. Selection is explicit and retained in build/run fingerprints. Missing, changed, ambiguous or unsupported selected evidence blocks that path. Legacy absence remains legacy evidence and does not become a new full-patch pass.

The fixed host inspector must extract the complete actual semantic geometry from the target artifact, establish source/component correspondence, and evaluate the actual coordinates. One contact witness, an axis-aligned box, or an independently supplied JSON triangle snapshot cannot certify attachment. Run the complete check again on converted and final imported geometry before immutable package publication.

Use `qa.reference_occupancy` to measure all sure reference pixels in frozen critical regions. Its rasterizer uses exact integer half-plane spans at pixel centres for an axis-aligned orthographic camera with Blender AUTO sensor fit and square pixels. `ortho_scale` spans the larger image dimension. Other camera models are outside this helper's supported domain. The caller must verify the actual geometry origin and exact camera/reference bindings.

Existing trimap values 0 and 255 mean sure background and foreground; 85 and 170 remain unscored. The comparison reports every missing or unexpectedly filled pixel and connected gap extents. It does not resize, dilate, fill holes or turn a high global silhouette score into local success. A complete image-grid check does not prove continuous 3D contact, material ownership, optical correctness or hidden geometry.

The optional selected occupancy adapter also binds the original image, existing V0.3 trimap/extent evidence, source membership, exact camera, fresh extracted triangles and resulting masks. Inspect once after the first real build to fail before material baking, then repeat after conversion and clean import. Preserve pre-fixed known gap regions; removing them to improve a score changes the evaluation and requires a separately labeled comparison. All selected successful stage files must remain byte-identical through package publication.

Review actual front, oblique, rear and clay views after these measurements. Investigate geometric gaps before material polish. Separate optical/surface linework from structural supports, and examine actual normals and depth sections.

## Complete the supported delivery path

Plan materials with the converter's existing one-slot-per-mesh boundary in mind. Use meaningful closed single-slot parts or supported spatial material detail. Merely splitting a multi-material solid's faces creates open fragments and can change shading. Report any increase in objects/primitives and texture allocation.

Use existing V0.5 materials, V0.7 optimization, material conversion, full-evidence GLB packaging and independent clean import. Retain immutable exact optimization authority; never recycle a spent or source-stale grant. Scalar transmission support is distinct from volume/thickness/absorption parity. Inspect the actual imported material inputs and pixels rather than inferring optics from a generic clean-import pass.

For comparisons, preserve the same original reference, cameras, lights and render settings. Report triangles, delivered vertices, objects, primitives, materials, texture memory, package size and actual stage costs. Distinguish historical output comparisons from controlled same-input construction tests and equal-effort generation experiments. Final human visual acceptance remains separate.

The complete-solid eligibility proof may use strict global front/back depth
separation with exact equal projected domains for expensive cap tessellations.
Its thickness interval is explicitly conservative; all selected root overlaps
remain measured by the existing exact regional kernel. A zero or negative global
separation is never accepted by this shortcut.


## Optional error-bounded authoring helpers

Use [adaptive profile authoring](adaptive_profile_authoring.md) to choose an explicit centerline/radius error budget and preserve semantic stations before emitting ordinary triangulated-shell data. The radial evaluator honors authored ridge knots instead of substituting a Gaussian profile. Neither utility grants execution, registration or approval authority. Their numerical bounds do not prove swept-surface error or appearance. Compare actual reference-facing, end and rear pixels; report triangle/map costs; retain meaningful negative spaces and finished back surfaces. A technical package pass is a milestone until the requested appearance and cost outcome is satisfactory.
