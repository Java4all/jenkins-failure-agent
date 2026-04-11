"""
Tests for Knowledge Store (Phase 1).

Run: pytest tests/test_knowledge_store.py -v
"""

import pytest
import json
import yaml
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.knowledge_store import (
    KnowledgeStore, ToolDefinition, ToolError, ToolArgument,
    KnowledgeDoc, SourceAnalysisLog
)


class TestToolDefinition:
    """Tests for ToolDefinition dataclass."""
    
    @pytest.mark.unit
    def test_create_tool_definition(self):
        """Test creating a basic tool definition."""
        tool = ToolDefinition(
            name="a2l",
            description="Deployment tool",
            category="deployment",
        )
        
        assert tool.name == "a2l"
        assert tool.description == "Deployment tool"
        assert tool.category == "deployment"
        assert tool.aliases == []
        assert tool.errors == []
    
    @pytest.mark.unit
    def test_tool_with_errors(self):
        """Test tool with error patterns."""
        tool = ToolDefinition(
            name="a2l",
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED|token expired",
                    category="CREDENTIAL",
                    description="Auth token expired",
                    fix="Run a2l auth refresh",
                    retriable=True,
                )
            ]
        )
        
        assert len(tool.errors) == 1
        assert tool.errors[0].code == "A2L_AUTH_FAILED"
        assert tool.errors[0].retriable == True
    
    @pytest.mark.unit
    def test_tool_to_dict(self):
        """Test serialization to dict."""
        tool = ToolDefinition(
            name="a2l",
            aliases=["a2l-cli"],
            category="deployment",
        )
        
        d = tool.to_dict()
        
        assert d["name"] == "a2l"
        assert d["aliases"] == ["a2l-cli"]
        assert d["category"] == "deployment"
    
    @pytest.mark.unit
    def test_tool_from_dict_manual(self):
        """Test creating tool from dict manually."""
        data = {
            "name": "a2l",
            "aliases": ["a2l-cli"],
            "category": "deployment",
            "description": "Test tool",
        }
        
        tool = ToolDefinition(
            name=data["name"],
            aliases=data.get("aliases", []),
            category=data.get("category", ""),
            description=data.get("description", ""),
        )
        
        assert tool.name == "a2l"
        assert tool.aliases == ["a2l-cli"]


