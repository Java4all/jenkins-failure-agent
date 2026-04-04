"""
Jenkins Failure Analysis Agent

An autonomous AI-powered debugging assistant for Jenkins build failures.
Specializes in Groovy/Pipeline, shared library, and configuration error analysis.

Supports multiple analysis modes:
- Scripted: Fast, single LLM call for simple failures (default)
- Iterative: Multi-call analysis with source code context (recommended)
- Agentic: Deep investigation with MCP tools for code/library issues
"""

__version__ = "1.9.21"

from .config import (
    Config, JenkinsConfig, AIConfig, GitConfig, GitHubConfig,
    SCMConfig, ReporterConfig, RCAnalyzerConfig, SourceLocation
)
from .jenkins_client import JenkinsClient, BuildInfo, TestResult
from .log_parser import (
    LogParser, ParsedLog, FailureCategory, ToolInvocation,
    PipelineLineType, TraceStep, MethodExecutionTrace
)
from .git_analyzer import GitAnalyzer, GitAnalysis
from .github_client import GitHubClient, GitHubConfig as GitHubClientConfig, FetchResult
from .groovy_analyzer import GroovyAnalyzer, GroovyAnalysis, GroovyFailureType, SourceToolInvocation
from .config_analyzer import ConfigurationAnalyzer, ConfigurationAnalysis, ConfigFailureType
from .ai_analyzer import (
    AIAnalyzer, AnalysisResult, result_to_dict,
    FailureTier, RetryAssessment, CATEGORY_TO_TIER
)
from .report_generator import ReportGenerator, format_slack_message
from .scm_client import SCMClient, SCMProvider, PRInfo, format_pr_comment
from .hybrid_analyzer import HybridAnalyzer, HybridAnalysisResult, AnalysisMode
from .rc_finder import RootCauseFinder, RootCauseContext, ErrorType, find_root_cause
from .rc_analyzer import RCAnalyzer, RCAnalysisResult, IterationResult
from .iterative_analyzer import IterativeRCAnalyzer, InvestigationResult, InvestigationAction
from .feedback_store import FeedbackStore, FeedbackEntry, get_feedback_store

__all__ = [
    # Config
    "Config", "JenkinsConfig", "AIConfig", "GitConfig", "GitHubConfig",
    "SCMConfig", "ReporterConfig", "RCAnalyzerConfig", "SourceLocation",
    # Jenkins
    "JenkinsClient", "BuildInfo", "TestResult",
    # Log parsing
    "LogParser", "ParsedLog", "FailureCategory", "ToolInvocation",
    "PipelineLineType", "TraceStep", "MethodExecutionTrace",
    # Git analysis
    "GitAnalyzer", "GitAnalysis",
    # GitHub code fetching
    "GitHubClient", "GitHubClientConfig", "FetchResult",
    # Groovy analysis
    "GroovyAnalyzer", "GroovyAnalysis", "GroovyFailureType", "SourceToolInvocation",
    # Configuration analysis
    "ConfigurationAnalyzer", "ConfigurationAnalysis", "ConfigFailureType",
    # AI analysis
    "AIAnalyzer", "AnalysisResult", "result_to_dict",
    "FailureTier", "RetryAssessment", "CATEGORY_TO_TIER",
    # Hybrid analysis (iterative + deep modes)
    "HybridAnalyzer", "HybridAnalysisResult", "AnalysisMode",
    # Root Cause Finder Expert
    "RootCauseFinder", "RootCauseContext", "ErrorType", "find_root_cause",
    # RC Analyzer (iterative multi-call analysis)
    "RCAnalyzer", "RCAnalysisResult", "IterationResult",
    # Iterative analysis (legacy, use RCAnalyzer instead)
    "IterativeRCAnalyzer", "InvestigationResult", "InvestigationAction",
    # Feedback Store (Requirement 15)
    "FeedbackStore", "FeedbackEntry", "get_feedback_store",
    # Reports
    "ReportGenerator", "format_slack_message",
    # SCM (GitHub/GitLab)
    "SCMClient", "SCMProvider", "PRInfo", "format_pr_comment",
]
