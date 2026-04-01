# MarkFlow Streamlining Audit -- v0.16.0

**Date:** 2026-04-01
**Scope:** Full codebase (core/, api/, formats/, static/)
**Status:** 21 of 24 items RESOLVED in v0.16.1 (2026-04-01). Remaining: STR-05, STR-13 (partial), STR-17.

---

## Summary

| Impact | Count |
|--------|-------|
| HIGH   | 5 |
| MEDIUM | 12 |
| LOW    | 7 |
| **Total** | **24** |

---

## HIGH Impact

### STR-01: Three Identical ODF Helper Implementations -- RESOLVED
- **Files:** formats/odt_handler.py:160-190, formats/ods_handler.py:112-137, formats/odp_handler.py:126-148
- **Category:** Duplicated code
- **Description:** `_extract_fonts(doc)` and `_get_text(node)` are near-identical across all three ODF handlers. Only odt_handler adds fontfamily extraction. Should be extracted into shared `formats/odf_utils.py`.

### STR-02: ALLOWED_EXTENSIONS vs SUPPORTED_EXTENSIONS Maintained Separately -- RESOLVED
- **Files:** core/converter.py:56-77, core/bulk_scanner.py:33-61
- **Category:** Duplicated code
- **Description:** Both sets cover supported formats but are defined independently. converter.py is missing formats that bulk_scanner.py supports (.docm, .wpd, .ait, .indt, .tgz, images). New formats added to scanner silently fail on single-file upload. Should derive from handler registry.

### STR-03: _db_write_with_retry Only Available in bulk_worker.py -- RESOLVED
- **File:** core/bulk_worker.py:48-63
- **Category:** Missing shared utility
- **Description:** Exponential backoff on "database is locked" is only available as a private function in bulk_worker. Lifecycle scanner, scheduler, and other concurrent writers have no retry. Should live in core/database.py and be exported.

### STR-04: SearchIndexer() Instantiated Directly Instead of Using Singleton -- RESOLVED
- **File:** core/flag_manager.py:68,345
- **Category:** Inconsistent patterns
- **Description:** Every other module uses `get_search_indexer()` singleton accessor. flag_manager.py calls `SearchIndexer()` directly in two places, creating new HTTP client objects on every flag operation.

### STR-05: database.py Is 1,800+ Lines Covering 10+ Domains -- DEFERRED (own session)
- **File:** core/database.py
- **Category:** Large file that should be split
- **Description:** Single monolithic module handles schema DDL, migrations, preferences, bulk jobs, source files, Adobe indexing, locations, LLM providers, path issues, archive members, and flagging. Has internal logger inconsistency (_log vs log). Should be split into domain-specific modules (db/schema.py, db/bulk_jobs.py, db/source_files.py, etc.).

---

## MEDIUM Impact

### STR-06: _now_iso() Defined Four Times -- RESOLVED
- **Files:** core/database.py:1031, core/lifecycle_scanner.py:876, core/metadata.py:132, api/routes/bulk.py:702
- **Category:** Duplicated code
- **Description:** All four are identical: `datetime.now(timezone.utc).isoformat()`. bulk.py version wastefully imports datetime inside function body. Should consolidate to one location (database.py already has it).

### STR-07: media_exts Set Defined Inline in bulk_worker.py -- RESOLVED
- **File:** core/bulk_worker.py:734-735
- **Category:** Duplicated code
- **Description:** Audio/video extension set hardcoded inline rather than referencing AudioHandler.EXTENSIONS / MediaHandler.EXTENSIONS. Adding a new media format to handlers but not here silently skips Meilisearch transcript indexing.

### STR-08: _verify_source_mount Duplicated Between Scanners -- RESOLVED
- **Files:** core/bulk_scanner.py:109-122, core/lifecycle_scanner.py:119-132
- **Category:** Duplicated code
- **Description:** Both implement the same is_dir() + os.scandir() + next(it) check. bulk_scanner extracts it into a function but lifecycle_scanner repeats inline. Should share one implementation.

### STR-09: asyncio Imported Inside Function Bodies 4 Times in lifecycle_scanner.py -- RESOLVED
- **File:** core/lifecycle_scanner.py:159,192,511,796
- **Category:** Inconsistent patterns
- **Description:** Uses different aliases each time (_aio, _asyncio, asyncio). Should be a single top-level import.

### STR-10: Deferred get_preference Imports in Every Scheduler Function -- RESOLVED
- **File:** core/scheduler.py:42,65,83,189,292
- **Category:** Inconsistent patterns
- **Description:** `from core.database import get_preference` repeated inside every scheduler function's try block. No circular import risk exists. Should be module-level.

