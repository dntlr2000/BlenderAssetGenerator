# Cloud source checkpoint — 2026-10-08

This review checkpoint recovers the maintained BAG84 source and the subsequent
bounded-read repair. It is not a production asset delivery or a merge-readiness claim.

## Source boundary

- Parent baseline: `634de794d7694457b5e6a5bfd4a24ea75f1bc4b6`.
- The complete BAG84 source contained 1,771 files: 1,450 byte-identical to the
  baseline, 95 modified and 226 added. No baseline file was removed.
- A separate repair replaces oversized authored-split reads with 1 MiB streaming
  chunks, exact digest checks and file-identity/race checks, and adds regression tests.
- Repository projections are regenerated from the staged Git index. Historical
  verification receipts and their recorded results remain unchanged; their old
  source hashes do not certify this checkpoint.

## Excluded operational material

Asset-specific generation 85–87 study runners, frozen approvals and receipts,
recovery workspaces, dependency wheels, temporary logs, rendered assets, and large
working scenes are not copied into maintained source. They require separate
review and generalization before becoming reusable tools. Existing public fixtures,
reference images and immutable verification evidence remain in the repository.

The added ignore rules cover root-local environment files (with `.env.example`
preserved), alternate virtual environments, caches, coverage outputs, future remote
attachments and named Codex harness temporary roots. Existing workspace, output,
build and production ignore rules remain. No blanket PNG, JSON, blend or
verification-directory exclusion is introduced. Ignore rules do not untrack files.

## Fresh local checks

The available cloud Python is not the project's locked development environment.

- Passed: syntax parsing of 825 maintained Python source/test/script files.
- Passed: meta-validation of all 451 checked-in JSON schemas.
- Passed: hierarchical agent-instruction and known incident-literal checks.
- Passed: repository catalog/projection regeneration and check.
- Passed: direct bounded-read smoke for retained content, streaming digest and
  size-limit rejection. This does not replace the pytest race/regression suite.
- Passed: staged whitespace checks and reviewed source/ignore boundary.
- Not run: Ruff and pytest, absent from the available Python environment.
- Blocked: CLI doctor and compatibility entrypoints because `typer` is absent.
  The environment also lacks OpenCV. Dependencies were not installed for this checkpoint.
- Not run: production native checks. Available Blender is 4.3.2, not required 5.0.1.

Python CI is configured on push and can perform locked-dependency hosted checks;
its result must be inspected on the published commit. Native asset rendering,
clean-import/appearance parity, Unity validation and human aesthetic acceptance
remain outside this checkpoint. Historical pass counts are not fresh results.
