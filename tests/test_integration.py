"""
Integration Tests for AI Learning System.

Tests the full workflow across all components.

Run: pytest tests/test_integration.py -v
"""

import pytest
import os
import sys
import json

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.knowledge_store import KnowledgeStore, ToolDefinition, ToolError
from src.doc_importer import DocImporter
from src.training_pipeline import TrainingPipeline, TrainingExample
from src.knowledge_store import KnowledgeDoc


class TestKnowledgeToTrainingFlow:
    """Test knowledge store → training pipeline integration."""
    
    @pytest.mark.integration
    def test_tool_to_training_example(self, temp_dir):
        """Test that tool errors become training examples."""
        # Setup knowledge store
        knowledge_db = os.path.join(temp_dir, "knowledge.db")
        training_db = os.path.join(temp_dir, "training.db")
        export_path = os.path.join(temp_dir, "exports")
        
        knowledge_store = KnowledgeStore(db_path=knowledge_db)
        
        # Add tool with errors
        tool = ToolDefinition(
            name="a2l",
            description="Deployment tool",
            category="deployment",
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED",
                    category="CREDENTIAL",
                    description="Auth token expired",
                    fix="Run a2l auth refresh",
                    retriable=True,
                ),
                ToolError(
                    code="A2L_CLUSTER_NOT_FOUND",
                    pattern="A2L_CLUSTER_NOT_FOUND",
                    category="CONFIGURATION",
                    description="Cluster does not exist",
                    fix="Check cluster name",
                    retriable=False,
                ),
            ]
        )
        knowledge_store.add_tool(tool)
        
        # Create training pipeline with same paths
        # Note: In real use, import_from_knowledge would use get_knowledge_store()
        # For testing, we manually create examples
        training = TrainingPipeline(db_path=training_db, export_path=export_path)
        
        # Simulate what import_from_knowledge does
        for error in tool.errors:
            example = TrainingExample(
                source="knowledge",
                tool_name=tool.name,
                error_snippet=f"{error.code}: {error.description}",
                root_cause=f"Tool '{tool.name}' error: {error.description}",
                fix=error.fix,
                category=error.category,
                is_retriable=error.retriable,
            )
            training.add_example(example)
        
        # Verify examples were created
        examples = training.get_examples(source="knowledge")
        assert len(examples) == 2
        
        # Export and verify
        job_id = training.create_job(name="test", format="jsonl_openai")
        filepath = training.export_job(job_id)
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        
        # Verify content
        for line in lines:
            data = json.loads(line)
            assistant_content = data["messages"][2]["content"]
            response = json.loads(assistant_content)
            assert response["category"] in ["CREDENTIAL", "CONFIGURATION"]


class TestJavaAnalyzerToKnowledgeFlow:
    """Test Java analyzer → knowledge store integration."""
    
    @pytest.mark.integration
    def test_java_patterns_to_tool(self, temp_dir, sample_java_source):
        """Test that Java patterns can create proper tool definition."""
        import re
        knowledge_db = os.path.join(temp_dir, "knowledge.db")
        
        # Extract patterns manually (simulating what analyzer does)
        env_vars = re.findall(r'System\.getenv\s*\(\s*["\'](\w+)["\']\s*\)', sample_java_source)
        exit_codes = re.findall(r'System\.exit\s*\(\s*(\d+)\s*\)', sample_java_source)
        error_codes = re.findall(r'([A-Z][A-Z0-9_]+):\s*([^"]+)', sample_java_source)
        
        # Create tool from extracted patterns
        errors = []
        for code, msg in error_codes[:2]:  # Take first 2
            errors.append(ToolError(
                code=code,
                pattern=code,
                description=msg.strip(),
                category="CREDENTIAL" if "AUTH" in code else "CONFIGURATION",
            ))
        
        tool = ToolDefinition(
            name="a2l",
            description="Deployment tool",
            category="deployment",
            patterns_commands=["a2l deploy", "a2l rollback"],
            patterns_env_vars=env_vars,
            errors=errors,
        )
        
        # Store in knowledge store
        store = KnowledgeStore(db_path=knowledge_db)
        tool_id = store.add_tool(tool)
        
        # Retrieve and verify
        stored_tool = store.get_tool(tool_id=tool_id)
        
        assert stored_tool.name == "a2l"
        assert len(stored_tool.errors) >= 1
        assert "A2L_TOKEN" in stored_tool.patterns_env_vars


