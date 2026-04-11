# Changelog

## v2.0.0 - Major Release: AI Learning System Complete (2026-04-11)

### 🎉 MAJOR RELEASE CHECKPOINT

This is a major release milestone that completes the AI Learning System with full test coverage and documentation.

### What's New

| Feature | Description |
|---------|-------------|
| **Knowledge Store** | SQLite database for tool definitions and error patterns |
| **Doc Importer** | Import tool knowledge from documentation URLs |
| **Java Analyzer** | Extract CLI patterns from Java source (Spring Shell, Picocli) |
| **Training Pipeline** | Export training data for AI fine-tuning |
| **UI Tabs** | Three-tab interface (Analysis, Knowledge, Training) |
| **Test Suite** | 70 automated tests with pytest |

### Test Coverage

| Test File | Tests | Description |
|-----------|-------|-------------|
| `test_knowledge_store.py` | 20 | Tool/error CRUD, pattern matching |
| `test_java_analyzer.py` | 8 | Java pattern extraction |
| `test_doc_importer.py` | 16 | Documentation parsing |
| `test_training_pipeline.py` | 18 | Training job workflow |
| `test_integration.py` | 7 | End-to-end pipeline tests |
| **Total** | **70** | **All passing** |

### API Endpoints Added

**Knowledge Store:**
```
GET    /knowledge/tools              — List all tools
GET    /knowledge/tools/{id}         — Get tool details
POST   /knowledge/tools              — Add tool
DELETE /knowledge/tools/{id}         — Delete tool
GET    /knowledge/identify           — Identify tool from log
GET    /knowledge/match-error        — Find matching error
GET    /knowledge/stats              — Statistics
POST   /knowledge/import-doc         — Import from URL
POST   /knowledge/analyze-source     — Analyze Java source
```

**Training Pipeline:**
```
POST   /training/jobs                — Create job
GET    /training/jobs                — List jobs
GET    /training/jobs/{id}           — Get job details
POST   /training/jobs/{id}/prepare   — Prepare data
POST   /training/jobs/{id}/export    — Export to file
GET    /training/jobs/{id}/download  — Download file
GET    /training/stats               — Pipeline statistics
```

### Files Added/Modified

