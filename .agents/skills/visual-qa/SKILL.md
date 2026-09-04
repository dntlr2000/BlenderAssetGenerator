---
name: visual-qa
description: Compare a Blender preview against references using a fixed camera, identify localized mismatches, and propose minimal SceneSpec changes with acceptance criteria.
---

# Visual QA

1. Freeze the input hashes, SceneSpec hash, comparison-camera fingerprint, resolution, renderer, and run ID.
2. Render beauty, silhouette, object ID, material ID, normal, depth, and wireframe passes from the same camera.
3. Compare direct evidence first: global silhouette, observed semantic boxes, zone boundaries, landmark positions, height ratios, negative space, depth order, and measured constraints.
4. Localize each mismatch to stable object IDs and distinguish camera error from geometry, material, or lighting error.
5. For measured mode, include numeric residuals; for concept mode, report normalized image-space deviations.
6. If an image-model target is explicitly requested, generate it with the immutable reference as content evidence and the current beauty preview as camera/framing evidence. Import the resulting local image through the bounded existing-file provider, recording provider/model/version/seed/prompt/output hashes. It cannot independently authorize changes.
7. Produce non-executable revision candidates and preserve unrelated regions, the camera, and external custom-mesh payloads.
8. Require exact candidate selection plus a hash-bound, single-use user approval before applying any candidate.
9. Rebuild and repeat the same direct QA once. Accept only an improvement with no constraint regression; otherwise restore the archived SceneSpec and rebuild.
10. Persist every pass, report, approval, convergence result, and remaining uncertainty under one QA run.

For an explicitly selected reference-fidelity companion, also evaluate every frozen observation in `VisualFindingSetV01`: expected/actual volume, section, part relation, local dimension or material, exact targets/regions and confidence. Empty required observations are missing evidence, not a pass. A high silhouette/bbox/detail score cannot dismiss wrong volume. Use `evaluate_reference_fidelity` to route the findings and `compare_reference_fidelity` for actual paired conditions. These records are Codex judgments, never human approval. Keep Standard's guarded approval requirements; route structural reauthoring to a new V0.4 candidate review rather than pretending a scalar V0.6 candidate can fix topology. Existing direct-score guarded convergence remains unchanged.

The local CLI does not silently call an external image service. Enable `image_model_qa`, create the advisory image through the available image-generation surface, save the exact prompt beside it, and pass both with `visual-qa --target-image ... --target-prompt-file ...`. Keep that source under an explicitly allowed root when the environment requires path confinement.
