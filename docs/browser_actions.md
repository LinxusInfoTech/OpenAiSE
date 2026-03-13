# Browser Actions Documentation

## Overview

The `BrowserActions` class provides low-level browser action primitives with built-in error handling, retry logic, and timeout enforcement. These primitives are used by platform-specific browser drivers to automate interactions with web-based ticket systems.

## Requirements Addressed

- **11.6**: Browser operations with error handling
- **11.9**: Support headless and headed modes via configuration
- **11.10**: Cache login sessions for 30 minutes

## Architecture

```
BrowserActions (primitives)
    ↓
Platform Drivers (Zendesk, Freshdesk)
    ↓
BrowserAgent (high-level automation)
```

## BrowserActions Class

### Features

- **Automatic Retries**: All operations retry up to 3 times by default on failure
- **Timeout Enforcement**: 60-second default timeout for all operations
- **Error Handling**: Comprehensive error handling with structured logging
- **Selector Flexibility**: Click operations support both CSS selectors and text content

### Methods

#### navigate(page, url, timeout=None, retries=3)

Navigate to a URL with retry logic.

```python
from aise.browser_operator.actions import BrowserActions
from aise.browser_operator.browser import BrowserSession

actions = BrowserActions()

async with BrowserSession.new_page() as page:
    await actions.navigate(page, "https://example.com")
```

**Parameters:**
- `page`: Playwright page instance
- `url`: Target URL to navigate to
- `timeout`: Navigation timeout in milliseconds (default: 60000)
- `retries`: Number of retry attempts on failure (default: 3)

**Raises:**
- `BrowserError`: If navigation fails after all retries

#### click(page, selector_or_text, timeout=None, retries=3)

Click an element by CSS selector or text content.

```python
# Click by selector
await actions.click(page, "#submit-button")

# Click by text content
await actions.click(page, "Submit")
```

**Parameters:**
- `page`: Playwright page instance
- `selector_or_text`: CSS selector or text content to click
- `timeout`: Click timeout in milliseconds (default: 60000)
- `retries`: Number of retry attempts on failure (default: 3)

**Behavior:**
- First attempts to click using CSS selector
- Falls back to text-based selection if selector fails

**Raises:**
- `BrowserError`: If click fails after all retries

#### fill(page, selector, value, timeout=None, retries=3)

Fill an input field with text.

```python
await actions.fill(page, "#email", "user@example.com")
await actions.fill(page, "#password", "secret123")
```

**Parameters:**
- `page`: Playwright page instance
- `selector`: CSS selector for input field
- `value`: Text value to fill
- `timeout`: Fill timeout in milliseconds (default: 60000)
- `retries`: Number of retry attempts on failure (default: 3)

**Raises:**
- `BrowserError`: If fill fails after all retries

#### wait_for_selector(page, selector, timeout=None, retries=3)

Wait for an element to appear in the DOM.

```python
await actions.wait_for_selector(page, "#content-loaded")
```

**Parameters:**
- `page`: Playwright page instance
- `selector`: CSS selector to wait for
- `timeout`: Wait timeout in milliseconds (default: 60000)
- `retries`: Number of retry attempts on failure (default: 3)

**Raises:**
- `BrowserError`: If element doesn't appear after all retries

#### get_text(page, selector, timeout=None, retries=3)

Get text content from an element.

```python
ticket_body = await actions.get_text(page, ".ticket-body")
```

**Parameters:**
- `page`: Playwright page instance
- `selector`: CSS selector for element
- `timeout`: Operation timeout in milliseconds (default: 60000)
- `retries`: Number of retry attempts on failure (default: 3)

**Returns:**
- `str`: Text content of the element (stripped of whitespace)

**Raises:**
- `BrowserError`: If text retrieval fails after all retries

## Session Caching

### Overview

The `BrowserSession` class now supports caching authenticated browser contexts to avoid repeated logins. Cached sessions are automatically expired after 30 minutes of inactivity.

### authenticated_page Context Manager

Use the `authenticated_page` context manager to work with cached authenticated sessions:

```python
from aise.browser_operator.browser import BrowserSession

async def login(page):
    """Perform login actions."""
    await page.goto("https://example.com/login")
    await page.fill("#email", "user@example.com")
    await page.fill("#password", "secret")
    await page.click("#submit")
    await page.wait_for_selector("#dashboard")

# First call - performs login and caches session
async with BrowserSession.authenticated_page("example:user", login) as page:
    await page.goto("https://example.com/tickets")
    # ... perform operations ...

# Second call - reuses cached session (no login needed)
async with BrowserSession.authenticated_page("example:user", login) as page:
    await page.goto("https://example.com/tickets/123")
    # ... perform operations ...
```

