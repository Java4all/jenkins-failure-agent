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
    
    # Extracted identifiers (IDs, names, paths mentioned in error)
    identifiers: List[str] = field(default_factory=list)
    
    # Related lines (lines that mention the identifiers)
    related_lines: List[Tuple[int, str]] = field(default_factory=list)
    
    # Summary for AI
    def get_ai_prompt_context(self) -> str:
        """Generate focused context for AI analysis."""
        parts = []
        
        if self.failed_stage:
            parts.append(f"FAILED STAGE: {self.failed_stage}")
        if self.failed_method:
            parts.append(f"FAILED METHOD: {self.failed_method}")
        
        parts.append(f"\nERROR TYPE: {self.error_type.value}")
        parts.append(f"ERROR: {self.error_line}")
        
        if self.identifiers:
            parts.append(f"\nKEY IDENTIFIERS: {', '.join(self.identifiers)}")
        
        # Context before (commands that led to error)
        if self.context_before:
            parts.append("\n" + "="*50)
            parts.append("COMMANDS/OPERATIONS BEFORE ERROR:")
            parts.append("="*50)
            for line in self.context_before:
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
            for line in self.context_after:
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
    
    def find(self, log: str) -> RootCauseContext:
        """
        Find root cause context from log.
        
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
            context.error_line_number = error_idx
            context.error_line = error_line
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
        
        # Step 6: Extract identifiers from error
        context.identifiers = self._extract_identifiers(context.error_line)
        
        # Step 7: Find related lines (mention same identifiers)
        if context.identifiers:
            context.related_lines = self._find_related_lines(lines, context.identifiers, context.error_line_number)
        
        return context
    
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
        """Find the method that was running when failure occurred."""
        if not self.method_prefix:
            return None
        
        # Pattern for method execution
        prefix_pattern = re.compile(rf'{re.escape(self.method_prefix)}:\s*(.+)$', re.IGNORECASE)
        
        # Pattern for method start: hh:mm:ss  method_name: method_name
        start_pattern = re.compile(r'^\d{2}:\d{2}:\d{2}\s+([^:]+):\s*\1\s*$')
        
        # Pattern for method finish: method_name :time-elapsed-seconds:NN
        finish_pattern = re.compile(r'^(.+?)\s+:time-elapsed-seconds:\d+')
        
        started = []
        finished = set()
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Check prefix pattern
            match = prefix_pattern.search(line)
            if match:
                started.append(match.group(1).strip())
                continue
            
            # Check start pattern
            match = start_pattern.match(line)
            if match:
                started.append(match.group(1).strip())
                continue
            
            # Check finish pattern
            match = finish_pattern.match(line)
            if match:
                finished.add(match.group(1).strip())
        
        # Return last method that started but didn't finish
        for method in reversed(started):
            if method not in finished:
                return method
        
        return started[-1] if started else None
    
    def _find_error_line(self, lines: List[str], start_idx: int) -> Tuple[int, str, int]:
        """
        Find the primary error line, searching from end.
        
        Returns (line_index, line_content, confidence_score)
        """
        best_idx = -1
        best_line = ""
        best_score = 0
        
        # Search backwards from end
        for i in range(len(lines) - 1, start_idx - 1, -1):
            line = lines[i]
            score = self._score_error_line(line)
            
            # Prioritize later lines (closer to end) with same score
            if score > best_score:
                best_score = score
                best_idx = i
                best_line = line
        
        return best_idx, best_line, best_score
    
    def _score_error_line(self, line: str) -> int:
        """Score how likely this line is the primary error."""
        if not line.strip():
            return 0
        
        score = 0
        line_lower = line.lower()
        
        for pattern, weight in self.ERROR_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                score = max(score, weight)
        
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
