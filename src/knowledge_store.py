"""
Knowledge Store - SQLite-based storage for internal tool knowledge.

Implements Phase 1 of AI Learning System:
- Tool definitions with recognition patterns
- Error patterns and fix suggestions
- Documentation import storage
- Source analysis tracking

Database location: /app/data/knowledge.db (persisted via agent_data Docker volume)

Schema Version: 1.0
"""

import sqlite3
import logging
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum

logger = logging.getLogger("jenkins-agent.knowledge")

# Default database path
DEFAULT_DB_PATH = "/app/data/knowledge.db"

# Schema version for migrations
SCHEMA_VERSION = "1.0"


class ToolCategory(str, Enum):
    """Tool categories for classification."""
    DEPLOYMENT = "deployment"
    BUILD = "build"
    TEST = "test"
    INFRASTRUCTURE = "infrastructure"
    MONITORING = "monitoring"
    SECURITY = "security"
    UTILITY = "utility"
    UNKNOWN = "unknown"


class ErrorCategory(str, Enum):
    """Error categories matching existing system."""
    CREDENTIAL = "CREDENTIAL"
    NETWORK = "NETWORK"
    PERMISSION = "PERMISSION"
    CONFIGURATION = "CONFIGURATION"
    BUILD = "BUILD"
    TEST = "TEST"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    GROOVY_LIBRARY = "GROOVY_LIBRARY"
    GROOVY_CPS = "GROOVY_CPS"
    TOOL_ERROR = "TOOL_ERROR"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    """How knowledge was added."""
    SOURCE_ANALYSIS = "source_analysis"
    MANUAL = "manual"
    DOC_IMPORT = "doc_import"


@dataclass
class ToolArgument:
    """Command-line argument definition."""
    name: str
    aliases: List[str] = field(default_factory=list)
    required: bool = False
    default: Optional[str] = None
    description: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolArgument":
        return cls(**data)


@dataclass
class ToolError:
    """Error pattern definition for a tool."""
    id: Optional[int] = None
    tool_id: Optional[int] = None
    code: str = ""                      # e.g., "A2L_AUTH_FAILED"
    pattern: str = ""                   # Regex pattern to match
    exit_code: Optional[int] = None
    category: str = "UNKNOWN"           # ErrorCategory value
    description: str = ""
    fix: str = ""                       # Fix suggestion
    retriable: bool = False
    confidence: float = 1.0
    created_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool_id": self.tool_id,
            "code": self.code,
            "pattern": self.pattern,
            "exit_code": self.exit_code,
            "category": self.category,
            "description": self.description,
            "fix": self.fix,
            "retriable": self.retriable,
            "confidence": self.confidence,
        }
    
    @classmethod
    def from_row(cls, row: tuple) -> "ToolError":
        """Create from database row."""
        return cls(
            id=row[0],
            tool_id=row[1],
            code=row[2],
            pattern=row[3],
            exit_code=row[4],
            category=row[5],
            description=row[6],
            fix=row[7],
            retriable=bool(row[8]),
            confidence=row[9],
            created_at=row[10],
        )
    
    def matches(self, text: str) -> bool:
        """Check if this error pattern matches the given text."""
        if not self.pattern:
            return False
        try:
            return bool(re.search(self.pattern, text, re.IGNORECASE))
        except re.error:
            # Invalid regex, try simple substring match
            return self.pattern.lower() in text.lower()


