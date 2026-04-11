# Development Rules

These rules MUST be followed for all development work on this project.

---

## Pre-Release Checklist

Before ANY release package is created, the following MUST be done:

| # | Check | Command/Action |
|---|-------|----------------|
| 1 | Update version in `src/__init__.py` | `__version__ = "X.Y.Z"` |
| 2 | Update version in `Dockerfile` | `LABEL version="X.Y.Z"` |
| 3 | Update `CHANGELOG.md` | Add version section with all changes |
| 4 | Update `README.md` | Document new features, commands, config |
| 5 | Update `QUICKSTART.md` | If deployment steps changed |
| 6 | Update `config.example.yaml` | If new config options added |
| 7 | Update `.env.example` | If new env vars added |
| 8 | Verify code compiles | `python3 -c "from src import *"` |
| 9 | Run all tests | `python3 -m pytest tests/ -v` |
| 10 | Verify Makefile consistency | New modes get `make start-xxx` targets |

---

## Code Quality Rules

### DRY Principle (Don't Repeat Yourself)

**Single Source of Truth for Configuration:**
- All config defined in ONE place (`config.py`) and inherited everywhere
- Docker-compose files use `env_file: .env` — don't hardcode env vars in compose files
- Before making any change: audit ALL files that could be affected, fix ALL of them

**Example - SSL Configuration:**
```
.env                    ← User sets VERIFY_SSL here
    ↓
config.py               ← Reads and applies to all services
    ↓
JenkinsConfig.verify_ssl
GitHubConfig.verify_ssl
SCMConfig.verify_ssl
Config.verify_ssl
```

### Cross-Platform Compatibility

- Use `$(CURDIR)` not `$(PWD)` in Makefile (Windows compatibility)
- Use conditional for timestamps:
  ```makefile
  ifeq ($(OS),Windows_NT)
      TIMESTAMP := $(shell powershell -Command "Get-Date -Format 'yyyyMMdd-HHmmss'")
  else
      TIMESTAMP := $(shell date +%Y%m%d-%H%M%S)
  endif
  ```

### Dependency Awareness

When changing ANY file, ask:
1. What other files depend on this?
2. What files does this depend on?
3. Do I need to update tests?
4. Do I need to update documentation?

---

## Uncertainty Protocol

**When doubts arise:**
1. STOP
2. PROPOSE the approach
3. ASK for confirmation
4. WAIT for response
5. Only then proceed

**Never assume. Always verify.**

---

## File Privacy

ALL files shared by user are PRIVATE and must not be:
- Shared with external services
- Included in example outputs
- Referenced in documentation with real values

---

## Testing Requirements

| Requirement | Standard |
|-------------|----------|
| All tests pass | `pytest tests/ -v` returns 0 |
| New features have tests | Coverage for new functionality |
| Edge cases covered | Error handling tested |

---

## Documentation Standards

| Document | Purpose | Update When |
|----------|---------|-------------|
| `README.md` | Main docs, features, architecture | Any feature change |
| `CHANGELOG.md` | Version history | Every release |
| `QUICKSTART.md` | Quick start guide | Deployment changes |
| `.env.example` | Environment variables | New env vars |
| `config.example.yaml` | Config file template | New config options |

---

## Version Numbering

Follow Semantic Versioning (SemVer):
- **MAJOR.MINOR.PATCH** (e.g., 2.0.0)
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes

---

## Commit Message Format

```
<type>: <short description>

<detailed description if needed>

Files changed:
- file1.py
- file2.py
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

---

## Senior Developer Mindset

1. **Think before coding** — Plan the approach
2. **Audit before changing** — Check dependencies
3. **Test after changing** — Verify everything works
4. **Document after completing** — Update all docs
5. **Ask when uncertain** — Don't assume

---

*Last updated: 2026-04-11*
