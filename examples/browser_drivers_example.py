#!/usr/bin/env python3
"""
Example usage of Zendesk and Freshdesk browser drivers.

This example demonstrates how to use the platform-specific browser drivers
to automate ticket operations when APIs are unavailable.

Requirements:
- 11.6: Platform-specific drivers for Zendesk and Freshdesk
- 5.1: Zendesk integration
- 5.2: Freshdesk integration
- 5.4: Browser fallback when APIs unavailable
"""

import asyncio
from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.zendesk_driver import ZendeskBrowserDriver
from aise.browser_operator.freshdesk_driver import FreshdeskBrowserDriver
from aise.core.config import load_config


async def zendesk_example():
    """Example: Automate Zendesk ticket reply via browser."""
    print("\n=== Zendesk Browser Automation Example ===\n")
    
    # Initialize driver
    driver = ZendeskBrowserDriver()
    
    # Use authenticated session with login caching
    session_key = f"zendesk:{driver.config.ZENDESK_EMAIL}"
    
    async def login_callback(page):
        """Login callback for session caching."""
        await driver.login(page)
    
    async with BrowserSession.authenticated_page(session_key, login_callback) as page:
        # Open specific ticket
        ticket_id = "12345"
        await driver.open_ticket(page, ticket_id)
        
        # Read ticket body
        body = await driver.read_ticket_body(page)
        print(f"Ticket body: {body[:100]}...")
        
        # Submit reply
        reply_message = "Thank you for contacting support. We're investigating this issue."
        await driver.submit_reply(page, reply_message)
        print(f"Reply submitted: {reply_message}")
        
        # Update ticket status
        await driver.set_ticket_status(page, "pending")
        print("Ticket status updated to: pending")
    
    print("\n✓ Zendesk automation completed successfully")


async def freshdesk_example():
    """Example: Automate Freshdesk ticket reply via browser."""
    print("\n=== Freshdesk Browser Automation Example ===\n")
    
    # Initialize driver
    driver = FreshdeskBrowserDriver()
    
    # Use authenticated session with login caching
    session_key = f"freshdesk:{driver.config.FRESHDESK_DOMAIN}"
    
    async def login_callback(page):
        """Login callback for session caching."""
        await driver.login(page)
    
    async with BrowserSession.authenticated_page(session_key, login_callback) as page:
        # Open specific ticket
        ticket_id = "67890"
        await driver.open_ticket(page, ticket_id)
        
        # Read ticket body
        body = await driver.read_ticket_body(page)
        print(f"Ticket body: {body[:100]}...")
        
        # Submit reply
        reply_message = "We've identified the issue and are working on a fix."
        await driver.submit_reply(page, reply_message)
        print(f"Reply submitted: {reply_message}")
        
        # Update ticket status
        await driver.set_ticket_status(page, "pending")
        print("Ticket status updated to: pending")
    
    print("\n✓ Freshdesk automation completed successfully")


async def session_caching_example():
    """Example: Demonstrate session caching across multiple operations."""
    print("\n=== Session Caching Example ===\n")
    
    driver = ZendeskBrowserDriver()
    session_key = f"zendesk:{driver.config.ZENDESK_EMAIL}"
    
    async def login_callback(page):
        """Login callback - only called once."""
        print("Performing login (this should only happen once)...")
        await driver.login(page)
    
    # First operation - will perform login
    print("First operation (will login):")
    async with BrowserSession.authenticated_page(session_key, login_callback) as page:
        await driver.open_ticket(page, "12345")
        print("  ✓ Ticket opened")
    
    # Second operation - will reuse cached session
    print("\nSecond operation (will reuse session):")
    async with BrowserSession.authenticated_page(session_key, login_callback) as page:
        await driver.open_ticket(page, "67890")
        print("  ✓ Ticket opened (using cached session)")
    
    print("\n✓ Session caching demonstrated successfully")


async def main():
    """Run all examples."""
    # Load configuration
    load_config()
    
    print("Browser Driver Examples")
    print("=" * 50)
    
    # Note: These examples require valid credentials in .env
    # Uncomment the examples you want to run:
    
    # await zendesk_example()
    # await freshdesk_example()
    # await session_caching_example()
    
    print("\nNote: Uncomment examples in main() to run them.")
    print("Ensure ZENDESK_URL/FRESHDESK_URL and credentials are configured in .env")


if __name__ == "__main__":
    asyncio.run(main())
