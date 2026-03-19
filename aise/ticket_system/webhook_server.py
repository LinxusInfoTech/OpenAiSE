# aise/ticket_system/webhook_server.py
"""FastAPI webhook receiver for ticket systems.

This module implements a webhook server that receives ticket notifications
from various support platforms (Zendesk, Freshdesk, Slack) and queues them
for processing by the AiSE system.

Features:
- HMAC signature verification for security (Requirement 19.3)
- Rate limiting on webhook endpoints (Requirement 19.4)
- IP allowlisting for webhook sources (Requirement 19.9)
- Redis-based ticket queue for async processing (Requirement 8.2)
- Immediate 200 OK response after queuing

Example usage:
    $ uvicorn aise.ticket_system.webhook_server:app --host 0.0.0.0 --port 8000
    
    Then configure webhooks in your ticket system to POST to:
    - http://localhost:8000/webhook/zendesk
    - http://localhost:8000/webhook/freshdesk
    - http://localhost:8000/webhook/slack
"""

import hmac
import hashlib
import json
import time
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
import structlog
import redis.asyncio as redis

from aise.core.config import get_config
from aise.core.exceptions import ValidationError
from aise.observability.metrics import (
    record_request,
    get_metrics_output,
    TICKET_QUEUE_DEPTH,
    TICKETS_PROCESSED,
)

logger = structlog.get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="AiSE Webhook Server",
    description="Webhook receiver for ticket system integrations",
    version="0.1.0"
)

# Global Redis client
_redis_client: Optional[redis.Redis] = None

# Rate limiting state (in-memory for simplicity)
_rate_limit_state: Dict[str, list] = {}


async def get_redis_client() -> redis.Redis:
    """Get or create Redis client.
    
    Returns:
        Redis client instance
    """
    global _redis_client
    
    if _redis_client is None:
        config = get_config()
        _redis_client = redis.from_url(
            config.REDIS_URL,
            encoding="utf-8",
            decode_responses=True
        )
    
    return _redis_client


