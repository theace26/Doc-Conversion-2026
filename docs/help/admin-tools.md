# Administration

The Admin panel is the control center for your MarkFlow installation. It gives you
a bird's-eye view of the entire repository, tools for database maintenance, API key
management for integrations, and resource controls that let you tune how MarkFlow
uses your server's hardware.

You can reach it from the navigation bar by clicking **Admin**. This page is only
visible to users with the **Admin** role.

---

## Repository Overview

The top of the Admin page is a live dashboard of your MarkFlow repository. It
opens with a row of large KPI cards that give you the numbers at a glance:

| Card | What It Shows |
|------|---------------|
| Total Files Scanned | Every file the bulk scanner has ever encountered |
| Successfully Converted | Files that produced a valid Markdown output |
| Unrecognized Files | Files MarkFlow found but has no handler for (e.g. `.exe`, `.mp4`) |
| Failed Conversions | Files where conversion was attempted but errored out |
| OCR Needs Review | Scanned PDFs whose OCR confidence fell below your threshold |
| Pending Conversion | Files queued but not yet processed |

Below the KPI cards you will find detail panels:

- **File Status Breakdown** -- a table with the same status categories and
  percentage bars so you can see proportions.
- **Lifecycle Status** -- how many files are active, marked for deletion, or
  sitting in the trash. Includes a link to the [Trash management page](/trash.html).
- **Conversion Activity** -- success rate, conversions in the last 24 hours and
  7 days, and your top converted formats (DOCX, PDF, etc.).
- **OCR Review Queue** -- pending vs. resolved flag counts, with a link to the
  [OCR Review page](/review.html).
- **Unrecognized File Types** -- breakdown by category (video, audio, archive, etc.).
- **Search Index (Meilisearch)** -- whether the search engine is online, plus
  document and Adobe file counts.
- **LLM Provider** -- which AI provider is active (if any), with a link to the
  [Providers page](/providers.html).
- **Scheduled Jobs** -- next run times for the lifecycle scan, trash expiry, and
  database compaction.
- **Recent Conversion Errors** -- the last 10 failures with filename, format,
  error message, and timestamp.

Click the **Refresh** button in the section header to reload the dashboard data.

> **Tip:** The Repository Overview is a great starting point when something seems
> wrong. If the Failed count is climbing, check the Recent Errors table first --
> it will usually point you to the root cause.

---

## Disk Usage

Below the Repository Overview you will find the **Disk Usage** section. It shows
how much storage MarkFlow is consuming, broken down by component:

| Component | Description |
|-----------|-------------|
| Output Repository | The converted Markdown knowledge base |
| Trash | Soft-deleted files awaiting purge |
| Conversion Output | Single-file conversion results from the Upload page |
| Database | The SQLite database file plus its write-ahead log (WAL) |
| Logs | Operational and debug log files |
| Meilisearch Data | The full-text search index |

At the top of the section, two progress bars show overall volume usage and what
share of that volume MarkFlow occupies. Each component gets its own card with
the size in human-readable units and a file count where applicable.

> **Warning:** The disk usage scan walks every directory and can take several
> seconds on large repositories. It does not refresh automatically -- click
> **Refresh** when you need an update.

Cards with a yellow border indicate a potential concern. For example, if the
Trash grows past 1 GB, its card is highlighted so you know it may be time to
empty it.

---

## Database Tools

The **Database Tools** section gives you three maintenance actions for the
MarkFlow SQLite database. For a more detailed dashboard, visit the
[DB Health page](/db-health.html).

### Health Check (fast)

Runs a quick structural check. It verifies the WAL file size, confirms the
schema is intact, and reports row counts for the major tables. This completes
in under a second and is safe to run at any time.

### Integrity Check (slow)

