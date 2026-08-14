# Changelog

## Unreleased — AQ v2 Material Closure Stabilization 0.1.0

- Added additive strict `0.1.0` contracts for graph-derived material dependency closure and receipt,
  source binding, host-only MaterialGraph rebinding, promotion preflight, finite preflight resource
  accounting, isolated shadow compile, neutral preview, appearance approval and single-use
  consumption, canonical/attempt consistency, framework failure, retry supersession and material-only
  repair sessions. Project `0.9.0`, canonical SceneSpec `0.2.0`, legacy evidence meanings and all
  existing profile activation states remain unchanged.
- Made one closure projection authoritative for controller request, assignment and completion input
  maps. Planned MaterialPlan and rebound MaterialGraph outputs are exact-hash-bound; completion uses a
  non-circular structural binding. Missing ShaderRecipe, TextureManifest, channel, mask, reference,
  UV/surface-detail evidence, stale provenance and reduced maps fail closed before approval.
- Added host-owned path/hash-only graph rebinding and a full approval-before-controller preflight with
  isolated Blender 5.0.1 compile/build/inspect/validate checks and an actual neutral preview. A
  preflight failure creates framework failure evidence and consumes no appearance approval,
  controller invocation or canonical promotion authority.
- Kept `validate_and_promote_material_controller_result_v2` as the only canonical MaterialPlan
  promotion/rebuild/rollback authority. A specialized `MaterialAppearanceApproval` must bind the
  candidate, rebound graph, closure, passed preflight, preview, canonical geometry/blend and UV
  fingerprint, and is consumed at most once.
- Added additive AQ v2 material-attempt/canonical consistency projection and material closure binding
  on controller completion without rewriting existing AQ state. Raw AQ state remains visible beside
  closure, preflight, approval, controller, promotion, rollback and consistency companions.
- Added equivalent CLI/MCP surfaces for closure plan/status, graph rebind, preflight run/status,
  shadow compile, appearance approval, state consistency, framework failure status, retry
  supersession and material repair session plan/run. These surfaces do not synthesize user approval,
  ControllerResult, canonical state or destination writes.
- Audited the Crystalgun incident without editing history. The verified head is sequence `0012`,
  `terminal/cancelled/none`, not the previously reported running `0011`. Published discrepancy/failure,
  old-retry approval-absence/supersession and repair-session supersession evidence append-only. The
  final repair dry-run published an exact dependency closure and then stopped `preflight_failed` on
  missing image-backed UV coverage before Blender, approval, controller, promotion or canonical write;
  canonical MaterialPlan, `MaterialPhaseReceiptV2`, neutral preview and IQ evidence remain absent.
- Added a job-specific framework-literal gate and exact source-inventory/archive contracts. Historical
  workspace evidence is outside the executable framework scan and is never rewritten to make the gate
  pass. Archived the two exact incident recovery source files and inventory under job-local history
  before removing them from executable common source.
- Added architecture, test, migration, verification, incident and reusable prompt documentation and
  synchronized AQ v2, ImageGen Material Loop, material authoring, controller, delivery and
  surface-detail guidance. Commands and gates not actually executed remain `unverified` in the
  verification record.
- Final full regression passed with 1,750 tests, 62 skips and 8 warnings; an actual Blender 5.0.1
  preapproval fixture passed once while consuming zero approval/controller/promotion authority. Full
  authorized promotion, `MaterialPhaseReceiptV2`/IQ, ImageGen-localized and crystal/emission/alpha
  Blender fixtures, and chained V0.7–V0.9 gates remain unverified.

## Unreleased — Reversible terminal workspace archive

- Added strict V0.9 workspace relocation plan and receipt contracts with deterministic full-tree
  digests, exact workflow/job bindings, same-volume atomic rename, immutable control evidence, and
  crash adoption between rename and receipt publication.
- Added host CLI surfaces to list eligible jobs, archive one terminal job, restore one exact archive
  receipt, and resume one persisted relocation plan. No new MCP/controller relocation authority was
  added.
