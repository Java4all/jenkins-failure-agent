"""
Jenkins Failure Analysis Agent

An autonomous AI-powered debugging assistant for Jenkins build failures.
Specializes in Groovy/Pipeline, shared library, and configuration error analysis.

Supports multiple analysis modes:
- Scripted: Fast, single LLM call for simple failures (default)
- Iterative: Multi-call analysis with source code context (recommended)
- Agentic: Deep investigation with MCP tools for code/library issues

Supports multiple AI providers:
- OpenAI-compatible: Ollama, vLLM, LocalAI, OpenAI API
- AWS Bedrock: Claude, Titan, Llama, Mistral
"""

__version__ = "2.0.0"

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
from .ai_provider import (
    AIProvider, OpenAICompatibleProvider, BedrockProvider,
    ChatMessage, ChatResponse, create_ai_provider, get_provider_from_config
)
from .report_generator import ReportGenerator, format_slack_message
from .scm_client import SCMClient, SCMProvider, PRInfo, format_pr_comment
from .hybrid_analyzer import HybridAnalyzer, HybridAnalysisResult, AnalysisMode
from .rc_finder import RootCauseFinder, RootCauseContext, ErrorType, find_root_cause
from .rc_analyzer import RCAnalyzer, RCAnalysisResult, IterationResult
from .iterative_analyzer import IterativeRCAnalyzer, InvestigationResult, InvestigationAction
from .feedback_store import FeedbackStore, FeedbackEntry, get_feedback_store
from .knowledge_store import (
    KnowledgeStore, ToolDefinition, ToolError, ToolArgument,
    KnowledgeDoc, SourceAnalysisLog, get_knowledge_store
)
from .java_analyzer import (
    JavaSourceAnalyzer, AnalysisResult as JavaAnalysisResult,
    ExtractedCommand, ExtractedError, analyze_java_source
)
from .doc_importer import (
    DocImporter, ExtractedDocInfo, import_documentation
)
from .training_pipeline import (
    TrainingPipeline, TrainingExample, TrainingJob,
    TrainingFormat, TrainingJobStatus, get_training_pipeline
)
from .splunk_connector import (
    SplunkConnector, SplunkConfig, FailedBuild, get_splunk_connector
)
from .review_queue import (
    ReviewQueue, ReviewItem, ReviewStatus, get_review_queue
)

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
    # AI Provider abstraction
    "AIProvider", "OpenAICompatibleProvider", "BedrockProvider",
    "ChatMessage", "ChatResponse", "create_ai_provider", "get_provider_from_config",
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
    # Knowledge Store (AI Learning System)
    "KnowledgeStore", "ToolDefinition", "ToolError", "ToolArgument",
    "KnowledgeDoc", "SourceAnalysisLog", "get_knowledge_store",
    # Java Source Analyzer (Phase 2A)
    "JavaSourceAnalyzer", "JavaAnalysisResult", "ExtractedCommand",
    "ExtractedError", "analyze_java_source",
    # Doc Importer (Phase 2C)
    "DocImporter", "ExtractedDocInfo", "import_documentation",
    # Training Pipeline (Phase 4)
    "TrainingPipeline", "TrainingExample", "TrainingJob",
    "TrainingFormat", "TrainingJobStatus", "get_training_pipeline",
    # Splunk Integration
    "SplunkConnector", "SplunkConfig", "FailedBuild", "get_splunk_connector",
    # Review Queue
    "ReviewQueue", "ReviewItem", "ReviewStatus", "get_review_queue",
    # Reports
    "ReportGenerator", "format_slack_message",
    # SCM (GitHub/GitLab)
    "SCMClient", "SCMProvider", "PRInfo", "format_pr_comment",
]
