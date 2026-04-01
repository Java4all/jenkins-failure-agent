"""
Report generator for creating failure analysis reports in various formats.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from .ai_analyzer import AnalysisResult, result_to_dict


class ReportGenerator:
    """Generator for failure analysis reports."""
    
    def __init__(self, output_dir: str = "./reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(
        self,
        result: AnalysisResult,
        formats: list = None,
        include_raw_response: bool = False
    ) -> Dict[str, str]:
        """
        Generate reports in specified formats.
        
        Args:
            result: The analysis result to report
            formats: List of formats to generate ('json', 'markdown', 'html')
            include_raw_response: Include the raw AI response in reports
            
        Returns:
            Dictionary mapping format to file path
        """
        if formats is None:
            formats = ["json", "markdown"]
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_name = result.build_info.get("job", "unknown").replace("/", "_")
        build_num = result.build_info.get("build_number", 0)
        base_name = f"{job_name}_{build_num}_{timestamp}"
        
        generated = {}
        
        for fmt in formats:
            if fmt == "json":
                path = self._generate_json(result, base_name, include_raw_response)
                generated["json"] = str(path)
            elif fmt == "markdown":
                path = self._generate_markdown(result, base_name)
                generated["markdown"] = str(path)
            elif fmt == "html":
                path = self._generate_html(result, base_name)
                generated["html"] = str(path)
        
        return generated
    
    def _generate_json(
        self,
        result: AnalysisResult,
        base_name: str,
        include_raw: bool
    ) -> Path:
        """Generate JSON report."""
        data = result_to_dict(result)
        
        if include_raw:
            data["raw_ai_response"] = result.raw_ai_response
        
        data["generated_at"] = datetime.now().isoformat()
        
        path = self.output_dir / f"{base_name}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        
        return path
    
    def _generate_markdown(self, result: AnalysisResult, base_name: str) -> Path:
        """Generate Markdown report."""
        lines = []
        
        # Header
        lines.append(f"# Build Failure Analysis Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        
        # Build Info
        lines.append("## Build Information")
        lines.append("")
        lines.append(f"| Property | Value |")
        lines.append(f"|----------|-------|")
        lines.append(f"| Job | {result.build_info.get('job', 'N/A')} |")
        lines.append(f"| Build Number | {result.build_info.get('build_number', 'N/A')} |")
        lines.append(f"| Status | {result.build_info.get('status', 'N/A')} |")
        lines.append(f"| Duration | {result.build_info.get('duration', 'N/A')} |")
        lines.append("")
        
        # Failure Analysis
        analysis = result.failure_analysis
        lines.append("## Failure Analysis")
        lines.append("")
        lines.append(f"| Aspect | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Category | **{analysis.get('category', 'UNKNOWN')}** |")
        lines.append(f"| Failed Stage | {analysis.get('failed_stage', 'N/A')} |")
        lines.append(f"| Confidence | {analysis.get('confidence', 0):.0%} |")
        lines.append("")
        
        if analysis.get('primary_error'):
            lines.append("### Primary Error")
            lines.append("")
            lines.append("```")
            lines.append(analysis['primary_error'])
            lines.append("```")
            lines.append("")
        
        # Root Cause
        lines.append("## Root Cause Analysis")
        lines.append("")
        lines.append(f"### Summary")
        lines.append("")
        lines.append(f"> {result.root_cause.summary}")
        lines.append("")
        
        if result.root_cause.details:
            lines.append("### Details")
            lines.append("")
            lines.append(result.root_cause.details)
            lines.append("")
        
        if result.root_cause.related_commits:
            lines.append("### Related Commits")
            lines.append("")
            for commit in result.root_cause.related_commits:
                lines.append(f"- `{commit}`")
            lines.append("")
        
        if result.root_cause.affected_files:
            lines.append("### Affected Files")
            lines.append("")
            for file in result.root_cause.affected_files:
                lines.append(f"- `{file}`")
            lines.append("")
        
        # Recommendations
        lines.append("## Recommendations")
        lines.append("")
        
        priority_order = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_recs = sorted(
            result.recommendations,
            key=lambda r: priority_order.get(r.priority, 4)
        )
        
        for i, rec in enumerate(sorted_recs, 1):
            priority_badge = self._get_priority_badge(rec.priority)
            lines.append(f"### {i}. {priority_badge} {rec.action}")
            lines.append("")
            
            if rec.rationale:
                lines.append(f"**Rationale:** {rec.rationale}")
                lines.append("")
            
            if rec.estimated_effort:
                lines.append(f"**Estimated Effort:** {rec.estimated_effort}")
                lines.append("")
            
            if rec.code_suggestion:
                lines.append("**Code Suggestion:**")
                lines.append("")
                lines.append("```")
                lines.append(rec.code_suggestion)
                lines.append("```")
                lines.append("")
        
        # Metadata
        lines.append("---")
        lines.append("")
        lines.append(f"*Analysis performed in {result.analysis_duration_ms}ms using {result.model_used}*")
        
        path = self.output_dir / f"{base_name}.md"
        with open(path, "w") as f:
            f.write("\n".join(lines))
        
        return path
    
    def _generate_html(self, result: AnalysisResult, base_name: str) -> Path:
        """Generate HTML report."""
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Build Failure Analysis - {result.build_info.get('job', 'Unknown')}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{ color: #d32f2f; margin-bottom: 10px; }}
        h2 {{ color: #333; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        h3 {{ color: #555; }}
        .badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .badge-high {{ background: #ffebee; color: #c62828; }}
        .badge-medium {{ background: #fff3e0; color: #e65100; }}
        .badge-low {{ background: #e8f5e9; color: #2e7d32; }}
        .badge-failure {{ background: #ffebee; color: #c62828; }}
        .summary-box {{
            background: #fff3e0;
            border-left: 4px solid #ff9800;
            padding: 15px;
            margin: 15px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            text-align: left;
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}
        th {{ background: #fafafa; }}
        code {{
            background: #f5f5f5;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 14px;
        }}
        pre {{
            background: #263238;
            color: #aed581;
            padding: 15px;
            border-radius: 4px;
            overflow-x: auto;
        }}
        .recommendation {{
            border-left: 4px solid #2196f3;
            padding-left: 15px;
            margin: 15px 0;
        }}
        .recommendation.high {{ border-color: #f44336; }}
        .recommendation.medium {{ border-color: #ff9800; }}
        .recommendation.low {{ border-color: #4caf50; }}
        .footer {{
            text-align: center;
            color: #888;
            font-size: 12px;
            margin-top: 40px;
        }}
        .confidence-bar {{
            width: 100%;
            height: 8px;
            background: #eee;
            border-radius: 4px;
            overflow: hidden;
        }}
        .confidence-fill {{
            height: 100%;
            background: linear-gradient(90deg, #4caf50, #8bc34a);
            border-radius: 4px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>🔍 Build Failure Analysis</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>

    <div class="card">
        <h2>📋 Build Information</h2>
        <table>
            <tr><th>Job</th><td>{result.build_info.get('job', 'N/A')}</td></tr>
            <tr><th>Build Number</th><td>{result.build_info.get('build_number', 'N/A')}</td></tr>
            <tr><th>Status</th><td><span class="badge badge-failure">{result.build_info.get('status', 'N/A')}</span></td></tr>
            <tr><th>Duration</th><td>{result.build_info.get('duration', 'N/A')}</td></tr>
        </table>
    </div>

    <div class="card">
        <h2>⚠️ Failure Analysis</h2>
        <table>
            <tr><th>Category</th><td><strong>{result.failure_analysis.get('category', 'UNKNOWN')}</strong></td></tr>
            <tr><th>Failed Stage</th><td>{result.failure_analysis.get('failed_stage', 'N/A')}</td></tr>
            <tr>
                <th>Confidence</th>
                <td>
                    <div class="confidence-bar">
                        <div class="confidence-fill" style="width: {result.failure_analysis.get('confidence', 0) * 100}%"></div>
                    </div>
                    {result.failure_analysis.get('confidence', 0):.0%}
                </td>
            </tr>
        </table>
        {self._format_html_error(result.failure_analysis.get('primary_error', ''))}
    </div>

    <div class="card">
        <h2>🎯 Root Cause</h2>
        <div class="summary-box">
            <strong>{result.root_cause.summary}</strong>
        </div>
        {f'<p>{result.root_cause.details}</p>' if result.root_cause.details else ''}
        {self._format_html_commits(result.root_cause.related_commits)}
        {self._format_html_files(result.root_cause.affected_files)}
    </div>

    <div class="card">
        <h2>💡 Recommendations</h2>
        {self._format_html_recommendations(result.recommendations)}
    </div>

    <div class="footer">
        Analysis completed in {result.analysis_duration_ms}ms using {result.model_used}
    </div>
</body>
</html>
"""
        
        path = self.output_dir / f"{base_name}.html"
        with open(path, "w") as f:
            f.write(html)
        
        return path
    
    def _get_priority_badge(self, priority: str) -> str:
        """Get a text badge for priority."""
        badges = {
            "HIGH": "🔴 HIGH",
            "MEDIUM": "🟡 MEDIUM",
            "LOW": "🟢 LOW",
        }
        return badges.get(priority, priority)
    
    def _format_html_error(self, error: str) -> str:
        """Format error message as HTML."""
        if not error:
            return ""
        return f"""
        <h3>Primary Error</h3>
        <pre>{error}</pre>
        """
    
    def _format_html_commits(self, commits: list) -> str:
        """Format commits as HTML."""
        if not commits:
            return ""
        items = "".join(f"<li><code>{c}</code></li>" for c in commits)
        return f"""
        <h3>Related Commits</h3>
        <ul>{items}</ul>
        """
    
    def _format_html_files(self, files: list) -> str:
        """Format file list as HTML."""
        if not files:
            return ""
        items = "".join(f"<li><code>{f}</code></li>" for f in files)
        return f"""
        <h3>Affected Files</h3>
        <ul>{items}</ul>
        """
    
    def _format_html_recommendations(self, recommendations: list) -> str:
        """Format recommendations as HTML."""
        if not recommendations:
            return "<p>No recommendations available.</p>"
        
        html_parts = []
        priority_order = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}
        sorted_recs = sorted(
            recommendations,
            key=lambda r: priority_order.get(r.priority, 4)
        )
        
        for rec in sorted_recs:
            badge_class = rec.priority.lower()
            code_html = f"<pre>{rec.code_suggestion}</pre>" if rec.code_suggestion else ""
            effort_html = f"<p><em>Estimated effort: {rec.estimated_effort}</em></p>" if rec.estimated_effort else ""
            
            html_parts.append(f"""
            <div class="recommendation {badge_class}">
                <h3><span class="badge badge-{badge_class}">{rec.priority}</span> {rec.action}</h3>
                {f'<p>{rec.rationale}</p>' if rec.rationale else ''}
                {code_html}
                {effort_html}
            </div>
            """)
        
        return "".join(html_parts)


