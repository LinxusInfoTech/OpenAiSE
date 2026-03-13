# aise/browser_operator/freshdesk_driver.py
"""Freshdesk browser automation driver."""

from typing import Optional
import structlog
from playwright.async_api import Page

from aise.browser_operator.actions import BrowserActions
from aise.browser_operator.browser import BrowserSession
from aise.core.config import get_config
from aise.core.exceptions import BrowserError

logger = structlog.get_logger(__name__)


class FreshdeskBrowserDriver:
    """
    Freshdesk-specific browser automation driver.
    
    Provides high-level operations for Freshdesk ticket management
    using browser automation primitives.
    
    Requirements:
    - 11.6: Platform-specific drivers for Freshdesk
    - 5.2: Freshdesk integration
    - 5.4: Browser fallback when APIs unavailable
    """
    
    def __init__(self, actions: Optional[BrowserActions] = None):
        """
        Initialize Freshdesk driver.
        
        Args:
            actions: BrowserActions instance (creates new if not provided)
        """
        self.actions = actions or BrowserActions()
        self.config = get_config()
        
        # Determine base URL
        if self.config.FRESHDESK_URL:
            self.base_url = self.config.FRESHDESK_URL.rstrip('/')
        elif self.config.FRESHDESK_DOMAIN:
            self.base_url = f"https://{self.config.FRESHDESK_DOMAIN}.freshdesk.com"
        else:
            raise BrowserError(
                "Freshdesk URL not configured. Set FRESHDESK_URL or FRESHDESK_DOMAIN."
            )
        
        logger.info("freshdesk_driver_initialized", base_url=self.base_url)
    
    async def login(
        self,
        page: Page,
        email: Optional[str] = None,
        password: Optional[str] = None
    ) -> None:
        """
        Login to Freshdesk.
        
        Args:
            page: Playwright page instance
            email: Freshdesk admin email (uses config if not provided)
            password: Freshdesk password (uses API key from config if not provided)
            
        Raises:
            BrowserError: If login fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.2: Freshdesk authentication
        """
        email = email or self.config.FRESHDESK_DOMAIN  # Use domain as username fallback
        password = password or self.config.FRESHDESK_API_KEY
        
        if not email or not password:
            raise BrowserError(
                "Freshdesk credentials not configured. Set FRESHDESK_DOMAIN and FRESHDESK_API_KEY."
            )
        
        try:
            logger.info("freshdesk_login_start", email=email)
            
            # Navigate to login page
            login_url = f"{self.base_url}/login"
            await self.actions.navigate(page, login_url)
            
            # Capture screenshot before login
            await BrowserSession.screenshot(page, "freshdesk_login_page")
            
            # Fill email field
            await self.actions.fill(page, 'input[name="user[email]"]', email)
            
            # Fill password field
            await self.actions.fill(page, 'input[name="user[password]"]', password)
            
            # Click sign in button
            await self.actions.click(page, 'button[type="submit"]')
            
            # Wait for navigation to complete (dashboard or helpdesk)
            await self.actions.wait_for_selector(page, '#global-nav', timeout=30000)
            
            # Capture screenshot after login
            await BrowserSession.screenshot(page, "freshdesk_logged_in")
            
            logger.info("freshdesk_login_success", email=email)
            
        except Exception as e:
            logger.error(
                "freshdesk_login_failed",
                email=email,
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "freshdesk_login_error")
            raise BrowserError(f"Freshdesk login failed: {e}") from e
    
    async def open_ticket(
        self,
        page: Page,
        ticket_id: str
    ) -> None:
        """
        Navigate to specific ticket.
        
        Args:
            page: Playwright page instance
            ticket_id: Freshdesk ticket ID
            
        Raises:
            BrowserError: If navigation fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.2: Freshdesk ticket navigation
        """
        try:
            logger.info("freshdesk_open_ticket", ticket_id=ticket_id)
            
            # Navigate to ticket URL
            ticket_url = f"{self.base_url}/a/tickets/{ticket_id}"
            await self.actions.navigate(page, ticket_url)
            
            # Wait for ticket content to load
            await self.actions.wait_for_selector(page, '#ticket-details', timeout=30000)
            
            # Capture screenshot
            await BrowserSession.screenshot(page, f"freshdesk_ticket_{ticket_id}")
            
            logger.info("freshdesk_ticket_opened", ticket_id=ticket_id)
            
        except Exception as e:
            logger.error(
                "freshdesk_open_ticket_failed",
                ticket_id=ticket_id,
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, f"freshdesk_ticket_{ticket_id}_error")
            raise BrowserError(f"Failed to open Freshdesk ticket {ticket_id}: {e}") from e
    
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
        - 5.2: Freshdesk ticket content extraction
        """
        try:
            logger.debug("freshdesk_read_ticket_body")
            
            # Wait for ticket details to be visible
            await self.actions.wait_for_selector(page, '#ticket-details')
            
            # Extract ticket body from the conversation thread
            # Freshdesk uses .thread-conv for conversation display
            body = await self.actions.get_text(page, '.thread-conv .thread-message-body')
            
            logger.info(
                "freshdesk_ticket_body_read",
                body_length=len(body)
            )
            
            return body
            
        except Exception as e:
            logger.error(
                "freshdesk_read_ticket_body_failed",
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "freshdesk_read_body_error")
            raise BrowserError(f"Failed to read Freshdesk ticket body: {e}") from e
    
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
        - 5.2: Freshdesk reply submission
        """
        try:
            logger.info(
                "freshdesk_submit_reply",
                message_length=len(message)
            )
            
            # Wait for reply editor to be available
            await self.actions.wait_for_selector(page, '#reply-editor')
            
            # Click to focus the editor
            await self.actions.click(page, '#reply-editor')
            
            # Fill reply text (Freshdesk uses contenteditable div)
            await page.evaluate(f"""
                document.querySelector('#reply-editor').innerHTML = `{message}`;
            """)
            
            # Capture screenshot before submit
            await BrowserSession.screenshot(page, "freshdesk_reply_before_submit")
            
            # Click submit button
            await self.actions.click(page, 'button[data-test-id="submit-reply"]')
            
            # Wait for submission to complete
            await page.wait_for_timeout(2000)  # Brief wait for submission
            
            # Capture screenshot after submit
            await BrowserSession.screenshot(page, "freshdesk_reply_submitted")
            
            logger.info("freshdesk_reply_submitted_success")
            
        except Exception as e:
            logger.error(
                "freshdesk_submit_reply_failed",
                message_length=len(message),
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "freshdesk_submit_reply_error")
            raise BrowserError(f"Failed to submit Freshdesk reply: {e}") from e
    
    async def set_ticket_status(
        self,
        page: Page,
        status: str
    ) -> None:
        """
        Update ticket status.
        
        Args:
            page: Playwright page instance
            status: Target status (open, pending, resolved, closed)
            
        Raises:
            BrowserError: If status update fails
            
        Requirements:
        - 11.6: Browser operations with error handling
        - 5.2: Freshdesk ticket status management
        """
        valid_statuses = ["open", "pending", "resolved", "closed"]
        if status.lower() not in valid_statuses:
            raise BrowserError(
                f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
            )
        
        try:
            logger.info("freshdesk_set_ticket_status", status=status)
            
            # Wait for status dropdown
            await self.actions.wait_for_selector(page, '#ticket-status-select')
            
            # Click status dropdown
            await self.actions.click(page, '#ticket-status-select')
            
            # Wait for dropdown menu to appear
            await page.wait_for_timeout(500)
            
            # Click the status option
            status_capitalized = status.capitalize()
            await self.actions.click(page, f'text="{status_capitalized}"')
            
            # Wait for status to update
            await page.wait_for_timeout(1000)
            
            # Capture screenshot
            await BrowserSession.screenshot(page, f"freshdesk_status_{status}")
            
            logger.info("freshdesk_status_updated", status=status)
            
        except Exception as e:
            logger.error(
                "freshdesk_set_ticket_status_failed",
                status=status,
                error=str(e),
                error_type=type(e).__name__
            )
            await BrowserSession.screenshot(page, "freshdesk_set_status_error")
            raise BrowserError(f"Failed to set Freshdesk ticket status to {status}: {e}") from e
