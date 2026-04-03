# HDD Scan Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speed up mechanical HDD scans 10-100x via directory mtime skip, batched serial DB writes, and disk/DB write overlap — without changing any scan robustness features.

**Architecture:** New `scan_dir_mtimes` table caches directory mtimes between scans. All three scan paths (bulk serial, bulk parallel, lifecycle) check the cache before descending into directories. The bulk serial path batches DB writes (reusing existing `upsert_bulk_files_batch`) and overlaps stat() calls with DB writes via async tasks.

**Tech Stack:** Python/aiosqlite, os.walk/os.stat, asyncio

**Spec:** `docs/superpowers/specs/2026-04-03-hdd-scan-optimizations-design.md`

---

### Task 1: DB migration + preferences for directory mtime cache

**Files:**
- Modify: `core/db/schema.py` (add migration 21 after line 604)
- Modify: `core/db/preferences.py` (add 2 new defaults)
- Modify: `core/db/bulk.py` (add 4 new helpers)
- Modify: `core/db/__init__.py` (re-export new helpers)

- [ ] **Step 1: Add migration 21 to `core/db/schema.py`**

After migration 20 (line 604), before the closing `]` of `MIGRATIONS`, add:

```python
    (21, "Directory mtime cache for incremental scanning", [
        """CREATE TABLE IF NOT EXISTS scan_dir_mtimes (
            dir_path    TEXT PRIMARY KEY,
            dir_mtime   REAL NOT NULL,
            scan_run_id TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_scan_dir_mtimes_run ON scan_dir_mtimes(scan_run_id)",
    ]),
```

- [ ] **Step 2: Add preferences to `core/db/preferences.py`**

Add these two entries to the `DEFAULT_PREFERENCES` dict, in the Pipeline section (after `pipeline_auto_reset_days`):

```python
    # Incremental scanning (v0.19.5)
    "scan_incremental_enabled": "true",
    "scan_full_walk_interval": "5",
```

- [ ] **Step 3: Add DB helpers to `core/db/bulk.py`**

Add these four functions after `get_pipeline_files` (around line 455):

```python
async def load_dir_mtimes() -> dict[str, float]:
    """Load all cached directory mtimes into a dict for fast lookup."""
    rows = await db_fetch_all("SELECT dir_path, dir_mtime FROM scan_dir_mtimes")
    return {row["dir_path"]: row["dir_mtime"] for row in rows}


async def save_dir_mtimes_batch(
    dir_mtimes: dict[str, float],
    scan_run_id: str,
) -> None:
    """Persist directory mtimes in a single transaction."""
    if not dir_mtimes:
        return
    ts = now_iso()
    async with get_db() as conn:
        # Clear old entries and bulk-insert new ones
        await conn.execute("DELETE FROM scan_dir_mtimes")
        for dir_path, mtime in dir_mtimes.items():
            await conn.execute(
                "INSERT INTO scan_dir_mtimes (dir_path, dir_mtime, scan_run_id, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (dir_path, mtime, scan_run_id, ts),
            )
        await conn.commit()


async def get_incremental_scan_count() -> int:
    """Return the number of incremental scans since the last full walk."""
    row = await db_fetch_one(
        "SELECT value FROM preferences WHERE key = 'scan_incremental_count'"
    )
    if row:
        try:
            return int(row["value"])
        except (ValueError, TypeError):
            pass
    return 0


async def increment_scan_count() -> int:
    """Increment and return the incremental scan counter."""
    current = await get_incremental_scan_count()
    new_count = current + 1
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            ("scan_incremental_count", str(new_count), str(new_count)),
        )
        await conn.commit()
    return new_count


async def reset_scan_count() -> None:
    """Reset the incremental scan counter to 0 (after a full walk)."""
    async with get_db() as conn:
        await conn.execute(
            "INSERT INTO preferences (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = ?",
            ("scan_incremental_count", "0", "0"),
        )
        await conn.commit()
```

- [ ] **Step 4: Add re-exports in `core/db/__init__.py`**

Add `load_dir_mtimes`, `save_dir_mtimes_batch`, `get_incremental_scan_count`, `increment_scan_count`, `reset_scan_count` to the import from `core.db.bulk` and to the `__all__` list.

- [ ] **Step 5: Commit**

```bash
git add core/db/schema.py core/db/preferences.py core/db/bulk.py core/db/__init__.py
git commit -m "feat(db): add scan_dir_mtimes table, incremental scan preferences and helpers"
```

---

### Task 2: Directory mtime skip logic for bulk scanner

**Files:**
- Modify: `core/bulk_scanner.py` (scan method ~line 176, _serial_scan ~line 338, _walker_thread ~line 521)

- [ ] **Step 1: Add mtime skip decision logic to `scan()` method**

