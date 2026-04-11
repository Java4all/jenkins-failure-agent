# Jenkins Failure Analysis AI Agent

AI-powered debugging assistant that analyzes Jenkins build failures, identifies root causes, and suggests fixes. Features **continuous learning from user feedback** and a complete **AI Learning System** for knowledge management and fine-tuning.

## What It Does

```
🔴 Jenkins Build FAILS  ──▶  🧠 AI Analyzes  ──▶  ✅ Result
                                                    
• Console log              • 200+ tool patterns     • Root cause
• Test results             • Known failure patterns • Confidence %  
• Source code              • Few-shot learning      • Fix suggestion
                           • Knowledge Store        • Training data
```

## Quick Start

```bash
# 1. Clone and configure
git clone <repo> && cd jenkins-failure-agent
cp .env.example .env
# Edit .env with Jenkins URL + credentials

# 2. Start (includes Ollama + UI)
make start

# 3. Open UI
open http://localhost:3000
```

## AI Providers

Supports multiple AI backends — use local models or cloud APIs:

| Provider | Command | Models |
|----------|---------|--------|
| **Ollama** (default) | `make start` | llama3, codellama, mixtral |
| **AWS Bedrock** | `make start-bedrock` | Claude, Titan, Llama, Mistral |
| **OpenAI/Azure** | `make start-remote-ai` | GPT-4, GPT-3.5 |
| **vLLM/LocalAI** | `make start-external-ollama` | Any supported model |

### AWS Bedrock Setup

```bash
# 1. Configure config.yaml
ai:
  provider: "bedrock"
  model: "claude-3-sonnet"      # or claude-3-haiku, llama3-70b, etc.
  region: "us-east-1"
  profile: "my-aws-profile"     # Your AWS CLI profile

# 2. Start (auto-mounts ~/.aws for credentials)
make start-bedrock
```

Supports all AWS authentication methods: profiles, SSO, IAM roles, environment variables.

## Two Analysis Modes

