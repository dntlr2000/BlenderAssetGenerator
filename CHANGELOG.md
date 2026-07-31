# Changelog

## 0.9.0

- Added backward-compatible ModelingPlan surface-detail routing so shallow windows, seams,
  labels, rivets, painted panels, and repeated marks remain outside SceneSpec geometry unless
  silhouette, structure, gameplay, or physical transparency requires a mesh. Added exact V0.5
  UVMap/PBR TextureManifest bindings, build provenance, V0.6 coverage reporting, PDF summaries,
  V0.8 completion checks, CLI/MCP validation, schemas, tests, and Korean guidance without changing
  SceneSpec `0.2.0`, material `0.5.0`, QA `0.6.0`, or orchestration `0.8.0` contract versions.
- Added optional standard-only V0.6 bounded visual-convergence sessions with exact plan-hash approval, current direct-QA/camera/source binding, default three and hard maximum five iterations, direct-score and silhouette-IoU targets, constraint non-regression, immutable per-iteration receipts, rollback, and terminal JSON/PDF evidence.
- Added CLI/MCP plan, approve, run, status, and cancel surfaces plus V0.9 read-only active/history audit coverage. Manual candidate-by-candidate guarded revision remains the default, `background_exterior` still performs exactly one canonical QA with no post-QA auto revision, and convergence never replaces InteriorScope, V0.7 optimization, or Destination Handoff approvals.
- Hardened convergence with a non-empty exact initial-input hash map, exact initial candidate/build/constraint snapshots, a shared canonical SceneSpec write lock and compare-and-swap, source/result build-contract validation, immutable before/after constraint evidence, QA/candidate/build receipt continuity, durable cancellation receipts, orphan-terminal replay detection, and explicit execution/status-only flags plus next-action reporting for legacy partial plans.
- Added a strict hash-bound visual-convergence host-safety-envelope Schema. Excluded all InteriorScope-classified objects and material edits regardless of plan contents, re-derived the envelope at approval/run time, and allowed CLI/MCP path limits to narrow—but never broaden—its path, operation, or delta authority.
- Limited each host/MCP invocation to one recoverable staged Blender iteration so timeouts do not create an unresumable immutable directory. Receipt-less staging must be recovered before cancellation or terminalization, and a terminal session with remaining staging is an integrity failure.
- Added canonical V0.6 timestamp QA-run ID compatibility, complete seven-pass provenance auditing, terminal SceneSpec snapshots, rollback archive/current-content compare-and-swap checks, and fail-closed fast-workflow QA ownership detection.
- Hardened converted portable glTF delivery by promoting the portable atlas to UV0, verifying every converted material TextureInfo uses effective `TEXCOORD_0`, requiring textured primitives to expose `TEXCOORD_0` and normal-mapped primitives to expose tangents, and rejecting malformed texture indices, format mismatches, missing converted-material bindings, or unverified round-trip UV contracts.
- Propagated accepted clean-import UV-association warnings into Destination Handoff context, limitations, and PDF evidence. The warning remains explicit because file-level binding and imported UV0 readiness do not prove topology-independent loop-to-vertex UV identity or destination-runtime parity.
- Added an execution-policy-independent `reference_content_scope` for new jobs:
  backward-compatible `full_reference` or explicit `primary_object_only` with a
  required target subject.
- Added fail-closed ModelingPlan, SceneSpec, build-provenance, workflow
  continuation, and V0.6 subject-mask enforcement so object-only jobs preserve
  primary/supporting parts while excluding independent terrain, ground,
  vegetation, rocks, props, backdrops, and atmospheric context.
- Preserved legacy and standard workflows by defaulting missing scope metadata
  to `full_reference`; changing a job's scope or target requires a new job.