class TestDocImportToKnowledgeFlow:
    """Test doc import → knowledge store integration."""
    
    @pytest.mark.integration
    def test_doc_import_to_tool(self, temp_dir, sample_markdown_doc):
        """Test that doc import creates proper tool definition."""
        knowledge_db = os.path.join(temp_dir, "knowledge.db")
        
        # Parse documentation
        importer = DocImporter()
        doc = KnowledgeDoc(
            source_type="url",
            source_url="https://wiki.example.com/a2l",
            title="A2L Docs",
            content=sample_markdown_doc,
            content_type="markdown",
        )
        
        info = importer.extract_info(doc)
        
        # Convert to tool definition
        tool = importer.to_tool_definition(info, "a2l", "https://wiki.example.com/a2l")
        
        # Store in knowledge store
        store = KnowledgeStore(db_path=knowledge_db)
        tool_id = store.add_tool(tool)
        
        # Also store the doc
        doc.tool_id = tool_id
        store.add_doc(doc)
        
        # Retrieve and verify
        stored_tool = store.get_tool(tool_id=tool_id)
        
        assert stored_tool.name == "a2l"
        assert stored_tool.docs_url == "https://wiki.example.com/a2l"
        assert len(stored_tool.errors) >= 2  # A2L_AUTH_FAILED, A2L_CLUSTER_NOT_FOUND
        
        # Verify doc was stored
        docs = store.get_docs_for_tool(tool_id)
        assert len(docs) == 1


class TestFullPipeline:
    """Test complete pipeline from source to training data."""
    
    @pytest.mark.integration
    def test_source_to_training_data(self, temp_dir, sample_java_source, sample_markdown_doc):
        """Test full pipeline: source patterns + doc → knowledge → training."""
        import re
        knowledge_db = os.path.join(temp_dir, "knowledge.db")
        training_db = os.path.join(temp_dir, "training.db")
        export_path = os.path.join(temp_dir, "exports")
        
        # Step 1: Extract patterns from Java source (simulating analyzer)
        env_vars = re.findall(r'System\.getenv\s*\(\s*["\'](\w+)["\']\s*\)', sample_java_source)
        error_codes = re.findall(r'([A-Z][A-Z0-9_]+):\s*([^"]+)', sample_java_source)
        
        java_errors = []
        for code, msg in error_codes[:2]:
            java_errors.append(ToolError(
                code=code,
                pattern=code,
                description=msg.strip(),
                category="CREDENTIAL" if "AUTH" in code else "CONFIGURATION",
                fix="Check documentation",
            ))
        
        java_tool = ToolDefinition(
            name="a2l-java",
            description="From Java source",
            patterns_commands=["a2l deploy", "a2l rollback"],
            patterns_env_vars=env_vars,
            errors=java_errors,
        )
        
        # Step 2: Import documentation
        doc_importer = DocImporter()
        doc = KnowledgeDoc(content=sample_markdown_doc, source_type="test")
        doc_info = doc_importer.extract_info(doc)
        doc_tool = doc_importer.to_tool_definition(doc_info, "a2l-docs")
        
        # Step 3: Store in knowledge store
        store = KnowledgeStore(db_path=knowledge_db)
        store.add_tool(java_tool)
        store.add_tool(doc_tool)
        
        # Step 4: Create training examples from knowledge
        training = TrainingPipeline(db_path=training_db, export_path=export_path)
        
        # Manually add examples (simulating import_from_knowledge)
        for tool in [java_tool, doc_tool]:
            for error in tool.errors:
                training.add_example(TrainingExample(
                    source="knowledge",
                    tool_name=tool.name,
                    error_snippet=f"{error.code}: {error.description}",
                    root_cause=f"Tool error: {error.description}",
                    fix=error.fix or "Check documentation",
                    category=error.category or "TOOL_ERROR",
                ))
        
        # Step 5: Export training data
        job_id = training.create_job(name="full-pipeline-test", format="jsonl_openai")
        filepath = training.export_job(job_id)
        
        # Verify
        assert os.path.exists(filepath)
        
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        # Should have examples from both tools
        assert len(lines) >= 3  # At least some errors from both sources
        
        # Verify all are valid JSON
        for line in lines:
            data = json.loads(line)
            assert "messages" in data
            assert len(data["messages"]) == 3


