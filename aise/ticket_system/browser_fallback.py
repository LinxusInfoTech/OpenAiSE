# aise/ticket_system/browser_fallback.py
"""Browser fallback logic for ticket operations.

This module provides decorators and utilities for automatic browser fallback
when ticket API operations fail.

Requirements:
- 11.2: Detect API failures and trigger browser fallback
- 11.8: Log fallback events
- 11.12: Queue for retry if browser also fails
"""

from typing import Callable, Any, Optional, TypeVar, ParamSpec
from functools import wraps
import structlog

from aise.core.config import get_config
from aise.core.exceptions import TicketAPIError, BrowserError
from aise.agents.browser_agent import BrowserAgent, should_use_browser_fallback

logger = structlog.get_logger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


async def with_browser_fallback(
    platform: str,
    action: str,
    api_func: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs
) -> T:
    """
    Execute API function with automatic browser fallback.
    
    Attempts to execute the API function first. If it fails and browser
    fallback is enabled, automatically retries using browser automation.
    
    Args:
        platform: Platform name ("zendesk" or "freshdesk")
        action: Action name ("get", "reply", "close", "add_tags")
        api_func: API function to execute
        *args: Positional arguments for api_func
        **kwargs: Keyword arguments for api_func
    
    Returns:
        Result from API function or browser fallback
    
    Raises:
        TicketAPIError: If both API and browser fallback fail
        
    Requirements:
    - 11.2: Automatic fallback when API fails and USE_BROWSER_FALLBACK=true
    - 11.8: Log fallback events
    - 11.12: Queue for retry if browser also fails
    
    Example:
        >>> result = await with_browser_fallback(
        ...     platform="zendesk",
        ...     action="reply",
        ...     api_func=provider.reply,
        ...     ticket_id="123",
        ...     message="Hello"
        ... )
    """
    config = get_config()
    
    try:
        # Try API first
        logger.debug(
            "attempting_api_call",
            platform=platform,
            action=action
        )
        result = await api_func(*args, **kwargs)
        
        logger.debug(
            "api_call_success",
            platform=platform,
            action=action
        )
        return result
        
    except TicketAPIError as api_error:
        # Check if browser fallback should be used
        if not await should_use_browser_fallback(config, api_error):
            # Re-raise API error if fallback not enabled or not applicable
            raise
        
        # Log fallback event
        logger.warning(
            "api_failed_attempting_browser_fallback",
            platform=platform,
            action=action,
            api_error=str(api_error),
            error_type=type(api_error).__name__
        )
        
        try:
            # Attempt browser fallback
            browser_agent = BrowserAgent()
            
            # Map function arguments to browser action parameters
            params = _map_args_to_params(action, args, kwargs)
            
            result = await browser_agent.execute_action(
                platform=platform,
                action=action,
                params=params
            )
            
            logger.info(
                "browser_fallback_success",
                platform=platform,
                action=action,
                ticket_id=params.get("ticket_id")
            )
            
            # Return browser result (may need transformation)
            return _transform_browser_result(action, result)
            
        except BrowserError as browser_error:
            # Both API and browser failed
            logger.error(
                "browser_fallback_failed",
                platform=platform,
                action=action,
                api_error=str(api_error),
                browser_error=str(browser_error)
            )
            
            # TODO: Queue for retry (Requirement 11.12)
            # For now, re-raise the original API error
            raise TicketAPIError(
                f"Both API and browser fallback failed. API: {str(api_error)}, Browser: {str(browser_error)}",
                provider=platform
            ) from api_error


def _map_args_to_params(action: str, args: tuple, kwargs: dict) -> dict:
    """
    Map function arguments to browser action parameters.
    
    Args:
        action: Action name
        args: Positional arguments
        kwargs: Keyword arguments
    
    Returns:
        Dictionary of parameters for browser action
    """
    params = {}
    
    if action == "get":
        # get(ticket_id)
        if args:
            params["ticket_id"] = args[0]
        else:
            params["ticket_id"] = kwargs.get("ticket_id")
    
    elif action == "reply":
        # reply(ticket_id, message)
        if len(args) >= 2:
            params["ticket_id"] = args[0]
            params["message"] = args[1]
        else:
            params["ticket_id"] = kwargs.get("ticket_id")
            params["message"] = kwargs.get("message")
    
    elif action == "close":
        # close(ticket_id)
        if args:
            params["ticket_id"] = args[0]
        else:
            params["ticket_id"] = kwargs.get("ticket_id")
    
    elif action == "add_tags":
        # add_tags(ticket_id, tags)
        if len(args) >= 2:
            params["ticket_id"] = args[0]
            params["tags"] = args[1]
        else:
            params["ticket_id"] = kwargs.get("ticket_id")
            params["tags"] = kwargs.get("tags")
    
    return params


def _transform_browser_result(action: str, browser_result: dict) -> Any:
    """
    Transform browser result to match API function return type.
    
    Args:
        action: Action name
        browser_result: Result from browser action
    
    Returns:
        Transformed result matching API function return type
    """
    if action == "get":
        # For 'get', browser returns dict with body
        # API returns Ticket object, but we can't construct it here
        # Return the browser result as-is for now
        return browser_result
    
    elif action in ["reply", "close", "add_tags"]:
        # These actions return None in API
        # Browser returns dict with success flag
        if not browser_result.get("success"):
            raise BrowserError(
                f"Browser action '{action}' failed: {browser_result.get('message', 'Unknown error')}"
            )
        return None
    
    return browser_result


def browser_fallback_decorator(platform: str, action: str):
    """
    Decorator for automatic browser fallback on ticket provider methods.
    
    Args:
        platform: Platform name ("zendesk" or "freshdesk")
        action: Action name ("get", "reply", "close", "add_tags")
    
    Returns:
        Decorator function
    
    Example:
        >>> class ZendeskProvider(TicketProvider):
        ...     @browser_fallback_decorator("zendesk", "reply")
        ...     async def reply(self, ticket_id: str, message: str):
        ...         # API implementation
        ...         pass
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            return await with_browser_fallback(
                platform=platform,
                action=action,
                api_func=func,
                *args,
                **kwargs
            )
        return wrapper
    return decorator
