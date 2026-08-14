# Testing, CI, and verification

Run focused tests first, then proportional full gates. New or changed methods require a functional docstring/comment. Review related CLI, MCP, schemas, configuration, reports, standard/background/AQ paths, and legacy fixtures.

Python CI must run without Blender or bpy. Blender smoke is a separate workflow_dispatch job on an explicitly labeled self-hosted Windows Blender 5 runner. A missing runner is not a pass. Record baseline failures separately from new regressions.

Registry/document checks treat builder, autonomy profile, delivery, CLI, MCP server tools, project-enabled tools, controller phase profiles, tested-platform evidence, REPOSITORY_TREE, and FILE_MANIFEST as distinct projections. The MCP server registry is not the project allowlist; a phase profile is narrower still. Intentional exclusions need a stable reason.

Repository tree enumeration uses Git-index paths. Manifest SHA-256 values cover canonical Git blob payload bytes; text blobs are LF-normalized by Git attributes before hashing. FILE_MANIFEST excludes itself. The generator check mode compares expected bytes and reports drift without writing.

Before an authorized regeneration, stage the intended source path set so the Git index represents the future commit boundary, run the generator in write mode, then stage the three projections. CI check mode uses the already committed index and never stages or writes anything.

Never report an unexecuted command as passed. Contract-only, Blender-verified, engine-tested, experimental, not-run, and unavailable are distinct states.

Codex-owned temporary outputs, pytest basetemps, copied jobs, and isolated test workspaces must use a unique repository-local path. They are never authoritative evidence and must not be created on a drive root, in a sibling project, or in a system/user temporary directory. Remove only exact Codex-owned temporary paths when the user requests cleanup; preserve immutable evidence and unrelated user work.

Material Closure tests additionally require exact schema parity, recursive dependency and
case-collision negatives, one-projection request/assignment/completion equality, graph
rebind semantic-diff rejection, preapproval failure with zero approval/controller/canonical
effects, rollback-state consistency, and a bounded incident-literal scan over reusable
source/schema/prompt files. Incident documents and explicit test fixtures may be allowlisted;
the scanner must not ban arbitrary SHA-256 strings.

Material Identity Split tests additionally require paired SceneSpec/ModelingPlan diff allowlists,
semantic-clone and assignment-exclusivity negatives, actual Blender preapproval with canonical bytes
unchanged, specialized approval narrowing, single-use consumption, six guarded-transaction crash
points, exact rollback, at most one technical recovery retry, post-apply stale-authority refresh,
7/7 CLI/MCP parity and zero approval/canonical/controller side effects in the real preapproval node.
Test-only approval is mechanism evidence and cannot certify a production apply.

Primary rules: CBM-INV-014..027, CBM-INV-034, CBM-INV-043, CBM-INV-059..066, CBM-INV-121, CBM-INV-127..145, CBM-INV-161, CBM-INV-165..166, CBM-INV-180..192.
