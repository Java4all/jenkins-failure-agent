# Jenkins Failure Analysis AI Agent

An autonomous AI-powered debugging assistant that analyzes Jenkins build failures, identifies root causes, and suggests fixes. Features **AI-driven tool relationship analysis**, **continuous learning from feedback**, and automatic reporting to Jenkins, PRs, and Slack.

## 🎯 What It Does

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   Jenkins Build FAILS  ──────▶  AI Agent Analyzes  ──────▶  Results        │
│                                                                             │
│   • Console log             • Parses 200+ tool types     • Root cause      │
│   • Test results            • Matches known patterns     • Confidence %    │
│   • Jenkinsfile             • AI semantic analysis       • Fix suggestion  │
│   • Shared libraries        • Learns from feedback       • Retry advice    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 📊 System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     JENKINS FAILURE ANALYSIS AGENT v1.9.25                  │
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   Jenkins   │    │   GitHub    │    │   Ollama    │    │   SQLite    │  │
│  │   Server    │    │   API       │    │   (LLM)     │    │  (Feedback) │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │          │
│         └──────────────────┴──────────────────┴──────────────────┘          │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         HYBRID ANALYZER                               │  │
│  │                                                                       │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │ Log Parser  │  │ RC Finder   │  │ RC Analyzer │  │ Investigator│  │  │
│  │  │ (200+ tools)│  │ (context)   │  │ (AI-driven) │  │ (MCP tools) │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  │                                                                       │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│  │  │  KNOWN_FAILURE_PATTERNS (25+) + FEW-SHOT LEARNING (from history)│ │  │
│  │  └─────────────────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│                                    ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                              WEB UI                                   │  │
│  │   Analysis Results │ 👍👎 Feedback │ Jenkins Settings │ History       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🔄 Two Analysis Modes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SELECT ANALYSIS MODE                                │
├─────────────────────────────────┬───────────────────────────────────────────┤
│                                 │                                            │
│   🔄 ITERATIVE (Default)        │   🔍 DEEP (Agentic)                        │
│   ─────────────────────────     │   ──────────────────                       │
│                                 │                                            │
│   Multi-call AI analysis        │   MCP Tool-based investigation            │
│   Up to 3 iterations            │   5-15 autonomous tool calls              │
│   Source code pre-loading       │   Dynamic source exploration              │
│   Confidence-based stopping     │   Cross-file tracing                      │
│                                 │                                            │
│   Best for:                     │   Best for:                               │
│   • Quick analysis (~10-30s)    │   • Complex failures (~30-60s)            │
│   • Known error patterns        │   • Multi-file issues                     │
│   • High confidence results     │   • Deep code investigation               │
│                                 │                                            │
│         ↓                       │            ↓                              │
│   ┌─────────────────┐           │   ┌─────────────────┐                     │
│   │  RC_Analyzer    │           │   │  Investigator   │                     │
│   │                 │           │   │                 │                     │
│   │  Iteration 1 ───┼─ 0.4      │   │  Tool Call 1    │                     │
│   │  Iteration 2 ───┼─ 0.6      │   │  Tool Call 2    │                     │
│   │  Iteration 3 ───┼─ 0.85 ✓   │   │  ...            │                     │
│   └─────────────────┘           │   │  Tool Call N    │                     │
│                                 │   └─────────────────┘                     │
└─────────────────────────────────┴───────────────────────────────────────────┘
```

## 🧠 AI-Driven Analysis Pipeline

### Complete Analysis Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ANALYSIS PIPELINE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STEP 1: Fetch Data from Jenkins                                            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐                 │
│  │ Build Info     │  │ Console Log    │  │ Test Results   │                 │
│  │ (status, time) │  │ (full output)  │  │ (JUnit XML)    │                 │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘                 │
│          └───────────────────┼───────────────────┘                          │
│                              ▼                                               │
│  STEP 2: Parse Log (200+ tool patterns)                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  • Extract errors, stages, methods                                    │   │
│  │  • Detect tool invocations: kubectl, docker, aws, npm, git...        │   │
│  │  • Build execution timeline                                           │   │
│  │  • Support: HH:MM:SS +, ISO timestamp, $ prefix (docker)             │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│  STEP 3: Find Root Cause Context                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  • Identify primary error line                                        │   │
│  │  • Extract surrounding 30 lines                                       │   │
│  │  • Find related tool invocations by identifier matching               │   │
│  │  • Extract identifiers (IDs, paths, credentials)                     │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│  STEP 4: AI Analysis (3 iterations max)                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  • Match KNOWN_FAILURE_PATTERNS (25+ patterns)                        │   │
│  │  • Inject few-shot examples from feedback history                     │   │
│  │  • Send TOOL INVOCATIONS to AI for relationship analysis             │   │
│  │  • Parse response (JSON or Natural Language for Ollama)              │   │
│  │  • Boost confidence based on pattern matches                          │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                              │                                               │
│                              ▼                                               │
│  STEP 5: Return Result                                                       │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │  {                                                                    │   │
│  │    "root_cause": "kubectl rollout timed out - pod OOMKilled",        │   │
│  │    "category": "INFRASTRUCTURE",                                      │   │
│  │    "confidence": 0.85,                                                │   │
│  │    "failing_tool": {"tool_name": "kubectl", "line": 1234},           │   │
│  │    "fix": "Increase memory limit in deployment.yaml",                │   │
│  │    "is_retriable": true                                               │   │
│  │  }                                                                    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### AI Tool Relationship Analysis

The AI doesn't just guess - it sees ALL tool invocations and identifies which one failed:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                   AI-DRIVEN TOOL RELATIONSHIP ANALYSIS                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ERROR MESSAGE:                                                              │
│  "ERROR: Could not find credentials entry with ID 'CI_GB-SVC-SHPE-PRD'"     │
│                                                                              │
│  TOOL INVOCATIONS SENT TO AI:                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ ## TOOL INVOCATIONS ##                                                 │ │
│  │ Identify which tool (by line number) is MOST RELATED to the error.    │ │
│  │ ──────────────────────────────────────────────────────────────────────│ │
│  │ [line 3] docker: docker top 00be608e763c8efd373cb -eo pid,comm        │ │
│  │ [line 5] aws: aws ssm get-parameter --name /apix/CI_GB-SVC-SHPE-PRD   │ │
│  │ [line 6] jq: jq .Parameter.Value                                       │ │
│  │ [line 10] cat: cat deployment/template.yaml                            │ │
│  │ ──────────────────────────────────────────────────────────────────────│ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  AI RESPONSE:                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ {                                                                      │ │
│  │   "root_cause": "Jenkins credentials 'CI_GB-SVC-SHPE-PRD' not         │ │
│  │                  configured. This credential is used by the AWS SSM    │ │
│  │                  command to fetch secrets.",                           │ │
│  │   "related_tool_line": 5,   ← AI identifies the AWS command           │ │
│  │   "category": "CREDENTIAL",                                            │ │
│  │   "confidence": 0.90                                                   │ │
│  │ }                                                                      │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    │                                         │
│                                    ▼                                         │
│  UI shows AWS command as "Failed Command" (not unrelated docker/cat)        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Known Failure Patterns (25+)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      KNOWN_FAILURE_PATTERNS                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  KUBERNETES                           DOCKER                                 │
│  ├── rollout timeout                  ├── daemon not running                 │
│  ├── resource not found               ├── registry auth failed               │
│  ├── connection refused               ├── image not found                    │
│  └── RBAC permission denied           └── disk space exhausted               │
│                                                                              │
│  HELM                                 TERRAFORM                              │
│  ├── release deployment failed        ├── state lock conflict                │
│  └── chart not found                  └── provider installation failed       │
│                                                                              │
│  AWS CLI                              GIT                                    │
│  ├── credentials not found            ├── SSH authentication failed          │
│  └── IAM permission denied            └── HTTPS authentication failed        │
│                                                                              │
│  NPM/YARN                             MAVEN/GRADLE                           │
│  ├── package not found                ├── dependency resolution failed       │
│  └── EACCES permission error          └── compilation error                  │
│                                                                              │
│  When pattern matches → AI gets guidance + minimum confidence floor          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 📝 Feedback & Learning System

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      FEEDBACK & LEARNING SYSTEM                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                         ┌─────────────────┐                                  │
│                         │     USER        │                                  │
│                         └────────┬────────┘                                  │
│                                  │                                           │
│            Was this analysis helpful?                                        │
│                                  │                                           │
│              ┌───────────────────┼───────────────────┐                       │
│              ▼                   ▼                   ▼                       │
│        ┌──────────┐        ┌──────────┐       ┌──────────────┐              │
│        │  👍 Yes  │        │  👎 No   │       │ 📝 Correction│              │
│        └────┬─────┘        └────┬─────┘       └──────┬───────┘              │
│             │                   │                    │                       │
│             └───────────────────┼────────────────────┘                       │
│                                 │                                            │
│                                 ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                    FEEDBACK STORE (SQLite)                            │   │
│  │  /app/data/feedback.db                                                │   │
│  ├──────────────────────────────────────────────────────────────────────┤   │
│  │ id │ job_name │ category │ ai_answer   │ confirmed    │ correct      │   │
│  │ 1  │ deploy   │ INFRA    │ timeout...  │ OOMKilled    │ false        │   │
│  │ 2  │ build    │ BUILD    │ npm failed  │ npm failed   │ true         │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                 │                                            │
│              ┌──────────────────┴──────────────────┐                         │
│              ▼                                     ▼                         │
│  ┌────────────────────────┐          ┌────────────────────────────┐         │
│  │   FEW-SHOT LEARNING    │          │   FINE-TUNING EXPORT       │         │
│  │   (Real-time)          │          │   (Batch)                  │         │
│  │                        │          │                            │         │
│  │ Similar cases injected │          │ GET /feedback/export       │         │
│  │ into AI prompt:        │          │ → JSONL format             │         │
│  │                        │          │ → OpenAI fine-tuning       │         │
│  │ ## SIMILAR PAST CASES  │          │ → Ollama training          │         │
│  │ Case 1: INFRASTRUCTURE │          │                            │         │
│  │ Error: kubectl timeout │          │                            │         │
│  │ Fix: Increase memory   │          │                            │         │
│  └────────────────────────┘          └────────────────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Docker Compose (Recommended)

```bash
# Clone and start
git clone <repo>
cd jenkins-failure-agent
cp .env.example .env
# Edit .env with your Jenkins URL, credentials

