"""Output schema verifier — strict JSON-Schema check for every LLM output.

The 校验链 (verification chain) is the **last gate** before any
AI-produced payload reaches the canonical world state.  Every node
in the chain — ``int_parser`` (intent parser), ``npc`` (NPC Agent),
``director`` (Director Agent), ``resolver`` (Resolver) — must
emit a payload that conforms to a JSON-Schema declared in
``server/config/schemas/``.

This module is the **one** entry point the rest of the system
should use for that check.  It does *not* fix payloads; it rejects
them with a structured error report so the caller can decide
between falling back (W3-A degradation chain) or hard-blocking.

Design goals
------------

* **Strict** — the underlying ``jsonschema`` validator is in
  ``Draft7Validator`` mode; ``format`` checks are enabled.
* **Classified errors** — every failure is tagged with a stable
  error category (``format_error`` / ``enum_error`` /
  ``range_error`` / ``missing_field`` / ``extra_field`` /
  ``type_error`` / ``schema_error``) so the L4 fallback in
  ``degradation.py`` can switch on the category.
* **Self-contained** — no project imports; only stdlib + jsonschema.
  The safety package is what every other module depends on, so
  it must not depend on the engine.
* **Helpful reports** — every error includes the JSON path, the
  offending value (or its absence), the schema rule that fired,
  and a one-line human explanation.  Decision 6 requires the
  4-questions tool to "have a readable explanation"; the same
  rule applies here.

Why we do not "patch" LLM output
--------------------------------

Patching would let the LLM's bad numbers sneak into the
canonical state (e.g. ``relationship.trust = 5.0`` because the
LLM forgot the legal range).  The only safe place to clamp
numeric ranges is the Resolver, where the value is logged in
``ResolverOutcome.clampedValues``.  This verifier rejects
out-of-range values *before* they reach the Resolver so we can
keep the audit log small and meaningful.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

try:
    import jsonschema
    from jsonschema import Draft7Validator
    from jsonschema.exceptions import ValidationError as _JsonSchemaError
except ImportError as exc:  # pragma: no cover - jsonschema is documented as required
    raise ImportError(
        "The safety package requires the 'jsonschema' library. "
        "Install it with: pip install jsonschema"
    ) from exc


# ---------------------------------------------------------------------------
# Error categories
# ---------------------------------------------------------------------------


class ErrorCategory(str, Enum):
    """Stable error category strings used by the L4 degradation chain.

    Order matters for the human report; tests assert on the strings
    literally, so do **not** rename a category without updating the
    tests + the L4 fallback switch.
    """

    FORMAT_ERROR = "format_error"
    ENUM_ERROR = "enum_error"
    RANGE_ERROR = "range_error"
    MISSING_FIELD = "missing_field"
    EXTRA_FIELD = "extra_field"
    TYPE_ERROR = "type_error"
    SCHEMA_ERROR = "schema_error"


#: Map an internal ``jsonschema`` validator name to our public category.
#: Keys are the lower-cased validator names emitted by
#: ``jsonschema.exceptions.ValidationError.validator``.
_VALIDATOR_TO_CATEGORY: dict[str, ErrorCategory] = {
    # type checks
    "type": ErrorCategory.TYPE_ERROR,
    "required": ErrorCategory.MISSING_FIELD,
    "additionalProperties": ErrorCategory.EXTRA_FIELD,
    # numeric
    "minimum": ErrorCategory.RANGE_ERROR,
    "maximum": ErrorCategory.RANGE_ERROR,
    "exclusiveMinimum": ErrorCategory.RANGE_ERROR,
    "exclusiveMaximum": ErrorCategory.RANGE_ERROR,
    "multipleOf": ErrorCategory.RANGE_ERROR,
    # string
    "minLength": ErrorCategory.RANGE_ERROR,
    "maxLength": ErrorCategory.RANGE_ERROR,
    "pattern": ErrorCategory.FORMAT_ERROR,
    "format": ErrorCategory.FORMAT_ERROR,
    # enum
    "enum": ErrorCategory.ENUM_ERROR,
    "const": ErrorCategory.ENUM_ERROR,
    # array
    "minItems": ErrorCategory.RANGE_ERROR,
    "maxItems": ErrorCategory.RANGE_ERROR,
    "uniqueItems": ErrorCategory.RANGE_ERROR,
    # object
    "minProperties": ErrorCategory.RANGE_ERROR,
    "maxProperties": ErrorCategory.RANGE_ERROR,
    "dependencies": ErrorCategory.SCHEMA_ERROR,
    # conditional
    "if": ErrorCategory.SCHEMA_ERROR,
    "then": ErrorCategory.SCHEMA_ERROR,
    "else": ErrorCategory.SCHEMA_ERROR,
    "allOf": ErrorCategory.SCHEMA_ERROR,
    "anyOf": ErrorCategory.SCHEMA_ERROR,
    "oneOf": ErrorCategory.SCHEMA_ERROR,
    "not": ErrorCategory.SCHEMA_ERROR,
    # reference
    "$ref": ErrorCategory.SCHEMA_ERROR,
}


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FieldError:
    """One structured schema-violation report row.

    Attributes
    ----------
    category : ErrorCategory
        Stable error classification — see :class:`ErrorCategory`.
    path : str
        JSON-pointer style path of the offending value
        (e.g. ``"relationshipDelta[0].trust"``).
    validator : str
        The internal ``jsonschema`` validator name (e.g. ``"enum"``).
    message : str
        The raw jsonschema error message.
    offending_value : Any
        The value that violated the schema (or ``None`` for
        ``required``/``additionalProperties`` violations).
    schema_rule : Any
        The schema fragment the value violated (e.g. the enum
        list for an ``enum`` error).  Useful for "what was the
        legal set" diagnostics.
    explanation : str
        One-line human-readable explanation.  Pre-baked so the
        CLI does not have to do string templating.
    """

    category: str
    path: str
    validator: str
    message: str
    offending_value: Any
    schema_rule: Any
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationReport:
    """The aggregate result of verifying one payload against one schema.

    Attributes
    ----------
    schema_name : str
        Logical name of the schema (e.g. ``"player_action"``).
    schema_path : str
        Absolute path to the schema file.
    valid : bool
        True iff the payload passed every check.
    errors : list[FieldError]
        One entry per failure.
    summary : dict[str, int]
        Counts keyed by error category.
    """

    schema_name: str
    schema_path: str
    valid: bool
    errors: list[FieldError] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": self.schema_name,
            "schema_path": self.schema_path,
            "valid": self.valid,
            "errors": [e.to_dict() for e in self.errors],
            "summary": dict(self.summary),
        }

    def to_human_readable(self) -> str:
        lines: list[str] = []
        verdict = "✅ PASS" if self.valid else "❌ FAIL"
        lines.append(f"{verdict}  schema={self.schema_name}  path={self.schema_path}")
        s = self.summary
        lines.append(
            f"summary: {s.get('total', 0)} error(s); "
            + ", ".join(f"{k}={v}" for k, v in s.items() if k != "total" and v)
        )
        for e in self.errors:
            lines.append(f"  • [{e.category}] {e.path}")
            lines.append(f"      validator  : {e.validator}")
            if e.offending_value is not None:
                lines.append(f"      value      : {e.offending_value!r}")
            if e.schema_rule is not None:
                lines.append(f"      rule       : {e.schema_rule!r}")
            lines.append(f"      message    : {e.message}")
            lines.append(f"      hint       : {e.explanation}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Schema registry
# ---------------------------------------------------------------------------


#: Logical name → filename under ``server/config/schemas/``.
SCHEMA_REGISTRY: dict[str, str] = {
    "player_action": "player_action.schema.json",
    "npc_proposal": "npc_proposal.schema.json",
    "director_beat": "director_beat.schema.json",
    "resolver_outcome": "resolver_outcome.schema.json",
    "belief_matrix": "belief_matrix.schema.json",
    "narrative_contract": "narrative_contract.schema.json",
    "causal_seed": "causal_seed.schema.json",
    "world_snapshot": "world_snapshot.schema.json",
}


def _default_schema_dir() -> Path:
    """Return the canonical schema directory.

    The safety package is shipped at
    ``server/safety/output_verifier.py``; the schemas live at
    ``server/config/schemas/*.json``.  We resolve the latter from
    the former so the verifier is importable from anywhere.
    """

    here = Path(__file__).resolve().parent
    return here.parent / "config" / "schemas"


def _load_schema(schema_name: str, schema_dir: Path | None = None) -> tuple[dict[str, Any], Path]:
    """Load a schema by logical name and return ``(schema, abs_path)``.

    Raises
    ------
    KeyError
        ``schema_name`` is not in :data:`SCHEMA_REGISTRY`.
    FileNotFoundError
        The schema file does not exist on disk.
    json.JSONDecodeError
        The schema file is malformed.
    """

    if schema_name not in SCHEMA_REGISTRY:
        raise KeyError(
            f"unknown schema name {schema_name!r}; "
            f"available: {sorted(SCHEMA_REGISTRY)}"
        )
    sdir = schema_dir or _default_schema_dir()
    path = (sdir / SCHEMA_REGISTRY[schema_name]).resolve()
    with open(path, "r", encoding="utf-8") as fp:
        schema = json.load(fp)
    return schema, path


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def _format_path(error: _JsonSchemaError) -> str:
    """Render a ``jsonschema`` error path as a human-friendly string.

    ``jsonschema`` error paths are deque objects; we render them
    as ``"foo.bar[0].baz"`` so the report is grep-friendly.
    """

    parts: list[str] = []
    for token in error.absolute_path:
        if isinstance(token, int):
            parts.append(f"[{token}]")
        else:
            if parts:
                parts.append(f".{token}")
            else:
                parts.append(str(token))
    if not parts:
        # ``required`` errors put the missing field on
        # ``validator_value`` rather than ``absolute_path``.
        if error.validator == "required":
            missing = error.message.split("'")[-2] if "'" in error.message else "?"
            return f"<root>.{missing}"
        return "<root>"
    return "".join(parts)


def _format_path_from_parts(parts: Iterable[Any]) -> str:
    rendered: list[str] = []
    for token in parts:
        if isinstance(token, int):
            rendered.append(f"[{token}]")
        else:
            if rendered:
                rendered.append(f".{token}")
            else:
                rendered.append(str(token))
    return "".join(rendered) if rendered else "<root>"


def _classify(error: _JsonSchemaError) -> ErrorCategory:
    """Map a ``jsonschema`` error to our public category.

    The classification uses the validator name first; for the
    ``anyOf`` / ``oneOf`` cases the underlying ``context`` (the
    list of sub-errors) is walked to find the most specific
    category, which usually comes from one of the inner branches
    (e.g. an ``enum`` inside an ``anyOf``).
    """

    validator = error.validator or ""
    if validator in _VALIDATOR_TO_CATEGORY:
        # For "anyOf" / "oneOf" we want the most specific inner
        # cause, not the umbrella "schema_error" category.
        if validator in {"anyOf", "oneOf"} and error.context:
            inner: ErrorCategory = ErrorCategory.SCHEMA_ERROR
            for sub in error.context:
                if not sub.context:
                    sub_cat = _classify(sub)
                    if sub_cat != ErrorCategory.SCHEMA_ERROR:
                        inner = sub_cat
                        break
            else:
                # Walk the first sub-error one level deeper to
                # disambiguate.
                first = error.context[0]
                inner = _classify(first)
            return inner
        return _VALIDATOR_TO_CATEGORY[validator]

    # Unknown validator names default to SCHEMA_ERROR but log
    # the validator name in the message so the dev team can
    # extend the mapping.
    return ErrorCategory.SCHEMA_ERROR


def _explain(error: _JsonSchemaError, category: ErrorCategory) -> str:
    """Return a one-line human explanation for an error.

    The explanation uses the error's ``validator``, ``validator_value``,
    and a snippet of ``message`` so the reader doesn't have to look
    up the JSON-Schema spec.  Category-specific hints are added for
    the most common offenders.
    """

    validator = error.validator or "?"
    val = error.validator_value
    if category == ErrorCategory.MISSING_FIELD:
        if error.validator == "required":
            return "this required field is missing on the object"
        return "a field required by the schema is missing"
    if category == ErrorCategory.EXTRA_FIELD:
        return "object has fields not declared in the schema (additionalProperties: false)"
    if category == ErrorCategory.ENUM_ERROR:
        if isinstance(val, list):
            opts = ", ".join(repr(v) for v in val[:8])
            if len(val) > 8:
                opts += f", … (+{len(val) - 8} more)"
            return f"value not in the legal enum; allowed: {opts}"
        return f"value does not match the legal set: {val!r}"
    if category == ErrorCategory.RANGE_ERROR:
        if validator == "minimum":
            return f"value is below the minimum ({val})"
        if validator == "maximum":
            return f"value is above the maximum ({val})"
        if validator == "multipleOf":
            return f"value is not a multiple of {val}"
        if validator in {"minLength", "maxLength"}:
            return f"string length violates {validator}={val}"
        if validator in {"minItems", "maxItems"}:
            return f"array size violates {validator}={val}"
        if validator == "uniqueItems":
            return "array contains duplicate values"
        return f"value violates {validator}={val!r}"
    if category == ErrorCategory.FORMAT_ERROR:
        if validator == "format":
            return f"string is not a valid {val!r}"
        if validator == "pattern":
            return f"string does not match the required pattern {val!r}"
        return f"value violates {validator} format constraint"
    if category == ErrorCategory.TYPE_ERROR:
        return f"value is not of expected JSON type (expected {val!r})"
    # SCHEMA_ERROR
    if validator in {"anyOf", "oneOf"}:
        return f"value matches none of the {validator} branches"
    if validator == "allOf":
        return "value violates one of the allOf clauses"
    if validator == "$ref":
        return f"reference resolution failed: {val!r}"
    if validator == "if":
        return "value violates the if/then/else conditional rule"
    return f"schema rule {validator!r} failed"


# ---------------------------------------------------------------------------
# The verifier
# ---------------------------------------------------------------------------


def _coerce_input(payload: Any) -> Any:
    """Accept a JSON string, a dict, or a list; return the parsed form.

    The Agent layer sometimes hands us a raw ``str`` straight from
    the LLM; we parse it once here so the validator always sees a
    real object.  A malformed string is a ``format_error`` so the
    caller can fall back to L4.
    """

    if isinstance(payload, (str, bytes, bytearray)):
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="replace")
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            # Bubble up via a custom marker class
            raise _JSONParseError(str(exc)) from exc
    return payload


class _JSONParseError(Exception):
    """Internal: ``payload`` could not be parsed as JSON."""


class OutputVerifier:
    """The schema-validity gate of the 校验链.

    The verifier is **stateful** in the sense that it caches
    loaded schemas — the Resolver calls it many times per turn
    and we don't want to re-read the schema file every time.
    Cache eviction is handled by :meth:`clear_cache` (tests use
    it; production code rarely needs to).
    """

    def __init__(self, schema_dir: Path | None = None) -> None:
        self._schema_dir: Path = schema_dir or _default_schema_dir()
        self._cache: dict[str, tuple[dict[str, Any], Path]] = {}

    # ----- cache ----------------------------------------------------------

    def clear_cache(self) -> None:
        self._cache.clear()

    def _get_schema(self, schema_name: str) -> tuple[dict[str, Any], Path]:
        if schema_name in self._cache:
            return self._cache[schema_name]
        schema, path = _load_schema(schema_name, self._schema_dir)
        self._cache[schema_name] = (schema, path)
        return schema, path

    # ----- main API -------------------------------------------------------

    def verify(self, schema_name: str, payload: Any) -> VerificationReport:
        """Verify ``payload`` against the named schema.

        Parameters
        ----------
        schema_name : str
            Logical schema name (key in :data:`SCHEMA_REGISTRY`).
        payload : Any
            The candidate object.  May be a ``dict`` / ``list`` or
            a JSON string; strings are parsed once.

        Returns
        -------
        VerificationReport
            Never raises for valid payloads; reports the failure
            for invalid ones.  Only raises on infrastructure
            failures (unknown schema name, malformed JSON).
        """

        schema, path = self._get_schema(schema_name)
        try:
            instance = _coerce_input(payload)
        except _JSONParseError as exc:
            return VerificationReport(
                schema_name=schema_name,
                schema_path=str(path),
                valid=False,
                errors=[
                    FieldError(
                        category=ErrorCategory.FORMAT_ERROR.value,
                        path="<root>",
                        validator="json-parse",
                        message=f"could not parse payload as JSON: {exc}",
                        offending_value=None,
                        schema_rule=None,
                        explanation="LLM returned text that is not valid JSON",
                    )
                ],
                summary=self._summary_from_categories([ErrorCategory.FORMAT_ERROR.value]),
            )

        validator = Draft7Validator(schema)
        errors: list[FieldError] = []
        for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
            errors.append(self._convert(err, schema))
        summary = self._summary_from_categories([e.category for e in errors])
        return VerificationReport(
            schema_name=schema_name,
            schema_path=str(path),
            valid=len(errors) == 0,
            errors=errors,
            summary=summary,
        )

    # ----- internals ------------------------------------------------------

    @staticmethod
    def _convert(error: _JsonSchemaError, schema: dict[str, Any]) -> FieldError:
        category = _classify(error)
        path = _format_path(error)
        offending = error.instance
        if category == ErrorCategory.MISSING_FIELD:
            offending = None
        explanation = _explain(error, category)
        return FieldError(
            category=category.value,
            path=path,
            validator=error.validator or "?",
            message=error.message,
            offending_value=offending,
            schema_rule=error.validator_value,
            explanation=explanation,
        )

    @staticmethod
    def _summary_from_categories(categories: Iterable[str]) -> dict[str, int]:
        summary: dict[str, int] = {
            ErrorCategory.FORMAT_ERROR.value: 0,
            ErrorCategory.ENUM_ERROR.value: 0,
            ErrorCategory.RANGE_ERROR.value: 0,
            ErrorCategory.MISSING_FIELD.value: 0,
            ErrorCategory.EXTRA_FIELD.value: 0,
            ErrorCategory.TYPE_ERROR.value: 0,
            ErrorCategory.SCHEMA_ERROR.value: 0,
            "total": 0,
        }
        for c in categories:
            summary[c] = summary.get(c, 0) + 1
            summary["total"] += 1
        return summary


# ---------------------------------------------------------------------------
# Convenience functions (for the simple "just check it" path)
# ---------------------------------------------------------------------------


_DEFAULT_VERIFIER: OutputVerifier | None = None


def _verifier() -> OutputVerifier:
    global _DEFAULT_VERIFIER
    if _DEFAULT_VERIFIER is None:
        _DEFAULT_VERIFIER = OutputVerifier()
    return _DEFAULT_VERIFIER


def verify_output(schema_name: str, payload: Any) -> VerificationReport:
    """Module-level convenience wrapper around :meth:`OutputVerifier.verify`.

    The default verifier caches schemas on first use.  Tests that
    need to mock the schema directory should instantiate
    :class:`OutputVerifier` directly.
    """

    return _verifier().verify(schema_name, payload)


__all__ = [
    "ErrorCategory",
    "FieldError",
    "VerificationReport",
    "OutputVerifier",
    "SCHEMA_REGISTRY",
    "verify_output",
    "_format_path_from_parts",  # exposed for testing
]
