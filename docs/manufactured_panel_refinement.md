# Bounded manufactured-panel refinement staging

The additive `scripts/manufactured_panel_refinement_contract.py` and
`scripts/replay_manufactured_panel_refinement.py` pair produces ordinary staged BAG
MeshPayload data. It adds no CLI/MCP execution route or canonical-write authority.
A recipe is not an approved modeling plan, optimizer grant, or accepted package.

## Inputs and deterministic geometry

An explicitly launched supported Blender process reads a `refinement_recipe.json`
version `0.1.0`, an exact `sources/baseline_scene_spec.json`, an immutable reference
identity, and exact hash-bound source mesh payloads. Semantic IDs are supplied by the
recipe rather than inferred from names. The bounded operations are physical angle-based
edge rolls, a closed twelve-facet longitudinal core, closed profile/annular sections,
a sloped contact rail, a closed backstrap, and a limited indexed inlay reseat.

The pure validator rejects omitted/unknown recipe fields, duplicate JSON keys,
nonfinite or coerced numbers, unknown or duplicated identities, invalid indices,
stale hashes, path traversal, linked dependencies, and files larger than 32 MiB.
Counts and dimensions are finite. Arbitrary code, shader graphs, drivers, callbacks,
and destination operations are not recipe options. The source SceneSpec and generated
mesh payloads must also pass the ordinary BAG model, structural, contact, F32 and UV
checks; recipe validity is not a substitute for those independent gates.

The Blender writer refuses an existing `geometry/` or `analysis/` output. It materializes
bounded geometry and triangulated positive-area UV charts into the new staging root,
retains source/recipe hashes, and does not modify the original inputs. Normals and UVs
must then survive the unchanged actual-export/import comparison. Any geometry cleanup
has an explicit maximum weld tolerance and is visible in the exact resulting payload;
this is not permission to repair a failed delivered asset after export.

## Cost and appearance evidence

A large bevel subdivision count can consume more triangles than the visible section
shape requires. Prefer bounded broad sections that reproduce visible curvature and
measure actual triangle cost, rather than blindly increasing tiny chamfer-ring sampling.
Compare raw export against raw export under identical cameras, lights and render settings.
Retain the original, each rejected candidate, clay/material ablations, exact second replay,
clean import, and declared hidden-form inference. Optional glow is represented through
ordinary core emissive factors; support for an engine shader is not inferred from Blender.

Pure tests use small synthetic role-named fixtures and run without Blender or delivered
asset directories. Real source replay and import evidence belongs with each actual candidate,
not in the fixture result. The selected Laser study is an example, not a hardcoded runtime
special case or a general promise of triangle reduction.
