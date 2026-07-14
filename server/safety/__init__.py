"""server.safety — the 校验链 (verification chain) and 守门 (gatekeeping).

This package is the **last line of defense** between any
AI-produced payload and the canonical world state.  Every node
in the chain — ``int_parser``, ``npc``, ``director``, ``resolver``
— must pass through this package before its output is allowed
to touch the database.

Public API
----------

* :mod:`.output_verifier`  — strict JSON-Schema validation
* :mod:`.clamping`         — physical-boundary numeric clamps
* :mod:`.content_guards`   — secret-leak + mandatory-echo gate
* :mod:`.invariant_checker`— state-machine invariant checks (10)
* :mod:`.idempotency`      — replay-key / clientActionId audit
* :mod:`.cost_monitor`     — 决策 5 硬红线 + P0 报警

Why a separate package
----------------------

The safety package sits **below** the engine in the dependency
graph — it must not import from ``server.engine`` (which itself
imports from this package at the Resolver boundary).  This is
why every module here is self-contained: the only third-party
dependency is ``jsonschema``.

Design contract
---------------

* All public functions are **pure**: they accept primitive
  inputs and return structured reports.  Nothing here mutates
  global state.
* Every module exposes a ``*_Report`` dataclass with a
  ``to_dict()`` and ``to_human_readable()`` method so the
  same code can drive a CI log, a CLI tool, or the
  content-studio UI.
* Exit codes follow :class:`idempotency.ExitCode` /
  :class:`cost_monitor.ExitCode`: ``0`` pass, ``1`` block,
  ``2`` I/O error.
"""

from __future__ import annotations

from .clamping import (
    ClampEvent,
    ClampingAudit,
    ClampRequest,
    FIELD_SPECS,
    FieldKind,
    clamp_field,
    clamp_many,
    clamp_to_range,
    is_legal_echo_intensity,
    is_legal_event_sequence,
    is_legal_relationship,
    is_legal_relationship_delta,
    is_legal_unit,
)
from .content_guards import (
    BeliefVisibility,
    ContentGuardInput,
    ContentGuardReport,
    check_forbidden_reveals,
    check_mandatory_echoes,
    check_proposal_visibility,
    check_ungrounded_memory,
    run_content_guards,
)
from .cost_monitor import (
    CostReport,
    CostViolation,
    ExitCode as CostExitCode,
    HARD_RED_LINES,
    LiveCounter,
    ModelCall,
    P0_ESCALATION_THRESHOLD,
    RedLine,
    RunSummary,
    check_p0_escalation,
    check_red_lines,
    evaluate,
    evaluate_from_file,
    summarise_run,
)
from .idempotency import (
    ExitCode as IdempotencyExitCode,
    IdempotencyReport,
    IdempotencyViolation,
    audit_file,
    audit_idempotency_keys,
    load_log,
    scan_client_action_replays,
)
from .invariant_checker import (
    InvariantCheckInput,
    InvariantReport,
    InvariantViolation,
    check_all_invariants,
    check_artifact_location_uniqueness,
    check_atomic_write,
    check_event_log_idempotency,
    check_knowledge_grounded_in_evidence,
    check_no_action_by_inactive_character,
    check_no_entitlement_fabrication,
    check_no_forbidden_secret_leak,
    check_objective_facts_immutability,
    check_replay_determinism,
    check_relationship_values_in_range,
)
from .output_verifier import (
    ErrorCategory,
    FieldError,
    OutputVerifier,
    SCHEMA_REGISTRY,
    VerificationReport,
    verify_output,
)

__version__ = "1.0.0"

#: Convenience alias so callers can write ``safety.ExitCode``
#: without caring which sub-module owns the enum.  ``cost_monitor``
#: and ``idempotency`` share the same values, so the alias points
#: at the cost_monitor's enum (imported first).
ExitCode = CostExitCode

__all__ = [
    # clamping
    "FieldKind",
    "FIELD_SPECS",
    "ClampEvent",
    "ClampingAudit",
    "ClampRequest",
    "clamp_field",
    "clamp_many",
    "clamp_to_range",
    "is_legal_unit",
    "is_legal_relationship",
    "is_legal_relationship_delta",
    "is_legal_event_sequence",
    "is_legal_echo_intensity",
    # content_guards
    "BeliefVisibility",
    "ContentGuardInput",
    "ContentGuardReport",
    "check_forbidden_reveals",
    "check_mandatory_echoes",
    "check_proposal_visibility",
    "check_ungrounded_memory",
    "run_content_guards",
    # cost_monitor
    "RedLine",
    "HARD_RED_LINES",
    "P0_ESCALATION_THRESHOLD",
    "CostExitCode",
    "ModelCall",
    "RunSummary",
    "CostViolation",
    "CostReport",
    "LiveCounter",
    "summarise_run",
    "check_red_lines",
    "check_p0_escalation",
    "evaluate",
    "evaluate_from_file",
    # idempotency
    "IdempotencyExitCode",
    "IdempotencyReport",
    "IdempotencyViolation",
    "audit_idempotency_keys",
    "scan_client_action_replays",
    "load_log",
    "audit_file",
    # invariant_checker
    "InvariantCheckInput",
    "InvariantReport",
    "InvariantViolation",
    "check_all_invariants",
    "check_objective_facts_immutability",
    "check_knowledge_grounded_in_evidence",
    "check_artifact_location_uniqueness",
    "check_no_action_by_inactive_character",
    "check_relationship_values_in_range",
    "check_no_forbidden_secret_leak",
    "check_no_entitlement_fabrication",
    "check_replay_determinism",
    "check_atomic_write",
    "check_event_log_idempotency",
    # output_verifier
    "ErrorCategory",
    "FieldError",
    "OutputVerifier",
    "SCHEMA_REGISTRY",
    "VerificationReport",
    "verify_output",
    # aliases
    "ExitCode",
    "__version__",
]
