"""
GitHub and GitLab client for posting PR/MR comments with failure analysis.
"""

import re
import requests
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum


class SCMProvider(str, Enum):
    """Supported SCM providers."""
    GITHUB = "github"
    GITLAB = "gitlab"


@dataclass
class SCMConfig:
    """Configuration for SCM integration."""
    provider: SCMProvider
    api_url: str  # https://api.github.com or https://gitlab.com/api/v4
    token: str
    # Optional: for GitHub Enterprise or self-hosted GitLab
    verify_ssl: bool = True


@dataclass
class PRInfo:
    """Pull/Merge Request information."""
    owner: str  # GitHub org/user or GitLab namespace
    repo: str
    pr_number: int
    sha: Optional[str] = None  # Commit SHA for status updates


class SCMClient:
    """Client for GitHub and GitLab API operations."""
    
    def __init__(self, config: SCMConfig):
        self.config = config
        self.session = requests.Session()
        self.session.verify = config.verify_ssl
        
        # Set auth headers based on provider
        if config.provider == SCMProvider.GITHUB:
            self.session.headers["Authorization"] = f"Bearer {config.token}"
            self.session.headers["Accept"] = "application/vnd.github+json"
            self.session.headers["X-GitHub-Api-Version"] = "2022-11-28"
        else:  # GitLab
            self.session.headers["PRIVATE-TOKEN"] = config.token
    
    def _get(self, path: str) -> Dict[str, Any]:
        """Make a GET request."""
        url = f"{self.config.api_url}{path}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def _post(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a POST request."""
        url = f"{self.config.api_url}{path}"
        response = self.session.post(url, json=data)
        response.raise_for_status()
        return response.json()
    
    def _put(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a PUT request."""
        url = f"{self.config.api_url}{path}"
        response = self.session.put(url, json=data)
        response.raise_for_status()
        return response.json()
    
    def _patch(self, path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Make a PATCH request."""
        url = f"{self.config.api_url}{path}"
        response = self.session.patch(url, json=data)
        response.raise_for_status()
        return response.json()
    
    # =========================================================================
    # PR/MR Comments
    # =========================================================================
    
    def post_pr_comment(self, pr_info: PRInfo, comment: str) -> bool:
        """
        Post a comment on a PR/MR.
        
        Args:
            pr_info: PR/MR information
            comment: Markdown comment body
            
        Returns:
            True if successful
        """
        try:
            if self.config.provider == SCMProvider.GITHUB:
                self._post(
                    f"/repos/{pr_info.owner}/{pr_info.repo}/issues/{pr_info.pr_number}/comments",
                    {"body": comment}
                )
            else:  # GitLab
                # GitLab uses project ID or path
                project_path = f"{pr_info.owner}/{pr_info.repo}".replace("/", "%2F")
                self._post(
                    f"/projects/{project_path}/merge_requests/{pr_info.pr_number}/notes",
                    {"body": comment}
                )
            return True
        except Exception as e:
            print(f"Failed to post PR comment: {e}")
            return False
    
    def update_or_create_comment(
        self, 
        pr_info: PRInfo, 
        comment: str,
        marker: str = "<!-- jenkins-failure-analysis -->"
    ) -> bool:
        """
        Update existing comment or create new one.
        
        Uses a marker to identify comments from this tool.
        """
        try:
            # Find existing comment
            existing_comment_id = self._find_comment_by_marker(pr_info, marker)
            
            # Add marker to comment
            full_comment = f"{marker}\n{comment}"
            
            if existing_comment_id:
                # Update existing
                return self._update_comment(pr_info, existing_comment_id, full_comment)
            else:
                # Create new
                return self.post_pr_comment(pr_info, full_comment)
        except Exception as e:
            print(f"Failed to update/create comment: {e}")
            return False
    
    def _find_comment_by_marker(self, pr_info: PRInfo, marker: str) -> Optional[int]:
        """Find a comment containing the marker."""
        try:
            if self.config.provider == SCMProvider.GITHUB:
                comments = self._get(
                    f"/repos/{pr_info.owner}/{pr_info.repo}/issues/{pr_info.pr_number}/comments"
                )
                for comment in comments:
                    if marker in comment.get("body", ""):
                        return comment["id"]
            else:  # GitLab
                project_path = f"{pr_info.owner}/{pr_info.repo}".replace("/", "%2F")
                notes = self._get(
                    f"/projects/{project_path}/merge_requests/{pr_info.pr_number}/notes"
                )
                for note in notes:
                    if marker in note.get("body", ""):
                        return note["id"]
            return None
        except Exception:
            return None
    
    def _update_comment(self, pr_info: PRInfo, comment_id: int, body: str) -> bool:
        """Update an existing comment."""
        try:
            if self.config.provider == SCMProvider.GITHUB:
                self._patch(
                    f"/repos/{pr_info.owner}/{pr_info.repo}/issues/comments/{comment_id}",
                    {"body": body}
                )
            else:  # GitLab
                project_path = f"{pr_info.owner}/{pr_info.repo}".replace("/", "%2F")
                self._put(
                    f"/projects/{project_path}/merge_requests/{pr_info.pr_number}/notes/{comment_id}",
                    {"body": body}
                )
            return True
        except Exception as e:
            print(f"Failed to update comment: {e}")
            return False
    
    # =========================================================================
    # Commit Status
    # =========================================================================
    
    def set_commit_status(
        self,
        pr_info: PRInfo,
        state: str,  # pending, success, failure, error (GitHub) / pending, running, success, failed, canceled (GitLab)
        description: str,
        context: str = "jenkins-failure-analysis",
        target_url: Optional[str] = None
    ) -> bool:
        """
        Set commit status for the PR head commit.
        
        Args:
            pr_info: PR info with sha field set
            state: Status state
            description: Short description (max 140 chars for GitHub)
            context: Status context/name
            target_url: Optional URL to link to
        """
        if not pr_info.sha:
            print("Cannot set commit status: no SHA provided")
            return False
        
        try:
            if self.config.provider == SCMProvider.GITHUB:
                data = {
                    "state": state,
                    "description": description[:140],
                    "context": context,
                }
                if target_url:
                    data["target_url"] = target_url
                
                self._post(
                    f"/repos/{pr_info.owner}/{pr_info.repo}/statuses/{pr_info.sha}",
                    data
                )
            else:  # GitLab
                # Map GitHub states to GitLab
                state_map = {
                    "pending": "pending",
                    "success": "success",
                    "failure": "failed",
                    "error": "failed",
                }
                gitlab_state = state_map.get(state, "failed")
                
                project_path = f"{pr_info.owner}/{pr_info.repo}".replace("/", "%2F")
                data = {
                    "state": gitlab_state,
                    "description": description[:255],
                    "name": context,
                }
                if target_url:
                    data["target_url"] = target_url
                
                self._post(
                    f"/projects/{project_path}/statuses/{pr_info.sha}",
                    data
                )
            return True
        except Exception as e:
            print(f"Failed to set commit status: {e}")
            return False
    
    # =========================================================================
    # Helper Methods
    # =========================================================================
    
    def extract_pr_info_from_url(self, url: str) -> Optional[PRInfo]:
        """
        Extract PR info from a GitHub/GitLab URL.
        
        Supports:
            - https://github.com/owner/repo/pull/123
            - https://gitlab.com/owner/repo/-/merge_requests/123
        """
        # GitHub pattern
        github_match = re.match(
            r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/pull/(\d+)",
            url
        )
        if github_match:
            return PRInfo(
                owner=github_match.group(1),
                repo=github_match.group(2),
                pr_number=int(github_match.group(3))
            )
        
        # GitLab pattern
        gitlab_match = re.match(
            r"https?://(?:www\.)?gitlab\.com/([^/]+(?:/[^/]+)*)/([^/]+)/-/merge_requests/(\d+)",
            url
        )
        if gitlab_match:
            return PRInfo(
                owner=gitlab_match.group(1),
                repo=gitlab_match.group(2),
                pr_number=int(gitlab_match.group(3))
            )
        
        return None
    
    def test_connection(self) -> bool:
        """Test connection to the SCM API."""
        try:
            if self.config.provider == SCMProvider.GITHUB:
                self._get("/user")
            else:
                self._get("/user")
            return True
        except Exception:
            return False


def format_pr_comment(
    job_name: str,
    build_number: int,
    build_url: str,
    root_cause: str,
    category: str,
    tier: str,
    confidence: float,
    is_retriable: bool,
    recommendations: List[Dict[str, str]] = None,
    affected_files: List[str] = None
) -> str:
    """
    Format analysis result as a Markdown PR comment.
    
    Returns Markdown string suitable for GitHub/GitLab comments.
    """
    # Tier emoji
    tier_emoji = {
        "configuration": "⚙️",
        "pipeline_misuse": "🔧",
        "external_system": "🌐",
        "unknown": "❓",
    }
    emoji = tier_emoji.get(tier, "❓")
    
    # Retry badge
    if is_retriable:
        retry_badge = "🔄 **Retriable** - This failure may be transient"
    else:
        retry_badge = "⛔ **Not Retriable** - Requires code or config changes"
    
    # Build the comment
    lines = [
        f"## {emoji} Jenkins Build Failure Analysis",
        "",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| **Job** | [{job_name}]({build_url}) |",
        f"| **Build** | #{build_number} |",
        f"| **Category** | `{category}` |",
        f"| **Tier** | {tier.replace('_', ' ').title()} |",
        f"| **Confidence** | {confidence:.0%} |",
        "",
        f"> {retry_badge}",
        "",
        "### 🎯 Root Cause",
        "",
        f"> {root_cause}",
        "",
    ]
    
    # Affected files
    if affected_files:
        lines.extend([
            "### 📁 Affected Files",
            "",
        ])
        for f in affected_files[:5]:
            lines.append(f"- `{f}`")
        if len(affected_files) > 5:
            lines.append(f"- ... and {len(affected_files) - 5} more")
        lines.append("")
    
    # Recommendations
    if recommendations:
        lines.extend([
            "### 💡 Recommendations",
            "",
        ])
        for i, rec in enumerate(recommendations[:3], 1):
            priority = rec.get("priority", "MEDIUM")
            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(priority, "⚪")
            lines.append(f"{i}. {priority_icon} **{rec.get('action', 'N/A')}**")
            if rec.get("rationale"):
                lines.append(f"   - {rec['rationale']}")
            if rec.get("code_suggestion"):
                lines.append(f"   ```")
                lines.append(f"   {rec['code_suggestion']}")
                lines.append(f"   ```")
        lines.append("")
    
    # Footer
    lines.extend([
        "---",
        f"*🤖 Generated by Jenkins Failure Analysis Agent*",
    ])
    
    return "\n".join(lines)
