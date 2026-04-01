"""
Tool executor for handling LLM tool calls.

Manages the execution of tools called by the LLM during agentic investigation.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from .registry import ToolRegistry, ToolCategory

logger = logging.getLogger("jenkins-agent.mcp.executor")


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool."""
    tool_call_id: str
    name: str
    result: str
    success: bool
    error: Optional[str] = None


class ToolExecutor:
    """
    Executes tool calls from the LLM.
    
    Usage:
        executor = ToolExecutor(registry)
        
        # Parse tool calls from LLM response
        tool_calls = executor.parse_tool_calls(response.message)
        
        # Execute all tool calls
        results = executor.execute_all(tool_calls)
        
        # Format results for next LLM message
        messages = executor.format_results_for_llm(results)
    """
    
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.call_history: List[ToolResult] = []
        self.max_result_length = 10000  # Truncate very long results
    
    def parse_tool_calls(self, message: Any) -> List[ToolCall]:
        """
        Parse tool calls from an LLM response message.
        
        Handles both OpenAI format and Ollama format.
        """
        tool_calls = []
        
        # OpenAI format
        if hasattr(message, 'tool_calls') and message.tool_calls:
            for tc in message.tool_calls:
                arguments = tc.function.arguments
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {"raw": arguments}
                
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=arguments,
                ))
        
        # Ollama format (sometimes returns in content)
        elif hasattr(message, 'content') and message.content:
            content = message.content
            if isinstance(content, str) and '<tool_call>' in content:
                tool_calls.extend(self._parse_xml_tool_calls(content))
        
        return tool_calls
    
    def _parse_xml_tool_calls(self, content: str) -> List[ToolCall]:
        """Parse tool calls from XML format (Ollama sometimes uses this)."""
        import re
        tool_calls = []
        
        pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for i, match in enumerate(matches):
            try:
                data = json.loads(match)
                tool_calls.append(ToolCall(
                    id=f"call_{i}",
                    name=data.get('name', ''),
                    arguments=data.get('arguments', {}),
                ))
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse tool call: {match}")
        
        return tool_calls
    
    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a single tool call."""
        logger.info(f"Executing tool: {tool_call.name} with args: {tool_call.arguments}")
        
        try:
            result = self.registry.execute(tool_call.name, tool_call.arguments)
            
            # Convert result to string
            if isinstance(result, (dict, list)):
                result_str = json.dumps(result, indent=2, default=str)
            else:
                result_str = str(result)
            
            # Truncate very long results
            if len(result_str) > self.max_result_length:
                result_str = result_str[:self.max_result_length] + "\n... [truncated]"
            
            tool_result = ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=result_str,
                success=True,
            )
            
        except Exception as e:
            logger.error(f"Tool {tool_call.name} failed: {e}")
            tool_result = ToolResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                result=f"Error: {str(e)}",
                success=False,
                error=str(e),
            )
        
        self.call_history.append(tool_result)
        return tool_result
    
    def execute_all(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """Execute all tool calls and return results."""
        return [self.execute(tc) for tc in tool_calls]
    
    def format_results_for_llm(self, results: List[ToolResult]) -> List[Dict[str, Any]]:
        """Format tool results as messages for the LLM."""
        messages = []
        for result in results:
            messages.append({
                "role": "tool",
                "tool_call_id": result.tool_call_id,
                "name": result.name,
                "content": result.result,
            })
        return messages
    
    def get_call_summary(self) -> str:
        """Get a summary of all tool calls made during investigation."""
        if not self.call_history:
            return "No tools were called."
        
        lines = ["## Tool Calls Made\n"]
        for i, result in enumerate(self.call_history, 1):
            status = "✓" if result.success else "✗"
            lines.append(f"{i}. {status} `{result.name}`")
            if result.error:
                lines.append(f"   Error: {result.error}")
        
        return "\n".join(lines)
    
    def clear_history(self):
        """Clear the call history."""
        self.call_history = []


def create_executor(
    registry: Optional[ToolRegistry] = None,
    categories: Optional[List[ToolCategory]] = None,
) -> ToolExecutor:
    """
    Create a tool executor with the specified registry and category filters.
    
    If no registry is provided, uses the global registry.
    """
    from .registry import get_registry
    
    if registry is None:
        registry = get_registry()
    
    return ToolExecutor(registry)
