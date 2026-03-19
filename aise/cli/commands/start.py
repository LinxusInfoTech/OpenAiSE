# aise/cli/commands/start.py
"""aise start command for daemon mode.

Requirements: 16.10, 21.6, 21.11
"""

import asyncio
import signal
import sys
import structlog
import typer
from typing import Optional

logger = structlog.get_logger(__name__)

start_app = typer.Typer(
    name="start",
    help="Start AiSE in daemon mode (webhook server + ticket worker)",
    invoke_without_command=True
)


@start_app.callback(invoke_without_command=True)
def start(
    ctx: typer.Context,
    host: str = typer.Option("0.0.0.0", help="Webhook server host"),
    port: Optional[int] = typer.Option(None, help="Webhook server port (default from config)"),
    mode: Optional[str] = typer.Option(None, help="Override operational mode"),
):
    """Start AiSE daemon: webhook server + ticket worker running concurrently."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        from aise.core.config import load_config
        config = load_config()
    except Exception as e:
        typer.echo(f"[error] Failed to load configuration: {e}", err=True)
        raise typer.Exit(1)

    effective_port = port or config.WEBHOOK_SERVER_PORT
    effective_mode = mode or config.AISE_MODE

    typer.echo(f"Starting AiSE daemon (mode={effective_mode}, port={effective_port})")
    typer.echo("Press Ctrl+C to stop.")

    try:
        asyncio.run(_run_daemon(config, host, effective_port, effective_mode))
    except KeyboardInterrupt:
        typer.echo("\nShutting down AiSE daemon...")
    except Exception as e:
        logger.error("daemon_startup_failed", error=str(e))
        typer.echo(f"[error] Daemon failed: {e}", err=True)
        raise typer.Exit(1)


async def _run_daemon(config, host: str, port: int, mode: str) -> None:
    """Run webhook server and ticket worker concurrently.

    Args:
        config: Loaded Config instance
        host: Bind host for webhook server
        port: Bind port for webhook server
        mode: Operational mode
    """
    import uvicorn
    from aise.ticket_system.webhook_server import app as webhook_app
    from aise.cli.commands.start import _ticket_worker

    # Configure uvicorn server (non-blocking)
    uvicorn_config = uvicorn.Config(
        app=webhook_app,
        host=host,
        port=port,
        log_level=config.LOG_LEVEL.lower(),
        access_log=False,  # structlog handles logging
    )
    server = uvicorn.Server(uvicorn_config)

    # Graceful shutdown event
    stop_event = asyncio.Event()

    def _handle_signal(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("daemon_starting", host=host, port=port, mode=mode)

    # Run both tasks concurrently
    webhook_task = asyncio.create_task(server.serve(), name="webhook_server")
    worker_task = asyncio.create_task(
        _ticket_worker(config, mode, stop_event),
        name="ticket_worker"
    )

    try:
        # Wait until stop event or a task crashes
        done, pending = await asyncio.wait(
            [webhook_task, worker_task],
            return_when=asyncio.FIRST_EXCEPTION
        )

        for task in done:
            if task.exception():
                logger.error("daemon_task_failed", task=task.get_name(), error=str(task.exception()))

    finally:
        stop_event.set()
        server.should_exit = True

        for task in [webhook_task, worker_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        logger.info("daemon_stopped")


async def _ticket_worker(config, mode: str, stop_event: asyncio.Event) -> None:
    """Background worker that polls Redis queue and processes tickets.

    Args:
        config: Loaded Config instance
        mode: Operational mode
        stop_event: Event to signal graceful shutdown
    """
    import json
    import redis.asyncio as aioredis
    from aise.ticket_system.processor import TicketProcessor
    from aise.ai_engine.router import LLMRouter

    logger.info("ticket_worker_starting", mode=mode)

    redis_client = aioredis.from_url(
        config.REDIS_URL,
        encoding="utf-8",
        decode_responses=True
    )

    llm_router = LLMRouter(config)

    try:
        while not stop_event.is_set():
            try:
                # Blocking pop with 2s timeout so we can check stop_event
                item = await redis_client.brpop("ticket_queue", timeout=2)

                if item is None:
                    continue  # Timeout — loop and check stop_event

                _, raw = item
                queue_item = json.loads(raw)
                ticket_id = queue_item.get("ticket_id")
                platform = queue_item.get("platform", "unknown")

                logger.info(
                    "ticket_dequeued",
                    ticket_id=ticket_id,
                    platform=platform
                )

                await _process_queued_ticket(
                    config=config,
                    llm_router=llm_router,
                    ticket_id=ticket_id,
                    platform=platform,
                    mode=mode,
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("ticket_worker_error", error=str(e))
                await asyncio.sleep(1)  # Back off on error

    finally:
        await redis_client.aclose()
        logger.info("ticket_worker_stopped")


async def _process_queued_ticket(
    config,
    llm_router,
    ticket_id: str,
    platform: str,
    mode: str,
) -> None:
    """Process a single ticket from the queue.

    Args:
        config: Config instance
        llm_router: LLM router
        ticket_id: Ticket identifier
        platform: Source platform (zendesk, freshdesk, slack)
        mode: Operational mode
    """
    from aise.ticket_system.processor import TicketProcessor

    try:
        ticket_provider = _get_ticket_provider(config, platform)
        if ticket_provider is None:
            logger.warning(
                "no_ticket_provider_for_platform",
                platform=platform,
                ticket_id=ticket_id
            )
            return

        processor = TicketProcessor(
            ticket_provider=ticket_provider,
            llm_router=llm_router,
            mode=mode,
        )

        auto_reply = (mode == "autonomous")
        await processor.process_ticket(ticket_id, auto_reply=auto_reply)

        logger.info(
            "ticket_processed",
            ticket_id=ticket_id,
            platform=platform,
            mode=mode
        )

    except Exception as e:
        logger.error(
            "ticket_processing_failed",
            ticket_id=ticket_id,
            platform=platform,
            error=str(e)
        )


def _get_ticket_provider(config, platform: str):
    """Instantiate the correct ticket provider for a platform.

    Args:
        config: Config instance
        platform: Platform name

    Returns:
        TicketProvider instance or None if not configured
    """
    try:
        if platform == "zendesk" and config.ZENDESK_SUBDOMAIN and config.ZENDESK_API_TOKEN:
            from aise.ticket_system.zendesk import ZendeskProvider
            return ZendeskProvider(config)
        elif platform == "freshdesk" and config.FRESHDESK_DOMAIN and config.FRESHDESK_API_KEY:
            from aise.ticket_system.freshdesk import FreshdeskProvider
            return FreshdeskProvider(config)
        else:
            return None
    except Exception as e:
        logger.error("ticket_provider_init_failed", platform=platform, error=str(e))
        return None
