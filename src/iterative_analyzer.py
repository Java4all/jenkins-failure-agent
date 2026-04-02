"""
Iterative Root Cause Analyzer

Agentic investigation loop that:
1. Smart extract error context from log
2. Ask AI to analyze
3. If AI needs more info (code, dependencies) → fetch it
4. Repeat until root cause is found
5. Optionally check shared library source code

Max cycles: 5 (configurable)
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

from .rc_finder import RootCauseFinder, RootCauseContext, ErrorType

logger = logging.getLogger(__name__)


class InvestigationAction(Enum):
    """What action the AI requests next."""
    DONE = "done"                      # Root cause found
    NEED_CODE = "need_code"            # Need shared library code
    NEED_MORE_LOG = "need_more_log"    # Need more log context
    NEED_DEPENDENCY = "need_dependency" # Need code of called function
    NEED_CONFIG = "need_config"        # Need config/env info
    UNKNOWN = "unknown"


@dataclass
class InvestigationStep:
    """One step in the investigation cycle."""
    cycle: int
    action: InvestigationAction
    context_provided: str          # What we gave to AI
    ai_response: str               # AI's analysis
    ai_request: Optional[str]      # What AI asked for next
    findings: Optional[str] = None # Partial findings from this step


@dataclass 
class InvestigationResult:
    """Final result of iterative investigation."""
    root_cause: str
    error_type: ErrorType
    confidence: float
    failed_stage: Optional[str] = None
    failed_method: Optional[str] = None
    code_location: Optional[str] = None  # e.g., "deployService.groovy:42"
    
    # Solution from AI Solution Finder
    fix_suggestion: Optional[str] = None
    fix_code: Optional[str] = None        # Actual code/command to fix
    fix_file: Optional[str] = None        # File to modify
    fix_steps: List[str] = field(default_factory=list)  # Step-by-step instructions
    
    # Investigation trace
    cycles_used: int = 0
    steps: List[InvestigationStep] = field(default_factory=list)
    code_analyzed: List[str] = field(default_factory=list)  # Functions/files analyzed


class IterativeRCAnalyzer:
    """
    Iterative Root Cause Analyzer with agentic investigation loop.
    
    Usage:
        analyzer = IterativeRCAnalyzer(ai_client, github_client)
        result = analyzer.analyze(log_content, build_info)
    """
    
    MAX_CYCLES = 5
    
    # AI prompt for analysis
    ANALYSIS_PROMPT = """You are analyzing a Jenkins build failure. Based on the context provided, determine:

1. Can you identify the ROOT CAUSE? If yes, explain it clearly.
2. If NOT, what additional information do you need?

CONTEXT PROVIDED:
{context}

Respond with JSON only:
{{
  "status": "found" | "need_more",
  "root_cause": "Clear explanation of root cause (if found)",
  "confidence": 0.0-1.0,
  "code_location": "file:line (if applicable)",
  "fix_suggestion": "How to fix it",
  "need_action": "need_code" | "need_dependency" | "need_more_log" | "need_config" | null,
  "need_target": "function name or file path or what you need",
  "reasoning": "Why you need this / how you determined root cause"
}}

