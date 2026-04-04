# Jenkins Failure Analysis Agent v1.5
# Multi-stage build for optimal image size
# Supports: Standard (scripted), Iterative (multi-call), and Deep (agentic MCP) analysis modes

# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Ensure scripts in .local are usable
ENV PATH=/root/.local/bin:$PATH

# Copy application code (includes src/mcp/ and src/agent/ for deep investigation)
COPY src/ ./src/
COPY agent.py .

# Create directories for data persistence
RUN mkdir -p /app/reports /app/logs /app/data

# Create a default config (will be overridden by mount)
COPY config.yaml /app/config.yaml

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Default AI settings (Ollama in Docker)
    AI_BASE_URL=http://ollama:11434/v1 \
    AI_MODEL=llama3:8b \
    AI_API_KEY=ollama \
    AI_TIMEOUT=120 \
    # GitHub (disabled by default)
    GITHUB_ENABLED=false \
    # SCM/PR integration (disabled by default)
    SCM_ENABLED=false \
    SCM_PROVIDER=github \
    # Reporter options
    UPDATE_JENKINS_DESCRIPTION=true \
    POST_TO_PR=true

# Labels
LABEL org.opencontainers.image.title="Jenkins Failure Analysis Agent" \
      org.opencontainers.image.description="AI-powered Jenkins build failure analysis with iterative RC analysis and MCP tools" \
      org.opencontainers.image.version="1.9.21"

# Default port
EXPOSE 8080

# Health check - increased start_period for deep investigation mode
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command: run server
CMD ["python", "agent.py", "serve", "--host", "0.0.0.0", "--port", "8080"]
