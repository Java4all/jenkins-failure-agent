# API Testing Guide - Copy-Paste Commands

Base URL: `http://localhost:8080`

---

## 1. Health Check

```bash
curl http://localhost:8080/health
```

**Expected:**
```json
{"status": "healthy", "ai": "connected", "jenkins": "not_configured"}
```

---

## 2. Knowledge Store - Stats

```bash
curl http://localhost:8080/knowledge/stats
```

**Expected:**
```json
{
  "total_tools": 0,
  "total_errors": 0,
  "total_docs": 0,
  "total_analyses": 0
}
```

---

## 3. Knowledge Store - Add Tool Manually

```bash
curl -X POST http://localhost:8080/knowledge/tools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "a2l",
    "category": "deploy",
    "description": "Internal deployment CLI for Kubernetes",
    "aliases": ["a2l-cli"],
    "patterns_commands": ["a2l deploy", "a2l rollback", "a2l status"],
    "patterns_env_vars": ["A2L_TOKEN", "A2L_CLUSTER"],
    "errors": [
      {
        "code": "A2L_AUTH_FAILED",
        "pattern": "A2L_AUTH_FAILED|authentication failed|token expired",
        "category": "CREDENTIAL",
        "description": "Authentication token is invalid or expired",
        "fix": "Run: a2l auth refresh",
        "retriable": true
      },
      {
        "code": "A2L_CLUSTER_NOT_FOUND",
        "pattern": "cluster.*not found|A2L_CLUSTER_NOT_FOUND",
        "category": "CONFIGURATION",
        "description": "Target cluster does not exist",
        "fix": "Check cluster name: a2l clusters list",
        "retriable": false
      }
    ]
  }'
```

**Expected:**
```json
{"id": 1, "name": "a2l", ...}
```

---

## 4. Knowledge Store - List Tools

```bash
curl http://localhost:8080/knowledge/tools
```

**Expected:**
```json
{
  "tools": [
    {"id": 1, "name": "a2l", "category": "deploy", ...}
  ],
  "total": 1
}
```

---

## 5. Knowledge Store - Get Tool Details

```bash
curl http://localhost:8080/knowledge/tools/1
```

**Expected:**
```json
{
  "id": 1,
  "name": "a2l",
  "errors": [
    {"code": "A2L_AUTH_FAILED", "fix": "Run: a2l auth refresh", ...}
  ],
  ...
}
```

---

## 6. Knowledge Store - Import from URL

```bash
curl -X POST http://localhost:8080/knowledge/import-doc \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://kubernetes.io/docs/reference/kubectl/cheatsheet/",
    "tool_name": "kubectl"
  }'
```

**Expected:**
```json
{
  "status": "imported",
  "doc": {"title": "...", "id": 1},
  "tool": {"name": "kubectl", "id": 2},
  "tool_saved": true,
  "tool_merged": false,
  "extracted": {"commands": [...], "errors": [...]}
}
```

---

## 7. Knowledge Store - List Docs

```bash
curl http://localhost:8080/knowledge/docs
```

**Expected:**
```json
{
  "docs": [
    {"id": 1, "title": "...", "tool_id": 2, ...}
  ],
  "total": 1
}
```

---

## 8. Knowledge Store - Identify Tool

```bash
curl "http://localhost:8080/knowledge/identify?query=kubectl%20apply%20-f%20deployment.yaml"
```

**Expected:**
```json
{
  "tool": {"name": "kubectl", ...},
  "confidence": 0.95,
  "matched_patterns": ["kubectl apply"]
}
```

---

## 9. Knowledge Store - Match Error

```bash
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

---

## 10. Training Pipeline - Stats

```bash
curl http://localhost:8080/training/stats
```

**Expected:**
```json
{
  "total_examples": 0,
  "validated_examples": 0,
  "pending_jobs": 0,
  "completed_jobs": 0,
  ...
}
```

---

## 11. Training Pipeline - Create Job

```bash
curl -X POST http://localhost:8080/training/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-job-1",
    "format": "jsonl_openai",
    "include_feedback": true,
    "include_knowledge": true
  }'
