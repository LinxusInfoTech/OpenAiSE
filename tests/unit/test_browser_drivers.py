# tests/unit/test_browser_drivers.py
"""Unit tests for browser drivers (Zendesk and Freshdesk)."""

import pytest
from unittest.mock import AsyncMock, Mock, patch
from playwright.async_api import Page

from aise.browser_operator.zendesk_driver import ZendeskBrowserDriver
from aise.browser_operator.freshdesk_driver import FreshdeskBrowserDriver
from aise.core.exceptions import BrowserError


@pytest.fixture
def mock_config_zendesk():
    """Mock config with Zendesk settings."""
    config = Mock()
    config.ZENDESK_URL = "https://test.zendesk.com"
    config.ZENDESK_SUBDOMAIN = "test"
    config.ZENDESK_EMAIL = "admin@test.com"
    config.ZENDESK_API_TOKEN = "test_token_123"
    return config


@pytest.fixture
def mock_config_freshdesk():
    """Mock config with Freshdesk settings."""
    config = Mock()
    config.FRESHDESK_URL = "https://test.freshdesk.com"
    config.FRESHDESK_DOMAIN = "test"
    config.FRESHDESK_API_KEY = "test_key_123"
    return config


@pytest.fixture
def mock_browser_actions():
    """Mock BrowserActions."""
    actions = AsyncMock()
    actions.navigate = AsyncMock()
    actions.fill = AsyncMock()
    actions.click = AsyncMock()
    actions.wait_for_selector = AsyncMock()
    actions.get_text = AsyncMock(return_value="Test ticket body")
    return actions


@pytest.fixture
def mock_page():
    """Mock Playwright page."""
    page = AsyncMock(spec=Page)
    page.wait_for_timeout = AsyncMock()
    page.evaluate = AsyncMock()
    return page


