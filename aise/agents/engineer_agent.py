# aise/agents/engineer_agent.py
"""Senior cloud engineer agent for diagnosis and troubleshooting.

This module implements the Engineer Agent, which acts as a senior cloud
support engineer to analyze issues, generate diagnoses, and provide
troubleshooting guidance.

Example usage:
    >>> from aise.agents.engineer_agent import EngineerAgent
    >>> from aise.agents.state import create_initial_state
    >>> from aise.ai_engine.router import LLMRouter
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> router = LLMRouter(config)
    >>> agent = EngineerAgent(router)
    >>> 
    >>> state = create_initial_state(
    ...     messages=[{"role": "user", "content": "Why is my EC2 instance unreachable?"}]
    ... )
    >>> result_state = await agent.diagnose(state)
    >>> print(result_state["diagnosis"])
"""

from typing import List, Dict, Optional
import structlog

from aise.agents.state import AiSEState, update_state
from aise.ai_engine.router import LLMRouter
from aise.core.exceptions import ProviderError
from aise.observability.tracer import get_tracer, agent_span
from aise.observability.langsmith import get_run_metadata, is_enabled as langsmith_enabled

logger = structlog.get_logger(__name__)


# System prompt for the Engineer Agent
ENGINEER_SYSTEM_PROMPT = """You are a senior cloud support engineer with deep expertise in:
- AWS, Azure, GCP, and multi-cloud architectures
- Kubernetes, Docker, and container orchestration
- Infrastructure as Code (Terraform, CloudFormation, Ansible)
- Networking, security, and compliance
- Database systems (RDS, DynamoDB, MongoDB, PostgreSQL)
- CI/CD pipelines and DevOps practices
- Monitoring, logging, and observability
- Linux system administration

Your role is to:
1. Analyze technical issues systematically
2. Provide clear, actionable diagnoses
3. Suggest specific troubleshooting steps
4. Explain root causes in accessible language
5. Recommend preventive measures

Communication style:
- Be concise and direct
- Use technical terminology appropriately
- Provide specific commands and configurations
- Include relevant documentation links when available
- Acknowledge uncertainty when appropriate

When analyzing issues:
- Consider multiple potential causes
- Prioritize most likely causes first
- Suggest verification steps before fixes
- Consider security and compliance implications
- Think about blast radius of proposed changes"""