- Completed/cancelled jobs are eligible by default. Failed jobs require explicit `--allow-failed`;
  active, waiting, blocked, workflow-less, queued, locked, non-terminal dispatch, AQ/AQ v2, linked,
  escaped, stale, or tampered jobs fail closed.
- Archive storage defaults to the same-volume `workspace_archive/` sibling. Archived evidence is not
  migrated or loaded in place; exact restore returns it to `workspaces/<job-id>` before normal use.

## Unreleased — Codex ImageGen 0.2 Material Loop Closure

- Added an additive strict material-loop companion without changing project `0.9.0`, canonical
  SceneSpec `0.2.0`, the existing ImageGen core `0.1.0`, MaterialAuthoring `0.2.1`, or legacy
  evidence meanings. Both AQ v2 profiles remain `disabled_experimental`.
- Added native-output adoption that preserves the exact PNG as immutable `original.png`, plus
  requested-operation-bound deterministic normalization whose receipt recursively binds the exact
  adoption receipt. Existing core dimension rules remain exact; silent stretching, orphaned native
  provenance, and post-hoc replacement of an already selected candidate fail closed.
- Added `CodexImageNativeCorePreparationReceipt 0.1.0` to bind native adoption/original and normalization
  evidence to core completion, candidate, generated-image evidence, quality, selection, and the copied
  core image with exact normalized-to-core byte identity. The existing core contracts remain unchanged;
  native-fed bridge/controller/promotion evidence cannot omit or substitute this receipt.
- Added current-task, non-human semantic review and companion-only multi-candidate ranking. Every
  candidate must have exact review/ranking grounds; missing or unresolved evidence yields
  `review_required`. Precedence is file hard gate, deterministic quality, semantic outcome,
  material-role suitability, repair cost, then stable candidate ID. The companion selection receipt
  remains bound through bridge, controller input, and promotion evidence.
- Added strict V0.5 normalized/bridge evidence, exact canonical-material absence, material bridge
  plans/controller inputs/bindings, fixed neutral preview, promotion receipts, append-only state and
  terminal contracts. Full job/workflow/dispatch/session/profile identity and exact input digests are
  revalidated at each boundary.
- Connected staging evidence to the existing ControllerExecutor and host material promotion service.
  `exact_adoption` now requires a separate actual Blender shadow-compile preflight of the exact V0.5
  candidate bytes while preserving the original staging-only/compile-`not_run` receipt meaning;
  `controller_authored_completion` accepts only the exact material plan, material graph and completion
  output set. Neither controller mode receives canonical or destination write authority.
- Reused the existing host MaterialGraph compile, canonical MaterialPlan compare-and-swap, Blender
  rebuild/inspect/validate and rollback path to issue an actual `MaterialPhaseReceiptV2`. The original
  MaterialAuthoring `0.2.1` `not_run` receipt bytes remain immutable.
- Added exact promotion/state/IQ crash recovery and status fields for controller request/result,
  delivery progress and remaining companion budget. Material promotion is distinct from IQ pass;
  the companion uses `quality_approved` only when the exact base AQ quality terminal/freeze passed.
- Added nine CLI commands and nine equivalent MCP tools for bridge plan/status/run, isolated Blender
  exact-adoption preflight, host promote/resume, native normalize `adopt|prepare|execute`,
  semantic-review status and one-step AQ/IQ continuation. The preflight creates no ControllerResult
  or canonical/destination write. Existing five core ImageGen CLI/MCP surfaces are unchanged.
- Added actual Blender 5.0.1 fake-family material/IQ fixtures for wood, signage/decal, emissive and
  crystal. Fake evidence remains explicitly test-only and is not actual ImageGen or generalized
  material-quality evidence.
- Reused the preserved historical built-in ImageGen PNG only as a new immutable native input; no
  fresh ImageGen invocation occurred. Current-task non-human semantic review ended
  `review_required`, so the actual-source run stopped before canonical promotion and did not claim
  MaterialPhaseReceipt, IQ, package, or human review.
