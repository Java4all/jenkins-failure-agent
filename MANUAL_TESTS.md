# Complete Manual Test Guide
## Jenkins Failure Agent v2.0.0

---

# PART 1: SETUP

## Step 1.1: Extract and Configure

```bash
# Extract
unzip jenkins-failure-agent-v2.0.0.zip -d jenkins-failure-agent
cd jenkins-failure-agent

# Create .env from template
cp .env.example .env

# Edit .env if needed (optional for basic testing)
# nano .env
```

## Step 1.2: Start Services

```bash
make start
```

Wait 2-3 minutes for first startup.

## Step 1.3: Check Services Running

```bash
docker-compose ps
```

**Expected:** All services show "Up":
```
NAME                    STATUS
jenkins-agent-agent     Up
jenkins-agent-ui        Up  
jenkins-agent-ollama    Up
```

## Step 1.4: Wait for AI Model (First Time Only)

```bash
docker-compose logs -f ollama
```

**Wait until you see:** `llama3:8b pulled successfully`

Press `Ctrl+C` to exit logs.

## Step 1.5: Verify Health

```bash
curl http://localhost:8080/health
```

**Expected:**
```json
{"status":"healthy","version":"2.0.0","ai":"connected","jenkins":"not_configured"}
```

## Step 1.6: Open UI

**Browser:** http://localhost:3000

**Expected:** Dashboard with 3 tabs: Analysis, Knowledge, Training

---

# PART 2: KNOWLEDGE BASE TESTS

---

## TEST 2.1: Import Documentation with Tool Name

**Goal:** Import kubectl docs and create a tool automatically

### Steps:

1. **Open browser:** http://localhost:3000
2. **Click** "Knowledge" tab (top navigation)
3. **Click** "Import" sub-tab (third tab under Knowledge section)
4. **In "Documentation URL" field, enter:**
   ```
   https://kubernetes.io/docs/reference/kubectl/cheatsheet/
   ```
5. **In "Tool Name" field, enter:**
   ```
   kubectl
   ```
6. **Click** "Import Documentation" button
7. **Wait** 5-10 seconds for import

### Expected Result:
- ✅ **Green box** appears with message
- ✅ Shows: "Doc saved: kubectl Cheat Sheet" (or similar title)
- ✅ Shows: Tool "kubectl" (created new)
- ✅ Shows: X commands, Y errors extracted

### Verify - Check Tools Tab:

8. **Click** "Tools" sub-tab
9. **Look for** "kubectl" in the list
10. **Click** on the "kubectl" row to expand it

### Expected:
- ✅ See description
- ✅ See "Commands:" with patterns like "kubectl apply", "kubectl get"
- ✅ See Edit and Delete buttons

---

## TEST 2.2: Import Documentation WITHOUT Tool Name

**Goal:** Test auto-detection and warning message

### Steps:

1. **Click** "Import" sub-tab
2. **In "Documentation URL" field, enter:**
   ```
   https://helm.sh/docs/intro/quickstart/
   ```
3. **Leave** "Tool Name" field **empty**
4. **Click** "Import Documentation" button
5. **Wait** for import

### Expected Result:
- ✅ **Yellow box** appears (not green)
- ✅ Shows: "Doc saved: ..."
- ✅ Shows: "No tool created - enter Tool Name and re-import"

### Verify - Check Docs Tab:

6. **Click** "Docs" sub-tab
7. **Look for** the Helm document

### Expected:
- ✅ Document shows **yellow badge** "No tool"

---

## TEST 2.3: Create Tool from Existing Document

**Goal:** Link an orphan document to a new tool

### Prerequisites: Complete TEST 2.2 first

### Steps:

1. **Click** "Docs" sub-tab
2. **Find** the Helm document (has yellow "No tool" badge)
3. **Click** on the document row to expand it
4. **Click** "Create Tool" button (green)
5. **In the popup modal, enter Tool Name:**
   ```
   helm
   ```
6. **Click** "Create Tool" button in the modal

### Expected Result:
- ✅ Modal closes
- ✅ Automatically switches to "Tools" tab
- ✅ "helm" appears in the tools list

### Verify - Check Docs Tab:

7. **Click** "Docs" sub-tab
8. **Find** the Helm document

### Expected:
- ✅ Document now shows **green badge** with "helm"

---

## TEST 2.4: Edit a Tool

**Goal:** Modify tool details

### Prerequisites: Have at least one tool (kubectl from TEST 2.1)

### Steps:

1. **Click** "Tools" sub-tab
2. **Click** on "kubectl" row to expand it
3. **Click** "Edit" button (blue)
4. **In the modal, change Description to:**
   ```
   Kubernetes command-line tool for managing clusters
   ```
