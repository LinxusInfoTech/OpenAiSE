# aise/tool_executor/base.py
"""Tool execution interface and data models.

This module provides the main ToolExecutor class that integrates allowlist
validation with subprocess execution, and defines the ToolResult data model.

Requirements:
- 9.3: Return ToolResult with structured output
- 9.10: Audit log all command executions
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

from aise.tool_executor.allowlist import CommandAllowlist
from aise.tool_executor.runner import SubprocessRunner
from aise.core.exceptions import ForbiddenCommandError, ToolExecutionError
from aise.observability.tracer import get_tracer, tool_span
from aise.observability.metrics import record_tool_execution

logger = structlog.get_logger(__name__)


@dataclass
class ToolResult:
    """Result of tool execution with structured output.
    
    This data class encapsulates all information about a command execution,
    including the command itself, output, exit code, duration, and optional
    parsed output.
    
    Attributes:
        command: The executed command string
        stdout: Standard output as string
        stderr: Standard error as string
        exit_code: Process exit code (0 = success)
        duration_ms: Execution duration in milliseconds
        parsed_output: Optional structured/parsed output (e.g., JSON)
        anomalies: Optional list of detected anomalies or error patterns
        timestamp: ISO 8601 timestamp of execution
    """
    command: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    parsed_output: Optional[Dict[str, Any]] = None
    anomalies: Optional[List[str]] = None
    timestamp: str = None
    
    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()
    
    def is_success(self) -> bool:
        """Check if command executed successfully.
        
        Returns:
            True if exit code is 0, False otherwise
        """
        return self.exit_code == 0
    
    def has_output(self) -> bool:
        """Check if command produced any output.
        
        Returns:
            True if stdout or stderr is non-empty
        """
        return bool(self.stdout.strip() or self.stderr.strip())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation.
        
        Returns:
            Dictionary with all fields
        """
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "parsed_output": self.parsed_output,
            "anomalies": self.anomalies,
            "timestamp": self.timestamp
        }


