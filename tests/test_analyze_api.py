"""
API-level tests for POST /analyze (iterative vs deep wiring).

Uses FastAPI TestClient with Jenkins + HybridAnalyzer mocked so no live Jenkins/LLM is required.
"""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config import load_config
from src.jenkins_client import BuildInfo, TestResult
from src.hybrid_analyzer import HybridAnalysisResult, AnalysisMode
from src.ai_analyzer import AnalysisResult, RootCause, RetryAssessment, Recommendation

MINIMAL_CONFIG_YAML = """
jenkins:
  url: http://127.0.0.1:9
  username: u
  api_token: t
ai:
  base_url: http://127.0.0.1:9/v1
  model: test
  api_key: k
git:
  enabled: false
github:
  enabled: false
scm:
  enabled: false
server:
  api_key: ""
parsing:
  method_execution_prefix: ""
reporter:
  update_jenkins_description: false
  post_to_pr: false
notifications:
  slack: {}
rc_analyzer:
  enabled: true
"""


@pytest.fixture
def minimal_config_path(tmp_path):
    p = tmp_path / "test-config.yaml"
    p.write_text(MINIMAL_CONFIG_YAML.strip(), encoding="utf-8")
    # No .env in tmp — load_config tolerates missing .env
    return str(p)


def _sample_hybrid_result() -> HybridAnalysisResult:
    ar = AnalysisResult(
        build_info={
            "job": "folder/job",
            "build_number": 5,
            "status": "FAILURE",
            "duration": "0m 1s",
        },
        failure_analysis={
            "category": "NETWORK",
            "tier": "external_system",
            "confidence": 0.8,
        },
        root_cause=RootCause(
            summary="Pipeline failed at deploy",
            details="details",
            confidence=0.8,
            category="NETWORK",
            tier="external_system",
            fix="Retry with VPN",
        ),
        recommendations=[
            Recommendation(priority="HIGH", action="Check network", rationale="r"),
        ],
        retry_assessment=RetryAssessment(
            is_retriable=False, confidence=0.8, reason="external"
        ),
    )
    return HybridAnalysisResult(
        mode=AnalysisMode.ITERATIVE,
        result=ar,
        iterations_used=3,
        tool_calls_made=0,
    )


@pytest.mark.integration
def test_post_analyze_iterative_failed_build(minimal_config_path, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    hybrid_ret = _sample_hybrid_result()
    build_info = BuildInfo(
        job_name="folder/job",
        build_number=5,
        status="FAILURE",
        url="http://jenkins/job/5",
        timestamp=datetime.utcnow(),
        duration_ms=1000,
        building=False,
    )

    with patch("src.jenkins_client.JenkinsClient") as JC, patch(
        "src.hybrid_analyzer.HybridAnalyzer"
    ) as HA:
        jc_inst = JC.return_value
        jc_inst.get_build_info.return_value = build_info
        jc_inst.get_console_log.return_value = (
            "[Pipeline] sh\n+ deploy.sh\nERROR: connection refused\nFinished: FAILURE\n"
        )
        jc_inst.get_test_results.return_value = TestResult()
        jc_inst.format_analysis_description = MagicMock(return_value="desc")
        jc_inst.set_build_description.return_value = False

        ha_inst = HA.return_value
        ha_inst.analyze.return_value = hybrid_ret
        ha_inst.set_clients = MagicMock()

        from src.server import create_app

        config = load_config(minimal_config_path, env_file=str(tmp_path / ".env-missing"))
        app = create_app(config)
        client = TestClient(app)

        res = client.post(
            "/analyze",
            json={
                "job": "folder/job",
                "build": 5,
                "mode": "iterative",
                "generate_report": False,
                "update_jenkins_description": False,
                "post_to_pr": False,
            },
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("success") is True
    assert body.get("analysis_mode") == "iterative"
    assert body.get("iterations_used") == 3
    ha_inst.analyze.assert_called_once()
    assert ha_inst.analyze.call_args.kwargs.get("deep") is False


@pytest.mark.integration
def test_post_analyze_deep_sets_deep_flag(minimal_config_path, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    hybrid_ret = _sample_hybrid_result()
    hybrid_ret.mode = AnalysisMode.DEEP
    hybrid_ret.tool_calls_made = 2

    build_info = BuildInfo(
        job_name="folder/job",
        build_number=5,
        status="FAILURE",
        url="http://jenkins/job/5",
        timestamp=datetime.utcnow(),
        duration_ms=1000,
        building=False,
    )

    with patch("src.jenkins_client.JenkinsClient") as JC, patch(
        "src.hybrid_analyzer.HybridAnalyzer"
    ) as HA:
        jc_inst = JC.return_value
        jc_inst.get_build_info.return_value = build_info
        jc_inst.get_console_log.return_value = "ERROR\nFinished: FAILURE\n"
        jc_inst.get_test_results.return_value = TestResult()
        jc_inst.format_analysis_description = MagicMock(return_value="desc")
        jc_inst.set_build_description.return_value = False

        ha_inst = HA.return_value
        ha_inst.analyze.return_value = hybrid_ret
        ha_inst.set_clients = MagicMock()

        from src.server import create_app

        config = load_config(minimal_config_path, env_file=str(tmp_path / ".env-missing"))
        app = create_app(config)
        client = TestClient(app)

        res = client.post(
            "/analyze",
            json={
                "job": "folder/job",
                "build": 5,
                "mode": "deep",
                "generate_report": False,
                "update_jenkins_description": False,
                "post_to_pr": False,
            },
        )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("analysis_mode") == "deep"
    assert ha_inst.analyze.call_args.kwargs.get("deep") is True
