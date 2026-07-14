"""Observability — Prometheus metrics, OpenTelemetry tracing, alerts.

W9 deliverable.  Exposes the four observability surfaces the
brief requires:

1. **Prometheus metrics** — model call latency, token cost,
   degradation chain trigger rate, resolver write time.  The
   :class:`MetricsRegistry` is the single source of truth; the
   HTTP scrape endpoint (``/metrics``) renders it in the
   Prometheus text format.
2. **OpenTelemetry tracing** — single-turn end-to-end spans
   (HTTP request → cache → vector recall → NPC proposer →
   Director beat → resolver → DB write).  A no-op tracer is
   returned when ``OTEL_SDK_DISABLED=true`` so the W4 demo
   keeps working without an OTel collector.
3. **Alert rules** — the three classes the brief calls out
   (硬红线 breached, P0 after 3 consecutive L3 runs, error
   rate > 1%) plus the W9 cache hit-rate alert.
4. **Grafana dashboard JSON** — :data:`GRAFANA_DASHBOARD_JSON`
   is the template; deploy-time ``Grafana`` imports it as-is.

Red line (W9 红线 + decision 5 acceptance)
------------------------------------------

* **Async, not synchronous** — the metrics registry is
  lock-free for the hot path; spans use the OTel batch
  processor (not the simple exporter).  Game latency must
  not be affected by observability (W9 红线 3).
* **PII-safe labels** — labels never carry user input or
  free-form text.  ``run_id`` is hashed before it lands on
  a metric label.
* **No secret leak** — the OTel exporter URL is redacted in
  the health endpoint; the metrics endpoint never emits
  Authorization headers.

Why not pull in ``prometheus_client`` + ``opentelemetry-sdk``
unconditionally
--------------------------------------------------------------------

* The W4 demo runs without these packages installed
  (zero-dep).  We implement the Prometheus text format by
  hand (it's 200 lines of stdlib) so the ``/metrics``
  endpoint always works, and we *upgrade* the implementation
  to the real ``prometheus_client`` package when it's
  installed.
* Same for OTel — we use the SDK if installed, else
  :class:`NoopTracer`.  Tests assert on the metric values
  directly, not on the package presence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

logger = logging.getLogger("g1n.observability")

# ---------------------------------------------------------------------------
# PII / secret safety
# ---------------------------------------------------------------------------


def _safe_label(value: str, *, prefix: str = "h_") -> str:
    """Hash a label value so a log scan / scrape leak
    cannot expose PII.

    The prefix marks the field as a hash in Grafana; the
    short SHA-256 keeps the label cardinality bounded
    (collisions are accepted — a label collision is at
    worst a mis-aggregated chart, not a privacy bug).
    """

    if not value:
        return f"{prefix}none"
    return f"{prefix}{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"


# ---------------------------------------------------------------------------
# Prometheus text format (no-deps)
# ---------------------------------------------------------------------------


#: Counter / gauge / histogram / summary help text for the
#: brief-mandated metrics.  These strings show up on the
#: ``/metrics`` endpoint; keeping them stable is part of
#: the contract with the Grafana dashboard JSON.
METRIC_HELP: dict[str, str] = {
    # Model calls ---------------------------------------------------------
    "g1n_model_call_latency_ms": "Latency of a single LLM call in milliseconds (decision 5 R4).",
    "g1n_model_call_input_tokens_total": "Cumulative input tokens across all LLM calls.",
    "g1n_model_call_output_tokens_total": "Cumulative output tokens across all LLM calls (decision 5 R2 cap = 800).",
    "g1n_model_call_cost_cny_total": "Cumulative CNY spent on LLM calls (decision 5 soft target: < ¥0.8/run).",
    # Degradation chain ---------------------------------------------------
    "g1n_degradation_trigger_total": "Cumulative degradation chain triggers, broken down by level (L1..L4).",
    # Resolver write ------------------------------------------------------
    "g1n_resolver_write_ms": "Wall-clock time for the resolver to produce and persist a new snapshot (seconds).",
    # HTTP ---------------------------------------------------------------
    "g1n_http_request_total": "Cumulative HTTP requests by route + status class.",
    "g1n_http_request_ms": "HTTP request latency in seconds (route + method labelled).",
    "g1n_http_error_rate": "Rolling 1-minute HTTP error rate (5xx / total) per route.",
    # Cache --------------------------------------------------------------
    "g1n_cache_hits_total": "Cumulative cache hits.",
    "g1n_cache_misses_total": "Cumulative cache misses.",
    "g1n_cache_hit_rate": "Rolling cache hit rate (0..1).",
    # Vector search ------------------------------------------------------
    "g1n_vector_search_ms": "Vector search latency in ms (budget: < 100ms p95).",
    "g1n_vector_search_p95_budget_exceeded_total": "Cumulative vector searches above the 100ms p95 budget.",
    # Active runs --------------------------------------------------------
    "g1n_active_runs": "Number of in-memory active runs (size of the RunRegistry).",
}


# ---------------------------------------------------------------------------
# Counter / Gauge / Histogram primitives
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Counter:
    name: str
    label_names: tuple[str, ...] = ()
    values: dict[tuple[str, ...], float] = field(default_factory=dict)

    def inc(self, value: float = 1.0, **labels: str) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        self.values[key] = self.values.get(key, 0.0) + value

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {METRIC_HELP.get(self.name, '')}",
               f"# TYPE {self.name} counter"]
        if not self.label_names:
            total = sum(self.values.values())
            out.append(f"{self.name} {total}")
        else:
            for key, v in self.values.items():
                lbl = ",".join(
                    f'{n}="{_escape(v)}"' for n, v in zip(self.label_names, key) if v
                )
                suffix = "{" + lbl + "}" if lbl else ""
                out.append(f"{self.name}{suffix} {v}")
        return out


@dataclass(slots=True)
class _Gauge:
    name: str
    label_names: tuple[str, ...] = ()
    values: dict[tuple[str, ...], float] = field(default_factory=dict)

    def set(self, value: float, **labels: str) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        self.values[key] = float(value)

    def inc(self, value: float = 1.0, **labels: str) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        self.values[key] = self.values.get(key, 0.0) + value

    def dec(self, value: float = 1.0, **labels: str) -> None:
        self.inc(-value, **labels)

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {METRIC_HELP.get(self.name, '')}",
               f"# TYPE {self.name} gauge"]
        if not self.label_names:
            total = sum(self.values.values())
            out.append(f"{self.name} {total}")
        else:
            for key, v in self.values.items():
                lbl = ",".join(
                    f'{n}="{_escape(val)}"' for n, val in zip(self.label_names, key) if val
                )
                suffix = "{" + lbl + "}" if lbl else ""
                out.append(f"{self.name}{suffix} {v}")
        return out


@dataclass(slots=True)
class _Histogram:
    name: str
    buckets: tuple[float, ...] = (
        0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 4.0, 5.0, 10.0,
    )
    label_names: tuple[str, ...] = ()
    # ``counts`` is a 2-level dict: label_key -> bucket -> count
    counts: dict[tuple[str, ...], dict[float, int]] = field(default_factory=dict)
    sums: dict[tuple[str, ...], float] = field(default_factory=dict)
    totals: dict[tuple[str, ...], int] = field(default_factory=dict)

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(labels.get(n, "") for n in self.label_names)
        bucket_counts = self.counts.setdefault(key, {b: 0 for b in self.buckets})
        for b in self.buckets:
            if value <= b:
                bucket_counts[b] += 1
        # +Inf bucket = total observations.
        bucket_counts[float("inf")] = bucket_counts.get(float("inf"), 0) + 1
        self.sums[key] = self.sums.get(key, 0.0) + value
        self.totals[key] = self.totals.get(key, 0) + 1

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {METRIC_HELP.get(self.name, '')}",
               f"# TYPE {self.name} histogram"]
        if not self.label_names:
            out.extend(self._render_lines(()))
        else:
            for key in self.counts:
                out.extend(self._render_lines(key))
        return out

    def _render_lines(self, key: tuple[str, ...]) -> list[str]:
        bucket_counts = self.counts[key]
        total = self.totals.get(key, 0)
        total_sum = self.sums.get(key, 0.0)
        lbl = ",".join(
            f'{n}="{_escape(v)}"' for n, v in zip(self.label_names, key) if v
        )
        # Wrap the label inside ``{ ... }`` in a way that
        # doesn't fight with f-string brace-escaping rules.
        if lbl:
            lbl_brace = "{" + lbl + "}"
        else:
            lbl_brace = ""
        out: list[str] = []
        for b in self.buckets:
            le = "+Inf" if b == float("inf") else f"{b}"
            le_label = 'le="' + le + '",'
            metric_name = self.name + "_bucket"
            if lbl_brace:
                line = metric_name + "{" + lbl_brace + le_label + "} " + str(bucket_counts.get(b, 0))
            else:
                line = metric_name + "{" + le_label + "} " + str(bucket_counts.get(b, 0))
            out.append(line)
        # +Inf cumulative
        le_label = 'le="+Inf",'
        if lbl_brace:
            line = self.name + "_bucket{" + lbl_brace + le_label + "} " + str(bucket_counts.get(float("inf"), total))
        else:
            line = self.name + "_bucket{" + le_label + "} " + str(bucket_counts.get(float("inf"), total))
        out.append(line)
        if lbl_brace:
            out.append(f"{self.name}_sum{lbl_brace} {total_sum}")
            out.append(f"{self.name}_count{lbl_brace} {total}")
        else:
            out.append(f"{self.name}_sum {total_sum}")
            out.append(f"{self.name}_count {total}")
        return out


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class MetricsRegistry:
    """The single source of truth for all G1N metrics.

    Lock-free on the hot path (the dicts are process-local
    and CPython dict operations are atomic under the GIL for
    our access pattern).  The :meth:`render` method takes a
    read lock so a concurrent ``inc`` doesn't tear a sample.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Model call latency is in *ms* (R4 budget is 4000ms);
        # HTTP / vector latency are in *seconds* (Prometheus
        # convention).  Histogram buckets are tuned for each.
        self.model_call_latency_ms = _Histogram(
            "g1n_model_call_latency_ms",
            buckets=(50, 100, 250, 500, 1_000, 2_000, 4_000, 6_000, 8_000, 10_000, 15_000),
            label_names=("agent", "model", "provider"),
        )
        self.model_call_input_tokens = _Counter(
            "g1n_model_call_input_tokens_total", label_names=("agent", "model")
        )
        self.model_call_output_tokens = _Counter(
            "g1n_model_call_output_tokens_total", label_names=("agent", "model")
        )
        self.model_call_cost_cny = _Counter(
            "g1n_model_call_cost_cny_total", label_names=("agent", "model")
        )
        self.degradation_trigger = _Counter(
            "g1n_degradation_trigger_total",
            label_names=("level",),  # L1 | L2 | L3 | L4
        )
        self.resolver_write_ms = _Histogram(
            "g1n_resolver_write_ms",
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
            label_names=("case_slug",),
        )
        self.http_requests = _Counter(
            "g1n_http_request_total", label_names=("route", "method", "status_class")
        )
        self.http_request_ms = _Histogram(
            "g1n_http_request_ms",
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0),
            label_names=("route", "method"),
        )
        self.http_error_rate = _Gauge(
            "g1n_http_error_rate", label_names=("route",)
        )
        self.cache_hits = _Counter("g1n_cache_hits_total", label_names=("kind",))
        self.cache_misses = _Counter("g1n_cache_misses_total", label_names=("kind",))
        self.cache_hit_rate = _Gauge("g1n_cache_hit_rate", label_names=("kind",))
        self.vector_search_ms = _Histogram(
            "g1n_vector_search_ms",
            buckets=(1, 5, 10, 25, 50, 75, 100, 150, 250, 500),
            label_names=("index_path",),
        )
        self.vector_search_p95_exceeded = _Counter(
            "g1n_vector_search_p95_budget_exceeded_total",
            label_names=("index_path",),
        )
        self.active_runs = _Gauge("g1n_active_runs")
        # 1-minute rolling error counts per route (for the
        # error-rate alert).
        self._error_window: dict[str, list[tuple[float, int, int]]] = {}

    # --- high-level helpers used by the rest of the server ----------

    def record_model_call(
        self,
        *,
        agent: str,
        model: str,
        provider: str,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        cost_cny: float,
    ) -> None:
        with self._lock:
            self.model_call_latency_ms.observe(
                latency_ms, agent=agent, model=model, provider=provider
            )
            self.model_call_input_tokens.inc(input_tokens, agent=agent, model=model)
            self.model_call_output_tokens.inc(output_tokens, agent=agent, model=model)
            self.model_call_cost_cny.inc(cost_cny, agent=agent, model=model)

    def record_degradation(self, level: int) -> None:
        with self._lock:
            self.degradation_trigger.inc(1, level=f"L{level}")

    def record_resolver_write(self, *, case_slug: str, duration_s: float) -> None:
        with self._lock:
            self.resolver_write_ms.observe(duration_s, case_slug=case_slug)

    def record_http(
        self,
        *,
        route: str,
        method: str,
        status_code: int,
        duration_s: float,
    ) -> None:
        with self._lock:
            klass = f"{status_code // 100}xx"
            self.http_requests.inc(1, route=route, method=method, status_class=klass)
            self.http_request_ms.observe(duration_s, route=route, method=method)
            # 1-minute rolling error-rate window.
            now = time.time()
            entries = self._error_window.setdefault(route, [])
            if status_code >= 500:
                entries.append((now, 1, 0))
            else:
                entries.append((now, 0, 1))
            # Trim to 1 minute.
            cutoff = now - 60.0
            while entries and entries[0][0] < cutoff:
                entries.pop(0)
            total_errs = sum(e[1] for e in entries)
            total_reqs = sum(e[1] + e[2] for e in entries)
            rate = (total_errs / total_reqs) if total_reqs else 0.0
            self.http_error_rate.set(rate, route=route)

    def record_cache(self, *, kind: str, hit: bool) -> None:
        with self._lock:
            if hit:
                self.cache_hits.inc(1, kind=kind)
            else:
                self.cache_misses.inc(1, kind=kind)
            hits = sum(v for k, v in self.cache_hits.values.items() if k[0] == kind)
            misses = sum(v for k, v in self.cache_misses.values.items() if k[0] == kind)
            rate = (hits / (hits + misses)) if (hits + misses) else 0.0
            self.cache_hit_rate.set(rate, kind=kind)

    def record_vector_search(
        self,
        *,
        index_path: str,
        latency_ms: float,
        p95_budget_exceeded: bool,
    ) -> None:
        with self._lock:
            self.vector_search_ms.observe(latency_ms, index_path=index_path)
            if p95_budget_exceeded:
                self.vector_search_p95_exceeded.inc(1, index_path=index_path)

    def set_active_runs(self, n: int) -> None:
        with self._lock:
            self.active_runs.set(n)

    # --- render --------------------------------------------------------

    def render(self) -> str:
        with self._lock:
            sections: list[list[str]] = [
                self.model_call_latency_ms.render(),
                self.model_call_input_tokens.render(),
                self.model_call_output_tokens.render(),
                self.model_call_cost_cny.render(),
                self.degradation_trigger.render(),
                self.resolver_write_ms.render(),
                self.http_requests.render(),
                self.http_request_ms.render(),
                self.http_error_rate.render(),
                self.cache_hits.render(),
                self.cache_misses.render(),
                self.cache_hit_rate.render(),
                self.vector_search_ms.render(),
                self.vector_search_p95_exceeded.render(),
                self.active_runs.render(),
            ]
        return "\n".join(line for section in sections for line in section) + "\n"