- Split new background fast workflows into independent execution and quality outcomes. Structurally successful previews now deliver review evidence as `completed` / `delivered_for_review` with `quality_status=passed|needs_revision|unscorable`.
- Added workflow-owned primary/supporting/decorative/ground-background role maps and ground-independent primary object-ID silhouette and bbox evidence without changing SceneSpec `0.2.0`.
- Added at most two low-resolution pre-QA fit refinements with immutable SceneSpec candidates, exact attempt metrics, strict improvement-only promotion, history, and hash-bound promotion receipts. Canonical V0.6 QA remains exactly one seven-pass run.
- Reserved `requires_standard_workflow` for actual scope and safety boundaries, retained `orchestration_artifact_conflict` for unexpected ownership/fingerprint changes, and kept ordinary Blender/timeout/dependency failures separate.
- Added hash-bound background quality JSON, first-page PDF quality warnings, standard revision targets, and V0.7 review propagation for non-passing source quality without bypassing exact optimization-plan approval.
- Fixed new V0.8 workflow artifact lifecycles so expected downstream material promotion and derived rebuilds no longer retroactively stale valid upstream completions.
- Added separate workflow-owned material scaffold/authored candidates, strict canonical MaterialPlan promotion with history and immutable receipts, and exact candidate-bound agent completion.
- Added execution-time snapshots for shared derived `.blend`, preview, inventory, validation, and report outputs; exact QA-run binding now treats `qa/latest.json` as a convenience pointer only.
- Added workflow-owned PDF paths and machine-readable `orchestration_artifact_conflict`, distinct from scope/safety-only `requires_standard_workflow` and ordinary host failures.
- Preserved legacy V0.8 workflow readability and left existing blocked workflows immutable; the corrected lifecycle contract applies only to newly planned workflows.
- Verified Blender 5.0.1 fast `preview_only` completion, one direct seven-pass QA without generated targets or automatic revision, exact V0.7 approval stop, FBX package completion, and GLB/FBX/OBJ clean-import regressions in isolated workspaces.
- Added an explicit V0.8 `background_exterior` execution policy with `preview_only` and `portable_package` delivery scopes while retaining `standard` as the backward-compatible default.
- Added a bounded single-author exterior geometry pass, deterministic local material limits, one direct suggest-only QA run, combined PDF delivery, and fail-closed `requires_standard_workflow` instructions for actual fast-lane scope/safety risk discovery.
- Replaced the initial high-finding delivery blocker for newly planned workflows with a machine quality report that preserves every visual warning while allowing review delivery.
- Bound package-only continuation to the exact completed preview plan, terminal completion, QA run, canonical source, and embedded build fingerprints, with a non-retryable prerequisite recheck before V0.7.
- Removed only generic review gates from background plans; the exact V0.7 optimization-plan approval, immutable package, and clean-import round trip remain mandatory for portable delivery.
- Exposed the policy through CLI and MCP, regenerated strict V0.8 schemas, and added isolated preview/package planning gates without changing SceneSpec, material, QA, or portable contract versions.
- Added strict `0.9.0` environment-probe, workspace-audit, local-queue, attempt-receipt, queue-lock, and stability-PDF manifest contracts while preserving every V0.2-V0.8 asset contract version.
- Added privacy-safe host evidence that hashes existing Blender compatibility results without persisting repository, workspace, or external-source absolute paths.
- Added bounded read-only workspace audits for immutable source hashes, contract readability/version compatibility, workflow pointers, path escapes, temporary evidence, and scan limits without automatic repair or migration.
- Added a one-writer, one-worker local dispatcher for existing V0.8 workflows with leases, immutable receipts, approval/agent boundaries, explicit single-use failed retry, cancellation, and expired-lock recovery.
- Added an exact-source-hash V0.9 stability PDF and sidecar manifest, CLI/MCP surfaces, checked-in JSON Schemas, isolated Windows/POSIX gate scripts, and release-candidate documentation.
- Added optional approval-bound V0.6 multi-view interior QA with 4/6/8-direction camera plans, exact seven-pass rendering per selected view, semantic visibility and structural findings, manual-only candidates, contact sheets, QA PDF projection, V0.8 routing, and V0.9 read-only audit coverage.
- Kept interior QA temporary cameras and object isolation out of the authoring `.blend`, required a current approved InteriorScope, and refused to invent an interior reference-similarity score when no calibrated interior references are mapped.
- Added strict `0.9.0` Codex Destination Handoff contracts and CLI/MCP plan, generate, validate, and status surfaces for passed GLB/FBX clean-import packages.
- Added an immutable movable envelope containing the exact package copy, round-trip evidence, semantic assembly, portable material/PBR mapping, LOD/Collider context, safe destination prompt, import schemas, limitations, and exact-hash PDF.
- Bound optional V0.8 `destination.handoff` completion to exact package and handoff hashes, and extended V0.9 audit, stability/export/full PDF, feature reporting, tests, and isolated gates with handoff validity.
- Kept Unity, Unreal, and custom automatic engine adapters, runtime parity claims, distributed scheduling, cross-platform support claims, automatic migration, CAD parsing, rigs, and animation outside the verified V0.9 core. Automatic Destination Adapters are deferred until V1.1 or later after a destination is selected.

