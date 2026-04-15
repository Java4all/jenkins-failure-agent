"""
Tests for Splunk Connector and Review Queue.
"""

import pytest
import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.splunk_connector import (
    SplunkConnector, SplunkConfig, FailedBuild
)
from src.review_queue import (
    ReviewQueue, ReviewItem, ReviewStatus
)


# =============================================================================
# Splunk Connector Tests
# =============================================================================

class TestSplunkConfig:
    """Test SplunkConfig dataclass."""
    
    def test_default_values(self):
        config = SplunkConfig()
        assert config.enabled == False
        assert config.index == "jenkins_console"
        assert config.log_tail_lines == 500
        assert config.sync_interval_mins == 15
        assert config.verify_ssl == False
    
    def test_custom_values(self):
        config = SplunkConfig(
            enabled=True,
            url="https://splunk.test.com:8089",
            token="test-token",
            index="custom_index",
            search_filter="my-team/*",
            log_tail_lines=1000,
        )
        assert config.enabled == True
        assert config.url == "https://splunk.test.com:8089"
        assert config.index == "custom_index"
        assert config.search_filter == "my-team/*"
        assert config.log_tail_lines == 1000


class TestFailedBuild:
    """Test FailedBuild dataclass."""
    
    def test_job_name_extraction(self):
        build = FailedBuild(
            host="jenkins.test.com",
            src="/job/folder/job/my-pipeline",
            job_id="123"
        )
        assert build.job_name == "folder/my-pipeline"
    
    def test_job_name_simple(self):
        build = FailedBuild(
            host="jenkins.test.com",
            src="/job/simple-job",
            job_id="456"
        )
        assert build.job_name == "simple-job"
    
    def test_to_dict(self):
        build = FailedBuild(
            host="jenkins.test.com",
            src="/job/my-job",
            job_id="789",
            failure_count=2,
            log_snippet="Error: test failure"
        )
        data = build.to_dict()
        assert data["host"] == "jenkins.test.com"
        assert data["job_id"] == "789"
        assert data["job_name"] == "my-job"
        assert data["failure_count"] == 2


