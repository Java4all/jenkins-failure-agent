"""
Splunk Connector - Pull failed Jenkins builds from Splunk.

Features:
- Query failed builds from Splunk
- Fetch log tails (last N lines)
- Pagination handling
- Scheduled sync support
"""

import logging
import time
import requests
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin

logger = logging.getLogger("jenkins-agent.splunk")


@dataclass
class SplunkConfig:
    """Splunk connection configuration."""
    enabled: bool = False
    url: str = ""
    token: str = ""              # Bearer token
    index: str = "jenkins_console"
    search_filter: str = ""
    log_tail_lines: int = 500
    sync_interval_mins: int = 15
    verify_ssl: bool = False
    timeout: int = 60


@dataclass
class FailedBuild:
    """Represents a failed Jenkins build from Splunk."""
    host: str                    # Jenkins server URL
    src: str                     # Pipeline location/path
    job_id: str                  # Build number
    failure_count: int = 1
    timestamp: str = ""
    log_snippet: str = ""        # Last N lines of log
    
    @property
    def job_name(self) -> str:
        """Extract job name from src path."""
        # src typically like: /job/folder/job/pipeline-name
        parts = self.src.strip("/").split("/")
        # Filter out 'job' segments
        name_parts = [p for p in parts if p != "job"]
        return "/".join(name_parts) if name_parts else self.src
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "src": self.src,
            "job_id": self.job_id,
            "job_name": self.job_name,
            "failure_count": self.failure_count,
            "timestamp": self.timestamp,
            "log_snippet": self.log_snippet[:500] + "..." if len(self.log_snippet) > 500 else self.log_snippet,
        }


