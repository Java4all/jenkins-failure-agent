"""
Deep Root Cause Finder

Advanced log analysis that does deep investigation:
1. Find failed stage + map to source code
2. Parse error details (exception, message, stack trace, identifiers)
3. Trace dependencies through the log (where values came from)
4. Classify error type with evidence

This creates a complete investigation context for AI analysis.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any, Set
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """Error classification with specific sub-types."""
    CREDENTIAL = "credential"
    CREDENTIAL_NOT_FOUND = "credential_not_found"
    CREDENTIAL_EXPIRED = "credential_expired"
    CREDENTIAL_INVALID = "credential_invalid"
    
    NETWORK = "network"
    NETWORK_TIMEOUT = "network_timeout"
    NETWORK_DNS = "network_dns"
    NETWORK_CONNECTION_REFUSED = "network_connection_refused"
    
    PERMISSION = "permission"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_UNAUTHORIZED = "permission_unauthorized"
    
    NOT_FOUND = "not_found"
    FILE_NOT_FOUND = "file_not_found"
    RESOURCE_NOT_FOUND = "resource_not_found"
    METHOD_NOT_FOUND = "method_not_found"
    
    BUILD_FAILURE = "build_failure"
    COMPILATION_ERROR = "compilation_error"
    DEPENDENCY_ERROR = "dependency_error"
    
    TEST_FAILURE = "test_failure"
    
    CONFIGURATION = "configuration"
    ENV_VAR_MISSING = "env_var_missing"
    CONFIG_INVALID = "config_invalid"
    
    INFRASTRUCTURE = "infrastructure"
    DISK_FULL = "disk_full"
    MEMORY_ERROR = "memory_error"
    
    GROOVY_ERROR = "groovy_error"
    CPS_ERROR = "cps_error"
    SERIALIZATION_ERROR = "serialization_error"
    
    UNKNOWN = "unknown"


@dataclass
class StackFrame:
    """Single frame from a stack trace."""
    class_name: str = ""
    method_name: str = ""
    file_name: str = ""
    line_number: int = -1
    is_library_code: bool = False  # True if from shared library
    raw_line: str = ""


@dataclass
class ErrorDetails:
    """Parsed error information."""
    exception_type: str = ""           # e.g., "MissingMethodException"
    exception_message: str = ""        # Full error message
    error_line: str = ""               # The line where error occurred
    error_line_number: int = -1
    
    # Extracted identifiers from error
    identifiers: List[str] = field(default_factory=list)      # ABC, my-service, etc.
    paths: List[str] = field(default_factory=list)            # /path/to/file
    urls: List[str] = field(default_factory=list)             # http://...
    variables: List[str] = field(default_factory=list)        # Variable names
    
    # Stack trace (if present)
    stack_trace: List[StackFrame] = field(default_factory=list)
    
    # Source code reference
    source_file: Optional[str] = None   # vars/myMethod.groovy
    source_line: Optional[int] = None   # Line number in source


@dataclass
class DependencyTrace:
    """Traces where a value came from in the log."""
    identifier: str                     # The identifier we're tracing
    definition_line: Optional[str] = None      # Where it was defined
    definition_line_number: int = -1
    usage_lines: List[Tuple[int, str]] = field(default_factory=list)  # Where it was used
    flow: List[str] = field(default_factory=list)  # Data flow description


@dataclass
class StageInfo:
    """Information about a pipeline stage."""
    name: str
    start_line: int = -1
    end_line: int = -1
    status: str = "unknown"  # success, failed, skipped
    
    # Methods/functions called in this stage
    methods_called: List[str] = field(default_factory=list)
    failed_method: Optional[str] = None
    
    # Source mapping
    jenkinsfile_line: Optional[int] = None
    library_files: List[str] = field(default_factory=list)


@dataclass 
class DeepInvestigation:
    """Complete investigation result."""
    # Stage info
    failed_stage: Optional[StageInfo] = None
    all_stages: List[StageInfo] = field(default_factory=list)
    
    # Error details
    error: Optional[ErrorDetails] = None
    error_type: ErrorType = ErrorType.UNKNOWN
    
    # Dependency traces
    traces: List[DependencyTrace] = field(default_factory=list)
    
    # Context
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)
    
    # Commands that were executed
    commands_executed: List[Tuple[int, str]] = field(default_factory=list)
    
    # Evidence for classification
    classification_evidence: List[str] = field(default_factory=list)
    
    def get_investigation_report(self) -> str:
        """Generate detailed investigation report for AI."""
        parts = []
        
        # Header
        parts.append("=" * 60)
        parts.append("DEEP INVESTIGATION REPORT")
        parts.append("=" * 60)
        
        # Failed Stage
        if self.failed_stage:
            parts.append(f"\n## FAILED STAGE: {self.failed_stage.name}")
            if self.failed_stage.failed_method:
                parts.append(f"   Failed Method: {self.failed_stage.failed_method}")
            if self.failed_stage.library_files:
                parts.append(f"   Library Files: {', '.join(self.failed_stage.library_files)}")
            if self.failed_stage.methods_called:
                parts.append(f"   Methods Called: {', '.join(self.failed_stage.methods_called[-5:])}")
        
        # Error Details
        if self.error:
            parts.append(f"\n## ERROR DETAILS")
            parts.append(f"   Type: {self.error_type.value}")
            if self.error.exception_type:
                parts.append(f"   Exception: {self.error.exception_type}")
            parts.append(f"   Message: {self.error.exception_message or self.error.error_line}")
            
            if self.error.identifiers:
                parts.append(f"   Key Identifiers: {', '.join(self.error.identifiers)}")
            if self.error.paths:
                parts.append(f"   Paths: {', '.join(self.error.paths)}")
            if self.error.variables:
                parts.append(f"   Variables: {', '.join(self.error.variables)}")
            
            # Source reference
            if self.error.source_file:
                parts.append(f"   Source: {self.error.source_file}")
                if self.error.source_line:
                    parts.append(f"   Line: {self.error.source_line}")
            
            # Stack trace (first 5 frames)
            if self.error.stack_trace:
                parts.append(f"\n   Stack Trace (top 5):")
                for frame in self.error.stack_trace[:5]:
                    if frame.is_library_code:
                        parts.append(f"   >>> {frame.raw_line}  [LIBRARY CODE]")
                    else:
                        parts.append(f"       {frame.raw_line}")
        
        # Dependency Traces
        if self.traces:
            parts.append(f"\n## DEPENDENCY TRACES")
            for trace in self.traces[:5]:
                parts.append(f"\n   '{trace.identifier}':")
                if trace.definition_line:
                    parts.append(f"   Defined at [{trace.definition_line_number}]: {trace.definition_line[:80]}")
                if trace.usage_lines:
                    parts.append(f"   Used at:")
                    for line_num, line in trace.usage_lines[:3]:
                        parts.append(f"      [{line_num}]: {line[:80]}")
                if trace.flow:
                    parts.append(f"   Flow: {' -> '.join(trace.flow)}")
        
        # Commands Executed
        if self.commands_executed:
            parts.append(f"\n## COMMANDS EXECUTED (last 10)")
            for line_num, cmd in self.commands_executed[-10:]:
                parts.append(f"   [{line_num}] {cmd[:100]}")
        
        # Context
        if self.context_before:
            parts.append(f"\n## CONTEXT BEFORE ERROR (last 20 lines)")
            parts.append("-" * 50)
            for line in self.context_before[-20:]:
                parts.append(line)
        
        parts.append(f"\n## >>> ERROR <<<")
        parts.append("-" * 50)
        if self.error:
            parts.append(self.error.error_line)
        
        if self.context_after:
            parts.append(f"\n## CONTEXT AFTER ERROR (first 10 lines)")
            parts.append("-" * 50)
            for line in self.context_after[:10]:
                parts.append(line)
        
        # Classification Evidence
        if self.classification_evidence:
            parts.append(f"\n## CLASSIFICATION EVIDENCE")
            for evidence in self.classification_evidence:
                parts.append(f"   • {evidence}")
        
        return "\n".join(parts)


class DeepRCFinder:
    """
    Deep Root Cause Finder with full investigation capabilities.
    """
    
    # Stage patterns
    STAGE_START_PATTERN = re.compile(r'\[Pipeline\]\s*\{\s*\(([^)]+)\)')
    STAGE_END_PATTERN = re.compile(r'\[Pipeline\]\s*\}')
    
    # Method execution patterns (configurable prefix)
    METHOD_START_PATTERNS = [
        re.compile(r'(\d{2}:\d{2}:\d{2})\s+(\w+):\s*\2'),  # HH:MM:SS method: method
        re.compile(r'\[(\w+)\]\s*Starting'),               # [method] Starting
    ]
    METHOD_END_PATTERN = re.compile(r'(\w+)\s*:time-elapsed-seconds:(\d+)')
    
    # Error patterns with classification
    ERROR_PATTERNS = {
        # Credential errors
        (ErrorType.CREDENTIAL_NOT_FOUND, 100): [
            re.compile(r'could not find cred', re.I),
            re.compile(r'credential.*not found', re.I),
            re.compile(r'no.*credential.*found', re.I),
        ],
        (ErrorType.CREDENTIAL_EXPIRED, 95): [
            re.compile(r'credential.*expired', re.I),
            re.compile(r'token.*expired', re.I),
        ],
        (ErrorType.CREDENTIAL_INVALID, 90): [
            re.compile(r'invalid.*credential', re.I),
            re.compile(r'authentication failed', re.I),
            re.compile(r'access denied.*credential', re.I),
        ],
        
        # Network errors
        (ErrorType.NETWORK_TIMEOUT, 100): [
            re.compile(r'connection timed out', re.I),
            re.compile(r'read timed out', re.I),
            re.compile(r'timeout.*connect', re.I),
        ],
        (ErrorType.NETWORK_DNS, 95): [
            re.compile(r'unknown host', re.I),
            re.compile(r'could not resolve', re.I),
            re.compile(r'dns.*failed', re.I),
        ],
        (ErrorType.NETWORK_CONNECTION_REFUSED, 90): [
            re.compile(r'connection refused', re.I),
            re.compile(r'connect.*refused', re.I),
        ],
        
        # Permission errors
        (ErrorType.PERMISSION_DENIED, 100): [
            re.compile(r'permission denied', re.I),
            re.compile(r'access denied', re.I),
            re.compile(r'not authorized', re.I),
            re.compile(r'forbidden', re.I),
        ],
        
        # Not found errors
        (ErrorType.FILE_NOT_FOUND, 95): [
            re.compile(r'file not found', re.I),
            re.compile(r'no such file', re.I),
            re.compile(r'path.*not exist', re.I),
        ],
        (ErrorType.RESOURCE_NOT_FOUND, 90): [
            re.compile(r'resource.*not found', re.I),
            re.compile(r'404', re.I),
            re.compile(r'does not exist', re.I),
        ],
        (ErrorType.METHOD_NOT_FOUND, 95): [
            re.compile(r'MissingMethodException', re.I),
            re.compile(r'no signature of method', re.I),
            re.compile(r'method.*not found', re.I),
        ],
        
        # Groovy errors
        (ErrorType.CPS_ERROR, 100): [
            re.compile(r'CpsCallableInvocation', re.I),
            re.compile(r'NonCPS', re.I),
            re.compile(r'expected to call', re.I),
        ],
        (ErrorType.SERIALIZATION_ERROR, 95): [
            re.compile(r'NotSerializableException', re.I),
            re.compile(r'cannot serialize', re.I),
        ],
        (ErrorType.GROOVY_ERROR, 80): [
            re.compile(r'groovy\.lang\.\w+Exception', re.I),
            re.compile(r'MissingPropertyException', re.I),
        ],
        
        # Build errors
        (ErrorType.COMPILATION_ERROR, 90): [
            re.compile(r'compilation failed', re.I),
            re.compile(r'compile error', re.I),
            re.compile(r'syntax error', re.I),
        ],
        (ErrorType.DEPENDENCY_ERROR, 85): [
            re.compile(r'dependency.*not found', re.I),
            re.compile(r'could not resolve', re.I),
            re.compile(r'module not found', re.I),
        ],
        
        # Config errors
        (ErrorType.ENV_VAR_MISSING, 90): [
            re.compile(r'environment variable.*not set', re.I),
            re.compile(r'env.*is not defined', re.I),
            re.compile(r'\$\{?\w+\}?\s*is\s*(null|empty|undefined)', re.I),
        ],
        
        # Infrastructure errors
        (ErrorType.DISK_FULL, 100): [
            re.compile(r'no space left', re.I),
            re.compile(r'disk full', re.I),
        ],
        (ErrorType.MEMORY_ERROR, 95): [
            re.compile(r'OutOfMemoryError', re.I),
            re.compile(r'out of memory', re.I),
        ],
        
        # Test failures
        (ErrorType.TEST_FAILURE, 80): [
            re.compile(r'tests? failed', re.I),
            re.compile(r'test.*failure', re.I),
            re.compile(r'assertion.*failed', re.I),
        ],
    }
    
    # Command patterns (to extract executed commands)
    COMMAND_PATTERNS = [
        re.compile(r'^\+\s*(.+)$'),                        # + command (sh -x)
        re.compile(r'^\[.*?\]\s*\$\s*(.+)$'),             # [stage] $ command
        re.compile(r'^>\s*(.+)$'),                         # > command
        re.compile(r'Running:\s*(.+)$', re.I),             # Running: command
        re.compile(r'Executing:\s*(.+)$', re.I),           # Executing: command
    ]
    
    # Identifier extraction patterns
    IDENTIFIER_PATTERNS = [
        re.compile(r"'([A-Za-z][A-Za-z0-9_-]{2,})'"),     # 'identifier'
        re.compile(r'"([A-Za-z][A-Za-z0-9_-]{2,})"'),     # "identifier"
        re.compile(r'ID[:\s]+([A-Za-z][A-Za-z0-9_-]+)', re.I),  # ID: xxx
        re.compile(r'name[:\s]+([A-Za-z][A-Za-z0-9_-]+)', re.I), # name: xxx
        re.compile(r'--(\w+)[=\s]+([^\s]+)'),              # --param=value
    ]
    
    # Path patterns
    PATH_PATTERN = re.compile(r'(/[A-Za-z0-9._/-]+)')
    
    # URL patterns
    URL_PATTERN = re.compile(r'(https?://[^\s<>"]+)')
    
    # Variable patterns
    VAR_PATTERNS = [
        re.compile(r'\$\{?([A-Z][A-Z0-9_]+)\}?'),         # $VAR or ${VAR}
        re.compile(r'env\.([A-Z][A-Z0-9_]+)'),            # env.VAR
    ]
    
    # Stack trace patterns
    STACK_FRAME_PATTERN = re.compile(
        r'at\s+([\w.$]+)\.(\w+)\s*\(([^:]+):(\d+)\)'
    )
    GROOVY_STACK_PATTERN = re.compile(
        r'at\s+([\w.$]+)\.(\w+)\s*\(([^)]+)\)'
    )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.method_prefix = self.config.get('method_execution_prefix', '')
        
        # Library file patterns (to identify shared library code in stack)
        self.library_patterns = [
            re.compile(r'vars/\w+\.groovy'),
            re.compile(r'src/[\w/]+\.groovy'),
        ]
    
    def investigate(self, log: str) -> DeepInvestigation:
        """
        Perform deep investigation of the log.
        """
        lines = log.split('\n')
        investigation = DeepInvestigation()
        
        # Step 1: Parse all stages
        investigation.all_stages = self._parse_stages(lines)
        
        # Step 2: Find the failed stage (last stage with error)
        investigation.failed_stage = self._find_failed_stage(
            lines, investigation.all_stages
        )
        
        # Step 3: Find and parse error details
        investigation.error = self._find_error(lines)
        
        # Step 4: Classify error type with evidence
        investigation.error_type, investigation.classification_evidence = \
            self._classify_error(investigation.error, lines)
        
        # Step 5: Extract commands executed
        investigation.commands_executed = self._extract_commands(lines)
        
        # Step 6: Trace dependencies for each identifier
        if investigation.error and investigation.error.identifiers:
            investigation.traces = self._trace_dependencies(
                investigation.error.identifiers, lines
            )
        
        # Step 7: Extract context around error
        if investigation.error and investigation.error.error_line_number >= 0:
            error_idx = investigation.error.error_line_number
            investigation.context_before = lines[max(0, error_idx-30):error_idx]
            investigation.context_after = lines[error_idx+1:min(len(lines), error_idx+15)]
        
        # Step 8: Map error to source code
        if investigation.error:
            self._map_to_source(investigation.error, investigation.failed_stage)
        
        logger.info(f"Deep investigation: stage={investigation.failed_stage.name if investigation.failed_stage else None}, "
                   f"error_type={investigation.error_type.value}, "
                   f"identifiers={investigation.error.identifiers if investigation.error else []}")
        
        return investigation
    
    def _parse_stages(self, lines: List[str]) -> List[StageInfo]:
        """Parse all stages from the log."""
        stages = []
        current_stage = None
        method_stack = []
        
        for i, line in enumerate(lines):
            # Check for stage start
            match = self.STAGE_START_PATTERN.search(line)
            if match:
                if current_stage:
                    current_stage.end_line = i - 1
                    stages.append(current_stage)
                
                current_stage = StageInfo(
                    name=match.group(1),
                    start_line=i,
                )
                method_stack = []
                continue
            
            # Check for method start
            for pattern in self.METHOD_START_PATTERNS:
                match = pattern.search(line)
                if match:
                    method_name = match.group(2) if len(match.groups()) > 1 else match.group(1)
                    method_stack.append(method_name)
                    if current_stage:
                        current_stage.methods_called.append(method_name)
                    break
            
            # Check for method end
            match = self.METHOD_END_PATTERN.search(line)
            if match and method_stack:
                method_stack.pop()
            
            # Check if method execution prefix is in line
            if self.method_prefix and self.method_prefix in line:
                # Extract method name after prefix
                prefix_idx = line.find(self.method_prefix)
                after = line[prefix_idx + len(self.method_prefix):].strip()
                if after and after.split()[0].isidentifier():
                    method_name = after.split()[0].rstrip(':')
                    method_stack.append(method_name)
                    if current_stage:
                        current_stage.methods_called.append(method_name)
        
        # Close last stage
        if current_stage:
            current_stage.end_line = len(lines) - 1
            stages.append(current_stage)
        
        return stages
    
    def _find_failed_stage(
        self, 
        lines: List[str], 
        stages: List[StageInfo]
    ) -> Optional[StageInfo]:
        """Find the stage that failed."""
        if not stages:
            return None
        
        # Search from end for error indicators
        error_line_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].lower()
            if any(kw in line for kw in ['error', 'exception', 'failed', 'failure']):
                # Skip common false positives
                if 'error=' in line or 'onerror' in line:
                    continue
                error_line_idx = i
                break
        
        # Find which stage contains this error
        for stage in reversed(stages):
            if stage.start_line <= error_line_idx <= stage.end_line:
                stage.status = "failed"
                
                # Find which method failed (last method before error)
                if stage.methods_called:
                    stage.failed_method = stage.methods_called[-1]
                
                return stage
        
        # Default to last stage
        return stages[-1] if stages else None
    
    def _find_error(self, lines: List[str]) -> ErrorDetails:
        """Find and parse the error in the log."""
        error = ErrorDetails()
        
        # Search from end for error line
        error_scores = []
        
        for i in range(len(lines) - 1, max(0, len(lines) - 200), -1):
            line = lines[i]
            score = self._score_error_line(line)
            if score > 0:
                error_scores.append((i, line, score))
        
        # Sort by score (highest first)
        error_scores.sort(key=lambda x: x[2], reverse=True)
        
        if error_scores:
            error_idx, error_line, _ = error_scores[0]
            error.error_line = error_line.strip()
            error.error_line_number = error_idx
            
            # Parse exception type
            exc_match = re.search(r'(\w+Exception|\w+Error):', error_line)
            if exc_match:
                error.exception_type = exc_match.group(1)
            
            # Extract message (after exception type)
            if error.exception_type:
                msg_start = error_line.find(error.exception_type) + len(error.exception_type)
                error.exception_message = error_line[msg_start:].strip().lstrip(':').strip()
            else:
                error.exception_message = error_line
            
            # Extract identifiers
            error.identifiers = self._extract_identifiers(error_line)
            
            # Extract paths
            error.paths = self.PATH_PATTERN.findall(error_line)
            
            # Extract URLs
            error.urls = self.URL_PATTERN.findall(error_line)
            
            # Extract variables
            for pattern in self.VAR_PATTERNS:
                error.variables.extend(pattern.findall(error_line))
            
            # Parse stack trace (if present)
            error.stack_trace = self._parse_stack_trace(lines, error_idx)
        
        return error
    
    def _score_error_line(self, line: str) -> int:
        """Score how likely a line is the main error."""
        score = 0
        line_lower = line.lower()
        
        # High-value error indicators
        if 'exception' in line_lower:
            score += 50
        if 'error' in line_lower and 'error=' not in line_lower:
            score += 30
        if 'failed' in line_lower:
            score += 25
        if 'failure' in line_lower:
            score += 25
        
        # Specific patterns
        if re.search(r'^\s*(Caused by|Exception|Error):', line):
            score += 40
        if re.search(r'\w+Exception:', line):
            score += 45
        if re.search(r'\w+Error:', line):
            score += 40
        
        # Negative indicators (false positives)
        if line.strip().startswith('#'):
            score -= 50
        if 'WARN' in line and 'ERROR' not in line:
            score -= 20
        if len(line.strip()) < 10:
            score -= 30
        if 'at ' in line and '(' in line and ')' in line:
            # Stack trace line, not the error itself
            score -= 20
        
        return max(0, score)
    
    def _extract_identifiers(self, line: str) -> List[str]:
        """Extract potential identifiers from error line."""
        identifiers = set()
        
        for pattern in self.IDENTIFIER_PATTERNS:
            matches = pattern.findall(line)
            for match in matches:
                if isinstance(match, tuple):
                    identifiers.update(match)
                else:
                    identifiers.add(match)
        
        # Filter out common non-identifiers
        filtered = []
        for ident in identifiers:
            if len(ident) < 3:
                continue
            if ident.lower() in ('the', 'and', 'for', 'not', 'with', 'from', 'this', 'that'):
                continue
            if ident.isdigit():
                continue
            filtered.append(ident)
        
        return filtered
    
    def _parse_stack_trace(self, lines: List[str], error_idx: int) -> List[StackFrame]:
        """Parse stack trace following the error."""
        frames = []
        
        # Look for stack frames after error
        for i in range(error_idx + 1, min(len(lines), error_idx + 50)):
            line = lines[i].strip()
            
            # Check for standard Java/Groovy stack frame
            match = self.STACK_FRAME_PATTERN.search(line)
            if match:
                frame = StackFrame(
                    class_name=match.group(1),
                    method_name=match.group(2),
                    file_name=match.group(3),
                    line_number=int(match.group(4)),
                    raw_line=line,
                )
                
                # Check if it's library code
                for pattern in self.library_patterns:
                    if pattern.search(line):
                        frame.is_library_code = True
                        break
                
                frames.append(frame)
                continue
            
            # Check for Groovy stack frame
            match = self.GROOVY_STACK_PATTERN.search(line)
            if match:
                frame = StackFrame(
                    class_name=match.group(1),
                    method_name=match.group(2),
                    file_name=match.group(3),
                    raw_line=line,
                )
                for pattern in self.library_patterns:
                    if pattern.search(line):
                        frame.is_library_code = True
                        break
                frames.append(frame)
                continue
            
            # Stop if we hit a non-stack-trace line
            if line and not line.startswith('at ') and not line.startswith('...'):
                if 'Caused by' not in line:
                    break
        
        return frames
    
    def _classify_error(
        self, 
        error: ErrorDetails, 
        lines: List[str]
    ) -> Tuple[ErrorType, List[str]]:
        """Classify error type with evidence."""
        if not error or not error.error_line:
            return ErrorType.UNKNOWN, []
        
        error_line = error.error_line
        evidence = []
        
        # Score each error type
        scores: Dict[ErrorType, int] = {}
        
        for (error_type, base_score), patterns in self.ERROR_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(error_line):
                    current = scores.get(error_type, 0)
                    scores[error_type] = max(current, base_score)
                    evidence.append(f"Pattern '{pattern.pattern}' matched in error line")
                    break
        
        # Also check context
        context = lines[max(0, error.error_line_number-10):error.error_line_number+5]
        context_text = '\n'.join(context)
        
        for (error_type, base_score), patterns in self.ERROR_PATTERNS.items():
            if error_type in scores:
                continue
            for pattern in patterns:
                if pattern.search(context_text):
                    scores[error_type] = base_score - 20  # Lower score for context match
                    evidence.append(f"Pattern '{pattern.pattern}' found in context")
                    break
        
        # Pick highest scoring type
        if scores:
            best_type = max(scores.items(), key=lambda x: x[1])[0]
            return best_type, evidence
        
        return ErrorType.UNKNOWN, ["No error patterns matched"]
    
    def _extract_commands(self, lines: List[str]) -> List[Tuple[int, str]]:
        """Extract commands that were executed."""
        commands = []
        
        for i, line in enumerate(lines):
            for pattern in self.COMMAND_PATTERNS:
                match = pattern.search(line)
                if match:
                    cmd = match.group(1).strip()
                    if cmd and len(cmd) > 5:
                        commands.append((i, cmd))
                    break
        
        return commands
    
    def _trace_dependencies(
        self, 
        identifiers: List[str], 
        lines: List[str]
    ) -> List[DependencyTrace]:
        """Trace where each identifier came from."""
        traces = []
        
        for ident in identifiers[:5]:  # Limit to 5 identifiers
            trace = DependencyTrace(identifier=ident)
            
            # Find where it was defined
            define_patterns = [
                re.compile(rf'{re.escape(ident)}\s*='),
                re.compile(rf'--{re.escape(ident)}[=\s]'),
                re.compile(rf'export\s+{re.escape(ident)}'),
                re.compile(rf'{re.escape(ident)}:\s'),
            ]
            
            for i, line in enumerate(lines):
                for pattern in define_patterns:
                    if pattern.search(line):
                        if not trace.definition_line:
                            trace.definition_line = line.strip()
                            trace.definition_line_number = i
                        break
                
                # Find usages
                if ident in line and i != trace.definition_line_number:
                    trace.usage_lines.append((i, line.strip()))
            
            # Build flow description
            if trace.definition_line:
                trace.flow.append(f"Defined at line {trace.definition_line_number}")
            if trace.usage_lines:
                trace.flow.append(f"Used {len(trace.usage_lines)} times")
            
            traces.append(trace)
        
        return traces
    
    def _map_to_source(
        self, 
        error: ErrorDetails, 
        stage: Optional[StageInfo]
    ) -> None:
        """Map error to source code location."""
        # Try to find source file from stack trace
        for frame in error.stack_trace:
            if frame.is_library_code:
                error.source_file = frame.file_name
                error.source_line = frame.line_number
                return
        
        # Try to infer from failed method
        if stage and stage.failed_method:
            error.source_file = f"vars/{stage.failed_method}.groovy"
