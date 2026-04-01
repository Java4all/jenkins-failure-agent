"""
Jenkins MCP tools for build investigation.

These tools allow the LLM to query Jenkins for build information,
logs, stages, and test results during agentic investigation.
"""

import logging
from typing import Optional, List, Dict, Any

from .registry import ToolRegistry, ToolCategory, ToolDefinition, ToolParameter

logger = logging.getLogger("jenkins-agent.mcp.jenkins_tools")


def register_jenkins_tools(registry: ToolRegistry):
    """Register all Jenkins tools with the registry."""
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get basic information about a Jenkins build including status, duration, and parameters.",
    )
    def get_build_info(job: str, build: int) -> dict:
        """
        Get basic information about a Jenkins build.
        
        Args:
            job: The Jenkins job name (e.g., 'my-project' or 'folder/my-project')
            build: The build number
            
        Returns:
            Build info including status, duration, parameters, and cause.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return {"error": "Jenkins client not configured"}
        
        try:
            info = context.get_build_info(job, build)
            return {
                "job": info.job,
                "build_number": info.build_number,
                "status": info.result,
                "building": info.building,
                "duration_ms": info.duration,
                "timestamp": info.timestamp,
                "url": info.url,
                "parameters": info.parameters,
                "cause": info.cause,
            }
        except Exception as e:
            return {"error": str(e)}
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get console output from a Jenkins build. Use max_lines to limit output size.",
    )
    def get_console_log(job: str, build: int, max_lines: int = 500, from_end: bool = True) -> str:
        """
        Get console output from a Jenkins build.
        
        Args:
            job: The Jenkins job name
            build: The build number
            max_lines: Maximum number of lines to return (default 500)
            from_end: If True, get last N lines; if False, get first N lines
            
        Returns:
            Console log text, truncated to max_lines.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return "Error: Jenkins client not configured"
        
        try:
            log = context.get_console_log(job, build)
            lines = log.split('\n')
            
            if len(lines) > max_lines:
                if from_end:
                    lines = lines[-max_lines:]
                    return f"... [showing last {max_lines} lines]\n" + '\n'.join(lines)
                else:
                    lines = lines[:max_lines]
                    return '\n'.join(lines) + f"\n... [truncated, showing first {max_lines} lines]"
            
            return log
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Search the console log for lines matching a pattern.",
    )
    def search_console_log(job: str, build: int, pattern: str, context_lines: int = 3) -> str:
        """
        Search the console log for lines matching a pattern.
        
        Args:
            job: The Jenkins job name
            build: The build number  
            pattern: Text pattern to search for (case-insensitive)
            context_lines: Number of lines to show before and after each match
            
        Returns:
            Matching lines with surrounding context.
        """
        import re
        
        context_obj = registry.get_context('jenkins_client')
        if not context_obj:
            return "Error: Jenkins client not configured"
        
        try:
            log = context_obj.get_console_log(job, build)
            lines = log.split('\n')
            
            matches = []
            pattern_re = re.compile(pattern, re.IGNORECASE)
            
            for i, line in enumerate(lines):
                if pattern_re.search(line):
                    start = max(0, i - context_lines)
                    end = min(len(lines), i + context_lines + 1)
                    
                    snippet = []
                    for j in range(start, end):
                        prefix = ">>> " if j == i else "    "
                        snippet.append(f"{prefix}[{j+1}] {lines[j]}")
                    
                    matches.append('\n'.join(snippet))
            
            if not matches:
                return f"No matches found for pattern: {pattern}"
            
            return f"Found {len(matches)} matches:\n\n" + "\n\n---\n\n".join(matches[:10])
        
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get pipeline stages and their status for a Jenkins build.",
    )
    def get_pipeline_stages(job: str, build: int) -> list:
        """
        Get pipeline stages and their execution status.
        
        Args:
            job: The Jenkins job name
            build: The build number
            
        Returns:
            List of stages with name, status, and duration.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return [{"error": "Jenkins client not configured"}]
        
        try:
            stages = context.get_pipeline_stages(job, build)
            return [
                {
                    "name": s.get("name"),
                    "status": s.get("status"),
                    "duration_ms": s.get("durationMillis"),
                }
                for s in stages
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get the log output for a specific pipeline stage.",
    )
    def get_stage_log(job: str, build: int, stage_name: str) -> str:
        """
        Get the console log for a specific pipeline stage.
        
        Args:
            job: The Jenkins job name
            build: The build number
            stage_name: Name of the stage to get logs for
            
        Returns:
            Console output for that stage only.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return "Error: Jenkins client not configured"
        
        try:
            log = context.get_stage_log(job, build, stage_name)
            if log:
                return log
            return f"No log found for stage: {stage_name}"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get test results from a Jenkins build including failures and errors.",
    )
    def get_test_results(job: str, build: int) -> dict:
        """
        Get test results from a Jenkins build.
        
        Args:
            job: The Jenkins job name
            build: The build number
            
        Returns:
            Test summary with pass/fail counts and failure details.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return {"error": "Jenkins client not configured"}
        
        try:
            results = context.get_test_results(job, build)
            if not results:
                return {"message": "No test results found"}
            
            return {
                "total": results.total,
                "passed": results.passed,
                "failed": results.failed,
                "skipped": results.skipped,
                "failures": [
                    {
                        "class": f.test_class,
                        "name": f.name,
                        "message": f.message[:500] if f.message else None,
                        "stack_trace": f.stack_trace[:1000] if f.stack_trace else None,
                    }
                    for f in (results.failures or [])[:10]  # Limit to 10 failures
                ],
            }
        except Exception as e:
            return {"error": str(e)}
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get the Jenkinsfile content from a job's configuration.",
    )
    def get_jenkinsfile_from_job(job: str) -> str:
        """
        Get the Jenkinsfile content from a job's configuration.
        
        Args:
            job: The Jenkins job name
            
        Returns:
            The Jenkinsfile content if available.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return "Error: Jenkins client not configured"
        
        try:
            config = context.get_job_config(job)
            if config:
                # Try to extract script from different locations
                import re
                
                # Pipeline script in job config
                script_match = re.search(r'<script>(.*?)</script>', config, re.DOTALL)
                if script_match:
                    return script_match.group(1).strip()
                
                # SCM-based pipeline
                scm_match = re.search(r'<scriptPath>(.*?)</scriptPath>', config)
                if scm_match:
                    return f"Jenkinsfile loaded from SCM: {scm_match.group(1)}"
                
                return "Could not extract Jenkinsfile from job config"
            return "Job config not found"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get artifacts from a Jenkins build.",
    )
    def list_build_artifacts(job: str, build: int) -> list:
        """
        List artifacts from a Jenkins build.
        
        Args:
            job: The Jenkins job name
            build: The build number
            
        Returns:
            List of artifact names and paths.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return [{"error": "Jenkins client not configured"}]
        
        try:
            artifacts = context.get_artifacts(job, build)
            return [
                {
                    "name": a.get("fileName"),
                    "path": a.get("relativePath"),
                    "size": a.get("size"),
                }
                for a in artifacts
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.JENKINS,
        description="Get environment variables that were set during a build.",
    )
    def get_build_environment(job: str, build: int) -> dict:
        """
        Get environment variables from a Jenkins build.
        
        Args:
            job: The Jenkins job name
            build: The build number
            
        Returns:
            Dictionary of environment variables.
        """
        context = registry.get_context('jenkins_client')
        if not context:
            return {"error": "Jenkins client not configured"}
        
        try:
            env = context.get_build_environment(job, build)
            # Filter out sensitive values
            safe_env = {}
            sensitive_patterns = ['password', 'secret', 'token', 'key', 'credential']
            
            for k, v in env.items():
                if any(p in k.lower() for p in sensitive_patterns):
                    safe_env[k] = "[REDACTED]"
                else:
                    safe_env[k] = v
            
            return safe_env
        except Exception as e:
            return {"error": str(e)}
    
    logger.info(f"Registered {len(registry.get_tools_by_category(ToolCategory.JENKINS))} Jenkins tools")