class SplunkConnector:
    """
    Connects to Splunk to pull failed Jenkins builds.
    
    Usage:
        config = SplunkConfig(
            url="https://splunk:8089",
            token="xxx",
            index="jenkins_console",
            search_filter="abc/shared-code"
        )
        connector = SplunkConnector(config)
        
        # Get failed builds from last 15 minutes
        failures = connector.get_failed_builds(minutes=15)
        
        # Get log for specific build
        log = connector.get_build_log(host, job_id)
    """
    
    def __init__(self, config: SplunkConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.token}",
        })
    
    def _search(self, query: str, max_results: int = 1000) -> List[Dict[str, Any]]:
        """
        Execute Splunk search and return results.
        
        Uses async mode: create job, poll until done, fetch results.
        """
        if not self.config.enabled:
            logger.warning("Splunk integration not enabled")
            return []
        
        # Create search job (async mode)
        search_url = urljoin(self.config.url, "/services/search/jobs")
        
        search_query = f"search {query}"
        
        # Log curl equivalent for debugging
        logger.info("=" * 60)
        logger.info("SPLUNK DEBUG - Equivalent curl command:")
        logger.info(f'''curl -k -X POST "{search_url}" \\
  -H "Authorization: Bearer $SPLUNK_TOKEN" \\
  -d "search={search_query[:200]}..." \\
  -d "output_mode=json" \\
  -d "exec_mode=normal"''')
        logger.info("=" * 60)
        logger.info(f"Full query:\n{query}")
        logger.info("=" * 60)
        
        try:
            # Create job in normal (async) mode
            post_data = {
                "search": search_query,
                "output_mode": "json",
                "exec_mode": "normal",
            }
            
            logger.info(f"POST data: {post_data}")
            
            response = self.session.post(
                search_url,
                data=post_data,
                verify=self.config.verify_ssl,
                timeout=30,
            )
            
            logger.info(f"Job creation response: {response.status_code}")
            logger.info(f"Job creation body: {response.text[:500]}")
            
            response.raise_for_status()
            
            job_data = response.json()
            job_sid = job_data.get("sid")
            
            if not job_sid:
                logger.error(f"No job SID returned. Full response: {job_data}")
                return []
            
            logger.info(f"Job SID: {job_sid}")
            logger.info(f"Check job status: curl -k -H 'Authorization: Bearer $SPLUNK_TOKEN' '{self.config.url}/services/search/jobs/{job_sid}?output_mode=json'")
            
            # Poll for job completion
            status_url = urljoin(self.config.url, f"/services/search/jobs/{job_sid}")
            max_wait = self.config.timeout
            poll_interval = 2
            elapsed = 0
            is_done = False
            
            while elapsed < max_wait:
                status_response = self.session.get(
                    status_url,
                    params={"output_mode": "json"},
                    verify=self.config.verify_ssl,
                    timeout=10,
                )
                status_response.raise_for_status()
                
                status_data = status_response.json()
                entry = status_data.get("entry", [{}])[0]
                content = entry.get("content", {})
                
                dispatch_state = content.get("dispatchState", "")
                is_done = content.get("isDone", False)
                run_duration = content.get("runDuration", 0)
                scan_count = content.get("scanCount", 0)
                event_count = content.get("eventCount", 0)
                result_count = content.get("resultCount", 0)
                
                logger.info(f"[{elapsed}s] State: {dispatch_state}, Done: {is_done}, "
                           f"Duration: {run_duration:.1f}s, Scanned: {scan_count}, "
                           f"Events: {event_count}, Results: {result_count}")
                
                if is_done:
                    break
                
                if dispatch_state == "FAILED":
                    messages = content.get("messages", [])
                    logger.error(f"Splunk job FAILED: {messages}")
                    return []
                
                time.sleep(poll_interval)
                elapsed += poll_interval
            
            if not is_done:
                logger.error(f"Job timed out after {max_wait}s. Last state: {dispatch_state}")
                logger.error(f"Try running manually: curl -k -H 'Authorization: Bearer $SPLUNK_TOKEN' '{self.config.url}/services/search/jobs/{job_sid}?output_mode=json'")
                # Cancel the job
                try:
                    self.session.delete(status_url, verify=self.config.verify_ssl, timeout=5)
                    logger.info(f"Cancelled job {job_sid}")
                except Exception as e:
                    logger.warning(f"Failed to cancel job: {e}")
                return []
            
            # Get results
            results_url = urljoin(self.config.url, f"/services/search/jobs/{job_sid}/results")
            logger.info(f"Fetching results: curl -k -H 'Authorization: Bearer $SPLUNK_TOKEN' '{results_url}?output_mode=json&count={max_results}'")
            
            results_response = self.session.get(
                results_url,
                params={"output_mode": "json", "count": max_results},
                verify=self.config.verify_ssl,
                timeout=30,
            )
            
            logger.info(f"Results response: {results_response.status_code}")
            results_response.raise_for_status()
            
            results_data = results_response.json()
            results = results_data.get("results", [])
            
            logger.info(f"Got {len(results)} results")
            if results:
                logger.info(f"First result keys: {list(results[0].keys())}")
                logger.debug(f"First result: {results[0]}")
            
            return results
            
        except requests.RequestException as e:
            logger.error(f"Splunk request failed: {e}")
            logger.error(f"Response: {getattr(e.response, 'text', 'N/A')[:500] if hasattr(e, 'response') else 'N/A'}")
            return []
    
    def get_failed_builds(self, minutes: int = None, simple_query: bool = True) -> List[FailedBuild]:
        """
        Get list of failed builds from Splunk.
        
        Args:
            minutes: Look back N minutes (default: sync_interval_mins)
            simple_query: Use simpler query without subsearch (default True - faster)
            
        Returns:
            List of FailedBuild objects
        """
        if minutes is None:
            minutes = self.config.sync_interval_mins
        
        filter_clause = ""
        if self.config.search_filter:
            filter_clause = f'"{self.config.search_filter}"'
        
        if simple_query:
            # Simple query - just find "Finished: FAILURE" lines directly
            query = f'''
index={self.config.index} "Finished: FAILURE" {filter_clause} earliest=-{minutes}m
| rex field=source "/(?<job_id>\d+)/console$"
| stats count as failure_count BY host, source, job_id
| rename source as src
| sort -failure_count
| head 100
'''
        else:
            # Complex query with regex extraction (slower)
            query = f'''
index={self.config.index} "Finished:" {filter_clause} earliest=-{minutes}m
| rex field=_raw "Finished:\s+(?<result>\w+)"
| where result=="FAILURE"
| rex field=source "/(?<job_id>\d+)/console$"
| stats count as failure_count BY host, source, job_id
| rename source as src
| sort -failure_count
| head 100
'''
        
        logger.info(f"Querying Splunk for failed builds (last {minutes} mins, simple={simple_query})")
        results = self._search(query.strip())
        
        failures = []
        for row in results:
            failures.append(FailedBuild(
                host=row.get("host", ""),
                src=row.get("src", ""),
                job_id=row.get("job_id", ""),
                failure_count=int(row.get("failure_count", 1)),
            ))
        
        logger.info(f"Found {len(failures)} failed builds")
        return failures
    
    def test_simple_search(self, minutes: int = 15) -> Dict[str, Any]:
        """
        Run a minimal test search to verify Splunk query execution.
        Use this to debug - if this works, issue is with the main query.
        """
        import time as time_module
        
        query = f'''
index={self.config.index} earliest=-{minutes}m
| head 10
| stats count
'''
        
        logger.info(f"Running test search on index={self.config.index}")
        start = time_module.time()
        results = self._search(query.strip())
        elapsed = time_module.time() - start
        
        return {
            "success": len(results) > 0,
            "elapsed_seconds": round(elapsed, 2),
            "event_count": results[0].get("count", 0) if results else 0,
            "index": self.config.index,
            "query": query.strip(),
        }
    
    def get_build_log(self, host: str, job_id: str, tail_lines: int = None) -> str:
        """
        Get console log for a specific build.
        
        Args:
            host: Jenkins server host
            job_id: Build number
            tail_lines: Number of lines from end (default: config.log_tail_lines)
            
        Returns:
            Log content (last N lines)
        """
        if tail_lines is None:
            tail_lines = self.config.log_tail_lines
        
        query = f'''
index={self.config.index} host="{host}" source="*/{job_id}/console"
| sort _time
| tail {tail_lines}
| table _raw
'''
        
        logger.info(f"Fetching log for {host} build {job_id} (last {tail_lines} lines)")
        results = self._search(query.strip(), max_results=tail_lines)
        
        # Combine _raw fields
        log_lines = [row.get("_raw", "") for row in results]
        return "\n".join(log_lines)
    
    def get_failed_builds_with_logs(self, minutes: int = None) -> List[FailedBuild]:
        """
        Get failed builds with log snippets.
        
        Args:
            minutes: Look back N minutes
            
        Returns:
            List of FailedBuild with log_snippet populated
        """
        failures = self.get_failed_builds(minutes)
        
        for failure in failures:
            try:
                failure.log_snippet = self.get_build_log(failure.host, failure.job_id)
            except Exception as e:
                logger.error(f"Failed to fetch log for {failure.host}/{failure.job_id}: {e}")
                failure.log_snippet = ""
        
        return failures
    
    def test_connection(self) -> Dict[str, Any]:
        """Test Splunk connection with detailed status."""
        if not self.config.enabled:
            return {
                "success": False, 
                "enabled": False,
                "error": "Splunk integration not enabled"
            }
        
        if not self.config.url:
            return {
                "success": False,
                "enabled": True,
                "error": "SPLUNK_URL not configured"
            }
        
        if not self.config.token:
            return {
                "success": False,
                "enabled": True,
                "error": "SPLUNK_TOKEN not configured"
            }
        
        try:
            # Test basic connectivity to Splunk server info endpoint
            info_url = urljoin(self.config.url, "/services/server/info")
            
            response = self.session.get(
                info_url,
                params={"output_mode": "json"},
                verify=self.config.verify_ssl,
                timeout=10,  # Short timeout for connection test
            )
            
            if response.status_code == 401:
                return {
                    "success": False,
                    "enabled": True,
                    "error": "Authentication failed - check SPLUNK_TOKEN",
                    "status_code": 401
                }
            
            if response.status_code == 403:
                return {
                    "success": False,
                    "enabled": True,
                    "error": "Access forbidden - token may lack permissions",
                    "status_code": 403
                }
            
            response.raise_for_status()
            
            # Parse server info
            data = response.json()
            server_info = data.get("entry", [{}])[0].get("content", {})
            
            return {
                "success": True,
                "enabled": True,
                "message": "Connected to Splunk",
                "url": self.config.url,
                "index": self.config.index,
                "search_filter": self.config.search_filter or "(none)",
                "server_name": server_info.get("serverName", "unknown"),
                "version": server_info.get("version", "unknown"),
            }
            
        except requests.Timeout:
            return {
                "success": False,
                "enabled": True,
                "error": f"Connection timeout - check SPLUNK_URL ({self.config.url})",
                "url": self.config.url
            }
        except requests.ConnectionError as e:
            return {
                "success": False,
                "enabled": True,
                "error": f"Connection failed - {str(e)[:100]}",
                "url": self.config.url
            }
        except Exception as e:
            return {
                "success": False,
                "enabled": True, 
                "error": str(e)[:200],
                "url": self.config.url
            }


