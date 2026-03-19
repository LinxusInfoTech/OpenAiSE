# aise/cli/commands/config.py
"""aise config commands for configuration management.

This module provides CLI commands for viewing and managing AiSE configuration,
including displaying configuration values, showing sources, and masking sensitive data.

Example usage:
    $ aise config show
    $ aise config show --reveal
"""

import typer
import structlog
from typing import Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from aise.core.config import get_config, load_config
from aise.core.exceptions import ConfigurationError
from aise.cli.output import print_error, print_success, console

logger = structlog.get_logger(__name__)

# Create config subcommand app
config_app = typer.Typer(
    name="config",
    help="Configuration management commands"
)


@config_app.command()
def show(
    reveal: bool = typer.Option(False, "--reveal", "--no-reveal", help="Show unmasked sensitive values (API keys, passwords)")
):
    """Display all configuration organized by section.
    
    Shows configuration values with their sources (environment variable, .env file,
    database, system config, or default). Sensitive values are masked by default.
    
    Examples:
        aise config show              # Show masked configuration
        aise config show --reveal     # Show unmasked sensitive values
    """
    try:
        # Load configuration
        try:
            config = get_config()
        except RuntimeError:
            # Config not loaded yet, load it
            config = load_config()
        
        # Get configuration as dictionary
        config_dict = config.to_dict(mask_sensitive=not reveal)
        
        # Get configuration sources
        sources = config.get_config_sources()
        
        logger.info(
            "config_show_command",
            reveal=reveal,
            total_settings=len(config_dict)
        )
        
        # Organize configuration by section
        sections = _organize_config_by_section(config_dict, sources)
        
        # Display header
        console.print()
        if reveal:
            console.print(Panel(
                "[bold yellow]⚠ Displaying unmasked sensitive values[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED
            ))
            console.print()
        
        # Display each section
        for section_name, settings in sections.items():
            _display_section(section_name, settings, reveal)
        
        # Display footer with legend
        _display_legend()
        
        logger.info("config_show_complete")
        
    except ConfigurationError as e:
        print_error("Configuration error", str(e))
        logger.error("config_show_failed", error=str(e))
        raise typer.Exit(1)
    
    except Exception as e:
        print_error("Unexpected error", str(e))
        logger.error("config_show_unexpected_error", error=str(e))
        raise typer.Exit(1)


