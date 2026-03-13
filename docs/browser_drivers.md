# Browser Drivers Documentation

## Overview

The browser drivers provide platform-specific automation for Zendesk and Freshdesk ticket systems. These drivers use Playwright browser automation as a fallback when APIs are unavailable or rate-limited.

## Architecture

```
┌─────────────────────────────────────────┐
│         Browser Drivers                 │
├─────────────────────────────────────────┤
│  ZendeskBrowserDriver                   │
│  FreshdeskBrowserDriver                 │
└──────────────┬──────────────────────────┘
               │
               ├─ Uses BrowserActions (primitives)
               ├─ Uses BrowserSession (lifecycle)
               └─ Uses Config (URLs, credentials)
```

## Components

### ZendeskBrowserDriver

Platform-specific driver for Zendesk ticket automation.

**Features:**
- Login with email/API token authentication
- Navigate to specific tickets
- Read ticket body content
- Submit replies
- Update ticket status

**Configuration:**
```bash
# Option 1: Full URL
ZENDESK_URL=https://mycompany.zendesk.com

# Option 2: Subdomain (will construct URL)
ZENDESK_SUBDOMAIN=mycompany

# Credentials
ZENDESK_EMAIL=admin@mycompany.com
ZENDESK_API_TOKEN=your_api_token_here
```

**Usage:**
```python
from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.zendesk_driver import ZendeskBrowserDriver

driver = ZendeskBrowserDriver()

# Use authenticated session with caching
session_key = f"zendesk:{driver.config.ZENDESK_EMAIL}"

async def login_callback(page):
    await driver.login(page)

async with BrowserSession.authenticated_page(session_key, login_callback) as page:
    # Open ticket
    await driver.open_ticket(page, "12345")
    
    # Read content
    body = await driver.read_ticket_body(page)
    
    # Submit reply
    await driver.submit_reply(page, "Thank you for contacting support.")
    
    # Update status
    await driver.set_ticket_status(page, "pending")
```

### FreshdeskBrowserDriver

Platform-specific driver for Freshdesk ticket automation.

**Features:**
- Login with domain/API key authentication
- Navigate to specific tickets
- Read ticket body content
- Submit replies
- Update ticket status

**Configuration:**
```bash
# Option 1: Full URL
FRESHDESK_URL=https://mycompany.freshdesk.com

# Option 2: Domain (will construct URL)
FRESHDESK_DOMAIN=mycompany

# Credentials
FRESHDESK_API_KEY=your_api_key_here
```

**Usage:**
```python
from aise.browser_operator.browser import BrowserSession
from aise.browser_operator.freshdesk_driver import FreshdeskBrowserDriver

driver = FreshdeskBrowserDriver()

# Use authenticated session with caching
session_key = f"freshdesk:{driver.config.FRESHDESK_DOMAIN}"

async def login_callback(page):
    await driver.login(page)

async with BrowserSession.authenticated_page(session_key, login_callback) as page:
    # Open ticket
    await driver.open_ticket(page, "67890")
    
    # Read content
    body = await driver.read_ticket_body(page)
    
    # Submit reply
    await driver.submit_reply(page, "We're investigating this issue.")
    
    # Update status
    await driver.set_ticket_status(page, "pending")
```

## Session Caching

Both drivers leverage `BrowserSession.authenticated_page()` for login session caching:

**Benefits:**
- Login performed once, reused for 30 minutes
- Faster subsequent operations
- Reduced authentication overhead
- Automatic session cleanup

**Example:**
```python
session_key = "zendesk:admin@example.com"

async def login_callback(page):
    await driver.login(page)

# First operation - performs login
async with BrowserSession.authenticated_page(session_key, login_callback) as page:
    await driver.open_ticket(page, "12345")

# Second operation - reuses cached session (no login)
async with BrowserSession.authenticated_page(session_key, login_callback) as page:
    await driver.open_ticket(page, "67890")
```

## Error Handling

All driver methods include comprehensive error handling:

**Error Types:**
- `BrowserError`: Base exception for browser operations
- Configuration errors (missing URL/credentials)
- Navigation failures
- Element not found errors
- Timeout errors

**Error Recovery:**
- Automatic retries (configured in BrowserActions)
- Screenshot capture on errors
- Detailed error logging
- Graceful degradation

**Example:**
```python
from aise.core.exceptions import BrowserError

try:
    await driver.submit_reply(page, message)
except BrowserError as e:
    logger.error(f"Reply failed: {e}")
    # Screenshot automatically captured at:
    # ./data/screenshots/{timestamp}_error.png
```

## Screenshots

Screenshots are automatically captured at key steps:

**Capture Points:**
- Before/after login
- After opening ticket
- Before/after submitting reply
- After status updates
- On any error

**Location:** `./data/screenshots/`

**Naming:** `{timestamp}_{label}.png`

