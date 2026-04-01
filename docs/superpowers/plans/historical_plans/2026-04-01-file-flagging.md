# File Flagging & Content Moderation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-service file flagging system that lets users suppress sensitive files from search/download, with admin triage (dismiss/extend/remove), blocklist enforcement, webhook notifications, and auto-expiry.

**Architecture:** Two new DB tables (`file_flags`, `blocklisted_files`) with a `FlagManager` business-logic layer that coordinates SQLite state and Meilisearch `is_flagged` attribute. Flag API routes split user/admin. Scanner checks blocklist before upserting. Scheduler runs hourly expiry.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, Meilisearch, structlog, vanilla HTML/JS/CSS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `core/database.py` | Modify | Add `file_flags` + `blocklisted_files` tables to `_SCHEMA_SQL`, add 2 new preferences to `DEFAULT_PREFERENCES` |
| `core/flag_manager.py` | Create | Flag business logic: create/retract/resolve flags, blocklist CRUD, Meilisearch `is_flagged` sync, webhook fire |
| `api/routes/flags.py` | Create | Flag API endpoints (user: POST/GET/DELETE, admin: GET/PUT/DELETE + stats) |
| `core/search_indexer.py` | Modify | Add `is_flagged` to filterable/displayed attrs on all 3 indexes, fix `file_size_bytes` source |
| `api/routes/search.py` | Modify | Add `is_flagged != true` default filter, 403 checks on source/download, skip flagged in batch |
| `core/bulk_scanner.py` | Modify | Add blocklist check in `_process_discovered_file()` |
| `core/scheduler.py` | Modify | Add hourly flag expiry job |
| `main.py` | Modify | Mount flags router |
| `static/search.html` | Modify | Add flag button per result, flag modal |
| `static/flagged.html` | Create | Admin flagged files page |
| `static/admin.html` | Modify | Add flagged files KPI card |
| `static/app.js` | Modify | Add nav entry for flagged page |

---

## Task 1: Database Schema — `file_flags` + `blocklisted_files` Tables

**Files:**
- Modify: `core/database.py` (schema at line ~517-531, preferences at line ~92-113)

- [ ] **Step 1: Add tables to `_SCHEMA_SQL`**

Insert before the closing `"""` of `_SCHEMA_SQL` (after the `transcript_segments` index at line 530):

```python
-- v0.16.0: File flagging & content moderation
CREATE TABLE IF NOT EXISTS file_flags (
    id                TEXT PRIMARY KEY,
    source_file_id    TEXT NOT NULL REFERENCES source_files(id),
    flagged_by_sub    TEXT NOT NULL,
    flagged_by_email  TEXT NOT NULL,
    reason            TEXT NOT NULL,
    note              TEXT,
    status            TEXT NOT NULL DEFAULT 'active',
    expires_at        DATETIME NOT NULL,
    created_at        DATETIME NOT NULL DEFAULT (datetime('now')),
    resolved_at       DATETIME,
    resolved_by_email TEXT,
    resolution_note   TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_flags_source_status
    ON file_flags(source_file_id, status);
CREATE INDEX IF NOT EXISTS idx_file_flags_status_expires
    ON file_flags(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_file_flags_user
    ON file_flags(flagged_by_email);

CREATE TABLE IF NOT EXISTS blocklisted_files (
    id              TEXT PRIMARY KEY,
    content_hash    TEXT,
    source_path     TEXT,
    reason          TEXT,
    added_by_email  TEXT NOT NULL,
    flag_id         TEXT REFERENCES file_flags(id),
    created_at      DATETIME NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_blocklist_hash ON blocklisted_files(content_hash);
CREATE INDEX IF NOT EXISTS idx_blocklist_path ON blocklisted_files(source_path);
```

- [ ] **Step 2: Add flag preferences to `DEFAULT_PREFERENCES`**

Add after the cloud prefetch block (after line ~103):

```python
    # File flagging (v0.16.0)
    "flag_webhook_url": "",
    "flag_default_expiry_days": "14",
```

- [ ] **Step 3: Verify schema loads**

Run: `docker-compose exec markflow python -c "import asyncio; from core.database import init_db; asyncio.run(init_db()); print('OK')"`

Expected: `OK` (no errors)

- [ ] **Step 4: Commit**

```bash
git add core/database.py
git commit -m "feat(flags): add file_flags + blocklisted_files tables and preferences"
```

---

## Task 2: Flag Manager — Business Logic Layer

**Files:**
- Create: `core/flag_manager.py`

- [ ] **Step 1: Create `core/flag_manager.py` with all business logic**