class TestKnowledgeMatchingInAnalysis:
    """Test that knowledge store is used during analysis."""
    
    @pytest.mark.integration
    def test_log_matches_known_tool(self, temp_dir, sample_log_text):
        """Test that log analysis matches known tools."""
        knowledge_db = os.path.join(temp_dir, "knowledge.db")
        
        # Setup knowledge store with a2l tool
        store = KnowledgeStore(db_path=knowledge_db)
        store.add_tool(ToolDefinition(
            name="a2l",
            patterns_commands=["a2l deploy", "a2l rollback"],
            patterns_log_signatures=["A2L_"],
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED",
                    category="CREDENTIAL",
                    fix="Refresh your token",
                )
            ]
        ))
        
        # Get knowledge context for log
        context = store.get_relevant_knowledge_for_log(sample_log_text)
        
        # Should find a2l tool and error
        assert "a2l" in context.lower() or "A2L" in context
        assert "AUTH" in context or "auth" in context or "CREDENTIAL" in context
    
    @pytest.mark.integration
    def test_error_matching(self, temp_dir):
        """Test matching specific error patterns."""
        knowledge_db = os.path.join(temp_dir, "knowledge.db")
        
        store = KnowledgeStore(db_path=knowledge_db)
        store.add_tool(ToolDefinition(
            name="a2l",
            errors=[
                ToolError(
                    code="A2L_AUTH_FAILED",
                    pattern="A2L_AUTH_FAILED|authentication failed|token expired",
                    category="CREDENTIAL",
                    fix="Run 'a2l auth refresh' to renew token",
                    confidence=0.9,
                )
            ]
        ))
        
        # Test exact match
        matches = store.match_error("Error: A2L_AUTH_FAILED - token expired")
        assert len(matches) >= 1
        
        error, tool, confidence = matches[0]
        assert error.code == "A2L_AUTH_FAILED"
        assert tool.name == "a2l"
        assert error.fix == "Run 'a2l auth refresh' to renew token"


class TestDataQuality:
    """Test data quality throughout the pipeline."""
    
    @pytest.mark.integration
    def test_validation_preserves_quality(self, temp_dir):
        """Test that validation correctly identifies quality issues."""
        training_db = os.path.join(temp_dir, "training.db")
        export_path = os.path.join(temp_dir, "exports")
        
        training = TrainingPipeline(db_path=training_db, export_path=export_path)
        
        # Add valid example
        valid_id = training.add_example(TrainingExample(
            source="test",
            error_snippet="A2L_AUTH_FAILED: Token expired after 24 hours",
            root_cause="The authentication token has expired and needs refresh",
            category="CREDENTIAL",
        ))
        
        # Add invalid example (too short)
        invalid_id = training.add_example(TrainingExample(
            source="test",
            error_snippet="E",
            root_cause="X",
        ))
        
        # Get examples
        all_examples = training.get_examples()
        valid_examples = training.get_examples(validated_only=True)
        
        assert len(all_examples) == 2
        assert len(valid_examples) == 1
        
        # Check quality scores
        high_quality = training.get_examples(min_quality=0.9)
        low_quality = training.get_examples(min_quality=0.0)
        
        assert len(high_quality) == 1
        assert len(low_quality) == 2
