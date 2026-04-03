"""
Log parser for extracting errors, stack traces, and patterns from Jenkins logs.
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum


class FailureCategory(Enum):
    COMPILATION_ERROR = "compilation_error"
    TEST_FAILURE = "test_failure"
    INFRASTRUCTURE = "infrastructure"
    DEPENDENCY = "dependency"
    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    NETWORK = "network"
    PERMISSION = "permission"
    RESOURCE = "resource"
    # Groovy/Pipeline specific categories
    GROOVY_LIBRARY = "groovy_library"
    GROOVY_CPS = "groovy_cps"
    GROOVY_SANDBOX = "groovy_sandbox"
    GROOVY_SERIALIZATION = "groovy_serialization"
    CREDENTIAL_ERROR = "credential_error"
    AGENT_ERROR = "agent_error"
    PLUGIN_ERROR = "plugin_error"
    # Tool/CLI errors (internal and external tools)
    TOOL_ERROR = "tool_error"
    UNKNOWN = "unknown"


class PipelineLineType(Enum):
    """Classification of Jenkins Pipeline log lines (Requirement 20.1)."""
    PIPELINE_STEP = "pipeline_step"       # [Pipeline] <something> (not stage/echo/sh)
    PIPELINE_ECHO = "pipeline_echo"       # [Pipeline] echo
    ECHO_OUTPUT = "echo_output"           # Line following [Pipeline] echo
    PIPELINE_SH = "pipeline_sh"           # [Pipeline] sh
    SHELL_COMMAND = "shell_command"       # HH:MM:SS + <command>
    SHELL_OUTPUT = "shell_output"         # Output of shell command
    PIPELINE_STAGE = "pipeline_stage"     # [Pipeline] stage or [Pipeline] { (stage_name)
    METHOD_TAG = "method_tag"             # Method execution tag
    OTHER = "other"                       # Anything else


@dataclass
class ToolInvocation:
    """Represents a detected tool invocation in the log (Requirement 17.2)."""
    tool_name: str
    command_line: str
    line_number: int
    exit_code: Optional[int] = None
    output_lines: List[str] = field(default_factory=list)  # Req 19.3: output of the command
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "command_line": self.command_line,
            "line_number": self.line_number,
            "exit_code": self.exit_code,
            "output_lines": self.output_lines,
        }


@dataclass
class TraceStep:
    """Represents a step in the method execution trace (Requirement 19.3)."""
    step_type: str  # "tool", "command", "function_call", "output"
    name: str  # tool name or function name
    command_line: str  # full command as it appeared in log
    output_lines: List[str] = field(default_factory=list)  # output following the command
    exit_code: Optional[int] = None
    status: str = "unknown"  # "success", "failed", "unknown"
    line_number: int = 0
    source_line_ref: Optional[str] = None  # Reference to source code line (Req 19.9)
    line_type: Optional[PipelineLineType] = None  # Req 20.5: Line classification
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "name": self.name,
            "command_line": self.command_line,
            "output_lines": self.output_lines,
            "exit_code": self.exit_code,
            "status": self.status,
            "line_number": self.line_number,
            "source_line_ref": self.source_line_ref,
            "line_type": self.line_type.value if self.line_type else None,
        }


@dataclass
class MethodExecutionTrace:
    """Ordered trace of steps executed within a method (Requirement 19.2)."""
    method_name: str
    steps: List[TraceStep] = field(default_factory=list)
    failure_step_index: Optional[int] = None  # Req 19.5: Index of step that failed
    start_line: int = 0
    end_line: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "method_name": self.method_name,
            "steps": [s.to_dict() for s in self.steps],
            "failure_step_index": self.failure_step_index,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }
    
    def format_for_prompt(self) -> str:
        """Format trace for AI prompt (Requirement 19.6)."""
        lines = [
            f"METHOD EXECUTION TRACE: {self.method_name}",
            "=" * (24 + len(self.method_name)),
        ]
        
        for i, step in enumerate(self.steps, 1):
            status_str = "SUCCESS" if step.status == "success" else (
                "FAILED" if step.status == "failed" else "UNKNOWN"
            )
            exit_str = f" (exit {step.exit_code})" if step.exit_code is not None else ""
            
            # Mark failure point
            marker = "→" if step.status == "failed" else " "
            
            lines.append(f"[{i}]{marker} {step.command_line} → {status_str}{exit_str}")
            
            # Include output for failed steps or last few lines
            if step.output_lines and (step.status == "failed" or i == len(self.steps)):
                for out_line in step.output_lines[:10]:  # Limit output lines
                    lines.append(f"    {out_line}")
            
            # Mark not reached steps
            if self.failure_step_index is not None and i > self.failure_step_index + 1:
                lines[-1] = f"[{i}]  {step.command_line} → NOT REACHED"
        
        return "\n".join(lines)


@dataclass
class ErrorMatch:
    """Represents a matched error in the log."""
    line_number: int
    line: str
    pattern_matched: str
    category: FailureCategory
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    severity: str = "ERROR"
    # Requirement 17.4: Related tool invocation
    related_tool: Optional[ToolInvocation] = None


@dataclass
class StackTrace:
    """Represents a parsed stack trace."""
    exception_type: str
    message: str
    frames: List[Dict[str, str]] = field(default_factory=list)
    caused_by: Optional["StackTrace"] = None
    raw_text: str = ""


@dataclass
class ParsedLog:
    """Represents a fully parsed log with extracted information."""
    total_lines: int
    errors: List[ErrorMatch] = field(default_factory=list)
    stack_traces: List[StackTrace] = field(default_factory=list)
    failed_stage: Optional[str] = None
    failed_method: Optional[str] = None  # Shared library method that was running when failure occurred
    primary_category: FailureCategory = FailureCategory.UNKNOWN
    timestamps: List[Tuple[int, str]] = field(default_factory=list)
    summary: str = ""
    
    # Requirement 1.11: Full method call sequence from method tags
    method_call_sequence: List[str] = field(default_factory=list)
    
    # Active methods at failure time (started but not finished)
    active_methods: List[str] = field(default_factory=list)
    
    # Requirement 13.4: Full stage sequence from pipeline tags
    stage_sequence: List[str] = field(default_factory=list)
    
    # Requirement 17.3: Tool invocations detected in the log
    tool_invocations: List[ToolInvocation] = field(default_factory=list)
    
    # Requirement 19.4: Method execution trace when failed_method is identified
    method_execution_trace: Optional[MethodExecutionTrace] = None


class LogParser:
    """Parser for Jenkins build logs."""
    
    # Predefined error patterns by category
    DEFAULT_PATTERNS = {
        FailureCategory.COMPILATION_ERROR: [
            r"(?i)cannot find symbol",
            r"(?i)compilation failed",
            r"(?i)build failed",
            r"(?i)syntax error",
            r"SyntaxError:",
            r"ModuleNotFoundError:",
            r"ImportError:",
            r"(?i)undefined reference",
            r"(?i)unresolved external symbol",
            r"error: .*\.java:\d+:",
            r"error TS\d+:",  # TypeScript
            r"error\[E\d+\]:",  # Rust
        ],
        FailureCategory.TEST_FAILURE: [
            r"(?i)test.*failed",
            r"(?i)tests? failed",
            r"AssertionError",
            r"(?i)assertion failed",
            r"Expected .* but got",
            r"expected:<.*> but was:<.*>",
            r"FAILED\s+\[",
            r"✗|✘|❌",  # Failure markers
            r"pytest.*FAILED",
            r"FAIL:",
        ],
        FailureCategory.INFRASTRUCTURE: [
            r"(?i)out of memory",
            r"(?i)cannot allocate memory",
            r"(?i)no space left on device",
            r"(?i)disk quota exceeded",
            r"OOMKilled",
            r"(?i)killed by signal",
            r"(?i)segmentation fault",
            r"SIGSEGV",
            r"(?i)core dumped",
        ],
        FailureCategory.DEPENDENCY: [
            r"(?i)could not resolve dependencies",
            r"(?i)dependency .* not found",
            r"(?i)package .* not found",
            r"(?i)module .* not found",
            r"npm ERR!",
            r"yarn error",
            r"pip.*error",
            r"(?i)version conflict",
            r"(?i)incompatible version",
            r"ERESOLVE",
            r"(?i)failed to download",
        ],
        FailureCategory.CONFIGURATION: [
            r"(?i)missing required",
            r"(?i)configuration error",
            r"(?i)invalid.*config",
            r"(?i)environment variable.*not set",
            r"(?i)missing environment",
            r"(?i)file not found",
            r"FileNotFoundException",
            r"(?i)no such file or directory",
        ],
        FailureCategory.TIMEOUT: [
            r"(?i)timed? ?out",
            r"(?i)timeout exceeded",
            r"(?i)deadline exceeded",
            r"(?i)operation timed out",
            r"TimeoutError",
            r"TimeoutException",
        ],
        FailureCategory.NETWORK: [
            r"(?i)connection refused",
            r"(?i)connection reset",
            r"(?i)network unreachable",
            r"(?i)host not found",
            r"(?i)dns lookup failed",
            r"ECONNREFUSED",
            r"ECONNRESET",
            r"ETIMEDOUT",
            r"(?i)ssl.*error",
            r"(?i)certificate.*error",
        ],
        FailureCategory.PERMISSION: [
            r"(?i)permission denied",
            r"(?i)access denied",
            r"(?i)unauthorized",
            r"(?i)forbidden",
            r"EACCES",
            r"EPERM",
            r"401 Unauthorized",
            r"403 Forbidden",
        ],
        FailureCategory.RESOURCE: [
            r"(?i)resource .* not found",
            r"(?i)service unavailable",
            r"503 Service Unavailable",
            r"502 Bad Gateway",
            r"504 Gateway Timeout",
            r"(?i)database.*error",
            r"(?i)connection pool exhausted",
        ],
        # Groovy/Pipeline specific patterns
        FailureCategory.GROOVY_LIBRARY: [
            r"(?i)Unable to find source for class",
            r"(?i)Could not find shared library",
            r"(?i)Library.*not found",
            r"(?i)@Library.*does not exist",
            r"(?i)Branch .* not found",
            r"(?i)Unable to checkout revision",
            r"(?i)vars/\w+\.groovy.*not found",
        ],
        FailureCategory.GROOVY_CPS: [
            r"(?i)CpsCallableInvocation",
            r"(?i)CPS-transformed.*cannot be invoked",
            r"(?i)expected to call.*wound up catching",
            r"(?i)Continuation passing style",
            r"(?i)cannot be CPS transformed",
            r"(?i)CpsScript\.invokeMethod",
        ],
        FailureCategory.GROOVY_SANDBOX: [
            r"(?i)Scripts not permitted to use",
            r"(?i)RejectedAccessException",
            r"(?i)script-security sandbox",
            r"(?i)Administrator approval is required",
            r"(?i)Waiting for approval",
        ],
        FailureCategory.GROOVY_SERIALIZATION: [
            r"(?i)java\.io\.NotSerializableException",
            r"(?i)Unable to serialize",
            r"(?i)cannot be serialized",
            r"(?i)Expected to find a CPS-transformed",
        ],
        FailureCategory.CREDENTIAL_ERROR: [
            r"(?i)CredentialsNotFoundException",
            r"(?i)Could not find credentials",
            r"(?i)No credentials with id",
            r"(?i)Unable to find credentials",
            r"(?i)Credential.*not found",
            r"(?i)withCredentials.*failed",
        ],
        FailureCategory.AGENT_ERROR: [
            r"(?i)There are no nodes with the label",
            r"(?i)Still waiting for",
            r"(?i)Agent.*is offline",
            r"(?i)Node.*offline",
            r"(?i)Waiting for next available executor",
        ],
        FailureCategory.PLUGIN_ERROR: [
            r"(?i)Plugin.*not found",
            r"(?i)Required plugin.*not installed",
            r"(?i)No such DSL method",
            r"(?i)java\.lang\.NoClassDefFoundError.*plugin",
            r"(?i)Incompatible plugin version",
        ],
        # Tool/CLI errors - errors from shell commands (internal and external tools)
        FailureCategory.TOOL_ERROR: [
            # Generic "Error:" patterns from tools (Helm, Terraform, custom tools, etc.)
            r"^Error:\s+.+",
            r"^\[ERROR\]\s+.+",
            r"^ERROR:\s+.+",
            r"^error:\s+.+",
            # Cloud CLI errors
            r"(?i)An error occurred \(",  # AWS error format
            r"(?i)ERROR:.*gcloud",
            r"(?i)az:.*error",
            # Kubernetes/Helm errors
            r"(?i)UPGRADE FAILED",
            r"(?i)INSTALLATION FAILED",
            r"(?i)error:.*kubectl",
            r"(?i)cannot validate",
            # Terraform errors
            r"(?i)Error:.*terraform",
            r"(?i)Error applying plan",
            # Docker errors
            r"(?i)error during connect",
            r"(?i)Error response from daemon",
            # Generic script/tool errors
            r"(?i)script returned exit code [1-9]",
            r"(?i)command not found",
            r"(?i)fatal:\s+.+",  # Git fatal errors
            r"(?i)FATAL:\s+.+",
            # Exit code patterns
            r"(?i)exit status [1-9]",
            r"(?i)exited with code [1-9]",
            # Generic tool failure patterns
            r"(?i)failed to execute",
            r"(?i)execution failed",
            r"(?i)command failed",
            r"(?i)unable to execute",
        ],
        # Generic/Unknown errors - fallback
        FailureCategory.UNKNOWN: [
            r"(?i)Exception:",
            r"(?i)Error$",  # Just "Error" at end of line
        ],
    }
    
    # Stack trace patterns for different languages
    STACK_TRACE_PATTERNS = {
        "java": re.compile(
            r"(?P<exception>[\w.]+(?:Exception|Error|Throwable)):\s*(?P<message>.*?)\n"
            r"(?P<frames>(?:\s+at\s+.*\n)+)",
            re.MULTILINE
        ),
        "groovy": re.compile(
            r"(?P<exception>groovy\.lang\.\w+(?:Exception|Error)|"
            r"org\.jenkinsci\.plugins\.scriptsecurity\.\w+|"
            r"org\.codehaus\.groovy\.\w+(?:Exception|Error)):\s*(?P<message>.*?)\n"
            r"(?P<frames>(?:\s+at\s+.*\n)+)",
            re.MULTILINE
        ),
        "groovy_cps": re.compile(
            r"(?P<exception>[\w.]+(?:Exception|Error)).*?(?:CPS|workflow).*?:\s*(?P<message>.*?)\n"
            r"(?P<frames>(?:\s+at\s+.*\n)+)",
            re.MULTILINE | re.IGNORECASE
        ),
        "python": re.compile(
            r"Traceback \(most recent call last\):\n"
            r"(?P<frames>(?:\s+File .*\n\s+.*\n)+)"
            r"(?P<exception>\w+(?:Error|Exception)):\s*(?P<message>.*)",
            re.MULTILINE
        ),
        "javascript": re.compile(
            r"(?P<exception>\w+(?:Error|Exception)):\s*(?P<message>.*?)\n"
            r"(?P<frames>(?:\s+at\s+.*\n)+)",
            re.MULTILINE
        ),
        "go": re.compile(
            r"panic:\s*(?P<message>.*?)\n\n"
            r"goroutine.*:\n(?P<frames>(?:.*\n)+?)(?:\n\n|$)",
            re.MULTILINE
        ),
    }
    
    # Stage detection patterns
    STAGE_PATTERNS = [
        r"\[Pipeline\]\s*{\s*\((?P<stage>[^)]+)\)",
        r"Stage\s*['\"](?P<stage>[^'\"]+)['\"].*(?:FAILED|ERROR)",
        r">>>.*stage:\s*(?P<stage>\w+)",
        r"\[(?P<stage>[A-Z][a-zA-Z\s]+)\]\s*(?:FAILED|ERROR)",
    ]
    
    # Requirement 17.1: Built-in tool recognition patterns
    # Each entry: (tool_name, regex_pattern)
    BUILTIN_TOOL_PATTERNS = [
        # Cloud CLIs
        ("aws", r"^\s*\+?\s*(aws\s+.+)"),
        ("az", r"^\s*\+?\s*(az\s+.+)"),
        ("gcloud", r"^\s*\+?\s*(gcloud\s+.+)"),
        # Kubernetes/Container
        ("kubectl", r"^\s*\+?\s*(kubectl\s+.+)"),
        ("helm", r"^\s*\+?\s*(helm\s+.+)"),
        ("docker", r"^\s*\+?\s*(docker\s+.+)"),
        # Infrastructure as Code
        ("terraform", r"^\s*\+?\s*(terraform\s+.+)"),
        # Build tools
        ("mvn", r"^\s*\+?\s*(mvn\s+.+|mvnw\s+.+)"),
        ("gradle", r"^\s*\+?\s*(gradle\s+.+|gradlew\s+.+|\./gradlew\s+.+)"),
        # Package managers
        ("npm", r"^\s*\+?\s*(npm\s+.+)"),
        ("yarn", r"^\s*\+?\s*(yarn\s+.+)"),
        ("pip", r"^\s*\+?\s*(pip3?\s+.+)"),
        # Shell commands (detect sh/bash script execution - NOT Jenkins Pipeline markers)
        # Must have actual command content, not just "[Pipeline] sh"
        ("sh", r"^\s*\+\s*(sh\s+-c\s+.+|bash\s+-c\s+.+)"),
        ("bash", r"^\s*\+\s*(/bin/(?:ba)?sh\s+.+)"),
        # Network tools
        ("curl", r"^\s*\+?\s*(curl\s+.+)"),
        ("wget", r"^\s*\+?\s*(wget\s+.+)"),
    ]
    
    # Exit code detection patterns
    EXIT_CODE_PATTERNS = [
        r"exit code[:\s]+(\d+)",
        r"returned (\d+)",
        r"exited with (\d+)",
        r"status[:\s]+(\d+)",
        r"rc=(\d+)",
        r"Return code[:\s]+(\d+)",
    ]
    
    # Requirement 20.2: Shell command pattern - HH:MM:SS + <command>
    # The + might have optional space after it
    SHELL_COMMAND_PATTERN = re.compile(r"^\d{2}:\d{2}:\d{2}\s+\+\s*(.+)")
    
    # Requirement 19.8: Failure indicators in command output
    OUTPUT_FAILURE_PATTERNS = [
        r"(?i)^error:",
        r"(?i)Error:",
        r"(?i)FAILED",
        r"(?i)Exception",
        r"(?i)fatal:",
        r"(?i)cannot\s",
        r"(?i)invalid\s",
        r"(?i)not found",
        r"(?i)permission denied",
        r"(?i)access denied",
        r"(?i)unable to",
        r"(?i)failed to",
    ]
    
    # How many lines after a tool invocation to look for related errors
    TOOL_ERROR_PROXIMITY = 20
    
    # Req 19.7: Max output lines to collect per command
    MAX_OUTPUT_LINES = 30
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_lines = self.config.get("error_context_lines", 10)
        self.max_log_size = self.config.get("max_log_size", 10 * 1024 * 1024)
        
        # Configurable prefix for method execution tracking
        # Pattern: "{prefix}: method_name"
        self.method_execution_prefix = self.config.get("method_execution_prefix", "")
        
        # Req 19.7: Configurable max output lines
        self.max_output_lines = self.config.get("max_output_lines", self.MAX_OUTPUT_LINES)
        
        # Requirement 17.7, 17.10: Combine built-in + custom tool patterns
        self.tool_patterns = []
        
        # Add built-in patterns
        for tool_name, pattern in self.BUILTIN_TOOL_PATTERNS:
            self.tool_patterns.append((tool_name, re.compile(pattern, re.IGNORECASE)))
        
        # Add custom patterns from config (Req 17.7)
        custom_tool_patterns = self.config.get("tool_patterns", [])
        for entry in custom_tool_patterns:
            if isinstance(entry, dict) and "name" in entry and "pattern" in entry:
                try:
                    self.tool_patterns.append((
                        entry["name"],
                        re.compile(entry["pattern"], re.IGNORECASE)
                    ))
                except re.error:
                    pass  # Skip invalid patterns
        
        # Compile exit code patterns
        self.exit_code_patterns = [re.compile(p, re.IGNORECASE) for p in self.EXIT_CODE_PATTERNS]
        
        # Compile output failure patterns (Req 19.8)
        self.output_failure_patterns = [re.compile(p) for p in self.OUTPUT_FAILURE_PATTERNS]
        
        # Compile custom patterns from config
        self.custom_patterns = {}
        for category_name, category_config in self.config.get("categories", {}).items():
            try:
                category = FailureCategory(category_name)
                patterns = category_config.get("patterns", [])
                self.custom_patterns[category] = [re.compile(p) for p in patterns]
            except ValueError:
                pass
    
    def classify_line(self, line: str, in_sh_block: bool = False, prev_line_type: PipelineLineType = None) -> PipelineLineType:
        """
        Classify a Jenkins Pipeline log line by type (Requirement 20.7).
        
        Args:
            line: The log line to classify
            in_sh_block: Whether we're currently inside a shell block
            prev_line_type: The type of the previous line (for ECHO_OUTPUT detection)
            
        Returns:
            PipelineLineType classification
        """
        line_stripped = line.strip()
        
        # Method tag detection (using configured prefix)
        if self.method_execution_prefix and self.method_execution_prefix in line:
            return PipelineLineType.METHOD_TAG
        
        # Pipeline markers
        if line_stripped.startswith("[Pipeline]"):
            rest = line_stripped[10:].strip()
            
            if rest.startswith("stage") or rest.startswith("{ ("):
                return PipelineLineType.PIPELINE_STAGE
            elif rest == "echo":
                return PipelineLineType.PIPELINE_ECHO
            elif rest == "sh":
                return PipelineLineType.PIPELINE_SH
            else:
                return PipelineLineType.PIPELINE_STEP
        
        # Echo output (line after [Pipeline] echo)
        if prev_line_type == PipelineLineType.PIPELINE_ECHO:
            return PipelineLineType.ECHO_OUTPUT
        
        # Shell command detection (Req 20.2, 20.8)
        if in_sh_block:
            if self.SHELL_COMMAND_PATTERN.match(line_stripped):
                return PipelineLineType.SHELL_COMMAND
            else:
                return PipelineLineType.SHELL_OUTPUT
        
        return PipelineLineType.OTHER
    
    def _extract_shell_command(self, line: str) -> Optional[str]:
        """
        Extract command from shell command line (Req 20.8).
        Strips timestamp and + prefix.
        
        Example: "09:00:01 + abc_tool --s -file_config=filepath"
        Returns: "abc_tool --s -file_config=filepath"
        """
        match = self.SHELL_COMMAND_PATTERN.match(line.strip())
        if match:
            return match.group(1)
        return None
    
    def _detect_output_failure(self, output_lines: List[str]) -> bool:
        """
        Check if output lines indicate a failure (Req 19.8).
        """
        for line in output_lines:
            for pattern in self.output_failure_patterns:
                if pattern.search(line):
                    return True
        return False
    
    def parse(self, log_content: str) -> ParsedLog:
        """Parse a Jenkins log and extract errors, stack traces, and patterns.
        
        Strategy: Focus on the LAST stage since that's where errors usually are.
        Jenkins logs pattern: [Pipeline] stage / [Pipeline] { (stage_name)
        """
        
        # Truncate if too large - but keep the END (where errors are)
        if len(log_content) > self.max_log_size:
            # Keep the last portion of the log, not the first!
            log_content = log_content[-self.max_log_size:]
        
        lines = log_content.split("\n")
        result = ParsedLog(total_lines=len(lines))
        
        # FIRST: Find the last stage and full stage sequence (Req 13)
        last_stage_name, last_stage_start, stage_sequence = self._find_last_stage(lines)
        result.failed_stage = last_stage_name
        result.stage_sequence = stage_sequence
        
        # Find the method tracking info (Req 1)
        failed_method, method_call_sequence, active_methods = self._find_failed_method(lines)
        result.failed_method = failed_method
        result.method_call_sequence = method_call_sequence
        result.active_methods = active_methods
        
        # Focus on lines from the last stage onwards (or last 500 lines if no stage found)
        if last_stage_start >= 0:
            focus_lines = lines[last_stage_start:]
            focus_start_offset = last_stage_start
        else:
            # No stage found, focus on last 500 lines
            focus_start = max(0, len(lines) - 500)
            focus_lines = lines[focus_start:]
            focus_start_offset = focus_start
        
        # Extract errors from the focused section first (prioritize end of log)
        result.errors = self._extract_errors_from_end(focus_lines, focus_start_offset)
        
        # If no errors found in last stage, search the whole log
        if not result.errors:
            result.errors = self._extract_errors(lines)
        
        # Requirement 17.2, 17.3: Extract tool invocations (with shell block tracking - Req 20.4)
        result.tool_invocations = self._extract_tool_invocations_v2(lines)
        
        # Associate final exit code with failing tool
        self._associate_exit_code_with_failing_tool(result.tool_invocations, result.errors, lines)
        
        # Requirement 17.4: Associate errors with preceding tool invocations
        self._associate_errors_with_tools(result.errors, result.tool_invocations)
        
        # Requirement 19: Build method execution trace when failed_method is identified
        if result.failed_method:
            result.method_execution_trace = self._build_method_execution_trace(
                lines, result.failed_method, result.errors
            )
        
        # Extract stack traces - focus on the focused section
        focus_content = "\n".join(focus_lines)
        result.stack_traces = self._extract_stack_traces(focus_content)
        
        # If no stack traces found, try the whole log
        if not result.stack_traces:
            result.stack_traces = self._extract_stack_traces(log_content)
        
        # Extract timestamps
        result.timestamps = self._extract_timestamps(lines)
        
        # Determine primary category
        result.primary_category = self._determine_primary_category(result.errors)
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        return result
    
    def _extract_tool_invocations_v2(self, lines: List[str]) -> List[ToolInvocation]:
        """
        Extract tool invocations with shell block context tracking (Req 17.2, 20.4).
        
        Tracks shell blocks to correctly identify commands and their output.
        """
        invocations = []
        in_sh_block = False
        current_command: Optional[ToolInvocation] = None
        prev_line_type = PipelineLineType.OTHER
        
        for i, line in enumerate(lines):
            line_type = self.classify_line(line, in_sh_block, prev_line_type)
            
            # Track shell block state (Req 20.3)
            if line_type == PipelineLineType.PIPELINE_SH:
                in_sh_block = True
                prev_line_type = line_type
                continue
            elif line_type in (PipelineLineType.PIPELINE_STEP, PipelineLineType.PIPELINE_STAGE,
                              PipelineLineType.PIPELINE_ECHO):
                # Any [Pipeline] line except output ends the shell block
                in_sh_block = False
                if current_command:
                    invocations.append(current_command)
                    current_command = None
            
            # Shell command detection (Req 20.4)
            if line_type == PipelineLineType.SHELL_COMMAND:
                # Save previous command if any
                if current_command:
                    invocations.append(current_command)
                
                # Extract command from shell line (Req 20.8)
                command = self._extract_shell_command(line)
                if command:
                    # Detect tool name from command
                    tool_name = self._detect_tool_name(command)
                    current_command = ToolInvocation(
                        tool_name=tool_name,
                        command_line=command,
                        line_number=i + 1,
                        output_lines=[],
                    )
            
            # Collect output for current command (Req 20.4)
            elif line_type == PipelineLineType.SHELL_OUTPUT and current_command:
                if len(current_command.output_lines) < self.max_output_lines:
                    current_command.output_lines.append(line.strip())
                    
                    # Check for exit code in output
                    if current_command.exit_code is None:
                        for pattern in self.exit_code_patterns:
                            match = pattern.search(line)
                            if match:
                                try:
                                    current_command.exit_code = int(match.group(1))
                                except (ValueError, IndexError):
                                    pass
            
            # Also detect tools from non-shell context (original behavior)
            elif line_type == PipelineLineType.OTHER:
                # First check if this is a HH:MM:SS + command pattern (may appear outside shell block)
                shell_cmd_match = self.SHELL_COMMAND_PATTERN.match(line.strip())
                if shell_cmd_match:
                    command = shell_cmd_match.group(1)
                    tool_name = self._detect_tool_name(command)
                    if current_command:
                        invocations.append(current_command)
                    current_command = ToolInvocation(
                        tool_name=tool_name,
                        command_line=command,
                        line_number=i + 1,
                        output_lines=[],
                    )
                else:
                    # Check against known tool patterns
                    for tool_name, pattern in self.tool_patterns:
                        match = pattern.search(line)
                        if match:
                            command_line = match.group(1) if match.groups() else line.strip()
                            exit_code = self._find_exit_code(lines, i)
                            invocations.append(ToolInvocation(
                                tool_name=tool_name,
                                command_line=command_line.strip(),
                                line_number=i + 1,
                                exit_code=exit_code,
                            ))
                            break
            
            prev_line_type = line_type
        
        # Don't forget the last command
        if current_command:
            invocations.append(current_command)
        
        return invocations
    
    def _detect_tool_name(self, command: str) -> str:
        """
        Detect tool name from a command string.
        
        The tool name is the FIRST word after stripping:
        - Leading/trailing whitespace
        - Quotes around the command
        - Environment variable assignments (VAR=value)
        
        Examples:
          'abc -a read --file' -> 'abc'
          '/usr/bin/abc --file' -> 'abc'
          'VAR=1 abc --file' -> 'abc'
          '"abc" --file' -> 'abc'
        """
        if not command:
            return "shell"
        
        cmd = command.strip()
        
        # Strip surrounding quotes if present
        if (cmd.startswith('"') and '"' in cmd[1:]) or (cmd.startswith("'") and "'" in cmd[1:]):
            quote = cmd[0]
            end_quote = cmd.find(quote, 1)
            if end_quote > 0:
                cmd = cmd[1:end_quote]
        
        # Split by whitespace
        parts = cmd.split()
        if not parts:
            return "shell"
        
        # Skip environment variable assignments (VAR=value)
        idx = 0
        while idx < len(parts) and '=' in parts[idx] and not parts[idx].startswith('-'):
            idx += 1
        
        if idx >= len(parts):
            return parts[0].split('=')[0]  # Fallback to first part
        
        tool = parts[idx]
        
        # Handle path-based commands - extract just the filename
        if "/" in tool:
            tool = tool.split("/")[-1]
        
        # Strip any remaining quotes
        tool = tool.strip("'\"")
        
        # Known tools for normalization
        known_tools = {
            "aws", "az", "gcloud", "kubectl", "helm", "docker",
            "terraform", "mvn", "mvnw", "gradle", "gradlew",
            "npm", "yarn", "pip", "pip3", "curl", "wget",
            "git", "make", "python", "python3", "java", "node",
            "ansible", "packer", "vault", "consul",
        }
        
        if tool in known_tools:
            return tool
        
        return tool
    
    def _build_method_execution_trace(
        self,
        lines: List[str],
        failed_method: str,
        errors: List[ErrorMatch],
    ) -> Optional[MethodExecutionTrace]:
        """
        Build method execution trace (Requirement 19.1, 19.2).
        
        Extracts all log lines between the method's start and finish tags,
        then identifies tool invocations and their output.
        """
        if not self.method_execution_prefix or not failed_method:
            return None
        
        # Find method start and end (Req 19.1)
        start_pattern = f"{self.method_execution_prefix}: {failed_method}"
        finish_pattern = f"{self.method_execution_prefix}: Finished {failed_method}"
        
        start_line = -1
        end_line = len(lines)
        
        for i, line in enumerate(lines):
            if start_pattern in line and "Finished" not in line:
                start_line = i
            elif finish_pattern in line:
                end_line = i
                break
        
        if start_line < 0:
            return None
        
        # Extract method execution window (Req 19.1)
        method_lines = lines[start_line:end_line + 1]
        
        trace = MethodExecutionTrace(
            method_name=failed_method,
            start_line=start_line + 1,
            end_line=end_line + 1,
        )
        
        # Process method lines to extract trace steps (Req 19.2)
        in_sh_block = False
        current_step: Optional[TraceStep] = None
        prev_line_type = PipelineLineType.OTHER
        
        for rel_idx, line in enumerate(method_lines):
            abs_line_num = start_line + rel_idx + 1
            line_type = self.classify_line(line, in_sh_block, prev_line_type)
            
            # Track shell block state
            if line_type == PipelineLineType.PIPELINE_SH:
                in_sh_block = True
            elif line_type in (PipelineLineType.PIPELINE_STEP, PipelineLineType.PIPELINE_STAGE):
                in_sh_block = False
                if current_step:
                    self._finalize_trace_step(current_step)
                    trace.steps.append(current_step)
                    current_step = None
            
            # Create trace step for shell commands (Req 19.3)
            if line_type == PipelineLineType.SHELL_COMMAND:
                if current_step:
                    self._finalize_trace_step(current_step)
                    trace.steps.append(current_step)
                
                command = self._extract_shell_command(line)
                if command:
                    tool_name = self._detect_tool_name(command)
                    current_step = TraceStep(
                        step_type="tool" if tool_name != command.split()[0] else "command",
                        name=tool_name,
                        command_line=command,
                        line_number=abs_line_num,
                        line_type=line_type,
                    )
            
            # Collect output (Req 19.7)
            elif line_type == PipelineLineType.SHELL_OUTPUT and current_step:
                if len(current_step.output_lines) < self.max_output_lines:
                    current_step.output_lines.append(line.strip())
            
            prev_line_type = line_type
        
        # Finalize last step
        if current_step:
            self._finalize_trace_step(current_step)
            trace.steps.append(current_step)
        
        # Mark failure point (Req 19.5)
        for i, step in enumerate(trace.steps):
            if step.status == "failed":
                trace.failure_step_index = i
                break
        
        return trace if trace.steps else None
    
    def cross_reference_trace_with_source(
        self,
        trace: MethodExecutionTrace,
        source_tool_invocations: List[Any],
    ) -> MethodExecutionTrace:
        """
        Cross-reference trace steps with source code (Requirement 19.9).
        
        Matches each TraceStep to the corresponding source line
        based on tool name and command similarity.
        
        Args:
            trace: The method execution trace
            source_tool_invocations: List of SourceToolInvocation from GroovyAnalyzer
            
        Returns:
            Updated trace with source_line_ref populated
        """
        if not trace or not source_tool_invocations:
            return trace
        
        # Build a lookup by tool name
        tool_to_sources = {}
        for inv in source_tool_invocations:
            tool_name = inv.tool_name if hasattr(inv, 'tool_name') else inv.get('tool_name', '')
            if tool_name not in tool_to_sources:
                tool_to_sources[tool_name] = []
            tool_to_sources[tool_name].append(inv)
        
        # Match each step to source
        for step in trace.steps:
            if step.name not in tool_to_sources:
                continue
            
            sources = tool_to_sources[step.name]
            
            # Find best match based on command similarity
            best_match = None
            best_score = 0
            
            for src in sources:
                cmd_template = (
                    src.command_template if hasattr(src, 'command_template')
                    else src.get('command_template', '')
                )
                
                # Score based on common substrings
                score = self._command_similarity(step.command_line, cmd_template)
                if score > best_score:
                    best_score = score
                    best_match = src
            
            # Set source reference if match found
            if best_match and best_score > 0.3:  # Threshold for match
                src_file = (
                    best_match.source_file if hasattr(best_match, 'source_file')
                    else best_match.get('source_file', '')
                )
                src_line = (
                    best_match.line_number if hasattr(best_match, 'line_number')
                    else best_match.get('line_number', 0)
                )
                step.source_line_ref = f"{src_file}:{src_line}"
        
        return trace
    
    def _command_similarity(self, cmd1: str, cmd2: str) -> float:
        """
        Calculate similarity between two commands.
        
        Handles variable substitution by matching on tool and arguments.
        """
        # Normalize commands
        cmd1_parts = set(cmd1.lower().split())
        cmd2_parts = set(cmd2.lower().split())
        
        # Remove variable placeholders from cmd2
        cmd2_parts = {p for p in cmd2_parts if not p.startswith('$')}
        
        if not cmd1_parts or not cmd2_parts:
            return 0.0
        
        # Calculate Jaccard similarity
        intersection = cmd1_parts & cmd2_parts
        union = cmd1_parts | cmd2_parts
        
        return len(intersection) / len(union) if union else 0.0
    
    def _finalize_trace_step(self, step: TraceStep):
        """Finalize a trace step by determining its status (Req 19.8)."""
        # Check exit code
        if step.exit_code is not None:
            step.status = "success" if step.exit_code == 0 else "failed"
        else:
            # Check for exit code in output
            for line in step.output_lines:
                for pattern in self.exit_code_patterns:
                    match = pattern.search(line)
                    if match:
                        try:
                            step.exit_code = int(match.group(1))
                            step.status = "success" if step.exit_code == 0 else "failed"
                            return
                        except (ValueError, IndexError):
                            pass
            
            # Check for failure indicators in output (Req 19.8)
            if self._detect_output_failure(step.output_lines):
                step.status = "failed"
            else:
                step.status = "unknown"
    
    def _find_exit_code(self, lines: List[str], tool_line_idx: int) -> Optional[int]:
        """Find exit code in lines following a tool invocation."""
        # Look in the next 10 lines for exit code
        for i in range(tool_line_idx + 1, min(tool_line_idx + 11, len(lines))):
            line = lines[i]
            for pattern in self.exit_code_patterns:
                match = pattern.search(line)
                if match:
                    try:
                        return int(match.group(1))
                    except (ValueError, IndexError):
                        pass
        return None
    
    def _associate_errors_with_tools(
        self,
        errors: List[ErrorMatch],
        tool_invocations: List[ToolInvocation]
    ) -> None:
        """Associate errors with preceding tool invocations (Requirement 17.4).
        
        If an error occurs within TOOL_ERROR_PROXIMITY lines after a tool invocation,
        associate that error with the tool.
        """
        if not tool_invocations or not errors:
            return
        
        for error in errors:
            # Find the most recent tool invocation before this error
            # that is within TOOL_ERROR_PROXIMITY lines
            for tool in reversed(tool_invocations):
                if tool.line_number < error.line_number:
                    distance = error.line_number - tool.line_number
                    if distance <= self.TOOL_ERROR_PROXIMITY:
                        error.related_tool = tool
                    break  # Stop at the most recent tool before the error
    
    def _associate_exit_code_with_failing_tool(
        self,
        tool_invocations: List[ToolInvocation],
        errors: List[ErrorMatch],
        lines: List[str],
    ) -> None:
        """
        Associate final exit code with the failing tool.
        
        When Jenkins reports "script returned exit code N", associate that
        exit code with the tool that has error output.
        """
        if not tool_invocations:
            return
        
        # Find exit code from errors or final lines
        exit_code = None
        for error in errors:
            match = re.search(r'(?:exit code|exit status|exited with)\s*[:\s]*(\d+)', 
                            error.line, re.IGNORECASE)
            if match:
                try:
                    exit_code = int(match.group(1))
                    break
                except (ValueError, IndexError):
                    pass
        
        # If no exit code found in errors, check last lines
        if exit_code is None:
            for line in reversed(lines[-20:]):
                match = re.search(r'(?:exit code|exit status|exited with|returned)\s*[:\s]*(\d+)', 
                                line, re.IGNORECASE)
                if match:
                    try:
                        exit_code = int(match.group(1))
                        break
                    except (ValueError, IndexError):
                        pass
        
        if exit_code is None or exit_code == 0:
            return
        
        # Find the tool with error indicators in its output
        # Start from the last tool and work backwards
        error_indicators = [
            'error:', 'Error:', 'ERROR:', 'FATAL:', 'fatal:',
            'FAILED', 'failed', 'cannot', 'unable to', 'not found',
            'denied', 'invalid', 'Exception', 'exception',
        ]
        
        for tool in reversed(tool_invocations):
            if tool.exit_code is not None:
                continue  # Already has exit code
            
            # Check if tool output contains error indicators
            has_error = False
            for output_line in tool.output_lines:
                for indicator in error_indicators:
                    if indicator in output_line:
                        has_error = True
                        break
                if has_error:
                    break
            
            if has_error:
                tool.exit_code = exit_code
                break  # Only associate with one tool
    
    def _find_failed_method(self, lines: List[str]) -> Tuple[Optional[str], List[str], List[str]]:
        """Find the shared library method that was running when failure occurred.
        
        Implements Requirement 1: Robust Method Tag Tracking
        
        Tracks method start/finish tags:
        - Primary (if prefix configured): {prefix}: method_name (Req 1.1)
        - Secondary (fallback): hh:mm:ss  method_name: method_name (Req 1.3)
        - Finish: method_name :time-elapsed-seconds:NN (Req 1.4)
        
        Returns:
            Tuple of (failed_method, method_call_sequence, active_methods)
            - failed_method: Last method that started but didn't finish (Req 1.6, 1.7)
            - method_call_sequence: All method start events in order (Req 1.11)
            - active_methods: Methods that started but didn't finish
        """
        method_call_sequence = []  # All methods detected (Req 1.11)
        started_methods = []  # Stack of (method_name, line_index)
        finished_methods = set()  # Set of normalized method names
        
        # Pattern for method finish: method_name :time-elapsed-seconds:NN (Req 1.4)
        finish_pattern = re.compile(r'^(.+?)\s+:time-elapsed-seconds:\d+')
        
        # Primary pattern: {prefix}: method_name (Req 1.1)
        # Prefix may appear anywhere on the line, method name may contain :, (), whitespace
        execution_pattern = None
        if self.method_execution_prefix:
            escaped_prefix = re.escape(self.method_execution_prefix)
            execution_pattern = re.compile(rf'{escaped_prefix}:\s*(.+)$', re.IGNORECASE)
        
        # Secondary pattern (fallback when no prefix): timestamp + method: method (Req 1.3)
        secondary_pattern = re.compile(r'^\d{2}:\d{2}:\d{2}\s+(\S[^:]*?):\s*\1\s*$')
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Check for method start - primary pattern first (Req 1.1)
            if execution_pattern:
                exec_match = execution_pattern.search(line_stripped)
                if exec_match:
                    # Preserve full method name including :, (), whitespace (Req 1.2)
                    method_name = exec_match.group(1).strip()
                    method_call_sequence.append(method_name)
                    started_methods.append((method_name, i))
                    continue
            
            # Check secondary pattern only if no prefix configured (Req 1.3)
            if not self.method_execution_prefix:
                start_match = secondary_pattern.match(line_stripped)
                if start_match:
                    method_name = start_match.group(1).strip()
                    method_call_sequence.append(method_name)
                    started_methods.append((method_name, i))
                    continue
            
            # Check for method finish (Req 1.4)
            finish_match = finish_pattern.match(line_stripped)
            if finish_match:
                method_name = finish_match.group(1).strip()
                # Normalize for matching (Req 1.9)
                normalized = self._normalize_method_name(method_name)
                finished_methods.add(normalized)
        
        # Find active methods (started but not finished)
        active_methods = []
        for method_name, line_idx in started_methods:
            normalized = self._normalize_method_name(method_name)
            if normalized not in finished_methods:
                active_methods.append(method_name)
        
        # Find failed_method: last method that started but didn't finish (Req 1.6, 1.7)
        failed_method = None
        for method_name, line_idx in reversed(started_methods):
            normalized = self._normalize_method_name(method_name)
            if normalized not in finished_methods:
                failed_method = method_name
                break
        
        # Fallback: if all methods finished, return last one (Req 1.8)
        if failed_method is None and started_methods:
            failed_method = started_methods[-1][0]
        
        return failed_method, method_call_sequence, active_methods
    
    def _normalize_method_name(self, name: str) -> str:
        """Normalize method name for comparison (Req 1.9).
        
        - Lowercases
        - Collapses all whitespace sequences to single space
        - Strips () suffix
        """
        # Lowercase
        normalized = name.lower()
        # Collapse whitespace sequences to single space
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        # Strip () suffix if present
        if normalized.endswith('()'):
            normalized = normalized[:-2]
        return normalized
    
    def get_method_file_name(self, method_name: str) -> str:
        """Extract the file name to search for from a method name.
        
        Handles patterns like:
        - method() -> method
        - prefix:method:submethod -> method (skips known prefix)
        - gitHub:repoClone -> gitHub
        - Class.method -> Class
        
        Returns the actual file name (without .groovy extension) to search in vars/
        """
        # Strip () suffix
        name = method_name.strip()
        if name.endswith('()'):
            name = name[:-2]
        
        # Handle prefix:method:submethod pattern
        # e.g., "pipeline:gitHub:repoClone" or "gitHub:repoClone"
        parts = name.split(':')
        if len(parts) >= 2:
            # If first part matches the configured prefix, skip it
            if self.method_execution_prefix and parts[0].lower() == self.method_execution_prefix.lower():
                # "pipeline:gitHub:repoClone" -> return "gitHub"
                return parts[1] if len(parts) > 1 else parts[0]
            else:
                # "gitHub:repoClone" -> return "gitHub"
                return parts[0]
        
        # Handle Class.method pattern
        if '.' in name:
            parts = name.split('.')
            return parts[0]
        
        return name
    
    def _find_last_stage(self, lines: List[str]) -> Tuple[Optional[str], int]:
        """Find the last pipeline stage in the log.
        
        Jenkins stage patterns:
        - [Pipeline] stage
        - [Pipeline] { (Stage Name)
        - [Pipeline] { (stage_name)
        
        Returns: (stage_name, line_index, stage_sequence) or (None, -1, []) if not found
        """
        stage_sequence = []  # All stages in order (Req 13.4)
        last_stage_name = None
        last_stage_line = -1
        
        # Pattern for [Pipeline] stage marker (first line of two-line pattern)
        stage_marker_pattern = re.compile(r'\[Pipeline\]\s+stage')
        
        # Pattern for [Pipeline] { (stage_name) - match LAST ) on line (Req 13.3)
        # This handles stage names containing (, ), {, } characters
        stage_name_pattern = re.compile(r'\[Pipeline\]\s*\{\s*\((.+)\)\s*$')
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Check for [Pipeline] stage marker (Req 13.1)
            if stage_marker_pattern.search(line):
                # Look ahead up to 2 lines for stage name (Req 13.8)
                for lookahead in range(1, 3):
                    if i + lookahead < len(lines):
                        name_match = stage_name_pattern.search(lines[i + lookahead])
                        if name_match:
                            # Extract stage name, strip whitespace but preserve internal chars (Req 13.9)
                            stage_name = name_match.group(1).strip()
                            stage_sequence.append(stage_name)
                            last_stage_name = stage_name
                            last_stage_line = i
                            break
                i += 1
                continue
            
            # Also check single-line pattern (Req 13.2)
            name_match = stage_name_pattern.search(line)
            if name_match:
                stage_name = name_match.group(1).strip()
                # Avoid duplicates from two-line detection
                if not stage_sequence or stage_sequence[-1] != stage_name:
                    stage_sequence.append(stage_name)
                    last_stage_name = stage_name
                    last_stage_line = i
            
            i += 1
        
        return last_stage_name, last_stage_line, stage_sequence
    
    def _extract_errors_from_end(self, lines: List[str], line_offset: int = 0) -> List[ErrorMatch]:
        """Extract errors, prioritizing those at the END of the log section.
        
        This reverses the search order so errors near the end are found first
        and ranked higher.
        """
        errors = []
        seen_errors = set()
        
        # Search from the END backwards
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            
            # Skip if we should ignore this line
            if self._should_ignore(line):
                continue
            
            # Check against all patterns
            for category, patterns in self.DEFAULT_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, line):
                        # Deduplicate similar errors
                        error_key = (category, line.strip()[:100])
                        if error_key in seen_errors:
                            continue
                        seen_errors.add(error_key)
                        
                        # Get context
                        start = max(0, i - self.context_lines)
                        end = min(len(lines), i + self.context_lines + 1)
                        
                        actual_line_num = i + line_offset + 1
                        
                        error = ErrorMatch(
                            line_number=actual_line_num,
                            line=line,
                            pattern_matched=pattern,
                            category=category,
                            context_before=lines[start:i],
                            context_after=lines[i + 1:end],
                            severity=self._determine_severity(line),
                        )
                        errors.append(error)
                        break
            
            # Stop after finding enough errors (prioritize recent ones)
            if len(errors) >= 20:
                break
        
        # Reverse so the most recent error is first
        # (We found them in reverse order, so reverse again to get newest first)
        return errors  # Keep reverse order - newest errors first!
    
    def _extract_errors(self, lines: List[str]) -> List[ErrorMatch]:
        """Extract error lines with context."""
        errors = []
        seen_errors = set()  # Deduplication
        
        for i, line in enumerate(lines):
            # Skip if we should ignore this line
            if self._should_ignore(line):
                continue
            
            # Check against all patterns
            for category, patterns in self.DEFAULT_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, line):
                        # Deduplicate similar errors
                        error_key = (category, line.strip()[:100])
                        if error_key in seen_errors:
                            continue
                        seen_errors.add(error_key)
                        
                        # Get context
                        start = max(0, i - self.context_lines)
                        end = min(len(lines), i + self.context_lines + 1)
                        
                        error = ErrorMatch(
                            line_number=i + 1,
                            line=line,
                            pattern_matched=pattern,
                            category=category,
                            context_before=lines[start:i],
                            context_after=lines[i + 1:end],
                            severity=self._determine_severity(line),
                        )
                        errors.append(error)
                        break
            
            # Check custom patterns
            for category, patterns in self.custom_patterns.items():
                for pattern in patterns:
                    if pattern.search(line):
                        error_key = (category, line.strip()[:100])
                        if error_key not in seen_errors:
                            seen_errors.add(error_key)
                            start = max(0, i - self.context_lines)
                            end = min(len(lines), i + self.context_lines + 1)
                            
                            error = ErrorMatch(
                                line_number=i + 1,
                                line=line,
                                pattern_matched=pattern.pattern,
                                category=category,
                                context_before=lines[start:i],
                                context_after=lines[i + 1:end],
                                severity=self._determine_severity(line),
                            )
                            errors.append(error)
        
        return errors
    
    def _extract_stack_traces(self, log_content: str) -> List[StackTrace]:
        """Extract and parse stack traces from the log."""
        stack_traces = []
        
        for lang, pattern in self.STACK_TRACE_PATTERNS.items():
            for match in pattern.finditer(log_content):
                try:
                    frames = self._parse_frames(match.group("frames"), lang)
                    
                    exception_type = match.group("exception") if "exception" in match.groupdict() else "Unknown"
                    message = match.group("message") if "message" in match.groupdict() else ""
                    
                    stack_trace = StackTrace(
                        exception_type=exception_type,
                        message=message.strip(),
                        frames=frames,
                        raw_text=match.group(0),
                    )
                    stack_traces.append(stack_trace)
                except Exception:
                    continue
        
        return stack_traces
    
    def _parse_frames(self, frames_text: str, language: str) -> List[Dict[str, str]]:
        """Parse stack trace frames based on language."""
        frames = []
        
        if language == "java":
            frame_pattern = re.compile(r"\s+at\s+(?P<method>[\w.$<>]+)\((?P<location>[^)]+)\)")
            for match in frame_pattern.finditer(frames_text):
                frames.append({
                    "method": match.group("method"),
                    "location": match.group("location"),
                })
        
        elif language == "python":
            frame_pattern = re.compile(
                r'\s+File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<method>\w+)'
            )
            for match in frame_pattern.finditer(frames_text):
                frames.append({
                    "file": match.group("file"),
                    "line": match.group("line"),
                    "method": match.group("method"),
                })
        
        elif language == "javascript":
            frame_pattern = re.compile(r"\s+at\s+(?:(?P<method>[\w.]+)\s+)?\(?(?P<location>[^)\s]+)\)?")
            for match in frame_pattern.finditer(frames_text):
                frames.append({
                    "method": match.group("method") or "anonymous",
                    "location": match.group("location"),
                })
        
        return frames
    
    def _detect_failed_stage(self, log_content: str) -> Optional[str]:
        """Detect which pipeline stage failed."""
        
        # Look for stage markers near failures
        for pattern in self.STAGE_PATTERNS:
            matches = list(re.finditer(pattern, log_content))
            if matches:
                # Return the last matched stage (most likely the failed one)
                return matches[-1].group("stage")
        
        # Try to find stage from Pipeline syntax
        pipeline_stages = re.findall(r"\[Pipeline\]\s*{\s*\(([^)]+)\)", log_content)
        if pipeline_stages:
            # Find stages that appear after error markers
            error_pos = log_content.find("ERROR")
            if error_pos == -1:
                error_pos = log_content.find("FAILURE")
            
            if error_pos > 0:
                # Find the most recent stage before the error
                last_stage = None
                for match in re.finditer(r"\[Pipeline\]\s*{\s*\(([^)]+)\)", log_content[:error_pos]):
                    last_stage = match.group(1)
                return last_stage
        
        return None
    
    def _extract_timestamps(self, lines: List[str]) -> List[Tuple[int, str]]:
        """Extract timestamp information from log lines."""
        timestamps = []
        timestamp_patterns = [
            r"^\[(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})",
            r"^(\d{2}:\d{2}:\d{2})",
            r"^\[(\d+:\d{2}:\d{2})\]",
        ]
        
        for i, line in enumerate(lines):
            for pattern in timestamp_patterns:
                match = re.match(pattern, line)
                if match:
                    timestamps.append((i, match.group(1)))
                    break
        
        return timestamps
    
    def _determine_primary_category(self, errors: List[ErrorMatch]) -> FailureCategory:
        """Determine the primary failure category from errors."""
        if not errors:
            return FailureCategory.UNKNOWN
        
        # Count categories
        category_counts: Dict[FailureCategory, int] = {}
        for error in errors:
            category_counts[error.category] = category_counts.get(error.category, 0) + 1
        
        # Priority order for tie-breaking
        priority = [
            FailureCategory.INFRASTRUCTURE,
            # Groovy/Pipeline errors are high priority as they block everything
            FailureCategory.GROOVY_LIBRARY,
            FailureCategory.GROOVY_CPS,
            FailureCategory.GROOVY_SANDBOX,
            FailureCategory.GROOVY_SERIALIZATION,
            FailureCategory.CREDENTIAL_ERROR,
            FailureCategory.AGENT_ERROR,
            FailureCategory.PLUGIN_ERROR,
            FailureCategory.COMPILATION_ERROR,
            FailureCategory.TEST_FAILURE,
            FailureCategory.DEPENDENCY,
            FailureCategory.CONFIGURATION,
            FailureCategory.NETWORK,
            FailureCategory.PERMISSION,
            FailureCategory.TIMEOUT,
            FailureCategory.RESOURCE,
            # Tool errors - common in CI/CD pipelines
            FailureCategory.TOOL_ERROR,
        ]
        
        # Find most common category, using priority for ties
        max_count = max(category_counts.values())
        for cat in priority:
            if category_counts.get(cat, 0) == max_count:
                return cat
        
        return FailureCategory.UNKNOWN
    
    def _determine_severity(self, line: str) -> str:
        """Determine the severity of an error line."""
        line_lower = line.lower()
        
        if any(w in line_lower for w in ["fatal", "critical", "panic"]):
            return "CRITICAL"
        elif any(w in line_lower for w in ["error", "exception", "failed"]):
            return "ERROR"
        elif any(w in line_lower for w in ["warn", "warning"]):
            return "WARNING"
        
        return "ERROR"
    
    def _should_ignore(self, line: str) -> bool:
        """Check if a line should be ignored."""
        ignore_patterns = [
            r"^\s*$",  # Empty lines
            r"^Downloading:",
            r"^Downloaded:",
            r"^Progress:",
            r"^\[INFO\]\s*Download",
            r"^\+\+\+",  # Git diff markers
            r"^---",
        ]
        
        for pattern in ignore_patterns:
            if re.match(pattern, line):
                return True
        
        # Check custom ignore patterns
        for pattern in self.config.get("ignore_patterns", []):
            if re.search(pattern, line):
                return True
        
        return False
    
    def _generate_summary(self, result: ParsedLog) -> str:
        """Generate a human-readable summary of the parsed log."""
        parts = []
        
        parts.append(f"Analyzed {result.total_lines} lines")
        parts.append(f"Found {len(result.errors)} errors")
        
        if result.stack_traces:
            parts.append(f"Detected {len(result.stack_traces)} stack traces")
        
        if result.failed_stage:
            parts.append(f"Failed in stage: {result.failed_stage}")
        
        if result.failed_method:
            parts.append(f"Failed in method: {result.failed_method}")
        
        parts.append(f"Primary category: {result.primary_category.value}")
        
        return ". ".join(parts) + "."
    
    def extract_command_context(self, log: str, max_sections: int = 10) -> List[Dict[str, Any]]:
        """
        Extract command executions and their outputs from the log.
        This helps identify cloud/API issues that precede the final error.
        
        Returns list of command contexts with:
        - command: The command that was run
        - output: The output (success or error)
        - line_number: Where in the log
        - is_error: Whether this appears to be an error
        """
        lines = log.split('\n')
        contexts = []
        
        # Patterns for command starts
        command_patterns = [
            # Cloud CLIs
            r'^\+?\s*(aws\s+\S+)',
            r'^\+?\s*(az\s+\S+)',
            r'^\+?\s*(gcloud\s+\S+)',
            r'^\+?\s*(kubectl\s+\S+)',
            r'^\+?\s*(helm\s+\S+)',
            r'^\+?\s*(terraform\s+\S+)',
            r'^\+?\s*(docker\s+\S+)',
            # Build tools
            r'^\+?\s*(npm\s+\S+)',
            r'^\+?\s*(yarn\s+\S+)',
            r'^\+?\s*(mvn\s+\S+)',
            r'^\+?\s*(gradle\s+\S+)',
            r'^\+?\s*(pip\s+\S+)',
            # Generic shell
            r'^\+\s+(.+)',  # Lines starting with + (shell trace)
            r'^\[INFO\]\s+Executing:\s+(.+)',
            r'^Running:\s+(.+)',
            r'^Executing:\s+(.+)',
        ]
        
        # Error indicators in output
        error_indicators = [
            r'(?i)error[:\s]',
            r'(?i)failed',
            r'(?i)exception',
            r'(?i)denied',
            r'(?i)forbidden',
            r'(?i)not found',
            r'(?i)unauthorized',
            r'(?i)invalid',
            r'(?i)missing',
            r'(?i)unable to',
            r'(?i)cannot',
            r'(?i)could not',
            r'\b4\d{2}\b',  # HTTP 4xx
            r'\b5\d{2}\b',  # HTTP 5xx
        ]
        
        i = 0
        while i < len(lines) and len(contexts) < max_sections:
            line = lines[i]
            
            # Check if this line is a command
            for pattern in command_patterns:
                match = re.search(pattern, line)
                if match:
                    command = match.group(1)
                    
                    # Capture output (next lines until next command or empty block)
                    output_lines = []
                    j = i + 1
                    while j < len(lines) and j < i + 30:  # Max 30 lines of output
                        next_line = lines[j]
                        # Stop at next command or stage marker
                        if any(re.search(p, next_line) for p in command_patterns[:12]):
                            break
                        if re.match(r'^\[Pipeline\]', next_line):
                            break
                        if next_line.strip():
                            output_lines.append(next_line)
                        elif len(output_lines) > 0:  # Empty line after some output
                            break
                        j += 1
                    
                    output = '\n'.join(output_lines[:20])  # Limit output length
                    
                    # Check if output contains errors
                    is_error = any(re.search(p, output) for p in error_indicators)
                    
                    if output.strip():  # Only add if there's output
                        contexts.append({
                            'command': command[:200],
                            'output': output[:1000],
                            'line_number': i + 1,
                            'is_error': is_error,
                        })
                    
                    i = j - 1  # Skip the lines we've processed
                    break
            i += 1
        
        return contexts
    
    def extract_api_responses(self, log: str, max_responses: int = 5) -> List[Dict[str, Any]]:
        """
        Extract API/HTTP responses from the log.
        Looks for JSON responses, HTTP status codes, and API error messages.
        """
        responses = []
        lines = log.split('\n')
        
        # Patterns for API responses
        response_patterns = [
            (r'HTTP/[\d.]+ (\d{3})', 'http_status'),
            (r'"status":\s*(\d{3})', 'json_status'),
            (r'"error":\s*"([^"]+)"', 'json_error'),
            (r'"message":\s*"([^"]+)"', 'json_message'),
            (r'"code":\s*"?([^",}\s]+)', 'error_code'),
            (r'Response:\s*(.+)', 'response'),
            (r'API Error:\s*(.+)', 'api_error'),
        ]
        
        for i, line in enumerate(lines):
            if len(responses) >= max_responses:
                break
                
            for pattern, resp_type in response_patterns:
                match = re.search(pattern, line)
                if match:
                    # Get context around this response
                    context_start = max(0, i - 3)
                    context_end = min(len(lines), i + 3)
                    context = '\n'.join(lines[context_start:context_end])
                    
                    responses.append({
                        'type': resp_type,
                        'value': match.group(1),
                        'line_number': i + 1,
                        'context': context[:500],
                    })
                    break
        
        return responses
    
    def get_enhanced_error_context(
        self, 
        log: str, 
        result: ParsedLog,
        context_lines: int = 10
    ) -> str:
        """
        Build enhanced context for AI analysis including:
        - Commands that failed
        - API responses
        - Extended context around errors
        """
        sections = []
        
        # 1. Failed stage context
        if result.failed_stage:
            sections.append(f"=== FAILED STAGE: {result.failed_stage} ===")
            # Try to find the stage in the log and get more context
            stage_pattern = rf'\[Pipeline\]\s*{{\s*\(\s*{re.escape(result.failed_stage)}\s*\)'
            match = re.search(stage_pattern, log)
            if match:
                start = match.start()
                # Get 2000 chars from stage start
                sections.append(log[start:start+2000])
        
        # 2. Command executions with errors
        cmd_contexts = self.extract_command_context(log)
        error_commands = [c for c in cmd_contexts if c['is_error']]
        if error_commands:
            sections.append("\n=== COMMAND ERRORS (check these for root cause) ===")
            for cmd in error_commands[-5:]:  # Last 5 error commands
                sections.append(f"\n[Line {cmd['line_number']}] $ {cmd['command']}")
                sections.append(cmd['output'])
        
        # 3. API/HTTP responses
        api_responses = self.extract_api_responses(log)
        error_responses = [r for r in api_responses if r['type'] in ('json_error', 'api_error') or 
                          (r['type'] in ('http_status', 'json_status') and int(r['value']) >= 400)]
        if error_responses:
            sections.append("\n=== API/HTTP ERRORS ===")
            for resp in error_responses[-3:]:
                sections.append(f"\n[Line {resp['line_number']}] {resp['type']}: {resp['value']}")
                sections.append(resp['context'])
        
        # 4. Extended error context (more lines before each error)
        if result.errors:
            sections.append("\n=== ERRORS WITH EXTENDED CONTEXT ===")
            for error in result.errors[:5]:
                sections.append(f"\n>>> ERROR at line {error.line_number}:")
                # Get more context from the log
                lines = log.split('\n')
                start = max(0, error.line_number - context_lines - 1)
                end = min(len(lines), error.line_number + 3)
                context = '\n'.join(lines[start:end])
                sections.append(context)
        
        return '\n'.join(sections)
    
    def get_error_snippet(
        self, 
        result: ParsedLog, 
        max_errors: int = 5,
        include_context: bool = True
    ) -> str:
        """Generate a concise error snippet for AI analysis."""
        snippets = []
        
        for error in result.errors[:max_errors]:
            snippet_parts = []
            
            if include_context and error.context_before:
                context = "\n".join(error.context_before[-3:])
                snippet_parts.append(f"Context:\n{context}")
            
            snippet_parts.append(f">>> Error (line {error.line_number}, {error.category.value}):")
            snippet_parts.append(error.line)
            
            if include_context and error.context_after:
                context = "\n".join(error.context_after[:3])
                snippet_parts.append(f"After:\n{context}")
            
            snippets.append("\n".join(snippet_parts))
        
        # Add stack traces
        for trace in result.stack_traces[:3]:
            trace_snippet = f"\n>>> Stack Trace ({trace.exception_type}):\n"
            trace_snippet += f"Message: {trace.message}\n"
            for frame in trace.frames[:5]:
                trace_snippet += f"  - {frame}\n"
            snippets.append(trace_snippet)
        
        return "\n\n---\n\n".join(snippets)
