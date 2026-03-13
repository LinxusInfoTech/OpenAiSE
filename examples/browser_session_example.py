#!/usr/bin/env python3
# examples/browser_session_example.py
"""Example demonstrating BrowserSession usage."""

import asyncio
from aise.browser_operator.browser import BrowserSession


async def main():
    """Demonstrate browser session management."""
    
    print("Example 1: Basic page navigation")
    print("-" * 50)
    
    # Use context manager for automatic cleanup
    async with BrowserSession.new_page() as page:
        await page.goto("https://example.com")
        title = await page.title()
        print(f"Page title: {title}")
        
        # Capture screenshot
        screenshot_path = await BrowserSession.screenshot(page, "example_homepage")
        print(f"Screenshot saved to: {screenshot_path}")
    
    print("\nExample 2: Browser session reuse")
    print("-" * 50)
    
    # First page
    async with BrowserSession.new_page() as page1:
        await page1.goto("https://example.com")
        print("First page loaded")
    
    # Second page reuses the same browser instance
    async with BrowserSession.new_page() as page2:
        await page2.goto("https://example.org")
        print("Second page loaded (browser reused)")
    
    print("\nExample 3: Multiple operations with screenshots")
    print("-" * 50)
    
    async with BrowserSession.new_page() as page:
        # Navigate to page
        await page.goto("https://example.com")
        await BrowserSession.screenshot(page, "step1_initial_load")
        
        # Interact with page
        content = await page.content()
        print(f"Page content length: {len(content)} characters")
        
        # Take another screenshot
        await BrowserSession.screenshot(page, "step2_after_interaction")
    
    print("\nAll examples completed successfully!")
    print("Browser session will be automatically cleaned up after 30 minutes of inactivity.")


if __name__ == "__main__":
    asyncio.run(main())
