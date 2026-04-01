"""
Tool registry for MCP-style tools.

Provides decorators and infrastructure for registering tools that can be
called by the LLM during agentic investigation.
"""

import inspect
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Any, Optional, get_type_hints
from enum import Enum

logger = logging.getLogger("jenkins-agent.mcp.registry")


class ToolCategory(str, Enum):
    """Categories of tools for organization and filtering."""
    JENKINS = "jenkins"
    GITHUB = "github"
    GITLAB = "gitlab"
    INVESTIGATION = "investigation"
    REPORTING = "reporting"


@dataclass
class ToolParameter:
    """Definition of a tool parameter."""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class ToolDefinition:
    """Full definition of a tool."""
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter]
    function: Callable
    returns: str = "string"
    examples: List[str] = field(default_factory=list)
    
    def to_openai_format(self) -> dict:
        """Convert to OpenAI function calling format."""
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                }
            }
        }


class ToolRegistry:
    """
    Registry for managing investigation tools.
    
    Usage:
        registry = ToolRegistry()
        
        @registry.tool(category=ToolCategory.JENKINS)
        def get_console_log(job: str, build: int, max_lines: int = 500) -> str:
            '''Get console output from a Jenkins build.'''
            ...
        
        # Get tools for LLM
        tools = registry.get_openai_tools()
        
        # Execute a tool
        result = registry.execute("get_console_log", {"job": "my-job", "build": 123})
    """
    
    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._context: Dict[str, Any] = {}
    
    def set_context(self, **kwargs):
        """Set context objects (clients, configs) that tools can access."""
        self._context.update(kwargs)
    
    def get_context(self, key: str) -> Any:
        """Get a context object."""
        return self._context.get(key)
    
    def tool(
        self,
        category: ToolCategory,
        name: Optional[str] = None,
        description: Optional[str] = None,
        examples: Optional[List[str]] = None,
    ):
        """
        Decorator to register a function as a tool.
        
        Parameters are automatically extracted from function signature and docstring.
        """
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            tool_desc = description or (func.__doc__ or "").split("\n")[0].strip()
            
            # Extract parameters from function signature
            sig = inspect.signature(func)
            type_hints = get_type_hints(func) if hasattr(func, '__annotations__') else {}
            
            # Parse docstring for parameter descriptions
            param_docs = self._parse_docstring_params(func.__doc__ or "")
            
            parameters = []
            for param_name, param in sig.parameters.items():
                if param_name in ('self', 'cls', 'context'):
                    continue
                
                # Determine type
                hint = type_hints.get(param_name, str)
                param_type = self._python_type_to_json(hint)
                
                # Get description from docstring
                param_desc = param_docs.get(param_name, f"The {param_name} parameter")
                
                # Check if required
                has_default = param.default != inspect.Parameter.empty
                default_value = param.default if has_default else None
                
                parameters.append(ToolParameter(
                    name=param_name,
                    type=param_type,
                    description=param_desc,
                    required=not has_default,
                    default=default_value,
                ))
            
            tool_def = ToolDefinition(
                name=tool_name,
                description=tool_desc,
                category=category,
                parameters=parameters,
                function=func,
                examples=examples or [],
            )
            
            self._tools[tool_name] = tool_def
            logger.debug(f"Registered tool: {tool_name} ({category.value})")
            
            return func
        
        return decorator
    
    def register(self, tool_def: ToolDefinition):
        """Register a pre-built tool definition."""
        self._tools[tool_def.name] = tool_def
        logger.debug(f"Registered tool: {tool_def.name} ({tool_def.category.value})")
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def get_tools_by_category(self, category: ToolCategory) -> List[ToolDefinition]:
        """Get all tools in a category."""
        return [t for t in self._tools.values() if t.category == category]
    
    def get_all_tools(self) -> List[ToolDefinition]:
        """Get all registered tools."""
        return list(self._tools.values())
    
    def get_openai_tools(
        self,
        categories: Optional[List[ToolCategory]] = None
    ) -> List[dict]:
        """Get tools in OpenAI function calling format."""
        tools = self._tools.values()
        if categories:
            tools = [t for t in tools if t.category in categories]
        return [t.to_openai_format() for t in tools]
    
    def execute(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")
        
        # Inject context if the function accepts it
        sig = inspect.signature(tool.function)
        if 'context' in sig.parameters:
            arguments['context'] = self._context
        
        try:
            result = tool.function(**arguments)
            return result
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return f"Error executing {name}: {str(e)}"
    
    def _python_type_to_json(self, python_type) -> str:
        """Convert Python type hint to JSON schema type."""
        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }
        
        # Handle Optional, List, etc.
        origin = getattr(python_type, '__origin__', None)
        if origin is not None:
            if origin is list:
                return "array"
            if origin is dict:
                return "object"
        
        return type_map.get(python_type, "string")
    
    def _parse_docstring_params(self, docstring: str) -> Dict[str, str]:
        """Parse parameter descriptions from docstring."""
        params = {}
        lines = docstring.split('\n')
        
        in_params = False
        current_param = None
        current_desc = []
        
        for line in lines:
            stripped = line.strip()
            
            # Detect Args/Parameters section
            if stripped.lower() in ('args:', 'arguments:', 'parameters:', 'params:'):
                in_params = True
                continue
            
            # Detect end of params section
            if in_params and stripped.lower() in ('returns:', 'raises:', 'examples:', 'note:', 'notes:'):
                if current_param:
                    params[current_param] = ' '.join(current_desc).strip()
                break
            
            if in_params:
                # Check for new parameter (name: description or name (type): description)
                if ':' in stripped and not stripped.startswith(' '):
                    if current_param:
                        params[current_param] = ' '.join(current_desc).strip()
                    
                    parts = stripped.split(':', 1)
                    param_part = parts[0].strip()
                    # Handle "param_name (type)" format
                    if '(' in param_part:
                        param_part = param_part.split('(')[0].strip()
                    current_param = param_part
                    current_desc = [parts[1].strip()] if len(parts) > 1 else []
                elif current_param and stripped:
                    current_desc.append(stripped)
        
        if current_param:
            params[current_param] = ' '.join(current_desc).strip()
        
        return params


# Global registry instance
_global_registry = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def tool(
    category: ToolCategory,
    name: Optional[str] = None,
    description: Optional[str] = None,
    examples: Optional[List[str]] = None,
):
    """Decorator to register a tool with the global registry."""
    return get_registry().tool(category, name, description, examples)
