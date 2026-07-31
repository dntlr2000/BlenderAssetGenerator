# Task: Visual QA and minimal correction plan

Compare the immutable reference image with the current preview rendered from the comparison camera.

Evaluate:

1. global silhouette
2. camera/projection
3. zone boundaries and area ratios
4. landmark positions
5. height ratios
6. negative space and pathways
7. large color/material blocks
8. local detail only after 1–7 pass

Surface-attached details routed to TextureManifest are not geometry revision targets. Report their
contract coverage separately, do not invent SceneSpec objects for them, and do not interpret
coverage as pixel-level similarity. If a visible mark is absent from the map, recommend V0.5
material/texture revision; if it changes silhouette or structure, return it to V0.4 geometry.

Map each issue to stable object IDs. Separate camera errors from geometry errors. Return a minimal change plan with measurable acceptance criteria. Do not propose unrelated beautification.
