# aise/observability/langsmith.py
"""LangSmith integration for LLM observability.

Configures LangSmith tracing for LangChain/LangGraph calls and provides
helpers to tag runs with ticket_id, mode, and user_id metadata.
"""

import os
from typing import Optional, Dict, Any
import structlog

logger = structlog.get_logger(__name__)

_langsmith_enabled: bool = False


def configure_langsmith(
    api_key: Optional[str] = None,
    project: str = "aise",
    endpoint: Optional[str] = None,
) -> bool:
    """Configure LangSmith tracing.

    Sets the required environment variables that LangChain reads to enable
    LangSmith tracing automatically for all LangChain/LangGraph calls.

    Args:
        api_key: LangSmith API key. Falls back to LANGSMITH_API_KEY env var.
        project: LangSmith project name (default: "aise")
        endpoint: Optional custom LangSmith endpoint URL

    Returns:
        True if LangSmith was successfully configured, False otherwise
    """
    global _langsmith_enabled

    resolved_key = api_key or os.environ.get("LANGSMITH_API_KEY")

    if not resolved_key:
        logger.info("langsmith_not_configured", reason="no API key provided")
        _langsmith_enabled = False
        return False

    # LangChain reads these env vars to enable LangSmith tracing
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = resolved_key
    os.environ["LANGCHAIN_PROJECT"] = project

    if endpoint:
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint

    try:
        # Validate the key by importing the client
        from langsmith import Client
        client = Client(api_key=resolved_key)
        # Light connectivity check — list projects (raises on bad key)
        list(client.list_projects())
        _langsmith_enabled = True
        logger.info(
            "langsmith_configured",
            project=project,
            endpoint=endpoint or "https://api.smith.langchain.com",
        )
        return True
    except Exception as e:
        logger.warning("langsmith_configuration_failed", error=str(e))
        # Don't raise — LangSmith is optional observability
        _langsmith_enabled = False
        return False


def is_enabled() -> bool:
    """Return whether LangSmith tracing is currently enabled."""
    return _langsmith_enabled


def get_run_metadata(
    ticket_id: Optional[str] = None,
    mode: Optional[str] = None,
    user_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build LangSmith run metadata dict.

    Pass the returned dict as the ``metadata`` argument to LangChain
    ``invoke`` / ``ainvoke`` calls so that runs are tagged in LangSmith.

    Args:
        ticket_id: Support ticket identifier
        mode: Operational mode (interactive, approval, autonomous)
        user_id: Optional user identifier
        extra: Any additional key-value pairs to include

    Returns:
        Metadata dictionary suitable for LangChain run metadata
    """
    metadata: Dict[str, Any] = {}

    if ticket_id:
        metadata["ticket_id"] = ticket_id
    if mode:
        metadata["mode"] = mode
    if user_id:
        metadata["user_id"] = user_id
    if extra:
        metadata.update(extra)

    return metadata


def tag_run(tags: list[str]) -> list[str]:
    """Return a list of tags to attach to a LangSmith run.

    Args:
        tags: Base tags to include (e.g. ["engineer_agent", "diagnosis"])

    Returns:
        Tags list (passable as ``tags`` kwarg to LangChain calls)
    """
    return tags
