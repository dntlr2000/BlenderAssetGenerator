# Material-graph subsystem instructions

Before editing this directory, read:

- [Blender execution](../../../docs/agent/blender_execution.md)
- [Source of truth](../../../docs/agent/source_of_truth.md)
- [Testing and verification](../../../docs/agent/testing_and_verification.md)

Normative focus: CBM-INV-017, CBM-INV-022, CBM-INV-113..121, and CBM-INV-180..190.

Compile only registry-backed nodes, sockets, ranges, links, graph depths, texture counts, and deterministic templates. Reject Script nodes, unknown node groups, cycles, drivers, arbitrary expressions, Python callbacks, and external execution. MaterialGraph companions never replace canonical MaterialPlan/ShaderRecipe 0.5.0.