def verify_hmac_signature(
    payload: bytes,
    signature: str,
    secret: str,
    algorithm: str = "sha256"
) -> bool:
    """Verify HMAC signature for webhook payload.
    
    Args:
        payload: Raw request body bytes
        signature: Signature from webhook header
        secret: Shared secret for HMAC verification
        algorithm: Hash algorithm (default: sha256)
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not secret:
        logger.warning("webhook_secret_not_configured")
        return False
    
    # Compute expected signature
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload,
        getattr(hashlib, algorithm)
    ).hexdigest()
    
    # Compare signatures (constant-time comparison)
    return hmac.compare_digest(signature, expected_signature)


def check_ip_allowlist(client_ip: str, allowed_ips: Optional[str]) -> bool:
    """Check if client IP is in allowlist.
    
    Args:
        client_ip: Client IP address
        allowed_ips: Comma-separated list of allowed IPs (or None to allow all)
    
    Returns:
        True if IP is allowed, False otherwise
    """
    if not allowed_ips:
        # No allowlist configured, allow all
        return True
    
    allowed_list = [ip.strip() for ip in allowed_ips.split(',')]
    return client_ip in allowed_list


async def check_rate_limit(
    endpoint: str,
    client_ip: str,
    max_requests: int = 100,
    window_seconds: int = 60
) -> bool:
    """Check if request is within rate limit.
    
    Simple in-memory rate limiting using sliding window.
    
    Args:
        endpoint: Endpoint being accessed
        client_ip: Client IP address
        max_requests: Maximum requests allowed in window
        window_seconds: Time window in seconds
    
    Returns:
        True if within rate limit, False if exceeded
    """
    key = f"{endpoint}:{client_ip}"
    current_time = time.time()
    
    # Initialize if not exists
    if key not in _rate_limit_state:
        _rate_limit_state[key] = []
    
    # Remove old timestamps outside the window
    _rate_limit_state[key] = [
        ts for ts in _rate_limit_state[key]
        if current_time - ts < window_seconds
    ]
    
    # Check if limit exceeded
    if len(_rate_limit_state[key]) >= max_requests:
        return False
    
    # Add current timestamp
    _rate_limit_state[key].append(current_time)
    return True


async def enqueue_ticket(ticket_id: str, platform: str, payload: Dict[str, Any]) -> None:
    """Enqueue ticket for processing.
    
    Args:
        ticket_id: Unique ticket identifier
        platform: Platform name (zendesk, freshdesk, slack)
        payload: Full webhook payload
    """
    redis_client = await get_redis_client()
    
    # Create queue item
    queue_item = {
        "ticket_id": ticket_id,
        "platform": platform,
        "payload": payload,
        "received_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Push to Redis queue (left push for FIFO with right pop)
    await redis_client.lpush("ticket_queue", json.dumps(queue_item))
    
    # Update queue depth metric
    queue_depth = await redis_client.llen("ticket_queue")
    TICKET_QUEUE_DEPTH.set(queue_depth)
    
    logger.info(
        "ticket_enqueued",
        ticket_id=ticket_id,
        platform=platform
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "aise-webhook-server",
        "version": "0.1.0",
        "endpoints": [
            "/webhook/zendesk",
            "/webhook/freshdesk",
            "/webhook/slack"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Check Redis connectivity
        redis_client = await get_redis_client()
        await redis_client.ping()
        
        return {
            "status": "healthy",
            "service": "aise-webhook-server",
            "redis": "connected"
        }
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "service": "aise-webhook-server",
                "error": str(e)
            }
        )


@app.get("/status")
async def status_check():
    """Detailed component health status endpoint.

    Delegates to the dashboard module for a full system health snapshot
    including component status and key operational metrics.

    Returns:
        JSON with per-component status, overall health, and metrics
    """
    from aise.observability.dashboard import get_system_status

    config = get_config()
    snapshot = await get_system_status(config)

    http_status_code = (
        status.HTTP_200_OK
        if snapshot["status"] == "healthy"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return JSONResponse(
        status_code=http_status_code,
        content={"service": "aise-webhook-server", **snapshot},
    )


@app.get("/metrics")
async def metrics_endpoint():
    """Expose Prometheus metrics."""
    from fastapi.responses import Response
    output, content_type = get_metrics_output()
    return Response(content=output, media_type=content_type)


@app.post("/webhook/zendesk")
async def zendesk_webhook(request: Request):
    """Receive Zendesk webhook notifications.
    
    Zendesk sends webhooks for ticket events (created, updated, etc.).
    This endpoint verifies the signature, checks rate limits, and queues
    the ticket for processing.
    
    Args:
        request: FastAPI request object
    
    Returns:
        200 OK with queued status
    
    Raises:
        HTTPException: If signature verification fails or rate limit exceeded
    """
    config = get_config()
    client_ip = request.client.host
    
    # Check IP allowlist
    if not check_ip_allowlist(client_ip, config.WEBHOOK_ALLOWED_IPS):
        logger.warning(
            "webhook_ip_blocked",
            platform="zendesk",
            client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP address not allowed"
        )
    
    # Check rate limit
    if not await check_rate_limit("zendesk", client_ip):
        logger.warning(
            "webhook_rate_limit_exceeded",
            platform="zendesk",
            client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
    
    # Get raw body for signature verification
    body = await request.body()
    
    # Verify HMAC signature if configured
    if config.WEBHOOK_SECRET:
        signature_header = request.headers.get("X-Zendesk-Webhook-Signature")
        
        if not signature_header:
            logger.warning(
                "webhook_missing_signature",
                platform="zendesk"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature"
            )
        
        if not verify_hmac_signature(body, signature_header, config.WEBHOOK_SECRET):
            logger.warning(
                "webhook_invalid_signature",
                platform="zendesk",
                client_ip=client_ip
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
    
    # Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("webhook_invalid_payload", platform="zendesk", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    # Extract ticket ID
    try:
        ticket_id = payload.get("ticket", {}).get("id")
        if not ticket_id:
            raise ValidationError("Missing ticket ID in payload")
        ticket_id = str(ticket_id)
    except Exception as e:
        logger.error("webhook_missing_ticket_id", platform="zendesk", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid ticket ID"
        )
    
    # Enqueue for processing
    await enqueue_ticket(ticket_id, "zendesk", payload)
    
    logger.info(
        "webhook_received",
        platform="zendesk",
        ticket_id=ticket_id,
        client_ip=client_ip
    )
    
    record_request("webhook_zendesk", "success", 0.0)
    
    return {
        "status": "queued",
        "ticket_id": ticket_id,
        "platform": "zendesk"
    }


@app.post("/webhook/freshdesk")
async def freshdesk_webhook(request: Request):
    """Receive Freshdesk webhook notifications.
    
    Freshdesk sends webhooks for ticket events (created, updated, etc.).
    This endpoint verifies the signature, checks rate limits, and queues
    the ticket for processing.
    
    Args:
        request: FastAPI request object
    
    Returns:
        200 OK with queued status
    
    Raises:
        HTTPException: If signature verification fails or rate limit exceeded
    """
    config = get_config()
    client_ip = request.client.host
    
    # Check IP allowlist
    if not check_ip_allowlist(client_ip, config.WEBHOOK_ALLOWED_IPS):
        logger.warning(
            "webhook_ip_blocked",
            platform="freshdesk",
            client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP address not allowed"
        )
    
    # Check rate limit
    if not await check_rate_limit("freshdesk", client_ip):
        logger.warning(
            "webhook_rate_limit_exceeded",
            platform="freshdesk",
            client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
    
    # Get raw body for signature verification
    body = await request.body()
    
    # Verify HMAC signature if configured
    if config.WEBHOOK_SECRET:
        signature_header = request.headers.get("X-Freshdesk-Webhook-Signature")
        
        if not signature_header:
            logger.warning(
                "webhook_missing_signature",
                platform="freshdesk"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature"
            )
        
        if not verify_hmac_signature(body, signature_header, config.WEBHOOK_SECRET):
            logger.warning(
                "webhook_invalid_signature",
                platform="freshdesk",
                client_ip=client_ip
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
    
    # Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("webhook_invalid_payload", platform="freshdesk", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    # Extract ticket ID
    try:
        ticket_id = payload.get("ticket_id") or payload.get("id")
        if not ticket_id:
            raise ValidationError("Missing ticket ID in payload")
        ticket_id = str(ticket_id)
    except Exception as e:
        logger.error("webhook_missing_ticket_id", platform="freshdesk", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid ticket ID"
        )
    
    # Enqueue for processing
    await enqueue_ticket(ticket_id, "freshdesk", payload)
    
    logger.info(
        "webhook_received",
        platform="freshdesk",
        ticket_id=ticket_id,
        client_ip=client_ip
    )
    
    record_request("webhook_freshdesk", "success", 0.0)
    
    return {
        "status": "queued",
        "ticket_id": ticket_id,
        "platform": "freshdesk"
    }


@app.post("/webhook/slack")
async def slack_webhook(request: Request):
    """Receive Slack webhook notifications.
    
    Slack sends webhooks for message events in channels where the bot is present.
    This endpoint verifies the signature, checks rate limits, and queues
    the message for processing.
    
    Args:
        request: FastAPI request object
    
    Returns:
        200 OK with queued status
    
    Raises:
        HTTPException: If signature verification fails or rate limit exceeded
    """
    config = get_config()
    client_ip = request.client.host
    
    # Check IP allowlist
    if not check_ip_allowlist(client_ip, config.WEBHOOK_ALLOWED_IPS):
        logger.warning(
            "webhook_ip_blocked",
            platform="slack",
            client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IP address not allowed"
        )
    
    # Check rate limit
    if not await check_rate_limit("slack", client_ip):
        logger.warning(
            "webhook_rate_limit_exceeded",
            platform="slack",
            client_ip=client_ip
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded"
        )
    
    # Get raw body for signature verification
    body = await request.body()
    
    # Parse payload first to check for URL verification
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("webhook_invalid_payload", platform="slack", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    
    # Handle Slack URL verification challenge (no signature required)
    if payload.get("type") == "url_verification":
        logger.info("slack_url_verification_challenge")
        return {"challenge": payload.get("challenge")}
    
    # Verify Slack signature if configured
    if config.SLACK_SIGNING_SECRET:
        # Slack uses a different signature format: v0=<signature>
        signature_header = request.headers.get("X-Slack-Signature")
        timestamp_header = request.headers.get("X-Slack-Request-Timestamp")
        
        if not signature_header or not timestamp_header:
            logger.warning(
                "webhook_missing_signature",
                platform="slack"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing webhook signature or timestamp"
            )
        
        # Check timestamp to prevent replay attacks (within 5 minutes)
        current_time = int(time.time())
        request_time = int(timestamp_header)
        if abs(current_time - request_time) > 300:
            logger.warning(
                "webhook_timestamp_expired",
                platform="slack",
                client_ip=client_ip
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request timestamp too old"
            )
        
        # Compute Slack signature
        sig_basestring = f"v0:{timestamp_header}:{body.decode('utf-8')}"
        expected_signature = 'v0=' + hmac.new(
            config.SLACK_SIGNING_SECRET.encode('utf-8'),
            sig_basestring.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature_header, expected_signature):
            logger.warning(
                "webhook_invalid_signature",
                platform="slack",
                client_ip=client_ip
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )
    
    # Extract message/event ID
    try:
        event = payload.get("event", {})
        # Use channel + timestamp as unique ID for Slack messages
        channel_id = event.get("channel")
        ts = event.get("ts")
        
        if not channel_id or not ts:
            raise ValidationError("Missing channel or timestamp in payload")
        
        ticket_id = f"{channel_id}:{ts}"
    except Exception as e:
        logger.error("webhook_missing_event_id", platform="slack", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid event data"
        )
    
    # Enqueue for processing
    await enqueue_ticket(ticket_id, "slack", payload)
    
    logger.info(
        "webhook_received",
        platform="slack",
        ticket_id=ticket_id,
        client_ip=client_ip
    )
    
    record_request("webhook_slack", "success", 0.0)
    
    return {
        "status": "queued",
        "ticket_id": ticket_id,
        "platform": "slack"
    }


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown.
    
    Note: on_event is deprecated in FastAPI. This should be migrated to
    lifespan event handlers in a future update.
    """
    global _redis_client
    
    if _redis_client:
        await _redis_client.close()
        logger.info("redis_connection_closed")
