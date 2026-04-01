"""
MCP-inspired tool system for agentic investigation.

This module provides a tool-calling interface compatible with OpenAI's function calling
format, allowing the LLM to dynamically investigate Jenkins failures by calling tools.

Architecture:
    Tools are registered as Python functions with metadata.
    The LLM receives tool definitions in OpenAI format.
    Tool calls are executed and results returned to the LLM.
    
This can be upgraded to full MCP protocol later if needed.
"""

from .registry import ToolRegistry, tool, get_registry
from .executor import ToolExecutor
from .jenkins_tools import register_jenkins_tools
from .github_tools import register_github_tools
from .investigation_tools import register_investigation_tools

__all__ = [
    "ToolRegistry",
    "ToolExecutor", 
    "tool",
    "get_registry",
    "register_jenkins_tools",
    "register_github_tools",
    "register_investigation_tools",
]
