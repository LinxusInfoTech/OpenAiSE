# aise/ticket_system/zendesk.py
"""Zendesk API ticket provider implementation."""

import asyncio
from datetime import datetime
from typing import List, Optional
import httpx
import structlog

from aise.ticket_system.base import TicketProvider, Ticket, Message, TicketStatus
from aise.core.exceptions import TicketAPIError, TicketNotFoundError

logger = structlog.get_logger(__name__)


async def _retry_with_backoff(coro_fn, max_retries: int = 3, base_delay: float = 1.0):
    """Execute an async callable with exponential backoff retry.

    Args:
        coro_fn: Zero-argument async callable to retry
        max_retries: Maximum number of attempts (default 3)
        base_delay: Initial delay in seconds (doubles each retry)

    Returns:
        Result of coro_fn on success

    Raises:
        Last exception if all retries exhausted
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return await coro_fn()
        except TicketNotFoundError:
            raise  # Don't retry 404s
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "ticket_api_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=delay,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
    raise last_exc


class ZendeskProvider(TicketProvider):
    """Zendesk API v2 ticket provider.
    
    Implements the TicketProvider interface for Zendesk Support.
    Uses the Zendesk API v2 with API token authentication.
    
    Example:
        >>> provider = ZendeskProvider(
        ...     subdomain="mycompany",
        ...     email="admin@mycompany.com",
        ...     api_token="abc123..."
        ... )
        >>> tickets = await provider.list_open(limit=10)
    """
    
    def __init__(
        self,
        subdomain: str,
        email: str,
        api_token: str,
        timeout: int = 30
    ):
        """Initialize Zendesk provider.
        
        Args:
            subdomain: Zendesk subdomain (e.g., "mycompany" for mycompany.zendesk.com)
            email: Admin email for API authentication
            api_token: API token from Zendesk admin panel
            timeout: Request timeout in seconds (default: 30)
        """
        self.subdomain = subdomain
        self.email = email
        self.api_token = api_token
        self.timeout = timeout
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        
        # Create HTTP client with authentication
        self.client = httpx.AsyncClient(
            auth=(f"{email}/token", api_token),
            timeout=timeout,
            headers={"Content-Type": "application/json"}
        )
        
        logger.info("zendesk_provider_initialized", subdomain=subdomain)
    
    async def list_open(self, limit: int = 50) -> List[Ticket]:
        """List open tickets from Zendesk.
        
        Args:
            limit: Maximum number of tickets to return
        
        Returns:
            List of open Ticket objects
        
        Raises:
            TicketAPIError: If API request fails after retries
        """
        async def _do():
            logger.debug("listing_open_tickets", limit=limit)
            url = f"{self.base_url}/search.json"
            params = {
                "query": "type:ticket status<solved",
                "per_page": min(limit, 100),
                "sort_by": "updated_at",
                "sort_order": "desc"
            }
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            tickets = []
            for ticket_data in data.get("results", []):
                ticket = await self._parse_ticket(ticket_data)
                tickets.append(ticket)
            logger.info("open_tickets_listed", count=len(tickets))
            return tickets

        try:
            return await _retry_with_backoff(_do)
        except httpx.HTTPStatusError as e:
            logger.error("zendesk_api_error", status=e.response.status_code, error=str(e))
            raise TicketAPIError(f"Zendesk API error: {e.response.status_code}", provider="zendesk")
        except Exception as e:
            logger.error("list_open_failed", error=str(e))
            raise TicketAPIError(f"Failed to list open tickets: {str(e)}", provider="zendesk")
    
    async def get(self, ticket_id: str) -> Ticket:
        """Get ticket by ID with full thread.
        
        Args:
            ticket_id: Zendesk ticket ID
        
        Returns:
            Ticket object with complete message thread
        
        Raises:
            TicketNotFoundError: If ticket doesn't exist
            TicketAPIError: If API request fails
        """
        try:
            logger.debug("getting_ticket", ticket_id=ticket_id)
            
            # Get ticket details
            ticket_url = f"{self.base_url}/tickets/{ticket_id}.json"
            ticket_response = await self.client.get(ticket_url)
            
            if ticket_response.status_code == 404:
                raise TicketNotFoundError(f"Ticket not found: {ticket_id}")
            
            ticket_response.raise_for_status()
            ticket_data = ticket_response.json()["ticket"]
            
            # Get ticket comments (thread)
            comments_url = f"{self.base_url}/tickets/{ticket_id}/comments.json"
            comments_response = await self.client.get(comments_url)
            comments_response.raise_for_status()
            comments_data = comments_response.json()["comments"]
            
            # Parse ticket with thread
            ticket = await self._parse_ticket(ticket_data, comments_data)
            
            logger.info("ticket_retrieved", ticket_id=ticket_id, messages=len(ticket.thread))
            return ticket
            
        except TicketNotFoundError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("zendesk_api_error", status=e.response.status_code, error=str(e))
            raise TicketAPIError(
                f"Zendesk API error: {e.response.status_code}",
                provider="zendesk"
            )
        except Exception as e:
            logger.error("get_ticket_failed", ticket_id=ticket_id, error=str(e))
            raise TicketAPIError(f"Failed to get ticket: {str(e)}", provider="zendesk")
    
    async def reply(self, ticket_id: str, message: str) -> None:
        """Post reply to ticket with exponential backoff retry.
        
        Args:
            ticket_id: Zendesk ticket ID
            message: Reply message content (HTML or plain text)
        
        Raises:
            TicketNotFoundError: If ticket doesn't exist
            TicketAPIError: If API request fails after retries
        """
        async def _do():
            logger.debug("posting_reply", ticket_id=ticket_id)
            url = f"{self.base_url}/tickets/{ticket_id}.json"
            payload = {"ticket": {"comment": {"body": message, "public": True}}}
            response = await self.client.put(url, json=payload)
            if response.status_code == 404:
                raise TicketNotFoundError(f"Ticket not found: {ticket_id}")
            response.raise_for_status()
            logger.info("reply_posted", ticket_id=ticket_id)

        try:
            await _retry_with_backoff(_do)
        except TicketNotFoundError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("zendesk_api_error", status=e.response.status_code, error=str(e))
            raise TicketAPIError(f"Zendesk API error: {e.response.status_code}", provider="zendesk")
        except Exception as e:
            logger.error("reply_failed", ticket_id=ticket_id, error=str(e))
            raise TicketAPIError(f"Failed to post reply: {str(e)}", provider="zendesk")
    
    async def close(self, ticket_id: str) -> None:
        """Close ticket.
        
        Args:
            ticket_id: Zendesk ticket ID
        
        Raises:
            TicketNotFoundError: If ticket doesn't exist
            TicketAPIError: If API request fails
        """
        try:
            logger.debug("closing_ticket", ticket_id=ticket_id)
            
            url = f"{self.base_url}/tickets/{ticket_id}.json"
            payload = {
                "ticket": {
                    "status": "solved"
                }
            }
            
            response = await self.client.put(url, json=payload)
            
            if response.status_code == 404:
                raise TicketNotFoundError(f"Ticket not found: {ticket_id}")
            
            response.raise_for_status()
            
            logger.info("ticket_closed", ticket_id=ticket_id)
            
        except TicketNotFoundError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("zendesk_api_error", status=e.response.status_code, error=str(e))
            raise TicketAPIError(
                f"Zendesk API error: {e.response.status_code}",
                provider="zendesk"
            )
        except Exception as e:
            logger.error("close_failed", ticket_id=ticket_id, error=str(e))
            raise TicketAPIError(f"Failed to close ticket: {str(e)}", provider="zendesk")
    
    async def add_tags(self, ticket_id: str, tags: List[str]) -> None:
        """Add tags to ticket.
        
        Args:
            ticket_id: Zendesk ticket ID
            tags: List of tag names to add
        
        Raises:
            TicketNotFoundError: If ticket doesn't exist
            TicketAPIError: If API request fails
        """
        try:
            logger.debug("adding_tags", ticket_id=ticket_id, tags=tags)
            
            url = f"{self.base_url}/tickets/{ticket_id}.json"
            payload = {
                "ticket": {
                    "additional_tags": tags
                }
            }
            
            response = await self.client.put(url, json=payload)
            
            if response.status_code == 404:
                raise TicketNotFoundError(f"Ticket not found: {ticket_id}")
            
            response.raise_for_status()
            
            logger.info("tags_added", ticket_id=ticket_id, tags=tags)
            
        except TicketNotFoundError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error("zendesk_api_error", status=e.response.status_code, error=str(e))
            raise TicketAPIError(
                f"Zendesk API error: {e.response.status_code}",
                provider="zendesk"
            )
        except Exception as e:
            logger.error("add_tags_failed", ticket_id=ticket_id, error=str(e))
            raise TicketAPIError(f"Failed to add tags: {str(e)}", provider="zendesk")
    
    async def _parse_ticket(
        self,
        ticket_data: dict,
        comments_data: Optional[List[dict]] = None
    ) -> Ticket:
        """Parse Zendesk API response into Ticket object.
        
        Args:
            ticket_data: Ticket data from Zendesk API
            comments_data: Optional comments data for thread
        
        Returns:
            Ticket object
        """
        # Parse status
        status_map = {
            "new": TicketStatus.NEW,
            "open": TicketStatus.OPEN,
            "pending": TicketStatus.PENDING,
            "hold": TicketStatus.ON_HOLD,
            "solved": TicketStatus.SOLVED,
            "closed": TicketStatus.CLOSED
        }
        status = status_map.get(ticket_data.get("status", "open"), TicketStatus.OPEN)
        
        # Parse thread
        thread = []
        if comments_data:
            for comment in comments_data:
                message = Message(
                    id=str(comment["id"]),
                    author=comment.get("author_id", "unknown"),
                    body=comment.get("body", ""),
                    is_customer=not comment.get("public", True),
                    created_at=datetime.fromisoformat(
                        comment["created_at"].replace("Z", "+00:00")
                    )
                )
                thread.append(message)
        
        # Create ticket
        ticket = Ticket(
            id=str(ticket_data["id"]),
            subject=ticket_data.get("subject", ""),
            body=ticket_data.get("description", ""),
            customer_email=ticket_data.get("requester_id", "unknown"),
            status=status,
            tags=ticket_data.get("tags", []),
            created_at=datetime.fromisoformat(
                ticket_data["created_at"].replace("Z", "+00:00")
            ),
            updated_at=datetime.fromisoformat(
                ticket_data["updated_at"].replace("Z", "+00:00")
            ),
            thread=thread
        )
        
        return ticket
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