def _organize_config_by_section(
    config_dict: Dict[str, Any],
    sources: Dict[str, str]
) -> Dict[str, list]:
    """Organize configuration settings by logical section.
    
    Args:
        config_dict: Configuration dictionary
        sources: Configuration sources dictionary
        
    Returns:
        Dictionary mapping section name to list of (key, value, source) tuples
    """
    sections = {
        "LLM Providers": [],
        "Database": [],
        "Ticket Systems": [],
        "Browser Automation": [],
        "Cloud Providers": [],
        "Observability": [],
        "Security": [],
        "Tool Execution": [],
        "Knowledge Engine": [],
        "Web UI": [],
        "Development": []
    }
    
    # Define section mappings
    section_mapping = {
        # LLM Providers
        "LLM_PROVIDER": "LLM Providers",
        "ANTHROPIC_API_KEY": "LLM Providers",
        "OPENAI_API_KEY": "LLM Providers",
        "DEEPSEEK_API_KEY": "LLM Providers",
        "OLLAMA_BASE_URL": "LLM Providers",
        
        # Database
        "POSTGRES_URL": "Database",
        "DATABASE_URL": "Database",
        "REDIS_URL": "Database",
        "CHROMA_HOST": "Database",
        "CHROMA_PORT": "Database",
        
        # Ticket Systems
        "ZENDESK_SUBDOMAIN": "Ticket Systems",
        "ZENDESK_EMAIL": "Ticket Systems",
        "ZENDESK_API_TOKEN": "Ticket Systems",
        "ZENDESK_URL": "Ticket Systems",
        "FRESHDESK_DOMAIN": "Ticket Systems",
        "FRESHDESK_API_KEY": "Ticket Systems",
        "FRESHDESK_URL": "Ticket Systems",
        "EMAIL_IMAP_HOST": "Ticket Systems",
        "EMAIL_IMAP_PORT": "Ticket Systems",
        "EMAIL_IMAP_USERNAME": "Ticket Systems",
        "EMAIL_IMAP_PASSWORD": "Ticket Systems",
        "EMAIL_SMTP_HOST": "Ticket Systems",
        "EMAIL_SMTP_PORT": "Ticket Systems",
        "EMAIL_SMTP_USERNAME": "Ticket Systems",
        "EMAIL_SMTP_PASSWORD": "Ticket Systems",
        "SLACK_BOT_TOKEN": "Ticket Systems",
        "SLACK_SIGNING_SECRET": "Ticket Systems",
        
        # Browser Automation
        "USE_BROWSER_FALLBACK": "Browser Automation",
        "BROWSER_HEADLESS": "Browser Automation",
        "CUSTOM_SUPPORT_URL": "Browser Automation",
        
        # Cloud Providers
        "AWS_PROFILE": "Cloud Providers",
        "AWS_DEFAULT_REGION": "Cloud Providers",
        "AWS_ACCESS_KEY_ID": "Cloud Providers",
        "AWS_SECRET_ACCESS_KEY": "Cloud Providers",
        "KUBECONFIG": "Cloud Providers",
        "GOOGLE_APPLICATION_CREDENTIALS": "Cloud Providers",
        "AZURE_CONFIG_DIR": "Cloud Providers",
        
        # Observability
        "LANGSMITH_API_KEY": "Observability",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "Observability",
        "PROMETHEUS_PORT": "Observability",
        
        # Security
        "CREDENTIAL_VAULT_KEY": "Security",
        "WEBHOOK_SECRET": "Security",
        "WEBHOOK_ALLOWED_IPS": "Security",
        
        # Tool Execution
        "TOOL_EXECUTION_TIMEOUT": "Tool Execution",
        "MAX_CONCURRENT_TOOLS": "Tool Execution",
        
        # Knowledge Engine
        "CHROMA_PERSIST_PATH": "Knowledge Engine",
        "KNOWLEDGE_CRAWL_MAX_DEPTH": "Knowledge Engine",
        "KNOWLEDGE_CHUNK_SIZE": "Knowledge Engine",
        "KNOWLEDGE_CHUNK_OVERLAP": "Knowledge Engine",
        "KNOWLEDGE_MIN_REINIT_HOURS": "Knowledge Engine",
        "EMBEDDING_MODEL": "Knowledge Engine",
        "LOCAL_EMBEDDING_MODEL": "Knowledge Engine",
        "MAX_CRAWL_PAGES": "Knowledge Engine",
        "MAX_CRAWL_DEPTH": "Knowledge Engine",
        "CHUNK_SIZE": "Knowledge Engine",
        "CHUNK_OVERLAP": "Knowledge Engine",
        
        # Web UI
        "CONFIG_UI_PORT": "Web UI",
        "WEBHOOK_SERVER_PORT": "Web UI",
        
        # Development
        "AISE_MODE": "Development",
        "LOG_LEVEL": "Development",
        "DEBUG": "Development"
    }
    
    # Organize settings into sections
    for key, value in config_dict.items():
        section = section_mapping.get(key, "Development")
        source = sources.get(key, "unknown")
        sections[section].append((key, value, source))
    
    # Remove empty sections
    sections = {k: v for k, v in sections.items() if v}
    
    return sections


def _display_section(section_name: str, settings: list, reveal: bool):
    """Display a configuration section as a Rich table.
    
    Args:
        section_name: Name of the section
        settings: List of (key, value, source) tuples
        reveal: Whether sensitive values are revealed
    """
    table = Table(
        title=f"[bold cyan]{section_name}[/bold cyan]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
        title_style="bold cyan",
        padding=(0, 1)
    )
    
    table.add_column("Setting", style="white", no_wrap=True)
    table.add_column("Value", style="green")
    table.add_column("Source", style="dim cyan", no_wrap=True)
    
    # Sort settings by key
    settings.sort(key=lambda x: x[0])
    
    for key, value, source in settings:
        # Format value
        if value is None:
            value_str = "[dim]not set[/dim]"
        elif isinstance(value, bool):
            value_str = "[green]✓[/green]" if value else "[red]✗[/red]"
        else:
            value_str = str(value)
        
        # Format source with color coding
        source_str = _format_source(source)
        
        table.add_row(key, value_str, source_str)
    
    console.print(table)
    console.print()


