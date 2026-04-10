# Jenkins Failure Analysis AI Agent

AI-powered debugging assistant that analyzes Jenkins build failures, identifies root causes, and suggests fixes. Features **continuous learning from user feedback**.

## What It Does

```
🔴 Jenkins Build FAILS  ──▶  🧠 AI Analyzes  ──▶  ✅ Result
                                                    
• Console log              • 200+ tool patterns     • Root cause
• Test results             • Known failure patterns • Confidence %  
• Source code              • Few-shot learning      • Fix suggestion
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
┌─────────────────────────────────────────────────────────────────────────┐
│                         JENKINS FAILURE AGENT                            │
│                                                                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐   ┌──────────┐     │
│  │ Jenkins  │   │  GitHub  │   │   AI Provider    │   │  SQLite  │     │
│  │  Server  │   │   API    │   │ ┌──────────────┐ │   │(Feedback)│     │
│  │          │   │          │   │ │Ollama/Bedrock│ │   │          │     │
│  │          │   │          │   │ │OpenAI/vLLM   │ │   │          │     │
│  └────┬─────┘   └────┬─────┘   │ └──────────────┘ │   └────┬─────┘     │
│       └──────────────┴─────────┴────────┬─────────┴────────┘           │
│                                         │                               │
│                                         ▼                               │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                      HYBRID ANALYZER                               │  │
│  │  Log Parser → RC Finder → RC Analyzer → Result                    │  │
│  │  (200+ tools)  (context)   (AI + patterns)                        │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                         │                               │
│                                         ▼                               │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  WEB UI: Results │ 👍👎 Feedback │ Settings │ History              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
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
├── ui/index.html               # Web dashboard
└── src/
    ├── server.py               # REST API
    ├── ai_provider.py          # Multi-provider AI abstraction
    ├── hybrid_analyzer.py      # Analysis orchestrator
    ├── rc_analyzer.py          # AI root cause (iterative)
    ├── log_parser.py           # Tool detection (200+)
    └── feedback_store.py       # Learning system
```

## Documentation

- **[QUICKSTART.md](QUICKSTART.md)** — Detailed deployment & configuration
- **[CHANGELOG.md](CHANGELOG.md)** — Version history & stable checkpoints

## Version

**Current: v1.9.28** | [View changelog](CHANGELOG.md)

## License

MIT
