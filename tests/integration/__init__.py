"""End-to-end integration tests for the AI-native engine stack.

This package holds the W3 integration tests that drive the
**full pipeline** end-to-end:

* :class:`server.engine` state machine
* :class:`server.agents.resolver.ResolverAgent` (write authority)
* :class:`server.model.ModelGateway` with a :class:`MockProvider`
* :class:`server.safety.SchemaValidator`

through the three case_01 scenes (``photo_lab_2008`` →
``farewell_2011`` → ``reunion_2024``) to verify the
**mandatory-echo** cross-era invariant from decision 3 of
``docs/design/requirements-review-v1.md``.

The tests are designed to be the **highest signal** gate in the
W3 deliverable — every component must work together for these
to pass.
"""

from __future__ import annotations

__all__: list[str] = []
