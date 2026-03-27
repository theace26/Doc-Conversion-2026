# MarkFlow Patch: Path Safety & Collision Handling
# Version: patch-0.7.4b
# Scope: Bulk scanner, bulk worker, database, bulk API, bulk UI.
# No changes to format handlers, OCR engine, or single-file conversion logic.

---

## 0. Read First

Load `CLAUDE.md` before writing anything. This patch addresses two structural gaps
in the bulk conversion output path mapping:

1. **Path length overflow** — deeply nested source paths can produce output paths
   that exceed filesystem limits, causing silent write failures.

2. **Output path collisions** — two source files with the same stem but different
   extensions (e.g. `report.docx` and `report.pdf`) map to the same output path
   (`report.md`), causing the second to silently overwrite the first.

Both problems are detected at scan time, not at conversion time. Files with these
problems are flagged before any conversion is attempted. Nothing is silently lost.

---

## 1. Configuration

### New preferences

Add to `_PREFERENCE_SCHEMA` in `api/routes/preferences.py`:

| Key | Type | Default | Valid values | Label |
|-----|------|---------|--------------|-------|
| `max_output_path_length` | number | 240 | 100–400 | Max output path length (chars) |
| `collision_strategy` | select | `rename` | `rename`, `skip`, `error` | Duplicate filename strategy |

**`max_output_path_length`** — output paths (absolute, container-side) longer than
this value are flagged as `path_too_long` and skipped. Default 240 leaves margin
below the 255-char Linux limit and the 260-char Windows limit.

**`collision_strategy`** — what to do when two source files map to the same output path:
- `rename` — append source extension before `.md`:
  `report.docx` → `report.docx.md`, `report.pdf` → `report.pdf.md`. **Default.**
  No data loss. Both files are converted.
- `skip` — convert the first file encountered, skip all subsequent collisions.
  Skipped files are recorded in the collision report.
- `error` — mark all colliding files as failed. No file in a collision group
  is converted. Requires manual resolution before re-running.

Add both to `.env.example` as optional overrides:
```bash
# Bulk conversion path safety
MAX_OUTPUT_PATH_LENGTH=240
COLLISION_STRATEGY=rename
```

---

## 2. Database Changes

### `core/database.py` (modify)

Add two new tables. Use `_add_column_if_missing()` pattern for any column additions
to existing tables (already established in v0.7.3).

#### Table: `bulk_path_issues`

Stores all path problems detected during scan — both length overflows and collisions.
Populated during scan, before any conversion is attempted.

```sql
CREATE TABLE IF NOT EXISTS bulk_path_issues (
    id              TEXT PRIMARY KEY,       -- UUID
    job_id          TEXT NOT NULL REFERENCES bulk_jobs(id),
    issue_type      TEXT NOT NULL,          -- 'path_too_long' | 'collision' | 'case_collision'
    source_path     TEXT NOT NULL,          -- the problematic source file
    output_path     TEXT,                   -- the intended (conflicting) output path
    collision_group TEXT,                   -- shared output path for collision groups (null for path_too_long)
    collision_peer  TEXT,                   -- other source file in collision (null for path_too_long)
    resolution      TEXT,                   -- 'renamed' | 'skipped' | 'errored' | 'pending'
    resolved_path   TEXT,                   -- final output path after rename (null if not renamed)
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_path_issues_job
    ON bulk_path_issues(job_id, issue_type);
CREATE INDEX IF NOT EXISTS idx_path_issues_collision_group
    ON bulk_path_issues(collision_group);
```

#### Extend `bulk_jobs` table

Add columns (use `_add_column_if_missing`):
```sql
path_too_long_count   INTEGER NOT NULL DEFAULT 0
collision_count       INTEGER NOT NULL DEFAULT 0
case_collision_count  INTEGER NOT NULL DEFAULT 0
```

#### New DB helpers

```python
async def record_path_issue(job_id, issue_type, source_path,
                             output_path=None, collision_group=None,
                             collision_peer=None, resolution=None,
                             resolved_path=None) -> str
    """Insert into bulk_path_issues. Returns id."""

async def get_path_issues(job_id, issue_type=None) -> list[dict]
    """Return all path issues for a job, optionally filtered by type."""

async def get_path_issue_summary(job_id) -> dict
    """
    Returns:
    {
        "path_too_long": N,
        "collision": N,
        "case_collision": N,
        "total": N
    }
    """

async def update_path_issue_resolution(issue_id, resolution,
                                        resolved_path=None) -> None

async def get_collision_group(job_id, output_path) -> list[dict]
    """Return all path issues sharing the same collision_group (output_path)."""
```