- Removed synthesized V0.7 approval from the Material Loop delivery fixture. Fake-family flows stop at
  `waiting_for_v07_approval`; separate raw GLB/FBX export and Blender clean-import runs are mechanism
  evidence only, with no package manifest, accepted production result, completed delivery terminal or
  destination-runtime parity claim.
- Added Material Loop architecture, getting-started, test-plan, migration and verification documents
  and reconciled the existing ImageGen, AQ v2, MaterialAuthoring, ControllerExecutor, DeliveryProfile,
  README and roadmap surfaces. Added a Korean copy/paste prompt collection, updated the general
  reference-validation prompt collection, and added an internal material-loop orchestration prompt.
- Recorded the executed local result instead of placeholders: full pytest `1569 passed, 56 skipped,
  8 warnings`; focused material-loop security/schema/service/public `160 passed, 1 skipped`; final
  public/schema/catalog/CI parity `59 passed`; fake four-family actual Blender material/IQ `4 passed`;
  and approval-free review/export-mechanism coverage `5 passed, 1 skipped`. Historical built-in source
  replay remained `review_required`; fresh built-in ImageGen full-loop, human approval, production
  package acceptance, destination parity, hosted CI, and the approval-synthesizing legacy chained gate
  remain explicitly unverified or not run.

## Unreleased — Codex Built-in ImageGen Texture Provider 0.1.0

- Added the separate `autonomous_static_prop_v2_codex_imagegen` profile as an explicit
  `disabled_experimental` companion over unchanged AQ v2 local-only behavior. Planning requires both
  ImageGen opt-in and disabled-profile opt-in; loading or auditing an existing session never enables
  it implicitly.
- Added strict `0.1.0` provider, budget, plan, assignment, completion, candidate, generated-image,
  quality, selection, and terminal evidence; `ImageToMaterialAdoption 0.2.0`; and an append-only AQ v2
  ImageGen overlay state chain. Exact paths, SHA-256, identity, provenance, protected job inventory,
  budget, and predecessor bindings fail closed.
- Added a dedicated ControllerExecutor `codex_imagegen` phase for the current Codex task. It uses an
  execution-owned workspace, exact input snapshots and declared PNG/completion outputs, then replays
  the full request/result and receipt lifecycle before adoption. The repository does not create a
  Codex task or daemon; app exit leaves the same request waiting for an exact resume.
- Kept the provider credential-free and API-free: no `OPENAI_API_KEY`, OpenAI SDK image client,
  external HTTP provider, endpoint, or API billing contract is added. Built-in ImageGen remains a
  Codex-managed controller capability, distinct from repository MCP/network authority.
- Restricted generated pixels to direct `base_color`, `decal_rgb`, `emission`, or `opacity_source`
  roles. Added MaterialAuthoring `0.2.1` staging-only requests/manifests/receipts that perform bounded
  local lighting normalization and source-bound height, OpenGL normal, roughness, optional occlusion,
  and constant-channel derivation instead of accepting pseudo-PBR maps from ImageGen.
- Added exact local signage composition using a separate `ExactSignageTextEvidenceV021` artifact and
  hash-bound project bitmap-font JSON or TTF/OTF evidence. Exact user text is excluded from provider
  prompts; unknown or inferred text cannot carry or render invented glyphs.
- Added deterministic PNG dimension/detail/alpha/border/seam/emission checks, wood anisotropy advisory,
  preserved candidate decisions, and single selection. Semantic unwanted object/text and style or
  background alignment remain explicitly non-hard `unscorable`; deterministic pass does not claim
  human review.
- Added a deterministic fake controller for contract, negative, recovery, material, and Blender
  fixtures while keeping fake and actual built-in ImageGen controller/source kinds distinct.
- Bound capacity rejection and final controller timeout/failure/rejection/cancellation to one immutable
  terminal carrying the exact plan item, runtime trigger, controller request, and controller result.
  Waiting remains resumable; terminal-write crash recovery reuses canonical bytes and rejects tamper
  without spending generation budget or invoking the controller again.
