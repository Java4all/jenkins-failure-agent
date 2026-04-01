"""
Jenkins Configuration analyzer.

Specializes in:
- Configuration-as-Code (JCasC) issues
- Credentials and secrets problems
- Environment variable misconfigurations
- Agent label and node issues
- Plugin version mismatches
- Pipeline parameter problems
"""

import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum


class ConfigFailureType(Enum):
    """Categories of configuration failures."""
    MISSING_CREDENTIAL = "missing_credential"
    INVALID_CREDENTIAL = "invalid_credential"
    WRONG_CREDENTIAL_TYPE = "wrong_credential_type"
    MISSING_ENV_VAR = "missing_env_var"
    INVALID_ENV_VAR = "invalid_env_var"
    WRONG_AGENT_LABEL = "wrong_agent_label"
    NO_AGENT_AVAILABLE = "no_agent_available"
    AGENT_OFFLINE = "agent_offline"
    MISSING_TOOL = "missing_tool"
    WRONG_TOOL_VERSION = "wrong_tool_version"
    PLUGIN_MISSING = "plugin_missing"
    PLUGIN_VERSION = "plugin_version"
    MISSING_PARAMETER = "missing_parameter"
    INVALID_PARAMETER = "invalid_parameter"
    JCASC_ERROR = "jcasc_error"
    FOLDER_CONFIG = "folder_config"
    GLOBAL_CONFIG = "global_config"
    SCM_CONFIG = "scm_config"
    WORKSPACE_ERROR = "workspace_error"
    PERMISSION_CONFIG = "permission_config"
    UNKNOWN = "unknown"


@dataclass
class CredentialIssue:
    """A credential-related configuration issue."""
    credential_id: str
    issue_type: str  # missing, invalid, wrong_type, expired
    expected_type: str = ""  # usernamePassword, sshKey, secretText, etc.
    actual_type: str = ""
    used_in_stage: str = ""
    used_by_step: str = ""
    binding_name: str = ""  # Variable name it was bound to
    suggestions: List[str] = field(default_factory=list)


@dataclass
class EnvironmentIssue:
    """An environment variable issue."""
    variable_name: str
    issue_type: str  # missing, invalid, empty
    expected_value_pattern: str = ""
    actual_value: str = ""  # May be masked
    used_in_stage: str = ""
    defined_in: str = ""  # Jenkinsfile, JCasC, agent, etc.
    suggestions: List[str] = field(default_factory=list)


@dataclass
class AgentIssue:
    """An agent/node configuration issue."""
    label_requested: str
    issue_type: str  # no_match, offline, busy, missing_tool
    available_labels: List[str] = field(default_factory=list)
    node_name: str = ""
    missing_tools: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class ToolIssue:
    """A tool configuration issue."""
    tool_name: str
    tool_type: str  # jdk, maven, gradle, nodejs, etc.
    issue_type: str  # missing, wrong_version, not_configured
    required_version: str = ""
    available_versions: List[str] = field(default_factory=list)
    node_context: str = ""  # Which node has the issue
    suggestions: List[str] = field(default_factory=list)


@dataclass
class PluginIssue:
    """A plugin-related issue."""
    plugin_name: str
    issue_type: str  # missing, version_mismatch, incompatible
    required_version: str = ""
    installed_version: str = ""
    required_by: str = ""  # What needs this plugin
    suggestions: List[str] = field(default_factory=list)


@dataclass
class ParameterIssue:
    """A pipeline parameter issue."""
    parameter_name: str
    issue_type: str  # missing, wrong_type, invalid_value
    expected_type: str = ""
    actual_value: str = ""
    defined_in: str = ""  # Jenkinsfile, job config, upstream
    used_in_stage: str = ""
    suggestions: List[str] = field(default_factory=list)


@dataclass
class JCaSCIssue:
    """A Configuration-as-Code issue."""
    config_path: str  # e.g., jenkins.systemMessage
    issue_type: str  # parse_error, invalid_value, missing_required
    error_message: str
    yaml_location: str = ""  # File and line if known
    suggestions: List[str] = field(default_factory=list)


@dataclass
class ConfigurationAnalysis:
    """Complete configuration analysis result."""
    primary_issue_type: ConfigFailureType
    credential_issues: List[CredentialIssue] = field(default_factory=list)
    environment_issues: List[EnvironmentIssue] = field(default_factory=list)
    agent_issues: List[AgentIssue] = field(default_factory=list)
    tool_issues: List[ToolIssue] = field(default_factory=list)
    plugin_issues: List[PluginIssue] = field(default_factory=list)
    parameter_issues: List[ParameterIssue] = field(default_factory=list)
    jcasc_issues: List[JCaSCIssue] = field(default_factory=list)
    detected_environment: Dict[str, str] = field(default_factory=dict)
    detected_credentials_used: Set[str] = field(default_factory=set)
    detected_tools_used: Set[str] = field(default_factory=set)
    jenkins_version: str = ""
    summary: str = ""


