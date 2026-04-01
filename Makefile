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
	@echo "Jenkins Failure Analysis Agent v1.4"
	@echo ""
	@echo "Deployment Modes (Build from Source):"
	@echo "  make start                    - Start with Ollama in Docker (default)"
	@echo "  make start-external-ollama    - Start with Ollama on host machine"
	@echo "  make start-remote-ai          - Start with remote AI API (OpenAI, etc.)"
	@echo ""
	@echo "Deployment Modes (Pre-built Images - No Build Required):"
	@echo "  make start-prebuilt           - Pre-built image + Ollama in Docker"
	@echo "  make start-prebuilt-external  - Pre-built image + Ollama on host"
	@echo ""
	@echo "Setup:"
	@echo "  make setup                    - First-time setup (copy .env, pull model)"
	@echo "  make setup-external-ollama    - Setup for external Ollama"
	@echo "  make setup-deep               - Setup for deep investigation (larger model)"
	@echo "  make stop                     - Stop all services"
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
	@echo "  make shell                    - Shell into agent container"
	@echo "  make clean                    - Stop and remove all data"
	@echo ""
	@echo "AI Models (for local Ollama):"
	@echo "  make pull-model MODEL=llama3:70b  - Pull a different model"
	@echo "  make pull-model-deep              - Pull recommended model for deep analysis"
	@echo "  make list-models                  - List available models"

# =============================================================================
# Setup
# =============================================================================

setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from template"; \
	fi
	@echo ""
	@echo "Starting Ollama and pulling AI model..."
	docker-compose up -d ollama
	docker-compose run --rm ollama-pull
	@echo ""
	@echo "✓ Setup complete!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env with your Jenkins credentials"
	@echo "  2. Run: make start"
	@echo "  3. Open: http://localhost:3000"

setup-deep:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from template"; \
	fi
	@echo ""
	@echo "Setting up for deep investigation mode..."
	@echo "This requires a larger AI model for best results."
	@echo ""
	docker-compose up -d ollama
	@echo "Pulling llama3:70b (this will take a while, ~40GB)..."
	docker-compose exec ollama ollama pull llama3:70b
	@echo ""
	@echo "✓ Setup complete!"
	@echo ""
	@echo "To use the 70B model, update .env:"
	@echo "  AI_MODEL=llama3:70b"
	@echo ""
	@echo "Then run: make start"

setup-external-ollama:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env from template"; \
	fi
	@echo ""
	@echo "Checking Ollama on host machine..."
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || \
		(echo "✗ Ollama not running! Start it with: ollama serve" && exit 1)
	@echo "✓ Ollama is running"
	@echo ""
	@echo "Checking for llama3:8b model..."
	@curl -s http://localhost:11434/api/tags | grep -q "llama3:8b" || \
		(echo "Pulling llama3:8b model..." && ollama pull llama3:8b)
	@echo "✓ Model ready"
	@echo ""
	@echo "Setup complete! Next steps:"
	@echo "  1. Edit .env with your Jenkins credentials"
	@echo "  2. Run: make start-external-ollama"
	@echo "  3. Open: http://localhost:3000"

# =============================================================================
# Start/Stop Services
# =============================================================================

start:
	docker-compose up -d
	@echo ""
	@echo "✓ Services running:"
	@echo "  • UI Dashboard: http://localhost:3000"
	@echo "  • Agent API:    http://localhost:8080"
	@echo "  • Ollama:       http://localhost:11434"
	@echo ""
	@echo "Use 'make logs' to follow logs"

start-external-ollama:
	@echo "Starting with external Ollama (on host machine)..."
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || \
		(echo "✗ Ollama not running! Start it with: ollama serve" && exit 1)
	docker-compose -f docker-compose.external-ollama.yml up -d
	@echo ""
	@echo "✓ Services running:"
	@echo "  • UI Dashboard: http://localhost:3000"
	@echo "  • Agent API:    http://localhost:8080"
	@echo "  • Ollama:       http://localhost:11434 (host)"
	@echo ""
	@echo "Use 'make logs-external' to follow logs"

start-remote-ai:
	@if [ -z "$$AI_BASE_URL" ] && ! grep -q "^AI_BASE_URL=" .env 2>/dev/null; then \
		echo "✗ AI_BASE_URL not set! Configure it in .env first."; \
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
	@echo "✓ Services running:"
	@echo "  • UI Dashboard: http://localhost:3000"
	@echo "  • Agent API:    http://localhost:8080"
	@echo "  • AI:           Remote API"
	@echo ""
	@echo "Use 'make logs-remote' to follow logs"

# =============================================================================
# Pre-built Image Deployment (No Build Required)
# =============================================================================

start-prebuilt:
	@echo "Starting with pre-built images + Ollama in Docker..."
	@echo "Pulling latest agent image..."
	docker-compose -f docker-compose.prebuilt.yml pull agent 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt.yml up -d
	@echo ""
	@echo "✓ Services running (pre-built):"
	@echo "  • UI Dashboard: http://localhost:3000"
	@echo "  • Agent API:    http://localhost:8080"
	@echo "  • Ollama:       http://localhost:11434"
	@echo ""
	@echo "Use 'make logs-prebuilt' to follow logs"

start-prebuilt-external:
	@echo "Starting with pre-built images + external Ollama..."
	@curl -s http://localhost:11434/api/tags > /dev/null 2>&1 || \
		(echo "✗ Ollama not running! Start it with: ollama serve" && exit 1)
	@echo "Pulling latest agent image..."
	docker-compose -f docker-compose.prebuilt-external.yml pull agent 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt-external.yml up -d
	@echo ""
	@echo "✓ Services running (pre-built):"
	@echo "  • UI Dashboard: http://localhost:3000"
	@echo "  • Agent API:    http://localhost:8080"
	@echo "  • Ollama:       http://localhost:11434 (host)"
	@echo ""
	@echo "Use 'make logs-prebuilt-external' to follow logs"

stop:
	docker-compose down 2>/dev/null || true
	docker-compose -f docker-compose.external-ollama.yml down 2>/dev/null || true
	docker-compose -f docker-compose.remote-ai.yml down 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt.yml down 2>/dev/null || true
	docker-compose -f docker-compose.prebuilt-external.yml down 2>/dev/null || true
	@echo "✓ All services stopped"

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

clean:
	docker-compose down -v
	@echo "All containers and volumes removed"

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
	@echo "✓ Model ready! To use it, update .env:"
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
	@curl -s http://localhost:3000 > /dev/null && echo "  ✓ Running" || echo "  ✗ NOT RUNNING"
	@echo ""
	@echo "Agent API (port 8080):"
	@curl -s http://localhost:8080/health && echo "" || echo "  ✗ NOT RUNNING"
	@echo ""
	@echo "Ollama (port 11434):"
	@curl -s http://localhost:11434/api/tags | head -c 100 || echo "  ✗ NOT RUNNING"
	@echo ""

status:
	docker-compose ps
