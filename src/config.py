"""
Configuration loader for Jenkins Failure Analysis Agent
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class JenkinsConfig:
    url: str
    username: str
    api_token: str
    verify_ssl: bool = False
    timeout: int = 30
    monitored_jobs: List[str] = field(default_factory=list)


@dataclass
class AIConfig:
    # Provider: "openai_compatible" (default), "bedrock", "azure" (future)
    provider: str = "openai_compatible"
    # OpenAI-compatible settings
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3:8b"
    api_key: str = "ollama"
    # Common settings
    temperature: float = 0.1
    max_tokens: int = 4096
    # Combined system + user prompt soft cap (characters). Ollama often uses ~4096 *tokens*
    # context; long prompts trigger server-side truncation. We clip client-side first and log.
    max_prompt_chars: int = 9000
    timeout: int = 120
    max_retries: int = 3
    retry_delay: int = 5
    # AWS Bedrock settings
    region: str = ""  # AWS region (e.g., "us-east-1")
    profile: str = ""  # AWS profile name (from ~/.aws/credentials or ~/.aws/config)
    credentials_file: str = ""  # Custom path to AWS credentials file
    config_file: str = ""  # Custom path to AWS config file


@dataclass
class GitConfig:
    enabled: bool = True
    lookback_commits: int = 10
    clone_repos: bool = False
    clone_directory: str = "/tmp/jenkins-agent-repos"
    api: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GitHubConfig:
    """GitHub/GitHub Enterprise configuration for source code fetching."""
    enabled: bool = True
    # Base URL for GitHub API
    # GitHub.com: https://api.github.com
    # GitHub Enterprise: https://github.mycompany.com/api/v3
    base_url: str = "https://api.github.com"
    # Personal access token with repo read access
    token: str = ""
    # Request timeout in seconds
    timeout: int = 30
    # SSL verification (set False for self-signed certs)
    verify_ssl: bool = False
    # Cache settings
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    # Library name to repository mappings
    # e.g., {"my-lib": "org/jenkins-shared-library"}
    library_mappings: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParsingConfig:
    max_log_size: int = 10485760
    # Lines of shell output stored per ToolInvocation (default 30 in LogParser). Raise for richer command↔error linking.
    max_output_lines: int = 30
    error_context_lines: int = 10
    error_patterns: List[str] = field(default_factory=list)
    ignore_patterns: List[str] = field(default_factory=list)
    # Prefix for shared library method execution tracking
    # Pattern: "{prefix}: method_name"
    method_execution_prefix: str = ""
    # Requirement 17.7: Custom tool patterns for recognition
    # Each entry: {"name": "tool_name", "pattern": "regex_pattern"}
    tool_patterns: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class NotificationsConfig:
    slack: Dict[str, Any] = field(default_factory=dict)
    teams: Dict[str, Any] = field(default_factory=dict)
    email: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SCMConfig:
    """SCM (GitHub/GitLab) configuration for PR comments."""
    enabled: bool = False
    provider: str = "github"  # github or gitlab
    api_url: str = "https://api.github.com"  # or https://gitlab.com/api/v4
    token: str = ""
    verify_ssl: bool = False
    # Auto-post analysis to PRs
    auto_comment: bool = True
    # Update existing comment instead of creating new
    update_existing: bool = True
    # Set commit status
    set_commit_status: bool = True


@dataclass
class ReporterConfig:
    """Configuration for result reporting destinations."""
    # Update Jenkins build description
    update_jenkins_description: bool = True
    # Post to PR/MR
    post_to_pr: bool = True
    # Post to Slack
    post_to_slack: bool = False
    # Generate reports
    generate_reports: bool = True
    report_formats: List[str] = field(default_factory=lambda: ["json", "markdown"])


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    api_key_enabled: bool = True
    api_key: str = ""
    cors_origins: List[str] = field(default_factory=list)
    rate_limit: int = 100


@dataclass
class SourceLocation:
    """Configuration for a source file location (Req 9)."""
    type: str = "repo"  # "local_path", "repo", or "inline"
    value: str = ""     # Path, repo (owner/repo[@ref]), or content
    ref: str = "main"   # Git ref for repo type
    name: str = ""      # Optional label


@dataclass
class RCAnalyzerConfig:
    """Configuration for iterative RC Analyzer (Requirement 6, 9)."""
    enabled: bool = True
    max_rc_iterations: int = 3
    confidence_threshold: float = 0.7
    max_source_context_chars: int = 8000
    
    # Requirement 9: Source locations
    jenkinsfile_source: Optional[SourceLocation] = None
    library_sources: List[SourceLocation] = field(default_factory=list)
    
    # Requirement 10: Source registry (populated at runtime)
    source_registry: List[SourceLocation] = field(default_factory=list)


@dataclass
class Config:
    jenkins: JenkinsConfig
    ai: AIConfig
    git: GitConfig
    github: GitHubConfig
    parsing: ParsingConfig
    notifications: NotificationsConfig
    scm: SCMConfig
    reporter: ReporterConfig
    server: ServerConfig
    rc_analyzer: RCAnalyzerConfig
    categories: Dict[str, Any] = field(default_factory=dict)
    reporting: Dict[str, Any] = field(default_factory=dict)
    history: Dict[str, Any] = field(default_factory=dict)
    logging: Dict[str, Any] = field(default_factory=dict)
    # Global SSL verification (used as default for all HTTP clients)
    verify_ssl: bool = False


def load_config(config_path: Optional[str] = None, env_file: str = ".env") -> Config:
    """Load configuration from YAML file.
    
    Implements Requirement 12: Environment File Support
    
    Args:
        config_path: Path to config.yaml file
        env_file: Path to .env file (default: ".env")
    """
    # Load .env file first (Req 12.1)
    try:
        from dotenv import load_dotenv
        env_path = Path(env_file)
        if env_path.exists():
            load_dotenv(env_path)
        # Req 12.2: Continue without error if .env doesn't exist
    except ImportError:
        # python-dotenv not installed, continue without it
        pass
    
    # Find config file
    if config_path:
        path = Path(config_path)
    else:
        # Look in standard locations
        locations = [
            Path("config.yaml"),
            Path("config.yml"),
            Path.home() / ".jenkins-agent" / "config.yaml",
            Path("/etc/jenkins-agent/config.yaml"),
        ]
        path = None
        for loc in locations:
            if loc.exists():
                path = loc
                break
        
        if not path:
            raise FileNotFoundError(
                "No config file found. Create config.yaml or specify path with --config"
            )
    
    with open(path) as f:
        raw_config = yaml.safe_load(f)
    
    # Apply environment variable overrides
    raw_config = _apply_env_overrides(raw_config)
    
    # Global SSL verification default (can be overridden per-service)
    global_verify_ssl = raw_config.get("global", {}).get("verify_ssl", False)
    
    # Build config objects
    jenkins_cfg = JenkinsConfig(
        url=raw_config.get("jenkins", {}).get("url", ""),
        username=raw_config.get("jenkins", {}).get("username", ""),
        api_token=raw_config.get("jenkins", {}).get("api_token", ""),
        verify_ssl=raw_config.get("jenkins", {}).get("verify_ssl", global_verify_ssl),
        timeout=raw_config.get("jenkins", {}).get("timeout", 30),
        monitored_jobs=raw_config.get("jenkins", {}).get("monitored_jobs", []),
    )
    
    ai_cfg = AIConfig(
        provider=raw_config.get("ai", {}).get("provider", "openai_compatible"),
        base_url=raw_config.get("ai", {}).get("base_url", "http://localhost:11434/v1"),
        model=raw_config.get("ai", {}).get("model", "llama3:8b"),
        api_key=raw_config.get("ai", {}).get("api_key", "ollama"),
        temperature=raw_config.get("ai", {}).get("temperature", 0.1),
        max_tokens=raw_config.get("ai", {}).get("max_tokens", 4096),
        max_prompt_chars=raw_config.get("ai", {}).get("max_prompt_chars", 9000),
        timeout=raw_config.get("ai", {}).get("timeout", 120),
        max_retries=raw_config.get("ai", {}).get("max_retries", 3),
        retry_delay=raw_config.get("ai", {}).get("retry_delay", 5),
        # AWS Bedrock settings
        region=raw_config.get("ai", {}).get("region", ""),
        profile=raw_config.get("ai", {}).get("profile", ""),
        credentials_file=raw_config.get("ai", {}).get("credentials_file", ""),
        config_file=raw_config.get("ai", {}).get("config_file", ""),
    )
    
    git_cfg = GitConfig(
        enabled=raw_config.get("git", {}).get("enabled", True),
        lookback_commits=raw_config.get("git", {}).get("lookback_commits", 10),
        clone_repos=raw_config.get("git", {}).get("clone_repos", False),
        clone_directory=raw_config.get("git", {}).get("clone_directory", "/tmp/jenkins-agent-repos"),
        api=raw_config.get("git", {}).get("api", {}),
    )
    
    github_cfg = GitHubConfig(
        enabled=raw_config.get("github", {}).get("enabled", True),
        base_url=raw_config.get("github", {}).get("base_url", "https://api.github.com"),
        token=raw_config.get("github", {}).get("token", ""),
        timeout=raw_config.get("github", {}).get("timeout", 30),
        verify_ssl=raw_config.get("github", {}).get("verify_ssl", global_verify_ssl),
        cache_enabled=raw_config.get("github", {}).get("cache_enabled", True),
        cache_ttl_seconds=raw_config.get("github", {}).get("cache_ttl_seconds", 300),
        library_mappings=raw_config.get("github", {}).get("library_mappings", {}),
    )
    
    parsing_cfg = ParsingConfig(
        max_log_size=raw_config.get("parsing", {}).get("max_log_size", 10485760),
        max_output_lines=raw_config.get("parsing", {}).get("max_output_lines", 30),
        error_context_lines=raw_config.get("parsing", {}).get("error_context_lines", 10),
        error_patterns=raw_config.get("parsing", {}).get("error_patterns", [
            r"\[ERROR\]", r"\[FATAL\]", r"Exception:", r"Error:",
            r"FAILED", r"BUILD FAILURE", r"AssertionError",
        ]),
        ignore_patterns=raw_config.get("parsing", {}).get("ignore_patterns", []),
        method_execution_prefix=raw_config.get("parsing", {}).get("method_execution_prefix", ""),
    )
    
    notifications_cfg = NotificationsConfig(
        slack=raw_config.get("notifications", {}).get("slack", {}),
        teams=raw_config.get("notifications", {}).get("teams", {}),
        email=raw_config.get("notifications", {}).get("email", {}),
    )
    
    scm_cfg = SCMConfig(
        enabled=raw_config.get("scm", {}).get("enabled", False),
        provider=raw_config.get("scm", {}).get("provider", "github"),
        api_url=raw_config.get("scm", {}).get("api_url", "https://api.github.com"),
        token=raw_config.get("scm", {}).get("token", ""),
        verify_ssl=raw_config.get("scm", {}).get("verify_ssl", global_verify_ssl),
        auto_comment=raw_config.get("scm", {}).get("auto_comment", True),
        update_existing=raw_config.get("scm", {}).get("update_existing", True),
        set_commit_status=raw_config.get("scm", {}).get("set_commit_status", True),
    )
    
    reporter_cfg = ReporterConfig(
        update_jenkins_description=raw_config.get("reporter", {}).get("update_jenkins_description", True),
        post_to_pr=raw_config.get("reporter", {}).get("post_to_pr", True),
        post_to_slack=raw_config.get("reporter", {}).get("post_to_slack", False),
        generate_reports=raw_config.get("reporter", {}).get("generate_reports", True),
        report_formats=raw_config.get("reporter", {}).get("report_formats", ["json", "markdown"]),
    )
    
    server_cfg = ServerConfig(
        host=raw_config.get("server", {}).get("host", "0.0.0.0"),
        port=raw_config.get("server", {}).get("port", 8080),
        api_key_enabled=raw_config.get("server", {}).get("api_key_enabled", True),
        api_key=raw_config.get("server", {}).get("api_key", ""),
        cors_origins=raw_config.get("server", {}).get("cors_origins", []),
        rate_limit=raw_config.get("server", {}).get("rate_limit", 100),
    )
    
    # RC Analyzer config (Requirement 6, 9, 10)
    rc_raw = raw_config.get("rc_analyzer", {})
    
    # Parse jenkinsfile_source (Req 9.3)
    jenkinsfile_source = None
    jf_raw = rc_raw.get("jenkinsfile_source", {})
    if jf_raw:
        jenkinsfile_source = SourceLocation(
            type=jf_raw.get("type", "repo"),
            value=jf_raw.get("value", ""),
            ref=jf_raw.get("ref", "main"),
            name=jf_raw.get("name", "Jenkinsfile"),
        )
    
    # Parse library_sources (Req 9.3)
    library_sources = []
    for lib_raw in rc_raw.get("library_sources", []):
        library_sources.append(SourceLocation(
            type=lib_raw.get("type", "repo"),
            value=lib_raw.get("value", ""),
            ref=lib_raw.get("ref", "main"),
            name=lib_raw.get("name", ""),
        ))
    
    # Build initial source_registry from library_mappings (Req 10.2, 10.9)
    source_registry = []
    for lib_name, repo_path in github_cfg.library_mappings.items():
        source_registry.append(SourceLocation(
            type="repo",
            value=repo_path,
            name=lib_name,
        ))
    
    # Add jenkinsfile_source to registry if configured (Req 10.9)
    if jenkinsfile_source and jenkinsfile_source.value:
        source_registry.insert(0, jenkinsfile_source)
    
    # Add explicit library_sources to registry
    for lib_src in library_sources:
        if lib_src.value and lib_src not in source_registry:
            source_registry.append(lib_src)
    
    rc_analyzer_cfg = RCAnalyzerConfig(
        enabled=rc_raw.get("enabled", True),
        max_rc_iterations=rc_raw.get("max_rc_iterations", 3),
        confidence_threshold=rc_raw.get("confidence_threshold", 0.7),
        max_source_context_chars=rc_raw.get("max_source_context_chars", 8000),
        jenkinsfile_source=jenkinsfile_source,
        library_sources=library_sources,
        source_registry=source_registry,
    )
    
    return Config(
        jenkins=jenkins_cfg,
        ai=ai_cfg,
        git=git_cfg,
        github=github_cfg,
        parsing=parsing_cfg,
        notifications=notifications_cfg,
        scm=scm_cfg,
        reporter=reporter_cfg,
        server=server_cfg,
        rc_analyzer=rc_analyzer_cfg,
        categories=raw_config.get("categories", {}),
        reporting=raw_config.get("reporting", {}),
        history=raw_config.get("history", {}),
        logging=raw_config.get("logging", {}),
        verify_ssl=global_verify_ssl,
    )


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values.
    
    Supports:
      ${VAR}          - expands to env var or empty string
      ${VAR:-default} - expands to env var or default if not set
    
    Also converts boolean-like strings to actual booleans.
    """
    import re
    
    if isinstance(value, str):
        # Pattern: ${VAR} or ${VAR:-default}
        pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'
        
        def replacer(match):
            var_name = match.group(1)
            default = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default)
        
        expanded = re.sub(pattern, replacer, value)
        
        # Convert boolean-like strings to actual booleans
        if expanded.lower() in ('true', 'yes', '1'):
            return True
        elif expanded.lower() in ('false', 'no', '0'):
            return False
        
        return expanded
    
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    
    return value


