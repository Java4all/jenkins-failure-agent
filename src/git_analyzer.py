"""
Git analyzer for correlating build failures with recent code changes.
"""

import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from datetime import datetime


@dataclass
class CommitInfo:
    """Represents a Git commit."""
    sha: str
    short_sha: str
    author: str
    author_email: str
    timestamp: datetime
    message: str
    files_changed: List[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0


@dataclass
class FileChange:
    """Represents a file change in a commit."""
    path: str
    status: str  # A (added), M (modified), D (deleted), R (renamed)
    insertions: int = 0
    deletions: int = 0
    diff_snippet: str = ""


@dataclass
class BlameInfo:
    """Blame information for a specific line."""
    sha: str
    author: str
    timestamp: datetime
    line_number: int
    content: str


@dataclass
class GitAnalysis:
    """Complete Git analysis for a build failure."""
    recent_commits: List[CommitInfo] = field(default_factory=list)
    suspicious_commits: List[CommitInfo] = field(default_factory=list)
    affected_files: Dict[str, List[FileChange]] = field(default_factory=dict)
    risk_score: float = 0.0
    risk_factors: List[str] = field(default_factory=list)
    correlation_summary: str = ""


class GitAnalyzer:
    """Analyzer for correlating failures with Git changes."""
    
    # File patterns that are high-risk for causing failures
    HIGH_RISK_PATTERNS = [
        r".*\.py$",
        r".*\.java$",
        r".*\.js$",
        r".*\.ts$",
        r".*\.go$",
        r".*\.rs$",
        r"requirements.*\.txt$",
        r"package.*\.json$",
        r"pom\.xml$",
        r"build\.gradle$",
        r"Dockerfile$",
        r".*\.yml$",
        r".*\.yaml$",
        r"Jenkinsfile$",
        r"Makefile$",
    ]
    
    # Keywords in commit messages that might indicate risky changes
    RISKY_KEYWORDS = [
        "refactor", "rewrite", "breaking", "major", "migration",
        "upgrade", "update dependencies", "security", "auth",
        "database", "schema", "config", "deploy", "ci", "build"
    ]
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.lookback_commits = self.config.get("lookback_commits", 10)
    
    def analyze(
        self,
        repo_path: str,
        error_files: Optional[List[str]] = None,
        error_patterns: Optional[List[str]] = None,
        since_commit: Optional[str] = None,
    ) -> GitAnalysis:
        """
        Analyze Git history to find potential causes of build failure.
        
        Args:
            repo_path: Path to the Git repository
            error_files: Files mentioned in error messages
            error_patterns: Error patterns to correlate with changes
            since_commit: Only look at commits after this SHA
        """
        repo_path = Path(repo_path)
        if not (repo_path / ".git").exists():
            raise ValueError(f"Not a Git repository: {repo_path}")
        
        analysis = GitAnalysis()
        
        # Get recent commits
        analysis.recent_commits = self._get_recent_commits(
            repo_path, 
            self.lookback_commits,
            since_commit
        )
        
        # Analyze file changes
        for commit in analysis.recent_commits:
            changes = self._get_file_changes(repo_path, commit.sha)
            for change in changes:
                commit.files_changed.append(change.path)
                if change.path not in analysis.affected_files:
                    analysis.affected_files[change.path] = []
                analysis.affected_files[change.path].append(change)
        
        # Find suspicious commits
        analysis.suspicious_commits = self._find_suspicious_commits(
            analysis.recent_commits,
            error_files or [],
            error_patterns or []
        )
        
        # Calculate risk score
        analysis.risk_score, analysis.risk_factors = self._calculate_risk(
            analysis.recent_commits,
            analysis.suspicious_commits,
            analysis.affected_files
        )
        
        # Generate correlation summary
        analysis.correlation_summary = self._generate_summary(analysis, error_files)
        
        return analysis
    
    def _get_recent_commits(
        self,
        repo_path: Path,
        limit: int,
        since_commit: Optional[str] = None
    ) -> List[CommitInfo]:
        """Get recent commits from the repository."""
        commits = []
        
        # Build git log command
        cmd = [
            "git", "-C", str(repo_path), "log",
            f"-{limit}",
            "--format=%H|%h|%an|%ae|%at|%s",
            "--no-merges"
        ]
        
        if since_commit:
            cmd.append(f"{since_commit}..HEAD")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                    
                parts = line.split("|", 5)
                if len(parts) >= 6:
                    commit = CommitInfo(
                        sha=parts[0],
                        short_sha=parts[1],
                        author=parts[2],
                        author_email=parts[3],
                        timestamp=datetime.fromtimestamp(int(parts[4])),
                        message=parts[5]
                    )
                    
                    # Get stats
                    stats = self._get_commit_stats(repo_path, commit.sha)
                    commit.insertions = stats.get("insertions", 0)
                    commit.deletions = stats.get("deletions", 0)
                    
                    commits.append(commit)
        except subprocess.CalledProcessError:
            pass
        
        return commits
    
    def _get_commit_stats(self, repo_path: Path, sha: str) -> Dict[str, int]:
        """Get insertion/deletion stats for a commit."""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "show", sha, "--stat", "--format="],
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse the last line for stats
            lines = result.stdout.strip().split("\n")
            if lines:
                last_line = lines[-1]
                insertions = 0
                deletions = 0
                
                ins_match = re.search(r"(\d+) insertion", last_line)
                if ins_match:
                    insertions = int(ins_match.group(1))
                
                del_match = re.search(r"(\d+) deletion", last_line)
                if del_match:
                    deletions = int(del_match.group(1))
                
                return {"insertions": insertions, "deletions": deletions}
        except subprocess.CalledProcessError:
            pass
        
        return {}
    
    def _get_file_changes(self, repo_path: Path, sha: str) -> List[FileChange]:
        """Get file changes for a specific commit."""
        changes = []
        
        try:
            # Get list of changed files with status
            result = subprocess.run(
                ["git", "-C", str(repo_path), "show", sha, "--name-status", "--format="],
                capture_output=True,
                text=True,
                check=True
            )
            
            for line in result.stdout.strip().split("\n"):
                if not line or not line.strip():
                    continue
                
                parts = line.split("\t")
                if len(parts) >= 2:
                    status = parts[0][0]  # First character of status
                    file_path = parts[-1]  # Last part is the file path
                    
                    change = FileChange(
                        path=file_path,
                        status=status
                    )
                    
                    # Get diff snippet for the file
                    change.diff_snippet = self._get_diff_snippet(repo_path, sha, file_path)
                    
                    changes.append(change)
        except subprocess.CalledProcessError:
            pass
        
        return changes
    
    def _get_diff_snippet(
        self, 
        repo_path: Path, 
        sha: str, 
        file_path: str,
        max_lines: int = 20
    ) -> str:
        """Get a snippet of the diff for a specific file."""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_path), "show", sha, "--", file_path],
                capture_output=True,
                text=True,
                check=True
            )
            
            diff_lines = result.stdout.split("\n")
            
            # Extract only the actual diff lines (starting with + or -)
            relevant_lines = []
            for line in diff_lines:
                if line.startswith("+") or line.startswith("-"):
                    if not line.startswith("+++") and not line.startswith("---"):
                        relevant_lines.append(line)
            
            return "\n".join(relevant_lines[:max_lines])
        except subprocess.CalledProcessError:
            return ""
    
    def _find_suspicious_commits(
        self,
        commits: List[CommitInfo],
        error_files: List[str],
        error_patterns: List[str]
    ) -> List[CommitInfo]:
        """Find commits that might have caused the failure."""
        suspicious = []
        
        for commit in commits:
            score = 0
            
            # Check if commit modified files mentioned in errors
            for error_file in error_files:
                for changed_file in commit.files_changed:
                    if self._files_match(changed_file, error_file):
                        score += 10
            
            # Check for risky keywords in commit message
            message_lower = commit.message.lower()
            for keyword in self.RISKY_KEYWORDS:
                if keyword in message_lower:
                    score += 3
            
            # Check for high-risk file patterns
            for changed_file in commit.files_changed:
                for pattern in self.HIGH_RISK_PATTERNS:
                    if re.match(pattern, changed_file):
                        score += 2
                        break
            
            # Large changes are riskier
            total_changes = commit.insertions + commit.deletions
            if total_changes > 500:
                score += 5
            elif total_changes > 100:
                score += 2
            
            # Check if error patterns appear in diff
            for error_pattern in error_patterns:
                for changed_file in commit.files_changed:
                    # This would need the diff content to be stored
                    pass
            
            if score >= 5:
                suspicious.append(commit)
        
        # Sort by suspicion score (we'd need to track scores for proper sorting)
        return suspicious[:5]  # Return top 5 most suspicious
    
    def _files_match(self, changed_file: str, error_file: str) -> bool:
        """Check if a changed file matches a file mentioned in an error."""
        # Normalize paths
        changed_file = changed_file.replace("\\", "/").lower()
        error_file = error_file.replace("\\", "/").lower()
        
        # Direct match
        if changed_file == error_file:
            return True
        
        # Check if error_file is a suffix of changed_file
        if changed_file.endswith(error_file):
            return True
        
        # Check if they share the same filename
        if Path(changed_file).name == Path(error_file).name:
            return True
        
        return False
    
    def _calculate_risk(
        self,
        recent_commits: List[CommitInfo],
        suspicious_commits: List[CommitInfo],
        affected_files: Dict[str, List[FileChange]]
    ) -> Tuple[float, List[str]]:
        """Calculate overall risk score and identify risk factors."""
        risk_factors = []
        score = 0.0
        
        # Factor 1: Number of suspicious commits
        if len(suspicious_commits) > 0:
            factor = min(len(suspicious_commits) * 0.15, 0.4)
            score += factor
            risk_factors.append(
                f"{len(suspicious_commits)} potentially risky commits identified"
            )
        
        # Factor 2: Total changes
        total_changes = sum(c.insertions + c.deletions for c in recent_commits)
        if total_changes > 1000:
            score += 0.2
            risk_factors.append(f"Large amount of code changes ({total_changes} lines)")
        elif total_changes > 500:
            score += 0.1
            risk_factors.append(f"Moderate code changes ({total_changes} lines)")
        
        # Factor 3: Critical files modified
        critical_patterns = [
            r"Jenkinsfile$", r"Dockerfile$", r".*\.yml$",
            r"requirements.*\.txt$", r"package.*\.json$",
            r"pom\.xml$", r"build\.gradle$"
        ]
        critical_files_modified = []
        for file_path in affected_files:
            for pattern in critical_patterns:
                if re.match(pattern, file_path):
                    critical_files_modified.append(file_path)
                    break
        
        if critical_files_modified:
            score += 0.15
            risk_factors.append(
                f"Critical configuration files modified: {', '.join(critical_files_modified[:3])}"
            )
        
        # Factor 4: Multiple authors
        authors = set(c.author for c in recent_commits)
        if len(authors) > 3:
            score += 0.1
            risk_factors.append(f"Changes from multiple authors ({len(authors)})")
        
        # Factor 5: Recent rapid commits
        if len(recent_commits) >= 5:
            first = recent_commits[0].timestamp
            last = recent_commits[-1].timestamp
            if (first - last).total_seconds() < 3600:  # Within an hour
                score += 0.15
                risk_factors.append("Rapid succession of commits")
        
        return min(score, 1.0), risk_factors
    
    def _generate_summary(
        self, 
        analysis: GitAnalysis,
        error_files: Optional[List[str]]
    ) -> str:
        """Generate a human-readable correlation summary."""
        parts = []
        
        parts.append(f"Analyzed {len(analysis.recent_commits)} recent commits")
        
        if analysis.suspicious_commits:
            parts.append(
                f"Found {len(analysis.suspicious_commits)} potentially related commits"
            )
            
            # Mention the most suspicious commit
            most_suspicious = analysis.suspicious_commits[0]
            parts.append(
                f"Most likely cause: {most_suspicious.short_sha} by {most_suspicious.author} "
                f"- '{most_suspicious.message[:50]}...'"
            )
        
        if analysis.risk_factors:
            parts.append(f"Risk factors: {'; '.join(analysis.risk_factors[:3])}")
        
        if error_files:
            # Check if any error files were modified
            modified_error_files = []
            for error_file in error_files:
                for changed_file in analysis.affected_files:
                    if self._files_match(changed_file, error_file):
                        modified_error_files.append(changed_file)
            
            if modified_error_files:
                parts.append(
                    f"Error-related files recently modified: {', '.join(modified_error_files[:3])}"
                )
        
        return ". ".join(parts) + "."
    
    def get_blame_for_line(
        self,
        repo_path: str,
        file_path: str,
        line_number: int
    ) -> Optional[BlameInfo]:
        """Get blame information for a specific line."""
        try:
            result = subprocess.run(
                [
                    "git", "-C", repo_path, "blame",
                    "-L", f"{line_number},{line_number}",
                    "--line-porcelain", file_path
                ],
                capture_output=True,
                text=True,
                check=True
            )
            
            lines = result.stdout.split("\n")
            blame_data = {}
            content = ""
            
            for line in lines:
                if line.startswith("\t"):
                    content = line[1:]
                elif " " in line:
                    key, _, value = line.partition(" ")
                    blame_data[key] = value
            
            if blame_data:
                return BlameInfo(
                    sha=blame_data.get("sha", "")[:8],
                    author=blame_data.get("author", "Unknown"),
                    timestamp=datetime.fromtimestamp(
                        int(blame_data.get("author-time", 0))
                    ),
                    line_number=line_number,
                    content=content
                )
        except subprocess.CalledProcessError:
            pass
        
        return None
    
    def format_for_ai(self, analysis: GitAnalysis) -> str:
        """Format Git analysis for AI prompt."""
        parts = []
        
        parts.append("## Git Analysis")
        parts.append(f"Risk Score: {analysis.risk_score:.2f}/1.0")
        
        if analysis.risk_factors:
            parts.append("\n### Risk Factors:")
            for factor in analysis.risk_factors:
                parts.append(f"- {factor}")
        
        if analysis.suspicious_commits:
            parts.append("\n### Suspicious Commits:")
            for commit in analysis.suspicious_commits[:5]:
                parts.append(
                    f"- [{commit.short_sha}] {commit.author}: {commit.message[:60]}"
                )
                if commit.files_changed:
                    parts.append(f"  Modified: {', '.join(commit.files_changed[:5])}")
        
        parts.append(f"\n### Summary\n{analysis.correlation_summary}")
        
        return "\n".join(parts)
