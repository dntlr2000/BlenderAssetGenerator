# Codex Blender Modeler v0.9.0 — Repository Instructions

## Mission

Turn references, measured evidence, and user feedback into reproducible Blender static assets while preserving exact machine-readable provenance, approvals, rollback boundaries, and engine-neutral delivery evidence.

## Mandatory collaboration rules

- [CBM-ROOT-METHOD-DOC] Every method added or changed by Codex needs a brief functional comment or docstring.
- [CBM-ROOT-ROLLBACK] Codex owns requested source rollback. Keep harmless logs/intermediates unless they cause a real problem; explain the exact file, reason, impact, and requested permission before deleting or changing them.
- [CBM-ROOT-COMPAT] Review every related code path and public surface when adding or changing a feature.
- [CBM-ROOT-SKILL-OPTIN] Do not use a project skill unless the user explicitly requests it.
- [CBM-ROOT-USER-CHANGES] Preserve user changes. Never discard, overwrite, or reclassify them to make a gate pass.
- [CBM-ROOT-NO-RESET] Never use reset, clean, checkout, restore, or an equivalent destructive command against user work unless the user explicitly requests that exact operation.
- [CBM-ROOT-TEMP-LOCAL] Keep every Codex-created temporary output, pytest basetemp, copied job, and isolated test workspace under the repository root. Never create them on a drive root, in a sibling project, or in a system/user temporary directory.

<!-- RULE_POLICY project_skill=explicit_user_opt_in -->
<!-- RULE_POLICY user_changes=preserve -->
<!-- RULE_POLICY source_rollback=codex_owned -->
<!-- RULE_POLICY project_version=0.9.0 -->
<!-- RULE_POLICY canonical_scenespec=0.2.0 -->

## Absolute safety sentinels

