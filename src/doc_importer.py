"""
Documentation Importer - Extract tool knowledge from documentation URLs.

Phase 2C of AI Learning System.

Fetches documentation from URLs and extracts:
- Tool descriptions
- Command examples
- Error codes and messages
- Configuration options
- Environment variables

Supports:
- Markdown files (GitHub, GitLab, etc.)
- HTML pages (Confluence, wikis, etc.)
- Plain text

Can optionally use AI to extract structured information.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urljoin
import requests
from bs4 import BeautifulSoup

from .knowledge_store import (
    KnowledgeStore, KnowledgeDoc, ToolDefinition, ToolError, ToolArgument,
    get_knowledge_store
)

logger = logging.getLogger("jenkins-agent.doc-importer")


@dataclass
class ExtractedDocInfo:
    """Information extracted from documentation."""
    title: str = ""
    description: str = ""
    commands: List[Dict[str, str]] = field(default_factory=list)  # [{name, description, example}]
    errors: List[Dict[str, str]] = field(default_factory=list)    # [{code, description, fix}]
    env_vars: List[Dict[str, str]] = field(default_factory=list)  # [{name, description, default}]
    arguments: List[Dict[str, str]] = field(default_factory=list) # [{name, description, required}]
    examples: List[str] = field(default_factory=list)
    related_tools: List[str] = field(default_factory=list)
    confidence: float = 0.0


class DocImporter:
    """
    Imports and parses documentation from URLs.
    
    Usage:
        importer = DocImporter()
        
        # Import and extract info
        doc, info = importer.import_url(
            url="https://wiki.company.com/tools/a2l",
            tool_name="a2l"  # Optional, link to existing tool
        )
        
        # Or just fetch raw content
        doc = importer.fetch_url("https://example.com/docs.md")
    """
    
    # Common documentation patterns
    COMMAND_PATTERNS = [
        # Markdown code blocks with shell commands
        re.compile(r'```(?:bash|sh|shell|console)?\n(.*?)```', re.DOTALL),
        # Inline code that looks like commands
        re.compile(r'`([a-z][\w-]*(?:\s+[^\s`]+)+)`'),
        # Lines starting with $ or >
        re.compile(r'^\s*[$>]\s*(.+)$', re.MULTILINE),
    ]
    
    ERROR_PATTERNS = [
        # Error code definitions
        re.compile(r'(?:error|code|exit)[\s:]+([A-Z][A-Z0-9_]+)[\s:-]+(.+?)(?:\n|$)', re.IGNORECASE),
        # Table rows with error codes
        re.compile(r'\|\s*([A-Z][A-Z0-9_]+)\s*\|\s*([^|]+)\s*\|'),
        # List items with error codes
        re.compile(r'[-*]\s*`?([A-Z][A-Z0-9_]+)`?[\s:-]+(.+?)(?:\n|$)'),
    ]
    
    ENV_VAR_PATTERNS = [
        # Environment variable definitions
        re.compile(r'([A-Z][A-Z0-9_]+)[\s:=]+(.+?)(?:\n|$)'),
        # Markdown table with env vars
        re.compile(r'\|\s*`?([A-Z][A-Z0-9_]+)`?\s*\|\s*([^|]+)\s*\|'),
        # Shell export statements
        re.compile(r'export\s+([A-Z][A-Z0-9_]+)=(.*)'),
    ]
    
    ARGUMENT_PATTERNS = [
        # Command-line arguments
        re.compile(r'(--?[\w-]+)(?:\s*[,=]\s*)?(?:<[^>]+>|[\w]+)?\s*[:\s]+(.+?)(?:\n|$)'),
        # Markdown table with arguments
        re.compile(r'\|\s*`?(--?[\w-]+)`?\s*\|\s*([^|]+)\s*\|'),
    ]
    
    def __init__(self, timeout: int = 30, verify_ssl: bool = True):
        """
        Initialize doc importer.
        
        Args:
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
        """
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Jenkins-Failure-Agent/1.0 DocImporter",
            "Accept": "text/html,text/markdown,text/plain,application/json,*/*",
        })
    
    def fetch_url(self, url: str) -> Optional[KnowledgeDoc]:
        """
        Fetch documentation from a URL.
        
        Args:
            url: URL to fetch
            
        Returns:
            KnowledgeDoc with raw content, or None if fetch failed
        """
        logger.info(f"Fetching documentation from {url}")
        
        try:
            response = self.session.get(
                url, 
                timeout=self.timeout, 
                verify=self.verify_ssl
            )
            response.raise_for_status()
            
            # Determine content type
            content_type = response.headers.get("Content-Type", "").lower()
            
            if "text/html" in content_type:
                content, title = self._parse_html(response.text, url)
                doc_type = "html"
            elif "text/markdown" in content_type or url.endswith(".md"):
                content = response.text
                title = self._extract_markdown_title(content)
                doc_type = "markdown"
            else:
                content = response.text
                title = self._extract_title_from_url(url)
                doc_type = "text"
            
            return KnowledgeDoc(
                source_type="url",
                source_url=url,
                title=title,
                content=content,
                content_type=doc_type,
            )
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None
    
    def _parse_html(self, html: str, base_url: str) -> Tuple[str, str]:
        """Parse HTML and extract text content."""
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script and style elements
        for element in soup(["script", "style", "nav", "header", "footer"]):
            element.decompose()
        
        # Get title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        elif soup.h1:
            title = soup.h1.get_text(strip=True)
        
        # Find main content area
        main_content = (
            soup.find("main") or 
            soup.find("article") or 
            soup.find(class_=re.compile(r"content|main|body", re.I)) or
            soup.find("div", class_=re.compile(r"content|main|body", re.I)) or
            soup.body or
            soup
        )
        
        # Extract text while preserving some structure
        lines = []
        for element in main_content.find_all(["p", "h1", "h2", "h3", "h4", "li", "pre", "code", "td", "th"]):
            text = element.get_text(strip=True)
            if text:
                # Add markdown-style headers
                if element.name.startswith("h"):
                    level = int(element.name[1])
                    text = "#" * level + " " + text
                elif element.name == "li":
                    text = "- " + text
                elif element.name in ["pre", "code"]:
                    text = "```\n" + text + "\n```"
                
                lines.append(text)
        
        return "\n\n".join(lines), title
    
    def _extract_markdown_title(self, content: str) -> str:
        """Extract title from Markdown content."""
        # Look for first H1
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        
        # Look for title in YAML frontmatter
        frontmatter = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if frontmatter:
            title_match = re.search(r'title:\s*["\']?([^"\'\n]+)', frontmatter.group(1))
            if title_match:
                return title_match.group(1).strip()
        
        return ""
    
    def _extract_title_from_url(self, url: str) -> str:
        """Extract a title from URL path."""
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if path:
            # Get last path segment
            segment = path.split("/")[-1]
            # Remove extension
            segment = re.sub(r'\.[^.]+$', '', segment)
            # Convert dashes/underscores to spaces
            return segment.replace("-", " ").replace("_", " ").title()
        return parsed.netloc
    
    def extract_info(self, doc: KnowledgeDoc) -> ExtractedDocInfo:
        """
        Extract structured information from documentation.
        
        Args:
            doc: KnowledgeDoc to analyze
            
        Returns:
            ExtractedDocInfo with extracted data
        """
        info = ExtractedDocInfo()
        content = doc.content
        
        info.title = doc.title
        
        # Extract description (first paragraph or summary)
        info.description = self._extract_description(content)
        
        # Extract commands
        info.commands = self._extract_commands(content)
        
        # Extract error codes
        info.errors = self._extract_errors(content)
        
        # Extract environment variables
        info.env_vars = self._extract_env_vars(content)
        
        # Extract arguments
        info.arguments = self._extract_arguments(content)
        
        # Extract code examples
        info.examples = self._extract_examples(content)
        
        # Calculate confidence
        info.confidence = self._calculate_confidence(info)
        
        return info
    
    def _extract_description(self, content: str) -> str:
        """Extract tool description from content."""
        # Try to find description section
        desc_match = re.search(
            r'(?:^|\n)(?:#+\s*)?(?:description|overview|about|introduction)[:\s]*\n+(.+?)(?:\n#|\n\n|$)',
            content, re.IGNORECASE | re.DOTALL
        )
        if desc_match:
            return desc_match.group(1).strip()[:500]
        
        # Fall back to first paragraph after title
        paragraphs = re.split(r'\n\n+', content)
        for p in paragraphs[:3]:
            p = p.strip()
            # Skip headers, code blocks, lists
            if p and not p.startswith("#") and not p.startswith("```") and not p.startswith("-"):
                return p[:500]
        
        return ""
    
    def _extract_commands(self, content: str) -> List[Dict[str, str]]:
        """Extract command examples from content."""
        commands = []
        seen = set()
        
        for pattern in self.COMMAND_PATTERNS:
            for match in pattern.finditer(content):
                cmd_text = match.group(1) if match.lastindex else match.group(0)
                cmd_text = cmd_text.strip()
                
                # Parse command
                lines = cmd_text.split("\n")
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    # Remove shell prompt
                    line = re.sub(r'^[$>]\s*', '', line)
                    
                    # Get command name
                    parts = line.split()
                    if parts:
                        cmd_name = parts[0]
                        
                        # Skip common non-tool commands
                        if cmd_name in ["cd", "echo", "export", "set", "if", "then", "fi", "for", "do", "done"]:
                            continue
                        
                        if line not in seen:
                            seen.add(line)
                            commands.append({
                                "name": cmd_name,
                                "example": line,
                                "description": "",
                            })
        
        return commands[:20]  # Limit
    
    def _extract_errors(self, content: str) -> List[Dict[str, str]]:
        """Extract error codes from content."""
        errors = []
        seen = set()
        
        # Look for error/exit code sections
        error_section = re.search(
            r'(?:^|\n)(?:#+\s*)?(?:error|exit)\s*codes?[:\s]*\n(.+?)(?:\n#[^#]|\Z)',
            content, re.IGNORECASE | re.DOTALL
        )
        
        search_content = error_section.group(1) if error_section else content
        
        for pattern in self.ERROR_PATTERNS:
            for match in pattern.finditer(search_content):
                code = match.group(1).strip()
                description = match.group(2).strip() if match.lastindex >= 2 else ""
                
                # Validate error code format
                if not re.match(r'^[A-Z][A-Z0-9_]+$', code):
                    continue
                
                if code not in seen:
                    seen.add(code)
                    errors.append({
                        "code": code,
                        "description": description[:200],
                        "fix": "",  # Will need AI or manual input
                    })
        
        return errors[:30]  # Limit
    
    def _extract_env_vars(self, content: str) -> List[Dict[str, str]]:
        """Extract environment variables from content."""
        env_vars = []
        seen = set()
        
        # Look for environment/configuration section
        env_section = re.search(
            r'(?:^|\n)(?:#+\s*)?(?:environment|configuration|config|settings)[:\s]*\n(.+?)(?:\n#[^#]|\Z)',
            content, re.IGNORECASE | re.DOTALL
        )
        
        search_content = env_section.group(1) if env_section else content
        
        for pattern in self.ENV_VAR_PATTERNS:
            for match in pattern.finditer(search_content):
                name = match.group(1).strip()
                description = match.group(2).strip() if match.lastindex >= 2 else ""
                
                # Validate env var format
                if not re.match(r'^[A-Z][A-Z0-9_]+$', name):
                    continue
                
                # Skip common system vars
                if name in ["PATH", "HOME", "USER", "PWD", "SHELL", "TERM"]:
                    continue
                
                if name not in seen:
                    seen.add(name)
                    env_vars.append({
                        "name": name,
                        "description": description[:200],
                        "default": "",
                    })
        
        return env_vars[:20]  # Limit
    
    def _extract_arguments(self, content: str) -> List[Dict[str, str]]:
        """Extract command-line arguments from content."""
        arguments = []
        seen = set()
        
        # Look for arguments/options section
        args_section = re.search(
            r'(?:^|\n)(?:#+\s*)?(?:arguments?|options?|flags?|parameters?)[:\s]*\n(.+?)(?:\n#[^#]|\Z)',
            content, re.IGNORECASE | re.DOTALL
        )
        
        search_content = args_section.group(1) if args_section else content
        
        for pattern in self.ARGUMENT_PATTERNS:
            for match in pattern.finditer(search_content):
                name = match.group(1).strip()
                description = match.group(2).strip() if match.lastindex >= 2 else ""
                
                # Validate argument format
                if not name.startswith("-"):
                    continue
                
                if name not in seen:
                    seen.add(name)
                    
                    # Check if required
                    required = bool(re.search(r'required|mandatory', description, re.I))
                    
                    arguments.append({
                        "name": name,
                        "description": description[:200],
                        "required": required,
                    })
        
        return arguments[:30]  # Limit
    
    def _extract_examples(self, content: str) -> List[str]:
        """Extract code examples from content."""
        examples = []
        
        # Find code blocks
        for match in re.finditer(r'```(?:\w+)?\n(.*?)```', content, re.DOTALL):
            example = match.group(1).strip()
            if example and len(example) < 500:
                examples.append(example)
        
        return examples[:10]  # Limit
    
    def _calculate_confidence(self, info: ExtractedDocInfo) -> float:
        """Calculate confidence score for extracted info."""
        score = 0.0
        
        if info.title:
            score += 0.1
        if info.description:
            score += 0.2
        if info.commands:
            score += min(0.2, len(info.commands) * 0.05)
        if info.errors:
            score += min(0.2, len(info.errors) * 0.05)
        if info.env_vars:
            score += min(0.15, len(info.env_vars) * 0.05)
        if info.arguments:
            score += min(0.15, len(info.arguments) * 0.05)
        
        return min(score, 1.0)
    
    def import_url(
        self,
        url: str,
        tool_name: str = None,
        extract_info: bool = True
    ) -> Tuple[Optional[KnowledgeDoc], Optional[ExtractedDocInfo]]:
        """
        Import documentation from URL and optionally extract info.
        
        Args:
            url: URL to import
            tool_name: Optional tool name to link to
            extract_info: Whether to extract structured info
            
        Returns:
            Tuple of (KnowledgeDoc, ExtractedDocInfo or None)
        """
        doc = self.fetch_url(url)
        if not doc:
            return None, None
        
        info = None
        if extract_info:
            info = self.extract_info(doc)
            doc.extracted_info = {
                "title": info.title,
                "description": info.description,
                "commands_count": len(info.commands),
                "errors_count": len(info.errors),
                "env_vars_count": len(info.env_vars),
                "confidence": info.confidence,
            }
        
        # Link to tool if specified
        if tool_name:
            store = get_knowledge_store()
            tool = store.get_tool(name=tool_name)
            if tool:
                doc.tool_id = tool.id
        
        return doc, info
    
    def to_tool_definition(
        self,
        info: ExtractedDocInfo,
        tool_name: str,
        source_url: str = ""
    ) -> ToolDefinition:
        """
        Convert extracted info to ToolDefinition.
        
        Args:
            info: ExtractedDocInfo from extraction
            tool_name: Name for the tool
            source_url: Source URL for reference
            
        Returns:
            ToolDefinition ready for storage
        """
        tool = ToolDefinition(
            name=tool_name,
            description=info.description,
            category="utility",
            docs_url=source_url,
            added_by="doc_import",
            confidence=info.confidence,
        )
        
        # Add commands as patterns (normalized to base command + subcommand)
        for cmd in info.commands:
            if cmd["example"]:
                # Normalize command pattern: extract base command + first subcommand
                # e.g., "a2l deploy --cluster prod --env staging" -> "a2l deploy"
                pattern = self._normalize_command_pattern(cmd["example"], tool.name)
                if pattern and pattern not in tool.patterns_commands:
                    tool.patterns_commands.append(pattern)
        
        # Add arguments
        for arg in info.arguments:
            tool.arguments.append(ToolArgument(
                name=arg["name"],
                description=arg.get("description", ""),
                required=arg.get("required", False),
            ))
        
        # Add errors
        for err in info.errors:
            tool.errors.append(ToolError(
                code=err["code"],
                pattern=err["code"].replace("_", "[ _]"),
                category=self._categorize_error_code(err["code"]),
                description=err.get("description", ""),
                fix=err.get("fix", ""),
            ))
        
        # Add env vars
        for env in info.env_vars:
            if env["name"] not in tool.patterns_env_vars:
                tool.patterns_env_vars.append(env["name"])
        
        return tool
    
    def _normalize_command_pattern(self, command: str, tool_name: str) -> Optional[str]:
        """
        Normalize command to base pattern for matching.
        
        Examples:
            "a2l deploy --cluster prod" -> "a2l deploy"
            "kubectl get pods -n kube-system" -> "kubectl get"
            "git commit -m 'message'" -> "git commit"
            "npm install --save-dev" -> "npm install"
            
        Args:
            command: Full command string
            tool_name: Expected tool name for validation
            
        Returns:
            Normalized pattern or None if invalid
        """
        if not command:
            return None
        
        parts = command.split()
        if not parts:
            return None
        
        # Extract meaningful parts (skip arguments starting with -)
        meaningful_parts = []
        for part in parts:
            # Stop at first argument (starts with -)
            if part.startswith("-"):
                break
            # Stop at values that look like paths, URLs, or variables
            if "/" in part or "=" in part or part.startswith("$"):
                break
            meaningful_parts.append(part)
        
        if not meaningful_parts:
            return None
        
        # Limit to tool + subcommand (max 2-3 words)
        # e.g., "a2l deploy" or "kubectl get pods" -> "kubectl get"
        if len(meaningful_parts) > 2:
            # For 3+ words, check if first word is the tool
            if meaningful_parts[0].lower() == tool_name.lower():
                meaningful_parts = meaningful_parts[:2]  # tool + subcommand
            else:
                meaningful_parts = meaningful_parts[:2]
        
        pattern = " ".join(meaningful_parts)
        
        # Validate pattern includes tool name (case-insensitive)
        if tool_name.lower() not in pattern.lower():
            return None
        
        return pattern
    
    def _categorize_error_code(self, code: str) -> str:
        """Categorize error code based on naming patterns."""
        code_lower = code.lower()
        
        if any(w in code_lower for w in ["auth", "credential", "token", "login", "permission"]):
            return "CREDENTIAL"
        if any(w in code_lower for w in ["connect", "network", "timeout", "host", "dns"]):
            return "NETWORK"
        if any(w in code_lower for w in ["config", "invalid", "missing", "notfound"]):
            return "CONFIGURATION"
        if any(w in code_lower for w in ["build", "compile"]):
            return "BUILD"
        if any(w in code_lower for w in ["test", "assert"]):
            return "TEST"
        
        return "TOOL_ERROR"


def import_documentation(
    url: str,
    tool_name: str = None,
    save: bool = False
) -> Tuple[Optional[KnowledgeDoc], Optional[ExtractedDocInfo], Optional[ToolDefinition]]:
    """
    Convenience function to import documentation.
    
    Args:
        url: URL to import
        tool_name: Optional tool name
        save: Whether to save doc to store
        
    Returns:
        Tuple of (KnowledgeDoc, ExtractedDocInfo, ToolDefinition or None)
    """
    importer = DocImporter()
    doc, info = importer.import_url(url, tool_name)
    
    tool = None
    if doc and info and tool_name:
        tool = importer.to_tool_definition(info, tool_name, url)
    
    if save and doc:
        store = get_knowledge_store()
        doc_id = store.add_doc(doc)
        doc.id = doc_id
    
    return doc, info, tool