```python
"""Flag manager — business logic for file flagging & content moderation.

Coordinates SQLite state, Meilisearch is_flagged sync, and webhook delivery.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from core.database import db_execute, db_fetch_all, db_fetch_one, get_db, get_preference

log = structlog.get_logger(__name__)

VALID_REASONS = {"pii", "confidential", "unauthorized", "other"}
ACTIVE_STATUSES = ("active", "extended")


# ── Meilisearch sync ────────────────────────────────────────────────────────

async def _sync_is_flagged(source_file_id: str, force_value: bool | None = None) -> None:
    """Update is_flagged on all Meilisearch entries for this source file.

    If force_value is None, derives from DB (any active/extended flag = True).
    """
    if force_value is None:
        row = await db_fetch_one(
            "SELECT COUNT(*) as cnt FROM file_flags WHERE source_file_id = ? AND status IN ('active', 'extended')",
            (source_file_id,),
        )
        force_value = (row["cnt"] > 0) if row else False

    # Look up all paths for this source file to find Meilisearch doc IDs
    sf = await db_fetch_one("SELECT source_path, output_path FROM source_files WHERE id = ?", (source_file_id,))
    if not sf:
        return

    try:
        from core.search_indexer import SearchIndexer, _doc_id
        indexer = SearchIndexer()
        if not await indexer.client.health_check():
            log.warning("flag_meili_unavailable", source_file_id=source_file_id)
            return

        # Update across all 3 indexes where this file might appear
        source_path = sf.get("source_path", "")
        output_path = sf.get("output_path", "")
        doc_id_by_output = _doc_id(output_path) if output_path else None
        doc_id_by_source = _doc_id(source_path) if source_path else None

        for index_name in ("documents", "adobe-files", "transcripts"):
            for did in (doc_id_by_output, doc_id_by_source):
                if not did:
                    continue
                try:
                    await indexer.client.update_documents(index_name, [{"id": did, "is_flagged": force_value}])
                except Exception:
                    pass  # document may not exist in this index
    except Exception as exc:
        log.warning("flag_meili_sync_error", source_file_id=source_file_id, error=str(exc))


# ── Webhook ──────────────────────────────────────────────────────────────────

async def _fire_webhook(event: str, flag: dict, actor_email: str, actor_role: str = "") -> None:
    """Fire-and-forget webhook POST. 3-second timeout, no retries."""
    url = await get_preference("flag_webhook_url")
    if not url:
        return

    sf = await db_fetch_one(
        "SELECT source_path FROM source_files WHERE id = ?",
        (flag["source_file_id"],),
    )

    payload = {
        "event": event,
        "flag_id": flag["id"],
        "file": {
            "source_file_id": flag["source_file_id"],
            "source_path": sf["source_path"] if sf else "",
            "source_filename": sf["source_path"].rsplit("/", 1)[-1] if sf and sf.get("source_path") else "",
        },
        "actor": {"email": actor_email, "role": actor_role},
        "reason": flag.get("reason", ""),
        "note": flag.get("note", ""),
        "status": flag.get("status", ""),
        "expires_at": flag.get("expires_at", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(url, json=payload)
        log.info("webhook_delivered", event=event, flag_id=flag["id"])
    except Exception as exc:
        log.warning("webhook_delivery_failed", event=event, flag_id=flag["id"], error=str(exc))


# ── Flag CRUD ────────────────────────────────────────────────────────────────

async def create_flag(
    source_file_id: str,
    reason: str,
    flagged_by_sub: str,
    flagged_by_email: str,
    note: str = "",
    role: str = "",
) -> dict:
    """Create a new file flag. Returns the flag dict."""
    if reason not in VALID_REASONS:
        raise ValueError(f"Invalid reason: {reason}. Must be one of: {VALID_REASONS}")

    # Verify source file exists
    sf = await db_fetch_one("SELECT id FROM source_files WHERE id = ?", (source_file_id,))
    if not sf:
        raise ValueError(f"Source file not found: {source_file_id}")

    expiry_days = int(await get_preference("flag_default_expiry_days") or "14")
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)

    flag_id = uuid.uuid4().hex
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO file_flags (id, source_file_id, flagged_by_sub, flagged_by_email,
               reason, note, status, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
            (flag_id, source_file_id, flagged_by_sub, flagged_by_email,
             reason, note, expires_at.isoformat()),
        )
        await conn.commit()

    flag = await get_flag(flag_id)
    await _sync_is_flagged(source_file_id, force_value=True)
    log.info("file_flagged", flag_id=flag_id, source_file_id=source_file_id,
             user=flagged_by_email, reason=reason)
    await _fire_webhook("file_flagged", flag, flagged_by_email, role)
    return flag


async def get_flag(flag_id: str) -> dict | None:
    """Get a single flag by ID."""
    return await db_fetch_one("SELECT * FROM file_flags WHERE id = ?", (flag_id,))


async def get_my_flags(flagged_by_sub: str) -> list[dict]:
    """Get all active flags for a given user."""
    return await db_fetch_all(
        """SELECT f.*, sf.source_path
           FROM file_flags f
           JOIN source_files sf ON sf.id = f.source_file_id
           WHERE f.flagged_by_sub = ? AND f.status IN ('active', 'extended')
           ORDER BY f.created_at DESC""",
        (flagged_by_sub,),
    )


async def retract_flag(flag_id: str, user_sub: str) -> dict:
    """Retract own flag (before admin acts). Returns updated flag."""
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError("Flag not found")
    if flag["flagged_by_sub"] != user_sub:
        raise PermissionError("Can only retract your own flags")
    if flag["status"] != "active":
        raise ValueError(f"Cannot retract flag in status: {flag['status']}")

    async with get_db() as conn:
        await conn.execute(
            "UPDATE file_flags SET status = 'retracted', resolved_at = datetime('now') WHERE id = ?",
            (flag_id,),
        )
        await conn.commit()

    await _sync_is_flagged(flag["source_file_id"])
    log.info("flag_retracted", flag_id=flag_id, source_file_id=flag["source_file_id"])
    updated = await get_flag(flag_id)
    await _fire_webhook("flag_retracted", updated, flag["flagged_by_email"])
    return updated


# ── Admin actions ────────────────────────────────────────────────────────────

async def dismiss_flag(flag_id: str, admin_email: str, resolution_note: str = "") -> dict:
    """Admin dismisses a flag — restores file access."""
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError("Flag not found")

    async with get_db() as conn:
        await conn.execute(
            """UPDATE file_flags SET status = 'dismissed', resolved_at = datetime('now'),
               resolved_by_email = ?, resolution_note = ? WHERE id = ?""",
            (admin_email, resolution_note, flag_id),
        )
        await conn.commit()

    await _sync_is_flagged(flag["source_file_id"])
    log.info("flag_dismissed", flag_id=flag_id, admin=admin_email)
    updated = await get_flag(flag_id)
    await _fire_webhook("flag_dismissed", updated, admin_email, "admin")
    return updated


async def extend_flag(flag_id: str, days: int, admin_email: str, resolution_note: str = "") -> dict:
    """Admin extends a flag's suppression period."""
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError("Flag not found")

    if days <= 0:
        new_expires = "9999-12-31T23:59:59"  # indefinite
    else:
        new_expires = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()

    async with get_db() as conn:
        await conn.execute(
            """UPDATE file_flags SET status = 'extended', expires_at = ?,
               resolved_at = datetime('now'), resolved_by_email = ?, resolution_note = ?
               WHERE id = ?""",
            (new_expires, admin_email, resolution_note, flag_id),
        )
        await conn.commit()

    log.info("flag_extended", flag_id=flag_id, new_expires=new_expires, admin=admin_email)
    updated = await get_flag(flag_id)
    await _fire_webhook("flag_extended", updated, admin_email, "admin")
    return updated


async def remove_and_blocklist(flag_id: str, admin_email: str, resolution_note: str = "") -> dict:
    """Admin permanently removes file + adds to blocklist."""
    flag = await get_flag(flag_id)
    if not flag:
        raise ValueError("Flag not found")

    sf = await db_fetch_one(
        "SELECT content_hash, source_path FROM source_files WHERE id = ?",
        (flag["source_file_id"],),
    )

    async with get_db() as conn:
        # Update flag
        await conn.execute(
            """UPDATE file_flags SET status = 'removed', resolved_at = datetime('now'),
               resolved_by_email = ?, resolution_note = ? WHERE id = ?""",
            (admin_email, resolution_note, flag_id),
        )
        # Create blocklist entry
        bl_id = uuid.uuid4().hex
        await conn.execute(
            """INSERT INTO blocklisted_files (id, content_hash, source_path, reason,
               added_by_email, flag_id) VALUES (?, ?, ?, ?, ?, ?)""",
            (bl_id, sf["content_hash"] if sf else None,
             sf["source_path"] if sf else None,
             flag["reason"], admin_email, flag_id),
        )
        await conn.commit()

    # Delete from Meilisearch entirely
    try:
        from core.search_indexer import SearchIndexer, _doc_id
        indexer = SearchIndexer()
        if sf:
            source_path = sf.get("source_path", "")
            output_path_row = await db_fetch_one(
                "SELECT output_path FROM source_files WHERE id = ?", (flag["source_file_id"],)
            )
            output_path = output_path_row["output_path"] if output_path_row and output_path_row.get("output_path") else ""
            for index_name in ("documents", "adobe-files", "transcripts"):
                for path in (output_path, source_path):
                    if path:
                        try:
                            await indexer.client.delete_document(index_name, _doc_id(path))
                        except Exception:
                            pass
    except Exception as exc:
        log.warning("remove_meili_delete_error", flag_id=flag_id, error=str(exc))

    log.info("file_removed_and_blocklisted", flag_id=flag_id,
             source_file_id=flag["source_file_id"], admin=admin_email)
    updated = await get_flag(flag_id)
    await _fire_webhook("file_removed_and_blocklisted", updated, admin_email, "admin")
    return updated


# ── Blocklist queries ────────────────────────────────────────────────────────

async def is_blocklisted(source_path: str, content_hash: str | None = None) -> bool:
    """Check if a file is blocklisted by path or content hash."""
    if content_hash:
        row = await db_fetch_one(
            "SELECT id FROM blocklisted_files WHERE content_hash = ? OR source_path = ?",
            (content_hash, source_path),
        )
    else:
        row = await db_fetch_one(
            "SELECT id FROM blocklisted_files WHERE source_path = ?",
            (source_path,),
        )
    return row is not None


async def get_blocklist(page: int = 1, per_page: int = 25) -> dict:
    """Get paginated blocklist."""
    offset = (page - 1) * per_page
    items = await db_fetch_all(
        "SELECT * FROM blocklisted_files ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    count_row = await db_fetch_one("SELECT COUNT(*) as cnt FROM blocklisted_files")
    return {"items": items, "total": count_row["cnt"] if count_row else 0, "page": page, "per_page": per_page}


async def remove_from_blocklist(blocklist_id: str) -> bool:
    """Remove a file from the blocklist (allows re-indexing)."""
    async with get_db() as conn:
        cursor = await conn.execute("DELETE FROM blocklisted_files WHERE id = ?", (blocklist_id,))
        await conn.commit()
        deleted = cursor.rowcount > 0
    if deleted:
        log.info("blocklist_entry_removed", blocklist_id=blocklist_id)
    return deleted


# ── Flag queries (admin) ─────────────────────────────────────────────────────

async def list_flags(
    status: str | None = None,
    flagged_by: str | None = None,
    reason: str | None = None,
    path_prefix: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "expires_at",
    sort_dir: str = "asc",
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """List flags with filters and pagination (admin)."""
    conditions = []
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

    where = " AND ".join(conditions) if conditions else "1=1"

    # Validate sort column
    allowed_sorts = {"expires_at", "created_at", "reason", "flagged_by_email", "resolved_at"}
    if sort_by not in allowed_sorts:
        sort_by = "expires_at"
    direction = "DESC" if sort_dir.lower() == "desc" else "ASC"

    offset = (page - 1) * per_page
    items = await db_fetch_all(
        f"""SELECT f.*, sf.source_path, sf.file_ext
            FROM file_flags f
            JOIN source_files sf ON sf.id = f.source_file_id
            WHERE {where}
            ORDER BY f.{sort_by} {direction}
            LIMIT ? OFFSET ?""",
        tuple(params) + (per_page, offset),
    )

    count_row = await db_fetch_one(
        f"""SELECT COUNT(*) as cnt
            FROM file_flags f
            JOIN source_files sf ON sf.id = f.source_file_id
            WHERE {where}""",
        tuple(params),
    )

    return {"items": items, "total": count_row["cnt"] if count_row else 0, "page": page, "per_page": per_page}


async def get_flag_stats() -> dict:
    """Counts by status for dashboard KPI."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) as cnt FROM file_flags GROUP BY status"
    )
    stats = {r["status"]: r["cnt"] for r in rows}
    return {
        "active": stats.get("active", 0),
        "extended": stats.get("extended", 0),
        "dismissed": stats.get("dismissed", 0),
        "expired": stats.get("expired", 0),
        "removed": stats.get("removed", 0),
        "retracted": stats.get("retracted", 0),
    }


# ── Auto-expiry ──────────────────────────────────────────────────────────────

async def expire_flags() -> int:
    """Expire flags past their expires_at. Called hourly by scheduler."""
    now = datetime.now(timezone.utc).isoformat()
    expired_flags = await db_fetch_all(
        "SELECT id, source_file_id FROM file_flags WHERE status IN ('active', 'extended') AND expires_at < ?",
        (now,),
    )

    if not expired_flags:
        return 0

    async with get_db() as conn:
        await conn.execute(
            "UPDATE file_flags SET status = 'expired' WHERE status IN ('active', 'extended') AND expires_at < ?",
            (now,),
        )
        await conn.commit()

    # Sync Meilisearch for each affected source file
    source_ids = {f["source_file_id"] for f in expired_flags}
    for sid in source_ids:
        await _sync_is_flagged(sid)

    for f in expired_flags:
        log.info("flag_expired", flag_id=f["id"], source_file_id=f["source_file_id"])

    return len(expired_flags)


# ── Flag check helper (for search/download endpoints) ────────────────────────

async def is_file_flagged(source_file_id: str) -> bool:
    """Check if a source file has any active/extended flag."""
    row = await db_fetch_one(
        "SELECT COUNT(*) as cnt FROM file_flags WHERE source_file_id = ? AND status IN ('active', 'extended')",
        (source_file_id,),
    )
    return (row["cnt"] > 0) if row else False


async def is_file_flagged_by_path(source_path: str) -> bool:
    """Check if a file is flagged, looking up by source_path."""
    row = await db_fetch_one(
        """SELECT COUNT(*) as cnt FROM file_flags f
           JOIN source_files sf ON sf.id = f.source_file_id
           WHERE sf.source_path = ? AND f.status IN ('active', 'extended')""",
        (source_path,),
    )
    return (row["cnt"] > 0) if row else False
```

