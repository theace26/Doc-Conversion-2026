"""
Tests for Task B2 analysis batch management functions (TDD — failing tests).

Functions exercised (to be implemented in `core/db/analysis.py`):
    - get_batches() -> list[dict]
    - get_batch_files(batch_id: str) -> list[dict]
    - exclude_files(file_ids: list[str]) -> int
    - cancel_all_batched() -> int

Batch status derivation rule (for get_batches()):
    Priority, first match wins:
      1. any row in batch has status == 'failed'    -> 'failed'
      2. any row in batch has status == 'batched'   -> 'batched'  (in flight)
      3. all rows in batch have status == 'completed' -> 'completed'
      4. all rows in batch have status == 'excluded' -> batch is hidden from
         get_batches() (cancelled batches don't show up)
      5. fallback                                   -> 'mixed'

Tests expect all four functions to be importable from core.db.analysis.
Until Task B2 lands, import will fail with ImportError — that's the point.
"""

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    import core.db.connection as conn_mod
    monkeypatch.setattr(conn_mod, "DB_PATH", tmp_path / "test.db")
    from core.db.schema import init_db
    await init_db()
    yield


async def _insert_source_file(sf_id: str, source_path: str, size: int, mtime: float) -> None:
    """Directly insert a source_files row via get_db() (pool not initialized in tests)."""
    from core.db.connection import get_db
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO source_files
               (id, source_path, file_ext, file_size_bytes, source_mtime)
               VALUES (?, ?, ?, ?, ?)""",
            (sf_id, source_path, ".jpg", size, mtime),
        )
        await conn.commit()


async def _set_status(entry_id: str, status: str) -> None:
    from core.db.connection import get_db
    async with get_db() as conn:
        await conn.execute(
            "UPDATE analysis_queue SET status = ? WHERE id = ?",
            (status, entry_id),
        )
        await conn.commit()


# ── get_batches() ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_batches_empty(db):
    from core.db.analysis import get_batches
    assert await get_batches() == []


@pytest.mark.asyncio
async def test_get_batches_groups_by_batch_id(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, get_batches

    # Batch 1: 3 files
    for i in range(3):
        await enqueue_for_analysis(f"/nas/photos/a{i}.jpg", content_hash=f"a{i}")
    await claim_pending_batch(batch_size=3)

    # Batch 2: 2 files
    for i in range(2):
        await enqueue_for_analysis(f"/nas/photos/b{i}.jpg", content_hash=f"b{i}")
    await claim_pending_batch(batch_size=2)

    batches = await get_batches()
    assert len(batches) == 2
    counts = sorted(b["file_count"] for b in batches)
    assert counts == [2, 3]
    for b in batches:
        assert "batch_id" in b
        assert "earliest_batched_at" in b
        assert "latest_batched_at" in b


@pytest.mark.asyncio
async def test_get_batches_total_size_bytes(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, get_batches

    await _insert_source_file("sf1", "/nas/photos/a.jpg", 1000, 1700000000.0)
    await _insert_source_file("sf2", "/nas/photos/b.jpg", 2500, 1700000000.0)

    await enqueue_for_analysis("/nas/photos/a.jpg", content_hash="a")
    await enqueue_for_analysis("/nas/photos/b.jpg", content_hash="b")
    await claim_pending_batch(batch_size=10)

    batches = await get_batches()
    assert len(batches) == 1
    assert batches[0]["total_size_bytes"] == 3500


@pytest.mark.asyncio
async def test_get_batches_derived_status_in_flight(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, get_batches

    for i in range(3):
        await enqueue_for_analysis(f"/nas/photos/m{i}.jpg", content_hash=f"m{i}")
    rows = await claim_pending_batch(batch_size=3)

    # Mark one row completed; the other two stay 'batched' -> batch is in flight.
    await _set_status(rows[0]["id"], "completed")

    batches = await get_batches()
    assert len(batches) == 1
    assert batches[0]["status"] == "batched"


# ── get_batch_files() ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_batch_files_returns_files_for_batch(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, get_batch_files

    for i in range(2):
        await enqueue_for_analysis(f"/nas/photos/a{i}.jpg", content_hash=f"a{i}")
    rows_a = await claim_pending_batch(batch_size=2)
    batch_a = rows_a[0]["batch_id"]

    for i in range(3):
        await enqueue_for_analysis(f"/nas/photos/b{i}.jpg", content_hash=f"b{i}")
    rows_b = await claim_pending_batch(batch_size=3)
    batch_b = rows_b[0]["batch_id"]

    files_a = await get_batch_files(batch_a)
    files_b = await get_batch_files(batch_b)

    assert len(files_a) == 2
    assert len(files_b) == 3
    paths_a = {f["source_path"] for f in files_a}
    assert paths_a == {"/nas/photos/a0.jpg", "/nas/photos/a1.jpg"}


@pytest.mark.asyncio
async def test_get_batch_files_joins_source_file_metadata(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, get_batch_files

    await _insert_source_file("sf1", "/nas/photos/x.jpg", 4242, 1700000123.0)
    await enqueue_for_analysis("/nas/photos/x.jpg", content_hash="x")
    rows = await claim_pending_batch(batch_size=1)
    batch_id = rows[0]["batch_id"]

    files = await get_batch_files(batch_id)
    assert len(files) == 1
    f = files[0]
    assert f["source_path"] == "/nas/photos/x.jpg"
    assert f["file_size_bytes"] == 4242
    assert f["source_mtime"] == 1700000123.0
    assert f["status"] == "batched"
    assert "batched_at" in f
    assert "enqueued_at" in f
    assert f["source_file_id"] == "sf1"


# ── exclude_files() ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exclude_files_marks_excluded(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, exclude_files
    from core.db.connection import db_fetch_all

    ids = []
    for i in range(3):
        eid = await enqueue_for_analysis(f"/nas/photos/x{i}.jpg", content_hash=f"x{i}")
        ids.append(eid)
    await claim_pending_batch(batch_size=3)

    n = await exclude_files([ids[0], ids[1]])
    assert n == 2

    rows = await db_fetch_all("SELECT id, status FROM analysis_queue")
    status_by_id = {r["id"]: r["status"] for r in rows}
    assert status_by_id[ids[0]] == "excluded"
    assert status_by_id[ids[1]] == "excluded"
    assert status_by_id[ids[2]] == "batched"
    excluded_count = sum(1 for r in rows if r["status"] == "excluded")
    assert excluded_count == 2


@pytest.mark.asyncio
async def test_exclude_files_returns_count(db):
    from core.db.analysis import enqueue_for_analysis, claim_pending_batch, exclude_files

    ids = []
    for i in range(2):
        eid = await enqueue_for_analysis(f"/nas/photos/y{i}.jpg", content_hash=f"y{i}")
        ids.append(eid)
    await claim_pending_batch(batch_size=2)

    # All real ids -> count equals len(ids).
    n_all = await exclude_files(ids)
    assert n_all == 2

    # Non-existent ids -> count less than input length (0 here, since both bogus).
    n_none = await exclude_files(["nonexistent-id-1", "nonexistent-id-2"])
    assert n_none == 0


# ── cancel_all_batched() ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_all_batched_resets_batched_rows(db):
    from core.db.analysis import (
        enqueue_for_analysis, claim_pending_batch, cancel_all_batched,
    )
    from core.db.connection import db_fetch_all

    for i in range(3):
        await enqueue_for_analysis(f"/nas/photos/c{i}.jpg", content_hash=f"c{i}")
    rows = await claim_pending_batch(batch_size=3)

    # Mark one row 'completed' — must NOT be touched by cancel_all_batched().
    completed_id = rows[0]["id"]
    await _set_status(completed_id, "completed")

    await cancel_all_batched()

    after = {r["id"]: r for r in await db_fetch_all("SELECT * FROM analysis_queue")}
    # Completed row untouched
    assert after[completed_id]["status"] == "completed"

    # Previously batched rows now pending with cleared batch metadata
    for r in rows[1:]:
        row = after[r["id"]]
        assert row["status"] == "pending"
        assert row["batch_id"] is None
        assert row["batched_at"] is None


@pytest.mark.asyncio
async def test_cancel_all_batched_returns_count(db):
    from core.db.analysis import (
        enqueue_for_analysis, claim_pending_batch, cancel_all_batched,
    )

    for i in range(4):
        await enqueue_for_analysis(f"/nas/photos/d{i}.jpg", content_hash=f"d{i}")
    rows = await claim_pending_batch(batch_size=4)

    # Mark one completed so only 3 remain 'batched'.
    await _set_status(rows[0]["id"], "completed")

    n = await cancel_all_batched()
    assert n == 3
