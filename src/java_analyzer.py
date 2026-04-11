"""
Java Source Analyzer - Extract tool definitions from Java source code.

Phase 2A of AI Learning System.

Parses Java source files to extract:
- CLI commands and subcommands (Spring Shell, Picocli, main())
- Command arguments and options
- Exception types and error messages
- Exit codes
- Log signatures

Uses existing GitHubClient for fetching source code.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path

from .github_client import GitHubClient, FetchedFile
from .knowledge_store import (
    ToolDefinition, ToolError, ToolArgument,
    SourceAnalysisLog, get_knowledge_store
)

logger = logging.getLogger("jenkins-agent.java-analyzer")


@dataclass
class JavaClass:
    """Parsed Java class information."""
    name: str
    package: str = ""
    file_path: str = ""
    content: str = ""
    imports: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    methods: List[Dict[str, Any]] = field(default_factory=list)
    fields: List[Dict[str, Any]] = field(default_factory=list)
    is_cli_entry: bool = False
    cli_framework: str = ""  # spring_shell, picocli, commons_cli, main


@dataclass 
class ExtractedError:
    """An error pattern extracted from source."""
    code: str
    message_pattern: str
    exception_class: str = ""
    exit_code: Optional[int] = None
    category: str = "UNKNOWN"
    source_file: str = ""
    source_line: int = 0


@dataclass
class ExtractedCommand:
    """A CLI command extracted from source."""
    name: str
    description: str = ""
    method_name: str = ""
    arguments: List[ToolArgument] = field(default_factory=list)
    source_file: str = ""


@dataclass
class AnalysisResult:
    """Result of analyzing Java source code."""
    tool_name: str = ""
    tool_description: str = ""
    commands: List[ExtractedCommand] = field(default_factory=list)
    errors: List[ExtractedError] = field(default_factory=list)
    log_signatures: List[str] = field(default_factory=list)
    env_vars: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    files_analyzed: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    confidence: float = 0.0
    cli_framework: str = ""


class JavaSourceAnalyzer:
    """
    Analyzes Java source code to extract tool definitions.
    
    Supports:
    - Spring Shell (@ShellComponent, @ShellMethod)
    - Picocli (@Command, @Option, @Parameters)
    - Apache Commons CLI
    - Plain main() entry points
    
    Usage:
        analyzer = JavaSourceAnalyzer(github_client)
        result = analyzer.analyze_repo(
            repo="org/my-tool",
            branch="main",
            entry_point="src/main/java/com/company/MyCli.java",
            depth=2
        )
        
        # Convert to ToolDefinition
        tool = analyzer.to_tool_definition(result)
    """
    
    # Regex patterns for Java parsing
    PACKAGE_PATTERN = re.compile(r'package\s+([\w.]+)\s*;')
    IMPORT_PATTERN = re.compile(r'import\s+(?:static\s+)?([\w.*]+)\s*;')
    CLASS_PATTERN = re.compile(
        r'(?:public\s+)?(?:abstract\s+)?(?:final\s+)?class\s+(\w+)'
        r'(?:\s+extends\s+(\w+))?(?:\s+implements\s+[\w,\s]+)?'
    )
    ANNOTATION_PATTERN = re.compile(r'@(\w+)(?:\s*\([^)]*\))?')
    METHOD_PATTERN = re.compile(
        r'(?:@\w+(?:\s*\([^)]*\))?\s*)*'
        r'(?:public|private|protected)?\s*'
        r'(?:static\s+)?'
        r'(\w+(?:<[^>]+>)?)\s+'  # return type
        r'(\w+)\s*'              # method name
        r'\(([^)]*)\)'           # parameters
    )
    
    # Spring Shell patterns
    SPRING_SHELL_COMPONENT = re.compile(r'@ShellComponent(?:\s*\(\s*["\']([^"\']+)["\']\s*\))?')
    SPRING_SHELL_METHOD = re.compile(
        r'@ShellMethod\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)["\']'
        r'(?:\s*,\s*key\s*=\s*["\']([^"\']+)["\'])?'
    )
    SPRING_SHELL_OPTION = re.compile(
        r'@ShellOption\s*\('
        r'(?:[^)]*value\s*=\s*\{?\s*["\']([^"\']+)["\'])?'
        r'(?:[^)]*defaultValue\s*=\s*["\']([^"\']+)["\'])?'
        r'(?:[^)]*help\s*=\s*["\']([^"\']+)["\'])?'
    )
    
    # Picocli patterns
    PICOCLI_COMMAND = re.compile(
        r'@Command\s*\('
        r'(?:[^)]*name\s*=\s*["\']([^"\']+)["\'])?'
        r'(?:[^)]*description\s*=\s*["\']([^"\']+)["\'])?'
        r'(?:[^)]*subcommands\s*=\s*\{([^}]+)\})?'
    )
    PICOCLI_OPTION = re.compile(
        r'@Option\s*\(\s*names\s*=\s*\{?\s*([^})]+)\}?'
        r'(?:[^)]*description\s*=\s*["\']([^"\']+)["\'])?'
        r'(?:[^)]*required\s*=\s*(true|false))?'
        r'(?:[^)]*defaultValue\s*=\s*["\']([^"\']+)["\'])?'
    )
    
    # Exception patterns
    THROW_PATTERN = re.compile(
        r'throw\s+new\s+(\w+(?:Exception|Error))\s*\(\s*["\']([^"\']+)["\']'
    )
    EXCEPTION_CLASS_PATTERN = re.compile(
        r'class\s+(\w+(?:Exception|Error))\s+extends\s+(\w+)'
    )
    
    # Exit code patterns
    EXIT_PATTERN = re.compile(r'System\.exit\s*\(\s*(\d+)\s*\)')
    EXIT_CODE_ENUM = re.compile(r'(\w+)\s*\(\s*(\d+)\s*[,)]')
    
    # Log signature patterns
    LOG_PATTERN = re.compile(
        r'(?:logger|log|LOG)\s*\.\s*(?:error|warn|info)\s*\(\s*["\']([^"\']+)["\']'
    )
    STDERR_PATTERN = re.compile(r'System\.err\.println\s*\(\s*["\']([^"\']+)["\']')
    
    # Environment variable patterns
    ENV_VAR_PATTERN = re.compile(
        r'(?:System\.getenv|getenv|Environment\.get)\s*\(\s*["\']([A-Z_][A-Z0-9_]+)["\']'
    )
    ENV_VAR_PROPERTY = re.compile(r'\$\{([A-Z_][A-Z0-9_]+)(?::[^}]*)?\}')
    
    # Error code patterns (commonly used naming conventions)
    ERROR_CODE_CONSTANT = re.compile(
        r'(?:public\s+)?(?:static\s+)?(?:final\s+)?String\s+(\w*(?:ERROR|CODE|ERR)\w*)\s*=\s*["\']([^"\']+)["\']'
    )
    
    def __init__(self, github_client: GitHubClient):
        """
        Initialize analyzer with GitHub client.
        
        Args:
            github_client: Configured GitHubClient for fetching source
        """
        self.github = github_client
        self._analyzed_files: Set[str] = set()
        self._classes: Dict[str, JavaClass] = {}
    
    def analyze_repo(
        self,
        repo: str,
        branch: str = "main",
        entry_point: str = None,
        depth: int = 2
    ) -> AnalysisResult:
        """
        Analyze a Java repository to extract tool definition.
        
        Args:
            repo: Repository in "owner/repo" format
            branch: Branch/tag/commit to analyze
            entry_point: Optional specific file to start from
            depth: How many levels of imports to follow (1-3)
            
        Returns:
            AnalysisResult with extracted information
        """
        self._analyzed_files = set()
        self._classes = {}
        
        result = AnalysisResult()
        result.confidence = 0.0
        
        logger.info(f"Analyzing repo {repo}@{branch}, entry_point={entry_point}, depth={depth}")
        
        try:
            # Step 1: Find entry points
            if entry_point:
                # Use provided entry point
                entry_files = [entry_point]
            else:
                # Search for CLI entry points
                entry_files = self._find_entry_points(repo, branch)
            
            if not entry_files:
                result.warnings.append("No CLI entry points found")
                return result
            
            logger.info(f"Found {len(entry_files)} entry points: {entry_files}")
            
            # Step 2: Analyze each entry point
            for file_path in entry_files:
                self._analyze_file(repo, branch, file_path, depth, result)
            
            # Step 3: Calculate confidence
            result.confidence = self._calculate_confidence(result)
            
            result.files_analyzed = list(self._analyzed_files)
            
            logger.info(
                f"Analysis complete: {len(result.commands)} commands, "
                f"{len(result.errors)} errors, confidence={result.confidence:.2f}"
            )
            
        except Exception as e:
            logger.exception(f"Analysis failed: {e}")
            result.warnings.append(f"Analysis error: {str(e)}")
        
        return result
    
    def _find_entry_points(self, repo: str, branch: str) -> List[str]:
        """Find CLI entry point files in the repository."""
        entry_points = []
        
        # Search common source directories
        search_dirs = [
            "src/main/java",
            "src",
            "app/src/main/java",
        ]
        
        for search_dir in search_dirs:
            files = self.github.fetch_directory(repo, search_dir, branch, recursive=True)
            
            for file in files:
                if not file.path.endswith(".java"):
                    continue
                
                content = file.content
                
                # Check for Spring Shell
                if "@ShellComponent" in content:
                    entry_points.append(file.path)
                    continue
                
                # Check for Picocli
                if "@Command" in content and "picocli" in content.lower():
                    entry_points.append(file.path)
                    continue
                
                # Check for main method in CLI-looking classes
                if "public static void main" in content:
                    # Check if it looks like a CLI tool
                    if any(indicator in content.lower() for indicator in [
                        "cli", "command", "shell", "terminal", "args",
                        "commandline", "console"
                    ]):
                        entry_points.append(file.path)
        
        return entry_points[:10]  # Limit to 10 entry points
    
    def _analyze_file(
        self,
        repo: str,
        branch: str,
        file_path: str,
        remaining_depth: int,
        result: AnalysisResult
    ):
        """Analyze a single Java file."""
        if file_path in self._analyzed_files:
            return
        
        if remaining_depth < 0:
            return
        
        self._analyzed_files.add(file_path)
        
        # Fetch file
        fetched = self.github.fetch_file(repo, file_path, branch)
        if not fetched:
            result.warnings.append(f"Could not fetch {file_path}")
            return
        
        content = fetched.content
        
        # Parse class structure
        java_class = self._parse_java_class(file_path, content)
        self._classes[java_class.name] = java_class
        
        # Extract based on framework
        if "@ShellComponent" in content or "@ShellMethod" in content:
            result.cli_framework = "spring_shell"
            self._extract_spring_shell(java_class, result)
        
        if "@Command" in content and ("picocli" in content.lower() or "CommandLine" in content):
            result.cli_framework = "picocli"
            self._extract_picocli(java_class, result)
        
        # Always extract these
        self._extract_errors(java_class, result)
        self._extract_exit_codes(java_class, result)
        self._extract_log_signatures(java_class, result)
        self._extract_env_vars(java_class, result)
        self._extract_error_codes(java_class, result)
        
        # Set tool name from class if not yet set
        if not result.tool_name:
            # Try to extract from class name
            name = java_class.name
            # Remove common suffixes
            for suffix in ["Cli", "CLI", "Command", "Commands", "Shell", "Application", "App"]:
                if name.endswith(suffix) and len(name) > len(suffix):
                    name = name[:-len(suffix)]
                    break
            result.tool_name = self._to_kebab_case(name)
        
        # Follow imports for deeper analysis
        if remaining_depth > 0:
            for imp in java_class.imports:
                # Only follow local imports (same package prefix or relative)
                if self._is_local_import(imp, java_class.package):
                    import_path = self._import_to_path(imp, repo, branch)
                    if import_path:
                        self._analyze_file(repo, branch, import_path, remaining_depth - 1, result)
    
    def _parse_java_class(self, file_path: str, content: str) -> JavaClass:
        """Parse basic Java class structure."""
        java_class = JavaClass(
            name="Unknown",
            file_path=file_path,
            content=content
        )
        
        # Extract package
        pkg_match = self.PACKAGE_PATTERN.search(content)
        if pkg_match:
            java_class.package = pkg_match.group(1)
        
        # Extract imports
        java_class.imports = self.IMPORT_PATTERN.findall(content)
        
        # Extract class name
        class_match = self.CLASS_PATTERN.search(content)
        if class_match:
            java_class.name = class_match.group(1)
        
        # Extract annotations
        java_class.annotations = self.ANNOTATION_PATTERN.findall(content)
        
        # Check if CLI entry
        java_class.is_cli_entry = any(a in java_class.annotations for a in [
            "ShellComponent", "Command", "SpringBootApplication"
        ]) or "public static void main" in content
        
        return java_class
    
    def _extract_spring_shell(self, java_class: JavaClass, result: AnalysisResult):
        """Extract Spring Shell commands and options."""
        content = java_class.content
        
        # Extract component description
        comp_match = self.SPRING_SHELL_COMPONENT.search(content)
        if comp_match and comp_match.group(1):
            result.tool_description = comp_match.group(1)
        
        # Extract shell methods
        for match in self.SPRING_SHELL_METHOD.finditer(content):
            description = match.group(1) or ""
            key = match.group(2) or ""
            
            # Find the method name
            method_start = match.end()
            method_match = self.METHOD_PATTERN.search(content[method_start:method_start + 500])
            
            command = ExtractedCommand(
                name=key if key else (method_match.group(2) if method_match else "unknown"),
                description=description,
                method_name=method_match.group(2) if method_match else "",
                source_file=java_class.file_path
            )
            
            # Extract options from method parameters
            if method_match:
                params_str = method_match.group(3)
                command.arguments = self._parse_spring_shell_params(params_str, content)
            
            result.commands.append(command)
    
    def _parse_spring_shell_params(self, params_str: str, full_content: str) -> List[ToolArgument]:
        """Parse Spring Shell method parameters."""
        arguments = []
        
        # Split parameters
        params = [p.strip() for p in params_str.split(",") if p.strip()]
        
        for param in params:
            # Look for @ShellOption annotation
            option_match = self.SPRING_SHELL_OPTION.search(param)
            
            # Extract type and name
            parts = param.split()
            if len(parts) >= 2:
                param_type = parts[-2] if not parts[-2].startswith("@") else "String"
                param_name = parts[-1]
                
                arg = ToolArgument(
                    name=f"--{self._to_kebab_case(param_name)}",
                    description=option_match.group(3) if option_match and option_match.group(3) else "",
                    required=True,  # Default, will override if defaultValue present
                    default=option_match.group(2) if option_match and option_match.group(2) else None
                )
                
                if arg.default:
                    arg.required = False
                
                # Extract aliases from @ShellOption value
                if option_match and option_match.group(1):
                    aliases = [a.strip().strip('"\'') for a in option_match.group(1).split(",")]
                    arg.aliases = [a for a in aliases if a != arg.name]
                
                arguments.append(arg)
        
        return arguments
    
    def _extract_picocli(self, java_class: JavaClass, result: AnalysisResult):
        """Extract Picocli commands and options."""
        content = java_class.content
        
        # Extract @Command annotation
        cmd_match = self.PICOCLI_COMMAND.search(content)
        if cmd_match:
            if cmd_match.group(1):
                result.tool_name = cmd_match.group(1)
            if cmd_match.group(2):
                result.tool_description = cmd_match.group(2)
            
            # Extract subcommands
            if cmd_match.group(3):
                subcommands = re.findall(r'(\w+)\.class', cmd_match.group(3))
                for sub in subcommands:
                    result.commands.append(ExtractedCommand(
                        name=self._to_kebab_case(sub),
                        description=f"Subcommand: {sub}",
                        source_file=java_class.file_path
                    ))
        
        # Extract @Option annotations
        for match in self.PICOCLI_OPTION.finditer(content):
            names_str = match.group(1)
            description = match.group(2) or ""
            required = match.group(3) == "true" if match.group(3) else False
            default = match.group(4)
            
            # Parse option names
            names = [n.strip().strip('"\'') for n in names_str.split(",")]
            primary_name = names[0] if names else "--unknown"
            aliases = names[1:] if len(names) > 1 else []
            
            arg = ToolArgument(
                name=primary_name,
                aliases=aliases,
                required=required,
                default=default,
                description=description
            )
            
            # Add to first command or create default
            if result.commands:
                result.commands[0].arguments.append(arg)
            else:
                result.commands.append(ExtractedCommand(
                    name=result.tool_name or "main",
                    arguments=[arg],
                    source_file=java_class.file_path
                ))
    
    def _extract_errors(self, java_class: JavaClass, result: AnalysisResult):
        """Extract exception throws and error patterns."""
        content = java_class.content
        
        # Find throw statements
        for match in self.THROW_PATTERN.finditer(content):
            exception_class = match.group(1)
            message = match.group(2)
            
            # Try to extract error code from message
            code_match = re.search(r'([A-Z][A-Z0-9_]+(?:_ERROR|_FAILED|_EXCEPTION)?)', message)
            code = code_match.group(1) if code_match else exception_class.upper()
            
            # Determine category
            category = self._categorize_error(exception_class, message)
            
            error = ExtractedError(
                code=code,
                message_pattern=self._message_to_pattern(message),
                exception_class=exception_class,
                category=category,
                source_file=java_class.file_path
            )
            
            # Avoid duplicates
            if not any(e.code == error.code for e in result.errors):
                result.errors.append(error)
    
    def _extract_exit_codes(self, java_class: JavaClass, result: AnalysisResult):
        """Extract System.exit() calls and exit code enums."""
        content = java_class.content
        
        # Find System.exit calls
        for match in self.EXIT_PATTERN.finditer(content):
            exit_code = int(match.group(1))
            
            # Find context (what error this relates to)
            context_start = max(0, match.start() - 500)
            context = content[context_start:match.start()]
            
            # Look for related error
            for error in result.errors:
                if error.code.lower() in context.lower() or error.message_pattern[:20] in context:
                    error.exit_code = exit_code
                    break
    
    def _extract_log_signatures(self, java_class: JavaClass, result: AnalysisResult):
        """Extract logging patterns that identify this tool."""
        content = java_class.content
        
        # Logger statements
        for match in self.LOG_PATTERN.finditer(content):
            signature = match.group(1)
            # Extract prefix/tag if present
            if signature.startswith("[") or signature.startswith("<"):
                bracket_end = signature.find("]") if "[" in signature else signature.find(">")
                if bracket_end > 0:
                    tag = signature[:bracket_end + 1]
                    if tag not in result.log_signatures:
                        result.log_signatures.append(tag)
        
        # System.err.println
        for match in self.STDERR_PATTERN.finditer(content):
            message = match.group(1)
            # Look for consistent prefixes
            if message.startswith("[") or message.startswith("ERROR:") or ": " in message[:20]:
                prefix = message.split(":")[0] + ":"
                if prefix not in result.log_signatures and len(prefix) < 30:
                    result.log_signatures.append(prefix)
    
    def _extract_env_vars(self, java_class: JavaClass, result: AnalysisResult):
        """Extract environment variable references."""
        content = java_class.content
        
        # System.getenv calls
        for match in self.ENV_VAR_PATTERN.finditer(content):
            var = match.group(1)
            if var not in result.env_vars:
                result.env_vars.append(var)
        
        # Property placeholders ${VAR}
        for match in self.ENV_VAR_PROPERTY.finditer(content):
            var = match.group(1)
            if var not in result.env_vars:
                result.env_vars.append(var)
    
    def _extract_error_codes(self, java_class: JavaClass, result: AnalysisResult):
        """Extract error code constants."""
        content = java_class.content
        
        for match in self.ERROR_CODE_CONSTANT.finditer(content):
            const_name = match.group(1)
            const_value = match.group(2)
            
            # Check if this code is already captured
            if not any(e.code == const_value for e in result.errors):
                error = ExtractedError(
                    code=const_value,
                    message_pattern=const_value.replace("_", "[ _]"),
                    category=self._categorize_error(const_name, const_value),
                    source_file=java_class.file_path
                )
                result.errors.append(error)
    
    def _categorize_error(self, exception_class: str, message: str) -> str:
        """Determine error category from exception class and message."""
        combined = (exception_class + " " + message).lower()
        
        if any(w in combined for w in ["auth", "credential", "token", "login", "permission", "denied", "forbidden"]):
            return "CREDENTIAL"
        if any(w in combined for w in ["connect", "network", "timeout", "unreachable", "host", "socket", "dns"]):
            return "NETWORK"
        if any(w in combined for w in ["config", "property", "setting", "invalid", "missing", "required"]):
            return "CONFIGURATION"
        if any(w in combined for w in ["file", "path", "directory", "notfound", "not found", "exist"]):
            return "CONFIGURATION"
        if any(w in combined for w in ["build", "compile", "maven", "gradle"]):
            return "BUILD"
        if any(w in combined for w in ["test", "assert", "expect"]):
            return "TEST"
        
        return "TOOL_ERROR"
    
    def _message_to_pattern(self, message: str) -> str:
        """Convert error message to regex pattern."""
        # Escape regex special chars
        pattern = re.escape(message)
        
        # Replace common variable parts with wildcards
        pattern = re.sub(r'\\\{[^}]+\\\}', r'.+', pattern)  # {variable}
        pattern = re.sub(r'%[sd]', r'.+', pattern)  # %s, %d
        
        return pattern
    
    def _is_local_import(self, import_path: str, current_package: str) -> bool:
        """Check if an import is from the same project (not external library)."""
        if not current_package:
            return False
        
        # Same package or subpackage
        pkg_parts = current_package.split(".")
        if len(pkg_parts) >= 2:
            # Check if import starts with same org/company prefix
            prefix = ".".join(pkg_parts[:2])
            return import_path.startswith(prefix)
        
        return import_path.startswith(current_package)
    
    def _import_to_path(self, import_path: str, repo: str, branch: str) -> Optional[str]:
        """Convert Java import to file path."""
        # Remove wildcard imports
        if import_path.endswith(".*"):
            return None
        
        # Convert to path
        relative_path = import_path.replace(".", "/") + ".java"
        
        # Try common source directories
        for src_dir in ["src/main/java", "src", "app/src/main/java"]:
            full_path = f"{src_dir}/{relative_path}"
            # Check if file exists (via cache or quick HEAD request)
            if self.github.fetch_file(repo, full_path, branch):
                return full_path
        
        return None
    
    def _to_kebab_case(self, name: str) -> str:
        """Convert CamelCase to kebab-case."""
        # Insert hyphen before uppercase letters
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1-\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1-\2', s1).lower()
    
    def _calculate_confidence(self, result: AnalysisResult) -> float:
        """Calculate confidence score for the analysis."""
        score = 0.0
        
        # Has tool name
        if result.tool_name:
            score += 0.2
        
        # Has commands
        if result.commands:
            score += min(0.3, len(result.commands) * 0.1)
        
        # Has errors
        if result.errors:
            score += min(0.2, len(result.errors) * 0.05)
        
        # Has framework detected
        if result.cli_framework:
            score += 0.15
        
        # Has env vars
        if result.env_vars:
            score += 0.1
        
        # Has log signatures
        if result.log_signatures:
            score += 0.05
        
        return min(score, 1.0)
    
    def to_tool_definition(self, result: AnalysisResult) -> ToolDefinition:
        """
        Convert analysis result to ToolDefinition.
        
        Args:
            result: AnalysisResult from analyze_repo()
            
        Returns:
            ToolDefinition ready for storage
        """
        tool = ToolDefinition(
            name=result.tool_name or "unknown-tool",
            description=result.tool_description,
            category="utility",  # Default, can be refined
            added_by="source_analysis",
            confidence=result.confidence,
        )
        
        # Build command patterns
        for cmd in result.commands:
            cmd_pattern = f"{result.tool_name} {cmd.name}" if cmd.name != result.tool_name else result.tool_name
            if cmd_pattern not in tool.patterns_commands:
                tool.patterns_commands.append(cmd_pattern)
            
            # Add arguments to tool
            for arg in cmd.arguments:
                if arg not in tool.arguments:
                    tool.arguments.append(arg)
        
        # Add log signatures
        tool.patterns_log_signatures = result.log_signatures.copy()
        
        # Add env vars
        tool.patterns_env_vars = result.env_vars.copy()
        
        # Convert errors
        for err in result.errors:
            tool_error = ToolError(
                code=err.code,
                pattern=err.message_pattern,
                exit_code=err.exit_code,
                category=err.category,
                description=f"Exception: {err.exception_class}" if err.exception_class else "",
                confidence=result.confidence,
            )
            tool.errors.append(tool_error)
        
        # Set source file
        if result.files_analyzed:
            tool.source_file = result.files_analyzed[0]
        
        return tool


def analyze_java_source(
    github_client: GitHubClient,
    repo: str,
    branch: str = "main",
    entry_point: str = None,
    depth: int = 2
) -> Tuple[ToolDefinition, AnalysisResult]:
    """
    Convenience function to analyze Java source and get ToolDefinition.
    
    Args:
        github_client: Configured GitHubClient
        repo: Repository in "owner/repo" format
        branch: Branch/tag/commit
        entry_point: Optional entry point file
        depth: Analysis depth (1-3)
        
    Returns:
        Tuple of (ToolDefinition, AnalysisResult)
    """
    analyzer = JavaSourceAnalyzer(github_client)
    result = analyzer.analyze_repo(repo, branch, entry_point, depth)
    tool = analyzer.to_tool_definition(result)
    
    return tool, result
