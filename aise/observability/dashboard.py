# aise/observability/dashboard.py
"""Status dashboard — reusable health-check and metrics summary module.

Provides get_system_status() which can be called from any FastAPI app
(e.g. webhook_server.py) or from the CLI to report component health and
key operational metrics.

Components checked:
- Redis (ping + queue depth)
- PostgreSQL (SELECT 1)
- ChromaDB (heartbeat endpoint)
- LLM provider (key/URL configured)

Key metrics surfaced:
- Tickets processed (from Prometheus counter)
- Tool execution success rate
- Average LLM latency (from histogram)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger(__name__)


async def _check_redis(redis_url: str) -> Dict[str, Any]:
    """Ping Redis and return queue depth."""
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(redis_url, encoding="utf-8", decode_responses=True)
        await client.ping()
        queue_depth = await client.llen("ticket_queue")
        await client.aclose()
        return {"status": "healthy", "queue_depth": queue_depth}
    except Exception as exc:
        logger.warning("dashboard_redis_check_failed", error=str(exc))
        return {"status": "unhealthy", "error": str(exc)}


async def _check_postgres(postgres_url: str) -> Dict[str, Any]:
    """Run a trivial query to verify PostgreSQL connectivity."""
    try:
        import asyncpg

        conn = await asyncpg.connect(postgres_url, timeout=5)
        await conn.fetchval("SELECT 1")
        await conn.close()
        return {"status": "healthy"}
    except Exception as exc:
        logger.warning("dashboard_postgres_check_failed", error=str(exc))
        return {"status": "unhealthy", "error": str(exc)}


async def _check_chromadb(host: str, port: int) -> Dict[str, Any]:
    """Hit the ChromaDB heartbeat endpoint."""
    try:
        import httpx

        url = f"http://{host}:{port}/api/v1/heartbeat"
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            return {"status": "healthy"}
        return {"status": "unhealthy", "http_status": resp.status_code}
    except Exception as exc:
        logger.warning("dashboard_chromadb_check_failed", error=str(exc))
        return {"status": "unhealthy", "error": str(exc)}


def _check_llm_provider(config: Any) -> Dict[str, Any]:
    """Check whether the configured LLM provider has credentials."""
    try:
        provider = config.LLM_PROVIDER
        has_key = bool(
            (provider == "anthropic" and config.ANTHROPIC_API_KEY)
            or (provider == "openai" and config.OPENAI_API_KEY)
            or (provider == "deepseek" and config.DEEPSEEK_API_KEY)
            or (provider == "ollama" and config.OLLAMA_BASE_URL)
        )
        return {
            "status": "configured" if has_key else "not_configured",
            "provider": provider,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _get_metrics_summary() -> Dict[str, Any]:
    """Pull key values from Prometheus counters/histograms.

    Returns best-effort summary — never raises.
    """
    summary: Dict[str, Any] = {}
    try:
        from prometheus_client import REGISTRY

        # Tickets processed
        tickets_success = 0.0
        tickets_failure = 0.0
        tool_success = 0.0
        tool_total = 0.0
        llm_duration_sum = 0.0
        llm_duration_count = 0.0

        for metric in REGISTRY.collect():
            name = metric.name
            for sample in metric.samples:
                if name == "aise_tickets_processed_total":
                    if sample.labels.get("status") == "success":
                        tickets_success += sample.value
                    elif sample.labels.get("status") == "failure":
                        tickets_failure += sample.value
                elif name == "aise_tool_executions_total":
                    tool_total += sample.value
                    if sample.labels.get("status") == "success":
                        tool_success += sample.value
                elif name == "aise_llm_duration_seconds_sum":
                    llm_duration_sum += sample.value
                elif name == "aise_llm_duration_seconds_count":
                    llm_duration_count += sample.value

        summary["tickets_processed"] = int(tickets_success + tickets_failure)
        summary["tickets_success"] = int(tickets_success)
        summary["tickets_failure"] = int(tickets_failure)

        if tool_total > 0:
            summary["tool_success_rate"] = round(tool_success / tool_total, 4)
        else:
            summary["tool_success_rate"] = None

        if llm_duration_count > 0:
            summary["avg_llm_latency_seconds"] = round(
                llm_duration_sum / llm_duration_count, 3
            )
        else:
            summary["avg_llm_latency_seconds"] = None

    except Exception as exc:
        logger.warning("dashboard_metrics_summary_failed", error=str(exc))

    return summary


async def get_system_status(config: Optional[Any] = None) -> Dict[str, Any]:
    """Return a full system health and metrics snapshot.

    Args:
        config: AiSE Config object. If None, loads via get_config().

    Returns:
        Dict with keys:
            status: "healthy" | "degraded"
            components: per-component health dicts
            metrics: key operational metrics
    """
    if config is None:
        from aise.core.config import get_config

        config = get_config()

    components: Dict[str, Any] = {}
    overall_healthy = True

    # Redis
    result = await _check_redis(config.REDIS_URL)
    components["redis"] = result
    if result["status"] != "healthy":
        overall_healthy = False

    # PostgreSQL
    result = await _check_postgres(config.POSTGRES_URL)
    components["postgres"] = result
    if result["status"] != "healthy":
        overall_healthy = False

    # ChromaDB
    result = await _check_chromadb(config.CHROMA_HOST, config.CHROMA_PORT)
    components["chromadb"] = result
    if result["status"] != "healthy":
        overall_healthy = False

    # LLM provider (non-fatal — just informational)
    components["llm_provider"] = _check_llm_provider(config)

    metrics = _get_metrics_summary()

    status_str = "healthy" if overall_healthy else "degraded"
    logger.info("dashboard_status_checked", status=status_str)

    return {
        "status": status_str,
        "components": components,
        "metrics": metrics,
    }
