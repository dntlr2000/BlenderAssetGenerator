# ImageGen material-loop as-built record — 2026-08-13

This compact tracked record describes only results confirmed during the 2026-08-13 integration
session. It is an index of execution outcomes and safety boundaries, not a copy of the pytest
stdout, temporary workspaces, exported binaries, or clean-import workspaces.

## Final confirmed results

- The final repository suite reported `1569 passed, 56 skipped, 8 warnings in 257.44s`.
- The official AQ host/focused list reported `616 passed, 24 skipped, 8 warnings in 102.01s`.
  The narrower final material-loop security/schema/service/public bundle reported
  `160 passed, 1 skipped in 19.49s`.
- The deterministic fake four-family Blender 5.0.1 material-loop run reported `4 passed in 101.63s`.
  The cases were wood, signage/decal, emissive, and crystal. The covered path reached real Blender
  compilation, controller promotion, a material-phase receipt, neutral preview, and the integrated
  quality boundary.
- The revised review-boundary and unapproved export-mechanism node reported
  `5 passed, 1 skipped in 345.23s` with Blender 5.0.1. The five passes are one review-only case and
  four fake-family cases. Each fake family exercised independent raw
  GLB and FBX export, Blender clean import, material-preservation checks, and geometry-survival
  checks. The historical actual-source parameter skipped because the actual-source environment was
  intentionally unset.
- The final standalone review-only rerun reported `1 passed in 55.24s`.
- The preserved historical 1254x1254 built-in ImageGen PNG reported `1 passed in 10.96s` at the
  current-task non-human `review_required` boundary, and its delivery-stop assertion reported
  `1 passed in 14.81s`. It did not reach canonical promotion or packaging.
- The synthetic-user-approval test was excluded from the safe AQ Blender final. The remaining safe
  split reported `42 passed, 1 skipped`; AQ 0.1 and AQ 0.2 benchmark manifests separately reported
  `8/8` with 3 Blender cases and `10/10` with 2 Blender cases.

Representative exact final commands are recorded in
[`command-log.txt`](command-log.txt). The delivery-mechanism command was:

```text
$env:CBM_RUN_CODEX_IMAGE_MATERIAL_LOOP_DELIVERY_BLENDER_E2E = "1"
uv run --no-cache pytest -q tests/test_codex_image_material_loop_delivery_blender.py --basetemp E:\mldeliveryfinal20260813
```

`CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_PATH`, `CBM_CODEX_IMAGEGEN_ACTUAL_SOURCE_SHA256`, and
`CBM_CODEX_IMAGEGEN_ACTUAL_PROMPT_SHA256` were unset for that command.

## Authorization and evidence boundaries

- The final exact-adoption design does not reinterpret the immutable MaterialAuthoring `0.2.1`
  `staging_only`/compile-`not_run` receipt. It requires a separate actual Blender shadow-preflight
  receipt for the exact candidate bytes; that preflight creates no ControllerResult and performs no
  canonical or destination write.
- Native-original normalization recursively binds its exact native-output adoption receipt. A
  `CodexImageNativeCorePreparationReceipt` then binds normalized-to-core byte identity and the core
  completion/candidate/quality/selection chain without changing core contracts. A multi-candidate run
  likewise keeps its companion selection receipt bound through bridge, controller-input, and
  promotion evidence; missing or mismatched closure fails closed.
- All four material families used deterministic fake controller completions. This is historical
  fixture evidence, not an actual repository-triggered Codex built-in ImageGen execution.
- No human review or approval occurred. The revised delivery node creates neither an
  `OptimizationApproval` nor policy authorization and does not claim an authorized full loop.
- The production package validator rejects each unapproved run at the V0.7 review boundary. The
  test then probes only the fixed lower-level exporter and clean-import mechanisms under a test
  report namespace. It creates no production package manifest and no delivery terminal.
- The GLB/FBX results establish bounded mechanism behavior for these fixtures only. They do not
  establish production package acceptance, destination-engine parity, general material quality,
  or support for arbitrary assets.
- No Unity, Unreal, or other destination project was written, imported, or validated.
- `autonomous_static_prop_v2_codex_imagegen` remains `disabled_experimental`.

## Portability limit

The temporary basetemps are deliberately not part of this tracked bundle. A clean
checkout can audit this record and the test contract, but must rerun the opt-in Blender node to
produce fresh machine evidence. The final counts and declared limits are mirrored in
`verification/latest_summary.json`; raw workspaces and generated binaries remain ignored evidence.
