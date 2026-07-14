"""Test package for the AI-native engine.

Each test file targets a specific module of the engine:

* ``test_state_machine.py`` — 12-action reducer unit tests
* ``test_artifact.py``       — artifact ownership + uniqueness
* ``test_belief.py``         — belief-matrix state transitions
* ``test_resolver.py``       — Resolver write-authority tests
* ``test_replay.py``         — 100% replay consistency
* ``test_degradation.py``    — 4-level degradation chain
"""

from __future__ import annotations