In the `scan()` method, after the exclusion loading block (around line 182) and before the storage probe (line 184), add the incremental scan decision:

```python
        # ── Incremental scan decision ──────────────────────────────────
        from core.db.bulk import (
            load_dir_mtimes, save_dir_mtimes_batch,
            get_incremental_scan_count, increment_scan_count, reset_scan_count,
        )
        incremental_enabled = (await get_preference("scan_incremental_enabled") or "true") == "true"
        full_walk_interval = int(await get_preference("scan_full_walk_interval") or "5")

        # Determine if this should be a full walk
        scan_count = await get_incremental_scan_count()
        bh_start = int((await get_preference("scanner_business_hours_start") or "06:00").split(":")[0])
        bh_end = int((await get_preference("scanner_business_hours_end") or "22:00").split(":")[0])
        current_hour = datetime.now().hour
        outside_business_hours = current_hour < bh_start or current_hour >= bh_end
        force_full_walk = (scan_count >= full_walk_interval) or outside_business_hours

        if incremental_enabled and not force_full_walk:
            self._dir_mtime_cache = await load_dir_mtimes()
            self._incremental_mode = True
            log.info("scan_incremental_mode", job_id=self.job_id,
                     cached_dirs=len(self._dir_mtime_cache),
                     scans_since_full=scan_count)
        else:
            self._dir_mtime_cache = {}
            self._incremental_mode = False
            reason = "outside_business_hours" if outside_business_hours else f"interval_reached ({scan_count}/{full_walk_interval})"
            log.info("scan_full_walk_mode", job_id=self.job_id, reason=reason)
```

Also add instance variable declarations in `__init__` or at the top of `scan()`:

```python
        self._dir_mtime_cache: dict[str, float] = {}
        self._current_dir_mtimes: dict[str, float] = {}
        self._incremental_mode = False
```

After the scan completes (after the serial/parallel scan call, around line 247), persist the directory mtimes and update counters:

```python
        # ── Persist directory mtimes for next incremental scan ──────────
        if self._current_dir_mtimes:
            try:
                await save_dir_mtimes_batch(self._current_dir_mtimes, self.job_id)
            except Exception:
                log.warning("save_dir_mtimes_failed", job_id=self.job_id)
        if self._incremental_mode:
            await increment_scan_count()
        else:
            await reset_scan_count()
```

- [ ] **Step 2: Add mtime skip to `_serial_scan` directory pruning**

In `_serial_scan` (line 338), modify the `os.walk` loop. Replace the `dirnames[:]` filtering block (lines 353-357) with:

```python
            # Record current directory mtime
            try:
                dir_mtime = os.stat(dirpath).st_mtime
                self._current_dir_mtimes[dirpath] = dir_mtime
            except OSError:
                dir_mtime = None

            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "_markflow"
                and not self._is_excluded(str(Path(dirpath) / d))
            ]

            # Incremental skip: if directory mtime unchanged, skip its files
            if (self._incremental_mode and dir_mtime is not None
                    and self._dir_mtime_cache.get(dirpath) == dir_mtime):
                # Directory unchanged — still need to record subdirs for mtime tracking
                # but skip processing files in this directory
                continue
```

- [ ] **Step 3: Add mtime skip to parallel `_walker_thread`**

In `_walker_thread` (around line 521), modify the inner `os.walk` loop. After the `dirnames[:]` pruning (line 524-528), add the same mtime skip check:

```python
                    # Record current directory mtime for cache
                    try:
                        dir_mtime = os.stat(dirpath).st_mtime
                        # Thread-safe: each worker writes different dirs
                        self._current_dir_mtimes[dirpath] = dir_mtime
                    except OSError:
                        dir_mtime = None

                    # Incremental skip: if directory mtime unchanged, skip files
                    if (self._incremental_mode and dir_mtime is not None
                            and self._dir_mtime_cache.get(dirpath) == dir_mtime):
                        continue
```

Note: `self._current_dir_mtimes` is written from multiple threads. Since each thread walks different directories (round-robin distribution), there are no write conflicts. Python dict assignment is atomic for simple key/value pairs.

- [ ] **Step 4: Commit**

```bash
git add core/bulk_scanner.py
git commit -m "feat(scan): add directory mtime skip to bulk scanner (serial + parallel)"
```

---

### Task 3: Directory mtime skip for lifecycle scanner

**Files:**
- Modify: `core/lifecycle_scanner.py` (walker thread ~line 665, scan function entry/exit)

- [ ] **Step 1: Add incremental scan decision to lifecycle scan entry**

Find the lifecycle scan entry function (the one that calls the parallel walker). Add the same incremental decision logic at the beginning — load mtime cache, decide full vs incremental, and at the end persist new mtimes and update counters.

