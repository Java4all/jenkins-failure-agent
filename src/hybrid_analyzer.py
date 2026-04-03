"""
Hybrid analyzer that routes to iterative or deep investigation modes.

This module provides a unified interface that:
1. Uses iterative multi-call RC analysis for most failures (default)
2. Triggers deep agentic investigation with MCP tools when needed

Simplified to two modes per Requirement 5:
- ITERATIVE (default): Multi-call AI loop with automatic source pre-loading
- DEEP: Full MCP tool investigation for complex code/library issues
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum

from .config import Config, AIConfig
from .jenkins_client import JenkinsClient, BuildInfo, TestResult
from .log_parser import LogParser, ParsedLog, FailureCategory
from .git_analyzer import GitAnalyzer, GitAnalysis
from .ai_analyzer import (
    AIAnalyzer, AnalysisResult, RootCause, Recommendation,
    RetryAssessment, FailureTier, CATEGORY_TO_TIER, result_to_dict
)

logger = logging.getLogger("jenkins-agent.hybrid")


class AnalysisMode(str, Enum):
    """Analysis mode - simplified to two options per Requirement 5.7."""
    ITERATIVE = "iterative"   # Multi-call iterative RC analysis (default)
    DEEP = "deep"             # Deep investigation with MCP tool calls


# Categories that benefit from agentic investigation
AGENTIC_CATEGORIES = {
    "GROOVY_LIBRARY",
    "GROOVY_CPS",
    "GROOVY_SANDBOX",
    "GROOVY_SERIALIZATION",
    "PLUGIN_ERROR",
}

# Error patterns that trigger agentic investigation
AGENTIC_ERROR_PATTERNS = [
    "MissingMethodException",
    "MissingPropertyException",
    "MissingClassException",
    "NoSuchMethodError",
    "ClassNotFoundException",
    "cannot resolve class",
    "unable to resolve class",
    "No signature of method",
    "No such property",
    "NonCPS",
    "NotSerializableException",
    "cannot serialize",
]


@dataclass
class HybridAnalysisResult:
    """Result from analysis (iterative or deep mode)."""
    mode: AnalysisMode
    result: AnalysisResult  # The final analysis result
    iterations_used: int = 1
    tool_calls_made: int = 0
    source_files_fetched: List[str] = field(default_factory=list)
    skipped: bool = False  # True if analysis was skipped (Req 14)
    skip_reason: str = ""  # Reason for skipping
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        if self.skipped:
            return {
                "success": True,
                "status": "no_analysis_needed",
                "reason": self.skip_reason,
                "analysis_mode": self.mode.value,
            }
        
        base = result_to_dict(self.result)
        base["analysis_mode"] = self.mode.value
        base["iterations_used"] = self.iterations_used
        if self.tool_calls_made > 0:
            base["tool_calls_made"] = self.tool_calls_made
        if self.source_files_fetched:
            base["source_files_fetched"] = self.source_files_fetched
        return base


class HybridAnalyzer:
    """
    Routes analysis to iterative or deep investigation mode.
    
    Per Requirement 5:
    - Iterative (default): Multi-call AI loop with source pre-loading
    - Deep: Full MCP tool investigation for complex cases
    
    Usage:
        analyzer = HybridAnalyzer(config)
        
        # Default iterative mode
        result = analyzer.analyze(build_info, parsed_log)
        
        # Force deep mode
        result = analyzer.analyze(build_info, parsed_log, deep=True)
    """
    
    def __init__(self, config: Config):
        """
        Initialize hybrid analyzer.
        
        Args:
            config: Full configuration object
        """
        self.config = config
        self.ai_config = config.ai
        
        # RC Analyzer for iterative mode (lazy init)
        self._rc_analyzer = None
        
        # Investigator for deep mode (lazy init)
        self._investigator = None
        
        # Clients for source code fetching
        self.jenkins_client: Optional[JenkinsClient] = None
        self.github_client = None
        self.scm_client = None
        self._clients_set = False
        
        logger.info("HybridAnalyzer initialized (modes: iterative, deep)")
    
    def set_clients(
        self,
        jenkins_client: JenkinsClient = None,
        github_client = None,
        scm_client = None,
    ):
        """Set client instances for source fetching and deep investigation."""
        self.jenkins_client = jenkins_client
        self.github_client = github_client
        self.scm_client = scm_client
        self._clients_set = True
    
    @property
    def rc_analyzer(self):
        """Lazy initialization of RC Analyzer for iterative mode."""
        if self._rc_analyzer is None:
            from .rc_analyzer import RCAnalyzer
            from .groovy_analyzer import GroovyAnalyzer
            
            # Create AI analyzer instance
            ai_analyzer = AIAnalyzer(self.ai_config)
            
            self._rc_analyzer = RCAnalyzer(
                ai_analyzer=ai_analyzer,
                github_client=self.github_client,
                groovy_analyzer=GroovyAnalyzer(),
                config=self.config.rc_analyzer,
            )
        return self._rc_analyzer
    
    @property
    def investigator(self):
        """Lazy initialization of Investigator for deep mode."""
        if self._investigator is None:
            from .agent import Investigator
            self._investigator = Investigator(self.ai_config)
            
            if self._clients_set:
                self._investigator.set_clients(
                    jenkins_client=self.jenkins_client,
                    github_client=self.github_client,
                    scm_client=self.scm_client,
                )
        return self._investigator
    
    def _check_build_status(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog = None,
        user_hint: str = None,
    ) -> Optional[HybridAnalysisResult]:
        """
        Pre-check build status before analysis (Requirement 14).
        
        Returns HybridAnalysisResult with skipped=True if analysis should be skipped,
        or None if analysis should proceed.
        """
        # Req 14.3: Build still in progress
        if build_info.building:
            logger.info(f"Build {build_info.job_name}#{build_info.build_number} is still running")
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                result=None,
                skipped=True,
                skip_reason="Build is still in progress",
            )
        
        status = build_info.status
        
        # Req 14.2: Build succeeded
        if status == "SUCCESS":
            logger.info(f"Build {build_info.job_name}#{build_info.build_number} succeeded — no failure to analyze")
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                result=None,
                skipped=True,
                skip_reason="Build succeeded",
            )
        
        # Req 14.4: Build aborted
        if status == "ABORTED":
            logger.info(f"Build {build_info.job_name}#{build_info.build_number} was aborted")
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                result=None,
                skipped=True,
                skip_reason="Build was manually aborted",
            )
        
        # Req 14.6: UNSTABLE builds - lightweight scan for serious issues
        if status == "UNSTABLE":
            logger.info(f"UNSTABLE build detected - performing lightweight scan")
            
            # Req 14.6a: Check for serious issues only
            serious_issues = self._scan_for_serious_issues(parsed_log) if parsed_log else False
            
            if not serious_issues:
                # Req 14.6b: No serious issues found
                # Req 18.6: If user_hint provided, do targeted search
                if user_hint:
                    logger.info(f"UNSTABLE build with user hint - will do targeted search")
                    # Mark as UNSTABLE in build_info for labeling
                    return None  # Proceed with analysis using hint
                
                # Req 14.6c: Return cautious response
                logger.info(f"UNSTABLE build with no critical errors detected - skipping analysis")
                return HybridAnalysisResult(
                    mode=AnalysisMode.ITERATIVE,
                    result=None,
                    skipped=True,
                    skip_reason="Build is unstable but no critical errors were detected. "
                               "This often means tests passed but with warnings, or quality gates weren't met. "
                               "If you believe there's a real issue, please provide a hint about what you expected "
                               "using --hint or the hint field in the UI.",
                )
            else:
                # Req 14.6a: Serious issues found - proceed but log it
                logger.info(f"UNSTABLE build with serious issues detected - proceeding with analysis")
        
        # Req 14.1: Only proceed for FAILURE or UNSTABLE (with issues)
        if status not in ("FAILURE", "UNSTABLE", None):
            logger.warning(f"Unexpected build status: {status}")
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                result=None,
                skipped=True,
                skip_reason=f"Unexpected build status: {status}",
            )
        
        return None  # Proceed with analysis
    
    def _scan_for_serious_issues(self, parsed_log: ParsedLog) -> bool:
        """
        Lightweight scan for serious issues in UNSTABLE builds (Req 14.6).
        
        Only returns True for REAL serious issues, not noise.
        Returns True if serious issues found.
        """
        # Check for stack traces - these are always serious
        if parsed_log.stack_traces:
            logger.debug(f"Found {len(parsed_log.stack_traces)} stack traces - serious issue")
            return True
        
        # Serious error categories that warrant investigation
        serious_categories = {
            FailureCategory.COMPILATION_ERROR,
            FailureCategory.INFRASTRUCTURE,
            FailureCategory.PERMISSION,
            FailureCategory.CREDENTIAL_ERROR,
            FailureCategory.GROOVY_LIBRARY,
            FailureCategory.GROOVY_CPS,
            FailureCategory.GROOVY_SANDBOX,
            FailureCategory.GROOVY_SERIALIZATION,
            FailureCategory.PLUGIN_ERROR,
        }
        
        for error in parsed_log.errors:
            if error.category in serious_categories:
                logger.debug(f"Found serious error category: {error.category}")
                return True
        
        # Only check for VERY specific serious patterns (not generic ones)
        serious_patterns = [
            'exception:',
            'fatal error',
            'fatal:',
            'build failure',
            'compilation failed',
            'unable to resolve',
            'could not find',
            'permission denied',
            'access denied',
            'authentication failed',
            'connection refused',
            'timeout',
        ]
        
        for error in parsed_log.errors:
            error_lower = error.line.lower()
            for pattern in serious_patterns:
                if pattern in error_lower:
                    logger.debug(f"Found serious pattern '{pattern}' in: {error.line[:100]}")
                    return True
        
        # No serious issues found
        logger.debug("No serious issues found in UNSTABLE build")
        return False
    
    def _check_parsed_log(self, parsed_log: ParsedLog) -> Optional[HybridAnalysisResult]:
        """
        Check if parsed log has actionable errors (Requirement 14.8, 14.11).
        
        Filters out noise patterns and returns skipped result if no real errors.
        """
        # Req 14.8: Check for presence of errors/traces/failed stage
        has_traces = bool(parsed_log.stack_traces)
        has_failed_stage = parsed_log.failed_stage is not None
        
        # Req 14.11: Filter out noise patterns from errors
        actionable_errors = self._filter_noise_errors(parsed_log.errors)
        has_actionable_errors = bool(actionable_errors)
        
        if not has_actionable_errors and not has_traces and not has_failed_stage:
            if parsed_log.errors:
                # We had errors but they were all noise
                logger.warning(f"Found {len(parsed_log.errors)} errors but all were noise patterns - skipping analysis")
            else:
                logger.info("No actionable errors found in log")
            
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                result=None,
                skipped=True,
                skip_reason="No actionable errors detected in build log",
            )
        
        return None  # Proceed with analysis
    
    def _filter_noise_errors(self, errors: List) -> List:
        """
        Filter out noise/non-actionable errors (Requirement 14.11).
        
        Returns list of actionable errors only.
        """
        if not errors:
            return []
        
        # Noise patterns - these are common log lines that aren't real errors
        noise_patterns = [
            # Download/progress indicators
            r'downloading:',
            r'downloaded:',
            r'progress[\s:]*\d',
            r'\[\d+/\d+\]',  # [1/10] style progress
            r'^\s*\d+%',  # Percentage indicators
            # Git/SCM noise
            r'checking out',
            r'cloning into',
            r'fetching',
            # Jenkins Pipeline markers (not errors)
            r'\[pipeline\]\s*(sh|stage|node|checkout)',
            r'\[pipeline\]\s*\{',
            r'\[pipeline\]\s*\}',
            r'^\s*\+\s*[\w-]+$',  # Just a command name with no content
            # Build tool info messages
            r'^\[info\]',
            r'^info:',
            r'build started',
            r'build finished',
            # Test framework noise
            r'tests? (run|passed|skipped)',
            r'test suite',
            r'running \d+ test',
        ]
        
        actionable = []
        for error in errors:
            error_lower = error.line.lower().strip()
            
            # Skip empty or very short lines
            if len(error_lower) < 5:
                continue
            
            # Check against noise patterns
            is_noise = False
            for pattern in noise_patterns:
                if re.search(pattern, error_lower):
                    is_noise = True
                    break
            
            if not is_noise:
                actionable.append(error)
        
        return actionable
    
    def should_use_agentic(
        self,
        category: str,
        primary_error: str,
        parsed_log: ParsedLog,
    ) -> bool:
        """
        Determine if agentic investigation would be beneficial.
        
        Args:
            category: Failure category
            primary_error: Primary error message
            parsed_log: Parsed log data
            
        Returns:
            True if agentic investigation should be used.
        """
        # Check category
        if category in AGENTIC_CATEGORIES:
            logger.info(f"Category {category} triggers agentic mode")
            return True
        
        # Check error patterns
        error_text = primary_error.lower()
        for pattern in AGENTIC_ERROR_PATTERNS:
            if pattern.lower() in error_text:
                logger.info(f"Error pattern '{pattern}' triggers agentic mode")
                return True
        
        # Check if there are library-related errors in the log
        groovy_categories = {
            FailureCategory.GROOVY_LIBRARY,
            FailureCategory.GROOVY_CPS,
            FailureCategory.GROOVY_SANDBOX,
            FailureCategory.GROOVY_SERIALIZATION,
        }
        groovy_errors = [e for e in parsed_log.errors if e.category in groovy_categories]
        if groovy_errors:
            for error in groovy_errors:
                if any(p.lower() in error.line.lower() for p in AGENTIC_ERROR_PATTERNS):
                    logger.info("Groovy errors in log trigger agentic mode")
                    return True
        
        return False
    
    def analyze(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog,
        test_results: Optional[TestResult] = None,
        git_analysis: Optional[GitAnalysis] = None,
        console_log_snippet: str = "",
        jenkinsfile_content: str = None,
        library_sources: Dict[str, str] = None,
        deep: bool = False,  # Req 5.8: --deep flag
        pr_url: str = None,
        user_hint: str = None,  # Req 18.1: Optional user hint
    ) -> HybridAnalysisResult:
        """
        Analyze a build failure.
        
        Per Requirement 5: Only two modes:
        - iterative (default): Multi-call AI with source pre-loading
        - deep: Full MCP tool investigation
        
        Per Requirement 14: Pre-check build status before analysis.
        Per Requirement 18: Accept user_hint for focused analysis.
        
        Args:
            build_info: Jenkins build information
            parsed_log: Parsed log data
            test_results: Test results if available
            git_analysis: Git analysis if available
            console_log_snippet: Relevant console log snippet
            jenkinsfile_content: Jenkinsfile content if available
            library_sources: Library source code if available
            deep: Use deep investigation mode (Req 5.8)
            pr_url: PR URL for posting results
            user_hint: Optional user hint for focused analysis (Req 18.1)
            
        Returns:
            HybridAnalysisResult with analysis findings.
        """
        job_build = f"{build_info.job_name}#{build_info.build_number}"
        mode = AnalysisMode.DEEP if deep else AnalysisMode.ITERATIVE
        
        # Req 18.8: Truncate user_hint to 500 characters
        if user_hint and len(user_hint) > 500:
            logger.debug(f"User hint truncated from {len(user_hint)} to 500 characters")
            user_hint = user_hint[:500]
        
        logger.info(f"Starting {mode.value} analysis for {job_build}")
        if user_hint:
            logger.info(f"User hint provided: {user_hint[:100]}...")
        
        # Requirement 14.1-14.6: Pre-check build status (with UNSTABLE handling)
        skip_result = self._check_build_status(build_info, parsed_log, user_hint)
        if skip_result:
            return skip_result
        
        # Requirement 14.8: Check for actual errors (skip if user_hint provided)
        if not user_hint:
            skip_result = self._check_parsed_log(parsed_log)
            if skip_result:
                return skip_result
        
        # Requirement 6.4: Check if RC analyzer is disabled
        if not deep and not self.config.rc_analyzer.enabled:
            logger.info("RC analyzer disabled in config, using deep mode")
            mode = AnalysisMode.DEEP
            deep = True
        
        if deep:
            # Deep mode: Use Investigator with MCP tools
            return self._run_deep_analysis(
                build_info=build_info,
                parsed_log=parsed_log,
                console_log_snippet=console_log_snippet,
                pr_url=pr_url,
                user_hint=user_hint,
            )
        else:
            # Iterative mode (default): Use RCAnalyzer
            return self._run_iterative_analysis(
                build_info=build_info,
                parsed_log=parsed_log,
                console_log_snippet=console_log_snippet,
                jenkinsfile_content=jenkinsfile_content,
                library_sources=library_sources,
                user_hint=user_hint,
            )
    
    def _run_iterative_analysis(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog,
        console_log_snippet: str,
        jenkinsfile_content: str = None,
        library_sources: Dict[str, str] = None,
        user_hint: str = None,
    ) -> HybridAnalysisResult:
        """Run iterative RC analysis (Requirement 5.2)."""
        from .rc_finder import RootCauseFinder
        from .groovy_analyzer import GroovyAnalyzer
        
        logger.info("Running iterative RC analysis")
        
        try:
            # Get focused context from RootCauseFinder
            # Pass tool_invocations if available (Req 17.5)
            rc_finder = RootCauseFinder({
                'method_execution_prefix': self.config.parsing.method_execution_prefix
            })
            tool_invocations = getattr(parsed_log, 'tool_invocations', None)
            rc_context = rc_finder.find(console_log_snippet or "", tool_invocations)
            
            # Req 19.9: Cross-reference method execution trace with source code
            if parsed_log and hasattr(parsed_log, 'method_execution_trace') and parsed_log.method_execution_trace:
                if jenkinsfile_content or library_sources:
                    groovy_analyzer = GroovyAnalyzer()
                    source_invocations = groovy_analyzer.analyze_source_for_tools(
                        jenkinsfile_content=jenkinsfile_content,
                        library_sources=library_sources,
                    )
                    if source_invocations:
                        from .log_parser import LogParser
                        log_parser = LogParser(vars(self.config.parsing))
                        parsed_log.method_execution_trace = log_parser.cross_reference_trace_with_source(
                            parsed_log.method_execution_trace,
                            source_invocations,
                        )
            
            # Run RC analyzer (Req 18.4: pass user_hint)
            rc_result = self.rc_analyzer.analyze(
                parsed_log=parsed_log,
                rc_context=rc_context,
                build_info={
                    "job_name": build_info.job_name,
                    "build_number": build_info.build_number,
                    "status": build_info.status,  # Include status for UNSTABLE labeling
                },
                jenkinsfile_content=jenkinsfile_content,
                library_sources=library_sources,
                user_hint=user_hint,
            )
            
            # Convert RC result to AnalysisResult
            analysis_result = self._rc_result_to_analysis_result(rc_result, build_info, parsed_log)
            
            # Req 18.7, 19.10: Store metadata in result
            if analysis_result:
                if not hasattr(analysis_result, 'metadata') or analysis_result.metadata is None:
                    analysis_result.metadata = {}
                
                # Req 18.7: Store user_hint
                if user_hint:
                    analysis_result.metadata['user_hint'] = user_hint
                
                # Req 19.10: Store method_execution_trace
                if parsed_log and hasattr(parsed_log, 'method_execution_trace') and parsed_log.method_execution_trace:
                    analysis_result.metadata['method_execution_trace'] = parsed_log.method_execution_trace.to_dict()
            
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                result=analysis_result,
                iterations_used=rc_result.iterations_used,
                source_files_fetched=rc_result.source_files_fetched,
            )
            
        except Exception as e:
            logger.error(f"Iterative analysis failed: {e}")
            # Requirement 5.5: Return partial result on failure
            return self._create_fallback_result(build_info, parsed_log, str(e))
    
    def _run_deep_analysis(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog,
        console_log_snippet: str,
        pr_url: str = None,
        user_hint: str = None,
    ) -> HybridAnalysisResult:
        """Run deep investigation with MCP tools (Requirement 5.3)."""
        logger.info("Running deep MCP investigation")
        
        # Get primary error info
        primary_error = ""
        if parsed_log.errors:
            primary_error = parsed_log.errors[0].line
        
        category = parsed_log.primary_category.value if parsed_log.primary_category else "UNKNOWN"
        failed_stage = parsed_log.failed_stage or ""
        
        # Req 18: Include user_hint in initial_error context
        initial_context = primary_error or console_log_snippet[:500]
        if user_hint:
            initial_context = f"USER HINT: {user_hint}\n\nERROR: {initial_context}"
        
        try:
            investigation = self.investigator.investigate(
                job=build_info.job_name,
                build=build_info.build_number,
                initial_error=initial_context,
                error_category=category,
                failed_stage=failed_stage,
                pr_url=pr_url,
            )
            
            # Convert investigation to AnalysisResult
            analysis_result = self._investigation_to_analysis_result(investigation, build_info, parsed_log)
            
            # Req 18.7: Store user_hint in result metadata
            if user_hint and analysis_result:
                if not hasattr(analysis_result, 'metadata'):
                    analysis_result.metadata = {}
                analysis_result.metadata['user_hint'] = user_hint
            
            return HybridAnalysisResult(
                mode=AnalysisMode.DEEP,
                result=analysis_result,
                tool_calls_made=investigation.tool_calls_made,
            )
            
        except Exception as e:
            logger.error(f"Deep investigation failed: {e}")
            return self._create_fallback_result(build_info, parsed_log, str(e))
    
    def _rc_result_to_analysis_result(self, rc_result, build_info: BuildInfo, parsed_log: ParsedLog) -> AnalysisResult:
        """Convert RCAnalysisResult to AnalysisResult format."""
        category = rc_result.category or "UNKNOWN"
        tier = CATEGORY_TO_TIER.get(category, "unknown")
        
        # Build failure_analysis with failing_tool if available
        failure_analysis = {
            "category": category,
            "primary_error": rc_result.root_cause[:200] if rc_result.root_cause else "",
            "failed_stage": parsed_log.failed_stage,
            "confidence": rc_result.confidence,
            "tier": tier,
        }
        
        # Include failing tool info for UI display
        if hasattr(rc_result, 'failing_tool') and rc_result.failing_tool:
            failure_analysis["failing_tool"] = rc_result.failing_tool
        
        # Build metadata
        metadata = {}
        if hasattr(rc_result, 'failing_tool') and rc_result.failing_tool:
            metadata["failing_tool"] = rc_result.failing_tool
        
        return AnalysisResult(
            build_info={
                "job_name": build_info.job_name,
                "build_number": build_info.build_number,
                "status": build_info.status,
            },
            failure_analysis=failure_analysis,
            root_cause=RootCause(
                summary=rc_result.root_cause,
                details=rc_result.fix or "",
                confidence=rc_result.confidence,
                category=category,
                tier=tier,
            ),
            retry_assessment=RetryAssessment(
                is_retriable=rc_result.is_retriable,
                confidence=rc_result.confidence,
                reason=rc_result.root_cause[:100] if rc_result.root_cause else "",
            ),
            recommendations=[
                Recommendation(priority="HIGH", action=rc_result.fix, rationale=rc_result.root_cause[:100])
            ] if rc_result.fix else [],
            metadata=metadata,
        )
    
    def _investigation_to_analysis_result(self, investigation, build_info: BuildInfo, parsed_log: ParsedLog) -> AnalysisResult:
        """Convert Investigation result to AnalysisResult format."""
        category = parsed_log.primary_category.value if parsed_log.primary_category else "UNKNOWN"
        tier = CATEGORY_TO_TIER.get(category, "unknown")
        
        return AnalysisResult(
            build_info={
                "job_name": build_info.job_name,
                "build_number": build_info.build_number,
                "status": build_info.status,
            },
            failure_analysis={
                "category": category,
                "primary_error": investigation.root_cause[:200] if investigation.root_cause else "",
                "failed_stage": parsed_log.failed_stage,
                "confidence": investigation.confidence,
                "tier": tier,
            },
            root_cause=RootCause(
                summary=investigation.root_cause or "Unable to determine root cause",
                details=investigation.details or "",
                confidence=investigation.confidence,
                category=category,
                tier=tier,
            ),
            retry_assessment=RetryAssessment(
                is_retriable=False,
                confidence=investigation.confidence,
                reason=investigation.root_cause[:100] if investigation.root_cause else "",
            ),
            recommendations=[
                Recommendation(priority="HIGH", action=rec, rationale="")
                for rec in (investigation.recommendations or [])
            ],
        )
    
    def _create_fallback_result(self, build_info: BuildInfo, parsed_log: ParsedLog, error: str) -> HybridAnalysisResult:
        """Create a fallback result when analysis fails (Requirement 5.5)."""
        category = parsed_log.primary_category.value if parsed_log.primary_category else "UNKNOWN"
        primary_error = parsed_log.errors[0].line if parsed_log.errors else "Unknown error"
        
        return HybridAnalysisResult(
            mode=AnalysisMode.ITERATIVE,
            result=AnalysisResult(
                build_info={
                    "job_name": build_info.job_name,
                    "build_number": build_info.build_number,
                    "status": build_info.status,
                },
                failure_analysis={
                    "category": category,
                    "primary_error": primary_error,
                    "failed_stage": parsed_log.failed_stage,
                    "confidence": 0.3,
                    "tier": "unknown",
                    "analysis_error": error,
                },
                root_cause=RootCause(
                    summary=f"Analysis incomplete: {primary_error}",
                    details=f"Analysis error: {error}",
                    confidence=0.3,
                    category=category,
                    tier="unknown",
                ),
                retry_assessment=RetryAssessment(is_retriable=False, confidence=0.3, reason="Analysis incomplete"),
                recommendations=[],
            ),
            iterations_used=0,
        )
