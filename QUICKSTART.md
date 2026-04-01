# Quick Start Guide - Docker Compose

Run the Jenkins Failure Analysis Agent locally with a single command.

## Prerequisites

- Docker Desktop (Mac/Windows) or Docker + Docker Compose (Linux)
- 8GB+ RAM (16GB recommended for larger AI models)
- 10GB free disk space (for AI model, if using local Ollama)

## Deployment Modes

Choose the mode that fits your setup:

| Mode | Command | Best For |
|------|---------|----------|
| **Full Local** | `make start` | Self-contained, all in Docker |
| **External Ollama** | `make start-external-ollama` | Better GPU performance, shared Ollama |
| **Remote AI** | `make start-remote-ai` | OpenAI, Azure, vLLM server |

---

## Mode 1: Full Local Stack (Ollama in Docker)

Best for: Quick setup, isolated environment, no existing Ollama installation.

```bash
cd jenkins-failure-agent

# Setup (first run only - downloads ~4GB AI model)
make setup

# Edit .env with your Jenkins credentials
nano .env

# Start all services
make start

# Open the UI
open http://localhost:3000
```

**Services started:**
- Ollama (AI model server) — port 11434
- Agent (API server) — port 8080  
- UI (Dashboard) — port 3000

---

## Mode 2: External Ollama (on Host Machine)

Best for: Better GPU performance (native CUDA/Metal), shared Ollama instance, Apple Silicon Macs.

### Prerequisites

1. Install Ollama: https://ollama.ai/download
2. Start Ollama (or it runs as a service):
   ```bash
   ollama serve
   ```
3. Pull a model:
   ```bash
   ollama pull llama3:8b
   ```

### Start

```bash
cd jenkins-failure-agent

# Setup (verifies Ollama is running)
make setup-external-ollama

# Edit .env with your Jenkins credentials
nano .env

# Start agent and UI only
make start-external-ollama

# Open the UI
open http://localhost:3000
```

**Services started:**
- Agent (API server) — port 8080  
- UI (Dashboard) — port 3000
- Uses Ollama on host — port 11434

---

## Mode 3: Remote AI API (OpenAI, Azure, vLLM)

Best for: Using cloud AI, shared vLLM server, no local GPU.

> ⚠️ **Note:** Using cloud APIs means your Jenkins logs will be sent to the provider.

### Configure

Edit `.env` with your AI provider settings:

```bash
# OpenAI
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4
AI_API_KEY=sk-your-openai-key

# Azure OpenAI
AI_BASE_URL=https://your-resource.openai.azure.com/openai/deployments/your-deployment
AI_MODEL=gpt-4
AI_API_KEY=your-azure-key

# Remote vLLM server
AI_BASE_URL=http://your-vllm-server:8000/v1
AI_MODEL=meta-llama/Llama-3-70b-chat-hf
AI_API_KEY=your-api-key
```

### Start

```bash
cd jenkins-failure-agent

# Edit .env with your AI and Jenkins credentials
nano .env

# Start agent and UI
make start-remote-ai

# Open the UI
open http://localhost:3000
```

**Services started:**
- Agent (API server) — port 8080  
- UI (Dashboard) — port 3000
- Connects to your remote AI API

---

## Access the UI

Open your browser to: **http://localhost:3000**

The dashboard lets you:
- Enter job name and build number to analyze
- View root cause analysis with confidence scores
- See AI-powered fix recommendations
- Track Groovy library and configuration issues
- Monitor system health (Agent, AI, Jenkins)

## Configure Jenkins Connection

Edit `.env` with your Jenkins details:

```bash
# For Jenkins running on your host machine
JENKINS_URL=http://host.docker.internal:8080
JENKINS_USERNAME=admin
JENKINS_API_TOKEN=your-token-here

# For remote Jenkins
JENKINS_URL=https://jenkins.yourcompany.com
JENKINS_USERNAME=your-username
JENKINS_API_TOKEN=your-token-here
```

### Getting a Jenkins API Token