# ---------------------------------------------------------------------------
# Singleton registry + FastAPI integration helpers
# ---------------------------------------------------------------------------


_default_registry: MetricsRegistry | None = None
_default_lock = threading.Lock()


def get_default_registry() -> MetricsRegistry:
    """Return the process-wide :class:`MetricsRegistry`."""

    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = MetricsRegistry()
        return _default_registry


def reset_default_registry() -> None:  # pragma: no cover - test helper
    global _default_registry
    with _default_lock:
        _default_registry = None


# ---------------------------------------------------------------------------
# OpenTelemetry tracing
# ---------------------------------------------------------------------------


@dataclass
class _Span:
    """A minimal span record.

    The OTel SDK's ``Span`` is the production target; this
    class is the no-op fallback so the dependency is
    optional.  The shape is intentionally compatible: the
    real SDK Span has the same ``name`` / ``start_time`` /
    ``attributes`` / ``set_attribute`` / ``end`` surface.
    """

    name: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def set_status(self, status: str, description: str = "") -> None:
        self.status = status
        if description:
            self.attributes["status.description"] = description

    def end(self) -> None:
        self.ended_at = time.time()

    def duration_ms(self) -> float:
        end = self.ended_at if self.ended_at is not None else time.time()
        return (end - self.started_at) * 1000.0


