# aise/ticket_system/processor.py
"""Ticket processing workflow with classification integration.

This module implements the ticket processing workflow that integrates
the Ticket Agent for classification, Knowledge Agent for retrieval,
and Engineer Agent for diagnosis and response generation.

Example usage:
    >>> from aise.ticket_system.processor import TicketProcessor
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> processor = TicketProcessor(config)
    >>> await processor.process_ticket("ticket-123", "zendesk")
"""

import structlog
from typing import Optional, Dict, Any
from datetime import datetime

from aise.agents.state import AiSEState, create_initial_state, update_state
from aise.agents.ticket_agent import TicketAgent
from aise.agents.knowledge_agent import KnowledgeAgent
from aise.agents.engineer_agent import EngineerAgent
from aise.ai_engine.router import LLMRouter
from aise.ticket_system.base import TicketProvider, Message
from aise.ticket_system.memory import ConversationMemory
from aise.core.exceptions import ProviderError

logger = structlog.get_logger(__name__)


DEFAULT_SERVICE_TO_SOURCE: Dict[str, str] = {
    "EC2": "aws",
    "S3": "aws",
    "RDS": "aws",
    "Lambda": "aws",
    "VPC": "aws",
    "IAM": "aws",
    "Kubernetes": "kubernetes",
    "Docker": "docker",
}


