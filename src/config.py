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
    verify_ssl: bool = True
    timeout: int = 30
    monitored_jobs: List[str] = field(default_factory=list)


@dataclass
class AIConfig:
    provider: str = "openai_compatible"
    base_url: str = "http://localhost:11434/v1"
    model: str = "llama3:8b"
    api_key: str = "ollama"
    temperature: float = 0.1
    max_tokens: int = 4096
    timeout: int = 120
    max_retries: int = 3
    retry_delay: int = 5


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
    verify_ssl: bool = True
    # Cache settings
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    # Library name to repository mappings
    # e.g., {"my-lib": "org/jenkins-shared-library"}
    library_mappings: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParsingConfig:
    max_log_size: int = 10485760
    error_context_lines: int = 10
    error_patterns: List[str] = field(default_factory=list)
    ignore_patterns: List[str] = field(default_factory=list)


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
    verify_ssl: bool = True
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
    categories: Dict[str, Any] = field(default_factory=dict)
    reporting: Dict[str, Any] = field(default_factory=dict)
    history: Dict[str, Any] = field(default_factory=dict)
    logging: Dict[str, Any] = field(default_factory=dict)


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file."""
    
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
    
    # Build config objects
    jenkins_cfg = JenkinsConfig(
        url=raw_config.get("jenkins", {}).get("url", ""),
        username=raw_config.get("jenkins", {}).get("username", ""),
        api_token=raw_config.get("jenkins", {}).get("api_token", ""),
        verify_ssl=raw_config.get("jenkins", {}).get("verify_ssl", True),
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
        timeout=raw_config.get("ai", {}).get("timeout", 120),
        max_retries=raw_config.get("ai", {}).get("max_retries", 3),
        retry_delay=raw_config.get("ai", {}).get("retry_delay", 5),
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
        verify_ssl=raw_config.get("github", {}).get("verify_ssl", True),
        cache_enabled=raw_config.get("github", {}).get("cache_enabled", True),
        cache_ttl_seconds=raw_config.get("github", {}).get("cache_ttl_seconds", 300),
        library_mappings=raw_config.get("github", {}).get("library_mappings", {}),
    )
    
    parsing_cfg = ParsingConfig(
        max_log_size=raw_config.get("parsing", {}).get("max_log_size", 10485760),
        error_context_lines=raw_config.get("parsing", {}).get("error_context_lines", 10),
        error_patterns=raw_config.get("parsing", {}).get("error_patterns", [
            r"\[ERROR\]", r"\[FATAL\]", r"Exception:", r"Error:",
            r"FAILED", r"BUILD FAILURE", r"AssertionError",
        ]),
        ignore_patterns=raw_config.get("parsing", {}).get("ignore_patterns", []),
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
        verify_ssl=raw_config.get("scm", {}).get("verify_ssl", True),
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
        categories=raw_config.get("categories", {}),
        reporting=raw_config.get("reporting", {}),
        history=raw_config.get("history", {}),
        logging=raw_config.get("logging", {}),
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
    """Apply environment variable overrides to config."""
    
    # First, expand ${VAR} references in config values
    config = _expand_env_vars(config)
    
    env_mappings = {
        "JENKINS_URL": ("jenkins", "url"),
        "JENKINS_USERNAME": ("jenkins", "username"),
        "JENKINS_API_TOKEN": ("jenkins", "api_token"),
        "AI_BASE_URL": ("ai", "base_url"),
        "AI_MODEL": ("ai", "model"),
        "AI_API_KEY": ("ai", "api_key"),
        "GITHUB_BASE_URL": ("github", "base_url"),
        "GITHUB_TOKEN": ("github", "token"),
        "SCM_PROVIDER": ("scm", "provider"),
        "SCM_API_URL": ("scm", "api_url"),
        "SCM_TOKEN": ("scm", "token"),
        "SLACK_WEBHOOK_URL": ("notifications", "slack", "webhook_url"),
        "SERVER_API_KEY": ("server", "api_key"),
    }
    
    # Boolean env vars
    bool_mappings = {
        "SCM_ENABLED": ("scm", "enabled"),
        "SCM_AUTO_COMMENT": ("scm", "auto_comment"),
        "SCM_SET_COMMIT_STATUS": ("scm", "set_commit_status"),
        "UPDATE_JENKINS_DESCRIPTION": ("reporter", "update_jenkins_description"),
        "POST_TO_PR": ("reporter", "post_to_pr"),
    }
    
    for env_var, path in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            _set_nested(config, path, value)
    
    for env_var, path in bool_mappings.items():
        value = os.environ.get(env_var)
        if value:
            _set_nested(config, path, value.lower() in ("true", "1", "yes"))
    
    return config


def _set_nested(d: Dict, path: tuple, value: Any) -> None:
    """Set a nested dictionary value using a path tuple."""
    for key in path[:-1]:
        d = d.setdefault(key, {})
    d[path[-1]] = value