| Mode | Speed | Use Case |
|------|-------|----------|
| 🔄 **Iterative** (default) | ~10-30s | Quick analysis, known patterns |
| 🔍 **Deep** | ~30-60s | Complex failures, code tracing |

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      JENKINS FAILURE AGENT v2.0                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │   ANALYSIS UI   │    │  KNOWLEDGE UI   │    │  TRAINING UI    │         │
│  │  Analyze builds │    │  Manage tools   │    │  Export data    │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
│           └──────────────────────┴──────────────────────┘                   │
│                                  │                                          │
│  ┌───────────────────────────────┴───────────────────────────────┐         │
│  │                         REST API                               │         │
│  │  /analyze  /knowledge/*  /training/*  /feedback  /health      │         │
│  └───────────────────────────────────────────────────────────────┘         │
│                                  │                                          │
│  ┌───────────┬───────────────────┼───────────────────┬───────────┐         │
│  │ Jenkins   │   AI Provider     │   Knowledge Store │  Training │         │
│  │ + GitHub  │   (Ollama/etc)    │   (SQLite)        │  Pipeline │         │
│  └───────────┴───────────────────┴───────────────────┴───────────┘         │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────┐         │
│  │  feedback.db  │  knowledge.db  │  training.db  │  exports/    │         │
│  └───────────────────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Features

### AI-Driven Tool Detection
```
ERROR: "Could not find credentials 'CI_GB-SVC-SHPE-PRD'"

Tool invocations sent to AI:
  [line 3] docker: docker top 00be608e...        ← Not related
  [line 5] aws: aws ssm get-parameter --name CI_GB-SVC-SHPE-PRD  ← AI picks this!
  [line 6] jq: jq .Parameter.Value               ← Not related

Result: AI identifies AWS command as failing tool (not docker or jq)
```

### Known Failure Patterns (25+)
- **Kubernetes**: rollout timeout, RBAC denied, resource not found
- **Docker**: daemon not running, auth failed, image not found
- **AWS/Terraform/Helm**: credentials, state locks, chart errors
- **Build tools**: npm/maven/gradle dependency failures

### Feedback & Learning
```
User votes 👍/👎 → SQLite stores feedback
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
  Few-Shot Learning                Fine-Tuning Export
  (Real-time, in-prompt)           (GET /feedback/export)
```

## AI Learning System (v2.0)

The AI Learning System enables continuous improvement through knowledge management and fine-tuning data generation.

### Three UI Tabs

| Tab | Purpose |
|-----|---------|
| **Analysis** | Analyze build failures, view results, provide feedback |
| **Knowledge** | Manage tools, import docs, view error patterns |
| **Training** | Create training jobs, export data for fine-tuning |

### Knowledge Store

Store and manage tool definitions with error patterns:

```bash
# List all tools
curl http://localhost:8080/knowledge/tools

# Add a tool (JSON)
curl -X POST http://localhost:8080/knowledge/tools \
  -H "Content-Type: application/json" \
  -d '{"name": "a2l", "category": "deployment", "errors": [...]}'

# Import from documentation URL
curl -X POST http://localhost:8080/knowledge/import-doc \
  -d '{"url": "https://wiki.example.com/a2l-cli"}'

# Identify tool from log text
curl "http://localhost:8080/knowledge/identify?query=a2l%20deploy%20--cluster"

# Match error pattern
curl "http://localhost:8080/knowledge/match-error?snippet=A2L_AUTH_FAILED"
```

### Training Pipeline

Export training data for AI fine-tuning:

```bash
# Create training job
curl -X POST http://localhost:8080/training/jobs \
  -H "Content-Type: application/json" \
  -d '{"name": "finetune-v1", "format": "jsonl_openai"}'

# Prepare job (imports from feedback + knowledge)
curl -X POST http://localhost:8080/training/jobs/1/prepare

# Export to file
curl -X POST http://localhost:8080/training/jobs/1/export

# Download exported file
curl http://localhost:8080/training/jobs/1/download -o training.jsonl
```

**Supported Formats:**
- `jsonl_openai` — OpenAI fine-tuning format
- `jsonl_anthropic` — Anthropic fine-tuning format  
- `csv` — Spreadsheet analysis
- `json` — Generic JSON export

## API Usage

```bash
# Analyze a build
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"job": "my-project", "build": 123}'

# Get feedback stats  
curl http://localhost:8080/feedback/stats

# Export for fine-tuning
curl http://localhost:8080/feedback/export?format=jsonl
```

## Failure Categories

| Category | Retriable | Examples |
|----------|-----------|----------|
| CREDENTIAL | Sometimes | Auth/token failures |
| NETWORK | Usually | Connection timeout |
| INFRASTRUCTURE | Sometimes | K8s/Docker issues |
| BUILD | No | Compilation errors |
| TEST | No | Test failures |
| CONFIGURATION | No | YAML/config errors |

## Project Structure

```
jenkins-failure-agent/
├── docker-compose.yml          # Ollama deployment (default)
├── docker-compose.bedrock.yml  # AWS Bedrock deployment
├── config.yaml                 # Main configuration
├── Makefile                    # make start, make start-bedrock, etc.
├── QUICKSTART.md               # Detailed setup guide
├── CHANGELOG.md                # Version history
├── pytest.ini                  # Test configuration
├── ui/index.html               # Web dashboard (3 tabs)
├── tests/                      # Test suite (70 tests)
│   ├── conftest.py             # Shared fixtures
│   ├── test_knowledge_store.py # Knowledge Store tests
│   ├── test_java_analyzer.py   # Java Analyzer tests
│   ├── test_doc_importer.py    # Doc Importer tests
│   ├── test_training_pipeline.py # Training Pipeline tests
│   └── test_integration.py     # Integration tests
└── src/
    ├── server.py               # REST API
    ├── ai_provider.py          # Multi-provider AI abstraction
    ├── hybrid_analyzer.py      # Analysis orchestrator
    ├── rc_analyzer.py          # AI root cause (iterative)
    ├── log_parser.py           # Tool detection (200+)
    ├── feedback_store.py       # Feedback learning system
    ├── knowledge_store.py      # Tool/error knowledge (v2.0)
    ├── java_analyzer.py        # Java CLI source analyzer (v2.0)
    ├── doc_importer.py         # Documentation importer (v2.0)
    └── training_pipeline.py    # Training data export (v2.0)
```

## Testing

Run tests in Docker (no local Python required):

```bash
# Run all tests (70 tests)
make test

# Run unit tests only (fast)
make test-unit

# Run integration tests
make test-integration

# Run specific test file
make test-file FILE=test_knowledge_store.py

# Run with full output
make test-verbose
```

Or with local Python:

```bash
pip install pytest pyyaml beautifulsoup4
pytest tests/ -v
```

## Documentation

- **[QUICKSTART.md](QUICKSTART.md)** — Detailed deployment & configuration
- **[CHANGELOG.md](CHANGELOG.md)** — Version history & stable checkpoints

## Version

**Current: v2.0.0** | [View changelog](CHANGELOG.md)

### What's New in v2.0

- **Knowledge Store** — SQLite database for tool definitions and error patterns
- **Doc Importer** — Import tool knowledge from documentation URLs
- **Java Analyzer** — Extract CLI patterns from Java source (Spring Shell, Picocli)
- **Training Pipeline** — Export training data for AI fine-tuning
- **UI Tabs** — Analysis, Knowledge, and Training tabs
- **Test Suite** — 70 automated tests

## License

MIT