Performs a full content verification using SQLite's built-in `PRAGMA
integrity_check`. This reads every page of the database and can take 30 seconds
or longer on large files. Use it when you suspect data corruption -- for
example, after an unexpected container shutdown.

### Repair Database (destructive)

This is the nuclear option. It dumps the entire database to SQL, creates a
backup of the original (saved as `.db.bak`), and restores from the dump into
a fresh file. You must stop all running jobs before this will execute.

> **Warning:** The Repair action acquires an exclusive lock on the database.
> All in-flight API requests will wait until the repair finishes. Never run
> this during active conversions. The button will ask you to confirm before
> proceeding.

---

## API Key Management

API keys allow external systems -- primarily UnionCore -- to authenticate
with MarkFlow's API without using JWT tokens. Keys are service accounts that
always receive the `search_user` role, which means they can search and read
documents but cannot start conversions or change settings.

### Generating a Key

1. Type a descriptive label in the text field (e.g. `unioncore-prod` or
   `staging-cowork-bot`).
2. Click **Generate New Key**.
3. A green banner appears with the raw key. It starts with `mf_` followed by
   a long random string.

> **Warning:** The raw key is shown exactly once. Copy it immediately. If you
> lose it, there is no way to recover it -- you will need to generate a new
> one and revoke the old one.

### Copying and Distributing

Click the **Copy** button next to the key to put it on your clipboard. Paste
it into the consuming system's configuration (e.g., UnionCore's MarkFlow
connection settings).

### The Keys Table

The table below the generate form shows every key that has been created:

| Column | Meaning |
|--------|---------|
| Label | The friendly name you gave it |
| Key ID | A truncated identifier (not the key itself) |
| Created | When it was generated |
| Last Used | The most recent API call made with this key |
| Status | Active or Revoked |

### Revoking a Key

Click **Revoke** on any active key. You will be asked to confirm. Once
revoked, the key immediately stops working -- any system still using it
will start receiving `401 Unauthorized` responses.

Revocation is permanent. You cannot reactivate a revoked key.

---

## Resource Controls

The Resource Controls section (inside the Task Manager area) lets you tune
how MarkFlow uses your server's CPU and memory. These settings take effect
at different times:

### Worker Count

Sets how many files are converted in parallel during bulk jobs. The default
is 4. Increasing this speeds up large bulk runs but uses more CPU and
memory. The new value takes effect on the **next** bulk job start -- it does
not change a job that is already running.

Valid range: 1 to 32.

### Process Priority

Controls the OS-level scheduling priority of the MarkFlow process:

| Setting | Effect |
|---------|--------|
| Low | Yields CPU to other processes on the server |
| Normal | Default operating system scheduling |
| High | Prioritizes MarkFlow over other processes (may require root) |

This takes effect immediately.

> **Tip:** If MarkFlow shares its host with other services, set priority to
> **Low** during business hours and **Normal** overnight when conversions
> typically run unattended.

### CPU Core Pinning

Check or uncheck individual CPU cores to control which cores MarkFlow is
allowed to use. When "Use all available cores" is checked, MarkFlow can
run on any core. Pinning to specific cores is useful when you want to
reserve some cores for other applications.

This takes effect immediately, but note that core pinning is not supported
on all platforms. If it cannot be applied, MarkFlow will log a warning and
continue using all cores.

Click **Apply Changes** to save your selections. A confirmation message
appears briefly to let you know the settings were applied.

---

## Log Management

Two admin pages, linked from the Admin panel's **Log Management**
card, give you full control over MarkFlow's structured log files.

### Inventory page (`/log-management.html`)

A table of every log file currently on disk under `/app/logs`,
including the legacy `archive/` subdir. Each row shows:

- **File name** (active log, rotated backup, or compressed archive)
- **Size** in KB
- **Status pill** -- Active (currently being written), Rotated
  (numbered backup pending compression), or Compressed
  (`.gz` / `.tar.gz` / `.7z`)
- **Stream** -- Operational, Debug, or Other
- **Modified** timestamp

Top-bar actions:

- **Download** any file directly via its row link.
- **Multi-select + Download Selected (N)** bundles your picks
  into a single ZIP for offline review.
- **Download All** zips every log on disk.
- **Compress Rotated Now** triggers an immediate compression
  pass using your current Settings format. Useful right after a
  large bulk job rotates a debug log to dozens of MB.
- **Apply Retention Now** deletes compressed logs older than
  your retention window without waiting for the cron.

Settings card on the same page:

| Setting | Effect |
|---------|--------|
| Compression format | `gz` (default), `tar.gz`, or `7z`. As of v0.31.0 the cron honours this — earlier versions ignored it for the automated cycle. |
| Retention days | Compressed logs older than this are auto-purged on the cron. |
| Rotation max size MB | Active log file size at which the stdlib RotatingFileHandler triggers a rotation. Takes effect on next container restart. |
| 7z search byte cap (MB) | (v0.31.1) Per-reader decompressed-byte cap when searching `.7z` archives. Default 200 MB. Range 1-4096. Bounds how much of a `.7z` log the history search reads before truncating. **Examples** below. |

#### Sizing the `.7z` search byte cap

The cap exists to keep a runaway search from pinning a worker
thread for hours on a deliberately-pathological archive. The
default 200 MB is conservative; raise it if you regularly
investigate large archives.

| Host & archive shape | Recommended cap |
|---|---|
| Workstation with 64 GB RAM, typical archive < 200 MB | 200 (default) |
| Same workstation, archives 500-800 MB compressed | 1024 |
| VM with 8 GB RAM, occasional small archives | 200 |
| VM with 4 GB RAM, search competes with bulk worker | 100 |
| One-time deep dive into one huge archive | 4096 (then drop back) |

The UI gives live feedback as you type:

- **Below 1024 MB** → neutral hint with the value-as-applied
- **Above 1024 MB** OR **above 50% of currently-free RAM** → amber
  warning with the reasons
- **Above 4096 MB** → red "above hard limit" error (the backend
  rejects this with HTTP 400)

When a search truncates because the cap fired, the viewer's
status line reads `reader: 7z stream truncated at NNN MB` so
you know exactly what knob to turn next.

#### Host resource snapshot

Below the Settings inputs, a one-shot snapshot row shows your
host's actual specs. Refresh the page to refresh the numbers.

```
Host: Intel(R) Xeon(R) Silver 4214R (24 cores) - 32.0 GB total / 14.7 GB free - load 0.42 / 0.51 / 0.48
```

The fields are read from `/proc/cpuinfo`, `/proc/meminfo`, and
`os.getloadavg()`. The CPU model + total/free RAM are the most
load-bearing for sizing the byte cap; the load averages are
informational. (A future release will poll the snapshot
periodically and use it to estimate ETA on long-running
searches and bulk jobs.)

> **Tip:** The 6-hourly cron runs `compress_rotated_logs()` then
> `apply_retention()` automatically. If a rotated log is sitting
> uncompressed for hours and you can't wait, click **Compress
> Rotated Now**. That call is identical in effect to the cron
> body — same code path.

### Live viewer (`/log-viewer.html`) — v0.31.0 multi-tab edition

A power-user log inspector with **two modes** and **multiple
simultaneous tabs**.

#### Modes

- **Live tail** -- Server-Sent Events stream. Each new line
  appended to the file is pushed to the page in real time.
  Connection backfills the last ~200 lines so you don't open to
  a blank screen. The connection-state dot on each tab is green
  when connected, red when disconnected, grey while connecting.
  *Active uncompressed `.log` files only — compressed files
  return HTTP 400 (they don't grow, so tailing makes no sense).*
- **Search history** -- Server-side paginated search.
  Substring or regex query, level filter chips
  (DEBUG / INFO / WARNING / ERROR+CRITICAL), 200 lines per page,
  **Load older** for pagination.
  *Works on uncompressed AND `.gz` / `.tar.gz` AND `.7z` files
  (v0.31.0). Gzip streams are decompressed transparently via
  Python's stdlib; `.7z` archives are decompressed via the
  already-installed `7z` system binary streamed to stdout
  without writing a temp file. When opening a compressed file
  the viewer auto-switches to history mode (live tail can't
  follow a file that doesn't grow).*

##### Headless safety caps

The search request has a **triple-barrier defense** so an
unattended cron-style operation cannot hang on a malicious or
pathological log:

1. **Line cap** (500,000 lines) — bounds CPU on big files.
2. **Wall-clock cap** (60 seconds) — bounds time even when
   reads are cheap-per-line but the file is huge.
3. **`.7z` byte cap** (200 MB decompressed inside
   `_SevenZReader`) — bounds the worst-case worker-thread time
   on a deliberately huge archive. The 7z subprocess is launched
   in its own session so the cap-fire path can `SIGTERM` the
   whole process group cleanly.

When any cap fires, the response includes the partial results
plus a status line indicator. You'll see:

- `line cap hit` — narrow your search, tighten the filter chips,
  or shrink the time range.
- `time cap hit` — same advice; also consider opening the
  uncompressed counterpart if you're searching an archive.
- `7z stream truncated at NNN MB` — the archive is bigger than
  the in-process decompression budget. As of **v0.31.1** the cap
  is operator-tunable from the Settings card (default 200 MB,
  hard max 4096 MB; see "Sizing the .7z search byte cap" below).
  If you've already set the cap to its hard max and still hit
  this, download the archive and use a desktop tool for
  full-file work.

##### ETA estimates (new in v0.31.5)

Above the search controls in history mode, you'll see an ETA
hint like **"ETA: estimated 1.4s (12 prior obs)"** once the
estimator has seen 3+ searches against this archive's format
bucket (gzip vs 7z vs plain `.log` — they decompress at very
different speeds, so they're tracked separately).

The estimate is based on **actual throughput observed on your
hardware** during recent searches, not a static benchmark. It
uses an exponentially-weighted moving average — the most
recent 30% weighting on each new observation, so the estimator
adapts quickly to host changes (RAM upgrade, SSD migration,
container under heavy bulk-job load, etc.) over the next
handful of searches.

Confidence tiers:

| Observations | Phrasing | Meaning |
|--------------|----------|---------|
| `<3` | hint absent | not enough data yet |
| `3-9` | "estimated ~Xs" | low confidence (squiggle) |
| `10-49` | "estimated Xs" | medium confidence |
| `50+` | "expected Xs" | high confidence |

Searches that bail at the line cap or wall-clock cap are NOT
counted toward the estimate — those ran out of budget before
finishing the work they would have done, and would skew the
math toward "infinitely slow."

For deeper diagnostics: `GET /api/logs/eta/stats` returns the
observation count + EWMA throughput per operation key. The same
endpoint accepts `?op=log_search_gz` (or another op key) to drop
in a trailing-20-entry history sample for that bucket.

#### Tabbed view (new in v0.31.0)

The viewer now supports watching **multiple log streams
side-by-side** without losing state when you switch between them.

- The tab strip below the controls shows every open log, each
  with a connection-state dot, the file name, and a `×` close
  button.
- Click **+ Add tab** to open a popover listing all available
  logs. Click any one to open it in a new tab. Already-open logs
  are greyed out with a `✓ open` marker.
- Each tab keeps its own EventSource open in the background, so
  events don't get lost while you watch a different tab. (Body
  contents are capped at 1000 lines per tab so memory stays
  bounded — older lines drop off the head.)
- **Filters apply to the active tab only.** Switching tabs
  syncs the top control bar (mode, level chips, search box,
  time range, pause button) to that tab's stored state. So you
  can have a markflow.log tab filtered to ERROR only AND a
  markflow-debug.log tab showing everything — independently.
- Open tabs and per-tab filter state persist to `localStorage`.
  Refresh the page and your layout is restored.

##### Example workflow

1. Open `/log-viewer.html`. The most-recent log auto-opens in
   the first tab.
2. Click **+ Add tab**, pick `markflow-debug.log`. Two tabs
   now run in parallel.
3. Switch to the markflow.log tab, set mode → **Live tail**,
   uncheck DEBUG / INFO so you see only WARNING+.
4. Switch to markflow-debug.log, leave it on Live tail with
   all levels enabled.
5. Trigger the operation you're investigating. Both tabs
   accumulate events. Flip between them as needed — neither
   loses its state.

#### Time-range filter (history mode, new in v0.31.0)

When the active tab is in **Search history** mode, a second row
of controls appears with two `<input type="datetime-local">`
fields (From / To) plus four preset chips:

| Preset | Effect |
|--------|--------|
| Last hour | From = now − 1h, To = now |
| Last 24h | From = now − 24h, To = now |
| Last 7d | From = now − 7d, To = now |
| Clear range | Empties both inputs |

The inputs use your local timezone; values are converted to UTC
ISO before being sent to the server. The hint text next to the
chips shows the active From/To as ISO so you can verify exactly
what's being queried. Backend search supports flexible ISO
parsing — naive timestamps are treated as UTC.

#### Other features

- **Auto-scroll** chip auto-pins to the bottom on new lines.
  Uncheck to scroll freely without losing your place.
- **Pause** suspends new-line append on the active tab without
  closing the SSE stream. Resume picks up from where the buffer
  left off.
- **JSON-aware line parsing.** Structlog output (one JSON object
  per line) is rendered with colored timestamp / level / logger /
  event / k=v tail. Plain-text lines render verbatim.
- **Substring + regex search.** Toggle the **Regex** chip to
  switch from case-insensitive substring match to a regex.
  Invalid regex shows an error banner without breaking the page.
- **Live search spinner** (v0.31.1). When you click **Apply** in
  history mode, the status line shows a spinning indicator + the
  ticking elapsed time (e.g. `⟳ Searching markflow.log.5.7z ...
  3.2s`). Once the response lands the spinner clears and the
  existing returned/scanned/wall-clock summary takes over. This
  is most useful on `.7z` archives, which can take 10+ seconds
  on multi-hundred-megabyte files because the entire stream
  flows through `7z e -so` before the search filter pass begins.

---

## Provider Spend (LLM costs) — v0.33.2

A new card on the Admin dashboard shows your **monthly LLM spend** at a
glance, plus a month-end projection so you can budget before the invoice
lands.

### What you see

```
Provider Spend (LLM costs)
$72.10  total this cycle
1.6M tokens · 1,199 files analyzed