---

## 3. Path Safety Utilities

### `core/path_utils.py` (new file)

All path validation and collision logic lives here. No filesystem writes — pure
computation. Tested independently of the bulk pipeline.

```python
from pathlib import Path
from typing import Literal

CollisionStrategy = Literal["rename", "skip", "error"]

# ---------------------------------------------------------------------------
# Path length check
# ---------------------------------------------------------------------------

def check_path_length(output_path: Path, max_length: int = 240) -> bool:
    """
    Returns True if the path is within the allowed length.
    Returns False if it exceeds max_length.
    Measures the full absolute path string length.
    """
    return len(str(output_path)) <= max_length


def truncate_path_diagnosis(source_path: Path, output_path: Path,
                             max_length: int) -> dict:
    """
    Returns a diagnostic dict for a path that is too long:
    {
        "source_path": str,
        "output_path": str,
        "output_path_length": int,
        "max_length": int,
        "overage": int,         # how many chars over the limit
        "suggestion": str       # human-readable suggestion
    }
    """


# ---------------------------------------------------------------------------
# Output path mapping
# ---------------------------------------------------------------------------

def map_output_path(source_file: Path, source_root: Path,
                    output_root: Path) -> Path:
    """
    Maps a source file to its mirrored output .md path.

    source_root: /mnt/source
    source_file: /mnt/source/dept/finance/Q4_Report.docx
    output_root: /mnt/output-repo
    returns:     /mnt/output-repo/dept/finance/Q4_Report.md

    Raises ValueError if source_file is not under source_root.
    """
    relative = source_file.relative_to(source_root)
    return output_root / relative.with_suffix(".md")


def map_output_path_renamed(source_file: Path, source_root: Path,
                             output_root: Path) -> Path:
    """
    Collision-safe variant — appends source extension before .md.

    source_file: /mnt/source/dept/finance/report.pdf
    returns:     /mnt/output-repo/dept/finance/report.pdf.md

    Used when collision_strategy = 'rename' and a collision is detected.
    """
    relative = source_file.relative_to(source_root)
    new_name = relative.name + ".md"    # e.g. "report.pdf.md"
    return output_root / relative.parent / new_name


# ---------------------------------------------------------------------------
# Collision detection
# ---------------------------------------------------------------------------

def detect_collisions(
    file_list: list[Path],
    source_root: Path,
    output_root: Path
) -> dict[str, list[Path]]:
    """
    Given a list of source file paths, find all output path collisions.

    Returns a dict mapping each colliding output path (str) to the list
    of source files that map to it.

    Only paths with 2+ source files are included (no collision = not returned).

    Example:
        {
            "/mnt/output-repo/dept/finance/report.md": [
                Path("/mnt/source/dept/finance/report.docx"),
                Path("/mnt/source/dept/finance/report.pdf")
            ]
        }
    """
    seen: dict[str, list[Path]] = {}
    for f in file_list:
        out = map_output_path(f, source_root, output_root)
        key = str(out)
        seen.setdefault(key, []).append(f)
    return {k: v for k, v in seen.items() if len(v) > 1}


def detect_case_collisions(
    file_list: list[Path],
    source_root: Path,
    output_root: Path
) -> dict[str, list[Path]]:
    """
    Find files whose output paths differ only by case.
    This catches Windows case-insensitive filesystem pairs that become
    collisions inside the Linux container.

    Returns same shape as detect_collisions() but keyed by
    lowercased output path.

    Example:
        {
            "/mnt/output-repo/dept/finance/report.md": [
                Path("/mnt/source/dept/finance/Report.docx"),
                Path("/mnt/source/dept/finance/report.docx")
            ]
        }
    """
    seen: dict[str, list[Path]] = {}
    for f in file_list:
        out = map_output_path(f, source_root, output_root)
        key = str(out).lower()
        seen.setdefault(key, []).append(f)
    # Only return groups where lowercased paths match but originals differ
    return {
        k: v for k, v in seen.items()
        if len(v) > 1 and len({str(map_output_path(f, source_root, output_root))
                                for f in v}) > 1
    }


def resolve_collision(
    collision_group: list[Path],
    source_root: Path,
    output_root: Path,
    strategy: CollisionStrategy
) -> dict[Path, tuple[str, Path | None]]:
    """
    Given a group of source files that collide, apply the strategy and
    return a resolution for each file.

    Returns dict mapping source_path → (resolution, resolved_output_path):
        resolution: 'renamed' | 'skipped' | 'errored'
        resolved_output_path: final output path (None if skipped/errored)

    Strategy behavior:
        'rename':
            All files in the group get renamed output paths.
            e.g. report.docx → report.docx.md
                 report.pdf  → report.pdf.md
        'skip':
            First file (sorted by source_path for determinism) gets the
            canonical output path. All others are marked 'skipped'.
        'error':
            All files in the group are marked 'errored'. None are converted.
    """
    sorted_group = sorted(collision_group, key=lambda p: str(p))
    result = {}

    if strategy == "rename":
        for f in sorted_group:
            renamed = map_output_path_renamed(f, source_root, output_root)
            result[f] = ("renamed", renamed)

    elif strategy == "skip":
        first = sorted_group[0]
        canonical = map_output_path(first, source_root, output_root)
        result[first] = ("skipped_kept", canonical)   # kept, no rename
        for f in sorted_group[1:]:
            result[f] = ("skipped", None)

    elif strategy == "error":
        for f in sorted_group:
            result[f] = ("errored", None)

    return result
```

