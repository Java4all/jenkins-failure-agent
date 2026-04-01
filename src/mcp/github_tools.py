"""
GitHub/GitLab MCP tools for source code investigation.

These tools allow the LLM to fetch and search source code from
GitHub/GitLab repositories during agentic investigation.
"""

import logging
from typing import Optional, List

from .registry import ToolRegistry, ToolCategory

logger = logging.getLogger("jenkins-agent.mcp.github_tools")


def register_github_tools(registry: ToolRegistry):
    """Register all GitHub/GitLab source code tools."""
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get a file from a GitHub/GitLab repository.",
    )
    def get_file(repo: str, path: str, ref: str = "main") -> str:
        """
        Get a file from a repository.
        
        Args:
            repo: Repository in 'owner/repo' format (e.g., 'myorg/jenkins-shared-lib')
            path: Path to the file (e.g., 'vars/deployApp.groovy')
            ref: Branch, tag, or commit SHA (default: main)
            
        Returns:
            File content as text.
        """
        client = registry.get_context('github_client')
        if not client:
            return "Error: GitHub client not configured"
        
        try:
            content = client.get_file_content(repo, path, ref)
            if content:
                return content
            return f"File not found: {path} in {repo}@{ref}"
        except Exception as e:
            return f"Error fetching file: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get a shared library file by library name and path.",
    )
    def get_library_file(library: str, path: str, ref: str = "main") -> str:
        """
        Get a file from a Jenkins shared library.
        
        Args:
            library: Library name as declared in @Library (e.g., 'my-pipeline-lib')
            path: Path within the library (e.g., 'vars/deployApp.groovy' or 'src/com/company/Helper.groovy')
            ref: Branch or tag (default: main)
            
        Returns:
            File content.
        """
        client = registry.get_context('github_client')
        if not client:
            return "Error: GitHub client not configured"
        
        try:
            # Look up library repository from mappings
            repo = client.get_library_repo(library)
            if not repo:
                return f"Error: No repository mapping found for library '{library}'. Configure library_mappings in config."
            
            content = client.get_file_content(repo, path, ref)
            if content:
                return f"# {library}/{path} @ {ref}\n\n{content}"
            return f"File not found: {path} in library '{library}'"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="List files in a repository directory.",
    )
    def list_directory(repo: str, path: str = "", ref: str = "main") -> list:
        """
        List files in a repository directory.
        
        Args:
            repo: Repository in 'owner/repo' format
            path: Directory path (empty for root)
            ref: Branch, tag, or commit
            
        Returns:
            List of files and directories.
        """
        client = registry.get_context('github_client')
        if not client:
            return [{"error": "GitHub client not configured"}]
        
        try:
            contents = client.list_directory(repo, path, ref)
            return [
                {
                    "name": item.get("name"),
                    "type": item.get("type"),  # "file" or "dir"
                    "path": item.get("path"),
                    "size": item.get("size"),
                }
                for item in contents
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="List files in a shared library's vars/ or src/ directory.",
    )
    def list_library_files(library: str, directory: str = "vars", ref: str = "main") -> list:
        """
        List files in a Jenkins shared library directory.
        
        Args:
            library: Library name as declared in @Library
            directory: Directory to list ('vars' for global vars, 'src' for classes)
            ref: Branch or tag
            
        Returns:
            List of files in the library.
        """
        client = registry.get_context('github_client')
        if not client:
            return [{"error": "GitHub client not configured"}]
        
        try:
            repo = client.get_library_repo(library)
            if not repo:
                return [{"error": f"No repository mapping for library '{library}'"}]
            
            contents = client.list_directory(repo, directory, ref)
            return [
                {
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "path": item.get("path"),
                }
                for item in contents
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Search for text in repository files.",
    )
    def search_code(repo: str, query: str, path_filter: str = "") -> list:
        """
        Search for code in a repository.
        
        Args:
            repo: Repository in 'owner/repo' format
            query: Search query (e.g., 'def deployApp' or 'CredentialManager')
            path_filter: Optional path prefix to filter results (e.g., 'src/')
            
        Returns:
            List of matching files with snippets.
        """
        client = registry.get_context('github_client')
        if not client:
            return [{"error": "GitHub client not configured"}]
        
        try:
            results = client.search_code(repo, query, path_filter)
            return [
                {
                    "file": r.get("path"),
                    "matches": r.get("matches", [])[:5],  # Limit matches per file
                }
                for r in results[:10]  # Limit total results
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Search for code in a shared library.",
    )
    def search_library_code(library: str, query: str, directory: str = "") -> list:
        """
        Search for code in a Jenkins shared library.
        
        Args:
            library: Library name
            query: Search query
            directory: Optional directory filter ('vars' or 'src')
            
        Returns:
            List of matching files with snippets.
        """
        client = registry.get_context('github_client')
        if not client:
            return [{"error": "GitHub client not configured"}]
        
        try:
            repo = client.get_library_repo(library)
            if not repo:
                return [{"error": f"No repository mapping for library '{library}'"}]
            
            results = client.search_code(repo, query, directory)
            return [
                {
                    "file": r.get("path"),
                    "matches": r.get("matches", [])[:5],
                }
                for r in results[:10]
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get the Jenkinsfile from a project repository.",
    )
    def get_jenkinsfile(repo: str, ref: str = "main", path: str = "Jenkinsfile") -> str:
        """
        Get the Jenkinsfile from a repository.
        
        Args:
            repo: Repository in 'owner/repo' format
            ref: Branch or commit
            path: Path to Jenkinsfile (default: 'Jenkinsfile')
            
        Returns:
            Jenkinsfile content.
        """
        client = registry.get_context('github_client')
        if not client:
            return "Error: GitHub client not configured"
        
        try:
            content = client.get_file_content(repo, path, ref)
            if content:
                return content
            
            # Try alternate locations
            for alt_path in ['Jenkinsfile', 'jenkins/Jenkinsfile', 'ci/Jenkinsfile']:
                content = client.get_file_content(repo, alt_path, ref)
                if content:
                    return f"# Found at {alt_path}\n\n{content}"
            
            return "Jenkinsfile not found"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get git blame information for a file to see who changed what.",
    )
    def get_blame(repo: str, path: str, ref: str = "main") -> list:
        """
        Get git blame for a file showing who changed each line.
        
        Args:
            repo: Repository in 'owner/repo' format
            path: Path to the file
            ref: Branch or commit
            
        Returns:
            Blame information with line ranges and authors.
        """
        client = registry.get_context('github_client')
        if not client:
            return [{"error": "GitHub client not configured"}]
        
        try:
            blame = client.get_blame(repo, path, ref)
            return [
                {
                    "start_line": b.get("start_line"),
                    "end_line": b.get("end_line"),
                    "author": b.get("author"),
                    "commit": b.get("commit_sha", "")[:8],
                    "date": b.get("date"),
                    "message": b.get("commit_message", "")[:100],
                }
                for b in blame[:20]  # Limit results
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get recent commits on a repository.",
    )
    def get_recent_commits(repo: str, ref: str = "main", limit: int = 10, path: str = "") -> list:
        """
        Get recent commits on a repository.
        
        Args:
            repo: Repository in 'owner/repo' format
            ref: Branch or tag
            limit: Maximum number of commits to return
            path: Optional path to filter commits that touched this file/directory
            
        Returns:
            List of recent commits.
        """
        client = registry.get_context('github_client')
        if not client:
            return [{"error": "GitHub client not configured"}]
        
        try:
            commits = client.get_commits(repo, ref, limit, path)
            return [
                {
                    "sha": c.get("sha", "")[:8],
                    "author": c.get("author"),
                    "date": c.get("date"),
                    "message": c.get("message", "")[:200],
                    "files_changed": c.get("files_changed", [])[:10],
                }
                for c in commits
            ]
        except Exception as e:
            return [{"error": str(e)}]
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get a specific Groovy class definition from a library.",
    )
    def get_class_definition(library: str, class_name: str, ref: str = "main") -> str:
        """
        Get a Groovy class definition from a shared library.
        
        Args:
            library: Library name
            class_name: Full class name (e.g., 'com.company.K8sHelper')
            ref: Branch or tag
            
        Returns:
            Class file content.
        """
        client = registry.get_context('github_client')
        if not client:
            return "Error: GitHub client not configured"
        
        try:
            repo = client.get_library_repo(library)
            if not repo:
                return f"Error: No repository mapping for library '{library}'"
            
            # Convert class name to path
            # com.company.K8sHelper -> src/com/company/K8sHelper.groovy
            path = "src/" + class_name.replace('.', '/') + ".groovy"
            
            content = client.get_file_content(repo, path, ref)
            if content:
                return f"# {class_name} from {library}\n# Path: {path}\n\n{content}"
            
            return f"Class not found: {class_name} (looked in {path})"
        except Exception as e:
            return f"Error: {str(e)}"
    
    @registry.tool(
        category=ToolCategory.GITHUB,
        description="Get the signature/parameters of a Groovy function or method.",
    )
    def get_function_signature(library: str, function_name: str, ref: str = "main") -> str:
        """
        Get the signature of a Jenkins shared library function.
        
        Args:
            library: Library name
            function_name: Function name (e.g., 'deployApp' for vars/deployApp.groovy)
            ref: Branch or tag
            
        Returns:
            Function signature and documentation.
        """
        client = registry.get_context('github_client')
        if not client:
            return "Error: GitHub client not configured"
        
        try:
            repo = client.get_library_repo(library)
            if not repo:
                return f"Error: No repository mapping for library '{library}'"
            
            # Check vars/ directory first
            path = f"vars/{function_name}.groovy"
            content = client.get_file_content(repo, path, ref)
            
            if content:
                # Extract the call method signature
                import re
                
                # Look for def call(...) pattern
                call_match = re.search(
                    r'def\s+call\s*\((.*?)\)',
                    content,
                    re.DOTALL
                )
                
                if call_match:
                    params = call_match.group(1).strip()
                    
                    # Look for documentation comment
                    doc_match = re.search(
                        r'/\*\*(.*?)\*/\s*def\s+call',
                        content,
                        re.DOTALL
                    )
                    doc = doc_match.group(1).strip() if doc_match else "No documentation"
                    
                    return f"""## {function_name}
                    
**Signature:** `{function_name}({params})`

**Documentation:**
{doc}

**Full source:**
```groovy
{content}
```"""
                
                return f"# {function_name}\n\n{content}"
            
            return f"Function not found: {function_name}"
        except Exception as e:
            return f"Error: {str(e)}"
    
    logger.info(f"Registered {len(registry.get_tools_by_category(ToolCategory.GITHUB))} GitHub tools")
