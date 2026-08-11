# AQ 0.2 portable evidence — 2026-08-11

## Recorded execution

- Full pytest: `1350 passed, 39 skipped, 8 warnings`.
- AQ v2 focused gate: `397 passed, 17 skipped, 8 warnings`.
- Blender gate: `30 passed, 6 warnings` on Blender 5.0.1.
- Deterministic AQ v2 benchmark: `10/10 passed`; Blender fixture subset `2/2 passed`.
- Human review status: `not_reviewed`.
- Profile status: `autonomous_static_prop_v2=disabled_experimental`.

Raw pytest stdout and basetemp trees are not included. The recorded counts remain historical metadata;
a new installation must rerun the gates before making a fresh verification claim.

## Preserved evidence

- `autonomous_quality_benchmark_v02.json`
  - SHA-256: `7bf51bfb1a16a94537e2cb7db44602df1a82332779e0a91c1581fd53f715b271`
- `autonomous_quality_benchmark.json`
  - preserved AQ 0.1 compatibility benchmark snapshot
- `artifacts/curved_loft/blender/receipt.json`
  - SHA-256: `37bd89b590017f3cec9b152ea7b1f5221eb82d14b945ca56b43fc61422575f64`
- `artifacts/simple_hard_surface_box/blender/receipt.json`
  - SHA-256: `df39ce0a124b46d564d044f1aa3d6c83a3f77d04d9601d03a77786f4015dfb5b`

This compact bundle proves the recorded benchmark artifacts and their Blender fixture receipts. It
does not embed all 397 host-test basetemps or all 30 Blender-test workspaces.
