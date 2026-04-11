"""
Pytest configuration and shared fixtures.

Run tests:
    pytest                          # All tests
    pytest -m unit                  # Unit tests only
    pytest -m "not slow"            # Skip slow tests
    pytest tests/test_knowledge.py  # Specific file
"""

import pytest
import tempfile
import shutil
import os
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    path = tempfile.mkdtemp(prefix="jenkins_agent_test_")
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def temp_db(temp_dir):
    """Create a temporary database path."""
    return os.path.join(temp_dir, "test.db")


@pytest.fixture
def sample_log_text():
    """Sample Jenkins log text for testing."""
    return """
Started by user admin
Running in Durability level: MAX_SURVIVABILITY
[Pipeline] Start of Pipeline
[Pipeline] stage
[Pipeline] { (Build)
[Pipeline] sh
+ npm install
npm ERR! code ERESOLVE
npm ERR! ERESOLVE unable to resolve dependency tree
npm ERR! peer dep missing: react@^18.0.0
[Pipeline] }
[Pipeline] // stage
[Pipeline] stage
[Pipeline] { (Deploy)
[Pipeline] sh
+ a2l deploy --cluster prod
A2L_AUTH_FAILED: Authentication token expired
Exit code: 1
[Pipeline] }
[Pipeline] // stage
[Pipeline] End of Pipeline
ERROR: script returned exit code 1
Finished: FAILURE
"""


@pytest.fixture
def sample_java_source():
    """Sample Java CLI source code for testing."""
    return '''
package com.company.cli;

import org.springframework.shell.standard.ShellComponent;
import org.springframework.shell.standard.ShellMethod;
import org.springframework.shell.standard.ShellOption;

@ShellComponent
public class A2LCli {
    
    @ShellMethod(value = "Deploy application to cluster", key = "deploy")
    public String deploy(
        @ShellOption(value = {"--cluster", "-c"}, help = "Target cluster") String cluster,
        @ShellOption(value = "--version", defaultValue = "latest") String version
    ) {
        if (cluster == null) {
            throw new IllegalArgumentException("A2L_CLUSTER_REQUIRED: Cluster must be specified");
        }
        
        String token = System.getenv("A2L_TOKEN");
        if (token == null || token.isEmpty()) {
            System.err.println("A2L_AUTH_FAILED: Authentication token not found");
            System.exit(1);
        }
        
        return "Deployed to " + cluster;
    }
    
    @ShellMethod(value = "Rollback deployment", key = "rollback")
    public String rollback(
        @ShellOption(value = "--version", help = "Version to rollback to") String version
    ) {
        return "Rolled back to " + version;
    }
}
'''


@pytest.fixture
def sample_markdown_doc():
    """Sample markdown documentation for testing."""
    return '''
# A2L CLI Tool

A deployment tool for Kubernetes clusters.

## Installation

```bash
pip install a2l-cli
```

## Commands

```bash
$ a2l deploy --cluster prod
$ a2l rollback --version 1.2.3
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| A2L_TOKEN | Authentication token |
| A2L_CLUSTER | Default cluster name |

## Error Codes

| Code | Description |
|------|-------------|
| A2L_AUTH_FAILED | Authentication token is invalid or expired |
| A2L_CLUSTER_NOT_FOUND | Specified cluster does not exist |
| A2L_DEPLOY_FAILED | Deployment failed |

## Arguments

- `--cluster` - Target cluster name (required)
- `--timeout` - Operation timeout in seconds
- `--version` - Version to deploy
'''


@pytest.fixture
def sample_tool_yaml():
    """Sample tool definition in YAML format."""
    return '''
schema_version: "1.0"
tool:
  name: "a2l"
  aliases: ["a2l-cli", "a2l-deploy"]
  category: "deployment"
  description: "A2L deployment tool for Kubernetes clusters"
  owner: "platform-team"
  docs_url: "https://wiki.company.com/a2l"
  patterns:
    commands:
      - "a2l deploy"
      - "a2l rollback"
      - "a2l status"
    log_signatures:
      - "[A2L]"
      - "A2L_"
    env_vars:
      - "A2L_TOKEN"
      - "A2L_CLUSTER"
  arguments:
    - name: "--cluster"
      aliases: ["-c"]
      required: true
      description: "Target cluster name"
    - name: "--version"
      required: false
      description: "Version to deploy"
  errors:
    - code: "A2L_AUTH_FAILED"
      pattern: "A2L_AUTH_FAILED|authentication failed|token expired"
      exit_code: 1
      category: "CREDENTIAL"
      description: "Authentication token is invalid or expired"
      fix: "Run 'a2l auth refresh' to renew your token"
      retriable: true
    - code: "A2L_CLUSTER_NOT_FOUND"
      pattern: "A2L_CLUSTER_NOT_FOUND|cluster.*not found"
      exit_code: 2
      category: "CONFIGURATION"
      description: "The specified cluster does not exist"
      fix: "Check cluster name with 'a2l clusters list'"
      retriable: false
  dependencies:
    tools: ["kubectl", "helm"]
    services: ["internal-registry.company.com"]
    credentials: ["A2L_TOKEN"]
'''


@pytest.fixture
def mock_feedback_entry():
    """Sample feedback entry for testing."""
    return {
        "id": 1,
        "job_name": "my-project",
        "build_number": 123,
        "error_snippet": "A2L_AUTH_FAILED: Token expired",
        "error_category": "CREDENTIAL",
        "failed_stage": "Deploy",
        "failed_method": None,
        "original_root_cause": "Authentication error",
        "original_confidence": 0.65,
        "was_correct": False,
        "confirmed_root_cause": "A2L authentication token expired",
        "confirmed_fix": "Run 'a2l auth refresh' to renew token",
        "user_notes": "Token needs refresh weekly",
        "created_at": "2026-04-10T12:00:00",
    }
