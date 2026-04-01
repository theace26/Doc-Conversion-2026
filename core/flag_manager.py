"""
Business logic for file flagging and content moderation.

Provides CRUD for flags, admin actions (dismiss/extend/remove+blocklist),
blocklist queries, Meilisearch sync, webhook dispatch, and auto-expiry.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import structlog

from core.database import db_execute, db_fetch_all, db_fetch_one, get_db, get_preference

log = structlog.get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

VALID_REASONS = {"pii", "confidential", "unauthorized", "other"}
ACTIVE_STATUSES = ("active", "extended")

_MEILI_INDEXES = ("documents", "adobe-files", "transcripts")

_ALLOWED_SORT_COLUMNS = {
    "expires_at", "created_at", "reason", "flagged_by_email", "resolved_at",
}


# ── Meilisearch sync ────────────────────────────────────────────────────────

async def _sync_is_flagged(
    source_file_id: str, force_value: bool | None = None
) -> None:
    """Update the ``is_flagged`` field in all Meilisearch indexes.

    If *force_value* is None the current DB state is queried to determine
    whether any active/extended flag exists for the file.
    """
    # Lazy imports to avoid circular dependency with search_indexer
    from core.search_indexer import get_search_indexer, _doc_id

    if force_value is None:
        force_value = await is_file_flagged(source_file_id)

    sf = await db_fetch_one(
        "SELECT source_path, output_path FROM source_files WHERE id = ?",
        (source_file_id,),
    )
    if not sf:
        return

    # Build doc IDs from both paths (file may be indexed under either)
    doc_ids: set[str] = set()
    if sf["source_path"]:
        doc_ids.add(_doc_id(sf["source_path"]))
    if sf["output_path"]:
        doc_ids.add(_doc_id(sf["output_path"]))

    if not doc_ids:
        return

    indexer = get_search_indexer()
    if not indexer:
        return
    for index_name in _MEILI_INDEXES:
        for did in doc_ids:
            try:
                await indexer.client.add_documents(
                    index_name, [{"id": did, "is_flagged": force_value}]
                )
            except Exception:
                pass  # document may not exist in this index


# ── Webhook ──────────────────────────────────────────────────────────────────

async def _fire_webhook(
    event: str,
    flag: dict,
    actor_email: str,
    actor_role: str = "",
) -> None:
    """POST a flag event to the configured webhook URL (fire-and-forget)."""
    url = await get_preference("flag_webhook_url")
    if not url:
        return

    # Look up source info
    sf = await db_fetch_one(
        "SELECT source_path FROM source_files WHERE id = ?",
        (flag.get("source_file_id"),),
    )
    source_path = sf["source_path"] if sf else ""
    source_filename = Path(source_path).name if source_path else ""

    payload = {
        "event": event,
        "flag_id": flag.get("id"),
        "file": {
            "source_file_id": flag.get("source_file_id"),
            "source_path": source_path,
            "source_filename": source_filename,
        },
        "actor": {
            "email": actor_email,
            "role": actor_role,
        },
        "reason": flag.get("reason"),
        "note": flag.get("note", ""),
        "status": flag.get("status"),
        "expires_at": flag.get("expires_at"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(url, json=payload)
            log.info(
                "webhook_delivered",
                event=event,
                flag_id=flag.get("id"),
                status_code=resp.status_code,
            )
    except Exception as exc:
        log.warning(
            "webhook_delivery_failed",
            event=event,
            flag_id=flag.get("id"),
            error=str(exc),
        )


# ── Flag CRUD ────────────────────────────────────────────────────────────────

async def create_flag(
    source_file_id: str,
    reason: str,
    flagged_by_sub: str,
    flagged_by_email: str,
    note: str = "",
    role: str = "",
) -> dict:
    """Create a new flag on a source file.

    Returns the created flag as a dict.
    Raises ValueError for invalid reason or missing source file.
    """
    if reason not in VALID_REASONS:
        raise ValueError(f"Invalid reason '{reason}'. Must be one of: {VALID_REASONS}")

    sf = await db_fetch_one(
        "SELECT id FROM source_files WHERE id = ?", (source_file_id,)
    )
    if not sf:
        raise ValueError(f"source_file_id {source_file_id} does not exist")

    expiry_pref = await get_preference("flag_default_expiry_days")
    expiry_days = int(expiry_pref) if expiry_pref else 14

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=expiry_days)).isoformat()
    flag_id = uuid.uuid4().hex

    await db_execute(
        """INSERT INTO file_flags
           (id, source_file_id, flagged_by_sub, flagged_by_email,
            reason, note, status, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
        (flag_id, source_file_id, flagged_by_sub, flagged_by_email,
         reason, note, expires_at, now.isoformat()),
    )

    flag = await get_flag(flag_id)

    await _sync_is_flagged(source_file_id, force_value=True)
    log.info(
        "file_flagged",
        flag_id=flag_id,
        source_file_id=source_file_id,
        reason=reason,
        flagged_by=flagged_by_email,
    )
    await _fire_webhook("flag_created", flag, flagged_by_email, role)

    return flag