**Example:**
```
./data/screenshots/
├── 20240115_143022_zendesk_login_page.png
├── 20240115_143025_zendesk_logged_in.png
├── 20240115_143030_zendesk_ticket_12345.png
├── 20240115_143035_zendesk_reply_before_submit.png
└── 20240115_143037_zendesk_reply_submitted.png
```

## Platform-Specific Selectors

### Zendesk Selectors

```python
# Navigation
'[data-garden-id="chrome.nav"]'  # Main navigation

# Ticket
'[data-test-id="ticket-conversation"]'  # Conversation thread
'[data-test-id="comment-body"]'  # Comment body
'[data-test-id="comment-input"]'  # Reply input
'[data-test-id="submit-button"]'  # Submit button

# Status
'[data-test-id="ticket-status-select"]'  # Status dropdown
'[data-test-id="status-option-{status}"]'  # Status option
```

### Freshdesk Selectors

```python
# Navigation
'#global-nav'  # Main navigation

# Ticket
'#ticket-details'  # Ticket details container
'.thread-conv .thread-message-body'  # Message body
'#reply-editor'  # Reply editor
'button[data-test-id="submit-reply"]'  # Submit button

# Status
'#ticket-status-select'  # Status dropdown
```

## Best Practices

### 1. Use Session Caching

Always use `authenticated_page()` context manager for session reuse:

```python
# ✓ Good - uses session caching
async with BrowserSession.authenticated_page(session_key, login_callback) as page:
    await driver.open_ticket(page, ticket_id)

# ✗ Bad - creates new session every time
async with BrowserSession.new_page() as page:
    await driver.login(page)
    await driver.open_ticket(page, ticket_id)
```

### 2. Handle Errors Gracefully

Always catch and handle `BrowserError`:

```python
try:
    await driver.submit_reply(page, message)
except BrowserError as e:
    logger.error(f"Browser operation failed: {e}")
    # Fall back to API or queue for retry
```

### 3. Configure Timeouts

Adjust timeouts for slow networks:

```python
# Default timeout: 60 seconds
await driver.open_ticket(page, ticket_id)

# Custom timeout via BrowserActions
driver.actions.DEFAULT_TIMEOUT = 120000  # 120 seconds
```

### 4. Enable Browser Fallback

Configure when to use browser automation:

```bash
# Enable browser fallback
USE_BROWSER_FALLBACK=true

# Run in headed mode for debugging
BROWSER_HEADLESS=false
```

### 5. Monitor Screenshots

Check screenshots directory for debugging:

```bash
# View recent screenshots
ls -lt ./data/screenshots/ | head -10

# Clean old screenshots
find ./data/screenshots/ -mtime +7 -delete
```

## Troubleshooting

### Login Fails

**Symptoms:** Login page loads but authentication fails

**Solutions:**
1. Verify credentials in `.env`
2. Check if 2FA is enabled (not supported)
3. Run in headed mode to see errors: `BROWSER_HEADLESS=false`
4. Check screenshots in `./data/screenshots/`

### Selectors Not Found

**Symptoms:** `BrowserError: Element not found`

**Solutions:**
1. Platform UI may have changed - update selectors
2. Increase timeout: `driver.actions.DEFAULT_TIMEOUT = 120000`
3. Check if page fully loaded
4. Verify ticket ID is valid

### Session Expired

**Symptoms:** Operations fail after 30 minutes

**Solutions:**
1. Session cache automatically expires after 30 minutes
2. Next operation will re-authenticate automatically
3. Adjust timeout: `BrowserSession._context_timeout = timedelta(minutes=60)`

### Screenshots Not Captured

**Symptoms:** No screenshots in `./data/screenshots/`

**Solutions:**
1. Ensure directory exists: `mkdir -p ./data/screenshots`
2. Check write permissions
3. Verify `BrowserSession.screenshot()` is called

## Requirements Mapping

### Requirement 11.6: Platform-specific drivers
- ✓ ZendeskBrowserDriver implemented
- ✓ FreshdeskBrowserDriver implemented
- ✓ Uses BrowserActions primitives
- ✓ Uses BrowserSession for lifecycle

### Requirement 5.1: Zendesk integration
- ✓ Login with email/API token
- ✓ Navigate to tickets
- ✓ Read ticket content
- ✓ Submit replies
- ✓ Update status

### Requirement 5.2: Freshdesk integration
- ✓ Login with domain/API key
- ✓ Navigate to tickets
- ✓ Read ticket content
- ✓ Submit replies
- ✓ Update status

### Requirement 5.4: Browser fallback
- ✓ USE_BROWSER_FALLBACK configuration
- ✓ Automatic fallback on API failure
- ✓ Session caching for performance
- ✓ Screenshot capture for debugging

## See Also

- [Browser Session Documentation](./browser_session.md)
- [Browser Actions Documentation](./browser_actions.md)
- [Configuration Guide](./configuration.md)
- [Examples](../examples/browser_drivers_example.py)
