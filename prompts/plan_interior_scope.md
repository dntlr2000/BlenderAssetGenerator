# Optional interior scope planning prompt

Use this prompt only after the user explicitly asks for an interior. A general request to model a
building, improve its exterior, add window depth, or make the facade believable does not authorize
rooms or other interior geometry.

1. Read the exact user request and enumerate only the requested levels, spaces, furnishing depth,
   and evidence class.
2. Select one policy: `visible_only`, `proxy`, `measured`, or `authored`.
3. Define the narrowest dot-delimited `allowed_semantic_prefixes`; exclusions take priority.
4. Create `architecture/interior_scope.json` with `interior-scope-init` or
   `initialize_interior_scope`. This creates a draft only.
5. Show the complete scope and current SHA-256 to the user. Do not create interior SceneSpec objects
   before a matching approval exists.
6. After the user explicitly approves the scope, show the manual
   `interior-scope-approve` command and wait. Never run that interactive command for
   the user; it is intentionally unavailable through MCP.
7. Mark every interior object with the `.interior` semantic namespace or an explicit `interior`
   tag. Add `level:<id>` and `space:<id>` when the scope constrains those axes.
8. Run `interior-scope-validate`, then the normal build → render → inspect → validate workflow.

Facade backing, window recesses, door reveals, and exterior wall thickness may remain exterior
helpers only when they do not represent rooms and do not carry interior markers. An InteriorScope
authorizes static geometry only; never infer interactive doors, navigation, runtime room systems,
lighting gameplay, or engine-specific shaders.
