"""
Investigation MCP tools for code analysis and error tracing.

These tools provide higher-level investigation capabilities that help
the LLM trace errors through call chains and analyze code patterns.
"""

import re
import logging
from typing import Optional, List, Dict, Any

from .registry import ToolRegistry, ToolCategory

logger = logging.getLogger("jenkins-agent.mcp.investigation_tools")


def register_investigation_tools(registry: ToolRegistry):
    """Register all investigation tools."""
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Parse @Library declarations from a Jenkinsfile to find which libraries are used.",
    )
    def parse_library_declarations(jenkinsfile_content: str) -> list:
        """
        Parse @Library declarations from Jenkinsfile content.
        
        Args:
            jenkinsfile_content: The Jenkinsfile content as a string
            
        Returns:
            List of libraries with name and version/branch.
        """
        libraries = []
        
        # Pattern: @Library('name') or @Library('name@version') or @Library(['lib1', 'lib2'])
        patterns = [
            r"@Library\s*\(\s*'([^']+)'\s*\)",
            r'@Library\s*\(\s*"([^"]+)"\s*\)',
            r"@Library\s*\(\s*\[(.*?)\]\s*\)",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, jenkinsfile_content, re.MULTILINE)
            for match in matches:
                if '[' in pattern:
                    # Handle array format
                    lib_strings = re.findall(r"['\"]([^'\"]+)['\"]", match)
                    for lib in lib_strings:
                        name, version = _parse_lib_string(lib)
                        libraries.append({"name": name, "version": version})
                else:
                    name, version = _parse_lib_string(match)
                    libraries.append({"name": name, "version": version})
        
        return libraries
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Extract library function calls from Jenkinsfile or Groovy code.",
    )
    def find_library_calls(code: str) -> list:
        """
        Find calls to shared library functions in code.
        
        Args:
            code: Groovy/Jenkinsfile code
            
        Returns:
            List of function calls that likely come from shared libraries.
        """
        calls = []
        
        # Find function calls that look like library calls
        # Pattern: functionName(...) or functionName { ... }
        # Skip common Jenkins built-ins
        builtins = {
            'sh', 'bat', 'echo', 'node', 'stage', 'parallel', 'script', 'dir',
            'checkout', 'git', 'input', 'timeout', 'retry', 'sleep', 'error',
            'archiveArtifacts', 'stash', 'unstash', 'deleteDir', 'fileExists',
            'readFile', 'writeFile', 'pwd', 'isUnix', 'tool', 'withEnv',
            'withCredentials', 'sshagent', 'wrap', 'timestamps', 'ansiColor',
            'if', 'else', 'for', 'while', 'try', 'catch', 'finally', 'def',
            'return', 'new', 'import', 'package', 'class', 'interface',
        }
        
        # Find function calls
        pattern = r'\b([a-z][a-zA-Z0-9_]*)\s*\('
        matches = re.findall(pattern, code)
        
        for func in matches:
            if func not in builtins and func not in calls:
                calls.append(func)
        
        # Find closure-style calls: functionName { }
        pattern = r'\b([a-z][a-zA-Z0-9_]*)\s*\{'
        matches = re.findall(pattern, code)
        
        for func in matches:
            if func not in builtins and func not in calls:
                calls.append(func)
        
        return calls
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Parse a Groovy stack trace to extract the call chain.",
    )
    def parse_stack_trace(stack_trace: str) -> list:
        """
        Parse a Groovy/Java stack trace to extract the call chain.
        
        Args:
            stack_trace: Stack trace text
            
        Returns:
            List of stack frames with file, line, and method info.
        """
        frames = []
        
        # Java/Groovy stack trace pattern
        pattern = r'at\s+([^\(]+)\(([^:]+):?(\d+)?\)'
        
        for match in re.finditer(pattern, stack_trace):
            method = match.group(1)
            file = match.group(2)
            line = match.group(3)
            
            # Filter out Jenkins/CPS internal frames
            if any(skip in method for skip in [
                'WorkflowScript', 'CpsThread', 'CpsVmThread',
                'groovy.lang', 'java.lang', 'sun.reflect',
                'org.jenkinsci.plugins.workflow.cps',
                'com.cloudbees.groovy.cps',
            ]):
                continue
            
            frames.append({
                "method": method,
                "file": file,
                "line": int(line) if line else None,
                "is_user_code": not any(skip in method for skip in [
                    'org.', 'com.cloudbees', 'hudson.', 'jenkins.'
                ])
            })
        
        return frames
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Extract error messages and exceptions from log text.",
    )
    def extract_errors(log_text: str) -> list:
        """
        Extract error messages and exceptions from log text.
        
        Args:
            log_text: Console log text
            
        Returns:
            List of errors with type, message, and context.
        """
        errors = []
        lines = log_text.split('\n')
        
        # Patterns for different error types
        error_patterns = [
            # Groovy/Java exceptions
            (r'(\w+(?:\.\w+)*Exception):\s*(.+)', 'exception'),
            (r'(\w+(?:\.\w+)*Error):\s*(.+)', 'error'),
            # Jenkins errors
            (r'\[ERROR\]\s*(.+)', 'jenkins_error'),
            (r'ERROR:\s*(.+)', 'error_line'),
            # Build tool errors
            (r'FAILURE:\s*(.+)', 'build_failure'),
            (r'BUILD FAILED', 'build_failed'),
            # Script errors
            (r'groovy\.lang\.MissingMethodException:\s*(.+)', 'missing_method'),
            (r'groovy\.lang\.MissingPropertyException:\s*(.+)', 'missing_property'),
        ]
        
        for i, line in enumerate(lines):
            for pattern, error_type in error_patterns:
                match = re.search(pattern, line)
                if match:
                    # Get context
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    context = '\n'.join(lines[start:end])
                    
                    errors.append({
                        "type": error_type,
                        "message": match.group(0),
                        "line_number": i + 1,
                        "context": context,
                    })
                    break  # Only match one pattern per line
        
        return errors[:20]  # Limit results
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Analyze a MissingMethodException to determine the expected method signature.",
    )
    def analyze_missing_method(error_message: str) -> dict:
        """
        Analyze a MissingMethodException error message.
        
        Args:
            error_message: The exception message
            
        Returns:
            Analysis of what method was expected.
        """
        result = {
            "called_method": None,
            "called_on_class": None,
            "argument_types": [],
            "suggestions": [],
        }
        
        # Pattern: No signature of method: ClassName.methodName() is applicable for argument types: (Type1, Type2)
        pattern = r"No signature of method:\s*(\S+)\.(\w+)\(\)\s*is applicable for argument types:\s*\(([^)]*)\)"
        match = re.search(pattern, error_message)
        
        if match:
            result["called_on_class"] = match.group(1)
            result["called_method"] = match.group(2)
            args = match.group(3)
            result["argument_types"] = [a.strip() for a in args.split(',') if a.strip()]
            
            result["suggestions"] = [
                f"Check the {result['called_method']} method signature in {result['called_on_class']}",
                f"The method was called with types: {result['argument_types']}",
                "Verify parameter names and types match",
            ]
        
        # Pattern: No such property: propertyName for class: ClassName
        pattern = r"No such property:\s*(\w+)\s*for class:\s*(\S+)"
        match = re.search(pattern, error_message)
        
        if match:
            result["called_method"] = match.group(1)
            result["called_on_class"] = match.group(2)
            result["suggestions"] = [
                f"Property '{result['called_method']}' does not exist on {result['called_on_class']}",
                "Check spelling of the property name",
                "Check if the property exists in the expected Map/Object",
            ]
        
        return result
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Find credential references in code.",
    )
    def find_credential_references(code: str) -> list:
        """
        Find credential references in Jenkinsfile or Groovy code.
        
        Args:
            code: The code to analyze
            
        Returns:
            List of credential IDs and how they're used.
        """
        credentials = []
        
        # withCredentials patterns
        patterns = [
            r"usernamePassword\s*\([^)]*credentialsId:\s*['\"]([^'\"]+)['\"]",
            r"string\s*\([^)]*credentialsId:\s*['\"]([^'\"]+)['\"]",
            r"sshUserPrivateKey\s*\([^)]*credentialsId:\s*['\"]([^'\"]+)['\"]",
            r"usernameColonPassword\s*\([^)]*credentialsId:\s*['\"]([^'\"]+)['\"]",
            r"file\s*\([^)]*credentialsId:\s*['\"]([^'\"]+)['\"]",
            r"credentials\s*\(['\"]([^'\"]+)['\"]",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, code)
            for cred_id in matches:
                if cred_id not in [c['id'] for c in credentials]:
                    credentials.append({
                        "id": cred_id,
                        "pattern": pattern.split('\\')[0],
                    })
        
        return credentials
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Trace a function call through library code to find the root implementation.",
    )
    def trace_call_chain(
        initial_function: str,
        code_snippets: Dict[str, str]
    ) -> list:
        """
        Trace a function call through multiple code files.
        
        Args:
            initial_function: Starting function name
            code_snippets: Dict mapping file paths to their content
            
        Returns:
            Call chain showing how functions call each other.
        """
        chain = []
        visited = set()
        
        def find_calls_in_code(func_name: str, code: str) -> List[str]:
            """Find what functions this code calls."""
            # Simple pattern - find function calls
            pattern = r'\b([a-z][a-zA-Z0-9_]*)\s*\('
            matches = re.findall(pattern, code)
            return list(set(matches))
        
        def trace(func: str, depth: int = 0):
            if depth > 10 or func in visited:
                return
            visited.add(func)
            
            # Look for this function in all code snippets
            for file_path, code in code_snippets.items():
                # Check if function is defined here
                def_pattern = rf'def\s+{func}\s*\('
                if re.search(def_pattern, code):
                    # Extract function body (simplified)
                    called_funcs = find_calls_in_code(func, code)
                    
                    chain.append({
                        "function": func,
                        "file": file_path,
                        "depth": depth,
                        "calls": called_funcs[:10],
                    })
                    
                    # Recursively trace called functions
                    for called in called_funcs[:5]:
                        trace(called, depth + 1)
                    break
        
        trace(initial_function)
        return chain
    
    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Compare expected vs actual function parameters.",
    )
    def compare_parameters(
        expected_signature: str,
        actual_call: str
    ) -> dict:
        """
        Compare expected function signature with actual call.
        
        Args:
            expected_signature: Function definition like 'def call(Map config)'
            actual_call: Function call like 'deployApp(env: "prod", version: "1.0")'
            
        Returns:
            Comparison showing mismatches.
        """
        result = {
            "expected_params": [],
            "actual_params": [],
            "missing": [],
            "extra": [],
            "type_mismatches": [],
        }
        
        # Parse expected signature
        sig_match = re.search(r'\(([^)]*)\)', expected_signature)
        if sig_match:
            params = sig_match.group(1)
            for param in params.split(','):
                param = param.strip()
                if param:
                    # Handle "Type name" or "Type name = default"
                    parts = param.split()
                    if len(parts) >= 2:
                        result["expected_params"].append({
                            "type": parts[0],
                            "name": parts[1].rstrip('=').strip(),
                            "has_default": '=' in param,
                        })
                    elif len(parts) == 1:
                        result["expected_params"].append({
                            "type": "Object",
                            "name": parts[0],
                            "has_default": False,
                        })
        
        # Parse actual call
        call_match = re.search(r'\(([^)]*)\)', actual_call)
        if call_match:
            args = call_match.group(1)
            # Handle named parameters: key: value
            named_pattern = r'(\w+)\s*:\s*'
            named_params = re.findall(named_pattern, args)
            result["actual_params"] = named_params
        
        # Find mismatches
        expected_names = {p["name"] for p in result["expected_params"]}
        actual_names = set(result["actual_params"])
        
        required = {p["name"] for p in result["expected_params"] if not p["has_default"]}
        result["missing"] = list(required - actual_names)
        result["extra"] = list(actual_names - expected_names)
        
        return result

    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Post analysis results to a PR comment.",
    )
    def post_pr_comment(
        pr_url: str,
        analysis_summary: str,
        root_cause: str,
        recommendations: List[str]
    ) -> str:
        """
        Post investigation results as a PR comment.
        
        Args:
            pr_url: The PR URL (GitHub or GitLab)
            analysis_summary: Brief summary of the analysis
            root_cause: Identified root cause
            recommendations: List of recommended fixes
            
        Returns:
            Success/failure message.
        """
        scm_client = registry.get_context('scm_client')
        if not scm_client:
            return "Error: SCM client not configured"
        
        try:
            pr_info = scm_client.extract_pr_info_from_url(pr_url)
            if not pr_info:
                return f"Error: Could not parse PR URL: {pr_url}"
            
            # Format comment
            comment = f"""## 🔍 AI Failure Investigation

### Summary
{analysis_summary}

### Root Cause
{root_cause}

### Recommendations
"""
            for i, rec in enumerate(recommendations, 1):
                comment += f"{i}. {rec}\n"
            
            comment += "\n---\n*Analyzed by Jenkins Failure Analysis Agent (MCP Investigation)*"
            
            success = scm_client.update_or_create_comment(pr_info, comment)
            
            if success:
                return f"Successfully posted analysis to {pr_url}"
            return "Failed to post comment"
            
        except Exception as e:
            return f"Error posting comment: {str(e)}"

    @registry.tool(
        category=ToolCategory.INVESTIGATION,
        description="Update Jenkins build description with investigation results.",
    )
    def update_build_description(
        job: str,
        build: int,
        root_cause: str,
        is_retriable: bool
    ) -> str:
        """
        Update Jenkins build description with investigation results.
        
        Args:
            job: Jenkins job name
            build: Build number
            root_cause: Root cause summary
            is_retriable: Whether the failure is retriable
            
        Returns:
            Success/failure message.
        """
        jenkins_client = registry.get_context('jenkins_client')
        if not jenkins_client:
            return "Error: Jenkins client not configured"
        
        try:
            description = jenkins_client.format_analysis_description(
                root_cause=root_cause,
                category="INVESTIGATED",
                tier="investigated",
                confidence=0.9,
                is_retriable=is_retriable,
                recommendations=[],
            )
            
            success = jenkins_client.set_build_description(job, build, description)
            
            if success:
                return f"Successfully updated build description for {job}#{build}"
            return "Failed to update build description"
            
        except Exception as e:
            return f"Error: {str(e)}"
    
    logger.info(f"Registered {len(registry.get_tools_by_category(ToolCategory.INVESTIGATION))} investigation tools")


def _parse_lib_string(lib_str: str) -> tuple:
    """Parse 'name@version' into (name, version)."""
    if '@' in lib_str:
        parts = lib_str.split('@', 1)
        return parts[0], parts[1]
    return lib_str, "main"
