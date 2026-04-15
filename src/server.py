"""
FastAPI server for Jenkins Failure Analysis Agent.
Provides HTTP endpoints for integration with Jenkins webhooks.
"""

import logging
import uuid
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, File, UploadFile, Form
from starlette.requests import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import Config
from .jenkins_client import JenkinsClient
from .log_parser import LogParser
from .git_analyzer import GitAnalyzer
from .github_client import GitHubClient, GitHubConfig, FetchResult
from .ai_analyzer import AIAnalyzer, AnalysisResult, result_to_dict
from .report_generator import ReportGenerator, format_slack_message
from .scm_client import SCMClient, SCMConfig as SCMClientConfig, SCMProvider, PRInfo, format_pr_comment

logger = logging.getLogger("jenkins-agent.server")


class AnalyzeRequest(BaseModel):
    """Request body for analyze endpoint."""
    job: str
    build: Optional[int] = None
    latest_failed: bool = False
    workspace: Optional[str] = None
    # GitHub repository info (optional - for source code fetching)
    project_repo: Optional[str] = None  # e.g., "org/my-project"
    project_ref: Optional[str] = None   # branch/tag/commit
    # PR info for posting comments (optional)
    pr_url: Optional[str] = None  # e.g., "https://github.com/org/repo/pull/123"
    pr_sha: Optional[str] = None  # Commit SHA for status updates
    # Analysis mode (Requirement 5.9)
    mode: str = "iterative"  # "iterative" (default) or "deep"
    # User hint for focused analysis (Requirement 18.1)
    user_hint: Optional[str] = None  # e.g., "I think the issue is in the deploy stage"
    # Notification options
    notify_slack: bool = False
    update_jenkins_description: bool = True
    post_to_pr: bool = True
    generate_report: bool = True


class AnalyzeResponse(BaseModel):
    """Response body for analyze endpoint."""
    success: bool
    job: str
    build: int
    category: str = ""
    tier: str = ""  # 3-tier classification
    root_cause: str = ""
    confidence: float = 0.0
    is_retriable: bool = False
    retry_reason: str = ""
    recommendations: list = []
    report_url: Optional[str] = None
    # Source code fetch info
    source_files_fetched: list = []
    # Reporter status
    jenkins_description_updated: bool = False
    pr_comment_posted: bool = False
    # Analysis mode info (Req 5.9)
    analysis_mode: str = "iterative"  # iterative or deep
    iterations_used: int = 0
    # Req 14: Skip status
    status: str = "completed"  # "completed", "no_analysis_needed", "in_progress"
    skip_reason: str = ""
    tool_calls_made: int = 0
    correlation_id: str = ""


class HealthResponse(BaseModel):
    """Response for health check endpoint."""
    status: str
    jenkins_connected: bool
    ai_connected: bool
    github_connected: bool = False
    scm_connected: bool = False
    timestamp: str


class JenkinsConfigRequest(BaseModel):
    """Request body for updating Jenkins configuration."""
    url: Optional[str] = None
    username: Optional[str] = None
    api_token: Optional[str] = None


