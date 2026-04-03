"""
AI analyzer for root cause analysis using a private AI model.
Supports any OpenAI-compatible API (Ollama, vLLM, LocalAI, etc.)
"""

import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from enum import Enum
from openai import OpenAI

from .config import AIConfig
from .log_parser import ParsedLog, FailureCategory
from .git_analyzer import GitAnalysis
from .jenkins_client import BuildInfo, TestResult
from .groovy_analyzer import GroovyAnalyzer, GroovyAnalysis, GroovyFailureType
from .config_analyzer import ConfigurationAnalyzer, ConfigurationAnalysis, ConfigFailureType


class FailureTier(str, Enum):
    """High-level failure classification (3-tier model)."""
    CONFIGURATION = "configuration"      # End-user configuration mismatch
    PIPELINE_MISUSE = "pipeline_misuse"  # Pipeline/Jenkinsfile misuse
    EXTERNAL_SYSTEM = "external_system"  # External system failure
    UNKNOWN = "unknown"


# Mapping from detailed categories to 3-tier model
CATEGORY_TO_TIER = {
    # Configuration tier
    "CREDENTIAL_ERROR": FailureTier.CONFIGURATION,
    "CONFIGURATION": FailureTier.CONFIGURATION,
    "MISSING_PARAMETER": FailureTier.CONFIGURATION,
    "AGENT_ERROR": FailureTier.CONFIGURATION,
    
    # Pipeline misuse tier
    "GROOVY_LIBRARY": FailureTier.PIPELINE_MISUSE,
    "GROOVY_CPS": FailureTier.PIPELINE_MISUSE,
    "GROOVY_SANDBOX": FailureTier.PIPELINE_MISUSE,
    "GROOVY_SERIALIZATION": FailureTier.PIPELINE_MISUSE,
    "PLUGIN_ERROR": FailureTier.PIPELINE_MISUSE,
    "COMPILATION_ERROR": FailureTier.PIPELINE_MISUSE,
    
    # External system tier
    "NETWORK": FailureTier.EXTERNAL_SYSTEM,
    "TIMEOUT": FailureTier.EXTERNAL_SYSTEM,
    "INFRASTRUCTURE": FailureTier.EXTERNAL_SYSTEM,
    "RESOURCE": FailureTier.EXTERNAL_SYSTEM,
    "DEPENDENCY": FailureTier.EXTERNAL_SYSTEM,
    "TEST_FAILURE": FailureTier.EXTERNAL_SYSTEM,  # Tests fail due to code, not pipeline
    
    # Unknown
    "UNKNOWN": FailureTier.UNKNOWN,
}


@dataclass
class RetryAssessment:
    """Assessment of whether the build is safe to retry."""
    is_retriable: bool
    confidence: float  # 0.0-1.0
    reason: str
    recommended_wait_seconds: int = 0  # For transient failures
    max_retries: int = 0  # Suggested retry limit


@dataclass
class Recommendation:
    """A recommended action to fix the failure."""
    priority: str  # HIGH, MEDIUM, LOW
    action: str
    rationale: str = ""
    code_suggestion: str = ""
    estimated_effort: str = ""  # e.g., "5 minutes", "1 hour"


@dataclass
class RootCause:
    """Identified root cause of the failure."""
    summary: str
    details: str
    confidence: float
    category: str
    tier: str = ""  # 3-tier classification
    related_commits: List[str] = field(default_factory=list)
    affected_files: List[str] = field(default_factory=list)
    similar_issues: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AnalysisResult:
    """Complete AI analysis result."""
    build_info: Dict[str, Any]
    failure_analysis: Dict[str, Any]
    root_cause: RootCause
    recommendations: List[Recommendation]
    retry_assessment: Optional[RetryAssessment] = None
    raw_ai_response: str = ""
    analysis_duration_ms: int = 0
    model_used: str = ""
    # Enhanced analysis data
    groovy_analysis: Optional[Dict[str, Any]] = None
    config_analysis: Optional[Dict[str, Any]] = None
    # Requirement 18.7, 19.10: Metadata for user_hint and method_execution_trace
    metadata: Dict[str, Any] = field(default_factory=dict)


