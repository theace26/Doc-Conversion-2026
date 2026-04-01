# Auto-Conversion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the lifecycle scanner the sole trigger for conversion — when it detects new or changed files, it automatically spins up the bulk converter to process them. Remove manual scan/convert triggers from settings and rework the settings UI to reflect this automated pipeline approach.

**Architecture:** The lifecycle scanner (runs on a configurable interval) walks the source directory. When it finds new/changed files, it creates or updates `source_files` + `bulk_files` rows with status `pending`. After the scan completes, if any pending files exist, it automatically starts a bulk conversion job. Settings are reworked: remove manual "Start Scan" / "Start Conversion" buttons, replace with pipeline controls (scan interval, auto-convert toggle, worker count, pause/resume pipeline).

**Tech Stack:** Python/FastAPI, existing scheduler (APScheduler), existing bulk_worker.py, existing lifecycle_scanner.py

---

### Task 1: Understand current auto-conversion and manual trigger architecture

**Files:**
- Read: `core/auto_converter.py` — understand existing auto-conversion decision engine
- Read: `core/scheduler.py` — understand how lifecycle scan is scheduled
- Read: `core/bulk_worker.py` — understand how bulk jobs are created/started
- Read: `api/routes/bulk.py` — understand manual scan/convert API endpoints
- Read: `static/bulk.html` or equivalent — understand UI triggers
- Read: `core/lifecycle_scanner.py` — understand how new/changed files are detected

- [ ] **Step 1: Map the current flow**

Document:
1. How does a user currently trigger a scan? (API endpoint, UI button)
2. How does a user currently trigger conversion? (API endpoint, UI button)
3. What does `auto_converter.py` do? Is it already partially solving this?
4. What settings/preferences exist for scanning and conversion?
5. What are the manual trigger endpoints that need to be removed or repurposed?

- [ ] **Step 2: Identify all settings/preferences related to scanning and conversion**

Query the database defaults in `core/database.py` for all scanner/converter preferences. List each one with its purpose and whether it stays, gets removed, or gets reworked.

---

### Task 2: Wire lifecycle scanner to auto-trigger bulk conversion

**Files:**
- Modify: `core/lifecycle_scanner.py` — add auto-convert trigger after scan
- Modify: `core/auto_converter.py` — simplify or integrate into scanner
- Modify: `core/scheduler.py` — ensure scheduler orchestrates the pipeline

- [ ] **Step 1: Add conversion trigger at end of lifecycle scan**

After `run_lifecycle_scan()` completes and finds pending files, check the `auto_convert_enabled` preference. If enabled, automatically create a bulk job and start conversion:

```python
# At end of run_lifecycle_scan(), after counters are finalized:
if counters["files_new"] > 0 or counters["files_modified"] > 0:
    auto_convert = await get_preference("auto_convert_enabled")
    if auto_convert == "true":
        await _trigger_auto_conversion(scan_run_id, counters)
```

- [ ] **Step 2: Implement `_trigger_auto_conversion()`**