---

## 4. Scanner Changes

### `core/bulk_scanner.py` (modify)

The scanner is responsible for detecting all path issues during the discovery phase,
before any conversion work begins. This is the right place — catch problems early,
never during conversion.

#### Modify `BulkScanner.scan()` — add path safety pass

After collecting all convertible files and before returning `ScanResult`, run the
path safety pass:

```python
async def _run_path_safety_pass(
    self,
    all_files: list[Path],
    source_root: Path,
    output_root: Path,
    max_path_length: int,
    collision_strategy: CollisionStrategy
) -> PathSafetyResult:
    """
    1. Check every file for path length overflow
    2. Detect standard collisions (same stem, different extension)
    3. Detect case collisions
    4. Record all issues in bulk_path_issues table
    5. Build a mapping: source_path → final_output_path (or None if skipped/errored)
    6. Return PathSafetyResult

    Yields control (await asyncio.sleep(0)) every 500 files.
    """
```

#### `PathSafetyResult` dataclass

```python
@dataclass
class PathSafetyResult:
    path_too_long: list[Path]           # files exceeding max path length
    collision_groups: dict[str, list[Path]]  # output_path → [source files]
    case_collision_groups: dict[str, list[Path]]
    # Final resolved mapping for all files:
    # source_path → (final_output_path | None, resolution_note)
    resolved_paths: dict[Path, tuple[Path | None, str]]
    # Counts
    total_checked: int
    safe_count: int
    too_long_count: int
    collision_count: int
    case_collision_count: int
```

#### Modify `ScanResult` — add path safety fields

```python
@dataclass
class ScanResult:
    job_id: str
    total_discovered: int
    convertible_count: int
    adobe_count: int
    skipped_count: int
    new_count: int
    changed_count: int
    # New fields:
    path_too_long_count: int        # files that exceeded max path length
    collision_count: int            # files involved in collisions
    case_collision_count: int       # files involved in case collisions
    path_safety_result: PathSafetyResult
    scan_duration_ms: int
```

#### Scanner log events (add to structured logging)

```python
log.info("path_safety_pass_complete",
    job_id=job_id,
    total_checked=result.total_checked,
    too_long=result.too_long_count,
    collisions=result.collision_count,
    case_collisions=result.case_collision_count
)

# One event per collision group (not per file — avoid log spam)
for output_path, files in result.collision_groups.items():
    log.warning("output_collision_detected",
        job_id=job_id,
        output_path=output_path,
        source_files=[str(f) for f in files],
        strategy=collision_strategy
    )
```

---

## 5. Worker Changes

### `core/bulk_worker.py` (modify)

#### Use resolved paths from scanner