```

**Expected:**
```json
{
  "id": 1,
  "name": "test-job-1",
  "status": "pending",
  "next_step": "POST /training/jobs/1/prepare"
}
```

---

## 12. Training Pipeline - Prepare Job

```bash
curl -X POST http://localhost:8080/training/jobs/1/prepare
```

**Expected:**
```json
{
  "success": true,
  "job_id": 1,
  "status": "ready",
  "total_examples": 2,
  "valid_examples": 2,
  "next_step": "POST /training/jobs/1/export"
}
```

**Note:** If you see `total_examples: 0`, you need to:
1. Add a tool with errors first (step 3)
2. Or import a doc with tool_name (step 6)

---

## 13. Training Pipeline - Export Job

```bash
curl -X POST http://localhost:8080/training/jobs/1/export
```

**Expected:**
```json
{
  "success": true,
  "job_id": 1,
  "status": "completed",
  "exported_path": "/app/data/exports/training_test-job-1_20240412_120000.jsonl",
  "download_url": "/training/jobs/1/download"
}
```

---

## 14. Training Pipeline - Download File

```bash
curl http://localhost:8080/training/jobs/1/download -o training-data.jsonl
cat training-data.jsonl
```

**Expected (JSONL format):**
```json
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
{"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

---

## 15. Training Pipeline - Restore from export (disaster recovery)

Upload a file previously produced by **Export** (`jsonl_openai` / `jsonl_ollama` or `json` bundle):

```bash
curl -X POST http://localhost:8080/training/restore \
  -F "file=@training-data.jsonl" \
  -F "source=restore"
```

**Expected:**
```json
{
  "success": true,
  "filename": "training-data.jsonl",
  "added": 12,
  "skipped": 2,
  "format_detected": "jsonl_openai",
  "lines_processed": 14,
  "parse_errors": []
}
```

`skipped` counts duplicates (same content hash as an existing row). `source` is stored on imported examples (default `import`).

---

### Training examples — list, get, patch, delete

```bash
# Paginated list (optional: &source=feedback)
curl "http://localhost:8080/training/examples?page=1&page_size=20"

curl http://localhost:8080/training/examples/1

curl -X PATCH http://localhost:8080/training/examples/1 \
  -H "Content-Type: application/json" \
  -d '{"root_cause":"Updated explanation","fix":"Updated fix"}'

curl -X DELETE http://localhost:8080/training/examples/1
```

---

## 16. Training Pipeline - List Jobs

```bash
curl http://localhost:8080/training/jobs
```

**Expected:**
```json
{
  "jobs": [
    {"id": 1, "name": "test-job-1", "status": "completed", ...}
  ],
  "total": 1
}
```

---

## 17. Feedback - Submit

```bash
curl -X POST http://localhost:8080/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "job_name": "test-project",
    "build_number": 123,
    "error_snippet": "A2L_AUTH_FAILED: Token expired",
    "error_category": "CREDENTIAL",
    "failed_stage": "Deploy",
    "original_root_cause": "Authentication error",
    "original_confidence": 0.65,
    "was_correct": false,
    "confirmed_root_cause": "A2L authentication token expired after 24 hours",
    "confirmed_fix": "Run: a2l auth refresh"
  }'
```

**Expected:**
```json
{"id": 1, "status": "stored"}
```

---

## 18. Feedback - Stats

```bash
curl http://localhost:8080/feedback/stats
```

**Expected:**
```json
{
  "total": 1,
  "correct": 0,
  "incorrect": 1,
  "accuracy_rate": 0.0
}
```

---

## 19. Feedback - Export

```bash
curl "http://localhost:8080/feedback/export?format=jsonl" -o feedback.jsonl
cat feedback.jsonl
```

---

## Complete Test Workflow

Run these commands in order for a full test:

```bash
# 1. Check health
curl http://localhost:8080/health

# 2. Add a tool with errors
curl -X POST http://localhost:8080/knowledge/tools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "a2l",
    "category": "deploy",
    "description": "Internal deployment CLI",
    "errors": [
      {"code": "A2L_AUTH_FAILED", "pattern": "A2L_AUTH_FAILED", "category": "CREDENTIAL", "description": "Auth failed", "fix": "Run: a2l auth refresh"}
    ]
  }'

# 3. Check stats - should show 1 tool, 1 error
curl http://localhost:8080/knowledge/stats

# 4. Create training job
curl -X POST http://localhost:8080/training/jobs \
  -H "Content-Type: application/json" \
  -d '{"name": "test-1", "format": "jsonl_openai", "include_knowledge": true}'

# 5. Prepare job (imports errors as training examples)
curl -X POST http://localhost:8080/training/jobs/1/prepare

# 6. Export job
curl -X POST http://localhost:8080/training/jobs/1/export

# 7. Download and view
curl http://localhost:8080/training/jobs/1/download -o training.jsonl
cat training.jsonl
```

---

## Troubleshooting

### Job stuck in "pending"
- Click "Prepare" button or call `/prepare` API
- Check that you have tools with errors

### "0 examples" after prepare
- Need tools with error patterns first
- Add a tool manually with errors (step 3)
- Or import from URL with tool_name

### Import fails
- Check `VERIFY_SSL=false` in .env
- Check URL is accessible

### Download 404
- Job must be in "completed" status
- Run export first

---
