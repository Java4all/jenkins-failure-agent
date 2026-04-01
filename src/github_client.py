"""
GitHub client for fetching Jenkinsfile and shared library source code.

Supports:
- GitHub.com
- GitHub Enterprise Server
- Fetching Jenkinsfile from project repos
- Fetching shared library code (vars/, src/)
- Branch/tag/commit version resolution
- Caching to avoid repeated API calls
"""

import re
import base64
import time
import hashlib
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import requests
from urllib.parse import urljoin, quote


@dataclass
class GitHubConfig:
    """GitHub connection configuration."""
    # GitHub Enterprise base URL (e.g., https://github.mycompany.com)
    # For github.com, use https://api.github.com
    base_url: str = "https://api.github.com"
    
    # Personal access token with repo read access
    token: str = ""
    
    # Request timeout
    timeout: int = 30
    
    # SSL verification (set False for self-signed certs)
    verify_ssl: bool = True
    
    # Cache settings
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300  # 5 minutes
    
    # Rate limiting
    requests_per_second: float = 10.0


@dataclass
class LibraryConfig:
    """Configuration for a Jenkins shared library."""
    name: str
    repo: str  # owner/repo format
    default_branch: str = "main"
    # Optional: map library name to different repo
    # e.g., {"my-lib": "org/jenkins-shared-library"}


@dataclass
class FetchedFile:
    """A file fetched from GitHub."""
    path: str
    content: str
    repo: str
    ref: str  # branch, tag, or commit
    sha: str
    size: int
    url: str


@dataclass
class FetchedLibrary:
    """A fetched shared library with all its files."""
    name: str
    version: str  # branch, tag, or commit used
    repo: str
    files: Dict[str, str] = field(default_factory=dict)  # path -> content
    vars_functions: List[str] = field(default_factory=list)  # List of global vars
    src_classes: List[str] = field(default_factory=list)  # List of src classes
    fetch_errors: List[str] = field(default_factory=list)


@dataclass
class FetchResult:
    """Result of fetching code for analysis."""
    jenkinsfile: Optional[str] = None
    jenkinsfile_repo: str = ""
    jenkinsfile_ref: str = ""
    libraries: Dict[str, FetchedLibrary] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    from_cache: bool = False