5. **In "Command Patterns" textarea, add a new line:**
   ```
   kubectl logs
   ```
6. **Click** "Save Changes" button

### Expected Result:
- ✅ Modal closes
- ✅ Click on kubectl to expand again
- ✅ New description visible
- ✅ "kubectl logs" appears in Commands list

---

## TEST 2.5: Delete a Tool

**Goal:** Remove a tool from knowledge base

### Steps:

1. **Click** "Tools" sub-tab
2. **Click** on "helm" row to expand it
3. **Click** "Delete" button (red)
4. **Click** "OK" on the confirmation dialog

### Expected Result:
- ✅ "helm" disappears from the list
- ✅ Stats at top update (Tools count decreases)

---

## TEST 2.6: Add Tool via API (with Error Patterns)

**Goal:** Add internal tool with error patterns for training

### Run in Terminal:

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

### Expected Response:
```json
{"id":3,"name":"a2l","category":"deploy",...}
```

### Verify in UI:

1. **Refresh browser** (F5)
2. **Click** "Knowledge" → "Tools"
3. **See** "a2l" in the list
4. **Click** to expand
5. **See** "2 errors" badge

---

## TEST 2.7: View Knowledge Stats

### Via UI:

1. **Click** "Knowledge" tab
2. **Look at** the stats cards at the top

### Expected:
- ✅ Shows: Tools count (e.g., 2)
- ✅ Shows: Error Patterns count (e.g., 2)
- ✅ Shows: Docs count (e.g., 2)

### Via API:

```bash
curl http://localhost:8080/knowledge/stats
```

### Expected:
```json
{"total_tools":2,"total_errors":2,"total_docs":2,"total_analyses":0}
```

---

## TEST 2.8: Match Error Pattern (API)

**Goal:** Test if system can match log errors to known patterns

### Run in Terminal:

```bash
curl "http://localhost:8080/knowledge/match-error?snippet=A2L_AUTH_FAILED%3A%20Token%20expired%20at%2012%3A00"
```

### Expected Response:
```json
{
  "matched": true,
  "error": {
    "code": "A2L_AUTH_FAILED",
    "category": "CREDENTIAL",
    "description": "Authentication token is invalid or expired",
    "fix": "Run: a2l auth refresh"
  },
  "tool": "a2l"
}
```

---

## TEST 2.9: Identify Tool from Command (API)

**Goal:** Test if system can identify which tool is in a log

### Run in Terminal:

```bash
curl "http://localhost:8080/knowledge/identify?query=Running%20kubectl%20apply%20-f%20deployment.yaml"
```

### Expected Response:
```json
{
  "matched": true,
  "tool": {"id":1,"name":"kubectl",...},
  "confidence": 0.9,
  "matched_patterns": ["kubectl apply"]
}
```

---

# PART 3: TRAINING PIPELINE TESTS

---

## TEST 3.1: View Training Stats

### Via UI:

1. **Click** "Training" tab (top navigation)
2. **Look at** the stats cards

### Expected:
- ✅ Shows example counts
- ✅ Shows job counts

### Via API:

```bash
curl http://localhost:8080/training/stats
```

---

## TEST 3.2: Create Training Job

### Prerequisites: Have tools with errors (complete TEST 2.6)

### Steps:

1. **Click** "Training" tab
2. **In "Job Name" field, enter:**
   ```
   my-first-training
   ```
3. **In "Format" dropdown, select:**
   ```
   JSONL (OpenAI/Ollama)
   ```
4. **Ensure checkboxes are checked:**
   - ✅ Include feedback
   - ✅ Include knowledge
5. **Click** "Create Job" button

### Expected Result:
- ✅ Job appears in the list below
- ✅ Status shows: **pending** (gray badge)
- ✅ "Prepare" button visible (blue)

---

## TEST 3.3: Prepare Training Job

### Prerequisites: Complete TEST 3.2

### Steps:

1. **Find** your job "my-first-training" in the list
2. **Click** "Prepare" button (blue)
3. **Wait** 2-3 seconds

### Expected Result:
- ✅ Status changes to: **ready** (blue badge)
- ✅ Shows example count (e.g., "2 total, 2 valid")
- ✅ "Export" button appears (purple)

### If you see "0 examples":
- You need tools with error patterns first
- Go back to TEST 2.6 and add the a2l tool

---

## TEST 3.4: Export Training Job

### Prerequisites: Complete TEST 3.3 (job must be "ready")

### Steps:

1. **Find** your job in the list (status: ready)
2. **Click** "Export" button (purple)
3. **Wait** 2-3 seconds

### Expected Result:
- ✅ Status changes to: **completed** (green badge)
- ✅ "Download" button appears (green)

