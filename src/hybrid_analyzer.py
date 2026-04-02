"""
Hybrid analyzer that combines scripted and agentic investigation modes.

This module provides a unified interface that:
1. Uses fast scripted analysis for simple failures (80% of cases)
2. Triggers deep agentic investigation for code/library issues (20% of cases)
3. Merges results from both approaches

The hybrid approach gives the best of both worlds:
- Speed and efficiency for common failures
- Deep investigation capabilities for complex code issues
"""

import logging
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
    """Analysis mode used."""
    SCRIPTED = "scripted"           # Fast, single LLM call
    ITERATIVE = "iterative"         # Multi-call iterative RC analysis
    AGENTIC = "agentic"             # Deep investigation with tool calls
    HYBRID = "hybrid"               # Scripted + Agentic enhancement


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
    """Result from hybrid analysis."""
    mode: AnalysisMode
    scripted_result: Optional[AnalysisResult]
    agentic_result: Optional[Dict[str, Any]]
    merged_result: AnalysisResult
    agentic_enhanced: bool = False
    tool_calls_made: int = 0
    investigation_tokens: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        base = result_to_dict(self.merged_result)
        base["analysis_mode"] = self.mode.value
        base["agentic_enhanced"] = self.agentic_enhanced
        if self.agentic_enhanced:
            base["investigation_details"] = {
                "tool_calls_made": self.tool_calls_made,
                "tokens_used": self.investigation_tokens,
            }
        return base


