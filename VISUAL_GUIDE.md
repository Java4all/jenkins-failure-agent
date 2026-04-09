# Jenkins Failure Agent - Visual Guide

This document provides visual diagrams to help understand the system architecture.

---

## 1. High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│   🔴 Jenkins Build FAILS                                                    │
│          │                                                                  │
│          ▼                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                     AI AGENT ANALYZES                                │  │
│   │                                                                      │  │
│   │   📜 Console Log    🧠 AI Analysis    📚 History                    │  │
│   │   📋 Test Results   🔍 Pattern Match  📝 Feedback                   │  │
│   │   📁 Source Code    🛠️ Tool Detection                               │  │
│   │                                                                      │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│          │                                                                  │
│          ▼                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                        RESULT                                        │  │
│   │                                                                      │  │
│   │   ✅ Root Cause: "kubectl rollout timed out - pod OOMKilled"        │  │
│   │   📊 Confidence: 85%                                                 │  │
│   │   🏷️ Category: INFRASTRUCTURE                                       │  │
│   │   🔧 Fix: "Increase memory limit in deployment.yaml"                │  │
│   │   🔄 Retriable: Yes                                                  │  │
│   │                                                                      │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. System Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM COMPONENTS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  EXTERNAL SERVICES                      AGENT CORE                           │
│  ─────────────────                      ──────────                           │
│                                                                              │
│  ┌─────────────┐                        ┌─────────────────────────────────┐ │
│  │   Jenkins   │ ◄─────────────────────▶│          HYBRID ANALYZER        │ │
│  │   Server    │   builds, logs          │                                 │ │
│  └─────────────┘                        │  ┌───────────┐  ┌───────────┐   │ │
│                                         │  │Log Parser │  │RC Finder  │   │ │
│  ┌─────────────┐                        │  │(200+ tools)  │(context)  │   │ │
│  │   GitHub    │ ◄─────────────────────▶│  └───────────┘  └───────────┘   │ │
│  │   API       │   source code          │                                 │ │
│  └─────────────┘                        │  ┌───────────┐  ┌───────────┐   │ │
│                                         │  │RC Analyzer│  │Investigator  │ │
│  ┌─────────────┐                        │  │(AI-driven)│  │(MCP tools)│   │ │
│  │   Ollama    │ ◄─────────────────────▶│  └───────────┘  └───────────┘   │ │
│  │   (LLM)     │   AI prompts           │                                 │ │
│  └─────────────┘                        └─────────────────────────────────┘ │
│                                                    │                        │
│  ┌─────────────┐                                   │                        │
│  │   SQLite    │ ◄─────────────────────────────────┘                        │
│  │  (Feedback) │   learning data                                            │
│  └─────────────┘                                                            │
│                                                                              │
│  OUTPUTS                                                                     │
│  ───────                                                                     │
│                                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   Web UI    │  │  Jenkins    │  │   GitHub    │  │   Slack     │        │
│  │             │  │ Description │  │ PR Comment  │  │  Message    │        │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Two Analysis Modes

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CHOOSE YOUR MODE                                   │
├─────────────────────────────────┬───────────────────────────────────────────┤
│                                 │                                            │
│   🔄 ITERATIVE MODE             │   🔍 DEEP MODE                             │
│   ═══════════════               │   ═════════════                            │
│                                 │                                            │
│   Default, recommended          │   For complex issues                       │
│                                 │                                            │
│   ┌─────────────────────┐       │   ┌─────────────────────┐                 │
│   │                     │       │   │                     │                 │
│   │   AI Call 1         │       │   │   Tool: get_log     │                 │
│   │   confidence: 0.4   │       │   │   Tool: get_source  │                 │
│   │   "Need more info"  │       │   │   Tool: search_code │                 │
│   │         │           │       │   │   Tool: get_tests   │                 │
│   │         ▼           │       │   │   Tool: analyze     │                 │
│   │   AI Call 2         │       │   │   ...               │                 │
│   │   confidence: 0.6   │       │   │   Tool: conclude    │                 │
│   │   "Getting closer"  │       │   │                     │                 │
│   │         │           │       │   └─────────────────────┘                 │
│   │         ▼           │       │                                            │
│   │   AI Call 3         │       │   5-15 autonomous calls                   │
│   │   confidence: 0.85  │       │   AI decides what to investigate          │
│   │   "Found it!" ✓     │       │                                            │
│   │                     │       │                                            │
│   └─────────────────────┘       │                                            │
│                                 │                                            │
│   ~10-30 seconds                │   ~30-60 seconds                           │
│                                 │                                            │
└─────────────────────────────────┴───────────────────────────────────────────┘
```

---

## 4. Log Parsing - Tool Detection

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LOG PARSING PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  RAW JENKINS LOG                                                             │
│  ════════════════                                                            │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ [Pipeline] stage                                                       │ │
│  │ [Pipeline] { (Deploy)                                                  │ │
│  │ [Pipeline] sh                                                          │ │
│  │ 09:26:14  + kubectl rollout status deployment/myapp --timeout=300s    │ │
│  │ 09:26:16  Waiting for deployment "myapp" rollout to finish...         │ │
│  │ 09:31:14  error: timed out waiting for rollout to finish              │ │
│  │ [Pipeline] }                                                           │ │
│  │ [Pipeline] // stage                                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                        │                                     │
│                                        ▼                                     │
│  DETECTED PATTERNS                                                           │
│  ═════════════════                                                           │
│                                                                              │
│  ┌────────────────┐   ┌────────────────┐   ┌────────────────┐              │
│  │ STAGE          │   │ TOOL           │   │ ERROR          │              │
│  │                │   │                │   │                │              │
│  │ name: Deploy   │   │ name: kubectl  │   │ line: 6        │              │
│  │ status: FAILED │   │ line: 4        │   │ text: "timed   │              │
│  │                │   │ cmd: rollout   │   │  out waiting"  │              │
│  └────────────────┘   │  status...     │   │                │              │
│                       └────────────────┘   └────────────────┘              │
│                                                                              │
│  SUPPORTED FORMATS                                                           │
│  ═════════════════                                                           │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 09:26:14  + command        ← Standard (HH:MM:SS + prefix)             │ │
│  │ [2025-12-10T07:25:34Z] + cmd  ← ISO timestamp                         │ │
│  │ 15:06:19  $ docker top...  ← Docker container ($ prefix)              │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. AI Tool Relationship Analysis

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AI IDENTIFIES THE FAILING TOOL                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ERROR: "Could not find credentials entry with ID 'CI_GB-SVC-SHPE-PRD'"     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                     TOOL INVOCATIONS SENT TO AI                        │ │
│  │                                                                        │ │
│  │  [line 3] docker: docker top 00be608e763c8efd -eo pid,comm            │ │
│  │  [line 5] aws: aws ssm get-parameter --name /apix/CI_GB-SVC-SHPE-PRD  │ │
│  │  [line 6] jq: jq .Parameter.Value                                      │ │
│  │  [line 10] cat: cat deployment/template.yaml                           │ │
│  │                                                                        │ │
│  │  Which tool is related to the error?                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                        │                                     │
│                                        ▼                                     │
│                              ┌─────────────────┐                            │
│                              │   🧠 AI THINKS  │                            │
│                              │                 │                            │
│                              │  The error says │                            │
│                              │  'CI_GB-SVC-    │                            │
│                              │   SHPE-PRD'     │                            │
│                              │                 │                            │
│                              │  Line 5 has     │                            │
│                              │  that same ID!  │                            │
│                              │                 │                            │
│                              └────────┬────────┘                            │
│                                       │                                      │
│                                       ▼                                      │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                            AI RESPONSE                                  │ │
│  │                                                                        │ │
│  │  "related_tool_line": 5  ───▶  AWS command is the failing tool        │ │
│  │                                                                        │ │
│  │  Root Cause: Jenkins credential 'CI_GB-SVC-SHPE-PRD' not configured   │ │
│  │  Category: CREDENTIAL                                                  │ │
│  │  Confidence: 90%                                                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  UI shows: "Failed Command: aws ssm get-parameter..."                       │
│  (NOT docker or cat - those are unrelated)                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Known Failure Patterns

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       25+ KNOWN FAILURE PATTERNS                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                       │
│  │     KUBERNETES       │    │       DOCKER         │                       │
│  │     ──────────       │    │       ──────         │                       │
│  │                      │    │                      │                       │
│  │  • rollout timeout   │    │  • daemon not running│                       │
│  │  • resource not found│    │  • auth failed       │                       │
│  │  • connection refused│    │  • image not found   │                       │
│  │  • RBAC denied       │    │  • disk exhausted    │                       │
│  └──────────────────────┘    └──────────────────────┘                       │
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                       │
│  │        HELM          │    │      TERRAFORM       │                       │
│  │        ────          │    │      ─────────       │                       │
│  │                      │    │                      │                       │
│  │  • deploy failed     │    │  • state lock        │                       │
│  │  • chart not found   │    │  • provider failed   │                       │
│  └──────────────────────┘    └──────────────────────┘                       │
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                       │
│  │       AWS CLI        │    │         GIT          │                       │
│  │       ───────        │    │         ───          │                       │
│  │                      │    │                      │                       │
│  │  • creds not found   │    │  • SSH auth failed   │                       │
│  │  • IAM denied        │    │  • HTTPS auth failed │                       │
│  └──────────────────────┘    └──────────────────────┘                       │
│                                                                              │
│  ┌──────────────────────┐    ┌──────────────────────┐                       │
│  │      NPM/YARN        │    │    MAVEN/GRADLE      │                       │
│  │      ────────        │    │    ───────────       │                       │
│  │                      │    │                      │                       │
│  │  • package not found │    │  • dependency failed │                       │
│  │  • EACCES error      │    │  • compilation error │                       │
│  └──────────────────────┘    └──────────────────────┘                       │
│                                                                              │
│                                                                              │
│  WHEN PATTERN MATCHES:                                                       │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                        │ │
│  │  ✓ AI gets guidance on likely root causes                             │ │
│  │  ✓ Minimum confidence floor (e.g., 75%)                               │ │
│  │  ✓ Category pre-filled if AI uncertain                                │ │
│  │  ✓ is_retriable hint provided                                         │ │
│  │                                                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Ollama Natural Language Parser

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                 OLLAMA NATURAL LANGUAGE RESPONSE HANDLING                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PROBLEM: Ollama models often return prose instead of JSON                  │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  OLLAMA RESPONSE:                                                      │ │
│  │                                                                        │ │
│  │  Here's the root cause analysis:                                       │ │
│  │                                                                        │ │
│  │  **Summary**                                                           │ │
│  │  The pipeline failed with exit code 1 due to a timeout in kubectl.    │ │
│  │                                                                        │ │
│  │  **Root Cause Analysis**                                               │ │
│  │  The deployment exceeded the progress deadline because the pod         │ │
│  │  was experiencing OOMKilled restarts.                                  │ │
│  │                                                                        │ │
│  │  **Fix**                                                               │ │
│  │  Increase the memory limit in deployment.yaml                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                        │                                     │
│                                        ▼                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    NATURAL LANGUAGE PARSER                             │ │
│  │                                                                        │ │
│  │  5 EXTRACTION STRATEGIES:                                              │ │
│  │                                                                        │ │
│  │  1. Markdown sections    → **Summary**, ## Root Cause                 │ │
│  │  2. Bullet points        → - Root Cause:, * Issue:                    │ │
│  │  3. Numbered lists       → 1. Root Cause:, 2. Category:               │ │
│  │  4. Direct statements    → "failed because", "The issue is"           │ │
│  │  5. First paragraph      → fallback to first substantive text         │ │
│  │                                                                        │ │
│  │  + Keyword scoring for category                                        │ │
│  │  + Language certainty for confidence                                   │ │
│  │  + Retry keywords detection                                            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                        │                                     │
│                                        ▼                                     │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  EXTRACTED STRUCTURED RESULT:                                          │ │
│  │                                                                        │ │
│  │  {                                                                     │ │
│  │    "root_cause": "The pipeline failed due to timeout in kubectl...",  │ │
│  │    "category": "INFRASTRUCTURE",                                       │ │
│  │    "confidence": 0.75,                                                 │ │
│  │    "is_retriable": true,                                               │ │
│  │    "fix": "Increase the memory limit in deployment.yaml"              │ │
│  │  }                                                                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Feedback & Learning Loop

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         FEEDBACK & LEARNING LOOP                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                              ┌──────────────┐                                │
│                              │     USER     │                                │
│                              │   sees       │                                │
│                              │   result     │                                │
│                              └──────┬───────┘                                │
│                                     │                                        │
│              Was this analysis helpful?                                      │
│                                     │                                        │
│         ┌───────────────────────────┼───────────────────────────┐            │
│         │                           │                           │            │
│         ▼                           ▼                           ▼            │
│   ┌───────────┐              ┌───────────┐              ┌───────────┐       │
│   │           │              │           │              │           │       │
│   │  👍 YES   │              │  👎 NO    │              │ 📝 FIX    │       │
│   │           │              │           │              │           │       │
│   └─────┬─────┘              └─────┬─────┘              └─────┬─────┘       │
│         │                          │                          │              │
│         │                          │     ┌────────────────────┘              │
│         │                          │     │                                   │
│         │                          ▼     ▼                                   │
│         │                   ┌─────────────────┐                              │
│         │                   │ Enter correct   │                              │
│         │                   │ root cause:     │                              │
│         │                   │ ┌─────────────┐ │                              │
│         │                   │ │             │ │                              │
│         │                   │ └─────────────┘ │                              │
│         │                   │ Enter fix:      │                              │
│         │                   │ ┌─────────────┐ │                              │
│         │                   │ │             │ │                              │
│         │                   │ └─────────────┘ │                              │
│         │                   │ [Submit]        │                              │
│         │                   └────────┬────────┘                              │
│         │                            │                                       │
│         └────────────────────────────┼───────────────────────────────────    │
│                                      │                                       │
│                                      ▼                                       │
│                        ┌─────────────────────────┐                           │
│                        │    FEEDBACK STORE       │                           │
│                        │       (SQLite)          │                           │
│                        │                         │                           │
│                        │  job │ ai_said │ actual │                          │
│                        │  ────┼─────────┼────────│                          │
│                        │  app │ timeout │ OOM    │                          │
│                        │  web │ npm err │ ✓      │                          │
│                        └───────────┬─────────────┘                           │
│                                    │                                         │
│              ┌─────────────────────┴─────────────────────┐                   │
│              │                                           │                   │
│              ▼                                           ▼                   │
│   ┌─────────────────────┐                   ┌─────────────────────┐         │
│   │   FEW-SHOT LEARNING │                   │  FINE-TUNING EXPORT │         │
│   │   (immediate)       │                   │  (batch)            │         │
│   │                     │                   │                     │         │
│   │ Next analysis sees: │                   │ GET /feedback/export│         │
│   │                     │                   │                     │         │
│   │ ## SIMILAR CASES    │                   │ → JSONL format      │         │
│   │ Case 1: INFRA       │                   │ → OpenAI fine-tune  │         │
│   │ Error: timeout      │                   │ → Ollama training   │         │
│   │ Fix: increase mem   │                   │                     │         │
│   └─────────────────────┘                   └─────────────────────┘         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Docker Deployment

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DOCKER COMPOSE DEPLOYMENT                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                           ┌─────────────────┐                                │
│                           │   Web Browser   │                                │
│                           │  localhost:3000 │                                │
│                           └────────┬────────┘                                │
│                                    │                                         │
│  ┌─────────────────────────────────┼─────────────────────────────────────┐  │
│  │                    DOCKER COMPOSE NETWORK                              │  │
│  │                                 │                                      │  │
│  │   ┌─────────────────────────────┼─────────────────────────────────┐   │  │
│  │   │                             │                                 │   │  │
│  │   ▼                             ▼                             ▼   │   │  │
│  │ ┌───────────┐             ┌───────────┐             ┌───────────┐│   │  │
│  │ │           │             │           │             │           ││   │  │
│  │ │    UI     │────────────▶│   AGENT   │────────────▶│  OLLAMA   ││   │  │
│  │ │  (nginx)  │  API calls  │ (FastAPI) │  LLM calls  │  (llama3) ││   │  │
│  │ │           │             │           │             │           ││   │  │
│  │ │  :80      │             │  :8080    │             │  :11434   ││   │  │
│  │ │           │             │           │             │           ││   │  │
│  │ └───────────┘             └─────┬─────┘             └───────────┘│   │  │
│  │                                 │                                 │   │  │
│  │                                 │                                 │   │  │
│  │                           ┌─────┴─────┐                          │   │  │
│  │                           │           │                          │   │  │
│  │                           │  VOLUMES  │                          │   │  │
│  │                           │           │                          │   │  │
│  │                           └───────────┘                          │   │  │
│  │                                 │                                 │   │  │
│  │              ┌──────────────────┴──────────────────┐             │   │  │
│  │              │                                     │             │   │  │
│  │              ▼                                     ▼             │   │  │
│  │       ┌─────────────┐                       ┌─────────────┐     │   │  │
│  │       │ agent_data  │                       │ ollama_data │     │   │  │
│  │       │             │                       │             │     │   │  │
│  │       │ feedback.db │                       │ models/     │     │   │  │
│  │       │ (learning)  │                       │ llama3.2    │     │   │  │
│  │       └─────────────┘                       └─────────────┘     │   │  │
│  │                                                                  │   │  │
│  └──────────────────────────────────────────────────────────────────┘   │  │
│                                                                          │  │
└──────────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  COMMANDS:                                                                   │
│  ═════════                                                                   │
│  docker-compose up -d          # Start everything                           │
│  docker-compose logs -f agent  # Watch logs                                 │
│  docker-compose down           # Stop everything                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. API Endpoints

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API ENDPOINTS                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ANALYSIS                                                                    │
│  ════════                                                                    │
│                                                                              │
│  POST /analyze                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ Request:  { "job": "my-app", "build": 123, "mode": "iterative" }      │ │
│  │ Response: { "root_cause": {...}, "confidence": 0.85, ... }            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  FEEDBACK                                                                    │
│  ════════                                                                    │
│                                                                              │
│  POST /feedback                Submit thumbs up/down                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ { "job": "my-app", "build": 123, "was_correct": false,                │ │
│  │   "confirmed_root_cause": "The actual issue was...",                  │ │
│  │   "confirmed_fix": "Fixed by..." }                                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
│  GET /feedback                 Get feedback history                         │
│  GET /feedback/stats           Get accuracy metrics                         │
│  GET /feedback/export          Export for fine-tuning (JSONL)              │
│                                                                              │
│  CONFIGURATION                                                               │
│  ═════════════                                                               │
│                                                                              │
│  GET /config/jenkins           Get current Jenkins config                   │
│  POST /config/jenkins          Update Jenkins credentials                   │
│                                                                              │
│  HEALTH                                                                      │
│  ══════                                                                      │
│                                                                              │
│  GET /health                   Health check                                  │
│  GET /                         Serve Web UI                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 11. Complete Request Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE REQUEST FLOW                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. USER                2. UI              3. AGENT            4. RESULT    │
│  ══════                 ════              ═══════            ════════       │
│                                                                              │
│  ┌──────┐               ┌──────┐          ┌──────┐           ┌──────┐      │
│  │ User │               │ Web  │          │Agent │           │Result│      │
│  │clicks│               │  UI  │          │Server│           │ Page │      │
│  │Analyze               │      │          │      │           │      │      │
│  └──┬───┘               └──┬───┘          └──┬───┘           └──┬───┘      │
│     │                      │                 │                  │           │
│     │  "Analyze job #123"  │                 │                  │           │
│     │─────────────────────▶│                 │                  │           │
│     │                      │                 │                  │           │
│     │                      │  POST /analyze  │                  │           │
│     │                      │────────────────▶│                  │           │
│     │                      │                 │                  │           │
│     │                      │                 │──┐               │           │
│     │                      │                 │  │ Fetch log     │           │
│     │                      │                 │  │ from Jenkins  │           │
│     │                      │                 │◀─┘               │           │
│     │                      │                 │                  │           │
│     │                      │                 │──┐               │           │
│     │                      │                 │  │ Parse log     │           │
│     │                      │                 │  │ Detect tools  │           │
│     │                      │                 │◀─┘               │           │
│     │                      │                 │                  │           │
│     │                      │                 │──┐               │           │
│     │                      │                 │  │ AI Analysis   │           │
│     │                      │                 │  │ (Ollama)      │           │
│     │                      │                 │◀─┘               │           │
│     │                      │                 │                  │           │
│     │                      │  JSON Response  │                  │           │
│     │                      │◀────────────────│                  │           │
│     │                      │                 │                  │           │
│     │  Display result      │                 │                  │           │
│     │◀─────────────────────│                 │                  │           │
│     │                      │                 │                  │           │
│     │                      │                 │                  │           │
│     │  👍 or 👎            │                 │                  │           │
│     │─────────────────────▶│                 │                  │           │
│     │                      │                 │                  │           │
│     │                      │ POST /feedback  │                  │           │
│     │                      │────────────────▶│                  │           │
│     │                      │                 │                  │           │
│     │                      │                 │  Store for       │           │
│     │                      │                 │  learning        │           │
│     │                      │                 │                  │           │
│     │  "Thank you!"        │                 │                  │           │
│     │◀─────────────────────│                 │                  │           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           QUICK REFERENCE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  START:          docker-compose up -d                                        │
│  OPEN UI:        http://localhost:3000                                       │
│  VIEW LOGS:      docker-compose logs -f agent                               │
│  STOP:           docker-compose down                                         │
│                                                                              │
│  MODES:          Iterative (default) | Deep (--deep)                        │
│  CONFIDENCE:     0-100% (higher = more certain)                             │
│  RETRIABLE:      Yes = try again | No = need to fix                         │
│                                                                              │
│  FEEDBACK:       👍 = correct | 👎 = wrong (enter correction)               │
│  EXPORT:         GET /feedback/export?format=jsonl                          │
│                                                                              │
│  PATTERNS:       25+ known failure patterns for common tools                │
│  TOOLS:          200+ detected (kubectl, docker, aws, npm, git...)          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```