---

## TEST 3.5: Download Training Data

### Prerequisites: Complete TEST 3.4 (job must be "completed")

### Steps:

1. **Find** your job in the list (status: completed)
2. **Click** "Download" button (green)
3. **File downloads** to your computer

### Expected Result:
- ✅ File downloaded with name like: `training_my-first-training_20240412_120000.jsonl`

### Verify File Contents:

Open the downloaded file in a text editor:

```json
{"messages":[{"role":"user","content":"Analyze this Jenkins error..."},{"role":"assistant","content":"Root cause: ..."}]}
{"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}
```

---

## TEST 3.6: Training Pipeline via API (Complete Flow)

### Run each command in sequence:

```bash
# Step 1: Create job
curl -X POST http://localhost:8080/training/jobs \
  -H "Content-Type: application/json" \
  -d '{"name": "api-test-job", "format": "jsonl_openai", "include_knowledge": true}'
```

**Note the job ID in response (e.g., `"id": 2`)**

```bash
# Step 2: Prepare job (use your job ID)
curl -X POST http://localhost:8080/training/jobs/2/prepare
```

**Expected:** `"status": "ready"`, `"total_examples": 2`

```bash
# Step 3: Export job
curl -X POST http://localhost:8080/training/jobs/2/export
```

**Expected:** `"status": "completed"`, `"exported_path": "/app/data/exports/..."`

```bash
# Step 4: Download file
curl http://localhost:8080/training/jobs/2/download -o training-api-test.jsonl

# Step 5: View contents
cat training-api-test.jsonl
```

---

# PART 4: FEEDBACK TESTS

---

## TEST 4.1: Submit Feedback via API

**Goal:** Record a correction to train the AI

### Run in Terminal:

```bash
curl -X POST http://localhost:8080/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "my-app-build",
    "build_number": 456,
    "error_snippet": "A2L_AUTH_FAILED: Token expired",
    "error_category": "CREDENTIAL",
    "failed_stage": "Deploy",
    "original_root_cause": "Authentication error",
    "original_confidence": 0.65,
    "was_correct": false,
    "confirmed_root_cause": "A2L token expired after 24 hours due to security policy",
    "confirmed_fix": "Run: a2l auth refresh --force"
  }'
```

### Expected Response:
```json
{"id":1,"status":"stored"}
```

---

## TEST 4.2: View Feedback Stats

### Run in Terminal:

```bash
curl http://localhost:8080/feedback/stats
```

### Expected Response:
```json
{
  "total": 1,
  "correct": 0,
  "incorrect": 1,
  "accuracy_rate": 0.0,
  ...
}
```

---

## TEST 4.3: Export Feedback

### Run in Terminal:

```bash
curl "http://localhost:8080/feedback/export?format=jsonl" -o feedback-export.jsonl
cat feedback-export.jsonl
```

### Expected:
- ✅ File contains feedback records in JSONL format

---

## TEST 4.4: List All Feedback

### Run in Terminal:

```bash
curl http://localhost:8080/feedback
```

### Expected:
```json
{
  "feedback": [
    {"id":1,"job_name":"my-app-build","build_number":456,...}
  ],
  "total": 1
}
```

---

# PART 5: ANALYSIS TESTS (Requires Jenkins)

---

## TEST 5.1: Health Check with Jenkins

**Note:** These tests require Jenkins configured in .env

### Check Connection:

```bash
curl http://localhost:8080/health
```

### Expected (with Jenkins configured):
```json
{"status":"healthy","ai":"connected","jenkins":"connected"}
```

### Expected (without Jenkins):
```json
{"status":"healthy","ai":"connected","jenkins":"not_configured"}
```

---

## TEST 5.2: Analyze a Build (UI)

### Prerequisites: Jenkins configured and has a failed build

### Steps:

1. **Click** "Analysis" tab
2. **In "Job Name" field, enter your Jenkins job name:**
   ```
   my-pipeline
   ```
3. **In "Build Number" field, enter:**
   ```
   123
   ```
4. **Click** "Analyze" button
5. **Wait** 10-30 seconds for AI analysis

### Expected Result:
- ✅ Results panel appears
- ✅ Shows: Root Cause
- ✅ Shows: Confidence percentage
- ✅ Shows: Suggested Fix
- ✅ Shows: 👍 and 👎 feedback buttons

---

## TEST 5.3: Provide Feedback on Analysis (UI)

### Prerequisites: Complete TEST 5.2

### Steps for CORRECT analysis:

1. **Click** 👍 button
2. **See** "Thank you for your feedback" message

### Steps for INCORRECT analysis:

1. **Click** 👎 button
2. **Correction form appears**
3. **Enter correct root cause:**
   ```
   Database connection pool exhausted due to connection leak
   ```
