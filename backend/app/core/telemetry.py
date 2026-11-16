"""OpenTelemetry setup.

Stdout is the only exporter when no OTLP endpoint and no Langfuse keys are set.
That stdout path drops SQLAlchemy spans so statement text does not hide the business cycle.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult

from app.core.config import Settings

logger = logging.getLogger(__name__)

_configured = False
_SQLALCHEMY_SCOPE = "opentelemetry.instrumentation.sqlalchemy"

_tasks = None
_import_rows = None
_import_duration = None
_questions_duration = None
_llm_latency = None
_llm_tokens = None
_nats_publish = None


class _DropSqlAlchemyExporter(SpanExporter):
    """Forward every span except automatic SQLAlchemy instrumentation."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Drop database statement spans and export the rest."""
        kept = [
            span
            for span in spans
            if not (span.instrumentation_scope and span.instrumentation_scope.name.startswith(_SQLALCHEMY_SCOPE))
        ]
        if not kept:
            return SpanExportResult.SUCCESS
        return self._inner.export(kept)

    def shutdown(self) -> None:
        """Shut down the inner exporter."""
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Flush the inner exporter."""
        return self._inner.force_flush(timeout_millis)


def reset_telemetry() -> None:
    """Allow a later configure_telemetry call. The process tracer provider is not replaced twice."""
    global _configured
    _configured = False


def configure_telemetry(
    settings: Settings,
    service_name: str,
    *,
    span_exporter: SpanExporter | None = None,
) -> None:
    """Install the tracer and meter providers.

    span_exporter replaces the normal destination. Tests pass an in-memory exporter.
    """
    global _configured
    global _tasks, _import_rows, _import_duration, _questions_duration, _llm_latency, _llm_tokens, _nats_publish
    if _configured:
        return
    _configured = True
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter, metric_readers = _destinations(settings, span_exporter)
    if span_exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=metric_readers))
    meter = metrics.get_meter("orders")
    _tasks = meter.create_counter("orders.tasks")
    _import_rows = meter.create_counter("orders.import.rows")
    _import_duration = meter.create_histogram("orders.import.duration", unit="ms")
    _questions_duration = meter.create_histogram("orders.questions.duration", unit="ms")
    _llm_latency = meter.create_histogram("orders.llm.latency", unit="ms")
    _llm_tokens = meter.create_counter("orders.llm.tokens")
    _nats_publish = meter.create_counter("orders.nats.publish")


def _destinations(
    settings: Settings,
    span_exporter: SpanExporter | None,
) -> tuple[SpanExporter, list[PeriodicExportingMetricReader]]:
    """Choose stdout, Langfuse, or an explicit OTLP endpoint."""
    if span_exporter is not None:
        return span_exporter, []
    endpoint, headers = _otlp_target(settings)
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        traces = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers)
        metric_exporter = OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", headers=headers)
        reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)
        return traces, [reader]
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter

    console = _DropSqlAlchemyExporter(ConsoleSpanExporter())
    reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=60000)
    return console, [reader]


def _otlp_target(settings: Settings) -> tuple[str, dict[str, str]]:
    """Return the OTLP base URL and headers. Empty URL means stdout."""
    if settings.otel_exporter_otlp_endpoint:
        return settings.otel_exporter_otlp_endpoint.rstrip("/"), {}
    if settings.langfuse_public_key and settings.langfuse_secret_key and settings.langfuse_host:
        token = base64.b64encode(
            f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
        ).decode()
        host = settings.langfuse_host.rstrip("/")
        return f"{host}/api/public/otel", {"Authorization": f"Basic {token}"}
    return "", {}


def tracer() -> trace.Tracer:
    """The process tracer. Spans are no-ops until configure_telemetry has run."""
    return trace.get_tracer("orders")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[trace.Span]:
    """Start a span and set only attributes that have a value."""
    with tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


def record_task(status: str) -> None:
    """Count one committed status change."""
    if _tasks is not None:
        _tasks.add(1, {"status": status})


def record_import_rows(outcome: str, count: int) -> None:
    """Count accepted, rejected, or duplicate rows."""
    if _import_rows is not None and count:
        _import_rows.add(count, {"outcome": outcome})


def record_import_duration(duration_ms: float) -> None:
    """Record how long an import took from claim to a terminal status."""
    if _import_duration is not None:
        _import_duration.record(duration_ms)


def record_question(duration_ms: float, *, success: bool) -> None:
    """Record one question call."""
    if _questions_duration is not None:
        _questions_duration.record(duration_ms, {"success": str(success).lower()})


def record_llm(duration_ms: float, *, model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Record a model call. Token counters stay at zero when the provider does not report them."""
    if _llm_latency is not None:
        _llm_latency.record(duration_ms, {"model": model})
    if _llm_tokens is not None and (input_tokens or output_tokens):
        _llm_tokens.add(input_tokens, {"direction": "input", "model": model})
        _llm_tokens.add(output_tokens, {"direction": "output", "model": model})


def record_publish(result: str) -> None:
    """Count one NATS publish. result is ok or error."""
    if _nats_publish is not None:
        _nats_publish.add(1, {"result": result})
