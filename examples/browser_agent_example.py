#!/usr/bin/env python3
"""
Browser Agent Example

This example demonstrates how to use the BrowserAgent for ticket operations
and automatic API fallback.

Requirements:
- Zendesk or Freshdesk credentials configured
- USE_BROWSER_FALLBACK=true in .env
- Playwright browsers installed (poetry run playwright install chromium)
"""

import asyncio
import os
from pathlib import Path

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from aise.agents.browser_agent import BrowserAgent, should_use_browser_fallback
from aise.ticket_system.browser_fallback import with_browser_fallback
from aise.ticket_system.zendesk import ZendeskProvider
from aise.core.config import load_config
from aise.core.exceptions import TicketAPIError
import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ]
)

logger = structlog.get_logger(__name__)


async def example_direct_browser_usage():
    """Example 1: Direct browser agent usage."""
    print("\n" + "="*60)
    print("Example 1: Direct Browser Agent Usage")
    print("="*60 + "\n")
    
    # Initialize browser agent
    agent = BrowserAgent()
    
    # Example: Get ticket details
    print("Getting ticket details via browser...")
    try:
        result = await agent.execute_action(
            platform="zendesk",
            action="get",
            params={"ticket_id": "123"}
        )
        
        print(f"✓ Ticket retrieved successfully")
        print(f"  Body: {result['body'][:100]}...")
        print(f"  Screenshot: {result['screenshot']}")
    except Exception as e:
        print(f"✗ Failed to get ticket: {e}")
    
    # Example: Reply to ticket
    print("\nReplying to ticket via browser...")
    try:
        result = await agent.execute_action(
            platform="zendesk",
            action="reply",
            params={
                "ticket_id": "123",
                "message": "Thank you for contacting support. We're investigating your issue."
            }
        )
        
        print(f"✓ Reply posted successfully")
        print(f"  Message length: {result['message_length']} characters")
        print(f"  Screenshot: {result['screenshot']}")
    except Exception as e:
        print(f"✗ Failed to post reply: {e}")
    
    # Example: Close ticket
    print("\nClosing ticket via browser...")
    try:
        result = await agent.execute_action(
            platform="zendesk",
            action="close",
            params={"ticket_id": "123"}
        )
        
        print(f"✓ Ticket closed successfully")
        print(f"  Status: {result['status']}")
        print(f"  Screenshot: {result['screenshot']}")
    except Exception as e:
        print(f"✗ Failed to close ticket: {e}")


async def example_automatic_fallback():
    """Example 2: Automatic API fallback."""
    print("\n" + "="*60)
    print("Example 2: Automatic API Fallback")
    print("="*60 + "\n")
    
    # Load configuration
    config = load_config()
    
    # Create Zendesk provider
    provider = ZendeskProvider(
        subdomain=config.ZENDESK_SUBDOMAIN,
        email=config.ZENDESK_EMAIL,
        api_token=config.ZENDESK_API_TOKEN
    )
    
    # Example: Reply with automatic fallback
    print("Attempting to reply via API (with browser fallback)...")
    try:
        result = await with_browser_fallback(
            platform="zendesk",
            action="reply",
            api_func=provider.reply,
            ticket_id="123",
            message="This reply will use API first, then browser if API fails."
        )
        
        print(f"✓ Reply posted successfully (via API)")
    except TicketAPIError as e:
        print(f"✗ Both API and browser failed: {e}")


async def example_fallback_decision():
    """Example 3: Fallback decision logic."""
    print("\n" + "="*60)
    print("Example 3: Fallback Decision Logic")
    print("="*60 + "\n")
    
    # Load configuration
    config = load_config()
    
    # Test different error scenarios
    scenarios = [
        ("API Error (500)", TicketAPIError("Server error", provider="zendesk", status_code=500)),
        ("Not Found (404)", TicketAPIError("Not found", provider="zendesk", status_code=404, ticket_id="999")),
        ("Network Error", TicketAPIError("Connection timeout", provider="zendesk")),
        ("Other Error", ValueError("Some other error")),
    ]
    
    for name, error in scenarios:
        should_fallback = await should_use_browser_fallback(config, error)
        status = "✓ FALLBACK" if should_fallback else "✗ NO FALLBACK"
        print(f"{status}: {name}")


async def example_session_caching():
    """Example 4: Session caching demonstration."""
    print("\n" + "="*60)
    print("Example 4: Session Caching")
    print("="*60 + "\n")
    
    agent = BrowserAgent()
    
    print("First operation (will login)...")
    try:
        result1 = await agent.execute_action(
            platform="zendesk",
            action="get",
            params={"ticket_id": "123"}
        )
        print("✓ First operation complete")
    except Exception as e:
        print(f"✗ First operation failed: {e}")
    
    print("\nSecond operation (will reuse session)...")
    try:
        result2 = await agent.execute_action(
            platform="zendesk",
            action="get",
            params={"ticket_id": "456"}
        )
        print("✓ Second operation complete (session reused)")
    except Exception as e:
        print(f"✗ Second operation failed: {e}")
    
    print("\nSession caching improves performance by reusing authenticated sessions.")


async def example_screenshot_capture():
    """Example 5: Screenshot capture for debugging."""
    print("\n" + "="*60)
    print("Example 5: Screenshot Capture")
    print("="*60 + "\n")
    
    agent = BrowserAgent()
    
    print("Executing operation with screenshot capture...")
    try:
        result = await agent.execute_action(
            platform="zendesk",
            action="get",
            params={"ticket_id": "123"}
        )
        
        screenshot_path = result.get("screenshot")
        if screenshot_path and os.path.exists(screenshot_path):
            print(f"✓ Screenshot captured: {screenshot_path}")
            print(f"  File size: {os.path.getsize(screenshot_path)} bytes")
        else:
            print("✗ Screenshot not found")
    except Exception as e:
        print(f"✗ Operation failed: {e}")
    
    print("\nScreenshots are saved to ./data/screenshots/ for debugging.")


async def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("Browser Agent Examples")
    print("="*60)
    
    # Check configuration
    try:
        config = load_config()
        
        if not config.USE_BROWSER_FALLBACK:
            print("\n⚠ Warning: USE_BROWSER_FALLBACK is disabled")
            print("Set USE_BROWSER_FALLBACK=true in .env to enable browser automation")
            return
        
        if not (config.ZENDESK_SUBDOMAIN or config.FRESHDESK_DOMAIN):
            print("\n⚠ Warning: No ticket system configured")
            print("Configure Zendesk or Freshdesk credentials in .env")
            return
        
        print(f"\n✓ Configuration loaded")
        print(f"  Browser fallback: {config.USE_BROWSER_FALLBACK}")
        print(f"  Headless mode: {config.BROWSER_HEADLESS}")
        print(f"  Zendesk: {'✓' if config.ZENDESK_SUBDOMAIN else '✗'}")
        print(f"  Freshdesk: {'✓' if config.FRESHDESK_DOMAIN else '✗'}")
        
    except Exception as e:
        print(f"\n✗ Configuration error: {e}")
        return
    
    # Run examples
    try:
        # Example 1: Direct browser usage
        await example_direct_browser_usage()
        
        # Example 2: Automatic fallback
        await example_automatic_fallback()
        
        # Example 3: Fallback decision logic
        await example_fallback_decision()
        
        # Example 4: Session caching
        await example_session_caching()
        
        # Example 5: Screenshot capture
        await example_screenshot_capture()
        
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted by user")
    except Exception as e:
        print(f"\n\n✗ Unexpected error: {e}")
        logger.exception("example_failed")
    
    print("\n" + "="*60)
    print("Examples Complete")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
