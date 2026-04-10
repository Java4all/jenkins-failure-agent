# Changelog

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