## 0.8.0

- Added strict `0.8.0` contracts for short requests, deterministic intent routing, immutable workflow plans, reconstructed workflow state, generic approvals, agent completion markers, execution attempts, and exclusive locks.
- Added isolated new-job defaults, primary-reference reuse rejection, staged auxiliary-view promotion, and fail-closed ambiguity handling for existing jobs. Explicit `new_asset` is rejected for every existing job even when the primary-reference hash matches.
- Added resumable deterministic host execution with bounded step counts, exact input/output freshness, unique attempt receipts, explicit failed-step retry, abandoned-attempt finalization, cancellation, and expired-lock recovery.
- Added approval-aware orchestration across proxy/detail geometry, material swatches, Visual QA, optional interiors, and V0.7 portable packaging without replacing specialized hash approvals.
- Added destination capability reporting. Unity, Unreal, and custom adapters remain unsupported and explicitly fall back to the engine-neutral portable-package boundary.
- Added CLI/MCP orchestration surfaces, schemas, tests, documentation, and isolated V0.8 gate scripts while preserving SceneSpec `0.2.0`, material `0.5.0`, QA `0.6.0`, and portable asset `0.7.0`.
- Refreshed the top-level README, start-page routing, and V1.0 roadmap so the current V0.8 baseline, verified environment, unsupported boundaries, and V0.9 entry scope are stated consistently.

## 0.7.4

- Added a mandatory pre-optimization review showing exact LOD, collider, cleanup, consolidation, and budget settings before any derived optimization.
- Added exact plan SHA-256 approval bound to job, source, profile, preflight, run, and single-use optimization consumption.
- Added profile-level LOD enable/disable and collision strategy controls plus review/approval evidence in package snapshots and export PDFs.
- Verified the isolated Blender 5.0.1 V0.7 gate for GLB, FBX, OBJ, portable material conversion, clean-import round trip, and PDF reporting.

## 0.7.3

- Added backward-compatible AssetProfile consolidation and static cost-budget policies while keeping the portable contract at `0.7.0`.
- Added derived-only loose-geometry cleanup, duplicate material-slot cleanup, exact duplicate collider removal, and semantic/material/LOD/UV-safe batching.
- Added immutable `StaticAssetCostReport 0.7.0` evidence with before/after object, material-slot, draw-call proxy, triangle, collider, instance-group, and overlap metrics.
- Preserved total triangles and per-source LOD ceilings through consolidation; legacy stored profiles default to `consolidation.mode=none`.
- Added advisory repeated-mesh detection and broad-phase AABB overlap findings without claiming runtime instancing or deleting internal/coplanar faces.
- Added warning/fail cost-budget enforcement, package snapshots, export-PDF projection, CLI/MCP controls, schema coverage, and isolated Blender gate assertions.
- Kept canonical SceneSpec, geometry payloads, material contracts, textures, and authoring `.blend` read-only throughout cleanup and consolidation.
- Separated host-only Pydantic validation from Blender's Python 3.11 provenance collector so Blender 5.0.1 does not depend on the host Python ABI.

## 0.7.2

- Added the optional `InteriorScope 0.1.0`, approval, and validation contracts without changing Geometry SceneSpec `0.2.0`.
- Made absence of `architecture/interior_scope.json` a valid `default_disabled` state so legacy and exterior-only jobs do not gain files or interior geometry implicitly.
- Required an explicit user request plus `architecture/interior_scope.approval.json` bound to the exact current scope SHA-256 before any reserved interior object can pass validation.
- Added fail-closed checks for normalized explicit interior tags and common room namespaces, approved/excluded prefixes, optional level/space locators, proxy/detailed furnishing limits, measured constraint coverage, measured mode, and visible-only/measured evidence.
- Added CLI and whitelisted MCP operations to initialize, inspect, and validate a scope; approval is a manual interactive CLI-only action requiring the complete scope hash, so creating a draft never approves or changes SceneSpec.
- Bound explicit scope and approval hashes into build provenance so changing the authorized interior boundary makes derived builds stale.
- Preserved exterior facade helpers such as backing, reveals, recesses, and exterior wall thickness when they are not represented as interior objects.
- Kept interactive doors, navigation, gameplay volumes, engine-specific room systems, light baking, and runtime interior shaders outside the current static-geometry scope.

