"""
Jenkins Failure Analysis Agent

An autonomous AI-powered debugging assistant for Jenkins build failures.
Specializes in Groovy/Pipeline, shared library, and configuration error analysis.

Supports multiple analysis modes:
- Scripted: Fast, single LLM call for simple failures (default)
- Agentic: Deep investigation with MCP tools for code/library issues
- Iterative: Multi-cycle investigation with code lookup for complex failures
"""

__version__ = "1.4.0"

from .config import (
    Config, JenkinsConfig, AIConfig, GitConfig, GitHubConfig,
    SCMConfig, ReporterConfig
)
from .jenkins_client import JenkinsClient, BuildInfo, TestResult
from .log_parser import LogParser, ParsedLog, FailureCategory
from .git_analyzer import GitAnalyzer, GitAnalysis
from .github_client import GitHubClient, GitHubConfig as GitHubClientConfig, FetchResult
from .groovy_analyzer import GroovyAnalyzer, GroovyAnalysis, GroovyFailureType
from .config_analyzer import ConfigurationAnalyzer, ConfigurationAnalysis, ConfigFailureType
from .ai_analyzer import (
    AIAnalyzer, AnalysisResult, result_to_dict,
    FailureTier, RetryAssessment, CATEGORY_TO_TIER
)
from .report_generator import ReportGenerator, format_slack_message
from .scm_client import SCMClient, SCMProvider, PRInfo, format_pr_comment
from .hybrid_analyzer import HybridAnalyzer, HybridAnalysisResult, AnalysisMode
from .rc_finder import RootCauseFinder, RootCauseContext, ErrorType, find_root_cause
from .iterative_analyzer import IterativeRCAnalyzer, InvestigationResult, InvestigationAction

__all__ = [
    # Config
    "Config", "JenkinsConfig", "AIConfig", "GitConfig", "GitHubConfig",
    "SCMConfig", "ReporterConfig",
    # Jenkins
    "JenkinsClient", "BuildInfo", "TestResult",
    # Log parsing
    "LogParser", "ParsedLog", "FailureCategory",
    # Git analysis
    "GitAnalyzer", "GitAnalysis",
    # GitHub code fetching
    "GitHubClient", "GitHubClientConfig", "FetchResult",
    # Groovy analysis
    "GroovyAnalyzer", "GroovyAnalysis", "GroovyFailureType",
    # Configuration analysis
    "ConfigurationAnalyzer", "ConfigurationAnalysis", "ConfigFailureType",
    # AI analysis (scripted)
    "AIAnalyzer", "AnalysisResult", "result_to_dict",
    "FailureTier", "RetryAssessment", "CATEGORY_TO_TIER",
    # Hybrid analysis (scripted + agentic)
    "HybridAnalyzer", "HybridAnalysisResult", "AnalysisMode",
    # Root Cause Finder Expert
    "RootCauseFinder", "RootCauseContext", "ErrorType", "find_root_cause",
    # Iterative analysis (multi-cycle investigation)
    "IterativeRCAnalyzer", "InvestigationResult", "InvestigationAction",
    # Reports
    "ReportGenerator", "format_slack_message",
    # SCM (GitHub/GitLab)
    "SCMClient", "SCMProvider", "PRInfo", "format_pr_comment",
]