class GitHubClient:
    """
    Client for fetching source code from GitHub/GitHub Enterprise.
    
    Usage:
        client = GitHubClient(GitHubConfig(
            base_url="https://github.mycompany.com/api/v3",
            token="ghp_xxxx"
        ))
        
        # Fetch Jenkinsfile
        jenkinsfile = client.fetch_jenkinsfile("org/my-project", "main")
        
        # Fetch shared library
        library = client.fetch_library("org/jenkins-shared-lib", "v1.0.0")
        
        # Fetch everything for a build
        result = client.fetch_for_analysis(
            project_repo="org/my-project",
            project_ref="feature/xyz",
            library_refs=[("my-lib", "org/jenkins-shared-lib", "main")]
        )
    """
    
    def __init__(self, config: GitHubConfig, library_configs: Optional[List[LibraryConfig]] = None):
        self.config = config
        self.library_configs = {lc.name: lc for lc in (library_configs or [])}
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._last_request_time = 0.0
        
        # Normalize base URL
        self.base_url = config.base_url.rstrip("/")
        if not self.base_url.endswith("/api/v3") and "api.github.com" not in self.base_url:
            # GitHub Enterprise uses /api/v3 path
            if "/api/" not in self.base_url:
                self.base_url = f"{self.base_url}/api/v3"
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Jenkins-Failure-Agent/1.0",
        }
        if self.config.token:
            headers["Authorization"] = f"token {self.config.token}"
        return headers
    
    def _rate_limit(self):
        """Simple rate limiting."""
        if self.config.requests_per_second > 0:
            min_interval = 1.0 / self.config.requests_per_second
            elapsed = time.time() - self._last_request_time
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
        self._last_request_time = time.time()
    
    def _cache_key(self, *args) -> str:
        """Generate cache key from arguments."""
        key_str = "|".join(str(a) for a in args)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_cached(self, key: str) -> Optional[Any]:
        """Get value from cache if valid."""
        if not self.config.cache_enabled:
            return None
        if key in self._cache:
            timestamp, value = self._cache[key]
            if time.time() - timestamp < self.config.cache_ttl_seconds:
                return value
            del self._cache[key]
        return None
    
    def _set_cached(self, key: str, value: Any):
        """Set value in cache."""
        if self.config.cache_enabled:
            self._cache[key] = (time.time(), value)
    
    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make an API request with rate limiting and error handling."""
        self._rate_limit()
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        kwargs.setdefault("headers", self._get_headers())
        kwargs.setdefault("timeout", self.config.timeout)
        kwargs.setdefault("verify", self.config.verify_ssl)
        
        response = requests.request(method, url, **kwargs)
        
        # Handle rate limiting
        if response.status_code == 403:
            remaining = response.headers.get("X-RateLimit-Remaining", "?")
            reset_time = response.headers.get("X-RateLimit-Reset", "?")
            raise RuntimeError(
                f"GitHub rate limit exceeded. Remaining: {remaining}, "
                f"Reset: {reset_time}"
            )
        
        return response
    
    def test_connection(self) -> Tuple[bool, str]:
        """Test GitHub connection and authentication."""
        try:
            response = self._request("GET", "/user")
            if response.status_code == 200:
                user = response.json()
                return True, f"Connected as {user.get('login', 'unknown')}"
            elif response.status_code == 401:
                return False, "Authentication failed - check your token"
            else:
                return False, f"Unexpected status: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {str(e)}"
    
    def fetch_file(
        self,
        repo: str,
        path: str,
        ref: str = "main"
    ) -> Optional[FetchedFile]:
        """
        Fetch a single file from a repository.
        
        Args:
            repo: Repository in "owner/repo" format
            path: Path to file within repository
            ref: Branch, tag, or commit SHA
            
        Returns:
            FetchedFile or None if not found
        """
        cache_key = self._cache_key("file", repo, path, ref)
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        try:
            # URL encode the path
            encoded_path = quote(path, safe="")
            endpoint = f"/repos/{repo}/contents/{encoded_path}"
            
            response = self._request("GET", endpoint, params={"ref": ref})
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            data = response.json()
            
            # Handle file content
            if data.get("type") != "file":
                return None
            
            # Decode base64 content
            content = ""
            if data.get("encoding") == "base64" and data.get("content"):
                content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            
            result = FetchedFile(
                path=path,
                content=content,
                repo=repo,
                ref=ref,
                sha=data.get("sha", ""),
                size=data.get("size", 0),
                url=data.get("html_url", ""),
            )
            
            self._set_cached(cache_key, result)
            return result
            
        except Exception as e:
            # Log but don't fail - file might not exist
            return None
    
    def fetch_directory(
        self,
        repo: str,
        path: str,
        ref: str = "main",
        recursive: bool = True
    ) -> List[FetchedFile]:
        """
        Fetch all files in a directory.
        
        Args:
            repo: Repository in "owner/repo" format
            path: Directory path within repository
            ref: Branch, tag, or commit SHA
            recursive: Whether to fetch subdirectories
            
        Returns:
            List of FetchedFile objects
        """
        cache_key = self._cache_key("dir", repo, path, ref, recursive)
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        files = []
        
        try:
            encoded_path = quote(path.rstrip("/"), safe="")
            endpoint = f"/repos/{repo}/contents/{encoded_path}"
            
            response = self._request("GET", endpoint, params={"ref": ref})
            
            if response.status_code == 404:
                return []
            
            response.raise_for_status()
            items = response.json()
            
            if not isinstance(items, list):
                return []
            
            for item in items:
                if item.get("type") == "file":
                    # Fetch file content
                    file = self.fetch_file(repo, item["path"], ref)
                    if file:
                        files.append(file)
                elif item.get("type") == "dir" and recursive:
                    # Recurse into directory
                    subfiles = self.fetch_directory(repo, item["path"], ref, recursive)
                    files.extend(subfiles)
            
            self._set_cached(cache_key, files)
            return files
            
        except Exception as e:
            return []
    
    def fetch_jenkinsfile(
        self,
        repo: str,
        ref: str = "main",
        paths: Optional[List[str]] = None
    ) -> Optional[FetchedFile]:
        """
        Fetch Jenkinsfile from a repository.
        
        Tries multiple common locations:
        - Jenkinsfile
        - jenkins/Jenkinsfile
        - .jenkins/Jenkinsfile
        - ci/Jenkinsfile
        
        Args:
            repo: Repository in "owner/repo" format
            ref: Branch, tag, or commit SHA
            paths: Custom paths to try
            
        Returns:
            FetchedFile or None if not found
        """
        default_paths = [
            "Jenkinsfile",
            "jenkins/Jenkinsfile",
            ".jenkins/Jenkinsfile",
            "ci/Jenkinsfile",
            ".ci/Jenkinsfile",
        ]
        
        search_paths = paths or default_paths
        
        for path in search_paths:
            file = self.fetch_file(repo, path, ref)
            if file:
                return file
        
        return None
    
    def fetch_library(
        self,
        repo: str,
        ref: str = "main",
        name: Optional[str] = None
    ) -> FetchedLibrary:
        """
        Fetch a Jenkins shared library's source code.
        
        Fetches:
        - vars/*.groovy (global variables)
        - src/**/*.groovy (classes)
        - resources/** (optional resources)
        
        Args:
            repo: Repository in "owner/repo" format
            ref: Branch, tag, or commit SHA
            name: Library name (for identification)
            
        Returns:
            FetchedLibrary with all files
        """
        library = FetchedLibrary(
            name=name or repo.split("/")[-1],
            version=ref,
            repo=repo,
        )
        
        # Fetch vars/ directory
        vars_files = self.fetch_directory(repo, "vars", ref, recursive=False)
        for f in vars_files:
            if f.path.endswith(".groovy"):
                library.files[f.path] = f.content
                # Extract function name from filename
                func_name = Path(f.path).stem
                library.vars_functions.append(func_name)
        
        # Fetch src/ directory (recursive)
        src_files = self.fetch_directory(repo, "src", ref, recursive=True)
        for f in src_files:
            if f.path.endswith(".groovy"):
                library.files[f.path] = f.content
                # Extract class name from path (e.g., src/com/example/MyClass.groovy)
                class_path = f.path.replace("src/", "").replace("/", ".").replace(".groovy", "")
                library.src_classes.append(class_path)
        
        # Fetch resources/ directory (optional, might contain config files)
        resources_files = self.fetch_directory(repo, "resources", ref, recursive=True)
        for f in resources_files:
            library.files[f.path] = f.content
        
        if not library.files:
            library.fetch_errors.append(f"No Groovy files found in {repo}@{ref}")
        
        return library
    
    def resolve_library_repo(self, library_name: str) -> Optional[str]:
        """
        Resolve a library name to its repository.
        
        Uses configured library mappings, or returns None if not found.
        """
        if library_name in self.library_configs:
            return self.library_configs[library_name].repo
        return None
    
    def parse_library_declarations(self, jenkinsfile_content: str) -> List[Tuple[str, str]]:
        """
        Parse @Library declarations from Jenkinsfile content.
        
        Returns list of (library_name, version) tuples.
        """
        libraries = []
        
        patterns = [
            # @Library('my-lib@version') _
            r"@Library\s*\(\s*['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]\s*\)",
            # @Library(['lib1@v1', 'lib2@v2'])
            r"@Library\s*\(\s*\[([^\]]+)\]\s*\)",
            # library 'my-lib@version'
            r"library\s+['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]",
            # library identifier: 'my-lib@version'
            r"library\s+identifier:\s*['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]",
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, jenkinsfile_content):
                groups = match.groups()
                
                # Handle array syntax
                if "[" in pattern:
                    lib_array = groups[0]
                    for lib_match in re.finditer(r"['\"]([^'\"@]+)(?:@([^'\"]+))?['\"]", lib_array):
                        name = lib_match.group(1)
                        version = lib_match.group(2) or "main"
                        libraries.append((name, version))
                else:
                    name = groups[0]
                    version = groups[1] if len(groups) > 1 and groups[1] else "main"
                    libraries.append((name, version))
        
        return libraries
    
    def fetch_for_analysis(
        self,
        project_repo: Optional[str] = None,
        project_ref: str = "main",
        jenkinsfile_content: Optional[str] = None,
        library_refs: Optional[List[Tuple[str, str, str]]] = None,
        auto_detect_libraries: bool = True
    ) -> FetchResult:
        """
        Fetch all source code needed for failure analysis.
        
        This is the main entry point for fetching code before analysis.
        
        Args:
            project_repo: Project repository ("owner/repo") to fetch Jenkinsfile from
            project_ref: Branch/tag/commit for the project
            jenkinsfile_content: Optional pre-fetched Jenkinsfile content
            library_refs: List of (name, repo, ref) for libraries to fetch
            auto_detect_libraries: If True, parse Jenkinsfile for @Library declarations
            
        Returns:
            FetchResult with Jenkinsfile and library code
        """
        result = FetchResult()
        
        # Fetch Jenkinsfile if not provided
        if jenkinsfile_content:
            result.jenkinsfile = jenkinsfile_content
        elif project_repo:
            jenkinsfile = self.fetch_jenkinsfile(project_repo, project_ref)
            if jenkinsfile:
                result.jenkinsfile = jenkinsfile.content
                result.jenkinsfile_repo = project_repo
                result.jenkinsfile_ref = project_ref
            else:
                result.errors.append(f"Jenkinsfile not found in {project_repo}@{project_ref}")
        
        # Auto-detect libraries from Jenkinsfile
        libraries_to_fetch: List[Tuple[str, str, str]] = list(library_refs or [])
        
        if auto_detect_libraries and result.jenkinsfile:
            declared_libs = self.parse_library_declarations(result.jenkinsfile)
            for lib_name, lib_version in declared_libs:
                # Check if already in list
                if any(l[0] == lib_name for l in libraries_to_fetch):
                    continue
                
                # Try to resolve repo from config
                lib_repo = self.resolve_library_repo(lib_name)
                if lib_repo:
                    libraries_to_fetch.append((lib_name, lib_repo, lib_version))
                else:
                    result.errors.append(
                        f"Library '{lib_name}' declared but no repository mapping found. "
                        f"Configure it in github.library_mappings"
                    )
        
        # Fetch libraries
        for lib_name, lib_repo, lib_ref in libraries_to_fetch:
            try:
                library = self.fetch_library(lib_repo, lib_ref, lib_name)
                result.libraries[lib_name] = library
                
                if library.fetch_errors:
                    result.errors.extend(library.fetch_errors)
                    
            except Exception as e:
                result.errors.append(f"Failed to fetch library {lib_name}: {str(e)}")
        
        return result
    
    def get_library_sources_dict(self, result: FetchResult) -> Dict[str, str]:
        """
        Convert FetchResult libraries to the format expected by analyzers.
        
        Returns dict of {file_path: content} for all library files.
        """
        sources = {}
        
        for lib_name, library in result.libraries.items():
            for file_path, content in library.files.items():
                # Prefix with library name for uniqueness
                key = f"{lib_name}/{file_path}"
                sources[key] = content
        
        return sources
    
    def format_for_ai_prompt(self, result: FetchResult) -> str:
        """
        Format fetched code for inclusion in AI prompt.
        
        Creates a structured representation of the source code
        that the AI can use for analysis.
        """
        parts = []
        
        # Jenkinsfile
        if result.jenkinsfile:
            parts.append("## Jenkinsfile")
            if result.jenkinsfile_repo:
                parts.append(f"Source: {result.jenkinsfile_repo}@{result.jenkinsfile_ref}")
            parts.append("```groovy")
            # Truncate if too long
            content = result.jenkinsfile
            if len(content) > 5000:
                content = content[:5000] + "\n... (truncated)"
            parts.append(content)
            parts.append("```")
            parts.append("")
        
        # Libraries
        for lib_name, library in result.libraries.items():
            parts.append(f"## Shared Library: {lib_name}")
            parts.append(f"Repository: {library.repo}@{library.version}")
            
            if library.vars_functions:
                parts.append(f"Global Variables: {', '.join(library.vars_functions)}")
            
            if library.src_classes:
                parts.append(f"Classes: {', '.join(library.src_classes[:10])}")
                if len(library.src_classes) > 10:
                    parts.append(f"  ... and {len(library.src_classes) - 10} more")
            
            # Include vars/ files (most important for debugging)
            parts.append("")
            parts.append("### Global Variable Definitions (vars/)")
            for file_path, content in library.files.items():
                if file_path.startswith("vars/") and file_path.endswith(".groovy"):
                    func_name = Path(file_path).stem
                    parts.append(f"\n#### {func_name}")
                    parts.append("```groovy")
                    # Truncate individual files
                    if len(content) > 2000:
                        content = content[:2000] + "\n... (truncated)"
                    parts.append(content)
                    parts.append("```")
            
            # Include key src/ files (summarized)
            src_files = [(p, c) for p, c in library.files.items() 
                         if p.startswith("src/") and p.endswith(".groovy")]
            if src_files:
                parts.append("")
                parts.append("### Source Classes (src/)")
                for file_path, content in src_files[:5]:  # Limit to 5 files
                    class_name = Path(file_path).stem
                    parts.append(f"\n#### {class_name}")
                    parts.append("```groovy")
                    if len(content) > 1500:
                        content = content[:1500] + "\n... (truncated)"
                    parts.append(content)
                    parts.append("```")
                
                if len(src_files) > 5:
                    parts.append(f"\n... and {len(src_files) - 5} more source files")
            
            parts.append("")
        
        # Errors
        if result.errors:
            parts.append("## Fetch Warnings")
            for error in result.errors:
                parts.append(f"- {error}")
        
        return "\n".join(parts)


def create_github_client(config: Dict[str, Any]) -> GitHubClient:
    """
    Factory function to create GitHubClient from config dict.
    
    Expected config format:
    {
        "github": {
            "base_url": "https://github.mycompany.com/api/v3",
            "token": "ghp_xxxx",
            "library_mappings": {
                "my-lib": "org/jenkins-shared-library",
                "common-lib": "org/common-pipeline-lib"
            }
        }
    }
    """
    github_config = config.get("github", {})
    
    client_config = GitHubConfig(
        base_url=github_config.get("base_url", "https://api.github.com"),
        token=github_config.get("token", ""),
        timeout=github_config.get("timeout", 30),
        cache_enabled=github_config.get("cache_enabled", True),
        cache_ttl_seconds=github_config.get("cache_ttl_seconds", 300),
    )
    
    # Parse library mappings
    library_configs = []
    for lib_name, lib_repo in github_config.get("library_mappings", {}).items():
        if isinstance(lib_repo, str):
            library_configs.append(LibraryConfig(name=lib_name, repo=lib_repo))
        elif isinstance(lib_repo, dict):
            library_configs.append(LibraryConfig(
                name=lib_name,
                repo=lib_repo.get("repo", ""),
                default_branch=lib_repo.get("default_branch", "main"),
            ))
    
    return GitHubClient(client_config, library_configs)