- Added `codex-imagegen-status`, `plan`, `run`, `select`, and `adopt` CLI surfaces with equivalent
  MCP tools. `run` only publishes or resumes the controller request; two-mode `adopt` first prepares
  staging adoption and then accepts one contained MaterialAuthoring `0.2.1` request. The final public
  boundary is overlay `status=adopted`, `next_action=controller_promotion_required`; it does not resume
  base AQ or claim canonical promotion.
- At the core `0.1.0` release boundary, kept full material promotion, IQ, and package continuation
  outside core `adopt`; the later additive Material Loop section above supplies that exact bridge
  without rewriting this historical staging boundary.
- Added architecture, getting-started, test-plan, migration, verification, material-authoring, AQ v2,
  ControllerExecutor, README, and roadmap documentation. Exact executed results remain in
  `VERIFICATION_CODEX_IMAGEGEN_PROVIDER_KO.md` and do not activate the experimental profile by prose.

## Unreleased — Autonomous Quality Extension 0.2.0

- Added `autonomous_static_prop_v2` as an additive `0.2.0` overlay without changing project
  version `0.9.0`, canonical SceneSpec `0.2.0`, AQ v1 behavior, or any legacy evidence. The v2
  profile remains `disabled_experimental` and cannot be selected as a verified active profile.
- Added a bounded geometry-controller promotion → material-controller promotion → external
  Integrated Quality 0.2 submission chain. `needs_revision` or `unscorable` terminates with an exact
  non-production review bundle, `blocked` terminates without a bundle or freeze, and only a quality
  pass freezes the exact source before `review_only` or independently exact-approved GLB and FBX
  delivery.
- Added ControllerExecutor execution-owned workspaces with exact input snapshots, declared-output
  collection, request-bound receipts, strict crash adoption, and fail-closed path, symlink, extra,
  stale, hash-mismatch, and tamper checks. Controllers never receive canonical job-root write
  authority.
- Hardened `desktop_in_session` waiting recovery so public advance/run revalidate and adopt only the
  same immutable request and request-owned workspace. Waiting does not create a duplicate invocation
  or consume budget twice, while any protected job-inventory, request, result, profile, output, or
  receipt change fails before adoption.
- Reconstructed the complete executor lifecycle and exact stored result bytes for both execution-root
  and adoption recovery. Direct controller and delivery effects now require an active, unexpired,
  exact plan/profile/budget authorization; AQ v2 timeout terminalizes as nonretryable failure.
- Added public AQ v2 plan, status, single-step advance, bounded run, and cancel CLI/MCP surfaces.
  They preserve all specialized approval boundaries and never synthesize V0.7 optimization or
  destination approval.
- Hardened state reconstruction with exact predecessor transitions and monotonic budget checks.
  IQ submission/freeze now recomputes contour and semantic metrics from exact PNG bytes and rebuilds
  gates, findings, reentry, and outcome before exact report comparison. It then revalidates the current
  canonical and required geometry/material promotion receipts. Required scored landmark/multi-view
  evidence without typed host-verifiable inputs has no pass authority, authoritative hard findings
  block quality pass, and QualityTerminal validation recursively checks its exact IQ, freeze or review
  bundle, and nested artifacts.
- Added strict geometry and material candidate validation/promotion, runtime-whitelisted material
  compilation, IQ 0.2 contour/semantic/landmark/multi-view companion metrics, quality source freeze,
  review-only terminal evidence, and independent GLB/FBX delivery terminal revalidation.
- Added selected Blender 5 structural/material fixtures and a synthetic same-freeze dual-delivery
  fixture that performs independent GLB and FBX optimization, package, and clean-import checks.
  These fixtures do not establish generalized human reference quality or destination-runtime parity.
- Verified the latest shared tree with full pytest `1438 passed, 44 skipped, 8 warnings`; the AQ
  focused gate reported `485 passed, 22 skipped, 8 warnings`; the actual Blender AQ gate reported
  `34 passed, 6 warnings`; and the V0.7, V0.8, and V0.9 regression gates passed. The Codex App Server or
  supporting-client closed loop, human reference-quality review, and Unity/Unreal/custom runtime
  parity remain unverified, so `autonomous_static_prop_v2` stays `disabled_experimental`.