@dataclass
class ToolDefinition:
    """Complete tool definition with all metadata."""
    id: Optional[int] = None
    name: str = ""
    aliases: List[str] = field(default_factory=list)
    version: str = ""
    category: str = "utility"           # ToolCategory value
    description: str = ""
    owner: str = ""
    docs_url: str = ""
    source_repo: str = ""
    
    # Recognition patterns
    patterns_commands: List[str] = field(default_factory=list)
    patterns_log_signatures: List[str] = field(default_factory=list)
    patterns_env_vars: List[str] = field(default_factory=list)
    
    # Arguments
    arguments: List[ToolArgument] = field(default_factory=list)
    
    # Dependencies
    dependencies_tools: List[str] = field(default_factory=list)
    dependencies_services: List[str] = field(default_factory=list)
    dependencies_credentials: List[str] = field(default_factory=list)
    
    # Errors (populated separately)
    errors: List[ToolError] = field(default_factory=list)
    
    # Metadata
    added_by: str = "manual"            # SourceType value
    source_file: str = ""               # Entry point if from source analysis
    confidence: float = 1.0
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "version": self.version,
            "category": self.category,
            "description": self.description,
            "owner": self.owner,
            "docs_url": self.docs_url,
            "source_repo": self.source_repo,
            "patterns": {
                "commands": self.patterns_commands,
                "log_signatures": self.patterns_log_signatures,
                "env_vars": self.patterns_env_vars,
            },
            "arguments": [arg.to_dict() for arg in self.arguments],
            "dependencies": {
                "tools": self.dependencies_tools,
                "services": self.dependencies_services,
                "credentials": self.dependencies_credentials,
            },
            "errors": [err.to_dict() for err in self.errors],
            "metadata": {
                "added_by": self.added_by,
                "source_file": self.source_file,
                "confidence": self.confidence,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
        }
    
    def to_yaml_template(self) -> str:
        """Generate YAML template for this tool."""
        import yaml
        
        template = {
            "schema_version": SCHEMA_VERSION,
            "tool": {
                "name": self.name,
                "aliases": self.aliases,
                "version": self.version,
                "category": self.category,
                "description": self.description,
                "owner": self.owner,
                "docs_url": self.docs_url,
                "source_repo": self.source_repo,
                "patterns": {
                    "commands": self.patterns_commands,
                    "log_signatures": self.patterns_log_signatures,
                    "env_vars": self.patterns_env_vars,
                },
                "arguments": [arg.to_dict() for arg in self.arguments],
                "errors": [
                    {
                        "code": err.code,
                        "pattern": err.pattern,
                        "exit_code": err.exit_code,
                        "category": err.category,
                        "description": err.description,
                        "fix": err.fix,
                        "retriable": err.retriable,
                    }
                    for err in self.errors
                ],
                "dependencies": {
                    "tools": self.dependencies_tools,
                    "services": self.dependencies_services,
                    "credentials": self.dependencies_credentials,
                },
            },
        }
        
        return yaml.dump(template, default_flow_style=False, sort_keys=False)
    
    @classmethod
    def from_row(cls, row: tuple) -> "ToolDefinition":
        """Create from database row."""
        return cls(
            id=row[0],
            name=row[1],
            aliases=json.loads(row[2]) if row[2] else [],
            version=row[3] or "",
            category=row[4] or "utility",
            description=row[5] or "",
            owner=row[6] or "",
            docs_url=row[7] or "",
            source_repo=row[8] or "",
            patterns_commands=json.loads(row[9]) if row[9] else [],
            patterns_log_signatures=json.loads(row[10]) if row[10] else [],
            patterns_env_vars=json.loads(row[11]) if row[11] else [],
            arguments=[ToolArgument.from_dict(a) for a in json.loads(row[12])] if row[12] else [],
            dependencies_tools=json.loads(row[13]).get("tools", []) if row[13] else [],
            dependencies_services=json.loads(row[13]).get("services", []) if row[13] else [],
            dependencies_credentials=json.loads(row[13]).get("credentials", []) if row[13] else [],
            added_by=row[14] or "manual",
            source_file=row[15] or "",
            confidence=row[16] if row[16] is not None else 1.0,
            created_at=row[17] or "",
            updated_at=row[18] or "",
        )
    
    @classmethod
    def from_yaml(cls, yaml_content: str) -> "ToolDefinition":
        """Parse tool definition from YAML template."""
        import yaml
        
        data = yaml.safe_load(yaml_content)
        tool_data = data.get("tool", data)
        
        patterns = tool_data.get("patterns", {})
        dependencies = tool_data.get("dependencies", {})
        
        tool = cls(
            name=tool_data.get("name", ""),
            aliases=tool_data.get("aliases", []),
            version=tool_data.get("version", ""),
            category=tool_data.get("category", "utility"),
            description=tool_data.get("description", ""),
            owner=tool_data.get("owner", ""),
            docs_url=tool_data.get("docs_url", ""),
            source_repo=tool_data.get("source_repo", ""),
            patterns_commands=patterns.get("commands", []),
            patterns_log_signatures=patterns.get("log_signatures", []),
            patterns_env_vars=patterns.get("env_vars", []),
            arguments=[
                ToolArgument.from_dict(a) for a in tool_data.get("arguments", [])
            ],
            dependencies_tools=dependencies.get("tools", []),
            dependencies_services=dependencies.get("services", []),
            dependencies_credentials=dependencies.get("credentials", []),
            added_by=tool_data.get("metadata", {}).get("added_by", "manual"),
        )
        
        # Parse errors
        for err_data in tool_data.get("errors", []):
            tool.errors.append(ToolError(
                code=err_data.get("code", ""),
                pattern=err_data.get("pattern", ""),
                exit_code=err_data.get("exit_code"),
                category=err_data.get("category", "UNKNOWN"),
                description=err_data.get("description", ""),
                fix=err_data.get("fix", ""),
                retriable=err_data.get("retriable", False),
            ))
        
        return tool
    
    def matches_command(self, command: str) -> bool:
        """Check if a command matches this tool's patterns."""
        command_lower = command.lower()
        
        # Check exact name match
        if self.name.lower() in command_lower:
            return True
        
        # Check aliases
        for alias in self.aliases:
            if alias.lower() in command_lower:
                return True
        
        # Check command patterns
        for pattern in self.patterns_commands:
            if pattern.startswith("regex:"):
                try:
                    if re.search(pattern[6:], command, re.IGNORECASE):
                        return True
                except re.error:
                    pass
            elif pattern.lower() in command_lower:
                return True
        
        return False
    
    def matches_log_line(self, log_line: str) -> bool:
        """Check if a log line matches this tool's signatures."""
        log_lower = log_line.lower()
        
        for signature in self.patterns_log_signatures:
            if signature.startswith("regex:"):
                try:
                    if re.search(signature[6:], log_line, re.IGNORECASE):
                        return True
                except re.error:
                    pass
            elif signature.lower() in log_lower:
                return True
        
        return False