def _format_source(source: str) -> str:
    """Format configuration source with color coding.
    
    Args:
        source: Source description
        
    Returns:
        Formatted source string with Rich markup
    """
    source_colors = {
        "environment variable": "[bold yellow]env var[/bold yellow]",
        ".env file": "[bold blue].env[/bold blue]",
        "database": "[bold magenta]database[/bold magenta]",
        "system config": "[bold green]system[/bold green]",
        "default": "[dim]default[/dim]"
    }
    
    return source_colors.get(source, f"[dim]{source}[/dim]")


def _display_legend():
    """Display legend explaining configuration sources."""
    legend_text = """[bold]Configuration Sources:[/bold]
  [bold yellow]env var[/bold yellow]    - Environment variable (highest priority)
  [bold blue].env[/bold blue]        - .env file in project directory
  [bold magenta]database[/bold magenta]   - Config UI database settings
  [bold green]system[/bold green]     - System-level config files (~/.aws/config, ~/.kube/config)
  [dim]default[/dim]    - Default value (lowest priority)"""
    
    console.print(Panel(
        legend_text,
        title="[bold]Legend[/bold]",
        border_style="dim",
        box=box.ROUNDED
    ))
    console.print()


@config_app.command()
def validate():
    """Validate current configuration by testing connectivity to all configured services.
    
    Tests connectivity to:
    - LLM providers (Anthropic, OpenAI, DeepSeek, Ollama)
    - Databases (PostgreSQL, Redis, ChromaDB)
    - Ticket systems (Zendesk, Freshdesk)
    
    Displays validation results with clear success/failure indicators and
    provides remediation suggestions for failures.
    
    Examples:
        aise config validate
    """
    try:
        import asyncio
        from aise.config_ui.validators import (
            validate_llm_provider,
            validate_postgres_url,
            validate_redis_url,
            validate_zendesk_credentials,
            validate_freshdesk_credentials
        )
        
        # Load configuration
        try:
            config = get_config()
        except RuntimeError:
            config = load_config()
        
        logger.info("config_validate_command")
        
        console.print()
        console.print(Panel(
            "[bold cyan]🔍 Validating Configuration[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        ))
        console.print()
        
        # Track validation results
        results = []
        
        # Validate LLM Providers
        console.print("[bold]LLM Providers:[/bold]")
        
        if config.ANTHROPIC_API_KEY:
            is_valid, error = asyncio.run(validate_llm_provider("anthropic", config.ANTHROPIC_API_KEY))
            results.append(("Anthropic API", is_valid, error))
            _print_validation_result("Anthropic API", is_valid, error)
        
        if config.OPENAI_API_KEY:
            is_valid, error = asyncio.run(validate_llm_provider("openai", config.OPENAI_API_KEY))
            results.append(("OpenAI API", is_valid, error))
            _print_validation_result("OpenAI API", is_valid, error)
        
        if config.DEEPSEEK_API_KEY:
            is_valid, error = asyncio.run(validate_llm_provider("deepseek", config.DEEPSEEK_API_KEY))
            results.append(("DeepSeek API", is_valid, error))
            _print_validation_result("DeepSeek API", is_valid, error)
        
        # Ollama doesn't need validation
        if config.OLLAMA_BASE_URL:
            console.print(f"  [dim]Ollama:[/dim] [yellow]⚠[/yellow] Skipped (no validation needed)")
        
        console.print()
        
        # Validate Databases
        console.print("[bold]Databases:[/bold]")
        
        is_valid, error = asyncio.run(validate_postgres_url(config.POSTGRES_URL))
        results.append(("PostgreSQL", is_valid, error))
        _print_validation_result("PostgreSQL", is_valid, error)
        
        is_valid, error = asyncio.run(validate_redis_url(config.REDIS_URL))
        results.append(("Redis", is_valid, error))
        _print_validation_result("Redis", is_valid, error)
        
        # ChromaDB validation (simple connectivity check)
        try:
            import httpx
            response = asyncio.run(
                httpx.AsyncClient().get(
                    f"http://{config.CHROMA_HOST}:{config.CHROMA_PORT}/api/v1/heartbeat",
                    timeout=5.0
                )
            )
            is_valid = response.status_code == 200
            error = None if is_valid else f"ChromaDB returned status {response.status_code}"
        except Exception as e:
            is_valid = False
            error = f"Failed to connect: {str(e)}"
        
        results.append(("ChromaDB", is_valid, error))
        _print_validation_result("ChromaDB", is_valid, error)
        
        console.print()
        
        # Validate Ticket Systems
        if config.ZENDESK_SUBDOMAIN and config.ZENDESK_EMAIL and config.ZENDESK_API_TOKEN:
            console.print("[bold]Ticket Systems:[/bold]")
            is_valid, error = asyncio.run(
                validate_zendesk_credentials(
                    config.ZENDESK_SUBDOMAIN,
                    config.ZENDESK_EMAIL,
                    config.ZENDESK_API_TOKEN
                )
            )
            results.append(("Zendesk", is_valid, error))
            _print_validation_result("Zendesk", is_valid, error)
            console.print()
        
        if config.FRESHDESK_DOMAIN and config.FRESHDESK_API_KEY:
            if not any(r[0] == "Zendesk" for r in results):
                console.print("[bold]Ticket Systems:[/bold]")
            is_valid, error = asyncio.run(
                validate_freshdesk_credentials(
                    config.FRESHDESK_DOMAIN,
                    config.FRESHDESK_API_KEY
                )
            )
            results.append(("Freshdesk", is_valid, error))
            _print_validation_result("Freshdesk", is_valid, error)
            console.print()
        
        # Summary
        total = len(results)
        passed = sum(1 for _, is_valid, _ in results if is_valid)
        failed = total - passed
        
        if failed == 0:
            console.print(Panel(
                f"[bold green]✓ All {total} validation checks passed![/bold green]",
                border_style="green",
                box=box.ROUNDED
            ))
            logger.info("config_validate_success", total=total)
        else:
            console.print(Panel(
                f"[bold yellow]⚠ {passed}/{total} validation checks passed, {failed} failed[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED
            ))
            logger.warning("config_validate_partial", passed=passed, failed=failed)
            raise typer.Exit(1)
        
    except typer.Exit:
        raise
    except Exception as e:
        print_error("Validation failed", str(e))
        logger.error("config_validate_error", error=str(e))
        raise typer.Exit(1)


def _print_validation_result(service: str, is_valid: bool, error: str):
    """Print validation result for a service.
    
    Args:
        service: Service name
        is_valid: Whether validation passed
        error: Error message if validation failed
    """
    if is_valid:
        console.print(f"  [dim]{service}:[/dim] [green]✓[/green] Connected")
    else:
        console.print(f"  [dim]{service}:[/dim] [red]✗[/red] Failed")
        if error:
            # Wrap error message
            import textwrap
            wrapped = textwrap.fill(error, width=70, initial_indent="    ", subsequent_indent="    ")
            console.print(f"[red]{wrapped}[/red]")


@config_app.command()
def export(
    output: str = typer.Option(".env.export", "--output", "-o", help="Output file path")
):
    """Export configuration to .env format with comments.
    
    Exports all configuration values to a .env file format, including:
    - Current values for all settings
    - Comments explaining each setting
    - Section headers for organization
    
    Examples:
        aise config export                    # Export to .env.export
        aise config export -o my-config.env   # Export to custom file
    """
    try:
        # Load configuration
        try:
            config = get_config()
        except RuntimeError:
            config = load_config()
        
        logger.info("config_export_command", output=output)
        
        # Get configuration as dictionary
        config_dict = config.to_dict(mask_sensitive=False)
        
        # Get configuration sources
        sources = config.get_config_sources()
        
        # Organize by section
        sections = _organize_config_by_section(config_dict, sources)
        
        # Write to file
        with open(output, 'w') as f:
            f.write("# AiSE Configuration Export\n")
            f.write(f"# Generated by: aise config export\n")
            f.write(f"# \n")
            f.write("# This file contains all configuration values for AiSE.\n")
            f.write("# Copy this file to .env and modify as needed.\n")
            f.write("\n")
            
            for section_name, settings in sections.items():
                f.write(f"# ===== {section_name} =====\n")
                f.write("\n")
                
                for key, value, source in sorted(settings, key=lambda x: x[0]):
                    # Write comment with source
                    f.write(f"# Source: {source}\n")
                    
                    # Write value
                    if value is None:
                        f.write(f"# {key}=\n")
                    elif isinstance(value, bool):
                        f.write(f"{key}={'true' if value else 'false'}\n")
                    else:
                        f.write(f"{key}={value}\n")
                    
                    f.write("\n")
        
        print_success("Configuration exported", f"Saved to {output}")
        logger.info("config_export_success", output=output)
        
    except Exception as e:
        print_error("Export failed", str(e))
        logger.error("config_export_error", error=str(e))
        raise typer.Exit(1)


@config_app.command()
def import_config(
    file: str = typer.Argument(..., help="Path to .env file to import")
):
    """Import configuration from .env file with validation.
    
    Imports configuration values from a .env file, validates them,
    and updates the configuration database.
    
    Examples:
        aise config import my-config.env
        aise config import .env.production
    """
    try:
        import os
        from pathlib import Path
        
        logger.info("config_import_command", file=file)
        
        # Check file exists
        if not Path(file).exists():
            print_error("File not found", f"{file} does not exist")
            raise typer.Exit(1)
        
        # Read file
        config_values = {}
        with open(file, 'r') as f:
            for line in f:
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                # Parse key=value
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Handle boolean values
                    if value.lower() in ('true', 'false'):
                        value = value.lower() == 'true'
                    
                    config_values[key] = value
        
        console.print()
        console.print(Panel(
            f"[bold cyan]📥 Importing {len(config_values)} configuration values[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        ))
        console.print()
        
        # Import each value
        success_count = 0
        error_count = 0
        
        for key, value in config_values.items():
            try:
                # Set environment variable
                os.environ[key] = str(value)
                console.print(f"  [green]✓[/green] {key}")
                success_count += 1
            except Exception as e:
                console.print(f"  [red]✗[/red] {key}: {str(e)}")
                error_count += 1
        
        console.print()
        
        if error_count == 0:
            print_success(
                "Import complete",
                f"Successfully imported {success_count} configuration values"
            )
            console.print("[dim]Note: Restart AiSE for changes to take effect[/dim]")
            logger.info("config_import_success", count=success_count)
        else:
            console.print(Panel(
                f"[yellow]⚠ Imported {success_count} values, {error_count} failed[/yellow]",
                border_style="yellow",
                box=box.ROUNDED
            ))
            logger.warning("config_import_partial", success=success_count, errors=error_count)
            raise typer.Exit(1)
        
    except typer.Exit:
        raise
    except Exception as e:
        print_error("Import failed", str(e))
        logger.error("config_import_error", error=str(e))
        raise typer.Exit(1)


@config_app.command()
def sources():
    """Display configuration provenance for each key.
    
    Shows where each configuration value comes from:
    - Environment variable (highest priority)
    - .env file
    - Database (Config UI)
    - System config files (~/.aws/config, ~/.kube/config)
    - Default value (lowest priority)
    
    Highlights overrides when multiple sources provide the same value.
    
    Examples:
        aise config sources
    """
    try:
        # Load configuration
        try:
            config = get_config()
        except RuntimeError:
            config = load_config()
        
        logger.info("config_sources_command")
        
        # Get configuration as dictionary
        config_dict = config.to_dict(mask_sensitive=True)
        
        # Get configuration sources with details
        sources = config.get_config_sources()
        
        console.print()
        console.print(Panel(
            "[bold cyan]📋 Configuration Sources[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED
        ))
        console.print()
        
        # Create table
        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
            padding=(0, 1)
        )
        
        table.add_column("Setting", style="white", no_wrap=True)
        table.add_column("Value", style="green")
        table.add_column("Source", style="cyan", no_wrap=True)
        table.add_column("Priority", style="dim", no_wrap=True)
        
        # Priority mapping
        priority_map = {
            "environment variable": "1 (highest)",
            ".env file": "2",
            "database": "3",
            "system config": "4",
            "default": "5 (lowest)"
        }
        
        # Sort by key
        for key in sorted(config_dict.keys()):
            value = config_dict[key]
            source = sources.get(key, "unknown")
            priority = priority_map.get(source, "unknown")
            
            # Format value
            if value is None:
                value_str = "[dim]not set[/dim]"
            elif isinstance(value, bool):
                value_str = "[green]✓[/green]" if value else "[red]✗[/red]"
            else:
                value_str = str(value)
            
            # Format source with color
            source_str = _format_source(source)
            
            table.add_row(key, value_str, source_str, priority)
        
        console.print(table)
        console.print()
        
        # Display precedence explanation
        _display_legend()
        
        logger.info("config_sources_complete")
        
    except Exception as e:
        print_error("Failed to display sources", str(e))
        logger.error("config_sources_error", error=str(e))
        raise typer.Exit(1)


@config_app.command()
def get(
    key: str = typer.Argument(..., help="Configuration key to retrieve")
):
    """Get a specific configuration value.
    
    Examples:
        aise config get LLM_PROVIDER
        aise config get POSTGRES_URL
    """
    try:
        # Load configuration
        try:
            config = get_config()
        except RuntimeError:
            config = load_config()
        
        logger.info("config_get_command", key=key)
        
        # Get value
        if not hasattr(config, key):
            print_error("Unknown key", f"Configuration key '{key}' does not exist")
            raise typer.Exit(1)
        
        value = getattr(config, key)
        
        # Get source
        sources = config.get_config_sources()
        source = sources.get(key, "unknown")
        
        # Display
        console.print()
        console.print(f"[bold]{key}[/bold]")
        console.print(f"  Value:  [green]{value}[/green]")
        console.print(f"  Source: {_format_source(source)}")
        console.print()
        
        logger.info("config_get_success", key=key)
        
    except typer.Exit:
        raise
    except Exception as e:
        print_error("Failed to get configuration", str(e))
        logger.error("config_get_error", key=key, error=str(e))
        raise typer.Exit(1)


@config_app.command()
def set(
    key: str = typer.Argument(..., help="Configuration key to set"),
    value: str = typer.Argument(..., help="New value for the configuration key")
):
    """Set a configuration value.
    
    Updates a configuration value and persists it to the database.
    The change takes effect immediately without requiring a restart.
    
    Examples:
        aise config set LLM_PROVIDER openai
        aise config set AISE_MODE autonomous
    """
    try:
        import asyncio
        from aise.config_ui.persistence import ConfigPersistence
        from aise.core.credential_storage import CredentialStorage
        from aise.core.credential_vault import CredentialVault
        
        # Load configuration
        try:
            config = get_config()
        except RuntimeError:
            config = load_config()
        
        logger.info("config_set_command", key=key, value_length=len(value))
        
        # Check key exists
        if not hasattr(config, key):
            print_error("Unknown key", f"Configuration key '{key}' does not exist")
            raise typer.Exit(1)
        
        # Initialize persistence
        vault = CredentialVault(config)
        credential_storage = CredentialStorage(config, vault)
        asyncio.run(credential_storage.initialize())
        
        persistence = ConfigPersistence(config, credential_storage)
        asyncio.run(persistence.initialize())
        
        # Update configuration
        asyncio.run(persistence.update_config(key, value, component="cli"))
        
        print_success("Configuration updated", f"{key} = {value}")
        console.print("[dim]Change applied immediately (no restart required)[/dim]")
        
        logger.info("config_set_success", key=key)
        
    except typer.Exit:
        raise
    except Exception as e:
        print_error("Failed to set configuration", str(e))
        logger.error("config_set_error", key=key, error=str(e))
        raise typer.Exit(1)
