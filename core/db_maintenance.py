"""
Database health and maintenance operations.

Provides: compaction (incremental vacuum + WAL checkpoint), integrity checks,
foreign key checks, stale data detection, and health summary.
"""

import time

import structlog

from core.database import DB_PATH, get_db, log_maintenance, db_fetch_all, db_fetch_one

log = structlog.get_logger(__name__)


async def run_compaction() -> None:
    """Incremental vacuum + WAL checkpoint. Full VACUUM if freelist > 25%."""
    t0 = time.perf_counter()
    details: dict = {}

    try:
        async with get_db() as conn:
            # Incremental vacuum — reclaim up to 100 pages
            await conn.execute("PRAGMA incremental_vacuum(100)")

            # WAL checkpoint
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            # Check if full VACUUM is needed
            row = await conn.execute("PRAGMA page_count")
            page_count = (await row.fetchone())[0]
            row2 = await conn.execute("PRAGMA freelist_count")
            freelist_count = (await row2.fetchone())[0]

            details["page_count"] = page_count
            details["freelist_count"] = freelist_count

            if page_count > 0 and (freelist_count / page_count) > 0.25:
                await conn.execute("VACUUM")
                details["full_vacuum"] = True
                log.info("db_maintenance.full_vacuum", freelist_ratio=freelist_count / page_count)
            else:
                details["full_vacuum"] = False

            await conn.commit()

        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("compaction", "ok", details, duration_ms)
        log.info("db_maintenance.compaction_complete", duration_ms=duration_ms, **details)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("compaction", "error", {"error": str(exc)}, duration_ms)
        log.error("db_maintenance.compaction_failed", error=str(exc))


async def run_integrity_check() -> dict:
    """Run PRAGMA integrity_check. Returns {result, findings}."""
    t0 = time.perf_counter()

    try:
        async with get_db() as conn:
            cursor = await conn.execute("PRAGMA integrity_check")
            rows = await cursor.fetchall()

        findings = [row[0] for row in rows]
        is_ok = len(findings) == 1 and findings[0] == "ok"
        result = "ok" if is_ok else "error"

        duration_ms = int((time.perf_counter() - t0) * 1000)
        details = {"findings": findings}
        await log_maintenance("integrity_check", result, details, duration_ms)

        if not is_ok:
            log.error("db_maintenance.integrity_check_failed", findings=findings)
        else:
            log.info("db_maintenance.integrity_check_ok", duration_ms=duration_ms)

        return {"result": result, "findings": findings}
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("integrity_check", "error", {"error": str(exc)}, duration_ms)
        return {"result": "error", "findings": [str(exc)]}


async def run_foreign_key_check() -> dict:
    """Run PRAGMA foreign_key_check."""
    t0 = time.perf_counter()

    try:
        async with get_db() as conn:
            cursor = await conn.execute("PRAGMA foreign_key_check")
            rows = await cursor.fetchall()

        violations = [{"table": r[0], "rowid": r[1], "parent": r[2], "fkid": r[3]} for r in rows]
        result = "ok" if not violations else "warning"

        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("foreign_key_check", result, {"violations": violations}, duration_ms)

        return {"result": result, "violations": violations}
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("foreign_key_check", "error", {"error": str(exc)}, duration_ms)
        return {"result": "error", "violations": [str(exc)]}


