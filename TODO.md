# Project TODO & Roadmap

## Active Development

*Currently v2.1.0 - Splunk Integration*

---

## IN PROGRESS: Splunk Integration

### Status: ✅ IMPLEMENTED (needs testing)

### Components Built:
- [x] `.env.example` - Splunk config vars
- [x] `src/splunk_connector.py` - Query Splunk API
- [x] `src/review_queue.py` - Human review storage
- [x] API endpoints: `/splunk/*`, `/review-queue/*`
- [x] Training pipeline: `add_from_review()` method

### Config (.env):
```
SPLUNK_ENABLED=true
SPLUNK_URL=https://splunk.company.com:8089
SPLUNK_TOKEN=xxx
SPLUNK_INDEX=jenkins_console
SPLUNK_SEARCH_FILTER=abc/shared-code
SPLUNK_LOG_TAIL_LINES=500
SPLUNK_SYNC_INTERVAL_MINS=15
```

### API Endpoints:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/splunk/status` | GET | Test connection |
| `/splunk/sync` | POST | Pull failures + analyze |
| `/splunk/failures` | GET | List failures (no sync) |
| `/review-queue` | GET | List review items |
| `/review-queue/{id}` | GET | Get item details |
| `/review-queue/{id}/approve` | POST | Approve + add to training |
| `/review-queue/{id}/reject` | POST | Reject item |

### Still TODO:
- [ ] Review Queue UI tab
- [ ] Scheduled sync (cron/background task)
- [ ] Full log fetch on-demand (backlog)

---

## PENDING: Doc Import Improvements

### Status: ⏳ PARTIAL (validation done, UI pending)

### Target: v2.1.0

### Description
Integrate with Splunk to automatically pull failed Jenkins builds (last 24h) and create training data with human review.

### Blockers (Need Answers)

| Question | Status | Answer |
|----------|--------|--------|
| Splunk API token access (not SAML) | ⏳ Checking with Admin | |
| Splunk log format / field names | ⏳ Need sample | |
| Index name for Jenkins logs | ⏳ Need info | |

### User Action Items
- [ ] Ask Splunk Admin for API token access
- [ ] Get sample Splunk query for failed builds
- [ ] Share field names (job_name, status, log, etc.)

### Proposed Features

1. **Splunk Connector** (`src/splunk_connector.py`)
   - Pull failures from last 24 hours
   - Configurable schedule
   - Historical backfill option

2. **Batch Ingestion API** (`POST /ingest/batch`)
   - Process multiple failures
   - Auto-analyze with AI
   - Assign confidence scores

3. **Review Queue UI** (New tab in UI)
   - List pending reviews
   - Edit root cause / fix
   - Approve / Reject / Skip
   - Bulk actions for similar failures
   - Keyboard shortcuts

4. **Quality Controls**
   - High confidence (>85%): Auto-approve option with spot-check
   - Low confidence (<85%): Must review
   - Track reviewer accuracy

### Architecture

```
Splunk (24h failures)
    ↓
Auto-Analysis (AI + pattern matching)
    ↓
Review Queue (Human verification)
    ↓
Approved Training Data (High quality)
    ↓
Fine-tuned Model (Weekly/Monthly)
```

### Reminder Schedule
- **Next check-in: April 15, 2026**
- Then every 3 days until blockers resolved

---

## Future Ideas

### v2.2.0 - Advanced Features
- [ ] Slack notifications for review queue
- [ ] Daily digest email
- [ ] Pattern clustering (group similar failures)
- [ ] Confidence calibration tracking

### v2.3.0 - Automation
- [ ] Scheduled model fine-tuning
- [ ] A/B testing for model versions
- [ ] Auto-rollback if accuracy drops

### v3.0.0 - Enterprise
- [ ] Multi-tenant support
- [ ] RBAC for reviewers
- [ ] Audit logging
- [ ] SSO integration

---

## Completed

### v2.0.0 (2026-04-12)
- ✅ Knowledge Store (tools, errors, docs)
- ✅ Doc Import from URL
- ✅ Training Pipeline (create, prepare, export, download)
- ✅ Feedback system
- ✅ UI with 3 tabs (Analysis, Knowledge, Training)
- ✅ 70 automated tests
- ✅ Backup/Restore system
- ✅ SSL configuration (DRY)
- ✅ Tool categories (runtime, application, database, security)
- ✅ Docs management with tool linking
- ✅ Edit tool functionality

---

*Last Updated: 2026-04-12*