async def get_flag(flag_id: str) -> dict | None:
    """Return a single flag by ID, or None."""
    return await db_fetch_one("SELECT * FROM file_flags WHERE id = ?", (flag_id,))


async def get_my_flags(flagged_by_sub: str) -> list[dict]:
    """Return active/extended flags created by a specific user."""
    return await db_fetch_all(
        """SELECT f.*, sf.source_path, sf.content_hash
           FROM file_flags f
           JOIN source_files sf ON sf.id = f.source_file_id
           WHERE f.flagged_by_sub = ?
             AND f.status IN ('active', 'extended')
           ORDER BY f.created_at DESC""",
        (flagged_by_sub,),
    )


async def retract_flag(flag_id: str, user_sub: str) -> dict:
    """Retract a flag (owner only).

    Raises ValueError if flag not found or not active.
    Raises PermissionError if user is not the flag creator.
    """
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError(f"Flag {flag_id} not found")
    if flag["flagged_by_sub"] != user_sub:
        raise PermissionError("Only the flag creator can retract it")
    if flag["status"] != "active":
        raise ValueError(f"Flag {flag_id} is '{flag['status']}', not active")

    now = datetime.now(timezone.utc).isoformat()
    await db_execute(
        "UPDATE file_flags SET status = 'retracted', resolved_at = ? WHERE id = ?",
        (now, flag_id),
    )

    await _sync_is_flagged(flag["source_file_id"])
    log.info("flag_retracted", flag_id=flag_id, user_sub=user_sub)

    updated = await get_flag(flag_id)
    await _fire_webhook("flag_retracted", updated, flag["flagged_by_email"])
    return updated


# ── Admin actions ────────────────────────────────────────────────────────────

async def dismiss_flag(
    flag_id: str, admin_email: str, resolution_note: str = ""
) -> dict:
    """Dismiss a flag (admin action)."""
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError(f"Flag {flag_id} not found")

    now = datetime.now(timezone.utc).isoformat()
    await db_execute(
        """UPDATE file_flags
           SET status = 'dismissed', resolved_at = ?, resolved_by_email = ?,
               resolution_note = ?
           WHERE id = ?""",
        (now, admin_email, resolution_note, flag_id),
    )

    await _sync_is_flagged(flag["source_file_id"])
    log.info("flag_dismissed", flag_id=flag_id, admin=admin_email)

    updated = await get_flag(flag_id)
    await _fire_webhook("flag_dismissed", updated, admin_email)
    return updated


