# aise/browser_operator/zendesk_driver.py
"""Zendesk browser automation driver."""

from typing import Optional
import structlog
from playwright.async_api import Page

from aise.browser_operator.actions import BrowserActions
from aise.browser_operator.browser import BrowserSession
from aise.core.config import get_config
from aise.core.exceptions import BrowserError

logger = structlog.get_logger(__name__)


class ZendeskBrowserDriver:
    """
    Zendesk-specific browser automation driver.
    
    Provides high-level operations for Zendesk ticket management
    using browser automation primitives.
    
    Requirements:
    - 11.6: Platform-specific drivers for Zendesk
    - 5.1: Zendesk integration
    - 5.4: Browser fallback when APIs unavailable
    """
    
    def __init__(self, actions: Optional[BrowserActions] = None):
        """
        Initialize Zendesk driver.
        
        Args:
            actions: BrowserActions instance (creates new if not provided)
        """
        self.actions = actions or BrowserActions()
        self.config = get_config()
        
        # Determine base URL
        if self.config.ZENDESK_URL:
            self.base_url = self.config.ZENDESK_URL.rstrip('/')
        elif self.config.ZENDESK_SUBDOMAIN:
            self.base_url = f"https://{self.config.ZENDESK_SUBDOMAIN}.zendesk.com"
        else:
            raise BrowserError(
                "Zendesk URL not configured. Set ZENDESK_URL or ZENDESK_SUBDOMAIN."
            )
        
        logger.info("zendesk_driver_initialized", base_url=self.base_url)
    
    async def login(
        self,
        page: Page,
        email: Optional[str] = None,
        password: Optional[str] = None
    ) -> None:
        """
        Login to Zendesk.
        
        Args:
            page: Playwright page instance
            email: Zendesk admin email (uses config if not provided)
            password: Zendesk password (uses API token from config if not provided)
            
        Raises:
            BrowserError: If login fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.1: Zendesk authentication
        """
        email = email or self.config.ZENDESK_EMAIL
        password = password or self.config.ZENDESK_API_TOKEN
        
        if not email or not password:
            raise BrowserError(
                "Zendesk credentials not configured. Set ZENDESK_EMAIL and ZENDESK_API_TOKEN."
            )
        
        try:
            logger.info("zendesk_login_start", email=email)
            
            # Navigate to login page
            login_url = f"{self.base_url}/auth/v2/login"
            await self.actions.navigate(page, login_url)
            
            # Capture screenshot before login
            await BrowserSession.screenshot(page, "zendesk_login_page")
            
            # Fill email field
            await self.actions.fill(page, 'input[name="email"]', email)
            
            # Fill password field (API token for token-based auth)
            await self.actions.fill(page, 'input[name="password"]', password)
            
            # Click sign in button
            await self.actions.click(page, 'button[type="submit"]')
            
            # Wait for navigation to complete (dashboard or agent interface)
            await self.actions.wait_for_selector(page, '[data-garden-id="chrome.nav"]', timeout=30000)
            
            # Capture screenshot after login
            await BrowserSession.screenshot(page, "zendesk_logged_in")
            
            logger.info("zendesk_login_success", email=email)
            
        except Exception as e:
            logger.error(
                "zendesk_login_failed",
                email=email,
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "zendesk_login_error")
            raise BrowserError(f"Zendesk login failed: {e}") from e
    
    async def open_ticket(
        self,
        page: Page,
        ticket_id: str
    ) -> None:
        """
        Navigate to specific ticket.
        
        Args:
            page: Playwright page instance
            ticket_id: Zendesk ticket ID
            
        Raises:
            BrowserError: If navigation fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.1: Zendesk ticket navigation
        """
        try:
            logger.info("zendesk_open_ticket", ticket_id=ticket_id)
            
            # Navigate to ticket URL
            ticket_url = f"{self.base_url}/agent/tickets/{ticket_id}"
            await self.actions.navigate(page, ticket_url)
            
            # Wait for ticket content to load
            await self.actions.wait_for_selector(page, '[data-test-id="ticket-conversation"]', timeout=30000)
            
            # Capture screenshot
            await BrowserSession.screenshot(page, f"zendesk_ticket_{ticket_id}")
            
            logger.info("zendesk_ticket_opened", ticket_id=ticket_id)
            
        except Exception as e:
            logger.error(
                "zendesk_open_ticket_failed",
                ticket_id=ticket_id,
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, f"zendesk_ticket_{ticket_id}_error")
            raise BrowserError(f"Failed to open Zendesk ticket {ticket_id}: {e}") from e
    
    async def read_ticket_body(self, page: Page) -> str:
        """
        Extract ticket content from current page.
        
        Args:
            page: Playwright page instance
            
        Returns:
            str: Ticket body text
            
        Raises:
            BrowserError: If content extraction fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.1: Zendesk ticket content extraction
        """
        try:
            logger.debug("zendesk_read_ticket_body")
            
            # Wait for ticket conversation to be visible
            await self.actions.wait_for_selector(page, '[data-test-id="ticket-conversation"]')
            
            # Extract ticket body from the first comment (original ticket)
            # Zendesk uses data-test-id for ticket comments
            body = await self.actions.get_text(page, '[data-test-id="ticket-conversation"] [data-test-id="comment-body"]')
            
            logger.info(
                "zendesk_ticket_body_read",
                body_length=len(body)
            )
            
            return body
            
        except Exception as e:
            logger.error(
                "zendesk_read_ticket_body_failed",
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "zendesk_read_body_error")
            raise BrowserError(f"Failed to read Zendesk ticket body: {e}") from e
    
    async def submit_reply(
        self,
        page: Page,
        message: str
    ) -> None:
        """
        Post reply to ticket.
        
        Args:
            page: Playwright page instance
            message: Reply message text
            
        Raises:
            BrowserError: If reply submission fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.1: Zendesk reply submission
        """
        try:
            logger.info(
                "zendesk_submit_reply",
                message_length=len(message)
            )
            
            # Wait for reply editor to be available
            await self.actions.wait_for_selector(page, '[data-test-id="comment-input"]')
            
            # Fill reply text
            await self.actions.fill(page, '[data-test-id="comment-input"]', message)
            
            # Capture screenshot before submit
            await BrowserSession.screenshot(page, "zendesk_reply_before_submit")
            
            # Click submit button
            await self.actions.click(page, '[data-test-id="submit-button"]')
            
            # Wait for submission to complete (button becomes disabled or success message appears)
            await page.wait_for_timeout(2000)  # Brief wait for submission
            
            # Capture screenshot after submit
            await BrowserSession.screenshot(page, "zendesk_reply_submitted")
            
            logger.info("zendesk_reply_submitted_success")
            
        except Exception as e:
            logger.error(
                "zendesk_submit_reply_failed",
                message_length=len(message),
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "zendesk_submit_reply_error")
            raise BrowserError(f"Failed to submit Zendesk reply: {e}") from e
    
    async def set_ticket_status(
        self,
        page: Page,
        status: str
    ) -> None:
        """
        Update ticket status.
        
        Args:
            page: Playwright page instance
            status: Target status (open, pending, solved, closed)
            
        Raises:
            BrowserError: If status update fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.1: Zendesk ticket status management
        """
        valid_statuses = ["open", "pending", "solved", "closed"]
        if status.lower() not in valid_statuses:
            raise BrowserError(
                f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
            )
        
        try:
            logger.info("zendesk_set_ticket_status", status=status)
            
            # Wait for status dropdown
            await self.actions.wait_for_selector(page, '[data-test-id="ticket-status-select"]')
            
            # Click status dropdown
            await self.actions.click(page, '[data-test-id="ticket-status-select"]')
            
            # Wait for dropdown menu to appear
            await page.wait_for_timeout(500)
            
            # Click the status option
            await self.actions.click(page, f'[data-test-id="status-option-{status.lower()}"]')
            
            # Wait for status to update
            await page.wait_for_timeout(1000)
            
            # Capture screenshot
            await BrowserSession.screenshot(page, f"zendesk_status_{status}")
            
            logger.info("zendesk_status_updated", status=status)
            
        except Exception as e:
            logger.error(
                "zendesk_set_ticket_status_failed",
                status=status,
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "zendesk_set_status_error")
            raise BrowserError(f"Failed to set Zendesk ticket status to {status}: {e}") from e
