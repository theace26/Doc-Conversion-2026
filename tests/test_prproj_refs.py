"""Tests for the prproj_media_refs cross-reference subsystem.

Covers:
    - upsert replaces (not duplicates) on repeat
    - reverse lookup returns every project referencing a given media path
    - forward lookup returns every media ref for a given project
    - cascade delete on bulk_files row removal
    - sync entry point (handler-side) writes correctly

Author: v0.34.0 Phase 2.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import pytest


# ── Test DB setup ────────────────────────────────────────────────────────────


def _seed_test_db(db_path: Path) -> dict[str, str]:
    """Create a minimal schema mirroring the migration so tests work
    against an isolated DB without bringing the whole init_db pipeline.
    Returns a dict of seeded ids for cross-test reuse.
    """
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE bulk_jobs (id TEXT PRIMARY KEY);
        CREATE TABLE bulk_files (
            id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            source_path TEXT NOT NULL UNIQUE
        );
        CREATE TABLE prproj_media_refs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES bulk_files(id) ON DELETE CASCADE,
            project_path TEXT NOT NULL,
            media_path TEXT NOT NULL,
            media_name TEXT,
            media_type TEXT,
            duration_ticks INTEGER,
            in_use_in_sequences TEXT,
            recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_refs_media_path  ON prproj_media_refs(media_path);
        CREATE INDEX idx_refs_project_id  ON prproj_media_refs(project_id);
    """)
    job_id = uuid.uuid4().hex
    conn.execute("INSERT INTO bulk_jobs (id) VALUES (?)", (job_id,))

    project_a_id = uuid.uuid4().hex
    project_b_id = uuid.uuid4().hex
    project_c_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO bulk_files (id, job_id, source_path) VALUES (?, ?, ?)",
        (project_a_id, job_id, "/projects/a.prproj"),
    )
    conn.execute(
        "INSERT INTO bulk_files (id, job_id, source_path) VALUES (?, ?, ?)",
        (project_b_id, job_id, "/projects/b.prproj"),
    )
    conn.execute(
        "INSERT INTO bulk_files (id, job_id, source_path) VALUES (?, ?, ?)",
        (project_c_id, job_id, "/projects/c.prproj"),
    )
    conn.commit()
    conn.close()
    return {
        "job_id": job_id,
        "project_a": project_a_id,
        "project_b": project_b_id,
        "project_c": project_c_id,
    }


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Set DB_PATH to an isolated test database with a minimal schema."""
    db_path = tmp_path / "test.db"
    seeded = _seed_test_db(db_path)
    monkeypatch.setenv("DB_PATH", str(db_path))
    return {"path": db_path, **seeded}


# ── Sync surface (handler-side) ──────────────────────────────────────────────


def test_upsert_sync_writes_refs(isolated_db):
    from core.db.prproj_refs import upsert_media_refs_sync

    n = upsert_media_refs_sync(
        project_path="/projects/a.prproj",
        refs=[
            {"media_path": "/clips/v1.mp4", "media_name": "v1.mp4", "media_type": "video"},
            {"media_path": "/clips/a1.wav", "media_name": "a1.wav", "media_type": "audio"},
        ],
    )
    assert n == 2

    conn = sqlite3.connect(str(isolated_db["path"]))
    cur = conn.execute(
        "SELECT COUNT(*) FROM prproj_media_refs WHERE project_id = ?",
        (isolated_db["project_a"],),
    )
    assert cur.fetchone()[0] == 2
    conn.close()


def test_upsert_sync_replaces_not_duplicates(isolated_db):
    """Calling upsert twice for the same project replaces the previous set."""
    from core.db.prproj_refs import upsert_media_refs_sync

    upsert_media_refs_sync(
        project_path="/projects/a.prproj",
        refs=[
            {"media_path": "/clips/v1.mp4", "media_name": "v1.mp4", "media_type": "video"},
            {"media_path": "/clips/v2.mp4", "media_name": "v2.mp4", "media_type": "video"},
        ],
    )
    n_second = upsert_media_refs_sync(
        project_path="/projects/a.prproj",
        refs=[
            {"media_path": "/clips/different.mp4", "media_name": "different.mp4", "media_type": "video"},
        ],
    )
    assert n_second == 1

    # Total rows for project A should now be 1 — the prior 2 were replaced.
    conn = sqlite3.connect(str(isolated_db["path"]))
    cur = conn.execute(
        "SELECT COUNT(*) FROM prproj_media_refs WHERE project_id = ?",
        (isolated_db["project_a"],),
    )
    assert cur.fetchone()[0] == 1
    cur = conn.execute(
        "SELECT media_path FROM prproj_media_refs WHERE project_id = ?",
        (isolated_db["project_a"],),
    )
    paths = [r[0] for r in cur.fetchall()]
    assert paths == ["/clips/different.mp4"]
    conn.close()


def test_upsert_sync_no_bulk_row_returns_zero(isolated_db):
    """If no bulk_files row exists for the project_path, return 0 silently."""
    from core.db.prproj_refs import upsert_media_refs_sync

    n = upsert_media_refs_sync(
        project_path="/projects/never_indexed.prproj",
        refs=[{"media_path": "/clips/x.mp4"}],
    )
    assert n == 0


# ── Async surface (FastAPI route consumers) ──────────────────────────────────


@pytest.mark.asyncio
async def test_reverse_lookup_3_projects_one_clip(isolated_db, monkeypatch):
    """Three projects all reference one clip — reverse lookup returns 3."""
    from core.db.prproj_refs import (
        upsert_media_refs_sync,
        get_projects_referencing,
    )

    SHARED = "/clips/shared.mp4"
    for project_path in (
        "/projects/a.prproj",
        "/projects/b.prproj",
        "/projects/c.prproj",
    ):
        upsert_media_refs_sync(
            project_path=project_path,
            refs=[{"media_path": SHARED, "media_name": "shared.mp4", "media_type": "video"}],
        )

    # Force the async helper to use our test DB. The async helpers go
    # through the connection pool, so we need to point that at our DB
    # too. We do this by importing pool, initialising it, and then
    # tearing down after.
    from core.db.pool import init_pool, shutdown_pool

    await shutdown_pool()  # defensive: clear any pre-existing pool from session-scoped fixtures
    await init_pool(str(isolated_db["path"]))
    try:
        results = await get_projects_referencing(SHARED)
    finally:
        await shutdown_pool()

    assert len(results) == 3
    project_paths = sorted(r["project_path"] for r in results)
    assert project_paths == [
        "/projects/a.prproj",
        "/projects/b.prproj",
        "/projects/c.prproj",
    ]


@pytest.mark.asyncio
async def test_forward_lookup_returns_all_media(isolated_db):
    """Project with N media → forward lookup returns all N."""
    from core.db.prproj_refs import (
        upsert_media_refs_sync,
        get_media_for_project,
    )
    from core.db.pool import init_pool, shutdown_pool

    refs = [
        {"media_path": f"/clips/c{i:03d}.mp4", "media_name": f"c{i:03d}.mp4",
         "media_type": "video"}
        for i in range(15)
    ]
    upsert_media_refs_sync(project_path="/projects/a.prproj", refs=refs)

    await shutdown_pool()  # defensive: clear any pre-existing pool from session-scoped fixtures
    await init_pool(str(isolated_db["path"]))
    try:
        media = await get_media_for_project(isolated_db["project_a"])
    finally:
        await shutdown_pool()

    assert len(media) == 15


@pytest.mark.asyncio
async def test_cascade_delete_on_project_removal(isolated_db):
    """Deleting the bulk_files row cascades into prproj_media_refs."""
    from core.db.prproj_refs import upsert_media_refs_sync
    from core.db.pool import init_pool, shutdown_pool

    upsert_media_refs_sync(
        project_path="/projects/a.prproj",
        refs=[{"media_path": "/clips/v1.mp4", "media_name": "v1.mp4",
               "media_type": "video"}],
    )

    conn = sqlite3.connect(str(isolated_db["path"]))
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.execute(
        "SELECT COUNT(*) FROM prproj_media_refs WHERE project_id = ?",
        (isolated_db["project_a"],),
    )
    before = cur.fetchone()[0]
    assert before == 1

    conn.execute("DELETE FROM bulk_files WHERE id = ?", (isolated_db["project_a"],))
    conn.commit()

    cur = conn.execute(
        "SELECT COUNT(*) FROM prproj_media_refs WHERE project_id = ?",
        (isolated_db["project_a"],),
    )
    after = cur.fetchone()[0]
    assert after == 0
    conn.close()


@pytest.mark.asyncio
async def test_stats_aggregates(isolated_db):
    from core.db.prproj_refs import upsert_media_refs_sync, stats
    from core.db.pool import init_pool, shutdown_pool

    upsert_media_refs_sync(
        project_path="/projects/a.prproj",
        refs=[
            {"media_path": "/clips/shared.mp4", "media_type": "video"},
            {"media_path": "/clips/uniq_a.mp4", "media_type": "video"},
        ],
    )
    upsert_media_refs_sync(
        project_path="/projects/b.prproj",
        refs=[
            {"media_path": "/clips/shared.mp4", "media_type": "video"},
            {"media_path": "/clips/uniq_b.mp4", "media_type": "video"},
        ],
    )

    await shutdown_pool()  # defensive: clear any pre-existing pool from session-scoped fixtures
    await init_pool(str(isolated_db["path"]))
    try:
        s = await stats()
    finally:
        await shutdown_pool()

    assert s["n_projects"] == 2
    assert s["n_media_refs"] == 4
    # The shared clip should top the list
    assert s["top_5_most_referenced"][0]["media_path"] == "/clips/shared.mp4"
    assert s["top_5_most_referenced"][0]["n_projects"] == 2