IMPORTANT:
- If you see a function call in the error but don't have its source code, request it
- If the error mentions a config/parameter, and you don't see where it's set, request it
- Only say "found" if you're confident about the root cause"""

    CODE_ANALYSIS_PROMPT = """Analyze this code in context of the Jenkins build failure.

ERROR CONTEXT:
{error_context}

CODE ({code_path}):
```
{code}
```

Questions:
1. Does this code cause or contribute to the error?
2. Do you need to see any functions this code calls?
3. Can you identify the root cause now?

Respond with JSON:
{{
  "status": "found" | "need_more",
  "root_cause": "explanation (if found)",
  "confidence": 0.0-1.0,
  "code_location": "file:line",
  "fix_suggestion": "how to fix",
  "need_action": "need_dependency" | null,
  "need_target": "function name to fetch",
  "analysis": "what you found in this code"
}}"""

    # Solution Finder prompt - generates specific fix based on root cause
    SOLUTION_FINDER_PROMPT = """You are a DevOps expert. Given the ROOT CAUSE of a Jenkins build failure, provide a SPECIFIC, ACTIONABLE solution.

ROOT CAUSE:
{root_cause}

ERROR TYPE: {error_type}
FAILED STAGE: {failed_stage}
FAILED METHOD: {failed_method}
CODE LOCATION: {code_location}

ADDITIONAL CONTEXT:
{additional_context}

Generate a solution with:
1. WHAT to fix (specific file, config, parameter)
2. HOW to fix it (actual code/command)
3. Step-by-step instructions

Respond with JSON:
{{
  "fix_summary": "One sentence describing the fix",
  "fix_file": "File to modify (if applicable)",
  "fix_code": "Actual code snippet or command to run",
  "fix_steps": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ],
  "verification": "How to verify the fix worked",
  "need_more_info": null | "what additional info would help"
}}

RULES:
- Be SPECIFIC - use actual names/values from the root cause
- Provide REAL code/commands, not placeholders like <value>
- If it's a credential issue, show where to create it
- If it's a code issue, show the fixed code
- If it's a config issue, show the correct config"""

    def __init__(
        self, 
        ai_client,  # OpenAI-compatible client
        github_client=None,  # For fetching shared library code
        config: Optional[Dict[str, Any]] = None
    ):
        self.ai_client = ai_client
        self.github_client = github_client
        self.config = config or {}
        self.max_cycles = self.config.get('max_cycles', self.MAX_CYCLES)
        self.model = self.config.get('model', 'llama3:8b')
        
        # Library mappings: library_name -> repo_path
        self.library_mappings = self.config.get('library_mappings', {})
        
        # RC Finder for smart extraction
        self.rc_finder = RootCauseFinder(config)
    
    def analyze(
        self, 
        log: str, 
        build_info: Optional[Dict[str, Any]] = None,
        jenkinsfile_content: Optional[str] = None
    ) -> InvestigationResult:
        """
        Run iterative root cause analysis.
        
        Args:
            log: Jenkins console log
            build_info: Build metadata (job name, number, etc.)
            jenkinsfile_content: Optional Jenkinsfile content
            
        Returns:
            InvestigationResult with root cause and investigation trace
        """
        # Step 1: Smart extract initial context
        rc_context = self.rc_finder.find(log)
        
        result = InvestigationResult(
            root_cause="",
            error_type=rc_context.error_type,
            failed_stage=rc_context.failed_stage,
            failed_method=rc_context.failed_method,
            confidence=0.0,
        )
        
        # Build initial context for AI
        current_context = self._build_initial_context(rc_context, build_info, jenkinsfile_content)
        
        # Investigation loop
        for cycle in range(1, self.max_cycles + 1):
            logger.info(f"Investigation cycle {cycle}/{self.max_cycles}")
            
            # Ask AI to analyze
            ai_response = self._call_ai(self.ANALYSIS_PROMPT.format(context=current_context))
            parsed = self._parse_ai_response(ai_response)
            
            # Record step
            step = InvestigationStep(
                cycle=cycle,
                action=self._parse_action(parsed.get('need_action')),
                context_provided=current_context[:500] + "..." if len(current_context) > 500 else current_context,
                ai_response=ai_response,
                ai_request=parsed.get('need_target'),
                findings=parsed.get('reasoning'),
            )
            result.steps.append(step)
            result.cycles_used = cycle
            
            # Check if root cause found
            if parsed.get('status') == 'found' and parsed.get('confidence', 0) >= 0.7:
                result.root_cause = parsed.get('root_cause', '')
                result.confidence = parsed.get('confidence', 0.8)
                result.code_location = parsed.get('code_location')
                result.fix_suggestion = parsed.get('fix_suggestion')
                logger.info(f"Root cause found in cycle {cycle}")
                break
            
            # Determine next action
            action = self._parse_action(parsed.get('need_action'))
            target = parsed.get('need_target', '')
            
            if action == InvestigationAction.DONE or not target:
                # AI says done or no specific request
                result.root_cause = parsed.get('root_cause', 'Unable to determine root cause')
                result.confidence = parsed.get('confidence', 0.5)
                break
            
            # Fetch additional information
            additional_context = self._fetch_additional_info(action, target, rc_context, log)
            
            if additional_context:
                current_context = self._merge_context(current_context, additional_context, action, target)
                if action in (InvestigationAction.NEED_CODE, InvestigationAction.NEED_DEPENDENCY):
                    result.code_analyzed.append(target)
            else:
                # Couldn't fetch what AI asked for
                logger.warning(f"Could not fetch {action.value}: {target}")
                current_context += f"\n\n[NOTE: Could not fetch {target}. Please analyze with available information.]"
        
        # If no root cause after max cycles
        if not result.root_cause:
            result.root_cause = "Investigation inconclusive after maximum cycles"
            result.confidence = 0.3
        
        # =====================================================
        # SOLUTION FINDER: Generate specific fix for root cause
        # =====================================================
        if result.root_cause and result.confidence >= 0.5:
            logger.info("Running Solution Finder...")
            solution = self._find_solution(result, rc_context, current_context)
            
            if solution:
                result.fix_suggestion = solution.get('fix_summary', result.fix_suggestion)
                result.fix_code = solution.get('fix_code')
                result.fix_file = solution.get('fix_file')
                result.fix_steps = solution.get('fix_steps', [])
                
                # If solution finder needs more info, try to fetch it
                need_more = solution.get('need_more_info')
                if need_more and result.cycles_used < self.max_cycles:
                    logger.info(f"Solution finder needs more info: {need_more}")
                    more_context = self._fetch_solution_context(need_more, rc_context, log)
                    if more_context:
                        # Re-run solution finder with more context
                        enhanced_solution = self._find_solution(
                            result, rc_context, 
                            current_context + f"\n\nADDITIONAL INFO:\n{more_context}"
                        )
                        if enhanced_solution:
                            result.fix_suggestion = enhanced_solution.get('fix_summary', result.fix_suggestion)
                            result.fix_code = enhanced_solution.get('fix_code', result.fix_code)
                            result.fix_file = enhanced_solution.get('fix_file', result.fix_file)
                            result.fix_steps = enhanced_solution.get('fix_steps', result.fix_steps)
        
        return result
    
    def _find_solution(
        self, 
        result: InvestigationResult,
        rc_context: RootCauseContext,
        investigation_context: str
    ) -> Optional[Dict[str, Any]]:
        """
        Use AI to generate a specific solution for the root cause.
        """
        # Build additional context from investigation
        additional_context_parts = []
        
        # Include error context
        if rc_context.context_before:
            additional_context_parts.append("Commands before error:")
            additional_context_parts.extend(rc_context.context_before[-10:])
        
        # Include related lines (commands that used the same identifiers)
        if rc_context.related_lines:
            additional_context_parts.append("\nRelated commands:")
            for line_num, line in rc_context.related_lines[:5]:
                additional_context_parts.append(f"  [{line_num}] {line}")
        
        # Include code analyzed
        if result.code_analyzed:
            additional_context_parts.append(f"\nCode analyzed: {', '.join(result.code_analyzed)}")
        
        prompt = self.SOLUTION_FINDER_PROMPT.format(
            root_cause=result.root_cause,
            error_type=result.error_type.value,
            failed_stage=result.failed_stage or "unknown",
            failed_method=result.failed_method or "unknown",
            code_location=result.code_location or "unknown",
            additional_context='\n'.join(additional_context_parts) if additional_context_parts else "None",
        )
        
        response = self._call_ai(prompt)
        return self._parse_ai_response(response)
    
    def _fetch_solution_context(
        self, 
        need_info: str, 
        rc_context: RootCauseContext,
        log: str
    ) -> Optional[str]:
        """Fetch additional context requested by solution finder."""
        # Try to find the requested info in the log
        lines = log.split('\n')
        matching_lines = []
        
        # Search for lines containing the requested info
        keywords = need_info.lower().split()
        for i, line in enumerate(lines):
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords if len(kw) > 3):
                # Include context around matching line
                start = max(0, i - 3)
                end = min(len(lines), i + 3)
                matching_lines.extend(lines[start:end])
                matching_lines.append("---")
        
        if matching_lines:
            return '\n'.join(matching_lines[:50])  # Limit context size
        
        # Try fetching from GitHub if it looks like a code reference
        if self.github_client and ('function' in need_info.lower() or 'method' in need_info.lower() or '.groovy' in need_info):
            # Extract potential function/file name
            words = need_info.split()
            for word in words:
                if len(word) > 3 and not word.lower() in ('function', 'method', 'code', 'file', 'the', 'for'):
                    code = self._fetch_code(word.strip('().,'))
                    if code:
                        return code
        
        return None
    
    def _build_initial_context(
        self, 
        rc_context: RootCauseContext,
        build_info: Optional[Dict[str, Any]],
        jenkinsfile_content: Optional[str]
    ) -> str:
        """Build initial context for AI analysis."""
        parts = []
        
        # Build info
        if build_info:
            parts.append(f"Job: {build_info.get('job_name', 'unknown')} #{build_info.get('build_number', '?')}")
        
        # RC Finder context
        parts.append(rc_context.get_ai_prompt_context())
        
        # Jenkinsfile if available
        if jenkinsfile_content:
            # Extract relevant portion (stage that failed)
            relevant_jenkinsfile = self._extract_relevant_jenkinsfile(
                jenkinsfile_content, 
                rc_context.failed_stage
            )
            if relevant_jenkinsfile:
                parts.append("\n" + "="*50)
                parts.append("JENKINSFILE (relevant section):")
                parts.append("="*50)
                parts.append(relevant_jenkinsfile)
        
        return "\n".join(parts)
    
    def _extract_relevant_jenkinsfile(self, content: str, stage_name: Optional[str]) -> Optional[str]:
        """Extract relevant portion of Jenkinsfile around the failed stage."""
        if not stage_name:
            # Return last 50 lines
            lines = content.split('\n')
            return '\n'.join(lines[-50:])
        
        # Find the stage in Jenkinsfile
        lines = content.split('\n')
        stage_pattern = re.compile(rf"stage\s*\(\s*['\"]?{re.escape(stage_name)}['\"]?\s*\)", re.IGNORECASE)
        
        for i, line in enumerate(lines):
            if stage_pattern.search(line):
                # Return 30 lines around the stage
                start = max(0, i - 5)
                end = min(len(lines), i + 30)
                return '\n'.join(lines[start:end])
        
        return None
    
    def _call_ai(self, prompt: str) -> str:
        """Call AI model."""
        try:
            response = self.ai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a Jenkins CI/CD expert analyzing build failures. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1500,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"AI call failed: {e}")
            return json.dumps({"status": "error", "root_cause": f"AI analysis failed: {e}"})
    
    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
        """Parse AI response JSON."""
        try:
            # Clean response
            response = response.strip()
            if response.startswith('```'):
                response = re.sub(r'^```\w*\n?', '', response)
                response = re.sub(r'\n?```$', '', response)
            
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
            return {"status": "error", "root_cause": "Could not parse AI response"}
    
    def _parse_action(self, action_str: Optional[str]) -> InvestigationAction:
        """Parse action string to enum."""
        if not action_str:
            return InvestigationAction.DONE
        
        action_map = {
            'need_code': InvestigationAction.NEED_CODE,
            'need_dependency': InvestigationAction.NEED_DEPENDENCY,
            'need_more_log': InvestigationAction.NEED_MORE_LOG,
            'need_config': InvestigationAction.NEED_CONFIG,
            'done': InvestigationAction.DONE,
        }
        return action_map.get(action_str.lower(), InvestigationAction.UNKNOWN)
    
    def _fetch_additional_info(
        self, 
        action: InvestigationAction, 
        target: str,
        rc_context: RootCauseContext,
        log: str
    ) -> Optional[str]:
        """Fetch additional information based on AI request."""
        
        if action == InvestigationAction.NEED_CODE:
            return self._fetch_code(target)
        
        elif action == InvestigationAction.NEED_DEPENDENCY:
            return self._fetch_code(target)
        
        elif action == InvestigationAction.NEED_MORE_LOG:
            return self._fetch_more_log(target, log)
        
        elif action == InvestigationAction.NEED_CONFIG:
            return self._fetch_config_info(target, log)
        
        return None
    
    def _fetch_code(self, target: str) -> Optional[str]:
        """Fetch code from shared library via GitHub."""
        if not self.github_client:
            logger.warning("No GitHub client configured, cannot fetch code")
            return None
        
        # Parse target: could be "functionName" or "path/to/file.groovy"
        # Try to find in library mappings
        
        for library_name, repo_path in self.library_mappings.items():
            try:
                # Common shared library structure: vars/functionName.groovy
                if '/' not in target and not target.endswith('.groovy'):
                    file_path = f"vars/{target}.groovy"
                else:
                    file_path = target
                
                content = self.github_client.get_file_content(repo_path, file_path)
                if content:
                    return f"// Source: {repo_path}/{file_path}\n{content}"
            except Exception as e:
                logger.debug(f"Could not fetch {target} from {repo_path}: {e}")
                continue
        
        return None
    
    def _fetch_more_log(self, target: str, log: str) -> Optional[str]:
        """Fetch more log context around a specific pattern."""
        lines = log.split('\n')
        
        # Find lines matching target
        for i, line in enumerate(lines):
            if target.lower() in line.lower():
                # Return 20 lines around it
                start = max(0, i - 10)
                end = min(len(lines), i + 10)
                return '\n'.join(lines[start:end])
        
        return None
    
    def _fetch_config_info(self, target: str, log: str) -> Optional[str]:
        """Try to find config/env info in the log."""
        lines = log.split('\n')
        config_lines = []
        
        # Look for lines that might set the target config
        patterns = [
            rf'{re.escape(target)}\s*=',
            rf'--{re.escape(target)}',
            rf'-D{re.escape(target)}',
            rf'export\s+{re.escape(target)}',
        ]
        
        for line in lines:
            for pattern in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    config_lines.append(line)
        
        return '\n'.join(config_lines) if config_lines else None
    
    def _merge_context(
        self, 
        current: str, 
        additional: str, 
        action: InvestigationAction,
        target: str
    ) -> str:
        """Merge additional context into current context."""
        section_header = {
            InvestigationAction.NEED_CODE: f"CODE: {target}",
            InvestigationAction.NEED_DEPENDENCY: f"DEPENDENCY CODE: {target}",
            InvestigationAction.NEED_MORE_LOG: f"ADDITIONAL LOG: {target}",
            InvestigationAction.NEED_CONFIG: f"CONFIG INFO: {target}",
        }
        
        header = section_header.get(action, f"ADDITIONAL INFO: {target}")
        
        return f"{current}\n\n{'='*50}\n{header}\n{'='*50}\n{additional}"


def create_iterative_analyzer(
    ai_base_url: str,
    ai_model: str,
    ai_api_key: str = "ollama",
    github_config: Optional[Dict] = None,
    library_mappings: Optional[Dict[str, str]] = None,
) -> IterativeRCAnalyzer:
    """
    Factory function to create IterativeRCAnalyzer with configured clients.
    
    Args:
        ai_base_url: OpenAI-compatible API URL
        ai_model: Model name
        ai_api_key: API key
        github_config: GitHub client config (base_url, token)
        library_mappings: Map of library names to repo paths
        
    Returns:
        Configured IterativeRCAnalyzer
    """
    from openai import OpenAI
    
    ai_client = OpenAI(
        base_url=ai_base_url,
        api_key=ai_api_key,
    )
    
    github_client = None
    if github_config:
        from .github_client import GitHubClient, GitHubConfig
        github_client = GitHubClient(GitHubConfig(
            base_url=github_config.get('base_url', 'https://api.github.com'),
            token=github_config.get('token', ''),
            verify_ssl=github_config.get('verify_ssl', True),
        ))
    
    return IterativeRCAnalyzer(
        ai_client=ai_client,
        github_client=github_client,
        config={
            'model': ai_model,
            'library_mappings': library_mappings or {},
        }
    )