### STR-11: record_activity_event Import-Guarded in 6 Files -- RESOLVED
- **Files:** core/bulk_worker.py, core/lifecycle_scanner.py, core/scheduler.py, core/bulk_scanner.py, core/search_indexer.py, main.py
- **Category:** Inconsistent patterns
- **Description:** Each wraps the import in try/except even though metrics_collector is a first-party module that is always present. Import should be top-level; only the await call needs try/except.

### STR-12: get_search_indexer() Fetched Twice Per Conversion in bulk_worker.py -- RESOLVED
- **File:** core/bulk_worker.py:726-740
- **Category:** Redundant operations
- **Description:** Two separate try blocks each re-import and call get_search_indexer() -- once for document indexing, once for transcript indexing. Should consolidate.

### STR-13: upsert_source_file Uses SELECT-then-INSERT/UPDATE Instead of SQLite UPSERT -- PARTIAL (adobe_index converted; source_file deferred due to dynamic fields)
- **File:** core/database.py:1098-1152
- **Category:** Inefficient patterns
- **Description:** Two DB round-trips where one would suffice. SQLite supports INSERT ... ON CONFLICT DO UPDATE. Compare with set_preference() at line 850 which already uses the correct pattern. Hot path during scanning.

### STR-14: upsert_adobe_index Has Same SELECT-then-INSERT Pattern -- RESOLVED
- **File:** core/database.py:1276-1314
- **Category:** Inefficient patterns
- **Description:** Same as STR-13. Hot path during Adobe indexing runs.

### STR-15: Repeated Optional-Filter Query Pattern in database.py (6 Functions) -- RESOLVED
- **File:** core/database.py (get_bulk_files, get_review_queue, get_bulk_file_count, get_review_queue_count, get_flags_for_batch, etc.)
- **Category:** Verbose/boilerplate code
- **Description:** Each function has if/else branching to add an optional WHERE clause. flag_manager.py already uses the cleaner `conditions` list pattern. Should standardize.

### STR-16: formatDate and formatLocalTime Overlap in app.js -- RESOLVED
- **File:** static/app.js:112-140
- **Category:** Redundant operations
- **Description:** formatDate() is legacy, formatLocalTime() is the standard per CLAUDE.md. formatDate should be removed or made to call formatLocalTime(). Callers should be audited.

### STR-17: init_db() Has 40+ _add_column_if_missing Calls -- DEFERRED (own session)
- **File:** core/database.py:683-761
- **Category:** Overly complex function
- **Description:** Each call does PRAGMA table_info() plus conditional ALTER TABLE. A schema_migrations table would let startup skip already-applied migrations. Will degrade as versions accumulate.

---

## LOW Impact

### STR-18: import os Inside _fire_webhook Function Body -- RESOLVED
- **File:** core/flag_manager.py:98
- **Category:** Dead code / Verbose
- **Description:** os imported solely for os.path.basename(). File already has pathlib available. Use Path(source_path).name instead.

### STR-19: Unused aiosqlite Import in auto_converter.py -- RESOLVED
- **File:** core/auto_converter.py:13
- **Category:** Dead code
- **Description:** aiosqlite imported at module level but never used directly. Module uses get_db() from core.database.

### STR-20: logger vs log Naming Inconsistency -- RESOLVED
- **Files:** core/auto_converter.py:19, core/auto_metrics_aggregator.py:14
- **Category:** Inconsistent patterns
- **Description:** These two files use `logger` while all 40+ other modules use `log`. Project standard is `log`.

### STR-21: cleanup_orphaned_jobs Creates Its Own Logger -- RESOLVED
- **File:** core/database.py:780
- **Category:** Inconsistent patterns
- **Description:** Creates `_log = structlog.get_logger(__name__)` inside function body when module-level `log` is identical and available.

### STR-22: is_file_flagged() and _sync_is_flagged() Run Same Query -- RESOLVED
- **File:** core/flag_manager.py:43-49,522-529
- **Category:** Duplicated code
- **Description:** Both run identical SELECT COUNT(*) query on file_flags. _sync_is_flagged should call is_file_flagged() when force_value is None.

### STR-23: GROUP BY Status Pattern Repeated 3 Times -- RESOLVED
- **Files:** core/database.py:1016-1026,1492-1501, core/flag_manager.py:472-480
- **Category:** Redundant operations
- **Description:** Identical boilerplate to count rows by status and produce a dict with a total key. Could be a shared helper.

### STR-24: API Error Extraction Duplicated 4 Times in app.js -- RESOLVED
- **File:** static/app.js:6-71
- **Category:** Duplicated code
- **Description:** API.post, API.put, API.del, API.upload each repeat the same 4-line error extraction block. API.del also adds err.data which others do not -- an inconsistency that could cause subtle bugs.