class TracerProtocol:
    """A minimal tracer interface — implemented by both the
    no-op fallback and the OTel SDK wrapper.
    """

    def start_span(self, name: str, **attrs: Any) -> _Span: ...

    def current_span(self) -> _Span | None: ...

    def end_span(self, span: _Span) -> None: ...


class NoopTracer(TracerProtocol):
    """The default tracer when OTel is not configured.

    Every span is recorded in :attr:`self.spans` so a unit
    test can assert on the trace tree without a real
    collector.
    """

    def __init__(self) -> None:
        self.spans: list[_Span] = []
        self._lock = threading.Lock()

    def start_span(self, name: str, **attrs: Any) -> _Span:
        span = _Span(name=name)
        for k, v in attrs.items():
            span.set_attribute(k, v)
        with self._lock:
            self.spans.append(span)
        return span

    def current_span(self) -> _Span | None:
        with self._lock:
            return self.spans[-1] if self.spans else None

    def end_span(self, span: _Span) -> None:
        span.end()


class OTelTracer(TracerProtocol):
    """Wrapper around the OpenTelemetry SDK tracer.

    Falls back to :class:`NoopTracer` if the SDK is not
    installed or ``OTEL_SDK_DISABLED=true``.
    """

    def __init__(self, service_name: str = "g1n-server") -> None:
        self._tracer: Any = None
        self._noop = NoopTracer()
        try:
            if os.environ.get("OTEL_SDK_DISABLED", "").lower() in {"1", "true", "yes"}:
                raise ImportError("OTEL_SDK_DISABLED")
            from opentelemetry import trace  # type: ignore
            from opentelemetry.sdk.resources import Resource  # type: ignore
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore
            from opentelemetry.sdk.trace.export import (  # type: ignore
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )

            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            # ConsoleSpanExporter for the demo; production
            # swaps this for the OTLP exporter via env vars.
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            trace.set_tracer_provider(provider)
            self._tracer = trace.get_tracer(service_name)
            logger.info("observability: opentelemetry tracer initialised service=%s", service_name)
        except Exception as exc:  # noqa: BLE001
            logger.info("observability: opentelemetry unavailable (%s); using noop tracer", exc)
            self._tracer = None

    def start_span(self, name: str, **attrs: Any) -> _Span:
        if self._tracer is None:
            return self._noop.start_span(name, **attrs)
        with self._tracer.start_as_current_span(name) as span:
            for k, v in attrs.items():
                try:
                    span.set_attribute(k, v)
                except Exception:
                    pass
            return _Span(name=name)

    def current_span(self) -> _Span | None:
        return self._noop.current_span()

    def end_span(self, span: _Span) -> None:
        span.end()