The scanner now produces a `resolved_paths` dict mapping each source file to its
final output path (or None if it should be skipped/errored). The worker must
use this dict instead of calling `_map_output_path()` directly.

```python
# In BulkJob.run() — after scan completes:
self._resolved_paths = scan_result.path_safety_result.resolved_paths

# In BulkJob._worker() — when processing a file:
resolved = self._resolved_paths.get(Path(file.source_path))
if resolved is None:
    # File was flagged during scan — should not reach here,
    # but guard defensively
    log.error("worker_received_unresolved_file", source_path=file.source_path)
    continue

final_output_path, resolution_note = resolved

if final_output_path is None:
    # File was skipped or errored during path safety pass
    # bulk_files record already updated by scanner — skip silently
    continue
```

#### Update `bulk_files` records for path issues

When the scanner flags a file, update its `bulk_files` record:
- `path_too_long`: status = `skipped`, error_msg = `"Output path too long ({N} chars, max {M})"`
- `collision` + strategy `skip` (non-kept): status = `skipped`, error_msg = `"Output collision — skipped in favor of {peer}"`
- `collision` + strategy `error`: status = `failed`, error_msg = `"Output collision with {peer} — manual resolution required"`
- `collision` + strategy `rename`: status stays `pending`, output_path updated to renamed path

#### SSE events for path issues

Emit during the scan phase (inside `scan_complete` event and as separate events):

```
event: path_issues_found
data: {
    "job_id": "...",
    "too_long": 3,
    "collisions": 12,
    "case_collisions": 2,
    "total_affected": 17,
    "strategy_applied": "rename"
}
```

If `too_long > 0` or `collision_count > 0` with strategy `error`:
```
event: path_issues_require_attention
data: {
    "job_id": "...",
    "message": "12 files have output path collisions and will not be converted. Review before proceeding.",
    "details_url": "/api/bulk/jobs/{id}/path-issues"
}
```

---

## 6. API Changes

### `api/routes/bulk.py` (modify)

**Extend `GET /api/bulk/jobs/{job_id}`** — add path issue counts to response:

```json
{
  "job_id": "...",
  "status": "completed",
  "converted": 56200,
  "skipped": 22000,
  "failed": 250,
  "path_too_long_count": 3,
  "collision_count": 12,
  "case_collision_count": 2,
  ...
}
```

**New endpoint: `GET /api/bulk/jobs/{job_id}/path-issues`**

Returns all path issues for a job, grouped by type.

Query params: `type` (`path_too_long` | `collision` | `case_collision`),
`page`, `per_page` (default 50)

```json
{
  "job_id": "...",
  "summary": {
    "path_too_long": 3,
    "collision": 12,
    "case_collision": 2,
    "total": 17
  },
  "issues": [
    {
      "id": "...",
      "issue_type": "collision",
      "source_path": "/host/c/.../report.pdf",
      "output_path": "/mnt/output-repo/dept/finance/report.md",
      "collision_peer": "/host/c/.../report.docx",
      "resolution": "renamed",
      "resolved_path": "/mnt/output-repo/dept/finance/report.pdf.md"
    },
    {
      "id": "...",
      "issue_type": "path_too_long",
      "source_path": "/host/c/very/deeply/nested/.../file.docx",
      "output_path": "/mnt/output-repo/very/deeply/nested/.../file.md",
      "resolution": "skipped",
      "resolved_path": null
    }
  ]
}
```

**New endpoint: `GET /api/bulk/jobs/{job_id}/path-issues/export`**

Returns the full path issues list as a downloadable CSV. Useful for sending
to whoever owns the source share to fix naming issues.

CSV columns:
```
issue_type, source_path, output_path, collision_peer, resolution, resolved_path
```

---

## 7. Manifest Changes

### `core/metadata.py` (modify)

Extend `generate_manifest()` to include a `path_issues` section:

```json
{
  "batch_id": "...",
  "job_id": "...",
  "converted": 56200,
  "skipped": 22000,
  "failed": 250,
  "path_issues": {
    "summary": {
      "path_too_long": 3,
      "collision": 12,
      "case_collision": 2
    },
    "files": [
      {
        "issue_type": "collision",
        "source_path": "dept/finance/report.pdf",
        "resolution": "renamed",
        "resolved_path": "dept/finance/report.pdf.md"
      }
    ]
  }
}
```

