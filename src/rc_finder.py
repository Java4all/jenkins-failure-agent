"""
Root Cause Finder Expert

Smart log analysis to extract the most relevant context for AI analysis.
This expert finds the error location and extracts focused context around it.

Strategy:
1. Find the LAST stage (where errors usually occur)
2. Find the ERROR line within that stage
3. Extract context: ~30 lines BEFORE (commands that caused it) + ~15 lines AFTER (error details)
4. Return focused, clean data for AI analysis

Works for ANY error type - no pattern matching needed.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum

from .failure_fingerprint import FailureFingerprint
from .command_association import pick_best_tool_invocation, tool_dict_from_any

# Import PipelineLineType for line classification (Req 20.6)
try:
    from .log_parser import PipelineLineType
except ImportError:
    PipelineLineType = None


class ErrorType(Enum):
    """High-level error type classification."""
    CREDENTIAL = "credential"
    NETWORK = "network"
    TIMEOUT = "timeout"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    BUILD_FAILURE = "build_failure"
    TEST_FAILURE = "test_failure"
    CONFIGURATION = "configuration"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


@dataclass
class RootCauseContext:
    """
    Focused context extracted for root cause analysis.
    Contains only the relevant portion of the log.
    """
    # Location info
    failed_stage: Optional[str] = None
    failed_method: Optional[str] = None
    error_line_number: int = -1
    
    # The actual error
    error_line: str = ""
    error_type: ErrorType = ErrorType.UNKNOWN
    
    # Focused context (what AI will analyze)
    context_before: List[str] = field(default_factory=list)  # ~30 lines before error
    context_after: List[str] = field(default_factory=list)   # ~15 lines after error
    
    # Requirement 20.6: Line type classifications for context lines
    # Maps line index to type label (e.g., "SHELL_CMD", "SHELL_OUT", "ECHO", "STEP")
    context_line_types: Dict[int, str] = field(default_factory=dict)
    
    # Extracted identifiers (IDs, names, paths mentioned in error)
    identifiers: List[str] = field(default_factory=list)
    
    # Related lines (lines that mention the identifiers)
    related_lines: List[Tuple[int, str]] = field(default_factory=list)
    
    # Requirement 17.5: Related tool invocation
    related_tool: Optional[Dict[str, Any]] = None
    
    # When LogParser primary error vs tail-focused finder disagree (early SCM/Git, etc.)
    reconciliation_note: str = ""
    
    # Structured line alignment (finder vs parser); exposed in API metadata
    fingerprint: Optional[FailureFingerprint] = None
    
    # Summary for AI
    def get_ai_prompt_context(self) -> str:
        """Generate focused context for AI analysis."""
        parts = []
        
        if self.failed_stage:
            parts.append(f"FAILED STAGE: {self.failed_stage}")
        if self.failed_method:
            parts.append(f"FAILED METHOD: {self.failed_method}")
        if self.reconciliation_note:
            parts.append("\n" + "=" * 50)
            parts.append("RECONCILIATION (LogParser vs error focus)")
            parts.append("=" * 50)
            parts.append(self.reconciliation_note)
        
        # Requirement 17.5, 17.6: Include tool context
        if self.related_tool:
            parts.append("\n" + "="*50)
            parts.append("TOOL CONTEXT:")
            parts.append("="*50)
            parts.append(f"TOOL: {self.related_tool.get('tool_name', 'unknown')}")
            parts.append(f"COMMAND: {self.related_tool.get('command_line', 'unknown')}")
            exit_code = self.related_tool.get('exit_code')
            parts.append(f"EXIT CODE: {exit_code if exit_code is not None else 'unknown'}")
            # Include tool output if available
            output_lines = self.related_tool.get('output_lines', [])
            if output_lines:
                parts.append("OUTPUT:")
                for line in output_lines[:10]:
                    parts.append(f"  {line}")
        
        parts.append(f"\nERROR TYPE: {self.error_type.value}")
        parts.append(f"ERROR: {self.error_line}")
        
        if self.identifiers:
            parts.append(f"\nKEY IDENTIFIERS: {', '.join(self.identifiers)}")
        
        # Context before (commands that led to error) - Req 20.6: with line type labels
        if self.context_before:
            parts.append("\n" + "="*50)
            parts.append("COMMANDS/OPERATIONS BEFORE ERROR:")
            parts.append("="*50)
            for i, line in enumerate(self.context_before):
                line_type = self.context_line_types.get(i, "")
                if line_type:
                    parts.append(f"[{line_type}] {line}")
                else:
                    parts.append(line)
        
        # The error itself
        parts.append("\n" + "="*50)
        parts.append(">>> ERROR <<<")
        parts.append("="*50)
        parts.append(self.error_line)
        
        # Context after (error details)
        if self.context_after:
            parts.append("\n" + "="*50)
            parts.append("ERROR DETAILS:")
            parts.append("="*50)
            for i, line in enumerate(self.context_after):
                # Offset index for after-context
                idx = len(self.context_before) + 1 + i
                line_type = self.context_line_types.get(idx, "")
                if line_type:
                    parts.append(f"[{line_type}] {line}")
                else:
                    parts.append(line)
        
        # Related lines (if identifiers found)
        if self.related_lines:
            parts.append("\n" + "="*50)
            parts.append("RELATED LINES (mention same identifiers):")
            parts.append("="*50)
            for line_num, line in self.related_lines[:10]:
                parts.append(f"[{line_num}] {line}")
        
        return "\n".join(parts)


class RootCauseFinder:
    """
    Expert system for finding root cause context in Jenkins logs.
    
    Usage:
        finder = RootCauseFinder()
        context = finder.find(log_content)
        ai_prompt = context.get_ai_prompt_context()
    """
    
    # Lines to extract before/after error
    CONTEXT_BEFORE = 30
    CONTEXT_AFTER = 15
    
    # Error patterns (ordered by priority)
    ERROR_PATTERNS = [
        # Explicit errors
        (r'^(?:ERROR|Error|error)[:\s]', 10),
        (r'\bFATAL[:\s]', 10),
        (r'\bFAILED[:\s]', 9),
        (r'\bException[:\s]', 8),
        (r'\bfailed\b', 7),
        # Build tool errors
        (r'BUILD FAILURE', 9),
        (r'npm ERR!', 9),
        (r'\[ERROR\]', 8),
        # Stack traces
        (r'^\s+at\s+[\w.$]+\(', 6),
        (r'Caused by:', 7),
        # Common error phrases
        (r'could not find', 7),
        (r'not found', 6),
        (r'permission denied', 8),
        (r'access denied', 8),
        (r'connection refused', 8),
        (r'timeout', 7),
        (r'timed out', 7),
    ]
    
    # Error type detection patterns
    ERROR_TYPE_PATTERNS = {
        ErrorType.CREDENTIAL: [
            r'credential', r'cred\s+entry', r'secret', r'password',
            r'api[_-]?key', r'token', r'auth', r'login failed',
        ],
        ErrorType.NETWORK: [
            r'connection refused', r'connection reset', r'network',
            r'unreachable', r'dns', r'resolve', r'socket',
        ],
        ErrorType.TIMEOUT: [
            r'timeout', r'timed out', r'deadline exceeded',
        ],
        ErrorType.PERMISSION: [
            r'permission denied', r'access denied', r'forbidden',
            r'unauthorized', r'not authorized', r'403',
        ],
        ErrorType.NOT_FOUND: [
            r'not found', r'no such', r'does not exist', r'missing',
            r'404', r'could not find',
        ],
        ErrorType.BUILD_FAILURE: [
            r'build failure', r'compilation error', r'compile error',
            r'syntax error', r'npm err', r'maven', r'gradle',
        ],
        ErrorType.TEST_FAILURE: [
            r'test failed', r'tests failed', r'assertion',
            r'expected.*but', r'junit', r'pytest',
        ],
        ErrorType.CONFIGURATION: [
            r'invalid config', r'configuration error', r'missing param',
            r'required parameter', r'invalid value',
        ],
        ErrorType.INFRASTRUCTURE: [
            r'out of memory', r'disk full', r'no space', r'oom',
            r'killed', r'resource', r'quota',
        ],
    }
    
    # Patterns for stage detection
    STAGE_PATTERN = re.compile(r'\[Pipeline\]\s*\{\s*\(([^)]+)\)')
    STAGE_END_PATTERNS = [
        re.compile(r'\[Pipeline\]\s*//\s*stage'),
        re.compile(r'\[Pipeline\]\s*\}'),
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.context_before = self.config.get('context_before', self.CONTEXT_BEFORE)
        self.context_after = self.config.get('context_after', self.CONTEXT_AFTER)
        self.method_prefix = self.config.get('method_execution_prefix', '')
    
    def find(
        self,
        log: str,
        tool_invocations: Optional[List[Any]] = None,
        parsed_log: Optional[Any] = None,
    ) -> RootCauseContext:
        """
        Find root cause context from log.
        
        Args:
            log: The log content to analyze
            tool_invocations: Optional list of ToolInvocation objects from LogParser
                              (Requirement 17.5)
            parsed_log: Optional ParsedLog — when set, reconciles tail-focused error with
                        LogParser's primary error and boosts early SCM/Git signals.
        
        Returns RootCauseContext with focused, relevant data for AI analysis.
        """
        lines = log.split('\n')
        context = RootCauseContext()
        
        # Step 1: Find last stage
        context.failed_stage, stage_start_idx = self._find_last_stage(lines)
        
        # Step 2: Find failed method (if tracking enabled)
        context.failed_method = self._find_failed_method(lines)
        
        # Step 3: Find the primary error line
        # Search from end, prioritizing lines in the last stage
        search_start = stage_start_idx if stage_start_idx >= 0 else max(0, len(lines) - 200)
        error_idx, error_line, error_score = self._find_error_line(lines, search_start)
        
        if error_idx >= 0:
            new_idx, new_line, note, fp = self._reconcile_primary_error_line(
                lines, error_idx, error_score, parsed_log
            )
            context.error_line_number = new_idx
            context.error_line = new_line
            context.reconciliation_note = note
            context.fingerprint = fp
        else:
            # Fallback: use last non-empty line as "error"
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip():
                    context.error_line_number = i
                    context.error_line = lines[i]
                    break
        
        # Step 4: Classify error type
        context.error_type = self._classify_error(context.error_line)
        
        # Step 5: Extract context around error
        context.context_before = self._extract_context_before(lines, context.error_line_number)
        context.context_after = self._extract_context_after(lines, context.error_line_number)
        
        # Step 5b (Req 20.6): Classify context lines
        context.context_line_types = self._classify_context_lines(
            context.context_before, context.context_after
        )
        
        # Step 6: Extract identifiers from error
        context.identifiers = self._extract_identifiers(context.error_line)
        
        # Step 7: Find related lines (mention same identifiers)
        if context.identifiers:
            context.related_lines = self._find_related_lines(lines, context.identifiers, context.error_line_number)
        
        # Step 8 (Req 17.5): Find related tool invocation
        if tool_invocations:
            if self._is_pipeline_level_error(context.error_line):
                # For pipeline errors, find tool that references the same identifier
                context.related_tool = self._find_tool_by_identifier(
                    context.error_line, tool_invocations
                )
            else:
                context.related_tool = self._find_related_tool(
                    context.error_line_number,
                    tool_invocations,
                )
        
        return context
    
    def _find_tool_by_identifier(self, error_line: str, tool_invocations: List[Any]) -> Optional[Dict[str, Any]]:
        """
        Find a tool invocation that references the same identifier as in the error.
        
        Example: Error mentions 'CI_GB-SVC-SHPE-PRD', find the aws command that uses it.
        """
        if not error_line or not tool_invocations:
            return None
        
        # Extract identifiers from error (quoted strings, paths, IDs)
        identifier_patterns = [
            r"'([A-Za-z0-9_-]{4,})'",  # Single quoted
            r'"([A-Za-z0-9_-]{4,})"',  # Double quoted
            r'/([A-Za-z0-9_-]{4,})(?:\s|$|\'|")',  # Path component
        ]
        
        identifiers = set()
        for pattern in identifier_patterns:
            for match in re.finditer(pattern, error_line):
                identifiers.add(match.group(1))
        
        if not identifiers:
            return None
        
        # Find tool that references any of these identifiers
        for tool in reversed(tool_invocations):  # Check last tools first
            command = (
                tool.command_line if hasattr(tool, 'command_line')
                else tool.get('command_line', '')
            )
            for identifier in identifiers:
                if identifier in command:
                    if hasattr(tool, 'to_dict'):
                        return tool.to_dict()
                    elif isinstance(tool, dict):
                        return tool
                    else:
                        return {
                            'tool_name': getattr(tool, 'tool_name', 'unknown'),
                            'command_line': command,
                            'line_number': getattr(tool, 'line_number', 0),
                            'output_lines': getattr(tool, 'output_lines', []),
                            'exit_code': getattr(tool, 'exit_code', None),
                        }
        
        return None
    
    def _is_pipeline_level_error(self, error_line: str) -> bool:
        """
        Check if error is a Jenkins pipeline-level error (not from shell command).
        
        These errors should NOT be attributed to a shell command/tool because
        they occur at the Jenkins pipeline level, not inside a sh/bat step.
        """
        if not error_line:
            return False
        
        pipeline_error_patterns = [
            r"Could not find credentials entry with ID",
            r"Credentials .+ not found",
            r"No such DSL method",
            r"java\.lang\.\w+Exception:",
            r"java\.io\.\w+Exception:",
            r"hudson\.\w+Exception:",
            r"org\.jenkinsci\.\w+Exception:",
            r"Timeout .+ exceeded",
            r"Script approval required",
            r"RejectedAccessException",
            r"CpsCallableInvocation",
            r"WorkflowScript:",
            r"groovy\.lang\.\w+Exception:",
            r"No signature of method",
            r"Cannot invoke method .+ on null",
            r"MissingPropertyException",
        ]
        
        for pattern in pipeline_error_patterns:
            if re.search(pattern, error_line, re.IGNORECASE):
                return True
        
        return False
    
    def _find_related_tool(
        self,
        error_line_index: int,
        tool_invocations: List[Any],
    ) -> Optional[Dict[str, Any]]:
        """Find the tool invocation most likely related to the error (Req 17.5).

        ``error_line_index`` is 0-based in the full console log; tool lines are 1-based (LogParser).
        Uses span-based scoring so long outputs (Maven, internal CLIs) still map to the right command.
        """
        if not tool_invocations or error_line_index < 0:
            return None

        error_line_1based = error_line_index + 1
        best = pick_best_tool_invocation(tool_invocations, error_line_1based)
        if best is None:
            return None
        return tool_dict_from_any(best)
    
    def _classify_context_lines(
        self,
        context_before: List[str],
        context_after: List[str],
    ) -> Dict[int, str]:
        """
        Classify context lines by type (Requirement 20.6).
        
        Returns a dict mapping line index to type label.
        """
        if PipelineLineType is None:
            return {}
        
        result = {}
        in_sh_block = False
        prev_type = None
        
        # Shell command pattern (HH:MM:SS + command)
        shell_cmd_pattern = re.compile(r'^\d{2}:\d{2}:\d{2}\s+\+\s+(.+)')
        
        def classify(line: str) -> str:
            nonlocal in_sh_block, prev_type
            
            line_stripped = line.strip()
            
            # Pipeline markers
            if line_stripped.startswith("[Pipeline]"):
                rest = line_stripped[10:].strip()
                
                if rest.startswith("stage") or rest.startswith("{ ("):
                    in_sh_block = False
                    prev_type = "STAGE"
                    return "STAGE"
                elif rest == "echo":
                    in_sh_block = False
                    prev_type = "ECHO"
                    return "ECHO"
                elif rest == "sh":
                    in_sh_block = True
                    prev_type = "SH"
                    return "SH"
                else:
                    in_sh_block = False
                    prev_type = "STEP"
                    return "STEP"
            
            # Echo output (line after [Pipeline] echo)
            if prev_type == "ECHO":
                prev_type = None
                return "ECHO_OUT"
            
            # Inside shell block
            if in_sh_block:
                if shell_cmd_pattern.match(line_stripped):
                    return "SHELL_CMD"
                else:
                    return "SHELL_OUT"
            
            prev_type = None
            return ""  # No label for OTHER lines
        
        # Classify before context
        for i, line in enumerate(context_before):
            label = classify(line)
            if label:
                result[i] = label
        
        # Reset state for after context
        in_sh_block = False
        prev_type = None
        
        # Classify after context (offset index)
        offset = len(context_before) + 1  # +1 for error line
        for i, line in enumerate(context_after):
            label = classify(line)
            if label:
                result[offset + i] = label
        
        return result
    
    def _find_last_stage(self, lines: List[str]) -> Tuple[Optional[str], int]:
        """Find the last pipeline stage."""
        last_stage_name = None
        last_stage_idx = -1
        
        for i, line in enumerate(lines):
            match = self.STAGE_PATTERN.search(line)
            if match:
                last_stage_name = match.group(1).strip()
                last_stage_idx = i
        
        return last_stage_name, last_stage_idx
    
    def _find_failed_method(self, lines: List[str]) -> Optional[str]:
        """Find the method that was running when failure occurred.
        
        Implements Requirement 1.10: Same logic as LogParser for consistency
        
        Pattern priority:
        - Primary (if prefix configured): {prefix}: method_name (Req 1.1)
        - Secondary (fallback): hh:mm:ss  method_name: method_name (Req 1.3)
        - Finish: method_name :time-elapsed-seconds:NN (Req 1.4)
        
        Returns the last method that started but didn't finish.
        """
        # Pattern for method finish: method_name :time-elapsed-seconds:NN (Req 1.4)
        finish_pattern = re.compile(r'^(.+?)\s+:time-elapsed-seconds:\d+')
        
        # Primary pattern: {prefix}: method_name (Req 1.1)
        prefix_pattern = None
        if self.method_prefix:
            prefix_pattern = re.compile(rf'{re.escape(self.method_prefix)}:\s*(.+)$', re.IGNORECASE)
        
        # Secondary pattern (fallback): timestamp + method: method (Req 1.3)
        secondary_pattern = re.compile(r'^\d{2}:\d{2}:\d{2}\s+(\S[^:]*?):\s*\1\s*$')
        
        started_methods = []  # List of (method_name, line_index)
        finished_methods = set()  # Set of normalized method names
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # Check primary pattern first (Req 1.1)
            if prefix_pattern:
                exec_match = prefix_pattern.search(line_stripped)
                if exec_match:
                    method_name = exec_match.group(1).strip()
                    started_methods.append((method_name, i))
                    continue
            
            # Check secondary pattern only if no prefix configured (Req 1.3)
            if not self.method_prefix:
                start_match = secondary_pattern.match(line_stripped)
                if start_match:
                    method_name = start_match.group(1).strip()
                    started_methods.append((method_name, i))
                    continue
            
            # Check for method finish (Req 1.4)
            finish_match = finish_pattern.match(line_stripped)
            if finish_match:
                method_name = finish_match.group(1).strip()
                # Normalize: lowercase + collapse whitespace (Req 1.9)
                normalized = self._normalize_method_name(method_name)
                finished_methods.add(normalized)
        
        # Find the last method that started but didn't finish (Req 1.6, 1.7)
        for method_name, line_idx in reversed(started_methods):
            normalized = self._normalize_method_name(method_name)
            if normalized not in finished_methods:
                return method_name
        
        # If all methods finished, return the last one that ran (Req 1.8)
        if started_methods:
            return started_methods[-1][0]
        
        return None
    
    def _normalize_method_name(self, name: str) -> str:
        """Normalize method name for comparison (Req 1.9).
        
        Lowercases and collapses all whitespace sequences to single space.
        """
        normalized = name.lower()
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized
    
    def _early_scm_signal_score(self, line: str) -> int:
        """Score lines that indicate checkout / SCM / Git failure (often in early log)."""
        if not line or not line.strip():
            return 0
        patterns = [
            (r"(?i)couldn'?t find any revision", 10),
            (r"(?i)could not find any revision", 10),
            (r"(?i)gitexception", 10),
            (r"(?i)unable to checkout", 9),
            (r"(?i)checkout failed", 9),
            (r"(?i)fatal:.*(git|remote|repository)", 9),
            (r"(?i)hudson\.plugins\.git", 9),
            (r"(?i)revision.*not found", 8),
            (r"(?i)repository.*not found", 8),
            (r"(?i)authentication failed.*git", 7),
            (r"(?i)error fetching remote", 8),
        ]
        best = 0
        for pat, weight in patterns:
            if re.search(pat, line):
                best = max(best, weight)
        return best
    
    def _reconcile_primary_error_line(
        self,
        lines: List[str],
        finder_idx: int,
        finder_score: int,
        parsed_log: Optional[Any],
    ) -> Tuple[int, str, str, FailureFingerprint]:
        """
        Align tail-focused finder with LogParser's first error when early SCM signals warrant it.
        Returns (line_index, line_text, reconciliation_note, fingerprint).
        """
        n = len(lines)
        fp = FailureFingerprint(
            finder_primary_line_1based=finder_idx + 1 if 0 <= finder_idx < n else 0,
            chosen_primary_line_1based=finder_idx + 1 if 0 <= finder_idx < n else 0,
            chosen_source="finder",
            aligned=True,
        )
        if n == 0 or finder_idx < 0 or finder_idx >= n:
            return finder_idx, lines[finder_idx] if 0 <= finder_idx < n else "", "", fp
        finder_line = lines[finder_idx]
        if parsed_log is None:
            return finder_idx, finder_line, "", fp
        errs = getattr(parsed_log, "errors", None) or []
        if not errs:
            return finder_idx, finder_line, "", fp
        pe = errs[0]
        pi = getattr(pe, "line_number", 0) - 1
        fp.parser_primary_line_1based = pi + 1 if pi >= 0 else None
        if pi < 0 or pi >= n:
            return finder_idx, finder_line, "", fp
        pline = lines[pi]
        early = self._early_scm_signal_score(pline)
        # Strong early SCM in first third; finder on last third — prefer early
        if early >= 9 and pi < n // 3 and finder_idx >= 2 * n // 3:
            note = (
                f"Using LogParser's first error (line {pi + 1}) over tail-focused line ({finder_idx + 1}): "
                "strong SCM/checkout/Git signal early in the log."
            )
            fp.chosen_primary_line_1based = pi + 1
            fp.chosen_source = "parser_early_scm"
            fp.aligned = abs(pi - finder_idx) <= 2
            fp.note = note
            return pi, pline, note, fp
        # Parser much earlier with solid SCM signal
        if (
            early >= 7
            and pi < finder_idx
            and (finder_idx - pi) > max(25, n // 10)
        ):
            note = (
                f"LogParser first error (line {pi + 1}) precedes tail focus (line {finder_idx + 1}); "
                "checkout/SCM issues may cause later failures—investigate both."
            )
            fp.chosen_primary_line_1based = pi + 1
            fp.chosen_source = "parser_precedes_tail"
            fp.aligned = False
            fp.note = note
            return pi, pline, note, fp
        if abs(pi - finder_idx) <= 2:
            fp.aligned = True
            fp.chosen_primary_line_1based = finder_idx + 1
            return finder_idx, finder_line, "", fp
        note = (
            f"LogParser highlights line {pi + 1}; focused context centers on line {finder_idx + 1}. "
            "Consider both if the failure chain spans stages."
        )
        fp.chosen_source = "finder_with_note"
        fp.aligned = False
        fp.note = note
        return finder_idx, finder_line, note, fp
    
    def _find_error_line(self, lines: List[str], start_idx: int) -> Tuple[int, str, int]:
        """
        Find the primary error line, searching from end.
        
        Returns (line_index, line_content, confidence_score)
        """
        best_idx = -1
        best_line = ""
        best_score = 0
        
        n_lines = len(lines)
        # Search backwards from end
        for i in range(n_lines - 1, start_idx - 1, -1):
            line = lines[i]
            score = self._score_error_line(line, line_index=i, n_lines=n_lines)
            
            # Prioritize later lines (closer to end) with same score
            if score > best_score:
                best_score = score
                best_idx = i
                best_line = line
        
        return best_idx, best_line, best_score
    
    def _score_error_line(self, line: str, line_index: int = 0, n_lines: int = 1) -> int:
        """Score how likely this line is the primary error (multi-signal: pattern + early SCM position)."""
        if not line.strip():
            return 0
        
        score = 0
        for pattern, weight in self.ERROR_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                score = max(score, weight)
        
        scm = self._early_scm_signal_score(line)
        if scm >= 7 and n_lines > 20:
            score += min(scm, 10)
            # Boost strong early-log SCM even if tail search would otherwise win later
            pos = line_index / max(n_lines - 1, 1)
            if pos < 0.35:
                score += 4
        
        return score
    
    def _classify_error(self, error_line: str) -> ErrorType:
        """Classify error type based on error message."""
        if not error_line:
            return ErrorType.UNKNOWN
        
        error_lower = error_line.lower()
        
        for error_type, patterns in self.ERROR_TYPE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, error_lower, re.IGNORECASE):
                    return error_type
        
        return ErrorType.UNKNOWN
    
    def _extract_context_before(self, lines: List[str], error_idx: int) -> List[str]:
        """Extract lines before the error."""
        start = max(0, error_idx - self.context_before)
        return lines[start:error_idx]
    
    def _extract_context_after(self, lines: List[str], error_idx: int) -> List[str]:
        """Extract lines after the error."""
        end = min(len(lines), error_idx + 1 + self.context_after)
        return lines[error_idx + 1:end]
    
    def _extract_identifiers(self, error_line: str) -> List[str]:
        """
        Extract potential identifiers from error message.
        
        Looks for:
        - Quoted strings
        - IDs, names, paths
        - CAPS words (likely constants/IDs)
        """
        identifiers = set()
        
        # Quoted strings
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", error_line)
        identifiers.update(quoted)
        
        # After keywords: ID, name, parameter, etc.
        keyword_patterns = [
            r'\bID\s+(\S+)',
            r'\bname\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
            r'\bparameter\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
            r'\bsecret\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
            r'\bcredential\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
            r'\bservice\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
            r'\bfile\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
            r'\bpath\s+[\'"]?(\S+?)[\'"]?(?:\s|$)',
        ]
        for pattern in keyword_patterns:
            matches = re.findall(pattern, error_line, re.IGNORECASE)
            identifiers.update(matches)
        
        # CAPS words (likely IDs/constants)
        caps = re.findall(r'\b([A-Z][A-Z0-9_-]{2,})\b', error_line)
        identifiers.update(caps)
        
        # Filter noise
        noise = {'ERROR', 'FAILED', 'NOT', 'FOUND', 'THE', 'WITH', 'FOR', 'AND', 'BUT'}
        identifiers = {id for id in identifiers if id.upper() not in noise and len(id) > 1}
        
        return list(identifiers)
    
    def _find_related_lines(
        self, 
        lines: List[str], 
        identifiers: List[str],
        error_idx: int
    ) -> List[Tuple[int, str]]:
        """Find lines that mention the same identifiers as the error."""
        related = []
        
        for i, line in enumerate(lines):
            if i == error_idx:
                continue
            
            for identifier in identifiers:
                if identifier in line or identifier.lower() in line.lower():
                    related.append((i, line))
                    break
        
        # Sort by distance to error (closest first)
        related.sort(key=lambda x: abs(x[0] - error_idx))
        
        return related[:10]  # Max 10 related lines


def find_root_cause(log: str, config: Optional[Dict[str, Any]] = None) -> RootCauseContext:
    """
    Convenience function to find root cause context.
    
    Usage:
        context = find_root_cause(log_content)
        print(context.get_ai_prompt_context())
    """
    finder = RootCauseFinder(config)
    return finder.find(log)
