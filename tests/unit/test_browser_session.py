# tests/unit/test_browser_session.py
"""Unit tests for BrowserSession singleton."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from aise.browser_operator.browser import BrowserSession
from aise.core.exceptions import BrowserError


class TestBrowserSession:
    """Test BrowserSession singleton class."""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton state before each test."""
        BrowserSession._instance = None
        BrowserSession._browser = None
        BrowserSession._playwright = None
        BrowserSession._last_activity = None
        BrowserSession._cached_contexts = {}
        BrowserSession._context_timestamps = {}
        yield
        # Cleanup after test
        BrowserSession._instance = None
        BrowserSession._browser = None
        BrowserSession._playwright = None
        BrowserSession._last_activity = None
        BrowserSession._cached_contexts = {}
        BrowserSession._context_timestamps = {}
    
    def test_singleton_pattern(self):
        """Test that BrowserSession follows singleton pattern."""
        session1 = BrowserSession()
        session2 = BrowserSession()
        
        assert session1 is session2
        assert BrowserSession._instance is session1
    
    @pytest.mark.asyncio
    async def test_get_browser_creates_new_browser(self):
        """Test get_browser creates new browser instance."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_browser = AsyncMock()
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                browser = await BrowserSession.get_browser()
                
                assert browser is mock_browser
                assert BrowserSession._browser is mock_browser
                assert BrowserSession._playwright is mock_playwright
                assert BrowserSession._last_activity is not None
                
                # Verify browser was launched with correct settings
                mock_playwright.chromium.launch.assert_called_once_with(headless=True)
    
    @pytest.mark.asyncio
    async def test_get_browser_reuses_existing_browser(self):
        """Test get_browser reuses existing browser instance."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_browser = AsyncMock()
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                # First call creates browser
                browser1 = await BrowserSession.get_browser()
                
                # Second call should reuse browser
                browser2 = await BrowserSession.get_browser()
                
                assert browser1 is browser2
                # Launch should only be called once
                assert mock_playwright.chromium.launch.call_count == 1
    
    @pytest.mark.asyncio
    async def test_get_browser_terminates_timed_out_session(self):
        """Test get_browser terminates session after timeout."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_browser = AsyncMock()
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                # Create initial browser
                browser1 = await BrowserSession.get_browser()
                
                # Simulate timeout by setting last activity to 31 minutes ago
                BrowserSession._last_activity = datetime.now() - timedelta(minutes=31)
                
                # Next call should terminate old session and create new one
                browser2 = await BrowserSession.get_browser()
                
                # Browser should have been closed
                mock_browser.close.assert_called_once()
                mock_playwright.stop.assert_called_once()
                
                # New browser should be created
                assert mock_playwright.chromium.launch.call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_browser_raises_on_launch_failure(self):
        """Test get_browser raises BrowserError on launch failure."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(
            side_effect=Exception("Launch failed")
        )
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                with pytest.raises(BrowserError) as exc_info:
                    await BrowserSession.get_browser()
                
                assert "Failed to launch browser" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_new_page_context_manager(self):
        """Test new_page context manager creates and cleans up page."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                async with BrowserSession.new_page() as page:
                    assert page is mock_page
                    # Page should not be closed yet
                    mock_page.close.assert_not_called()
                    mock_context.close.assert_not_called()
                
                # After exiting context, page and context should be closed
                mock_page.close.assert_called_once()
                mock_context.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_new_page_cleans_up_on_error(self):
        """Test new_page cleans up resources even on error."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                with pytest.raises(BrowserError):
                    async with BrowserSession.new_page() as page:
                        # Simulate error during page operation
                        raise Exception("Page operation failed")
                
                # Resources should still be cleaned up
                mock_page.close.assert_called_once()
                mock_context.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_screenshot_captures_and_saves(self):
        """Test screenshot method captures and saves screenshot."""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock()
        
        filepath = await BrowserSession.screenshot(mock_page, "test_label")
        
        # Verify screenshot was captured
        mock_page.screenshot.assert_called_once()
        
        # Verify path contains label
        assert "test_label" in filepath
        assert filepath.endswith(".png")
        assert "data/screenshots" in filepath
    
    @pytest.mark.asyncio
    async def test_screenshot_raises_on_failure(self):
        """Test screenshot raises BrowserError on capture failure."""
        mock_page = AsyncMock()
        mock_page.screenshot = AsyncMock(side_effect=Exception("Screenshot failed"))
        
        with pytest.raises(BrowserError) as exc_info:
            await BrowserSession.screenshot(mock_page, "test_label")
        
        assert "Failed to capture screenshot" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_browser_launched_in_headed_mode(self):
        """Test browser can be launched in headed mode."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = False
        
        mock_browser = AsyncMock()
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                await BrowserSession.get_browser()
                
                # Verify browser was launched in headed mode
                mock_playwright.chromium.launch.assert_called_once_with(headless=False)

    @pytest.mark.asyncio
    async def test_get_cached_context_miss(self):
        """Test get_cached_context returns None when context not cached."""
        context = await BrowserSession.get_cached_context("test:session")
        
        assert context is None
    
    @pytest.mark.asyncio
    async def test_cache_context_stores_context(self):
        """Test cache_context stores context with timestamp."""
        mock_context = AsyncMock()
        
        await BrowserSession.cache_context("test:session", mock_context)
        
        assert "test:session" in BrowserSession._cached_contexts
        assert BrowserSession._cached_contexts["test:session"] is mock_context
        assert "test:session" in BrowserSession._context_timestamps
    
    @pytest.mark.asyncio
    async def test_get_cached_context_hit(self):
        """Test get_cached_context returns cached context."""
        mock_context = AsyncMock()
        
        await BrowserSession.cache_context("test:session", mock_context)
        
        retrieved = await BrowserSession.get_cached_context("test:session")
        
        assert retrieved is mock_context
    
    @pytest.mark.asyncio
    async def test_get_cached_context_expires_after_timeout(self):
        """Test cached context expires after 30 minutes."""
        mock_context = AsyncMock()
        
        await BrowserSession.cache_context("test:session", mock_context)
        
        # Simulate 31 minutes passing
        BrowserSession._context_timestamps["test:session"] = datetime.now() - timedelta(minutes=31)
        
        retrieved = await BrowserSession.get_cached_context("test:session")
        
        assert retrieved is None
        assert "test:session" not in BrowserSession._cached_contexts
        mock_context.clear_cookies.assert_called_once()
        mock_context.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_clear_cached_context_cleans_up(self):
        """Test _clear_cached_context cleans up context resources."""
        mock_context = AsyncMock()
        
        await BrowserSession.cache_context("test:session", mock_context)
        await BrowserSession._clear_cached_context("test:session")
        
        assert "test:session" not in BrowserSession._cached_contexts
        assert "test:session" not in BrowserSession._context_timestamps
        mock_context.clear_cookies.assert_called_once()
        mock_context.clear_permissions.assert_called_once()
        mock_context.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_clear_all_cached_contexts(self):
        """Test _clear_all_cached_contexts clears all contexts."""
        mock_context1 = AsyncMock()
        mock_context2 = AsyncMock()
        
        await BrowserSession.cache_context("session1", mock_context1)
        await BrowserSession.cache_context("session2", mock_context2)
        
        await BrowserSession._clear_all_cached_contexts()
        
        assert len(BrowserSession._cached_contexts) == 0
        assert len(BrowserSession._context_timestamps) == 0
        mock_context1.close.assert_called_once()
        mock_context2.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_authenticated_page_creates_new_context_with_login(self):
        """Test authenticated_page creates new context and performs login."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        login_called = False
        
        async def mock_login(page):
            nonlocal login_called
            login_called = True
            assert page is mock_page
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                async with BrowserSession.authenticated_page("test:user", mock_login) as page:
                    assert page is mock_page
                    assert login_called
                
                # Context should be cached
                assert "test:user" in BrowserSession._cached_contexts
                
                # Page should be closed but context should remain open
                mock_page.close.assert_called_once()
                mock_context.close.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_authenticated_page_reuses_cached_context(self):
        """Test authenticated_page reuses cached context without re-login."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_page1 = AsyncMock()
        mock_page2 = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(side_effect=[mock_page1, mock_page2])
        
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        login_count = 0
        
        async def mock_login(page):
            nonlocal login_count
            login_count += 1
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                # First call - should login
                async with BrowserSession.authenticated_page("test:user", mock_login) as page:
                    assert page is mock_page1
                
                # Second call - should reuse cached context without login
                async with BrowserSession.authenticated_page("test:user", mock_login) as page:
                    assert page is mock_page2
                
                # Login should only be called once
                assert login_count == 1
                
                # new_context should only be called once
                assert mock_browser.new_context.call_count == 1
    
    @pytest.mark.asyncio
    async def test_authenticated_page_without_login_callback(self):
        """Test authenticated_page works without login callback."""
        mock_config = MagicMock()
        mock_config.BROWSER_HEADLESS = True
        
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        
        mock_playwright = AsyncMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        
        with patch("aise.browser_operator.browser.get_config", return_value=mock_config):
            with patch("aise.browser_operator.browser.async_playwright") as mock_pw:
                mock_pw.return_value.start = AsyncMock(return_value=mock_playwright)
                
                async with BrowserSession.authenticated_page("test:user") as page:
                    assert page is mock_page
                
                # Context should still be cached
                assert "test:user" in BrowserSession._cached_contexts
