"""LLM token-cost lookup, arithmetic, and period aggregation.

This module is the **single source of truth** for LLM cost data and
the **only place** that computes USD costs from token counts. Every
caller — UI route, background job, audit log — funnels through the
public surface below so a single rate-table edit propagates
consistently.

Public surface:

    load_costs() -> CostTable             # called once at startup
    reload_costs() -> CostTable           # admin-triggered hot reload
    get_costs() -> CostTable              # frozen accessor
    estimate_cost(provider, model, tokens) -> CostEstimate
    aggregate_batch_cost(rows) -> BatchCostSummary
    aggregate_period_cost(rows, cycle_start_day) -> PeriodCostSummary
    is_data_stale(threshold_days=90) -> bool

All return values are frozen dataclasses for thread-safety and JSON
serializability via `dataclasses.asdict`.

Defensive degradation: when cost data is missing for a provider/model
combo, callers receive `cost_usd=None` + a descriptive `error`
string rather than blanking or raising. Bad rate data on disk also
soft-fails to an empty CostTable so the app keeps serving requests.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import structlog

log = structlog.get_logger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "llm_costs.json"
_OLLAMA_WILDCARD_KEY = "*"

# ── Frozen dataclasses ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class TokenRate:
    provider: str
    model: str
    input_per_million_usd: float
    output_per_million_usd: float
    cache_write_per_million_usd: float | None = None
    cache_read_per_million_usd: float | None = None
    notes: str = ""

    def estimate_blended_per_million(self) -> float:
        """A 50/50 input/output blended rate. Used when the caller
        doesn't break tokens into input vs output (which is the
        current state of `analysis_queue.tokens_used`)."""
        return (self.input_per_million_usd + self.output_per_million_usd) / 2.0


@dataclass(frozen=True)
class CostEstimate:
    tokens_used: int
    cost_usd: float | None
    rate_used: TokenRate | None
    error: str | None = None


@dataclass(frozen=True)
class FileCost:
    """Per-row breakdown used by aggregate_batch_cost."""
    file_id: str
    source_path: str
    provider: str | None
    model: str | None
    tokens_used: int | None
    cost_usd: float | None
    estimated: bool
    error: str | None = None


@dataclass(frozen=True)
class BatchCostSummary:
    batch_id: str
    total_files: int
    files_with_tokens: int
    files_estimated: int
    actual_tokens: int
    estimated_tokens: int
    actual_cost_usd: float
    estimated_cost_usd: float
    total_cost_usd: float
    per_file_avg_tokens: float
    per_file_avg_cost_usd: float
    rates_used: list[TokenRate]
    files: list[FileCost]


@dataclass(frozen=True)
class PeriodCostSummary:
    cycle_start_iso: str
    cycle_end_iso: str
    cycle_label: str
    total_tokens: int
    total_cost_usd: float
    by_provider: dict[str, float]
    by_model: dict[str, float]
    file_count: int
    days_into_cycle: int
    days_total: int
    days_remaining: int
    projected_full_cycle_cost_usd: float
    rates_used: list[TokenRate]


@dataclass(frozen=True)
class CostTable:
    schema_version: int
    updated_at: str
    source_url: str
    notes: str
    rates: dict[str, dict[str, TokenRate]]  # provider -> model -> TokenRate

    def lookup(self, provider: str | None, model: str | None) -> TokenRate | None:
        if not provider:
            return None
        provider_rates = self.rates.get(provider.lower())
        if not provider_rates:
            return None
        if model:
            exact = provider_rates.get(model)
            if exact:
                return exact
        wildcard = provider_rates.get(_OLLAMA_WILDCARD_KEY)
        return wildcard


# ── Loader + module-level cache ──────────────────────────────────────────────

_CACHE: CostTable | None = None


def _empty_table() -> CostTable:
    return CostTable(schema_version=0, updated_at="", source_url="", notes="", rates={})


def _validate_and_build(payload: dict) -> CostTable:
    """Strict schema validation. Raises ValueError on a malformed
    top-level shape; logs warnings and skips individual bad rate rows
    rather than aborting the whole file (so one typo doesn't kill all
    cost reporting)."""
    if not isinstance(payload, dict):
        raise ValueError("llm_costs.json root must be an object")

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        raise ValueError(
            f"Unsupported llm_costs.json schema_version: {schema_version!r} "
            "(this build expects schema_version=1)"
        )

    providers_raw = payload.get("providers")
    if not isinstance(providers_raw, dict):
        raise ValueError("llm_costs.json 'providers' must be an object")

    rates: dict[str, dict[str, TokenRate]] = {}
    for provider, models in providers_raw.items():
        if not isinstance(models, dict):
            log.warning("llm_costs.bad_provider_block",
                        provider=provider, reason="not a dict")
            continue
        provider_key = provider.lower().strip()
        rates[provider_key] = {}
        for model, rate_dict in models.items():
            if not isinstance(rate_dict, dict):
                log.warning("llm_costs.bad_rate_row",
                            provider=provider, model=model, reason="not a dict")
                continue
            try:
                input_rate = float(rate_dict["input_per_million_usd"])
                output_rate = float(rate_dict["output_per_million_usd"])
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("llm_costs.bad_rate_row",
                            provider=provider, model=model, reason=str(exc))
                continue
            if input_rate < 0 or output_rate < 0:
                log.warning("llm_costs.negative_rate",
                            provider=provider, model=model,
                            input_rate=input_rate, output_rate=output_rate)
                continue
            cache_write = rate_dict.get("cache_write_per_million_usd")
            cache_read = rate_dict.get("cache_read_per_million_usd")
            try:
                cache_write_f = float(cache_write) if cache_write is not None else None
                cache_read_f = float(cache_read) if cache_read is not None else None
            except (TypeError, ValueError):
                cache_write_f = None
                cache_read_f = None
            rates[provider_key][model] = TokenRate(
                provider=provider_key,
                model=model,
                input_per_million_usd=input_rate,
                output_per_million_usd=output_rate,
                cache_write_per_million_usd=cache_write_f,
                cache_read_per_million_usd=cache_read_f,
                notes=str(rate_dict.get("notes", "")),
            )

    return CostTable(
        schema_version=schema_version,
        updated_at=str(payload.get("updated_at", "")),
        source_url=str(payload.get("source_url", "")),
        notes=str(payload.get("notes", "")),
        rates=rates,
    )


def load_costs(strict: bool = False, path: Path | None = None) -> CostTable:
    """Read llm_costs.json from disk and populate the module-level cache.

    Called once during app lifespan startup (after init_db). Failure to
    parse raises in `strict=True` mode (used by tests) but logs a warning
    and serves an empty table in production so the app keeps starting.
    """
    global _CACHE
    target = path or _DATA_FILE
    try:
        with target.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        _CACHE = _validate_and_build(payload)
        log.info(
            "llm_costs.loaded",
            schema_version=_CACHE.schema_version,
            updated_at=_CACHE.updated_at,
            providers=list(_CACHE.rates.keys()),
            total_rates=sum(len(m) for m in _CACHE.rates.values()),
        )
        return _CACHE
    except FileNotFoundError:
        log.warning("llm_costs.file_missing", path=str(target))
        if strict:
            raise
        _CACHE = _empty_table()
        return _CACHE
    except (ValueError, json.JSONDecodeError) as exc:
        log.warning("llm_costs.load_failed", path=str(target), error=str(exc))
        if strict:
            raise
        _CACHE = _empty_table()
        return _CACHE


def reload_costs() -> CostTable:
    """Re-read the JSON file from disk. Returns the freshly-loaded
    table; callers should compare `updated_at` to detect changes."""
    return load_costs()


def get_costs() -> CostTable:
    """Return the currently-cached CostTable. Calls `load_costs()`
    on first access if the cache hasn't been initialised yet (so
    tests can call this without a lifespan)."""
    global _CACHE
    if _CACHE is None:
        return load_costs()
    return _CACHE


# ── Cost arithmetic ──────────────────────────────────────────────────────────


def estimate_cost(
    provider: str | None,
    model: str | None,
    tokens_used: int | None,
) -> CostEstimate:
    """Compute USD cost for a given token count.

    Uses a 50/50 blended input/output rate because `analysis_queue`
    stores a single per-row token count (a per-image share of the
    batch's input+output total). Returns `cost_usd=None` with a
    descriptive `error` if the rate is unavailable or tokens is None.

    Emits a `llm_cost.computed` (or `llm_cost.no_rate`) audit log
    line for every call, regardless of result, so the calculation
    is traceable via the Log Viewer.
    """
    if tokens_used is None:
        log.info("llm_cost.no_tokens", provider=provider, model=model)
        return CostEstimate(
            tokens_used=0,
            cost_usd=None,
            rate_used=None,
            error="tokens_used is null",
        )

    table = get_costs()
    rate = table.lookup(provider, model)
    if rate is None:
        log.info(
            "llm_cost.no_rate",
            provider=provider,
            model=model,
            tokens_used=tokens_used,
        )
        return CostEstimate(
            tokens_used=tokens_used,
            cost_usd=None,
            rate_used=None,
            error=f"rate not configured for provider={provider!r} model={model!r}",
        )

    blended = rate.estimate_blended_per_million()
    cost = round((tokens_used / 1_000_000.0) * blended, 6)
    log.info(
        "llm_cost.computed",
        scope="row",
        provider=provider,
        model=model,
        tokens_used=tokens_used,
        cost_usd=cost,
    )
    return CostEstimate(tokens_used=tokens_used, cost_usd=cost, rate_used=rate)


def aggregate_batch_cost(
    batch_id: str,
    rows: list[dict],
) -> BatchCostSummary:
    """Aggregate a batch's per-row token usage into a cost summary.

    Each row dict must include `id`, `source_path`, optionally
    `provider_id`, `model`, and `tokens_used` (the per-image token
    share already populated by the analysis worker).

    Files without `tokens_used` are extrapolated using the batch's
    own per-file average (or marked as estimate_unavailable when no
    rows are analysed yet).
    """
    files: list[FileCost] = []
    actual_tokens = 0
    actual_cost = 0.0
    files_with_tokens = 0
    rates_seen: dict[str, TokenRate] = {}

    # First pass: real values
    for row in rows:
        provider = row.get("provider_id")
        model = row.get("model")
        tokens = row.get("tokens_used")
        if tokens is None:
            files.append(FileCost(
                file_id=row["id"],
                source_path=row.get("source_path", ""),
                provider=provider,
                model=model,
                tokens_used=None,
                cost_usd=None,
                estimated=True,
            ))
            continue
        est = estimate_cost(provider, model, tokens)
        if est.rate_used is not None:
            rates_seen[f"{est.rate_used.provider}/{est.rate_used.model}"] = est.rate_used
        cost_val = est.cost_usd or 0.0
        actual_tokens += tokens
        actual_cost += cost_val
        files_with_tokens += 1
        files.append(FileCost(
            file_id=row["id"],
            source_path=row.get("source_path", ""),
            provider=provider,
            model=model,
            tokens_used=tokens,
            cost_usd=est.cost_usd,
            estimated=False,
            error=est.error,
        ))

    # Second pass: extrapolate the unanalysed rows from the batch average
    files_estimated_count = sum(1 for f in files if f.estimated)
    estimated_tokens = 0
    estimated_cost = 0.0
    if files_with_tokens > 0:
        per_file_avg_tokens = actual_tokens / files_with_tokens
        per_file_avg_cost = actual_cost / files_with_tokens
        estimated_tokens = int(per_file_avg_tokens * files_estimated_count)
        estimated_cost = round(per_file_avg_cost * files_estimated_count, 6)
        # Promote each estimated FileCost with its average-derived values
        promoted: list[FileCost] = []
        for f in files:
            if f.estimated and f.tokens_used is None:
                promoted.append(FileCost(
                    file_id=f.file_id,
                    source_path=f.source_path,
                    provider=f.provider,
                    model=f.model,
                    tokens_used=int(per_file_avg_tokens),
                    cost_usd=round(per_file_avg_cost, 6),
                    estimated=True,
                    error="extrapolated from batch average",
                ))
            else:
                promoted.append(f)
        files = promoted
    else:
        per_file_avg_tokens = 0.0
        per_file_avg_cost = 0.0

    total_cost = round(actual_cost + estimated_cost, 6)
    total_files = len(rows)

    log.info(
        "llm_cost.computed",
        scope="batch",
        batch_id=batch_id,
        total_files=total_files,
        files_with_tokens=files_with_tokens,
        files_estimated=files_estimated_count,
        total_cost_usd=total_cost,
        rates_used=sorted(rates_seen.keys()),
    )

    return BatchCostSummary(
        batch_id=batch_id,
        total_files=total_files,
        files_with_tokens=files_with_tokens,
        files_estimated=files_estimated_count,
        actual_tokens=actual_tokens,
        estimated_tokens=estimated_tokens,
        actual_cost_usd=round(actual_cost, 6),
        estimated_cost_usd=estimated_cost,
        total_cost_usd=total_cost,
        per_file_avg_tokens=round(per_file_avg_tokens, 1),
        per_file_avg_cost_usd=round(per_file_avg_cost, 6),
        rates_used=list(rates_seen.values()),
        files=files,
    )


# ── Period (billing-cycle) aggregation ───────────────────────────────────────


def compute_billing_cycle_window(
    cycle_start_day: int,
    today: datetime | None = None,
) -> tuple[datetime, datetime, str, int, int, int]:
    """Return (cycle_start_dt, cycle_end_dt, label, days_into, days_total, days_remaining).

    cycle_start_day clamped to 1..28 (avoids February edge case).
    cycle_end_dt is exclusive — the moment the *next* cycle starts.
    """
    if cycle_start_day < 1:
        cycle_start_day = 1
    if cycle_start_day > 28:
        cycle_start_day = 28

    now = today or datetime.now(timezone.utc)

    if now.day >= cycle_start_day:
        cycle_start = now.replace(day=cycle_start_day, hour=0, minute=0,
                                  second=0, microsecond=0)
    else:
        # Roll back to previous month
        if now.month == 1:
            cycle_start = now.replace(year=now.year - 1, month=12,
                                      day=cycle_start_day,
                                      hour=0, minute=0, second=0, microsecond=0)
        else:
            cycle_start = now.replace(month=now.month - 1,
                                      day=cycle_start_day,
                                      hour=0, minute=0, second=0, microsecond=0)

    # End is the same day next month
    if cycle_start.month == 12:
        cycle_end = cycle_start.replace(year=cycle_start.year + 1, month=1)
    else:
        cycle_end = cycle_start.replace(month=cycle_start.month + 1)

    days_total = (cycle_end - cycle_start).days
    days_into = (now - cycle_start).days
    if days_into < 1:
        days_into = 1  # at least the first day
    days_remaining = max(0, days_total - days_into)

    label = f"{cycle_start.strftime('%B %Y')} (cycle starts day {cycle_start_day})"
    return cycle_start, cycle_end, label, days_into, days_total, days_remaining


def aggregate_period_cost(
    rows: list[dict],
    cycle_start_day: int,
    today: datetime | None = None,
) -> PeriodCostSummary:
    """Aggregate analysis_queue rows into a period (billing-cycle) summary.

    Each row should have `provider_id`, `model`, `tokens_used`, and
    `analyzed_at` (ISO string). Rows outside the current cycle are
    filtered here, so the caller can pass either a SQL-windowed result
    or the full `analysis_queue` table.
    """
    cycle_start, cycle_end, label, days_into, days_total, days_remaining = (
        compute_billing_cycle_window(cycle_start_day, today=today)
    )

    by_provider: dict[str, float] = {}
    by_model: dict[str, float] = {}
    total_tokens = 0
    total_cost = 0.0
    file_count = 0
    rates_seen: dict[str, TokenRate] = {}

    for row in rows:
        analyzed_at = row.get("analyzed_at")
        if not analyzed_at:
            continue
        try:
            # SQLite ISO strings may or may not have a TZ suffix.
            ts = analyzed_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue
        if dt < cycle_start or dt >= cycle_end:
            continue

        provider = row.get("provider_id")
        model = row.get("model")
        tokens = row.get("tokens_used")
        if tokens is None:
            continue

        est = estimate_cost(provider, model, tokens)
        if est.cost_usd is None:
            continue
        if est.rate_used is not None:
            rates_seen[f"{est.rate_used.provider}/{est.rate_used.model}"] = est.rate_used

        total_tokens += tokens
        total_cost += est.cost_usd
        file_count += 1
        prov_key = (provider or "unknown").lower()
        mod_key = f"{prov_key}/{model or 'unknown'}"
        by_provider[prov_key] = round(by_provider.get(prov_key, 0.0) + est.cost_usd, 6)
        by_model[mod_key] = round(by_model.get(mod_key, 0.0) + est.cost_usd, 6)

    total_cost = round(total_cost, 6)
    if days_into > 0:
        projected = round((total_cost / days_into) * days_total, 6)
    else:
        projected = 0.0

    log.info(
        "llm_cost.computed",
        scope="period",
        cycle_start_iso=cycle_start.isoformat(),
        cycle_end_iso=cycle_end.isoformat(),
        total_cost_usd=total_cost,
        file_count=file_count,
        rates_used=sorted(rates_seen.keys()),
    )

    return PeriodCostSummary(
        cycle_start_iso=cycle_start.isoformat(),
        cycle_end_iso=cycle_end.isoformat(),
        cycle_label=label,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        by_provider=by_provider,
        by_model=by_model,
        file_count=file_count,
        days_into_cycle=days_into,
        days_total=days_total,
        days_remaining=days_remaining,
        projected_full_cycle_cost_usd=projected,
        rates_used=list(rates_seen.values()),
    )


# ── Operational helpers (used by Phase 3 staleness check too) ────────────────


def is_data_stale(threshold_days: int = 90) -> bool:
    """Return True if the loaded rate table's `updated_at` is older
    than `threshold_days`. Used by the admin card warning banner and
    the Phase-3 daily scheduler check.
    """
    table = get_costs()
    if not table.updated_at:
        return True
    try:
        updated = datetime.fromisoformat(table.updated_at)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - updated
    return age.days > threshold_days


# ── JSON-serialisation helpers (so route handlers can return dataclasses) ────


def to_dict(obj) -> dict:
    """Wrapper around dataclasses.asdict that recursively unwraps
    nested dataclasses (TokenRate, FileCost, etc.)."""
    return asdict(obj)