- Added the AQ 0.2 architecture, getting-started, test-plan, migration, verification,
  ControllerExecutor, delivery-profile, material-authoring, and quality-benchmark documents.

## Unreleased — Autonomous Quality Extension 0.1.0

- Added an explicit opt-in `autonomous_static_prop_v1` supervisor over newly created `standard`
  production workflows without changing the default `standard` or `background_exterior` policies
  and without changing the project version from `0.9.0`.
- Added strict `0.1.0` RootAuthorization, single-use machine PolicyAuthorization, immutable budget,
  state/transition/terminal, candidate, Integrated Quality, review-bundle, package-repair, reference,
  material-graph, structural-geometry, assembly, and topology companion contracts and checked-in
  Schemas. `preauthorized_profile` is policy authority, never synthesized user approval.
- Added local Reference Evidence with bounded foreground-mask candidates and perspective/orthographic
  camera hypotheses, plus deterministic fallback when OpenCV is unavailable. Hypotheses remain
  advisory and never mutate the canonical camera by themselves.
- Added parallel SceneSpec V03 `0.3.0` structural recipes for loft, sweep, multi-loop extrusion,
  boolean trees, and one whitelisted Geometry Nodes template. Public plan/apply CLI and MCP surfaces
  create exact-hash derived copies and receipts only; canonical SceneSpec `0.2.0` and legacy jobs are
  not automatically migrated. AQ structural assignments may additionally carry a full V03 candidate,
  materialize all structural objects into candidate-owned mesh/receipt/`.blend` evidence, and compile
  one path-backed V02 candidate for the existing build path before any canonical promotion.
- Added four-axis Integrated Quality companion evidence for reference alignment, structural
  integrity, material fidelity, and production readiness while preserving the existing V0.6 direct
  score. Hard gates, unavailable evidence, Pareto/lexicographic ranking, minimum gain, bounded
  budgets, duplicate/oscillation/plateau detection, and best-known candidate preservation prevent a
  single score or unbounded loop from authorizing promotion.
- Hardened candidate evaluation so build, inventory, validation, effective SceneSpec, assembly,
  topology, and quality provenance are candidate-owned. Eight named candidate hard gates feed the
  same hard-gate/Pareto/minimum-gain ranker, while unavailable material or production evidence stays
  unscorable.
- Hardened first-use PolicyAuthorization by persisting, reloading, and fully revalidating exact
  root/profile/budget/target/dependency/predecessor/single-use/hash identity before any authorized
  side effect. The active profile keeps two bounded material rounds and routes cycle, plateau,
  repeated failure, or budget exhaustion to review instead of extending authority.
- Added exact terminal verification for IQ JSON/PDF/manifest provenance and mutually exclusive
  package/roundtrip versus review-bundle evidence. Quality-pass completion requires an immutable
  portable GLB and fresh passed clean-import roundtrip; quality non-pass creates a non-production,
  non-handoff-eligible review bundle.
- Added one bounded derived package-repair runtime for an immutable package-ID collision or an exact
  format-only roundtrip failure. It uses a fresh `-aqrNN` package ID and accepts only a fresh passed
  clean import; material, bounds, dependency, Blender, unknown, stale, and tampered failures remain
  fail-closed.
- Unified Windows long-path package and Destination Handoff directory hashing so generation and
  V0.9 postflight enumerate the same package-relative recursive file set while real missing, added,
  escaped, stale, or tampered files remain fail-closed.
- Added deterministic host/optional Blender benchmarks, AQ CLI/MCP surfaces, isolated gate scripts,
  migration/start/architecture/test/verification documentation, and explicit legacy V0.7–V0.9
  regression coverage. These fixtures validate contracts and materialization, not generalized
  reference reconstruction quality or destination-runtime parity.
