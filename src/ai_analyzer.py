"""
AI analyzer for root cause analysis using a private AI model.
Supports any OpenAI-compatible API (Ollama, vLLM, LocalAI, etc.)
"""

import json
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


SYSTEM_PROMPT = """You are a Jenkins CI/CD failure analyst. Analyze the build failure and respond with a JSON object.

CRITICAL: The error is almost always at the END of the log, in the LAST stage. Look there FIRST.

IMPORTANT: Respond ONLY with valid JSON, no other text. Use this exact format:

{
  "root_cause": "One sentence describing the main reason for failure - quote the actual error message",
  "category": "TEST_FAILURE|COMPILATION_ERROR|DEPENDENCY|CONFIGURATION|NETWORK|TIMEOUT|INFRASTRUCTURE|GROOVY_LIBRARY|GROOVY_CPS|CREDENTIAL_ERROR|AGENT_ERROR|PLUGIN_ERROR|UNKNOWN",
  "is_retriable": true or false,
  "confidence": 0.0 to 1.0,
  "failed_stage": "stage name or null",
  "failed_method": "method/function name that was running when it failed, or null",
  "fix_suggestion": "What to do to fix this",
  "details": "Additional context about the failure"
}

WHERE TO LOOK FOR ERRORS:
1. LAST stage in the log (stages start with [Pipeline] stage / [Pipeline] { (name))
2. The FAILED METHOD indicator shows which shared library function was running
3. Exception messages and stack traces
4. Lines containing ERROR, FATAL, FAILED, Exception
5. Build tool errors (Maven: BUILD FAILURE, Gradle: FAILED, npm: ERR!)
6. The LAST error message before the build ends

METHOD TRACKING:
- Method start: "hh:mm:ss  method_name: method_name"
- Method finish: "method_name :time-elapsed-seconds:NN"
- If a method started but didn't finish, the error happened in that method

The root_cause MUST be specific - quote the actual error message from the log, not a generic description."""


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
        """Build a simple, effective analysis prompt."""
        
        parts = []
        
        # Basic build info
        parts.append(f"Job: {build_info.job_name} #{build_info.build_number}")
        parts.append(f"Status: {build_info.status}")
        if parsed_log.failed_stage:
            parts.append(f"FAILED STAGE: {parsed_log.failed_stage} <-- LOOK HERE FOR THE ERROR")
        if parsed_log.failed_method:
            parts.append(f"FAILED METHOD: {parsed_log.failed_method} <-- THIS METHOD WAS RUNNING WHEN IT FAILED")
        
        # FIRST: Show the raw log END - this is where the error is!
        if console_log_snippet:
            snippet = console_log_snippet
            # Take the LAST 8000 chars - this is where the error almost always is
            if len(snippet) > 8000:
                snippet = snippet[-8000:]
            parts.append("\n=== END OF BUILD LOG (MOST IMPORTANT - ERROR IS HERE) ===")
            parts.append(snippet)
            parts.append("=== END OF LOG ===")
        
        # Then show extracted errors (these are from the log parser)
        if parsed_log.errors:
            parts.append("\n--- EXTRACTED ERRORS ---")
            for i, error in enumerate(parsed_log.errors[:10]):
                parts.append(f"\nError {i+1} (line {error.line_number}):")
                parts.append(error.line)
                if error.context_before:
                    for ctx in error.context_before[-2:]:
                        parts.append(f"  {ctx}")
                if error.context_after:
                    for ctx in error.context_after[:2]:
                        parts.append(f"  {ctx}")
        
        # Stack traces
        if parsed_log.stack_traces:
            parts.append("\n--- STACK TRACES ---")
            for i, trace in enumerate(parsed_log.stack_traces[:3]):
                parts.append(f"\nException: {trace.exception_type}")
                parts.append(f"Message: {trace.message}")
                if trace.frames:
                    for frame in trace.frames[:5]:
                        parts.append(f"  {frame}")
        
        # Test failures
        if test_results and test_results.failed > 0:
            parts.append(f"\n--- TEST FAILURES ({test_results.failed} failed) ---")
            for failure in test_results.failures[:5]:
                parts.append(f"- {failure.get('name', 'Unknown')}: {failure.get('message', '')[:200]}")
        
        parts.append("\n--- TASK ---")
        parts.append("Find the ROOT CAUSE in the log above. Quote the actual error message.")
        parts.append("Respond with JSON only.")
        
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
        
        root_cause = RootCause(
            summary=data.get("root_cause", "Unable to determine root cause"),
            details=data.get("details", ""),
            confidence=confidence,
            category=category,
            tier=tier,
        )
        
        retry_assessment = RetryAssessment(
            is_retriable=is_retriable,
            confidence=confidence,
            reason=data.get("fix_suggestion", ""),
        )
        
        recommendations = []
        if data.get("fix_suggestion"):
            recommendations.append(Recommendation(
                priority="HIGH",
                action=data.get("fix_suggestion"),
                rationale=data.get("details", ""),
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
                "failed_stage": data.get("failed_stage"),
                "primary_error": data.get("root_cause", ""),
                "confidence": confidence,
            },
            root_cause=root_cause,
            recommendations=recommendations if recommendations else [
                Recommendation(priority="MEDIUM", action="Review the error details above")
            ],
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
        
        if parsed_log:
            category = parsed_log.primary_category.value
            failed_stage = parsed_log.failed_stage
            
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
            recommendations=[
                Recommendation(
                    priority="HIGH",
                    action=f"Fix the error: {primary_error[:200]}",
                    rationale="This error was extracted directly from the build log",
                )
            ],
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