4. **Enter correct fix:**
   ```
   Restart the application and fix connection leak in UserService.java line 45
   ```
5. **Click** "Submit Correction" button

### Expected:
- ✅ Form closes
- ✅ Feedback stored (verify with TEST 4.2)

---

# PART 6: DOCUMENT MANAGEMENT TESTS

---

## TEST 6.1: List All Documents

### Via API:

```bash
curl http://localhost:8080/knowledge/docs
```

### Expected:
```json
{
  "docs": [
    {"id":1,"title":"kubectl Cheat Sheet","tool_id":1,...},
    {"id":2,"title":"Helm Quickstart","tool_id":2,...}
  ],
  "total": 2
}
```

---

## TEST 6.2: Delete a Document (UI)

### Steps:

1. **Click** "Knowledge" → "Docs" sub-tab
2. **Find** a document to delete
3. **Click** on the document row to expand
4. **Click** "Delete" button (red)
5. **Click** "OK" on confirmation

### Expected:
- ✅ Document disappears from list
- ✅ Docs count decreases in stats

---

## TEST 6.3: Delete a Document (API)

### Run in Terminal:

```bash
# First, list docs to get ID
curl http://localhost:8080/knowledge/docs

# Delete doc with ID 1
curl -X DELETE http://localhost:8080/knowledge/docs/1
```

### Expected:
```json
{"status":"deleted","id":1}
```

---

# PART 7: COMPLETE TEST CHECKLIST

Use this checklist to track your testing progress:

| # | Test | API/UI | Status |
|---|------|--------|--------|
| **SETUP** | | | |
| 1.1 | Extract and configure | Terminal | ☐ |
| 1.2 | Start services | Terminal | ☐ |
| 1.3 | Verify services running | Terminal | ☐ |
| 1.4 | Wait for AI model | Terminal | ☐ |
| 1.5 | Health check | API | ☐ |
| 1.6 | Open UI | UI | ☐ |
| **KNOWLEDGE - IMPORT** | | | |
| 2.1 | Import with tool name | UI | ☐ |
| 2.2 | Import without tool name | UI | ☐ |
| 2.3 | Create tool from doc | UI | ☐ |
| **KNOWLEDGE - CRUD** | | | |
| 2.4 | Edit tool | UI | ☐ |
| 2.5 | Delete tool | UI | ☐ |
| 2.6 | Add tool via API | API | ☐ |
| 2.7 | View stats | UI + API | ☐ |
| **KNOWLEDGE - MATCHING** | | | |
| 2.8 | Match error pattern | API | ☐ |
| 2.9 | Identify tool | API | ☐ |
| **TRAINING** | | | |
| 3.1 | View training stats | UI + API | ☐ |
| 3.2 | Create job | UI | ☐ |
| 3.3 | Prepare job | UI | ☐ |
| 3.4 | Export job | UI | ☐ |
| 3.5 | Download file | UI | ☐ |
| 3.6 | Full flow via API | API | ☐ |
| **FEEDBACK** | | | |
| 4.1 | Submit feedback | API | ☐ |
| 4.2 | View feedback stats | API | ☐ |
| 4.3 | Export feedback | API | ☐ |
| 4.4 | List feedback | API | ☐ |
| **DOCUMENTS** | | | |
| 6.1 | List documents | API | ☐ |
| 6.2 | Delete document | UI | ☐ |
| 6.3 | Delete document | API | ☐ |

---

# TROUBLESHOOTING

## Services won't start

```bash
# Check Docker is running
docker ps

# Check logs
docker-compose logs

# Restart everything
docker-compose down
docker-compose up -d
```

## UI shows blank page

```bash
# Check UI service
docker-compose logs ui

# Restart UI
docker-compose restart ui

# Hard refresh browser
# Mac: Cmd+Shift+R
# Windows: Ctrl+Shift+R
```

## Import fails with SSL error

```bash
# Edit .env
nano .env

# Set:
VERIFY_SSL=false

# Restart agent
docker-compose restart agent
```

## Training job shows 0 examples

You need tools with error patterns first:
1. Complete TEST 2.6 (add a2l tool with errors)
2. Then create and prepare training job

## Download returns error

1. Job must be in "completed" status
2. Run Prepare first, then Export, then Download
3. Check job status: `curl http://localhost:8080/training/jobs`

## API returns 500 error

```bash
# Check agent logs
docker-compose logs agent

# Look for Python errors
```

---

# CLEANUP

When done testing:

```bash
# Stop all services
make stop

# OR remove everything including data
make clean
```

---

*Test Guide Version: 2.0.0*
*Last Updated: 2026-04-12*
