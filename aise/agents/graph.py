# aise/agents/graph.py
"""LangGraph state machine orchestration.

This module implements the AiSEGraph state machine that orchestrates
the complete workflow: classify → retrieve knowledge → diagnose → 
plan tools → execute tools → generate response → post reply.

Example usage:
    >>> from aise.agents.graph import AiSEGraph
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> graph = AiSEGraph.from_config(config)
    >>> 
    >>> state = create_initial_state(
    ...     messages=[{"role": "user", "content": "Why is my pod crashing?"}],
    ...     mode="approval"
    ... )
    >>> 
    >>> final_state = await graph.run(state)
"""

import structlog
from typing import Dict, Any, Optional, Literal
from datetime import datetime
from langgraph.graph import StateGraph, END

from aise.agents.state import AiSEState, update_state, create_initial_state
from aise.agents.ticket_agent import TicketAgent
from aise.agents.knowledge_agent import KnowledgeAgent
from aise.agents.engineer_agent import EngineerAgent
from aise.agents.tool_agent import ToolAgent
from aise.agents.browser_agent import BrowserAgent, should_use_browser_fallback
from aise.user_style.style_injector import StyleInjector
from aise.agents.approval import log_approval_request
from aise.ai_engine.router import LLMRouter
from aise.ticket_system.base import TicketProvider
from aise.core.exceptions import ProviderError, TicketAPIError, BrowserError

logger = structlog.get_logger(__name__)