The lifecycle scanner needs access to `_dir_mtime_cache`, `_current_dir_mtimes`, and `_incremental_mode`. Since the lifecycle scanner is function-based (not a class), pass these as parameters or use module-level variables scoped to the scan run.

Create a simple container at the top of the function:

```python
    # Incremental scan decision
    from core.db.bulk import (
        load_dir_mtimes, save_dir_mtimes_batch,
        get_incremental_scan_count, increment_scan_count, reset_scan_count,
    )
    incremental_enabled = (await get_preference("scan_incremental_enabled") or "true") == "true"
    full_walk_interval = int(await get_preference("scan_full_walk_interval") or "5")
    scan_count = await get_incremental_scan_count()
    bh_start = int((await get_preference("scanner_business_hours_start") or "06:00").split(":")[0])
    bh_end = int((await get_preference("scanner_business_hours_end") or "22:00").split(":")[0])
    current_hour = datetime.now().hour
    outside_business_hours = current_hour < bh_start or current_hour >= bh_end
    force_full = (scan_count >= full_walk_interval) or outside_business_hours

    if incremental_enabled and not force_full:
        dir_mtime_cache = await load_dir_mtimes()
        incremental_mode = True
        log.info("lifecycle_scan.incremental_mode", cached_dirs=len(dir_mtime_cache))
    else:
        dir_mtime_cache = {}
        incremental_mode = False

    current_dir_mtimes: dict[str, float] = {}
```

Pass `dir_mtime_cache`, `current_dir_mtimes`, and `incremental_mode` to the walker thread function.

- [ ] **Step 2: Add mtime skip to lifecycle walker thread**

In the lifecycle `_walker_thread` (line 665-683), after the `dirnames[:]` pruning (line 671-675), add:

```python
                    # Record dir mtime and skip if unchanged
                    try:
                        _dir_mt = os.stat(dirpath).st_mtime
                        current_dir_mtimes[dirpath] = _dir_mt
                    except OSError:
                        _dir_mt = None
                    if (incremental_mode and _dir_mt is not None
                            and dir_mtime_cache.get(dirpath) == _dir_mt):
                        continue
```

- [ ] **Step 3: Persist mtimes and update counter after lifecycle scan**

After the walker finishes and before the function returns, add:

```python
    # Persist directory mtimes
    if current_dir_mtimes:
        try:
            await save_dir_mtimes_batch(current_dir_mtimes, scan_run_id)
        except Exception:
            log.warning("lifecycle_scan.save_dir_mtimes_failed")
    if incremental_mode:
        await increment_scan_count()
    else:
        await reset_scan_count()
```

- [ ] **Step 4: Commit**

```bash
git add core/lifecycle_scanner.py
git commit -m "feat(scan): add directory mtime skip to lifecycle scanner"
```

---

### Task 4: Batch serial DB writes + disk/DB overlap

**Files:**
- Modify: `core/bulk_scanner.py` (`_serial_scan` method, lines 315-389)

- [ ] **Step 1: Rewrite `_serial_scan` with batched writes and async overlap**

Replace the `_serial_scan` method body (lines 315-389) with a new implementation that:

1. Walks directories sequentially (same `os.walk`)
2. Accumulates convertible files into a batch buffer (max 200)
3. When buffer is full, fires an `asyncio.Task` for the DB write and continues stat'ing
4. Awaits the previous DB write task before starting a new one
5. Unrecognized files still go per-file (need MIME classification)