class TestZendeskBrowserDriver:
    """Tests for ZendeskBrowserDriver."""
    
    def test_init_with_url(self, mock_config_zendesk):
        """Test driver initialization with ZENDESK_URL."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            driver = ZendeskBrowserDriver()
            assert driver.base_url == "https://test.zendesk.com"
    
    def test_init_with_subdomain(self, mock_config_zendesk):
        """Test driver initialization with ZENDESK_SUBDOMAIN."""
        mock_config_zendesk.ZENDESK_URL = None
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            driver = ZendeskBrowserDriver()
            assert driver.base_url == "https://test.zendesk.com"
    
    def test_init_without_config(self):
        """Test driver initialization fails without config."""
        config = Mock()
        config.ZENDESK_URL = None
        config.ZENDESK_SUBDOMAIN = None
        
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=config):
            with pytest.raises(BrowserError, match="Zendesk URL not configured"):
                ZendeskBrowserDriver()
    
    @pytest.mark.asyncio
    async def test_login_success(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test successful Zendesk login."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            with patch("aise.browser_operator.zendesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = ZendeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.login(mock_page)
                
                # Verify navigation to login page
                mock_browser_actions.navigate.assert_called_once()
                assert "login" in mock_browser_actions.navigate.call_args[0][1]
                
                # Verify credentials filled
                assert mock_browser_actions.fill.call_count == 2
                
                # Verify submit clicked
                mock_browser_actions.click.assert_called()
                
                # Verify wait for navigation
                mock_browser_actions.wait_for_selector.assert_called()
    
    @pytest.mark.asyncio
    async def test_login_without_credentials(self, mock_browser_actions, mock_page):
        """Test login fails without credentials."""
        config = Mock()
        config.ZENDESK_URL = "https://test.zendesk.com"
        config.ZENDESK_EMAIL = None
        config.ZENDESK_API_TOKEN = None
        
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=config):
            driver = ZendeskBrowserDriver(actions=mock_browser_actions)
            
            with pytest.raises(BrowserError, match="credentials not configured"):
                await driver.login(mock_page)
    
    @pytest.mark.asyncio
    async def test_open_ticket(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test opening a ticket."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            with patch("aise.browser_operator.zendesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = ZendeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.open_ticket(mock_page, "12345")
                
                # Verify navigation to ticket URL
                mock_browser_actions.navigate.assert_called_once()
                assert "tickets/12345" in mock_browser_actions.navigate.call_args[0][1]
                
                # Verify wait for ticket content
                mock_browser_actions.wait_for_selector.assert_called()
    
    @pytest.mark.asyncio
    async def test_read_ticket_body(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test reading ticket body."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            driver = ZendeskBrowserDriver(actions=mock_browser_actions)
            
            body = await driver.read_ticket_body(mock_page)
            
            assert body == "Test ticket body"
            mock_browser_actions.wait_for_selector.assert_called()
            mock_browser_actions.get_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_submit_reply(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test submitting a reply."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            with patch("aise.browser_operator.zendesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = ZendeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.submit_reply(mock_page, "Test reply message")
                
                # Verify reply filled
                mock_browser_actions.fill.assert_called_once()
                assert "Test reply message" in str(mock_browser_actions.fill.call_args)
                
                # Verify submit clicked
                mock_browser_actions.click.assert_called()
    
    @pytest.mark.asyncio
    async def test_set_ticket_status(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test setting ticket status."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            with patch("aise.browser_operator.zendesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = ZendeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.set_ticket_status(mock_page, "pending")
                
                # Verify status dropdown clicked
                assert mock_browser_actions.click.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_set_ticket_status_invalid(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test setting invalid ticket status."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            driver = ZendeskBrowserDriver(actions=mock_browser_actions)
            
            with pytest.raises(BrowserError, match="Invalid status"):
                await driver.set_ticket_status(mock_page, "invalid_status")


class TestFreshdeskBrowserDriver:
    """Tests for FreshdeskBrowserDriver."""
    
    def test_init_with_url(self, mock_config_freshdesk):
        """Test driver initialization with FRESHDESK_URL."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            driver = FreshdeskBrowserDriver()
            assert driver.base_url == "https://test.freshdesk.com"
    
    def test_init_with_domain(self, mock_config_freshdesk):
        """Test driver initialization with FRESHDESK_DOMAIN."""
        mock_config_freshdesk.FRESHDESK_URL = None
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            driver = FreshdeskBrowserDriver()
            assert driver.base_url == "https://test.freshdesk.com"
    
    def test_init_without_config(self):
        """Test driver initialization fails without config."""
        config = Mock()
        config.FRESHDESK_URL = None
        config.FRESHDESK_DOMAIN = None
        
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=config):
            with pytest.raises(BrowserError, match="Freshdesk URL not configured"):
                FreshdeskBrowserDriver()
    
    @pytest.mark.asyncio
    async def test_login_success(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test successful Freshdesk login."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            with patch("aise.browser_operator.freshdesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.login(mock_page)
                
                # Verify navigation to login page
                mock_browser_actions.navigate.assert_called_once()
                assert "login" in mock_browser_actions.navigate.call_args[0][1]
                
                # Verify credentials filled
                assert mock_browser_actions.fill.call_count == 2
                
                # Verify submit clicked
                mock_browser_actions.click.assert_called()
    
    @pytest.mark.asyncio
    async def test_open_ticket(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test opening a ticket."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            with patch("aise.browser_operator.freshdesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.open_ticket(mock_page, "67890")
                
                # Verify navigation to ticket URL
                mock_browser_actions.navigate.assert_called_once()
                assert "tickets/67890" in mock_browser_actions.navigate.call_args[0][1]
    
    @pytest.mark.asyncio
    async def test_read_ticket_body(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test reading ticket body."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
            
            body = await driver.read_ticket_body(mock_page)
            
            assert body == "Test ticket body"
            mock_browser_actions.get_text.assert_called()
    
    @pytest.mark.asyncio
    async def test_submit_reply(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test submitting a reply."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            with patch("aise.browser_operator.freshdesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.submit_reply(mock_page, "Test reply message")
                
                # Verify editor clicked and content set
                mock_browser_actions.click.assert_called()
                mock_page.evaluate.assert_called()
    
    @pytest.mark.asyncio
    async def test_set_ticket_status(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test setting ticket status."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            with patch("aise.browser_operator.freshdesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
                
                await driver.set_ticket_status(mock_page, "resolved")
                
                # Verify status dropdown clicked
                assert mock_browser_actions.click.call_count >= 2
    
    @pytest.mark.asyncio
    async def test_set_ticket_status_invalid(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test setting invalid ticket status."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
            
            with pytest.raises(BrowserError, match="Invalid status"):
                await driver.set_ticket_status(mock_page, "invalid_status")


class TestDriverIntegration:
    """Integration tests for driver interaction patterns."""
    
    @pytest.mark.asyncio
    async def test_zendesk_full_workflow(self, mock_config_zendesk, mock_browser_actions, mock_page):
        """Test complete Zendesk workflow."""
        with patch("aise.browser_operator.zendesk_driver.get_config", return_value=mock_config_zendesk):
            with patch("aise.browser_operator.zendesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = ZendeskBrowserDriver(actions=mock_browser_actions)
                
                # Login
                await driver.login(mock_page)
                
                # Open ticket
                await driver.open_ticket(mock_page, "12345")
                
                # Read body
                body = await driver.read_ticket_body(mock_page)
                assert body == "Test ticket body"
                
                # Submit reply
                await driver.submit_reply(mock_page, "Thank you for contacting support.")
                
                # Update status
                await driver.set_ticket_status(mock_page, "pending")
                
                # Verify all operations called
                assert mock_browser_actions.navigate.call_count >= 2
                assert mock_browser_actions.fill.call_count >= 3
                assert mock_browser_actions.click.call_count >= 3
    
    @pytest.mark.asyncio
    async def test_freshdesk_full_workflow(self, mock_config_freshdesk, mock_browser_actions, mock_page):
        """Test complete Freshdesk workflow."""
        with patch("aise.browser_operator.freshdesk_driver.get_config", return_value=mock_config_freshdesk):
            with patch("aise.browser_operator.freshdesk_driver.BrowserSession.screenshot", new_callable=AsyncMock):
                driver = FreshdeskBrowserDriver(actions=mock_browser_actions)
                
                # Login
                await driver.login(mock_page)
                
                # Open ticket
                await driver.open_ticket(mock_page, "67890")
                
                # Read body
                body = await driver.read_ticket_body(mock_page)
                assert body == "Test ticket body"
                
                # Submit reply
                await driver.submit_reply(mock_page, "We're investigating this issue.")
                
                # Update status
                await driver.set_ticket_status(mock_page, "pending")
                
                # Verify all operations called
                assert mock_browser_actions.navigate.call_count >= 2
                assert mock_browser_actions.fill.call_count >= 2
                assert mock_browser_actions.click.call_count >= 3
