"""
Tests for Training Pipeline (Phase 4).

Run: pytest tests/test_training_pipeline.py -v
"""

import pytest
import json
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.training_pipeline import (
    TrainingPipeline, TrainingExample, TrainingJob,
    TrainingFormat, TrainingJobStatus
)


class TestTrainingExample:
    """Tests for TrainingExample dataclass."""
    
    @pytest.mark.unit
    def test_create_example(self):
        """Test creating a training example."""
        example = TrainingExample(
            source="feedback",
            error_snippet="A2L_AUTH_FAILED: Token expired",
            root_cause="Authentication token has expired",
            fix="Run 'a2l auth refresh'",
            category="CREDENTIAL",
            confidence=0.9,
        )
        
        assert example.source == "feedback"
        assert example.category == "CREDENTIAL"
        assert example.confidence == 0.9
    
    @pytest.mark.unit
    def test_compute_hash(self):
        """Test content hash computation."""
        example1 = TrainingExample(
            error_snippet="Error A",
            root_cause="Cause A",
            fix="Fix A",
        )
        
        example2 = TrainingExample(
            error_snippet="Error A",
            root_cause="Cause A",
            fix="Fix A",
        )
        
        example3 = TrainingExample(
            error_snippet="Error B",
            root_cause="Cause B",
            fix="Fix B",
        )
        
        # Same content should have same hash
        assert example1.compute_hash() == example2.compute_hash()
        
        # Different content should have different hash
        assert example1.compute_hash() != example3.compute_hash()
    
    @pytest.mark.unit
    def test_validate_valid_example(self):
        """Test validation of valid example."""
        example = TrainingExample(
            error_snippet="A2L_AUTH_FAILED: Token expired after 24 hours",
            root_cause="The authentication token for A2L has expired",
            category="CREDENTIAL",
            confidence=0.85,
        )
        
        is_valid, issues = example.validate()
        
        assert is_valid == True
        assert len(issues) == 0
    
    @pytest.mark.unit
    def test_validate_invalid_example(self):
        """Test validation of invalid example."""
        example = TrainingExample(
            error_snippet="E",  # Too short
            root_cause="",      # Empty
            category="INVALID_CATEGORY",
            confidence=1.5,     # Out of range
        )
        
        is_valid, issues = example.validate()
        
        assert is_valid == False
        assert len(issues) >= 3
    
    @pytest.mark.unit
    def test_to_openai_format(self):
        """Test conversion to OpenAI fine-tuning format."""
        example = TrainingExample(
            job_name="my-project",
            failed_stage="Deploy",
            tool_name="a2l",
            error_snippet="A2L_AUTH_FAILED: Token expired",
            root_cause="Auth token expired",
            category="CREDENTIAL",
            confidence=0.9,
            fix="Refresh token",
        )
        
        openai_fmt = example.to_openai_format()
        
        assert "messages" in openai_fmt
        assert len(openai_fmt["messages"]) == 3
        
        # Check roles
        roles = [m["role"] for m in openai_fmt["messages"]]
        assert roles == ["system", "user", "assistant"]
        
        # Check user message contains context
        user_msg = openai_fmt["messages"][1]["content"]
        assert "my-project" in user_msg
        assert "Deploy" in user_msg
        assert "A2L_AUTH_FAILED" in user_msg
        
        # Check assistant response is valid JSON
        assistant_msg = openai_fmt["messages"][2]["content"]
        response_data = json.loads(assistant_msg)
        assert response_data["root_cause"] == "Auth token expired"
        assert response_data["category"] == "CREDENTIAL"
    
    @pytest.mark.unit
    def test_to_anthropic_format(self):
        """Test conversion to Anthropic fine-tuning format."""
        example = TrainingExample(
            error_snippet="Error occurred",
            root_cause="Root cause",
            category="TEST",
        )
        
        anthropic_fmt = example.to_anthropic_format()
        
        assert "prompt" in anthropic_fmt
        assert "Human:" in anthropic_fmt["prompt"]
        assert "Assistant:" in anthropic_fmt["prompt"]


