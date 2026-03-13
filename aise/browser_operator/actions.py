# aise/browser_operator/actions.py
"""Browser action primitives with error handling and retries."""

import asyncio
from typing import Optional
import structlog
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from aise.core.exceptions import BrowserError

logger = structlog.get_logger(__name__)


class BrowserActions:
    """
    Low-level browser action primitives with error handling and retries.
    
    Provides reusable browser operations with automatic retry logic,
    timeout enforcement, and comprehensive error handling.
    
    Requirements:
    - 11.6: Browser operations with error handling
    - 11.9: Support headless and headed modes via configuration
    """
    
    DEFAULT_TIMEOUT = 60000  # 60 seconds in milliseconds
    DEFAULT_RETRIES = 3
    RETRY_DELAY = 1.0  # seconds
    
    async def navigate(
        self,
        page: Page,
        url: str,
        timeout: Optional[int] = None,
        retries: int = DEFAULT_RETRIES
    ) -> None:
        """
        Navigate to URL with retry logic.
        
        Args:
            page: Playwright page instance
            url: Target URL to navigate to
            timeout: Navigation timeout in milliseconds (default: 60s)
            retries: Number of retry attempts on failure
            
        Raises:
            BrowserError: If navigation fails after all retries
            
        Requirements:
        - 11.6: Browser operations with error handling
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        
        for attempt in range(retries):
            try:
                logger.info(
                    "browser_navigate",
                    url=url,
                    attempt=attempt + 1,
                    timeout_ms=timeout
                )
                
                await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
                
                logger.info("browser_navigate_success", url=url)
                return
                
            except PlaywrightTimeoutError as e:
                logger.warning(
                    "browser_navigate_timeout",
                    url=url,
                    attempt=attempt + 1,
                    retries=retries,
                    error=str(e)
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Navigation to {url} timed out after {retries} attempts"
                    ) from e
                    
            except Exception as e:
                logger.error(
                    "browser_navigate_error",
                    url=url,
                    attempt=attempt + 1,
                    error=str(e),
                    error_type=type(e).__name__
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Navigation to {url} failed: {e}"
                    ) from e
    
    async def click(
        self,
        page: Page,
        selector_or_text: str,
        timeout: Optional[int] = None,
        retries: int = DEFAULT_RETRIES
    ) -> None:
        """
        Click element by selector or text with retry logic.
        
        Args:
            page: Playwright page instance
            selector_or_text: CSS selector or text content to click
            timeout: Click timeout in milliseconds (default: 60s)
            retries: Number of retry attempts on failure
            
        Raises:
            BrowserError: If click fails after all retries
            
        Requirements:
        - 11.6: Browser operations with error handling
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        
        for attempt in range(retries):
            try:
                logger.debug(
                    "browser_click",
                    selector=selector_or_text,
                    attempt=attempt + 1
                )
                
                # Try as selector first
                try:
                    await page.click(selector_or_text, timeout=timeout)
                except Exception:
                    # Fall back to text content
                    await page.get_by_text(selector_or_text).click(timeout=timeout)
                
                logger.debug("browser_click_success", selector=selector_or_text)
                return
                
            except PlaywrightTimeoutError as e:
                logger.warning(
                    "browser_click_timeout",
                    selector=selector_or_text,
                    attempt=attempt + 1,
                    retries=retries
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Click on '{selector_or_text}' timed out after {retries} attempts"
                    ) from e
                    
            except Exception as e:
                logger.error(
                    "browser_click_error",
                    selector=selector_or_text,
                    attempt=attempt + 1,
                    error=str(e),
                    error_type=type(e).__name__
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Click on '{selector_or_text}' failed: {e}"
                    ) from e
    
    async def fill(
        self,
        page: Page,
        selector: str,
        value: str,
        timeout: Optional[int] = None,
        retries: int = DEFAULT_RETRIES
    ) -> None:
        """
        Fill input field with retry logic.
        
        Args:
            page: Playwright page instance
            selector: CSS selector for input field
            value: Text value to fill
            timeout: Fill timeout in milliseconds (default: 60s)
            retries: Number of retry attempts on failure
            
        Raises:
            BrowserError: If fill fails after all retries
            
        Requirements:
        - 11.6: Browser operations with error handling
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        
        for attempt in range(retries):
            try:
                logger.debug(
                    "browser_fill",
                    selector=selector,
                    value_length=len(value),
                    attempt=attempt + 1
                )
                
                await page.fill(selector, value, timeout=timeout)
                
                logger.debug("browser_fill_success", selector=selector)
                return
                
            except PlaywrightTimeoutError as e:
                logger.warning(
                    "browser_fill_timeout",
                    selector=selector,
                    attempt=attempt + 1,
                    retries=retries
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Fill on '{selector}' timed out after {retries} attempts"
                    ) from e
                    
            except Exception as e:
                logger.error(
                    "browser_fill_error",
                    selector=selector,
                    attempt=attempt + 1,
                    error=str(e),
                    error_type=type(e).__name__
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Fill on '{selector}' failed: {e}"
                    ) from e
    
    async def wait_for_selector(
        self,
        page: Page,
        selector: str,
        timeout: Optional[int] = None,
        retries: int = DEFAULT_RETRIES
    ) -> None:
        """
        Wait for element to appear with retry logic.
        
        Args:
            page: Playwright page instance
            selector: CSS selector to wait for
            timeout: Wait timeout in milliseconds (default: 60s)
            retries: Number of retry attempts on failure
            
        Raises:
            BrowserError: If element doesn't appear after all retries
            
        Requirements:
        - 11.6: Browser operations with error handling
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        
        for attempt in range(retries):
            try:
                logger.debug(
                    "browser_wait_for_selector",
                    selector=selector,
                    attempt=attempt + 1,
                    timeout_ms=timeout
                )
                
                await page.wait_for_selector(selector, timeout=timeout)
                
                logger.debug("browser_wait_for_selector_success", selector=selector)
                return
                
            except PlaywrightTimeoutError as e:
                logger.warning(
                    "browser_wait_for_selector_timeout",
                    selector=selector,
                    attempt=attempt + 1,
                    retries=retries
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Wait for selector '{selector}' timed out after {retries} attempts"
                    ) from e
                    
            except Exception as e:
                logger.error(
                    "browser_wait_for_selector_error",
                    selector=selector,
                    attempt=attempt + 1,
                    error=str(e),
                    error_type=type(e).__name__
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Wait for selector '{selector}' failed: {e}"
                    ) from e
    
    async def get_text(
        self,
        page: Page,
        selector: str,
        timeout: Optional[int] = None,
        retries: int = DEFAULT_RETRIES
    ) -> str:
        """
        Get text content from element with retry logic.
        
        Args:
            page: Playwright page instance
            selector: CSS selector for element
            timeout: Operation timeout in milliseconds (default: 60s)
            retries: Number of retry attempts on failure
            
        Returns:
            str: Text content of the element
            
        Raises:
            BrowserError: If text retrieval fails after all retries
            
        Requirements:
        - 11.6: Browser operations with error handling
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        
        for attempt in range(retries):
            try:
                logger.debug(
                    "browser_get_text",
                    selector=selector,
                    attempt=attempt + 1
                )
                
                # Wait for element first
                await page.wait_for_selector(selector, timeout=timeout)
                
                # Get text content
                element = await page.query_selector(selector)
                if element is None:
                    raise BrowserError(f"Element '{selector}' not found")
                
                text = await element.text_content()
                if text is None:
                    text = ""
                
                logger.debug(
                    "browser_get_text_success",
                    selector=selector,
                    text_length=len(text)
                )
                return text.strip()
                
            except PlaywrightTimeoutError as e:
                logger.warning(
                    "browser_get_text_timeout",
                    selector=selector,
                    attempt=attempt + 1,
                    retries=retries
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Get text from '{selector}' timed out after {retries} attempts"
                    ) from e
                    
            except Exception as e:
                logger.error(
                    "browser_get_text_error",
                    selector=selector,
                    attempt=attempt + 1,
                    error=str(e),
                    error_type=type(e).__name__
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(self.RETRY_DELAY)
                else:
                    raise BrowserError(
                        f"Get text from '{selector}' failed: {e}"
                    ) from e