### Session Key Format

Session keys should uniquely identify the authenticated session:

```python
# Format: "platform:username"
session_key = f"zendesk:{email}"
session_key = f"freshdesk:{email}"
```

### Cache Management

#### Manual Cache Operations

```python
# Get cached context
context = await BrowserSession.get_cached_context("zendesk:user@example.com")

# Cache a context
await BrowserSession.cache_context("zendesk:user@example.com", context)

# Clear specific cached context
await BrowserSession._clear_cached_context("zendesk:user@example.com")

# Clear all cached contexts
await BrowserSession._clear_all_cached_contexts()
```

#### Automatic Expiration

- Cached contexts expire after 30 minutes of inactivity
- Expired contexts are automatically cleaned up (cookies cleared, context closed)
- When a cached context is retrieved, its timestamp is checked
- If expired, the context is removed and `None` is returned

## Error Handling

### Retry Logic

All browser actions implement exponential backoff retry logic:

1. First attempt fails → wait 1 second
2. Second attempt fails → wait 1 second
3. Third attempt fails → raise `BrowserError`

### Timeout Enforcement

All operations enforce a 60-second timeout by default:

```python
# Use default 60-second timeout
await actions.navigate(page, url)

# Use custom timeout (30 seconds)
await actions.navigate(page, url, timeout=30000)
```

### Error Types

- `PlaywrightTimeoutError`: Operation timed out (triggers retry)
- `BrowserError`: Operation failed after all retries (raised to caller)

## Logging

All browser actions emit structured logs:

```python
# Success logs
logger.info("browser_navigate_success", url=url)
logger.debug("browser_click_success", selector=selector)

# Warning logs (retries)
logger.warning("browser_navigate_timeout", url=url, attempt=2, retries=3)

# Error logs (final failure)
logger.error("browser_navigate_error", url=url, error=str(e))
```

## Best Practices

### 1. Use Appropriate Timeouts

```python
# Quick operations - shorter timeout
await actions.click(page, "#button", timeout=10000)

# Slow page loads - longer timeout
await actions.navigate(page, url, timeout=90000)
```

### 2. Handle Errors Gracefully

```python
from aise.core.exceptions import BrowserError

try:
    await actions.navigate(page, url)
except BrowserError as e:
    logger.error("navigation_failed", error=str(e))
    # Fall back to API or retry later
```

### 3. Use Session Caching for Repeated Operations

```python
# Good - reuses authenticated session
async with BrowserSession.authenticated_page(session_key, login) as page:
    for ticket_id in ticket_ids:
        await page.goto(f"https://example.com/tickets/{ticket_id}")
        # ... process ticket ...

# Bad - logs in for each ticket
for ticket_id in ticket_ids:
    async with BrowserSession.new_page() as page:
        await login(page)  # Unnecessary repeated login
        await page.goto(f"https://example.com/tickets/{ticket_id}")
```

### 4. Clean Up Resources

```python
# Context manager handles cleanup automatically
async with BrowserSession.authenticated_page(session_key, login) as page:
    # ... operations ...
# Page is automatically closed here
```

## Testing

### Unit Tests

Mock Playwright page objects for unit testing:

```python
from unittest.mock import AsyncMock
from aise.browser_operator.actions import BrowserActions

async def test_navigate():
    actions = BrowserActions()
    mock_page = AsyncMock()
    
    await actions.navigate(mock_page, "https://example.com")
    
    mock_page.goto.assert_called_once()
```

### Integration Tests

Use real browser instances for integration testing:

```python
from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.actions import BrowserActions

async def test_real_navigation():
    actions = BrowserActions()
    
    async with BrowserSession.new_page() as page:
        await actions.navigate(page, "https://example.com")
        title = await page.title()
        assert "Example" in title
```

## Configuration

Browser behavior is controlled via configuration:

```python
# .env file
BROWSER_HEADLESS=true  # Run in headless mode
USE_BROWSER_FALLBACK=true  # Enable browser automation
```

See [Configuration Documentation](configuration.md) for details.

## Related Documentation

- [Browser Session Management](browser_session.md)
- [Platform-Specific Drivers](browser_drivers.md) (coming soon)
- [Browser Agent](browser_agent.md) (coming soon)