class TestSplunkConnector:
    """Test SplunkConnector."""
    
    def test_disabled_connector(self):
        config = SplunkConfig(enabled=False)
        connector = SplunkConnector(config)
        
        # Should return empty when disabled
        results = connector._search("test query")
        assert results == []
    
    def test_test_connection_disabled(self):
        config = SplunkConfig(enabled=False)
        connector = SplunkConnector(config)
        
        result = connector.test_connection()
        assert result["success"] == False
        assert result["enabled"] == False
    
    def test_test_connection_no_url(self):
        config = SplunkConfig(enabled=True, url="", token="test")
        connector = SplunkConnector(config)
        
        result = connector.test_connection()
        assert result["success"] == False
        assert "SPLUNK_URL" in result["error"]
    
    def test_test_connection_no_token(self):
        config = SplunkConfig(enabled=True, url="https://splunk.test.com", token="")
        connector = SplunkConnector(config)
        
        result = connector.test_connection()
        assert result["success"] == False
        assert "SPLUNK_TOKEN" in result["error"]
    
    @patch('requests.Session.get')
    def test_test_connection_timeout(self, mock_get):
        import requests
        config = SplunkConfig(enabled=True, url="https://splunk.test.com", token="test")
        connector = SplunkConnector(config)
        
        mock_get.side_effect = requests.Timeout()
        
        result = connector.test_connection()
        assert result["success"] == False
        assert "timeout" in result["error"].lower()
    
    @patch('requests.Session.post')
    @patch('requests.Session.get')
    def test_search_success(self, mock_get, mock_post):
        config = SplunkConfig(
            enabled=True,
            url="https://splunk.test.com:8089",
            token="test-token"
        )
        connector = SplunkConnector(config)
        
        # Mock job creation
        post_response = Mock()
        post_response.status_code = 200
        post_response.text = '{"sid": "12345"}'
        post_response.json.return_value = {"sid": "12345"}
        post_response.raise_for_status = Mock()
        mock_post.return_value = post_response
        
        # Mock results
        get_response = Mock()
        get_response.status_code = 200
        get_response.text = '{"results": [{"host": "jenkins", "job_id": "1"}]}'
        get_response.json.return_value = {"results": [{"host": "jenkins", "job_id": "1"}]}
        get_response.raise_for_status = Mock()
        mock_get.return_value = get_response
        
        results = connector._search("test query")
        assert len(results) == 1
        assert results[0]["host"] == "jenkins"
    
    @patch('requests.Session.post')
    def test_search_failure(self, mock_post):
        config = SplunkConfig(
            enabled=True,
            url="https://splunk.test.com:8089",
            token="test-token"
        )
        connector = SplunkConnector(config)
        
        # Mock request exception
        import requests
        mock_post.side_effect = requests.RequestException("Connection failed")
        
        results = connector._search("test query")
        assert results == []
    
    @patch.object(SplunkConnector, '_search')
    def test_get_failed_builds(self, mock_search):
        config = SplunkConfig(
            enabled=True,
            url="https://splunk.test.com:8089",
            token="test-token",
            search_filter="abc/shared-code"
        )
        connector = SplunkConnector(config)
        
        mock_search.return_value = [
            {"host": "jenkins1", "src": "/job/pipeline1", "job_id": "100", "failure_count": "1"},
            {"host": "jenkins2", "src": "/job/pipeline2", "job_id": "200", "failure_count": "2"},
        ]
        
        failures = connector.get_failed_builds(minutes=30)
        
        assert len(failures) == 2
        assert failures[0].host == "jenkins1"
        assert failures[0].job_id == "100"
        assert failures[1].failure_count == 2

    @patch.object(SplunkConnector, '_search')
    def test_get_failed_builds_uses_source_subsearch_filter(self, mock_search):
        config = SplunkConfig(
            enabled=True,
            url="https://splunk.test.com:8089",
            token="test-token",
            index="jenkins_console",
            search_filter="xomecd/my-lib",
        )
        connector = SplunkConnector(config)
        mock_search.return_value = []

        connector.get_failed_builds(minutes=15, simple_query=True)

        called_query = mock_search.call_args[0][0]
        assert '[ search index=jenkins_console "xomecd/my-lib" earliest=-15m | fields source | dedup source ]' in called_query
    
    @patch.object(SplunkConnector, '_search')
    def test_get_build_log(self, mock_search):
        config = SplunkConfig(
            enabled=True,
            url="https://splunk.test.com:8089",
            token="test-token"
        )
        connector = SplunkConnector(config)
        
        mock_search.return_value = [
            {"_raw": "Line 1: Starting build"},
            {"_raw": "Line 2: Running tests"},
            {"_raw": "Line 3: Error: Test failed"},
        ]
        
        log = connector.get_build_log("jenkins.test.com", "123", tail_lines=100)
        
        assert "Line 1" in log
        assert "Error: Test failed" in log


# =============================================================================
# Review Queue Tests
# =============================================================================

