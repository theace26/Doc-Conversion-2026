# MarkFlow Bug Log

## 2026-03-25 — MCP Crash + Lifecycle FK Constraint

### Bug 1: MCP Server Crash-Looping

**Symptom:** Container `doc-conversion-2026-markflow-mcp-1` restarted every ~30 seconds.
Logs showed:
```
TypeError: FastMCP.__init__() got an unexpected keyword argument 'description'
```

**Root cause:** The `mcp` library updated its API. `FastMCP.__init__()` no longer accepts
a `description` keyword argument.

**Fix:** Already applied in a prior session. `mcp_server/server.py` line 24 uses
`FastMCP("MarkFlow")` with only the positional name argument. No `description` kwarg.

**Verified (2026-03-26):** `inspect.signature(FastMCP.__init__)` confirms `description`
is not in the parameter list. Container stays up with clean startup logs. No crash loop.

---

### Bug 2: Lifecycle Scanner FK Constraint Failures

**Symptom:** Lifecycle scan at 2026-03-25T17:46:43 scanned 12,847 files but recorded
`files_new=0` and `errors=7055`. Every supported-format file insert failed with
`FOREIGN KEY constraint failed`.

**Diagnostic findings (2026-03-26):**

- `bulk_files.job_id` references `bulk_jobs(id)` via FK constraint.
- At 17:46, `bulk_jobs` had **zero rows** — no user-created bulk jobs existed yet.
- The scanner code (`lifecycle_scanner.py:150-161`) has synthetic job creation logic
  that should have created a parent `bulk_jobs` row. However, no synthetic job was
  found in the DB. The code path either didn't execute (stale Docker image) or
  failed silently.
- The issue **self-resolved** when the first user-created bulk_job was added at 18:05.
  All subsequent scans (67 total) completed with `errors=0`.
- Scan at 20:30 successfully added 2,074 new files after the FK parent existed.

**Secondary issue:** 6 `scan_runs` were stuck with `status='running'` forever (never
finished). These occurred around bulk_job creation times, suggesting concurrent access
issues. Stuck scans would cause `run_db_compaction()` to defer indefinitely (it checks
for running scans before proceeding).

**Actions taken:**
1. Cleaned up 6 stuck `scan_runs` → set `status='failed'`
2. Verified current lifecycle scanner works: 12,847 files scanned, 0 errors
3. Documented findings in CLAUDE.md gotchas section

**Current state:** No code fix needed — the synthetic job creation code is already
correct in the current codebase. The FK error was a one-time boot issue. Current
scans work correctly.

**Files changed:** None (DB cleanup only via Python script in container)

---

## 2026-03-26 — "Stop Requested" Banner Never Clears

**Symptom:** Clicking "Reset & allow new jobs" on `status.html` calls
`POST /api/admin/reset-stop` successfully (returns `{ok: true}`) but the yellow
"Stop requested — jobs are winding down" banner never disappears. The nav badge
(showing `!`) also persists until the next poll cycle.

**Root cause:** The reset handler called `poll()` immediately after the API call,
but `poll()` re-fetches `/api/admin/active-jobs` and re-renders. If the backend
hasn't fully committed the flag change before the poll response arrives, the banner
reappears. There was no immediate UI feedback — the banner hide/show relied entirely
on the next poll result.

**Fix:**
1. `static/status.html`: Hide the banner (`hidden = true`) and re-enable the Stop All
   button immediately after the reset API returns `ok`, before calling `poll()`. Added
   error handling for failed resets.
2. `static/js/global-status-bar.js`: Exposed `window.refreshStatusBadge()` so the
   status page can trigger an immediate badge refresh after reset, clearing the `!`
   badge without waiting for the 5-second poll interval.

**Files changed:**
- `static/status.html` (reset handler, ~6 lines)
- `static/js/global-status-bar.js` (1 line: expose `window.refreshStatusBadge`)