- Verified on 2026-08-10 with Windows 11, Python 3.14.6, and Blender 5.0.1/Python 3.11.13 EEVEE:
  full pytest `1145 passed, 20 skipped, 8 warnings`, Ruff/doctor/GLB-FBX-OBJ compatibility passed,
  the AQ focused gate reported `195 passed, 2 skipped`, the actual Blender AQ bundle reported
  `14 passed`, the 8-case benchmark passed including three Blender structural cases, and the chained
  V0.7/V0.8/V0.9 gates completed. This verifies `autonomous_static_prop_v1` only and is not an
  arbitrary-reference before/after quality claim.

## 0.9.0

- Added explicit `desktop_in_session` execution for Asset Production Dispatcher and Delegated
  Production Controller. The current Codex Desktop task can now advance a dispatch without an
  external task API or binding, while launch/state evidence explicitly reports
  `approval_isolation=workflow_contract_only` and never claims per-task MCP/shell enforcement.
  Existing `client_mediated` remains the default and still fails closed until its exact restricted
  controller profile is client-attested. Both modes preserve all V0.8 approvals, fingerprints,
  single-writer locks, bounded convergence approval, V0.7 optimization approval, handoff approval,
  failed-retry boundaries, and V0.9 postflight audit.
- Extended standard bounded V0.6 convergence to authored `spatial_v1` assets. New plans bind a
  fresh five-view structural baseline; every result iteration captures another exact five-view
  evidence set, and semantic visibility/assembly regression vetoes acceptance and restores the
  archived canonical SceneSpec. Legacy/non-spatial sessions retain the fixed-camera path with an
  explicit `not_applicable` structural policy.
- Added an explicit `standard + bounded_after_v06` bridge to Asset Production Dispatcher and the
  Delegated Production Controller. The initial V0.8 workflow ends at one canonical V0.6 preview,
  the Controller plans but cannot approve the exact convergence plan, and every later advance
  executes or recovers at most one approved Blender iteration before a hash-bound V0.9 postflight.
  Package optimization and Destination Handoff remain separate, newly approved workflows.
- Added a backward-compatible explicit `standard + preview_only` V0.8 boundary so production
  convergence can preserve its completed baseline workflow without implicitly entering V0.7.

- Added strict `0.9.0` Asset Production Dispatcher and Delegated Production Controller contracts,
  eleven checked-in Schemas, CLI/MCP surfaces, and V0.9 read-only audit coverage. A new reference,
  purpose, content scope, portable profile, and destination hint now prepare one new V0.8
  workflow plus a hash-bound client-mediated Codex task launch bundle.
- Added a controller-only canonical-writer policy with at most three read-only advisory subagents,
  exact workflow/input-bound assignments, and immutable hash-chained advance receipts. Standard
  remains the default execution policy; `background_exterior` remains explicit and must use a
  separate post-package Destination Handoff flow.
- Hardened task launch and binding with an allowlist-only controller MCP profile, explicit denied
  approval/retry tools and equivalent shell-command policy, client-enforcement requirement,
  controller-tool-profile SHA-256 covering the required client capability list, exact task-binding
  receipt, and fail-closed stale/tamper checks.
  The repository prepares but does not create or authenticate the Codex task; an enforcing
  supporting client remains responsible for actual task creation and tool/shell restrictions.
- Preserved every existing generic and specialized approval, failed-step retry and Destination
  Handoff exact-plan boundary. Production completion additionally requires an atomic V0.9
  postflight audit receipt bound to the exact terminal workflow state and artifacts; repository
  contracts do not claim to prevent a malicious controller from using an unrestricted client shell.
- Hardened shared workflow locks so TTL expiry never steals a live, remote, unknown, or legacy
  owner; automatic recovery now requires a conclusively dead same-host PID and an OS-serialized
  lock transition. Production evidence paths reject traversal, symlinks, junctions, dangling
  leaves, and linked directory members before reads or writes.

