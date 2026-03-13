# tests/unit/test_browser_actions.py
"""Unit tests for BrowserActions primitives."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from aise.browser_operator.actions import BrowserActions
from aise.core.exceptions import BrowserError


class TestBrowserActions:
    """Test BrowserActions class."""
    
    @pytest.fixture
    def actions(self):
        """Create BrowserActions instance."""
        return BrowserActions()
    
    @pytest.fixture
    def mock_page(self):
        """Create mock Playwright page."""
        page = AsyncMock()
        page.goto = AsyncMock()
        page.click = AsyncMock()
        page.fill = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.query_selector = AsyncMock()
        page.get_by_text = MagicMock()
        return page
    
    @pytest.mark.asyncio
    async def test_navigate_success(self, actions, mock_page):
        """Test successful navigation."""
        await actions.navigate(mock_page, "https://example.com")
        
        mock_page.goto.assert_called_once()
        call_args = mock_page.goto.call_args
        assert call_args[0][0] == "https://example.com"
        assert call_args[1]["timeout"] == BrowserActions.DEFAULT_TIMEOUT
        assert call_args[1]["wait_until"] == "domcontentloaded"
    
    @pytest.mark.asyncio
    async def test_navigate_with_custom_timeout(self, actions, mock_page):
        """Test navigation with custom timeout."""
        custom_timeout = 30000
        await actions.navigate(mock_page, "https://example.com", timeout=custom_timeout)
        
        call_args = mock_page.goto.call_args
        assert call_args[1]["timeout"] == custom_timeout
    
    @pytest.mark.asyncio
    async def test_navigate_retries_on_timeout(self, actions, mock_page):
        """Test navigation retries on timeout."""
        # Fail twice, succeed on third attempt
        mock_page.goto.side_effect = [
            PlaywrightTimeoutError("Timeout"),
            PlaywrightTimeoutError("Timeout"),
            None
        ]
        
        await actions.navigate(mock_page, "https://example.com", retries=3)
        
        # Should have been called 3 times
        assert mock_page.goto.call_count == 3
    
    @pytest.mark.asyncio
    async def test_navigate_raises_after_max_retries(self, actions, mock_page):
        """Test navigation raises BrowserError after max retries."""
        mock_page.goto.side_effect = PlaywrightTimeoutError("Timeout")
        
        with pytest.raises(BrowserError) as exc_info:
            await actions.navigate(mock_page, "https://example.com", retries=2)
        
        assert "timed out after 2 attempts" in str(exc_info.value)
        assert mock_page.goto.call_count == 2
    
    @pytest.mark.asyncio
    async def test_click_success(self, actions, mock_page):
        """Test successful click."""
        await actions.click(mock_page, "#submit-button")
        
        mock_page.click.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_click_falls_back_to_text(self, actions, mock_page):
        """Test click falls back to text selector."""
        # Selector click fails
        mock_page.click.side_effect = Exception("Selector not found")
        
        # Text-based click succeeds
        mock_text_locator = AsyncMock()
        mock_page.get_by_text.return_value = mock_text_locator
        
        await actions.click(mock_page, "Submit")
        
        # Should have tried selector first, then text
        mock_page.click.assert_called_once()
        mock_page.get_by_text.assert_called_once_with("Submit")
        mock_text_locator.click.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_click_retries_on_timeout(self, actions, mock_page):
        """Test click retries on timeout."""
        # Fail once, succeed on second attempt
        mock_page.click.side_effect = [
            PlaywrightTimeoutError("Timeout"),
            None
        ]
        
        await actions.click(mock_page, "#button", retries=2)
        
        assert mock_page.click.call_count == 2
    
    @pytest.mark.asyncio
    async def test_click_raises_after_max_retries(self, actions, mock_page):
        """Test click raises BrowserError after max retries."""
        mock_page.click.side_effect = PlaywrightTimeoutError("Timeout")
        mock_page.get_by_text.return_value.click.side_effect = PlaywrightTimeoutError("Timeout")
        
        with pytest.raises(BrowserError) as exc_info:
            await actions.click(mock_page, "#button", retries=2)
        
        assert "timed out after 2 attempts" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_fill_success(self, actions, mock_page):
        """Test successful fill."""
        await actions.fill(mock_page, "#email", "user@example.com")
        
        mock_page.fill.assert_called_once_with(
            "#email",
            "user@example.com",
            timeout=BrowserActions.DEFAULT_TIMEOUT
        )
    
    @pytest.mark.asyncio
    async def test_fill_retries_on_timeout(self, actions, mock_page):
        """Test fill retries on timeout."""
        # Fail once, succeed on second attempt
        mock_page.fill.side_effect = [
            PlaywrightTimeoutError("Timeout"),
            None
        ]
        
        await actions.fill(mock_page, "#input", "value", retries=2)
        
        assert mock_page.fill.call_count == 2
    
    @pytest.mark.asyncio
    async def test_fill_raises_after_max_retries(self, actions, mock_page):
        """Test fill raises BrowserError after max retries."""
        mock_page.fill.side_effect = PlaywrightTimeoutError("Timeout")
        
        with pytest.raises(BrowserError) as exc_info:
            await actions.fill(mock_page, "#input", "value", retries=2)
        
        assert "timed out after 2 attempts" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_wait_for_selector_success(self, actions, mock_page):
        """Test successful wait for selector."""
        await actions.wait_for_selector(mock_page, "#content")
        
        mock_page.wait_for_selector.assert_called_once_with(
            "#content",
            timeout=BrowserActions.DEFAULT_TIMEOUT
        )
    
    @pytest.mark.asyncio
    async def test_wait_for_selector_retries_on_timeout(self, actions, mock_page):
        """Test wait_for_selector retries on timeout."""
        # Fail once, succeed on second attempt
        mock_page.wait_for_selector.side_effect = [
            PlaywrightTimeoutError("Timeout"),
            None
        ]
        
        await actions.wait_for_selector(mock_page, "#element", retries=2)
        
        assert mock_page.wait_for_selector.call_count == 2
    
    @pytest.mark.asyncio
    async def test_wait_for_selector_raises_after_max_retries(self, actions, mock_page):
        """Test wait_for_selector raises BrowserError after max retries."""
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Timeout")
        
        with pytest.raises(BrowserError) as exc_info:
            await actions.wait_for_selector(mock_page, "#element", retries=2)
        
        assert "timed out after 2 attempts" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_text_success(self, actions, mock_page):
        """Test successful get_text."""
        mock_element = AsyncMock()
        mock_element.text_content = AsyncMock(return_value="  Hello World  ")
        mock_page.query_selector.return_value = mock_element
        
        text = await actions.get_text(mock_page, "#content")
        
        assert text == "Hello World"  # Should be stripped
        mock_page.wait_for_selector.assert_called_once()
        mock_page.query_selector.assert_called_once_with("#content")
    
    @pytest.mark.asyncio
    async def test_get_text_returns_empty_string_for_none(self, actions, mock_page):
        """Test get_text returns empty string when text_content is None."""
        mock_element = AsyncMock()
        mock_element.text_content = AsyncMock(return_value=None)
        mock_page.query_selector.return_value = mock_element
        
        text = await actions.get_text(mock_page, "#content")
        
        assert text == ""
    
    @pytest.mark.asyncio
    async def test_get_text_raises_when_element_not_found(self, actions, mock_page):
        """Test get_text raises BrowserError when element not found."""
        mock_page.query_selector.return_value = None
        
        with pytest.raises(BrowserError) as exc_info:
            await actions.get_text(mock_page, "#missing")
        
        assert "not found" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_get_text_retries_on_timeout(self, actions, mock_page):
        """Test get_text retries on timeout."""
        mock_element = AsyncMock()
        mock_element.text_content = AsyncMock(return_value="Success")
        
        # Fail once, succeed on second attempt
        mock_page.wait_for_selector.side_effect = [
            PlaywrightTimeoutError("Timeout"),
            None
        ]
        mock_page.query_selector.return_value = mock_element
        
        text = await actions.get_text(mock_page, "#content", retries=2)
        
        assert text == "Success"
        assert mock_page.wait_for_selector.call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_text_raises_after_max_retries(self, actions, mock_page):
        """Test get_text raises BrowserError after max retries."""
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Timeout")
        
        with pytest.raises(BrowserError) as exc_info:
            await actions.get_text(mock_page, "#content", retries=2)
        
        assert "timed out after 2 attempts" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_operation_timeout_enforcement(self, actions, mock_page):
        """Test that 60-second timeout is enforced by default."""
        await actions.navigate(mock_page, "https://example.com")
        
        # Verify default timeout is 60 seconds (60000 ms)
        call_args = mock_page.goto.call_args
        assert call_args[1]["timeout"] == 60000
    
    @pytest.mark.asyncio
    async def test_error_handling_logs_errors(self, actions, mock_page):
        """Test that errors are properly logged."""
        mock_page.goto.side_effect = Exception("Network error")
        
        with pytest.raises(BrowserError):
            await actions.navigate(mock_page, "https://example.com", retries=1)
        
        # Error should have been raised after retries exhausted
        assert mock_page.goto.call_count == 1