This function:
1. Checks if any bulk job is already running (skip if so — don't stack jobs)
2. Creates a new bulk job with `auto_triggered=True`
3. Starts the bulk worker pool for pending files
4. Logs the auto-trigger event

- [ ] **Step 3: Consolidate with existing auto_converter.py**

Review what `auto_converter.py` already does. If it duplicates the above logic, consolidate into one place. If it adds value (e.g., conservative factor, rate limiting), keep it but wire it into the scanner's post-scan hook.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: lifecycle scanner auto-triggers bulk conversion for new/changed files"
```

---

### Task 3: Rework settings/preferences for pipeline mode

**Files:**
- Modify: `core/database.py` — update default preferences
- Modify: `api/routes/settings.py` or equivalent — update settings API

- [ ] **Step 1: Define the new settings schema**

Keep:
- `scanner_interval_minutes` — how often the pipeline runs (rename display to "Pipeline interval")
- `auto_convert_enabled` — master toggle for auto-conversion (default: true)
- `worker_count` — number of parallel conversion workers
- `scan_max_threads` — scanner parallelism (auto/manual)
- `lifecycle_grace_period_hours` — deletion grace period
- `lifecycle_trash_retention_days` — trash retention

Remove or hide:
- Manual scan trigger settings that no longer apply
- Any "conservative factor" or throttling that duplicates the pipeline's own scheduling
- Settings for features that are now automatic

Add:
- `pipeline_enabled` — master on/off for the entire scan+convert pipeline (default: true)
- `pipeline_max_files_per_run` — optional cap on files converted per pipeline cycle (default: 0 = unlimited)

- [ ] **Step 2: Update database defaults**

Add/modify preference defaults in `core/database.py`.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: rework settings for automated pipeline mode"
```

---

### Task 4: Rework the UI for pipeline mode

**Files:**
- Modify: `static/bulk.html` or equivalent — remove manual triggers, add pipeline controls
- Modify: `static/settings.html` or equivalent — rework settings section

- [ ] **Step 1: Remove manual "Start Scan" and "Start Conversion" buttons**

Replace with:
- Pipeline status indicator (running/idle/paused)
- Pause/Resume pipeline button
- "Run Now" button (triggers one immediate pipeline cycle)
- Last scan time + next scan time display

- [ ] **Step 2: Rework settings section**

Group settings logically:
- **Pipeline** — enabled, interval, max files per run
- **Scanning** — max threads, storage probe
- **Conversion** — worker count, OCR settings
- **Lifecycle** — grace period, trash retention

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: rework UI for automated pipeline mode"
```

---

### Task 5: Update API endpoints

**Files:**
- Modify: `api/routes/bulk.py` — adjust or deprecate manual trigger endpoints
- Add/modify: pipeline status endpoint

- [ ] **Step 1: Add pipeline status endpoint**

```
GET /api/pipeline/status
```

Returns: pipeline enabled, last scan time, next scan time, currently running, files pending, files converted this cycle.

- [ ] **Step 2: Add pipeline control endpoints**

```
POST /api/pipeline/pause
POST /api/pipeline/resume
POST /api/pipeline/run-now
```

- [ ] **Step 3: Keep existing bulk job endpoints for backward compatibility**

Don't break existing endpoints — they may be used by MCP tools or external integrations. Just ensure the pipeline uses the same underlying bulk job infrastructure.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add pipeline status and control API endpoints"
```

---

### Task 6: Update all project docs

**Files:**
- Modify: `CLAUDE.md` — update current status, architecture reminders, gotchas
- Modify: `docs/version-history.md` — add version entry
- Modify: `docs/key-files.md` — update file purposes
- Modify: `docs/gotchas.md` — add pipeline gotchas
- Modify: `README.md` — update feature description

- [ ] **Step 1: Update all 5 docs**

Key points to document:
- Pipeline replaces manual scan+convert triggers
- Lifecycle scanner is the sole entry point for new file detection
- Settings reworked for pipeline mode
- Existing bulk job API still works for programmatic access

- [ ] **Step 2: Bump version**

Update `core/version.py` to next version.

- [ ] **Step 3: Commit and push**

```bash
git add -A
git commit -m "feat: automated conversion pipeline — lifecycle scan triggers bulk conversion"
git push origin main
```

---

### Task 7: Verification

- [ ] **Step 1: Test the pipeline end-to-end**

1. Ensure pipeline is enabled in settings
2. Wait for lifecycle scan to run (or trigger with "Run Now")
3. Verify new/changed files are detected
4. Verify bulk conversion auto-starts
5. Verify converted files appear in output directory
6. Verify pipeline status endpoint reports correctly

- [ ] **Step 2: Test pause/resume**

1. Pause pipeline
2. Verify no new scans run
3. Resume pipeline
4. Verify scanning resumes

- [ ] **Step 3: Test settings changes**

1. Change scan interval
2. Verify scheduler picks up new interval
3. Disable auto-convert
4. Verify scan runs but conversion doesn't start