- Added `candidate_review` as the default strategy for newly planned standard `revise_asset`
  workflows. The workflow-owned RevisionPlan is evaluated through isolated baseline/candidate
  builds, exact fixed-camera seven-pass QA, optional constraints, and authored `spatial_v1`
  five-view structural non-regression before one exact decision-hash promotion approval.
- Added immutable candidate decision, approval, promotion-receipt, and PDF-sidecar contracts plus
  CLI/MCP status and approval surfaces. Canonical SceneSpec and authoring outputs remain unchanged
  until the final approval; explicit `manual_guarded` preserves the legacy pre-application gate,
  and existing immutable workflows are not migrated.

- Added External Static Asset Intake for user-authored `.blend`, `.fbx`, and `.glb` static
  assets. It inspects untrusted sources with Blender auto-execution disabled, copies exact source
  and image dependencies, records meter conversion and stable semantic/material mappings, and
  requires a single-use exact plan-hash approval before publishing a script-free normalized
  authoring derivative.
- Added alternate V0.7 source provenance for validated external manifests without fabricating a
  SceneSpec. Multi-material sources become traceable single-material semantic submeshes, master
  Blender graphs remain in the normalized blend, and V0.7 bakes portable raw PBR outputs before
  immutable package and clean-import validation. V0.9 audit and Destination Handoff retain the
  external source hierarchy and exact hashes without claiming destination shader parity.

- Added backward-compatible `spatial_v1` ModelingPlan assembly frames, stable attached-part
  relationships, exact build provenance, Blender root-frame evaluated-bounds inspection, and
  fail-closed structural validation. New workflows prevent single-view screen offsets from
  silently becoming hidden-axis placement; legacy unbound plans remain readable but unverified.
- Added center-plane, coaxial, containment, contact with transverse overlap, evidenced
  side-specific, and bilateral-pair checks plus isolated host and Blender 5 regression fixtures,
  including detection of a visually plausible but laterally side-mounted centerline part.
- Added hash-bound V0.6 camera/geometry/assembly companion diagnostics without changing the
  canonical direct score or exact seven-pass run. Bounded camera probes use an exact
  primary-object request mask or explicit primary/supporting semantic-mask union when available,
  otherwise preserve bbox-only fallback; no silhouette mask is fabricated from bounding boxes.
  Companion evidence is written to immutable `attempts/attempt-NNN` directories, an explicit
  retry preserves earlier failure evidence, and only one fully revalidated terminal bundle is
  published at the diagnostic root.
- Added a strict semantic reference-mask registry with `qa-semantic-masks-register` / status CLI
  and matching allowlisted MCP tools. Exact candidate bytes are promoted only after current
  SceneSpec/reference, observed semantic, binary-image, path, and SHA-256 validation; prior
  manifests enter dedicated history and recoverable immutable receipts record promotion. Status
  distinguishes `current`, `legacy_current`, `absent`, `stale`, and `invalid`, while diagnostics
  bind run-owned manifest/mask snapshots so later valid promotion does not stale historical runs.
- Added explicit semantic-mask IoU, centroid, area, boundary, contour-distance, and undirected PCA
  metrics plus signed 3D `axis_alignment`, `axis_clearance`, and required-check evidence. PCA does
  not claim 180-degree facing, and the five-view assembly sanity path remains structurally
  `unscorable` for reference similarity.
- Added public `qa-diagnose` plus `qa-assembly-sanity-plan` / `qa-assembly-sanity-run`
  CLI surfaces and allowlisted `run_visual_diagnostics`, `plan_assembly_multiview_sanity`, and
  `run_assembly_multiview_sanity` MCP tools. Standalone assembly rendering requires the exact
  caller-reviewed plan SHA-256. Camera-versus-geometry attribution remains advisory, new V0.8
  workflows may add the companion, and legacy workflows remain readable; no diagnostic bypasses
  guarded revision, convergence, InteriorScope, V0.7 optimization, or handoff approvals.