def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """Apply environment variable overrides to config.
    
    Implements Requirement 12: Environment File Support
    """
    
    # First, expand ${VAR} references in config values
    config = _expand_env_vars(config)
    
    env_mappings = {
        "JENKINS_URL": ("jenkins", "url"),
        "JENKINS_USERNAME": ("jenkins", "username"),
        "JENKINS_API_TOKEN": ("jenkins", "api_token"),
        # AI provider settings
        "AI_PROVIDER": ("ai", "provider"),
        "AI_BASE_URL": ("ai", "base_url"),
        "AI_MODEL": ("ai", "model"),
        "AI_API_KEY": ("ai", "api_key"),
        # AWS Bedrock settings
        # Note: AWS_REGION, AWS_PROFILE, AWS_SHARED_CREDENTIALS_FILE, AWS_CONFIG_FILE
        # are also read directly by boto3, but we support AI_* prefixed versions too
        "AI_REGION": ("ai", "region"),
        "AI_PROFILE": ("ai", "profile"),
        "AI_CREDENTIALS_FILE": ("ai", "credentials_file"),
        "AI_CONFIG_FILE": ("ai", "config_file"),
        # GitHub settings
        "GITHUB_BASE_URL": ("github", "base_url"),
        "GITHUB_TOKEN": ("github", "token"),
        "SCM_PROVIDER": ("scm", "provider"),
        "SCM_API_URL": ("scm", "api_url"),
        "SCM_TOKEN": ("scm", "token"),
        "SLACK_WEBHOOK_URL": ("notifications", "slack", "webhook_url"),
        "SERVER_API_KEY": ("server", "api_key"),
        # Req 12.4: Method execution prefix
        "METHOD_EXECUTION_PREFIX": ("parsing", "method_execution_prefix"),
        # Req 9: Jenkinsfile source
        "JENKINSFILE_REPO": ("rc_analyzer", "jenkinsfile_source", "value"),
        "JENKINSFILE_REF": ("rc_analyzer", "jenkinsfile_source", "ref"),
    }
    
    # Boolean env vars
    bool_mappings = {
        "SCM_ENABLED": ("scm", "enabled"),
        "SCM_AUTO_COMMENT": ("scm", "auto_comment"),
        "SCM_SET_COMMIT_STATUS": ("scm", "set_commit_status"),
        "UPDATE_JENKINS_DESCRIPTION": ("reporter", "update_jenkins_description"),
        "POST_TO_PR": ("reporter", "post_to_pr"),
        # Req 12.5: RC Analyzer boolean
        "RC_ANALYZER_ENABLED": ("rc_analyzer", "enabled"),
        # GitHub enabled flag
        "GITHUB_ENABLED": ("github", "enabled"),
        # SSL verification settings (global and per-service)
        "VERIFY_SSL": ("global", "verify_ssl"),  # Global default
        "JENKINS_VERIFY_SSL": ("jenkins", "verify_ssl"),
        "GITHUB_VERIFY_SSL": ("github", "verify_ssl"),
        "SCM_VERIFY_SSL": ("scm", "verify_ssl"),
    }
    
    # Numeric env vars (Req 12.5)
    int_mappings = {
        "RC_ANALYZER_MAX_ITERATIONS": ("rc_analyzer", "max_rc_iterations"),
        "RC_ANALYZER_MAX_SOURCE_CHARS": ("rc_analyzer", "max_source_context_chars"),
        "AI_MAX_PROMPT_CHARS": ("ai", "max_prompt_chars"),
        "PARSING_MAX_OUTPUT_LINES": ("parsing", "max_output_lines"),
    }
    
    float_mappings = {
        "RC_ANALYZER_CONFIDENCE_THRESHOLD": ("rc_analyzer", "confidence_threshold"),
    }
    
    for env_var, path in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            _set_nested(config, path, value)
    
    for env_var, path in bool_mappings.items():
        value = os.environ.get(env_var)
        if value:
            _set_nested(config, path, value.lower() in ("true", "1", "yes"))
    
    for env_var, path in int_mappings.items():
        value = os.environ.get(env_var)
        if value:
            try:
                _set_nested(config, path, int(value))
            except ValueError:
                pass
    
    for env_var, path in float_mappings.items():
        value = os.environ.get(env_var)
        if value:
            try:
                _set_nested(config, path, float(value))
            except ValueError:
                pass
    
    return config


def _set_nested(d: Dict, path: tuple, value: Any) -> None:
    """Set a nested dictionary value using a path tuple."""
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value
