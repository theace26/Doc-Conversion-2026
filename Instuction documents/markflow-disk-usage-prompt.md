# MarkFlow — Admin Disk Usage Feature

> Target version: **v0.9.6**
> Scope: One new backend endpoint + one new UI section on admin.html
> Read `CLAUDE.md` before starting.

---

## Context

The admin page (`static/admin.html`) already has four sections:
1. **Repository Overview** — KPI cards (file counts, lifecycle stats, OCR stats, etc.)
2. **Task Manager** — per-core CPU bars, memory gauge, thread count (2s polling via `GET /api/admin/system/metrics`)
3. **Resource Controls** — worker count, process priority, CPU core pinning
4. **API Key Management** — create/revoke service account keys
5. **DB Tools** — health check, integrity check, dump-and-restore repair

`core/resource_manager.py` already wraps `psutil` and is imported in the admin routes.
`psutil` provides `disk_usage()` and filesystem traversal is trivial with `pathlib`.

The admin route file is `api/routes/admin.py`. The admin page JS is inline in `static/admin.html`.

---

## What to Build

### 1. New endpoint — `GET /api/admin/disk-usage`

Add to `api/routes/admin.py`. Requires `ADMIN` role (same as all other admin endpoints).

Compute sizes for every directory MarkFlow writes to. Run the directory walks in a thread
to avoid blocking the event loop (`asyncio.to_thread`).

**Response shape:**

```json
{
  "total_bytes": 1482735616,
  "total_human": "1.38 GB",
  "breakdown": [
    {
      "label": "Output Repository",
      "path": "/mnt/output-repo",
      "bytes": 1073741824,
      "human": "1.00 GB",
      "file_count": 24350,
      "description": "Bulk-converted Markdown knowledge base"
    },
    {
      "label": "Trash",
      "path": "/mnt/output-repo/.trash",
      "bytes": 209715200,
      "human": "200.00 MB",
      "file_count": 1200,
      "description": "Soft-deleted files awaiting purge"
    },
    {
      "label": "Conversion Output",
      "path": "/app/output",
      "bytes": 104857600,
      "human": "100.00 MB",
      "file_count": 580,
      "description": "Single-file conversion results"
    },
    {
      "label": "Database",
      "path": "/app/data/markflow.db",
      "bytes": 52428800,
      "human": "50.00 MB",
      "file_count": 1,
      "description": "SQLite database (WAL mode)"
    },
    {
      "label": "Database WAL",
      "path": "/app/data/markflow.db-wal",
      "bytes": 1048576,
      "human": "1.00 MB",
      "file_count": 1,
      "description": "SQLite write-ahead log"
    },
    {
      "label": "Logs",
      "path": "/app/logs",
      "bytes": 10485760,
      "human": "10.00 MB",
      "file_count": 4,
      "description": "Operational and debug log files"
    },
    {
      "label": "Meilisearch Data",
      "path": "/meili_data",
      "bytes": 31457280,
      "human": "30.00 MB",
      "file_count": null,
      "description": "Search index data"
    }
  ],
  "volume_info": {
    "mount": "/",
    "total_bytes": 107374182400,
    "total_human": "100.00 GB",
    "used_bytes": 53687091200,
    "used_human": "50.00 GB",
    "free_bytes": 53687091200,
    "free_human": "50.00 GB",
    "used_percent": 50.0
  }
}
```

**Implementation details:**

```python
import os
from pathlib import Path

# These paths match docker-compose.yml volumes
_DISK_TARGETS = [
    ("Output Repository", Path("/mnt/output-repo"), "Bulk-converted Markdown knowledge base"),
    ("Trash", Path("/mnt/output-repo/.trash"), "Soft-deleted files awaiting purge"),
    ("Conversion Output", Path(os.environ.get("OUTPUT_DIR", "output")), "Single-file conversion results"),
    ("Logs", Path(os.environ.get("LOG_DIR", "logs")), "Operational and debug log files"),
    ("Meilisearch Data", Path(os.environ.get("MEILI_DATA_PATH", "/meili_data")), "Search index data"),
]

# DB is a single file — don't walk, just stat
_DB_PATH = Path(os.environ.get("DB_PATH", "/app/data/markflow.db"))
```

For each directory target:
- Use `Path.rglob("*")` to find all files (skip `.rglob` on missing dirs — return 0 bytes, 0 files)
- Sum file sizes via `f.stat().st_size` (catch `OSError` per-file and skip)
- Count files
- Wrap the entire walk in `asyncio.to_thread()` since large repos can take a few seconds

For the database:
- Stat `markflow.db` directly
- Also stat `markflow.db-wal` and `markflow.db-shm` if they exist (WAL mode files)
- Report DB and WAL as separate line items

For `volume_info`:
- Use `psutil.disk_usage("/")` (or the mount point of the output-repo volume)
- This gives total/used/free/percent for the underlying filesystem

Human-readable formatting helper:
```python
def _human_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"
```

