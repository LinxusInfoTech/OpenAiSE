# aise/observability/metrics.py
"""Prometheus metrics collection for AiSE.

Exposes a /metrics endpoint and provides counters, histograms, and gauges
for requests, LLM usage, tool executions, and system health.
"""

from typing import Optional
import structlog
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Request metrics
# ---------------------------------------------------------------------------

REQUEST_COUNT = Counter(
    "aise_requests_total",
    "Total number of requests by operation type",
    ["operation", "status"],
)

REQUEST_LATENCY = Histogram(
    "aise_request_duration_seconds",
    "Request latency in seconds",
    ["operation"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

ERROR_COUNT = Counter(
    "aise_errors_total",
    "Total number of errors by type",
    ["error_type"],
)

# ---------------------------------------------------------------------------
# LLM metrics
# ---------------------------------------------------------------------------

LLM_TOKEN_USAGE = Counter(
    "aise_llm_tokens_total",
    "Total LLM tokens used",
    ["provider", "model", "token_type"],  # token_type: prompt | completion
)

LLM_COST = Counter(
    "aise_llm_cost_usd_total",
    "Estimated total LLM cost in USD",
    ["provider", "model"],
)

LLM_LATENCY = Histogram(
    "aise_llm_duration_seconds",
    "LLM call latency in seconds",
    ["provider", "model"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

LLM_ERROR_COUNT = Counter(
    "aise_llm_errors_total",
    "Total LLM errors by provider",
    ["provider", "error_type"],
)

# ---------------------------------------------------------------------------
# Tool execution metrics
# ---------------------------------------------------------------------------

TOOL_EXECUTION_COUNT = Counter(
    "aise_tool_executions_total",
    "Total tool executions by tool type and status",
    ["tool", "status"],  # status: success | failure | forbidden | timeout
)

TOOL_EXECUTION_LATENCY = Histogram(
    "aise_tool_duration_seconds",
    "Tool execution latency in seconds",
    ["tool"],
    buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0],
)

# ---------------------------------------------------------------------------
# System health metrics
# ---------------------------------------------------------------------------

DB_POOL_CONNECTIONS = Gauge(
    "aise_db_pool_connections",
    "Database connection pool usage",
    ["state"],  # state: active | idle | waiting
)

REDIS_CACHE_OPS = Counter(
    "aise_redis_cache_ops_total",
    "Redis cache operations",
    ["operation", "result"],  # operation: get | set | delete; result: hit | miss | ok
)

VECTOR_STORE_QUERY_LATENCY = Histogram(
    "aise_vector_store_query_seconds",
    "Vector store query latency in seconds",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

TICKET_QUEUE_DEPTH = Gauge(
    "aise_ticket_queue_depth",
    "Number of tickets currently in the processing queue",
)

TICKETS_PROCESSED = Counter(
    "aise_tickets_processed_total",
    "Total tickets processed",
    ["status"],  # status: success | failure
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def record_request(operation: str, status: str, duration_seconds: float) -> None:
    """Record a request metric.

    Args:
        operation: Operation name (e.g. "ask", "ticket_process")
        status: "success" or "failure"
        duration_seconds: Duration of the request
    """
    REQUEST_COUNT.labels(operation=operation, status=status).inc()
    REQUEST_LATENCY.labels(operation=operation).observe(duration_seconds)


def record_llm_call(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_seconds: float,
    cost_usd: Optional[float] = None,
) -> None:
    """Record LLM call metrics.

    Args:
        provider: LLM provider name
        model: Model name
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        duration_seconds: Call duration
        cost_usd: Estimated cost in USD
    """
    LLM_TOKEN_USAGE.labels(provider=provider, model=model, token_type="prompt").inc(prompt_tokens)
    LLM_TOKEN_USAGE.labels(provider=provider, model=model, token_type="completion").inc(completion_tokens)
    LLM_LATENCY.labels(provider=provider, model=model).observe(duration_seconds)
    if cost_usd is not None:
        LLM_COST.labels(provider=provider, model=model).inc(cost_usd)


def record_llm_error(provider: str, error_type: str) -> None:
    """Record an LLM error.

    Args:
        provider: LLM provider name
        error_type: Type of error (e.g. "auth", "rate_limit", "timeout")
    """
    LLM_ERROR_COUNT.labels(provider=provider, error_type=error_type).inc()
    ERROR_COUNT.labels(error_type=f"llm_{error_type}").inc()


def record_tool_execution(tool: str, status: str, duration_seconds: float) -> None:
    """Record a tool execution metric.

    Args:
        tool: Tool name (e.g. "aws", "kubectl", "docker")
        status: "success", "failure", "forbidden", or "timeout"
        duration_seconds: Execution duration
    """
    TOOL_EXECUTION_COUNT.labels(tool=tool, status=status).inc()
    TOOL_EXECUTION_LATENCY.labels(tool=tool).observe(duration_seconds)


def record_cache_op(operation: str, result: str) -> None:
    """Record a Redis cache operation.

    Args:
        operation: "get", "set", or "delete"
        result: "hit", "miss", or "ok"
    """
    REDIS_CACHE_OPS.labels(operation=operation, result=result).inc()


def get_metrics_output() -> tuple[bytes, str]:
    """Generate Prometheus metrics output.

    Returns:
        Tuple of (metrics bytes, content type string)
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