1. Log into Jenkins
2. Click your username → Configure
3. Add new Token → Generate
4. Copy the token to `.env`

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                       docker-compose                             │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │    Ollama    │    │    Agent     │    │      UI      │       │
│  │   (AI Model) │◄───│  (API Server)│◄───│  (Dashboard) │       │
│  │  Port 11434  │    │  Port 8080   │    │  Port 3000   │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│     (Docker or       │         │                   │             │
│      External)       ▼         │                   │             │
│                [agent_reports] │                   │             │
│                                │                   │             │
│                      ┌─────────┴─────┐             │             │
│                      │    Jenkins    │◄────────────┘             │
│                      │  (External)   │                           │
│                      └───────────────┘                           │
└─────────────────────────────────────────────────────────────────┘
```

| Service | Port | Description |
|---------|------|-------------|
| **UI** | 3000 | Web dashboard |
| **Agent** | 8080 | REST API |
| **Ollama** | 11434 | AI model server (local or external) |
| **Jenkins** | 8081 | Optional local (use `--profile with-jenkins`) |

## Using the Agent

### Option A: Web UI (Recommended)

1. Open http://localhost:3000
2. Enter job name (e.g., `my-project/main`)
3. Enter build number or check "Latest Failed"
4. Click "Analyze"
5. View results with root cause, recommendations, and detailed analysis

### Option B: HTTP API

```bash
# Analyze a specific build
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"job": "my-project", "build": 123}'

# Analyze latest failed build
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"job": "my-project", "latest_failed": true}'

# Check health
curl http://localhost:8080/health
```

### Option C: CLI Mode

```bash
# Analyze specific build
make analyze JOB=my-project BUILD=123

# Analyze latest failed
make analyze-latest JOB=my-project

# Test connections
make test-connection
```

## 6. Using Different AI Models

Edit `.env` to change models:

```bash
# Smaller/faster (default)
AI_MODEL=llama3:8b

# Larger/smarter (requires 32GB+ RAM)
AI_MODEL=llama3:70b

# Code-specialized
AI_MODEL=codellama:34b

# Mixture of experts
AI_MODEL=mixtral:8x7b
```

Then pull the new model:

```bash
docker-compose exec ollama ollama pull llama3:70b
# Update .env and restart
docker-compose restart agent
```

## 7. GPU Acceleration (NVIDIA)

Uncomment the GPU section in `docker-compose.yml`:

```yaml
ollama:
  # ... existing config ...
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

Then restart:

```bash
docker-compose down
docker-compose up -d
```

## 8. Running with Local Jenkins (for Testing)

Start the full stack including a local Jenkins:

```bash
# Start with Jenkins
docker-compose --profile with-jenkins up -d

# Jenkins will be at http://localhost:8081
# Get the initial admin password:
docker-compose exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

## 9. Troubleshooting

### Agent can't connect to Jenkins

```bash
# Check Jenkins URL is reachable from container
docker-compose exec agent curl -v $JENKINS_URL

# For host machine Jenkins, use:
JENKINS_URL=http://host.docker.internal:8080
```

### AI model is slow

```bash
# Check if model is loaded
docker-compose exec ollama ollama list

# Check resource usage
docker stats

# Use a smaller model
AI_MODEL=llama3:8b
```

### Out of memory

```bash
# Use a smaller model
AI_MODEL=llama3:8b

# Or increase Docker memory limit in Docker Desktop settings
```

### View analysis results

```bash
# Reports are saved to a Docker volume
docker-compose exec agent ls -la /app/reports/

# Copy reports out
docker cp jenkins-failure-agent:/app/reports ./local-reports/
```

## 10. API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/analyze` | POST | Analyze a build |
| `/results/{job}/{build}` | GET | Get cached result |
| `/webhook/jenkins` | POST | Jenkins notification webhook |

### POST /analyze

```json
{
  "job": "my-project",
  "build": 123,
  "workspace": "/path/to/workspace",
  "notify_slack": false,
  "generate_report": true
}
```

### Response

```json
{
  "build_info": { "job": "my-project", "build_number": 123 },
  "failure_analysis": {
    "category": "GROOVY_SANDBOX",
    "failed_stage": "Deploy",
    "confidence": 0.92
  },
  "root_cause": {
    "summary": "Sandbox rejection in deployToK8s library function",
    "details": "..."
  },
  "recommendations": [
    {
      "priority": "HIGH",
      "action": "Approve method in Script Security",
      "code_suggestion": "..."
    }
  ],
  "groovy_analysis": { ... },
  "config_analysis": { ... }
}
```

## Next Steps

1. Configure Slack notifications in `.env`
2. Set up Jenkins webhooks for automatic analysis
3. Try different AI models for your use case
4. Check `examples/JENKINS_INTEGRATION.md` for more integration patterns
