"""Tests for core/db_backup.py — backup, restore, list backups."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    """Isolated DB + isolated backups dir, with pool initialized (needed for restore)."""
    db_path = tmp_path / "markflow.db"
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Patch DB_PATH everywhere it's imported
    import core.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", db_path)

    from core.db.schema import init_db
    await init_db()

    # Initialize the pool (restore needs to shut it down and reinit)
    from core.db import pool as pool_mod
    # Ensure clean slate
    if getattr(pool_mod, "_pool", None) is not None:
        await pool_mod.shutdown_pool()
    await pool_mod.init_pool(db_path, read_pool_size=2)

    # Patch BACKUPS_DIR in db_backup module
    import core.db_backup as backup_mod
    monkeypatch.setattr(backup_mod, "BACKUPS_DIR", backups_dir)
    monkeypatch.setattr(backup_mod, "DB_PATH", db_path)

    yield {"db_path": db_path, "backups_dir": backups_dir}

    # Teardown: shut down the pool if still running
    try:
        if getattr(pool_mod, "_pool", None) is not None:
            await pool_mod.shutdown_pool()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_backup_database_copies_file(db, monkeypatch):
    from core import db_backup
    monkeypatch.setattr(db_backup, "get_all_active_jobs", _fake_no_active_jobs)

    result = await db_backup.backup_database(download=False)
    assert result["ok"] is True
    assert Path(result["path"]).exists()
    assert result["size_bytes"] > 0
    assert result["generated_at"]
    # Filename convention
    assert Path(result["path"]).name.startswith("markflow-")
    assert Path(result["path"]).suffix == ".db"


@pytest.mark.asyncio
async def test_backup_database_refuses_during_bulk_job(db, monkeypatch):
    from core import db_backup

    async def fake_running():
        return [{"job_id": "x", "status": "running"}]

    monkeypatch.setattr(db_backup, "get_all_active_jobs", fake_running)
    result = await db_backup.backup_database(download=False)
    assert result["ok"] is False
    assert result["code"] == "bulk_jobs_active"
    assert "Bulk jobs active" in result["error"]


@pytest.mark.asyncio
async def test_list_backups_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    from core import db_backup
    missing = tmp_path / "nope"
    monkeypatch.setattr(db_backup, "BACKUPS_DIR", missing)
    result = await db_backup.list_backups()
    assert result == []


@pytest.mark.asyncio
async def test_list_backups_sorted_newest_first(db):
    from core import db_backup
    bdir = db["backups_dir"]
    f1 = bdir / "markflow-20260101-000000.db"
    f2 = bdir / "markflow-20260202-000000.db"
    f3 = bdir / "markflow-20260303-000000.db"
    for f in (f1, f2, f3):
        f.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    # Set mtimes explicitly (newest = f3)
    now = time.time()
    os.utime(f1, (now - 300, now - 300))
    os.utime(f2, (now - 200, now - 200))
    os.utime(f3, (now - 100, now - 100))

    result = await db_backup.list_backups()
    assert len(result) == 3
    assert result[0]["filename"] == "markflow-20260303-000000.db"
    assert result[2]["filename"] == "markflow-20260101-000000.db"
    for entry in result:
        assert "path" in entry
        assert "size_bytes" in entry
        assert "modified_at" in entry


@pytest.mark.asyncio
async def test_list_backups_ignores_non_matching(db):
    from core import db_backup
    bdir = db["backups_dir"]
    (bdir / "markflow-20260101-000000.db").write_bytes(b"x")
    (bdir / "somethingelse.db").write_bytes(b"x")
    (bdir / "markflow-20260101-000000.db-shm").write_bytes(b"x")
    result = await db_backup.list_backups()
    names = [r["filename"] for r in result]
    assert "markflow-20260101-000000.db" in names
    assert "somethingelse.db" not in names
    # .db-shm doesn't match markflow-*.db pattern
    assert not any(n.endswith("-shm") for n in names)


@pytest.mark.asyncio
async def test_restore_database_validates_integrity(db, monkeypatch):
    from core import db_backup
    monkeypatch.setattr(db_backup, "get_all_active_jobs", _fake_no_active_jobs)

    corrupt = db["backups_dir"] / "markflow-bogus.db"
    corrupt.write_bytes(b"this is not a sqlite database at all")

    result = await db_backup.restore_database(source_path=corrupt)
    assert result["ok"] is False
    assert result["code"] == "integrity_check_failed"
    assert "integrity" in result["error"].lower()


@pytest.mark.asyncio
async def test_restore_database_rotates_current_db(db, monkeypatch):
    from core import db_backup
    monkeypatch.setattr(db_backup, "get_all_active_jobs", _fake_no_active_jobs)

    # Insert a recognizable sentinel row BEFORE the backup so we can verify
    # the restored DB actually contains the data (not just an empty valid DB).
    live = db["db_path"]
    sentinel_key = "backup_test_marker"
    sentinel_val = "a3-sentinel"

    def _insert_sentinel():
        conn = sqlite3.connect(str(live))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS backup_test_sentinel "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO backup_test_sentinel (key, value) VALUES (?, ?)",
                (sentinel_key, sentinel_val),
            )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_insert_sentinel)

    # First take a valid backup of the live DB
    backup_result = await db_backup.backup_database(download=False)
    assert backup_result["ok"] is True
    backup_path = Path(backup_result["path"])

    # Now restore from it
    restore_result = await db_backup.restore_database(source_path=backup_path)
    assert restore_result["ok"] is True, restore_result
    rotated = Path(restore_result["rotated_to"])
    assert rotated.exists()
    assert ".pre-restore-" in rotated.name
    assert rotated.name.endswith(".bak")

    # Live DB still exists and is a valid sqlite file
    assert live.exists()
    conn = sqlite3.connect(str(live))
    try:
        cur = conn.execute("PRAGMA integrity_check")
        assert cur.fetchone()[0] == "ok"
        # Verify the sentinel row survived the backup -> restore round trip.
        cur = conn.execute(
            "SELECT value FROM backup_test_sentinel WHERE key = ?",
            (sentinel_key,),
        )
        row = cur.fetchone()
        assert row is not None, "sentinel row missing after restore"
        assert row[0] == sentinel_val
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_restore_database_refuses_during_bulk_job(db, monkeypatch):
    from core import db_backup

    async def fake_running():
        return [{"status": "scanning"}]

    monkeypatch.setattr(db_backup, "get_all_active_jobs", fake_running)
    # Need a candidate file — doesn't matter, should bail before integrity check
    candidate = db["backups_dir"] / "markflow-test.db"
    candidate.write_bytes(b"x")
    result = await db_backup.restore_database(source_path=candidate)
    assert result["ok"] is False
    assert result["code"] == "bulk_jobs_active"
    assert "Bulk jobs active" in result["error"]


@pytest.mark.asyncio
async def test_restore_requires_exactly_one_source(db, monkeypatch):
    from core import db_backup
    monkeypatch.setattr(db_backup, "get_all_active_jobs", _fake_no_active_jobs)

    with pytest.raises(ValueError):
        await db_backup.restore_database(source_path=None, uploaded_bytes=None)

    with pytest.raises(ValueError):
        await db_backup.restore_database(source_path=Path("a"), uploaded_bytes=b"x")


@pytest.mark.asyncio
async def test_backup_download_returns_file_response(db, monkeypatch):
    from core import db_backup
    from fastapi.responses import FileResponse

    monkeypatch.setattr(db_backup, "get_all_active_jobs", _fake_no_active_jobs)
    result = await db_backup.backup_database(download=True)
    assert isinstance(result, FileResponse)
    # FileResponse should have a filename attribute
    assert "markflow-" in result.filename


@pytest.mark.asyncio
async def test_restore_database_source_missing_code(db, monkeypatch):
    from core import db_backup
    monkeypatch.setattr(db_backup, "get_all_active_jobs", _fake_no_active_jobs)

    missing = db["backups_dir"] / "does-not-exist.db"
    result = await db_backup.restore_database(source_path=missing)
    assert result["ok"] is False
    assert result["code"] == "source_missing"


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _fake_no_active_jobs():
    return []
