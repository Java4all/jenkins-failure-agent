# Changelog

## v1.9.18 - STABLE CHECKPOINT (2026-04-04)

### Status: ✅ Working Release - Rollback Point

### Features Working:
- Tool invocation detection (+ and $ prefix)
- HH:MM:SS and ISO timestamp formats
- Jenkins Settings override in UI
- Identifier-based tool matching for pipeline errors
- RC analysis with iterative and deep modes
- All 17 failure categories
- GitHub source code fetching

### Rule-Based Tool Matching:
- Extracts identifiers from error messages
- Matches tools by identifier (e.g., credential ID → AWS command)
- Falls back to exit code / error output matching

---

## v1.9.19+ - AI-Driven Tool Relationship Analysis

### Goal:
Replace rule-based tool matching with AI-driven analysis.
Send tool invocations to AI prompt, let AI identify which tool
is semantically related to the failure.

### Rollback:
If issues arise, rollback to v1.9.18 (stable checkpoint above)

### Implementation (v1.9.19):
- Added TOOL INVOCATIONS section to AI prompt
- AI returns `related_tool_line` identifying most related tool
- Falls back to rule-based matching if AI doesn't identify tool
- Semantic understanding: AI knows "credentials 'X'" relates to "aws --name X"

## v1.9.21 - Known Failure Patterns (AI Guidance)

### New Feature: KNOWN_FAILURE_PATTERNS
When a tool fails with a recognized pattern, AI receives:
- Symptom description
- Ranked list of likely root causes
- Keywords to look for in log
- Minimum confidence level

### Patterns Covered:
- **Kubernetes**: rollout timeout, resource not found, connection, RBAC
- **Docker**: daemon, registry auth, image not found, disk space
- **Helm**: release failure, chart not found
- **Terraform**: state lock, provider installation
- **AWS**: credentials, IAM permissions
- **NPM**: package not found, permissions
- **Maven/Gradle**: dependencies, compilation
- **Git**: SSH auth, HTTPS auth

### UI Fix:
- Root cause summary now expandable for long text
- primary_error limit increased from 200 to 2000 chars