```python
    async def _serial_scan(
        self,
        tracker: RollingWindowETA,
        result: ScanResult,
        on_progress: Callable[[dict], Awaitable[None]] | None,
        progress_interval: int,
    ) -> int:
        """Single-threaded scan with batched DB writes and disk/DB overlap."""
        file_count = 0
        last_eta_write = time.monotonic()
        error_monitor = ErrorRateMonitor()

        # Batch buffer for convertible files
        BATCH_SIZE = 200
        convertible_batch: list[tuple[str, str, int, float]] = []
        pending_write: asyncio.Task | None = None

        async def _flush_batch() -> None:
            """Write accumulated convertible files to DB."""
            nonlocal convertible_batch
            if not convertible_batch:
                return
            batch = convertible_batch
            convertible_batch = []
            await upsert_bulk_files_batch(self.job_id, batch)

        def _serial_walk_error(err: OSError) -> None:
            if isinstance(err, PermissionError):
                log.warning(
                    "scan_permission_denied",
                    path=str(err.filename or ""),
                    error=str(err),
                    hint="folder may be gated by Active Directory",
                )
            else:
                log.warning("scan_walk_error", path=str(err.filename or ""), error=str(err))

        for dirpath, dirnames, filenames in os.walk(self.source_path, onerror=_serial_walk_error):
            if should_stop() or error_monitor.should_abort():
                reason = "high_error_rate" if error_monitor.aborted else "global_stop_requested"
                log.warning("scan_stopped_early", job_id=self.job_id,
                            scanned_so_far=file_count, reason=reason)
                if on_progress:
                    await on_progress({
                        "event": "scan_stopped" if not error_monitor.aborted else "scan_aborted",
                        "job_id": self.job_id,
                        "scanned": file_count,
                        "reason": reason,
                        "total_errors": error_monitor.total_errors,
                    })
                break

            # Record current directory mtime for incremental cache
            try:
                dir_mtime = os.stat(dirpath).st_mtime
                self._current_dir_mtimes[dirpath] = dir_mtime
            except OSError:
                dir_mtime = None

            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d != "_markflow"
                and not self._is_excluded(str(Path(dirpath) / d))
            ]

            # Incremental skip: directory unchanged since last scan
            if (self._incremental_mode and dir_mtime is not None
                    and self._dir_mtime_cache.get(dirpath) == dir_mtime):
                continue

            for filename in filenames:
                file_path = Path(dirpath) / filename
                if self._is_excluded(str(file_path)):
                    continue
                # Skip NTFS Alternate Data Streams
                if ":" in file_path.name:
                    continue

                # Check blocklist
                from core.flag_manager import is_blocklisted
                if await is_blocklisted(str(file_path)):
                    continue

                ext = _get_effective_extension(file_path)

                try:
                    stat = file_path.stat()
                    file_size = stat.st_size
                    mtime = stat.st_mtime
                except FileNotFoundError:
                    log.debug("scan_file_vanished", path=str(file_path))
                    continue
                except PermissionError:
                    log.debug("scan_file_permission_denied", path=str(file_path))
                    continue
                except OSError as exc:
                    log.warning("bulk_scan_stat_error", path=str(file_path), error=str(exc))
                    error_monitor.record_error(f"stat failed: {file_path}")
                    if error_monitor.should_abort():
                        break
                    continue

                error_monitor.record_success()
                result.total_discovered += 1

                if ext in SUPPORTED_EXTENSIONS:
                    result.convertible_count += 1
                    self._convertible_paths.append(file_path)
                    convertible_batch.append((str(file_path), ext, file_size, mtime))

                    # Flush batch when full — overlap with next stat() calls
                    if len(convertible_batch) >= BATCH_SIZE:
                        if pending_write is not None:
                            await pending_write
                        pending_write = asyncio.create_task(_flush_batch())
                else:
                    result.unrecognized_count += 1
                    await self._record_unrecognized(file_path, ext, file_size, mtime)

                file_count += 1
                await tracker.record_completion()

                if on_progress and (file_count % progress_interval == 0):
                    await self._emit_progress(
                        on_progress, tracker, file_count, file_path,
                    )

                now = time.monotonic()
                if now - last_eta_write >= ETA_UPDATE_INTERVAL:
                    await self._log_eta(tracker, last_eta_write)
                    last_eta_write = now

                if file_count % self._yield_interval == 0:
                    await asyncio.sleep(0)

        # Flush remaining batch
        if pending_write is not None:
            await pending_write
        await _flush_batch()

        return file_count
```

This replaces the old `_serial_scan` and `_process_discovered_file` (for the serial path). The `_process_discovered_file` method remains for any other callers but is no longer called by `_serial_scan`.

- [ ] **Step 2: Commit**

```bash
git add core/bulk_scanner.py
git commit -m "feat(scan): batch serial DB writes + disk/DB overlap in _serial_scan"
```

---

### Task 5: Update docs and version

**Files:**
- Modify: `CLAUDE.md`
- Modify: `core/version.py`
- Modify: `docs/version-history.md`
- Modify: `docs/gotchas.md`

- [ ] **Step 1: Update CLAUDE.md**

Update the Current Status section for v0.19.5 describing the HDD scan optimizations: directory mtime skip (all 3 scan paths), batched serial DB writes, disk/DB overlap, full walk forced every Nth scan and outside business hours, new preferences.

- [ ] **Step 2: Bump version**

Update `core/version.py` from `0.19.4` to `0.19.5`.

- [ ] **Step 3: Update version-history.md**

Add v0.19.5 entry.

- [ ] **Step 4: Update gotchas.md**

Add gotchas:
- `scan_dir_mtimes` shared between bulk and lifecycle scanners — whichever ran last provides the cache
- Incremental scan counter is a preference, not a table column — simple `preferences` key `scan_incremental_count`
- Full walk forced outside business hours using `scanner_business_hours_start/end`
- `_current_dir_mtimes` dict is written from multiple walker threads — safe because each thread walks different directories (round-robin)
- Cancelled scans still persist their dir mtimes (the dirs they did visit are valid)

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md core/version.py docs/version-history.md docs/gotchas.md
git commit -m "docs: update for v0.19.5 HDD scan optimizations"
```
