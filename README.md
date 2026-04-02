# Jenkins Failure Analysis AI Agent

An autonomous AI-powered debugging assistant that analyzes Jenkins build failures, identifies root causes, and suggests fixes. Results are automatically pushed to Jenkins build descriptions, PR comments, and Slack.

## Architecture

The agent supports **three analysis modes**: fast scripted analysis, iterative root cause investigation, and deep agentic investigation:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Jenkins CI/CD Pipeline                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │  Build   │───▶│   Test   │───▶│  Deploy  │───▶│ On Failure Hook  │  │
│  └──────────┘    └──────────┘    └──────────┘    └────────┬─────────┘  │
└───────────────────────────────────────────────────────────┼─────────────┘
                                                            │
                                                            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Jenkins Failure Analysis Agent                        │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                     SELECT ANALYSIS MODE                         │    │
│  │                                                                  │    │
│  │     ⚡ Standard        🔄 Iterative          🔍 Deep            │    │
│  │     (default)         (recommended)         (--deep)            │    │
│  └──────────┬──────────────────┬──────────────────┬────────────────┘    │
│             │                  │                  │                      │
│             ▼                  ▼                  ▼                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │ Single AI Call   │  │ RC Finder Expert │  │ MCP Tool Agent   │      │
│  │ ~2 seconds       │  │ + Solution Finder│  │ 31 tools         │      │
│  │                  │  │ Multi-cycle      │  │ 5-15 tool calls  │      │
│  └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘      │
│           │                     │                     │                  │
│           └─────────────────────┴─────────────────────┘                  │
│                                 │                                        │
│                                 ▼                                        │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        Reporter Layer                              │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────┐  ┌─────────────┐  │  │
│  │  │   Jenkins   │  │  GitHub/    │  │  Slack  │  │   Reports   │  │  │
│  │  │ Description │  │  GitLab PR  │  │         │  │ JSON/MD/HTML│  │  │
│  │  └─────────────┘  └─────────────┘  └─────────┘  └─────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Analysis Modes

| Mode | Flag | Speed | Use Case |
|------|------|-------|----------|
| **Standard** | Default | ⚡ Fast (1 AI call, ~2s) | Simple errors, quick triage |
| **Iterative** | `--iterative` | 🔄 Smart (3-5 cycles, ~10-30s) | **Recommended** - finds root cause + generates fix with code |
| **Deep** | `--deep` | 🔍 Thorough (5-15 tool calls, ~30-60s) | Complex library/code issues |

### Iterative Mode (Recommended)

The iterative mode uses a **multi-call AI analysis** that iteratively narrows down the root cause:

```
┌────────────────────────────────────────────────────────────────────┐
│                    ITERATIVE ROOT CAUSE ANALYSIS                   │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  Iteration 1: Initial Context                                      │
│  ┌──────────────────────────────────────────────────┐             │
│  │ RootCauseFinder → Extract error + 30 lines       │             │
│  │ AI Call #1 → "Error in deployService(), need     │             │
│  │               source code" (confidence: 0.4)     │             │
│  │               needs_source: [vars/deployService] │             │
│  └──────────────────────────────────────────────────┘             │
│                         ↓                                          │
│  Iteration 2: With Source Code                                     │
│  ┌──────────────────────────────────────────────────┐             │
│  │ GitHub → Fetch vars/deployService.groovy         │             │
│  │ AI Call #2 → "Line 42 calls awsHelper(), need    │             │
│  │               that file" (confidence: 0.55)      │             │
│  │               needs_source: [vars/awsHelper]     │             │
│  └──────────────────────────────────────────────────┘             │
│                         ↓                                          │
│  Iteration 3: With Dependencies                                    │
│  ┌──────────────────────────────────────────────────┐             │
│  │ GitHub → Fetch vars/awsHelper.groovy             │             │
│  │ AI Call #3 → "Found! SSM param ABC missing"      │             │
│  │               (confidence: 0.85) ✓ THRESHOLD     │             │
│  └──────────────────────────────────────────────────┘             │
│                         ↓                                          │
│  RESULT                                                            │
│  ┌──────────────────────────────────────────────────┐             │
│  │ root_cause: "SSM param ABC missing in eu-west-1" │             │
│  │ category: CREDENTIAL                              │             │
│  │ confidence: 0.85                                  │             │
│  │ fix: "aws ssm put-parameter --name ABC ..."       │             │
│  │ iterations_used: 3                                │             │
│  └──────────────────────────────────────────────────┘             │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

**Configuration** (`config.yaml`):
```yaml
rc_analyzer:
  enabled: true
  max_rc_iterations: 3       # Max AI calls per analysis
  confidence_threshold: 0.7  # Stop when confidence >= this
  max_source_context_chars: 8000  # Limit source code in prompts
