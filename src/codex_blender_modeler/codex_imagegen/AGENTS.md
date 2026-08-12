# Codex built-in ImageGen companion instructions

Before editing this directory, read:

- [Source of truth](../../../docs/agent/source_of_truth.md)
- [Evidence hashing and history](../../../docs/agent/evidence_hashing_and_history.md)
- [Autonomy and controller safety](../../../docs/agent/autonomy_safety.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

This package is a controller-mediated companion for the current Codex task. Repository
code may publish assignments and validate staged results, but it must never call an
external image service, require credentials, create a Codex task, claim daemon execution,
or write canonical material or destination-project state. Core `0.1.0` staging behavior
and immutable historical evidence retain their original meaning.

The additive material-loop companion may adopt and normalize native outputs, record
current-task non-human semantic/ranking evidence, and bind staging evidence to the AQ v2
material controller. Every multi-candidate decision requires exact semantic and ranking
evidence for every candidate; missing or unresolved evidence must stop at
`review_required`. The exact companion selection receipt must remain recursively bound
through bridge, controller input, and promotion evidence; single-candidate legacy
selection must not claim it. Such evidence always keeps `human_reviewed=false`.

A normalization receipt whose source is a run-owned native `original.png` must bind its
exact native-output adoption receipt. Replay the assignment, original bytes and metadata,
normalization plan, and derivative recursively; reject missing, orphaned, or mismatched
native provenance. When those normalized bytes feed core completion and selection, require
the additive `CodexImageNativeCorePreparationReceipt` to bind adoption/original,
normalization, completion/candidate/generated-image evidence/quality/selection, and exact
normalized-to-core byte identity through bridge, controller input, and promotion evidence.
Do not change the core contracts to carry this closure.

Never reinterpret the existing V0.5 staging-only/compile-`not_run` receipt. `exact_adoption`
requires a separate exact-candidate actual Blender shadow-preflight receipt. That preflight
must not create a ControllerResult or perform canonical/destination writes. Controller-authored
completion is limited to the exact declared material plan, material graph, and completion
outputs. Only the existing authorized host material phase may compile the promoted run,
rebuild, promote canonical MaterialPlan state, roll back, or issue an actual
`MaterialPhaseReceiptV2`.

Keep material promotion, IQ pass, V0.7 approval, package acceptance, and destination parity
distinct. Use `quality_approved` only for an exact passed base quality terminal/freeze.
Never synthesize semantic observations, human review, optimization approval, package
acceptance, or destination-runtime parity from fake, historical-source, raw-export, or
clean-import mechanism evidence.

Only base color, decal RGB, emission, and opacity-source candidates may come directly
from generated pixels. Normal, roughness, metallic, height, displacement, occlusion, and
tangent-space data require explicit local deterministic derivation evidence. Exact signage
text remains project-local deterministic rasterization. Every method added or changed here
needs a brief functional comment or docstring.