class TicketProcessor:
    """Processes tickets through the complete workflow with classification.
    
    The processor orchestrates the ticket workflow:
    1. Fetch ticket from provider
    2. Classify ticket (category, severity, affected_service)
    3. Retrieve relevant documentation filtered by classification
    4. Generate diagnosis and response
    5. Add suggested tags to ticket
    """
    
    def __init__(
        self,
        ticket_provider: TicketProvider,
        llm_router: LLMRouter,
        knowledge_agent: Optional[KnowledgeAgent] = None,
        conversation_memory: Optional[ConversationMemory] = None,
        mode: str = "approval",
        service_to_source: Optional[Dict[str, str]] = None,
    ):
        """Initialize ticket processor.
        
        Args:
            ticket_provider: Ticket system provider
            llm_router: LLM router for AI agents
            knowledge_agent: Optional knowledge retrieval agent
            conversation_memory: Optional conversation memory
            mode: Operational mode (interactive, approval, autonomous)
            service_to_source: Mapping of service names to documentation source
                keys used for knowledge filtering. Defaults to
                DEFAULT_SERVICE_TO_SOURCE.
        """
        self._ticket_provider = ticket_provider
        self._llm_router = llm_router
        self._knowledge_agent = knowledge_agent
        self._conversation_memory = conversation_memory
        self._mode = mode
        self._service_to_source = service_to_source if service_to_source is not None else DEFAULT_SERVICE_TO_SOURCE
        
        # Initialize agents
        self._ticket_agent = TicketAgent(llm_router)
        self._engineer_agent = EngineerAgent(llm_router)
        
        logger.info(
            "ticket_processor_initialized",
            mode=mode,
            has_knowledge_agent=knowledge_agent is not None,
            has_conversation_memory=conversation_memory is not None
        )
    
    async def process_ticket(
        self,
        ticket_id: str,
        auto_reply: bool = False
    ) -> AiSEState:
        """Process ticket through complete workflow.
        
        Workflow:
        1. Fetch ticket from provider
        2. Classify ticket using Ticket Agent
        3. Retrieve relevant documentation (filtered by classification)
        4. Generate diagnosis using Engineer Agent
        5. Add suggested tags to ticket
        6. Optionally post reply (if auto_reply=True and mode=autonomous)
        
        Args:
            ticket_id: Unique ticket identifier
            auto_reply: Whether to automatically post reply (requires autonomous mode)
        
        Returns:
            Final AiSEState with diagnosis and classification
        
        Raises:
            ProviderError: If ticket processing fails
        """
        logger.info(
            "ticket_processing_start",
            ticket_id=ticket_id,
            mode=self._mode,
            auto_reply=auto_reply
        )
        
        try:
            # Step 1: Fetch ticket
            ticket = await self._ticket_provider.get(ticket_id)
            
            logger.info(
                "ticket_fetched",
                ticket_id=ticket_id,
                subject=ticket.subject[:100],
                status=ticket.status.value
            )
            
            # Step 2: Classify ticket
            ticket_analysis = await self._ticket_agent.classify(ticket)
            
            logger.info(
                "ticket_classified",
                ticket_id=ticket_id,
                category=ticket_analysis.category,
                severity=ticket_analysis.severity,
                affected_service=ticket_analysis.affected_service,
                tags_count=len(ticket_analysis.suggested_tags)
            )
            
            # Step 3: Load conversation memory (if available)
            messages = []
            if self._conversation_memory:
                thread = await self._conversation_memory.get_thread(ticket_id)
                messages = self._convert_thread_to_messages(thread)
            
            # Add current ticket as initial message if no thread
            if not messages:
                messages = [{
                    "role": "user",
                    "content": f"Subject: {ticket.subject}\n\n{ticket.body}"
                }]
            
            # Step 4: Create initial state
            state = create_initial_state(
                messages=messages,
                mode=self._mode,
                ticket_id=ticket_id
            )
            
            # Add ticket and classification to state
            state["ticket"] = ticket
            state["ticket_analysis"] = ticket_analysis
            
            # Step 5: Retrieve relevant documentation (filtered by classification)
            if self._knowledge_agent:
                knowledge_context = await self._retrieve_filtered_knowledge(
                    ticket=ticket,
                    classification=ticket_analysis
                )
                state["knowledge_context"] = knowledge_context
                
                logger.info(
                    "knowledge_retrieved",
                    ticket_id=ticket_id,
                    chunks_count=len(knowledge_context)
                )
            
            # Step 6: Generate diagnosis
            state = await self._engineer_agent.diagnose(state)
            
            logger.info(
                "diagnosis_generated",
                ticket_id=ticket_id,
                diagnosis_length=len(state["diagnosis"]) if state["diagnosis"] else 0
            )
            
            # Step 7: Add suggested tags to ticket
            if ticket_analysis.suggested_tags:
                await self._ticket_provider.add_tags(
                    ticket_id,
                    ticket_analysis.suggested_tags
                )
                
                logger.info(
                    "tags_added",
                    ticket_id=ticket_id,
                    tags=ticket_analysis.suggested_tags
                )
            
            # Step 8: Optionally post reply (only in autonomous mode)
            if auto_reply and self._mode == "autonomous" and state["diagnosis"]:
                await self._ticket_provider.reply(ticket_id, state["diagnosis"])
                
                # Store in conversation memory
                if self._conversation_memory:
                    await self._conversation_memory.store_message(
                        ticket_id,
                        Message(
                            id=f"msg-{datetime.utcnow().timestamp()}",
                            author="AiSE",
                            body=state["diagnosis"],
                            is_customer=False,
                            created_at=datetime.utcnow()
                        )
                    )
                
                logger.info(
                    "reply_posted",
                    ticket_id=ticket_id,
                    reply_length=len(state["diagnosis"])
                )
            
            logger.info(
                "ticket_processing_complete",
                ticket_id=ticket_id,
                category=ticket_analysis.category,
                severity=ticket_analysis.severity
            )
            
            return state
            
        except Exception as e:
            logger.error(
                "ticket_processing_failed",
                ticket_id=ticket_id,
                error=str(e)
            )
            raise ProviderError(f"Ticket processing failed: {str(e)}")
    
    async def _retrieve_filtered_knowledge(
        self,
        ticket,
        classification
    ) -> list:
        """Retrieve knowledge filtered by ticket classification.
        
        Uses the classification to build a more targeted query and
        optionally filter by affected service.
        
        Args:
            ticket: Ticket object
            classification: TicketAnalysis object
        
        Returns:
            List of DocumentChunk objects
        """
        from aise.agents.state import DocumentChunk
        
        # Build enhanced query with classification context
        query_parts = [ticket.subject, ticket.body]
        
        # Add classification context to query
        if classification.affected_service and classification.affected_service != "unknown":
            query_parts.insert(0, classification.affected_service)
        
        query_parts.append(classification.category)
        
        query = " ".join(query_parts)
        
        # Retrieve with optional source filtering
        # Note: This assumes the vector store supports filtering by service
        source_filter = None
        if classification.affected_service and classification.affected_service != "unknown":
            source_filter = self._service_to_source.get(classification.affected_service)
        
        results = await self._knowledge_agent.retrieve(
            query=query,
            top_k=5,
            source_filter=source_filter
        )
        
        # Convert dict results to DocumentChunk objects
        chunks = []
        for result in results:
            # Handle both dict and DocumentChunk objects
            if isinstance(result, dict):
                chunk = DocumentChunk(
                    id=result.get("id", ""),
                    content=result.get("text", ""),
                    metadata={"source": result.get("source_name", "unknown")},
                    source_url=result.get("source_url", ""),
                    heading_context=result.get("heading_context", ""),
                    embedding=None
                )
                chunks.append(chunk)
            else:
                # Already a DocumentChunk
                chunks.append(result)
        
        return chunks
    
    def _convert_thread_to_messages(self, thread) -> list:
        """Convert thread messages to LLM message format.
        
        Args:
            thread: List of Message objects
        
        Returns:
            List of message dicts for LLM
        """
        messages = []
        
        for msg in thread:
            role = "user" if msg.is_customer else "assistant"
            messages.append({
                "role": role,
                "content": msg.body
            })
        
        return messages
