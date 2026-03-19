# aise/cli/commands/ask.py
"""aise ask command for interactive Q&A.

This module provides the `aise ask` command that allows users to ask
technical questions and receive AI-powered diagnoses and troubleshooting guidance.

Example usage:
    $ aise ask "Why is my EC2 instance unreachable?"
    $ aise ask "How do I configure a security group for SSH?"
"""

import typer
import asyncio
import structlog
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich import box

from aise.agents.state import create_initial_state, AiSEState
from aise.agents.engineer_agent import EngineerAgent
from aise.agents.knowledge_agent import KnowledgeAgent
from aise.ai_engine.router import LLMRouter
from aise.knowledge_engine.vector_store import ChromaDBVectorStore
from aise.core.config import get_config
from aise.core.exceptions import ProviderError, AuthenticationError
from aise.cli.output import (
    print_diagnosis,
    print_error,
    print_warning,
    print_info,
    console
)

logger = structlog.get_logger(__name__)

# Create ask subcommand app
ask_app = typer.Typer(
    name="ask",
    help="Ask technical questions and get AI-powered diagnoses"
)


@ask_app.command()
def main(
    question: str = typer.Argument(..., help="Your technical question"),
    stream: bool = typer.Option(True, "--stream", "--no-stream", help="Stream response in real-time"),
    mode: str = typer.Option("interactive", "--mode", "-m", help="Operational mode (interactive/approval/autonomous)")
):
    """Ask a technical question and get an AI-powered diagnosis.
    
    Examples:
        aise ask "Why is my EC2 instance unreachable?"
        aise ask "How do I configure a Kubernetes ingress?" --no-stream
        aise ask "Debug my pod crash" --mode approval
    """
    asyncio.run(_ask_question(question, stream, mode))


async def _ask_question(question: str, stream: bool, mode: str):
    """Async implementation of ask command.
    
    Args:
        question: User's technical question
        stream: Whether to stream response
        mode: Operational mode
    """
    try:
        # Load configuration
        config = get_config()
        
        # Initialize components
        console.print("\n[dim]Initializing...[/dim]")
        
        # Initialize LLM router
        try:
            llm_router = LLMRouter(config)
        except AuthenticationError as e:
            print_error(
                "LLM provider not configured",
                str(e)
            )
            raise typer.Exit(1)
        except Exception as e:
            print_error(
                "Failed to initialize LLM providers",
                str(e)
            )
            raise typer.Exit(1)
        
        # Initialize vector store for knowledge retrieval
        vector_store = ChromaDBVectorStore(config)
        await vector_store.initialize()
        
        # Initialize agents
        engineer_agent = EngineerAgent(llm_router)
        knowledge_agent = KnowledgeAgent(vector_store)
        
        # Create initial state
        state = create_initial_state(
            messages=[{"role": "user", "content": question}],
            mode=mode
        )
        
        logger.info(
            "ask_command_start",
            question_length=len(question),
            mode=mode,
            stream=stream
        )
        
        # Retrieve relevant knowledge
        console.print("[dim]Searching knowledge base...[/dim]")
        knowledge_chunks = await knowledge_agent.retrieve(
            query=question,
            top_k=5
        )
        
        if knowledge_chunks:
            console.print(f"[dim]Found {len(knowledge_chunks)} relevant documentation chunks[/dim]\n")
            state["knowledge_context"] = knowledge_chunks
        else:
            print_warning(
                "No documentation indexed yet. Run 'aise init' to index documentation sources.\n"
                "Proceeding with general knowledge only."
            )
        
        # Generate diagnosis
        if stream:
            # Stream response
            console.print("[bold cyan]Diagnosis:[/bold cyan]\n")
            
            diagnosis_text = ""
            async for token in engineer_agent.stream_diagnose(state):
                console.print(token, end="", flush=True)
                diagnosis_text += token
            
            console.print("\n")
            
        else:
            # Non-streaming response
            console.print("[dim]Analyzing...[/dim]\n")
            
            result_state = await engineer_agent.diagnose(state)
            diagnosis_text = result_state["diagnosis"]
            
            # Display diagnosis
            print_diagnosis(diagnosis_text)
        
        # Display knowledge sources if available
        if knowledge_chunks:
            console.print("\n[bold cyan]Sources:[/bold cyan]")
            for i, chunk in enumerate(knowledge_chunks[:3], 1):
                console.print(f"  [{i}] {chunk.source_url}")
            console.print()
        
        logger.info(
            "ask_command_complete",
            diagnosis_length=len(diagnosis_text),
            knowledge_chunks=len(knowledge_chunks)
        )
        
        # Close vector store
        await vector_store.close()
        
    except ProviderError as e:
        print_error(
            "LLM provider error",
            str(e)
        )
        logger.error("ask_command_provider_error", error=str(e))
        raise typer.Exit(1)
    
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted by user[/yellow]")
        raise typer.Exit(0)
    
    except Exception as e:
        print_error(
            "Unexpected error",
            str(e)
        )
        logger.error("ask_command_failed", error=str(e))
        raise typer.Exit(1)


# Standalone function for direct invocation
def ask(question: str, stream: bool = True, mode: str = "interactive"):
    """Ask a question (convenience function).
    
    Args:
        question: Technical question
        stream: Whether to stream response
        mode: Operational mode
    """
    asyncio.run(_ask_question(question, stream, mode))
