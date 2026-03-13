# Browser Agent Documentation

## Overview

The Browser Agent provides high-level browser automation for ticket operations when APIs are unavailable. It orchestrates platform-specific drivers (Zendesk, Freshdesk) and provides automatic fallback logic when ticket API operations fail.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Browser Agent                          │
│  - Routes operations to platform drivers                    │
│  - Manages authenticated sessions                           │
│  - Captures screenshots for observability                   │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Zendesk    │   │  Freshdesk   │   │   Browser    │
│   Driver     │   │   Driver     │   │   Session    │
└──────────────┘   └──────────────┘   └──────────────┘
```

## Requirements Satisfied

- **11.1**: Browser automation as fallback when APIs unavailable
- **11.2**: Automatic fallback when API fails and USE_BROWSER_FALLBACK=true
- **11.5**: Capture screenshots for observability
- **11.6**: Platform-specific drivers for Zendesk and Freshdesk
- **11.8**: Log fallback events
- **11.12**: Only invoke when API fails and fallback enabled

## Components

### BrowserAgent

High-level orchestrator for browser automation operations.

**Key Features:**
- Routes operations to platform-specific drivers
- Manages authenticated browser sessions with caching
- Captures screenshots for debugging
- Provides error handling and logging

**Supported Platforms:**
- Zendesk
- Freshdesk

**Supported Actions:**
- `get`: Retrieve ticket details
- `reply`: Post reply to ticket
- `close`: Close/solve ticket
- `add_tags`: Add tags to ticket (not implemented via browser)

### Browser Fallback Logic

Automatic fallback mechanism that detects API failures and retries using browser automation.

**Key Features:**
- Transparent fallback when API fails
- Respects USE_BROWSER_FALLBACK configuration
- Logs all fallback events
- Handles both API and browser failures

## Usage

### Basic Usage

```python
from aise.agents.browser_agent import BrowserAgent

# Initialize agent
agent = BrowserAgent()

# Execute action
result = await agent.execute_action(
    platform="zendesk",
    action="reply",
    params={
        "ticket_id": "123",
        "message": "Thank you for contacting support..."
    }
)

print(f"Screenshot: {result['screenshot']}")
```

### With Automatic Fallback

```python
from aise.ticket_system.browser_fallback import with_browser_fallback
from aise.ticket_system.zendesk import ZendeskProvider

# Create provider
provider = ZendeskProvider(
    subdomain="mycompany",
    email="admin@example.com",
    api_token="token"
)

# Execute with automatic fallback
result = await with_browser_fallback(
    platform="zendesk",
    action="reply",
    api_func=provider.reply,
    ticket_id="123",
    message="Hello"
)
```

### LangGraph Integration

The Browser Agent is automatically integrated into the LangGraph workflow:

```python
from aise.agents.graph import AiSEGraph
from aise.core.config import get_config

config = get_config()
graph = AiSEGraph.from_config(config, llm_router)

# Browser agent is automatically used when:
# 1. USE_BROWSER_FALLBACK=true
# 2. API operation fails
# 3. Error is retryable (not 404)
```

## Configuration

### Environment Variables

```bash
# Enable browser fallback
USE_BROWSER_FALLBACK=true

# Browser mode (headless or headed)
BROWSER_HEADLESS=true

# Zendesk configuration
ZENDESK_SUBDOMAIN=mycompany
ZENDESK_EMAIL=admin@example.com
ZENDESK_API_TOKEN=your_token

