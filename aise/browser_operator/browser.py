# aise/browser_operator/browser.py
"""Playwright browser session management with singleton pattern."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, AsyncIterator, Dict
import structlog
from playwright.async_api import Browser, Page, BrowserContext, async_playwright, Playwright

from aise.core.config import get_config
from aise.core.exceptions import BrowserError

logger = structlog.get_logger(__name__)


class BrowserSession:
    """
    Singleton Playwright browser session manager.
    
    Manages browser lifecycle with session reuse and automatic timeout.
    Supports headless and headed modes via configuration.
    
    Requirements:
    - 11.1: Browser automation as fallback when APIs unavailable
    - 11.4: Browser sessions should be reused for subsequent operations
    - 11.7: Close browser context to free resources after operations
    - 11.9: Support headless and headed modes via configuration
    - 11.10: Terminate sessions idle for 30 minutes
    """
    
    _instance: Optional["BrowserSession"] = None
    _browser: Optional[Browser] = None
    _playwright: Optional[Playwright] = None
    _last_activity: Optional[datetime] = None
    _lock: asyncio.Lock = asyncio.Lock()
    _session_timeout: timedelta = timedelta(minutes=30)
    
    # Login session caching
    _cached_contexts: Dict[str, BrowserContext] = {}
    _context_timestamps: Dict[str, datetime] = {}
    _context_timeout: timedelta = timedelta(minutes=30)
    
    def __new__(cls) -> "BrowserSession":
        """Ensure only one instance exists (singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def get_browser(cls) -> Browser:
        """
        Get or create browser instance.
        
        Returns:
            Browser: Active Playwright browser instance
            
        Raises:
            BrowserError: If browser fails to launch
            
        Requirements:
        - 11.1: Use Playwright for browser automation
        - 11.4: Browser sessions should be reused for subsequent operations
        - 11.9: Support headless and headed modes via configuration
        - 11.10: Terminate sessions idle for 30 minutes
        """
        async with cls._lock:
            # Check if session has timed out
            if cls._browser is not None and cls._last_activity is not None:
                if datetime.now() - cls._last_activity > cls._session_timeout:
                    logger.info(
                        "browser_session_timeout",
                        idle_time=(datetime.now() - cls._last_activity).total_seconds()
                    )
                    await cls._terminate_session()
            
            # Create new browser if needed
            if cls._browser is None:
                try:
                    config = get_config()
                    
                    logger.info(
                        "launching_browser",
                        headless=config.BROWSER_HEADLESS
                    )
                    
                    cls._playwright = await async_playwright().start()
                    cls._browser = await cls._playwright.chromium.launch(
                        headless=config.BROWSER_HEADLESS
                    )
                    
                    logger.info("browser_launched_successfully")
                    
                except Exception as e:
                    logger.error(
                        "browser_launch_failed",
                        error=str(e),
                        error_type=type(e).__name__
                    )
                    raise BrowserError(f"Failed to launch browser: {e}") from e
            
            # Update last activity timestamp
            cls._last_activity = datetime.now()
            
            return cls._browser
    
    @classmethod
    async def _terminate_session(cls) -> None:
        """
        Terminate browser session and clean up resources.
        
        Requirements:
        - 11.7: Close browser context to free resources after operations
        - 11.10: Terminate sessions idle for 30 minutes
        """
        # Clean up cached contexts first
        await cls._clear_all_cached_contexts()
        
        if cls._browser is not None:
            try:
                logger.info("terminating_browser_session")
                await cls._browser.close()
                cls._browser = None
            except Exception as e:
                logger.warning(
                    "browser_close_error",
                    error=str(e)
                )
        
        if cls._playwright is not None:
            try:
                await cls._playwright.stop()
                cls._playwright = None
            except Exception as e:
                logger.warning(
                    "playwright_stop_error",
                    error=str(e)
                )
        
        cls._last_activity = None
    
    @classmethod
    @asynccontextmanager
    async def new_page(cls) -> AsyncIterator[Page]:
        """
        Context manager for isolated page contexts.
        
        Creates a new browser context and page, yields it for use,
        and automatically cleans up after the operation completes.
        
        Yields:
            Page: Isolated Playwright page instance
            
        Raises:
            BrowserError: If page creation fails
            
        Example:
            async with BrowserSession.new_page() as page:
                await page.goto("https://example.com")
                # ... perform operations ...
            # Context automatically cleaned up here
            
        Requirements:
        - 11.4: Browser sessions should be reused for subsequent operations
        - 11.7: Close browser context to free resources after operations
        """
        browser = await cls.get_browser()
        context = None
        page = None
        
        try:
            # Create new browser context (isolated cookies, storage, etc.)
            context = await browser.new_context()
            page = await context.new_page()
            
            logger.debug("browser_page_created")
            
            yield page
            
        except Exception as e:
            logger.error(
                "browser_page_error",
                error=str(e),
                error_type=type(e).__name__
            )
            raise BrowserError(f"Browser page operation failed: {e}") from e
            
        finally:
            # Clean up page and context
            if page is not None:
                try:
                    await page.close()
                    logger.debug("browser_page_closed")
                except Exception as e:
                    logger.warning("page_close_error", error=str(e))
            
            if context is not None:
                try:
                    await context.close()
                    logger.debug("browser_context_closed")
                except Exception as e:
                    logger.warning("context_close_error", error=str(e))
    
    @classmethod
    async def screenshot(cls, page: Page, label: str) -> str:
        """
        Capture and save screenshot for debugging.
        
        Args:
            page: Playwright page to capture
            label: Descriptive label for the screenshot
            
        Returns:
            str: Path to saved screenshot file
            
        Raises:
            BrowserError: If screenshot capture fails
            
        Requirements:
        - 11.5: Capture screenshots for debugging
        """
        try:
            # Create screenshots directory if it doesn't exist
            screenshots_dir = Path("./data/screenshots")
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename with timestamp and label
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
            filename = f"{timestamp}_{safe_label}.png"
            filepath = screenshots_dir / filename
            
            # Capture screenshot
            await page.screenshot(path=str(filepath), full_page=True)
            
            logger.info(
                "screenshot_captured",
                label=label,
                path=str(filepath)
            )
            
            return str(filepath)
            
        except Exception as e:
            logger.error(
                "screenshot_capture_failed",
                label=label,
                error=str(e)
            )
            raise BrowserError(f"Failed to capture screenshot: {e}") from e
    
    @classmethod
    async def get_cached_context(
        cls,
        session_key: str
    ) -> Optional[BrowserContext]:
        """
        Get cached authenticated browser context if available and not expired.
        
        Args:
            session_key: Unique identifier for the session (e.g., "zendesk:user@example.com")
            
        Returns:
            BrowserContext if cached and valid, None otherwise
            
        Requirements:
        - 11.10: Cache login sessions for 30 minutes
        """
        async with cls._lock:
            # Check if context exists
            if session_key not in cls._cached_contexts:
                logger.debug("cached_context_miss", session_key=session_key)
                return None
            
            # Check if context has expired
            timestamp = cls._context_timestamps.get(session_key)
            if timestamp is None or datetime.now() - timestamp > cls._context_timeout:
                logger.info(
                    "cached_context_expired",
                    session_key=session_key,
                    age_seconds=(datetime.now() - timestamp).total_seconds() if timestamp else None
                )
                await cls._clear_cached_context(session_key)
                return None
            
            logger.info(
                "cached_context_hit",
                session_key=session_key,
                age_seconds=(datetime.now() - timestamp).total_seconds()
            )
            return cls._cached_contexts[session_key]
    
    @classmethod
    async def cache_context(
        cls,
        session_key: str,
        context: BrowserContext
    ) -> None:
        """
        Cache an authenticated browser context for reuse.
        
        Args:
            session_key: Unique identifier for the session
            context: Authenticated browser context to cache
            
        Requirements:
        - 11.10: Cache login sessions for 30 minutes
        """
        async with cls._lock:
            cls._cached_contexts[session_key] = context
            cls._context_timestamps[session_key] = datetime.now()
            
            logger.info(
                "context_cached",
                session_key=session_key,
                total_cached=len(cls._cached_contexts)
            )
    
    @classmethod
    async def _clear_cached_context(cls, session_key: str) -> None:
        """
        Clear a specific cached context and clean up resources.
        
        Args:
            session_key: Session identifier to clear
            
        Requirements:
        - 11.10: Clear cookies and storage after timeout
        """
        if session_key in cls._cached_contexts:
            context = cls._cached_contexts[session_key]
            try:
                # Clear cookies and storage
                await context.clear_cookies()
                await context.clear_permissions()
                
                # Close the context
                await context.close()
                
                logger.info("cached_context_cleared", session_key=session_key)
            except Exception as e:
                logger.warning(
                    "cached_context_clear_error",
                    session_key=session_key,
                    error=str(e)
                )
            finally:
                del cls._cached_contexts[session_key]
                if session_key in cls._context_timestamps:
                    del cls._context_timestamps[session_key]
    
    @classmethod
    async def _clear_all_cached_contexts(cls) -> None:
        """
        Clear all cached contexts.
        
        Requirements:
        - 11.10: Clear cookies and storage after timeout
        """
        session_keys = list(cls._cached_contexts.keys())
        for session_key in session_keys:
            await cls._clear_cached_context(session_key)
        
        logger.info("all_cached_contexts_cleared")
    
    @classmethod
    @asynccontextmanager
    async def authenticated_page(
        cls,
        session_key: str,
        login_callback: Optional[callable] = None
    ) -> AsyncIterator[Page]:
        """
        Context manager for authenticated page with session caching.
        
        Reuses cached authenticated contexts when available, or creates
        a new one and caches it for future use.
        
        Args:
            session_key: Unique identifier for the session
            login_callback: Optional async function to perform login if needed.
                           Should accept (page: Page) and perform login actions.
        
        Yields:
            Page: Authenticated page instance
            
        Example:
            async def login(page):
                await page.goto("https://example.com/login")
                await page.fill("#email", "user@example.com")
                await page.fill("#password", "secret")
                await page.click("#submit")
            
            async with BrowserSession.authenticated_page("example:user", login) as page:
                # Page is already logged in
                await page.goto("https://example.com/dashboard")
        
        Requirements:
        - 11.10: Cache login sessions for 30 minutes
        - 11.10: Reuse authenticated sessions across operations
        """
        browser = await cls.get_browser()
        context = None
        page = None
        is_cached = False
        
        try:
            # Try to get cached context
            context = await cls.get_cached_context(session_key)
            
            if context is not None:
                # Use cached context
                is_cached = True
                page = await context.new_page()
                logger.debug("using_cached_authenticated_context", session_key=session_key)
            else:
                # Create new context
                context = await browser.new_context()
                page = await context.new_page()
                
                # Perform login if callback provided
                if login_callback is not None:
                    logger.info("performing_login", session_key=session_key)
                    await login_callback(page)
                    logger.info("login_completed", session_key=session_key)
                
                # Cache the authenticated context
                await cls.cache_context(session_key, context)
                logger.debug("created_and_cached_authenticated_context", session_key=session_key)
            
            yield page
            
        except Exception as e:
            logger.error(
                "authenticated_page_error",
                session_key=session_key,
                error=str(e),
                error_type=type(e).__name__
            )
            raise BrowserError(f"Authenticated page operation failed: {e}") from e
            
        finally:
            # Only close the page, not the context (it's cached)
            if page is not None:
                try:
                    await page.close()
                    logger.debug("authenticated_page_closed", session_key=session_key)
                except Exception as e:
                    logger.warning("authenticated_page_close_error", error=str(e))
            
            # If context was newly created and not cached (error occurred), clean it up
            if context is not None and not is_cached and session_key not in cls._cached_contexts:
                try:
                    await context.close()
                    logger.debug("uncached_context_closed")
                except Exception as e:
                    logger.warning("context_close_error", error=str(e))
