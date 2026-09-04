---
name: aq-quality-stage
description: Run exact Integrated Quality 0.2 evaluation and publish either accepted source freeze or a safe review terminal.
---

# AQ quality stage

1. Require current candidate-owned build, reference, structural, material, and production evidence.
2. Preserve the exact V0.6 direct score while evaluating the separate IQ axes.
3. Treat unavailable required evidence as unscorable, never zero or pass.
4. Accept quality only through the existing exact host policy boundary and source freeze.
5. Route non-pass, plateau, cycle, or bounded termination to a non-production review bundle when safe.

For an explicitly bound fidelity loop, evaluation is not terminal publication. Compare the reference to actual beauty/normal/depth and the other four passes, and assess every frozen required observation in `VisualFindingSetV01`. Use exact reference, source, render, camera and pass hashes, semantic targets, image regions, expected/actual descriptions and confidence. Missing evidence is unscorable; N/A must have been declared in the hypothesis before evaluation. Extra views prove candidate consistency, not unseen reference truth.

Use `render_aq_reference_fidelity` for new-loop seven-pass evidence; it reserves render costs before Blender and captures actual comparison conditions and immutable build sources. Then call `submit_aq_quality_attempt` before final IQ publication. Consume the returned host route through `begin_aq_quality_reentry` and the same One-Prompt/controller session. Large-volume, section and part-relation errors route to V0.4; bounded scalar errors to parametric correction; surface/color/roughness to V0.5. Do not rerun unchanged candidates, invent human disposition, or directly write canonical state.

If that attempt is `evidence_required`, inspect the same exact rendered evidence and use `supplement_aq_quality_evidence` at most once to fill only the missing observations. The host preserves the first attempt, known defects, camera, source, IQ and budget; supplementation is not a new visual improvement. If evidence still cannot be assessed, report the missing evidence or calibration requirement for consultation. Never erase an observed defect by replacing its judgment, reset the job budget, or claim extra diagnostic views as recovered hidden reference geometry.

Use `compare_reference_fidelity` for exact paired renders. If camera or actual lighting changes, rerender both sources under the new conditions. Report legacy direct score separately: resolving structure can lower that score. Count defect resolution and no regression, not attempts, detail counts or needs_revision entries, as visual improvement. The maximum three structural and two shared local rounds are upper bounds; the frozen root execution budget can be tighter. Repeated stagnation requires a strategy change or the host's safe review terminal.