- [ ] **Step 2: Verify import works**

Run: `docker-compose exec markflow python -c "from core.flag_manager import create_flag, is_blocklisted; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add core/flag_manager.py
git commit -m "feat(flags): add FlagManager business logic layer"
```

---

## Task 3: Flag API Routes — User + Admin Endpoints

**Files:**
- Create: `api/routes/flags.py`

- [ ] **Step 1: Create `api/routes/flags.py`**

**Important:** Fixed-path routes (`/mine`, `/stats`, `/blocklist`, `/lookup-source`) MUST be defined BEFORE the `/{flag_id}` catch-all, or FastAPI matches literal segments as a flag_id.

```python
"""Flag API routes — user flagging + admin triage."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import structlog

from core.auth import AuthenticatedUser, UserRole, require_role
from core import flag_manager

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/flags", tags=["flags"])


# ── User endpoints (SEARCH_USER+) ───────────────────────────────────────────

@router.post("")
async def flag_file(
    body: dict = Body(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Flag a file for review. Body: {source_file_id, reason, note?}"""
    source_file_id = body.get("source_file_id")
    reason = body.get("reason")
    note = body.get("note", "")

    if not source_file_id or not reason:
        raise HTTPException(status_code=400, detail="source_file_id and reason are required.")

    try:
        flag = await flag_manager.create_flag(
            source_file_id=source_file_id,
            reason=reason,
            flagged_by_sub=user.sub,
            flagged_by_email=user.email,
            note=note,
            role=user.role.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"flag": flag, "message": "File flagged — hidden from search."}


@router.get("/mine")
async def my_flags(
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """List caller's active flags."""
    flags = await flag_manager.get_my_flags(user.sub)
    return {"flags": flags}


@router.get("/lookup-source")
async def lookup_source_file_id(
    source_path: str = Query(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Look up source_file_id from source_path (for flag UI)."""
    from core.database import db_fetch_one
    row = await db_fetch_one(
        "SELECT id FROM source_files WHERE source_path = ?", (source_path,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Source file not found in database.")
    return {"source_file_id": row["id"]}


# ── Admin endpoints (ADMIN) — fixed paths before /{flag_id} catch-all ────────

@router.get("/stats")
async def flag_stats(
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Flag counts by status for dashboard KPI."""
    return await flag_manager.get_flag_stats()


@router.get("/blocklist")
async def view_blocklist(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=100),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """View blocklisted files."""
    return await flag_manager.get_blocklist(page, per_page)


@router.get("")
async def list_flags(
    status: str | None = None,
    flagged_by: str | None = None,
    reason: str | None = None,
    path_prefix: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = Query("expires_at"),
    sort_dir: str = Query("asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=5, le=100),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """List all flags with filters (admin)."""
    return await flag_manager.list_flags(
        status=status, flagged_by=flagged_by, reason=reason,
        path_prefix=path_prefix, date_from=date_from, date_to=date_to,
        sort_by=sort_by, sort_dir=sort_dir, page=page, per_page=per_page,
    )


@router.delete("/blocklist/{blocklist_id}")
async def un_blocklist(
    blocklist_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Remove from blocklist (allows re-indexing)."""
    removed = await flag_manager.remove_from_blocklist(blocklist_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Blocklist entry not found.")
    return {"message": "Removed from blocklist."}


# ── Parameterized routes (after all fixed paths) ────────────────────────────

@router.delete("/{flag_id}")
async def retract_flag(
    flag_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.SEARCH_USER)),
):
    """Retract own flag (before admin acts)."""
    try:
        flag = await flag_manager.retract_flag(flag_id, user.sub)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Can only retract your own flags.")

    return {"flag": flag, "message": "Flag retracted."}


@router.get("/{flag_id}")
async def get_flag(
    flag_id: str,
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Get single flag detail."""
    flag = await flag_manager.get_flag(flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail="Flag not found.")
    return {"flag": flag}


@router.put("/{flag_id}/dismiss")
async def dismiss_flag(
    flag_id: str,
    body: dict = Body(default={}),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Dismiss flag — restore file access."""
    try:
        flag = await flag_manager.dismiss_flag(flag_id, user.email, body.get("resolution_note", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"flag": flag, "message": "Flag dismissed — file restored."}


@router.put("/{flag_id}/extend")
async def extend_flag(
    flag_id: str,
    body: dict = Body(...),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Extend flag suppression. Body: {days, resolution_note?}"""
    days = body.get("days")
    if days is None:
        raise HTTPException(status_code=400, detail="days is required.")
    try:
        flag = await flag_manager.extend_flag(flag_id, int(days), user.email, body.get("resolution_note", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"flag": flag, "message": "Flag extended."}


@router.put("/{flag_id}/remove")
async def remove_file(
    flag_id: str,
    body: dict = Body(default={}),
    user: AuthenticatedUser = Depends(require_role(UserRole.ADMIN)),
):
    """Permanently remove file + blocklist."""
    try:
        flag = await flag_manager.remove_and_blocklist(flag_id, user.email, body.get("resolution_note", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"flag": flag, "message": "File removed and blocklisted."}
```