```

**Key Features:**
- **Iterative refinement**: Each AI call can request additional source files
- **Source-aware classification**: Detects signature mismatches → GROOVY_LIBRARY
- **Confidence-based stopping**: Stops when confident, uses best result if max iterations reached
- **Previous analysis context**: Follow-up prompts include prior findings

## Key Features

### 5-Layer Architecture
1. **Collector**: Fetches logs, test reports, artifacts, Jenkinsfile, shared library code
2. **Preprocessor**: Extracts errors, stack traces, failed stage, library calls
3. **Classifier**: 3-tier classification (configuration / pipeline_misuse / external_system)
4. **AI Reasoner**: Root cause, exact fix, retry safety assessment
5. **Reporter**: Pushes results to Jenkins, GitHub/GitLab PRs, Slack

### 3-Tier Failure Classification
Every failure is classified into one of three tiers:

| Tier | Description | Examples | Retriable? |
|------|-------------|----------|------------|
| **Configuration** | User config issue | Missing credentials, wrong agent label, bad env vars | ❌ No |
| **Pipeline Misuse** | Code/Jenkinsfile bug | CPS errors, sandbox rejection, wrong parameters | ❌ No |
| **External System** | Transient/external | Network timeout, rate limit, flaky test | ✅ Often |

### Retry Safety Assessment
The agent tells you whether to retry or fix:

```json
{
  "retry_assessment": {
    "is_retriable": true,
    "confidence": 0.85,
    "reason": "Network timeout to external service - likely transient",
    "recommended_wait_seconds": 60,
    "max_retries": 2
  }
}
```

### Automatic Result Posting
- **Jenkins Build Description**: Shows tier badge, retry status, quick fix
- **GitHub/GitLab PR Comments**: Full analysis with affected files and recommendations
- **Slack Notifications**: Summary with priority and action items

### Groovy & Shared Library Analysis
- **CPS Stack Trace Decoding**: Filters Jenkins internals to show actual user code
- **Library Call Mapping**: Traces errors to exact `vars/` or `src/` functions
- **Sandbox Rejection Detection**: Identifies required script approvals
- **Serialization Issue Identification**: Finds non-serializable objects
- **Library Version Correlation**: Detects branch/tag mismatches
- **Method Call Sequence Tracking**: Tracks all library method invocations via configurable prefix tags
- **Pipeline Stage Sequence**: Full execution path of all stages including special characters

### Source Registry (v1.6.0)
- **Automatic Source Pre-loading**: Fetches source code for all active methods at failure time
- **Multi-Repo Search**: Searches across all registered library repos for method implementations
- **Runtime Registry Management**: Add/remove source locations via API or UI
- **Cross-Library Support**: Single method prefix tracks calls across multiple shared libraries

### Configuration Analysis  
- **Credential Validation**: Missing IDs, wrong types, binding failures
- **Environment Variable Tracking**: Unset variables, scope issues
- **Agent/Node Diagnostics**: Label mismatches, offline nodes
- **Plugin Dependency Checking**: Missing plugins, version conflicts

### MCP Tools for Agentic Investigation

When deep investigation is enabled, the LLM can use these tools:

**Jenkins Tools:**
- `get_console_log(job, build)` - Get build logs
- `search_console_log(job, build, pattern)` - Search for patterns
- `get_pipeline_stages(job, build)` - Get stage info
- `get_test_results(job, build)` - Get test failures

**Source Code Tools:**
- `get_library_file(library, path)` - Fetch shared library code
- `get_jenkinsfile(repo)` - Get Jenkinsfile
- `get_class_definition(library, class_name)` - Get Groovy class
- `get_function_signature(library, function)` - Get function details
- `search_library_code(library, query)` - Search code
- `get_blame(repo, path)` - See who changed what

**Investigation Tools:**
- `parse_stack_trace(trace)` - Parse stack traces
- `analyze_missing_method(error)` - Analyze method errors
- `find_credential_references(code)` - Find credential usage
- `compare_parameters(expected, actual)` - Compare signatures

## Installation

```bash
# Clone and install
cd jenkins-failure-agent
pip install -r requirements.txt

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your Jenkins and AI settings
```

## Configuration

Edit `config.yaml`:

```yaml
jenkins:
  url: "https://jenkins.yourcompany.com"
  username: "your-username"
  api_token: "your-api-token"

