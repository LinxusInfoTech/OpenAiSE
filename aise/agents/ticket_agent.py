# aise/agents/ticket_agent.py
"""Ticket classification agent.

This module implements the Ticket Agent, which classifies support tickets
by category, severity, and affected service using LLM-based analysis.

Example usage:
    >>> from aise.agents.ticket_agent import TicketAgent
    >>> from aise.ai_engine.router import LLMRouter
    >>> from aise.core.config import get_config
    >>> from aise.ticket_system.base import Ticket
    >>> 
    >>> config = get_config()
    >>> router = LLMRouter(config)
    >>> agent = TicketAgent(router)
    >>> 
    >>> analysis = await agent.classify(ticket)
    >>> print(f"Category: {analysis.category}, Severity: {analysis.severity}")
"""

import json
from typing import Dict, Any
import structlog

from aise.agents.state import TicketAnalysis
from aise.ticket_system.base import Ticket
from aise.ai_engine.router import LLMRouter
from aise.core.exceptions import ProviderError
from aise.observability.tracer import get_tracer, agent_span

logger = structlog.get_logger(__name__)


# System prompt for ticket classification
TICKET_CLASSIFICATION_PROMPT = """You are a ticket classification system for a cloud infrastructure support platform.

Your task is to analyze support tickets and extract structured metadata to help route and prioritize them.

Analyze the ticket and provide:
1. **category**: The primary category of the issue
   - "cloud_infra": Infrastructure, compute, networking, storage issues
   - "billing": Billing, pricing, cost-related questions
   - "access": Authentication, authorization, permissions, IAM issues
   - "general": General questions, documentation requests, other

2. **severity**: The urgency/impact level
   - "critical": System down, data loss, security breach, production outage
   - "high": Major functionality impaired, significant business impact
   - "medium": Partial functionality affected, workaround available
   - "low": Minor issue, cosmetic, feature request, general question

3. **affected_service**: The primary cloud service or component affected (e.g., "EC2", "S3", "RDS", "Kubernetes", "Lambda", "VPC", "IAM")
   - Use specific service names when identifiable
   - Use "unknown" if not clear from the ticket

4. **customer_context**: A brief 1-2 sentence summary of the customer's situation and what they're trying to accomplish

5. **suggested_tags**: 2-5 relevant tags for categorization (e.g., ["networking", "security-group", "connectivity"])

Respond ONLY with valid JSON in this exact format:
{
  "category": "cloud_infra",
  "severity": "high",
  "affected_service": "EC2",
  "customer_context": "Customer cannot connect to EC2 instance after security group changes",
  "suggested_tags": ["ec2", "networking", "security-group", "connectivity"]
}

Be precise and consistent. Base your classification on the actual content, not assumptions."""


