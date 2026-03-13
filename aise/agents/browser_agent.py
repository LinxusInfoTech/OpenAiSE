# aise/agents/browser_agent.py
"""Browser automation agent for ticket operations.

This module implements the BrowserAgent that orchestrates browser automation
for ticket operations when APIs are unavailable. It routes operations to
platform-specific drivers and provides fallback logic.

Requirements:
- 11.1: Browser automation as fallback when APIs unavailable
- 11.2: Automatic fallback when API fails and USE_BROWSER_FALLBACK=true
- 11.5: Capture screenshots for observability
- 11.8: Queue for retry if browser also fails
- 11.12: Only invoke when API fails and fallback enabled
"""

from typing import Dict, Any, Optional, Literal
import structlog
from playwright.async_api import Page

from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.zendesk_driver import ZendeskBrowserDriver
from aise.browser_operator.freshdesk_driver import FreshdeskBrowserDriver
from aise.core.config import get_config
from aise.core.exceptions import BrowserError, TicketAPIError

logger = structlog.get_logger(__name__)


class BrowserAgent:
    """
    High-level browser automation agent for ticket operations.
    
    Orchestrates browser automation across multiple platforms (Zendesk, Freshdesk)
    and provides fallback logic when ticket APIs fail.
    
    Requirements:
    - 11.1: Browser automation as fallback when APIs unavailable
    - 11.2: Automatic fallback when API fails and USE_BROWSER_FALLBACK=true
    - 11.5: Capture screenshots for observability
    - 11.6: Platform-specific drivers
    
    Example:
        >>> agent = BrowserAgent()
        >>> result = await agent.execute_action(
        ...     platform="zendesk",
        ...     action="reply",
        ...     params={"ticket_id": "123", "message": "Hello"}
        ... )
    """
    
    def __init__(self):
        """Initialize BrowserAgent with platform drivers."""
        self.config = get_config()
        self.session = BrowserSession()
        
        # Initialize platform-specific drivers
        self.drivers: Dict[str, Any] = {}
        
        # Initialize Zendesk driver if configured
        if self.config.ZENDESK_SUBDOMAIN or self.config.ZENDESK_URL:
            try:
                self.drivers["zendesk"] = ZendeskBrowserDriver()
                logger.info("zendesk_driver_initialized")
            except Exception as e:
                logger.warning("zendesk_driver_init_failed", error=str(e))
        
        # Initialize Freshdesk driver if configured
        if self.config.FRESHDESK_DOMAIN or self.config.FRESHDESK_URL:
            try:
                self.drivers["freshdesk"] = FreshdeskBrowserDriver()
                logger.info("freshdesk_driver_initialized")
            except Exception as e:
                logger.warning("freshdesk_driver_init_failed", error=str(e))
        
        logger.info(
            "browser_agent_initialized",
            platforms=list(self.drivers.keys()),
            fallback_enabled=self.config.USE_BROWSER_FALLBACK
        )
    
    async def execute_action(
        self,
        platform: Literal["zendesk", "freshdesk"],
        action: Literal["get", "reply", "close", "add_tags"],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute browser action on specified platform.
        
        Routes the action to the appropriate platform driver and handles
        authentication, navigation, and error recovery.
        
        Args:
            platform: Target platform ("zendesk" or "freshdesk")
            action: Action to perform ("get", "reply", "close", "add_tags")
            params: Action parameters (ticket_id, message, tags, etc.)
        
        Returns:
            Dictionary with action result and metadata
        
        Raises:
            BrowserError: If browser operation fails
            
        Requirements:
        - 11.1: Browser automation as fallback
        - 11.2: Route platform-specific operations
        - 11.5: Capture screenshots for observability
        
        Example:
            >>> result = await agent.execute_action(
            ...     platform="zendesk",
            ...     action="reply",
            ...     params={"ticket_id": "123", "message": "Hello"}
            ... )
        """
        logger.info(
            "browser_action_start",
            platform=platform,
            action=action,
            ticket_id=params.get("ticket_id")
        )
        
        # Check if platform driver is available
        if platform not in self.drivers:
            raise BrowserError(
                f"Platform '{platform}' not configured or driver not available",
                action=action
            )
        
        driver = self.drivers[platform]
        
        try:
            # Create session key for authenticated context caching
            session_key = f"{platform}:{self.config.ZENDESK_EMAIL if platform == 'zendesk' else self.config.FRESHDESK_DOMAIN}"
            
            # Use authenticated page with session caching
            async with self.session.authenticated_page(
                session_key=session_key,
                login_callback=lambda page: driver.login(page)
            ) as page:
                # Route to appropriate action handler
                if action == "get":
                    result = await self._handle_get(driver, page, params)
                elif action == "reply":
                    result = await self._handle_reply(driver, page, params)
                elif action == "close":
                    result = await self._handle_close(driver, page, params)
                elif action == "add_tags":
                    result = await self._handle_add_tags(driver, page, params)
                else:
                    raise BrowserError(f"Unknown action: {action}", action=action)
                
                logger.info(
                    "browser_action_complete",
                    platform=platform,
                    action=action,
                    ticket_id=params.get("ticket_id")
                )
                
                return result
        
        except Exception as e:
            logger.error(
                "browser_action_failed",
                platform=platform,
                action=action,
                ticket_id=params.get("ticket_id"),
                error=str(e),
                error_type=type(e).__name__
            )
            raise BrowserError(
                f"Browser action failed: {action} on {platform}: {str(e)}",
                action=action
            ) from e
    
    async def _handle_get(
        self,
        driver: Any,
        page: Page,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle 'get' action - retrieve ticket details.
        
        Args:
            driver: Platform-specific driver
            page: Playwright page instance
            params: Action parameters with ticket_id
        
        Returns:
            Dictionary with ticket data
        """
        ticket_id = params.get("ticket_id")
        if not ticket_id:
            raise BrowserError("ticket_id required for 'get' action", action="get")
        
        # Navigate to ticket
        await driver.open_ticket(page, ticket_id)
        
        # Read ticket body
        body = await driver.read_ticket_body(page)
        
        # Capture screenshot
        screenshot_path = await BrowserSession.screenshot(
            page,
            f"get_ticket_{ticket_id}"
        )
        
        return {
            "ticket_id": ticket_id,
            "body": body,
            "screenshot": screenshot_path,
            "success": True
        }
    
    async def _handle_reply(
        self,
        driver: Any,
        page: Page,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle 'reply' action - post reply to ticket.
        
        Args:
            driver: Platform-specific driver
            page: Playwright page instance
            params: Action parameters with ticket_id and message
        
        Returns:
            Dictionary with reply result
        """
        ticket_id = params.get("ticket_id")
        message = params.get("message")
        
        if not ticket_id or not message:
            raise BrowserError(
                "ticket_id and message required for 'reply' action",
                action="reply"
            )
        
        # Navigate to ticket
        await driver.open_ticket(page, ticket_id)
        
        # Submit reply
        await driver.submit_reply(page, message)
        
        # Capture screenshot
        screenshot_path = await BrowserSession.screenshot(
            page,
            f"reply_ticket_{ticket_id}"
        )
        
        return {
            "ticket_id": ticket_id,
            "message_length": len(message),
            "screenshot": screenshot_path,
            "success": True
        }
    
    async def _handle_close(
        self,
        driver: Any,
        page: Page,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle 'close' action - close ticket.
        
        Args:
            driver: Platform-specific driver
            page: Playwright page instance
            params: Action parameters with ticket_id
        
        Returns:
            Dictionary with close result
        """
        ticket_id = params.get("ticket_id")
        if not ticket_id:
            raise BrowserError("ticket_id required for 'close' action", action="close")
        
        # Navigate to ticket
        await driver.open_ticket(page, ticket_id)
        
        # Set ticket status to closed/solved
        await driver.set_ticket_status(page, "solved")
        
        # Capture screenshot
        screenshot_path = await BrowserSession.screenshot(
            page,
            f"close_ticket_{ticket_id}"
        )
        
        return {
            "ticket_id": ticket_id,
            "status": "solved",
            "screenshot": screenshot_path,
            "success": True
        }
    
    async def _handle_add_tags(
        self,
        driver: Any,
        page: Page,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Handle 'add_tags' action - add tags to ticket.
        
        Note: This is a placeholder as tag management via browser
        is complex and platform-specific. Consider using API for tags.
        
        Args:
            driver: Platform-specific driver
            page: Playwright page instance
            params: Action parameters with ticket_id and tags
        
        Returns:
            Dictionary with tag result
        """
        ticket_id = params.get("ticket_id")
        tags = params.get("tags", [])
        
        if not ticket_id or not tags:
            raise BrowserError(
                "ticket_id and tags required for 'add_tags' action",
                action="add_tags"
            )
        
        # Navigate to ticket
        await driver.open_ticket(page, ticket_id)
        
        # Note: Tag management via browser is complex and not implemented
        # in the current drivers. This would require platform-specific
        # UI interactions that are fragile and hard to maintain.
        # Recommend using API for tag operations when possible.
        
        logger.warning(
            "add_tags_via_browser_not_implemented",
            ticket_id=ticket_id,
            tags=tags
        )
        
        return {
            "ticket_id": ticket_id,
            "tags": tags,
            "success": False,
            "message": "Tag management via browser not implemented. Use API instead."
        }


async def should_use_browser_fallback(
    config: Any,
    api_error: Optional[Exception] = None
) -> bool:
    """
    Determine if browser fallback should be used.
    
    Args:
        config: Configuration object
        api_error: Optional API error that triggered fallback consideration
    
    Returns:
        True if browser fallback should be used, False otherwise
    
    Requirements:
    - 11.2: Only use browser fallback when USE_BROWSER_FALLBACK=true
    - 11.12: Only invoke when API fails and fallback enabled
    """
    # Check if browser fallback is enabled
    if not config.USE_BROWSER_FALLBACK:
        logger.debug("browser_fallback_disabled")
        return False
    
    # If no API error, don't use browser fallback
    if api_error is None:
        logger.debug("no_api_error_no_fallback")
        return False
    
    # Check if error is a ticket API error (not authentication or other errors)
    if isinstance(api_error, TicketAPIError):
        # Don't fallback for 404 errors (ticket not found)
        if hasattr(api_error, 'status_code') and api_error.status_code == 404:
            logger.debug("ticket_not_found_no_fallback", ticket_id=api_error.ticket_id)
            return False
        
        # Fallback for other API errors (5xx, network errors, etc.)
        logger.info(
            "browser_fallback_triggered",
            error_type=type(api_error).__name__,
            error=str(api_error)
        )
        return True
    
    # Don't fallback for other error types
    logger.debug("non_api_error_no_fallback", error_type=type(api_error).__name__)
    return False