- Added a V0.4 geometry-review stage to newly planned proxy, detail, background, and eligible
  `spatial_v1` revision workflows. A host renders temporary asset-local front/right/top/rear/
  oblique cameras with beauty, silhouette, object-ID, and wireframe passes, targeting the union
  of every primary/supporting and root/attached semantic. A following agent must actually inspect
  all five beauty/wireframe pairs and write `visual_review.json` bound to the exact plan, render
  manifest, and structural-report hashes. Per-view occlusion is advisory; cross-view coherence,
  assembly, topology, all-view disappearance, and manual V0.4 parametric/redesign recommendations
  never fabricate side/rear likeness or authorize a revision. PDFs include the run images while
  machine JSON remains authoritative; legacy plans are not migrated.
- Added five-view baseline/result veto and rollback to manual one-shot guarded revision for
  authored `spatial_v1` assets. Because bounded-convergence iteration receipts and audits do not
  yet bind equivalent evidence, authored spatial plans now fail closed before planning and again
  before execution; legacy/non-spatial fixed-camera sessions remain compatible. Canonical V0.6
  remains one fixed-reference, exact seven-pass QA run.
- Preloaded optional OpenCV/NumPy vision modules before MCP stdio worker startup to avoid a
  Windows native-import stall on the first QA mask refinement, while preserving the Pillow
  fallback when vision extras are absent. V0.6 gates now regenerate both QA and combined PDFs
  after companion diagnostics so their exact source manifests cannot remain stale.
- Hardened new V0.5 surface-detail authoring with backward-compatible `spatial_v1`
  object/material/current-UV bindings, bounded UV-rectangle or hash-bound mask placement,
  image-backed channel declarations, edge-safe non-repeating sampling, and separate hybrid
  procedural coordinates. Existing unbound workspaces remain immutable and readable but are not
  silently upgraded.
- Added deterministic Material Fidelity QA and PDF projection for channel hashes, suspicious
  black-line/full-field variation, normal-map deviation, and spatial leakage risks. Blender
  material inspection now verifies the applied UVMap/identity-Mapping/Image-Texture topology,
  image identity and extension, parent assignment, exclusive material use, and current ordered
  polygon-corner UV fingerprint. The report remains advisory for semantic face placement and
  never replaces swatch or direct-reference review.
- Changed clean stylized procedural defaults to neutral, conservative PBR maps and restricted
  semantic marks to their declared image-backed channels and bounded placement. Generic panel,
  band, groove, and scratch patterns no longer receive implicit whole-material authority.
- Added backward-compatible ModelingPlan surface-detail routing so shallow windows, seams,
  labels, rivets, painted panels, and repeated marks remain outside SceneSpec geometry unless
  silhouette, structure, gameplay, or physical transparency requires a mesh. Added exact V0.5
  UVMap/PBR TextureManifest bindings, build provenance, V0.6 coverage reporting, PDF summaries,
  V0.8 completion checks, CLI/MCP validation, schemas, tests, and Korean guidance without changing
  SceneSpec `0.2.0`, material `0.5.0`, QA `0.6.0`, or orchestration `0.8.0` contract versions.
- Added optional standard-only V0.6 bounded visual-convergence sessions with exact plan-hash approval, current direct-QA/camera/source binding, default three and hard maximum five iterations, direct-score and silhouette-IoU targets, constraint non-regression, immutable per-iteration receipts, rollback, and terminal JSON/PDF evidence.
- Added CLI/MCP plan, approve, run, status, and cancel surfaces plus V0.9 read-only active/history audit coverage. At that milestone manual candidate-by-candidate guarded revision remained the default; the later `candidate_review` entry above changes only newly planned standard `revise_asset` workflows. `background_exterior` still performs exactly one canonical QA with no post-QA auto revision, and convergence never replaces InteriorScope, V0.7 optimization, or Destination Handoff approvals.
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
- Added backward-compatible V0.7 `revise_asset` review guidance alongside `approve`, `revise_profile`, and `cancel`. New `needs_revision` reviews recommend a separate immutable standard asset-revision workflow, while legacy three-choice reviews remain readable and no optimization or revision approval is synthesized.
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
