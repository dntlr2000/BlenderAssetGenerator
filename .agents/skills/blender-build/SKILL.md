---
name: blender-build
description: Build or update Blender assets from SceneSpec v0.2 geometry recipes using deterministic, whitelisted MCP tools, then inspect and validate the result.
---

# Blender build

1. Read the SceneSpec and verify schema validity.
2. Call `get_modeling_capabilities` before choosing a new geometry representation.
3. Choose recipes in this order: primitive, profile extrude, revolve, curve, terrain, custom mesh.
4. Keep large custom mesh payloads in `geometry/*.mesh.json` rather than inline.
5. Use `build_scene`; do not directly mutate the `.blend` file as the primary design action.
6. If an approved `analysis/material_plan.json` exists, require every recipe to match a stable SceneSpec material ID. If it is absent, preserve legacy SceneSpec material behavior.
7. Use stable object names derived from IDs and preserve modifier intent.
8. Save `blender/scene.blend`.
9. Run `render_preview`, `inspect_scene`, and `validate_scene`.
10. When material work is in scope, also run material contract validation, Blender material inspection, and swatch rendering.
11. On failure, fix SceneSpec or deterministic build code; do not hand-edit the generated file without updating the source of truth.
12. Validate the job's InteriorScope before build. Absence means `disabled`; reject explicit interior IDs/tags unless the current enabled scope has an exact hash-bound user approval and the objects stay inside its boundary.
13. Do not convert facade backing, door reveals, recesses, or exterior wall thickness into implied rooms, and do not treat an approved interior scope as permission for engine-specific or interactive interior systems.