- [ ] **Step 2: Mount router in `main.py`**

Add after the pipeline routes block (after line ~280):

```python
# v0.16.0 — File flagging & content moderation
from api.routes import flags as flags_routes
app.include_router(flags_routes.router)
```

- [ ] **Step 3: Verify routes register**

Run: `docker-compose exec markflow python -c "from main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'flag' in r])"`

Expected: List of flag-related paths

- [ ] **Step 4: Commit**

```bash
git add api/routes/flags.py main.py
git commit -m "feat(flags): add flag API routes and mount router"
```

---

## Task 4: Meilisearch `is_flagged` Attribute + File Size Fix

**Files:**
- Modify: `core/search_indexer.py` (lines 27-80 for settings, line 208 for file_size_bytes)

- [ ] **Step 1: Add `is_flagged` to all 3 index settings**

In `DOCUMENTS_INDEX_SETTINGS` (line ~35), add to `filterableAttributes`:

```python
    "filterableAttributes": [
        "source_format",
        "fidelity_tier",
        "has_ocr",
        "job_id",
        "relative_path_prefix",
        "enrichment_level",
        "vision_provider",
        "is_flagged",
    ],
```

Add `"is_flagged"` to `displayedAttributes` (line ~49):

```python
    "displayedAttributes": [
        "id", "title", "source_filename", "source_format", "relative_path",
        "output_path", "source_path", "content_preview", "headings",
        "frame_descriptions", "fidelity_tier", "has_ocr", "converted_at",
        "file_size_bytes", "job_id", "enrichment_level", "vision_provider",
        "scene_count", "is_flagged",
    ],
```

