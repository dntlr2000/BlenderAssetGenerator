# Blender execution

Blender subprocesses use --python-exit-code 1 and stdin DEVNULL. Probe BLENDER_EEVEE before BLENDER_EEVEE_NEXT. Do not expose arbitrary Python, node, driver, callback, or script authority. Builders and graph compilers dispatch only strict whitelisted recipes.

Build, QA, baking, optimization, and package inspection require a fresh embedded fingerprint matching every current canonical and external dependency. Stable semantic/material identities, unit/axis rules, UV/channel intent, assembly bindings, and deterministic geometry payloads must survive derived steps. Temporary cameras and visibility changes are never saved to the authoring blend.

Actual Blender support claims require Blender 5.0.1 execution evidence. Pure contract tests cannot establish Blender or destination parity.

Primary rules: CBM-INV-002..024, CBM-INV-028..044, CBM-INV-067..071, CBM-INV-091..094, CBM-INV-113..150, CBM-INV-182, CBM-INV-189..190.

