#!/usr/bin/env python3
"""
Jenkins Failure Analysis Agent
Main entry point for CLI and server modes.

Supports two analysis modes:
- Scripted (default): Fast, single LLM call
- Deep/Agentic: Multi-step investigation with MCP tools (--deep flag)
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.config import load_config, Config
from src.jenkins_client import JenkinsClient
from src.log_parser import LogParser
from src.git_analyzer import GitAnalyzer
from src.ai_analyzer import AIAnalyzer, result_to_dict
from src.hybrid_analyzer import HybridAnalyzer, AnalysisMode
from src.report_generator import ReportGenerator, format_slack_message

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("jenkins-agent")

console = Console()


def setup_logging(config: Config):
    """Setup logging from configuration."""
    log_config = config.logging
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    
    # Update root logger
    logging.getLogger().setLevel(level)
    
    # Add file handler if configured
    log_file = log_config.get("file")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter(log_config.get("format", "%(asctime)s - %(message)s"))
        )
        logging.getLogger().addHandler(file_handler)


@click.group()
@click.option("--config", "-c", "config_path", help="Path to config file")
@click.pass_context
def cli(ctx, config_path: Optional[str]):
    """Jenkins Failure Analysis Agent - AI-powered build debugging assistant."""
    ctx.ensure_object(dict)
    
    try:
        ctx.obj["config"] = load_config(config_path)
        setup_logging(ctx.obj["config"])
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print("Run [cyan]python agent.py init[/cyan] to create a config file.")
        sys.exit(1)


@cli.command()
@click.option("--job", "-j", required=True, help="Jenkins job name")
@click.option("--build", "-b", type=int, help="Build number (default: latest failed)")
@click.option("--latest-failed", is_flag=True, help="Analyze latest failed build")
@click.option("--output", "-o", help="Output directory for reports")
@click.option("--format", "-f", "formats", multiple=True, 
              type=click.Choice(["json", "markdown", "html"]),
              help="Report formats to generate")
@click.option("--no-git", is_flag=True, help="Skip git analysis")
@click.option("--workspace", "-w", help="Path to workspace/repo for git analysis")
@click.option("--deep", is_flag=True, help="Enable deep agentic investigation (slower but more thorough)")
@click.option("--scripted-only", is_flag=True, help="Use scripted analysis only (no agentic)")
@click.pass_context
def analyze(
    ctx, 
    job: str, 
    build: Optional[int], 
    latest_failed: bool,
    output: Optional[str],
    formats: tuple,
    no_git: bool,
    workspace: Optional[str],
    deep: bool,
    scripted_only: bool,
):
    """Analyze a Jenkins build failure."""
    config: Config = ctx.obj["config"]
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        # Connect to Jenkins
        task = progress.add_task("Connecting to Jenkins...", total=None)
        jenkins = JenkinsClient(config.jenkins)
        
        if not jenkins.test_connection():
            console.print("[red]Error:[/red] Cannot connect to Jenkins")
            sys.exit(1)
        
        # Get build info
        progress.update(task, description="Fetching build information...")
        
        try:
            if build:
                build_info = jenkins.get_build_info(job, build)
            else:
                build_info = jenkins.get_latest_build(job, status="FAILURE" if latest_failed else None)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)
        
        console.print(Panel(
            f"[bold]Job:[/bold] {build_info.job_name}\n"
            f"[bold]Build:[/bold] #{build_info.build_number}\n"
            f"[bold]Status:[/bold] {build_info.status}\n"
            f"[bold]Duration:[/bold] {build_info.duration_str}",
            title="Build Information"
        ))
        
        # Fetch console log
        progress.update(task, description="Fetching console log...")
        console_log = jenkins.get_console_log(job, build_info.build_number)
        
        # Parse logs
        progress.update(task, description="Parsing logs...")
        parser = LogParser(vars(config.parsing))
        parsed_log = parser.parse(console_log)
        
        console.print(f"Found [yellow]{len(parsed_log.errors)}[/yellow] errors, "
                      f"[yellow]{len(parsed_log.stack_traces)}[/yellow] stack traces")
        
        if parsed_log.failed_stage:
            console.print(f"Failed stage: [red]{parsed_log.failed_stage}[/red]")
        
        # Get test results
        progress.update(task, description="Fetching test results...")
        test_results = jenkins.get_test_results(job, build_info.build_number)
        
        if test_results:
            console.print(f"Tests: {test_results.passed} passed, "
                          f"[red]{test_results.failed}[/red] failed, "
                          f"{test_results.skipped} skipped")
        
        # Git analysis
        git_analysis = None
        if not no_git and config.git.enabled:
            progress.update(task, description="Analyzing git history...")
            
            # Determine workspace path
            ws_path = workspace
            if not ws_path and build_info.changeset:
                # Try to find workspace from Jenkins
                pass
            
            if ws_path and Path(ws_path).exists():
                try:
                    git_analyzer = GitAnalyzer(vars(config.git))
                    
                    # Extract error files from parsed log
                    error_files = []
                    for error in parsed_log.errors:
                        # Try to extract file paths from error lines
                        import re
                        file_matches = re.findall(
                            r'(?:File\s+["\']?|in\s+)([^\s"\']+\.\w+)',
                            error.line
                        )
                        error_files.extend(file_matches)
                    
                    git_analysis = git_analyzer.analyze(
                        ws_path,
                        error_files=error_files
                    )
                    
                    if git_analysis.suspicious_commits:
                        console.print(f"Found [yellow]{len(git_analysis.suspicious_commits)}[/yellow] "
                                      f"suspicious commits")
                except Exception as e:
                    logger.warning(f"Git analysis failed: {e}")
        
        # AI Analysis (using hybrid analyzer)
        progress.update(task, description="Performing AI analysis...")
        
        # Initialize hybrid analyzer
        hybrid_analyzer = HybridAnalyzer(config)
        hybrid_analyzer.set_clients(
            jenkins_client=jenkins,
            github_client=None,  # Could be initialized from config
            scm_client=None,     # Could be initialized from config
        )
        
        if not hybrid_analyzer.test_connection():
            console.print("[yellow]Warning:[/yellow] Cannot connect to AI model. "
                          "Proceeding without AI analysis.")
            hybrid_analyzer = None
        
        if hybrid_analyzer:
            try:
                # Get a log snippet for AI
                log_snippet = parser.get_error_snippet(parsed_log, max_errors=10)
                
                # Show analysis mode
                if deep:
                    console.print("[cyan]Using deep agentic investigation mode[/cyan]")
                elif scripted_only:
                    console.print("[dim]Using scripted-only mode[/dim]")
                else:
                    console.print("[dim]Using hybrid mode (auto-selects best approach)[/dim]")
                
                # Run hybrid analysis
                hybrid_result = hybrid_analyzer.analyze(
                    build_info=build_info,
                    parsed_log=parsed_log,
                    test_results=test_results,
                    git_analysis=git_analysis,
                    console_log_snippet=log_snippet,
                    force_agentic=deep,
                    force_scripted=scripted_only,
                )
                
                result = hybrid_result.merged_result
                
                # Show analysis mode used
                mode_msg = f"Analysis mode: {hybrid_result.mode.value}"
                if hybrid_result.agentic_enhanced:
                    mode_msg += f" ({hybrid_result.tool_calls_made} tool calls)"
                progress.update(task, description=f"Analysis complete! [{mode_msg}]")
                
            except Exception as e:
                console.print(f"[red]AI analysis error:[/red] {e}")
                sys.exit(1)
        else:
            # Create a basic result without AI
            from src.ai_analyzer import AnalysisResult, RootCause, Recommendation
            result = AnalysisResult(
                build_info={
                    "job": build_info.job_name,
                    "build_number": build_info.build_number,
                    "status": build_info.status,
                    "duration": build_info.duration_str,
                },
                failure_analysis={
                    "category": parsed_log.primary_category.value,
                    "failed_stage": parsed_log.failed_stage,
                    "primary_error": parsed_log.errors[0].line if parsed_log.errors else "",
                    "confidence": 0.5,
                },
                root_cause=RootCause(
                    summary="AI analysis unavailable - review errors manually",
                    details="",
                    confidence=0.5,
                    category=parsed_log.primary_category.value,
                ),
                recommendations=[
                    Recommendation(
                        priority="HIGH",
                        action="Review the error logs manually",
                        rationale="AI analysis was not available",
                    )
                ]
            )
    
    # Display results
    console.print("\n")
    
    # Root cause panel
    console.print(Panel(
        f"[bold]{result.root_cause.summary}[/bold]\n\n"
        f"{result.root_cause.details[:500] if result.root_cause.details else ''}",
        title="🎯 Root Cause",
        border_style="yellow"
    ))
    
    # Recommendations table
    rec_table = Table(title="💡 Recommendations")
    rec_table.add_column("Priority", style="bold")
    rec_table.add_column("Action")
    rec_table.add_column("Effort")
    
    for rec in result.recommendations:
        priority_style = {
            "HIGH": "red",
            "MEDIUM": "yellow",
            "LOW": "green"
        }.get(rec.priority, "white")
        
        rec_table.add_row(
            f"[{priority_style}]{rec.priority}[/{priority_style}]",
            rec.action,
            rec.estimated_effort or "-"
        )
    
    console.print(rec_table)
    
    # Generate reports
    if formats:
        report_gen = ReportGenerator(output or "./reports")
        generated = report_gen.generate(result, list(formats))
        
        console.print("\n[bold]Generated Reports:[/bold]")
        for fmt, path in generated.items():
            console.print(f"  • {fmt}: [cyan]{path}[/cyan]")
    
    # Output JSON to stdout if requested
    if not formats:
        console.print("\n[dim]Use --format json/markdown/html to generate reports[/dim]")


@cli.command()
@click.option("--port", "-p", default=8080, help="Server port")
@click.option("--host", "-h", default="0.0.0.0", help="Server host")
@click.pass_context
def serve(ctx, port: int, host: str):
    """Start the agent as an HTTP server."""
    config: Config = ctx.obj["config"]
    
    console.print(f"Starting server on [cyan]{host}:{port}[/cyan]")
    
    # Import and start FastAPI server
    from src.server import create_app
    import uvicorn
    
    app = create_app(config)
    uvicorn.run(app, host=host, port=port)


@cli.command()
@click.option("--job", "-j", required=True, help="Jenkins job name to watch")
@click.option("--interval", "-i", default=60, help="Poll interval in seconds")
@click.pass_context
def watch(ctx, job: str, interval: int):
    """Watch a job and analyze failures automatically."""
    import time
    
    config: Config = ctx.obj["config"]
    jenkins = JenkinsClient(config.jenkins)
    
    console.print(f"Watching job [cyan]{job}[/cyan] for failures...")
    console.print(f"Poll interval: {interval} seconds")
    console.print("Press Ctrl+C to stop\n")
    
    last_build = None
    
    try:
        while True:
            try:
                current_build = jenkins.get_latest_build(job, status="FAILURE")
                
                if last_build is None:
                    last_build = current_build.build_number
                    console.print(f"[dim]Starting watch from build #{last_build}[/dim]")
                
                elif current_build.build_number > last_build:
                    console.print(f"\n[red]New failure detected![/red] Build #{current_build.build_number}")
                    
                    # Trigger analysis
                    ctx.invoke(
                        analyze,
                        job=job,
                        build=current_build.build_number,
                        formats=("markdown",)
                    )
                    
                    last_build = current_build.build_number
                
            except Exception as e:
                logger.error(f"Watch error: {e}")
            
            time.sleep(interval)
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Watch stopped[/yellow]")


@cli.command()
@click.pass_context
def test_connection(ctx):
    """Test connections to Jenkins and AI model."""
    config: Config = ctx.obj["config"]
    
    # Test Jenkins
    console.print("Testing Jenkins connection...", end=" ")
    jenkins = JenkinsClient(config.jenkins)
    if jenkins.test_connection():
        console.print("[green]✓ Connected[/green]")
    else:
        console.print("[red]✗ Failed[/red]")
    
    # Test AI
    console.print("Testing AI model connection...", end=" ")
    ai = AIAnalyzer(config.ai)
    if ai.test_connection():
        console.print("[green]✓ Connected[/green]")
        console.print(f"  Model: [cyan]{config.ai.model}[/cyan]")
    else:
        console.print("[red]✗ Failed[/red]")
        console.print(f"  URL: {config.ai.base_url}")


@cli.command()
def init():
    """Create a new configuration file."""
    config_path = Path("config.yaml")
    example_path = Path(__file__).parent / "config.example.yaml"
    
    if config_path.exists():
        if not click.confirm("config.yaml already exists. Overwrite?"):
            return
    
    if example_path.exists():
        import shutil
        shutil.copy(example_path, config_path)
        console.print(f"[green]Created[/green] {config_path}")
        console.print("Edit this file with your Jenkins and AI settings.")
    else:
        console.print("[red]Error:[/red] Could not find example config")


if __name__ == "__main__":
    cli()
