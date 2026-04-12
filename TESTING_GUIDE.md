# Manual Testing Guide - Jenkins Failure Agent v2.0.0

## Prerequisites

1. Docker Desktop installed and running
2. 16GB+ RAM recommended
3. Ports 3000, 8080, 11434 available

---

## STEP 1: Start the System

```bash
# 1.1 Unzip
unzip jenkins-failure-agent-v2.0.0.zip -d jenkins-failure-agent
cd jenkins-failure-agent

# 1.2 Create config
cp .env.example .env

# 1.3 Start services
make start

# 1.4 Wait for Ollama model download (~4GB, first time only)
# Watch logs until you see "llama3:8b pulled successfully"
docker-compose logs -f ollama
# Press Ctrl+C to exit logs

# 1.5 Verify health
curl http://localhost:8080/health
# Expected: {"status": "healthy", ...}
```

---

## STEP 2: Open the UI

**Open browser:** http://localhost:3000

You should see three tabs at the top:
- **Analysis** - Analyze Jenkins builds
- **Knowledge** - Manage tools and docs
- **Training** - Export training data

---

## TEST 1: Knowledge Base - Import from URL

### Goal: Import kubectl documentation and create a tool

**Steps:**

1. **Click** "Knowledge" tab at the top
2. **Click** "Import" sub-tab (third tab under Knowledge)
3. **Enter URL:** `https://kubernetes.io/docs/reference/kubectl/cheatsheet/`
4. **Enter Tool Name:** `kubectl`
5. **Click** "Import Documentation" button
6. **Wait** for import to complete (5-10 seconds)

**Expected Result:**
- ✅ Green message: "Doc saved: kubectl Cheat Sheet"
- ✅ Shows: Tool "kubectl" (created new)
- ✅ Shows: X commands, Y errors extracted

**Verify:**

7. **Click** "Tools" sub-tab
8. **See** `kubectl` in the list
9. **Click** on `kubectl` row to expand
10. **See** extracted commands (e.g., "kubectl apply", "kubectl get")

**Verify Docs:**

11. **Click** "Docs" sub-tab
12. **See** document with green badge showing `kubectl`

---

## TEST 2: Knowledge Base - Edit Tool

### Goal: Modify a tool's details

**Steps:**

1. **Click** "Knowledge" tab
2. **Click** "Tools" sub-tab
3. **Click** on `kubectl` row to expand it
4. **Click** "Edit" button (blue)
5. **Change** description to: "Kubernetes command-line tool"
6. **Add** to Command Patterns (new line): `kubectl logs`
7. **Click** "Save Changes" button

**Expected Result:**
- ✅ Modal closes
- ✅ Tool shows updated description
- ✅ New command pattern visible when expanded

---

## TEST 3: Knowledge Base - Add Tool Manually (API)

### Goal: Add an internal tool that isn't publicly documented

**Run in terminal:**

```bash
curl -X POST http://localhost:8080/knowledge/tools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "a2l",
    "category": "deploy",
    "description": "Internal deployment CLI for Kubernetes",
    "patterns_commands": ["a2l deploy", "a2l rollback", "a2l status"],
    "patterns_env_vars": ["A2L_TOKEN", "A2L_CLUSTER"],
    "errors": [
      {
        "code": "A2L_AUTH_FAILED",
        "pattern": "A2L_AUTH_FAILED|authentication failed|token expired",
        "category": "CREDENTIAL",
        "description": "Authentication token is invalid or expired",
        "fix": "Run: a2l auth refresh"
      },
      {
        "code": "A2L_CLUSTER_NOT_FOUND",
        "pattern": "cluster.*not found|A2L_CLUSTER_NOT_FOUND",
        "category": "CONFIGURATION",
        "description": "Target cluster does not exist",
        "fix": "Check cluster name: a2l clusters list"
      }
    ]
  }'
```

**Expected:** Returns `{"id": 2, "name": "a2l", ...}`

**Verify in UI:**
1. **Refresh** the browser (F5)
2. **Click** "Knowledge" → "Tools"
3. **See** `a2l` in the list with 2 errors

---

## TEST 4: Training Pipeline - Full Workflow

### Goal: Create training data from your tools

**IMPORTANT:** You must have tools with error patterns first (do TEST 3 first!)

### Step 4.1: Check Stats

