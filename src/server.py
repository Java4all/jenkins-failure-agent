"""
FastAPI server for Jenkins Failure Analysis Agent.
Provides HTTP endpoints for integration with Jenkins webhooks.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
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
        version="1.4.0"
    )
    
    # CORS middleware - allow all for UI access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
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
        request: AnalyzeRequest,
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
            # Determine build number
            build_number = request.build
            if request.latest_failed or not build_number:
                # Find latest failed build
                build_number = jenkins_client.get_latest_failed_build(request.job)
                if not build_number:
                    raise HTTPException(
                        status_code=404,
                        detail="No failed builds found for this job"
                    )
            
            # Get build info
            build_info = jenkins_client.get_build_info(request.job, build_number)
            
            # =========================================================
            # Requirement 14.1: Check build status BEFORE log parsing
            # =========================================================
            
            # Req 14.3: Build still in progress
            if build_info.building:
                logger.info(f"Build {request.job}#{build_number} is still running - skipping analysis")
                return AnalyzeResponse(
                    success=True,
                    job=request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason="Build is still in progress",
                    analysis_mode="none",
                )
            
            # Req 14.2: Build succeeded
            if build_info.status == "SUCCESS":
                logger.info(f"Build {request.job}#{build_number} succeeded - no failure to analyze")
                return AnalyzeResponse(
                    success=True,
                    job=request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason="Build succeeded",
                    analysis_mode="none",
                )
            
            # Req 14.4: Build was aborted
            if build_info.status == "ABORTED":
                logger.info(f"Build {request.job}#{build_number} was aborted - skipping analysis")
                return AnalyzeResponse(
                    success=True,
                    job=request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason="Build was manually aborted",
                    analysis_mode="none",
                )
            
            # =========================================================
            # Only fetch and parse logs for FAILURE or UNSTABLE builds
            # =========================================================
            
            # Fetch console log
            console_log = jenkins_client.get_console_log(request.job, build_number)
            
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
            test_results = jenkins_client.get_test_results(request.job, build_number)
            
            # Git analysis (if workspace provided)
            git_analysis = None
            if git_analyzer and request.workspace:
                try:
                    git_analysis = git_analyzer.analyze(request.workspace)
                except Exception as e:
                    logger.warning(f"Git analysis failed: {e}")
            
            # Fetch source code from GitHub
            jenkinsfile_content = None
            library_sources = {}
            fetch_result = None
            
            if github_client:
                try:
                    # Determine project repo and ref
                    project_repo = request.project_repo
                    project_ref = request.project_ref or "main"
                    
                    # Try to infer repo from job name if not provided
                    if not project_repo:
                        # Check if we have a mapping in config
                        project_mappings = getattr(config.github, 'project_mappings', {})
                        if request.job in project_mappings:
                            project_repo = project_mappings[request.job]
                    
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
            deep_mode = request.mode == "deep"
            
            # Req 18.8: Truncate user_hint to 500 characters
            user_hint = request.user_hint
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
                pr_url=request.pr_url,
                user_hint=user_hint,
            )
            
            # Check if analysis was skipped (Requirement 14)
            if hybrid_result.skipped:
                return AnalyzeResponse(
                    success=True,
                    job=request.job,
                    build=build_number,
                    status="no_analysis_needed",
                    skip_reason=hybrid_result.skip_reason,
                    analysis_mode=hybrid_result.mode.value,
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
            if request.generate_report:
                generated = report_generator.generate(result, ["json", "markdown"])
                report_url = generated.get("markdown")
            
            # =====================================================================
            # Reporter Layer - Push results to developer workflows
            # =====================================================================
            
            jenkins_description_updated = False
            pr_comment_posted = False
            
            # 1. Update Jenkins build description
            if request.update_jenkins_description and config.reporter.update_jenkins_description:
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
                        request.job, build_number, description
                    )
                    if jenkins_description_updated:
                        logger.info(f"Updated Jenkins description for {request.job}#{build_number}")
                except Exception as e:
                    logger.warning(f"Failed to update Jenkins description: {e}")
            
            # 2. Post to PR/MR
            if request.post_to_pr and config.reporter.post_to_pr and scm_client:
                pr_info = None
                
                # Try to get PR info from request
                if request.pr_url:
                    pr_info = scm_client.extract_pr_info_from_url(request.pr_url)
                    if pr_info and request.pr_sha:
                        pr_info.sha = request.pr_sha
                
                if pr_info:
                    try:
                        # Format comment
                        comment = format_pr_comment(
                            job_name=request.job,
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
            if request.notify_slack and config.notifications.slack.get("enabled"):
                background_tasks.add_task(
                    send_slack_notification,
                    config.notifications.slack,
                    result
                )
            
            # Store result
            result_key = f"{request.job}:{build_number}"
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
                "job": request.job,
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
        
        # Only process failures
        status = build.get("status") or build.get("phase")
        if status not in ["FAILURE", "UNSTABLE", "FINALIZED"]:
            return {"status": "ignored", "reason": f"Build status: {status}"}
        
        # Check if this is a completed build
        if build.get("phase") == "FINALIZED" and build.get("status") not in ["FAILURE", "UNSTABLE"]:
            return {"status": "ignored", "reason": "Build succeeded"}
        
        job_name = payload.get("name") or build.get("full_url", "").split("/job/")[-1].split("/")[0]
        build_number = build.get("number")
        
        if not job_name or not build_number:
            raise HTTPException(
                status_code=400,
                detail="Missing job name or build number"
            )
        
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
