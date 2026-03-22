# aise/agents/state.py
"""Agent state management with TypedDict definitions.

This module defines the AiSEState TypedDict and related data models used
throughout the agent graph execution.

Example usage:
    >>> from aise.agents.state import AiSEState
    >>> from datetime import datetime
    >>> 
    >>> state = AiSEState(
    ...     ticket_id=None,
    ...     ticket=None,
    ...     messages=[{"role": "user", "content": "Why is my pod crashing?"}],
    ...     diagnosis=None,
    ...     ticket_analysis=None,
    ...     actions_taken=[],
    ...     tool_results=[],
    ...     pending_approval=None,
    ...     knowledge_context=[],
    ...     user_style_context=None,
    ...     mode="interactive",
    ...     created_at=datetime.utcnow().isoformat(),
    ...     updated_at=datetime.utcnow().isoformat()
    ... )
"""

from typing import TypedDict, List, Optional, Literal, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AiSEState(TypedDict):
    """Global state for agent graph execution.
    
    This state is passed through the agent graph and updated by each agent.
    Agents must never mutate the input state - they should return a new
    state object with updates.
    
    Attributes:
        ticket_id: Optional ticket ID being processed
        ticket: Optional Ticket object with full ticket data
        messages: Conversation messages [{"role": "user", "content": "..."}]
        diagnosis: Generated diagnosis text
        ticket_analysis: Structured ticket analysis results
        actions_taken: List of actions performed (for audit trail)
        tool_results: Results from tool executions
        pending_approval: Pending action awaiting approval (approval mode)
        knowledge_context: Retrieved documentation chunks
        user_style_context: User communication style guidance
        mode: Operational mode (interactive, approval, autonomous)
        created_at: ISO timestamp when state was created
        updated_at: ISO timestamp when state was last updated
    """
    
    # Ticket context
    ticket_id: Optional[str]
    ticket: Optional['Ticket']
    
    # Conversation
    messages: List[Dict[str, str]]  # [{"role": "user", "content": "..."}]
    
    # Analysis results
    diagnosis: Optional[str]
    ticket_analysis: Optional['TicketAnalysis']
    
    # Actions
    actions_taken: List[str]
    tool_results: List['ToolResult']
    pending_approval: Optional[Dict[str, Any]]
    
    # Context
    knowledge_context: List['DocumentChunk']
    user_style_context: Optional[str]
    
    # Configuration
    mode: Literal["interactive", "approval", "autonomous"]
    
    # Metadata
    created_at: str  # ISO format timestamp
    updated_at: str  # ISO format timestamp


class TicketStatus(Enum):
    """Ticket status enumeration."""
    OPEN = "open"
    PENDING = "pending"
    SOLVED = "solved"
    CLOSED = "closed"


@dataclass
class Message:
    """A message in a ticket thread.
    
    Attributes:
        id: Unique message identifier
        author: Message author name or email
        body: Message content
        is_customer: True if message is from customer
        created_at: When message was created
    """
    id: str
    author: str
    body: str
    is_customer: bool
    created_at: datetime


@dataclass
class Ticket:
    """A support ticket.
    
    Attributes:
        id: Unique ticket identifier
        subject: Ticket subject line
        body: Initial ticket body
        customer_email: Customer email address
        status: Current ticket status
        tags: List of tags applied to ticket
        created_at: When ticket was created
        updated_at: When ticket was last updated
        thread: List of messages in chronological order
    """
    id: str
    subject: str
    body: str
    customer_email: str
    status: TicketStatus
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    thread: List[Message]


@dataclass
class TicketAnalysis:
    """Structured analysis of a ticket.
    
    Attributes:
        category: Ticket category (e.g., "compute", "networking", "storage")
        severity: Severity level (e.g., "low", "medium", "high", "critical")
        affected_service: Primary affected service (e.g., "EC2", "S3", "RDS")
        suggested_tags: Suggested tags for the ticket
        confidence: Confidence score (0.0 to 1.0)
    """
    category: str
    severity: str
    affected_service: str
    suggested_tags: List[str]
    confidence: float


@dataclass
class DocumentChunk:
    """A chunk of documentation with embeddings.
    
    Attributes:
        id: Unique chunk identifier (hash of content + source_url)
        content: Markdown text content
        metadata: Additional metadata (source, section, etc.)
        source_url: Original documentation URL
        heading_context: Parent headings for context
        embedding: Optional embedding vector
        created_at: ISO timestamp when chunk was created
    """
    id: str
    content: str
    metadata: Dict[str, Any]
    source_url: str
    heading_context: str
    embedding: Optional[List[float]] = None
    created_at: Optional[str] = None


@dataclass
class ToolResult:
    """Result from a tool execution.
    
    Attributes:
        tool_name: Name of the tool executed
        command: Command that was executed
        stdout: Standard output from command
        stderr: Standard error from command
        exit_code: Exit code (0 for success)
        duration_seconds: Execution duration
        timestamp: ISO timestamp when tool was executed
    """
    tool_name: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float
    timestamp: str


def create_initial_state(
    messages: List[Dict[str, str]],
    mode: Literal["interactive", "approval", "autonomous"] = "interactive",
    ticket_id: Optional[str] = None
) -> AiSEState:
    """Create an initial AiSEState with default values.
    
    Args:
        messages: Initial conversation messages
        mode: Operational mode
        ticket_id: Optional ticket ID
    
    Returns:
        AiSEState with default values
    """
    now = datetime.utcnow().isoformat()
    
    return AiSEState(
        ticket_id=ticket_id,
        ticket=None,
        messages=messages,
        diagnosis=None,
        ticket_analysis=None,
        actions_taken=[],
        tool_results=[],
        pending_approval=None,
        knowledge_context=[],
        user_style_context=None,
        mode=mode,
        created_at=now,
        updated_at=now
    )


def update_state(state: AiSEState, **updates) -> AiSEState:
    """Create a new state with updates (immutable update).
    
    Args:
        state: Current state
        **updates: Fields to update
    
    Returns:
        New AiSEState with updates applied
    """
    # Create a copy of the state
    new_state = state.copy()
    
    # Update timestamp
    new_state["updated_at"] = datetime.utcnow().isoformat()
    
    # Apply updates — raise on unknown keys to catch typos early
    for key, value in updates.items():
        if key not in new_state:
            raise KeyError(f"update_state: unknown state key '{key}'")
        new_state[key] = value
    
    return new_state
