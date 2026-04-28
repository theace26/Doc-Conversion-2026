"""Unit tests for core.llm_costs (v0.33.1).

Covers:
- Schema validation (rejects bad shape, accepts good)
- estimate_cost arithmetic (known model -> known cost; unknown -> null;
  ollama wildcard -> 0.0)
- aggregate_batch_cost (mixed actual + estimated extrapolation)
- aggregate_period_cost cycle window logic
- Billing cycle window edge cases (start_day=31 -> capped to 28; today <
  start_day -> rolls back a month; year boundary)
- is_data_stale freshness threshold
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import llm_costs as lc


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_cache():
    """Clear the module-level cache before each test."""
    lc._CACHE = None
    yield
    lc._CACHE = None


@pytest.fixture
def sample_payload() -> dict:
    return {
        "schema_version": 1,
        "updated_at": "2026-04-28",
        "source_url": "https://example.com/pricing",
        "notes": "Test rates",
        "providers": {
            "anthropic": {
                "claude-opus-4-7": {
                    "input_per_million_usd": 15.0,
                    "output_per_million_usd": 75.0,
                },
                "claude-sonnet-4-6": {
                    "input_per_million_usd": 3.0,
                    "output_per_million_usd": 15.0,
                },
            },
            "ollama": {
                "*": {
                    "input_per_million_usd": 0.0,
                    "output_per_million_usd": 0.0,
                },
            },
        },
    }


@pytest.fixture
def loaded_table(tmp_path, sample_payload, monkeypatch) -> Path:
    """Write a sample JSON file and load it; returns the file path."""
    p = tmp_path / "llm_costs.json"
    p.write_text(json.dumps(sample_payload))
    monkeypatch.setattr(lc, "_DATA_FILE", p)
    lc.load_costs()
    return p


# ── Schema validation ────────────────────────────────────────────────────────


def test_load_rejects_wrong_schema_version(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99, "providers": {}}))
    monkeypatch.setattr(lc, "_DATA_FILE", bad)
    with pytest.raises(ValueError, match="schema_version"):
        lc.load_costs(strict=True)


def test_load_soft_fails_on_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "_DATA_FILE", tmp_path / "missing.json")
    table = lc.load_costs(strict=False)
    assert table.schema_version == 0
    assert table.rates == {}


def test_load_skips_negative_rates(tmp_path, monkeypatch):
    payload = {
        "schema_version": 1,
        "providers": {
            "openai": {
                "good": {"input_per_million_usd": 1.0, "output_per_million_usd": 2.0},
                "bad":  {"input_per_million_usd": -1.0, "output_per_million_usd": 2.0},
            }
        },
    }
    p = tmp_path / "neg.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(lc, "_DATA_FILE", p)
    table = lc.load_costs()
    assert "good" in table.rates["openai"]
    assert "bad" not in table.rates["openai"]


# ── estimate_cost arithmetic ─────────────────────────────────────────────────


def test_estimate_cost_anthropic_opus(loaded_table):
    # 1M tokens at blended (15+75)/2 = 45 USD
    est = lc.estimate_cost("anthropic", "claude-opus-4-7", 1_000_000)
    assert est.cost_usd == pytest.approx(45.0)
    assert est.rate_used is not None
    assert est.rate_used.model == "claude-opus-4-7"


def test_estimate_cost_partial_million(loaded_table):
    # 100k tokens at blended 45 -> 4.5 USD
    est = lc.estimate_cost("anthropic", "claude-opus-4-7", 100_000)
    assert est.cost_usd == pytest.approx(4.5)


def test_estimate_cost_unknown_model(loaded_table):
    est = lc.estimate_cost("anthropic", "claude-fictional-9000", 1_000_000)
    assert est.cost_usd is None
    assert est.error is not None
    assert "rate not configured" in est.error


def test_estimate_cost_ollama_wildcard_zero(loaded_table):
    est = lc.estimate_cost("ollama", "llava:7b", 100_000)
    assert est.cost_usd == 0.0
    assert est.rate_used is not None
    # Wildcard match -> model name from the table is "*", not the requested model
    assert est.rate_used.model == "*"


def test_estimate_cost_null_tokens(loaded_table):
    est = lc.estimate_cost("anthropic", "claude-opus-4-7", None)
    assert est.cost_usd is None
    assert est.error == "tokens_used is null"


def test_estimate_cost_no_provider(loaded_table):
    est = lc.estimate_cost(None, None, 1000)
    assert est.cost_usd is None


# ── aggregate_batch_cost ─────────────────────────────────────────────────────


def test_aggregate_batch_cost_all_analysed(loaded_table):
    rows = [
        {"id": "r1", "source_path": "/a.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 100_000},
        {"id": "r2", "source_path": "/b.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 200_000},
    ]
    summary = lc.aggregate_batch_cost("batch_xyz", rows)
    assert summary.total_files == 2
    assert summary.files_with_tokens == 2
    assert summary.files_estimated == 0
    assert summary.actual_tokens == 300_000
    assert summary.actual_cost_usd == pytest.approx(13.5)  # 0.3M * 45
    assert summary.estimated_cost_usd == 0
    assert summary.total_cost_usd == pytest.approx(13.5)


def test_aggregate_batch_cost_extrapolation(loaded_table):
    # 2 analysed (avg 150k tokens, $6.75 each), 3 pending -> extrapolate
    rows = [
        {"id": "r1", "source_path": "/a.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 100_000},
        {"id": "r2", "source_path": "/b.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 200_000},
        {"id": "r3", "source_path": "/c.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": None},
        {"id": "r4", "source_path": "/d.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": None},
        {"id": "r5", "source_path": "/e.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": None},
    ]
    summary = lc.aggregate_batch_cost("batch_mix", rows)
    assert summary.total_files == 5
    assert summary.files_with_tokens == 2
    assert summary.files_estimated == 3
    # 2 analysed: 100k + 200k = 300k tokens -> $13.5; avg per file 150k / $6.75
    # 3 estimated: 3 * 150k = 450k tokens -> 3 * $6.75 = $20.25
    assert summary.actual_cost_usd == pytest.approx(13.5)
    assert summary.estimated_cost_usd == pytest.approx(20.25)
    assert summary.total_cost_usd == pytest.approx(33.75)
    # All 5 FileCost rows present, with the estimated ones promoted
    estimated_files = [f for f in summary.files if f.estimated]
    assert len(estimated_files) == 3
    for f in estimated_files:
        assert f.cost_usd == pytest.approx(6.75)
        assert f.tokens_used == 150_000


def test_aggregate_batch_cost_zero_analysed(loaded_table):
    """A batch with no analysed rows yet should not crash; estimates stay None."""
    rows = [
        {"id": "r1", "source_path": "/a.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": None},
        {"id": "r2", "source_path": "/b.jpg",
         "provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": None},
    ]
    summary = lc.aggregate_batch_cost("batch_zero", rows)
    assert summary.total_files == 2
    assert summary.files_with_tokens == 0
    assert summary.files_estimated == 2
    assert summary.actual_cost_usd == 0
    assert summary.estimated_cost_usd == 0
    assert summary.total_cost_usd == 0


# ── Billing cycle window math ────────────────────────────────────────────────


def test_cycle_window_today_after_start_day():
    # Today is April 15, cycle starts day 1 -> April 1 to May 1
    today = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    start, end, label, into, total, remaining = lc.compute_billing_cycle_window(1, today=today)
    assert start.month == 4 and start.day == 1
    assert end.month == 5 and end.day == 1
    assert "April 2026" in label
    assert into == 14 or into == 15  # depending on rounding


def test_cycle_window_today_before_start_day():
    # Today is April 5, cycle starts day 15 -> March 15 to April 15
    today = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)
    start, end, _, _, _, _ = lc.compute_billing_cycle_window(15, today=today)
    assert start.month == 3 and start.day == 15
    assert end.month == 4 and end.day == 15


def test_cycle_window_year_boundary():
    # Today is January 5, cycle starts day 15 -> December 15 (prev year)
    today = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    start, end, _, _, _, _ = lc.compute_billing_cycle_window(15, today=today)
    assert start.year == 2025 and start.month == 12 and start.day == 15
    assert end.year == 2026 and end.month == 1 and end.day == 15


def test_cycle_window_clamps_high_start_day():
    # start_day=31 should clamp to 28 to avoid February edge case
    today = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    start, _, _, _, _, _ = lc.compute_billing_cycle_window(31, today=today)
    assert start.day == 28


def test_cycle_window_clamps_low_start_day():
    today = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
    start, _, _, _, _, _ = lc.compute_billing_cycle_window(0, today=today)
    assert start.day == 1


# ── aggregate_period_cost ────────────────────────────────────────────────────


def test_aggregate_period_filters_outside_window(loaded_table):
    today = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    rows = [
        # In window (April 1-30)
        {"provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 1_000_000, "analyzed_at": "2026-04-15T10:00:00+00:00"},
        # Out of window (March)
        {"provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 1_000_000, "analyzed_at": "2026-03-15T10:00:00+00:00"},
    ]
    summary = lc.aggregate_period_cost(rows, cycle_start_day=1, today=today)
    assert summary.file_count == 1
    assert summary.total_tokens == 1_000_000
    assert summary.total_cost_usd == pytest.approx(45.0)


def test_aggregate_period_projection(loaded_table):
    today = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)  # 9-10 days into cycle
    rows = [
        {"provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 1_000_000, "analyzed_at": "2026-04-05T10:00:00+00:00"},
    ]
    summary = lc.aggregate_period_cost(rows, cycle_start_day=1, today=today)
    # 45 USD spent in ~9 days; projected to 30 days ~ 150 USD
    assert summary.projected_full_cycle_cost_usd > summary.total_cost_usd
    # With 9 days into cycle and total 30 days: 45/9*30 = 150
    expected = (summary.total_cost_usd / summary.days_into_cycle) * summary.days_total
    assert summary.projected_full_cycle_cost_usd == pytest.approx(round(expected, 6))


def test_aggregate_period_by_provider_breakdown(loaded_table):
    today = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    rows = [
        {"provider_id": "anthropic", "model": "claude-opus-4-7",
         "tokens_used": 1_000_000, "analyzed_at": "2026-04-05T10:00:00+00:00"},
        {"provider_id": "ollama", "model": "llava:7b",
         "tokens_used": 5_000_000, "analyzed_at": "2026-04-06T10:00:00+00:00"},
    ]
    summary = lc.aggregate_period_cost(rows, cycle_start_day=1, today=today)
    assert summary.by_provider.get("anthropic") == pytest.approx(45.0)
    assert summary.by_provider.get("ollama") == pytest.approx(0.0)


# ── Staleness check ─────────────────────────────────────────────────────────


def test_is_data_stale_recent(loaded_table):
    # Sample fixture has updated_at = today (2026-04-28). Threshold of
    # 10000 days -> definitely fresh.
    assert lc.is_data_stale(threshold_days=10_000) is False
    # Threshold of -1 forces stale=True regardless of file age, since
    # age.days is non-negative and the comparison is `age.days > threshold`.
    assert lc.is_data_stale(threshold_days=-1) is True


def test_is_data_stale_no_updated_at(tmp_path, monkeypatch):
    payload = {"schema_version": 1, "providers": {}}
    p = tmp_path / "no_date.json"
    p.write_text(json.dumps(payload))
    monkeypatch.setattr(lc, "_DATA_FILE", p)
    lc.load_costs()
    assert lc.is_data_stale() is True