@dataclass
class KnowledgeDoc:
    """Imported documentation."""
    id: Optional[int] = None
    tool_id: Optional[int] = None
    source_type: str = "url"            # url|file|manual
    source_url: str = ""
    title: str = ""
    content: str = ""
    content_type: str = "text"          # markdown|html|text
    extracted_info: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "tool_id": self.tool_id,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "title": self.title,
            "content": self.content[:500] + "..." if len(self.content) > 500 else self.content,
            "content_type": self.content_type,
            "extracted_info": self.extracted_info,
            "created_at": self.created_at,
        }
    
    @classmethod
    def from_row(cls, row: tuple) -> "KnowledgeDoc":
        return cls(
            id=row[0],
            tool_id=row[1],
            source_type=row[2],
            source_url=row[3],
            title=row[4],
            content=row[5],
            content_type=row[6],
            extracted_info=json.loads(row[7]) if row[7] else {},
            created_at=row[8],
        )


@dataclass
class SourceAnalysisLog:
    """Track source code analysis runs."""
    id: Optional[int] = None
    repo_url: str = ""
    branch: str = ""
    entry_point: str = ""
    depth: int = 2
    files_analyzed: List[str] = field(default_factory=list)
    tools_extracted: List[int] = field(default_factory=list)
    status: str = "pending"             # success|partial|failed
    error_message: str = ""
    created_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_row(cls, row: tuple) -> "SourceAnalysisLog":
        return cls(
            id=row[0],
            repo_url=row[1],
            branch=row[2],
            entry_point=row[3],
            depth=row[4],
            files_analyzed=json.loads(row[5]) if row[5] else [],
            tools_extracted=json.loads(row[6]) if row[6] else [],
            status=row[7],
            error_message=row[8],
            created_at=row[9],
        )


