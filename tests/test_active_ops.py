"""Unit tests for core.active_ops — Active Operations Registry (v0.35.0)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

import pytest

from core.database import db_fetch_all, db_fetch_one


@pytest.mark.asyncio
async def test_migration_v29_creates_active_operations_table(client):
    """Migration v29 must create the table with the schema in spec §3.

    Depends on the session-scoped ``client`` fixture so ``init_db()`` runs
    (and applies all _MIGRATIONS) against the test temp DB before assertions.
    """
    # Schema check: table exists
    row = await db_fetch_one(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='active_operations'"
    )
    assert row is not None, "active_operations table not created"

    # Column shape (PRAGMA table_info returns rows of cid/name/type/...)
    cols = await db_fetch_all("PRAGMA table_info(active_operations)")
    col_map = {c["name"]: c["type"] for c in cols}

    expected = {
        "op_id": "TEXT",
        "op_type": "TEXT",
        "label": "TEXT",
        "icon": "TEXT",
        "origin_url": "TEXT",
        "started_by": "TEXT",
        "started_at_epoch": "REAL",
        "last_progress_at_epoch": "REAL",
        "finished_at_epoch": "REAL",
        "total": "INTEGER",
        "done": "INTEGER",
        "errors": "INTEGER",
        "error_msg": "TEXT",
        "cancelled": "INTEGER",
        "cancellable": "INTEGER",
        "cancel_url": "TEXT",
        "extra_json": "TEXT",
    }
    for col, typ in expected.items():
        assert col in col_map, f"missing column: {col}"
        assert col_map[col] == typ, (
            f"column {col} type mismatch: expected {typ}, got {col_map[col]}"
        )

    # Indexes — partial indexes for running and finished
    idx = await db_fetch_all(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='active_operations'"
    )
    idx_names = {r["name"] for r in idx}
    assert "idx_active_ops_running" in idx_names
    assert "idx_active_ops_finished_at" in idx_names