In `TRANSCRIPTS_INDEX_SETTINGS` (line ~63), add to `filterableAttributes`:

```python
    "filterableAttributes": ["source_format", "engine", "language", "is_flagged"],
```

Add `"is_flagged"` to `displayedAttributes`:

```python
    "displayedAttributes": [
        "id", "title", "raw_text", "source_path", "source_format",
        "duration_seconds", "engine", "whisper_model", "language",
        "word_count", "created_at", "is_flagged",
    ],
```

In `ADOBE_INDEX_SETTINGS` (line ~74), add to `filterableAttributes`:

```python
    "filterableAttributes": ["file_ext", "creator", "job_id", "is_flagged"],
```

Add `"is_flagged"` to `displayedAttributes`:

```python
    "displayedAttributes": [
        "id", "source_filename", "file_ext", "source_path", "title",
        "creator", "keywords", "text_preview", "indexed_at", "job_id",
        "is_flagged",
    ],
```

- [ ] **Step 2: Set `is_flagged` when indexing documents**

In `index_document()` (line ~192), add `is_flagged` to the doc dict. After the `doc` dict is built and before `add_documents`, insert:

```python
        # Check if file is flagged
        is_flagged = False
        if source_path:
            try:
                from core.flag_manager import is_file_flagged_by_path
                is_flagged = await is_file_flagged_by_path(source_path)
            except Exception:
                pass
        doc["is_flagged"] = is_flagged
```

Insert this between the closing `}` of the doc dict (after line ~213) and the `task_uid` line (~215).

- [ ] **Step 3: Fix `file_size_bytes` to use source file size**

Replace line 208:
```python
            "file_size_bytes": md_path.stat().st_size,
```

With:
```python
            "file_size_bytes": await _get_source_file_size(source_path, md_path),
```

Add this helper function before `index_document()` (around line 135):

```python
async def _get_source_file_size(source_path: str, fallback_path: Path) -> int:
    """Get original source file size. Falls back to output file size."""
    if source_path:
        row = await db_fetch_one(
            "SELECT file_size_bytes FROM source_files WHERE source_path = ?",
            (source_path,),
        )
        if row and row["file_size_bytes"]:
            return row["file_size_bytes"]
    try:
        return fallback_path.stat().st_size
    except OSError:
        return 0
```

- [ ] **Step 4: Commit**