# Singleton instance
_splunk_connector: Optional[SplunkConnector] = None


def reset_splunk_connector():
    """Reset singleton to pick up config changes."""
    global _splunk_connector
    _splunk_connector = None


def get_splunk_connector() -> Optional[SplunkConnector]:
    """Get or create Splunk connector singleton."""
    global _splunk_connector
    
    if _splunk_connector is None:
        import os
        
        splunk_config = SplunkConfig(
            enabled=os.environ.get("SPLUNK_ENABLED", "false").lower() == "true",
            url=os.environ.get("SPLUNK_URL", ""),
            token=os.environ.get("SPLUNK_TOKEN", ""),
            index=os.environ.get("SPLUNK_INDEX", "jenkins_console"),
            search_filter=os.environ.get("SPLUNK_SEARCH_FILTER", ""),
            log_tail_lines=int(os.environ.get("SPLUNK_LOG_TAIL_LINES", "500")),
            sync_interval_mins=int(os.environ.get("SPLUNK_SYNC_INTERVAL_MINS", "15")),
            verify_ssl=os.environ.get("SPLUNK_VERIFY_SSL", "false").lower() == "true",
        )
        
        if splunk_config.enabled:
            _splunk_connector = SplunkConnector(splunk_config)
    
    return _splunk_connector
