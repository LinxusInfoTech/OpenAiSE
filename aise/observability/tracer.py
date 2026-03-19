# aise/observability/tracer.py
"""OpenTelemetry distributed tracing configuration and instrumentation."""

import re
from contextlib import contextmanager
from typing import Optional, Dict, Any, Generator

import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Span, Status, StatusCode

logger = structlog.get_logger(__name__)

# PII patterns for redaction
_PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL]'),
    (re.compile(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b'), '[PHONE]'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[IP]'),
    (re.compile(r'\b(?:sk-|sk-ant-|AKIA)[A-Za-z0-9]{16,}\b'), '[API_KEY]'),
]

_tracer_provider: Optional[TracerProvider] = None


def redact_pii(value: str) -> str:
    """Redact PII from a string value.

    Args:
        value: String that may contain PII

    Returns:
        String with PII replaced by placeholders
    """
    if not isinstance(value, str):
        return value
    for pattern, replacement in _PII_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact_attributes(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Redact PII from span attributes dict.

    Args:
        attributes: Span attributes

    Returns:
        Attributes with PII redacted
    """
    return {k: redact_pii(str(v)) if isinstance(v, str) else v for k, v in attributes.items()}


def configure_tracing(
    service_name: str = "aise",
    otlp_endpoint: Optional[str] = None,
    use_console: bool = False,
) -> TracerProvider:
    """Configure OpenTelemetry tracing.

    Sets up a TracerProvider with either an OTLP exporter (when endpoint is
    provided) or a console exporter (for development/testing).

    Args:
        service_name: Service name for trace identification
        otlp_endpoint: OTLP gRPC endpoint (e.g. "http://localhost:4317")
        use_console: Force console exporter (useful for testing)

    Returns:
        Configured TracerProvider
    """
    global _tracer_provider

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint and not use_console:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        logger.info("tracing_configured_otlp", endpoint=otlp_endpoint)
    else:
        exporter = ConsoleSpanExporter()
        logger.info("tracing_configured_console")

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    return provider


def get_tracer(name: str = "aise") -> trace.Tracer:
    """Get a tracer instance.

    Args:
        name: Tracer name (typically module name)

    Returns:
        OpenTelemetry Tracer
    """
    return trace.get_tracer(name)


def shutdown_tracing() -> None:
    """Flush and shut down the tracer provider."""
    global _tracer_provider
    if _tracer_provider:
        _tracer_provider.shutdown()
        _tracer_provider = None
        logger.info("tracing_shutdown")


@contextmanager
def agent_span(
    tracer: trace.Tracer,
    operation: str,
    attributes: Optional[Dict[str, Any]] = None,
) -> Generator[Span, None, None]:
    """Context manager for agent operation spans.

    Automatically sets error status on exceptions and redacts PII from
    all span attributes.

    Args:
        tracer: OpenTelemetry tracer
        operation: Span name (e.g. "engineer_agent.diagnose")
        attributes: Optional span attributes (PII will be redacted)

    Yields:
        Active Span
    """
    safe_attrs = redact_attributes(attributes or {})
    with tracer.start_as_current_span(operation, attributes=safe_attrs) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def llm_span(
    tracer: trace.Tracer,
    provider: str,
    model: str,
    temperature: float = 0.7,
) -> Generator[Span, None, None]:
    """Context manager for LLM call spans.

    Args:
        tracer: OpenTelemetry tracer
        provider: LLM provider name (e.g. "anthropic")
        model: Model name
        temperature: Sampling temperature

    Yields:
        Active Span
    """
    with tracer.start_as_current_span(
        f"llm.{provider}.complete",
        attributes={
            "llm.provider": provider,
            "llm.model": model,
            "llm.temperature": temperature,
        },
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise


@contextmanager
def tool_span(
    tracer: trace.Tracer,
    command: str,
) -> Generator[Span, None, None]:
    """Context manager for tool execution spans.

    Args:
        tracer: OpenTelemetry tracer
        command: Command being executed (PII will be redacted)

    Yields:
        Active Span
    """
    safe_command = redact_pii(command)
    tool_name = safe_command.split()[0] if safe_command else "unknown"
    with tracer.start_as_current_span(
        f"tool.{tool_name}",
        attributes={"tool.command": safe_command},
    ) as span:
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
