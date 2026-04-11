# Jenkins Failure Analysis Agent - Makefile
# 
# Usage:
#   make help        - Show available commands
#   make start       - Start all services
#   make analyze     - Run CLI analysis

.PHONY: help start stop logs build clean analyze test shell pull-model

# Deployment mode (can be overridden)
COMPOSE_FILE ?= docker-compose.yml

# Default target
help:
	@echo "Jenkins Failure Analysis Agent v1.9"
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
	@echo "Stop/Clean:"
	@echo "  make stop                     - Stop all services (DATA PRESERVED)"
	@echo "  make clean                    - Stop + DELETE ALL DATA (feedback, models, reports)"
	@echo ""
	@echo "Usage:"
	@echo "  make ui                       - Open the web dashboard"
	@echo "  make analyze JOB=x BUILD=123  - Analyze a specific build (fast mode)"
	@echo "  make analyze-deep JOB=x BUILD=123  - Deep agentic investigation"
	@echo "  make analyze-latest JOB=x     - Analyze latest failed build"
	@echo "  make test-connection          - Test Jenkins & AI connection"
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
	docker-compose up -d
	@echo ""
	@echo "[OK] Services running:"
	@echo "  * UI Dashboard: http://localhost:3000"
	@echo "  * Agent API:    http://localhost:8080"
	@echo "  * Ollama:       http://localhost:11434"
	@echo ""
	@echo "Use 'make logs' to follow logs"

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

api-analyze:
ifndef JOB
	$(error JOB is required. Usage: make api-analyze JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make api-analyze JOB=my-job BUILD=123)
endif
	curl -s -X POST http://localhost:8080/analyze \
		-H "Content-Type: application/json" \
		-d '{"job":"$(JOB)","build":$(BUILD)}' | jq .

api-analyze-deep:
ifndef JOB
	$(error JOB is required. Usage: make api-analyze-deep JOB=my-job BUILD=123)
endif
ifndef BUILD
	$(error BUILD is required. Usage: make api-analyze-deep JOB=my-job BUILD=123)
endif
	curl -s -X POST http://localhost:8080/analyze \
		-H "Content-Type: application/json" \
		-d '{"job":"$(JOB)","build":$(BUILD),"deep":true}' | jq .

api-health:
	curl -s http://localhost:8080/health | jq .

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
	docker buildx create --name multiarch --driver docker-container --use 2>/dev/null || docker buildx use multiarch
	docker buildx inspect --bootstrap
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
		-t $(DOCKER_REPO):v1.9.0 \
		--push \
		.
	@echo ""
	@echo "[OK] Built and pushed $(DOCKER_REPO):$(DOCKER_TAG)"
	@echo "[OK] Built and pushed $(DOCKER_REPO):v1.9.0"
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
		-t $(DOCKER_REPO):v1.9.0 \
		--push \
		.
	@echo ""
	@echo "Building multi-arch UI image: $(DOCKER_REPO)-ui:$(DOCKER_TAG)"
	docker buildx build \
		--platform $(PLATFORMS) \
		-t $(DOCKER_REPO)-ui:$(DOCKER_TAG) \
		-t $(DOCKER_REPO)-ui:v1.9.0 \
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