If no path issues: `"path_issues": null`.

---

## 8. UI Changes

### `static/bulk.html` (modify)

**During scan phase** — if `path_issues_found` SSE event is received with
non-zero counts, show an inline alert below the scan progress:

```
⚠ Path issues detected during scan:
  • 3 files have paths that are too long and will be skipped
  • 12 files have output name collisions → renamed automatically (report.docx.md, report.pdf.md)
  • 2 files have case-sensitivity collisions → renamed automatically
  [View Details →]
```

Color: amber (`--warn`) for rename/skip, red (`--error`) for error strategy.

If strategy is `error` and collisions > 0, show a stronger warning:
```
⛔ 12 files have output name collisions and WILL NOT be converted.
   Strategy is set to 'error'. Change to 'rename' in Settings to convert them.
   [Change Strategy →]  [View Details →]
```

"Change Strategy →" links to `settings.html#collision-strategy`.
"View Details →" links to the path issues panel (see below).

**After job complete** — if path issues exist, add a section to the completion
summary alongside the review queue section:

```
Path Issues — 17 files affected
  3 too long (skipped)  ·  12 collisions (renamed)  ·  2 case collisions (renamed)
  [Download Report (CSV) ↗]  [View Details →]
```

**Path issues detail panel** (inline expandable, not a new page):

Triggered by "View Details →". Expands below the job summary.

```
Path Issues
──────────────────────────────────────────────────────
Filter: [All types ▾]

⚠ COLLISION (renamed)
   report.pdf     → report.pdf.md
   Collided with: report.docx → report.docx.md
   Folder: dept/finance/

⚠ COLLISION (renamed)
   budget.xlsx    → budget.xlsx.md
   Collided with: budget.csv  → budget.csv.md
   Folder: dept/finance/

✗ PATH TOO LONG (skipped)
   /very/deeply/nested/.../quarterly_summary_final_v3_reviewed.docx
   Path length: 268 chars (max: 240)

──────────────────────────────────────────────────────
[Download Full Report (CSV)]
```

### `static/settings.html` (modify)

Add path safety settings to the **Conversion** section:

```
Path Safety
──────────────────────────────────────────────────────
Max output path length    [240] chars
                          Paths longer than this are skipped during bulk jobs.
                          Linux limit: 255 · Windows limit: 260

Duplicate filename strategy   [Rename (add extension) ▾]
  Rename (add extension)   report.docx.md + report.pdf.md — no data loss (recommended)
  Skip second file         Keep first, skip duplicates — some files not converted
  Error (skip all)         Flag all colliding files — manual fix required

Add anchor: id="collision-strategy" on this section for deep-linking from bulk UI.
```

---

## 9. Tests

### `tests/test_path_utils.py` (new)

**`map_output_path()`:**
- [ ] Simple path maps correctly
- [ ] Deeply nested path (10+ levels) maps correctly
- [ ] Path with spaces and special characters maps correctly
- [ ] Raises `ValueError` if source_file not under source_root

**`map_output_path_renamed()`:**
- [ ] `report.pdf` → `report.pdf.md`
- [ ] `report.docx` → `report.docx.md`
- [ ] Nested path preserves directory structure

**`check_path_length()`:**
- [ ] Path of 239 chars returns True (within limit)
- [ ] Path of 240 chars returns True (at limit)
- [ ] Path of 241 chars returns False (over limit)

**`detect_collisions()`:**
- [ ] Two files with same stem, different extension → collision detected
- [ ] Two files with different stems → no collision
- [ ] Three files all mapping to same output → all three in collision group
- [ ] Files in different directories with same name → no collision (different output paths)

**`detect_case_collisions()`:**
- [ ] `Report.docx` and `report.docx` → case collision detected
- [ ] `Report.docx` and `Report.pdf` → standard collision, not case collision
- [ ] `dept/Report.docx` and `DEPT/report.docx` → case collision (directory AND filename differ)

**`resolve_collision()`:**
- [ ] Strategy `rename`: all files get renamed paths, none are None
- [ ] Strategy `skip`: first file (sorted) gets canonical path, rest get None
- [ ] Strategy `error`: all files get None
- [ ] Deterministic: same input always produces same output (sort order stable)

### `tests/test_bulk_path_safety.py` (new)

