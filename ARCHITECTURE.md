# Jenkins Failure Analysis Agent - Architecture

## Table of Contents
1. [System Overview](#system-overview)
2. [Component Architecture](#component-architecture)
3. [Analysis Flow](#analysis-flow)
4. [AI-Driven Analysis](#ai-driven-analysis)
5. [Log Parsing Pipeline](#log-parsing-pipeline)
6. [Feedback & Learning System](#feedback--learning-system)
7. [Data Models](#data-models)
8. [API Reference](#api-reference)

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     JENKINS FAILURE ANALYSIS AGENT                          │
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   Jenkins   │    │   GitHub    │    │   Ollama    │    │   SQLite    │  │
│  │   Server    │    │   API       │    │   (LLM)     │    │   (Feedback)│  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │          │
│         └──────────────────┼──────────────────┼──────────────────┘          │
│                            │                  │                             │
│                            ▼                  ▼                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         HYBRID ANALYZER                               │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │ Log Parser  │  │ RC Finder   │  │ RC Analyzer │  │ Investigator│  │  │
│  │  │             │  │             │  │ (Iterative) │  │ (Deep Mode) │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                            │                                                │
│                            ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                              WEB UI                                   │  │
│  │   Analysis Results │ Feedback Voting │ Jenkins Settings │ History    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           SOURCE FILES                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  src/                                                                    │
│  ├── server.py           ← FastAPI server, REST endpoints               │
│  ├── hybrid_analyzer.py  ← Orchestrates Iterative & Deep modes          │
│  ├── rc_analyzer.py      ← AI-driven root cause analysis                │
│  ├── rc_finder.py        ← Rule-based error context extraction          │
│  ├── log_parser.py       ← Jenkins log parsing, tool detection          │
│  ├── feedback_store.py   ← SQLite storage, few-shot learning            │
│  ├── jenkins_client.py   ← Jenkins API integration                      │
│  ├── github_client.py    ← GitHub API for source fetching               │
│  ├── ai_analyzer.py      ← LLM API wrapper (Ollama/OpenAI)              │
│  ├── groovy_analyzer.py  ← Groovy/Jenkins DSL analysis                  │
│  └── agent/                                                              │
│      ├── investigator.py ← MCP-based deep investigation                 │
│      └── prompts.py      ← AI prompt templates                          │
│                                                                          │
│  ui/                                                                     │
│  └── index.html          ← Single-page React application                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Two Analysis Modes

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        SELECT ANALYSIS MODE                              │
├────────────────────────────────┬────────────────────────────────────────┤
│                                │                                         │
│   🔄 ITERATIVE (Default)       │   🔍 DEEP (Agentic)                     │
│                                │                                         │
│   Multi-call AI analysis       │   MCP Tool-based investigation         │
│   Up to 3 iterations           │   5-15 tool calls                      │
│   Source code pre-loading      │   Dynamic source exploration           │
│   Confidence-based stopping    │   Autonomous decision making           │
│                                │                                         │
│   Best for:                    │   Best for:                            │
│   • Quick analysis             │   • Complex failures                   │
│   • Known error patterns       │   • Multi-file issues                  │
│   • High confidence results    │   • Deep code tracing                  │
│                                │                                         │
│         ↓                      │            ↓                           │
│   ┌─────────────┐              │   ┌─────────────┐                      │
│   │ RC_Analyzer │              │   │ Investigator│                      │
│   │             │              │   │             │                      │
│   │ Iteration 1 │              │   │ Tool Call 1 │                      │
│   │ Iteration 2 │              │   │ Tool Call 2 │                      │
│   │ Iteration 3 │              │   │    ...      │                      │
│   └─────────────┘              │   │ Tool Call N │                      │
│                                │   └─────────────┘                      │
└────────────────────────────────┴────────────────────────────────────────┘
```

---

## Analysis Flow

### Complete Request Flow

```
┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌─────────────┐
│  User    │────▶│  Web UI  │────▶│  REST API    │────▶│  Hybrid     │
│          │     │          │     │  /analyze    │     │  Analyzer   │
└──────────┘     └──────────┘     └──────────────┘     └──────┬──────┘
                                                               │
                 ┌─────────────────────────────────────────────┘
                 │
                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           ANALYSIS PIPELINE                             │
├────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  STEP 1: Fetch Data                                                     │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │ Jenkins     │    │ Console     │    │ Test        │                 │
│  │ Build Info  │    │ Log         │    │ Results     │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│         │                  │                  │                         │
│         └──────────────────┼──────────────────┘                         │
│                            ▼                                            │
│  STEP 2: Parse Log                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      LOG PARSER                                   │  │
│  │  • Extract errors, stages, methods                               │  │
│  │  • Detect tool invocations (kubectl, docker, aws, etc.)          │  │
│  │  • Build execution timeline                                       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                            │                                            │
│                            ▼                                            │
│  STEP 3: Find Root Cause Context                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     RC FINDER                                     │  │
│  │  • Identify primary error line                                    │  │
│  │  • Extract surrounding context                                    │  │
│  │  • Find related tool invocations                                  │  │
│  │  • Extract identifiers (IDs, paths, names)                        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                            │                                            │
│                            ▼                                            │
│  STEP 4: AI Analysis                                                    │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                     RC ANALYZER                                   │  │
│  │  • Match known failure patterns                                   │  │
│  │  • Inject few-shot examples from history                          │  │
│  │  • Call LLM with structured prompt                                │  │
│  │  • Parse response (JSON or Natural Language)                      │  │
│  │  • Boost confidence based on patterns                             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                            │                                            │
│                            ▼                                            │
│  STEP 5: Return Result                                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  {                                                                │  │
│  │    "root_cause": "kubectl rollout timed out...",                  │  │
│  │    "category": "INFRASTRUCTURE",                                  │  │
│  │    "confidence": 0.85,                                            │  │
│  │    "failing_tool": {"tool_name": "kubectl", ...},                 │  │
│  │    "fix": "Check pod readiness probes...",                        │  │
│  │    "is_retriable": true                                           │  │
│  │  }                                                                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

---

## AI-Driven Analysis

### Known Failure Patterns

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    KNOWN_FAILURE_PATTERNS (25+)                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  KUBERNETES                           DOCKER                             │
│  ├── rollout timeout                  ├── daemon not running             │
│  ├── resource not found               ├── registry auth failed           │
│  ├── connection refused               ├── image not found                │
│  └── RBAC permission denied           └── disk space exhausted           │
│                                                                          │
│  HELM                                 TERRAFORM                          │
│  ├── release deployment failed        ├── state lock conflict            │
│  └── chart not found                  └── provider installation failed   │
│                                                                          │
│  AWS                                  GIT                                │
│  ├── credentials not found            ├── SSH auth failed                │
│  └── IAM permission denied            └── HTTPS auth failed              │
│                                                                          │
│  NPM/YARN                             MAVEN/GRADLE                       │
│  ├── package not found                ├── dependency resolution failed   │
│  └── permission error                 └── compilation error              │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      PATTERN MATCHING FLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Error: "error: timed out waiting for rollout to finish"               │
│                              │                                           │
│                              ▼                                           │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │ MATCHED PATTERN: kubectl rollout timeout                        │    │
│   │                                                                 │    │
│   │ ## KNOWN FAILURE PATTERN DETECTED ##                            │    │
│   │ Tool: kubectl rollout                                           │    │
│   │ Symptom: Deployment rollout timed out                           │    │
│   │                                                                 │    │
│   │ LIKELY ROOT CAUSES (investigate in order):                      │    │
│   │   1. Pod failed readiness probe                                 │    │
│   │   2. Pod failed liveness probe                                  │    │
│   │   3. Container in CrashLoopBackOff                              │    │
│   │   4. ImagePullBackOff                                           │    │
│   │   5. Insufficient resources                                     │    │
│   │                                                                 │    │
│   │ Minimum confidence: 0.75                                        │    │
│   │ Category: INFRASTRUCTURE                                        │    │
│   │ Is Retriable: true                                              │    │
│   └────────────────────────────────────────────────────────────────┘    │
│                              │                                           │
│                              ▼                                           │
│   Injected into AI prompt for guided analysis                           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### AI Tool Relationship Analysis

```
┌─────────────────────────────────────────────────────────────────────────┐
│                 AI-DRIVEN TOOL RELATIONSHIP ANALYSIS                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ERROR MESSAGE:                                                          │
│  "ERROR: Could not find credentials entry with ID 'CI_GB-SVC-SHPE-PRD'" │
│                                                                          │
│  TOOL INVOCATIONS SENT TO AI:                                           │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ ## TOOL INVOCATIONS ##                                             │ │
│  │ Shell commands executed during the build:                          │ │
│  │ Identify which tool (by line number) is MOST RELATED.              │ │
│  │ ─────────────────────────────────────────────────────────────────  │ │
│  │ [line 3] docker: docker top 00be608e763c8efd373cb -eo pid,comm     │ │
│  │ [line 5] aws: aws ssm get-parameter --name /apix/CI_GB-SVC-SHPE-PRD│ │
│  │ [line 6] jq: jq .Parameter.Value                                   │ │
│  │ [line 10] cat: cat deployment/template.yaml                        │ │
│  │ ─────────────────────────────────────────────────────────────────  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    │                                     │
│                                    ▼                                     │
│  AI RESPONSE:                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ {                                                                  │ │
│  │   "root_cause": "Jenkins credentials 'CI_GB-SVC-SHPE-PRD' not     │ │
│  │                  configured. The AWS SSM command would use this    │ │
│  │                  credential to fetch secrets.",                    │ │
│  │   "related_tool_line": 5,  ← AI identifies the AWS command        │ │
│  │   "category": "CREDENTIAL",                                        │ │
│  │   "confidence": 0.90                                               │ │
│  │ }                                                                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    │                                     │
│                                    ▼                                     │
│  RESULT: Shows AWS command as "Failed Command" in UI                    │
│  (Not the unrelated docker or cat commands)                             │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Natural Language Response Parser

```
┌─────────────────────────────────────────────────────────────────────────┐
│              MULTI-STYLE NATURAL LANGUAGE PARSER                         │
│                    (Ollama Compatibility)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  PROBLEM: Ollama models often return prose instead of JSON              │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Here's the root cause analysis:                                    │ │
│  │                                                                    │ │
│  │ **Summary**                                                        │ │
│  │ The pipeline failed with exit code 1 due to a timeout...          │ │
│  │                                                                    │ │
│  │ **Root Cause Analysis**                                            │ │
│  │ 1. **Timeout Error**: The deployment exceeded...                   │ │
│  │                                                                    │ │
│  │ **Fix**                                                            │ │
│  │ To resolve this, increase the timeout value...                     │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    │                                     │
│                                    ▼                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                 _parse_natural_language_response()                 │ │
│  ├────────────────────────────────────────────────────────────────────┤ │
│  │                                                                    │ │
│  │  STRATEGY 1: Markdown sections (**Summary**, ##Root Cause)        │ │
│  │  STRATEGY 2: Bullet/list format (- Root Cause:, 1. Issue:)        │ │
│  │  STRATEGY 3: Direct statements (failed because, The issue is)     │ │
│  │  STRATEGY 4: First substantive paragraph                          │ │
│  │  STRATEGY 5: Cleaned fallback text                                │ │
│  │                                                                    │ │
│  │  + _detect_category()      → Keyword scoring                      │ │
│  │  + _estimate_confidence()  → Language certainty                   │ │
│  │  + _determine_retriable()  → Retry keywords                       │ │
│  │  + _extract_fix()          → Solution patterns                    │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    │                                     │
│                                    ▼                                     │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ EXTRACTED RESULT:                                                  │ │
│  │ {                                                                  │ │
│  │   "root_cause": "The pipeline failed with exit code 1 due to...", │ │
│  │   "category": "INFRASTRUCTURE",                                    │ │
│  │   "confidence": 0.75,                                              │ │
│  │   "is_retriable": true,                                            │ │
│  │   "fix": "increase the timeout value..."                          │ │
│  │ }                                                                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Log Parsing Pipeline

### Shell Command Detection

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    JENKINS LOG FORMATS SUPPORTED                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  FORMAT 1: Standard timestamp + command                                  │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ 09:26:16  + kubectl rollout status deployment/myapp                │ │
│  │ HH:MM:SS  + command                                                │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  FORMAT 2: ISO timestamp (Jenkins API)                                   │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ [2025-12-10T07:25:34.270Z] + env                                   │ │
│  │ [ISO timestamp]           + command                                │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  FORMAT 3: Docker container commands ($ prefix)                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ 15:06:19  $ docker top <container_id> -eo pid,comm                 │ │
│  │ HH:MM:SS  $ docker_wrapper_command                                 │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  PIPELINE BLOCK MARKERS:                                                 │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ [Pipeline] stage                    ← Block START                  │ │
│  │ [Pipeline] // stage                 ← Block END (// = closing)     │ │
│  │ [Pipeline] withDockerContainer      ← Docker block START           │ │
│  │ [Pipeline] // withDockerContainer   ← Docker block END             │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Tool Invocation Detection

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     TOOL INVOCATION DETECTION                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  BUILTIN TOOL PATTERNS:                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ aws, az, gcloud           ← Cloud CLIs                             │ │
│  │ kubectl, helm             ← Kubernetes tools                       │ │
│  │ docker, podman            ← Container tools                        │ │
│  │ terraform, ansible        ← IaC tools                              │ │
│  │ mvn, gradle, npm, yarn    ← Build tools                            │ │
│  │ git, curl, wget           ← Common utilities                       │ │
│  │ p2l, a2l                  ← Custom enterprise tools                │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  DETECTION FLOW:                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Log Line: "09:26:16  + kubectl rollout status deployment/app"      │ │
│  │                             │                                      │ │
│  │                             ▼                                      │ │
│  │ 1. Match timestamp pattern (HH:MM:SS)                              │ │
│  │ 2. Match command prefix (+ or $)                                   │ │
│  │ 3. Extract command: "kubectl rollout status deployment/app"       │ │
│  │ 4. Identify tool: "kubectl"                                        │ │
│  │ 5. Track output lines until next command                          │ │
│  │ 6. Detect exit code if present                                     │ │
│  │                             │                                      │ │
│  │                             ▼                                      │ │
│  │ ToolInvocation {                                                   │ │
│  │   tool_name: "kubectl",                                            │ │
│  │   command_line: "kubectl rollout status deployment/app",           │ │
│  │   line_number: 1234,                                               │ │
│  │   output_lines: ["deployment/app successfully rolled out"],        │ │
│  │   exit_code: 0                                                     │ │
│  │ }                                                                  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Feedback & Learning System

### Complete Feedback Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      FEEDBACK & LEARNING SYSTEM                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│                         ┌─────────────────┐                              │
│                         │     USER        │                              │
│                         └────────┬────────┘                              │
│                                  │                                       │
│                    ┌─────────────┼─────────────┐                         │
│                    ▼             ▼             ▼                         │
│              ┌──────────┐  ┌──────────┐  ┌──────────────┐               │
│              │  👍 Yes  │  │  👎 No   │  │ 📝 Correction│               │
│              └────┬─────┘  └────┬─────┘  └──────┬───────┘               │
│                   │             │               │                        │
│                   └─────────────┼───────────────┘                        │
│                                 │                                        │
│                                 ▼                                        │
│              ┌──────────────────────────────────────┐                    │
│              │          POST /feedback              │                    │
│              │  {                                   │                    │
│              │    "job": "my-pipeline",             │                    │
│              │    "build": 123,                     │                    │
│              │    "was_correct": true/false,        │                    │
│              │    "ai_root_cause": "...",           │                    │
│              │    "confirmed_root_cause": "...",    │                    │
│              │    "confirmed_fix": "..."            │                    │
│              │  }                                   │                    │
│              └──────────────────┬───────────────────┘                    │
│                                 │                                        │
│                                 ▼                                        │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    FEEDBACK STORE (SQLite)                        │   │
│  │  /app/data/feedback.db                                            │   │
│  ├──────────────────────────────────────────────────────────────────┤   │
│  │ id │ job_name │ category │ ai_root_cause │ confirmed │ correct   │   │
│  │ 1  │ deploy   │ INFRA    │ timeout...    │ OOMKilled │ false     │   │
│  │ 2  │ build    │ BUILD    │ npm failed    │ npm failed│ true      │   │
│  │ 3  │ test     │ TEST     │ assertion     │ assertion │ true      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                 │                                        │
│              ┌──────────────────┴──────────────────┐                     │
│              │                                     │                     │
│              ▼                                     ▼                     │
│  ┌────────────────────────┐          ┌────────────────────────────┐     │
│  │   FEW-SHOT LEARNING    │          │   FINE-TUNING EXPORT       │     │
│  │   (Real-time)          │          │   (Batch)                  │     │
│  │                        │          │                            │     │
│  │ Similar cases from     │          │ GET /feedback/export       │     │
│  │ history injected into  │          │                            │     │
│  │ AI prompt:             │          │ Returns JSONL format:      │     │
│  │                        │          │ {"messages": [             │     │
│  │ ## SIMILAR PAST CASES  │          │   {"role": "system",...},  │     │
│  │ Case 1: INFRASTRUCTURE │          │   {"role": "user",...},    │     │
│  │ Error: kubectl timeout │          │   {"role": "assistant",...}│     │
│  │ Root Cause: OOMKilled  │          │ ]}                         │     │
│  │ Fix: Increase memory   │          │                            │     │
│  │                        │          │ Use for:                   │     │
│  │ → Improves next        │          │ • OpenAI fine-tuning       │     │
│  │   analysis immediately │          │ • Ollama model training    │     │
│  └────────────────────────┘          └────────────────────────────┘     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Few-Shot Learning Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       FEW-SHOT LEARNING FLOW                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  STEP 1: New Analysis Request                                            │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Error: "kubectl rollout status timed out"                          │ │
│  │ Category: INFRASTRUCTURE                                           │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                 │                                        │
│                                 ▼                                        │
│  STEP 2: Search Feedback Store                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ find_similar(                                                      │ │
│  │   error_snippet="kubectl rollout status timed out",                │ │
│  │   category="INFRASTRUCTURE",                                       │ │
│  │   limit=3                                                          │ │
│  │ )                                                                  │ │
│  │                                                                    │ │
│  │ Keyword Overlap Scoring:                                           │ │
│  │ • Tokenize error snippet                                           │ │
│  │ • Compare with stored entries                                      │ │
│  │ • Boost score for matching category/stage                          │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                 │                                        │
│                                 ▼                                        │
│  STEP 3: Inject into AI Prompt                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ ## SIMILAR PAST CASES ##                                           │ │
│  │                                                                    │ │
│  │ Case 1: INFRASTRUCTURE in stage "Deploy"                          │ │
│  │ Error: kubectl rollout status deployment/app timed out            │ │
│  │ Root Cause: Pod failed readiness probe - /health returned 500     │ │
│  │ Fix: Fixed database connection string in ConfigMap                │ │
│  │                                                                    │ │
│  │ Case 2: INFRASTRUCTURE in stage "Deploy"                          │ │
│  │ Error: Deployment rollout exceeded progress deadline              │ │
│  │ Root Cause: Container OOMKilled - memory limit too low            │ │
│  │ Fix: Increased memory limit from 256Mi to 512Mi                   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                 │                                        │
│                                 ▼                                        │
│  STEP 4: AI Uses Examples for Better Analysis                           │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ AI sees patterns from similar past cases and produces             │ │
│  │ more accurate root cause with higher confidence                   │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Models

### Core Data Structures

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DATA MODELS                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ToolInvocation                        ParsedLog                         │
│  ┌─────────────────────────────┐      ┌─────────────────────────────┐   │
│  │ tool_name: str              │      │ errors: List[Error]         │   │
│  │ command_line: str           │      │ stages: List[str]           │   │
│  │ line_number: int            │      │ tool_invocations: List      │   │
│  │ output_lines: List[str]     │      │ failed_stage: str           │   │
│  │ exit_code: Optional[int]    │      │ failed_method: str          │   │
│  └─────────────────────────────┘      │ stage_sequence: List[str]   │   │
│                                       │ method_call_sequence: List  │   │
│  RootCauseContext                     └─────────────────────────────┘   │
│  ┌─────────────────────────────┐                                        │
│  │ error_line: str             │      RCAnalysisResult                  │
│  │ error_line_number: int      │      ┌─────────────────────────────┐   │
│  │ surrounding_lines: List     │      │ root_cause: str             │   │
│  │ identifiers: List[str]      │      │ confidence: float           │   │
│  │ related_tool: Optional[Dict]│      │ category: str               │   │
│  └─────────────────────────────┘      │ is_retriable: bool          │   │
│                                       │ fix: str                    │   │
│  FeedbackEntry                        │ failing_tool: Optional[Dict]│   │
│  ┌─────────────────────────────┐      │ iterations_used: int        │   │
│  │ job_name: str               │      └─────────────────────────────┘   │
│  │ build_number: int           │                                        │
│  │ error_category: str         │      AnalysisResult (Final)            │
│  │ error_snippet: str          │      ┌─────────────────────────────┐   │
│  │ ai_root_cause: str          │      │ build_info: Dict            │   │
│  │ confirmed_root_cause: str   │      │ failure_analysis: Dict      │   │
│  │ confirmed_fix: str          │      │ root_cause: RootCause       │   │
│  │ was_correct: bool           │      │ recommendations: List       │   │
│  │ timestamp: str              │      │ retry_assessment: Dict      │   │
│  └─────────────────────────────┘      └─────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Failure Categories

```
┌─────────────────────────────────────────────────────────────────────────┐
│                       FAILURE CATEGORIES (17)                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  CATEGORY          │ DESCRIPTION                    │ RETRIABLE         │
│  ──────────────────┼────────────────────────────────┼──────────────────│
│  CREDENTIAL        │ Auth/token failures            │ Sometimes         │
│  NETWORK           │ Connection/timeout issues      │ Usually           │
│  PERMISSION        │ Access denied/RBAC             │ No                │
│  INFRASTRUCTURE    │ K8s/Docker/resource issues     │ Sometimes         │
│  CONFIGURATION     │ Config/YAML errors             │ No                │
│  BUILD             │ Compilation/dependency         │ No                │
│  TEST              │ Test failures                  │ No                │
│  GROOVY_LIBRARY    │ Jenkins shared library         │ No                │
│  GROOVY_CPS        │ CPS transformation errors      │ No                │
│  TOOL_ERROR        │ CLI tool failures              │ Sometimes         │
│  ARTIFACT          │ Artifact upload/download       │ Sometimes         │
│  SCM               │ Git/checkout issues            │ Sometimes         │
│  DEPLOYMENT        │ Deploy step failures           │ Sometimes         │
│  TIMEOUT           │ Step/build timeout             │ Yes               │
│  RESOURCE          │ Memory/CPU exhaustion          │ Sometimes         │
│  FLAKY             │ Intermittent failures          │ Yes               │
│  UNKNOWN           │ Unclassified                   │ Unknown           │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## API Reference

### Endpoints

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          API ENDPOINTS                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ANALYSIS                                                                │
│  ────────────────────────────────────────────────────────────────────── │
│  POST /analyze                                                           │
│    Request:  { job, build, mode, user_hint, ... }                       │
│    Response: { build_info, failure_analysis, root_cause, ... }          │
│                                                                          │
│  GET /analyze/stream                                                     │
│    SSE stream of analysis progress                                       │
│                                                                          │
│  FEEDBACK                                                                │
│  ────────────────────────────────────────────────────────────────────── │
│  POST /feedback                                                          │
│    Submit user feedback (thumbs up/down)                                │
│    Request:  { job, build, was_correct, confirmed_root_cause, ... }     │
│    Response: { id, status }                                             │
│                                                                          │
│  GET /feedback                                                           │
│    Get feedback history                                                  │
│    Query:    ?category=INFRASTRUCTURE&limit=50                          │
│    Response: { entries, count, stats }                                  │
│                                                                          │
│  GET /feedback/stats                                                     │
│    Get accuracy metrics                                                  │
│    Response: { accuracy_percent, total_feedback, by_category }          │
│                                                                          │
│  GET /feedback/export                                                    │
│    Export for fine-tuning                                                │
│    Query:    ?format=jsonl&correct_only=true                            │
│    Response: JSONL file (OpenAI format)                                 │
│                                                                          │
│  CONFIGURATION                                                           │
│  ────────────────────────────────────────────────────────────────────── │
│  GET /config/jenkins                                                     │
│    Get current Jenkins config (token masked)                            │
│                                                                          │
│  POST /config/jenkins                                                    │
│    Update Jenkins credentials at runtime                                 │
│    Request:  { url, username, api_token }                               │
│                                                                          │
│  HEALTH                                                                  │
│  ────────────────────────────────────────────────────────────────────── │
│  GET /health                                                             │
│    Health check endpoint                                                 │
│                                                                          │
│  GET /                                                                   │
│    Serve Web UI                                                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Deployment

### Docker Compose Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      DOCKER COMPOSE DEPLOYMENT                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                         docker-compose.yml                       │    │
│  ├─────────────────────────────────────────────────────────────────┤    │
│  │                                                                  │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │    │
│  │  │    agent     │  │    ollama    │  │     ui       │           │    │
│  │  │              │  │              │  │              │           │    │
│  │  │ FastAPI      │  │ LLM Server   │  │ Nginx        │           │    │
│  │  │ Python 3.11  │  │ llama3.2     │  │ Static files │           │    │
│  │  │ Port: 8080   │  │ Port: 11434  │  │ Port: 80     │           │    │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘           │    │
│  │         │                 │                 │                    │    │
│  │         └─────────────────┼─────────────────┘                    │    │
│  │                           │                                      │    │
│  │                           ▼                                      │    │
│  │                    ┌──────────────┐                              │    │
│  │                    │   network    │                              │    │
│  │                    │  jenkins-net │                              │    │
│  │                    └──────────────┘                              │    │
│  │                                                                  │    │
│  │  VOLUMES:                                                        │    │
│  │  ┌──────────────┐  ┌──────────────┐                              │    │
│  │  │ agent_data   │  │ ollama_data  │                              │    │
│  │  │ /app/data    │  │ /root/.ollama│                              │    │
│  │  │ (feedback.db)│  │ (models)     │                              │    │
│  │  └──────────────┘  └──────────────┘                              │    │
│  │                                                                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
│  COMMANDS:                                                               │
│  ─────────────────────────────────────────────────────────────────────  │
│  docker-compose up -d              # Start all services                  │
│  docker-compose logs -f agent      # View agent logs                     │
│  docker-compose down               # Stop all services                   │
│  docker-compose build              # Rebuild images                      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Version History

| Version | Date | Key Features |
|---------|------|--------------|
| v1.9.25 | 2026-04-09 | Feedback voting UI, fine-tuning export |
| v1.9.24 | 2026-04-04 | Multi-style NL parser (Ollama support) |
| v1.9.21 | 2026-04-04 | Known failure patterns (25+) |
| v1.9.19 | 2026-04-04 | AI-driven tool relationship |
| v1.9.18 | 2026-04-04 | Stable checkpoint (rule-based) |
| v1.9.17 | 2026-04-04 | Docker $ prefix commands |
| v1.9.16 | 2026-04-04 | Jenkins Settings UI |
| v1.9.15 | 2026-04-04 | ISO timestamp support |
