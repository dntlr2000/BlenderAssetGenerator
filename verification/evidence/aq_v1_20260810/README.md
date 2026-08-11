# AQ 0.1 portable evidence — 2026-08-10

## Recorded execution

- Full pytest: `1145 passed, 20 skipped, 8 warnings` (`1165 collected`).
- AQ focused gate: `195 passed, 2 skipped, 8 warnings`.
- Blender gate: `14 passed, 6 warnings` on Blender 5.0.1.
- Deterministic benchmark: `8/8 passed`.
- V0.7/V0.8/V0.9 chained regressions: recorded as passed by the final AQ gate.

Raw pytest stdout was not persisted by pytest and the original basetemp trees are intentionally not
part of the repository. These counts are historical execution metadata, not a substitute for a new
gate run.

## Preserved evidence

- `autonomous_quality_benchmark.json`
  - SHA-256: `0946535b3e148ddc159248ef0bc14aac2c3388fce33715dcdfe9056efa0adb39`
- `aq_full_box/`
  - exact `quality_passed` terminal closure snapshot
  - immutable portable package, clean-import roundtrip, destination handoff, final IQ report, final
    state, and selected candidate evidence
  - terminal SHA-256: `02b9ec22b7083bd6da7ede57b605716eb3b7b4bba362e6af7bfb86fc41cc203c`
- `aq_review_box/`
  - exact `review_required` terminal closure snapshot
  - self-contained non-production review bundle, candidate IQ report, final state, and selected
    candidate evidence
  - terminal SHA-256: `254cd7c87d288a714c05fa98e48993c5fae65f6cae4d01874ffb411c2baf094d`

The snapshot intentionally excludes unrelated test cases and intermediate basetemps. Some terminal
provenance outside the copied direct closure is therefore historical rather than fully replayable.