By provider
  anthropic: $72.10 (100%)

April 2026 (cycle starts day 1) · day 27 of 30 · 3 days remaining
Projected at current pace: $80.11 by cycle end

[Set cycle start day →] [Edit rate table →]
```

The card auto-refreshes when you click **Refresh** at the top of the
Repository Overview section. If your loaded rate data is older than 90
days, an amber warning appears at the bottom of the card reminding you
to verify the rates against the providers' published pricing pages.

### Setting your billing cycle

The "this cycle" total is computed from a configurable start day, which
**should match your actual provider invoice date** to be useful. To
change it: open [Settings → Billing & Costs](/settings.html#billing-section)
and set **Billing cycle start day** to your invoice date (e.g. 15 if
your Anthropic bill closes on the 15th of the month). Default is 1
(calendar month).

### Worked example: budgeting for the next month

> Your operator analyzes about 500 photos a month at an average of 3,400
> tokens/photo on `claude-opus-4-6`. Per the rate table that's roughly
> 500 × 3,400 × ($45 / 1,000,000) = **$76.50/month**. Watch the
> **Projected at current pace** figure trend over the cycle to budget
> for next month — if you ramp from 500 to 800 photos in week 3, the
> projection updates each refresh and you see your bill grow before the
> invoice arrives.

### Per-batch cost on the Batch Management page

Click any batch on the [Batch Management](/batch-management.html) page to
expand it, and the file table is preceded by a **Cost Estimate** panel:

```
Cost Estimate                         10 files · 8 analyzed (actual) · 2 estimated