**Important: Trash is a SUBTREE of output-repo.** The trash bytes must be subtracted from
the output-repo total to avoid double-counting. Compute trash first, then compute
output-repo excluding `.trash/`:

```python
# Walk output-repo but skip .trash directory
for f in repo_path.rglob("*"):
    if f.is_file() and ".trash" not in f.parts:
        repo_bytes += f.stat().st_size
        repo_count += 1
```

The endpoint must never return 500. Wrap everything in try/except and return
partial results with `null` for any section that fails. Follow the same pattern as
`GET /api/admin/stats`.

---

### 2. New UI section on `static/admin.html` — "Disk Usage"

Add a new collapsible section between **Repository Overview** and **Task Manager**.
Use the existing design system classes from `markflow.css`.

**Layout:**

```
┌─────────────────────────────────────────────────────────────┐
│  Disk Usage                                    [↻ Refresh]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Total MarkFlow footprint: 1.38 GB                         │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Volume: / ── 50.00 GB used of 100.00 GB (50.0%)    │    │
│  │ ████████████████████░░░░░░░░░░░░░░░░░░░░           │    │
│  │ MarkFlow: 1.38 GB (1.4% of volume)                 │    │
│  │ ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░            │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ Output Repo      │  │ Trash            │                 │
│  │ 1.00 GB          │  │ 200.00 MB        │                 │
│  │ 24,350 files     │  │ 1,200 files      │                 │
│  └──────────────────┘  └──────────────────┘                 │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ Conversion Out   │  │ Database         │                 │
│  │ 100.00 MB        │  │ 51.00 MB         │                 │
│  │ 580 files        │  │ DB + WAL         │                 │
│  └──────────────────┘  └──────────────────┘                 │
│  ┌──────────────────┐  ┌──────────────────┐                 │
│  │ Logs             │  │ Meilisearch      │                 │
│  │ 10.00 MB         │  │ 30.00 MB         │                 │
│  │ 4 files          │  │ Search indexes   │                 │
│  └──────────────────┘  └──────────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Implementation notes:**

- Use the existing `.stat-card` class (same as Repository Overview cards) for the breakdown items
- The volume progress bars use a simple `<div>` with percentage width and `var(--accent)` background
- The MarkFlow-share bar should use a contrasting color (e.g., `var(--warning)` or `var(--info)`)
- File counts formatted with `toLocaleString()` for commas
- The Refresh button calls `fetchDiskUsage()` — this is NOT auto-polled (disk walks are expensive). Manual refresh only.
- Show a brief loading spinner during the fetch since the walk can take a few seconds on large repos
- On initial page load, fetch disk usage once automatically (same as the stats section)
- If a breakdown item has `file_count: null` (e.g., Meilisearch — we may not be able to count its internal files), show the description text instead of a count
- If a breakdown item has `bytes: 0` and `file_count: 0`, still show the card (with "Empty" or "0 B") — don't hide it. The user wants to see all monitored paths.
- Combine Database + Database WAL into a single card in the UI (sum the bytes, show "DB + WAL" as subtitle). Keep them separate in the API response for transparency.

**Card color coding (optional, nice-to-have):**
- Output Repo card: default card style
- Trash card: if trash bytes > 1 GB, add a subtle warning border (`var(--warning)`) to nudge the admin to purge
- Database card: if DB > 500 MB, subtle warning border

---

### 3. Gotcha for CLAUDE.md

Add this to the Gotchas section:

```
- **Disk usage endpoint is not auto-polled**: `GET /api/admin/disk-usage` walks
  directories in a thread. On large repos (100K+ files) this can take 5-10 seconds.
  The admin UI fetches once on load and has a manual Refresh button — no interval
  polling. Do not add setInterval for this endpoint.

- **Trash is subtracted from output-repo total**: The `.trash/` directory lives
  inside `/mnt/output-repo`. The disk usage endpoint reports them separately and
  excludes `.trash/` from the output-repo walk to avoid double-counting.
```

---

## Files to Modify

| File | Change |
|------|--------|
| `api/routes/admin.py` | Add `GET /api/admin/disk-usage` endpoint |
| `static/admin.html` | Add Disk Usage section (HTML + JS) |

No new files. No new dependencies. No new tests required (but adding a basic test
for the endpoint shape in `test_admin.py` is welcome).

---

## Done Criteria

- [ ] `GET /api/admin/disk-usage` returns the response shape above
- [ ] Endpoint requires ADMIN role
- [ ] Endpoint never returns 500 — partial results on error
- [ ] Directory walks run in `asyncio.to_thread()`
- [ ] Trash bytes excluded from output-repo total (no double-counting)
- [ ] DB + WAL reported as separate items in API, combined in UI
- [ ] Admin page shows Disk Usage section with volume bar + breakdown cards
- [ ] Manual Refresh button works
- [ ] Loading state shown during fetch
- [ ] Large numbers formatted with commas
- [ ] Cards show even when empty (0 B)
- [ ] CLAUDE.md updated with version note and gotchas
- [ ] Tag `v0.9.6`
