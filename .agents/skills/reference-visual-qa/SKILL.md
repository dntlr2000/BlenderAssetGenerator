---
name: reference-visual-qa
description: Run V0.6 fixed-camera render passes and direct reference comparison, optionally adding a generated advisory target.
---

# Reference visual QA

1. Freeze the SceneSpec hash, input hashes, camera fingerprint, resolution, renderer, and run ID.
2. Render beauty, silhouette, object ID, material ID, normal, depth, and wireframe passes from the comparison camera.
3. Compare direct evidence first: content mask, silhouette, observed semantic boxes, negative space, landmarks, and measured constraints.
4. Keep beauty and generated-image judgments separate from shader-independent geometry metrics.
5. If an image model is explicitly enabled, use the reference for content and the preview only for camera/framing. Import its local result with `ExistingFileQATargetProvider` or `visual-qa --target-image`, and preserve the exact prompt text plus provider, model version, seed, prompt hash, and output hash.
6. Treat the generated target as advisory. It cannot lower direct-reference errors or independently authorize geometry edits.
7. Localize every finding to stable semantic IDs and record uncertainty.
8. Persist the request, render manifest, report, and candidates under one immutable `qa/runs/<run-id>/` record.

Do not imply that `--generated-target` invokes a bundled provider. The repository ships a provider protocol and a path-bounded existing-file adapter; an external image-generation surface must create the image first.
