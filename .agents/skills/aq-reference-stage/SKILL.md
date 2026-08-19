---
name: aq-reference-stage
description: Execute only the exact AQ v2 reference-collection boundary and preserve observed versus inferred evidence.
---

# AQ reference stage

1. Accept only an AQ route decision whose current next action is `collect_reference`.
2. Revalidate the immutable primary reference, target subject, content scope, RootAuthorizationV2, profile, and budget.
3. Produce only the existing reference evidence required by the AQ supervisor.
4. Never promote geometry, request routine approval, change scope, or call an external provider.