class ConfigurationAnalyzer:
    """
    Analyzer for Jenkins configuration issues.
    
    This analyzer detects misconfigurations in credentials, environment,
    agents, tools, plugins, and parameters that commonly cause pipeline failures.
    """
    
    # Credential patterns
    CREDENTIAL_PATTERNS = {
        "credential_not_found": [
            r"(?:CredentialsNotFoundException|Credentials not found).*?['\"]([^'\"]+)['\"]",
            r"Could not find credentials entry with ID ['\"]([^'\"]+)['\"]",
            r"No credentials with id ['\"]([^'\"]+)['\"]",
            r"Unable to find credentials with id ['\"]([^'\"]+)['\"]",
            r"Credential\s+['\"]([^'\"]+)['\"]\s+not found",
        ],
        "credential_type_mismatch": [
            r"Expected credentials of type\s+(\w+)\s+but got\s+(\w+)",
            r"Cannot cast.*?Credentials.*?to\s+(\S+)",
            r"credentials\s+['\"]([^'\"]+)['\"]\s+.*?wrong type",
        ],
        "credential_binding_failed": [
            r"withCredentials.*?failed.*?['\"]([^'\"]+)['\"]",
            r"Error binding credentials\s+['\"]([^'\"]+)['\"]",
        ],
    }
    
    # Environment variable patterns
    ENV_VAR_PATTERNS = {
        "env_not_set": [
            r"(?:Environment variable|env\.)\s*(\w+)\s*(?:is not set|not defined|is null|is empty)",
            r"\$(\w+)\s*(?:is undefined|not found)",
            r"Missing required environment variable[:\s]+(\w+)",
            r"env\.(\w+)\s+==\s+null",
            r"params\.(\w+)\s+==\s+null",
        ],
        "env_invalid_value": [
            r"Invalid value for\s+(\w+)",
            r"(\w+)\s+has invalid format",
            r"Failed to parse\s+(\w+)",
        ],
    }
    
    # Agent/node patterns
    AGENT_PATTERNS = {
        "no_agent_match": [
            r"There are no nodes with the label ['\"]([^'\"]+)['\"]",
            r"Waiting for next available executor on ['\"]([^'\"]+)['\"]",
            r"Label ['\"]([^'\"]+)['\"]\s+(?:does not match|has no|is not)",
            r"(?:Still waiting|Pending).*?label\s+['\"]([^'\"]+)['\"]",
        ],
        "agent_offline": [
            r"Agent\s+['\"]([^'\"]+)['\"]\s+is offline",
            r"(?:Node|Slave)\s+['\"]([^'\"]+)['\"]\s+(?:offline|disconnected)",
            r"Connection to\s+['\"]([^'\"]+)['\"]\s+(?:lost|failed)",
        ],
        "agent_busy": [
            r"All executors on\s+['\"]([^'\"]+)['\"]\s+are busy",
            r"Waiting for\s+['\"]([^'\"]+)['\"]\s+to become available",
        ],
    }
    
    # Tool patterns  
    TOOL_PATTERNS = {
        "tool_not_found": [
            r"Tool\s+['\"]([^'\"]+)['\"]\s+not found",
            r"(?:Cannot find|Unable to locate)\s+(\w+)\s+installation",
            r"(\w+)\s+is not installed on this node",
            r"No tool named ['\"]([^'\"]+)['\"]",
            r"tool type ['\"]([^'\"]+)['\"]\s+not found",
        ],
        "tool_version_mismatch": [
            r"Expected\s+(\w+)\s+version\s+([^\s,]+)",
            r"(\w+)\s+version\s+([^\s]+)\s+required",
            r"Incompatible\s+(\w+)\s+version",
        ],
        "tool_not_configured": [
            r"(\w+)\s+is not configured",
            r"Please configure\s+(\w+)\s+in",
            r"Tool\s+['\"]([^'\"]+)['\"]\s+is not configured",
        ],
    }
    
    # Plugin patterns
    PLUGIN_PATTERNS = {
        "plugin_missing": [
            r"(?:Plugin|Extension)\s+['\"]([^'\"]+)['\"]\s+(?:not found|missing|required)",
            r"Required plugin\s+['\"]([^'\"]+)['\"]\s+not installed",
            r"No such DSL method ['\"]([^'\"]+)['\"]\s+found",
            r"java\.lang\.NoClassDefFoundError.*?plugin",
        ],
        "plugin_version": [
            r"Plugin\s+['\"]([^'\"]+)['\"]\s+requires version\s+([^\s]+)",
            r"Incompatible plugin version.*?['\"]([^'\"]+)['\"]",
            r"Plugin\s+['\"]([^'\"]+)['\"]\s+([^\s]+)\s+is too old",
        ],
    }
    
    # Parameter patterns
    PARAMETER_PATTERNS = {
        "param_missing": [
            r"(?:Parameter|param)\s+['\"]([^'\"]+)['\"]\s+(?:not provided|is required|missing)",
            r"No such parameter\s+['\"]([^'\"]+)['\"]",
            r"params\.(\w+)\s+(?:is null|not defined)",
            r"Required parameter\s+['\"]([^'\"]+)['\"]\s+not specified",
        ],
        "param_invalid": [
            r"Invalid (?:value for )?parameter\s+['\"]([^'\"]+)['\"]",
            r"Parameter\s+['\"]([^'\"]+)['\"]\s+(?:has wrong type|validation failed)",
        ],
    }
    
    # JCasC patterns
    JCASC_PATTERNS = {
        "jcasc_parse": [
            r"(?:JCasC|configuration-as-code).*?(?:parse|syntax|validation)\s+error",
            r"Failed to apply JCasC configuration",
            r"YAML parse error at\s+(.+)",
            r"io\.jenkins\.plugins\.casc\.ConfiguratorException",
        ],
        "jcasc_invalid": [
            r"Unknown configuration key\s+['\"]([^'\"]+)['\"]",
            r"(?:Invalid|Unknown)\s+(?:property|field)\s+['\"]([^'\"]+)['\"]\s+in\s+(.+)",
            r"configurator.*?Cannot configure.*?['\"]([^'\"]+)['\"]",
        ],
    }
    
    # Patterns to extract environment variable definitions
    ENV_DEF_PATTERNS = [
        r"^\s*(\w+)\s*=\s*['\"]?([^'\"=\n]+)['\"]?\s*$",
        r"environment\s*\{\s*([^}]+)\}",
        r"env\.(\w+)\s*=\s*['\"]?([^'\"=\n]+)['\"]?",
        r"withEnv\s*\(\s*\[['\"](\w+)=([^'\"]+)['\"]",
    ]
    
    # Patterns to extract credential usage
    CRED_USAGE_PATTERNS = [
        r"withCredentials\s*\(\s*\[.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
        r"credentials\s*\(\s*['\"]([^'\"]+)['\"]\s*\)",
        r"usernamePassword\s*\(.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
        r"sshUserPrivateKey\s*\(.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
        r"string\s*\(.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
        r"file\s*\(.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
        r"git\s*\(.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
        r"checkout\s*\(.*?credentialsId:\s*['\"]([^'\"]+)['\"]",
    ]
    
    # Tool definition patterns
    TOOL_DEF_PATTERNS = [
        r"tools\s*\{\s*([^}]+)\}",
        r"tool\s+name:\s*['\"]([^'\"]+)['\"]",
        r"(?:jdk|maven|gradle|nodejs|docker)\s+['\"]([^'\"]+)['\"]",
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
    
    def analyze(
        self,
        log_content: str,
        jenkinsfile_content: Optional[str] = None,
        jcasc_content: Optional[str] = None,
        job_config_xml: Optional[str] = None,
    ) -> ConfigurationAnalysis:
        """
        Perform comprehensive configuration analysis.
        
        Args:
            log_content: Jenkins console log
            jenkinsfile_content: Optional Jenkinsfile source
            jcasc_content: Optional JCasC YAML content
            job_config_xml: Optional job config.xml content
        """
        result = ConfigurationAnalysis(primary_issue_type=ConfigFailureType.UNKNOWN)
        
        # Detect what credentials are used
        result.detected_credentials_used = self._detect_credentials_used(
            log_content, jenkinsfile_content
        )
        
        # Detect what tools are used
        result.detected_tools_used = self._detect_tools_used(
            log_content, jenkinsfile_content
        )
        
        # Detect environment context
        result.detected_environment = self._detect_environment(log_content)
        
        # Extract Jenkins version if present
        result.jenkins_version = self._detect_jenkins_version(log_content)
        
        # Analyze credential issues
        result.credential_issues = self._analyze_credentials(log_content)
        
        # Analyze environment issues
        result.environment_issues = self._analyze_environment(log_content, jenkinsfile_content)
        
        # Analyze agent issues
        result.agent_issues = self._analyze_agents(log_content)
        
        # Analyze tool issues
        result.tool_issues = self._analyze_tools(log_content)
        
        # Analyze plugin issues
        result.plugin_issues = self._analyze_plugins(log_content)
        
        # Analyze parameter issues
        result.parameter_issues = self._analyze_parameters(log_content, jenkinsfile_content)
        
        # Analyze JCasC issues if content provided
        if jcasc_content:
            result.jcasc_issues = self._analyze_jcasc(log_content, jcasc_content)
        
        # Determine primary issue type
        result.primary_issue_type = self._determine_primary_issue(result)
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        return result
    
    def _detect_credentials_used(
        self, log_content: str, jenkinsfile: Optional[str]
    ) -> Set[str]:
        """Detect which credentials are being used."""
        creds = set()
        
        content = log_content
        if jenkinsfile:
            content += "\n" + jenkinsfile
        
        for pattern in self.CRED_USAGE_PATTERNS:
            for match in re.finditer(pattern, content, re.MULTILINE):
                creds.add(match.group(1))
        
        return creds
    
    def _detect_tools_used(
        self, log_content: str, jenkinsfile: Optional[str]
    ) -> Set[str]:
        """Detect which tools are being used."""
        tools = set()
        
        content = log_content
        if jenkinsfile:
            content += "\n" + jenkinsfile
        
        for pattern in self.TOOL_DEF_PATTERNS:
            for match in re.finditer(pattern, content, re.MULTILINE | re.DOTALL):
                group = match.group(1) if match.groups() else ""
                # Parse tools block if found
                if "{" in pattern:
                    for tool_match in re.finditer(r"(\w+)\s+['\"]([^'\"]+)['\"]", group):
                        tools.add(f"{tool_match.group(1)}:{tool_match.group(2)}")
                else:
                    tools.add(group)
        
        return tools
    
    def _detect_environment(self, log_content: str) -> Dict[str, str]:
        """Extract visible environment variables from log."""
        env = {}
        
        # Look for printenv output
        printenv_match = re.search(r"printenv.*?\n((?:[\w_]+=.*\n)+)", log_content)
        if printenv_match:
            for line in printenv_match.group(1).split("\n"):
                if "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()[:100]  # Truncate
        
        # Look for common Jenkins env vars
        jenkins_vars = [
            "BUILD_NUMBER", "BUILD_URL", "JOB_NAME", "WORKSPACE",
            "JENKINS_URL", "NODE_NAME", "EXECUTOR_NUMBER",
            "BRANCH_NAME", "CHANGE_ID", "GIT_COMMIT",
        ]
        for var in jenkins_vars:
            pattern = rf"\b{var}[=:]\s*['\"]?([^'\"\s\n]+)"
            match = re.search(pattern, log_content)
            if match:
                env[var] = match.group(1)
        
        return env
    
    def _detect_jenkins_version(self, log_content: str) -> str:
        """Extract Jenkins version from log."""
        patterns = [
            r"Jenkins ver\.\s+([^\s\n]+)",
            r"Running on Jenkins\s+([^\s\n]+)",
            r"jenkins/([0-9.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, log_content)
            if match:
                return match.group(1)
        return ""
    
    def _analyze_credentials(self, log_content: str) -> List[CredentialIssue]:
        """Analyze credential-related issues."""
        issues = []
        
        for issue_type, patterns in self.CREDENTIAL_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    cred_id = match.group(1)
                    
                    issue = CredentialIssue(
                        credential_id=cred_id,
                        issue_type=issue_type.replace("credential_", ""),
                    )
                    
                    # Find context
                    issue.used_in_stage = self._find_stage_context(log_content, match.start())
                    
                    # Generate suggestions
                    issue.suggestions = self._generate_credential_suggestions(issue)
                    
                    issues.append(issue)
        
        return issues
    
    def _analyze_environment(
        self, log_content: str, jenkinsfile: Optional[str]
    ) -> List[EnvironmentIssue]:
        """Analyze environment variable issues."""
        issues = []
        
        for issue_type, patterns in self.ENV_VAR_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    var_name = match.group(1)
                    
                    issue = EnvironmentIssue(
                        variable_name=var_name,
                        issue_type=issue_type.replace("env_", ""),
                    )
                    
                    # Try to find where this should be defined
                    if jenkinsfile:
                        if var_name in jenkinsfile:
                            issue.defined_in = "Jenkinsfile"
                        elif f"env.{var_name}" in jenkinsfile:
                            issue.defined_in = "Jenkinsfile environment block"
                        elif f"params.{var_name}" in jenkinsfile:
                            issue.defined_in = "Pipeline parameters"
                    
                    issue.used_in_stage = self._find_stage_context(log_content, match.start())
                    issue.suggestions = self._generate_env_suggestions(issue)
                    
                    issues.append(issue)
        
        return issues
    
    def _analyze_agents(self, log_content: str) -> List[AgentIssue]:
        """Analyze agent/node issues."""
        issues = []
        
        for issue_type, patterns in self.AGENT_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    label_or_node = match.group(1)
                    
                    issue = AgentIssue(
                        label_requested=label_or_node,
                        issue_type=issue_type.replace("agent_", ""),
                    )
                    
                    # Try to extract available labels from log
                    avail_match = re.search(
                        r"Available (?:labels|nodes?):\s*\[([^\]]+)\]",
                        log_content
                    )
                    if avail_match:
                        issue.available_labels = [
                            l.strip() for l in avail_match.group(1).split(",")
                        ]
                    
                    issue.suggestions = self._generate_agent_suggestions(issue)
                    issues.append(issue)
        
        return issues
    
    def _analyze_tools(self, log_content: str) -> List[ToolIssue]:
        """Analyze tool configuration issues."""
        issues = []
        
        for issue_type, patterns in self.TOOL_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    tool_name = match.group(1)
                    
                    issue = ToolIssue(
                        tool_name=tool_name,
                        tool_type=self._infer_tool_type(tool_name),
                        issue_type=issue_type.replace("tool_", ""),
                    )
                    
                    # Try to extract version info
                    if len(match.groups()) > 1:
                        issue.required_version = match.group(2)
                    
                    issue.node_context = self._find_node_context(log_content, match.start())
                    issue.suggestions = self._generate_tool_suggestions(issue)
                    
                    issues.append(issue)
        
        return issues
    
    def _analyze_plugins(self, log_content: str) -> List[PluginIssue]:
        """Analyze plugin-related issues."""
        issues = []
        
        for issue_type, patterns in self.PLUGIN_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    plugin_name = match.group(1)
                    
                    issue = PluginIssue(
                        plugin_name=plugin_name,
                        issue_type=issue_type.replace("plugin_", ""),
                    )
                    
                    if len(match.groups()) > 1:
                        issue.required_version = match.group(2)
                    
                    issue.suggestions = self._generate_plugin_suggestions(issue)
                    issues.append(issue)
        
        return issues
    
    def _analyze_parameters(
        self, log_content: str, jenkinsfile: Optional[str]
    ) -> List[ParameterIssue]:
        """Analyze pipeline parameter issues."""
        issues = []
        
        for issue_type, patterns in self.PARAMETER_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    param_name = match.group(1)
                    
                    issue = ParameterIssue(
                        parameter_name=param_name,
                        issue_type=issue_type.replace("param_", ""),
                    )
                    
                    # Try to find parameter definition in Jenkinsfile
                    if jenkinsfile:
                        param_def = re.search(
                            rf"(?:string|boolean|choice|text)\s*\(\s*name:\s*['\"]?{param_name}['\"]?",
                            jenkinsfile,
                            re.IGNORECASE
                        )
                        if param_def:
                            issue.defined_in = "Jenkinsfile parameters block"
                    
                    issue.used_in_stage = self._find_stage_context(log_content, match.start())
                    issue.suggestions = self._generate_param_suggestions(issue)
                    
                    issues.append(issue)
        
        return issues
    
    def _analyze_jcasc(
        self, log_content: str, jcasc_content: str
    ) -> List[JCaSCIssue]:
        """Analyze JCasC configuration issues."""
        issues = []
        
        for issue_type, patterns in self.JCASC_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, log_content, re.MULTILINE | re.IGNORECASE):
                    config_path = match.group(1) if match.groups() else "unknown"
                    
                    issue = JCaSCIssue(
                        config_path=config_path,
                        issue_type=issue_type.replace("jcasc_", ""),
                        error_message=match.group(0)[:500],
                    )
                    
                    issue.suggestions = self._generate_jcasc_suggestions(issue)
                    issues.append(issue)
        
        return issues
    
    def _find_stage_context(self, log_content: str, position: int) -> str:
        """Find which pipeline stage contains a position."""
        before = log_content[:position]
        patterns = [
            r"\[Pipeline\]\s*{\s*\(([^)]+)\)",
            r"stage\s*\(\s*['\"]([^'\"]+)['\"]",
        ]
        for pattern in patterns:
            matches = list(re.finditer(pattern, before))
            if matches:
                return matches[-1].group(1)
        return ""
    
    def _find_node_context(self, log_content: str, position: int) -> str:
        """Find which node/agent is running at a position."""
        before = log_content[:position]
        patterns = [
            r"Running on\s+([^\s\n]+)",
            r"node\s*\(\s*['\"]([^'\"]+)['\"]",
            r"\[([^\]]+)\]\s+Running",
        ]
        for pattern in patterns:
            matches = list(re.finditer(pattern, before))
            if matches:
                return matches[-1].group(1)
        return ""
    
    def _infer_tool_type(self, tool_name: str) -> str:
        """Infer the tool type from its name."""
        name_lower = tool_name.lower()
        
        type_keywords = {
            "jdk": ["jdk", "java", "openjdk", "oracle"],
            "maven": ["maven", "mvn"],
            "gradle": ["gradle"],
            "nodejs": ["node", "npm", "nodejs"],
            "docker": ["docker"],
            "kubectl": ["kubectl", "kubernetes", "k8s"],
            "terraform": ["terraform", "tf"],
            "ansible": ["ansible"],
            "python": ["python", "pip"],
            "go": ["go", "golang"],
            "dotnet": ["dotnet", ".net"],
        }
        
        for tool_type, keywords in type_keywords.items():
            if any(kw in name_lower for kw in keywords):
                return tool_type
        
        return "unknown"
    
    def _generate_credential_suggestions(self, issue: CredentialIssue) -> List[str]:
        """Generate suggestions for credential issues."""
        suggestions = []
        
        if issue.issue_type == "not_found":
            suggestions.extend([
                f"Create credential with ID '{issue.credential_id}' in Jenkins Credentials store",
                "Check for typos in the credential ID",
                "Verify the credential exists in the correct scope (global, folder, or job)",
                "If using folders, ensure credential is defined at appropriate level",
            ])
        elif issue.issue_type == "type_mismatch":
            suggestions.extend([
                f"Change credential type from {issue.actual_type} to {issue.expected_type}",
                "Create a new credential with the correct type",
                "Update Jenkinsfile to use a different credential binding",
            ])
        elif issue.issue_type == "binding_failed":
            suggestions.extend([
                "Verify the credential ID exists",
                "Check credential binding syntax in Jenkinsfile",
                "Ensure variable names don't conflict",
            ])
        
        return suggestions
    
    def _generate_env_suggestions(self, issue: EnvironmentIssue) -> List[str]:
        """Generate suggestions for environment variable issues."""
        suggestions = []
        
        if issue.issue_type == "not_set":
            suggestions.extend([
                f"Define '{issue.variable_name}' in Jenkinsfile environment block",
                f"Set '{issue.variable_name}' in Jenkins job configuration",
                f"Add '{issue.variable_name}' to agent node's environment",
                f"Use withEnv(['{issue.variable_name}=value']) in pipeline",
            ])
        elif issue.issue_type == "invalid_value":
            suggestions.extend([
                f"Verify the format of '{issue.variable_name}'",
                f"Check if '{issue.variable_name}' is properly escaped",
            ])
        
        return suggestions
    
    def _generate_agent_suggestions(self, issue: AgentIssue) -> List[str]:
        """Generate suggestions for agent issues."""
        suggestions = []
        
        if issue.issue_type == "no_match":
            suggestions.extend([
                f"Create an agent with label '{issue.label_requested}'",
                "Check for typos in the agent label",
            ])
            if issue.available_labels:
                suggestions.append(f"Available labels: {', '.join(issue.available_labels)}")
        elif issue.issue_type == "offline":
            suggestions.extend([
                f"Reconnect agent '{issue.label_requested}'",
                "Check agent connectivity and credentials",
                "Review agent logs for disconnection reason",
            ])
        elif issue.issue_type == "busy":
            suggestions.extend([
                "Wait for executor to become available",
                "Add more executors to the agent",
                "Consider using a different agent pool",
            ])
        
        return suggestions
    
    def _generate_tool_suggestions(self, issue: ToolIssue) -> List[str]:
        """Generate suggestions for tool issues."""
        suggestions = []
        
        if issue.issue_type == "not_found":
            suggestions.extend([
                f"Install '{issue.tool_name}' on the agent node",
                f"Configure '{issue.tool_name}' in Global Tool Configuration",
                f"Use tools {{ {issue.tool_type} '{issue.tool_name}' }} in pipeline",
            ])
        elif issue.issue_type == "version_mismatch":
            suggestions.extend([
                f"Install version {issue.required_version} of {issue.tool_name}",
                "Update tool version in Global Tool Configuration",
            ])
        elif issue.issue_type == "not_configured":
            suggestions.extend([
                f"Go to Manage Jenkins → Global Tool Configuration → {issue.tool_type}",
                f"Add installation named '{issue.tool_name}'",
            ])
        
        return suggestions
    
    def _generate_plugin_suggestions(self, issue: PluginIssue) -> List[str]:
        """Generate suggestions for plugin issues."""
        suggestions = []
        
        if issue.issue_type == "missing":
            suggestions.extend([
                f"Install plugin '{issue.plugin_name}' from Plugin Manager",
                "Restart Jenkins after installation",
            ])
        elif issue.issue_type == "version":
            suggestions.extend([
                f"Update '{issue.plugin_name}' to version {issue.required_version}",
                "Check plugin compatibility with Jenkins version",
            ])
        
        return suggestions
    
    def _generate_param_suggestions(self, issue: ParameterIssue) -> List[str]:
        """Generate suggestions for parameter issues."""
        suggestions = []
        
        if issue.issue_type == "missing":
            suggestions.extend([
                f"Add parameter '{issue.parameter_name}' to Jenkinsfile parameters block",
                "Ensure parameter is passed from upstream job",
                "Check if Build with Parameters was used",
                f"Provide default value for '{issue.parameter_name}'",
            ])
        elif issue.issue_type == "invalid":
            suggestions.extend([
                f"Verify the type of parameter '{issue.parameter_name}'",
                "Check parameter validation rules",
            ])
        
        return suggestions
    
    def _generate_jcasc_suggestions(self, issue: JCaSCIssue) -> List[str]:
        """Generate suggestions for JCasC issues."""
        suggestions = []
        
        if issue.issue_type == "parse":
            suggestions.extend([
                "Validate YAML syntax with a YAML linter",
                "Check for indentation errors",
                "Ensure quotes are balanced",
            ])
        elif issue.issue_type == "invalid":
            suggestions.extend([
                f"Check JCasC documentation for '{issue.config_path}'",
                "Verify the configuration key is valid for your Jenkins version",
                "Check plugin documentation for configuration options",
            ])
        
        return suggestions
    
    def _determine_primary_issue(
        self, analysis: ConfigurationAnalysis
    ) -> ConfigFailureType:
        """Determine the primary configuration issue."""
        
        # Priority order
        if analysis.credential_issues:
            first = analysis.credential_issues[0]
            if first.issue_type == "not_found":
                return ConfigFailureType.MISSING_CREDENTIAL
            elif first.issue_type == "type_mismatch":
                return ConfigFailureType.WRONG_CREDENTIAL_TYPE
            return ConfigFailureType.INVALID_CREDENTIAL
        
        if analysis.environment_issues:
            first = analysis.environment_issues[0]
            if first.issue_type == "not_set":
                return ConfigFailureType.MISSING_ENV_VAR
            return ConfigFailureType.INVALID_ENV_VAR
        
        if analysis.agent_issues:
            first = analysis.agent_issues[0]
            if first.issue_type == "no_match":
                return ConfigFailureType.WRONG_AGENT_LABEL
            elif first.issue_type == "offline":
                return ConfigFailureType.AGENT_OFFLINE
            return ConfigFailureType.NO_AGENT_AVAILABLE
        
        if analysis.tool_issues:
            first = analysis.tool_issues[0]
            if first.issue_type == "not_found":
                return ConfigFailureType.MISSING_TOOL
            return ConfigFailureType.WRONG_TOOL_VERSION
        
        if analysis.plugin_issues:
            first = analysis.plugin_issues[0]
            if first.issue_type == "missing":
                return ConfigFailureType.PLUGIN_MISSING
            return ConfigFailureType.PLUGIN_VERSION
        
        if analysis.parameter_issues:
            first = analysis.parameter_issues[0]
            if first.issue_type == "missing":
                return ConfigFailureType.MISSING_PARAMETER
            return ConfigFailureType.INVALID_PARAMETER
        
        if analysis.jcasc_issues:
            return ConfigFailureType.JCASC_ERROR
        
        return ConfigFailureType.UNKNOWN
    
    def _generate_summary(self, analysis: ConfigurationAnalysis) -> str:
        """Generate a human-readable summary."""
        parts = []
        
        parts.append(f"Configuration Analysis: {analysis.primary_issue_type.value}")
        
        if analysis.credential_issues:
            creds = [i.credential_id for i in analysis.credential_issues]
            parts.append(f"Credential issues: {', '.join(creds)}")
        
        if analysis.environment_issues:
            vars_list = [i.variable_name for i in analysis.environment_issues]
            parts.append(f"Environment issues: {', '.join(vars_list)}")
        
        if analysis.agent_issues:
            labels = [i.label_requested for i in analysis.agent_issues]
            parts.append(f"Agent issues: {', '.join(labels)}")
        
        if analysis.tool_issues:
            tools = [i.tool_name for i in analysis.tool_issues]
            parts.append(f"Tool issues: {', '.join(tools)}")
        
        if analysis.plugin_issues:
            plugins = [i.plugin_name for i in analysis.plugin_issues]
            parts.append(f"Plugin issues: {', '.join(plugins)}")
        
        if analysis.parameter_issues:
            params = [i.parameter_name for i in analysis.parameter_issues]
            parts.append(f"Parameter issues: {', '.join(params)}")
        
        return ". ".join(parts) + "."
    
    def format_for_ai_prompt(self, analysis: ConfigurationAnalysis) -> str:
        """Format the analysis for inclusion in an AI prompt."""
        parts = []
        
        parts.append("## Configuration Analysis")
        parts.append(f"**Primary Issue:** {analysis.primary_issue_type.value}")
        parts.append("")
        
        # Environment context
        if analysis.detected_environment:
            parts.append("### Detected Environment")
            for key, value in list(analysis.detected_environment.items())[:10]:
                parts.append(f"- {key}: `{value}`")
            parts.append("")
        
        # Credential issues
        if analysis.credential_issues:
            parts.append("### Credential Issues")
            for issue in analysis.credential_issues:
                parts.append(f"\n**Credential:** `{issue.credential_id}`")
                parts.append(f"- Issue: {issue.issue_type}")
                if issue.used_in_stage:
                    parts.append(f"- Stage: {issue.used_in_stage}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        # Environment issues
        if analysis.environment_issues:
            parts.append("### Environment Variable Issues")
            for issue in analysis.environment_issues:
                parts.append(f"\n**Variable:** `{issue.variable_name}`")
                parts.append(f"- Issue: {issue.issue_type}")
                if issue.defined_in:
                    parts.append(f"- Should be defined in: {issue.defined_in}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        # Agent issues
        if analysis.agent_issues:
            parts.append("### Agent Issues")
            for issue in analysis.agent_issues:
                parts.append(f"\n**Label:** `{issue.label_requested}`")
                parts.append(f"- Issue: {issue.issue_type}")
                if issue.available_labels:
                    parts.append(f"- Available: {', '.join(issue.available_labels)}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        # Tool issues
        if analysis.tool_issues:
            parts.append("### Tool Issues")
            for issue in analysis.tool_issues:
                parts.append(f"\n**Tool:** `{issue.tool_name}` ({issue.tool_type})")
                parts.append(f"- Issue: {issue.issue_type}")
                if issue.required_version:
                    parts.append(f"- Required version: {issue.required_version}")
                if issue.node_context:
                    parts.append(f"- Node: {issue.node_context}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        # Plugin issues
        if analysis.plugin_issues:
            parts.append("### Plugin Issues")
            for issue in analysis.plugin_issues:
                parts.append(f"\n**Plugin:** `{issue.plugin_name}`")
                parts.append(f"- Issue: {issue.issue_type}")
                if issue.required_version:
                    parts.append(f"- Required version: {issue.required_version}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        # Parameter issues
        if analysis.parameter_issues:
            parts.append("### Parameter Issues")
            for issue in analysis.parameter_issues:
                parts.append(f"\n**Parameter:** `{issue.parameter_name}`")
                parts.append(f"- Issue: {issue.issue_type}")
                if issue.defined_in:
                    parts.append(f"- Defined in: {issue.defined_in}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        # JCasC issues
        if analysis.jcasc_issues:
            parts.append("### JCasC Issues")
            for issue in analysis.jcasc_issues:
                parts.append(f"\n**Path:** `{issue.config_path}`")
                parts.append(f"- Issue: {issue.issue_type}")
                parts.append(f"- Error: {issue.error_message[:200]}")
                parts.append("- Suggestions:")
                for s in issue.suggestions[:3]:
                    parts.append(f"  - {s}")
            parts.append("")
        
        parts.append(f"**Summary:** {analysis.summary}")
        
        return "\n".join(parts)
