"""
Agentic investigation module.

This module provides the agent loop that drives LLM-based investigation
of Jenkins failures using MCP tools.
"""

from .investigator import Investigator, InvestigationResult
from .prompts import get_investigation_prompt, get_system_prompt

__all__ = [
    "Investigator",
    "InvestigationResult",
    "get_investigation_prompt",
    "get_system_prompt",
]
