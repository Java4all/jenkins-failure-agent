"""
Agentic investigator for Jenkins failures.

This module provides the main investigation loop that drives the LLM
through a series of tool calls to investigate Jenkins build failures.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

from openai import OpenAI

from ..mcp.registry import ToolRegistry, ToolCategory, get_registry
from ..mcp.executor import ToolExecutor
from ..mcp.jenkins_tools import register_jenkins_tools
from ..mcp.github_tools import register_github_tools
from ..mcp.investigation_tools import register_investigation_tools
from .prompts import get_system_prompt, get_investigation_prompt

logger = logging.getLogger("jenkins-agent.investigator")


class InvestigationStatus(str, Enum):
    """Status of an investigation."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    MAX_ITERATIONS = "max_iterations"


@dataclass
class InvestigationResult:
    """Result of an agentic investigation."""
    status: InvestigationStatus
    root_cause: str
    details: str
    evidence: List[str]
    recommendations: List[str]
    is_retriable: bool
    confidence: float
    tool_calls_made: int
    tokens_used: int
    duration_seconds: float
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "root_cause": self.root_cause,
            "details": self.details,
            "evidence": self.evidence,
            "recommendations": self.recommendations,
            "is_retriable": self.is_retriable,
            "confidence": self.confidence,
            "tool_calls_made": self.tool_calls_made,
            "tokens_used": self.tokens_used,
            "duration_seconds": self.duration_seconds,
        }