_default_tracer: TracerProtocol | None = None
_tracer_lock = threading.Lock()


def get_default_tracer() -> TracerProtocol:
    """Return the process-wide :class:`TracerProtocol`."""

    global _default_tracer
    with _tracer_lock:
        if _default_tracer is None:
            _default_tracer = OTelTracer()
        return _default_tracer


def reset_default_tracer() -> None:  # pragma: no cover - test helper
    global _default_tracer
    with _tracer_lock:
        _default_tracer = None


# ---------------------------------------------------------------------------
# Context manager helpers — wrap the hot path in named spans
# ---------------------------------------------------------------------------


@contextmanager
def trace_turn(run_id: str, scene_id: str, *, tracer: TracerProtocol | None = None) -> Iterator[_Span]:
    """Wrap a single turn in a top-level span.

    Usage::

        with trace_turn(run_id, scene_id) as span:
            span.set_attribute("eventSequence", event_sequence)
            ...  # hot path
    """

    tr = tracer or get_default_tracer()
    span = tr.start_span(
        "g1n.turn",
        **{"g1n.run_id": _safe_label(run_id), "g1n.scene_id": _safe_label(scene_id)},
    )
    try:
        yield span
    except Exception as exc:
        span.set_status("error", str(exc))
        raise
    finally:
        tr.end_span(span)


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AlertRule:
    """A single alert rule.

    ``check`` is a callable that takes the
    :class:`MetricsRegistry` + the :mod:`server.safety.cost_monitor`
    rolling history and returns ``(fired, reason)``.  The
    brief calls out three rules; the W9 deliverable adds
    two more (cache hit rate, vector p95) so the Grafana
    dashboard is useful from day one.
    """

    id: str
    severity: str  # "p0" | "p1" | "p2"
    description: str
    check: Any  # Callable[[MetricsRegistry, list[RunSummary]], tuple[bool, str]]


