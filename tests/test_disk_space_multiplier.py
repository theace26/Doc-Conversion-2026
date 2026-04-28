"""Tests for the bulk-worker disk-space pre-check multiplier.

Spec: v0.34.3 fix for BUG-011 — replace the hardcoded `× 3` with an
env-configurable float defaulting to 0.5. Empirically, doc-to-markdown
conversion produces output well under 50% of input size; the legacy
multiplier of 3 silently rejected every auto-conversion job once total
source size exceeded ~33% of free output volume.
"""
from __future__ import annotations
import pytest

from core.bulk_worker import (
    _DISK_SPACE_MULTIPLIER_DEFAULT,
    _get_disk_space_multiplier,
)


def test_default_is_half(monkeypatch):
    """Unset env var → 0.5 (the default)."""
    monkeypatch.delenv("DISK_SPACE_MULTIPLIER", raising=False)
    assert _get_disk_space_multiplier() == 0.5
    assert _DISK_SPACE_MULTIPLIER_DEFAULT == 0.5


def test_override_with_valid_float(monkeypatch):
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "1.5")
    assert _get_disk_space_multiplier() == 1.5


def test_override_with_integer_string(monkeypatch):
    """Integer-formatted strings are accepted and parsed as floats."""
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "2")
    assert _get_disk_space_multiplier() == 2.0


def test_override_with_small_value(monkeypatch):
    """Tiny multipliers are honored — operator may know their conversion
    output ratio is genuinely small (e.g., archive-only workflow)."""
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "0.1")
    assert _get_disk_space_multiplier() == 0.1


def test_zero_falls_back_to_default(monkeypatch):
    """A zero multiplier would skip the check entirely — defensive: treat
    as user error and use the default."""
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "0")
    assert _get_disk_space_multiplier() == _DISK_SPACE_MULTIPLIER_DEFAULT


def test_negative_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "-1.5")
    assert _get_disk_space_multiplier() == _DISK_SPACE_MULTIPLIER_DEFAULT


def test_non_numeric_falls_back_to_default(monkeypatch):
    """Garbage values don't crash — fall back so the pre-check still runs."""
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "not_a_number")
    assert _get_disk_space_multiplier() == _DISK_SPACE_MULTIPLIER_DEFAULT


def test_empty_string_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "")
    assert _get_disk_space_multiplier() == _DISK_SPACE_MULTIPLIER_DEFAULT


def test_whitespace_falls_back_to_default(monkeypatch):
    """Pure-whitespace value (rare but possible from broken .env loaders)."""
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "   ")
    assert _get_disk_space_multiplier() == _DISK_SPACE_MULTIPLIER_DEFAULT


def test_per_call_read_not_import_snapshot(monkeypatch):
    """Each call must re-read the env var so runtime config changes take
    effect without restarting the process. Mirrors the v0.34.x lesson on
    output-path resolution (see CLAUDE.md → Architecture Reminders →
    'never capture as a module-level constant')."""
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "2.0")
    assert _get_disk_space_multiplier() == 2.0
    monkeypatch.setenv("DISK_SPACE_MULTIPLIER", "0.7")
    assert _get_disk_space_multiplier() == 0.7