async def extend_flag(
    flag_id: str, days: int, admin_email: str, resolution_note: str = ""
) -> dict:
    """Extend a flag's expiry (admin action).

    If *days* <= 0 the flag is set to indefinite (9999-12-31T23:59:59).
    """
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError(f"Flag {flag_id} not found")

    if days <= 0:
        expires_at = "9999-12-31T23:59:59"
    else:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    now = datetime.now(timezone.utc).isoformat()
    await db_execute(
        """UPDATE file_flags
           SET status = 'extended', expires_at = ?, resolved_at = ?,
               resolved_by_email = ?, resolution_note = ?
           WHERE id = ?""",
        (expires_at, now, admin_email, resolution_note, flag_id),
    )

    await _sync_is_flagged(flag["source_file_id"], force_value=True)
    log.info("flag_extended", flag_id=flag_id, days=days, admin=admin_email)

    updated = await get_flag(flag_id)
    await _fire_webhook("flag_extended", updated, admin_email, "admin")
    return updated


async def remove_and_blocklist(
    flag_id: str, admin_email: str, resolution_note: str = ""
) -> dict:
    """Remove a flagged file and add it to the blocklist (admin action)."""
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError(f"Flag {flag_id} not found")

    sf = await db_fetch_one(
        "SELECT source_path, content_hash FROM source_files WHERE id = ?",
        (flag["source_file_id"],),
    )
    content_hash = sf["content_hash"] if sf else None
    source_path = sf["source_path"] if sf else None

    now = datetime.now(timezone.utc).isoformat()
    blocklist_id = uuid.uuid4().hex

    async with get_db() as conn:
        await conn.execute(
            """UPDATE file_flags
               SET status = 'removed', resolved_at = ?, resolved_by_email = ?,
                   resolution_note = ?
               WHERE id = ?""",
            (now, admin_email, resolution_note, flag_id),
        )
        await conn.execute(
            """INSERT INTO blocklisted_files
               (id, content_hash, source_path, reason, added_by_email,
                flag_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (blocklist_id, content_hash, source_path,
             flag.get("reason", ""), admin_email, flag_id, now),
        )
        await conn.commit()

    # Delete from all Meilisearch indexes
    from core.search_indexer import get_search_indexer, _doc_id

    doc_ids: set[str] = set()
    if source_path:
        doc_ids.add(_doc_id(source_path))
    output_path = sf.get("output_path") if sf else None
    if output_path:
        doc_ids.add(_doc_id(output_path))

    indexer = get_search_indexer()
    if not indexer:
        log.warning("flag_manager.no_indexer", msg="SearchIndexer not available, skipping Meilisearch delete")
    for index_name in (_MEILI_INDEXES if indexer else []):
        for did in doc_ids:
            try:
                await indexer.client.delete_document(index_name, did)
            except Exception:
                pass

    log.info(
        "file_removed_and_blocklisted",
        flag_id=flag_id,
        blocklist_id=blocklist_id,
        source_path=source_path,
        admin=admin_email,
    )

    updated = await get_flag(flag_id)
    await _fire_webhook("file_removed_and_blocklisted", updated, admin_email)
    return updated


# ── Blocklist queries ────────────────────────────────────────────────────────

async def is_blocklisted(source_path: str, content_hash: str | None = None) -> bool:
    """Check whether a file is on the blocklist (by path or content hash)."""
    if content_hash:
        row = await db_fetch_one(
            "SELECT 1 FROM blocklisted_files WHERE content_hash = ? OR source_path = ?",
            (content_hash, source_path),
        )
    else:
        row = await db_fetch_one(
            "SELECT 1 FROM blocklisted_files WHERE source_path = ?",
            (source_path,),
        )
    return row is not None


async def get_blocklist(page: int = 1, per_page: int = 25) -> dict:
    """Return a paginated blocklist."""
    offset = (page - 1) * per_page

    total_row = await db_fetch_one("SELECT COUNT(*) AS cnt FROM blocklisted_files")
    total = total_row["cnt"] if total_row else 0

    items = await db_fetch_all(
        "SELECT * FROM blocklisted_files ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


async def remove_from_blocklist(blocklist_id: str) -> bool:
    """Remove an entry from the blocklist. Returns True if a row was deleted."""
    async with get_db() as conn:
        async with conn.execute(
            "DELETE FROM blocklisted_files WHERE id = ?", (blocklist_id,)
        ) as cursor:
            await conn.commit()
            return cursor.rowcount > 0


# ── Admin queries ────────────────────────────────────────────────────────────

async def list_flags(
    status: str | None = None,
    flagged_by: str | None = None,
    reason: str | None = None,
    path_prefix: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "created_at",
    sort_dir: str = "DESC",
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """Return a filtered, paginated list of flags with source file info."""
    conditions: list[str] = []
    params: list = []

    if status:
        conditions.append("f.status = ?")
        params.append(status)
    if flagged_by:
        conditions.append("f.flagged_by_email = ?")
        params.append(flagged_by)
    if reason:
        conditions.append("f.reason = ?")
        params.append(reason)
    if path_prefix:
        conditions.append("sf.source_path LIKE ?")
        params.append(f"{path_prefix}%")
    if date_from:
        conditions.append("f.created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("f.created_at <= ?")
        params.append(date_to)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    # Validate sort column
    if sort_by not in _ALLOWED_SORT_COLUMNS:
        sort_by = "created_at"
    sort_dir = "ASC" if sort_dir.upper() == "ASC" else "DESC"

    base_from = """
        FROM file_flags f
        JOIN source_files sf ON sf.id = f.source_file_id
    """

    total_row = await db_fetch_one(
        f"SELECT COUNT(*) AS cnt {base_from} {where}", tuple(params)
    )
    total = total_row["cnt"] if total_row else 0

    offset = (page - 1) * per_page
    items = await db_fetch_all(
        f"""SELECT f.*, sf.source_path, sf.content_hash
            {base_from} {where}
            ORDER BY f.{sort_by} {sort_dir}
            LIMIT ? OFFSET ?""",
        tuple(params) + (per_page, offset),
    )
    return {"items": items, "total": total, "page": page, "per_page": per_page}


async def get_flag_stats() -> dict:
    """Return flag counts grouped by status."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) AS cnt FROM file_flags GROUP BY status"
    )
    stats = {s: 0 for s in ("active", "extended", "dismissed", "expired", "removed", "retracted")}
    for r in rows:
        stats[r["status"]] = r["cnt"]
    return stats