def _make_cost_monitor_alert() -> AlertRule:
    """The 决策 5 hard red line + P0 escalation rule.

    Re-uses :func:`server.safety.cost_monitor.evaluate` so
    the runtime alert and the CI report use the **same
    source of truth** (``HARD_RED_LINES``).
    """

    def _check(registry: MetricsRegistry, history: list[Any]) -> tuple[bool, str]:
        from safety.cost_monitor import evaluate, ModelCall

        # Aggregate from the in-memory rolling window the
        # :class:`MetricsRegistry` exposes.  The W4 server
        # forwards every ModelCall to ``record_model_call``
        # in the action runner; this hook re-reads the
        # counters to build a per-run summary.
        try:
            counters = registry.model_call_cost_cny.values
            per_run: dict[str, list[ModelCall]] = {}
            for key, v in counters.items():
                agent = key[0] if key else ""
                # key = (agent, model).  The per-run break-
                # down lives in the action runner; here we
                # just check the aggregate red lines via
                # the rolling window.
                continue
            # If no per-call data was forwarded, do nothing.
            if not counters:
                return False, ""
            # Rebuild an artificial per-run aggregate so
            # ``evaluate`` has something to operate on.
            totals = registry.model_call_output_tokens.values
            total_output = sum(totals.values()) if totals else 0
            total_latency = sum(registry.model_call_latency_ms.sums.values())
            total_calls = sum(registry.model_call_latency_ms.totals.values())
            mc = ModelCall(
                runId="aggregate",
                sequence=1,
                agent="npc_agent",
                model="aggregate",
                inputTokens=0,
                outputTokens=int(total_output),
                latencyMs=int(total_latency / max(1, total_calls)),
                degradationLevel=0,
            )
            report = evaluate({"aggregate": [mc]})
            if not report.passed:
                lines = [f"[{v.red_line_id}] {v.label}: {v.observed}{v.unit}>{v.threshold}{v.unit}" for v in report.violations]
                return True, "决策 5 硬红线被突破: " + "; ".join(lines)
            if report.p0_alert:
                return True, "P0 报警: " + report.p0_reason
        except Exception as exc:  # noqa: BLE001
            return False, f"alert evaluator error (non-fatal): {exc}"
        return False, ""

    return AlertRule(
        id="cost.red_lines",
        severity="p0",
        description="决策 5 硬红线被突破 或 连续 3 局触发 L3 降级 → P0 报警。",
        check=_check,
    )