- [ ] Scanner detects path_too_long files and records in `bulk_path_issues`
- [ ] Scanner detects collisions and records them with correct collision_peer
- [ ] Scanner detects case collisions
- [ ] `bulk_jobs` counters updated correctly after path safety pass
- [ ] Worker uses resolved_paths — does not call `_map_output_path()` directly
- [ ] `path_too_long` file: `bulk_files.status = 'skipped'`, correct error_msg
- [ ] `collision` + strategy `rename`: output_path updated to renamed path
- [ ] `collision` + strategy `skip`: non-kept files have status `skipped`
- [ ] `collision` + strategy `error`: all collision files have status `failed`
- [ ] `GET /api/bulk/jobs/{id}/path-issues` returns correct grouped issues
- [ ] CSV export contains all issues with correct columns
- [ ] Manifest includes `path_issues` section when issues exist
- [ ] Manifest has `path_issues: null` when no issues exist

---

## 10. Done Criteria

- [ ] `core/path_utils.py` exists with all functions implemented and tested
- [ ] Scanner runs path safety pass after file discovery, before queuing
- [ ] Path length overflow files are skipped with clear error_msg in bulk_files
- [ ] Same-stem/different-extension collisions detected and resolved per strategy
- [ ] Case collisions detected and resolved per strategy
- [ ] Worker uses `resolved_paths` from scanner — no direct `_map_output_path()` calls
- [ ] `bulk_path_issues` table populated correctly during scan
- [ ] `GET /api/bulk/jobs/{id}/path-issues` returns full issue list
- [ ] CSV export of path issues works
- [ ] Manifest includes path issues section
- [ ] Bulk UI shows amber/red alert during scan when issues found
- [ ] Bulk UI completion summary shows path issues section
- [ ] Settings page exposes max path length and collision strategy
- [ ] All prior tests still passing
- [ ] New tests: 30+ covering path_utils and bulk path safety

---

## 11. CLAUDE.md Update

After done criteria pass:

```markdown
**v0.7.4b** — Path safety and collision handling. Deeply nested paths checked
  against configurable max length (default 240 chars). Output path collisions
  (same stem, different extension) detected at scan time and resolved per
  strategy: rename (default, no data loss), skip, or error. Case-sensitivity
  collisions detected separately. All issues recorded in bulk_path_issues table,
  reported in manifest, downloadable as CSV.
```

Add to Gotchas:
```markdown
- **Path safety pass runs during scan, not during conversion**: All path length
  and collision checks happen in BulkScanner._run_path_safety_pass() before any
  file is queued for conversion. The worker trusts resolved_paths — it does not
  re-check. If a file appears in the worker without a resolved_paths entry, that
  is a bug, not a handled edge case.

- **resolve_collision() is deterministic**: Sort order is by str(source_path)
  ascending. For strategy='skip', the alphabetically-first source path always
  wins. This is intentional — predictable behavior matters more than any
  particular ordering preference.

- **Case collision detection only flags same-output-path pairs**: Two files
  that differ only by case in the directory portion (DEPT vs dept) AND produce
  the same lowercased output path are flagged. Files that differ by case but
  produce different output paths are NOT flagged (the Linux container handles
  them correctly as separate files).

- **`path_too_long` files are silently skipped in the worker**: Their
  bulk_files.status is set to 'skipped' during the scan phase. The worker
  checks resolved_paths and finds None — it continues without logging an
  error (the scan already logged the issue). Do not add error-level logs
  in the worker for these files.

- **Renamed output paths use source extension**: report.pdf.md not
  report_pdf.md or report(1).md. The double extension is intentional —
  it makes the source format visible in the filename and is unambiguous.
```

Tag: `git tag v0.7.4b && git push origin v0.7.4b`

---

## 12. Output Cap Note

Fits in 3 turns:

1. **Turn 1**: `core/path_utils.py` + full test suite (`test_path_utils.py`),
   DB schema changes + helpers, scanner path safety pass, `ScanResult` extension
2. **Turn 2**: Worker `resolved_paths` integration, SSE events, all bulk API
   changes (`path-issues` endpoint, CSV export), manifest extension,
   `tests/test_bulk_path_safety.py`
3. **Turn 3**: `bulk.html` path issues alert + detail panel, `settings.html`
   path safety section, CLAUDE.md update, tag
