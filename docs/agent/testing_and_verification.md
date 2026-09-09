# Testing, CI, and verification

Run focused tests first, then proportional full gates. New or changed methods require a functional docstring/comment. Review related CLI, MCP, schemas, configuration, reports, standard/background/AQ paths, and legacy fixtures.

Python CI must run without Blender or bpy. Blender smoke is a separate workflow_dispatch job on an explicitly labeled self-hosted Windows Blender 5 runner. A missing runner is not a pass. Record baseline failures separately from new regressions.

Registry/document checks treat builder, autonomy profile, delivery, CLI, MCP server tools, project-enabled tools, controller phase profiles, tested-platform evidence, REPOSITORY_TREE, and FILE_MANIFEST as distinct projections. The MCP server registry is not the project allowlist; a phase profile is narrower still. Intentional exclusions need a stable reason.

Repository tree enumeration uses Git-index paths. Manifest SHA-256 values cover canonical Git blob payload bytes; text blobs are LF-normalized by Git attributes before hashing. FILE_MANIFEST excludes itself. The generator check mode compares expected bytes and reports drift without writing.

Before an authorized regeneration, stage the intended source path set so the Git index represents the future commit boundary, run the generator in write mode, then stage the three projections. CI check mode uses the already committed index and never stages or writes anything.

Never report an unexecuted command as passed. Contract-only, Blender-verified, engine-tested, experimental, not-run, and unavailable are distinct states.

Codex-owned temporary outputs, pytest basetemps, copied jobs, and isolated test workspaces must use a unique repository-local path. They are never authoritative evidence and must not be created on a drive root, in a sibling project, or in a system/user temporary directory. Remove only exact Codex-owned temporary paths when the user requests cleanup; preserve immutable evidence and unrelated user work.

Repository storage retention is an additive CLI-only operational boundary. Inventory and
planning never delete data. Apply accepts only immediate children of `.b/` or `.t/`, exact
tree hashes, an unchanged protection-source fingerprint, and the externally confirmed plan
file SHA-256. Unknown, recent, active, locked, linked, ACL-inaccessible, tracked, or referenced
trees remain protected. The confirmation digest is a safety input, not serialized user approval.

New repository gates default to `compact_success`: after every technical stage passes, publish
and validate a durable `reports/gate_runs/<run-id>/receipt.json`, then remove only that gate's
unique run root. Failed or interrupted gates keep their complete scratch tree. Retention failure
does not rewrite a passing test result; it reports a separate operational failure and preserves
or quarantines the remaining bytes for explicit recovery.

Legacy inventory candidates containing links or reparse points remain protected. A uniquely
owned successful gate root may contain link fixtures created by security tests; its preflight
hashes each link entry without following it, and compaction removes only the link or junction
entry while leaving every target untouched.

Preserved-evidence scanning skips a link alias only when its resolved target is an ordinary
file or directory independently reachable under the same scanned evidence root. External,
dangling, or linked-ancestor aliases keep the global protection index incomplete.

Legacy `.b`/`.t` trees with nested links remain non-deletable, but inventory counts their
ordinary files without following link targets and records `CONTAINS_LINK_OR_REPARSE_POINT`.
Only an immediate-child link or a genuinely unreadable member makes that inventory path partial.

If compaction stops after quarantine, `storage-gate-retention-resume` accepts only the exact
failed-retention gate receipt and deletes only its expected tokenized quarantine members. It
never captures a source root left behind by a partial move. Every attempt is append-only, and
a completed recovery conservatively binds the original source digest and byte count.

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

Skill Orchestration tests additionally require strict schema parity, exactly two public
entry skills, an acyclic mode-isolated dependency graph, unique routes, real project-enabled
MCP tool names, registry/resource snapshot containment and tamper rejection, receipt-chain
continuity, Standard approval/retry preservation, smart/force-all material impact behavior,
consumed guarded-revision continuation binding, V0.9 audit/archive compatibility, and
disabled-by-default AQ routing. Fixture success does not activate AQ v2 or prove visual quality.

Primary rules: CBM-INV-014..027, CBM-INV-034, CBM-INV-043, CBM-INV-059..066, CBM-INV-121, CBM-INV-127..145, CBM-INV-161, CBM-INV-165..166, CBM-INV-180..192.