# ── Auto-expiry ──────────────────────────────────────────────────────────────

async def expire_flags() -> int:
    """Expire all flags past their expiry date. Returns the count expired."""
    now = datetime.now(timezone.utc).isoformat()

    # Find flags to expire
    rows = await db_fetch_all(
        """SELECT id, source_file_id FROM file_flags
           WHERE status IN ('active', 'extended')
             AND expires_at < ?""",
        (now,),
    )

    if not rows:
        return 0

    flag_ids = [r["id"] for r in rows]
    source_file_ids = {r["source_file_id"] for r in rows}

    # Batch update
    placeholders = ",".join("?" for _ in flag_ids)
    await db_execute(
        f"UPDATE file_flags SET status = 'expired' WHERE id IN ({placeholders})",
        tuple(flag_ids),
    )

    # Sync Meilisearch for each unique source file
    for sfid in source_file_ids:
        await _sync_is_flagged(sfid)

    for r in rows:
        log.info("flag_expired", flag_id=r["id"], source_file_id=r["source_file_id"])

    return len(rows)


# ── Flag check helpers ───────────────────────────────────────────────────────

async def is_file_flagged(source_file_id: str) -> bool:
    """Return True if the source file has any active or extended flag."""
    row = await db_fetch_one(
        "SELECT COUNT(*) AS cnt FROM file_flags "
        "WHERE source_file_id = ? AND status IN ('active', 'extended')",
        (source_file_id,),
    )
    return (row["cnt"] > 0) if row else False


async def is_file_flagged_by_path(source_path: str) -> bool:
    """Return True if a file (by path) has any active or extended flag."""
    row = await db_fetch_one(
        """SELECT COUNT(*) AS cnt
           FROM file_flags f
           JOIN source_files sf ON sf.id = f.source_file_id
           WHERE sf.source_path = ?
             AND f.status IN ('active', 'extended')""",
        (source_path,),
    )
    return (row["cnt"] > 0) if row else False