class Investigator:
    """
    Agentic investigator that uses MCP tools to investigate Jenkins failures.
    
    Usage:
        investigator = Investigator(config)
        investigator.set_clients(jenkins_client, github_client, scm_client)
        
        result = investigator.investigate(
            job="my-project",
            build=123,
            initial_error="MissingMethodException: No signature...",
            error_category="GROOVY_LIBRARY",
        )
    """
    
    def __init__(
        self,
        ai_config: Any,
        max_iterations: int = 15,
        max_tokens_per_call: int = 4096,
    ):
        """
        Initialize the investigator.
        
        Args:
            ai_config: AI configuration with base_url, model, api_key
            max_iterations: Maximum tool call iterations
            max_tokens_per_call: Maximum tokens per LLM call
        """
        self.ai_config = ai_config
        self.max_iterations = max_iterations
        self.max_tokens_per_call = max_tokens_per_call
        
        # Initialize OpenAI client
        self.client = OpenAI(
            base_url=ai_config.base_url,
            api_key=ai_config.api_key or "not-needed",
        )
        self.model = ai_config.model
        
        # Initialize tool registry and register all tools
        self.registry = get_registry()
        register_jenkins_tools(self.registry)
        register_github_tools(self.registry)
        register_investigation_tools(self.registry)
        
        # Initialize executor
        self.executor = ToolExecutor(self.registry)
        
        logger.info(f"Investigator initialized with {len(self.registry.get_all_tools())} tools")
    
    def set_clients(
        self,
        jenkins_client: Any = None,
        github_client: Any = None,
        scm_client: Any = None,
    ):
        """
        Set the client instances that tools will use.
        
        Args:
            jenkins_client: JenkinsClient instance
            github_client: GitHubClient instance
            scm_client: SCMClient instance for PR comments
        """
        if jenkins_client:
            self.registry.set_context(jenkins_client=jenkins_client)
        if github_client:
            self.registry.set_context(github_client=github_client)
        if scm_client:
            self.registry.set_context(scm_client=scm_client)
    
    def investigate(
        self,
        job: str,
        build: int,
        initial_error: str,
        error_category: str,
        failed_stage: str = None,
        pr_url: str = None,
        include_categories: List[ToolCategory] = None,
    ) -> InvestigationResult:
        """
        Run an agentic investigation on a build failure.
        
        Args:
            job: Jenkins job name
            build: Build number
            initial_error: The primary error message
            error_category: Category from initial classification
            failed_stage: Stage where failure occurred
            pr_url: PR URL for posting results
            include_categories: Tool categories to include (None = all)
            
        Returns:
            InvestigationResult with findings.
        """
        start_time = time.time()
        self.executor.clear_history()
        
        logger.info(f"Starting investigation for {job}#{build}")
        logger.info(f"Category: {error_category}, Error: {initial_error[:100]}...")
        
        # Get available tools
        if include_categories:
            tools = self.registry.get_openai_tools(include_categories)
        else:
            tools = self.registry.get_openai_tools()
        
        logger.debug(f"Available tools: {[t['function']['name'] for t in tools]}")
        
        # Build initial messages
        system_prompt = get_system_prompt()
        user_prompt = get_investigation_prompt(
            job=job,
            build=build,
            initial_error=initial_error,
            error_category=error_category,
            failed_stage=failed_stage,
            pr_url=pr_url,
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        total_tokens = 0
        iteration = 0
        
        try:
            # Main agent loop
            while iteration < self.max_iterations:
                iteration += 1
                logger.info(f"Investigation iteration {iteration}/{self.max_iterations}")
                
                # Call LLM
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools if tools else None,
                    tool_choice="auto" if tools else None,
                    max_tokens=self.max_tokens_per_call,
                    temperature=0.1,
                )
                
                # Track tokens
                if response.usage:
                    total_tokens += response.usage.total_tokens
                
                assistant_message = response.choices[0].message
                
                # Check for tool calls
                if assistant_message.tool_calls:
                    logger.info(f"LLM requested {len(assistant_message.tool_calls)} tool calls")
                    
                    # Add assistant message to history
                    messages.append({
                        "role": "assistant",
                        "content": assistant_message.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                }
                            }
                            for tc in assistant_message.tool_calls
                        ]
                    })
                    
                    # Execute tool calls
                    tool_calls = self.executor.parse_tool_calls(assistant_message)
                    results = self.executor.execute_all(tool_calls)
                    
                    # Add results to messages
                    for result in results:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": result.tool_call_id,
                            "content": result.result,
                        })
                    
                else:
                    # No tool calls - LLM is done investigating
                    logger.info("LLM completed investigation")
                    
                    # Parse the final response
                    final_content = assistant_message.content or ""
                    messages.append({"role": "assistant", "content": final_content})
                    
                    # Extract structured result
                    result = self._parse_final_response(final_content)
                    result.status = InvestigationStatus.COMPLETED
                    result.tool_calls_made = len(self.executor.call_history)
                    result.tokens_used = total_tokens
                    result.duration_seconds = time.time() - start_time
                    result.conversation_history = messages
                    
                    logger.info(f"Investigation complete: {result.root_cause[:100]}...")
                    return result
            
            # Max iterations reached
            logger.warning(f"Investigation reached max iterations ({self.max_iterations})")
            
            # Get final summary from LLM
            messages.append({
                "role": "user",
                "content": "You've reached the maximum number of tool calls. Please provide your best analysis based on what you've found so far."
            })
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens_per_call,
                temperature=0.1,
            )
            
            final_content = response.choices[0].message.content or ""
            result = self._parse_final_response(final_content)
            result.status = InvestigationStatus.MAX_ITERATIONS
            result.tool_calls_made = len(self.executor.call_history)
            result.tokens_used = total_tokens
            result.duration_seconds = time.time() - start_time
            result.conversation_history = messages
            
            return result
            
        except Exception as e:
            logger.exception(f"Investigation failed: {e}")
            
            return InvestigationResult(
                status=InvestigationStatus.FAILED,
                root_cause=f"Investigation failed: {str(e)}",
                details="",
                evidence=[],
                recommendations=[],
                is_retriable=False,
                confidence=0.0,
                tool_calls_made=len(self.executor.call_history),
                tokens_used=total_tokens,
                duration_seconds=time.time() - start_time,
                conversation_history=messages,
            )
    
    def _parse_final_response(self, content: str) -> InvestigationResult:
        """
        Parse the LLM's final response into structured result.
        
        Args:
            content: The final response text
            
        Returns:
            InvestigationResult with extracted information.
        """
        # Try to extract structured information from the response
        root_cause = ""
        details = ""
        evidence = []
        recommendations = []
        is_retriable = False
        confidence = 0.7  # Default confidence
        
        # Split by common headers
        sections = {}
        current_section = "content"
        current_content = []
        
        for line in content.split('\n'):
            line_lower = line.lower().strip()
            
            # Detect section headers
            if line_lower.startswith('### root cause') or line_lower.startswith('## root cause') or line_lower == 'root cause':
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = 'root_cause'
                current_content = []
            elif line_lower.startswith('### detail') or line_lower.startswith('## detail'):
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = 'details'
                current_content = []
            elif line_lower.startswith('### evidence') or line_lower.startswith('## evidence'):
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = 'evidence'
                current_content = []
            elif line_lower.startswith('### recommend') or line_lower.startswith('## recommend') or line_lower.startswith('### fix'):
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = 'recommendations'
                current_content = []
            elif line_lower.startswith('### retriable') or line_lower.startswith('## retriable'):
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = 'retriable'
                current_content = []
            elif line_lower.startswith('### confidence') or line_lower.startswith('## confidence'):
                if current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = 'confidence'
                current_content = []
            else:
                current_content.append(line)
        
        # Don't forget the last section
        if current_content:
            sections[current_section] = '\n'.join(current_content)
        
        # Extract values from sections
        root_cause = sections.get('root_cause', '').strip()
        if not root_cause:
            # Try to get first meaningful paragraph
            root_cause = sections.get('content', '').split('\n\n')[0].strip()
        
        details = sections.get('details', '').strip()
        if not details:
            details = sections.get('content', '').strip()
        
        # Parse evidence as list
        evidence_text = sections.get('evidence', '')
        for line in evidence_text.split('\n'):
            line = line.strip()
            if line and line.startswith(('-', '*', '•')):
                evidence.append(line.lstrip('-*• '))
            elif line and not line.startswith('#'):
                evidence.append(line)
        
        # Parse recommendations as list
        rec_text = sections.get('recommendations', '')
        for line in rec_text.split('\n'):
            line = line.strip()
            if line and (line.startswith(('-', '*', '•')) or (line[0].isdigit() and '.' in line[:3])):
                rec = line.lstrip('-*•0123456789. ')
                if rec:
                    recommendations.append(rec)
        
        # Parse retriable
        retriable_text = sections.get('retriable', '').lower()
        is_retriable = 'true' in retriable_text or 'yes' in retriable_text
        
        # Parse confidence
        confidence_text = sections.get('confidence', '')
        try:
            import re
            conf_match = re.search(r'(\d+\.?\d*)', confidence_text)
            if conf_match:
                conf_val = float(conf_match.group(1))
                if conf_val > 1:
                    conf_val = conf_val / 100
                confidence = min(1.0, max(0.0, conf_val))
        except:
            pass
        
        # Ensure we have at least some content
        if not root_cause:
            root_cause = "Unable to determine root cause from investigation"
        if not recommendations:
            recommendations = ["Review the investigation details for more context"]
        
        return InvestigationResult(
            status=InvestigationStatus.IN_PROGRESS,  # Will be set by caller
            root_cause=root_cause[:500],  # Limit length
            details=details[:2000],
            evidence=evidence[:10],
            recommendations=recommendations[:5],
            is_retriable=is_retriable,
            confidence=confidence,
            tool_calls_made=0,  # Will be set by caller
            tokens_used=0,
            duration_seconds=0.0,
        )
    
    def get_tool_summary(self) -> str:
        """Get a summary of all tools called during investigation."""
        return self.executor.get_call_summary()