class KnowledgeStore:
    """
    SQLite-based knowledge storage for internal tools.
    
    Usage:
        store = KnowledgeStore()
        
        # Add tool
        tool_id = store.add_tool(tool_definition)
        
        # Find tool by command
        matches = store.identify_tool("a2l deploy --cluster prod")
        
        # Match error
        error_matches = store.match_error("A2L_AUTH_FAILED: token expired")
    """
    
    def __init__(self, db_path: str = None):
        """
        Initialize knowledge store.
        
        Args:
            db_path: Path to SQLite database. Defaults to /app/data/knowledge.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        logger.info(f"KnowledgeStore initialized at {self.db_path}")
    
    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # Tools table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    aliases TEXT,
                    version TEXT,
                    category TEXT NOT NULL DEFAULT 'utility',
                    description TEXT,
                    owner TEXT,
                    docs_url TEXT,
                    source_repo TEXT,
                    patterns_commands TEXT,
                    patterns_log_signatures TEXT,
                    patterns_env_vars TEXT,
                    arguments TEXT,
                    dependencies TEXT,
                    added_by TEXT NOT NULL DEFAULT 'manual',
                    source_file TEXT,
                    confidence REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Tool errors table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    exit_code INTEGER,
                    category TEXT NOT NULL DEFAULT 'UNKNOWN',
                    description TEXT,
                    fix TEXT,
                    retriable INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE CASCADE
                )
            """)
            
            # Knowledge docs table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_docs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_id INTEGER,
                    source_type TEXT NOT NULL DEFAULT 'url',
                    source_url TEXT,
                    title TEXT,
                    content TEXT NOT NULL,
                    content_type TEXT DEFAULT 'text',
                    extracted_info TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tool_id) REFERENCES tools(id) ON DELETE SET NULL
                )
            """)
            
            # Source analysis log table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS source_analysis_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_url TEXT NOT NULL,
                    branch TEXT,
                    entry_point TEXT,
                    depth INTEGER DEFAULT 2,
                    files_analyzed TEXT,
                    tools_extracted TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_category ON tools(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_errors_tool_id ON tool_errors(tool_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_errors_category ON tool_errors(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_docs_tool_id ON knowledge_docs(tool_id)")
            
            # Schema version tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Insert current version if not exists
            conn.execute("""
                INSERT OR IGNORE INTO schema_version (version) VALUES (?)
            """, (SCHEMA_VERSION,))
            
            conn.commit()
    
    # =========================================================================
    # Tool CRUD Operations
    # =========================================================================
    
    def add_tool(self, tool: ToolDefinition) -> int:
        """
        Add a new tool definition.
        
        Args:
            tool: ToolDefinition to store
            
        Returns:
            ID of the inserted tool
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            # Insert tool
            cursor = conn.execute("""
                INSERT INTO tools (
                    name, aliases, version, category, description,
                    owner, docs_url, source_repo,
                    patterns_commands, patterns_log_signatures, patterns_env_vars,
                    arguments, dependencies,
                    added_by, source_file, confidence,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tool.name,
                json.dumps(tool.aliases),
                tool.version,
                tool.category,
                tool.description,
                tool.owner,
                tool.docs_url,
                tool.source_repo,
                json.dumps(tool.patterns_commands),
                json.dumps(tool.patterns_log_signatures),
                json.dumps(tool.patterns_env_vars),
                json.dumps([arg.to_dict() for arg in tool.arguments]),
                json.dumps({
                    "tools": tool.dependencies_tools,
                    "services": tool.dependencies_services,
                    "credentials": tool.dependencies_credentials,
                }),
                tool.added_by,
                tool.source_file,
                tool.confidence,
                now,
                now,
            ))
            
            tool_id = cursor.lastrowid
            
            # Insert errors
            for error in tool.errors:
                conn.execute("""
                    INSERT INTO tool_errors (
                        tool_id, code, pattern, exit_code, category,
                        description, fix, retriable, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tool_id,
                    error.code,
                    error.pattern,
                    error.exit_code,
                    error.category,
                    error.description,
                    error.fix,
                    1 if error.retriable else 0,
                    error.confidence,
                ))
            
            conn.commit()
            
            logger.info(f"Added tool '{tool.name}' with {len(tool.errors)} error patterns")
            
            return tool_id
    
    def update_tool(self, tool_id: int, tool: ToolDefinition) -> bool:
        """
        Update an existing tool definition.
        
        Args:
            tool_id: ID of tool to update
            tool: Updated ToolDefinition
            
        Returns:
            True if updated, False if not found
        """
        now = datetime.utcnow().isoformat()
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                UPDATE tools SET
                    name = ?, aliases = ?, version = ?, category = ?, description = ?,
                    owner = ?, docs_url = ?, source_repo = ?,
                    patterns_commands = ?, patterns_log_signatures = ?, patterns_env_vars = ?,
                    arguments = ?, dependencies = ?,
                    source_file = ?, confidence = ?, updated_at = ?
                WHERE id = ?
            """, (
                tool.name,
                json.dumps(tool.aliases),
                tool.version,
                tool.category,
                tool.description,
                tool.owner,
                tool.docs_url,
                tool.source_repo,
                json.dumps(tool.patterns_commands),
                json.dumps(tool.patterns_log_signatures),
                json.dumps(tool.patterns_env_vars),
                json.dumps([arg.to_dict() for arg in tool.arguments]),
                json.dumps({
                    "tools": tool.dependencies_tools,
                    "services": tool.dependencies_services,
                    "credentials": tool.dependencies_credentials,
                }),
                tool.source_file,
                tool.confidence,
                now,
                tool_id,
            ))
            
            if cursor.rowcount == 0:
                return False
            
            # Delete existing errors and re-insert
            conn.execute("DELETE FROM tool_errors WHERE tool_id = ?", (tool_id,))
            
            for error in tool.errors:
                conn.execute("""
                    INSERT INTO tool_errors (
                        tool_id, code, pattern, exit_code, category,
                        description, fix, retriable, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tool_id,
                    error.code,
                    error.pattern,
                    error.exit_code,
                    error.category,
                    error.description,
                    error.fix,
                    1 if error.retriable else 0,
                    error.confidence,
                ))
            
            conn.commit()
            
            logger.info(f"Updated tool '{tool.name}' (id={tool_id})")
            
            return True
    
    def add_or_merge_tool(self, tool: ToolDefinition) -> Tuple[int, bool]:
        """
        Add a new tool or merge with existing tool if name matches.
        
        When merging:
        - Patterns (commands, log signatures, env vars) are merged (deduplicated)
        - Errors are merged by code (new codes added, existing codes updated)
        - Other fields are updated only if the new value is non-empty
        
        Args:
            tool: ToolDefinition to add or merge
            
        Returns:
            Tuple of (tool_id, was_merged)
        """
        existing = self.get_tool(name=tool.name)
        
        if not existing:
            # No existing tool - add new
            tool_id = self.add_tool(tool)
            return (tool_id, False)
        
        # Merge patterns (deduplicate)
        merged_commands = list(set(existing.patterns_commands + tool.patterns_commands))
        merged_log_sigs = list(set(existing.patterns_log_signatures + tool.patterns_log_signatures))
        merged_env_vars = list(set(existing.patterns_env_vars + tool.patterns_env_vars))
        
        # Merge errors by code
        existing_error_codes = {e.code: e for e in existing.errors}
        for new_error in tool.errors:
            if new_error.code not in existing_error_codes:
                existing.errors.append(new_error)
            # If code exists, keep existing (could add update logic here)
        
        # Update patterns
        existing.patterns_commands = merged_commands
        existing.patterns_log_signatures = merged_log_sigs
        existing.patterns_env_vars = merged_env_vars
        
        # Update description if new one is longer/better
        if tool.description and len(tool.description) > len(existing.description or ""):
            existing.description = tool.description
        
        # Update docs_url if not set
        if tool.docs_url and not existing.docs_url:
            existing.docs_url = tool.docs_url
        
        # Update source info
        if tool.source_file:
            existing.source_file = tool.source_file
        
        # Merge aliases
        existing.aliases = list(set(existing.aliases + tool.aliases))
        
        # Update confidence if higher
        if tool.confidence > existing.confidence:
            existing.confidence = tool.confidence
        
        # Save merged tool
        self.update_tool(existing.id, existing)
        
        logger.info(f"Merged tool '{tool.name}' (id={existing.id}): "
                   f"+{len(tool.patterns_commands)} commands, "
                   f"+{len(tool.errors)} error patterns")
        
        return (existing.id, True)
    
    def get_tool(self, tool_id: int = None, name: str = None) -> Optional[ToolDefinition]:
        """
        Get a tool by ID or name.
        
        Args:
            tool_id: Tool ID
            name: Tool name
            
        Returns:
            ToolDefinition or None
        """
        with sqlite3.connect(self.db_path) as conn:
            if tool_id:
                cursor = conn.execute("SELECT * FROM tools WHERE id = ?", (tool_id,))
            elif name:
                cursor = conn.execute("SELECT * FROM tools WHERE name = ?", (name,))
            else:
                return None
            
            row = cursor.fetchone()
            if not row:
                return None
            
            tool = ToolDefinition.from_row(row)
            
            # Load errors
            errors_cursor = conn.execute(
                "SELECT * FROM tool_errors WHERE tool_id = ?", (tool.id,)
            )
            tool.errors = [ToolError.from_row(r) for r in errors_cursor.fetchall()]
            
            return tool
    
    def list_tools(
        self, 
        category: str = None, 
        limit: int = 100
    ) -> List[ToolDefinition]:
        """
        List all tools, optionally filtered by category.
        
        Args:
            category: Optional category filter
            limit: Maximum results
            
        Returns:
            List of ToolDefinition objects (without errors populated)
        """
        with sqlite3.connect(self.db_path) as conn:
            if category:
                cursor = conn.execute(
                    "SELECT * FROM tools WHERE category = ? LIMIT ?",
                    (category, limit)
                )
            else:
                cursor = conn.execute("SELECT * FROM tools LIMIT ?", (limit,))
            
            tools = []
            for row in cursor.fetchall():
                tool = ToolDefinition.from_row(row)
                # Count errors for summary
                err_count = conn.execute(
                    "SELECT COUNT(*) FROM tool_errors WHERE tool_id = ?", (tool.id,)
                ).fetchone()[0]
                tool.errors = [ToolError()] * err_count  # Placeholder for count
                tools.append(tool)
            
            return tools
    
    def delete_tool(self, tool_id: int) -> bool:
        """
        Delete a tool and its errors.
        
        Args:
            tool_id: Tool ID
            
        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM tools WHERE id = ?", (tool_id,))
            conn.commit()
            
            if cursor.rowcount > 0:
                logger.info(f"Deleted tool id={tool_id}")
                return True
            return False
    
    # =========================================================================
    # Tool Identification & Error Matching
    # =========================================================================
    
    def identify_tool(self, query: str) -> List[Tuple[ToolDefinition, float]]:
        """
        Identify tools that match a command or log line.
        
        Args:
            query: Command string or log line
            
        Returns:
            List of (ToolDefinition, confidence) tuples, sorted by confidence
        """
        tools = self.list_tools()
        matches = []
        
        for tool in tools:
            # Load full tool with patterns
            full_tool = self.get_tool(tool_id=tool.id)
            if not full_tool:
                continue
            
            confidence = 0.0
            
            # Check command patterns
            if full_tool.matches_command(query):
                confidence = max(confidence, 0.9)
            
            # Check log signatures
            if full_tool.matches_log_line(query):
                confidence = max(confidence, 0.8)
            
            # Check simple name/alias match
            query_lower = query.lower()
            if full_tool.name.lower() in query_lower:
                confidence = max(confidence, 0.95)
            for alias in full_tool.aliases:
                if alias.lower() in query_lower:
                    confidence = max(confidence, 0.85)
            
            if confidence > 0:
                matches.append((full_tool, confidence))
        
        # Sort by confidence descending
        matches.sort(key=lambda x: x[1], reverse=True)
        
        return matches
    
    def match_error(self, error_text: str, tool_name: str = None) -> List[Tuple[ToolError, ToolDefinition, float]]:
        """
        Find error patterns that match the given error text.
        
        Args:
            error_text: Error message to match
            tool_name: Optional tool name to filter
            
        Returns:
            List of (ToolError, ToolDefinition, confidence) tuples
        """
        matches = []
        
        with sqlite3.connect(self.db_path) as conn:
            if tool_name:
                # Get specific tool
                tool = self.get_tool(name=tool_name)
                if tool:
                    tools = [tool]
                else:
                    tools = []
            else:
                tools = [self.get_tool(tool_id=t.id) for t in self.list_tools()]
                tools = [t for t in tools if t]
            
            for tool in tools:
                for error in tool.errors:
                    if error.matches(error_text):
                        confidence = error.confidence
                        
                        # Boost confidence if error code appears in text
                        if error.code and error.code.lower() in error_text.lower():
                            confidence = min(confidence + 0.1, 1.0)
                        
                        matches.append((error, tool, confidence))
        
        # Sort by confidence descending
        matches.sort(key=lambda x: x[2], reverse=True)
        
        return matches
    
    # =========================================================================
    # Knowledge Docs
    # =========================================================================
    
    def add_doc(self, doc: KnowledgeDoc) -> int:
        """Add a documentation entry."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO knowledge_docs (
                    tool_id, source_type, source_url, title,
                    content, content_type, extracted_info
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                doc.tool_id,
                doc.source_type,
                doc.source_url,
                doc.title,
                doc.content,
                doc.content_type,
                json.dumps(doc.extracted_info),
            ))
            conn.commit()
            
            return cursor.lastrowid
    
    def get_docs_for_tool(self, tool_id: int) -> List[KnowledgeDoc]:
        """Get all documentation for a tool."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM knowledge_docs WHERE tool_id = ?", (tool_id,)
            )
            return [KnowledgeDoc.from_row(row) for row in cursor.fetchall()]
    
    def search_docs(self, query: str, limit: int = 10) -> List[KnowledgeDoc]:
        """Simple text search across documentation content."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM knowledge_docs 
                WHERE content LIKE ? OR title LIKE ?
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", limit))
            
            return [KnowledgeDoc.from_row(row) for row in cursor.fetchall()]
    
    def delete_doc(self, doc_id: int) -> bool:
        """
        Delete a document from the knowledge store.
        
        Args:
            doc_id: ID of document to delete
            
        Returns:
            True if deleted, False if not found
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM knowledge_docs WHERE id = ?", 
                (doc_id,)
            )
            conn.commit()
            
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted document id={doc_id}")
            
            return deleted
    
    # =========================================================================
    # Source Analysis Log
    # =========================================================================
    
    def log_source_analysis(self, log: SourceAnalysisLog) -> int:
        """Log a source analysis run."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO source_analysis_log (
                    repo_url, branch, entry_point, depth,
                    files_analyzed, tools_extracted, status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log.repo_url,
                log.branch,
                log.entry_point,
                log.depth,
                json.dumps(log.files_analyzed),
                json.dumps(log.tools_extracted),
                log.status,
                log.error_message,
            ))
            conn.commit()
            
            return cursor.lastrowid
    
    def get_analysis_history(self, limit: int = 20) -> List[SourceAnalysisLog]:
        """Get recent source analysis history."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT * FROM source_analysis_log 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
            
            return [SourceAnalysisLog.from_row(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # Statistics
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge store statistics."""
        with sqlite3.connect(self.db_path) as conn:
            tools_count = conn.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
            errors_count = conn.execute("SELECT COUNT(*) FROM tool_errors").fetchone()[0]
            docs_count = conn.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0]
            
            categories = conn.execute("""
                SELECT category, COUNT(*) as cnt 
                FROM tools 
                GROUP BY category 
                ORDER BY cnt DESC
            """).fetchall()
            
            error_categories = conn.execute("""
                SELECT category, COUNT(*) as cnt 
                FROM tool_errors 
                GROUP BY category 
                ORDER BY cnt DESC
            """).fetchall()
            
            return {
                "total_tools": tools_count,
                "total_error_patterns": errors_count,
                "total_docs": docs_count,
                "tools_by_category": dict(categories),
                "errors_by_category": dict(error_categories),
                "schema_version": SCHEMA_VERSION,
            }
    
    # =========================================================================
    # AI Prompt Integration
    # =========================================================================
    
    def format_tool_context_for_prompt(self, tool: ToolDefinition) -> str:
        """
        Format tool knowledge for injection into AI prompt.
        
        Args:
            tool: ToolDefinition to format
            
        Returns:
            Formatted context string for AI prompt
        """
        lines = [
            f"## INTERNAL TOOL: {tool.name}",
            f"Category: {tool.category}",
        ]
        
        if tool.description:
            lines.append(f"Description: {tool.description}")
        
        if tool.patterns_commands:
            lines.append(f"Commands: {', '.join(tool.patterns_commands[:5])}")
        
        if tool.errors:
            lines.append("Known Errors:")
            for err in tool.errors[:5]:  # Limit to 5 errors
                lines.append(f"  - {err.code}: {err.description}")
                if err.fix:
                    lines.append(f"    Fix: {err.fix}")
        
        return "\n".join(lines)
    
    def get_relevant_knowledge_for_log(self, log_text: str, limit: int = 3) -> str:
        """
        Get relevant tool knowledge for a log snippet.
        
        Used to inject internal tool context into AI analysis prompts.
        
        Args:
            log_text: Log text to analyze
            limit: Maximum tools to include
            
        Returns:
            Formatted context string for AI prompt
        """
        # Identify relevant tools
        tool_matches = self.identify_tool(log_text)[:limit]
        
        if not tool_matches:
            return ""
        
        sections = ["## INTERNAL TOOLS CONTEXT ##\n"]
        
        for tool, confidence in tool_matches:
            sections.append(self.format_tool_context_for_prompt(tool))
            sections.append("")
        
        # Check for matching errors
        error_matches = self.match_error(log_text)[:3]
        
        if error_matches:
            sections.append("## KNOWN ERROR PATTERNS ##\n")
            for error, tool, confidence in error_matches:
                sections.append(f"Tool: {tool.name}")
                sections.append(f"Error: {error.code} - {error.description}")
                sections.append(f"Category: {error.category}")
                sections.append(f"Fix: {error.fix}")
                sections.append(f"Retriable: {'Yes' if error.retriable else 'No'}")
                sections.append("")
        
        return "\n".join(sections)


# Global instance
_store: Optional[KnowledgeStore] = None


def get_knowledge_store(db_path: str = None) -> KnowledgeStore:
    """Get or create the global knowledge store instance."""
    global _store
    if _store is None:
        _store = KnowledgeStore(db_path)
    return _store