```bash
git add core/search_indexer.py
git commit -m "feat(flags): add is_flagged to Meilisearch indexes, fix file_size_bytes source"
```

---

## Task 5: Search Endpoint Modifications — Flag Filtering + Access Blocking

**Files:**
- Modify: `api/routes/search.py` (lines 86-152, 157-247, 333-395, 426-489)

- [ ] **Step 1: Add `is_flagged != true` filter to single-index search**

In `search()` (line ~122), after building the filters list, add the flag filter. Add a new import at the top of the file:

```python
from core.auth import AuthenticatedUser, UserRole, require_role, role_satisfies
```

Then modify the filter building section:

```python
    # Build filters
    filters = []
    if format and index == "documents":
        filters.append(f'source_format = "{format}"')
    if path_prefix and index == "documents":
        filters.append(f'relative_path_prefix = "{path_prefix}"')
    # Hide flagged files from non-admin users
    if not role_satisfies(user.role, UserRole.ADMIN):
        filters.append("is_flagged != true")
    if filters:
        options["filter"] = " AND ".join(filters)
```

- [ ] **Step 2: Add `is_flagged` filter to unified search (`search_all`)**

In `search_all()` (line ~193), modify the filter building. Replace lines 193-194:

```python
    # Build document filter
    doc_filters = []
    if format:
        doc_filters.append(f'source_format = "{format}"')
    if not role_satisfies(user.role, UserRole.ADMIN):
        doc_filters.append("is_flagged != true")
    if doc_filters:
        options["filter"] = " AND ".join(doc_filters)

    # Build other-index filters (adobe, transcripts)
    other_filters = []
    if not role_satisfies(user.role, UserRole.ADMIN):
        other_filters.append("is_flagged != true")
```

Then update `other_options_adobe` and transcript search to include the flag filter:

```python
    if format:
        adobe_filter_parts = [f'file_ext = ".{format}"'] + other_filters
        other_options_adobe = {**other_options, "filter": " AND ".join(adobe_filter_parts)}
    elif other_filters:
        other_options_adobe = {**other_options, "filter": " AND ".join(other_filters)}
    else:
        other_options_adobe = other_options

    if other_filters:
        other_options_transcripts = {**other_options, "filter": " AND ".join(other_filters)}
    else:
        other_options_transcripts = other_options
```

And update the transcript search call to use `other_options_transcripts`:

```python
    transcript_task = client.search("transcripts", q, other_options_transcripts)
```

- [ ] **Step 3: Add 403 check to `serve_source` and `download_source`**

In `serve_source()` (line ~340), after resolving the source path (line ~344), add:

```python
    # Check if file is flagged
    from core.flag_manager import is_file_flagged_by_path
    if source_path and await is_file_flagged_by_path(str(source_path)):
        if not role_satisfies(user.role, UserRole.ADMIN):
            raise HTTPException(status_code=403, detail="This file has been flagged for review.")
```

Add the same check to `download_source()` after line ~382.

- [ ] **Step 4: Skip flagged files in batch download**

In `batch_download()` (line ~442), initialize a counter before the loop:

```python
    skipped_flagged = 0
```

Inside the for loop, after resolving the source path (line ~458), add before `zf.write(...)`:

```python
                # Skip flagged files
                from core.flag_manager import is_file_flagged_by_path
                if source_path and await is_file_flagged_by_path(str(source_path)):
                    skipped_flagged += 1
                    continue
```

Add to the response headers:

```python
            "X-Skipped-Flagged": str(skipped_flagged),
```

- [ ] **Step 5: Commit**

```bash
git add api/routes/search.py
git commit -m "feat(flags): add flag filtering to search, 403 on flagged source/download"
```

---

## Task 6: Scanner Blocklist Enforcement

**Files:**
- Modify: `core/bulk_scanner.py` (line ~640, `_process_discovered_file`)

- [ ] **Step 1: Add blocklist check in `_process_discovered_file()`**

After the NTFS ADS check (line ~649) and before the `ext = _get_effective_extension()` call (line ~652), add:

```python
        # Check blocklist
        from core.flag_manager import is_blocklisted
        if await is_blocklisted(str(file_path)):
            log.debug("blocklisted_file_skipped", path=str(file_path), matched_by="path")
            return file_count
```

- [ ] **Step 2: Commit**

```bash
git add core/bulk_scanner.py
git commit -m "feat(flags): add blocklist enforcement in scanner"
```

---

## Task 7: Scheduler — Hourly Flag Expiry Job

**Files:**
- Modify: `core/scheduler.py` (line ~456, `start_scheduler`)

- [ ] **Step 1: Add the expiry job wrapper function**

Add near the other job functions (before `start_scheduler()`):

```python
async def _expire_flags() -> None:
    """Hourly job: expire flags past their expires_at."""
    try:
        from core.flag_manager import expire_flags
        expired = await expire_flags()
        if expired:
            log.info("flag_expiry_run", expired_count=expired)
    except Exception as exc:
        log.error("flag_expiry_failed", error=str(exc))
```

- [ ] **Step 2: Register the job in `start_scheduler()`**

Add after the pipeline_watchdog job (line ~464), before `scheduler.start()`:

```python
    # v0.16.0: Flag expiry — hourly
    scheduler.add_job(
        _expire_flags,
        trigger=IntervalTrigger(hours=1),
        id="flag_expiry",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
```

Update the job count in the log message: change `jobs=12` to `jobs=13` on line ~467.

- [ ] **Step 3: Commit**

```bash
git add core/scheduler.py
git commit -m "feat(flags): add hourly flag expiry scheduler job"
```

---

## Task 8: Search UI — Flag Button + Modal

**Files:**
- Modify: `static/search.html`

- [ ] **Step 1: Add flag modal HTML**

Add before the closing `</body>` tag in `search.html`:

```html
<!-- Flag File Modal -->
<div id="flag-modal-backdrop" class="dialog-backdrop">
  <div class="dialog" style="max-width:420px;">
    <h3 style="margin-top:0;">Flag File for Review</h3>
    <p id="flag-modal-filename" style="color:var(--text-muted);word-break:break-all;"></p>
    <div class="form-group">
      <label for="flag-reason">Reason</label>
      <select id="flag-reason">
        <option value="">Select a reason...</option>
        <option value="pii">Contains PII</option>
        <option value="confidential">Confidential / Privileged</option>
        <option value="unauthorized">Not Authorized to Share</option>
        <option value="other">Other</option>
      </select>
    </div>
    <div class="form-group">
      <label for="flag-note">Note (optional)</label>
      <input type="text" id="flag-note" placeholder="Additional context...">
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">
      <button class="btn btn-ghost" onclick="closeFlagModal()">Cancel</button>
      <button class="btn btn-danger" id="flag-submit-btn" onclick="submitFlag()">Flag File</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Add flag button CSS**

Add to the page's `<style>` block:

```css
.btn-flag {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    padding: 4px 6px;
    font-size: 1rem;
    border-radius: var(--radius-sm);
    transition: color var(--transition), background var(--transition);
}
.btn-flag:hover {
    color: var(--error);
    background: color-mix(in srgb, var(--error) 10%, transparent);
}
```

- [ ] **Step 3: Add flag button to search result card rendering**

Find the JavaScript function that builds each `.hit` div. Add a flag button to each card after the checkbox. The exact location depends on the rendering function — find where `.hit-checkbox` or `.hit-body` is constructed and add:

```javascript
// Inside the hit card builder, add a flag button element
const flagBtn = document.createElement('button');
flagBtn.className = 'btn-flag';
flagBtn.title = 'Flag this file';
flagBtn.textContent = '\u2691';  // flag character
flagBtn.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    openFlagModal(hit.source_path, hit.id, hit.source_index);
});
// Append flagBtn to the hit card's action area
```

- [ ] **Step 4: Add flag modal JavaScript**

Add to the page's `<script>` block:

```javascript
let flagModalState = { sourceFileId: null, sourceIndex: null, docId: null };

function openFlagModal(sourcePath, docId, sourceIndex) {
    flagModalState = { sourcePath: sourcePath, docId: docId, sourceIndex: sourceIndex };
    document.getElementById('flag-modal-filename').textContent = sourcePath || docId;
    document.getElementById('flag-reason').value = '';
    document.getElementById('flag-note').value = '';
    document.getElementById('flag-modal-backdrop').classList.add('open');
}

function closeFlagModal() {
    document.getElementById('flag-modal-backdrop').classList.remove('open');
}