## 0.7.0

- Added separate `0.7.0` contracts for engine-neutral AssetProfile, source provenance, mesh preflight, OptimizationPlan, LOD, collision, UV, texture packing, immutable packages, and clean-import round trips.
- Added three conservative static-asset profiles: `portable_gltf`, `fbx_interchange`, and `obj_legacy`.
- Added read-only Blender topology inspection and stale-source/build-fingerprint rejection before optimization.
- Added run-owned optimized Blender scenes with deterministic LOD, collider, and UV manifests while preserving canonical geometry and materials.
- Added byte-preserved raw PBR packaging plus deterministic glTF ORM derivation with explicit `R=occlusion`, `G=roughness`, and `B=metallic` provenance.
- Added atomic GLB/FBX/OBJ package creation, relative-path/hash receipts, clean Blender reimport, bounds/identity/dependency validation, and immutable validation evidence.
- Added embedded FBX image dependencies and package-relative OBJ/MTL texture copies while preserving raw PBR sidecars as the authoritative reconstruction inputs.
- Added CLI and whitelisted MCP surfaces for profile initialization, preflight, optimization, packaging, validation, and status.
- Added `export` PDF reporting from canonical V0.7 evidence and extended `full` reports without making PDF data authoritative.
- Added isolated V0.7 gate scripts that use a fresh smoke workspace and `geometry_showcase` only.
- Kept engine-specific Unity, Unreal, or other runtime import adapters outside V0.7 until a destination is explicitly selected.

## 0.6.0

- Added V0.5 MaterialPlan, ShaderRecipe, TextureManifest, BakeManifest, and validation contracts while retaining SceneSpec `0.2.0`.
- Added a Blender-safe shader-recipe loader, portable Principled surface overrides, and a whitelisted procedural Noise/ColorRamp/Bump layer.
- Added material plan scaffolding, host contract validation, Blender node/image/color-space/UV inspection, and fixed sphere/plane swatches.
- Added nine deterministic Pillow PBR presets, six generated source channels, manifest attachment, hash/provenance checks, and Blender image-map execution.
- Added feature-probed Smart UV generation for explicitly UV-mapped materials and bounded Cycles baking for five portable PBR channels.
- Added canonical build provenance across SceneSpec, camera, external geometry, material contracts, texture channels, and source `.blend`; stale QA and bake runs now fail before output.
- Added V0.6 fixed-camera beauty, silhouette, object ID, material ID, normal, depth, and wireframe passes with hashes and semantic color maps.
- Required the exact seven-pass set and validated the actual Blender camera against the fixed SceneSpec camera before QA.
- Added direct reference-mask and observed semantic-region QA with immutable per-run records.
- Added an optional advisory image-target provider interface whose output cannot override direct evidence or authorize revisions.
- Added an explicit existing-file target handoff that preserves the exact prompt plus provider/model/version/seed and output hashes.
- Added safe revision candidates, explicit hash-bound single-use approval, one-iteration convergence checks, and automatic SceneSpec restoration/rebuild on regression or failure.
- Extended rollback protection across canonical replacement/reporting and compare measured constraints by stable ID, status, tolerance, and normalized residual.
- Added CLI/MCP tools, feature flags, skills, prompts, tests, and Blender 5.0.1 integration gates for the new layers.
- Kept profile packing and engine import outside V0.6. V0.7 adds engine-neutral glTF ORM/raw packaging, while Unity/Unreal-specific packing and import remain deferred until a destination is selected.

## 0.4.0

- Added deterministic reference analysis, content masks, edge diagnostics, dominant colors, symmetry scores, and optional OpenCV line clusters.
- Added camera-solution and modeling-plan schemas.
- Added measured constraint contracts and residual evaluation against Blender world-space inventory.
- Added safe `add-view` and atomic duplicate-resistant job creation.
- Added Blender compatibility probe with optional GLB/OBJ/FBX smoke exports.
- Added Blender 5.0.1 EEVEE feature probing, AgX fallback, Python exit-code propagation, and MCP stdin isolation.
- Added world-space object/family bounding boxes and Blender runtime metadata to inventory.
- Added quick-reference, reference-analysis, and measured-constraint Codex skills.
- Retained SceneSpec `0.2.0` for v0.2 geometry compatibility.

## 0.2.0

- Geometry Core: custom mesh, profile extrusion, revolve, curve, terrain, modifier stacks, and guarded revision plans.