class JenkinsConfigResponse(BaseModel):
    """Response for Jenkins configuration endpoint."""
    success: bool
    url: str
    username: str
    has_token: bool
    message: str = ""


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    
    app = FastAPI(
        title="Jenkins Failure Analysis Agent",
        description="AI-powered build failure analysis for Jenkins (Hybrid Mode)",
        version="3.0.0"
    )
    
    # CORS middleware - allow all for UI access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID"],
    )

    @app.middleware("http")
    async def correlation_id_middleware(http_request: Request, call_next):
        cid = http_request.headers.get("x-correlation-id") or str(uuid.uuid4())
        http_request.state.correlation_id = cid
        response = await call_next(http_request)
        response.headers["X-Correlation-ID"] = cid
        return response
    
    # Initialize clients
    jenkins_client = JenkinsClient(config.jenkins)
    log_parser = LogParser(vars(config.parsing))
    git_analyzer = GitAnalyzer(vars(config.git)) if config.git.enabled else None
    report_generator = ReportGenerator(config.reporting.get("output_directory", "./reports"))
    
    # Initialize GitHub client for source code fetching
    github_client = None
    if config.github.enabled and config.github.token:
        from .github_client import LibraryConfig
        
        library_configs = [
            LibraryConfig(name=name, repo=repo)
            for name, repo in config.github.library_mappings.items()
        ]
        
        github_config = GitHubConfig(
            base_url=config.github.base_url,
            token=config.github.token,
            timeout=config.github.timeout,
            verify_ssl=config.github.verify_ssl,
            cache_enabled=config.github.cache_enabled,
            cache_ttl_seconds=config.github.cache_ttl_seconds,
        )
        
        github_client = GitHubClient(github_config, library_configs)
        logger.info(f"GitHub client initialized for {config.github.base_url}")
    
    # Initialize SCM client for PR comments
    scm_client = None
    if config.scm.enabled and config.scm.token:
        scm_client_config = SCMClientConfig(
            provider=SCMProvider(config.scm.provider),
            api_url=config.scm.api_url,
            token=config.scm.token,
            verify_ssl=config.scm.verify_ssl,
        )
        scm_client = SCMClient(scm_client_config)
        logger.info(f"SCM client initialized for {config.scm.provider}")
    
    # Initialize hybrid analyzer (scripted + agentic)
    from .hybrid_analyzer import HybridAnalyzer
    hybrid_analyzer = HybridAnalyzer(config)
    hybrid_analyzer.set_clients(
        jenkins_client=jenkins_client,
        github_client=github_client,
        scm_client=scm_client,
    )
    logger.info("Hybrid analyzer initialized (scripted + agentic modes available)")
    
    # Keep legacy ai_analyzer for backward compatibility
    ai_analyzer = AIAnalyzer(config.ai)
    
    # API key validation
    async def verify_api_key(x_api_key: Optional[str] = Header(None)):
        # Skip validation if API key is not configured or empty
        server_api_key = config.server.api_key.strip() if config.server.api_key else ""
        if not server_api_key:
            return True
        
        if not x_api_key or x_api_key != server_api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return True
    
    # Store for background task results
    analysis_results = {}
    
    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        """Health check endpoint."""
        github_connected = False
        if github_client:
            connected, _ = github_client.test_connection()
            github_connected = connected
        
        scm_connected = False
        if scm_client:
            scm_connected = scm_client.test_connection()
        
        return HealthResponse(
            status="healthy",
            jenkins_connected=jenkins_client.test_connection(),
            ai_connected=ai_analyzer.test_connection(),
            github_connected=github_connected,
            scm_connected=scm_connected,
            timestamp=datetime.now().isoformat()
        )
    
    @app.get("/config/jenkins", response_model=JenkinsConfigResponse)
    async def get_jenkins_config():
        """Get current Jenkins configuration (token masked)."""
        return JenkinsConfigResponse(
            success=True,
            url=jenkins_client.config.url,
            username=jenkins_client.config.username,
            has_token=bool(jenkins_client.config.api_token),
            message="Current Jenkins configuration"
        )
    
    @app.post("/config/jenkins", response_model=JenkinsConfigResponse)
    async def update_jenkins_config(request: JenkinsConfigRequest):
        """
        Update Jenkins configuration at runtime.
        
        Only provided fields will be updated. Empty fields are ignored.
        This updates the running configuration only - not the config file.
        """
        try:
            # Update only provided fields
            jenkins_client.update_config(
                url=request.url if request.url else None,
                username=request.username if request.username else None,
                api_token=request.api_token if request.api_token else None
            )
            
            # Test connection with new config
            connected = jenkins_client.test_connection()
            
            if connected:
                logger.info(f"Jenkins config updated: {jenkins_client.config.url}")
                return JenkinsConfigResponse(
                    success=True,
                    url=jenkins_client.config.url,
                    username=jenkins_client.config.username,
                    has_token=bool(jenkins_client.config.api_token),
                    message="Jenkins configuration updated successfully"
                )
            else:
                return JenkinsConfigResponse(
                    success=False,
                    url=jenkins_client.config.url,
                    username=jenkins_client.config.username,
                    has_token=bool(jenkins_client.config.api_token),
                    message="Configuration updated but connection test failed"
                )
        except Exception as e:
            logger.error(f"Failed to update Jenkins config: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/analyze")
    async def analyze_build(
        analyze_request: AnalyzeRequest,
        http_request: Request,
        background_tasks: BackgroundTasks,
        _: bool = Depends(verify_api_key)
    ):
        """
        Analyze a Jenkins build failure.
        
        This endpoint fetches build information, parses logs, fetches source code
        from GitHub (if configured), performs AI analysis, and returns actionable insights.
        Results are automatically posted to Jenkins build description and PR comments.
        """
        try:
            correlation_id = getattr(http_request.state, "correlation_id", "") or ""
            logger.info(
                "Analyze job=%s correlation_id=%s",
                analyze_request.job,
                correlation_id,
            )
            # Determine build number
            build_number = analyze_request.build
            if analyze_request.latest_failed or not build_number:
                # Find latest failed build
                build_number = jenkins_client.get_latest_failed_build(analyze_request.job)
                if not build_number:
                    raise HTTPException(
                        status_code=404,
                        detail="No failed builds found for this job"
                    )
            
            # Get build info
            build_info = jenkins_client.get_build_info(analyze_request.job, build_number)
            
            # =========================================================
            # Requirement 14.1: Check build status BEFORE log parsing
            # =========================================================
            
            # Req 14.3: Build still in progress
            if build_info.building:
                logger.info(f"Build {analyze_request.job}#{build_number} is still running - skipping analysis")
                return AnalyzeResponse(
                    success=True,
                    job=analyze_request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason="Build is still in progress",
                    analysis_mode="none",
                    correlation_id=correlation_id,
                )
            
            # Req 14.2: Build succeeded
            if build_info.status == "SUCCESS":
                logger.info(f"Build {analyze_request.job}#{build_number} succeeded - no failure to analyze")
                return AnalyzeResponse(
                    success=True,
                    job=analyze_request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason="Build succeeded",
                    analysis_mode="none",
                    correlation_id=correlation_id,
                )
            
            # Req 14.4: Build was aborted
            if build_info.status == "ABORTED":
                logger.info(f"Build {analyze_request.job}#{build_number} was aborted - skipping analysis")
                return AnalyzeResponse(
                    success=True,
                    job=analyze_request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason="Build was manually aborted",
                    analysis_mode="none",
                    correlation_id=correlation_id,
                )
            
            # UNSTABLE: tests/quality gates — not analyzed (only FAILURE is)
            if build_info.status == "UNSTABLE":
                logger.info(
                    "Build %s#%s is UNSTABLE — skipping analysis (analyzer targets FAILURE only)",
                    analyze_request.job,
                    build_number,
                )
                return AnalyzeResponse(
                    success=True,
                    job=analyze_request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason=(
                        "Jenkins UNSTABLE (e.g. failing tests). Not analyzed; this service only analyzes FAILURE builds."
                    ),
                    analysis_mode="none",
                    correlation_id=correlation_id,
                )
            
            # =========================================================
            # Fetch logs for FAILURE builds only (UNSTABLE handled above).
            # "Latest failed" without a build number uses FAILURE only; see JenkinsClient.
            # =========================================================
            
            # Fetch console log
            console_log = jenkins_client.get_console_log(analyze_request.job, build_number)
            
            # Parse logs
            parsed_log = log_parser.parse(console_log)
            
            # DEBUG: Check if tool_invocations exist after parsing
            tool_inv = getattr(parsed_log, 'tool_invocations', None)
            logger.info(f"=== DEBUG PARSE: tool_invocations count = {len(tool_inv) if tool_inv else 0}")
            if tool_inv:
                for t in tool_inv[:3]:  # Log first 3
                    logger.info(f"=== DEBUG PARSE: tool = {t.tool_name}, cmd = {t.command_line[:50]}...")
            else:
                logger.warning("=== DEBUG PARSE: NO tool_invocations found by LogParser!")
            
            # Get test results
            test_results = jenkins_client.get_test_results(analyze_request.job, build_number)
            
            # Git analysis (if workspace provided)
            git_analysis = None
            if git_analyzer and analyze_request.workspace:
                try:
                    git_analysis = git_analyzer.analyze(analyze_request.workspace)
                except Exception as e:
                    logger.warning(f"Git analysis failed: {e}")
            
            # Fetch source code from GitHub
            jenkinsfile_content = None
            library_sources = {}
            fetch_result = None
            
            if github_client:
                try:
                    # Determine project repo and ref
                    project_repo = analyze_request.project_repo
                    project_ref = analyze_request.project_ref or "main"
                    
                    # Try to infer repo from job name if not provided
                    if not project_repo:
                        # Check if we have a mapping in config
                        project_mappings = getattr(config.github, 'project_mappings', {})
                        if analyze_request.job in project_mappings:
                            project_repo = project_mappings[analyze_request.job]
                    
                    # Fetch code
                    fetch_result = github_client.fetch_for_analysis(
                        project_repo=project_repo,
                        project_ref=project_ref,
                        auto_detect_libraries=True
                    )
                    
                    if fetch_result.jenkinsfile:
                        jenkinsfile_content = fetch_result.jenkinsfile
                        logger.info(f"Fetched Jenkinsfile from {fetch_result.jenkinsfile_repo}")
                    
                    if fetch_result.libraries:
                        library_sources = github_client.get_library_sources_dict(fetch_result)
                        logger.info(f"Fetched {len(fetch_result.libraries)} libraries")
                    
                    if fetch_result.errors:
                        for error in fetch_result.errors:
                            logger.warning(f"GitHub fetch warning: {error}")
                    
                except Exception as e:
                    logger.warning(f"GitHub code fetch failed: {e}")
            
            # AI analysis with source code (using hybrid analyzer)
            log_snippet = log_parser.get_error_snippet(parsed_log, max_errors=10)
            
            # Use hybrid analyzer (Requirement 5):
            # - mode="iterative" (default): multi-call iterative RC analysis
            # - mode="deep": full MCP tool agent investigation
            deep_mode = analyze_request.mode == "deep"
            
            # Req 18.8: Truncate user_hint to 500 characters
            user_hint = analyze_request.user_hint
            if user_hint and len(user_hint) > 500:
                logger.debug(f"User hint truncated from {len(user_hint)} to 500 characters")
                user_hint = user_hint[:500]
            
            hybrid_result = hybrid_analyzer.analyze(
                build_info=build_info,
                parsed_log=parsed_log,
                test_results=test_results,
                git_analysis=git_analysis,
                console_log_snippet=log_snippet,
                jenkinsfile_content=jenkinsfile_content,
                library_sources=library_sources,
                deep=deep_mode,
                pr_url=analyze_request.pr_url,
                user_hint=user_hint,
            )
            
            # Check if analysis was skipped (Requirement 14)
            if hybrid_result.skipped:
                return AnalyzeResponse(
                    success=True,
                    job=analyze_request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason=hybrid_result.skip_reason,
                    analysis_mode=hybrid_result.mode.value,
                    correlation_id=correlation_id,
                )
            
            # Get the result
            result = hybrid_result.result
            analysis_mode = hybrid_result.mode.value
            iterations_used = hybrid_result.iterations_used
            tool_calls_made = hybrid_result.tool_calls_made
            source_files_fetched = hybrid_result.source_files_fetched
            
            logger.info(f"Analysis complete: mode={analysis_mode}, iterations={iterations_used}, tool_calls={tool_calls_made}")
            
            # Generate report if requested
            report_url = None
            if analyze_request.generate_report:
                generated = report_generator.generate(result, ["json", "markdown"])
                report_url = generated.get("markdown")
            
            # =====================================================================
            # Reporter Layer - Push results to developer workflows
            # =====================================================================
            
            jenkins_description_updated = False
            pr_comment_posted = False
            
            # 1. Update Jenkins build description
            if analyze_request.update_jenkins_description and config.reporter.update_jenkins_description:
                try:
                    description = jenkins_client.format_analysis_description(
                        root_cause=result.root_cause.summary,
                        category=result.failure_analysis.get("category", "UNKNOWN"),
                        tier=result.failure_analysis.get("tier", "unknown"),
                        confidence=result.failure_analysis.get("confidence", 0),
                        is_retriable=result.retry_assessment.is_retriable if result.retry_assessment else False,
                        recommendations=[r.action for r in result.recommendations[:3]]
                    )
                    jenkins_description_updated = jenkins_client.set_build_description(
                        analyze_request.job, build_number, description
                    )
                    if jenkins_description_updated:
                        logger.info(f"Updated Jenkins description for {analyze_request.job}#{build_number}")
                except Exception as e:
                    logger.warning(f"Failed to update Jenkins description: {e}")
            
            # 2. Post to PR/MR
            if analyze_request.post_to_pr and config.reporter.post_to_pr and scm_client:
                pr_info = None
                
                # Try to get PR info from request
                if analyze_request.pr_url:
                    pr_info = scm_client.extract_pr_info_from_url(analyze_request.pr_url)
                    if pr_info and analyze_request.pr_sha:
                        pr_info.sha = analyze_request.pr_sha
                
                if pr_info:
                    try:
                        # Format comment
                        comment = format_pr_comment(
                            job_name=analyze_request.job,
                            build_number=build_number,
                            build_url=build_info.url,
                            root_cause=result.root_cause.summary,
                            category=result.failure_analysis.get("category", "UNKNOWN"),
                            tier=result.failure_analysis.get("tier", "unknown"),
                            confidence=result.failure_analysis.get("confidence", 0),
                            is_retriable=result.retry_assessment.is_retriable if result.retry_assessment else False,
                            recommendations=[
                                {"priority": r.priority, "action": r.action, "rationale": r.rationale}
                                for r in result.recommendations
                            ],
                            affected_files=result.root_cause.affected_files
                        )
                        
                        # Post comment (update existing if configured)
                        if config.scm.update_existing:
                            pr_comment_posted = scm_client.update_or_create_comment(pr_info, comment)
                        else:
                            pr_comment_posted = scm_client.post_pr_comment(pr_info, comment)
                        
                        if pr_comment_posted:
                            logger.info(f"Posted analysis to PR {pr_info.owner}/{pr_info.repo}#{pr_info.pr_number}")
                        
                        # Set commit status
                        if config.scm.set_commit_status and pr_info.sha:
                            status_state = "failure" if not (result.retry_assessment and result.retry_assessment.is_retriable) else "pending"
                            scm_client.set_commit_status(
                                pr_info,
                                state=status_state,
                                description=result.root_cause.summary[:140],
                                context="jenkins-failure-analysis"
                            )
                    except Exception as e:
                        logger.warning(f"Failed to post PR comment: {e}")
            
            # 3. Send Slack notification if requested
            if analyze_request.notify_slack and config.notifications.slack.get("enabled"):
                background_tasks.add_task(
                    send_slack_notification,
                    config.notifications.slack,
                    result
                )
            
            # Store result
            result_key = f"{analyze_request.job}:{build_number}"
            result_dict = result_to_dict(result)
            analysis_results[result_key] = result_dict
            
            # DEBUG: Log what's in failure_analysis
            fa = result.failure_analysis
            logger.info(f"=== DEBUG: failure_analysis keys: {list(fa.keys()) if fa else 'None'}")
            if fa:
                if 'failing_tool' in fa:
                    logger.info(f"=== DEBUG: failing_tool: {fa['failing_tool'].get('tool_name', 'unknown')}")
                else:
                    logger.warning("=== DEBUG: NO failing_tool in failure_analysis")
                if 'tool_invocations' in fa:
                    logger.info(f"=== DEBUG: tool_invocations count: {len(fa['tool_invocations'])}")
                else:
                    logger.warning("=== DEBUG: NO tool_invocations in failure_analysis")
            
            # Build response with retry info
            retry_assessment = result.retry_assessment
            
            return {
                "success": True,
                "job": analyze_request.job,
                "build": build_number,
                "category": result.failure_analysis.get("category", "UNKNOWN"),
                "tier": result.failure_analysis.get("tier", "unknown"),
                "root_cause": result.root_cause.summary,
                "confidence": result.failure_analysis.get("confidence", 0),
                "is_retriable": retry_assessment.is_retriable if retry_assessment else False,
                "retry_reason": retry_assessment.reason if retry_assessment else "",
                "recommendations": [
                    {"priority": r.priority, "action": r.action, "rationale": r.rationale}
                    for r in result.recommendations
                ],
                "report_url": report_url,
                "jenkinsfile_fetched": jenkinsfile_content is not None,
                "libraries_fetched": list(fetch_result.libraries.keys()) if fetch_result else [],
                "jenkins_description_updated": jenkins_description_updated,
                "pr_comment_posted": pr_comment_posted,
                # Analysis mode info
                "analysis_mode": analysis_mode,
                "iterations_used": iterations_used,
                "tool_calls_made": tool_calls_made,
                "correlation_id": correlation_id,
                # Include full analysis data
                **result_to_dict(result)
            }
        
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Analysis failed")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/results/{job}/{build}")
    async def get_result(
        job: str,
        build: int,
        _: bool = Depends(verify_api_key)
    ):
        """Get cached analysis result for a build."""
        result_key = f"{job}:{build}"
        
        if result_key not in analysis_results:
            raise HTTPException(status_code=404, detail="Result not found")
        
        return analysis_results[result_key]
    
    @app.post("/webhook/jenkins")
    async def jenkins_webhook(
        payload: dict,
        background_tasks: BackgroundTasks,
        _: bool = Depends(verify_api_key)
    ):
        """
        Webhook endpoint for Jenkins notifications.
        
        Configure Jenkins to send POST requests to this endpoint on build completion.
        Supports Jenkins Notification Plugin format.
        """
        # Extract build info from webhook payload
        build = payload.get("build", {})
        
        # Only queue analysis for hard failures (not UNSTABLE)
        status = build.get("status") or build.get("phase")
        if status == "UNSTABLE":
            return {"status": "ignored", "reason": "UNSTABLE builds are not analyzed (FAILURE only)"}
        if status not in ["FAILURE", "FINALIZED"]:
            return {"status": "ignored", "reason": f"Build status: {status}"}
        
        # Check if this is a completed build
        if build.get("phase") == "FINALIZED" and build.get("status") not in ["FAILURE"]:
            return {"status": "ignored", "reason": "Build succeeded or UNSTABLE"}
        
        job_name = payload.get("name") or build.get("full_url", "").split("/job/")[-1].split("/")[0]
        build_number = build.get("number")
        
        if not job_name or not build_number:
            raise HTTPException(
                status_code=400,
                detail="Missing job name or build number"
            )
        
        # Confirm Jenkins result: only FAILURE (UNSTABLE is not analyzed)
        try:
            bi = jenkins_client.get_build_info(job_name, int(build_number))
            if bi.status == "UNSTABLE":
                return {"status": "ignored", "reason": "UNSTABLE builds are not analyzed"}
        except Exception as e:
            logger.warning("Webhook: could not verify build status for %s#%s: %s", job_name, build_number, e)
        
        # Queue analysis as background task
        background_tasks.add_task(
            run_background_analysis,
            job_name,
            build_number,
            jenkins_client,
            log_parser,
            ai_analyzer,
            git_analyzer,
            report_generator,
            config
        )
        
        return {
            "status": "queued",
            "job": job_name,
            "build": build_number
        }
    
    # =========================================================================
    # Source Registry API (Requirement 10)
    # =========================================================================
    
    @app.get("/sources")
    async def get_sources(api_key: str = Depends(verify_api_key)):
        """
        Get current Source Registry entries (Req 10.4).
        
        Returns list of source locations used for resolving needs_source requests.
        """
        registry = config.rc_analyzer.source_registry
        return {
            "sources": [
                {
                    "index": i,
                    "type": src.type,
                    "value": src.value,
                    "ref": src.ref,
                    "name": src.name,
                }
                for i, src in enumerate(registry)
            ],
            "count": len(registry)
        }
    
    @app.post("/sources")
    async def add_source(
        source: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Add a source location to the registry (Req 10.5).
        
        Request body:
        {
            "type": "repo" | "local_path",
            "value": "owner/repo[@ref]" | "/path/to/library",
            "name": "optional-label"
        }
        """
        from .config import SourceLocation
        
        source_type = source.get("type", "repo")
        value = source.get("value", "")
        name = source.get("name", "")
        ref = source.get("ref", "main")
        
        if not value:
            raise HTTPException(status_code=400, detail="Missing 'value' field")
        
        if source_type not in ("repo", "local_path", "inline"):
            raise HTTPException(status_code=400, detail="Invalid 'type' - must be repo, local_path, or inline")
        
        new_source = SourceLocation(
            type=source_type,
            value=value,
            ref=ref,
            name=name,
        )
        
        config.rc_analyzer.source_registry.append(new_source)
        
        return {
            "success": True,
            "index": len(config.rc_analyzer.source_registry) - 1,
            "source": {
                "type": source_type,
                "value": value,
                "ref": ref,
                "name": name,
            }
        }
    
    @app.delete("/sources/{index}")
    async def delete_source(
        index: int,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Remove a source location from the registry (Req 10.6).
        """
        registry = config.rc_analyzer.source_registry
        
        if index < 0 or index >= len(registry):
            raise HTTPException(status_code=404, detail=f"Source index {index} not found")
        
        removed = registry.pop(index)
        
        return {
            "success": True,
            "removed": {
                "type": removed.type,
                "value": removed.value,
                "name": removed.name,
            },
            "remaining": len(registry)
        }
    
    # =========================================================================
    # Feedback API (Requirement 15)
    # =========================================================================
    
    @app.post("/feedback")
    async def add_feedback(
        feedback: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Add feedback for an analysis (Req 15.3).
        
        Request body:
        {
            "job": "job-name",
            "build": 123,
            "confirmed_root_cause": "The actual root cause",
            "confirmed_fix": "The fix that was applied",
            "was_correct": true,  // optional, defaults based on match
            "ai_root_cause": "What AI said",  // optional
            "error_category": "GROOVY_LIBRARY",  // optional
            "error_snippet": "Error text...",  // optional
            "failed_stage": "Deploy",  // optional
            "failed_method": "deployService"  // optional
        }
        """
        from .feedback_store import FeedbackStore, FeedbackEntry
        
        store = FeedbackStore()
        
        # Determine was_correct if not provided
        was_correct = feedback.get("was_correct")
        if was_correct is None:
            ai_root_cause = feedback.get("ai_root_cause", "")
            confirmed = feedback.get("confirmed_root_cause", "")
            # Simple heuristic: correct if significant overlap
            was_correct = (
                ai_root_cause.lower()[:50] in confirmed.lower() or
                confirmed.lower()[:50] in ai_root_cause.lower()
            ) if ai_root_cause and confirmed else True
        
        entry = FeedbackEntry(
            job_name=feedback.get("job", ""),
            build_number=feedback.get("build", 0),
            error_category=feedback.get("error_category", ""),
            error_snippet=feedback.get("error_snippet", "")[:500],
            failed_stage=feedback.get("failed_stage", ""),
            failed_method=feedback.get("failed_method", ""),
            ai_root_cause=feedback.get("ai_root_cause", ""),
            confirmed_root_cause=feedback.get("confirmed_root_cause", ""),
            confirmed_fix=feedback.get("confirmed_fix", ""),
            was_correct=was_correct,
            feedback_source="user",
        )
        
        entry_id = store.add_feedback(entry)
        
        return {
            "success": True,
            "id": entry_id,
            "was_correct": was_correct,
        }
    
    @app.get("/feedback")
    async def get_feedback(
        category: str = None,
        limit: int = 50,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Get recent feedback entries (Req 15.4).
        
        Query params:
        - category: Filter by error category (e.g., GROOVY_LIBRARY)
        - limit: Max entries to return (default 50)
        """
        from .feedback_store import FeedbackStore
        
        store = FeedbackStore()
        entries = store.get_recent(limit=limit, category=category)
        
        return {
            "entries": [e.to_dict() for e in entries],
            "count": len(entries),
            "stats": store.get_stats(),
        }
    
    @app.get("/feedback/stats")
    async def get_feedback_stats(api_key: str = Depends(verify_api_key)):
        """
        Get feedback statistics - accuracy metrics over time.
        """
        from .feedback_store import FeedbackStore
        
        store = FeedbackStore()
        stats = store.get_stats()
        
        return {
            "total_feedback": stats.get("total_entries", 0),
            "correct_predictions": stats.get("correct_predictions", 0),
            "accuracy_percent": round(stats.get("accuracy", 0) * 100, 1),
            "by_category": stats.get("by_category", {}),
        }
    
    @app.get("/feedback/export")
    async def export_feedback(
        format: str = "jsonl",
        correct_only: bool = False,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Export feedback for model fine-tuning.
        
        Query params:
        - format: 'jsonl' (OpenAI format) or 'json' (raw)
        - correct_only: If true, only export confirmed correct analyses
        
        Returns JSONL format suitable for fine-tuning:
        {"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
        """
        from .feedback_store import FeedbackStore
        import json
        
        store = FeedbackStore()
        entries = store.get_recent(limit=1000)  # Get all for export
        
        if correct_only:
            entries = [e for e in entries if e.was_correct]
        
        if format == "jsonl":
            # OpenAI fine-tuning format
            lines = []
            for entry in entries:
                if not entry.error_snippet or not entry.confirmed_root_cause:
                    continue
                    
                training_example = {
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an expert Jenkins CI/CD failure analyst. Analyze build failures and provide root cause analysis in JSON format."
                        },
                        {
                            "role": "user", 
                            "content": f"Analyze this Jenkins build failure:\n\nJob: {entry.job_name}\nStage: {entry.failed_stage}\nError: {entry.error_snippet}"
                        },
                        {
                            "role": "assistant",
                            "content": json.dumps({
                                "root_cause": entry.confirmed_root_cause,
                                "category": entry.error_category,
                                "fix": entry.confirmed_fix,
                                "confidence": 0.9
                            })
                        }
                    ]
                }
                lines.append(json.dumps(training_example))
            
            from starlette.responses import Response
            return Response(
                content="\n".join(lines),
                media_type="application/jsonl",
                headers={"Content-Disposition": "attachment; filename=feedback_finetune.jsonl"}
            )
        else:
            # Raw JSON format
            return {
                "entries": [e.to_dict() for e in entries],
                "count": len(entries),
                "export_date": datetime.utcnow().isoformat(),
            }
    
    # =========================================================================
    # Knowledge API - Internal Tool Definitions
    # =========================================================================
    
    @app.get("/knowledge/tools")
    async def list_knowledge_tools(
        category: str = None,
        limit: int = 100,
        api_key: str = Depends(verify_api_key)
    ):
        """
        List all known internal tools.
        
        Query params:
        - category: Filter by category (deployment, build, test, etc.)
        - limit: Maximum results (default 100)
        """
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        tools = store.list_tools(category=category, limit=limit)
        
        return {
            "tools": [
                {
                    "id": t.id,
                    "name": t.name,
                    "category": t.category,
                    "description": t.description[:100] if t.description else "",
                    "errors_count": len(t.errors),
                    "added_by": t.added_by,
                    "confidence": t.confidence,
                }
                for t in tools
            ],
            "total": len(tools),
        }
    
    @app.get("/knowledge/tools/{tool_id_or_name}")
    async def get_knowledge_tool(
        tool_id_or_name: str,
        api_key: str = Depends(verify_api_key)
    ):
        """Get full tool definition by ID or name."""
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        
        # Try as ID first
        try:
            tool_id = int(tool_id_or_name)
            tool = store.get_tool(tool_id=tool_id)
        except ValueError:
            tool = store.get_tool(name=tool_id_or_name)
        
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        
        return {"tool": tool.to_dict()}
    
    @app.post("/knowledge/tools")
    async def add_knowledge_tool(
        tool_data: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Add a new tool definition.
        
        Request body can be:
        1. Full tool object (from UI review)
        2. YAML template string (from file import)
        """
        from .knowledge_store import get_knowledge_store, ToolDefinition
        
        store = get_knowledge_store()
        
        # Parse input
        if "yaml" in tool_data:
            tool = ToolDefinition.from_yaml(tool_data["yaml"])
        else:
            # Direct object format
            tool_obj = tool_data.get("tool", tool_data)
            tool = ToolDefinition(
                name=tool_obj.get("name", ""),
                aliases=tool_obj.get("aliases", []),
                version=tool_obj.get("version", ""),
                category=tool_obj.get("category", "utility"),
                description=tool_obj.get("description", ""),
                owner=tool_obj.get("owner", ""),
                docs_url=tool_obj.get("docs_url", ""),
                source_repo=tool_obj.get("source_repo", ""),
                patterns_commands=tool_obj.get("patterns", {}).get("commands", []),
                patterns_log_signatures=tool_obj.get("patterns", {}).get("log_signatures", []),
                patterns_env_vars=tool_obj.get("patterns", {}).get("env_vars", []),
                added_by=tool_obj.get("metadata", {}).get("added_by", "manual"),
                source_file=tool_obj.get("metadata", {}).get("source_file", ""),
                confidence=tool_obj.get("metadata", {}).get("confidence", 1.0),
            )
            
            # Parse arguments
            from .knowledge_store import ToolArgument, ToolError
            for arg_data in tool_obj.get("arguments", []):
                tool.arguments.append(ToolArgument.from_dict(arg_data))
            
            # Parse errors
            for err_data in tool_obj.get("errors", []):
                tool.errors.append(ToolError(
                    code=err_data.get("code", ""),
                    pattern=err_data.get("pattern", ""),
                    exit_code=err_data.get("exit_code"),
                    category=err_data.get("category", "UNKNOWN"),
                    description=err_data.get("description", ""),
                    fix=err_data.get("fix", ""),
                    retriable=err_data.get("retriable", False),
                ))
            
            # Parse dependencies
            deps = tool_obj.get("dependencies", {})
            tool.dependencies_tools = deps.get("tools", [])
            tool.dependencies_services = deps.get("services", [])
            tool.dependencies_credentials = deps.get("credentials", [])
        
        if not tool.name:
            raise HTTPException(status_code=400, detail="Tool name is required")
        
        try:
            tool_id = store.add_tool(tool)
            return {
                "success": True,
                "id": tool_id,
                "name": tool.name,
            }
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                raise HTTPException(status_code=409, detail=f"Tool '{tool.name}' already exists")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.put("/knowledge/tools/{tool_id}")
    async def update_knowledge_tool(
        tool_id: int,
        tool_data: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """Update an existing tool definition."""
        from .knowledge_store import get_knowledge_store, ToolDefinition, ToolArgument, ToolError
        
        store = get_knowledge_store()
        
        # Get existing tool
        existing = store.get_tool(tool_id=tool_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Tool not found")
        
        # Parse updated data (same as add)
        tool_obj = tool_data.get("tool", tool_data)
        tool = ToolDefinition(
            name=tool_obj.get("name", existing.name),
            aliases=tool_obj.get("aliases", existing.aliases),
            version=tool_obj.get("version", existing.version),
            category=tool_obj.get("category", existing.category),
            description=tool_obj.get("description", existing.description),
            owner=tool_obj.get("owner", existing.owner),
            docs_url=tool_obj.get("docs_url", existing.docs_url),
            source_repo=tool_obj.get("source_repo", existing.source_repo),
            patterns_commands=tool_obj.get("patterns", {}).get("commands", existing.patterns_commands),
            patterns_log_signatures=tool_obj.get("patterns", {}).get("log_signatures", existing.patterns_log_signatures),
            patterns_env_vars=tool_obj.get("patterns", {}).get("env_vars", existing.patterns_env_vars),
            added_by=existing.added_by,
            source_file=existing.source_file,
            confidence=tool_obj.get("metadata", {}).get("confidence", existing.confidence),
        )
        
        # Parse arguments
        for arg_data in tool_obj.get("arguments", []):
            tool.arguments.append(ToolArgument.from_dict(arg_data))
        
        # Parse errors
        for err_data in tool_obj.get("errors", []):
            tool.errors.append(ToolError(
                code=err_data.get("code", ""),
                pattern=err_data.get("pattern", ""),
                exit_code=err_data.get("exit_code"),
                category=err_data.get("category", "UNKNOWN"),
                description=err_data.get("description", ""),
                fix=err_data.get("fix", ""),
                retriable=err_data.get("retriable", False),
            ))
        
        # Parse dependencies
        deps = tool_obj.get("dependencies", {})
        tool.dependencies_tools = deps.get("tools", [])
        tool.dependencies_services = deps.get("services", [])
        tool.dependencies_credentials = deps.get("credentials", [])
        
        if store.update_tool(tool_id, tool):
            return {"success": True, "id": tool_id}
        else:
            raise HTTPException(status_code=500, detail="Update failed")
    
    @app.delete("/knowledge/tools/{tool_id}")
    async def delete_knowledge_tool(
        tool_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """Delete a tool definition."""
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        
        if store.delete_tool(tool_id):
            return {"success": True, "deleted_id": tool_id}
        else:
            raise HTTPException(status_code=404, detail="Tool not found")
    
    @app.get("/knowledge/identify")
    async def identify_knowledge_tool(
        query: str,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Identify tools matching a command or log line.
        
        Query params:
        - query: Command string or log snippet to match
        """
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        matches = store.identify_tool(query)
        
        return {
            "matches": [
                {
                    "tool_id": tool.id,
                    "name": tool.name,
                    "category": tool.category,
                    "confidence": round(confidence, 2),
                }
                for tool, confidence in matches[:5]
            ],
            "query": query,
        }
    
    @app.get("/knowledge/match-error")
    async def match_knowledge_error(
        snippet: str,
        tool: str = None,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Find known error patterns matching error text.
        
        Query params:
        - snippet: Error text to match
        - tool: Optional tool name to filter
        """
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        matches = store.match_error(snippet, tool_name=tool)
        
        return {
            "matches": [
                {
                    "tool": tool_def.name,
                    "error_code": error.code,
                    "category": error.category,
                    "description": error.description,
                    "fix": error.fix,
                    "retriable": error.retriable,
                    "confidence": round(confidence, 2),
                }
                for error, tool_def, confidence in matches[:5]
            ],
            "snippet": snippet[:100],
        }
    
    @app.get("/knowledge/stats")
    async def get_knowledge_stats(
        api_key: str = Depends(verify_api_key)
    ):
        """Get knowledge store statistics."""
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        return store.get_stats()
    
    @app.post("/knowledge/analyze-source")
    async def analyze_source_code(
        request: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Analyze Java source code to extract tool definition.
        
        Uses existing GitHubClient for authentication.
        
        Request body:
        {
            "repo_url": "https://github.company.com/team/a2l-cli.git",
            "branch": "main",
            "entry_point": "src/main/java/com/company/A2LCli.java",
            "depth": 2
        }
        
        Returns extracted tool definition for review before saving.
        """
        from .java_analyzer import JavaSourceAnalyzer, analyze_java_source
        
        repo_url = request.get("repo_url", "")
        branch = request.get("branch", "main")
        entry_point = request.get("entry_point")
        depth = min(max(request.get("depth", 2), 1), 3)  # Clamp 1-3
        
        if not repo_url:
            raise HTTPException(status_code=400, detail="repo_url is required")
        
        # Extract owner/repo from URL
        # Supports: https://github.com/owner/repo.git, git@github.com:owner/repo.git
        import re
        repo_match = re.search(r'[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?$', repo_url)
        if not repo_match:
            raise HTTPException(status_code=400, detail="Invalid repo_url format. Expected: https://github.com/owner/repo")
        
        repo = f"{repo_match.group(1)}/{repo_match.group(2)}"
        
        # Get GitHubClient (should be initialized in app startup)
        if not github_client:
            raise HTTPException(
                status_code=503, 
                detail="GitHub client not configured. Set github.base_url and github.token in config."
            )
        
        try:
            # Run analysis
            tool, result = analyze_java_source(
                github_client=github_client,
                repo=repo,
                branch=branch,
                entry_point=entry_point,
                depth=depth
            )
            
            # Log the analysis
            from .knowledge_store import get_knowledge_store, SourceAnalysisLog
            store = get_knowledge_store()
            
            log_entry = SourceAnalysisLog(
                repo_url=repo_url,
                branch=branch,
                entry_point=entry_point or "",
                depth=depth,
                files_analyzed=result.files_analyzed,
                tools_extracted=[],  # Not saved yet
                status="success" if result.confidence > 0.3 else "partial",
                error_message="" if not result.warnings else "; ".join(result.warnings[:3])
            )
            store.log_source_analysis(log_entry)
            
            return {
                "status": "extracted",
                "tool": tool.to_dict(),
                "analysis": {
                    "files_analyzed": result.files_analyzed,
                    "commands_found": len(result.commands),
                    "errors_found": len(result.errors),
                    "cli_framework": result.cli_framework,
                    "warnings": result.warnings,
                },
                "confidence": round(result.confidence, 2),
                "needs_review": True,
                "save_url": "/knowledge/tools",
            }
            
        except Exception as e:
            logger.exception(f"Source analysis failed: {e}")
            raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
    
    @app.get("/knowledge/analysis-history")
    async def get_analysis_history(
        limit: int = 20,
        api_key: str = Depends(verify_api_key)
    ):
        """Get recent source analysis history."""
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        history = store.get_analysis_history(limit=limit)
        
        return {
            "history": [h.to_dict() for h in history],
            "total": len(history),
        }
    
    @app.post("/knowledge/import-doc")
    async def import_documentation(
        request: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Import documentation from URL and extract tool information.
        
        Request body:
        {
            "url": "https://wiki.company.com/tools/a2l",
            "tool_name": "a2l",  // Optional - link to existing tool
            "extract_errors": true,  // Optional - extract error patterns
            "save": false  // Optional - save doc to knowledge store
        }
        
        Returns extracted information for review.
        """
        from .doc_importer import DocImporter
        from .knowledge_store import get_knowledge_store
        
        url = request.get("url", "")
        tool_name = request.get("tool_name")
        extract_errors = request.get("extract_errors", True)
        save_doc = request.get("save", True)  # Default to save
        save_tool = request.get("save_tool", True)  # Default to save tool
        link_doc_id = request.get("link_doc_id")  # Optional: link existing doc to new tool
        
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        
        try:
            importer = DocImporter(verify_ssl=config.verify_ssl)
            doc, info = importer.import_url(url, tool_name, extract_info=extract_errors)
            
            if not doc:
                raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {url}")
            
            store = get_knowledge_store()
            
            response = {
                "status": "imported",
                "doc": {
                    "title": doc.title,
                    "content_type": doc.content_type,
                    "content_length": len(doc.content),
                    "source_url": doc.source_url,
                },
            }
            
            if info:
                response["extracted"] = {
                    "description": info.description[:300] if info.description else "",
                    "commands": info.commands[:10],
                    "errors": info.errors[:10],
                    "env_vars": info.env_vars[:10],
                    "arguments": info.arguments[:10],
                    "examples_count": len(info.examples),
                    "confidence": round(info.confidence, 2),
                }
                
                # Try to determine tool name if not provided
                effective_tool_name = tool_name
                if not effective_tool_name:
                    # Try to extract from first command
                    if info.commands and info.commands[0].get("name"):
                        effective_tool_name = info.commands[0]["name"]
                        response["tool_name_source"] = "auto_detected_from_commands"
                    # Or from document title (first word if it looks like a tool name)
                    elif doc.title:
                        first_word = doc.title.split()[0].lower() if doc.title.split() else ""
                        # Only use if it looks like a tool name (lowercase, no spaces, reasonable length)
                        if first_word and len(first_word) <= 20 and first_word.replace("-", "").replace("_", "").isalnum():
                            effective_tool_name = first_word
                            response["tool_name_source"] = "auto_detected_from_title"
                
                # Generate and optionally save tool definition
                if effective_tool_name:
                    tool = importer.to_tool_definition(info, effective_tool_name, url)
                    
                    if save_tool:
                        # Use add_or_merge to handle existing tools
                        tool_id, was_merged = store.add_or_merge_tool(tool)
                        saved_tool = store.get_tool(tool_id=tool_id)
                        response["tool"] = saved_tool.to_dict() if saved_tool else tool.to_dict()
                        response["tool"]["id"] = tool_id
                        response["tool_saved"] = True
                        response["tool_merged"] = was_merged
                        
                        # Link doc to tool
                        doc.tool_id = tool_id
                        
                        # Also link existing doc if specified (for "Create Tool from Doc" flow)
                        if link_doc_id:
                            store.update_doc_tool_id(link_doc_id, tool_id)
                            response["linked_doc_id"] = link_doc_id
                    else:
                        response["tool"] = tool.to_dict()
                        response["tool_saved"] = False
                else:
                    # No tool name - doc saved but no tool created
                    response["tool_saved"] = False
                    response["tool_name_required"] = True
                    response["hint"] = "Provide a tool_name to create a tool from this documentation"
            
            # Save doc if requested
            if save_doc:
                doc_id = store.add_doc(doc)
                response["doc"]["id"] = doc_id
                response["doc_saved"] = True
            else:
                response["doc_saved"] = False
            
            return response
            
        except requests.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {str(e)}")
        except Exception as e:
            logger.exception(f"Doc import failed: {e}")
            raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    
    @app.get("/knowledge/docs")
    async def list_knowledge_docs(
        tool_id: int = None,
        search: str = None,
        limit: int = 50,
        api_key: str = Depends(verify_api_key)
    ):
        """
        List imported documentation.
        
        Query params:
        - tool_id: Filter by linked tool
        - search: Search in content
        - limit: Max results
        """
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        
        if tool_id:
            docs = store.get_docs_for_tool(tool_id)
        elif search:
            docs = store.search_docs(search, limit=limit)
        else:
            # Get recent docs (would need new method, for now use search)
            docs = store.search_docs("", limit=limit)
        
        return {
            "docs": [
                {
                    "id": d.id,
                    "title": d.title,
                    "source_url": d.source_url,
                    "content_type": d.content_type,
                    "tool_id": d.tool_id,
                    "extracted_info": d.extracted_info,
                    "created_at": d.created_at,
                }
                for d in docs
            ],
            "total": len(docs),
        }
    
    @app.delete("/knowledge/docs/{doc_id}")
    async def delete_knowledge_doc(
        doc_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Delete an imported document.
        
        Args:
            doc_id: Document ID to delete
        """
        from .knowledge_store import get_knowledge_store
        
        store = get_knowledge_store()
        success = store.delete_doc(doc_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
        
        return {"status": "deleted", "id": doc_id}
    
    # =========================================================================
    # Training Pipeline API
    # =========================================================================
    
    @app.post("/training/jobs")
    async def create_training_job(
        request: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Create a new training data preparation job.
        
        Request body:
        {
            "name": "finetune-v1",
            "description": "First fine-tuning dataset",
            "include_feedback": true,
            "include_knowledge": true,
            "min_quality_score": 0.5,
            "format": "jsonl_openai"  // jsonl_openai, jsonl_anthropic, csv, json
        }
        """
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        
        name = request.get("name", f"job_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}")
        
        job_id = pipeline.create_job(
            name=name,
            description=request.get("description", ""),
            include_feedback=request.get("include_feedback", True),
            include_knowledge=request.get("include_knowledge", True),
            min_quality_score=request.get("min_quality_score", 0.5),
            format=request.get("format", "jsonl_openai"),
        )
        
        return {
            "success": True,
            "job_id": job_id,
            "name": name,
            "next_step": f"POST /training/jobs/{job_id}/prepare",
        }
    
    @app.get("/training/jobs")
    async def list_training_jobs(
        limit: int = 50,
        api_key: str = Depends(verify_api_key)
    ):
        """List training jobs."""
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        jobs = pipeline.list_jobs(limit=limit)
        
        return {
            "jobs": [j.to_dict() for j in jobs],
            "total": len(jobs),
        }
    
    @app.get("/training/jobs/{job_id}")
    async def get_training_job(
        job_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """Get training job details."""
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        job = pipeline.get_job(job_id)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return {"job": job.to_dict()}
    
    @app.post("/training/jobs/{job_id}/prepare")
    async def prepare_training_job(
        job_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Prepare training data for a job.
        
        Imports data from feedback and knowledge stores.
        """
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        
        success = pipeline.prepare_job(job_id)
        
        if not success:
            job = pipeline.get_job(job_id)
            raise HTTPException(
                status_code=500, 
                detail=job.error_message if job else "Preparation failed"
            )
        
        job = pipeline.get_job(job_id)
        
        return {
            "success": True,
            "job_id": job_id,
            "status": job.status,
            "total_examples": job.total_examples,
            "valid_examples": job.valid_examples,
            "next_step": f"POST /training/jobs/{job_id}/export",
        }
    
    @app.post("/training/jobs/{job_id}/export")
    async def export_training_job(
        job_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Export training data for a job.
        
        Returns the filepath to the exported file.
        """
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        
        filepath = pipeline.export_job(job_id)
        
        if not filepath:
            job = pipeline.get_job(job_id)
            raise HTTPException(
                status_code=500,
                detail=job.error_message if job else "Export failed"
            )
        
        job = pipeline.get_job(job_id)
        
        return {
            "success": True,
            "job_id": job_id,
            "status": job.status,
            "exported_path": filepath,
            "download_url": f"/training/jobs/{job_id}/download",
        }
    
    @app.get("/training/jobs/{job_id}/download")
    async def download_training_data(
        job_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """Download exported training data file."""
        from .training_pipeline import get_training_pipeline
        from starlette.responses import FileResponse
        
        pipeline = get_training_pipeline()
        job = pipeline.get_job(job_id)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if not job.exported_path:
            raise HTTPException(status_code=400, detail="Job not yet exported")
        
        filepath = Path(job.exported_path)
        if not filepath.exists():
            raise HTTPException(status_code=404, detail="Export file not found")
        
        return FileResponse(
            path=str(filepath),
            filename=filepath.name,
            media_type="application/octet-stream",
        )
    
    @app.get("/training/stats")
    async def get_training_stats(
        api_key: str = Depends(verify_api_key)
    ):
        """Get training pipeline statistics."""
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        return pipeline.get_stats()
    
    @app.get("/training/examples")
    async def list_training_examples(
        page: int = 1,
        page_size: int = 20,
        source: Optional[str] = None,
        validated_only: bool = False,
        api_key: str = Depends(verify_api_key),
    ):
        """
        List training examples (paginated).

        Query: ``page`` (1-based), ``page_size`` (max 200), optional ``source``,
        ``validated_only``.
        """
        from .training_pipeline import get_training_pipeline

        pipeline = get_training_pipeline()
        examples, total = pipeline.get_examples_page(
            page=page,
            page_size=page_size,
            source=source,
            validated_only=validated_only,
        )
        return {
            "examples": [e.to_dict() for e in examples],
            "total": total,
            "page": max(1, page),
            "page_size": min(200, max(1, page_size)),
        }
    
    @app.get("/training/examples/{example_id}")
    async def get_training_example(
        example_id: int,
        api_key: str = Depends(verify_api_key),
    ):
        """Get one training example by id."""
        from .training_pipeline import get_training_pipeline

        pipeline = get_training_pipeline()
        ex = pipeline.get_example_by_id(example_id)
        if not ex:
            raise HTTPException(status_code=404, detail="Example not found")
        return {"example": ex.to_dict()}
    
    @app.patch("/training/examples/{example_id}")
    async def patch_training_example(
        example_id: int,
        request: dict,
        api_key: str = Depends(verify_api_key),
    ):
        """
        Update fields on a training example (partial body).

        Allowed keys: job_name, error_category, error_snippet, failed_stage,
        failed_method, tool_name, root_cause, fix, category, confidence,
        is_retriable, is_validated, validation_notes.
        """
        from .training_pipeline import get_training_pipeline

        pipeline = get_training_pipeline()
        updated = pipeline.update_example(example_id, request)
        if updated is None:
            existing = pipeline.get_example_by_id(example_id)
            if not existing:
                raise HTTPException(status_code=404, detail="Example not found")
            raise HTTPException(
                status_code=409,
                detail="Update rejected (e.g. duplicate content hash after edit)",
            )
        return {"success": True, "example": updated.to_dict()}
    
    @app.delete("/training/examples/{example_id}")
    async def delete_training_example(
        example_id: int,
        api_key: str = Depends(verify_api_key),
    ):
        """Delete one training example."""
        from .training_pipeline import get_training_pipeline

        pipeline = get_training_pipeline()
        if not pipeline.delete_example(example_id):
            raise HTTPException(status_code=404, detail="Example not found")
        return {"success": True, "deleted_id": example_id}
    
    @app.post("/training/import")
    async def import_training_data(
        request: dict,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Manually import training data from sources.
        
        Request body:
        {
            "source": "feedback" | "knowledge" | "both"
        }
        """
        from .training_pipeline import get_training_pipeline
        
        pipeline = get_training_pipeline()
        source = request.get("source", "both")
        
        results = {}
        
        if source in ["feedback", "both"]:
            results["feedback_imported"] = pipeline.import_from_feedback()
        
        if source in ["knowledge", "both"]:
            results["knowledge_imported"] = pipeline.import_from_knowledge()
        
        return {
            "success": True,
            **results,
        }
    
    @app.post("/training/restore")
    async def restore_training_export(
        file: UploadFile = File(...),
        source: str = Form("import"),
        api_key: str = Depends(verify_api_key),
    ):
        """
        Restore training examples from a previously exported file (disaster recovery).

        Accepts multipart form:

        - ``file``: JSON bundle (``format=json`` export) or JSONL (``jsonl_openai`` / ``jsonl_ollama``)
        - ``source``: optional label stored on each row (default ``import``)

        Returns counts: ``added``, ``skipped`` (duplicates), ``format_detected``, ``parse_errors``.
        """
        from .training_pipeline import get_training_pipeline, MAX_TRAINING_IMPORT_BYTES

        pipeline = get_training_pipeline()
        data = await file.read()
        if len(data) > MAX_TRAINING_IMPORT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {MAX_TRAINING_IMPORT_BYTES} bytes)",
            )
        try:
            result = pipeline.import_from_export_bytes(
                data,
                filename=file.filename or "",
                source=source,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        return {
            "success": True,
            "filename": file.filename,
            **result,
        }
    
    # =========================================================================
    # SPLUNK INTEGRATION ENDPOINTS
    # =========================================================================
    
    @app.get("/splunk/status")
    async def get_splunk_status(api_key: str = Depends(verify_api_key)):
        """Get Splunk integration status."""
        from .splunk_connector import get_splunk_connector, reset_splunk_connector
        
        # Reset singleton to pick up any env changes
        reset_splunk_connector()
        
        connector = get_splunk_connector()
        if not connector:
            return {
                "success": False,
                "enabled": False, 
                "message": "Splunk integration not configured (SPLUNK_ENABLED=false or missing config)"
            }
        
        return connector.test_connection()
    
    @app.get("/splunk/test-search")
    async def test_splunk_search(
        minutes: int = 15,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Run a minimal test search to debug Splunk connectivity.
        
        This runs the simplest possible query to verify:
        1. Job creation works
        2. Polling works  
        3. Results retrieval works
        
        Check container logs for detailed debug output including curl commands.
        """
        from .splunk_connector import get_splunk_connector
        
        connector = get_splunk_connector()
        if not connector:
            raise HTTPException(status_code=400, detail="Splunk integration not enabled")
        
        return connector.test_simple_search(minutes=minutes)
    
    @app.post("/splunk/sync")
    async def sync_splunk_failures(
        minutes: int = None,
        analyze: bool = True,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Sync failed builds from Splunk.
        
        Args:
            minutes: Look back N minutes (default: SPLUNK_SYNC_INTERVAL_MINS)
            analyze: Run AI analysis on each failure
        """
        from .splunk_connector import get_splunk_connector
        from .review_queue import get_review_queue
        
        connector = get_splunk_connector()
        if not connector:
            raise HTTPException(status_code=400, detail="Splunk integration not enabled")
        
        # Get failed builds with logs
        failures = connector.get_failed_builds_with_logs(minutes)
        
        if not failures:
            return {"synced": 0, "message": "No failed builds found"}
        
        queue = get_review_queue()
        results = []
        
        for failure in failures:
            # Skip if already in queue
            if queue.exists(failure.host, failure.job_id):
                continue
            
            analysis_result = None
            if analyze and failure.log_snippet:
                try:
                    analysis_result = ai_analyzer.analyze_snippet(
                        failure.log_snippet,
                        job_name=failure.job_name,
                        log_parser_config=vars(config.parsing),
                        from_splunk_console=True,
                        agent_config=config,
                        github_client=github_client,
                    )
                except Exception as e:
                    logger.error(f"Analysis failed for {failure.job_name}#{failure.job_id}: {e}")
            
            ai_fix_text = ""
            if analysis_result:
                ai_fix_text = (analysis_result.root_cause.fix or "").strip()
                if not ai_fix_text and analysis_result.recommendations:
                    ai_fix_text = (analysis_result.recommendations[0].action or "").strip()
            
            # Add to review queue
            item = queue.add(
                host=failure.host,
                job_name=failure.job_name,
                job_id=failure.job_id,
                log_snippet=failure.log_snippet,
                ai_root_cause=analysis_result.root_cause.summary if analysis_result else "",
                ai_fix=ai_fix_text,
                ai_confidence=analysis_result.root_cause.confidence if analysis_result else 0.0,
                ai_category=analysis_result.root_cause.category if analysis_result else "",
            )
            results.append(item.to_dict())
        
        return {
            "synced": len(results),
            "total_failures": len(failures),
            "items": results,
        }
    
    @app.get("/splunk/failures")
    async def get_splunk_failures(
        minutes: int = None,
        api_key: str = Depends(verify_api_key)
    ):
        """Get failed builds from Splunk (without syncing to queue)."""
        from .splunk_connector import get_splunk_connector
        
        connector = get_splunk_connector()
        if not connector:
            raise HTTPException(status_code=400, detail="Splunk integration not enabled")
        
        failures = connector.get_failed_builds(minutes)
        
        return {
            "failures": [f.to_dict() for f in failures],
            "total": len(failures),
        }
    
    # =========================================================================
    # REVIEW QUEUE ENDPOINTS
    # =========================================================================
    
    @app.get("/review-queue")
    async def get_review_queue_items(
        status: str = None,
        limit: int = 50,
        api_key: str = Depends(verify_api_key)
    ):
        """Get items in review queue."""
        from .review_queue import get_review_queue
        
        queue = get_review_queue()
        items = queue.list(status=status, limit=limit)
        stats = queue.get_stats()
        
        return {
            "items": [item.to_dict() for item in items],
            "total": len(items),
            "stats": stats,
        }
    
    @app.get("/review-queue/{item_id}")
    async def get_review_queue_item(
        item_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """Get single review queue item."""
        from .review_queue import get_review_queue
        
        queue = get_review_queue()
        item = queue.get(item_id)
        
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        return {"item": item.to_dict()}
    
    @app.post("/review-queue/{item_id}/approve")
    async def approve_review_item(
        item_id: int,
        request: dict = {},
        api_key: str = Depends(verify_api_key)
    ):
        """
        Approve a review queue item.
        
        Optional request body:
        - root_cause: Override AI root cause
        - fix: Override AI fix
        - category: Override AI category
        """
        from .review_queue import get_review_queue, ReviewStatus
        
        queue = get_review_queue()
        item = queue.get(item_id)
        
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        # Update with overrides if provided
        root_cause = request.get("root_cause", item.ai_root_cause)
        fix = request.get("fix", item.ai_fix)
        category = request.get("category", item.ai_category)
        
        # Mark as approved
        queue.update_status(
            item_id,
            ReviewStatus.APPROVED,
            confirmed_root_cause=root_cause,
            confirmed_fix=fix,
            confirmed_category=category,
        )
        
        # Add to training examples
        from .training_pipeline import get_training_pipeline
        pipeline = get_training_pipeline()
        pipeline.add_from_review(
            job_name=item.job_name,
            build_number=item.job_id,
            log_snippet=item.log_snippet,
            root_cause=root_cause,
            fix=fix,
            category=category,
        )
        
        return {"status": "approved", "item_id": item_id}
    
    @app.post("/review-queue/{item_id}/reject")
    async def reject_review_item(
        item_id: int,
        request: dict = {},
        api_key: str = Depends(verify_api_key)
    ):
        """Reject a review queue item (not useful for training)."""
        from .review_queue import get_review_queue, ReviewStatus
        
        queue = get_review_queue()
        item = queue.get(item_id)
        
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        
        reason = request.get("reason", "")
        queue.update_status(item_id, ReviewStatus.REJECTED, notes=reason)
        
        return {"status": "rejected", "item_id": item_id}
    
    @app.delete("/review-queue/{item_id}")
    async def delete_review_item(
        item_id: int,
        api_key: str = Depends(verify_api_key)
    ):
        """Delete a review queue item."""
        from .review_queue import get_review_queue
        
        queue = get_review_queue()
        success = queue.delete(item_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Item not found")
        
        return {"status": "deleted", "item_id": item_id}
    
    return app


async def run_background_analysis(
    job: str,
    build: int,
    jenkins: JenkinsClient,
    parser: LogParser,
    ai: AIAnalyzer,
    git: Optional[GitAnalyzer],
    reporter: ReportGenerator,
    config: Config
):
    """Run analysis in background."""
    try:
        logger.info(f"Starting background analysis for {job}#{build}")
        
        # Perform analysis
        build_info = jenkins.get_build_info(job, build)
        if build_info.status == "UNSTABLE":
            logger.info("Background analysis skipped: build %s#%s is UNSTABLE", job, build)
            return
        console_log = jenkins.get_console_log(job, build)
        parsed_log = parser.parse(console_log)
        test_results = jenkins.get_test_results(job, build)
        
        log_snippet = parser.get_error_snippet(parsed_log, max_errors=10)
        
        result = ai.analyze(
            build_info=build_info,
            parsed_log=parsed_log,
            test_results=test_results,
            console_log_snippet=log_snippet
        )
        
        # Generate reports
        reporter.generate(result, ["json", "markdown"])
        
        # Send notification
        if config.notifications.slack.get("enabled"):
            await send_slack_notification(config.notifications.slack, result)
        
        logger.info(f"Completed background analysis for {job}#{build}")
        
    except Exception as e:
        logger.exception(f"Background analysis failed for {job}#{build}: {e}")


async def send_slack_notification(slack_config: dict, result):
    """Send Slack notification with analysis results."""
    import aiohttp
    
    webhook_url = slack_config.get("webhook_url")
    if not webhook_url:
        return
    
    message = format_slack_message(result)
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=message) as response:
                if response.status != 200:
                    logger.error(f"Slack notification failed: {await response.text()}")
    except Exception as e:
        logger.error(f"Slack notification error: {e}")