class TestTrainingPipeline:
    """Tests for TrainingPipeline operations."""
    
    @pytest.mark.unit
    def test_init_creates_tables(self, temp_dir):
        """Test that initialization creates database tables."""
        db_path = os.path.join(temp_dir, "training.db")
        export_path = os.path.join(temp_dir, "exports")
        
        pipeline = TrainingPipeline(db_path=db_path, export_path=export_path)
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        assert "training_examples" in tables
        assert "training_jobs" in tables
    
    @pytest.mark.unit
    def test_add_example(self, temp_dir):
        """Test adding a training example."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        example = TrainingExample(
            source="test",
            error_snippet="Test error message here",
            root_cause="This is the root cause",
            category="TEST",
        )
        
        example_id = pipeline.add_example(example)
        
        assert example_id > 0
    
    @pytest.mark.unit
    def test_add_duplicate_example(self, temp_dir):
        """Test that duplicate examples are rejected."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        example = TrainingExample(
            source="test",
            error_snippet="Same error",
            root_cause="Same cause",
        )
        
        id1 = pipeline.add_example(example)
        id2 = pipeline.add_example(example)  # Duplicate
        
        assert id1 > 0
        assert id2 == -1  # Rejected as duplicate
    
    @pytest.mark.unit
    def test_get_examples(self, temp_dir):
        """Test retrieving examples with filters."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        # Add examples with different sources
        pipeline.add_example(TrainingExample(
            source="feedback",
            error_snippet="Error from feedback",
            root_cause="Cause from feedback",
        ))
        pipeline.add_example(TrainingExample(
            source="knowledge",
            error_snippet="Error from knowledge",
            root_cause="Cause from knowledge",
        ))
        
        # Get all
        all_examples = pipeline.get_examples()
        assert len(all_examples) == 2
        
        # Filter by source
        feedback_examples = pipeline.get_examples(source="feedback")
        assert len(feedback_examples) == 1
        assert feedback_examples[0].source == "feedback"
    
    @pytest.mark.unit
    def test_create_job(self, temp_dir):
        """Test creating a training job."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        job_id = pipeline.create_job(
            name="test-job",
            description="Test training job",
            format="jsonl_openai",
        )
        
        assert job_id > 0
        
        # Retrieve and verify
        job = pipeline.get_job(job_id)
        assert job is not None
        assert job.name == "test-job"
        assert job.status == TrainingJobStatus.PENDING.value
    
    @pytest.mark.unit
    def test_list_jobs(self, temp_dir):
        """Test listing training jobs."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        pipeline.create_job(name="job1")
        pipeline.create_job(name="job2")
        pipeline.create_job(name="job3")
        
        jobs = pipeline.list_jobs()
        
        assert len(jobs) == 3
    
    @pytest.mark.unit
    def test_prepare_and_export_job(self, temp_dir):
        """Test full job workflow: create, prepare, export."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        # Add some test examples directly
        pipeline.add_example(TrainingExample(
            source="test",
            error_snippet="A2L_AUTH_FAILED: Token expired",
            root_cause="Authentication token has expired",
            fix="Run a2l auth refresh",
            category="CREDENTIAL",
        ))
        pipeline.add_example(TrainingExample(
            source="test",
            error_snippet="NETWORK_TIMEOUT: Connection failed",
            root_cause="Network connection timed out",
            fix="Check network connectivity",
            category="NETWORK",
        ))
        
        # Create job
        job_id = pipeline.create_job(
            name="test-export",
            format="jsonl_openai",
            include_feedback=False,  # Skip actual feedback import
            include_knowledge=False,  # Skip actual knowledge import
        )
        
        # Note: prepare_job would try to import from stores which may not exist
        # So we skip prepare and just export what we have
        
        # Export
        filepath = pipeline.export_job(job_id)
        
        assert filepath is not None
        assert os.path.exists(filepath)
        assert filepath.endswith(".jsonl")
        
        # Verify content
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        assert len(lines) == 2
        
        # Each line should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert "messages" in data
    
    @pytest.mark.unit
    def test_export_csv_format(self, temp_dir):
        """Test exporting to CSV format."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        pipeline.add_example(TrainingExample(
            source="test",
            error_snippet="Test error",
            root_cause="Test cause",
            category="TEST",
        ))
        
        job_id = pipeline.create_job(name="csv-test", format="csv")
        filepath = pipeline.export_job(job_id)
        
        assert filepath.endswith(".csv")
        
        # Verify CSV content
        with open(filepath, 'r') as f:
            content = f.read()
        
        assert "id,source,tool_name" in content  # Header
        assert "test" in content  # Source value
    
    @pytest.mark.unit
    def test_export_json_format(self, temp_dir):
        """Test exporting to JSON format."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        pipeline.add_example(TrainingExample(
            source="test",
            error_snippet="Test error",
            root_cause="Test cause",
        ))
        
        job_id = pipeline.create_job(name="json-test", format="json")
        filepath = pipeline.export_job(job_id)
        
        assert filepath.endswith(".json")
        
        # Verify JSON content
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        assert "examples" in data
        assert "count" in data
        assert data["count"] == 1
    
    @pytest.mark.unit
    def test_get_stats(self, temp_dir):
        """Test getting pipeline statistics."""
        pipeline = TrainingPipeline(
            db_path=os.path.join(temp_dir, "training.db"),
            export_path=os.path.join(temp_dir, "exports"),
        )
        
        pipeline.add_example(TrainingExample(
            source="feedback",
            error_snippet="Error 1",
            root_cause="Cause 1",
            category="CREDENTIAL",
        ))
        pipeline.add_example(TrainingExample(
            source="knowledge",
            error_snippet="Error 2",
            root_cause="Cause 2",
            category="NETWORK",
        ))
        
        pipeline.create_job(name="job1")
        
        stats = pipeline.get_stats()
        
        assert stats["total_examples"] == 2
        assert stats["total_jobs"] == 1
        assert "feedback" in stats["by_source"]
        assert "knowledge" in stats["by_source"]
        assert "CREDENTIAL" in stats["by_category"]
        assert "NETWORK" in stats["by_category"]


class TestTrainingJob:
    """Tests for TrainingJob dataclass."""
    
    @pytest.mark.unit
    def test_create_job(self):
        """Test creating a training job."""
        job = TrainingJob(
            name="finetune-v1",
            description="First fine-tuning attempt",
            format=TrainingFormat.JSONL_OPENAI.value,
        )
        
        assert job.name == "finetune-v1"
        assert job.status == TrainingJobStatus.PENDING.value
    
    @pytest.mark.unit
    def test_job_to_dict(self):
        """Test serializing job to dict."""
        job = TrainingJob(
            id=1,
            name="test-job",
            status=TrainingJobStatus.COMPLETED.value,
            total_examples=100,
            valid_examples=95,
        )
        
        d = job.to_dict()
        
        assert d["id"] == 1
        assert d["name"] == "test-job"
        assert d["total_examples"] == 100