ai:
  # For Ollama
  base_url: "http://localhost:11434/v1"
  model: "llama3:70b"
  
  # For vLLM
  # base_url: "http://your-vllm-server:8000/v1"
  # model: "meta-llama/Llama-3-70b-chat-hf"
  
  # For any OpenAI-compatible API
  # base_url: "https://your-private-api.com/v1"
  # api_key: "your-api-key"
  # model: "your-model-name"

git:
  enabled: true
  lookback_commits: 10

# GitHub Enterprise - Required for analyzing custom Groovy libraries
github:
  enabled: true
  base_url: "https://github.yourcompany.com/api/v3"
  token: "ghp_your_token"
  
  # Map @Library names to repository paths
  library_mappings:
    "my-pipeline-lib": "platform/jenkins-shared-library"
    "common-steps": "devops/common-pipeline-steps"
```

### Why GitHub Integration Matters

For custom Groovy libraries, the AI needs to see your actual code to provide accurate analysis:

```
Without source code:
  Error: MissingPropertyException: No such property: environment
  AI says: "The property 'environment' is not defined"  (generic guess)

With source code:
  Error: MissingPropertyException: No such property: environment
  AI sees: deployApp.groovy expects 'environment' but Jenkinsfile passes 'env'
  AI says: "Change line 42: use 'environment' instead of 'env'"  (exact fix)
```

The agent automatically:
1. Parses `@Library('name@version')` declarations from your Jenkinsfile
2. Fetches the corresponding library code from GitHub Enterprise
3. Includes relevant source code in the AI analysis context
4. Traces errors to exact functions and line numbers

## Usage

### CLI Mode
```bash
# Analyze a specific build (fast scripted mode)
python agent.py analyze --job "my-project" --build 123

# Analyze with deep investigation (agentic mode)
python agent.py analyze --job "my-project" --build 123 --deep

# Analyze latest failed build
python agent.py analyze --job "my-project" --latest-failed

# Watch mode (continuous monitoring)
python agent.py watch --job "my-project"
```

### Jenkins Pipeline Integration with PR Comments
```groovy
// Add to your Jenkinsfile
post {
    failure {
        script {
            def prUrl = env.CHANGE_URL ?: ''
            def prSha = env.GIT_COMMIT ?: ''
            
            httpRequest(
                url: 'http://your-agent-server:8080/analyze',
                httpMode: 'POST',
                contentType: 'APPLICATION_JSON',
                requestBody: """{
                    "job": "${env.JOB_NAME}",
                    "build": ${env.BUILD_NUMBER},
                    "pr_url": "${prUrl}",
                    "pr_sha": "${prSha}",
                    "update_jenkins_description": true,
                    "post_to_pr": true
                }"""
            )
        }
    }
}
```

### As a Service with Docker Compose
```bash
# Quick start
cp .env.example .env
# Edit .env with your Jenkins credentials and SCM token
docker-compose up -d

# Open the UI
open http://localhost:3000
```

### HTTP API
```bash
# Standard analysis (auto-selects mode based on error type)
curl -X POST http://localhost:8080/analyze \
    -H "Content-Type: application/json" \
    -d '{
        "job": "my-project",
        "build": 123
    }'

# Force deep investigation (agentic mode)
curl -X POST http://localhost:8080/analyze \
    -H "Content-Type: application/json" \
    -d '{
        "job": "my-project",
        "build": 123,
        "deep": true,
        "pr_url": "https://github.com/org/repo/pull/456",
        "pr_sha": "abc123def"
    }'