def format_slack_message(result: AnalysisResult) -> Dict[str, Any]:
    """Format analysis result as a Slack message."""
    
    # Emoji for category
    category_emoji = {
        "TEST_FAILURE": "🧪",
        "COMPILATION_ERROR": "🔨",
        "INFRASTRUCTURE": "🏗️",
        "DEPENDENCY": "📦",
        "CONFIGURATION": "⚙️",
        "UNKNOWN": "❓",
    }
    
    category = result.failure_analysis.get("category", "UNKNOWN")
    emoji = category_emoji.get(category, "❌")
    
    # Build blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Build Failure Analysis",
                "emoji": True
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Job:*\n{result.build_info.get('job', 'N/A')}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Build:*\n#{result.build_info.get('build_number', 'N/A')}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Category:*\n{category}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Confidence:*\n{result.failure_analysis.get('confidence', 0):.0%}"
                }
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Root Cause:*\n{result.root_cause.summary}"
            }
        }
    ]
    
    # Add recommendations
    if result.recommendations:
        rec_text = "*Recommendations:*\n"
        for i, rec in enumerate(result.recommendations[:3], 1):
            priority_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(rec.priority, "⚪")
            rec_text += f"{priority_icon} {rec.action}\n"
        
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": rec_text
            }
        })
    
    return {
        "blocks": blocks,
        "text": f"Build failure in {result.build_info.get('job', 'Unknown')}: {result.root_cause.summary}"
    }
