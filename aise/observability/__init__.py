# aise/observability/__init__.py
"""Tracing, metrics, and monitoring."""

from aise.observability.dashboard import get_system_status
from aise.observability.metrics import (
    get_metrics_output,
    record_request,
    record_llm_call,
    record_llm_error,
    record_tool_execution,
    record_cache_op,
)
from aise.observability.tracer import (
    configure_tracing,
    get_tracer,
    shutdown_tracing,
    agent_span,
    llm_span,
    tool_span,
)
from aise.observability.langsmith import (
    configure_langsmith,
    is_enabled as langsmith_enabled,
    get_run_metadata,
)

__all__ = [
    "get_system_status",
    "get_metrics_output",
    "record_request",
    "record_llm_call",
    "record_llm_error",
    "record_tool_execution",
    "record_cache_op",
    "configure_tracing",
    "get_tracer",
    "shutdown_tracing",
    "agent_span",
    "llm_span",
    "tool_span",
    "configure_langsmith",
    "langsmith_enabled",
    "get_run_metadata",
]
