# V0.5 material planning prompt

Use the approved SceneSpec, reference diagnostics, and preview. Preserve geometry, camera, transforms, semantic IDs, and existing material assignments.

For every material ID, produce a MaterialPlan v0.5 entry with:

- observed or inferred evidence and confidence;
- shader family and portable Principled surface behavior;
- UV, object, generated, or triplanar mapping with real-world scale;
- none, procedural, image, or hybrid texture strategy;
- Blender EEVEE/Cycles and GLTF/Unity export profiles;
- whether baking is required and why.

Do not generate textures, edit SceneSpec, or build arbitrary Blender nodes in this step.

