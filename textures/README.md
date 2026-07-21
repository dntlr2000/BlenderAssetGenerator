# Texture provider contract

A provider should write a `texture_manifest.json` and referenced images into a job's `textures/generated/<material_id>/` directory. The manifest should include material ID, generator/version, prompt, seed, physical scale or texel density, channel paths, channel color spaces, and license/provenance metadata.

The default starter does not call an external texture service. It uses Blender procedural/Principled materials so the modeling pipeline works without extra credentials.
