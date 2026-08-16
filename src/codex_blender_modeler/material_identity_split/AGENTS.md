# Material Identity Split Instructions

- This package is a generic additive companion for narrow material-identity scope changes. Never embed incident job IDs, session IDs, material IDs, object IDs, or hashes in reusable source.
- A passed shadow preapproval and approval request are not user approval. A legacy/interactive split accepts only exact caller-supplied specialized user decision bytes. A new bound envelope session may instead accept one exact unused `bounded_material_identity_split` policy authorization through the additive adapter; it is never a `MaterialIdentitySplitRootScopeApproval` or user approval.
- Keep explicit approval consumption and policy-authorization consumption as different contracts, paths, and provenance. Each authority can bind one substantive ApplyIntent only; exact byte replay may exact-adopt but cannot consume the authority again.
- SceneSpec, ModelingPlan, and Blend move together under the canonical host lock. Partial state is append-only evidence and must resolve to commit, exact rollback, or `recovery_required`.
- Identity split never creates MaterialPlan, ShaderRecipe, TextureManifest, controller, IQ, package, or destination evidence.
- Preserve historical plans and failed sessions exactly. New evidence is run-owned, immutable, create-once, and exact-adopts identical bytes only.
