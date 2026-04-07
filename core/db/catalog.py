"""
Adobe index, locations, LLM providers, unrecognized files, and archive members.
"""

import json
import uuid
from typing import Any

from core.db.connection import (
    db_fetch_all,
    db_fetch_one,
    db_execute,
    get_db,
    now_iso,
)


# ── Adobe index helpers ──────────────────────────────────────────────────────

async def upsert_adobe_index(
    source_path: str,
    file_ext: str,
    file_size_bytes: int,
    metadata: dict | None,
    text_layers: list[str] | None,
) -> str:
    """Insert or update an adobe_index record. Returns entry id."""
    metadata_json = json.dumps(metadata) if metadata else None
    text_json = json.dumps(text_layers) if text_layers else None
    now = now_iso()
    entry_id = uuid.uuid4().hex

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO adobe_index
               (id, source_path, file_ext, file_size_bytes, metadata, text_layers,
                indexing_level, meili_indexed, indexed_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_path) DO UPDATE SET
                 file_ext=excluded.file_ext,
                 file_size_bytes=excluded.file_size_bytes,
                 metadata=excluded.metadata,
                 text_layers=excluded.text_layers,
                 updated_at=excluded.updated_at,
                 meili_indexed=0""",
            (entry_id, source_path, file_ext, file_size_bytes,
             metadata_json, text_json, 2, 0, now, now),
        )
        async with conn.execute(
            "SELECT id FROM adobe_index WHERE source_path=?", (source_path,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                entry_id = row["id"]
        await conn.commit()
    return entry_id


async def get_adobe_index_entry(source_path: str) -> dict[str, Any] | None:
    row = await db_fetch_one(
        "SELECT * FROM adobe_index WHERE source_path=?", (source_path,)
    )
    if row:
        if isinstance(row.get("metadata"), str):
            row["metadata"] = json.loads(row["metadata"])
        if isinstance(row.get("text_layers"), str):
            row["text_layers"] = json.loads(row["text_layers"])
    return row


async def get_unindexed_adobe_entries(limit: int = 100) -> list[dict[str, Any]]:
    """Return adobe_index entries not yet indexed in Meilisearch."""
    rows = await db_fetch_all(
        "SELECT * FROM adobe_index WHERE meili_indexed=0 LIMIT ?", (limit,)
    )
    for row in rows:
        if isinstance(row.get("metadata"), str):
            row["metadata"] = json.loads(row["metadata"])
        if isinstance(row.get("text_layers"), str):
            row["text_layers"] = json.loads(row["text_layers"])
    return rows


async def mark_adobe_meili_indexed(entry_id: str) -> None:
    """Mark an adobe_index entry as indexed in Meilisearch."""
    async with get_db() as conn:
        await conn.execute(
            "UPDATE adobe_index SET meili_indexed=1 WHERE id=?", (entry_id,)
        )
        await conn.commit()


# ── Location helpers ────────────────────────────────────────────────────────

async def create_location(
    name: str, path: str, type_: str, notes: str | None = None
) -> str:
    """Insert a new location. Returns id. Raises ValueError if name exists."""
    existing = await db_fetch_one(
        "SELECT id FROM locations WHERE name = ?", (name,)
    )
    if existing:
        raise ValueError(f"Location name already exists: {name}")

    location_id = uuid.uuid4().hex
    now = now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO locations (id, name, path, type, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (location_id, name, path, type_, notes, now, now),
        )
        await conn.commit()
    return location_id


async def get_location(location_id: str) -> dict[str, Any] | None:
    """Return a single location by id."""
    return await db_fetch_one("SELECT * FROM locations WHERE id = ?", (location_id,))


async def list_locations(type_filter: str | None = None) -> list[dict[str, Any]]:
    """Return all locations, optionally filtered by type."""
    if type_filter and type_filter in ("source", "output"):
        return await db_fetch_all(
            "SELECT * FROM locations WHERE type = ? OR type = 'both' ORDER BY name",
            (type_filter,),
        )
    elif type_filter == "both":
        return await db_fetch_all(
            "SELECT * FROM locations WHERE type = 'both' ORDER BY name"
        )
    return await db_fetch_all("SELECT * FROM locations ORDER BY name")


async def update_location(location_id: str, **fields) -> None:
    """Update name, path, type, or notes. Raises ValueError if new name conflicts."""
    if not fields:
        return

    if "name" in fields:
        existing = await db_fetch_one(
            "SELECT id FROM locations WHERE name = ? AND id != ?",
            (fields["name"], location_id),
        )
        if existing:
            raise ValueError(f"Location name already exists: {fields['name']}")

    fields["updated_at"] = now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [location_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE locations SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def delete_location(location_id: str) -> None:
    """Delete a location by id."""
    async with get_db() as conn:
        await conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
        await conn.commit()


# ── Location exclusion helpers ─────────────────────────────────────────────

async def create_exclusion(
    name: str, path: str, notes: str | None = None
) -> str:
    """Insert a new exclusion. Returns id. Raises ValueError if name exists."""
    existing = await db_fetch_one(
        "SELECT id FROM location_exclusions WHERE name = ?", (name,)
    )
    if existing:
        raise ValueError(f"Exclusion name already exists: {name}")

    exclusion_id = uuid.uuid4().hex
    now = now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO location_exclusions (id, name, path, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,?)""",
            (exclusion_id, name, path, notes, now, now),
        )
        await conn.commit()
    return exclusion_id


