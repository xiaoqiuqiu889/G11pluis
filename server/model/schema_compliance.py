"""Schema compliance — bridges LLM output to the 8 engine JSON Schemas.

The Model Gateway enforces that LLM output for *structured* tasks
(player_intent_parser, npc_proposer, director_proposer, resolver)
matches the corresponding JSON Schema from W1-E.  Without this
gate, an LLM hallucination can land in the resolver and corrupt
the canonical world state.

What this module does
---------------------
1. Loads all 8 schemas from ``server/config/schemas/*.json`` once
   and caches them.
2. For each task type, knows which schema to enforce (see
   :data:`models.TASK_TO_SCHEMA`).
3. Validates the parsed JSON against the schema and returns a
   list of human-readable error paths.
4. Provides a helper that retries once on validation failure
   (decision 5: "validate → retry 1 → 降级").

Why a custom validator on top of ``jsonschema``
-----------------------------------------------
* The schemas use ``$ref`` to reference other schemas in the same
   directory.  The default ``jsonschema`` validator cannot follow
   relative refs out of the box — we register a
   :class:`jsonschema.RefResolver` against the schema's own
   directory.
* We collect *human-readable* error messages (with JSON paths)
   rather than raw ``ValidationError`` objects, so the audit log
   is easy to scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
from jsonschema import Draft7Validator, RefResolver
from jsonschema import validators as _jsonschema_validators

from .exceptions import SchemaValidationError
from .models import TaskType, TASK_TO_SCHEMA, safe_parse_json


# ---------------------------------------------------------------------------
# multipleOf — Decimal arithmetic to avoid float precision bugs
# ---------------------------------------------------------------------------
#
# JSON Schema's ``multipleOf`` is well known to mis-report on
# floats that have no exact binary representation (e.g. ``0.6``,
# ``0.7``).  The default validator uses Python ``%`` and
# ``/`` on floats, which mis-evaluates ``0.6 % 0.05 = 4.99e-02``
# (fails) when the value IS actually a multiple.
#
# We patch the ``multipleOf`` validator to convert both sides
# to :class:`decimal.Decimal` first.  This is the standard
# workaround; the jsonschema team is migrating to the
# ``referencing`` library but ``Decimal`` arithmetic is still
# the most portable fix across versions.


def _multiple_of_decimal(validator, multiple_of, instance, schema) -> Any:  # type: ignore[no-untyped-def]
    """``multipleOf`` validator that uses Decimal arithmetic.

    Returns a no-op iterator on success, or yields a
    :class:`jsonschema.ValidationError` on failure.
    """

    import math
    from decimal import Decimal, InvalidOperation

    if not isinstance(instance, (int, float)):
        return  # type-only constraint; not a number
    if multiple_of == 0:
        return
    try:
        d_instance = Decimal(str(instance))
        d_multiple = Decimal(str(multiple_of))
    except (InvalidOperation, ValueError):
        # Fall back to default behaviour for unconvertible values.
        if instance / multiple_of != math.floor(instance / multiple_of):
            yield jsonschema.ValidationError(
                f"{instance!r} is not a multiple of {multiple_of!r}",
            )
        return
    quotient = d_instance / d_multiple
    if quotient != quotient.to_integral_value():
        yield jsonschema.ValidationError(
            f"{instance!r} is not a multiple of {multiple_of!r}",
        )


#: Extended validator with the Decimal-arithmetic ``multipleOf``.
_EXTENDED_VALIDATOR: type[jsonschema.Draft7Validator] = _jsonschema_validators.extend(
    Draft7Validator,
    validators={"multipleOf": _multiple_of_decimal},
)


# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------


#: Default location of the JSON Schemas, relative to the project root.
DEFAULT_SCHEMA_DIR: Path = Path(__file__).resolve().parents[2] / "server" / "config" / "schemas"

#: Logical name → filename.  Names match the ``$id`` fragment
#: of each schema so callers can ask for "npc_proposal" without
#: knowing the filesystem layout.
SCHEMA_FILES: dict[str, str] = {
    "player_action": "player_action.schema.json",
    "npc_proposal": "npc_proposal.schema.json",
    "director_beat": "director_beat.schema.json",
    "resolver_outcome": "resolver_outcome.schema.json",
    "belief_matrix": "belief_matrix.schema.json",
    "narrative_contract": "narrative_contract.schema.json",
    "causal_seed": "causal_seed.schema.json",
    "world_snapshot": "world_snapshot.schema.json",
}


@dataclass(slots=True)
class ValidationIssue:
    """A single schema-validation issue, in human-readable form."""

    path: str
    message: str
    validator: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message} ({self.validator})"


@dataclass(slots=True)
class ValidationReport:
    """The result of a validation pass."""

    ok: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    parsed: dict[str, Any] | None = None

    def raise_if_invalid(self, *, schema: str) -> None:
        if not self.ok:
            raise SchemaValidationError(
                f"schema '{schema}' validation failed "
                f"({len(self.issues)} issues)",
                errors=[str(i) for i in self.issues],
                schema=schema,
            )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class SchemaValidator:
    """Loads the 8 JSON Schemas once and validates LLM output.

    Parameters
    ----------
    schema_dir
        Directory containing the schema JSON files.  Defaults to
        :data:`DEFAULT_SCHEMA_DIR`.  Override only for tests
        (e.g. with a tmp dir of synthetic schemas).
    """

    def __init__(self, schema_dir: Path | str | None = None) -> None:
        self._dir = Path(schema_dir) if schema_dir else DEFAULT_SCHEMA_DIR
        self._schemas: dict[str, dict[str, Any]] = {}
        self._validators: dict[str, _EXTENDED_VALIDATOR] = {}
        self._load_all()

    # ----- public API ----------------------------------------------------

    def validate(
        self,
        *,
        schema_name: str,
        payload: Mapping[str, Any] | str,
    ) -> ValidationReport:
        """Validate ``payload`` against the named schema.

        ``payload`` may be a dict (already parsed) or a string
        (will be parsed via :func:`models.safe_parse_json`).
        """

        schema = self._schemas.get(schema_name)
        if schema is None:
            raise KeyError(f"unknown schema: {schema_name}")
        if isinstance(payload, str):
            parsed = safe_parse_json(payload)
            if parsed is None:
                return ValidationReport(
                    ok=False,
                    issues=[ValidationIssue(
                        path="$",
                        message="payload is not parseable JSON",
                        validator="type",
                    )],
                )
        else:
            parsed = dict(payload)
        validator = self._validators[schema_name]
        errors = sorted(validator.iter_errors(parsed), key=lambda e: list(e.absolute_path))
        if not errors:
            return ValidationReport(ok=True, parsed=parsed)
        issues = [
            ValidationIssue(
                path="/" + "/".join(str(p) for p in err.absolute_path) or "/",
                message=err.message,
                validator=err.validator,
            )
            for err in errors
        ]
        return ValidationReport(ok=False, issues=issues, parsed=parsed)

    def validate_for_task(
        self,
        *,
        task_type: TaskType,
        payload: Mapping[str, Any] | str,
    ) -> ValidationReport:
        """Validate ``payload`` against the schema associated with ``task_type``.

        If the task type has no associated schema
        (:data:`TASK_TO_SCHEMA` is ``None``), returns
        :class:`ValidationReport` with ``ok=True`` and the parsed
        payload (or ``{}`` if the input was a string that didn't
        parse).
        """

        schema_name = TASK_TO_SCHEMA.get(task_type)
        if schema_name is None:
            if isinstance(payload, str):
                parsed = safe_parse_json(payload) or {}
            else:
                parsed = dict(payload)
            return ValidationReport(ok=True, parsed=parsed)
        return self.validate(schema_name=schema_name, payload=payload)

    def schema_for(self, name: str) -> dict[str, Any]:
        """Return the raw schema dict for ``name`` (used by tests)."""

        if name not in self._schemas:
            raise KeyError(f"unknown schema: {name}")
        return self._schemas[name]

    @property
    def schema_names(self) -> list[str]:
        return sorted(self._schemas.keys())

    # ----- internals -----------------------------------------------------

    def _load_all(self) -> None:
        if not self._dir.is_dir():
            raise FileNotFoundError(f"schema dir not found: {self._dir}")
        for name, filename in SCHEMA_FILES.items():
            path = self._dir / filename
            if not path.is_file():
                # Don't fail the whole gateway on a single missing
                # schema; the test suite builds synthetic schema
                # dirs.  Just skip.
                continue
            with path.open("r", encoding="utf-8") as f:
                schema = json.load(f)
            self._schemas[name] = schema
            # The RefResolver base is the schema's own $id when
            # present, else the file URI.
            store: dict[str, Any] = {**self._schemas}
            resolver = RefResolver(base_uri=schema.get("$id", path.as_uri()), referrer=schema, store=store)
            self._validators[name] = _EXTENDED_VALIDATOR(schema, resolver=resolver)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _retry_with_validation(
    *,
    validator: SchemaValidator,
    task_type: TaskType,
    schema_name: str | None,
    attempts: Sequence[Any],
    on_invalid: Any,
) -> Any:
    """Try each attempt; keep the first that passes schema validation.

    ``attempts`` is a list of strings (raw model output) or dicts
    (already-parsed JSON).  ``on_invalid`` is a one-arg callable
    invoked with the failed :class:`ValidationReport`; the
    gateway uses it to log the issue.

    Returns the first attempt whose JSON parses *and* passes
    validation.  Raises :class:`SchemaValidationError` if all
    attempts fail (or if there are no attempts).
    """

    last: ValidationReport | None = None
    for raw in attempts:
        if schema_name is None:
            # No schema for this task — accept anything parseable.
            if isinstance(raw, str):
                parsed = safe_parse_json(raw)
                if parsed is None:
                    on_invalid(ValidationReport(ok=False, parsed=None))
                    continue
                return parsed
            return dict(raw)
        report = validator.validate(schema_name=schema_name, payload=raw)
        if report.ok and report.parsed is not None:
            return report.parsed
        on_invalid(report)
        last = report
    if last is None:
        raise SchemaValidationError(
            f"no attempts supplied for task {task_type.value}",
            schema=schema_name or "",
        )
    last.raise_if_invalid(schema=schema_name or "")


__all__ = [
    "DEFAULT_SCHEMA_DIR",
    "SCHEMA_FILES",
    "ValidationIssue",
    "ValidationReport",
    "SchemaValidator",
    "_retry_with_validation",
]