class AiSEGraph:
    """LangGraph state machine orchestrating all agents.
    
    The AiSEGraph coordinates the complete workflow with conditional
    routing based on operational mode (interactive, approval, autonomous).
    
    Workflow:
    1. Classify ticket (if ticket_id present)
    2. Retrieve knowledge
    3. Diagnose issue
    4. Plan tool execution
    5. Execute tools (with approval gate if needed)
    6. Generate response
    7. Post reply (with approval gate if needed)
    """
    
    def __init__(
        self,
        ticket_agent: TicketAgent,
        knowledge_agent: Optional[KnowledgeAgent],
        engineer_agent: EngineerAgent,
        ticket_provider: Optional[TicketProvider] = None,
        browser_agent: Optional[BrowserAgent] = None,
        tool_agent: Optional["ToolAgent"] = None
    ):
        """Initialize AiSEGraph.
        
        Args:
            ticket_agent: Ticket classification agent
            knowledge_agent: Documentation retrieval agent (optional)
            engineer_agent: Diagnosis and response generation agent
            ticket_provider: Ticket system provider (optional)
            browser_agent: Browser automation agent (optional)
            tool_agent: Tool execution agent (optional)
        """
        self._ticket_agent = ticket_agent
        self._knowledge_agent = knowledge_agent
        self._engineer_agent = engineer_agent
        self._ticket_provider = ticket_provider
        self._browser_agent = browser_agent
        self._tool_agent = tool_agent or ToolAgent()
        self._style_injector: Optional[StyleInjector] = None
        
        # Build the graph
        self._graph = self._build_graph()
        
        logger.info(
            "aise_graph_initialized",
            has_knowledge_agent=knowledge_agent is not None,
            has_ticket_provider=ticket_provider is not None,
            has_browser_agent=browser_agent is not None
        )
    
    @classmethod
    def from_config(cls, config, llm_router: LLMRouter, **kwargs):
        """Create AiSEGraph from configuration.
        
        Args:
            config: Configuration object
            llm_router: LLM router instance
            **kwargs: Additional dependencies (vector_store, embedder, etc.)
        
        Returns:
            Configured AiSEGraph instance
        """
        ticket_agent = TicketAgent(llm_router)
        engineer_agent = EngineerAgent(
            llm_router,
            system_prompt=kwargs.get("engineer_system_prompt"),
            temperature=kwargs.get("engineer_temperature", 0.7),
            max_tokens=kwargs.get("engineer_max_tokens", 2048),
        )
        
        # Optional knowledge agent
        knowledge_agent = None
        if "vector_store" in kwargs and "embedder" in kwargs:
            knowledge_agent = KnowledgeAgent(
                kwargs["vector_store"],
                kwargs["embedder"]
            )
        
        # Optional ticket provider
        ticket_provider = kwargs.get("ticket_provider")
        
        # Optional browser agent (only if fallback enabled)
        browser_agent = None
        if config.USE_BROWSER_FALLBACK:
            try:
                browser_agent = BrowserAgent()
                logger.info("browser_agent_enabled_for_graph")
            except Exception as e:
                logger.warning("browser_agent_init_failed", error=str(e))
        
        return cls(
            ticket_agent=ticket_agent,
            knowledge_agent=knowledge_agent,
            engineer_agent=engineer_agent,
            ticket_provider=ticket_provider,
            browser_agent=browser_agent
        )
    
    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow.
        
        Returns:
            Compiled StateGraph
        """
        # Create graph with AiSEState
        workflow = StateGraph(AiSEState)
        
        # Add nodes for each step
        workflow.add_node("classify", self._classify_node)
        workflow.add_node("retrieve_knowledge", self._retrieve_knowledge_node)
        workflow.add_node("inject_style", self._inject_style_node)
        workflow.add_node("diagnose", self._diagnose_node)
        workflow.add_node("plan_tools", self._plan_tools_node)
        workflow.add_node("execute_tools", self._execute_tools_node)
        workflow.add_node("generate_response", self._generate_response_node)
        workflow.add_node("set_approval_gate", self._set_approval_gate_node)
        workflow.add_node("post_reply", self._post_reply_node)
        
        # Set entry point
        workflow.set_entry_point("classify")
        
        # Add edges with conditional routing
        workflow.add_conditional_edges(
            "classify",
            self._should_retrieve_knowledge,
            {
                "retrieve": "retrieve_knowledge",
                "skip": "inject_style"
            }
        )
        
        workflow.add_edge("retrieve_knowledge", "inject_style")
        workflow.add_edge("inject_style", "diagnose")
        workflow.add_edge("diagnose", "plan_tools")
        
        workflow.add_conditional_edges(
            "plan_tools",
            self._should_execute_tools,
            {
                "execute": "execute_tools",
                "skip": "generate_response",
                "approval_required": END  # Pause for approval
            }
        )
        
        workflow.add_edge("execute_tools", "generate_response")
        
        workflow.add_conditional_edges(
            "generate_response",
            self._should_post_reply,
            {
                "post": "post_reply",
                "skip": END,
                "approval_required": "set_approval_gate"  # Set approval before END
            }
        )
        
        workflow.add_edge("set_approval_gate", END)
        workflow.add_edge("post_reply", END)
        
        return workflow.compile()
    
    async def run(self, initial_state: AiSEState) -> AiSEState:
        """Execute graph from initial state to completion.
        
        Args:
            initial_state: Starting state
        
        Returns:
            Final state after graph execution
        
        Raises:
            ProviderError: If critical operation fails
        """
        logger.info(
            "graph_execution_start",
            mode=initial_state["mode"],
            has_ticket=initial_state.get("ticket_id") is not None,
            message_count=len(initial_state["messages"])
        )
        
        try:
            # Execute graph
            final_state = await self._graph.ainvoke(initial_state)
            
            logger.info(
                "graph_execution_complete",
                mode=final_state["mode"],
                has_diagnosis=final_state.get("diagnosis") is not None,
                actions_count=len(final_state["actions_taken"]),
                pending_approval=final_state.get("pending_approval") is not None
            )
            
            return final_state
            
        except Exception as e:
            logger.error(
                "graph_execution_failed",
                error=str(e),
                mode=initial_state["mode"]
            )
            raise ProviderError(f"Graph execution failed: {str(e)}")
    
    # Node implementations
    
    async def _classify_node(self, state: AiSEState) -> AiSEState:
        """Classify ticket if ticket_id is present.
        
        Args:
            state: Current state
        
        Returns:
            Updated state with ticket_analysis
        """
        logger.info("node_classify_start", ticket_id=state.get("ticket_id"))
        
        # Skip if no ticket
        if not state.get("ticket_id") or not self._ticket_provider:
            logger.info("node_classify_skip", reason="no_ticket_or_provider")
            return state
        
        try:
            # Fetch ticket if not already loaded
            if not state.get("ticket"):
                ticket = await self._ticket_provider.get(state["ticket_id"])
                state = update_state(state, ticket=ticket)
            
            # Classify ticket (use the ticket from the (possibly updated) state)
            ticket_analysis = await self._ticket_agent.classify(state["ticket"])
            
            logger.info(
                "node_classify_complete",
                category=ticket_analysis.category,
                severity=ticket_analysis.severity,
                affected_service=ticket_analysis.affected_service
            )
            
            return update_state(
                state,
                ticket_analysis=ticket_analysis,
                actions_taken=state["actions_taken"] + ["Classified ticket"]
            )
            
        except Exception as e:
            logger.error("node_classify_failed", error=str(e))
            # Continue without classification
            return state
    
    async def _retrieve_knowledge_node(self, state: AiSEState) -> AiSEState:
        """Retrieve relevant documentation.
        
        Args:
            state: Current state
        
        Returns:
            Updated state with knowledge_context
        """
        logger.info("node_retrieve_knowledge_start")
        
        if not self._knowledge_agent:
            logger.info("node_retrieve_knowledge_skip", reason="no_knowledge_agent")
            return state
        
        try:
            # Build query from messages and ticket
            query_parts = []
            
            if state.get("ticket"):
                query_parts.append(state["ticket"].subject)
                query_parts.append(state["ticket"].body)
            
            # Add recent messages
            for msg in state["messages"][-3:]:
                query_parts.append(msg["content"])
            
            query = " ".join(query_parts)
            
            # Use classification to build a source filter (mirrors TicketProcessor logic)
            from aise.ticket_system.processor import DEFAULT_SERVICE_TO_SOURCE
            source_filter = None
            classification = state.get("ticket_analysis")
            if classification and classification.affected_service and classification.affected_service != "unknown":
                source_filter = DEFAULT_SERVICE_TO_SOURCE.get(classification.affected_service)
                if classification.affected_service not in query_parts:
                    query = classification.affected_service + " " + query
            
            # Retrieve documentation
            results = await self._knowledge_agent.retrieve(
                query=query,
                top_k=5,
                source_filter=source_filter
            )
            
            # Convert dict results to DocumentChunk objects if needed
            from aise.agents.state import DocumentChunk
            chunks = []
            for result in results:
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
                    chunks.append(result)
            
            logger.info(
                "node_retrieve_knowledge_complete",
                chunks_count=len(chunks)
            )
            
            return update_state(
                state,
                knowledge_context=chunks,
                actions_taken=state["actions_taken"] + ["Retrieved documentation"]
            )
            
        except Exception as e:
            logger.error("node_retrieve_knowledge_failed", error=str(e))
            # Continue without knowledge context
            return state
    
    async def _inject_style_node(self, state: AiSEState) -> AiSEState:
        """Inject user style context before diagnosis.

        Args:
            state: Current state

        Returns:
            Updated state with user_style_context populated (if available)
        """
        logger.info("node_inject_style_start")

        if not self._style_injector:
            logger.info("node_inject_style_skip", reason="no_style_injector")
            return state

        try:
            # Use the most recent user message as the query
            query = ""
            for msg in reversed(state["messages"]):
                if msg.get("role") == "user":
                    query = msg["content"]
                    break

            if not query:
                return state

            style_context = await self._style_injector.get_style_context(query)

            if style_context:
                logger.info("node_inject_style_complete", context_length=len(style_context))
                return update_state(state, user_style_context=style_context)

        except Exception as e:
            logger.warning("node_inject_style_failed", error=str(e))

        return state

    async def _diagnose_node(self, state: AiSEState) -> AiSEState:
        """Generate diagnosis.
        
        Args:
            state: Current state
        
        Returns:
            Updated state with diagnosis
        """
        logger.info("node_diagnose_start")
        
        try:
            # Generate diagnosis
            new_state = await self._engineer_agent.diagnose(state)
            
            logger.info(
                "node_diagnose_complete",
                diagnosis_length=len(new_state["diagnosis"]) if new_state["diagnosis"] else 0
            )
            
            return new_state
            
        except Exception as e:
            logger.error("node_diagnose_failed", error=str(e))
            raise ProviderError(f"Diagnosis failed: {str(e)}")
    
    async def _plan_tools_node(self, state: AiSEState) -> AiSEState:
        """Plan tool execution based on diagnosis."""
        logger.info("node_plan_tools_start")
        planned = self._tool_agent.plan_execution(state)
        logger.info("node_plan_tools_complete", planned_tools=len(planned))
        # Store planned commands in actions_taken for routing decision
        return update_state(
            state,
            actions_taken=state["actions_taken"] + (
                [f"Planned tools: {', '.join(planned)}"] if planned else []
            )
        )
    
    async def _execute_tools_node(self, state: AiSEState) -> AiSEState:
        """Execute planned tools via ToolAgent."""
        logger.info("node_execute_tools_start")
        new_state = await self._tool_agent.execute_and_analyze(state)
        logger.info(
            "node_execute_tools_complete",
            results_count=len(new_state.get("tool_results") or [])
        )
        return new_state
    
    async def _generate_response_node(self, state: AiSEState) -> AiSEState:
        """Generate final response (uses existing diagnosis).
        
        Args:
            state: Current state
        
        Returns:
            Updated state
        """
        logger.info("node_generate_response_start")
        
        # Diagnosis already generated, just log
        logger.info(
            "node_generate_response_complete",
            has_diagnosis=state.get("diagnosis") is not None
        )
        
        return state
    
    async def _set_approval_gate_node(self, state: AiSEState) -> AiSEState:
        """Set pending approval for reply posting.
        
        Args:
            state: Current state
        
        Returns:
            Updated state with pending_approval set
        """
        logger.info("node_set_approval_gate_start")
        
        # Set pending approval
        approval_data = {
            "action": "post_reply",
            "ticket_id": state.get("ticket_id"),
            "message": state.get("diagnosis"),
            "reason": "Reply requires approval before posting"
        }
        
        # Log approval request
        try:
            await log_approval_request(
                action="post_reply",
                proposed_action=f"Post reply to ticket {state.get('ticket_id')}",
                ticket_id=state.get("ticket_id"),
                details={
                    "message_preview": state.get("diagnosis", "")[:200] if state.get("diagnosis") else "",
                    "message_length": len(state.get("diagnosis", ""))
                }
            )
        except Exception as e:
            logger.error("approval_request_logging_failed", error=str(e))
            # Continue even if logging fails
        
        logger.info(
            "node_set_approval_gate_complete",
            ticket_id=state.get("ticket_id")
        )
        
        return update_state(state, pending_approval=approval_data)
    
    async def _post_reply_node(self, state: AiSEState) -> AiSEState:
        """Post reply to ticket system.
        
        Args:
            state: Current state
        
        Returns:
            Updated state
        """
        logger.info("node_post_reply_start", ticket_id=state.get("ticket_id"))
        
        if not state.get("ticket_id") or not self._ticket_provider:
            logger.info("node_post_reply_skip", reason="no_ticket_or_provider")
            return state
        
        if not state.get("diagnosis"):
            logger.warning("node_post_reply_skip", reason="no_diagnosis")
            return state
        
        try:
            # Attempt to post reply via API
            await self._ticket_provider.reply(
                state["ticket_id"],
                state["diagnosis"]
            )
            
            logger.info("node_post_reply_complete", ticket_id=state["ticket_id"])
            
            return update_state(
                state,
                actions_taken=state["actions_taken"] + ["Posted reply to ticket"]
            )
            
        except TicketAPIError as api_error:
            # Check if browser fallback should be used
            from aise.core.config import get_config
            config = get_config()
            
            if await should_use_browser_fallback(config, api_error):
                logger.warning(
                    "api_post_reply_failed_attempting_browser_fallback",
                    ticket_id=state["ticket_id"],
                    error=str(api_error)
                )
                
                try:
                    # Attempt browser fallback
                    if not self._browser_agent:
                        self._browser_agent = BrowserAgent()
                    
                    # Determine platform from ticket provider
                    platform = self._detect_platform()
                    
                    result = await self._browser_agent.execute_action(
                        platform=platform,
                        action="reply",
                        params={
                            "ticket_id": state["ticket_id"],
                            "message": state["diagnosis"]
                        }
                    )
                    
                    logger.info(
                        "browser_fallback_post_reply_success",
                        ticket_id=state["ticket_id"],
                        screenshot=result.get("screenshot")
                    )
                    
                    return update_state(
                        state,
                        actions_taken=state["actions_taken"] + [
                            "Posted reply to ticket (via browser fallback)"
                        ]
                    )
                    
                except BrowserError as browser_error:
                    logger.error(
                        "browser_fallback_post_reply_failed",
                        ticket_id=state["ticket_id"],
                        api_error=str(api_error),
                        browser_error=str(browser_error)
                    )
                    # Don't fail the whole workflow, just log
                    return state
            else:
                logger.error("node_post_reply_failed", error=str(api_error))
                # Don't fail the whole workflow, just log
                return state
        
        except Exception as e:
            logger.error("node_post_reply_failed", error=str(e))
            # Don't fail the whole workflow, just log
            return state
    
    def _detect_platform(self) -> str:
        """
        Detect platform from ticket provider class name, falling back to config.
        
        Returns:
            Platform name ("zendesk" or "freshdesk")
        """
        if self._ticket_provider:
            provider_class = self._ticket_provider.__class__.__name__.lower()
            if "zendesk" in provider_class:
                return "zendesk"
            elif "freshdesk" in provider_class:
                return "freshdesk"
        
        # Fall back to config-driven default if available
        try:
            from aise.core.config import get_config
            config = get_config()
            if getattr(config, "ZENDESK_SUBDOMAIN", None) or getattr(config, "ZENDESK_URL", None):
                return "zendesk"
            if getattr(config, "FRESHDESK_DOMAIN", None) or getattr(config, "FRESHDESK_URL", None):
                return "freshdesk"
        except Exception:
            pass
        
        logger.warning("could_not_detect_platform_defaulting_to_zendesk")
        return "zendesk"
    
    # Routing functions
    
    def _should_retrieve_knowledge(self, state: AiSEState) -> Literal["retrieve", "skip"]:
        """Determine if knowledge retrieval is needed.
        
        Args:
            state: Current state
        
        Returns:
            "retrieve" if knowledge agent available, "skip" otherwise
        """
        if self._knowledge_agent:
            return "retrieve"
        return "skip"
    
    def _should_execute_tools(
        self,
        state: AiSEState
    ) -> Literal["execute", "skip", "approval_required"]:
        """Determine if tools should be executed."""
        planned = self._tool_agent.plan_execution(state)
        if not planned:
            return "skip"
        # In approval mode, still execute read-only diagnostic tools;
        # the reply posting is gated separately via _should_post_reply.
        return "execute"
    
    def _should_post_reply(
        self,
        state: AiSEState
    ) -> Literal["post", "skip", "approval_required"]:
        """Determine if reply should be posted.
        
        Args:
            state: Current state
        
        Returns:
            "post", "skip", or "approval_required"
        """
        # Skip if no ticket or provider
        if not state.get("ticket_id") or not self._ticket_provider:
            return "skip"
        
        # Skip if no diagnosis
        if not state.get("diagnosis"):
            return "skip"
        
        # Check approval mode
        if state["mode"] == "approval":
            return "approval_required"
        
        # Autonomous or interactive mode - post directly
        return "post"