TOKENS                                COST (USD)
  Actual:    34,021 tokens              Actual:    $1.23
  Estimated:  8,505 tokens              Estimated: $0.31
  Total:     42,526 tokens              Total:     $1.54

Per-file average: 4,253 tokens · $0.154
Rate used: anthropic/claude-opus-4-7 ($15.00 in / $75.00 out per 1M, blended $45.00)

[Show per-file breakdown ▼]
```

Files that haven't been analyzed yet are extrapolated using the batch's
own per-file average; the breakdown table marks them with an "estimated"
pill so you can tell actuals from extrapolations.

---

## Programmatic API access (for external integrators)

All cost endpoints respect the same JWT / `X-API-Key` auth as the rest
of MarkFlow's API. External programs (IP2A, finance dashboards, custom
tooling) can pull the cost data directly. Rate-table reads need
**OPERATOR+** role; the rate-table reload mutation needs **ADMIN**.

### For operators (the simple version)

> "I have a separate program that needs to know what we're spending on
> LLM analysis. How do I plug it in?"

1. **Get an API key.** Open Admin → API Key Management, type a label
   like `ip2a-prod`, click **Generate New Key**. Copy the `mf_…` string
   that appears (shown once).
2. **Hand the key to the other program.** It goes in an HTTP header
   called `X-API-Key`.
3. **The other program calls MarkFlow.** The endpoints in the table
   below all return JSON. Pick whichever one matches what your program
   needs to know.
4. **MarkFlow logs the call** as an audit-trail event so admins can see
   what's hitting the cost API. Search the [Log Viewer](/log-viewer.html)
   with `?q=llm_cost` to see them.

### For developers (the technical version)

#### Auth header pattern

```
X-API-Key: mf_<your_generated_key>
```

…or, if your consumer holds a UnionCore JWT:

```
Authorization: Bearer <jwt>
```

Both work on every endpoint listed below. JWT tokens carry their role
inline; API keys are pinned to `search_user` role unless an admin
overrides them — which means **API keys cannot reach the cost endpoints
out of the box**, since cost reads require OPERATOR+. Generate a JWT
with the appropriate role for service-to-service integration, OR ask
your admin to provision an OPERATOR-role API key for your service.

#### Endpoint reference

| Method | Path | Role | Returns |
|--------|------|------|---------|
| GET    | `/api/admin/llm-costs`               | OPERATOR+ | full rate table JSON |
| POST   | `/api/admin/llm-costs/reload`        | ADMIN     | `{ok, schema_version, providers, total_rates}` |
| GET    | `/api/analysis/cost/file/{entry_id}` | OPERATOR+ | `CostEstimate` for one analysis row |
| GET    | `/api/analysis/cost/batch/{batch_id}` | OPERATOR+ | `BatchCostSummary` |
| GET    | `/api/analysis/cost/period`          | OPERATOR+ | `PeriodCostSummary` for the configured cycle |
| GET    | `/api/analysis/cost/period?days=N`   | OPERATOR+ | `PeriodCostSummary` for trailing N days (1-365) |
| GET    | `/api/analysis/cost/staleness`       | OPERATOR+ | `{is_stale, age_days, threshold_days, updated_at}` |

#### curl samples

```bash
# Show your full rate table (lets an external system mirror what
# rates MarkFlow is using, so cost calcs stay aligned)
curl -H "X-API-Key: $MARKFLOW_KEY" \
  http://markflow.local:8000/api/admin/llm-costs

