# Source-bound exterior geometry review v3

`exterior_geometry_review_v3` is an explicit additive policy on the existing
assembly-sanity plan, render manifest, report, and visual review. The default
remains `exterior_geometry_review_v2`. Old v1/v2 evidence is read and replayed with
its original meaning; loading never creates v3 evidence or changes old scores.

## What is and is not established

- Canonical `overall_direct_score` still measures silhouette and global/semantic
  bounding boxes with the unchanged formula. New reports explicitly disclose that
  it does not verify internal forms, ornament, material likeness, or attachments.
- A clean export/import round trip establishes source preservation, not likeness
  to the original reference.
- `center_plane`, containment, overlap, and `surface_contact` checks retain their
  exact existing semantics. Even `surface_contact` is a **bound-face** check, not a
  triangle intersection or physical-attachment certificate.
- The v3 contract inventories declared attached roles, required broad-phase
  relation IDs, and surface-detail IDs. Coverage is initially `unverified`.
  An empty surface-detail list does not prove that visible details are unnecessary.
  A texture binding does not prove the appearance of its pixels.
- The review covers geometry-required internal forms, visible attachment intent,
  and explicit routing of declared surface details. It does not certify finalized
  texture/material appearance, unseen geometry, exported packages, or human
  acceptance. Those retain their independent review and approval boundaries.

## Selection and evidence

Select `--review-policy exterior_geometry_review_v3` on
`cbm qa-assembly-sanity-plan`, or the same `review_policy` on the existing
`plan_assembly_multiview_sanity` MCP tool / Python planning API.

For a normal full or guarded manual-revision workflow, select
`--geometry-review-policy exterior_geometry_review_v3` on `cbm workflow-plan`, or
`geometry_review_policy` on `plan_short_workflow` / `plan_workflow`. For an
existing-asset revision select `--revision-strategy manual_guarded`; the separate
candidate-review strategy is not silently upgraded by this policy.
The early proxy review remains v2; the detailed/revision review carries v3.
A selected route that contains no detailed/revision review fails explicitly,
including proxy-only and package-only routes. It never silently drops the policy.

The run owns exact SceneSpec, ModelingPlan, and primary-reference snapshots under
`detail_review_inputs/`. Before creating temporary cameras or isolating targets,
Blender validates the actual fixed source camera/build and captures
`canonical_beauty.png`. Its camera fingerprint, pixel dimensions, and exact hash
are carried by `canonical_detail_evidence` in the existing render manifest.
The existing five views and twenty diagnostic passes remain unchanged. This
additional beauty is **not** a canonical seven-pass QA run and creates no score.
Missing, changed, escaped, or mismatched source/image evidence fails closed.
Terminal replay uses immutable source snapshots, so a later legitimate source
revision does not invalidate intact history. Active workflow completion also
rechecks current sources and cannot reuse a stale review for a newer asset.

## Manual assessment contract

A v3 `GeometryMultiviewVisualReview` retains its existing exact plan, manifest,
report hashes and five-view beauty/wireframe review. It additionally requires:

- `reviewed_detail_contract_sha256`: stable JSON digest of the plan's exact
  `detail_review_contract`
- One `internal_form` assessment per selected semantic target
- One `attachment` assessment per declared `assembly_role=attached` target;
  intentionally free-standing/modular objects do not acquire an attachment rule
- One `reference_internal_detail` assessment on the assembly root for the whole
  visible reference, independent of uncertain 3D part partitioning

Each assessment names `target_id`, `aspect`, `reference_basis`, `outcome`, actual
`observation`, explicit `limitations`, evidence `view_ids`, and `finding_ids`.
Its `surface_detail_ids` must exactly cover the declared details for that parent
(or all declared details for the whole-reference assessment). A supported
attachment also names the exact `attachment_reference_ids` visually inspected;
required bound-face contact partners cannot be omitted. These names do not turn a
visual judgment into physical-contact proof.

`reference_basis` is `observed_reference` or `inferred_only` according to the
source object evidence. The whole-reference row is always reference-based.
Uncertain depth/part partition therefore cannot excuse missing clearly visible
front-region forms. No hidden surface is promoted to observed or measured.

`visually_supported` is a bounded manual/agent observation, never an automated
semantic score or human approval. `defect` must link an existing actionable
revision/redesign finding with the same target and evidence views. `unscorable`
must link an `insufficient_evidence` finding requesting additional evidence.
All images must actually be inspected; writing a row does not constitute review.

## Completion versus quality progression

The structural terminal can be generated and retained even when manual review
finds defects. Read-only validation preserves a correctly bound defective or
unscorable review as evidence.

The selected workflow's agent-completion boundary separately refuses to publish
a completion marker while required assembly constraints fail, an assessment is
missing/defective/unscorable, or the visual outcome remains unresolved. It reports
`revision_required`, `additional_evidence_required`, or `review_required` and
leaves dependent quality/approval steps inaccessible. A high direct score or a
generic acknowledgement cannot waive this condition. Source corrections or new
evidence use a new immutable run/workflow rather than rewriting a historical
review. No automatic revision, migration, specialized approval, or canonical
write authority is added.

## Verification

`tests/test_geometry_detail_review_v3.py` covers policy selection, untouched v2
serialization/replay, positive bounded review, absent/changed source and image
evidence, inferred/observed separation, declared attachment failures, intentional
modular separation, and failed or unscorable visual review independently of a
perfect silhouette/bbox score. Its native test is explicitly enabled with
`CBM_RUN_BLENDER_ASSEMBLY_SMOKE=1` and a supported `BLENDER_BIN`.
