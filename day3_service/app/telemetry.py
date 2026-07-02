"""OpenTelemetry setup: instrument once, choose the backend by env var.

If OTEL_EXPORTER_OTLP_ENDPOINT is set (e.g. http://localhost:4318 for Jaeger
all-in-one), spans ship over OTLP/HTTP. If not, tracing is a no-op — the code
paths in loop.py still run, they just export nowhere. Swapping Jaeger for Azure
Application Insights is the azure-monitor-opentelemetry distro instead of this
exporter: one function, same spans (FUNDAMENTALS ch.10)."""
from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "devops-copilot-api"


def setup_tracing() -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return  # no-op tracer: spans are created but never exported
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(
        resource=Resource.create({"service.name": SERVICE_NAME})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces"))
    )
    trace.set_tracer_provider(provider)