SYSTEM_PROMPT = """You analyze Jenkins build failures. Respond with JSON only.

IMPORTANT: The REAL root cause is often in COMMAND OUTPUTS that ran BEFORE the final error.
Look for:
- Cloud CLI errors (aws, az, gcloud, kubectl) - missing params, wrong region, permission denied
- API responses - HTTP 4xx/5xx, error messages, missing fields
- Configuration errors - wrong values, missing env vars, invalid syntax
- Custom tool errors - internal tools, scripts, deploy commands

STEP 1: Check TOOL CONTEXT section first - this shows the exact command that failed
STEP 2: Look at COMMAND OUTPUTS / shell output for error details
STEP 3: Connect them - what command/config caused the failure?
STEP 4: Generate a fix with specifics (tool name, param names, values, paths from the log)

JSON FORMAT:
{
  "root_cause": "The REAL cause - include the TOOL NAME and COMMAND that failed",
  "category": "CREDENTIAL_ERROR|DEPENDENCY|COMPILATION_ERROR|TEST_FAILURE|GROOVY_LIBRARY|TIMEOUT|NETWORK|CONFIGURATION|INFRASTRUCTURE|TOOL_ERROR|UNKNOWN",
  "is_retriable": false,
  "confidence": 0.85,
  "failed_stage": "stage name",
  "failed_method": "method name",
  "failed_tool": "tool name that caused the error (from TOOL CONTEXT)",
  "fix": {
    "action": "What to do - MUST include the tool name and specific changes",
    "file": "file to change (if applicable)",
    "code": "code snippet or command to run - use the actual tool name from the log"
  }
}

EXAMPLES - Root cause is often in command output, not final error:

Log shows: "aws ecs update-service" then "An error occurred (InvalidParameterException): Missing required parameter: taskDefinition"
Root cause: "AWS ECS update-service failed: Missing required parameter 'taskDefinition'"
Fix: {"action": "Add taskDefinition parameter to aws ecs update-service call", "file": "deploy.sh", "code": "aws ecs update-service --task-definition my-task:latest ..."}

Log shows: "kubectl apply" then "error: unable to recognize file: no matches for kind 'Deployment' in version 'apps/v1beta1'"
Root cause: "Kubernetes API version mismatch - apps/v1beta1 is deprecated"
Fix: {"action": "Update Kubernetes API version from apps/v1beta1 to apps/v1", "file": "deployment.yaml", "code": "apiVersion: apps/v1"}

Log shows: "az acr login" then "AADSTS700016: Application not found in tenant"
Root cause: "Azure ACR login failed - service principal not found in tenant"
Fix: {"action": "Verify Azure service principal exists and has ACR pull permission", "file": null, "code": "az ad sp show --id $AZURE_CLIENT_ID"}

Log shows: "terraform apply" then "Error: Missing required argument: The argument 'region' is required"
Root cause: "Terraform apply failed: missing required 'region' argument"
Fix: {"action": "Add region to Terraform provider configuration", "file": "main.tf", "code": "provider 'aws' { region = 'us-east-1' }"}

CRITICAL RULES:
1. Look at COMMAND OUTPUTS section first - the real cause is often there
2. Connect command errors to the final exception
3. The fix MUST include specifics from the log (param names, values, file paths)
4. NEVER say "review", "check", "investigate" - give the actual fix
5. If a cloud/API command failed, include the correct command syntax in fix"""


GROOVY_SPECIALIZED_PROMPT = """
## Groovy/Pipeline Specific Context

The failure appears to involve Groovy or Jenkins Pipeline issues. Pay special attention to:

1. **CPS Transformation Issues**
   - Methods that cannot be CPS-transformed (use @NonCPS)
   - Closures used in incompatible contexts
   - Inner classes and anonymous classes

2. **Serialization Issues**
   - Non-serializable objects stored in pipeline variables
   - Objects that survive CPS checkpoints must be serializable
   - Common culprits: Matcher, Scanner, Connection objects

3. **Sandbox Security**
   - Methods/classes that require script approval
   - Static method calls vs instance method calls
   - Field access restrictions

4. **Shared Library Debugging**
   - vars/*.groovy functions are global variables
   - src/**/*.groovy classes must be imported
   - Library version mismatches between branch/tag and code

When the decoded CPS stack trace is provided, focus on the non-CPS-machinery frames to find the actual user code that failed.
"""


