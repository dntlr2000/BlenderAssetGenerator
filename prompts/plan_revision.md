# Task: Create a guarded RevisionPlan

Read `AGENTS.md`, the current `analysis/scene_spec.json`, the user request, the attached reference images, and the current preview when present.
Return a RevisionPlan JSON only, conforming to `schemas/revision_plan.schema.json`.

Rules:

- Use the supplied exact `job_id` and `base_spec_sha256`.
- Do not return a replacement SceneSpec.
- Express every intended change as a small operation against a semantic object/material ID, camera, or scene field.
- Prefer `multiply` for relative requests such as “20% lower”, `add` for numeric deltas, and `set` for explicit values.
- Use path arrays, for example `["geometry", "dimensions", 2]` or `["transform", "location", 2]`.
- Do not target unrelated IDs or paths.
- Do not modify the comparison camera unless the user explicitly asks for a camera change.
- Include objective acceptance criteria that can be checked after rebuild and render.
- Record uncertainty in `assumptions`; do not hide it.