async def run_stale_data_check() -> dict:
    """Run 6 stale data checks. Returns summary dict."""
    t0 = time.perf_counter()
    checks: dict = {}

    # 1. Orphaned versions
    try:
        rows = await db_fetch_all(
            """SELECT COUNT(*) as cnt FROM file_versions
               WHERE bulk_file_id NOT IN (SELECT id FROM bulk_files)"""
        )
        count = rows[0]["cnt"] if rows else 0
        checks["orphaned_versions"] = {"count": count, "severity": "warning" if count else "ok"}
    except Exception as exc:
        checks["orphaned_versions"] = {"count": 0, "severity": "error", "error": str(exc)}

    # 2. Missing .md files (active + success but output doesn't exist)
    try:
        rows = await db_fetch_all(
            """SELECT id, output_path FROM bulk_files
               WHERE lifecycle_status='active' AND status='converted'
               AND output_path IS NOT NULL"""
        )
        from pathlib import Path
        missing = sum(1 for r in rows if r.get("output_path") and not Path(r["output_path"]).exists())
        checks["missing_md_files"] = {"count": missing, "severity": "warning" if missing else "ok"}
    except Exception as exc:
        checks["missing_md_files"] = {"count": 0, "severity": "error", "error": str(exc)}

    # 3. Stale Meilisearch entries
    try:
        from core.search_client import MeilisearchClient
        client = MeilisearchClient()
        if await client.health_check():
            result = await client.search(index="documents", query="", limit=1000)
            meili_ids = {hit.get("id") for hit in result.get("hits", [])}
            if meili_ids:
                # Check which IDs don't correspond to active bulk_files
                import hashlib
                active_rows = await db_fetch_all(
                    "SELECT source_path FROM bulk_files WHERE lifecycle_status='active'"
                )
                active_ids = {hashlib.sha256(r["source_path"].encode()).hexdigest()[:16] for r in active_rows}
                stale = meili_ids - active_ids
                checks["stale_meilisearch"] = {"count": len(stale), "severity": "warning" if stale else "ok"}
            else:
                checks["stale_meilisearch"] = {"count": 0, "severity": "ok"}
        else:
            checks["stale_meilisearch"] = {"count": 0, "severity": "ok", "note": "Meilisearch unavailable"}
    except Exception as exc:
        checks["stale_meilisearch"] = {"count": 0, "severity": "ok", "note": f"Meilisearch check skipped: {exc}"}

    # 4. Dangling trash entries
    try:
        from core.lifecycle_manager import get_trash_path, OUTPUT_REPO_ROOT
        from pathlib import Path
        rows = await db_fetch_all(
            "SELECT id, output_path FROM bulk_files WHERE lifecycle_status='in_trash'"
        )
        dangling = 0
        for r in rows:
            if r.get("output_path"):
                trash_path = get_trash_path(OUTPUT_REPO_ROOT, Path(r["output_path"]))
                if not trash_path.exists():
                    dangling += 1
        checks["dangling_trash"] = {"count": dangling, "severity": "warning" if dangling else "ok"}
    except Exception as exc:
        checks["dangling_trash"] = {"count": 0, "severity": "error", "error": str(exc)}

    # 5. Expired trash not purged
    try:
        from core.database import get_bulk_files_pending_purge
        expired = await get_bulk_files_pending_purge(trash_retention_days=60)
        count = len(expired)
        checks["expired_trash"] = {"count": count, "severity": "error" if count else "ok"}
    except Exception as exc:
        checks["expired_trash"] = {"count": 0, "severity": "error", "error": str(exc)}

    # 6. Expired grace not trashed
    try:
        from core.database import get_bulk_files_pending_trash
        expired = await get_bulk_files_pending_trash(grace_period_hours=36)
        count = len(expired)
        checks["expired_grace"] = {"count": count, "severity": "error" if count else "ok"}
    except Exception as exc:
        checks["expired_grace"] = {"count": 0, "severity": "error", "error": str(exc)}

    duration_ms = int((time.perf_counter() - t0) * 1000)
    await log_maintenance("stale_purge", "ok", checks, duration_ms)
    log.info("db_maintenance.stale_check_complete", duration_ms=duration_ms, checks=checks)

    return checks


async def run_wal_checkpoint() -> None:
    """Force WAL checkpoint."""
    t0 = time.perf_counter()
    try:
        async with get_db() as conn:
            await conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("wal_checkpoint", "ok", None, duration_ms)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        await log_maintenance("wal_checkpoint", "error", {"error": str(exc)}, duration_ms)


async def get_health_summary() -> dict:
    """Return comprehensive DB health summary."""
    summary: dict = {}

    # DB file stats
    try:
        if DB_PATH.exists():
            summary["db_size_bytes"] = DB_PATH.stat().st_size
        else:
            summary["db_size_bytes"] = 0
    except OSError:
        summary["db_size_bytes"] = 0

    # SQLite page/freelist stats
    try:
        async with get_db() as conn:
            cursor = await conn.execute("PRAGMA page_count")
            summary["page_count"] = (await cursor.fetchone())[0]
            cursor = await conn.execute("PRAGMA freelist_count")
            summary["freelist_count"] = (await cursor.fetchone())[0]
            cursor = await conn.execute("PRAGMA journal_mode")
            summary["journal_mode"] = (await cursor.fetchone())[0]
    except Exception:
        summary["page_count"] = 0
        summary["freelist_count"] = 0
        summary["journal_mode"] = "unknown"

    # Last maintenance timestamps
    try:
        from core.database import get_maintenance_log
        logs = await get_maintenance_log(limit=50)

        last_compaction = None
        last_integrity = None
        last_integrity_result = None
        last_stale = None

        for entry in logs:
            op = entry.get("operation")
            if op == "compaction" and not last_compaction:
                last_compaction = entry.get("run_at")
            elif op == "integrity_check" and not last_integrity:
                last_integrity = entry.get("run_at")
                last_integrity_result = entry.get("result")
            elif op == "stale_purge" and not last_stale:
                last_stale = entry.get("run_at")

        summary["last_compaction"] = last_compaction
        summary["last_integrity_check"] = last_integrity
        summary["last_integrity_result"] = last_integrity_result
        summary["last_stale_check"] = last_stale
    except Exception:
        summary["last_compaction"] = None
        summary["last_integrity_check"] = None
        summary["last_integrity_result"] = None
        summary["last_stale_check"] = None

    return summary
