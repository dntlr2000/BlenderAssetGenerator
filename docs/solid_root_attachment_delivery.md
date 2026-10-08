# Closed-solid local root-ball attachment companion

This separately selected 0.1.0 companion supports complete connected closed embedded
solid boundaries, including a torus or a thick shell with open windows. It does not
reinterpret the existing heightfield full-patch/root-region companion or its
axis-aligned reference occupancy measurements. Existing unselected jobs retain
legacy behavior and serialization.

The explicit host API is `register_solid_root_attachment_intent(job_id,
intent_path=..., intent_sha256=...)` in `packaging.attachment`. It is an input-domain
selection on a fresh unbuilt job, not approval, visual acceptance or package authority.
The original `register_surface_attachment_intent` accepts only its original domain.
The two domains use one exclusive immutable selection latch and cannot be silently
changed, removed, mixed, migrated or registered after building.

The strict `SolidRootAttachmentIntentV01` binds the original reference, canonical
ModelingPlan and SceneSpec, every geometry payload, and an explicit camera-hypothesis
artifact whose camera equals the selected SceneSpec camera. Hidden shape, scale and
camera estimates remain hypotheses. Required semantics must cover the entire asset;
every semantic is one complete triangulated, single-material-slot, identity-transform,
static_prop_closed mesh. Modifiers, generators and parent transforms are outside this
initial domain. Nested or disconnected boundary components are rejected rather than
interpreted as implicit cavities or unions.

Every declared connection binds its intended semantic joint description, an axis-aligned
world-space root region, a fixed center and radius. The entire closed ball, not just its
center, must fit in that region. The radius must meet the intent's fixed positive minimum
and its authored scale rationale. A failing connection requires a new explicitly bound
authoring revision; neither radius nor region is adapted automatically. A connected
required graph excludes omitted floating components, but does not establish visual
finish or attachment strength.

For each solid, topology, outward orientation, exact positive volume and complete exact
triangle embedding are required. Exact rational ray parity proves the center is inside
material, rejecting cavity points. Edge/vertex/coplanar ray ambiguity retries a bounded
deterministic direction list; exhaustion is unverified. Exact point-to-triangle squared
distance, with conservative exact AABB pruning, proves every boundary lies at least the
radius away. Therefore the same positive-volume ball lies in both solids. Receipts claim
only this local overlap and a conservative distance lower bound, never an attained
minimum, seam-wide embed, mechanical strength, visual likeness or human acceptance.

One context covers the whole evaluation: 25,000 total triangles, 4,096 per connected
component, the existing exact embedding pair cap and a one-million aggregate embedding
work cap, plus one million aggregate root predicate visits. The new domain uses a
deterministic AABB hierarchy whose construction entries, node-pair visits and leaf
pair tests are all charged. `embedding_candidate_pairs` still enumerates the complete
unordered closed-box pair set, equal to the legacy sweep. Inside complete embedding,
a separate fixed X+Y+Z projection can reject a pair only when its closed enclosing
intervals are strictly disjoint. Every signed-coordinate addition rounds both bounds
outward with `nextafter`; endpoint touches and uncertain overlaps continue to the
unchanged exact contact predicate. This is a conservative filter, not a sampled
intersection decision or a new tolerance.

The same one-million embedding counter charges one construction unit per triangle
per fixed direction (three vertex projections, at most three additions each), and
one unit per visited direction comparison for a candidate pair. There is one fixed
internal direction `(1, 1, 1)`, symmetric under coordinate-axis permutations, no
caller-selected direction or count, and no budget
reset between solids. Only surviving pairs consume the unchanged exact-predicate
pair cap. This filter may prune differently under rotation and does not promise that
every valid solid fits the caps; exhaustion remains unverified. Exact contact
predicates, coordinate/domain bounds and all caps are unchanged. Legacy
heightfield scan accounting remains unchanged. Budget types and ranges are
strict. No caller-supplied prepared solid or sampled JSON can attest native extraction;
the host prepares all solids itself from complete exact source/actual correspondence.

The existing fixed Blender5.0.1 reader runs freshly for native, converted and factory
clean-import GLB stages. Every oriented triangle and material identity must match source
binary32 coordinates exactly, with no nearest-neighbor match, welding or tolerance drift.
The strict intent/camera snapshot bytes are retained along with each actual extraction
and report; the package closure rehashes all copies and inspected dependencies before
immutable publication. The ordinary optimization authority, material conversion and
independent clean-import requirements remain separate and unchanged.

Reference-side and neutral front/rear/end/top diagnostics remain necessary. Choose the
component volumes/cross-sections and an explicit camera hypothesis before detail. A proof
domain must follow the intended geometry; do not flatten a model to accommodate a
heightfield validator, or use a local-ball result as a replacement image-quality score.