class ToolExecutor:
    """Executes CLI commands with allowlist validation and audit logging.
    
    This class integrates the CommandAllowlist and SubprocessRunner to provide
    secure command execution with:
    - Allowlist validation before execution
    - Subprocess execution without shell=True
    - Timeout enforcement
    - Structured output capture
    - Comprehensive audit logging
    
    The ToolExecutor is the main interface for executing CLI tools in the AiSE
    system. All tool executions should go through this class to ensure security
    and auditability.
    
    Attributes:
        allowlist: CommandAllowlist instance for validation
        runner: SubprocessRunner instance for execution
        audit_log: List of all executed commands (for audit trail)
    """
    
    def __init__(
        self,
        allowlist: Optional[CommandAllowlist] = None,
        runner: Optional[SubprocessRunner] = None,
        default_timeout: int = 30
    ):
        """Initialize the tool executor.
        
        Args:
            allowlist: CommandAllowlist instance (creates default if not provided)
            runner: SubprocessRunner instance (creates default if not provided)
            default_timeout: Default timeout in seconds for command execution
        """
        self.allowlist = allowlist or CommandAllowlist()
        self.runner = runner or SubprocessRunner(default_timeout=default_timeout)
        self.audit_log: List[Dict[str, Any]] = []
        self._tracer = get_tracer("aise.tool_executor")
        
        logger.info(
            "ToolExecutor initialized",
            default_timeout=default_timeout,
            allowed_commands=list(self.allowlist.get_allowed_commands().keys())
        )
    
    async def run(
        self,
        command: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None
    ) -> ToolResult:
        """Execute a command with allowlist validation and audit logging.
        
        This is the main method for executing CLI commands. It:
        1. Validates the command against the allowlist
        2. Executes the command in a restricted subprocess
        3. Captures structured output
        4. Logs the execution for audit purposes
        5. Returns a ToolResult with all execution details
        
        Args:
            command: Full command string to execute
            timeout: Timeout in seconds (uses runner's default if not specified)
            env: Additional environment variables
            cwd: Working directory for command execution
        
        Returns:
            ToolResult with execution details
        
        Raises:
            ForbiddenCommandError: If command is not in allowlist
            ToolExecutionTimeout: If command exceeds timeout
            ToolExecutionError: If command execution fails
        
        Example:
            >>> executor = ToolExecutor()
            >>> result = await executor.run("aws ec2 describe-instances")
            >>> print(result.exit_code)
            0
            >>> print(result.stdout)
            {...JSON output...}
        """
        # Step 1: Validate command against allowlist
        try:
            self.allowlist.validate_or_raise(command)
        except ForbiddenCommandError as e:
            # Audit log the forbidden attempt
            self._audit_log_execution(
                command=command,
                exit_code=-1,
                duration_ms=0,
                error="Forbidden command blocked",
                timestamp=datetime.utcnow().isoformat()
            )
            tool_name = command.split()[0] if command else "unknown"
            record_tool_execution(tool_name, "forbidden", 0.0)
            raise
        
        # Step 2: Execute command
        start_time = datetime.utcnow()
        
        try:
            import time as _time
            _t0 = _time.monotonic()
            with tool_span(self._tracer, command) as span:
                result_dict = await self.runner.run(
                    command=command,
                    timeout=timeout,
                    env=env,
                    cwd=cwd
                )
                
                # Step 3: Create ToolResult
                tool_result = ToolResult(
                    command=result_dict["command"],
                    stdout=result_dict["stdout"],
                    stderr=result_dict["stderr"],
                    exit_code=result_dict["exit_code"],
                    duration_ms=result_dict["duration_ms"],
                    timestamp=start_time.isoformat()
                )
                
                span.set_attribute("tool.exit_code", tool_result.exit_code)
                span.set_attribute("tool.duration_ms", tool_result.duration_ms)
            
            _duration = _time.monotonic() - _t0
            tool_name = command.split()[0] if command else "unknown"
            status = "success" if tool_result.exit_code == 0 else "failure"
            record_tool_execution(tool_name, status, _duration)
            
            # Step 4: Audit log the execution
            self._audit_log_execution(
                command=command,
                exit_code=tool_result.exit_code,
                duration_ms=tool_result.duration_ms,
                stdout_length=len(tool_result.stdout),
                stderr_length=len(tool_result.stderr),
                timestamp=tool_result.timestamp
            )
            
            return tool_result
        
        except Exception as e:
            # Audit log the failure
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self._audit_log_execution(
                command=command,
                exit_code=-1,
                duration_ms=duration_ms,
                error=str(e),
                timestamp=start_time.isoformat()
            )
            raise
    
    async def run_with_input(
        self,
        command: str,
        stdin_data: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None
    ) -> ToolResult:
        """Execute a command with stdin input.
        
        Similar to run() but allows passing data to stdin.
        
        Args:
            command: Full command string to execute
            stdin_data: Data to send to stdin
            timeout: Timeout in seconds
            env: Additional environment variables
            cwd: Working directory
        
        Returns:
            ToolResult with execution details
        
        Raises:
            ForbiddenCommandError: If command is not in allowlist
            ToolExecutionTimeout: If command exceeds timeout
            ToolExecutionError: If command execution fails
        """
        # Validate command
        try:
            self.allowlist.validate_or_raise(command)
        except ForbiddenCommandError as e:
            self._audit_log_execution(
                command=command,
                exit_code=-1,
                duration_ms=0,
                error="Forbidden command blocked",
                timestamp=datetime.utcnow().isoformat()
            )
            raise
        
        start_time = datetime.utcnow()
        
        try:
            result_dict = await self.runner.run_with_input(
                command=command,
                stdin_data=stdin_data,
                timeout=timeout,
                env=env,
                cwd=cwd
            )
            
            tool_result = ToolResult(
                command=result_dict["command"],
                stdout=result_dict["stdout"],
                stderr=result_dict["stderr"],
                exit_code=result_dict["exit_code"],
                duration_ms=result_dict["duration_ms"],
                timestamp=start_time.isoformat()
            )
            
            self._audit_log_execution(
                command=command,
                exit_code=tool_result.exit_code,
                duration_ms=tool_result.duration_ms,
                stdin_length=len(stdin_data),
                timestamp=tool_result.timestamp
            )
            
            return tool_result
        
        except Exception as e:
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            self._audit_log_execution(
                command=command,
                exit_code=-1,
                duration_ms=duration_ms,
                error=str(e),
                timestamp=start_time.isoformat()
            )
            raise
    
    def _audit_log_execution(
        self,
        command: str,
        exit_code: int,
        duration_ms: int,
        timestamp: str,
        stdout_length: int = 0,
        stderr_length: int = 0,
        stdin_length: int = 0,
        error: Optional[str] = None
    ) -> None:
        """Log command execution for audit trail.
        
        This method maintains an in-memory audit log and logs to the
        structured logger for persistence.
        
        Args:
            command: Executed command
            exit_code: Process exit code
            duration_ms: Execution duration in milliseconds
            timestamp: ISO 8601 timestamp
            stdout_length: Length of stdout
            stderr_length: Length of stderr
            stdin_length: Length of stdin (if applicable)
            error: Error message (if execution failed)
        """
        audit_entry = {
            "timestamp": timestamp,
            "command": command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stdout_length": stdout_length,
            "stderr_length": stderr_length,
        }
        
        if stdin_length > 0:
            audit_entry["stdin_length"] = stdin_length
        
        if error:
            audit_entry["error"] = error
        
        # Add to in-memory audit log
        self.audit_log.append(audit_entry)
        
        # Log to structured logger for persistence
        if error:
            logger.error("Tool execution failed", **audit_entry)
        elif exit_code != 0:
            logger.warning("Tool execution completed with error", **audit_entry)
        else:
            logger.info("Tool execution completed successfully", **audit_entry)
    
    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get the audit log of all command executions.
        
        Returns:
            List of audit log entries
        """
        return self.audit_log.copy()
    
    def clear_audit_log(self) -> None:
        """Clear the in-memory audit log.
        
        Note: This only clears the in-memory log. Structured logs
        are persisted and not affected by this method.
        """
        self.audit_log.clear()
        logger.info("Audit log cleared")
    
    def get_allowed_commands(self) -> Dict[str, List[str]]:
        """Get the current allowlist configuration.
        
        Returns:
            Dictionary mapping command names to allowed subcommands
        """
        return self.allowlist.get_allowed_commands()