1. **Click** "Training" tab at the top
2. **See** statistics panel showing:
   - Examples from Knowledge: should be > 0 if you added tools with errors
   - Examples from Feedback: 0 (unless you've given feedback)

### Step 4.2: Create Training Job

3. **Enter** Job Name: `my-first-job`
4. **Select** Format: `JSONL (OpenAI/Ollama)`
5. **Check** both boxes: Include feedback, Include knowledge
6. **Click** "Create Job" button

**Expected:**
- ✅ Job appears in list below
- ✅ Status: `pending` (gray badge)

### Step 4.3: Prepare Job

7. **Find** your job in the list
8. **Click** "Prepare" button (blue, only visible when status is pending)
9. **Wait** a few seconds

**Expected:**
- ✅ Status changes to: `ready` (blue badge)
- ✅ Shows: "X total, Y valid" examples

**If you see "0 examples":**
- You don't have tools with error patterns
- Go back to TEST 3 and add the a2l tool first

### Step 4.4: Export Job

10. **Click** "Export" button (purple, only visible when status is ready)
11. **Wait** a few seconds

**Expected:**
- ✅ Status changes to: `completed` (green badge)

### Step 4.5: Download File

12. **Click** "Download" button (green, only visible when status is completed)
13. **File downloads** to your computer

**Expected:**
- ✅ File named like `training_my-first-job_20240412_120000.jsonl`
- ✅ Open file to see training examples in JSON format

---

## TEST 5: Error Matching (API)

### Goal: Test if the system can match errors to tools

**Run in terminal:**

```bash
# Test 1: Match a2l auth error
curl "http://localhost:8080/knowledge/match-error?snippet=A2L_AUTH_FAILED%3A%20Token%20expired"
```

**Expected:**
```json
{
  "matched": true,
  "tool": "a2l",
  "error": {
    "code": "A2L_AUTH_FAILED",
    "category": "CREDENTIAL",
    "fix": "Run: a2l auth refresh"
  }
}
```

```bash
# Test 2: Identify tool from command
curl "http://localhost:8080/knowledge/identify?query=kubectl%20apply%20-f%20deployment.yaml"
```

**Expected:**
```json
{
  "tool": {"name": "kubectl", ...},
  "confidence": 0.9,
  "matched_patterns": ["kubectl apply"]
}
```

---

## TEST 6: Create Tool from Orphan Doc

### Goal: Link an unlinked document to a new tool

### Step 6.1: Import without tool name

1. **Click** "Knowledge" → "Import"
2. **Enter URL:** `https://helm.sh/docs/intro/quickstart/`
3. **Leave** Tool Name empty
4. **Click** "Import Documentation"

**Expected:**
- ✅ Yellow message: "Doc saved... No tool created"
- ✅ Warning: "enter Tool Name and re-import"

### Step 6.2: Create tool from doc

5. **Click** "Docs" sub-tab
6. **Find** the Helm doc (yellow "No tool" badge)
7. **Click** on it to expand
8. **Click** "Create Tool" button (green)
9. **Enter** Tool Name: `helm`
10. **Click** "Create Tool" button in modal

**Expected:**
- ✅ Modal closes
- ✅ Switches to Tools tab
- ✅ `helm` appears in tools list
- ✅ Back in Docs tab: doc now shows green `helm` badge

---

## Troubleshooting

### UI shows blank/loading forever
```bash
# Check services
docker-compose ps

# Restart
docker-compose restart
```

### Import fails with SSL error
```bash
# Edit .env file
VERIFY_SSL=false

# Restart agent
docker-compose restart agent
```

### Training job has 0 examples
- You need tools with error patterns first
- Add tools via API (TEST 3) or import with tool name (TEST 1)

### Download button doesn't appear
- Job must be in "completed" status
- Click Prepare first, then Export, then Download

---

## Quick API Reference

| What | Command |
|------|---------|
| Health check | `curl http://localhost:8080/health` |
| List tools | `curl http://localhost:8080/knowledge/tools` |
| List docs | `curl http://localhost:8080/knowledge/docs` |
| KB stats | `curl http://localhost:8080/knowledge/stats` |
| Training stats | `curl http://localhost:8080/training/stats` |
| List jobs | `curl http://localhost:8080/training/jobs` |

---

## Test Checklist

| # | Test | Status |
|---|------|--------|
| 1 | Import URL with tool name → Tool created | ☐ |
| 2 | Edit tool → Changes saved | ☐ |
| 3 | Add tool via API → Tool visible in UI | ☐ |
| 4.1 | Create training job → Status: pending | ☐ |
| 4.2 | Prepare job → Status: ready, examples > 0 | ☐ |
| 4.3 | Export job → Status: completed | ☐ |
| 4.4 | Download file → JSONL file downloads | ☐ |
| 5 | Match error → Returns fix suggestion | ☐ |
| 6 | Create tool from doc → Doc shows tool name | ☐ |

---

*Last updated: 2026-04-12*