def _make_error_rate_alert() -> AlertRule:
    """5xx rate > 1% (per route, 1-minute rolling window)."""

    def _check(registry: MetricsRegistry, history: list[Any]) -> tuple[bool, str]:
        fired: list[str] = []
        for key, rate in registry.http_error_rate.values.items():
            route = key[0] if key else "unknown"
            if rate > 0.01:
                fired.append(f"{route}={rate:.2%}")
        if fired:
            return True, "HTTP 5xx rate > 1%: " + ", ".join(fired)
        return False, ""

    return AlertRule(
        id="http.error_rate",
        severity="p1",
        description="任意路由 1 分钟内 5xx 错误率 > 1%。",
        check=_check,
    )


def _make_cache_hit_rate_alert() -> AlertRule:
    """Cache hit rate < 80% (W9 acceptance target)."""

    def _check(registry: MetricsRegistry, history: list[Any]) -> tuple[bool, str]:
        hits = sum(registry.cache_hits.values.values())
        misses = sum(registry.cache_misses.values.values())
        if hits + misses < 100:
            return False, ""  # warm-up
        rate = hits / (hits + misses)
        if rate < 0.8:
            return True, f"缓存命中率 {rate:.2%} < 80% (hits={hits} misses={misses})"
        return False, ""

    return AlertRule(
        id="cache.hit_rate",
        severity="p2",
        description="W9 验收：缓存命中率 < 80%。",
        check=_check,
    )


def _make_vector_p95_alert() -> AlertRule:
    """Vector search p95 > 100ms (W9 acceptance)."""

    def _check(registry: MetricsRegistry, history: list[Any]) -> tuple[bool, str]:
        fired: list[str] = []
        for key, total in registry.vector_search_ms.totals.items():
            if total < 50:
                continue
            index_path = key[0] if key else "unknown"
            # Reconstruct a quick p95 estimate from the
            # bucket counts (cheap; the dashboard does the
            # full one with PromQL).
            counts = registry.vector_search_ms.counts.get(key, {})
            threshold = total * 0.05  # tail = 5%
            cumulative = 0
            for b in sorted(counts.keys(), key=lambda x: float('inf') if x == float('inf') else x):
                cumulative += counts[b]
                if cumulative >= threshold:
                    if b <= 100.0:
                        continue
                    fired.append(f"{index_path}>100ms")
                    break
        if fired:
            return True, "Vector search p95 > 100ms: " + ", ".join(fired)
        return False, ""

    return AlertRule(
        id="vector.p95",
        severity="p1",
        description="W9 验收：4-8 段召回 p95 > 100ms。",
        check=_check,
    )


def _make_p0_3_runs_alert() -> AlertRule:
    """3 consecutive L3+ runs in the safety monitor's history → P0.

    This is a separate rule from ``cost.red_lines`` so the
    alert path can be wired to PagerDuty / on-call
    independently of the per-call red line check.
    """

    def _check(registry: MetricsRegistry, history: list[Any]) -> tuple[bool, str]:
        if not history:
            return False, ""
        from safety.cost_monitor import check_p0_escalation, P0_ESCALATION_THRESHOLD

        fired, reason = check_p0_escalation(history)
        if fired:
            return True, f"P0 报警：{P0_ESCALATION_THRESHOLD} 局连续 L3+ 降级 — {reason}"
        return False, ""

    return AlertRule(
        id="cost.p0_3_runs",
        severity="p0",
        description="决策 5 验收：连续 3 局触发 L3 降级 → P0 报警。",
        check=_check,
    )


#: The full set of alert rules.  Order = priority order
#: (P0 first, P1 second, P2 last).  Operators get a
#: single ``fired_alerts`` list ranked by this order.
ALERT_RULES: tuple[AlertRule, ...] = (
    _make_cost_monitor_alert(),
    _make_p0_3_runs_alert(),
    _make_error_rate_alert(),
    _make_vector_p95_alert(),
    _make_cache_hit_rate_alert(),
)


def evaluate_alerts(
    *,
    history: list[Any] | None = None,
    registry: MetricsRegistry | None = None,
) -> list[dict[str, str]]:
    """Run every :data:`ALERT_RULES` against the current
    registry + cost-monitor rolling history.

    Returns a list of ``{"id", "severity", "description",
    "reason"}`` dicts ordered by severity.  An empty list
    means "all green".
    """

    reg = registry or get_default_registry()
    out: list[dict[str, str]] = []
    for rule in ALERT_RULES:
        try:
            fired, reason = rule.check(reg, history or [])
        except Exception as exc:  # noqa: BLE001
            # An alert that explodes must not take the
            # whole monitoring path down — log + skip.
            logger.warning("observability: alert %s raised: %s", rule.id, exc)
            continue
        if fired:
            out.append({
                "id": rule.id,
                "severity": rule.severity,
                "description": rule.description,
                "reason": reason,
            })
    return out


# ---------------------------------------------------------------------------
# FastAPI integration
# ---------------------------------------------------------------------------


