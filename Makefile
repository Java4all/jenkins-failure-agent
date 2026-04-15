# Jenkins Failure Analysis Agent - Makefile
# 
# Usage:
#   make help        - Show available commands
#   make start       - Start all services
#   make analyze     - Run CLI analysis

.PHONY: help how-it-runs start stop logs build clean analyze test shell pull-model backup restore \
	api-analyze api-analyze-iterative api-analyze-deep api-analyze-latest-failed api-health

# Base URL for API examples (override: make api-health API_BASE=http://127.0.0.1:8080)
API_BASE ?= http://localhost:8080

# Deployment mode (can be overridden)
COMPOSE_FILE ?= docker-compose.yml

# Backup settings
BACKUP_DIR ?= ./backups
# Cross-platform timestamp (works on Windows, Mac, Linux)
ifeq ($(OS),Windows_NT)
    TIMESTAMP := $(shell powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'")
else
    TIMESTAMP := $(shell date +%Y%m%d-%H%M%S)
endif

# Default target
help:
	@echo "Jenkins Failure Analysis Agent v2.0"
	@echo ""
	@echo "How it runs (at a glance):"
	@echo "  1. make start (or start-external-ollama / start-remote-ai / …)"
	@echo "     → docker-compose starts services (see target output for ports)."
	@echo "  2. UI (port 3000) is static + JS; it talks to the Agent HTTP API (port 8080)."
	@echo "  3. Ollama or your AI backend (e.g. 11434) answers LLM calls from the agent."
	@echo "  4. On analyze: Agent → Jenkins API (log + build metadata) → log parse →"
	@echo "     HybridAnalyzer: default mode is iterative (multi-call RC loop); use mode=deep"
	@echo "     for full agentic/MCP-style investigation (UI “Deep” or API mode deep)."
	@echo "  5. CLI: make analyze* runs agent-cli → agent.py analyze (same pipeline, no HTTP)."
	@echo "  More detail:  make how-it-runs"
	@echo ""
	@echo "Deployment Modes (Build from Source):"
	@echo "  make start                    - Start with Ollama in Docker (default)"
	@echo "  make start-external-ollama    - Start with Ollama on host machine"
	@echo "  make start-remote-ai          - Start with remote AI API (OpenAI, etc.)"
	@echo "  make start-bedrock            - Start with AWS Bedrock (Claude, Titan, Llama)"
	@echo ""
	@echo "Deployment Modes (Pre-built Images - No Build Required):"
	@echo "  make start-prebuilt           - Pre-built image + Ollama in Docker"
	@echo "  make start-prebuilt-external  - Pre-built image + Ollama on host"
	@echo ""
	@echo "Setup:"
	@echo "  make setup                    - First-time setup (copy .env, pull model)"
	@echo "  make setup-external-ollama    - Setup for external Ollama"
	@echo "  make setup-deep               - Setup for deep investigation (larger model)"
	@echo "  make setup-bedrock            - Setup for AWS Bedrock"
	@echo ""
	@echo "Backup/Restore (migrate between environments):"
	@echo "  make backup                   - Backup all data (DBs, config, exports)"
	@echo "  make backup-full              - Full backup including AI models (~4GB)"
	@echo "  make restore FILE=<backup>    - Restore from backup file"
	@echo "  make backup-list              - List available backups"
	@echo ""
	@echo "Stop/Clean:"
	@echo "  make stop                     - Stop all services (DATA PRESERVED)"
	@echo "  make clean                    - Stop + DELETE ALL DATA (feedback, models, reports)"
	@echo ""
	@echo "Usage:"
	@echo "  make ui                       - Open the web dashboard"
	@echo "  make analyze JOB=x BUILD=123  - CLI: analyze build (iterative RC by default)"
	@echo "  make analyze-deep JOB=x BUILD=123  - CLI: --deep (agentic investigation)"
	@echo "  make analyze-latest JOB=x     - CLI: latest failed build"
	@echo "  make test-connection          - Test Jenkins & AI connection"
	@echo ""
	@echo "HTTP API (agent must be up: make start):"
	@echo "  make api-health               - GET  $(API_BASE)/health"
	@echo "  make api-analyze JOB=x BUILD=y - POST /analyze (default mode iterative)"
	@echo "  make api-analyze-iterative …   - same, mode explicit + fewer side effects"
	@echo "  make api-analyze-deep …        - POST /analyze with mode=deep"
	@echo "  make api-analyze-latest-failed JOB=x - POST latest failed, iterative"
	@echo ""
	@echo "Development:"
	@echo "  make build                    - Rebuild agent container"
	@echo "  make logs                     - Follow agent logs"
	@echo "  make logs-bedrock             - Follow logs (Bedrock mode)"
	@echo "  make shell                    - Shell into agent container"
	@echo ""
	@echo "Testing (runs in Docker, no local Python needed):"
	@echo "  make test                     - Run all tests (70 tests)"
	@echo "  make test-unit                - Run unit tests only (fast)"
	@echo "  make test-integration         - Run integration tests"
	@echo "  make test-verbose             - Run tests with full output"
	@echo "  make test-image-rebuild       - Rebuild test image (after dep changes)"
	@echo "  make test-clean               - Remove test image"
	@echo ""
	@echo "AI Models (for local Ollama):"
	@echo "  make pull-model MODEL=llama3:70b  - Pull a different model"
	@echo "  make pull-model-deep              - Pull recommended model for deep analysis"
	@echo "  make list-models                  - List available models"
	@echo ""
	@echo "Docker Hub (multi-arch: amd64 + arm64):"
	@echo "  make docker-setup-buildx            - One-time setup for multi-arch"
	@echo "  make docker-release DOCKER_REPO=u/r - Build + Push (amd64 + arm64)"
	@echo "  make docker-build-local DOCKER_REPO=u/r - Build local only (no push)"

# Longer narrative (what runs where, and what each layer does)
how-it-runs:
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo "  Runtime layout (typical: make start)"
	@echo "═══════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "  [Browser]  http://localhost:3000"
	@echo "       │     Static UI; set API base in the UI if not on same host."
	@echo "       ▼"
	@echo "  [Agent]    $(API_BASE)"
	@echo "       │     FastAPI: /health, POST /analyze, feedback, Splunk hooks, …"
	@echo "       │     Loads config.yaml + .env (Jenkins, AI, optional Splunk/SCM)."
	@echo "       ├────► [Jenkins]  JENKINS_URL — console log, build info, test reports"
	@echo "       ├────► [AI]       AI_BASE_URL / Bedrock / … — root-cause + recommendations"
	@echo "       └────► [Optional] GitHub/SCM — PR comments; Splunk — log sync"
	@echo ""
	@echo "  Analyze request path (POST /analyze):"
	@echo "    • mode omitted or \"iterative\" → HybridAnalyzer iterative RC loop (default)."
	@echo "    • mode \"deep\" → deep agentic path (MCP/tools as configured)."
	@echo "    • Build must be FAILURE/UNSTABLE (SUCCESS/ABORTED return skip reasons)."
	@echo ""
	@echo "  CLI (make analyze / analyze-deep):"
	@echo "    docker-compose --profile cli run agent-cli …"
	@echo "    → same core code as the API, without going through HTTP."
	@echo ""
	@echo "  See also:  make help"
	@echo ""

# =============================================================================
# Setup
# =============================================================================

setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "[OK] Created .env from template"; \
	fi
	@echo ""
	@echo "Starting Ollama and pulling AI model..."
	docker-compose up -d ollama
	docker-compose run --rm ollama-pull
	@echo ""
	@echo "[OK] Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env with your Jenkins credentials"
	@echo "  2. Run: make start"
	@echo "  3. Open: http://localhost:3000"

setup-deep:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "[OK] Created .env from template"; \
	fi
	@echo ""
	@echo "Setting up for deep investigation mode..."
	@echo "This requires a larger AI model for best results."
	@echo ""
	docker-compose up -d ollama
	@echo "Pulling llama3:70b (this will take a while, ~40GB)..."
	docker-compose exec ollama ollama pull llama3:70b
	@echo ""
	@echo "[OK] Setup complete!"
	@echo ""
	@echo "To use the 70B model, update .env:"
	@echo "  AI_MODEL=llama3:70b"
	@echo ""
	@echo "Then run: make start"

setup-external-ollama:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "[OK] Created .env from template"; \
	fi
	@echo ""
	@echo "Checking Ollama on host machine..."
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || \
		(echo "[FAIL] Ollama not running! Start it with: ollama serve" && exit 1)
	@echo "[OK] Ollama is running"
	@echo ""
	@echo "Checking for llama3:8b model..."
	@curl -s http://localhost:11434/api/tags | grep -q "llama3:8b" || \
		(echo "Pulling llama3:8b model..." && ollama pull llama3:8b)
	@echo "[OK] Model ready"
	@echo ""
	@echo "Setup complete! Next steps:"
	@echo "  1. Edit .env with your Jenkins credentials"
	@echo "  2. Run: make start-external-ollama"
	@echo "  3. Open: http://localhost:3000"

setup-bedrock:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "[OK] Created .env from template"; \
	fi
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│                    AWS Bedrock Setup                           │"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""
	@echo "Step 1: Configure .env with:"
	@echo ""
	@echo "  # Jenkins credentials"
	@echo "  JENKINS_URL=https://jenkins.example.com"
	@echo "  JENKINS_USERNAME=admin"
	@echo "  JENKINS_API_TOKEN=your-token"
	@echo ""
	@echo "  # AWS Bedrock"
	@echo "  AI_PROVIDER=bedrock"
	@echo "  AI_MODEL=claude-3-sonnet"
	@echo "  AI_PROFILE=your-aws-profile"
	@echo "  AWS_REGION=us-east-1"
	@echo ""
	@echo "Step 2: Verify your AWS profile works:"
	@echo "  aws sts get-caller-identity --profile your-aws-profile"
	@echo ""
	@echo "Step 3: Start the agent:"
	@echo "  make start-bedrock"
	@echo ""
	@echo "Note: Your ~/.aws directory will be mounted automatically."
	@echo ""

# =============================================================================
# Start/Stop Services
# =============================================================================

start:
	@echo "Starting stack: docker-compose up -d  (see docker-compose.yml for services)"
	docker-compose up -d
	@echo ""
	@echo "[OK] Services running:"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080  (POST /analyze, GET /health)"
	@echo "  * Ollama:       http://localhost:11434"
	@echo ""
	@echo "  Typical flow:  make api-health  →  open UI  →  run analysis from UI or:"
	@echo "                 make api-analyze-latest-failed JOB=<folder/job>"
	@echo ""
	@echo "Use 'make logs' to follow agent logs"

start-external-ollama:
	@echo "Starting with external Ollama (on host machine)..."
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || \
		(echo "[FAIL] Ollama not running! Start it with: ollama serve" && exit 1)
	docker-compose -f docker-compose.external-ollama.yml up -d
	@echo ""
	@echo "[OK] Services running:"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080"
	@echo "  * Ollama:       http://localhost:11434 (host)"
	@echo ""
	@echo "Use 'make logs-external' to follow logs"

start-remote-ai:
	@if [ -z "$$AI_BASE_URL" ] && ! grep -q "^AI_BASE_URL=" .env 2>/dev/null; then \
		echo "[FAIL] AI_BASE_URL not set! Configure it in .env first."; \
		echo ""; \
		echo "Example for OpenAI:"; \
		echo "  AI_BASE_URL=https://api.openai.com/v1"; \
		echo "  AI_MODEL=gpt-4-turbo"; \
		echo "  AI_API_KEY=sk-your-key"; \
		exit 1; \
	fi
	@echo "Starting with remote AI API..."
	docker-compose -f docker-compose.remote-ai.yml up -d
	@echo ""
	@echo "[OK] Services running:"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080"
	@echo "  * AI:           Remote API"
	@echo ""
	@echo "Use 'make logs-remote' to follow logs"

start-bedrock:
	@echo "Starting with AWS Bedrock..."
	@echo ""
	@# Check if AWS credentials are available
	@if [ -z "$$AWS_PROFILE" ] && [ -z "$$AWS_ACCESS_KEY_ID" ] && ! grep -q "^AI_PROFILE=" .env 2>/dev/null && ! grep -q "^AWS_PROFILE=" .env 2>/dev/null; then \
		echo "┌────────────────────────────────────────────────────────────────┐"; \
		echo "│  AWS credentials not detected!                                 │"; \
		echo "│                                                                │"; \
		echo "│  Configure ONE of the following:                               │"; \
		echo "│                                                                │"; \
		echo "│  Option 1: AWS Profile (recommended)                           │"; \
		echo "│    - Set AI_PROFILE=your-profile in .env                       │"; \
		echo "│    - Your ~/.aws directory will be mounted automatically       │"; \
		echo "│                                                                │"; \
		echo "│  Option 2: Environment Variables                               │"; \
		echo "│    - Set AWS_ACCESS_KEY_ID in .env                             │"; \
		echo "│    - Set AWS_SECRET_ACCESS_KEY in .env                         │"; \
		echo "│    - Set AWS_REGION in .env                                    │"; \
		echo "│                                                                │"; \
		echo "└────────────────────────────────────────────────────────────────┘"; \
		exit 1; \
	fi
	docker-compose -f docker-compose.bedrock.yml up -d
	@echo ""
	@echo "[OK] Services running with AWS Bedrock:"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080"
	@echo "  * AI:           AWS Bedrock"
	@echo ""
	@echo "Use 'make logs-bedrock' to follow logs"

logs-bedrock:
	docker-compose -f docker-compose.bedrock.yml logs -f agent

# =============================================================================
# Pre-built Image Deployment (No Build Required)
# =============================================================================

start-prebuilt:
	@echo "Starting with pre-built images + Ollama in Docker..."
	@echo "Pulling latest agent image..."
	docker-compose -f docker-compose.prebuilt.yml pull agent 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt.yml up -d
	@echo ""
	@echo "[OK] Services running (pre-built):"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080"
	@echo "  * Ollama:       http://localhost:11434"
	@echo ""
	@echo "Use 'make logs-prebuilt' to follow logs"

start-prebuilt-external:
	@echo "Starting with pre-built images + external Ollama..."
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || \
		(echo "[FAIL] Ollama not running! Start it with: ollama serve" && exit 1)
	@echo "Pulling latest agent image..."
	docker-compose -f docker-compose.prebuilt-external.yml pull agent 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt-external.yml up -d
	@echo ""
	@echo "[OK] Services running (pre-built):"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080"
	@echo "  * Ollama:       http://localhost:11434 (host)"
	@echo ""
	@echo "Use 'make logs-prebuilt-external' to follow logs"

stop:
	@echo "Stopping all services..."
	docker-compose down 2>/dev/null || true
	docker-compose -f docker-compose.external-ollama.yml down 2>/dev/null || true
	docker-compose -f docker-compose.remote-ai.yml down 2>/dev/null || true
	docker-compose -f docker-compose.bedrock.yml down 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt.yml down 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt-external.yml down 2>/dev/null || true
	@echo ""
	@echo "[OK] All services stopped (data volumes preserved)"
	@echo "     Feedback history, AI models, and reports are intact."
	@echo "     Use 'make clean' to remove all data."

clean:
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  ⚠️  WARNING: This will permanently delete ALL data:           │"
	@echo "│                                                                │"
	@echo "│    • Feedback history (feedback.db)                           │"
	@echo "│    • Downloaded AI models (ollama_data)                       │"
	@echo "│    • Generated reports (agent_reports)                        │"
	@echo "│    • Jenkins home (if using local Jenkins)                    │"
	@echo "│                                                                │"
	@echo "│  Press Ctrl+C within 5 seconds to cancel...                   │"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""
	@sleep 5
	@echo "Proceeding with cleanup..."
	docker-compose down -v 2>/dev/null || true
	docker-compose -f docker-compose.external-ollama.yml down -v 2>/dev/null || true
	docker-compose -f docker-compose.remote-ai.yml down -v 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt.yml down -v 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt-external.yml down -v 2>/dev/null || true
	@echo ""
	@echo "[OK] All services stopped and ALL DATA REMOVED"
	@echo "     Run 'make setup' to start fresh."

# =============================================================================
# Backup & Restore (for migration between environments)
# =============================================================================

# Backup all application data (databases, config, exports) - excludes AI models
backup:
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  📦 Creating backup...                                         │"
	@echo "│                                                                │"
	@echo "│  Includes:                                                     │"
	@echo "│    • feedback.db (user feedback & corrections)                │"
	@echo "│    • knowledge.db (tool definitions & error patterns)         │"
	@echo "│    • training.db (training jobs & examples)                   │"
	@echo "│    • exports/ (generated training files)                      │"
	@echo "│    • reports/ (analysis reports)                              │"
	@echo "│    • config.yaml, .env (configuration)                        │"
	@echo "│                                                                │"
	@echo "│  Excludes: AI models (use backup-full to include)             │"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""
	@mkdir -p "$(BACKUP_DIR)"
	@mkdir -p "$(BACKUP_DIR)/tmp-$(TIMESTAMP)"
	@echo "Extracting data from Docker volumes..."
	@# Extract agent_data volume (databases)
	@docker run --rm -v jenkins-agent-data:/data -v "$(CURDIR)/$(BACKUP_DIR)/tmp-$(TIMESTAMP)":/backup alpine \
		sh -c "cp -r /data/* /backup/ 2>/dev/null || echo 'No data volume yet'" || true
	@# Extract agent_reports volume
	@docker run --rm -v jenkins-agent-reports:/data -v "$(CURDIR)/$(BACKUP_DIR)/tmp-$(TIMESTAMP)":/backup alpine \
		sh -c "mkdir -p /backup/reports && cp -r /data/* /backup/reports/ 2>/dev/null || echo 'No reports yet'" || true
	@# Copy local config files
	@cp config.yaml "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/" 2>/dev/null || true
	@cp .env "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/" 2>/dev/null || true
	@cp config.example.yaml "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/" 2>/dev/null || true
	@cp .env.example "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/" 2>/dev/null || true
	@# Create manifest
	@echo "backup_version: 2.0.0" > "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/MANIFEST.txt"
	@echo "backup_date: $(TIMESTAMP)" >> "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/MANIFEST.txt"
	@echo "backup_type: standard" >> "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/MANIFEST.txt"
	@echo "includes: databases,config,reports,exports" >> "$(BACKUP_DIR)/tmp-$(TIMESTAMP)/MANIFEST.txt"
	@# Create archive
	@cd "$(BACKUP_DIR)" && tar -czf "backup-$(TIMESTAMP).tar.gz" -C "tmp-$(TIMESTAMP)" .
	@rm -rf "$(BACKUP_DIR)/tmp-$(TIMESTAMP)"
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  ✅ Backup created successfully!                               │"
	@echo "│                                                                │"
	@echo "│  File: $(BACKUP_DIR)/backup-$(TIMESTAMP).tar.gz"
	@echo "│                                                                │"
	@echo "│  To restore on another machine:                               │"
	@echo "│    1. Copy this file to the new machine                       │"
	@echo "│    2. Run: make restore FILE=backup-$(TIMESTAMP).tar.gz"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""

# Full backup including AI models (large, ~4GB+)
backup-full:
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  📦 Creating FULL backup (including AI models)...              │"
	@echo "│                                                                │"
	@echo "│  ⚠️  This will be large (~4GB+ depending on models)            │"
	@echo "│                                                                │"
	@echo "│  Press Ctrl+C within 5 seconds to cancel...                   │"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""
	@sleep 5
	@mkdir -p "$(BACKUP_DIR)"
	@mkdir -p "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)"
	@echo "Extracting data from Docker volumes..."
	@# Extract agent_data volume
	@docker run --rm -v jenkins-agent-data:/data -v "$(CURDIR)/$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)":/backup alpine \
		sh -c "cp -r /data/* /backup/ 2>/dev/null || echo 'No data volume yet'" || true
	@# Extract agent_reports volume
	@docker run --rm -v jenkins-agent-reports:/data -v "$(CURDIR)/$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)":/backup alpine \
		sh -c "mkdir -p /backup/reports && cp -r /data/* /backup/reports/ 2>/dev/null || echo 'No reports yet'" || true
	@# Extract ollama models (this is the big one)
	@echo "Extracting AI models (this may take a while)..."
	@docker run --rm -v jenkins-agent-ollama:/data -v "$(CURDIR)/$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)":/backup alpine \
		sh -c "mkdir -p /backup/ollama && cp -r /data/* /backup/ollama/ 2>/dev/null || echo 'No ollama data yet'" || true
	@# Copy local config files
	@cp config.yaml "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/" 2>/dev/null || true
	@cp .env "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/" 2>/dev/null || true
	@cp config.example.yaml "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/" 2>/dev/null || true
	@cp .env.example "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/" 2>/dev/null || true
	@# Create manifest
	@echo "backup_version: 2.0.0" > "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/MANIFEST.txt"
	@echo "backup_date: $(TIMESTAMP)" >> "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/MANIFEST.txt"
	@echo "backup_type: full" >> "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/MANIFEST.txt"
	@echo "includes: databases,config,reports,exports,ollama_models" >> "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)/MANIFEST.txt"
	@# Create archive
	@echo "Creating archive (this may take several minutes)..."
	@cd "$(BACKUP_DIR)" && tar -czf "backup-full-$(TIMESTAMP).tar.gz" -C "tmp-full-$(TIMESTAMP)" .
	@rm -rf "$(BACKUP_DIR)/tmp-full-$(TIMESTAMP)"
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  ✅ Full backup created successfully!                          │"
	@echo "│                                                                │"
	@echo "│  File: $(BACKUP_DIR)/backup-full-$(TIMESTAMP).tar.gz"
	@echo "│  Size: $$(du -h $(BACKUP_DIR)/backup-full-$(TIMESTAMP).tar.gz | cut -f1)"
	@echo "│                                                                │"
	@echo "│  To restore: make restore FILE=backup-full-$(TIMESTAMP).tar.gz"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""

# Restore from backup
restore:
ifndef FILE
	$(error FILE is required. Usage: make restore FILE=backups/backup-20240411.tar.gz)
endif
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  📥 Restoring from backup...                                   │"
	@echo "│                                                                │"
	@echo "│  File: $(FILE)"
	@echo "│                                                                │"
	@echo "│  ⚠️  This will OVERWRITE existing data!                        │"
	@echo "│                                                                │"
	@echo "│  Press Ctrl+C within 5 seconds to cancel...                   │"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""
	@sleep 5
	@# Check file exists
	@test -f "$(FILE)" || (echo "ERROR: Backup file not found: $(FILE)" && exit 1)
	@# Create temp extraction directory
	@mkdir -p "$(BACKUP_DIR)/restore-tmp"
	@echo "Extracting backup..."
	@tar -xzf "$(FILE)" -C "$(BACKUP_DIR)/restore-tmp"
	@# Show manifest
	@echo ""
	@echo "Backup manifest:"
	@cat "$(BACKUP_DIR)/restore-tmp/MANIFEST.txt" 2>/dev/null || echo "No manifest found (older backup format)"
	@echo ""
	@# Ensure volumes exist
	@docker volume create jenkins-agent-data 2>/dev/null || true
	@docker volume create jenkins-agent-reports 2>/dev/null || true
	@# Restore agent_data volume (databases)
	@echo "Restoring databases..."
	@docker run --rm -v jenkins-agent-data:/data -v "$(CURDIR)/$(BACKUP_DIR)/restore-tmp":/backup alpine \
		sh -c "rm -rf /data/* && cp /backup/*.db /data/ 2>/dev/null; cp -r /backup/exports /data/ 2>/dev/null || true"
	@# Restore reports
	@echo "Restoring reports..."
	@docker run --rm -v jenkins-agent-reports:/data -v "$(CURDIR)/$(BACKUP_DIR)/restore-tmp":/backup alpine \
		sh -c "rm -rf /data/* && cp -r /backup/reports/* /data/ 2>/dev/null || true"
	@# Restore ollama models if present (full backup)
	@if [ -d "$(BACKUP_DIR)/restore-tmp/ollama" ]; then \
		echo "Restoring AI models (this may take a while)..."; \
		docker volume create jenkins-agent-ollama 2>/dev/null || true; \
		docker run --rm -v jenkins-agent-ollama:/data -v "$(CURDIR)/$(BACKUP_DIR)/restore-tmp":/backup alpine \
			sh -c "rm -rf /data/* && cp -r /backup/ollama/* /data/"; \
	fi
	@# Restore config files (don't overwrite if exist, user might have customized)
	@if [ ! -f .env ] && [ -f "$(BACKUP_DIR)/restore-tmp/.env" ]; then \
		cp "$(BACKUP_DIR)/restore-tmp/.env" .env; \
		echo "Restored .env"; \
	else \
		echo ".env exists, skipping (backup copy in $(BACKUP_DIR)/restore-tmp/.env)"; \
	fi
	@if [ ! -f config.yaml ] && [ -f "$(BACKUP_DIR)/restore-tmp/config.yaml" ]; then \
		cp "$(BACKUP_DIR)/restore-tmp/config.yaml" config.yaml; \
		echo "Restored config.yaml"; \
	else \
		echo "config.yaml exists, skipping (backup copy in $(BACKUP_DIR)/restore-tmp/config.yaml)"; \
	fi
	@echo ""
	@echo "┌────────────────────────────────────────────────────────────────┐"
	@echo "│  ✅ Restore completed successfully!                            │"
	@echo "│                                                                │"
	@echo "│  Restored:                                                     │"
	@echo "│    • Databases (feedback.db, knowledge.db, training.db)       │"
	@echo "│    • Reports and exports                                       │"
	@test -d "$(BACKUP_DIR)/restore-tmp/ollama" && echo "│    • AI models (Ollama)                                        │" || true
	@echo "│                                                                │"
	@echo "│  Next steps:                                                   │"
	@echo "│    1. Review .env and config.yaml settings                    │"
	@echo "│    2. Run: make start                                          │"
	@echo "│    3. Open: http://localhost:3000                              │"
	@echo "└────────────────────────────────────────────────────────────────┘"
	@echo ""
	@# Cleanup
	@rm -rf "$(BACKUP_DIR)/restore-tmp"

# List available backups
backup-list:
	@echo ""
	@echo "Available backups in $(BACKUP_DIR)/:"
	@echo ""
	@ls -lh $(BACKUP_DIR)/*.tar.gz 2>/dev/null || echo "  No backups found. Run 'make backup' to create one."
	@echo ""

# Open UI in browser
ui:
	@echo "Opening UI at http://localhost:3000"
	@which xdg-open > /dev/null 2>&1 && xdg-open http://localhost:3000 || \
	 which open > /dev/null 2>&1 && open http://localhost:3000 || \
	 echo "Please open http://localhost:3000 in your browser"

# =============================================================================
# Logs
# =============================================================================

logs:
	docker-compose logs -f agent

logs-ui:
	docker-compose logs -f ui

logs-external:
	docker-compose -f docker-compose.external-ollama.yml logs -f agent

logs-remote:
	docker-compose -f docker-compose.remote-ai.yml logs -f agent

logs-prebuilt:
	docker-compose -f docker-compose.prebuilt.yml logs -f agent

logs-prebuilt-external:
	docker-compose -f docker-compose.prebuilt-external.yml logs -f agent

logs-all:
	docker-compose logs -f

build:
	docker-compose build agent

# =============================================================================
# Testing (runs in Docker - no local Python needed)
# Works on Windows, Mac, and Linux
# 
# First run builds a local test image with dependencies pre-installed.
# Subsequent runs are instant (no pip install).
# =============================================================================

# Test image name (local only, not pushed to registry)
TEST_IMAGE := jenkins-agent-test:local

# Build test image if it doesn't exist
.PHONY: test-image
test-image:
	@docker inspect $(TEST_IMAGE) > /dev/null 2>&1 || \
		(echo "Building test image (first time only)..." && \
		docker build -t $(TEST_IMAGE) -f Dockerfile.test .)

# Force rebuild test image (use when test dependencies change)
test-image-rebuild:
	@echo "Rebuilding test image..."
	docker build --no-cache -t $(TEST_IMAGE) -f Dockerfile.test .
	@echo "Test image rebuilt successfully"

# Run all tests (70 tests)
test: test-image
	@echo "Running all tests..."
	docker run --rm -v "$(CURDIR):/app" $(TEST_IMAGE) pytest tests/ -v

# Run unit tests only (fast, ~60 tests)
test-unit: test-image
	@echo "Running unit tests..."
	docker run --rm -v "$(CURDIR):/app" $(TEST_IMAGE) pytest tests/ -v -m "unit"

# Run integration tests (~10 tests)
test-integration: test-image
	@echo "Running integration tests..."
	docker run --rm -v "$(CURDIR):/app" $(TEST_IMAGE) pytest tests/ -v -m "integration"

# Run tests with full output
test-verbose: test-image
	@echo "Running tests with full output..."
	docker run --rm -v "$(CURDIR):/app" $(TEST_IMAGE) pytest tests/ -v --tb=long

# Run specific test file
test-file: test-image
ifndef FILE
	$(error FILE is required. Usage: make test-file FILE=test_knowledge_store.py)
endif
	docker run --rm -v "$(CURDIR):/app" $(TEST_IMAGE) pytest tests/$(FILE) -v

# Clean test image (to force rebuild)
test-clean:
	@echo "Removing test image..."
	-docker rmi $(TEST_IMAGE) 2>/dev/null
	@echo "Done. Run 'make test' to rebuild."

# =============================================================================
# Analysis Commands
# =============================================================================

analyze:
ifndef JOB
	$(error JOB is required. Usage: make analyze JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make analyze JOB=my-job BUILD=123)
endif
	docker-compose --profile cli run --rm agent-cli analyze --job "$(JOB)" --build $(BUILD)

analyze-deep:
ifndef JOB
	$(error JOB is required. Usage: make analyze-deep JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make analyze-deep JOB=my-job BUILD=123)
endif
	@echo "Running deep agentic investigation (this may take longer)..."
	docker-compose --profile cli run --rm agent-cli analyze --job "$(JOB)" --build $(BUILD) --deep

analyze-latest:
ifndef JOB
	$(error JOB is required. Usage: make analyze-latest JOB=my-job)
endif
	docker-compose --profile cli run --rm agent-cli analyze --job "$(JOB)" --latest-failed

analyze-latest-deep:
ifndef JOB
	$(error JOB is required. Usage: make analyze-latest-deep JOB=my-job)
endif
	@echo "Running deep agentic investigation (this may take longer)..."
	docker-compose --profile cli run --rm agent-cli analyze --job "$(JOB)" --latest-failed --deep

analyze-json:
ifndef JOB
	$(error JOB is required)
endif
ifndef BUILD
	$(error BUILD is required)
endif
	docker-compose --profile cli run --rm agent-cli analyze --job "$(JOB)" --build $(BUILD) --format json

test-connection:
	docker-compose --profile cli run --rm agent-cli test-connection

# =============================================================================
# API Calls (using curl)
# =============================================================================
# Body fields match AnalyzeRequest in src/server.py (mode: iterative | deep).
# If SERVER_API_KEY is set in .env, add:  -H "X-API-Key: $$SERVER_API_KEY"

api-analyze:
ifndef JOB
	$(error JOB is required. Usage: make api-analyze JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make api-analyze JOB=my-job BUILD=123)
endif
	@echo "→ POST $(API_BASE)/analyze"
	@echo "  Fetches console log for failed/unstable build, runs default iterative RC analysis."
	@echo "  Body: job=$(JOB) build=$(BUILD) (mode defaults to iterative)"
	curl -s -X POST $(API_BASE)/analyze \
		-H "Content-Type: application/json" \
		-d '{"job":"$(JOB)","build":$(BUILD)}' | jq .

# Explicit iterative mode; turns off report/Jenkins/PR side effects for a cleaner response
api-analyze-iterative:
ifndef JOB
	$(error JOB is required. Usage: make api-analyze-iterative JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make api-analyze-iterative JOB=my-job BUILD=123)
endif
	@echo "→ POST $(API_BASE)/analyze  (mode=iterative)"
	@echo "  Same as default analysis path; useful to compare with api-analyze-deep."
	curl -s -X POST $(API_BASE)/analyze \
		-H "Content-Type: application/json" \
		-d '{"job":"$(JOB)","build":$(BUILD),"mode":"iterative","generate_report":false,"update_jenkins_description":false,"post_to_pr":false}' | jq .

api-analyze-deep:
ifndef JOB
	$(error JOB is required. Usage: make api-analyze-deep JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make api-analyze-deep JOB=my-job BUILD=123)
endif
	@echo "→ POST $(API_BASE)/analyze  (mode=deep — agentic / MCP-style investigation)"
	curl -s -X POST $(API_BASE)/analyze \
		-H "Content-Type: application/json" \
		-d '{"job":"$(JOB)","build":$(BUILD),"mode":"deep"}' | jq .

api-analyze-latest-failed:
ifndef JOB
	$(error JOB is required. Usage: make api-analyze-latest-failed JOB=my-folder/job)
endif
	@echo "→ POST $(API_BASE)/analyze  (latest_failed=true, mode=iterative)"
	@echo "  Resolves the most recent failed build for the job, then analyzes it."
	curl -s -X POST $(API_BASE)/analyze \
		-H "Content-Type: application/json" \
		-d '{"job":"$(JOB)","latest_failed":true,"mode":"iterative","generate_report":false,"update_jenkins_description":false,"post_to_pr":false}' | jq .

api-health:
	@echo "→ GET $(API_BASE)/health"
	curl -s $(API_BASE)/health | jq .

# =============================================================================
# Development
# =============================================================================

shell:
	docker-compose exec agent bash

shell-ollama:
	docker-compose exec ollama bash

# =============================================================================
# AI Model Management
# =============================================================================

pull-model:
ifndef MODEL
	$(error MODEL is required. Usage: make pull-model MODEL=llama3:70b)
endif
	docker-compose exec ollama ollama pull $(MODEL)
	@echo ""
	@echo "Model $(MODEL) pulled. Update AI_MODEL in .env and run: make restart"

pull-model-deep:
	@echo "Pulling llama3:70b for deep investigation (recommended for agentic mode)..."
	@echo "This model is ~40GB and will take time to download."
	docker-compose exec ollama ollama pull llama3:70b
	@echo ""
	@echo "[OK] Model ready! To use it, update .env:"
	@echo "  AI_MODEL=llama3:70b"
	@echo ""
	@echo "Then run: make restart"

list-models:
	docker-compose exec ollama ollama list

restart:
	docker-compose restart agent

# =============================================================================
# Jenkins (Local Testing)
# =============================================================================

start-with-jenkins:
	docker-compose --profile with-jenkins up -d
	@echo ""
	@echo "Jenkins running at http://localhost:8081"
	@echo "Agent running at http://localhost:8080"
	@echo ""
	@echo "Get Jenkins admin password with:"
	@echo "  docker-compose exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword"

jenkins-password:
	@docker-compose exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword

# =============================================================================
# Health Checks
# =============================================================================

health:
	@echo "Checking services..."
	@echo ""
	@echo "UI (port 3000):"
	@curl -s http://localhost:3000 > /dev/null && echo "  [OK] Running" || echo "  [FAIL] NOT RUNNING"
	@echo ""
	@echo "Agent API (port 8080):"
	@curl -s http://localhost:8080/health && echo "" || echo "  [FAIL] NOT RUNNING"
	@echo ""
	@echo "Ollama (port 11434):"
	@curl -s http://localhost:11434/api/tags | head -c 100 || echo "  [FAIL] NOT RUNNING"
	@echo ""

status:
	docker-compose ps

# =============================================================================
# Docker Hub - Push/Pull Pre-built Images (Multi-Architecture)
# =============================================================================
# 
# Builds for both linux/amd64 (Intel/AMD) and linux/arm64 (Apple Silicon, ARM)
#
# Usage:
#   1. On Windows (build machine):
#      make docker-login
#      make docker-setup-buildx    # One-time setup for multi-arch
#      make docker-release DOCKER_REPO=yourusername/jenkins-failure-agent
#
#   2. On MacBook (run machine):
#      export AGENT_IMAGE=yourusername/jenkins-failure-agent:latest
#      make start-prebuilt-external
#

# Docker Hub repository (override with: make docker-push DOCKER_REPO=myuser/myrepo)
DOCKER_REPO ?= yourusername/jenkins-failure-agent
DOCKER_TAG ?= latest
PLATFORMS ?= linux/amd64,linux/arm64

docker-login:
	docker login

# One-time setup for multi-arch builds
docker-setup-buildx:
	@echo "Setting up Docker Buildx for multi-architecture builds..."
	@docker buildx create --name multiarch --driver docker-container --use 2>/dev/null || \
		docker buildx use multiarch 2>/dev/null || \
		echo "Using default builder"
	@docker buildx inspect --bootstrap || true
	@echo ""
	@echo "[OK] Buildx ready for platforms: $(PLATFORMS)"

# Build multi-arch and push (requires docker-setup-buildx first)
docker-build:
	@echo "Building multi-arch image: $(DOCKER_REPO):$(DOCKER_TAG)"
	@echo "Platforms: $(PLATFORMS)"
	@echo ""
	docker buildx build \
		--platform $(PLATFORMS) \
		-t $(DOCKER_REPO):$(DOCKER_TAG) \
		-t $(DOCKER_REPO):v2.0.0 \
		--push \
		.
	@echo ""
	@echo "[OK] Built and pushed $(DOCKER_REPO):$(DOCKER_TAG)"
	@echo "[OK] Built and pushed $(DOCKER_REPO):v2.0.0"
	@echo "[OK] Platforms: $(PLATFORMS)"

# Build for single platform (local testing, no push)
docker-build-local:
	@echo "Building local image: $(DOCKER_REPO):$(DOCKER_TAG)"
	docker build -t $(DOCKER_REPO):$(DOCKER_TAG) .
	@echo ""
	@echo "[OK] Built $(DOCKER_REPO):$(DOCKER_TAG) (local only)"

docker-push:
	@echo "Note: Use 'make docker-build' which builds and pushes multi-arch images"
	@echo "For multi-arch, build and push must happen together."
	@echo ""
	@echo "Run: make docker-build DOCKER_REPO=$(DOCKER_REPO)"

docker-pull:
	@echo "Pulling from Docker Hub..."
	docker pull $(DOCKER_REPO):$(DOCKER_TAG)
	@echo "[OK] Pulled $(DOCKER_REPO):$(DOCKER_TAG)"

# Build and push multi-arch in one command
docker-release: docker-setup-buildx docker-build
	@echo ""
	@echo "[OK] Release complete!"
	@echo ""
	@echo "To use on another machine (Intel or ARM):"
	@echo "  export AGENT_IMAGE=$(DOCKER_REPO):$(DOCKER_TAG)"
	@echo "  make start-prebuilt-external"

# Build and push both agent and UI images
docker-release-all: docker-setup-buildx
	@echo "Building multi-arch AGENT image: $(DOCKER_REPO):$(DOCKER_TAG)"
	docker buildx build \
		--platform $(PLATFORMS) \
		-t $(DOCKER_REPO):$(DOCKER_TAG) \
		-t $(DOCKER_REPO):v2.0.0 \
		--push \
		.
	@echo ""
	@echo "Building multi-arch UI image: $(DOCKER_REPO)-ui:$(DOCKER_TAG)"
	docker buildx build \
		--platform $(PLATFORMS) \
		-t $(DOCKER_REPO)-ui:$(DOCKER_TAG) \
		-t $(DOCKER_REPO)-ui:v2.0.0 \
		-f ui/Dockerfile.ui \
		--push \
		.
	@echo ""
	@echo "[OK] Released both images!"
	@echo "  Agent: $(DOCKER_REPO):$(DOCKER_TAG)"
	@echo "  UI:    $(DOCKER_REPO)-ui:$(DOCKER_TAG)"

# Restart UI to pick up file changes (no build needed - uses mounted volumes)
rebuild-ui:
	docker-compose restart ui
	@echo ""
	@echo "[OK] UI restarted with updated files"
	@echo "Hard refresh browser: Cmd+Shift+R (Mac) or Ctrl+Shift+R"