class TicketAgent:
    """Ticket classification agent for analyzing and categorizing support tickets.
    
    The Ticket Agent uses LLM capabilities to classify tickets by category,
    severity, and affected service, and suggests relevant tags for organization.
    """
    
    def __init__(
        self,
        llm_router: LLMRouter,
        temperature: float = 0.3,
        max_tokens: int = 512,
    ):
        """Initialize Ticket Agent.
        
        Args:
            llm_router: LLM router for completion requests
            temperature: Sampling temperature for classification completions.
            max_tokens: Maximum tokens for classification completions.
        """
        self._llm = llm_router
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._tracer = get_tracer("aise.agents.ticket")
        logger.info("ticket_agent_initialized")
    
    async def classify(self, ticket: Ticket) -> TicketAnalysis:
        """Classify ticket and extract structured metadata.
        
        Preconditions:
        - ticket.subject and ticket.body are non-empty
        - LLM provider is available
        
        Postconditions:
        - Returns TicketAnalysis with valid category
        - severity is one of: critical, high, medium, low
        - suggested_tags is non-empty list
        
        Args:
            ticket: Ticket object to classify
        
        Returns:
            TicketAnalysis with classification results
        
        Raises:
            ProviderError: If LLM completion fails
            ValueError: If ticket data is invalid
        """
        if not ticket.subject or not ticket.body:
            raise ValueError("Ticket must have non-empty subject and body")
        
        logger.info(
            "ticket_classification_start",
            ticket_id=ticket.id,
            subject=ticket.subject[:100]
        )
        
        try:
            # Build classification prompt
            ticket_content = self._format_ticket_for_classification(ticket)
            
            messages = [
                {
                    "role": "user",
                    "content": f"Classify this support ticket:\n\n{ticket_content}"
                }
            ]
            
            with agent_span(
                self._tracer,
                "ticket_agent.classify",
                {
                    "agent.ticket_id": ticket.id,
                    "agent.subject_length": len(ticket.subject),
                },
            ) as span:
                # Get classification from LLM with structured output
                result = await self._llm.complete(
                    messages=messages,
                    system_prompt=TICKET_CLASSIFICATION_PROMPT,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens
                )
                
                # Parse JSON response
                classification_data = self._parse_classification_response(result.content)
                
                # Create TicketAnalysis object
                analysis = TicketAnalysis(
                    category=classification_data["category"],
                    severity=classification_data["severity"],
                    affected_service=classification_data["affected_service"],
                    suggested_tags=classification_data["suggested_tags"],
                    confidence=0.85
                )
                
                span.set_attribute("agent.category", analysis.category)
                span.set_attribute("agent.severity", analysis.severity)
                span.set_attribute("llm.tokens_used", result.usage.total_tokens)
            
            logger.info(
                "ticket_classification_success",
                ticket_id=ticket.id,
                category=analysis.category,
                severity=analysis.severity,
                affected_service=analysis.affected_service,
                tags_count=len(analysis.suggested_tags),
                tokens_used=result.usage.total_tokens,
                cost_usd=result.usage.estimated_cost_usd
            )
            
            return analysis
            
        except Exception as e:
            logger.error(
                "ticket_classification_failed",
                ticket_id=ticket.id,
                error=str(e)
            )
            raise ProviderError(f"Ticket classification failed: {str(e)}")
    
    def _format_ticket_for_classification(self, ticket: Ticket) -> str:
        """Format ticket data for classification prompt.
        
        Args:
            ticket: Ticket object
        
        Returns:
            Formatted ticket content string
        """
        # Include recent thread messages for context
        thread_context = ""
        if ticket.thread:
            recent_messages = ticket.thread[-3:]  # Last 3 messages
            thread_messages = []
            for msg in recent_messages:
                author_type = "Customer" if msg.is_customer else "Agent"
                thread_messages.append(f"{author_type}: {msg.body[:200]}")
            thread_context = "\n\nRecent conversation:\n" + "\n".join(thread_messages)
        
        return f"""Subject: {ticket.subject}

Description:
{ticket.body}

Customer: {ticket.customer_email}
Status: {ticket.status.value}
Existing tags: {', '.join(ticket.tags) if ticket.tags else 'none'}{thread_context}"""
    
    def _parse_classification_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM classification response into structured data.
        
        Args:
            response: LLM response string (expected to be JSON)
        
        Returns:
            Dictionary with classification data
        
        Raises:
            ValueError: If response is not valid JSON or missing required fields
        """
        try:
            # Try to extract JSON from response (handle cases where LLM adds extra text)
            response = response.strip()
            
            # Find JSON object in response
            start_idx = response.find('{')
            end_idx = response.rfind('}') + 1
            
            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON object found in response")
            
            json_str = response[start_idx:end_idx]
            data = json.loads(json_str)
            
            # Validate required fields
            required_fields = ["category", "severity", "affected_service", "suggested_tags"]
            for field in required_fields:
                if field not in data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Validate category
            valid_categories = ["cloud_infra", "billing", "access", "general"]
            if data["category"] not in valid_categories:
                logger.warning(
                    "invalid_category",
                    category=data["category"],
                    defaulting_to="general"
                )
                data["category"] = "general"
            
            # Validate severity
            valid_severities = ["critical", "high", "medium", "low"]
            if data["severity"] not in valid_severities:
                logger.warning(
                    "invalid_severity",
                    severity=data["severity"],
                    defaulting_to="medium"
                )
                data["severity"] = "medium"
            
            # Ensure suggested_tags is a list
            if not isinstance(data["suggested_tags"], list):
                data["suggested_tags"] = [str(data["suggested_tags"])]
            
            # Ensure at least one tag
            if not data["suggested_tags"]:
                data["suggested_tags"] = [data["category"]]
            
            return data
            
        except json.JSONDecodeError as e:
            logger.error(
                "classification_json_parse_failed",
                response=response[:200],
                error=str(e)
            )
            raise ValueError(f"Failed to parse classification response as JSON: {str(e)}")
        except Exception as e:
            logger.error(
                "classification_parse_failed",
                response=response[:200],
                error=str(e)
            )
            raise ValueError(f"Failed to parse classification response: {str(e)}")
