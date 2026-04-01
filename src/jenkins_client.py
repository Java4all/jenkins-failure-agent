"""
Jenkins API client for fetching build information, logs, and artifacts.
"""

import re
import requests
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import xml.etree.ElementTree as ET

from .config import JenkinsConfig


@dataclass
class BuildInfo:
    """Represents a Jenkins build."""
    job_name: str
    build_number: int
    status: str  # SUCCESS, FAILURE, UNSTABLE, ABORTED
    url: str
    timestamp: datetime
    duration_ms: int
    building: bool = False
    causes: List[str] = field(default_factory=list)
    parameters: Dict[str, str] = field(default_factory=dict)
    artifacts: List[Dict[str, str]] = field(default_factory=list)
    changeset: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def duration_str(self) -> str:
        """Human-readable duration."""
        seconds = self.duration_ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}m {seconds}s"


@dataclass
class StageInfo:
    """Represents a pipeline stage."""
    name: str
    status: str
    duration_ms: int
    start_time: Optional[datetime] = None
    logs: str = ""


@dataclass
class TestResult:
    """Represents test results from a build."""
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)


class JenkinsClient:
    """Client for interacting with Jenkins API."""
    
    def __init__(self, config: JenkinsConfig):
        self.config = config
        self.base_url = config.url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (config.username, config.api_token)
        self.session.verify = config.verify_ssl
        self.session.timeout = config.timeout
    
    def _get(self, path: str, **kwargs) -> requests.Response:
        """Make a GET request to Jenkins API."""
        url = f"{self.base_url}{path}"
        response = self.session.get(url, **kwargs)
        response.raise_for_status()
        return response
    
    def _post(self, path: str, **kwargs) -> requests.Response:
        """Make a POST request to Jenkins API."""
        url = f"{self.base_url}{path}"
        
        # Jenkins requires crumb for CSRF protection
        crumb = self._get_crumb()
        if crumb:
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"][crumb["crumbRequestField"]] = crumb["crumb"]
        
        response = self.session.post(url, **kwargs)
        response.raise_for_status()
        return response
    
    def _get_crumb(self) -> Optional[Dict[str, str]]:
        """Get Jenkins crumb for CSRF protection."""
        try:
            response = self._get("/crumbIssuer/api/json")
            return response.json()
        except requests.exceptions.HTTPError:
            # Crumb issuer might be disabled
            return None
    
    def _get_json(self, path: str) -> Dict[str, Any]:
        """Get JSON response from Jenkins API."""
        if "?" in path:
            path = f"{path}&depth=2"
        else:
            path = f"{path}?depth=2"
        return self._get(path).json()
    
    def get_build_info(self, job_name: str, build_number: int) -> BuildInfo:
        """Fetch detailed information about a specific build."""
        
        # Handle folder paths
        job_path = self._job_path(job_name)
        data = self._get_json(f"/job/{job_path}/{build_number}/api/json")
        
        # Parse causes
        causes = []
        for action in data.get("actions", []):
            if "causes" in action:
                for cause in action["causes"]:
                    causes.append(cause.get("shortDescription", "Unknown cause"))
        
        # Parse parameters
        parameters = {}
        for action in data.get("actions", []):
            if "parameters" in action:
                for param in action["parameters"]:
                    parameters[param["name"]] = str(param.get("value", ""))
        
        # Parse changeset
        changeset = []
        changeset_data = data.get("changeSet", {})
        for item in changeset_data.get("items", []):
            changeset.append({
                "commit_id": item.get("commitId", "")[:8],
                "author": item.get("author", {}).get("fullName", "Unknown"),
                "message": item.get("msg", "").split("\n")[0],
                "timestamp": item.get("timestamp"),
                "affected_paths": item.get("affectedPaths", []),
            })
        
        return BuildInfo(
            job_name=job_name,
            build_number=build_number,
            status=data.get("result", "UNKNOWN"),
            url=data.get("url", ""),
            timestamp=datetime.fromtimestamp(data.get("timestamp", 0) / 1000),
            duration_ms=data.get("duration", 0),
            building=data.get("building", False),
            causes=causes,
            parameters=parameters,
            artifacts=[
                {"filename": a["fileName"], "path": a["relativePath"]}
                for a in data.get("artifacts", [])
            ],
            changeset=changeset,
        )
    
    def get_console_log(self, job_name: str, build_number: int) -> str:
        """Fetch console output for a build."""
        job_path = self._job_path(job_name)
        response = self._get(f"/job/{job_path}/{build_number}/consoleText")
        return response.text
    
    def get_pipeline_stages(self, job_name: str, build_number: int) -> List[StageInfo]:
        """Fetch pipeline stage information using Workflow API."""
        job_path = self._job_path(job_name)
        
        try:
            # Get workflow run
            data = self._get_json(f"/job/{job_path}/{build_number}/wfapi/describe")
            
            stages = []
            for stage in data.get("stages", []):
                stage_info = StageInfo(
                    name=stage.get("name", "Unknown"),
                    status=stage.get("status", "UNKNOWN"),
                    duration_ms=stage.get("durationMillis", 0),
                    start_time=datetime.fromtimestamp(
                        stage.get("startTimeMillis", 0) / 1000
                    ) if stage.get("startTimeMillis") else None,
                )
                
                # Try to get stage logs
                if "stageFlowNodes" in stage:
                    try:
                        stage_info.logs = self._get_stage_logs(
                            job_path, build_number, stage["id"]
                        )
                    except Exception:
                        pass
                
                stages.append(stage_info)
            
            return stages
        except requests.exceptions.HTTPError:
            # Not a pipeline job or no workflow API
            return []
    
    def _get_stage_logs(self, job_path: str, build_number: int, stage_id: str) -> str:
        """Fetch logs for a specific pipeline stage."""
        response = self._get(
            f"/job/{job_path}/{build_number}/execution/node/{stage_id}/wfapi/log"
        )
        return response.json().get("text", "")
    
    def get_test_results(self, job_name: str, build_number: int) -> Optional[TestResult]:
        """Fetch test results for a build."""
        job_path = self._job_path(job_name)
        
        try:
            data = self._get_json(f"/job/{job_path}/{build_number}/testReport/api/json")
            
            failures = []
            for suite in data.get("suites", []):
                for case in suite.get("cases", []):
                    if case.get("status") in ("FAILED", "REGRESSION"):
                        failures.append({
                            "class_name": case.get("className", ""),
                            "name": case.get("name", ""),
                            "status": case.get("status", ""),
                            "duration": case.get("duration", 0),
                            "error_details": case.get("errorDetails", ""),
                            "error_stack_trace": case.get("errorStackTrace", ""),
                            "stdout": case.get("stdout", ""),
                            "stderr": case.get("stderr", ""),
                        })
            
            return TestResult(
                total=data.get("totalCount", 0),
                passed=data.get("passCount", 0),
                failed=data.get("failCount", 0),
                skipped=data.get("skipCount", 0),
                failures=failures,
            )
        except requests.exceptions.HTTPError:
            return None
    
    def get_artifact_content(
        self, job_name: str, build_number: int, artifact_path: str
    ) -> bytes:
        """Download an artifact from a build."""
        job_path = self._job_path(job_name)
        response = self._get(
            f"/job/{job_path}/{build_number}/artifact/{artifact_path}"
        )
        return response.content
    
    def get_latest_build(self, job_name: str, status: Optional[str] = None) -> BuildInfo:
        """Get the latest build for a job, optionally filtered by status."""
        job_path = self._job_path(job_name)
        data = self._get_json(f"/job/{job_path}/api/json")
        
        if status == "FAILURE":
            build_num = data.get("lastFailedBuild", {}).get("number")
        elif status == "SUCCESS":
            build_num = data.get("lastSuccessfulBuild", {}).get("number")
        elif status == "UNSTABLE":
            build_num = data.get("lastUnstableBuild", {}).get("number")
        else:
            build_num = data.get("lastBuild", {}).get("number")
        
        if not build_num:
            raise ValueError(f"No {status or 'recent'} build found for job {job_name}")
        
        return self.get_build_info(job_name, build_num)
    
    def get_build_history(
        self, job_name: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent build history for a job."""
        job_path = self._job_path(job_name)
        data = self._get_json(f"/job/{job_path}/api/json")
        
        builds = []
        for build in data.get("builds", [])[:limit]:
            try:
                info = self.get_build_info(job_name, build["number"])
                builds.append({
                    "number": info.build_number,
                    "status": info.status,
                    "timestamp": info.timestamp.isoformat(),
                    "duration": info.duration_str,
                })
            except Exception:
                continue
        
        return builds
    
    def get_job_config(self, job_name: str) -> str:
        """Fetch job configuration XML."""
        job_path = self._job_path(job_name)
        response = self._get(f"/job/{job_path}/config.xml")
        return response.text
    
    def parse_jenkinsfile_stages(self, job_name: str) -> List[str]:
        """Extract stage names from job configuration."""
        try:
            config_xml = self.get_job_config(job_name)
            root = ET.fromstring(config_xml)
            
            # Try to find pipeline script
            script = root.find(".//script")
            if script is not None and script.text:
                # Extract stage names using regex
                stage_pattern = r"stage\s*\(\s*['\"]([^'\"]+)['\"]"
                return re.findall(stage_pattern, script.text)
        except Exception:
            pass
        
        return []
    
    def _job_path(self, job_name: str) -> str:
        """Convert job name to API path (handles folders).
        
        Accepts various input formats:
          - "jobname"                           -> "jobname"
          - "folder/jobname"                    -> "folder/job/jobname"
          - "folder1/folder2/jobname"           -> "folder1/job/folder2/job/jobname"
          - "job/folder/job/jobname"            -> "folder/job/jobname"
          - "/job/folder/job/jobname"           -> "folder/job/jobname"
          - Full URL                            -> extracts path
        
        Jenkins URL structure: /job/folder1/job/folder2/job/jobname/buildnum/
        """
        # Handle full URLs
        if job_name.startswith("http"):
            from urllib.parse import urlparse
            parsed = urlparse(job_name)
            job_name = parsed.path
        
        # Remove leading/trailing slashes
        job_name = job_name.strip("/")
        
        # Replace all /job/ with just / to normalize
        # Also handle job/ at the start
        normalized = job_name.replace("/job/", "/")
        if normalized.startswith("job/"):
            normalized = normalized[4:]  # Remove leading "job/"
        
        # Now split by / and rejoin with /job/
        parts = [p for p in normalized.split("/") if p]  # Filter empty parts
        return "/job/".join(parts)
    
    def test_connection(self) -> bool:
        """Test connection to Jenkins server."""
        try:
            self._get_json("/api/json")
            return True
        except Exception:
            return False
    
    def get_latest_failed_build(self, job_name: str) -> Optional[int]:
        """
        Find the most recent failed or unstable build for a job.
        
        Returns:
            Build number of the latest failed build, or None if no failures found.
        """
        job_path = self._job_path(job_name)
        
        try:
            # Get job info with build list
            data = self._get_json(f"/job/{job_path}/api/json")
            
            # Check lastFailedBuild first (most efficient)
            last_failed = data.get("lastFailedBuild")
            if last_failed and last_failed.get("number"):
                return last_failed["number"]
            
            # Check lastUnstableBuild
            last_unstable = data.get("lastUnstableBuild")
            if last_unstable and last_unstable.get("number"):
                return last_unstable["number"]
            
            # Fall back to scanning builds list
            builds = data.get("builds", [])
            for build in builds[:20]:  # Check last 20 builds
                build_num = build.get("number")
                if build_num:
                    try:
                        build_info = self.get_build_info(job_name, build_num)
                        if build_info.status in ("FAILURE", "UNSTABLE"):
                            return build_num
                    except Exception:
                        continue
            
            return None
            
        except Exception:
            return None
    
    def get_job_builds(self, job_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get list of recent builds for a job.
        
        Returns list of build summaries with number, status, timestamp.
        """
        job_path = self._job_path(job_name)
        
        try:
            data = self._get_json(f"/job/{job_path}/api/json")
            builds = data.get("builds", [])[:limit]
            
            result = []
            for build in builds:
                build_num = build.get("number")
                if build_num:
                    try:
                        info = self.get_build_info(job_name, build_num)
                        result.append({
                            "number": build_num,
                            "status": info.status,
                            "timestamp": info.timestamp.isoformat(),
                            "duration": info.duration_str,
                            "building": info.building,
                        })
                    except Exception:
                        result.append({
                            "number": build_num,
                            "status": "UNKNOWN",
                        })
            
            return result
            
        except Exception:
            return []
    
    def set_build_description(
        self, 
        job_name: str, 
        build_number: int, 
        description: str
    ) -> bool:
        """
        Set or update the build description in Jenkins.
        
        Args:
            job_name: Name of the job
            build_number: Build number to update
            description: HTML description to set
            
        Returns:
            True if successful, False otherwise
        """
        job_path = self._job_path(job_name)
        
        try:
            self._post(
                f"/job/{job_path}/{build_number}/submitDescription",
                data={"description": description}
            )
            return True
        except Exception as e:
            print(f"Failed to set build description: {e}")
            return False
    
    def format_analysis_description(
        self,
        root_cause: str,
        category: str,
        tier: str,
        confidence: float,
        is_retriable: bool,
        recommendations: List[str] = None
    ) -> str:
        """
        Format analysis result as HTML for Jenkins build description.
        
        Returns HTML string suitable for Jenkins build description.
        """
        # Tier emoji and color
        tier_info = {
            "configuration": ("⚙️", "#e65100", "Configuration Issue"),
            "pipeline_misuse": ("🔧", "#c62828", "Pipeline/Code Issue"),
            "external_system": ("🌐", "#1565c0", "External System Issue"),
            "unknown": ("❓", "#757575", "Unknown"),
        }
        emoji, color, tier_label = tier_info.get(tier, tier_info["unknown"])
        
        # Retry badge
        retry_badge = ""
        if is_retriable:
            retry_badge = '<span style="background:#4caf50;color:white;padding:2px 8px;border-radius:3px;font-size:11px;">🔄 RETRIABLE</span>'
        else:
            retry_badge = '<span style="background:#f44336;color:white;padding:2px 8px;border-radius:3px;font-size:11px;">⛔ NOT RETRIABLE</span>'
        
        html = f"""
<div style="font-family:sans-serif;padding:10px;background:#f5f5f5;border-radius:5px;margin:10px 0;">
    <h3 style="margin:0 0 10px 0;color:{color};">{emoji} {tier_label}</h3>
    <p style="margin:5px 0;"><strong>Category:</strong> {category}</p>
    <p style="margin:5px 0;"><strong>Confidence:</strong> {confidence:.0%}</p>
    <p style="margin:5px 0;">{retry_badge}</p>
    <div style="background:white;padding:10px;border-left:4px solid {color};margin:10px 0;">
        <strong>Root Cause:</strong><br/>
        {root_cause}
    </div>
"""
        
        if recommendations:
            html += "    <div style='margin-top:10px;'><strong>Quick Fixes:</strong><ul style='margin:5px 0;'>"
            for rec in recommendations[:3]:
                html += f"<li>{rec}</li>"
            html += "</ul></div>"
        
        html += """
    <p style="font-size:11px;color:#888;margin-top:10px;">
        Generated by Jenkins Failure Analysis Agent
    </p>
</div>
"""
        return html
