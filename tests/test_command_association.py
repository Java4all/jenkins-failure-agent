"""Tests for span-based failing-command association."""

import pytest

from src.log_parser import ToolInvocation
from src.command_association import pick_best_tool_invocation, inferred_span_end_1based


@pytest.mark.unit
def test_long_maven_like_command_wins_over_later_short_command():
    """Error in the middle of a long build: pick the build tool, not a later shell line."""
    tools = [
        ToolInvocation(
            tool_name="mvn",
            command_line="mvn -q clean install",
            line_number=10,
            exit_code=None,
            output_lines=["Downloading...", "[ERROR] Could not resolve dependency foo"],
        ),
        ToolInvocation(
            tool_name="shell",
            command_line="echo cleanup",
            line_number=800,
            exit_code=0,
            output_lines=["cleanup"],
        ),
    ]
    # Error on line 400 — still inside inferred span of mvn (>=400 lines assumed for mvn)
    best = pick_best_tool_invocation(tools, 400)
    assert best is not None
    assert best.tool_name == "mvn"


@pytest.mark.unit
def test_nonzero_exit_boosts_correct_tool():
    t1 = ToolInvocation("echo", "echo hi", 50, exit_code=0, output_lines=["hi"])
    t2 = ToolInvocation("custom-cli", "./tools/internal-deploy --env qa", 60, exit_code=1, output_lines=["ERROR: bad config"])
    best = pick_best_tool_invocation([t1, t2], 65)
    assert best.tool_name == "custom-cli"


@pytest.mark.unit
def test_inferred_span_includes_long_output_tools():
    t = ToolInvocation("mvn", "mvn verify", 1, None, [])
    assert inferred_span_end_1based(t) >= 400
