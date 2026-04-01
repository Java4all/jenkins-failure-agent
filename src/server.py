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
    # Analysis mode options
    deep: bool = False  # Force agentic/deep investigation mode
    scripted_only: bool = False  # Force scripted-only mode (no agentic)
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
    category: str
    tier: str  # 3-tier classification
    root_cause: str
    confidence: float
    is_retriable: bool
    retry_reason: str
    recommendations: list
    report_url: Optional[str] = None
    # Source code fetch info
    jenkinsfile_fetched: bool = False
    libraries_fetched: list = []
    # Reporter status
    jenkins_description_updated: bool = False
    pr_comment_posted: bool = False
    # Analysis mode info
    analysis_mode: str = "scripted"  # scripted, agentic, or hybrid
    agentic_enhanced: bool = False
    tool_calls_made: int = 0


class HealthResponse(BaseModel):
    """Response for health check endpoint."""
    status: str
    jenkins_connected: bool
    ai_connected: bool
    github_connected: bool = False
    scm_connected: bool = False
    timestamp: str


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
            
            if build_info.building:
                raise HTTPException(
                    status_code=400,
                    detail="Build is still in progress"
                )
            
            # Fetch console log
            console_log = jenkins_client.get_console_log(request.job, build_number)
            
            # Parse logs
            parsed_log = log_parser.parse(console_log)
            
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
            
            # Use hybrid analyzer for scripted + optional agentic investigation
            hybrid_result = hybrid_analyzer.analyze(
                build_info=build_info,
                parsed_log=parsed_log,
                test_results=test_results,
                git_analysis=git_analysis,
                console_log_snippet=log_snippet,
                jenkinsfile_content=jenkinsfile_content,
                library_sources=library_sources,
                force_agentic=request.deep,
                force_scripted=request.scripted_only,
                pr_url=request.pr_url,
            )
            
            # Get the merged result
            result = hybrid_result.merged_result
            analysis_mode = hybrid_result.mode.value
            agentic_enhanced = hybrid_result.agentic_enhanced
            tool_calls_made = hybrid_result.tool_calls_made
            
            logger.info(f"Analysis complete: mode={analysis_mode}, agentic_enhanced={agentic_enhanced}")
            
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
            analysis_results[result_key] = result_to_dict(result)
            
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
                "agentic_enhanced": agentic_enhanced,
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
