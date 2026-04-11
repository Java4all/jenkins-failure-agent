"""
Tests for Java Source Analyzer (Phase 2A).

Run: pytest tests/test_java_analyzer.py -v

Note: JavaSourceAnalyzer requires GitHubClient, so we test individual 
extraction methods separately where possible.
"""

import pytest
import re
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.java_analyzer import ExtractedCommand, ExtractedError, AnalysisResult


class TestExtractedCommand:
    """Tests for ExtractedCommand dataclass."""
    
    @pytest.mark.unit
    def test_create_command(self):
        """Test creating an extracted command."""
        cmd = ExtractedCommand(
            name="deploy",
            description="Deploy application",
            arguments=[
                {
                    "name": "--cluster",
                    "aliases": ["-c"],
                    "required": True,
                }
            ]
        )
        
        assert cmd.name == "deploy"
        assert len(cmd.arguments) == 1
        assert cmd.arguments[0]["required"] == True


class TestExtractedError:
    """Tests for ExtractedError dataclass."""
    
    @pytest.mark.unit
    def test_create_error(self):
        """Test creating an extracted error."""
        error = ExtractedError(
            code="AUTH_FAILED",
            message_pattern="Authentication failed",
            exit_code=1,
            source_line=42,
        )
        
        assert error.code == "AUTH_FAILED"
        assert error.exit_code == 1


class TestAnalysisResult:
    """Tests for AnalysisResult dataclass."""
    
    @pytest.mark.unit
    def test_create_result(self):
        """Test creating an analysis result."""
        result = AnalysisResult(
            cli_framework="spring_shell",
            commands=[ExtractedCommand(name="deploy")],
            errors=[ExtractedError(code="ERR", message_pattern="error")],
            env_vars=["TOKEN"],
            files_analyzed=["A2L.java"],
        )
        
        assert result.cli_framework == "spring_shell"
        assert len(result.commands) == 1
        assert len(result.errors) == 1


class TestJavaPatterns:
    """Test regex patterns used in Java analysis."""
    
    @pytest.mark.unit
    def test_spring_shell_pattern(self, sample_java_source):
        """Test Spring Shell detection pattern."""
        pattern = re.compile(r'@ShellComponent|@ShellMethod')
        assert pattern.search(sample_java_source) is not None
    
    @pytest.mark.unit
    def test_picocli_pattern(self):
        """Test Picocli detection pattern."""
        picocli_source = '@Command(name = "deploy")'
        pattern = re.compile(r'@Command\s*\(')
        assert pattern.search(picocli_source) is not None
    
    @pytest.mark.unit
    def test_system_exit_pattern(self, sample_java_source):
        """Test System.exit() pattern."""
        pattern = re.compile(r'System\.exit\s*\(\s*(\d+)\s*\)')
        match = pattern.search(sample_java_source)
        assert match is not None
        assert match.group(1) == "1"
    
    @pytest.mark.unit
    def test_env_var_pattern(self, sample_java_source):
        """Test System.getenv() pattern."""
        pattern = re.compile(r'System\.getenv\s*\(\s*["\'](\w+)["\']\s*\)')
        match = pattern.search(sample_java_source)
        assert match is not None
        assert match.group(1) == "A2L_TOKEN"
    
    @pytest.mark.unit
    def test_error_message_pattern(self, sample_java_source):
        """Test error code extraction pattern."""
        pattern = re.compile(r'([A-Z][A-Z0-9_]+):\s*([^"]+)')
        matches = list(pattern.finditer(sample_java_source))
        
        codes = [m.group(1) for m in matches]
        assert "A2L_CLUSTER_REQUIRED" in codes or "A2L_AUTH_FAILED" in codes
