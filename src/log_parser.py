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
    UNKNOWN = "unknown"


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
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_lines = self.config.get("error_context_lines", 10)
        self.max_log_size = self.config.get("max_log_size", 10 * 1024 * 1024)
        
        # Configurable prefix for method execution tracking
        # Pattern: "{prefix}: method_name"
        self.method_execution_prefix = self.config.get("method_execution_prefix", "")
        
        # Compile custom patterns from config
        self.custom_patterns = {}
        for category_name, category_config in self.config.get("categories", {}).items():
            try:
                category = FailureCategory(category_name)
                patterns = category_config.get("patterns", [])
                self.custom_patterns[category] = [re.compile(p) for p in patterns]
            except ValueError:
                pass
    
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
        
        Lowercases and collapses all whitespace sequences to single space.
        """
        # Lowercase
        normalized = name.lower()
        # Collapse whitespace sequences to single space
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
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