class TestReviewQueue:
    """Test ReviewQueue storage."""
    
    @pytest.fixture
    def queue(self, tmp_path):
        """Create a test queue with temp database."""
        db_path = str(tmp_path / "test_review.db")
        return ReviewQueue(db_path=db_path)
    
    def test_add_item(self, queue):
        item = queue.add(
            host="jenkins.test.com",
            job_name="my-pipeline",
            job_id="123",
            log_snippet="Error: Build failed",
            ai_root_cause="Missing dependency",
            ai_fix="Add dependency X",
            ai_confidence=0.85,
            ai_category="BUILD"
        )
        
        assert item.id is not None
        assert item.host == "jenkins.test.com"
        assert item.job_name == "my-pipeline"
        assert item.status == "pending"
    
    def test_get_item(self, queue):
        added = queue.add(
            host="jenkins.test.com",
            job_name="test-job",
            job_id="456"
        )
        
        retrieved = queue.get(added.id)
        
        assert retrieved is not None
        assert retrieved.id == added.id
        assert retrieved.job_name == "test-job"
    
    def test_get_nonexistent(self, queue):
        result = queue.get(99999)
        assert result is None
    
    def test_exists(self, queue):
        queue.add(host="jenkins", job_name="job", job_id="100")
        
        assert queue.exists("jenkins", "100") == True
        assert queue.exists("jenkins", "999") == False
        assert queue.exists("other", "100") == False
    
    def test_list_all(self, queue):
        queue.add(host="h1", job_name="j1", job_id="1")
        queue.add(host="h2", job_name="j2", job_id="2")
        queue.add(host="h3", job_name="j3", job_id="3")
        
        items = queue.list()
        assert len(items) == 3
    
    def test_list_by_status(self, queue):
        item1 = queue.add(host="h1", job_name="j1", job_id="1")
        item2 = queue.add(host="h2", job_name="j2", job_id="2")
        
        # Approve one
        queue.update_status(item1.id, ReviewStatus.APPROVED)
        
        pending = queue.list(status="pending")
        approved = queue.list(status="approved")
        
        assert len(pending) == 1
        assert len(approved) == 1
        assert pending[0].job_id == "2"
        assert approved[0].job_id == "1"
    
    def test_update_status(self, queue):
        item = queue.add(host="h", job_name="j", job_id="1")
        
        success = queue.update_status(
            item.id,
            ReviewStatus.APPROVED,
            confirmed_root_cause="Actual root cause",
            confirmed_fix="Actual fix",
            confirmed_category="CREDENTIAL"
        )
        
        assert success == True
        
        updated = queue.get(item.id)
        assert updated.status == "approved"
        assert updated.confirmed_root_cause == "Actual root cause"
        assert updated.confirmed_fix == "Actual fix"
        assert updated.reviewed_at is not None
    
    def test_delete(self, queue):
        item = queue.add(host="h", job_name="j", job_id="1")
        
        success = queue.delete(item.id)
        assert success == True
        
        # Should not exist
        assert queue.get(item.id) is None
        
        # Delete again should return False
        assert queue.delete(item.id) == False
    
    def test_get_stats(self, queue):
        # Add items with different statuses
        item1 = queue.add(host="h1", job_name="j1", job_id="1", ai_confidence=0.9)
        item2 = queue.add(host="h2", job_name="j2", job_id="2", ai_confidence=0.8)
        item3 = queue.add(host="h3", job_name="j3", job_id="3", ai_confidence=0.7)
        
        queue.update_status(item1.id, ReviewStatus.APPROVED)
        queue.update_status(item2.id, ReviewStatus.APPROVED)
        queue.update_status(item3.id, ReviewStatus.REJECTED)
        
        stats = queue.get_stats()
        
        assert stats["total"] == 3
        assert stats["pending"] == 0
        assert stats["approved"] == 2
        assert stats["rejected"] == 1
        assert stats["avg_approved_confidence"] == 0.85  # (0.9 + 0.8) / 2


class TestReviewItem:
    """Test ReviewItem dataclass."""
    
    def test_to_dict(self):
        item = ReviewItem(
            id=1,
            host="jenkins.test.com",
            job_name="my-pipeline",
            job_id="123",
            log_snippet="Error log here",
            ai_root_cause="Test failure",
            ai_confidence=0.75,
            status="pending"
        )
        
        data = item.to_dict()
        
        assert data["id"] == 1
        assert data["host"] == "jenkins.test.com"
        assert data["job_name"] == "my-pipeline"
        assert data["ai_confidence"] == 0.75
        assert data["status"] == "pending"
    
    def test_to_dict_truncates_log(self):
        long_log = "x" * 2000
        item = ReviewItem(
            id=1,
            host="h",
            job_name="j",
            job_id="1",
            log_snippet=long_log
        )
        
        data = item.to_dict()
        
        # Should be truncated to 1000 chars
        assert len(data["log_snippet"]) == 1000


class TestReviewStatus:
    """Test ReviewStatus enum."""
    
    def test_values(self):
        assert ReviewStatus.PENDING.value == "pending"
        assert ReviewStatus.APPROVED.value == "approved"
        assert ReviewStatus.REJECTED.value == "rejected"
        assert ReviewStatus.SKIPPED.value == "skipped"
