# Scheduler time-slot allocation

Canonical table of every scheduled job in MarkFlow. Update on every
job add/move (spec §17 P7).

All times are container-local (typically UTC). Trigger types: `Cron`
= specific time of day, `Interval` = fixed period from start.

| # | Line | Job ID | Trigger | Description |
|---|---|---|---|---|
| 1 | 664 | `collect_metrics` | Interval 120s | Resource metrics (CPU/RAM) |
| 2 | 676 | `check_stale_scans` | Interval 5min | Stale scan watchdog |
| 3 | 687 | `collect_disk_snapshot` | Interval 6h | Disk metrics snapshot |
| 4 | 697 | `purge_old_metrics` | Cron 03:00 daily | Purge old metrics rows |
| 5 | 706 | `lifecycle_scan` | Interval 45min | Run lifecycle scan (yields to bulk) |
| 6 | 715 | `trash_expiry` | Interval 1h | Move expired marks → trash |
| 7 | 724 | `purge_aged_trash` | Cron 04:00 daily | Permanent purge of aged trash |
| 8 | 734 | `db_compaction` | Cron Sun 02:00 | VACUUM |
| 9 | 743 | `db_integrity` | Cron Sun 02:15 | PRAGMA integrity_check |
| 10 | 752 | `stale_check` | Cron Sun 02:30 | Stale-data sweep |
| 11 | 762 | `auto_metrics_aggregation` | Cron :05 hourly | Hourly metrics aggregation |
| 12 | 771 | `deferred_conversion_runner` | Interval 15min | Backlog poller / deferred runs |
| 13 | 799 | `log_archive` | Interval 6h | Compress + retention sweep |
| 14 | 816 | `eta_system_spec_snapshot` | Interval 24h | ETA framework system spec snapshot |
| 15 | 827 | `pipeline_watchdog` | Interval 1h | Pipeline disabled watchdog + auto-reset |
| 16 | 837 | `flag_expiry` | Interval 1h | Expire flags past expires_at |
| 17 | 848 | `analysis_drain` | Interval 5min | Image-analysis queue drain |
| 18 | 860 | `bulk_files_self_correction` | Interval 6h | Phantom prune + cross-job dedup |
| 19 | 871 | `run_housekeeping` | Interval 2h | Dedup + optimize + conditional VACUUM |
| 20 | 882 | `mount_health` | Interval 5min | NFS/SMB share probe |
| 21 | 895 | `check_llm_costs_staleness` | Cron 03:30 daily | Warn if llm_costs.json stale |
| **22** | **NEW** | **`purge_old_active_ops`** | **Cron 03:50 daily** | **NEW v0.35.0 — delete finished ops > 7d** |

**Cron-time slots taken (avoid for new daily jobs):**
- Daily: 03:00, 03:30, **03:50** (new), 04:00
- Sunday-only: 02:00, 02:15, 02:30
- Hourly: :05

The 03:50 slot for `purge_old_active_ops` is 20 min after 03:30
(`check_llm_costs_staleness`) and 10 min before 04:00
(`purge_aged_trash`) — the largest gap available in the early-morning
cluster.

## Adding a new job

1. Find a slot with no neighboring conflicts (no other daily job
   within ±15 min in this table).
2. If your job runs longer than the inter-job gap, ensure it
   `yields to bulk` via `is_any_bulk_active()` (per gotcha P6).
3. Add a row to this table BEFORE adding the `scheduler.add_job(...)`
   call inside `start_scheduler()` in `core/scheduler.py`.
4. The `log.info("scheduler.started", jobs=...)` literal at
   `core/scheduler.py:906` is now self-counting via
   `len(scheduler.get_jobs())` (v0.35.0); no manual count to update.

## Why this exists

Pre-v0.35.0, scheduler times were scattered across `core/scheduler.py`
with no central reference. Recon §A.4 found that the existing
`jobs=19` log literal was already off-by-2 from the actual 21 jobs
registered, and the proposed v0.35.0 03:45 slot for active-ops purge
nearly collided with the 03:30 LLM-cost check. Moving to 03:50
preserved a 20-min gap. Without this table, future additions would
hit similar conflicts. See spec §17 P7.

A boot-time self-check that flags collisions automatically is
queued as a future ticket.