class TestKnowledgeStore:
    """Tests for KnowledgeStore database operations."""
    
    @pytest.mark.unit
    def test_init_creates_tables(self, temp_db):
        """Test that initialization creates database tables."""
        store = KnowledgeStore(db_path=temp_db)
        
        import sqlite3
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert "tools" in tables
        assert "tool_errors" in tables
        assert "knowledge_docs" in tables
        assert "source_analysis_log" in tables
    
    @pytest.mark.unit
    def test_add_tool(self, temp_db):
        """Test adding a tool to the store."""
        store = KnowledgeStore(db_path=temp_db)
        
        tool = ToolDefinition(
            name="a2l",
            description="Test deployment tool",
            category="deployment",
            patterns_commands=["a2l deploy"],
        )
        
        tool_id = store.add_tool(tool)
        
        assert tool_id > 0
        
        # Retrieve and verify
        retrieved = store.get_tool(tool_id=tool_id)
        assert retrieved is not None
        assert retrieved.name == "a2l"
        assert retrieved.description == "Test deployment tool"
    
    @pytest.mark.unit
    def test_add_tool_with_errors(self, temp_db):
        """Test adding a tool with error patterns."""
        store = KnowledgeStore(db_path=temp_db)
        
        tool = ToolDefinition(
            name="a2l",
            category="deployment",
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED",
                    category="CREDENTIAL",
                    fix="Refresh token",
                )
            ]
        )
        
        tool_id = store.add_tool(tool)
        
        # Retrieve and check errors
        retrieved = store.get_tool(tool_id=tool_id)
        assert len(retrieved.errors) == 1
        assert retrieved.errors[0].code == "A2L_AUTH_FAILED"
    
    @pytest.mark.unit
    def test_get_tool_by_name(self, temp_db):
        """Test retrieving a tool by name."""
        store = KnowledgeStore(db_path=temp_db)
        
        tool = ToolDefinition(name="kubectl", category="infrastructure")
        store.add_tool(tool)
        
        retrieved = store.get_tool(name="kubectl")
        
        assert retrieved is not None
        assert retrieved.name == "kubectl"
    
    @pytest.mark.unit
    def test_list_tools(self, temp_db):
        """Test listing all tools."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.add_tool(ToolDefinition(name="a2l", category="deployment"))
        store.add_tool(ToolDefinition(name="kubectl", category="infrastructure"))
        store.add_tool(ToolDefinition(name="helm", category="deployment"))
        
        tools = store.list_tools()
        
        assert len(tools) == 3
        names = [t.name for t in tools]
        assert "a2l" in names
        assert "kubectl" in names
        assert "helm" in names
    
    @pytest.mark.unit
    def test_list_tools_by_category(self, temp_db):
        """Test filtering tools by category."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.add_tool(ToolDefinition(name="a2l", category="deployment"))
        store.add_tool(ToolDefinition(name="kubectl", category="infrastructure"))
        store.add_tool(ToolDefinition(name="helm", category="deployment"))
        
        deployment_tools = store.list_tools(category="deployment")
        
        assert len(deployment_tools) == 2
        names = [t.name for t in deployment_tools]
        assert "a2l" in names
        assert "helm" in names
        assert "kubectl" not in names
    
    @pytest.mark.unit
    def test_update_tool(self, temp_db):
        """Test updating a tool."""
        store = KnowledgeStore(db_path=temp_db)
        
        tool = ToolDefinition(name="a2l", description="Old description")
        tool_id = store.add_tool(tool)
        
        # Update with new tool object
        updated_tool = ToolDefinition(name="a2l", description="New description")
        store.update_tool(tool_id, updated_tool)
        
        # Verify
        retrieved = store.get_tool(tool_id=tool_id)
        assert retrieved.description == "New description"
    
    @pytest.mark.unit
    def test_delete_tool(self, temp_db):
        """Test deleting a tool."""
        store = KnowledgeStore(db_path=temp_db)
        
        tool_id = store.add_tool(ToolDefinition(name="a2l"))
        
        # Delete
        result = store.delete_tool(tool_id)
        assert result == True
        
        # Verify deleted
        retrieved = store.get_tool(tool_id=tool_id)
        assert retrieved is None
    
    @pytest.mark.unit
    def test_identify_tool(self, temp_db):
        """Test identifying tools from log text."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.add_tool(ToolDefinition(
            name="a2l",
            patterns_commands=["a2l deploy", "a2l rollback"],
            patterns_log_signatures=["[A2L]", "A2L_"],
        ))
        store.add_tool(ToolDefinition(
            name="kubectl",
            patterns_commands=["kubectl apply", "kubectl get"],
        ))
        
        # Test identification
        matches = store.identify_tool("Running: a2l deploy --cluster prod")
        
        assert len(matches) >= 1
        tool_names = [t.name for t, conf in matches]
        assert "a2l" in tool_names
    
    @pytest.mark.unit
    def test_match_error(self, temp_db):
        """Test matching error patterns."""
        store = KnowledgeStore(db_path=temp_db)
        
        tool = ToolDefinition(
            name="a2l",
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED|authentication failed",
                    category="CREDENTIAL",
                    fix="Refresh your token",
                )
            ]
        )
        store.add_tool(tool)
        
        # Test matching
        matches = store.match_error("Error: A2L_AUTH_FAILED - token expired")
        
        assert len(matches) >= 1
        error, matched_tool, confidence = matches[0]
        assert error.code == "A2L_AUTH_FAILED"
        assert matched_tool.name == "a2l"
    
    @pytest.mark.unit
    def test_add_tool_from_yaml_manual(self, temp_db, sample_tool_yaml):
        """Test adding a tool from parsed YAML definition."""
        import yaml
        store = KnowledgeStore(db_path=temp_db)
        
        # Parse YAML manually
        data = yaml.safe_load(sample_tool_yaml)
        tool_data = data.get("tool", {})
        
        # Create tool from parsed data
        errors = []
        for err in tool_data.get("errors", []):
            errors.append(ToolError(
                code=err.get("code", ""),
                pattern=err.get("pattern", ""),
                category=err.get("category", "UNKNOWN"),
                description=err.get("description", ""),
                fix=err.get("fix", ""),
                retriable=err.get("retriable", False),
            ))
        
        tool = ToolDefinition(
            name=tool_data.get("name", ""),
            aliases=tool_data.get("aliases", []),
            category=tool_data.get("category", ""),
            description=tool_data.get("description", ""),
            errors=errors,
        )
        
        tool_id = store.add_tool(tool)
        
        assert tool_id > 0
        
        retrieved = store.get_tool(tool_id=tool_id)
        assert retrieved.name == "a2l"
        assert "a2l-cli" in retrieved.aliases
        assert len(retrieved.errors) == 2
    
    @pytest.mark.unit
    def test_get_stats(self, temp_db):
        """Test getting store statistics."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.add_tool(ToolDefinition(
            name="a2l",
            errors=[ToolError(code="ERR1", pattern="err")]
        ))
        store.add_tool(ToolDefinition(name="kubectl"))
        
        stats = store.get_stats()
        
        assert stats["total_tools"] == 2
        assert stats["total_error_patterns"] == 1
    
    @pytest.mark.unit
    def test_get_relevant_knowledge_for_log(self, temp_db):
        """Test getting relevant knowledge for a log snippet."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.add_tool(ToolDefinition(
            name="a2l",
            description="Deployment tool",
            patterns_commands=["a2l deploy"],
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED",
                    category="CREDENTIAL",
                    fix="Refresh token",
                )
            ]
        ))
        
        log_text = """
        Running a2l deploy --cluster prod
        A2L_AUTH_FAILED: Token expired
        """
        
        context = store.get_relevant_knowledge_for_log(log_text)
        
        assert "a2l" in context.lower() or "A2L" in context
        assert len(context) > 0


class TestKnowledgeDoc:
    """Tests for KnowledgeDoc storage."""
    
    @pytest.mark.unit
    def test_add_doc(self, temp_db):
        """Test adding a knowledge document."""
        store = KnowledgeStore(db_path=temp_db)
        
        doc = KnowledgeDoc(
            source_type="url",
            source_url="https://wiki.example.com/a2l",
            title="A2L Documentation",
            content="# A2L Tool\n\nDeployment tool for K8s",
            content_type="markdown",
        )
        
        doc_id = store.add_doc(doc)
        
        assert doc_id > 0
    
    @pytest.mark.unit
    def test_search_docs(self, temp_db):
        """Test searching documents."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.add_doc(KnowledgeDoc(
            source_type="url",
            title="A2L Docs",
            content="A2L deployment tool documentation",
        ))
        store.add_doc(KnowledgeDoc(
            source_type="url",
            title="Kubectl Docs",
            content="Kubernetes kubectl documentation",
        ))
        
        results = store.search_docs("deployment")
        
        assert len(results) >= 1


class TestSourceAnalysisLog:
    """Tests for source analysis logging."""
    
    @pytest.mark.unit
    def test_log_analysis(self, temp_db):
        """Test logging a source analysis."""
        store = KnowledgeStore(db_path=temp_db)
        
        log = SourceAnalysisLog(
            repo_url="https://github.com/company/a2l-cli",
            branch="main",
            entry_point="src/main/java/A2L.java",
            depth=2,
            files_analyzed=["A2L.java", "Commands.java"],
            tools_extracted=1,
            status="completed",
        )
        
        log_id = store.log_source_analysis(log)
        
        assert log_id > 0
    
    @pytest.mark.unit
    def test_get_analysis_history(self, temp_db):
        """Test getting analysis history."""
        store = KnowledgeStore(db_path=temp_db)
        
        store.log_source_analysis(SourceAnalysisLog(
            repo_url="https://github.com/company/a2l",
            status="completed",
        ))
        store.log_source_analysis(SourceAnalysisLog(
            repo_url="https://github.com/company/kubectl",
            status="failed",
            error_message="Parse error",
        ))
        
        history = store.get_analysis_history(limit=10)
        
        assert len(history) == 2