# Start all services (Agent + Ollama + UI)
docker-compose up -d

# Open the UI
open http://localhost:3000
```

### API Usage

```bash
# Analyze a build (iterative mode - default)
curl -X POST http://localhost:8080/analyze \
    -H "Content-Type: application/json" \
    -d '{"job": "my-project", "build": 123}'

# Deep investigation mode
curl -X POST http://localhost:8080/analyze \
    -H "Content-Type: application/json" \
    -d '{"job": "my-project", "build": 123, "deep": true}'

# Get feedback stats
curl http://localhost:8080/feedback/stats

# Export for fine-tuning
curl http://localhost:8080/feedback/export?format=jsonl > training.jsonl
```

## 📋 Failure Categories

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          FAILURE CATEGORIES (17)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CATEGORY          │ DESCRIPTION                    │ RETRIABLE             │
│  ──────────────────┼────────────────────────────────┼─────────────────────  │
│  CREDENTIAL        │ Auth/token failures            │ Sometimes             │
│  NETWORK           │ Connection/timeout issues      │ Usually Yes           │
│  PERMISSION        │ Access denied/RBAC             │ No                    │
│  INFRASTRUCTURE    │ K8s/Docker/resource issues     │ Sometimes             │
│  CONFIGURATION     │ Config/YAML errors             │ No                    │
│  BUILD             │ Compilation/dependency         │ No                    │
│  TEST              │ Test failures                  │ No                    │
│  GROOVY_LIBRARY    │ Jenkins shared library         │ No                    │
│  GROOVY_CPS        │ CPS transformation errors      │ No                    │
│  TOOL_ERROR        │ CLI tool failures              │ Sometimes             │
│  TIMEOUT           │ Step/build timeout             │ Yes                   │
│  UNKNOWN           │ Unclassified                   │ Unknown               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 📁 Project Structure

```
jenkins-failure-agent/
├── agent.py                    # CLI entry point
├── config.yaml                 # Configuration
├── docker-compose.yml          # Full stack deployment
├── ARCHITECTURE.md             # Detailed architecture docs
├── CHANGELOG.md                # Version history
│
├── ui/
│   └── index.html              # Web dashboard (React)
│
└── src/
    ├── server.py               # FastAPI REST server
    ├── hybrid_analyzer.py      # Orchestrates analysis modes
    ├── rc_analyzer.py          # AI-driven root cause (iterative)
    ├── rc_finder.py            # Error context extraction
    ├── log_parser.py           # Log parsing (200+ tools)
    ├── feedback_store.py       # SQLite + few-shot learning
    ├── jenkins_client.py       # Jenkins API
    ├── github_client.py        # GitHub source fetching
    └── agent/
        └── investigator.py     # MCP-based deep mode
```

## 📖 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Full system architecture with diagrams
- **[QUICKSTART.md](QUICKSTART.md)** - Docker quick start guide
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and stable checkpoints
- **[examples/JENKINS_INTEGRATION.md](examples/JENKINS_INTEGRATION.md)** - Jenkins pipeline integration

## 🏷️ Version History

| Version | Status | Key Features |
|---------|--------|--------------|
| **v1.9.25** | Current | Feedback voting UI, fine-tuning export |
| **v1.9.24** | Stable ✅ | Multi-style NL parser (Ollama support) |
| v1.9.21 | | Known failure patterns (25+) |
| v1.9.19 | | AI-driven tool relationship |
| v1.9.18 | Stable ✅ | Rule-based (rollback point) |

## License

MIT  
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
