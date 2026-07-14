"""Server package — FastAPI entry point + supporting modules.

The submodules below are the W4 deliverable.  Each one is
intentionally focused on a single concern:

* :mod:`db`             — SQLAlchemy 2.0 engine + 11 ORM models
* :mod:`repository`     — persistence boundary (the only writer)
* :mod:`scene_loader`   — YAML → contract normaliser
* :mod:`run_registry`   — in-memory active-run cache
* :mod:`llm_runtime`    — provider selection (mock by default)
* :mod:`action_runner`  — the per-turn choreography
* :mod:`app`            — FastAPI routes (the HTTP surface)

Write-domain isolation
----------------------

All canonical state mutations go through the
:class:`agents.resolver.ResolverAgent`.  The HTTP layer
(:mod:`app`) **never** writes to canonical state directly.
The repository layer (:mod:`repository`) is the
**persistence** boundary — it does not enforce invariants,
it just serialises what the Resolver has already validated.
"""

from __future__ import annotations

__all__ = [
    "db",
    "repository",
    "scene_loader",
    "run_registry",
    "llm_runtime",
    "action_runner",
    "app",
]