# Freshdesk configuration
FRESHDESK_DOMAIN=mycompany.freshdesk.com
FRESHDESK_API_KEY=your_key
```

### Fallback Behavior

The browser fallback is triggered when:

1. **USE_BROWSER_FALLBACK=true** in configuration
2. **API operation fails** with TicketAPIError
3. **Error is retryable** (not 404 Not Found)

The fallback is **NOT** triggered when:

- Browser fallback is disabled in config
- No API error occurred
- Error is 404 (ticket not found)
- Error is not a TicketAPIError

## Action Details

### Get Ticket

Retrieves ticket details via browser.

**Parameters:**
- `ticket_id`: Ticket ID to retrieve

**Returns:**
```python
{
    "ticket_id": "123",
    "body": "Ticket content...",
    "screenshot": "/path/to/screenshot.png",
    "success": True
}
```

**Example:**
```python
result = await agent.execute_action(
    platform="zendesk",
    action="get",
    params={"ticket_id": "123"}
)
```

### Reply to Ticket

Posts a reply to a ticket via browser.

**Parameters:**
- `ticket_id`: Ticket ID to reply to
- `message`: Reply message content

**Returns:**
```python
{
    "ticket_id": "123",
    "message_length": 150,
    "screenshot": "/path/to/screenshot.png",
    "success": True
}
```

**Example:**
```python
result = await agent.execute_action(
    platform="zendesk",
    action="reply",
    params={
        "ticket_id": "123",
        "message": "Thank you for contacting support..."
    }
)
```

### Close Ticket

Closes/solves a ticket via browser.

**Parameters:**
- `ticket_id`: Ticket ID to close

**Returns:**
```python
{
    "ticket_id": "123",
    "status": "solved",
    "screenshot": "/path/to/screenshot.png",
    "success": True
}
```

**Example:**
```python
result = await agent.execute_action(
    platform="zendesk",
    action="close",
    params={"ticket_id": "123"}
)
```

### Add Tags

**Note:** Tag management via browser is not currently implemented due to complexity and fragility of UI interactions. Use API for tag operations.

## Session Management

The Browser Agent uses authenticated session caching to improve performance:

- **Session Key**: `{platform}:{email}`
- **Cache Duration**: 30 minutes
- **Reuse**: Subsequent operations reuse cached sessions
- **Cleanup**: Sessions are automatically cleaned up after timeout

## Screenshots

All browser operations capture screenshots for debugging and observability:

- **Location**: `./data/screenshots/`
- **Format**: `{timestamp}_{label}.png`
- **Full Page**: Screenshots capture the entire page

**Example Screenshot Names:**
- `20240115_143022_zendesk_login_page.png`
- `20240115_143025_zendesk_ticket_123.png`
- `20240115_143030_zendesk_reply_submitted.png`

## Error Handling

### API Failure → Browser Fallback

```python
try:
    # Try API first
    await provider.reply(ticket_id, message)
except TicketAPIError as e:
    # Automatic browser fallback
    logger.warning("api_failed_attempting_browser_fallback")
    result = await browser_agent.execute_action(...)
```

### Both API and Browser Fail

```python
try:
    await with_browser_fallback(...)
except TicketAPIError as e:
    # Both failed - error includes both failures
    logger.error("both_api_and_browser_failed")
    # TODO: Queue for retry
```

## Logging

The Browser Agent provides comprehensive structured logging:

```python
# Action start
logger.info("browser_action_start", 
    platform="zendesk",
    action="reply",
    ticket_id="123"
)

# Fallback triggered
logger.warning("api_failed_attempting_browser_fallback",
    platform="zendesk",
    action="reply",
    api_error="Connection timeout"
)

# Action complete
logger.info("browser_action_complete",
    platform="zendesk",
    action="reply",
    ticket_id="123"
)

# Screenshot captured
logger.info("screenshot_captured",
    label="zendesk_reply_submitted",
    path="./data/screenshots/20240115_143030_zendesk_reply_submitted.png"
)
```

## Testing

### Unit Tests

```bash
# Test browser agent
poetry run pytest tests/unit/test_browser_agent.py -v

# Test browser fallback logic
poetry run pytest tests/unit/test_browser_fallback.py -v
```

### Integration Tests (Optional)

Integration tests require a real browser and test credentials:

```bash
# Set test credentials
export ZENDESK_SUBDOMAIN=test
export ZENDESK_EMAIL=test@example.com
export ZENDESK_API_TOKEN=test_token

# Run integration tests
poetry run pytest tests/integration/test_browser_integration.py -v
```

## Limitations

1. **Tag Management**: Adding tags via browser is not implemented due to UI complexity
2. **Platform Support**: Currently only Zendesk and Freshdesk are supported
3. **Browser Dependency**: Requires Playwright and browser binaries
4. **Performance**: Browser operations are slower than API calls
5. **Fragility**: UI changes can break browser automation

## Best Practices

1. **Use API First**: Always prefer API over browser automation
2. **Enable Fallback**: Set USE_BROWSER_FALLBACK=true for resilience
3. **Monitor Screenshots**: Review screenshots when debugging issues
4. **Session Caching**: Leverage session caching for performance
5. **Error Handling**: Handle both API and browser failures gracefully

## Troubleshooting

### Browser Fails to Launch

```bash
# Install Playwright browsers
poetry run playwright install chromium
```

### Login Fails

- Verify credentials in configuration
- Check if 2FA is enabled (not supported)
- Review login screenshot for errors

### Element Not Found

- UI may have changed - update driver selectors
- Check if page loaded completely
- Review screenshot for actual page state

### Session Timeout

- Sessions expire after 30 minutes
- New login will be performed automatically
- Check logs for session cache hits/misses

## Future Enhancements

1. **Retry Queue**: Implement retry queue for failed operations (Requirement 11.12)
2. **More Platforms**: Add support for Email, Slack ticket systems
3. **Tag Management**: Implement browser-based tag operations
4. **Performance**: Optimize session reuse and caching
5. **Observability**: Add metrics for fallback success rates
