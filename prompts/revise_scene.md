# Legacy task: Replace SceneSpec directly

This prompt is retained only for backward compatibility. Prefer `prompts/plan_revision.md`, followed by the guarded `apply-revision` command or `apply_revision_plan` MCP tool.

When this legacy path is explicitly used, read `AGENTS.md`, the current SceneSpec, validation report, and attached current preview. Return a complete replacement SceneSpec JSON.

Rules:

- Preserve every stable ID unless the user explicitly removes or replaces it.
- Change only geometry recipes, transforms, materials, camera values, modifiers, or generators required by the request.
- Preserve unrelated values byte-for-byte when practical.
- Add an entry to `revision_notes` listing changed IDs, before/after values, exclusions, and acceptance criteria.
- Do not change the comparison camera unless requested or demonstrably wrong.
- Keep schema version `0.2.0`, coordinate system, and units.
- Output JSON only and conform to `schemas/scene_spec.schema.json`.