async def get_exclusion(exclusion_id: str) -> dict[str, Any] | None:
    """Return a single exclusion by id."""
    return await db_fetch_one("SELECT * FROM location_exclusions WHERE id = ?", (exclusion_id,))


async def list_exclusions() -> list[dict[str, Any]]:
    """Return all exclusions ordered by name."""
    return await db_fetch_all("SELECT * FROM location_exclusions ORDER BY name")


async def update_exclusion(exclusion_id: str, **fields) -> None:
    """Update name, path, or notes. Raises ValueError if new name conflicts."""
    if not fields:
        return

    if "name" in fields:
        existing = await db_fetch_one(
            "SELECT id FROM location_exclusions WHERE name = ? AND id != ?",
            (fields["name"], exclusion_id),
        )
        if existing:
            raise ValueError(f"Exclusion name already exists: {fields['name']}")

    fields["updated_at"] = now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [exclusion_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE location_exclusions SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def delete_exclusion(exclusion_id: str) -> None:
    """Delete an exclusion by id."""
    async with get_db() as conn:
        await conn.execute("DELETE FROM location_exclusions WHERE id = ?", (exclusion_id,))
        await conn.commit()


async def get_exclusion_paths() -> list[str]:
    """Return all exclusion paths (for scanner filtering)."""
    rows = await db_fetch_all("SELECT path FROM location_exclusions ORDER BY path")
    return [r["path"] for r in rows]


# ── LLM provider helpers ────────────────────────────────────────────────────

async def create_llm_provider(
    name: str,
    provider: str,
    model: str,
    api_key: str | None = None,
    api_base_url: str | None = None,
) -> str:
    """Create an LLM provider record. Encrypts api_key. Returns id."""
    from core.crypto import encrypt_value

    provider_id = uuid.uuid4().hex
    now = now_iso()
    encrypted_key = encrypt_value(api_key) if api_key else None

    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO llm_providers
               (id, name, provider, model, api_key, api_base_url,
                is_active, is_verified, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (provider_id, name, provider, model, encrypted_key,
             api_base_url, 0, 0, now, now),
        )
        await conn.commit()
    return provider_id


async def get_llm_provider(provider_id: str) -> dict[str, Any] | None:
    """Return provider with api_key DECRYPTED."""
    row = await db_fetch_one(
        "SELECT * FROM llm_providers WHERE id = ?", (provider_id,)
    )
    if row and row.get("api_key"):
        from core.crypto import decrypt_value
        try:
            row["api_key"] = decrypt_value(row["api_key"])
        except Exception:
            row["api_key"] = None
    return row


async def list_llm_providers() -> list[dict[str, Any]]:
    """Return providers with api_key MASKED."""
    from core.crypto import mask_api_key

    rows = await db_fetch_all(
        "SELECT * FROM llm_providers ORDER BY is_active DESC, name ASC"
    )
    for row in rows:
        row["api_key"] = mask_api_key(row.get("api_key"))
    return rows


async def update_llm_provider(provider_id: str, **fields) -> None:
    """Update provider fields. Encrypts api_key if present."""
    if not fields:
        return
    if "api_key" in fields and fields["api_key"]:
        from core.crypto import encrypt_value
        fields["api_key"] = encrypt_value(fields["api_key"])
    fields["updated_at"] = now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [provider_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE llm_providers SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def delete_llm_provider(provider_id: str) -> None:
    """Delete a provider by id."""
    async with get_db() as conn:
        await conn.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
        await conn.commit()


async def set_active_provider(provider_id: str) -> None:
    """Set one provider as active, deactivate all others."""
    async with get_db() as conn:
        await conn.execute("UPDATE llm_providers SET is_active=0")
        await conn.execute(
            "UPDATE llm_providers SET is_active=1, updated_at=? WHERE id=?",
            (now_iso(), provider_id),
        )
        await conn.commit()


async def get_active_provider() -> dict[str, Any] | None:
    """Return the currently active provider with api_key DECRYPTED, or None."""
    row = await db_fetch_one(
        "SELECT * FROM llm_providers WHERE is_active=1"
    )
    if row and row.get("api_key"):
        from core.crypto import decrypt_value
        try:
            row["api_key"] = decrypt_value(row["api_key"])
        except Exception:
            row["api_key"] = None
    return row


async def get_ai_assist_provider() -> dict[str, Any] | None:
    """
    Return the provider that has been opted-in for AI Assist (the row with
    `use_for_ai_assist=1`), with `api_key` DECRYPTED. Returns None if no
    provider is opted in.

    This is INTENTIONALLY independent from `is_active` — the user may want
    AI Assist to use a different provider than the image scanner. (For
    example: image scanner uses a cheap Gemini provider for vision OCR,
    while AI Assist uses an Anthropic provider for natural-language
    synthesis.)
    """
    row = await db_fetch_one(
        "SELECT * FROM llm_providers WHERE use_for_ai_assist=1"
    )
    if row and row.get("api_key"):
        from core.crypto import decrypt_value
        try:
            row["api_key"] = decrypt_value(row["api_key"])
        except Exception:
            row["api_key"] = None
    return row


async def set_ai_assist_provider(provider_id: str | None) -> None:
    """
    Mark exactly one provider as the AI Assist provider, clearing the flag
    on all others. Pass `provider_id=None` to clear the flag everywhere
    (disable AI Assist provider routing entirely).
    """
    async with get_db() as conn:
        await conn.execute("UPDATE llm_providers SET use_for_ai_assist=0")
        if provider_id:
            await conn.execute(
                "UPDATE llm_providers SET use_for_ai_assist=1, updated_at=? WHERE id=?",
                (now_iso(), provider_id),
            )
        await conn.commit()


# ── Unrecognized file helpers ────────────────────────────────────────────

async def get_unrecognized_files(
    job_id: str | None = None,
    category: str | None = None,
    source_format: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    """Returns paginated unrecognized files with total count."""
    where = ["status='unrecognized'"]
    params: list[Any] = []
    if job_id:
        where.append("job_id=?")
        params.append(job_id)
    if category:
        where.append("file_category=?")
        params.append(category)
    if source_format:
        where.append("file_ext=?")
        params.append(source_format if source_format.startswith(".") else f".{source_format}")

    where_sql = " AND ".join(where)

    count_row = await db_fetch_one(
        f"SELECT COUNT(*) as cnt FROM bulk_files WHERE {where_sql}", tuple(params)
    )
    total = count_row["cnt"] if count_row else 0

    offset = (page - 1) * per_page
    rows = await db_fetch_all(
        f"SELECT * FROM bulk_files WHERE {where_sql} ORDER BY source_path LIMIT ? OFFSET ?",
        tuple(params) + (per_page, offset),
    )

    return {
        "files": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


async def get_unrecognized_stats(job_id: str | None = None) -> dict[str, Any]:
    """Returns summary statistics for unrecognized files."""
    where = "status='unrecognized'"
    params: list[Any] = []
    if job_id:
        where += " AND job_id=?"
        params.append(job_id)

    total_row = await db_fetch_one(
        f"SELECT COUNT(*) as cnt, COALESCE(SUM(file_size_bytes),0) as total_bytes FROM bulk_files WHERE {where}",
        tuple(params),
    )
    total = total_row["cnt"] if total_row else 0
    total_bytes = total_row["total_bytes"] if total_row else 0

    cat_rows = await db_fetch_all(
        f"SELECT file_category, COUNT(*) as cnt FROM bulk_files WHERE {where} GROUP BY file_category ORDER BY cnt DESC",
        tuple(params),
    )
    by_category = {r["file_category"]: r["cnt"] for r in cat_rows}

    fmt_rows = await db_fetch_all(
        f"SELECT file_ext, COUNT(*) as cnt FROM bulk_files WHERE {where} GROUP BY file_ext ORDER BY cnt DESC",
        tuple(params),
    )
    by_format = {r["file_ext"]: r["cnt"] for r in fmt_rows}

    job_rows = await db_fetch_all(
        f"SELECT DISTINCT job_id FROM bulk_files WHERE {where}",
        tuple(params),
    )
    job_ids = [r["job_id"] for r in job_rows]

    return {
        "total": total,
        "by_category": by_category,
        "by_format": by_format,
        "total_bytes": total_bytes,
        "job_ids": job_ids,
    }


# ── Archive member helpers ──────────────────────────────────────────────

async def upsert_archive_member(
    bulk_file_id: str,
    member_path: str,
    member_ext: str,
    member_size: int | None = None,
    member_modified_at: str | None = None,
    member_hash: str | None = None,
    is_directory: bool = False,
    is_archive: bool = False,
    nesting_depth: int = 0,
    parent_member_id: str | None = None,
) -> str:
    """Insert an archive_members record. Returns member id."""
    member_id = uuid.uuid4().hex
    now = now_iso()
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO archive_members
               (id, bulk_file_id, member_path, member_ext, member_size,
                member_modified_at, member_hash, is_directory, is_archive,
                nesting_depth, parent_member_id, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                member_id, bulk_file_id, member_path, member_ext,
                member_size, member_modified_at, member_hash,
                int(is_directory), int(is_archive),
                nesting_depth, parent_member_id, "pending", now, now,
            ),
        )
        await conn.commit()
    return member_id


async def update_archive_member(member_id: str, **fields) -> None:
    """Update any combination of archive_members fields."""
    if not fields:
        return
    fields["updated_at"] = now_iso()
    sets = [f"{k}=?" for k in fields]
    values = list(fields.values()) + [member_id]
    async with get_db() as conn:
        await conn.execute(
            f"UPDATE archive_members SET {', '.join(sets)} WHERE id=?", values
        )
        await conn.commit()


async def get_archive_members(
    bulk_file_id: str,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return archive members for a bulk file, optionally filtered by status."""
    sql = "SELECT * FROM archive_members WHERE bulk_file_id=?"
    params: list[Any] = [bulk_file_id]
    if status:
        sql += " AND status=?"
        params.append(status)
    sql += " ORDER BY member_path"
    return await db_fetch_all(sql, tuple(params))


async def get_archive_member_by_hash(content_hash: str) -> dict[str, Any] | None:
    """Find a converted archive member by content hash (for deduplication)."""
    return await db_fetch_one(
        """SELECT * FROM archive_members
           WHERE member_hash=? AND status='converted' AND output_path IS NOT NULL
           LIMIT 1""",
        (content_hash,),
    )


async def get_archive_member_count(bulk_file_id: str) -> dict[str, int]:
    """Return {pending, converted, error, total} counts for an archive's members."""
    rows = await db_fetch_all(
        "SELECT status, COUNT(*) AS cnt FROM archive_members WHERE bulk_file_id=? GROUP BY status",
        (bulk_file_id,),
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = row["cnt"]
    counts["total"] = sum(counts.values())
    return counts