# Show this cycle's running total (uses billing_cycle_start_day pref)
curl -H "X-API-Key: $MARKFLOW_KEY" \
  http://markflow.local:8000/api/analysis/cost/period

# Show last-7-days spend (ad-hoc trailing window)
curl -H "X-API-Key: $MARKFLOW_KEY" \
  'http://markflow.local:8000/api/analysis/cost/period?days=7'

# Cost for one specific batch
curl -H "X-API-Key: $MARKFLOW_KEY" \
  http://markflow.local:8000/api/analysis/cost/batch/6f1ef512abc

# Has the rate table gone stale?
curl -H "X-API-Key: $MARKFLOW_KEY" \
  http://markflow.local:8000/api/analysis/cost/staleness

# (admin-only) Re-read llm_costs.json from disk after editing it
curl -X POST -H "X-API-Key: $ADMIN_KEY" \
  http://markflow.local:8000/api/admin/llm-costs/reload
```

#### Python sample

```python
import os, requests

MF = os.environ["MARKFLOW_URL"]   # e.g. "http://markflow.local:8000"
KEY = os.environ["MARKFLOW_KEY"]
HEADERS = {"X-API-Key": KEY}

def current_cycle_total() -> dict:
    r = requests.get(f"{MF}/api/analysis/cost/period", headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def project_month_end() -> float:
    """Return the projected full-cycle USD cost at current pace."""
    return current_cycle_total()["projected_full_cycle_cost_usd"]

def trailing_week() -> float:
    r = requests.get(
        f"{MF}/api/analysis/cost/period",
        params={"days": 7},
        headers=HEADERS,
        timeout=10,
    )
    return r.json()["total_cost_usd"]

if __name__ == "__main__":
    p = current_cycle_total()
    print(f"Cycle: {p['cycle_label']}")
    print(f"Spent so far: ${p['total_cost_usd']:.2f}")
    print(f"Projected at cycle end: ${p['projected_full_cycle_cost_usd']:.2f}")
    print(f"Last 7 days: ${trailing_week():.2f}")
```

#### JavaScript / Node sample

```javascript
const MF = process.env.MARKFLOW_URL;
const KEY = process.env.MARKFLOW_KEY;

async function currentCycleSpend() {
  const r = await fetch(`${MF}/api/analysis/cost/period`, {
    headers: { 'X-API-Key': KEY },
  });
  if (!r.ok) throw new Error(`MarkFlow returned ${r.status}`);
  return r.json();
}

async function batchCost(batchId) {
  const r = await fetch(
    `${MF}/api/analysis/cost/batch/${encodeURIComponent(batchId)}`,
    { headers: { 'X-API-Key': KEY } },
  );
  if (!r.ok) throw new Error(`MarkFlow returned ${r.status}`);
  return r.json();
}

(async () => {
  const cycle = await currentCycleSpend();
  console.log(`This cycle: $${cycle.total_cost_usd.toFixed(2)}`);
  console.log(`Projected: $${cycle.projected_full_cycle_cost_usd.toFixed(2)}`);
  for (const [provider, usd] of Object.entries(cycle.by_provider)) {
    console.log(`  ${provider}: $${usd.toFixed(2)}`);
  }
})();
```

#### Response shapes

`GET /api/analysis/cost/period` returns:

```json
{
  "cycle_start_iso": "2026-04-01T00:00:00+00:00",
  "cycle_end_iso":   "2026-05-01T00:00:00+00:00",
  "cycle_label":     "April 2026 (cycle starts day 1)",
  "total_tokens":    1602202,
  "total_cost_usd":  72.09909,
  "by_provider":     { "anthropic": 72.09909 },
  "by_model":        { "anthropic/claude-opus-4-6": 72.09909 },
  "file_count":      1199,
  "days_into_cycle": 27,
  "days_total":      30,
  "days_remaining":  3,
  "projected_full_cycle_cost_usd": 80.1101,
  "rates_used": [
    { "provider": "anthropic", "model": "claude-opus-4-6",
      "input_per_million_usd": 15.0, "output_per_million_usd": 75.0,
      "cache_write_per_million_usd": 18.75, "cache_read_per_million_usd": 1.5,
      "notes": "Effective 2026-Q1; check source_url" }
  ]
}
```

`GET /api/analysis/cost/batch/{batch_id}` returns:

```json
{
  "batch_id": "6f1ef512abc",
  "total_files": 10,
  "files_with_tokens": 8,
  "files_estimated": 2,
  "actual_tokens": 34021,
  "estimated_tokens": 8505,
  "actual_cost_usd": 1.23,
  "estimated_cost_usd": 0.31,
  "total_cost_usd": 1.54,
  "per_file_avg_tokens": 4253.0,
  "per_file_avg_cost_usd": 0.154,
  "rates_used": [ /* TokenRate objects */ ],
  "files": [
    { "file_id": "abc...", "source_path": "/photos/a.jpg",
      "provider": "anthropic", "model": "claude-opus-4-7",
      "tokens_used": 4500, "cost_usd": 0.20, "estimated": false }
  ]
}
```

#### Audit trail

Every cost calculation emits a `llm_cost.computed` (or `llm_cost.no_rate`)
structured log line. To see every cost call from the past hour:

```bash
curl -H "X-API-Key: $KEY" \
  "http://markflow.local:8000/api/logs/search?q=llm_cost&hours=1"
```

…or open the [Log Viewer](/log-viewer.html?q=llm_cost.computed) with the
query pre-filled.

---

## System Info

At the bottom of the Admin page, the **System Info** card shows:

- **Version** -- the currently running MarkFlow version.
- **Auth Mode** -- either `JWT` (production) or `DEV_BYPASS` (local development).
- **Meilisearch** -- whether the search engine is reachable.
- **DB Size** -- the current database file size.
- **UnionCore Origin** -- the configured CORS origin for UnionCore integration.

If auth bypass is enabled, a yellow warning banner appears at the very top of
the Admin page as a reminder not to run in this mode in production.

---

## Related Articles

- [Resources & Monitoring](/help.html#resources-monitoring) -- CPU/memory charts
  and activity log
- [Status & Active Jobs](/help.html#status-page) -- monitoring running bulk jobs
- [Settings Reference](/help.html#settings-guide) -- every preference explained
- [Troubleshooting](/help.html#troubleshooting) -- common issues and fixes
