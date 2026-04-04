# MarkFlow Codebase Review

**Comprehensive Code Review Report**
Generated: April 03, 2026 | Version: v0.19.6.6

---

## Overall Score: 68 / 100

---

## Executive Summary

The MarkFlow codebase demonstrates strong architecture and engineering quality for its scope. The handler registry pattern, domain-split DB package, scan coordinator, and adaptive throttling are well-designed. Code follows its own conventions consistently with good structlog usage and clear naming.

The score of 68/100 is pulled down primarily by production-readiness gaps: configuration defaults that are wide open, missing input validation guardrails, and a migration error swallowing bug. Most critical/high items are quick config fixes. Two items need real engineering time: migration error handling and testing security-critical routes.

---

## Critical Issues (Fix Before Production)

| # | Finding | File | Fix Effort |
|---|---------|------|------------|
| 1 | **DEV_BYPASS_AUTH=true hardcoded** in docker-compose.yml as a literal, not overridable via `.env`. Every deployment using this file has no authentication. | `docker-compose.yml:33` | 1 min |
| 2 | **Migration errors silently swallowed** — `except Exception: pass` catches ALL failures (disk full, permissions, schema conflicts), then marks migration as applied. Failed CREATE TABLE becomes permanently "done". | `core/db/schema.py:638-648` | 30 min |
| 3 | **SQL injection via counter param** in `increment_bulk_job_counter` — f-string interpolation of column name. No exploit path today (all callers use literals), but no whitelist guard. | `core/db/bulk.py:69-76` | 10 min |

---

## High Severity Issues

| # | Finding | File |
|---|---------|------|
| 4 | **SSRF in /api/llm-providers/ollama-models** — `base_url` query param used directly in HTTP request with no validation against internal IPs. With DEV_BYPASS_AUTH=true, any user can probe internal services. | `api/routes/llm_providers.py:87-106` |
| 5 | **Unbounded memory leak** — `_rate_buckets` dict in client_log.py grows indefinitely per unique IP, never cleaned up. Accumulates thousands of empty deques over days/weeks. | `api/routes/client_log.py:25` |
| 6 | **SECRET_KEY default is public** — "dev-secret-change-in-prod" encrypts stored LLM API keys. Any deployment that forgets to set it = effectively plaintext API keys. | `docker-compose.yml:29` |
| 7 | **Meilisearch in development mode** — auth enforcement disabled even with a master key set. Port 7700 exposed to host. Anyone who can reach it has full index access. | `docker-compose.yml:84` |
| 8 | **`**extra_fields` keys interpolated as SQL column names** — systemic pattern in `upsert_source_file`, `update_bulk_file`, `update_bulk_job_status`. All current callers safe, but no whitelist guard. | `core/db/bulk.py:81-135` |

---

## Important Issues

| # | Finding | File |
|---|---------|------|
| 9 | **Unauthenticated client-log endpoint** — no `require_role()` on `/api/log/client-event`, allows log injection at 50/sec/IP when auth is enabled. | `api/routes/client_log.py:48` |
| 10 | **MCP server auth token defaults to empty** — port 8001 exposed, no enforcement code. Any process that can reach it has full MCP tool access. | `mcp_server/server.py:29` |
| 11 | **No pinned dependency versions** — `requirements.txt` uses minimums only. Builds on different days can produce different containers with breaking changes or CVEs. | `requirements.txt` |
| 12 | **Batch upsert fallback silently drops files** — failed files logged at WARNING but become phantom "pending" entries that accumulate across runs forever. | `core/db/bulk.py:288-306` |

---

## Assessment by Dimension

| Dimension | Assessment |
|-----------|------------|
| **Correctness** | Good overall. Scan/convert pipeline well-tested in practice. Migration error swallowing (#2) is the standout risk. |
| **Security** | Multiple hardened-in-dev-but-open-in-practice issues. Auth bypass, dev-mode Meilisearch, empty MCP token, public SECRET_KEY default. No active SQL exploit paths, but no guard rails either. |
| **Error Handling** | Strong "one bad file never crashes a batch" pattern, well-applied in workers. Weak in migrations and batch upsert fallback. |
| **Readability** | Good. Consistent structlog usage, clear naming, well-organized modules. The `**extra_fields` SQL builder pattern is the main pain point. |
| **Architecture** | Solid. Clean separation: `core/db/` domain split, format handler registry, scan coordinator, pipeline layers. `main.py` lifespan growing long but not a defect. |
| **Performance** | Adaptive scan throttling, batched DB writes, async DB overlap — all well-done. Only leak is the rate-limiter dict (#5). |
| **Test Coverage** | Tests exist for core paths but NO tests for `flag_manager`, `flags.py`, `llm_providers.py`, or `pipeline.py` — all security-critical paths. |
| **Input Validation** | Present but inconsistent. Sort/filter params whitelisted in some routes, not others. |
| **Dependencies** | No lock file, no pinned versions. Known reproducibility risk. |
| **Pattern Consistency** | Strong. New code follows existing conventions (structlog, handler registry, DB helpers). Recent additions follow established patterns cleanly. |

---

## Recommended Fix Priority

### Immediate (config changes, no code)

- Change `DEV_BYPASS_AUTH` to `${DEV_BYPASS_AUTH:-false}` in `docker-compose.yml`
- Set `MEILI_ENV=production` in `docker-compose.yml`
- Generate a proper `SECRET_KEY` at install time (`openssl rand -hex 32`)
- Set a non-empty `MCP_AUTH_TOKEN` default or enforce auth in MCP server

### Short-term (small code changes)

- Add column-name whitelist to `increment_bulk_job_counter` and all `**fields` update functions
- Validate `base_url` in Ollama models endpoint against private IP ranges
- Add `require_role()` to client-event endpoint
- Add TTL cleanup to `_rate_buckets` dict
- Pin dependency versions with `pip freeze`

### Engineering effort required

- Rewrite migration error handling: only catch `OperationalError` for ALTER TABLE, let CREATE TABLE errors propagate
- Add test coverage for `flag_manager`, `flags.py`, `llm_providers.py`, and `pipeline.py`
- Audit all `**extra_fields` patterns and add schema-column whitelists

---

*Report generated by Claude Code — MarkFlow Code Review*
