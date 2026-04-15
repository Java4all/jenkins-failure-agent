"""
Tool-agnostic association of Jenkins console errors with the shell command that caused them.

Uses execution envelope (command line + output span + exit code), not tool-specific anchors,
so internal/custom CLIs work without KB entries.

Line numbers follow Jenkins console: 1-based, matching ToolInvocation.line_number and
ErrorMatch.line_number from LogParser. RootCauseFinder passes a 0-based error index; convert
with +1 before calling pick_best_tool_invocation.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

# Generic failure / stderr signals in captured output (not tool-specific)
_OUTPUT_FAILURE_SIGNALS = (
    "error:",
    "fatal:",
    "failed",
    "exception",
    "cannot ",
    "unable to",
    "not found",
    "denied",
    " rejected",
    "non-zero",
    "exit code",
    "returned exit",
    "build failure",
    "[error]",
    "[fatal]",
)

# Build / package managers: output often far exceeds default captured lines — infer min span
_LONG_OUTPUT_CMD = re.compile(
    r"(?i)\b(mvnw?|gradle\w*|gradlew|npm|yarn|pnpm|make|cmake|ninja|bazel|buck)\b",
)

# Jenkins pipeline: script exit recorded near failing block
_EXIT_LINE = re.compile(
    r"(?i)(script returned exit code|returned exit code|exit code|finished:\s*failure)\s*[:\s]*(\d+)",
)


def _get_line_number(tool: Any) -> int:
    if hasattr(tool, "line_number"):
        return int(getattr(tool, "line_number") or 0)
    return int(tool.get("line_number") or 0)


def _get_output_lines(tool: Any) -> List[str]:
    if hasattr(tool, "output_lines"):
        return list(getattr(tool, "output_lines") or [])
    return list(tool.get("output_lines") or [])


def _get_exit_code(tool: Any) -> Optional[int]:
    if hasattr(tool, "exit_code"):
        ec = getattr(tool, "exit_code")
        return int(ec) if ec is not None else None
    ec = tool.get("exit_code")
    return int(ec) if ec is not None else None


def _get_command_line(tool: Any) -> str:
    if hasattr(tool, "command_line"):
        return str(getattr(tool, "command_line") or "")
    return str(tool.get("command_line") or "")


def inferred_output_span_lines(tool: Any) -> int:
    """
    Approximate how many console lines follow the command line for this invocation.
    LogParser caps output_lines; for long-running build tools we assume a larger footprint.
    """
    out = _get_output_lines(tool)
    n = len(out)
    cmd = _get_command_line(tool)
    if _LONG_OUTPUT_CMD.search(cmd):
        n = max(n, 400)
    else:
        # Unknown internal CLI: still assume commands can emit hundreds of lines
        n = max(n, 120)
    return n


def inferred_span_end_1based(tool: Any) -> int:
    start = _get_line_number(tool)
    return start + inferred_output_span_lines(tool) + 5


def score_tool_for_error_line(tool: Any, error_line_1based: int) -> float:
    """
    Higher score = more likely this command produced the error.
    """
    start = _get_line_number(tool)
    if start <= 0:
        return -1e9

    span_end = inferred_span_end_1based(tool)
    out_lines = _get_output_lines(tool)
    cmd = _get_command_line(tool)

    # Error must occur at or after the command line (same block)
    if error_line_1based < start:
        return -1e9

    score = 0.0

    # Dominant: error falls inside inferred output window of this tool
    if start <= error_line_1based <= span_end:
        score += 5000.0
        # Nearer to end of typical output block still inside span — slight preference for same tool
        score -= 0.02 * (error_line_1based - start)
    else:
        # After inferred span: long gap — penalize but keep some signal
        gap = error_line_1based - span_end
        if gap > 2000:
            score -= 2000.0
        else:
            score += 500.0 - gap

    # Non-zero exit strongly correlates with failing step
    ec = _get_exit_code(tool)
    if ec is not None and ec != 0:
        score += 350.0
    elif ec == 0:
        score -= 80.0

    # Failure-like text in captured output
    for line in out_lines:
        low = line.lower()
        for sig in _OUTPUT_FAILURE_SIGNALS:
            if sig in low:
                score += 45.0
                break

    # Jenkins explicit failure on output line
    for line in out_lines[-8:]:
        if _EXIT_LINE.search(line):
            score += 120.0
            break

    # Prefer smaller distance from command to error when scores tie
    score -= 0.15 * float(error_line_1based - start)

    # Tiny boost for typical shell invocations (informational only)
    if cmd.strip().startswith("./") or "&&" in cmd or "|" in cmd:
        score += 8.0

    return score


def pick_best_tool_invocation(
    invocations: List[Any],
    error_line_1based: int,
) -> Optional[Any]:
    """
    Select the tool invocation most likely tied to the error at ``error_line_1based`` (1-based).

    Pass ``error_line_1based = error_idx_0based + 1`` when converting from RootCauseFinder.
    """
    if not invocations or error_line_1based < 1:
        return None

    best: Optional[Any] = None
    best_score = -1e18

    for tool in invocations:
        s = score_tool_for_error_line(tool, error_line_1based)
        if s > best_score:
            best_score = s
            best = tool

    if best is None or best_score < -1e8:
        return None
    return best


def tool_dict_from_any(tool: Any) -> dict:
    """Normalize to dict for RootCauseContext / JSON."""
    if hasattr(tool, "to_dict"):
        return tool.to_dict()
    if isinstance(tool, dict):
        return tool
    return {
        "tool_name": getattr(tool, "tool_name", "unknown"),
        "command_line": getattr(tool, "command_line", ""),
        "line_number": getattr(tool, "line_number", 0),
        "exit_code": getattr(tool, "exit_code", None),
        "output_lines": list(getattr(tool, "output_lines", []) or []),
    }


def associate_error_to_tool_for_parsed_log(
    error_line_1based: int,
    tool_invocations: List[Any],
) -> Optional[Any]:
    """
    For LogParser ErrorMatch (already 1-based line_number): pick related tool.
    """
    return pick_best_tool_invocation(tool_invocations, error_line_1based)
