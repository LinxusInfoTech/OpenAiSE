# tests/unit/test_browser_fallback.py
"""Unit tests for browser fallback logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aise.ticket_system.browser_fallback import (
    with_browser_fallback,
    _map_args_to_params,
    _transform_browser_result
)
from aise.core.exceptions import TicketAPIError, BrowserError


@pytest.fixture
def mock_config():
    """Mock configuration."""
    config = MagicMock()
    config.USE_BROWSER_FALLBACK = True
    return config


@pytest.fixture
def mock_browser_agent():
    """Mock BrowserAgent."""
    with patch("aise.ticket_system.browser_fallback.BrowserAgent") as mock:
        agent = MagicMock()
        agent.execute_action = AsyncMock(return_value={
            "ticket_id": "123",
            "success": True,
            "screenshot": "/path/to/screenshot.png"
        })
        mock.return_value = agent
        yield mock


class TestWithBrowserFallback:
    """Test with_browser_fallback function."""
    
    @patch("aise.ticket_system.browser_fallback.get_config")
    @pytest.mark.asyncio
    async def test_api_success_no_fallback(self, mock_get_config, mock_config):
        """Test successful API call without fallback."""
        mock_get_config.return_value = mock_config
        
        api_func = AsyncMock(return_value="success")
        
        result = await with_browser_fallback(
            platform="zendesk",
            action="reply",
            api_func=api_func,
            ticket_id="123",
            message="Test"
        )
        
        assert result == "success"
        api_func.assert_called_once()
    
    @patch("aise.ticket_system.browser_fallback.get_config")
    @patch("aise.ticket_system.browser_fallback.should_use_browser_fallback")
    @pytest.mark.asyncio
    async def test_api_failure_fallback_disabled(
        self,
        mock_should_fallback,
        mock_get_config,
        mock_config
    ):
        """Test API failure with fallback disabled."""
        mock_get_config.return_value = mock_config
        mock_should_fallback.return_value = False
        
        api_func = AsyncMock(side_effect=TicketAPIError("API error", provider="zendesk"))
        
        with pytest.raises(TicketAPIError):
            await with_browser_fallback(
                platform="zendesk",
                action="reply",
                api_func=api_func,
                ticket_id="123",
                message="Test"
            )
    
    @patch("aise.ticket_system.browser_fallback.get_config")
    @patch("aise.ticket_system.browser_fallback.should_use_browser_fallback")
    @pytest.mark.asyncio
    async def test_api_failure_browser_success(
        self,
        mock_should_fallback,
        mock_get_config,
        mock_config,
        mock_browser_agent
    ):
        """Test API failure with successful browser fallback."""
        mock_get_config.return_value = mock_config
        mock_should_fallback.return_value = True
        
        api_func = AsyncMock(side_effect=TicketAPIError("API error", provider="zendesk"))
        
        result = await with_browser_fallback(
            platform="zendesk",
            action="reply",
            api_func=api_func,
            ticket_id="123",
            message="Test"
        )
        
        assert result is None  # reply returns None
        mock_browser_agent.return_value.execute_action.assert_called_once()
    
    @patch("aise.ticket_system.browser_fallback.get_config")
    @patch("aise.ticket_system.browser_fallback.should_use_browser_fallback")
    @pytest.mark.asyncio
    async def test_api_failure_browser_failure(
        self,
        mock_should_fallback,
        mock_get_config,
        mock_config,
        mock_browser_agent
    ):
        """Test API failure with browser fallback also failing."""
        mock_get_config.return_value = mock_config
        mock_should_fallback.return_value = True
        
        api_func = AsyncMock(side_effect=TicketAPIError("API error", provider="zendesk"))
        mock_browser_agent.return_value.execute_action.side_effect = BrowserError("Browser error")
        
        with pytest.raises(TicketAPIError) as exc_info:
            await with_browser_fallback(
                platform="zendesk",
                action="reply",
                api_func=api_func,
                ticket_id="123",
                message="Test"
            )
        
        assert "Both API and browser fallback failed" in str(exc_info.value)


class TestMapArgsToParams:
    """Test _map_args_to_params function."""
    
    def test_map_get_action_positional(self):
        """Test mapping 'get' action with positional args."""
        params = _map_args_to_params("get", ("123",), {})
        
        assert params == {"ticket_id": "123"}
    
    def test_map_get_action_keyword(self):
        """Test mapping 'get' action with keyword args."""
        params = _map_args_to_params("get", (), {"ticket_id": "123"})
        
        assert params == {"ticket_id": "123"}
    
    def test_map_reply_action_positional(self):
        """Test mapping 'reply' action with positional args."""
        params = _map_args_to_params("reply", ("123", "Test message"), {})
        
        assert params == {"ticket_id": "123", "message": "Test message"}
    
    def test_map_reply_action_keyword(self):
        """Test mapping 'reply' action with keyword args."""
        params = _map_args_to_params("reply", (), {"ticket_id": "123", "message": "Test"})
        
        assert params == {"ticket_id": "123", "message": "Test"}
    
    def test_map_close_action(self):
        """Test mapping 'close' action."""
        params = _map_args_to_params("close", ("123",), {})
        
        assert params == {"ticket_id": "123"}
    
    def test_map_add_tags_action(self):
        """Test mapping 'add_tags' action."""
        params = _map_args_to_params("add_tags", ("123", ["tag1", "tag2"]), {})
        
        assert params == {"ticket_id": "123", "tags": ["tag1", "tag2"]}


class TestTransformBrowserResult:
    """Test _transform_browser_result function."""
    
    def test_transform_get_result(self):
        """Test transforming 'get' action result."""
        browser_result = {
            "ticket_id": "123",
            "body": "Ticket content",
            "success": True
        }
        
        result = _transform_browser_result("get", browser_result)
        
        assert result == browser_result
    
    def test_transform_reply_result_success(self):
        """Test transforming 'reply' action result (success)."""
        browser_result = {
            "ticket_id": "123",
            "success": True
        }
        
        result = _transform_browser_result("reply", browser_result)
        
        assert result is None
    
    def test_transform_reply_result_failure(self):
        """Test transforming 'reply' action result (failure)."""
        browser_result = {
            "ticket_id": "123",
            "success": False,
            "message": "Failed to submit"
        }
        
        with pytest.raises(BrowserError) as exc_info:
            _transform_browser_result("reply", browser_result)
        
        assert "Failed to submit" in str(exc_info.value)
    
    def test_transform_close_result(self):
        """Test transforming 'close' action result."""
        browser_result = {
            "ticket_id": "123",
            "success": True
        }
        
        result = _transform_browser_result("close", browser_result)
        
        assert result is None