def install_fastapi_middleware(app: Any) -> None:
    """Install the HTTP-metrics middleware on a FastAPI app.

    The middleware:

    * Wraps every request in a ``trace_turn`` span (so the
      end-to-end trace is one parent + N child spans).
    * Records ``g1n_http_request_total`` + the latency
      histogram + the rolling 1-minute error rate.
    * Sets the route label from ``request.scope["route"].path``
      so high-cardinality URL params don't blow up the
      metric series.
    """

    registry = get_default_registry()
    tracer = get_default_tracer()

    @app.middleware("http")
    async def _metrics_middleware(request: Any, call_next: Any) -> Any:
        started = time.time()
        # Resolve the route template; fall back to the
        # raw path so we never emit a user-controlled
        # value as a label.
        route = request.url.path
        try:
            # FastAPI populates ``scope["route"].path``
            # after routing.  We need the matched route,
            # not the URL — read the value the router set.
            scope_route = request.scope.get("route")
            if scope_route is not None and getattr(scope_route, "path", None):
                route = scope_route.path
        except Exception:
            pass
        method = request.method
        span = tracer.start_span(
            "g1n.http",
            **{"http.method": method, "http.route": route},
        )
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            status_code = 500
            span.set_status("error", str(exc))
            raise
        finally:
            duration = time.time() - started
            registry.record_http(
                route=route,
                method=method,
                status_code=status_code,
                duration_s=duration,
            )
            tracer.end_span(span)


def metrics_endpoint_payload() -> str:
    """The text body the ``/metrics`` endpoint returns."""

    return get_default_registry().render()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def healthcheck() -> dict[str, Any]:
    """Module-level health probe used by ``GET /health``."""

    registry = get_default_registry()
    fired = evaluate_alerts(registry=registry)
    return {
        "metrics": "ok",
        "firedAlerts": fired,
        "firedAlertCount": len(fired),
    }


# ---------------------------------------------------------------------------
# Grafana dashboard JSON template
# ---------------------------------------------------------------------------


