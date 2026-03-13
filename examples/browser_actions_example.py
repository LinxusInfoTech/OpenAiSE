#!/usr/bin/env python3
"""
Example demonstrating browser action primitives and session caching.

This example shows how to:
1. Use basic browser actions (navigate, click, fill, get_text)
2. Implement login with session caching
3. Reuse authenticated sessions across operations
4. Handle errors gracefully

Requirements:
- BROWSER_HEADLESS=false (to see the browser in action)
"""

import asyncio
from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.actions import BrowserActions
from aise.core.exceptions import BrowserError


async def example_basic_actions():
    """Example 1: Basic browser actions."""
    print("\n=== Example 1: Basic Browser Actions ===\n")
    
    actions = BrowserActions()
    
    async with BrowserSession.new_page() as page:
        # Navigate to a page
        print("Navigating to example.com...")
        await actions.navigate(page, "https://example.com")
        
        # Wait for content to load
        print("Waiting for content...")
        await actions.wait_for_selector(page, "h1")
        
        # Get text from element
        print("Reading page title...")
        title = await actions.get_text(page, "h1")
        print(f"Page title: {title}")
        
        # Take a screenshot
        print("Capturing screenshot...")
        screenshot_path = await BrowserSession.screenshot(page, "example_basic")
        print(f"Screenshot saved to: {screenshot_path}")


async def example_form_interaction():
    """Example 2: Form interaction."""
    print("\n=== Example 2: Form Interaction ===\n")
    
    actions = BrowserActions()
    
    async with BrowserSession.new_page() as page:
        # Navigate to a form page
        print("Navigating to httpbin.org/forms/post...")
        await actions.navigate(page, "https://httpbin.org/forms/post")
        
        # Fill form fields
        print("Filling form fields...")
        await actions.fill(page, "input[name='custname']", "John Doe")
        await actions.fill(page, "input[name='custtel']", "555-1234")
        await actions.fill(page, "input[name='custemail']", "john@example.com")
        
        # Click submit button
        print("Clicking submit button...")
        await actions.click(page, "button[type='submit']")
        
        # Wait for response
        await actions.wait_for_selector(page, "pre")
        
        # Take a screenshot of the result
        screenshot_path = await BrowserSession.screenshot(page, "form_submitted")
        print(f"Screenshot saved to: {screenshot_path}")


async def example_login_with_caching():
    """Example 3: Login with session caching."""
    print("\n=== Example 3: Login with Session Caching ===\n")
    
    actions = BrowserActions()
    
    async def perform_login(page):
        """Simulate login process."""
        print("  → Performing login...")
        await actions.navigate(page, "https://httpbin.org/forms/post")
        await actions.fill(page, "input[name='custname']", "admin")
        await actions.fill(page, "input[name='custemail']", "admin@example.com")
        print("  → Login completed!")
    
    session_key = "httpbin:admin"
    
    # First operation - will perform login
    print("\nFirst operation (will login):")
    async with BrowserSession.authenticated_page(session_key, perform_login) as page:
        print("  → Using authenticated page...")
        await actions.navigate(page, "https://httpbin.org/html")
        title = await actions.get_text(page, "h1")
        print(f"  → Page title: {title}")
    
    # Second operation - will reuse cached session
    print("\nSecond operation (will reuse session):")
    async with BrowserSession.authenticated_page(session_key, perform_login) as page:
        print("  → Using authenticated page...")
        await actions.navigate(page, "https://httpbin.org/html")
        title = await actions.get_text(page, "h1")
        print(f"  → Page title: {title}")
    
    print("\n✓ Notice: Login was only performed once!")


async def example_error_handling():
    """Example 4: Error handling and retries."""
    print("\n=== Example 4: Error Handling ===\n")
    
    actions = BrowserActions()
    
    async with BrowserSession.new_page() as page:
        # Navigate to valid page
        print("Navigating to valid page...")
        await actions.navigate(page, "https://example.com")
        print("✓ Navigation succeeded")
        
        # Try to click non-existent element (will retry and fail)
        print("\nTrying to click non-existent element...")
        try:
            await actions.click(page, "#does-not-exist", timeout=5000, retries=2)
        except BrowserError as e:
            print(f"✓ Error caught as expected: {e}")
        
        # Try to get text from non-existent element
        print("\nTrying to get text from non-existent element...")
        try:
            await actions.get_text(page, "#also-does-not-exist", timeout=5000, retries=2)
        except BrowserError as e:
            print(f"✓ Error caught as expected: {e}")


async def example_custom_timeouts():
    """Example 5: Custom timeouts and retries."""
    print("\n=== Example 5: Custom Timeouts ===\n")
    
    actions = BrowserActions()
    
    async with BrowserSession.new_page() as page:
        # Quick operation with short timeout
        print("Quick navigation with 10-second timeout...")
        await actions.navigate(page, "https://example.com", timeout=10000)
        print("✓ Quick navigation completed")
        
        # Operation with custom retry count
        print("\nOperation with 5 retries...")
        await actions.wait_for_selector(page, "h1", retries=5)
        print("✓ Element found")
        
        # Get text with custom settings
        print("\nGet text with custom timeout...")
        text = await actions.get_text(page, "h1", timeout=15000, retries=2)
        print(f"✓ Text retrieved: {text}")


async def example_multiple_operations():
    """Example 6: Multiple operations in sequence."""
    print("\n=== Example 6: Multiple Operations ===\n")
    
    actions = BrowserActions()
    
    async with BrowserSession.new_page() as page:
        # Navigate
        print("1. Navigating...")
        await actions.navigate(page, "https://httpbin.org/forms/post")
        
        # Wait for form
        print("2. Waiting for form...")
        await actions.wait_for_selector(page, "form")
        
        # Fill multiple fields
        print("3. Filling form fields...")
        await actions.fill(page, "input[name='custname']", "Test User")
        await actions.fill(page, "input[name='custemail']", "test@example.com")
        await actions.fill(page, "textarea[name='comments']", "This is a test comment")
        
        # Select radio button
        print("4. Selecting options...")
        await actions.click(page, "input[value='medium']")
        
        # Take screenshot before submit
        print("5. Taking screenshot...")
        await BrowserSession.screenshot(page, "before_submit")
        
        # Submit form
        print("6. Submitting form...")
        await actions.click(page, "button[type='submit']")
        
        # Wait for result
        print("7. Waiting for result...")
        await actions.wait_for_selector(page, "pre")
        
        # Take screenshot after submit
        print("8. Taking final screenshot...")
        await BrowserSession.screenshot(page, "after_submit")
        
        print("\n✓ All operations completed successfully!")


async def main():
    """Run all examples."""
    print("=" * 60)
    print("Browser Actions Examples")
    print("=" * 60)
    
    try:
        # Run examples
        await example_basic_actions()
        await example_form_interaction()
        await example_login_with_caching()
        await example_error_handling()
        await example_custom_timeouts()
        await example_multiple_operations()
        
        print("\n" + "=" * 60)
        print("All examples completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error running examples: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
