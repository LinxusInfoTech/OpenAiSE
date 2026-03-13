# Browser Session Management

## Overview

The `BrowserSession` class provides a singleton-based browser automation framework using Playwright. It manages browser lifecycle, session reuse, automatic timeouts, and screenshot capture for debugging.

## Features

- **Singleton Pattern**: Single browser instance shared across operations
- **Session Reuse**: Browser sessions are reused for subsequent operations
- **Automatic Timeout**: Sessions idle for 30 minutes are automatically terminated
- **Context Isolation**: Each operation gets an isolated browser context
- **Screenshot Capture**: Built-in screenshot functionality for debugging
- **Headless/Headed Mode**: Configurable via `BROWSER_HEADLESS` setting

## Requirements Addressed

- **11.1**: Browser automation as fallback when APIs unavailable
- **11.4**: Browser sessions should be reused for subsequent operations
- **11.5**: Capture screenshots for debugging
- **11.7**: Close browser context to free resources after operations
- **11.9**: Support headless and headed modes via configuration
- **11.10**: Terminate sessions idle for 30 minutes

## Usage

### Basic Page Navigation

```python
from aise.browser_operator.browser import BrowserSession

async def navigate_example():
    async with BrowserSession.new_page() as page:
        await page.goto("https://example.com")
        title = await page.title()
        print(f"Page title: {title}")
```

### Capturing Screenshots

```python
async def screenshot_example():
    async with BrowserSession.new_page() as page:
        await page.goto("https://example.com")
        
        # Capture screenshot with descriptive label
        screenshot_path = await BrowserSession.screenshot(page, "homepage")
        print(f"Screenshot saved to: {screenshot_path}")
```

### Session Reuse

```python
async def reuse_example():
    # First operation
    async with BrowserSession.new_page() as page1:
        await page1.goto("https://example.com")
    
    # Second operation reuses the same browser instance
    async with BrowserSession.new_page() as page2:
        await page2.goto("https://example.org")
```

## Configuration

Browser behavior is controlled via environment variables or `.env` file:

```bash
# Enable browser fallback (default: false)
USE_BROWSER_FALLBACK=true

# Run browser in headless mode (default: true)
BROWSER_HEADLESS=true
```

## Architecture

### Singleton Pattern

The `BrowserSession` class uses the singleton pattern to ensure only one browser instance exists:

```python
class BrowserSession:
    _instance: Optional["BrowserSession"] = None
    _browser: Optional[Browser] = None
    
    def __new__(cls) -> "BrowserSession":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

### Session Lifecycle

1. **Creation**: Browser is launched on first `get_browser()` call
2. **Reuse**: Subsequent calls return the existing browser instance
3. **Timeout**: After 30 minutes of inactivity, the session is terminated
4. **Cleanup**: Browser and Playwright resources are properly closed

### Context Isolation

Each `new_page()` call creates an isolated browser context:

- Separate cookies and storage
- Independent page state
- Automatic cleanup after use

```python
@asynccontextmanager
async def new_page(cls) -> AsyncIterator[Page]:
    browser = await cls.get_browser()
    context = await browser.new_context()
    page = await context.new_page()
    
    try:
        yield page
    finally:
        await page.close()
        await context.close()
```

## Screenshot Storage

Screenshots are saved to `./data/screenshots/` with the following naming convention:

```
{timestamp}_{label}.png
```

Example: `20240314_153045_homepage.png`

## Error Handling

All browser operations raise `BrowserError` on failure:

```python
from aise.core.exceptions import BrowserError

try:
    async with BrowserSession.new_page() as page:
        await page.goto("https://example.com")
except BrowserError as e:
    print(f"Browser operation failed: {e}")
```

## Performance Considerations

### Session Timeout

The 30-minute timeout balances resource usage with performance:

- **Pros**: Reduces memory usage, prevents resource leaks
- **Cons**: Requires browser relaunch after timeout

### Context Isolation

Each operation gets a fresh context:

- **Pros**: Prevents state leakage between operations
- **Cons**: Slight overhead for context creation

### Browser Reuse

Reusing the browser instance improves performance:

- **First operation**: ~2-3 seconds (browser launch)
- **Subsequent operations**: ~100-200ms (context creation only)

## Testing

Unit tests verify all functionality:

```bash
poetry run pytest tests/unit/test_browser_session.py -v
```

Test coverage includes:

- Singleton pattern enforcement
- Browser creation and reuse
- Session timeout handling
- Context manager cleanup
- Screenshot capture
- Error handling
- Headless/headed mode switching

## Integration with Browser Drivers

The `BrowserSession` class is used by platform-specific drivers:

```python
from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.zendesk_driver import ZendeskBrowserDriver

async def zendesk_example():
    driver = ZendeskBrowserDriver()
    
    async with BrowserSession.new_page() as page:
        await driver.login(page, email, password)
        await driver.open_ticket(page, ticket_id)
        body = await driver.read_ticket_body(page)
```

## Troubleshooting

### Browser Launch Failures

If browser fails to launch:

1. Ensure Playwright browsers are installed:
   ```bash
   playwright install chromium
   ```

2. Check system dependencies:
   ```bash
   playwright install-deps
   ```

3. Verify configuration:
   ```bash
   aise config show | grep BROWSER
   ```

### Screenshot Failures

If screenshots fail to save:

1. Ensure `./data/screenshots/` directory exists and is writable
2. Check disk space availability
3. Verify page is fully loaded before capturing

### Session Timeout Issues

If sessions timeout too frequently:

1. Adjust timeout in `BrowserSession._session_timeout`
2. Consider implementing session keep-alive for long-running operations

## Security Considerations

- Browser runs in isolated contexts to prevent state leakage
- Screenshots may contain sensitive information - handle appropriately
- Headless mode recommended for production to reduce attack surface
- Browser automation should only be used when `USE_BROWSER_FALLBACK=true`

## Future Enhancements

Potential improvements for future releases:

- Configurable session timeout via environment variable
- Support for multiple browser types (Firefox, WebKit)
- Browser pool for parallel operations
- Automatic retry on browser crashes
- Screenshot compression and cleanup policies
- Browser performance metrics collection

## References

- [Playwright Documentation](https://playwright.dev/python/)
- [Design Document - Browser Automation](../design.md#component-6-browser-automation)
- [Requirements - Requirement 11](../requirements.md#requirement-11-browser-automation-fallback)