class HybridAnalyzer:
    """
    Hybrid analyzer that combines scripted and agentic analysis.
    
    Usage:
        analyzer = HybridAnalyzer(config)
        
        # Automatic mode selection
        result = analyzer.analyze(
            build_info=build_info,
            parsed_log=parsed_log,
            test_results=test_results,
        )
        
        # Force agentic mode
        result = analyzer.analyze(..., force_agentic=True)
        
        # Force scripted mode only
        result = analyzer.analyze(..., force_scripted=True)
    """
    
    def __init__(self, config: Config):
        """
        Initialize hybrid analyzer.
        
        Args:
            config: Full configuration object
        """
        self.config = config
        self.ai_config = config.ai
        
        # Initialize scripted analyzer (always available)
        self.scripted_analyzer = AIAnalyzer(config.ai)
        
        # Initialize agentic investigator (lazy - only when needed)
        self._investigator = None
        self._clients_set = False
        
        # Clients that may be set later
        self.jenkins_client: Optional[JenkinsClient] = None
        self.github_client = None
        self.scm_client = None
        
        logger.info("HybridAnalyzer initialized")
    
    def set_clients(
        self,
        jenkins_client: JenkinsClient = None,
        github_client = None,
        scm_client = None,
    ):
        """
        Set client instances for agentic investigation.
        
        Args:
            jenkins_client: Jenkins API client
            github_client: GitHub client for source code
            scm_client: SCM client for PR comments
        """
        self.jenkins_client = jenkins_client
        self.github_client = github_client
        self.scm_client = scm_client
        self._clients_set = True
    
    @property
    def investigator(self):
        """Lazy initialization of agentic investigator."""
        if self._investigator is None:
            from .agent import Investigator
            self._investigator = Investigator(self.ai_config)
            
            # Set clients if available
            if self._clients_set:
                self._investigator.set_clients(
                    jenkins_client=self.jenkins_client,
                    github_client=self.github_client,
                    scm_client=self.scm_client,
                )
        
        return self._investigator
    
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
        force_agentic: bool = False,
        force_scripted: bool = False,
        force_iterative: bool = False,
        pr_url: str = None,
    ) -> HybridAnalysisResult:
        """
        Analyze a build failure using hybrid approach.
        
        Args:
            build_info: Jenkins build information
            parsed_log: Parsed log data
            test_results: Test results if available
            git_analysis: Git analysis if available
            console_log_snippet: Relevant console log snippet
            jenkinsfile_content: Jenkinsfile content if available
            library_sources: Library source code if available
            force_agentic: Force agentic investigation regardless of category
            force_scripted: Force scripted-only mode
            force_iterative: Force iterative RC analysis (Requirement 5.2)
            pr_url: PR URL for posting results
            
        Returns:
            HybridAnalysisResult with merged findings.
        """
        logger.info(f"Starting hybrid analysis for {build_info.job_name}#{build_info.build_number}")
        
        # Phase 1: Always run scripted analysis first (fast baseline)
        logger.info("Phase 1: Running scripted analysis")
        scripted_result = self.scripted_analyzer.analyze(
            build_info=build_info,
            parsed_log=parsed_log,
            test_results=test_results,
            git_analysis=git_analysis,
            console_log_snippet=console_log_snippet,
            jenkinsfile_content=jenkinsfile_content,
            library_sources=library_sources,
        )
        
        # Get category and primary error
        category = scripted_result.failure_analysis.get("category", "UNKNOWN")
        primary_error = scripted_result.failure_analysis.get("primary_error", "")
        failed_stage = scripted_result.failure_analysis.get("failed_stage", "")
        
        logger.info(f"Scripted analysis complete: {category}, confidence={scripted_result.failure_analysis.get('confidence', 0):.2f}")
        
        # Check if iterative RC analysis should be used (Requirement 5)
        use_iterative = self._should_use_iterative(
            force_iterative=force_iterative,
            force_scripted=force_scripted,
            category=category,
            scripted_confidence=scripted_result.failure_analysis.get('confidence', 0),
        )
        
        if use_iterative:
            return self._run_iterative_analysis(
                build_info=build_info,
                parsed_log=parsed_log,
                scripted_result=scripted_result,
                console_log_snippet=console_log_snippet,
                jenkinsfile_content=jenkinsfile_content,
                library_sources=library_sources,
            )
        
        # Phase 2: Decide if agentic investigation is needed
        use_agentic = (
            force_agentic or 
            (
                not force_scripted and
                self._clients_set and
                self.should_use_agentic(category, primary_error, parsed_log)
            )
        )
        
        if not use_agentic:
            logger.info("Skipping agentic investigation (not needed or not configured)")
            return HybridAnalysisResult(
                mode=AnalysisMode.SCRIPTED,
                scripted_result=scripted_result,
                agentic_result=None,
                merged_result=scripted_result,
                agentic_enhanced=False,
            )
        
        # Phase 3: Run agentic investigation
        logger.info("Phase 2: Running agentic investigation")
        
        try:
            investigation = self.investigator.investigate(
                job=build_info.job_name,
                build=build_info.build_number,
                initial_error=primary_error or console_log_snippet[:500],
                error_category=category,
                failed_stage=failed_stage,
                pr_url=pr_url,
            )
            
            agentic_result = investigation.to_dict()
            
            logger.info(f"Agentic investigation complete: {investigation.tool_calls_made} tool calls, {investigation.status.value}")
            
            # Phase 4: Merge results
            merged = self._merge_results(scripted_result, investigation)
            
            return HybridAnalysisResult(
                mode=AnalysisMode.HYBRID,
                scripted_result=scripted_result,
                agentic_result=agentic_result,
                merged_result=merged,
                agentic_enhanced=True,
                tool_calls_made=investigation.tool_calls_made,
                investigation_tokens=investigation.tokens_used,
            )
            
        except Exception as e:
            logger.error(f"Agentic investigation failed: {e}")
            logger.info("Falling back to scripted result")
            
            return HybridAnalysisResult(
                mode=AnalysisMode.SCRIPTED,
                scripted_result=scripted_result,
                agentic_result={"error": str(e)},
                merged_result=scripted_result,
                agentic_enhanced=False,
            )
    
    def _merge_results(
        self,
        scripted: AnalysisResult,
        investigation,
    ) -> AnalysisResult:
        """
        Merge scripted and agentic results.
        
        Agentic results are preferred when:
        - They have higher confidence
        - They provide more specific information (evidence, exact fixes)
        
        Scripted results are kept for:
        - Groovy/Config analysis details
        - Metadata
        
        Args:
            scripted: Result from scripted analysis
            investigation: Result from agentic investigation
            
        Returns:
            Merged AnalysisResult.
        """
        from .agent import InvestigationStatus
        
        # Start with scripted result as base
        merged = scripted
        
        # If agentic succeeded and has good confidence, enhance the result
        if (investigation.status == InvestigationStatus.COMPLETED and 
            investigation.confidence >= 0.6):
            
            # Update root cause if agentic has better info
            if investigation.root_cause and investigation.confidence > scripted.root_cause.confidence:
                merged.root_cause = RootCause(
                    summary=investigation.root_cause,
                    details=investigation.details or scripted.root_cause.details,
                    confidence=investigation.confidence,
                    category=merged.failure_analysis.get("category", "UNKNOWN"),
                    tier=merged.failure_analysis.get("tier", "unknown"),
                    related_commits=scripted.root_cause.related_commits,
                    affected_files=scripted.root_cause.affected_files,
                )
                
                # Add evidence from investigation
                if investigation.evidence:
                    merged.root_cause.details += "\n\n**Investigation Evidence:**\n"
                    for ev in investigation.evidence:
                        merged.root_cause.details += f"- {ev}\n"
            
            # Merge recommendations
            if investigation.recommendations:
                # Add agentic recommendations as high priority
                new_recs = []
                
                # Filter out useless recommendations
                useless_phrases = ["review the", "check the", "investigate", "look at", "see above", "examine", "manual investigation"]
                
                for rec in investigation.recommendations:
                    # Skip useless recommendations
                    if any(u in rec.lower() for u in useless_phrases):
                        continue
                    # Skip very short recommendations
                    if len(rec) < 15:
                        continue
                        
                    new_recs.append(Recommendation(
                        priority="HIGH",
                        action=rec,
                        rationale=f"Based on code investigation: {investigation.root_cause[:100]}" if investigation.root_cause else "",
                    ))
                
                # Keep scripted recommendations that aren't duplicates (only if we have few agentic ones)
                if len(new_recs) < 3:
                    existing_actions = {r.action.lower() for r in new_recs}
                    for rec in merged.recommendations:
                        if rec.action.lower() not in existing_actions:
                            # Skip useless scripted recommendations too
                            if any(u in rec.action.lower() for u in useless_phrases):
                                continue
                            new_recs.append(rec)
                
                if new_recs:
                    merged.recommendations = new_recs[:5]  # Limit total
            
            # Update retry assessment
            if investigation.is_retriable != (merged.retry_assessment and merged.retry_assessment.is_retriable):
                merged.retry_assessment = RetryAssessment(
                    is_retriable=investigation.is_retriable,
                    confidence=investigation.confidence,
                    reason=investigation.root_cause[:200],
                    recommended_wait_seconds=60 if investigation.is_retriable else 0,
                    max_retries=2 if investigation.is_retriable else 0,
                )
        
        # Mark as agentic-enhanced in metadata
        merged.failure_analysis["agentic_enhanced"] = True
        merged.failure_analysis["investigation_confidence"] = investigation.confidence
        
        return merged
    
    def test_connection(self) -> bool:
        """Test if the analyzer is properly configured."""
        return self.scripted_analyzer.test_connection()
    
    def _should_use_iterative(
        self,
        force_iterative: bool,
        force_scripted: bool,
        category: str,
        scripted_confidence: float,
    ) -> bool:
        """
        Determine if iterative RC analysis should be used.
        
        Implements Requirement 5.2, 5.3, 5.4
        """
        # Check if RC analyzer is enabled
        if not hasattr(self.config, 'rc_analyzer') or not self.config.rc_analyzer.enabled:
            return False
        
        # Force flags (Requirement 5.2)
        if force_iterative:
            logger.info("Using iterative mode: force_iterative=True")
            return True
        
        if force_scripted:
            return False
        
        # Auto-select for AGENTIC_CATEGORIES (Requirement 5.3)
        if category in AGENTIC_CATEGORIES:
            logger.info(f"Using iterative mode: category {category} in AGENTIC_CATEGORIES")
            return True
        
        # Use iterative if scripted confidence is low
        if scripted_confidence < 0.5:
            logger.info(f"Using iterative mode: low scripted confidence {scripted_confidence}")
            return True
        
        return False
    
    def _run_iterative_analysis(
        self,
        build_info: BuildInfo,
        parsed_log: ParsedLog,
        scripted_result: AnalysisResult,
        console_log_snippet: str,
        jenkinsfile_content: str,
        library_sources: Dict[str, str],
    ) -> HybridAnalysisResult:
        """
        Run iterative RC analysis.
        
        Implements Requirement 5.4: Merge into HybridAnalysisResult
        Implements Requirement 5.5: Catch exceptions and fallback
        """
        logger.info("Running iterative RC analysis")
        
        try:
            from .rc_analyzer import RCAnalyzer, RCAnalyzerConfig
            from .rc_finder import RootCauseFinder
            
            # Create RC context using existing RootCauseFinder
            rc_finder = RootCauseFinder(self.config.__dict__ if hasattr(self.config, '__dict__') else {})
            rc_context = rc_finder.find(console_log_snippet)
            
            # Create RC analyzer config from main config
            rc_config = RCAnalyzerConfig(
                enabled=self.config.rc_analyzer.enabled if hasattr(self.config, 'rc_analyzer') else True,
                max_rc_iterations=self.config.rc_analyzer.max_rc_iterations if hasattr(self.config, 'rc_analyzer') else 3,
                confidence_threshold=self.config.rc_analyzer.confidence_threshold if hasattr(self.config, 'rc_analyzer') else 0.7,
                max_source_context_chars=self.config.rc_analyzer.max_source_context_chars if hasattr(self.config, 'rc_analyzer') else 8000,
            )
            
            # Create RC analyzer
            rc_analyzer = RCAnalyzer(
                ai_analyzer=self.scripted_analyzer,
                github_client=self.github_client,
                groovy_analyzer=None,  # TODO: Add groovy analyzer
                config=rc_config,
            )
            
            # Run iterative analysis
            rc_result = rc_analyzer.analyze(
                parsed_log=parsed_log,
                rc_context=rc_context,
                build_info={
                    'job_name': build_info.job_name,
                    'build_number': build_info.build_number,
                },
                jenkinsfile_content=jenkinsfile_content,
                library_sources=library_sources,
            )
            
            # Merge into scripted result (Requirement 5.4)
            merged = self._merge_iterative_result(scripted_result, rc_result)
            
            logger.info(f"Iterative analysis complete: {rc_result.iterations_used} iterations, "
                       f"confidence={rc_result.confidence}")
            
            return HybridAnalysisResult(
                mode=AnalysisMode.ITERATIVE,
                scripted_result=scripted_result,
                agentic_result=rc_result.to_dict(),
                merged_result=merged,
                agentic_enhanced=True,
                tool_calls_made=rc_result.iterations_used,
            )
            
        except Exception as e:
            # Requirement 5.5: Catch exception and fallback
            logger.error(f"Iterative analysis failed: {e}")
            logger.info("Falling back to scripted result")
            
            return HybridAnalysisResult(
                mode=AnalysisMode.SCRIPTED,
                scripted_result=scripted_result,
                agentic_result={"error": str(e)},
                merged_result=scripted_result,
                agentic_enhanced=False,
            )
    
    def _merge_iterative_result(
        self,
        scripted: AnalysisResult,
        rc_result,
    ) -> AnalysisResult:
        """
        Merge iterative RC analysis result into scripted result.
        
        Implements Requirement 5.4: Use existing _merge_results logic.
        """
        merged = scripted
        
        # If RC analysis has better confidence, use its root cause
        if rc_result.confidence > scripted.root_cause.confidence:
            merged.root_cause.summary = rc_result.root_cause
            merged.root_cause.confidence = rc_result.confidence
            merged.root_cause.category = rc_result.category
            
            if rc_result.fix:
                merged.root_cause.details = f"Fix: {rc_result.fix}"
        
        # Update failure analysis
        merged.failure_analysis["category"] = rc_result.category
        merged.failure_analysis["confidence"] = rc_result.confidence
        merged.failure_analysis["iterative_analysis"] = True
        merged.failure_analysis["iterations_used"] = rc_result.iterations_used
        merged.failure_analysis["source_files_fetched"] = rc_result.source_files_fetched
        
        # Add fix as recommendation
        if rc_result.fix:
            from .ai_analyzer import Recommendation
            fix_rec = Recommendation(
                action=rc_result.fix,
                priority="high",
                rationale=f"Based on {rc_result.iterations_used}-iteration analysis with {rc_result.confidence:.0%} confidence",
            )
            merged.recommendations = [fix_rec] + merged.recommendations[:4]
        
        # Update retry assessment
        merged.retry_assessment = RetryAssessment(
            is_retriable=rc_result.is_retriable,
            confidence=rc_result.confidence,
            reason=rc_result.root_cause[:200],
            recommended_wait_seconds=60 if rc_result.is_retriable else 0,
            max_retries=2 if rc_result.is_retriable else 0,
        )
        
        return merged
