"""AI Director + NPC agents + Resolver — the W3-B deliverable.

This package implements the *AI-native* heart of 《革命街没有尽头》:

* :class:`IntentParser`        — natural language → ``PlayerAction`` JSON
* :class:`MemoryManager`       — pgvector-backed 4-8 memory recall (6-step filter)
* :class:`NpcAgent`            — per-NPC proposal (12-action vocab, narrative contract)
* :class:`DirectorAgent`       — beat selection from the scene contract whitelist
* :class:`ResolverAgent`       — the proposal-merging writer (UP-20260715-002 mandatory_echo)

All five classes:

* consume the JSON Schema under :mod:`server.config.schemas` as the
  single source of truth
* call into the canonical engine in :mod:`server.engine` for any
  state mutation (only the Resolver writes)
* honour the 4-level degradation chain (decision 5)
* honour decision 3 (mandatory_echo allowlist) and decision 6
  (four-questions self-check)
* honour ADR 0007 (case-aware era validation)

Public API
----------
The names below are re-exported so callers can do::

    from server.agents import (
        IntentParser, NpcAgent, DirectorAgent, ResolverAgent,
        MemoryManager,
    )
"""

from __future__ import annotations

from .intent_parser import (
    IntentParser,
    IntentParseError,
    ParsedPlayerAction,
    INTENT_PARSER_VERSION,
)
from .memory_manager import (
    MemoryManager,
    MemoryRecall,
    RecallFilterError,
    MEMORY_MANAGER_VERSION,
    DEFAULT_SIMILARITY_THRESHOLD,
    DEFAULT_TOP_K,
    InMemoryVectorIndex,
    VectorIndex,
)
from .npc_agent import (
    NpcAgent,
    NpcAgentError,
    NPC_AGENT_VERSION,
)
from .director_agent import (
    DirectorAgent,
    DirectorAgentError,
    DIRECTOR_AGENT_VERSION,
)
from .resolver import (
    ResolverAgent,
    ResolverAgentError,
    RESOLVER_AGENT_VERSION,
    MandatoryEchoValidation,
    MandatoryEchoCheck,
    CaseAwareEraCheck,
)
from .model_gateway import (
    ModelGateway,
    ModelCallError,
    ModelResponse,
    StubModelGateway,
)
from .four_questions import (
    FourQuestionsResult,
    check_four_questions,
    check_proposal_four_questions,
    FOUR_QUESTIONS_VERSION,
)


__all__ = [
    # intent parser
    "IntentParser",
    "IntentParseError",
    "ParsedPlayerAction",
    "INTENT_PARSER_VERSION",
    # memory manager
    "MemoryManager",
    "MemoryRecall",
    "RecallFilterError",
    "MEMORY_MANAGER_VERSION",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "DEFAULT_TOP_K",
    "InMemoryVectorIndex",
    "VectorIndex",
    # npc agent
    "NpcAgent",
    "NpcAgentError",
    "NPC_AGENT_VERSION",
    # director agent
    "DirectorAgent",
    "DirectorAgentError",
    "DIRECTOR_AGENT_VERSION",
    # resolver
    "ResolverAgent",
    "ResolverAgentError",
    "RESOLVER_AGENT_VERSION",
    "MandatoryEchoValidation",
    "MandatoryEchoCheck",
    "CaseAwareEraCheck",
    # model gateway
    "ModelGateway",
    "ModelCallError",
    "ModelResponse",
    "StubModelGateway",
    # four-questions
    "FourQuestionsResult",
    "check_four_questions",
    "check_proposal_four_questions",
    "FOUR_QUESTIONS_VERSION",
]