- [CBM-ROOT-IMMUTABLE-INPUT] Never modify workspaces/*/input/ or replace user evidence.
- [CBM-ROOT-MACHINE-JSON] Versioned machine JSON and exact hashes are authoritative. PDF, preview, latest pointers, and prose are derived aids.
- [CBM-ROOT-NO-SYNTH-APPROVAL] Never infer, forge, broaden, or reuse user approval. Generic approval never replaces an exact specialized approval.
- [CBM-ROOT-CONTROLLER-WRITE] Only the authorized host/controller promotion path may write canonical job state. Advisers, subagents, destination prompts, and external controllers write only declared staging outputs.
- [CBM-ROOT-NO-ARBITRARY-CODE] Do not add arbitrary Blender Python, node graph, shell, callback, driver, or external execution authority. Use strict schemas and allowlists.
- [CBM-ROOT-PACKAGE-REVIEW-SEPARATION] A review bundle is not a production package. Package acceptance requires its immutable manifest and passed clean-import evidence.
- [CBM-ROOT-NO-DEST-WRITE] Do not modify a Unity, Unreal, or other destination project. Destination handoff is an engine-neutral contract and prompt boundary unless a separately validated adapter is explicitly authorized.
- [CBM-ROOT-NO-UNVERIFIED] Never claim support, parity, quality improvement, human review, or a passing gate without the exact executed evidence.
- [CBM-ROOT-NO-AUTO-MIGRATION] Loading, audit, orchestration, AQ, packaging, reporting, or controller execution must never auto-migrate legacy evidence.
- [CBM-ROOT-FAIL-CLOSED] Unknown, stale, tampered, escaped, under-authorized, or incomplete evidence fails closed and remains visible.
- [CBM-ROOT-HISTORY] Preserve immutable requests, plans, approvals, attempts, receipts, histories, packages, QA runs, and terminal evidence. Never repair history in place.
- [CBM-ROOT-STATIC-ONLY] V0.7, Destination Handoff, external intake, and current AQ profiles are static-asset boundaries; do not imply rig, animation, gameplay, CAD B-Rep, engine graph, or runtime parity.
- [CBM-ROOT-POLICY-NOT-USER] AQ Approval Envelope policy authorization is a separate, host-issued, exact single-use authority. Never serialize, count, display, or reuse it as user approval, and never treat initial delegation as approval of a future artifact.
- [CBM-ROOT-TECHNICAL-NO-APPROVAL] Dependency, manifest, path/hash, schema/projection, deterministic normalization, controller packaging, retry, and rollback failures must not create a user approval request.
- [CBM-ROOT-ENVELOPE-OPTIONAL] Approval Envelope 0.3 is an optional exact RootAuthorizationV2 companion. Missing historical evidence is not `interactive`, is never auto-created, and grants no retroactive authority.
- [CBM-ROOT-ONE-PROMPT-SESSION] One-Prompt execution is bounded to the current Codex task. Repository code must not spawn a Codex task or claim execution after app exit; resume must reuse and revalidate the same state, budget, and assignment.

## Version and compatibility baseline

Project remains 0.9.0. Canonical geometry remains SceneSpec 0.2.0. SceneSpec V03 0.3.0 is derived-only. Approval Envelope 0.3.0 and One-Prompt 0.1.0 are additive disabled-experimental companions over unchanged AQ v2 0.2.0. Existing Reference/Constraint 0.4.0, Material/Shader/Texture 0.5.0, Visual QA 0.6.0, Portable Asset 0.7.0, Workflow 0.8.0, Stabilization/Handoff 0.9.0, standard, background_exterior, external intake, AQ 0.1, and autonomous_static_prop_v1 evidence remain readable and retain their original meaning.

New companion versions and profiles are additive and selected by exact schema_version plus profile/session binding. Unknown combinations are never guessed. Existing blocked, failed, cancelled, or completed evidence is never rewritten or retroactively reclassified.

## Normative rule catalog

The exact legacy invariant set is preserved as CBM-INV-001 through CBM-INV-192 in [invariant_catalog.md](docs/agent/invariant_catalog.md). Those RULE_IDs are normative and the checker verifies their exact legacy digest. Before changing a subsystem, read its leaf AGENTS.md and every linked topic guide.

Instruction map:

- [Agent instruction map](docs/agent/README.md)
- [Source of truth and versions](docs/agent/source_of_truth.md)
- [Approvals and authorization](docs/agent/approvals_and_authorization.md)
- [Evidence hashing and history](docs/agent/evidence_hashing_and_history.md)
- [Blender execution](docs/agent/blender_execution.md)
- [Packaging and handoff](docs/agent/packaging_and_handoff.md)
- [Autonomy and controller safety](docs/agent/autonomy_safety.md)
- [Testing and verification](docs/agent/testing_and_verification.md)
- [Detailed workflow reference](docs/agent/workflow_reference.md)

If a topic guide summarizes a rule differently, invariant_catalog.md wins. Root sentinels always apply.

## Default short-reference behavior

For a new short image request: create a unique lowercase job ID; default to concept unless measured evidence exists; analyze the reference and camera before planning; author semantic decomposition and a proxy SceneSpec; build, render, inspect, and validate; then stop at the applicable approval boundary. Hidden geometry is inferred, never recovered truth. Interior geometry remains disabled without an explicit current InteriorScope hash approval.

For revisions, retain the job ID and use the guarded standard path. A new primary reference or changed immutable content scope requires a new job.

## Core execution boundaries

- Use meters, right-handed coordinates, +Z up, and -Y camera-forward.
- Stable semantic and material IDs survive revisions and derived delivery.
- Validate silhouette/proportion and assembly before detail; route shallow non-structural marks to bounded surface-detail material evidence.
- QA validates the actual Blender camera and exactly seven canonical passes. Companion and multi-view diagnostics never replace the V0.6 direct score or grant revision authority.
- standard remains default. background_exterior is explicit opt-in and never bypasses specialized approvals. AQ is an opt-in overlay, not a third modeling pipeline.
- Optimization is run-owned and never mutates canonical authoring inputs. Every accepted format needs independent package and clean-import evidence.
- V0.9 audit is read-only. Queue/controller work is bounded, single-writer, receipt-backed, and stops at every approval/failure boundary.
- Exact plan/apply migration is separate, hash-bound, single-use, and never implicit.

## Required validation baseline

Use the smallest proportional checks first, then the full relevant gate:

- uv sync --frozen --extra dev --extra vision
- uv run ruff check .
- uv run pytest
- uv run cbm doctor
- uv run cbm blender-compat
- python scripts/check_agent_instructions.py
- python scripts/generate_repository_summary.py --check
- relevant V0.7–V0.9 or AQ gate scripts
- git diff --check

Blender claims require the supported Blender 5.0.1 executable and exact recorded command/evidence. Missing self-hosted Blender CI is not a pass.

## File ownership

Edit source under src/codex_blender_modeler/, schemas under schemas/, deterministic scripts under scripts/, and tests under tests/. Never hand-edit generated/user workspace evidence to make tests pass. README.md, REPOSITORY_TREE.txt, FILE_MANIFEST.sha256, registries, schemas, CLI, MCP, and .codex allowlists must remain synchronized through their authoritative generators and parity checks.