async function submitFlag() {
    const reason = document.getElementById('flag-reason').value;
    if (!reason) { showToast('Please select a reason.', 'error'); return; }

    const note = document.getElementById('flag-note').value;
    const btn = document.getElementById('flag-submit-btn');
    btn.disabled = true;
    btn.textContent = 'Flagging...';

    try {
        // Look up source_file_id from source_path
        const sourcePath = flagModalState.sourcePath;
        const sfResp = await API.get(
            '/api/flags/lookup-source?source_path=' + encodeURIComponent(sourcePath)
        );

        await API.post('/api/flags', {
            source_file_id: sfResp.source_file_id,
            reason: reason,
            note: note,
        });

        closeFlagModal();
        showToast('File flagged \u2014 hidden from search for 14 days.', 'success');

        // Fade out the flagged result
        var hits = document.querySelectorAll('.hit');
        hits.forEach(function(h) {
            if (h.dataset.docId === flagModalState.docId) {
                h.style.opacity = '0.3';
                h.style.pointerEvents = 'none';
            }
        });
    } catch (err) {
        showToast(err.message || 'Failed to flag file.', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Flag File';
    }
}
```

- [ ] **Step 5: Commit**

```bash
git add static/search.html api/routes/flags.py
git commit -m "feat(flags): add flag button + modal to search results"
```

---

## Task 9: Admin Flagged Files Page

**Files:**
- Create: `static/flagged.html`

- [ ] **Step 1: Create `static/flagged.html`**

Build this page using safe DOM construction methods (textContent, createElement) for all user-provided data. Use the existing app.js `API` object, `showToast()`, and `buildNav()` functions. The page has:

1. Summary stats bar (flag counts by status)
2. Three tabs: Active, History, Blocklist
3. Filters: reason, flagged_by, path_prefix, sort_by
4. Table rendering using DOM methods (not innerHTML with user data)
5. Admin actions: dismiss, extend, remove (with prompt/confirm dialogs)
6. Pagination

The page should follow the same patterns as other admin pages (admin.html): nav-bar, main container, card-based layout.

**Note on rendering approach:** All dynamic content containing user-provided data (file paths, emails, notes, reasons) MUST be inserted using `textContent` or `createElement` + `textContent` — never via string concatenation into element content. Static structural HTML (table headers, empty states, pagination) can use string building since it contains no user data.

See the spec at `docs/superpowers/specs/2026-04-01-file-flagging-design.md` for complete UI requirements (filters, columns, sort options, action behaviors).

- [ ] **Step 2: Commit**

```bash
git add static/flagged.html
git commit -m "feat(flags): add admin flagged files page"
```

---

## Task 10: Admin Dashboard KPI Card + Nav Entry

**Files:**
- Modify: `static/admin.html` (KPI section)
- Modify: `static/app.js` (NAV_ITEMS)

- [ ] **Step 1: Add flagged files KPI card to admin.html**

Find the KPI row in `admin.html` (`.stats-kpi-row`). Add a new card after the existing ones:

```html
<div class="kpi-card kpi-danger" id="kpi-flagged-card" style="cursor:pointer;" onclick="window.location.href='/flagged.html'">
    <div class="kpi-value" id="kpi-flagged">&mdash;</div>
    <div class="kpi-label">Flagged Files</div>
</div>
```

- [ ] **Step 2: Populate the KPI from JavaScript**

Find the admin page's data-fetching function. Add a fetch for flag stats:

```javascript
// Load flag stats
try {
    const flagStats = await API.get('/api/flags/stats');
    document.getElementById('kpi-flagged').textContent =
        String((flagStats.active || 0) + (flagStats.extended || 0));
} catch (e) {
    document.getElementById('kpi-flagged').textContent = '\u2014';
}
```

- [ ] **Step 3: Add nav entry in `app.js`**

Find `NAV_ITEMS` array in `app.js` (line ~184). Add an entry for the flagged page:

```javascript
{ href: "/flagged.html", label: "Flagged", minRole: "admin" },
```

- [ ] **Step 4: Commit**

```bash
git add static/admin.html static/app.js
git commit -m "feat(flags): add flagged files KPI card to admin dashboard + nav link"
```

---

## Task 11: Settings Page — Flag Preferences

**Files:**
- Modify: `static/settings.html`

- [ ] **Step 1: Add Flag Settings section**

Find an appropriate location in `settings.html` (after the Pipeline section or similar). Add:

```html
<div class="section-title">File Flagging</div>
<div class="card">
    <div class="form-group">
        <label for="pref-flag_default_expiry_days">Default flag expiry (days)</label>
        <input type="number" id="pref-flag_default_expiry_days" data-key="flag_default_expiry_days" min="1" max="365">
        <span class="hint">How long flagged files stay hidden before auto-expiry.</span>
        <div class="inline-error" id="err-flag_default_expiry_days"></div>
    </div>
    <div class="form-group">
        <label for="pref-flag_webhook_url">Flag webhook URL</label>
        <input type="url" id="pref-flag_webhook_url" data-key="flag_webhook_url" placeholder="https://hooks.example.com/markflow-flags">
        <span class="hint">Receives POST notifications for all flag events. Leave blank to disable.</span>
        <div class="inline-error" id="err-flag_webhook_url"></div>
    </div>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add static/settings.html
git commit -m "feat(flags): add flag preferences to settings page"
```

---

## Task 12: Documentation Updates

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/version-history.md`
- Modify: `docs/key-files.md`
- Modify: `docs/gotchas.md`

- [ ] **Step 1: Update CLAUDE.md**

Update the Current Status section to v0.16.0. Move existing v0.15.1 block to "Previous" and add:

```
v0.16.0: File flagging & content moderation. Self-service file flagging lets any
authenticated user temporarily suppress a file from search and download. Admins
manage flags through dedicated page with three-action escalation: dismiss (restore),
extend (keep suppressed longer), or remove (permanent blocklist). New `file_flags`
and `blocklisted_files` tables. Meilisearch `is_flagged` filterable attribute on
all 3 indexes. Blocklist enforced during scanning — prevents re-indexing of removed
files. Webhook notifications for all flag events. Hourly auto-expiry scheduler job.
Flag button on search results, admin flagged files page with filters/sort/pagination.
File size fix: search results now show original source file size instead of markdown
output size. New preferences: `flag_webhook_url`, `flag_default_expiry_days`.
```

Add to Key Files table:
```
| `core/flag_manager.py` | Flag business logic, blocklist checks, Meilisearch is_flagged sync, webhooks |
| `api/routes/flags.py` | Flag API: user flagging + admin triage (dismiss/extend/remove/blocklist) |
| `static/flagged.html` | Admin flagged files page with filters, sort, pagination |
```

Add to Gotchas section:
```
- **Multiple flags per file**: File stays hidden while ANY flag has `status` in (`active`, `extended`). `is_flagged` only set to `false` when the last active/extended flag resolves/expires.
- **Flag + index rebuild**: `search_indexer.py` checks `file_flags` during indexing and sets `is_flagged=true` for any file with an active/extended flag. Flag state survives re-indexing.
- **Blocklist dual-match**: Scanner checks both `content_hash` and `source_path` against `blocklisted_files`. A file can be blocklisted by hash (catches copies) or by path (catches re-appearances).
- **Flag routes ordering**: In `api/routes/flags.py`, fixed-path routes (`/mine`, `/stats`, `/blocklist`, `/lookup-source`) must be defined BEFORE `/{flag_id}` catch-all, or FastAPI matches the literal path segment as a flag_id.
```

- [ ] **Step 2: Update `docs/version-history.md`** with v0.16.0 entry

- [ ] **Step 3: Update `docs/key-files.md`** with new files

- [ ] **Step 4: Update `docs/gotchas.md`** with new entries

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/version-history.md docs/key-files.md docs/gotchas.md
git commit -m "docs: update all project docs for v0.16.0 file flagging"
```

---

## Execution Notes

**Route ordering matters:** In `api/routes/flags.py`, put `/mine`, `/stats`, `/blocklist`, `/lookup-source` routes BEFORE the `/{flag_id}` route. FastAPI matches routes top-to-bottom, so `GET /api/flags/stats` would match `/{flag_id}` with `flag_id="stats"` if ordered wrong.

**Meilisearch index settings update:** After deploying, Meilisearch needs to re-process index settings. The `ensure_indexes()` call in `SearchIndexer.__init__` handles this on startup. A full index rebuild (`POST /api/search/rebuild`) will populate `is_flagged` on all existing documents.

**httpx dependency:** The webhook uses `httpx`. Check if it's already in `requirements.txt`. If not, add it. (It likely is, as FastAPI projects commonly include it.)

**The `role_satisfies` import in search.py:** It's already available from `core.auth` — just import it at the top of the file alongside the existing auth imports.
