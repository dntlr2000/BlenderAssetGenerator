# Exact texture-profile cost evidence

`packaging.texture_cost_audit.inspect_glb_texture_cost` is an opt-in read-only helper.
It binds to exact expected GLB bytes and reports each embedded PNG's encoded length,
SHA-256 and CRC-checked IHDR dimensions. It also reports explicit RGBA8 storage estimates,
including the exact rectangular mip chain. It does not decode pixels or establish normal
channel correctness, visible detail, runtime allocation or engine support.

The assumed resource is one uncompressed RGBA8 image per serialized image index. Actual
GPU compression and duplicate sharing are engine/importer decisions. The exact image-byte
and distinct-content totals are reported separately; they must not be called measured GPU
memory. PNG source depth is retained, so a 16-bit source is not accidentally described as
an observed RGBA8 allocation. Unsupported URI/JPEG/extension-specific containers fail closed.

A 1024-to-2048 square profile has four times the base texels. Its compressed PNG or GLB size
need not scale by four. Compare final imported assets with identical cameras, lights and
shader semantics. Keep physical form, atlas allocation and resolution ablations separate;
an improvement from greater source texture resolution is not evidence of improved geometry.

For a declared quality/economical pair, retain separate exact source/profile hashes,
conversion output, image costs, actual imported views, channel audit and clean-import proof.
The default and all existing acceptance limits remain unchanged. A cost receipt grants no
package, optimization, visual-quality or destination authority.
