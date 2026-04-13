"""
Documentation Importer - Extract tool knowledge from documentation URLs.

Phase 2C of AI Learning System.

Fetches documentation from URLs and extracts:
- Tool descriptions
- Command examples (with subcommand detection)
- Error codes and messages
- Configuration options
- Environment variables

Supports:
- Markdown files (GitHub, GitLab, etc.)
- HTML pages (Confluence, wikis, etc.)
- Plain text

Features:
- URL validation and auth page detection
- Subcommand hierarchy detection
- Alias-aware search
- Confidence scoring

Can optionally use AI to extract structured information.
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, urljoin
from enum import Enum
import requests
from bs4 import BeautifulSoup

from .knowledge_store import (
    KnowledgeStore, KnowledgeDoc, ToolDefinition, ToolError, ToolArgument,
    get_knowledge_store
)

logger = logging.getLogger("jenkins-agent.doc-importer")


class PageValidationResult(str, Enum):
    """Result of page validation."""
    VALID = "valid"
    AUTH_REQUIRED = "auth_required"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    EMPTY_CONTENT = "empty_content"
    NOT_DOCUMENTATION = "not_documentation"
    ERROR = "error"


class DocType(str, Enum):
    """Type of documentation page."""
    MAIN_TOOL = "main_tool"          # Main tool page with multiple commands
    SUBCOMMAND = "subcommand"        # Single subcommand documentation
    REFERENCE = "reference"          # API/CLI reference
    TUTORIAL = "tutorial"            # How-to/tutorial
    UNKNOWN = "unknown"


@dataclass
class PageValidation:
    """Result of validating a documentation URL."""
    status: PageValidationResult
    message: str = ""
    doc_type: DocType = DocType.UNKNOWN
    detected_tool: str = ""
    detected_subcommand: str = ""
    confidence: float = 0.0
    
    @property
    def is_valid(self) -> bool:
        return self.status == PageValidationResult.VALID


@dataclass
class SubcommandInfo:
    """Information about a subcommand."""
    name: str
    description: str = ""
    usage: str = ""
    arguments: List[Dict[str, str]] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    parent_command: str = ""


@dataclass
class ExtractedDocInfo:
    """Information extracted from documentation."""
    title: str = ""
    description: str = ""
    commands: List[Dict[str, str]] = field(default_factory=list)  # [{name, description, example}]
    subcommands: List[SubcommandInfo] = field(default_factory=list)  # Structured subcommands
    errors: List[Dict[str, str]] = field(default_factory=list)    # [{code, description, fix}]
    env_vars: List[Dict[str, str]] = field(default_factory=list)  # [{name, description, default}]
    arguments: List[Dict[str, str]] = field(default_factory=list) # [{name, description, required}]
    examples: List[str] = field(default_factory=list)
    related_tools: List[str] = field(default_factory=list)
    confidence: float = 0.0
    
    # Page classification
    doc_type: DocType = DocType.UNKNOWN
    parent_tool: str = ""           # If this is a subcommand page
    detected_subcommand: str = ""   # Detected subcommand name


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
    
    # Auth/login page detection patterns
    AUTH_PAGE_INDICATORS = [
        # Title patterns
        re.compile(r'sign\s*in|log\s*in|login|authenticate|authorization', re.IGNORECASE),
        # Form patterns
        re.compile(r'<input[^>]*type=["\']password["\']', re.IGNORECASE),
        re.compile(r'<form[^>]*(?:login|signin|auth)', re.IGNORECASE),
        # Content patterns
        re.compile(r'(?:enter|provide)\s+(?:your\s+)?(?:username|password|credentials)', re.IGNORECASE),
        re.compile(r'(?:forgot|reset)\s+(?:your\s+)?password', re.IGNORECASE),
        # OAuth/SSO patterns
        re.compile(r'continue\s+with\s+(?:google|github|sso|saml)', re.IGNORECASE),
        re.compile(r'single\s+sign[- ]on', re.IGNORECASE),
    ]
    
    # Error page indicators
    ERROR_PAGE_INDICATORS = [
        re.compile(r'404\s*[-:]\s*(?:not\s+found|page\s+not\s+found)', re.IGNORECASE),
        re.compile(r'403\s*[-:]\s*(?:forbidden|access\s+denied)', re.IGNORECASE),
        re.compile(r'401\s*[-:]\s*unauthorized', re.IGNORECASE),
        re.compile(r'page\s+(?:not\s+found|does\s+not\s+exist)', re.IGNORECASE),
        re.compile(r'you\s+don\'?t\s+have\s+(?:access|permission)', re.IGNORECASE),
    ]
    
    # Subcommand page indicators
    SUBCOMMAND_PAGE_INDICATORS = [
        re.compile(r'(?:^|\s)subcommand(?:\s|$)', re.IGNORECASE),
        re.compile(r'(?:^|\s)plugin(?:\s|$)', re.IGNORECASE),
        re.compile(r'(?:^|\s)command\s+reference(?:\s|$)', re.IGNORECASE),
        # URL patterns like /tool/commands/subcommand
        re.compile(r'/(?:commands?|subcommands?|plugins?)/[\w-]+/?$', re.IGNORECASE),
    ]
    
    def validate_url(self, url: str) -> PageValidation:
        """
        Validate a URL before importing.
        
        Checks:
        - URL is accessible
        - Page is not an auth/login page
        - Page has actual documentation content
        - Detects if page is main tool or subcommand
        
        Returns:
            PageValidation with status and detected info
        """
        logger.info(f"Validating URL: {url}")
        
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                verify=self.verify_ssl
            )
            
            # Check HTTP status
            if response.status_code == 404:
                return PageValidation(
                    status=PageValidationResult.NOT_FOUND,
                    message="Page not found (404)"
                )
            elif response.status_code == 403:
                return PageValidation(
                    status=PageValidationResult.ACCESS_DENIED,
                    message="Access denied (403)"
                )
            elif response.status_code == 401:
                return PageValidation(
                    status=PageValidationResult.AUTH_REQUIRED,
                    message="Authentication required (401)"
                )
            elif response.status_code >= 400:
                return PageValidation(
                    status=PageValidationResult.ERROR,
                    message=f"HTTP error: {response.status_code}"
                )
            
            html = response.text
            
            # Check for auth/login page
            auth_check = self._detect_auth_page(html)
            if auth_check:
                return PageValidation(
                    status=PageValidationResult.AUTH_REQUIRED,
                    message=auth_check
                )
            
            # Check for error pages
            error_check = self._detect_error_page(html)
            if error_check:
                return PageValidation(
                    status=PageValidationResult.NOT_FOUND,
                    message=error_check
                )
            
            # Check if page has actual content
            content_check = self._check_has_content(html)
            if not content_check:
                return PageValidation(
                    status=PageValidationResult.EMPTY_CONTENT,
                    message="Page has no meaningful documentation content"
                )
            
            # Detect page type (main tool vs subcommand)
            doc_type, tool_name, subcommand, confidence = self._detect_page_type(url, html)
            
            return PageValidation(
                status=PageValidationResult.VALID,
                message="Page validated successfully",
                doc_type=doc_type,
                detected_tool=tool_name,
                detected_subcommand=subcommand,
                confidence=confidence
            )
            
        except requests.Timeout:
            return PageValidation(
                status=PageValidationResult.ERROR,
                message="Request timed out"
            )
        except requests.ConnectionError as e:
            return PageValidation(
                status=PageValidationResult.ERROR,
                message=f"Connection error: {str(e)}"
            )
        except requests.RequestException as e:
            return PageValidation(
                status=PageValidationResult.ERROR,
                message=f"Request failed: {str(e)}"
            )
    
    def _detect_auth_page(self, html: str) -> Optional[str]:
        """
        Detect if page is an authentication/login page.
        
        Returns:
            Error message if auth page detected, None otherwise
        """
        soup = BeautifulSoup(html, "html.parser")
        
        # Check title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        
        for pattern in self.AUTH_PAGE_INDICATORS[:1]:  # Title patterns
            if pattern.search(title):
                return f"Page appears to be a login page (title: {title})"
        
        # Check for password input
        password_inputs = soup.find_all("input", {"type": "password"})
        if password_inputs:
            return "Page contains password input field - likely a login page"
        
        # Check for login forms
        forms = soup.find_all("form")
        for form in forms:
            form_action = form.get("action", "").lower()
            form_id = form.get("id", "").lower()
            form_class = " ".join(form.get("class", [])).lower()
            
            login_keywords = ["login", "signin", "sign-in", "auth", "authenticate", "sso"]
            if any(kw in form_action or kw in form_id or kw in form_class for kw in login_keywords):
                return "Page contains login form"
        
        # Check body content for auth indicators
        body_text = soup.get_text()[:2000].lower()  # Check first 2000 chars
        auth_phrases = [
            "enter your password",
            "enter your username",
            "sign in to continue",
            "log in to continue",
            "authenticate to access",
            "please sign in",
            "please log in",
        ]
        for phrase in auth_phrases:
            if phrase in body_text:
                return f"Page contains authentication prompt: '{phrase}'"
        
        return None
    
    def _detect_error_page(self, html: str) -> Optional[str]:
        """
        Detect if page is an error page (404, 403, etc).
        
        Returns:
            Error message if error page detected, None otherwise
        """
        soup = BeautifulSoup(html, "html.parser")
        
        # Check title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        
        # Check page content
        text = soup.get_text()[:3000]
        full_text = f"{title} {text}"
        
        for pattern in self.ERROR_PAGE_INDICATORS:
            match = pattern.search(full_text)
            if match:
                return f"Page appears to be an error page: {match.group(0)}"
        
        return None
    
    def _check_has_content(self, html: str) -> bool:
        """
        Check if page has meaningful documentation content.
        
        Returns:
            True if page has content, False otherwise
        """
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove nav, header, footer
        for tag in soup(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        
        text = soup.get_text(strip=True)
        
        # Check minimum content length
        if len(text) < 100:
            return False
        
        # Check for code blocks or command examples
        code_blocks = soup.find_all(["code", "pre"])
        if code_blocks:
            return True
        
        # Check for documentation-like patterns
        doc_indicators = [
            r'```',                           # Code blocks
            r'^\s*[$>]',                       # Command prompts
            r'--[\w-]+',                       # CLI arguments
            r'[A-Z][A-Z0-9_]{2,}',             # Constants/env vars
            r'(?:usage|example|command|install|configure)',  # Doc keywords
        ]
        
        for pattern in doc_indicators:
            if re.search(pattern, text, re.IGNORECASE | re.MULTILINE):
                return True
        
        # Fallback: if we have enough text, consider it valid
        return len(text) > 500
    
    def _detect_page_type(self, url: str, html: str) -> Tuple[DocType, str, str, float]:
        """
        Detect if page is main tool documentation or subcommand documentation.
        
        Returns:
            (doc_type, tool_name, subcommand_name, confidence)
        """
        soup = BeautifulSoup(html, "html.parser")
        parsed_url = urlparse(url)
        path_parts = [p for p in parsed_url.path.split("/") if p]
        
        # Default values
        doc_type = DocType.UNKNOWN
        tool_name = ""
        subcommand = ""
        confidence = 0.5
        
        # Analyze URL structure
        # Pattern: /docs/tool/command or /tool/commands/subcommand
        url_signals = {
            "is_subcommand": False,
            "tool_from_url": "",
            "subcommand_from_url": "",
        }
        
        # Check for subcommand URL patterns
        for pattern in self.SUBCOMMAND_PAGE_INDICATORS:
            if pattern.search(url):
                url_signals["is_subcommand"] = True
                break
        
        # Try to extract tool and subcommand from URL
        if len(path_parts) >= 2:
            # Check common patterns
            commands_idx = None
            for i, part in enumerate(path_parts):
                if part.lower() in ["commands", "subcommands", "cli", "reference"]:
                    commands_idx = i
                    break
            
            if commands_idx is not None and commands_idx > 0:
                # Pattern: /tool/commands/subcommand
                url_signals["tool_from_url"] = path_parts[commands_idx - 1]
                if commands_idx + 1 < len(path_parts):
                    url_signals["subcommand_from_url"] = path_parts[commands_idx + 1]
                    url_signals["is_subcommand"] = True
            elif len(path_parts) >= 2:
                # Pattern: /tool/subcommand or /docs/tool
                potential_tool = path_parts[-2] if path_parts[-1] in ["index", "readme", "overview"] else path_parts[-2]
                potential_sub = path_parts[-1] if path_parts[-1] not in ["index", "readme", "overview", "docs"] else ""
                
                # Check if potential_tool looks like a tool name
                if re.match(r'^[a-z][a-z0-9_-]*$', potential_tool, re.IGNORECASE):
                    url_signals["tool_from_url"] = potential_tool
                if potential_sub and re.match(r'^[a-z][a-z0-9_-]*$', potential_sub, re.IGNORECASE):
                    url_signals["subcommand_from_url"] = potential_sub
        
        # Analyze page content
        title = ""
        if soup.title:
            title = soup.title.string or ""
        h1 = soup.find("h1")
        h1_text = h1.get_text(strip=True) if h1 else ""
        
        # Count distinct commands mentioned
        text = soup.get_text()
        command_sections = len(re.findall(r'(?:^|\n)#{1,3}\s+\w+\s+(?:command|subcommand)', text, re.IGNORECASE))
        code_blocks = soup.find_all(["code", "pre"])
        
        # Heuristics for main tool page
        main_tool_signals = 0
        if command_sections >= 3:
            main_tool_signals += 2
        if len(code_blocks) >= 5:
            main_tool_signals += 1
        if re.search(r'(?:commands?|subcommands?)\s+available', text, re.IGNORECASE):
            main_tool_signals += 2
        if re.search(r'table\s+of\s+contents', text, re.IGNORECASE):
            main_tool_signals += 1
        
        # Heuristics for subcommand page
        subcommand_signals = 0
        if url_signals["is_subcommand"]:
            subcommand_signals += 2
        if url_signals["subcommand_from_url"]:
            subcommand_signals += 1
        if command_sections <= 1:
            subcommand_signals += 1
        if re.search(r'^(?:the\s+)?\w+\s+(?:command|subcommand)', h1_text, re.IGNORECASE):
            subcommand_signals += 2
        
        # Determine doc type
        if main_tool_signals > subcommand_signals and main_tool_signals >= 2:
            doc_type = DocType.MAIN_TOOL
            confidence = min(0.9, 0.5 + main_tool_signals * 0.1)
            tool_name = url_signals["tool_from_url"]
        elif subcommand_signals > main_tool_signals and subcommand_signals >= 2:
            doc_type = DocType.SUBCOMMAND
            confidence = min(0.9, 0.5 + subcommand_signals * 0.1)
            tool_name = url_signals["tool_from_url"]
            subcommand = url_signals["subcommand_from_url"] or self._extract_subcommand_name(h1_text, title)
        else:
            # Check if it looks like a reference page
            if re.search(r'(?:api|cli|command)\s+reference', title + text[:500], re.IGNORECASE):
                doc_type = DocType.REFERENCE
            elif re.search(r'(?:tutorial|guide|how\s+to|getting\s+started)', title + text[:500], re.IGNORECASE):
                doc_type = DocType.TUTORIAL
            
            tool_name = url_signals["tool_from_url"]
        
        return doc_type, tool_name, subcommand, confidence
    
    def _extract_subcommand_name(self, h1_text: str, title: str) -> str:
        """Extract subcommand name from heading or title."""
        # Try patterns like "scan command" or "the scan subcommand"
        for text in [h1_text, title]:
            match = re.match(r'^(?:the\s+)?(\w+)\s+(?:command|subcommand)', text, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        
        # Try to get first word if it looks like a command
        for text in [h1_text, title]:
            words = text.split()
            if words and re.match(r'^[a-z][a-z0-9_-]*$', words[0], re.IGNORECASE):
                return words[0].lower()
        
        return ""
    
    def fetch_url(self, url: str, validate: bool = True) -> Optional[KnowledgeDoc]:
        """
        Fetch documentation from a URL.
        
        Args:
            url: URL to fetch
            validate: Whether to validate the URL first (recommended)
            
        Returns:
            KnowledgeDoc with raw content, or None if fetch failed
        """
        logger.info(f"Fetching documentation from {url}")
        
        # Validate URL first
        if validate:
            validation = self.validate_url(url)
            if not validation.is_valid:
                logger.error(f"URL validation failed: {validation.message}")
                return None
        
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
        extract_info: bool = True,
        is_subcommand: bool = None,
        parent_tool: str = None
    ) -> Tuple[Optional[KnowledgeDoc], Optional[ExtractedDocInfo], Optional[PageValidation]]:
        """
        Import documentation from URL and optionally extract info.
        
        Args:
            url: URL to import
            tool_name: Optional tool name to link to
            extract_info: Whether to extract structured info
            is_subcommand: If True, treat as subcommand doc. If None, auto-detect.
            parent_tool: Parent tool name if this is a subcommand
            
        Returns:
            Tuple of (KnowledgeDoc, ExtractedDocInfo or None, PageValidation)
        """
        # First, validate the URL
        validation = self.validate_url(url)
        
        if not validation.is_valid:
            logger.error(f"URL validation failed: {validation.message}")
            return None, None, validation
        
        # Fetch with validation already done
        doc = self.fetch_url(url, validate=False)
        if not doc:
            return None, None, validation
        
        info = None
        if extract_info:
            info = self.extract_info(doc)
            
            # Apply validation detection results
            info.doc_type = validation.doc_type
            
            # Determine if subcommand based on user input or auto-detection
            if is_subcommand is True:
                info.doc_type = DocType.SUBCOMMAND
                info.parent_tool = parent_tool or tool_name or validation.detected_tool
            elif is_subcommand is False:
                info.doc_type = DocType.MAIN_TOOL
            elif validation.doc_type == DocType.SUBCOMMAND:
                # Auto-detected as subcommand
                info.parent_tool = validation.detected_tool
                info.detected_subcommand = validation.detected_subcommand
            
            doc.extracted_info = {
                "title": info.title,
                "description": info.description,
                "commands_count": len(info.commands),
                "errors_count": len(info.errors),
                "env_vars_count": len(info.env_vars),
                "confidence": info.confidence,
                "doc_type": info.doc_type.value if info.doc_type else "unknown",
                "parent_tool": info.parent_tool,
                "detected_subcommand": info.detected_subcommand,
            }
        
        # Link to tool if specified
        if tool_name:
            store = get_knowledge_store()
            tool = store.get_tool(name=tool_name)
            if tool:
                doc.tool_id = tool.id
        
        return doc, info, validation
    
    def to_tool_definition(
        self,
        info: ExtractedDocInfo,
        tool_name: str,
        source_url: str = "",
        is_subcommand: bool = False,
        subcommand_name: str = ""
    ) -> ToolDefinition:
        """
        Convert extracted info to ToolDefinition.
        
        Args:
            info: ExtractedDocInfo from extraction
            tool_name: Name for the tool (parent tool if subcommand)
            source_url: Source URL for reference
            is_subcommand: Whether this doc describes a subcommand
            subcommand_name: Name of the subcommand (if is_subcommand)
            
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
        
        # Handle subcommand case
        if is_subcommand and subcommand_name:
            # For subcommand docs, add the full command pattern
            full_command = f"{tool_name} {subcommand_name}"
            if full_command not in tool.patterns_commands:
                tool.patterns_commands.append(full_command)
            
            # Update description to note this is from subcommand docs
            if info.description:
                tool.description = f"{subcommand_name}: {info.description}"
        
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
