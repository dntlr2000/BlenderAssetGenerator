# Authored-material identity split 0.2

This additive, explicitly selected companion supports already-authored MaterialPlan
jobs with a registered SolidRootAttachmentIntent 0.1 and its existing complete,
triangulated, single-slot, world-space MeshPayloadV02 solid domain. It does not
migrate or relax Material Identity Split 0.1. Its original absence evidence, AQ
adapter, user approval formats, serialization and defaults remain unchanged.

## Exact scope

A rule declares one original material, one unique new material, one existing
exclusive object and all existing matching ModelingPlan detail IDs. Source materials
must retain another user. Every matching detail row changes only target_material_id.
The scene retains every object, camera, transform, root, semantic and reference.

Each MeshPayload derivative changes only its single material identity, normalized
source material intent/fingerprint and one appended exact predecessor source hash.
Geometry, loop UVs, sharp/seam/crease/weight declarations, smoothing, topology,
face groups and modifier intent remain exact. No material_binding_derivative override
is allowed.

For existing texture/recipe graphs, exact metadata derivatives rename material IDs
and contained graph locators. A cloned manifest selects only the declared host's
exact existing detail rows. All remaining row fields, UV fingerprints/placements,
channels, scalars, shader recipes (including explicit 0.5.1 volume values), image
bytes and rights/provenance remain unchanged. Media is copied byte-for-byte once
per shared source material into a run-owned bundle; clone manifests share that
bundle. Original manifest, recipe and MaterialPlan bytes remain untouched. Relative
manifest-local image/mask/recipe paths and job-relative recipe-to-manifest paths
are separate contracts. Finite visited traversal handles their path cycles.
An ordinary promoted MaterialPlan recipe may use a different contained job-relative
locator from the manifest-local recipe only when both bounded files are exactly
byte-identical. The effective MaterialPlan locator remains selected and both paths
remain in the exact dependency closure. Whitespace-only differences, latent recipe
substitution, foreign identities, escaped paths and stale or changed bytes fail
closed; this compatibility rule rewrites no source graph or historical evidence.

The split always leaves material closure `pending_native_material_workflow`.
It grants no MaterialPlan promotion, recipe appearance change, human beauty
acceptance, package acceptance or destination authority.

## Two explicit authority domains

- `authored_material_registered_solid_root_user_only`: an exact caller-authored
  specialized user approval and original user-decision bytes are required.
- `authored_material_registered_solid_root_delegated_technical`: a separate
  AuthoredMaterialIdentitySplitDelegationV02 binds the original user question/reply
  files and message references, the five exact current source hashes, the complete
  source dependency map and the exact finite clone/detail rules. The delegation
  permits one assistant technical decision within that scope; it does not assert
  user inspection or approval of future candidate hashes. A separate
  AuthoredMaterialIdentitySplitTechnicalApprovalV02 records actor
  `delegated_assistant` and exact later candidate/native hashes. Separate technical
  decision bytes and consumption records retain `user_approval_consumed=false` and
  `aq_authority_consumed=false`.

No generic paired approval, another profile's decision, open-ended delegation or
AQ authority can substitute for these contracts. A preapproval/request is never
approval. An existing plan cannot silently switch domains.

## Preparation and native proof

`material_identity_split.authored_service.prepare_authored_material_identity_split`
takes job_root, run_id, exact clone_rules, source_material_plan_mode (`current` by
default) and optional delegation_path. Omitting delegation_path explicitly selects
the direct-user profile. A supplied delegation must already be complete and exact;
the service does not generate user delegation or user decision text.

Use `authored_split_runtime.source_dependency_snapshot(root, scene, model,
material_plan, metadata)` to observe the source dependency map for the caller's
bounded delegation document. This is an observation, not permission. The source
MaterialPlan/SceneSpec/ModelingPlan/job/Blend and reference/source closure are
rechecked before the first staged plan artifact is created.

`run_authored_material_identity_split_preapproval(root, plan_path=...)` runs fixed
Blender 5.0.1 clone/inspect/validate scripts in a run-owned shadow. It opens the exact
bound source Blend and verifies its actual source mode/provenance before copying
only the declared source materials and assigning their clones to the declared hosts.
Every retained material stays present with its original effective shader graph.
Canonical MaterialPlan bytes remain an observation until a separate material workflow.
No ordinary SceneSpec-only rebuild constructs this candidate.

Complete source and Float32 root-ball proofs are recomputed. Native raw/evaluated
positions, topology, loop UVs, sharp/seams, smoothing, normals, attributes and
transforms are fully digested, never sampled. Native metadata changes are restricted
to exact v02 payload hashes/source fingerprints/material IDs, assembly ModelingPlan
hashes, prospective build provenance and optical-boundary material identity fields.
All other object/scene custom metadata remains exact.

