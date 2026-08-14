# Material Identity Split Instructions

- This package is a generic additive companion for narrow material-identity scope changes. Never embed incident job IDs, session IDs, material IDs, object IDs, or hashes in reusable source.
- A passed shadow preapproval and approval request are not user approval. Only exact caller-supplied user decision bytes may authorize one exact split transaction.
- SceneSpec, ModelingPlan, and Blend move together under the canonical host lock. Partial state is append-only evidence and must resolve to commit, exact rollback, or `recovery_required`.
- Identity split never creates MaterialPlan, ShaderRecipe, TextureManifest, controller, IQ, package, or destination evidence.
- Preserve historical plans and failed sessions exactly. New evidence is run-owned, immutable, create-once, and exact-adopts identical bytes only.

