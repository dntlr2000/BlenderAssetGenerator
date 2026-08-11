# Codex built-in ImageGen companion instructions

Before editing this directory, read:

- [Source of truth](../../../docs/agent/source_of_truth.md)
- [Evidence hashing and history](../../../docs/agent/evidence_hashing_and_history.md)
- [Autonomy and controller safety](../../../docs/agent/autonomy_safety.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

This package is a controller-mediated companion for the current Codex task. Repository
code may publish assignments and validate staged results, but it must never call an
external image service, require credentials, create a Codex task, claim daemon execution,
or write canonical material or destination-project state.

Only base color, decal RGB, emission, and opacity-source candidates may come directly
from generated pixels. Normal, roughness, metallic, height, displacement, occlusion, and
tangent-space data require explicit local deterministic derivation evidence. Exact signage
text remains project-local deterministic rasterization. Every method added or changed here
needs a brief functional comment or docstring.