```

## Output Example

```json
{
  "build_info": {
    "job": "backend-api",
    "build_number": 456,
    "status": "FAILURE",
    "duration": "4m 32s"
  },
  "failure_analysis": {
    "category": "GROOVY_SANDBOX",
    "tier": "pipeline_misuse",
    "failed_stage": "Deploy",
    "primary_error": "Scripts not permitted to use method java.lang.Runtime exec",
    "confidence": 0.95
  },
  "root_cause": {
    "summary": "Shared library deployToK8s() calls Runtime.exec() which requires script approval",
    "details": "The library function vars/deployToK8s.groovy line 42 calls Runtime.getRuntime().exec() to run kubectl. This method is blocked by the Jenkins sandbox.",
    "tier": "pipeline_misuse",
    "related_commits": ["abc123"],
    "affected_files": ["vars/deployToK8s.groovy"]
  },
  "retry_assessment": {
    "is_retriable": false,
    "confidence": 0.92,
    "reason": "Sandbox rejection requires code change or script approval - not a transient issue",
    "recommended_wait_seconds": 0,
    "max_retries": 0
  },
  "recommendations": [
    {
      "priority": "HIGH",
      "action": "Approve the method in Script Security or refactor to use Jenkins steps",
      "rationale": "Runtime.exec() is blocked by sandbox. Either approve 'method java.lang.Runtime exec java.lang.String[]' or use the sh step instead.",
      "code_suggestion": "// Replace Runtime.exec() with:\nsh 'kubectl apply -f deployment.yaml'",
      "estimated_effort": "5 minutes"
    }
  ],
  "metadata": {
    "analysis_duration_ms": 2340,
    "model_used": "llama3:8b",
    "jenkins_description_updated": true,
    "pr_comment_posted": true
  }
}
```

## Project Structure

```
jenkins-failure-agent/
├── agent.py                    # CLI entry point
├── config.example.yaml         # Configuration template
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container build
├── docker-compose.yml          # Full stack (Ollama + Agent + UI)
├── docker-compose.external-ollama.yml  # External Ollama mode
├── docker-compose.remote-ai.yml        # Remote AI API mode
├── Makefile                    # Convenience commands
├── QUICKSTART.md               # Docker quick start guide
├── ui/
│   ├── index.html              # Web dashboard
│   └── nginx.conf              # UI proxy config
├── examples/
│   └── JENKINS_INTEGRATION.md  # Integration patterns
└── src/
    ├── __init__.py
    ├── config.py               # Configuration loader
    ├── jenkins_client.py       # Jenkins API + build description updater
    ├── log_parser.py           # Log parsing and categorization
    ├── git_analyzer.py         # Git correlation and risk scoring
    ├── github_client.py        # GitHub source code fetching
    ├── groovy_analyzer.py      # Groovy/CPS/Sandbox analysis
    ├── config_analyzer.py      # Credential/Env/Agent analysis
    ├── ai_analyzer.py          # AI engine (scripted mode)
    ├── hybrid_analyzer.py      # Hybrid mode orchestrator (NEW)
    ├── scm_client.py           # GitHub/GitLab PR comments
    ├── report_generator.py     # Report generation
    ├── server.py               # HTTP API server
    ├── mcp/                    # MCP Tools (NEW)
    │   ├── __init__.py
    │   ├── registry.py         # Tool registration system
    │   ├── executor.py         # Tool execution engine
    │   ├── jenkins_tools.py    # Jenkins investigation tools
    │   ├── github_tools.py     # Source code investigation tools
    │   └── investigation_tools.py  # Error analysis tools
    └── agent/                  # Agentic Investigator (NEW)
        ├── __init__.py
        ├── prompts.py          # Investigation prompts
        └── investigator.py     # Main agent loop
```

## Failure Categories

The agent classifies failures into detailed categories, each mapped to a 3-tier model:

| Category | Tier | Description |
|----------|------|-------------|
| `CREDENTIAL_ERROR` | Configuration | Missing/wrong credentials |
| `CONFIGURATION` | Configuration | General config errors |
| `AGENT_ERROR` | Configuration | Node/label issues |
| `GROOVY_LIBRARY` | Pipeline Misuse | Shared library loading failures |
| `GROOVY_CPS` | Pipeline Misuse | CPS transformation errors |
| `GROOVY_SANDBOX` | Pipeline Misuse | Script security rejections |
| `GROOVY_SERIALIZATION` | Pipeline Misuse | Non-serializable pipeline objects |
| `PLUGIN_ERROR` | Pipeline Misuse | Missing/incompatible plugins |
| `COMPILATION_ERROR` | Pipeline Misuse | Build compilation failures |
| `TEST_FAILURE` | External System | Test failures |
| `DEPENDENCY` | External System | Dependency resolution errors |
| `INFRASTRUCTURE` | External System | OOM, disk space, etc. |
| `NETWORK` | External System | Connection failures |
| `TIMEOUT` | External System | Operation timeouts |

### Tier Decision Logic

```
┌─────────────────────────────────────────────────────────────────┐
│                    Is it retriable?                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Configuration Tier → ❌ NO                                      │
│    Missing credentials, wrong labels, bad env vars               │
│    Action: Fix Jenkins/job config                                │
│                                                                  │
│  Pipeline Misuse Tier → ❌ NO                                    │
│    CPS errors, sandbox issues, wrong parameters                  │
│    Action: Fix Jenkinsfile or library code                       │
│                                                                  │
│  External System Tier → ✅ MAYBE                                 │
│    Network timeout, rate limit, flaky test                       │
│    Action: Retry with backoff, or fix upstream                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## License

MIT
