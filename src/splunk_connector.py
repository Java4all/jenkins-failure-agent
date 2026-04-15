"""
Splunk Connector - Pull failed Jenkins builds from Splunk.

Features:
- Query failed builds from Splunk
- Fetch log tails (last N lines)
- Pagination handling
- Scheduled sync support
"""

import logging
import os
import re
import time
import requests
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
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
    source_subsearch_limit: int = 1000
    log_signal_lines: int = 120
    log_snippet_max_chars: int = 12000
    primary_candidate_limit: int = 5
    # Extra regex fragments (semicolon-separated in env) merged into signal search
    signal_extra_patterns: List[str] = field(default_factory=list)


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

    # High-signal failure patterns that often contain the true root cause
    # earlier than the final "script returned exit code N" lines.
    SIGNAL_PATTERNS = [
        r"could not find any revision to build",
        r"couldn't find any revision to build",
        r"unable to checkout revision",
        r"checkout failed",
        r"hudson\.plugins\.git\.GitException",
        r"fatal:",
        r"error:",
        r"exception",
        r"script returned exit code",
        r"permission denied",
        r"not found",
    ]

    # Higher score = more likely to be the true root cause (for ranking PRIMARY CANDIDATES).
    _SIGNAL_SCORE_RULES: List[Tuple[re.Pattern, int]] = [
        (re.compile(r"(?i)couldn'?t find any revision to build|could not find any revision to build"), 100),
        (re.compile(r"(?i)unable to checkout revision|checkout failed"), 95),
        (re.compile(r"(?i)hudson\.plugins\.git\.GitException|org\.jenkinsci\.plugins\.git"), 95),
        (re.compile(r"(?i)permission denied|access denied|unauthorized|forbidden"), 88),
        (re.compile(r"(?i)fatal:"), 80),
        (re.compile(r"(?i)(?:^|\s)(?:error|ERROR):\s*\S"), 50),
        (re.compile(r"(?i)java\.[a-z.]+\.(?:Exception|Error)"), 78),
        (re.compile(r"(?i)npm ERR!|yarn error|pip.*error|maven.*failure", re.IGNORECASE), 72),
        (re.compile(r"(?i)script returned exit code\s+[1-9]\d*"), 38),
        (re.compile(r"(?i)\bexception\b"), 45),
        (re.compile(r"(?i)not found|no such file"), 55),
    ]

    _NOISE_ONLY_TAIL_LINE = re.compile(
        r"(?i)^(?:\[[^\]]+\]\s*)?(?:\d{2}:\d{2}:\d{2}\s+)?(?:\+\s*)?"
        r"(?:Finished:\s*(?:FAILURE|ABORTED|UNSTABLE|NOT_BUILT)\s*|"
        r"Build (?:step .* )?marked build as failure\.?\s*|"
        r"script returned exit code\s+\d+\s*|"
        r"Sending interrupt signal to process.*\s*)$"
    )

    @staticmethod
    def _score_signal_line(line: str) -> int:
        if not line or not line.strip():
            return 0
        best = 0
        for rx, weight in SplunkConnector._SIGNAL_SCORE_RULES:
            if rx.search(line):
                best = max(best, weight)
        return best if best > 0 else 12

    @classmethod
    def _rank_primary_candidates(cls, lines: List[str], limit: int) -> List[str]:
        """Deduplicate by stripped text, sort by score desc then line length (specificity)."""
        seen = set()
        scored: List[Tuple[int, int, str]] = []
        for line in lines:
            key = line.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            scored.append((cls._score_signal_line(line), len(line), line))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        return [t[2] for t in scored[:limit]]

    @classmethod
    def _partition_tail_noise(cls, tail_lines: List[str]) -> Tuple[List[str], List[str]]:
        """Split tail into substantive vs low-signal-only lines (Finished: FAILURE, exit code only, etc.)."""
        keep: List[str] = []
        noise: List[str] = []
        for line in tail_lines:
            if cls._NOISE_ONLY_TAIL_LINE.match(line.strip()):
                noise.append(line)
            else:
                keep.append(line)
        return keep, noise

    def _build_source_filter_subsearch(self, minutes: int) -> str:
        """
        Build a source-based subsearch filter.

        Why: the source/library marker is often present on checkout/compile lines,
        not on the final "Finished: ..." line. Filtering by source avoids false zero
        results when a plain text filter is applied to the outer search event.
        """
        if not self.config.search_filter:
            return ""
        # Use `return` to emit source filters directly to outer search and cap
        # candidate sources to keep subsearch bounded.
        return (
            f'[ search index={self.config.index} source="*/console" "{self.config.search_filter}" earliest=-{minutes}m latest=now '
            f'| fields source | dedup source | head {self.config.source_subsearch_limit} '
            f'| return {self.config.source_subsearch_limit} source ]'
        )
    
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
        
        filter_clause = f'"{self.config.search_filter}"' if self.config.search_filter else ""
        source_filter_subsearch = self._build_source_filter_subsearch(minutes)

        if simple_query:
            # Fast path: direct text filter (often enough, much cheaper than subsearch).
            query = f'''
index={self.config.index} source="*/console" "Finished: FAILURE" {filter_clause} earliest=-{minutes}m latest=now
| rex field=source "/(?<job_id>\d+)/console$"
| where isnotnull(job_id) AND job_id!=""
| eval src=coalesce(source, host)
| stats count as failure_count BY host, src, job_id
| sort -failure_count
| head 100
'''
        else:
            # Complex query with result extraction and source normalization
            query = f'''
index={self.config.index} source="*/console" "Finished:" {source_filter_subsearch} earliest=-{minutes}m latest=now
| rex field=_raw "Finished:\s+(?<result>\w+)"
| eval result=upper(result)
| where result=="FAILURE"
| rex field=source "/(?<job_id>\d+)/console$"
| where isnotnull(job_id) AND job_id!=""
| eval src_orig=coalesce(source, host)
| eval src_try=replace(src_orig, "/\\d+/console$|/console$", "")
| eval src_tmp=if(src_try==src_orig, replace(src_orig, "/[^/]+/[^/]+$", ""), src_try)
| eval src=replace(replace(src_tmp, "/job/[a-z]{2}(?:-[a-z]+)*-\\d+", ""), "/+", "/")
| stats count as failure_count BY host, src, job_id
| sort -failure_count
| head 100
'''
        
        logger.info(f"Querying Splunk for failed builds (last {minutes} mins, simple={simple_query})")
        results = self._search(query.strip())

        # Fallback path: if fast direct filter returns nothing, retry with source
        # subsearch to avoid false negatives caused by term placement in non-final
        # log lines.
        if simple_query and not results and self.config.search_filter:
            logger.info("Fast query returned 0 rows. Retrying with source subsearch fallback.")
            fallback_query = f'''
index={self.config.index} source="*/console" "Finished: FAILURE" {source_filter_subsearch} earliest=-{minutes}m latest=now
| rex field=source "/(?<job_id>\d+)/console$"
| where isnotnull(job_id) AND job_id!=""
| eval src=coalesce(source, host)
| stats count as failure_count BY host, src, job_id
| sort -failure_count
| head 100
'''
            results = self._search(fallback_query.strip())
        
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

        tail_query = f'''
index={self.config.index} host="{host}" source="*/{job_id}/console"
| sort _time
| tail {tail_lines}
| table _raw
'''

        pattern_parts = list(self.SIGNAL_PATTERNS)
        pattern_parts.extend(self.config.signal_extra_patterns or [])
        signal_regex = "(?i)(" + "|".join(pattern_parts) + ")"
        signal_query = f'''
index={self.config.index} host="{host}" source="*/{job_id}/console"
| sort _time
| regex _raw="{signal_regex}"
| head {self.config.log_signal_lines}
| table _raw
'''

        logger.info(f"Fetching log for {host} build {job_id} (last {tail_lines} lines)")
        signal_results = self._search(signal_query.strip(), max_results=self.config.log_signal_lines)
        tail_results = self._search(tail_query.strip(), max_results=tail_lines)

        signal_lines = [row.get("_raw", "") for row in signal_results if row.get("_raw")]
        tail_lines_list = [row.get("_raw", "") for row in tail_results if row.get("_raw")]

        primary = self._rank_primary_candidates(
            signal_lines,
            limit=max(1, self.config.primary_candidate_limit),
        )
        tail_keep, tail_noise = self._partition_tail_noise(tail_lines_list)

        # Dedupe tail vs signals (avoid repeating identical lines in TAIL section)
        sig_set = {s.strip() for s in signal_lines}
        tail_deduped = [ln for ln in tail_keep if ln.strip() not in sig_set]

        sections: List[str] = []
        if primary:
            sections.append(
                "=== PRIMARY CANDIDATES (ranked by heuristic — prefer these for root cause) ===\n"
                + "\n".join(primary)
            )
        if signal_lines:
            sections.append(
                "=== ALL SIGNAL LINES (chronological, from full log) ===\n"
                + "\n".join(signal_lines)
            )
        if tail_deduped:
            sections.append("=== LOG TAIL (noise-reduced) ===\n" + "\n".join(tail_deduped))
        elif tail_lines_list and not signal_lines:
            sections.append("=== LOG TAIL ===\n" + "\n".join(tail_lines_list))
        if tail_noise:
            sections.append(
                "=== LOW-SIGNAL TAIL LINES (context only — do not treat as primary error alone) ===\n"
                + "\n".join(tail_noise)
            )

        if not sections:
            return ""

        combined = "\n\n".join(sections)
        return combined[: self.config.log_snippet_max_chars]
    
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
        
        extra_raw = os.environ.get("SPLUNK_SIGNAL_EXTRA_REGEX", "")
        signal_extra = [p.strip() for p in extra_raw.split(";") if p.strip()]

        splunk_config = SplunkConfig(
            enabled=os.environ.get("SPLUNK_ENABLED", "false").lower() == "true",
            url=os.environ.get("SPLUNK_URL", ""),
            token=os.environ.get("SPLUNK_TOKEN", ""),
            index=os.environ.get("SPLUNK_INDEX", "jenkins_console"),
            search_filter=os.environ.get("SPLUNK_SEARCH_FILTER", ""),
            log_tail_lines=int(os.environ.get("SPLUNK_LOG_TAIL_LINES", "500")),
            sync_interval_mins=int(os.environ.get("SPLUNK_SYNC_INTERVAL_MINS", "15")),
            verify_ssl=os.environ.get("SPLUNK_VERIFY_SSL", "false").lower() == "true",
            timeout=int(os.environ.get("SPLUNK_TIMEOUT", "60")),
            source_subsearch_limit=int(os.environ.get("SPLUNK_SOURCE_SUBSEARCH_LIMIT", "1000")),
            log_signal_lines=int(os.environ.get("SPLUNK_LOG_SIGNAL_LINES", "120")),
            log_snippet_max_chars=int(os.environ.get("SPLUNK_LOG_SNIPPET_MAX_CHARS", "12000")),
            primary_candidate_limit=int(os.environ.get("SPLUNK_PRIMARY_CANDIDATE_LIMIT", "5")),
            signal_extra_patterns=signal_extra,
        )
        
        if splunk_config.enabled:
            _splunk_connector = SplunkConnector(splunk_config)
    
    return _splunk_connector
