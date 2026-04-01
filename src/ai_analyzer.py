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


SYSTEM_PROMPT = """You are an expert CI/CD failure analyst specializing in Jenkins Pipeline, Groovy, and shared library debugging. Your job is to analyze Jenkins build failures and identify root causes.

## Core Expertise Areas

### 1. Groovy and Jenkins Pipeline
You have deep knowledge of:
- CPS (Continuation Passing Style) transformation and its limitations
- Jenkins Pipeline sandbox security and script approvals
- Serialization requirements for pipeline variables
- Shared library structure (vars/, src/, resources/)
- Common Groovy pitfalls in Jenkins context

### 2. Configuration Issues
You understand:
- Jenkins Configuration-as-Code (JCasC)
- Credentials management and binding
- Environment variable scoping (global, folder, job, agent)
- Agent labels and node selection
- Tool installations and auto-installers
- Plugin dependencies and versions

### 3. Multi-Layer Debugging
Jenkins failures often involve multiple layers:
- Jenkinsfile → shared library → internal steps → external tools
- Configuration-as-Code → overrides → environment variables → credentials
- Pipeline sandboxing → CPS transformation → serialization issues
- Master/agent differences → missing plugins or mismatched versions

The "real" error is rarely the last line of the log. You must reconstruct the execution path.

## Analysis Approach

When analyzing a build failure:
1. **Decode CPS traces**: Filter out internal CPS machinery to find actual user code
2. **Map library calls**: Trace errors back to the specific library function that failed
3. **Check signatures**: Verify function signatures match between Jenkinsfile and library
4. **Detect config mismatches**: Identify credential IDs, labels, env vars that don't match
5. **Find version issues**: Look for plugin or library version mismatches
6. **Assess retry safety**: Determine if the failure is transient or requires code/config changes
7. **Provide minimal fixes**: Suggest the smallest change that will fix the issue

## Response Format

Always structure your response as valid JSON with the following format:
{
    "failure_analysis": {
        "category": "GROOVY_LIBRARY | GROOVY_CPS | GROOVY_SANDBOX | GROOVY_SERIALIZATION | CREDENTIAL_ERROR | AGENT_ERROR | PLUGIN_ERROR | CONFIGURATION | TEST_FAILURE | COMPILATION_ERROR | INFRASTRUCTURE | DEPENDENCY | NETWORK | TIMEOUT | UNKNOWN",
        "tier": "configuration | pipeline_misuse | external_system",
        "failed_stage": "name of the failed pipeline stage or null",
        "primary_error": "the main error message",
        "confidence": 0.0-1.0,
        "groovy_specific": {
            "library_involved": "library name if applicable",
            "function_involved": "function name if applicable",
            "cps_issue": true/false,
            "sandbox_issue": true/false,
            "serialization_issue": true/false
        },
        "config_specific": {
            "credential_issue": "credential ID if applicable",
            "env_var_issue": "variable name if applicable",
            "agent_issue": "label if applicable",
            "plugin_issue": "plugin name if applicable"
        }
    },
    "root_cause": {
        "summary": "one-line summary of the root cause",
        "details": "detailed explanation including the execution path that led to failure",
        "category": "specific category",
        "related_commits": ["commit SHA if relevant"],
        "affected_files": ["list of affected files including library files"],
        "layers_involved": ["Jenkinsfile", "shared-library:myFunc", "plugin:git", etc.]
    },
    "retry_assessment": {
        "is_retriable": true/false,
        "confidence": 0.0-1.0,
        "reason": "explanation of why retry will/won't help",
        "recommended_wait_seconds": 0,
        "max_retries": 0
    },
    "recommendations": [
        {
            "priority": "HIGH | MEDIUM | LOW",
            "action": "specific action to take",
            "rationale": "why this will fix the issue and how it addresses the root cause",
            "code_suggestion": "exact code snippet or configuration change",
            "estimated_effort": "time estimate",
            "verification": "how to verify the fix worked"
        }
    ]
}

## Retry Assessment Guidelines

- **Retriable (transient)**: Network timeouts, rate limits, resource exhaustion, flaky tests, external service unavailable
- **Not retriable**: Code errors, configuration issues, missing credentials, wrong parameters, pipeline syntax errors
- For transient failures, suggest wait time (e.g., 60s for rate limits, 300s for resource exhaustion)
- Set max_retries based on failure type (typically 1-3 for transient issues)

## Tier Classification

Classify every failure into one of three tiers:
- **configuration**: Missing/wrong credentials, env vars, parameters, agent labels — user needs to fix Jenkins config
- **pipeline_misuse**: Jenkinsfile errors, shared library bugs, CPS issues, sandbox rejections — developer needs to fix code
- **external_system**: Network failures, dependency issues, test failures, infrastructure problems — may be transient or require ops intervention

## Important Guidelines

- For sandbox rejections: Always include the exact approval needed
- For missing methods: Check if the method exists in the library version being used
- For serialization errors: Suggest @NonCPS or restructuring
- For credential errors: Verify the ID and type match
- For agent errors: Check label spelling and node availability
- Be concise but thorough. Focus on actionable insights."""


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
        result = self._parse_response(response, build_info)
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
        """Build the analysis prompt for the AI model."""
        
        parts = []
        
        # Build information
        parts.append("## Build Information")
        parts.append(f"- Job: {build_info.job_name}")
        parts.append(f"- Build Number: {build_info.build_number}")
        parts.append(f"- Status: {build_info.status}")
        parts.append(f"- Duration: {build_info.duration_str}")
        parts.append(f"- Timestamp: {build_info.timestamp.isoformat()}")
        
        if build_info.causes:
            parts.append(f"- Trigger: {build_info.causes[0]}")
        
        # Log analysis summary
        parts.append("\n## Log Analysis Summary")
        parts.append(parsed_log.summary)
        
        if parsed_log.failed_stage:
            parts.append(f"- Failed Stage: {parsed_log.failed_stage}")
        
        parts.append(f"- Primary Category: {parsed_log.primary_category.value}")
        parts.append(f"- Total Errors Found: {len(parsed_log.errors)}")
        parts.append(f"- Stack Traces Found: {len(parsed_log.stack_traces)}")
        
        # Include Groovy analysis if available
        if groovy_analysis:
            parts.append("\n" + self.groovy_analyzer.format_for_ai_prompt(groovy_analysis))
        
        # Include Configuration analysis if available
        if config_analysis:
            parts.append("\n" + self.config_analyzer.format_for_ai_prompt(config_analysis))
        
        # Errors
        parts.append("\n## Extracted Errors")
        for i, error in enumerate(parsed_log.errors[:10]):
            parts.append(f"\n### Error {i + 1} (Line {error.line_number})")
            parts.append(f"Category: {error.category.value}")
            parts.append(f"Severity: {error.severity}")
            parts.append(f"```\n{error.line}\n```")
            
            # Add context
            if error.context_before:
                context = "\n".join(error.context_before[-5:])
                parts.append(f"Context before:\n```\n{context}\n```")
            if error.context_after:
                context = "\n".join(error.context_after[:5])
                parts.append(f"Context after:\n```\n{context}\n```")
        
        # Stack traces
        if parsed_log.stack_traces:
            parts.append("\n## Stack Traces")
            for i, trace in enumerate(parsed_log.stack_traces[:5]):
                parts.append(f"\n### Stack Trace {i + 1}")
                parts.append(f"Exception: {trace.exception_type}")
                parts.append(f"Message: {trace.message}")
                parts.append("Frames:")
                for frame in trace.frames[:10]:
                    parts.append(f"  - {frame}")
        
        # Test results
        if test_results:
            parts.append("\n## Test Results")
            parts.append(f"- Total: {test_results.total}")
            parts.append(f"- Passed: {test_results.passed}")
            parts.append(f"- Failed: {test_results.failed}")
            parts.append(f"- Skipped: {test_results.skipped}")
            
            if test_results.failures:
                parts.append("\n### Failed Tests")
                for failure in test_results.failures[:10]:
                    parts.append(f"- {failure.get('name', 'Unknown')}")
                    if failure.get('message'):
                        parts.append(f"  Message: {failure['message'][:200]}")
        
        # Git analysis
        if git_analysis:
            parts.append("\n## Git Analysis")
            parts.append(f"- Total Commits Analyzed: {git_analysis.total_commits}")
            parts.append(f"- Risk Score: {git_analysis.risk_score:.2f}")
            
            if git_analysis.risk_factors:
                parts.append("\nRisk Factors:")
                for factor in git_analysis.risk_factors:
                    parts.append(f"- {factor}")
            
            if git_analysis.suspicious_commits:
                parts.append("\nSuspicious Commits:")
                for commit in git_analysis.suspicious_commits[:5]:
                    parts.append(
                        f"- [{commit.short_sha}] {commit.author}: "
                        f"{commit.message[:80]}"
                    )
                    if commit.files_changed:
                        files = ", ".join(commit.files_changed[:5])
                        parts.append(f"  Changed files: {files}")
        
        # Raw log snippet (truncated)
        if console_log_snippet:
            parts.append("\n## Console Log Snippet")
            parts.append(f"```\n{console_log_snippet[:5000]}\n```")
        
        # Final instruction
        parts.append("\n## Analysis Request")
        parts.append(
            "Based on the above information, provide a detailed root cause analysis "
            "and actionable recommendations. Pay special attention to Groovy, "
            "shared library, and configuration issues if present. "
            "Respond with valid JSON only."
        )
        
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
        build_info: BuildInfo
    ) -> AnalysisResult:
        """Parse the AI response into structured result."""
        
        # Try to extract JSON from the response
        json_str = response
        
        # Handle markdown code blocks
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            json_str = response[start:end].strip()
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # If JSON parsing fails, create a basic response
            return self._create_fallback_result(response, build_info)
        
        # Extract failure analysis
        failure_analysis = data.get("failure_analysis", {})
        
        # Determine tier (from AI or derived from category)
        category = failure_analysis.get("category", "UNKNOWN")
        tier = failure_analysis.get("tier", "")
        if not tier:
            # Derive tier from category using mapping
            tier = CATEGORY_TO_TIER.get(category, FailureTier.UNKNOWN).value
        
        # Extract root cause
        root_cause_data = data.get("root_cause", {})
        root_cause = RootCause(
            summary=root_cause_data.get("summary", "Unable to determine root cause"),
            details=root_cause_data.get("details", ""),
            confidence=failure_analysis.get("confidence", 0.5),
            category=root_cause_data.get("category", category),
            tier=tier,
            related_commits=root_cause_data.get("related_commits", []),
            affected_files=root_cause_data.get("affected_files", []),
        )
        
        # Extract retry assessment
        retry_data = data.get("retry_assessment", {})
        retry_assessment = None
        if retry_data:
            retry_assessment = RetryAssessment(
                is_retriable=retry_data.get("is_retriable", False),
                confidence=retry_data.get("confidence", 0.5),
                reason=retry_data.get("reason", ""),
                recommended_wait_seconds=retry_data.get("recommended_wait_seconds", 0),
                max_retries=retry_data.get("max_retries", 0),
            )
        else:
            # Create default assessment based on tier
            if tier == FailureTier.EXTERNAL_SYSTEM.value:
                retry_assessment = RetryAssessment(
                    is_retriable=True,
                    confidence=0.6,
                    reason="External system failures are often transient",
                    recommended_wait_seconds=60,
                    max_retries=2,
                )
            else:
                retry_assessment = RetryAssessment(
                    is_retriable=False,
                    confidence=0.7,
                    reason=f"Failure tier '{tier}' typically requires code or config changes",
                    recommended_wait_seconds=0,
                    max_retries=0,
                )
        
        # Extract recommendations
        recommendations = []
        for rec_data in data.get("recommendations", []):
            recommendations.append(Recommendation(
                priority=rec_data.get("priority", "MEDIUM"),
                action=rec_data.get("action", ""),
                rationale=rec_data.get("rationale", ""),
                code_suggestion=rec_data.get("code_suggestion", ""),
                estimated_effort=rec_data.get("estimated_effort", ""),
            ))
        
        # If no recommendations, add a generic one
        if not recommendations:
            recommendations.append(Recommendation(
                priority="MEDIUM",
                action="Review the error logs and stack traces for more details",
                rationale="Additional investigation may be needed",
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
                "failed_stage": failure_analysis.get("failed_stage"),
                "primary_error": failure_analysis.get("primary_error", ""),
                "confidence": failure_analysis.get("confidence", 0.5),
            },
            root_cause=root_cause,
            recommendations=recommendations,
            retry_assessment=retry_assessment,
        )
    
    def _create_fallback_result(
        self, 
        response: str, 
        build_info: BuildInfo
    ) -> AnalysisResult:
        """Create a fallback result when JSON parsing fails."""
        
        return AnalysisResult(
            build_info={
                "job": build_info.job_name,
                "build_number": build_info.build_number,
                "status": build_info.status,
                "duration": build_info.duration_str,
            },
            failure_analysis={
                "category": "UNKNOWN",
                "tier": FailureTier.UNKNOWN.value,
                "failed_stage": None,
                "primary_error": "Unable to parse AI response",
                "confidence": 0.3,
            },
            root_cause=RootCause(
                summary="Analysis completed but response format was unexpected",
                details=response[:2000],
                confidence=0.3,
                category="UNKNOWN",
                tier=FailureTier.UNKNOWN.value,
            ),
            recommendations=[
                Recommendation(
                    priority="HIGH",
                    action="Review the raw AI response for insights",
                    rationale="The structured parsing failed, but the response may contain useful information",
                )
            ],
            retry_assessment=RetryAssessment(
                is_retriable=False,
                confidence=0.3,
                reason="Unable to determine retry safety due to parsing failure",
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