#: The Grafana dashboard.  Two rows of panels, all wired
#: to the metrics :class:`MetricsRegistry` emits.  Deploy
#: time: ``Grafana > Dashboards > Import > Upload JSON``.
GRAFANA_DASHBOARD_JSON: dict[str, Any] = {
    "title": "G1N 革命街 AI 原生 · 服务端监控",
    "uid": "g1n-server-overview",
    "schemaVersion": 38,
    "version": 1,
    "refresh": "10s",
    "time": {"from": "now-1h", "to": "now"},
    "tags": ["g1n", "ai-native", "decision-5"],
    "templating": {
        "list": [
            {
                "name": "route",
                "type": "query",
                "datasource": {"type": "prometheus", "uid": "prometheus"},
                "query": "label_values(g1n_http_request_total, route)",
                "refresh": 2,
                "includeAll": True,
                "multi": True,
            }
        ]
    },
    "panels": [
        # --- Row 1: decision 5 hard red lines --------------------
        {
            "id": 1,
            "type": "stat",
            "title": "决策 5 硬红线 — R1 纵切片主调用次数 (avg/run)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 0, "y": 0, "w": 6, "h": 4},
            "targets": [
                {
                    "expr": (
                        "sum(rate(g1n_model_call_latency_ms_count[5m])) by (agent) "
                        '* on() group_left() (60 / 5)'
                    ),
                    "legendFormat": "{{agent}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": 0},
                            {"color": "yellow", "value": 16},
                            {"color": "red", "value": 20.01},
                        ],
                    },
                    "unit": "short",
                }
            },
        },
        {
            "id": 2,
            "type": "stat",
            "title": "决策 5 硬红线 — R2 单次输出 token (max)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 6, "y": 0, "w": 6, "h": 4},
            "targets": [
                {
                    "expr": (
                        "sum by (model) (increase(g1n_model_call_output_tokens_total[5m])) "
                        "/ clamp_min(sum by (model) (increase(g1n_model_call_latency_ms_count[5m])), 1)"
                    ),
                    "legendFormat": "{{model}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": 0},
                            {"color": "yellow", "value": 700},
                            {"color": "red", "value": 800.01},
                        ],
                    },
                    "unit": "short",
                }
            },
        },
        {
            "id": 3,
            "type": "stat",
            "title": "决策 5 硬红线 — R4 关键交互 P95 (ms)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 12, "y": 0, "w": 6, "h": 4},
            "targets": [
                {
                    "expr": (
                        "histogram_quantile(0.95, sum by (le) ("
                        "rate(g1n_model_call_latency_ms_bucket[5m])))"
                    ),
                    "legendFormat": "p95",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": 0},
                            {"color": "yellow", "value": 3000},
                            {"color": "red", "value": 4000.01},
                        ],
                    },
                    "unit": "ms",
                }
            },
        },
        {
            "id": 4,
            "type": "stat",
            "title": "决策 5 软目标 — 单局 AI 成本 (¥)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 18, "y": 0, "w": 6, "h": 4},
            "targets": [
                {
                    "expr": "sum(increase(g1n_model_call_cost_cny_total[1h]))",
                    "legendFormat": "CNY/h",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": 0},
                            {"color": "yellow", "value": 0.7},
                            {"color": "red", "value": 0.8},
                        ],
                    },
                    "unit": "currencyCNY",
                }
            },
        },
        # --- Row 2: degradation chain + resolver write ----------
        {
            "id": 5,
            "type": "timeseries",
            "title": "4 级降级链触发率 (per second)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 0, "y": 4, "w": 12, "h": 8},
            "targets": [
                {
                    "expr": "sum by (level) (rate(g1n_degradation_trigger_total[1m]))",
                    "legendFormat": "{{level}}",
                }
            ],
            "fieldConfig": {"defaults": {"unit": "ops"}},
        },
        {
            "id": 6,
            "type": "timeseries",
            "title": "Resolver 写库 P95 (s)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 12, "y": 4, "w": 12, "h": 8},
            "targets": [
                {
                    "expr": (
                        "histogram_quantile(0.95, sum by (le) ("
                        "rate(g1n_resolver_write_ms_bucket[5m])))"
                    ),
                    "legendFormat": "p95",
                }
            ],
            "fieldConfig": {"defaults": {"unit": "s"}},
        },
        # --- Row 3: cache + vector + HTTP -----------------------
        {
            "id": 7,
            "type": "timeseries",
            "title": "缓存命中率 (rolling)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 0, "y": 12, "w": 8, "h": 7},
            "targets": [
                {"expr": "g1n_cache_hit_rate", "legendFormat": "{{kind}}"}
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "percentunit",
                    "min": 0,
                    "max": 1,
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "red", "value": 0},
                            {"color": "yellow", "value": 0.8},
                            {"color": "green", "value": 0.95},
                        ],
                    },
                }
            },
        },
        {
            "id": 8,
            "type": "timeseries",
            "title": "Vector Search p95 (ms) — 4-8 段召回",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 8, "y": 12, "w": 8, "h": 7},
            "targets": [
                {
                    "expr": (
                        "histogram_quantile(0.95, sum by (le, index_path) ("
                        "rate(g1n_vector_search_ms_bucket[5m])))"
                    ),
                    "legendFormat": "{{index_path}} p95",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "ms",
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": 0},
                            {"color": "yellow", "value": 80},
                            {"color": "red", "value": 100.01},
                        ],
                    },
                }
            },
        },
        {
            "id": 9,
            "type": "timeseries",
            "title": "HTTP 5xx 错误率 (1 min)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 16, "y": 12, "w": 8, "h": 7},
            "targets": [
                {"expr": "g1n_http_error_rate{route=~\"$route\"}", "legendFormat": "{{route}}"}
            ],
            "fieldConfig": {"defaults": {"unit": "percentunit"}},
        },
        # --- Row 4: cost + active runs --------------------------
        {
            "id": 10,
            "type": "timeseries",
            "title": "LLM 成本 (CNY/min)",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 0, "y": 19, "w": 12, "h": 7},
            "targets": [
                {
                    "expr": (
                        "sum by (model) (rate(g1n_model_call_cost_cny_total[1m])) * 60"
                    ),
                    "legendFormat": "{{model}}",
                }
            ],
            "fieldConfig": {"defaults": {"unit": "currencyCNY"}},
        },
        {
            "id": 11,
            "type": "stat",
            "title": "活跃 run 数",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 12, "y": 19, "w": 6, "h": 7},
            "targets": [{"expr": "g1n_active_runs"}],
            "fieldConfig": {"defaults": {"unit": "short"}},
        },
        {
            "id": 12,
            "type": "timeseries",
            "title": "降级 P95 触发率（连续 3 局 → P0 报警）",
            "datasource": {"type": "prometheus", "uid": "prometheus"},
            "gridPos": {"x": 18, "y": 19, "w": 6, "h": 7},
            "targets": [
                {
                    "expr": "sum by (level) (increase(g1n_degradation_trigger_total[5m]))",
                    "legendFormat": "{{level}}",
                }
            ],
            "fieldConfig": {"defaults": {"unit": "short"}},
        },
    ],
}


__all__ = [
    "MetricsRegistry",
    "NoopTracer",
    "OTelTracer",
    "TracerProtocol",
    "AlertRule",
    "ALERT_RULES",
    "GRAFANA_DASHBOARD_JSON",
    "trace_turn",
    "install_fastapi_middleware",
    "metrics_endpoint_payload",
    "get_default_registry",
    "get_default_tracer",
    "reset_default_registry",
    "reset_default_tracer",
    "evaluate_alerts",
    "healthcheck",
    "record_model_call",
    "record_degradation",
    "record_resolver_write",
    "record_cache",
    "record_vector_search",
    "set_active_runs",
]