CONFIG_SPECIALIZED_PROMPT = """
## Configuration Specific Context

The failure appears to involve configuration issues. Pay special attention to:

1. **Credentials**
   - Credential ID must exist in the expected scope (global, folder, job)
   - Credential type must match binding type (usernamePassword vs string vs sshKey)
   - Masked values may hide actual errors

2. **Environment Variables**
   - Scoping: env block vs withEnv vs agent environment
   - Order of definition (earlier stages may set vars for later stages)
   - params vs env namespace

3. **Agent/Node Issues**
   - Label expressions must match at least one online node
   - Tools must be installed on the specific node
   - Workspace paths differ between master and agents

4. **Plugin Dependencies**
   - DSL methods require specific plugins
   - Plugin version compatibility with Jenkins core
   - Pipeline step availability
"""


class AIAnalyzer:
    """AI-powered failure analyzer using private AI model."""
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.client = OpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )
        self.model = config.model
        self.groovy_analyzer = GroovyAnalyzer()
        self.config_analyzer = ConfigurationAnalyzer()
    
    def analyze(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog,
        test_results: Optional[TestResult] = None,
        git_analysis: Optional[GitAnalysis] = None,
        console_log_snippet: Optional[str] = None,
        jenkinsfile_content: Optional[str] = None,
        library_sources: Optional[Dict[str, str]] = None,
    ) -> AnalysisResult:
        """
        Perform AI analysis on a build failure.
        
        Args:
            build_info: Build metadata from Jenkins
            parsed_log: Parsed log with extracted errors
            test_results: Test results if available
            git_analysis: Git correlation analysis if available
            console_log_snippet: Raw log snippet for context
            jenkinsfile_content: Optional Jenkinsfile source for deeper analysis
            library_sources: Optional dict of library file paths to contents
        """
        start_time = time.time()
        
        # Perform specialized analyses
        groovy_analysis = None
        config_analysis = None
        
        if console_log_snippet:
            # Run Groovy analysis
            groovy_analysis = self.groovy_analyzer.analyze(
                console_log_snippet,
                jenkinsfile_content,
                library_sources or {}
            )
            
            # Run Configuration analysis
            config_analysis = self.config_analyzer.analyze(
                console_log_snippet,
                jenkinsfile_content
            )
        
        # Determine if we need specialized prompts
        use_groovy_prompt = self._should_use_groovy_prompt(parsed_log, groovy_analysis)
        use_config_prompt = self._should_use_config_prompt(parsed_log, config_analysis)
        
        # Build the analysis prompt
        prompt = self._build_prompt(
            build_info,
            parsed_log,
            test_results,
            git_analysis,
            console_log_snippet,
            groovy_analysis,
            config_analysis,
        )
        
        # Build system prompt with specializations
        system_prompt = SYSTEM_PROMPT
        if use_groovy_prompt:
            system_prompt += "\n\n" + GROOVY_SPECIALIZED_PROMPT
        if use_config_prompt:
            system_prompt += "\n\n" + CONFIG_SPECIALIZED_PROMPT
        
        # Call the AI model
        response = self._call_ai(prompt, system_prompt)
        
        # Parse the response
        result = self._parse_response(response, build_info, parsed_log)
        result.analysis_duration_ms = int((time.time() - start_time) * 1000)
        result.model_used = self.model
        result.raw_ai_response = response
        
        # Attach specialized analysis data
        if groovy_analysis:
            result.groovy_analysis = {
                "failure_type": groovy_analysis.failure_type.value,
                "errors": [
                    {
                        "type": e.error_type.value,
                        "message": e.message[:500],
                        "target_class": e.target_class,
                        "target_method": e.target_method,
                        "suggestions": e.suggestions[:3],
                    }
                    for e in groovy_analysis.errors[:5]
                ],
                "libraries": [
                    {"name": r.name, "version": r.version}
                    for r in groovy_analysis.library_references
                ],
                "root_cause_function": (
                    groovy_analysis.root_cause_function.name
                    if groovy_analysis.root_cause_function else None
                ),
            }
        
        if config_analysis:
            result.config_analysis = {
                "primary_issue": config_analysis.primary_issue_type.value,
                "credential_issues": [
                    {"id": i.credential_id, "type": i.issue_type}
                    for i in config_analysis.credential_issues[:5]
                ],
                "env_issues": [
                    {"name": i.variable_name, "type": i.issue_type}
                    for i in config_analysis.environment_issues[:5]
                ],
                "agent_issues": [
                    {"label": i.label_requested, "type": i.issue_type}
                    for i in config_analysis.agent_issues[:5]
                ],
            }
        
        return result
    
    def _should_use_groovy_prompt(
        self,
        parsed_log: ParsedLog,
        groovy_analysis: Optional[GroovyAnalysis]
    ) -> bool:
        """Determine if we should include Groovy-specialized prompt."""
        groovy_categories = {
            FailureCategory.GROOVY_LIBRARY,
            FailureCategory.GROOVY_CPS,
            FailureCategory.GROOVY_SANDBOX,
            FailureCategory.GROOVY_SERIALIZATION,
        }
        
        if parsed_log.primary_category in groovy_categories:
            return True
        
        if groovy_analysis and groovy_analysis.failure_type != GroovyFailureType.UNKNOWN:
            return True
        
        if groovy_analysis and (groovy_analysis.errors or groovy_analysis.library_references):
            return True
        
        return False
    
    def _should_use_config_prompt(
        self,
        parsed_log: ParsedLog,
        config_analysis: Optional[ConfigurationAnalysis]
    ) -> bool:
        """Determine if we should include Configuration-specialized prompt."""
        config_categories = {
            FailureCategory.CONFIGURATION,
            FailureCategory.CREDENTIAL_ERROR,
            FailureCategory.AGENT_ERROR,
            FailureCategory.PLUGIN_ERROR,
        }
        
        if parsed_log.primary_category in config_categories:
            return True
        
        if config_analysis and config_analysis.primary_issue_type != ConfigFailureType.UNKNOWN:
            return True
        
        if config_analysis and (
            config_analysis.credential_issues or
            config_analysis.environment_issues or
            config_analysis.agent_issues
        ):
            return True
        
        return False
    
    def _build_prompt(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog,
        test_results: Optional[TestResult],
        git_analysis: Optional[GitAnalysis],
        console_log_snippet: Optional[str],
        groovy_analysis: Optional[GroovyAnalysis] = None,
        config_analysis: Optional[ConfigurationAnalysis] = None,
    ) -> str:
        """Build focused prompt using Root Cause Finder Expert."""
        
        from .rc_finder import RootCauseFinder
        
        parts = []
        
        # Basic build info
        parts.append(f"Job: {build_info.job_name} #{build_info.build_number}")
        parts.append(f"Status: {build_info.status}")
        
        # Use Root Cause Finder Expert for smart extraction
        if console_log_snippet:
            finder = RootCauseFinder({
                'method_execution_prefix': getattr(self.config, 'method_execution_prefix', '') if hasattr(self.config, 'method_execution_prefix') else '',
                'context_before': 30,
                'context_after': 15,
            })
            
            rc_context = finder.find(console_log_snippet)
            
            # Add the focused context from RC Finder
            parts.append(rc_context.get_ai_prompt_context())
        else:
            # Fallback if no log
            if parsed_log.failed_stage:
                parts.append(f"FAILED STAGE: {parsed_log.failed_stage}")
            if parsed_log.failed_method:
                parts.append(f"FAILED METHOD: {parsed_log.failed_method}")
            if parsed_log.errors:
                parts.append(f"\nERROR: {parsed_log.errors[0].line}")
        
        # Add test failures if present
        if test_results and test_results.failed > 0:
            parts.append(f"\nTEST FAILURES: {test_results.failed} failed")
            for failure in test_results.failures[:3]:
                parts.append(f"  - {failure.get('name', 'Unknown')}: {failure.get('message', '')[:100]}")
        
        parts.append("\n" + "="*50)
        parts.append("TASK")
        parts.append("="*50)
        parts.append("1. Look at COMMANDS/OPERATIONS BEFORE ERROR - they often show the real cause")
        parts.append("2. Connect the error to what caused it")
        parts.append("3. Respond with JSON only")
        
        return "\n".join(parts)
    
    def _call_ai(self, prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
        """Call the AI model with retry logic."""
        
        last_error = None
        
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                )
                
                return response.choices[0].message.content
                
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay)
        
        raise RuntimeError(f"AI analysis failed after {self.config.max_retries} attempts: {last_error}")
    
    def _parse_response(
        self, 
        response: str, 
        build_info: BuildInfo,
        parsed_log: ParsedLog = None,
    ) -> AnalysisResult:
        """Parse the AI response into structured result."""
        
        # Try to extract JSON from the response
        json_str = response.strip()
        
        # Handle markdown code blocks
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            json_str = response[start:end].strip()
        
        # Try to find JSON object in response
        if not json_str.startswith("{"):
            # Look for JSON object anywhere in response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = response[start:end]
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # If JSON parsing fails, create result from parsed_log directly
            return self._create_fallback_from_log(response, build_info, parsed_log)
        
        # Extract from simple format
        category = data.get("category", "UNKNOWN")
        confidence = data.get("confidence", 0.7)
        
        # Ensure confidence is valid
        if isinstance(confidence, str):
            try:
                confidence = float(confidence.replace("%", "")) / 100 if "%" in confidence else float(confidence)
            except:
                confidence = 0.7
        confidence = min(1.0, max(0.0, confidence))
        
        # Determine tier
        tier = CATEGORY_TO_TIER.get(category, FailureTier.UNKNOWN).value
        
        # Get is_retriable
        is_retriable = data.get("is_retriable", False)
        if isinstance(is_retriable, str):
            is_retriable = is_retriable.lower() in ("true", "yes", "1")
        
        # Get root_cause summary and details - ensure they're strings
        root_cause_summary = data.get("root_cause", "Unable to determine root cause")
        if isinstance(root_cause_summary, dict):
            root_cause_summary = root_cause_summary.get("text", str(root_cause_summary))
        root_cause_summary = str(root_cause_summary) if root_cause_summary else "Unable to determine root cause"
        
        root_cause_details = data.get("details", "")
        if isinstance(root_cause_details, dict):
            root_cause_details = str(root_cause_details)
        root_cause_details = str(root_cause_details) if root_cause_details else ""
        
        root_cause = RootCause(
            summary=root_cause_summary,
            details=root_cause_details,
            confidence=confidence,
            category=category,
            tier=tier,
        )
        
        retry_assessment = RetryAssessment(
            is_retriable=is_retriable,
            confidence=confidence,
            reason="",
        )
        
        # Parse recommendations from AI response
        recommendations = []
        
        # NEW FORMAT: Parse "fix" object (simpler, more direct)
        fix_data = data.get("fix", {})
        if isinstance(fix_data, dict):
            action = fix_data.get("action", "")
            file_ref = fix_data.get("file", "")
            code = fix_data.get("code", "")
            
            # Ensure strings
            action = str(action) if action else ""
            file_ref = str(file_ref) if file_ref else ""
            code = str(code) if code else ""
            
            # Filter useless
            useless = ["review", "check the", "investigate", "look at", "examine", "see above"]
            is_useless = not action or any(u in action.lower() for u in useless)
            
            if action and not is_useless:
                # Build detailed rationale from file and code
                details_parts = []
                if file_ref and file_ref != "null":
                    details_parts.append(f"File: {file_ref}")
                if code and code != "null":
                    details_parts.append(f"Code:\n```\n{code}\n```")
                
                recommendations.append(Recommendation(
                    priority="HIGH",
                    action=action,
                    rationale="\n".join(details_parts) if details_parts else "",
                    code_suggestion=code if code and code != "null" else "",
                ))
        
        # LEGACY FORMAT: Parse "recommendations" array (backward compatibility)
        if not recommendations:
            ai_recommendations = data.get("recommendations", [])
            if isinstance(ai_recommendations, list):
                for rec in ai_recommendations:
                    if isinstance(rec, dict):
                        action = rec.get("action", "")
                        priority = rec.get("priority", "MEDIUM")
                        details = rec.get("details", "")
                        
                        action = str(action) if action else ""
                        priority = str(priority) if priority else "MEDIUM"
                        details = str(details) if details else ""
                        
                        useless = ["review the", "check the", "see above", "investigate", "look at", "examine"]
                        is_useless = not action or any(p in action.lower() for p in useless)
                        
                        if action and not is_useless:
                            recommendations.append(Recommendation(
                                priority=priority,
                                action=action,
                                rationale=details,
                            ))
        
        # FALLBACK: Use root_cause to generate fix suggestion
        if not recommendations:
            root_cause_text = root_cause_summary  # Already sanitized
            
            # Try to extract something actionable from the error
            if root_cause_text and len(root_cause_text) > 10:
                # Look for common patterns and create specific recommendations
                rc_lower = root_cause_text.lower()
                
                if "credential" in rc_lower or "credentials" in rc_lower:
                    # Extract credential ID if present
                    import re
                    cred_match = re.search(r"['\"]([^'\"]+)['\"]", root_cause_text)
                    cred_id = cred_match.group(1) if cred_match else "the-credential-id"
                    recommendations.append(Recommendation(
                        priority="HIGH",
                        action=f"Create Jenkins credential with ID '{cred_id}'",
                        rationale="Go to: Jenkins > Manage Jenkins > Credentials > Add Credentials",
                    ))
                elif "nullpointerexception" in rc_lower or "null pointer" in rc_lower:
                    # Extract location if present
                    loc_match = re.search(r"at\s+(\S+):(\d+)", root_cause_text) if 'at ' in root_cause_text else None
                    if loc_match:
                        recommendations.append(Recommendation(
                            priority="HIGH",
                            action=f"Add null check at {loc_match.group(1)} line {loc_match.group(2)}",
                            rationale="Add null safety: if (obj != null) or use ?. operator",
                        ))
                    else:
                        recommendations.append(Recommendation(
                            priority="HIGH",
                            action="Add null check before the failing method call",
                            rationale=f"Error: {root_cause_text[:150]}",
                        ))
                elif "timeout" in rc_lower:
                    recommendations.append(Recommendation(
                        priority="HIGH",
                        action="Increase timeout value for the failing operation",
                        rationale="In Jenkinsfile: timeout(time: 30, unit: 'MINUTES') { ... }",
                    ))
                elif "permission" in rc_lower or "access denied" in rc_lower:
                    recommendations.append(Recommendation(
                        priority="HIGH",
                        action="Grant required permissions for the operation",
                        rationale=f"Error: {root_cause_text[:150]}",
                    ))
                elif "not found" in rc_lower or "404" in rc_lower:
                    recommendations.append(Recommendation(
                        priority="HIGH",
                        action="Verify the resource exists and path is correct",
                        rationale=f"Error: {root_cause_text[:150]}",
                    ))
                else:
                    # Generic but with actual error
                    recommendations.append(Recommendation(
                        priority="HIGH",
                        action=f"Fix: {root_cause_text[:150]}",
                        rationale="See error details above for specifics",
                    ))
            else:
                recommendations.append(Recommendation(
                    priority="HIGH",
                    action="Unable to determine specific fix - see error details",
                    rationale="The AI could not parse specific fix from the error",
                ))
        
        return AnalysisResult(
            build_info={
                "job": build_info.job_name,
                "build_number": build_info.build_number,
                "status": build_info.status,
                "duration": build_info.duration_str,
            },
            failure_analysis={
                "category": category,
                "tier": tier,
                "failed_stage": str(data.get("failed_stage", "")) if data.get("failed_stage") else None,
                "primary_error": root_cause_summary,  # Use already-sanitized value
                "confidence": confidence,
            },
            root_cause=root_cause,
            recommendations=recommendations,
            retry_assessment=retry_assessment,
            raw_ai_response=response,
        )
    
    def _create_fallback_from_log(
        self, 
        response: str, 
        build_info: BuildInfo,
        parsed_log: ParsedLog = None,
    ) -> AnalysisResult:
        """Create a useful result from parsed_log when AI response parsing fails."""
        
        # Use parsed_log as primary source of truth
        category = "UNKNOWN"
        primary_error = "Unable to parse AI response"
        failed_stage = None
        failed_method = None
        
        if parsed_log:
            category = parsed_log.primary_category.value
            failed_stage = parsed_log.failed_stage
            failed_method = parsed_log.failed_method
            
            # Get actual error from the log
            if parsed_log.errors:
                primary_error = parsed_log.errors[0].line[:500]
            elif parsed_log.stack_traces:
                trace = parsed_log.stack_traces[0]
                primary_error = f"{trace.exception_type}: {trace.message}"
        
        tier = CATEGORY_TO_TIER.get(category, FailureTier.UNKNOWN).value
        
        # Try to extract useful info from AI response text
        summary = primary_error
        if response and len(response) > 10:
            # Use first meaningful sentence from AI response as additional context
            sentences = response.split(".")
            for s in sentences[:3]:
                s = s.strip()
                if len(s) > 20 and not s.startswith("{"):
                    summary = s
                    break
        
        # Simple recommendation based on actual error
        recommendations = []
        if primary_error and len(primary_error) > 10:
            # Build context string
            context_parts = []
            if failed_stage:
                context_parts.append(f"stage '{failed_stage}'")
            if failed_method:
                context_parts.append(f"method '{failed_method}'")
            context = f" in {' → '.join(context_parts)}" if context_parts else ""
            
            recommendations.append(Recommendation(
                priority="HIGH",
                action=f"Fix the error{context}: {primary_error[:300]}",
                rationale=f"Error extracted from build log. Category: {category}",
            ))
        else:
            recommendations.append(Recommendation(
                priority="HIGH",
                action="Review the build log for error details",
                rationale="AI analysis failed to parse - manual review needed",
            ))
        
        return AnalysisResult(
            build_info={
                "job": build_info.job_name,
                "build_number": build_info.build_number,
                "status": build_info.status,
                "duration": build_info.duration_str,
            },
            failure_analysis={
                "category": category,
                "tier": tier,
                "failed_stage": failed_stage,
                "primary_error": primary_error,
                "confidence": 0.6,
            },
            root_cause=RootCause(
                summary=summary,
                details=f"Primary error from log: {primary_error}",
                confidence=0.6,
                category=category,
                tier=tier,
            ),
            recommendations=recommendations,
            retry_assessment=RetryAssessment(
                is_retriable=tier == FailureTier.EXTERNAL_SYSTEM.value,
                confidence=0.6,
                reason=f"Category: {category}",
            ),
            raw_ai_response=response,
        )
    
    def test_connection(self) -> bool:
        """Test connection to the AI model."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": "Respond with 'OK' if you can read this."}
                ],
                max_tokens=10,
            )
            return "OK" in response.choices[0].message.content.upper()
        except Exception:
            return False


def result_to_dict(result: AnalysisResult) -> Dict[str, Any]:
    """Convert AnalysisResult to a dictionary for JSON serialization."""
    output = {
        "build_info": result.build_info,
        "failure_analysis": result.failure_analysis,
        "root_cause": {
            "summary": result.root_cause.summary,
            "details": result.root_cause.details,
            "confidence": result.root_cause.confidence,
            "category": result.root_cause.category,
            "tier": result.root_cause.tier,
            "related_commits": result.root_cause.related_commits,
            "affected_files": result.root_cause.affected_files,
            "similar_issues": result.root_cause.similar_issues,
        },
        "recommendations": [
            {
                "priority": rec.priority,
                "action": rec.action,
                "rationale": rec.rationale,
                "code_suggestion": rec.code_suggestion,
                "estimated_effort": rec.estimated_effort,
            }
            for rec in result.recommendations
        ],
        "metadata": {
            "analysis_duration_ms": result.analysis_duration_ms,
            "model_used": result.model_used,
        }
    }
    
    # Include retry assessment if present
    if result.retry_assessment:
        output["retry_assessment"] = {
            "is_retriable": result.retry_assessment.is_retriable,
            "confidence": result.retry_assessment.confidence,
            "reason": result.retry_assessment.reason,
            "recommended_wait_seconds": result.retry_assessment.recommended_wait_seconds,
            "max_retries": result.retry_assessment.max_retries,
        }
    
    # Include specialized analysis data if present
    if result.groovy_analysis:
        output["groovy_analysis"] = result.groovy_analysis
    
    if result.config_analysis:
        output["config_analysis"] = result.config_analysis
    
    return output
