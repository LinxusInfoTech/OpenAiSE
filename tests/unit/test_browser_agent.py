# tests/unit/test_browser_agent.py
"""Unit tests for BrowserAgent."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from playwright.async_api import Page

from aise.agents.browser_agent import BrowserAgent, should_use_browser_fallback
from aise.core.exceptions import BrowserError, TicketAPIError


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = MagicMock()
    config.USE_BROWSER_FALLBACK = True
    config.BROWSER_HEADLESS = True
    config.ZENDESK_SUBDOMAIN = "test"
    config.ZENDESK_EMAIL = "test@example.com"
    config.ZENDESK_API_TOKEN = "test_token"
    config.FRESHDESK_DOMAIN = "test"
    config.FRESHDESK_API_KEY = "test_key"
    return config


@pytest.fixture
def mock_browser_session():
    """Mock BrowserSession."""
    with patch("aise.agents.browser_agent.BrowserSession") as mock:
        session = MagicMock()
        mock.return_value = session
        
        # Mock authenticated_page context manager
        page = AsyncMock(spec=Page)
        session.authenticated_page.return_value.__aenter__ = AsyncMock(return_value=page)
        session.authenticated_page.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Mock screenshot
        mock.screenshot = AsyncMock(return_value="/path/to/screenshot.png")
        
        yield mock


@pytest.fixture
def mock_zendesk_driver():
    """Mock ZendeskBrowserDriver."""
    with patch("aise.agents.browser_agent.ZendeskBrowserDriver") as mock:
        driver = MagicMock()
        driver.login = AsyncMock()
        driver.open_ticket = AsyncMock()
        driver.read_ticket_body = AsyncMock(return_value="Ticket body content")
        driver.submit_reply = AsyncMock()
        driver.set_ticket_status = AsyncMock()
        mock.return_value = driver
        yield mock


@pytest.fixture
def mock_freshdesk_driver():
    """Mock FreshdeskBrowserDriver."""
    with patch("aise.agents.browser_agent.FreshdeskBrowserDriver") as mock:
        driver = MagicMock()
        driver.login = AsyncMock()
        driver.open_ticket = AsyncMock()
        driver.read_ticket_body = AsyncMock(return_value="Ticket body content")
        driver.submit_reply = AsyncMock()
        driver.set_ticket_status = AsyncMock()
        mock.return_value = driver
        yield mock


class TestBrowserAgent:
    """Test BrowserAgent class."""
    
    @patch("aise.agents.browser_agent.get_config")
    def test_init(self, mock_get_config, mock_config, mock_zendesk_driver, mock_freshdesk_driver):
        """Test BrowserAgent initialization."""
        mock_get_config.return_value = mock_config
        
        agent = BrowserAgent()
        
        assert "zendesk" in agent.drivers
        assert "freshdesk" in agent.drivers
        assert agent.config == mock_config
    
    @patch("aise.agents.browser_agent.get_config")
    @pytest.mark.asyncio
    async def test_execute_action_get(
        self,
        mock_get_config,
        mock_config,
        mock_browser_session,
        mock_zendesk_driver
    ):
        """Test execute_action with 'get' action."""
        mock_get_config.return_value = mock_config
        
        agent = BrowserAgent()
        
        result = await agent.execute_action(
            platform="zendesk",
            action="get",
            params={"ticket_id": "123"}
        )
        
        assert result["ticket_id"] == "123"
        assert result["body"] == "Ticket body content"
        assert result["success"] is True
    
    @patch("aise.agents.browser_agent.get_config")
    @pytest.mark.asyncio
    async def test_execute_action_reply(
        self,
        mock_get_config,
        mock_config,
        mock_browser_session,
        mock_zendesk_driver
    ):
        """Test execute_action with 'reply' action."""
        mock_get_config.return_value = mock_config
        
        agent = BrowserAgent()
        
        result = await agent.execute_action(
            platform="zendesk",
            action="reply",
            params={"ticket_id": "123", "message": "Test reply"}
        )
        
        assert result["ticket_id"] == "123"
        assert result["message_length"] == 10
        assert result["success"] is True
    
    @patch("aise.agents.browser_agent.get_config")
    @pytest.mark.asyncio
    async def test_execute_action_close(
        self,
        mock_get_config,
        mock_config,
        mock_browser_session,
        mock_zendesk_driver
    ):
        """Test execute_action with 'close' action."""
        mock_get_config.return_value = mock_config
        
        agent = BrowserAgent()
        
        result = await agent.execute_action(
            platform="zendesk",
            action="close",
            params={"ticket_id": "123"}
        )
        
        assert result["ticket_id"] == "123"
        assert result["status"] == "solved"
        assert result["success"] is True
    
    @patch("aise.agents.browser_agent.get_config")
    @pytest.mark.asyncio
    async def test_execute_action_unknown_platform(
        self,
        mock_get_config,
        mock_config
    ):
        """Test execute_action with unknown platform."""
        mock_get_config.return_value = mock_config
        
        agent = BrowserAgent()
        agent.drivers = {}  # Clear drivers
        
        with pytest.raises(BrowserError) as exc_info:
            await agent.execute_action(
                platform="unknown",
                action="get",
                params={"ticket_id": "123"}
            )
        
        assert "not configured" in str(exc_info.value)
    
    @patch("aise.agents.browser_agent.get_config")
    @pytest.mark.asyncio
    async def test_execute_action_unknown_action(
        self,
        mock_get_config,
        mock_config,
        mock_browser_session,
        mock_zendesk_driver
    ):
        """Test execute_action with unknown action."""
        mock_get_config.return_value = mock_config
        
        agent = BrowserAgent()
        
        with pytest.raises(BrowserError) as exc_info:
            await agent.execute_action(
                platform="zendesk",
                action="unknown",
                params={"ticket_id": "123"}
            )
        
        assert "Unknown action" in str(exc_info.value)


class TestShouldUseBrowserFallback:
    """Test should_use_browser_fallback function."""
    
    @pytest.mark.asyncio
    async def test_fallback_disabled(self, mock_config):
        """Test fallback when disabled in config."""
        mock_config.USE_BROWSER_FALLBACK = False
        
        result = await should_use_browser_fallback(
            mock_config,
            TicketAPIError("API error", provider="zendesk")
        )
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_no_api_error(self, mock_config):
        """Test fallback with no API error."""
        result = await should_use_browser_fallback(mock_config, None)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_ticket_not_found_error(self, mock_config):
        """Test fallback with 404 error."""
        error = TicketAPIError("Not found", provider="zendesk", status_code=404, ticket_id="123")
        
        result = await should_use_browser_fallback(mock_config, error)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_api_error_triggers_fallback(self, mock_config):
        """Test fallback with API error."""
        error = TicketAPIError("Server error", provider="zendesk", status_code=500)
        
        result = await should_use_browser_fallback(mock_config, error)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_non_api_error_no_fallback(self, mock_config):
        """Test fallback with non-API error."""
        error = ValueError("Some other error")
        
        result = await should_use_browser_fallback(mock_config, error)
        
        assert result is False