Every retained and cloned material is compared through complete native scalar RNA
settings, shader node/socket default values, ordered links, mapping/ramp state,
volume graphs and image interpretation/sampling state. Only declared identities and
contained metadata/media locators normalize. The proof also binds object visibility,
camera/light settings, world shader, render/color-management settings and collection
visibility. Unsupported nodes, nonlocal IDs, animation/drivers, constraints, shape
keys, additional scenes/view layers, compositor/sequence processing and external
world/light textures fail closed. The only supported shader group is the bounded
empty optical-volume export marker. Clean unpacked FILE images bind exact file
hashes and interpretation settings without allocating decoded pixel arrays. Generated,
packed, dirty and multi-view images are rejected.

The fixed clone step saves absolute contained image locators without relative path
remapping, then independently reopens, inspects and validates the exact final Blend.
Its provenance mode is `authored_identity_preserved`, distinct from the unchanged
ordinary `current` and `scene_spec_only` builders. The historical closure binds the
source Blend, source MaterialPlan and source build-provenance hashes. An ordinary
recipe-skipping rebuild cannot reproduce this specialized fingerprint.

`authored_split_runtime.collect_preserved_authored_split_provenance(root)` is a
read-only verifier, never a builder mode. It requires the exact committed specialized
tip, complete authority/native history, all four current post-commit hashes and the
exact archived prebuilt Blend. Replaced/rebuilt Blend bytes fail this verifier while
remaining eligible for separately authorized later material-workflow validation.
The ordinary material workflow uses freshly generated standard geometry validation
and UV inventory before candidate scaffold, authoring and promotion; its gates are
not weakened or bypassed. Original source/clone manifests and recipes remain
immutable history while that distinct workflow authors current material closure.

Limits are checked before model parsing, source proof or staging: 1–128 unique clone
rules, 8 MiB source JSON, and the complete source-plus-prospective-candidate dependency
union at 512 files/64 MiB. Native executable/script hashes and exact fixed scripts are
retained. Machine schema filenames use `material_identity_split_authored_*` so this
companion does not enter the existing AQ authored-material schema namespace.

## Apply and recovery

For direct user authority, call
`publish_authored_material_identity_split_approval` with the complete approval
model, exact user_decision bytes and explicit_user_decision_observed. For the
separate technical domain, call
`publish_authored_material_identity_split_technical_approval` with its complete
technical approval model, exact technical_decision bytes and
explicit_technical_decision_observed. Neither helper invents the decision.

`apply_authored_material_identity_split(root, intent=...)` accepts only the matching
strict direct-user or technical ApplyIntent. It checks the actual passed root
against workspace.job_dir, takes the existing shared job lock, revalidates exact
current authority and complete source/F32 proofs, then archives four files and
consumes one logical authority. SceneSpec, ModelingPlan, job metadata and the exact
prebuilt Blend move together through journaled CAS. Every publication/write/final
proof boundary rehashes all tracked bytes, the preserved MaterialPlan and complete
source/candidate closure. No canonical rebuild occurs while pending.

Every pending partial specialized journal blocks ordinary host and stdlib/Blender
readers. `recover_authored_material_identity_split(root, run_id=...,
apply_intent_sha256=...)` restores only exact before/after owned states. It handles
crashes between intent, global claim, local consumption and journal publication.
Concurrent third-state edits are preserved and recovery fails closed. Interrupted
rollback resumes the same consumed intent. Apply and terminal recovery replay are
refused. Global consumption claims also detect a removed run after tip rollback.

Specialized and original generic attachment records share one bounded predecessor
chain, preserving the original registration. Missing history, forks and rollback to
an older committed tip fail closed. Current-tip checks cover scene/model/job only:
the archived prebuilt Blend stays hash-pinned, while a later separately authorized
native material rebuild may legitimately replace the current derived Blend.

Limits remain 64 attachment records, 512 unique dependency files, 64 MiB complete
closure and 8 MiB individual JSON/ordinary evidence files. Native Blend archives
have a separate 512 MiB binary bound. No limits, approvals or reader gates are
silently bypassed.

## Public surfaces and testing

CLI commands use `authored-material-identity-split-` plus plan, preapproval, status,
approval-request, approve, approve-technical, apply or recover. MCP exposes the
corresponding explicit authored names. Planning optionally takes delegation_path;
the technical approval command is separate from direct user approve.

`tests/test_authored_material_identity_split.py` separates binding-only synthetic
fixtures from actual native opt-in tests. Enable native proofs with
`CBM_RUN_AUTHORED_SPLIT_NATIVE=1` and the supported Blender 5.0.1 executable. Every
fixture approval/delegation is synthetic; no production authority is generated.

The delegation's `original_delegation_id` hashes original question/reply message
references and bytes plus finite source/task scope, excluding wrapper/run IDs and
timestamps. A second original-conversation claim prevents scope rewrapping from
reusing the same reply. Both claims bind the exact single ApplyIntent, survive
rollback, and reject a new grant wrapper or a second candidate.