class EngineerAgent:
    """Senior cloud engineer agent for diagnosis and troubleshooting.
    
    The Engineer Agent uses LLM capabilities to analyze technical issues,
    generate diagnoses, and provide troubleshooting guidance. It maintains
    state immutability by always returning new state objects.
    """
    
    def __init__(
        self,
        llm_router: LLMRouter,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        """Initialize Engineer Agent.
        
        Args:
            llm_router: LLM router for completion requests
            system_prompt: System prompt override. Defaults to ENGINEER_SYSTEM_PROMPT.
            temperature: Sampling temperature for LLM completions.
            max_tokens: Maximum tokens for LLM completions.
        """
        self._llm = llm_router
        self._system_prompt = system_prompt if system_prompt is not None else ENGINEER_SYSTEM_PROMPT
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._tracer = get_tracer("aise.agents.engineer")
        logger.info("engineer_agent_initialized")
    
    async def diagnose(self, state: AiSEState) -> AiSEState:
        """Generate diagnosis and troubleshooting plan.
        
        Preconditions:
        - state.messages is non-empty
        - LLM provider is available
        - state.mode is valid
        
        Postconditions:
        - state.diagnosis contains structured analysis
        - state.updated_at is updated
        - Original state is not mutated (returns new state)
        
        Args:
            state: Current AiSEState
        
        Returns:
            New AiSEState with diagnosis added
        
        Raises:
            ProviderError: If LLM completion fails
        """
        logger.info(
            "engineer_diagnose_start",
            message_count=len(state["messages"]),
            mode=state["mode"],
            has_knowledge_context=len(state["knowledge_context"]) > 0
        )
        
        try:
            # Build context-aware prompt
            prompt_messages = self._build_prompt(state)
            
            # Get diagnosis from LLM
            with agent_span(
                self._tracer,
                "engineer_agent.diagnose",
                {
                    "agent.message_count": len(state["messages"]),
                    "agent.mode": state["mode"],
                    "agent.has_knowledge_context": len(state["knowledge_context"]) > 0,
                    "agent.ticket_id": state.get("ticket_id", ""),
                },
            ) as span:
                result = await self._llm.complete(
                    messages=prompt_messages,
                    system_prompt=self._system_prompt,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    run_metadata=get_run_metadata(
                        ticket_id=state.get("ticket_id"),
                        mode=state["mode"],
                    ) if langsmith_enabled() else None,
                )
                
                diagnosis = result.content
                span.set_attribute("agent.diagnosis_length", len(diagnosis))
                span.set_attribute("llm.tokens_used", result.usage.total_tokens)
            
            logger.info(
                "engineer_diagnose_success",
                diagnosis_length=len(diagnosis),
                tokens_used=result.usage.total_tokens,
                cost_usd=result.usage.estimated_cost_usd
            )
            
            # Update state with diagnosis (immutable)
            new_state = update_state(
                state,
                diagnosis=diagnosis,
                actions_taken=state["actions_taken"] + ["Generated diagnosis"]
            )
            
            return new_state
            
        except Exception as e:
            logger.error(
                "engineer_diagnose_failed",
                error=str(e),
                message_count=len(state["messages"])
            )
            raise ProviderError(f"Engineer diagnosis failed: {str(e)}")
    
    def _build_prompt(self, state: AiSEState) -> List[Dict[str, str]]:
        """Build context-aware prompt for diagnosis.
        
        Args:
            state: Current AiSEState
        
        Returns:
            List of message dicts for LLM
        """
        messages = []
        
        # Add knowledge context if available
        if state["knowledge_context"]:
            context_text = self._format_knowledge_context(state["knowledge_context"])
            messages.append({
                "role": "user",
                "content": f"Relevant documentation:\n\n{context_text}"
            })
        else:
            # Warn LLM that documentation context is unavailable
            messages.append({
                "role": "user",
                "content": (
                    "Note: Documentation context is currently unavailable "
                    "(vector store may be offline or no documentation has been indexed). "
                    "Please answer based on your training knowledge and note this limitation."
                )
            })
        
        # Add user style context if available
        if state["user_style_context"]:
            messages.append({
                "role": "user",
                "content": f"Communication style guidance:\n{state['user_style_context']}"
            })
        
        # Add tool results if available
        if state["tool_results"]:
            tool_context = self._format_tool_results(state["tool_results"])
            messages.append({
                "role": "user",
                "content": f"Diagnostic command results:\n\n{tool_context}"
            })
        
        # Add conversation messages
        messages.extend(state["messages"])
        
        return messages
    
    def _format_knowledge_context(self, chunks) -> str:
        """Format knowledge chunks for prompt with source citations.
        
        Args:
            chunks: List of DocumentChunk objects
        
        Returns:
            Formatted context string with source citations
        """
        if not chunks:
            return ""
        
        formatted = []
        
        for i, chunk in enumerate(chunks[:5], 1):  # Limit to top 5
            # Support both dict (from KnowledgeAgent) and DocumentChunk objects
            if isinstance(chunk, dict):
                heading = chunk.get("heading_context", "")
                source = chunk.get("source_url", "")
                content = chunk.get("text", "")
            else:
                heading = chunk.heading_context
                source = chunk.source_url
                content = chunk.content
            formatted.append(
                f"[{i}] {heading}\n"
                f"Source: {source}\n"
                f"{content}\n"
            )
        
        return "\n---\n".join(formatted)
    
    def _format_tool_results(self, results) -> str:
        """Format tool results for prompt.
        
        Args:
            results: List of ToolResult objects
        
        Returns:
            Formatted results string
        """
        formatted = []
        
        for result in results:
            status = "✓" if result.exit_code == 0 else "✗"
            formatted.append(
                f"{status} {result.command}\n"
                f"Exit code: {result.exit_code}\n"
                f"Output:\n{result.stdout}\n"
            )
            
            if result.stderr:
                formatted.append(f"Errors:\n{result.stderr}\n")
        
        return "\n---\n".join(formatted)
    
    async def stream_diagnose(self, state: AiSEState):
        """Stream diagnosis tokens as they are generated.
        
        Args:
            state: Current AiSEState
        
        Yields:
            String tokens as they are generated
        
        Raises:
            ProviderError: If LLM streaming fails
        """
        logger.info(
            "engineer_stream_diagnose_start",
            message_count=len(state["messages"]),
            mode=state["mode"]
        )
        
        try:
            # Build context-aware prompt
            prompt_messages = self._build_prompt(state)
            
            # Stream diagnosis from LLM
            async for token in self._llm.stream_complete(
                messages=prompt_messages,
                system_prompt=self._system_prompt,
                temperature=self._temperature,
                max_tokens=self._max_tokens
            ):
                yield token
            
            logger.info("engineer_stream_diagnose_complete")
            
        except Exception as e:
            logger.error(
                "engineer_stream_diagnose_failed",
                error=str(e)
            )
            raise ProviderError(f"Engineer streaming diagnosis failed: {str(e)}")