| File | Lines | Description |
|------|-------|-------------|
| `src/knowledge_store.py` | 1,110 | Tool/error SQLite storage |
| `src/java_analyzer.py` | 790 | Java CLI source analyzer |
| `src/doc_importer.py` | 620 | Documentation importer |
| `src/training_pipeline.py` | 813 | Training data export |
| `ui/index.html` | +600 | Knowledge + Training UI tabs |
| `tests/` | 5 files | Complete test suite |
| `pytest.ini` | 15 | Pytest configuration |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      JENKINS FAILURE AGENT v2.0                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │   ANALYSIS UI   │    │  KNOWLEDGE UI   │    │  TRAINING UI    │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
│           └──────────────────────┴──────────────────────┘                   │
│                                  │                                          │
│  ┌───────────────────────────────┴───────────────────────────────┐         │
│  │                         REST API                               │         │
│  │  /analyze  /knowledge/*  /training/*  /feedback  /health      │         │
│  └───────────────────────────────────────────────────────────────┘         │
│                                  │                                          │
│  ┌───────────┬───────────────────┼───────────────────┬───────────┐         │
│  │  Analyzer │   AI Provider     │   Knowledge Store │  Training │         │
│  └───────────┴───────────────────┴───────────────────┴───────────┘         │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────┐         │
│  │  feedback.db  │  knowledge.db  │  training.db  │  exports/    │         │
│  └───────────────────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Running Tests

```bash
# Install dependencies
pip install pytest pyyaml

# Run all tests
pytest tests/ -v

# Unit tests only (fast)
pytest tests/ -m "unit" -v

# Integration tests
pytest tests/ -m "integration" -v
```

### Upgrade from v1.x

No migration needed. New databases (knowledge.db, training.db) are created automatically on first use.

---

## v1.9.35 - UI & Automation: Phase 5 (2026-04-10)

### New Feature: Knowledge Management & Training Dashboard UI

Full web UI for managing the AI Learning System.

#### New Navigation

```
┌─────────────────────────────────────────────────────────────────┐
│  🤖 Jenkins Failure Analysis                                    │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐                       │
│  │ Analysis │ │ Knowledge │ │ Training │                       │
│  └──────────┘ └───────────┘ └──────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

#### Knowledge Tab Features

| Feature | Description |
|---------|-------------|
| **Stats Overview** | Tools, error patterns, docs, analyses count |
| **Tools List** | View all tools with details (commands, env vars, errors) |
| **Delete Tool** | Remove tools from knowledge base |
| **Import from URL** | Fetch documentation and extract tool patterns |
| **Import Feedback** | Visual status of imported docs |

#### Training Tab Features

| Feature | Description |
|---------|-------------|
| **Stats Dashboard** | Total examples, validated, validation rate, jobs |
| **Create Job** | Name, format selection (JSONL/CSV/JSON) |
| **Job Actions** | Prepare → Export → Download workflow |
| **Status Badges** | Visual status (pending, preparing, ready, completed, failed) |
| **Data Distribution** | Charts showing examples by source and category |

#### UI Components Added

| Component | Lines | Description |
|-----------|-------|-------------|
| `KnowledgePanel` | ~200 | Tool management, URL import |
| `TrainingPanel` | ~200 | Job management, stats dashboard |
| Navigation | ~30 | Top nav bar with 3 views |

### AI Learning System Complete! 🎉

| Phase | Version | Description |
|-------|---------|-------------|
| ✅ Phase 1 | v1.9.30 | Data structures & API |
| ✅ Phase 2A | v1.9.31 | Java source analysis |
| ✅ Phase 2C | v1.9.32 | Doc URL import |
| ✅ Phase 3 | v1.9.33 | AI Integration |
| ✅ Phase 4 | v1.9.34 | Training Pipeline |
| ✅ **Phase 5** | **v1.9.35** | **UI & Automation** |

### Full System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         JENKINS FAILURE AGENT v1.9.35                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │   ANALYSIS UI   │    │  KNOWLEDGE UI   │    │  TRAINING UI    │         │
│  │  (Build Debug)  │    │  (Tool Mgmt)    │    │  (Fine-tuning)  │         │
│  └────────┬────────┘    └────────┬────────┘    └────────┬────────┘         │
│           │                      │                      │                   │
│  ┌────────┴──────────────────────┴──────────────────────┴────────┐         │
│  │                         REST API                               │         │
│  │  /analyze  /knowledge/*  /training/*  /feedback  /health      │         │
│  └───────────────────────────┬───────────────────────────────────┘         │
│                              │                                              │
│  ┌───────────────────────────┴───────────────────────────────────┐         │
│  │                      CORE ENGINE                               │         │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │         │
│  │  │  RC Analyzer │  │  Knowledge   │  │  Training    │        │         │
│  │  │  (AI + MCP)  │  │    Store     │  │  Pipeline    │        │         │
│  │  └──────────────┘  └──────────────┘  └──────────────┘        │         │
│  └───────────────────────────────────────────────────────────────┘         │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────┐         │
│  │                      DATA STORES                               │         │
│  │  feedback.db  │  knowledge.db  │  training.db                 │         │
│  └───────────────────────────────────────────────────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## v1.9.34 - Training Pipeline: Phase 4 (2026-04-10)

### New Feature: Training Data Pipeline for Fine-Tuning

Complete pipeline to prepare and export training data for model fine-tuning.

#### Workflow

```bash
# 1. Create a training job
curl -X POST http://localhost:8080/training/jobs \
  -d '{"name": "finetune-v1", "format": "jsonl_openai"}'
# Returns: {"job_id": 1}

# 2. Prepare data (imports from feedback + knowledge stores)
curl -X POST http://localhost:8080/training/jobs/1/prepare
# Returns: {"total_examples": 150, "valid_examples": 142}

# 3. Export to file
curl -X POST http://localhost:8080/training/jobs/1/export
# Returns: {"exported_path": "/app/data/exports/training_finetune-v1_20260410.jsonl"}

# 4. Download
curl http://localhost:8080/training/jobs/1/download > training.jsonl
```

#### Supported Export Formats

| Format | Description | Use Case |
|--------|-------------|----------|
| `jsonl_openai` | OpenAI/Ollama format | Fine-tuning with Ollama, OpenAI |
| `jsonl_anthropic` | Anthropic format | Fine-tuning with Claude |
| `csv` | Spreadsheet format | Data review, analysis |
| `json` | Raw JSON | Custom processing |

#### Data Sources

- **Feedback Store** — User-confirmed corrections (highest quality)
- **Knowledge Store** — Tool error patterns (synthetic examples)

#### New API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/training/jobs` | POST | Create training job |
| `/training/jobs` | GET | List jobs |
| `/training/jobs/{id}` | GET | Get job details |
| `/training/jobs/{id}/prepare` | POST | Import & validate data |
| `/training/jobs/{id}/export` | POST | Export to file |
| `/training/jobs/{id}/download` | GET | Download exported file |
| `/training/stats` | GET | Pipeline statistics |
| `/training/import` | POST | Manual data import |

#### New Files

- `src/training_pipeline.py` — Training data management (~650 lines)

#### Quality Validation

Each training example is validated:
- Error snippet minimum 10 chars
- Root cause minimum 10 chars
- Valid category (CREDENTIAL, NETWORK, etc.)
- Confidence 0-1 range

### Phase Summary Complete ✅

| Phase | Version | Description |
|-------|---------|-------------|
| Phase 1 | v1.9.30 | Data structures & API |
| Phase 2A | v1.9.31 | Java source analysis |
| Phase 2C | v1.9.32 | Doc URL import |
| Phase 3 | v1.9.33 | AI Integration |
| **Phase 4** | **v1.9.34** | **Training Pipeline** |
| Phase 5 | Next | UI & Automation |

## v1.9.33 - AI Integration: Phase 3 (2026-04-10)

### New Feature: Knowledge Store Integration into AI Analysis

The AI now uses internal tool knowledge during failure analysis.

#### How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AI ANALYSIS WITH KNOWLEDGE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. Log Analysis                                                             │
│     └── Extract error text, tool invocations, commands                      │
│                                                                              │
│  2. Knowledge Lookup                                                         │
│     ├── identify_tool() → Find matching internal tools                      │
│     └── match_error() → Find known error patterns                           │
│                                                                              │
│  3. Prompt Injection                                                         │
│     └── ## INTERNAL TOOLS CONTEXT ##                                        │
│         └── Tool: a2l                                                        │
│             Category: deployment                                             │
│             Known Errors:                                                    │
│               - A2L_AUTH_FAILED: Token expired                              │
│                 Fix: Run 'a2l auth refresh'                                 │
│                                                                              │
│  4. Confidence Boosting                                                      │
│     └── If known error matched → boost confidence + use stored fix          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Changes

| File | Change |
|------|--------|
| `src/rc_analyzer.py` | Added `_get_internal_tools_knowledge()` — injects tool context into prompt |
| `src/rc_analyzer.py` | Added `_check_knowledge_store_errors()` — matches errors, boosts confidence |
| `src/rc_analyzer.py` | `_build_initial_prompt()` — now includes ## INTERNAL TOOLS CONTEXT ## |

#### Example: Before vs After

**Before (without knowledge):**
```
Root cause: Authentication error occurred
Confidence: 0.45
Fix: (none)
```

**After (with a2l tool in knowledge store):**
```
Root cause: a2l authentication token expired
Confidence: 0.85  ← Boosted from known error match
Fix: Run 'a2l auth refresh' to renew token  ← From knowledge store
```

### Phase Summary

| Phase | Version | Description |
|-------|---------|-------------|
| Phase 1 | v1.9.30 | Data structures & API |
| Phase 2A | v1.9.31 | Java source analysis |
| Phase 2C | v1.9.32 | Doc URL import |
| **Phase 3** | **v1.9.33** | **AI Integration** |
| Phase 4 | Next | Training pipeline |
| Phase 5 | Pending | UI & automation |

## v1.9.32 - Doc Importer: Phase 2C (2026-04-10)

### New Feature: Import Tool Documentation from URLs

Fetch documentation from URLs and extract tool patterns.

#### Supported Formats
- **Markdown** — GitHub/GitLab READMEs, wiki pages
- **HTML** — Confluence, internal wikis, web docs
- **Plain text** — Any text-based documentation

#### What Gets Extracted
| Element | Extraction Method |
|---------|-------------------|
| Description | First paragraph or "Description" section |
| Commands | Code blocks with `$` prefix, bash examples |
| Error codes | Tables, lists with `ERROR_CODE` patterns |
| Env vars | `UPPER_CASE` names in tables, `export` statements |
| Arguments | `--flag` patterns with descriptions |

#### New API Endpoints
```bash
# Import documentation
POST /knowledge/import-doc
{
  "url": "https://wiki.company.com/tools/a2l",
  "tool_name": "a2l",
  "extract_errors": true,
  "save": false
}

# List imported docs
GET /knowledge/docs?tool_id=1&search=deploy
```

#### New Dependencies
- `beautifulsoup4>=4.12.0` — HTML parsing

#### New Files
- `src/doc_importer.py` — Doc fetcher and parser (~500 lines)

### Phase 2 Complete ✅

| Phase | Component | Version |
|-------|-----------|---------|
| 2A | Java Source Analyzer | v1.9.31 |
| 2C | Doc URL Import | v1.9.32 |

### Next: Phase 3 — AI Integration
- Inject tool knowledge into analysis prompts
- Use knowledge base during failure analysis

## v1.9.31 - Java Source Analyzer: Phase 2A (2026-04-10)

### New Feature: Analyze Java Source Code to Extract Tool Definitions

Automatically extracts tool patterns from Java CLI source code using existing GitHubClient.

#### Supported Frameworks
- **Spring Shell** — `@ShellComponent`, `@ShellMethod`, `@ShellOption`
- **Picocli** — `@Command`, `@Option`, `@Parameters`
- **Plain Java** — `public static void main`, `System.exit`

#### What Gets Extracted
| Element | Source |
|---------|--------|
| Commands | `@ShellMethod`, `@Command`, subcommands |
| Arguments | `@ShellOption`, `@Option`, method parameters |
| Errors | `throw new XxxException("...")` |
| Exit codes | `System.exit(N)` |
| Log signatures | `logger.error("[TAG]...")`, `System.err.println` |
| Environment vars | `System.getenv("VAR")`, `${VAR}` |

#### New API Endpoint
```bash
POST /knowledge/analyze-source
{
  "repo_url": "https://github.company.com/team/a2l-cli.git",
  "branch": "main",
  "entry_point": "src/main/java/com/company/A2LCli.java",
  "depth": 2
}

# Response
{
  "status": "extracted",
  "tool": { ... ToolDefinition ... },
  "confidence": 0.85,
  "analysis": {
    "files_analyzed": ["A2LCli.java", "DeployCommand.java"],
    "commands_found": 5,
    "errors_found": 8,
    "cli_framework": "spring_shell"
  },
  "needs_review": true,
  "save_url": "/knowledge/tools"
}
```

#### New Files
- `src/java_analyzer.py` — Java source parser (~600 lines)

#### Usage Flow
1. Call `POST /knowledge/analyze-source` with repo URL
2. Review extracted tool definition in response
3. Edit if needed, then save with `POST /knowledge/tools`

### Next: Phase 2C — Doc URL Import

## v1.9.30 - Knowledge Store: Phase 1 (2026-04-10)

### New Feature: AI Learning System - Phase 1

Data structures and API for teaching AI about internal tools.

#### Tool Definition Schema
```yaml
tool:
  name: "a2l"
  aliases: ["a2l-cli"]
  category: "deployment"
  patterns:
    commands: ["a2l deploy", "a2l rollback"]
    log_signatures: ["[A2L]", "A2L_"]
    env_vars: ["A2L_TOKEN"]
  errors:
    - code: "A2L_AUTH_FAILED"
      pattern: "A2L_AUTH_FAILED|authentication failed"
      category: "CREDENTIAL"
      fix: "Check A2L_TOKEN env var"
      retriable: true
  dependencies:
    tools: ["kubectl", "helm"]
```

#### New API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/knowledge/tools` | GET | List all known tools |
| `/knowledge/tools/{id}` | GET | Get tool details |
| `/knowledge/tools` | POST | Add new tool |
| `/knowledge/tools/{id}` | PUT | Update tool |
| `/knowledge/tools/{id}` | DELETE | Delete tool |
| `/knowledge/identify?query=...` | GET | Identify tool from command/log |
| `/knowledge/match-error?snippet=...` | GET | Match known error patterns |
| `/knowledge/stats` | GET | Knowledge store statistics |

#### New Files
- `src/knowledge_store.py` — SQLite storage + data models (~700 lines)

#### Database Tables
- `tools` — Tool definitions
- `tool_errors` — Error patterns per tool
- `knowledge_docs` — Imported documentation
- `source_analysis_log` — Track source analysis runs

### Next: Phase 2
- Source code analysis (Java parser via GitHubClient)
- Doc URL import

## v1.9.29 - Feedback Buttons Fixed (2026-04-10)

### Bug Fix: Feedback Yes/No Buttons Not Working

**Root Cause:** nginx proxy was not configured to forward `/feedback` endpoint to the backend API. 

The UI called `fetch('/feedback', ...)` but nginx only had proxy rules for `/health`, `/analyze`, and `/results`. Requests to `/feedback` returned 404.

**Fix:** Added missing nginx proxy location blocks:
```nginx
location /feedback {
    proxy_pass http://agent:8080/feedback;
}

location /config {
    proxy_pass http://agent:8080/config;
}
```

### Changes
- `ui/nginx.conf` — Added `/feedback` and `/config` proxy routes
- `ui/index.html` — Added console logging to debug feedback submissions

### How to Update Running Instance
```bash
# Restart nginx to pick up config changes
docker-compose restart ui

# Or full restart
make stop && make start
```

## v1.9.28 - UI Bug Fixes (2026-04-10)

### Bug Fixes

1. **Feedback Yes button now shows visual reaction**
   - Added `useEffect` to reset feedback state when analysis result changes
   - Previously button appeared stuck after clicking on same session

2. **Fix tab now properly displays fix suggestions**
   - Added fallback to show `root_cause.fix` when `recommendations[]` is empty
   - Shows "No fix suggestions available" only when truly no fix exists
   - Previously showed empty content or truncated AI responses

### Technical Changes
- Added `fix` field to `RootCause` dataclass in `ai_analyzer.py`
- Added `fix` to API response in `result_to_dict()`
- Fix tab now checks: `recommendations[]` → `failure_analysis.fix_code` → `root_cause.fix`

## v1.9.27 - AWS Bedrock Support (2026-04-10)

### New Feature: Multi-Provider AI Architecture

#### Supported Providers:
- **OpenAI-compatible** (default): Ollama, vLLM, LocalAI, OpenAI, Azure
- **AWS Bedrock**: Claude, Titan, Llama, Mistral

#### Bedrock Model Aliases:
```
Claude:   claude-3-sonnet, claude-3-haiku, claude-3-opus, claude-3.5-sonnet
Titan:    titan-express, titan-lite
Llama:    llama3-8b, llama3-70b, llama2-13b, llama2-70b
Mistral:  mistral-7b, mistral-large, mixtral-8x7b
```

#### Configuration:
```yaml
# config.yaml
ai:
  provider: "bedrock"
  model: "claude-3-sonnet"
  region: "us-east-1"
```

```bash
# Environment variables
AI_PROVIDER=bedrock
AI_MODEL=claude-3-sonnet
AWS_REGION=us-east-1
```

#### AWS Authentication:
- Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- IAM role (recommended for EC2/ECS/Lambda)
- AWS credentials file (~/.aws/credentials)

### Architecture:
```
┌─────────────────────────────────────────────────────────────┐
│                    AI PROVIDER LAYER                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────┐    ┌─────────────────────┐         │
│  │ OpenAICompatible    │    │ BedrockProvider     │         │
│  │ Provider            │    │                     │         │
│  │                     │    │  • Claude format    │         │
│  │  • Ollama           │    │  • Titan format     │         │
│  │  • vLLM             │    │  • Llama format     │         │
│  │  • OpenAI           │    │  • Mistral format   │         │
│  │  • LocalAI          │    │                     │         │
│  └─────────────────────┘    └─────────────────────┘         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Files Added/Changed:
- `src/ai_provider.py` - New provider abstraction layer
- `docker-compose.bedrock.yml` - Bedrock deployment example
- Updated: config.py, ai_analyzer.py, rc_analyzer.py
- Updated: config.example.yaml, .env.example, requirements.txt

### Backward Compatibility:
- ✅ Existing Ollama/OpenAI configurations work unchanged
- ✅ No breaking changes to API or config format

## v1.9.24 - STABLE CHECKPOINT ✅ (2026-04-04)

### Status: Production-Ready AI-Driven Analysis

### Major Features in This Release:

#### 1. AI-Driven Tool Relationship Analysis
- AI semantically identifies which tool caused the failure
- No more rule-based pattern maintenance
- Handles novel relationships automatically

#### 2. Known Failure Patterns (KNOWN_FAILURE_PATTERNS)
- 25+ patterns for common DevOps tool failures
- Covers: kubectl, docker, helm, terraform, aws, npm, maven, git
- Provides AI with likely root causes and confidence guidance

#### 3. Multi-Style Natural Language Parser
- Handles Ollama/Llama prose responses (not just JSON)
- 5 extraction strategies for root cause
- Keyword-based category detection with scoring
- Language certainty confidence estimation

#### 4. Confidence Boosting
- Pattern-matched failures get minimum confidence floor
- Category and is_retriable from patterns when AI uncertain

### Supported LLM Response Styles:
- Markdown sections (**Summary**, ## Root Cause)
- Bullet points (- Root Cause:)
- Numbered lists (1. Issue:)
- Conversational prose
- Terse responses

### Test Coverage:
- kubectl rollout timeout → INFRASTRUCTURE, retriable
- Docker auth failure → CREDENTIAL
- NPM package not found → BUILD
- Permission denied → PERMISSION
- Network timeout → NETWORK, retriable

---

## v1.9.18 - Previous Stable Checkpoint

### Rollback Point (if needed)
- Rule-based identifier matching
- JSON-only response parsing

---

## Version History

| Version | Key Change |
|---------|------------|
| v1.9.24 | Multi-style NL parser, comprehensive |
| v1.9.23 | NL parser initial (Ollama support) |
| v1.9.22 | Confidence boosting, better error extraction |
| v1.9.21 | KNOWN_FAILURE_PATTERNS (25+ patterns) |
| v1.9.20 | Confidence guidelines in prompt |
| v1.9.19 | AI-driven tool relationship |
| v1.9.18 | Stable checkpoint (rule-based) |
| v1.9.17 | $ prefix docker commands |
| v1.9.16 | Jenkins Settings UI override |
| v1.9.15 | ISO timestamp pattern support |

## v1.9.25 - Feedback Loop & Fine-Tuning Export (2026-04-09)

### New Features:

#### 1. UI Feedback Panel (Voting)
- Thumbs up/down buttons after each analysis
- "Was this analysis helpful?" prompt
- Correction form for incorrect analyses
- Stores feedback to SQLite for learning

#### 2. Fine-Tuning Export
- `GET /feedback/export?format=jsonl` - OpenAI fine-tuning format
- `GET /feedback/export?format=json` - Raw export
- `GET /feedback/stats` - Accuracy metrics

#### 3. Few-Shot Learning (Already Working)
- Similar past cases injected into AI prompts
- Keyword-based similarity matching
- Confirmed fixes used as examples

### API Endpoints:
```
POST /feedback          - Submit user feedback
GET  /feedback          - Get feedback history
GET  /feedback/stats    - Accuracy metrics  
GET  /feedback/export   - Export for fine-tuning
```

### Data Flow:
```
User votes 👍/👎 → FeedbackStore (SQLite)
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
  Few-Shot Learning              Fine-Tuning Export
  (Real-time, in-prompt)         (Batch, for retraining)
```

---

## ✅ CHECKPOINT: v1.9.30 — Knowledge Store Phase 1 Complete

**Date:** 2026-04-10
**Status:** STABLE — All tests pass, ready for Phase 2

### What's Working
- Tool definition schema (YAML standard)
- SQLite storage (4 tables)
- Full CRUD API for tools
- Tool identification from commands/logs
- Error pattern matching
- AI prompt context generation

### Files Added/Changed in This Checkpoint
| File | Lines | Description |
|------|-------|-------------|
| `src/knowledge_store.py` | 1110 | NEW — Data models + SQLite storage |
| `src/server.py` | +250 | Knowledge API endpoints |
| `src/__init__.py` | +6 | Export new classes |
| `ui/nginx.conf` | +10 | Proxy /knowledge endpoint |

### Database Schema
```sql
tools (id, name, aliases, category, patterns_*, errors, ...)
tool_errors (id, tool_id, code, pattern, category, fix, ...)
knowledge_docs (id, tool_id, source_type, content, ...)
source_analysis_log (id, repo_url, branch, status, ...)
```

### API Endpoints Added
```
GET    /knowledge/tools
GET    /knowledge/tools/{id}
POST   /knowledge/tools
PUT    /knowledge/tools/{id}
DELETE /knowledge/tools/{id}
GET    /knowledge/identify?query=...
GET    /knowledge/match-error?snippet=...
GET    /knowledge/stats
```

### To Restore This Checkpoint
```bash
# Download v1.9.30 package
# Or rollback to this commit if using git
```

---

## Phase 2A: Source Code Analysis — Starting 2026-04-10

## Phase 2C: Doc URL Import — Starting 2026-04-10

## Phase 3: AI Integration — Starting 2026-04-10


## Phase 4: Training Pipeline — Starting 2026-04-10


## Phase 5: UI & Automation — Starting 2026-04-10

