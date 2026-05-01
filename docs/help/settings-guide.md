# Settings Reference

This article covers every setting in MarkFlow. If you can't find something,
use your browser's **Find** (Ctrl+F / Cmd+F) to search by keyword.

---

## Getting to Settings

Click your **avatar** (your initials or profile icon) in the top-right
corner of any page. A dropdown menu appears — click **Settings** to open
the settings overview.

> The old nav-bar Settings link is gone in v0.36.0. If you're used to
> clicking a link in the top navigation bar, look for your avatar instead.

---

## The Settings Overview

Settings opens to a **card grid** — one card per major section. Each card
shows the section name and who can access it.

Click any card to open that section's dedicated page. Every section page
has a **sidebar** on the left listing sub-sections. Click a sidebar item
to jump to that group of settings. When you make a change, a **Save bar**
appears at the bottom of the page — click **Save** to commit your changes
or **Discard** to abandon them.

### Who can see what

| Card | Minimum role required |
|------|-----------------------|
| Storage | Operator |
| Pipeline | Operator |
| AI Providers | Operator |
| Auth & Security | Admin |
| Notifications | Operator |
| DB Health | Admin |
| Log Management | Admin |

If a card doesn't appear on your overview, you don't have the required role.
Ask your administrator if you think that's a mistake.

---

## Storage

**URL:** `/settings/storage`

Everything about where MarkFlow reads files from and where it writes output.

### Source Locations

| Setting | What It Does |
|---------|--------------|
| Source paths | Paths MarkFlow scans for files. Add, edit, or remove paths here. |
| Check access | Verify MarkFlow can actually read each configured path. |

### Output Directory

| Setting | What It Does |
|---------|--------------|
| Output directory | Where converted Markdown files are written. |

### Excluded Paths

Prefix-match rules for directories you want MarkFlow to ignore.

| Setting | What It Does |
|---------|--------------|
| Excluded paths | Add a path prefix to skip it entirely during scanning. |

> **Important:** Adding an exclusion marks every file under that path for
> removal from the catalog. Those files enter a 36-hour grace period, then
> move to trash, then are permanently deleted after 60 days. See the
> [File Lifecycle](/help.html#file-lifecycle) article before excluding a
> large directory.

### Storage Connections

Mount remote filesystems (NFS shares, SMB/Windows shares, tiered NAS
volumes) without editing any Docker configuration files.

| Setting | What It Does |
|---------|--------------|
| Server address | Hostname or IP of the remote server |
| Export / share path | The path on the remote server to mount |
| Local mount point | Where MarkFlow sees the mount inside the container |
| Mount type | NFS or SMB |

MarkFlow handles the `mount` command and automatically re-mounts on
container restart. After adding a mount, use **Check access** under
Source Locations to confirm MarkFlow can read it.

---

## Pipeline

**URL:** `/settings/pipeline`

Controls the automated conversion pipeline — how MarkFlow discovers files
and converts them in the background.

### Pipeline Switch

| Setting | Default | What It Does |
|---------|---------|--------------|
| Pipeline enabled | On | Master switch. When off, no automatic conversion runs. |

> Turning this off does not stop a conversion that's already running. To
> stop an active job, use the Bulk page.

### Schedule

| Setting | Default | What It Does |
|---------|---------|--------------|
| Scanner enabled | On | Periodic scanning of source locations |
| Scan interval | 15 min | How often to check for new or changed files |
| Business hours | 06:00–18:00 | Scanner only runs during these hours on weekdays |
| Incremental scan | On | Skip directories whose modification time hasn't changed |
| Full walk every N scans | 5 | Force a complete directory walk every Nth scan |
| Startup delay | 5 min | How long to wait after container start before the first scan |

### Auto-Conversion

| Setting | Default | What It Does |
|---------|---------|--------------|
| Mode | Batch | How newly discovered files are converted: `batch`, `immediate`, or `off` |
| Batch size | 500 | Files per automatic batch |
| Workers | 4 | Parallel conversion workers |
| OCR threshold for auto-skip | 50 | Files below this OCR confidence score are skipped in auto-conversion |
| Max files per run | 0 | Cap on files converted per auto-conversion run (0 means no cap) |
| Auto-reset days | 3 | If the pipeline is disabled, automatically re-enable it after N days |

See the [Auto-Conversion](/help.html#auto-conversion) article for a full
explanation of the `batch`, `immediate`, and `off` modes.

### File Lifecycle

| Setting | Default | What It Does |
|---------|---------|--------------|
| Grace period | 36 hours | How long a missing file waits before moving to trash |
| Trash retention | 60 days | How long trashed files are kept before permanent deletion |
| Auto-purge aged trash | On | Master switch for the daily 04:00 auto-purge job |

> The daily auto-purge job runs at 04:00 local time and skips automatically
> if a bulk job is active. Turning off **Auto-purge aged trash** keeps trash
> indefinitely (useful if you want to review before permanent deletion).

---

## AI Providers

**URL:** `/settings/ai-providers`

Configure the LLM providers MarkFlow can use for AI features (OCR
correction, document summarization, heading inference, handwriting
transcription, and AI-assisted search).

### Provider List

The sidebar lists each provider you've added. Click one to view or edit
it. Supported provider types:

- **Anthropic** — Claude models (recommended for AI Assist)
- **OpenAI** — GPT and Whisper models
- **Gemini** — Google Gemini models
- **Ollama** — Local models running on your own hardware

### Adding or Editing a Provider

Click **Add Provider** (or select an existing provider from the sidebar)
to open the provider form.

| Field | What It Does |
|-------|--------------|
| Provider type | Anthropic, OpenAI, Gemini, or Ollama |
| API key | Your API key for the provider (stored encrypted) |
| Display name | A friendly name shown in dropdowns and logs |
| Is active | Whether this provider is available for use |
| Use for AI Assist | Route the AI-powered search answer drawer to this provider |
| Default model | Which model to use when no per-feature model is specified |

> **AI Assist note:** The **Use for AI Assist** checkbox is independent of
> the image-scanner provider. You can have one provider handle OCR/vision
> and a different one handle AI-assisted search. Only Anthropic providers
> support the AI Assist drawer today.

### AI Options

These settings appear under the main **AI Providers** sidebar section:

| Setting | Default | What It Does |
|---------|---------|--------------|
| OCR correction | Off | Use AI to clean up garbled OCR output |
| Summarize | Off | Generate a one-paragraph summary in each document's frontmatter |
| Heading inference | Off | Detect headings in PDFs that lack document structure |
| Enable AI Assist org-wide | On | Master switch for the AI answer drawer on the Search page |
| Max output tokens | 700 | Response length cap for AI Assist answers (about 380 words) |
| Max snippets fed to AI | 8 | How many top search results the AI sees when forming an answer |

### Vision & Frame Description

| Setting | Default | What It Does |
|---------|---------|--------------|
| Enrichment level | 2 | 1 = basic, 2 = standard, 3 = comprehensive |
| Frame limit | 50 | Max keyframes extracted per video |
| Save keyframes | Off | Keep extracted frame images on disk after processing |
| Vision provider | (uses active provider) | Provider used for image and video analysis |

### Transcription

| Setting | Default | What It Does |
|---------|---------|--------------|
| Whisper model | base | Local model size: `tiny`, `base`, `small`, `medium`, `large`. Larger = more accurate but slower. |
| Caption file extensions | `srt,vtt,sbv` | Caption files that are ingested automatically alongside media |
| Cloud fallback priority | (empty) | Order to try cloud providers if local Whisper is unavailable, e.g. `openai,gemini` |

### Claude Integration (MCP)

The Model Context Protocol server lets Claude Desktop (or any MCP client)
query your MarkFlow document index directly. It runs on port 8001.

| Setting | What It Does |
|---------|--------------|
| Enable MCP server | Start or stop the MCP endpoint |
| MCP auth token | Bearer token that clients must supply |
| Setup instructions | Expandable section with copy-paste config for Claude Desktop |

---

### Cost Dashboard

**URL:** `/settings/ai-providers/cost`

The Cost page gives you a clear view of what you're spending on LLM
providers. Access it by clicking **Cost** in the AI Providers sidebar.

#### Spend Tiles

At the top of the page you'll see spend summary tiles:

- **Spend today** — token costs accumulated since midnight local time
- **Spend this month** — costs since your billing cycle start day

If you have multiple active providers, the layout expands to show a tile
per provider.

#### Daily Spend Chart

A bar chart shows your daily LLM spend over the past 30 days, broken down
by provider. Hover over a bar to see the exact amount and which models
drove the cost.

#### CSV Rate Import

If your provider gives you a custom rate table (for example, enterprise
pricing that differs from the public list price), you can import it here.

Drag and drop a CSV file onto the import area, or click to browse. The
CSV must have these four columns (header row required):

| Column | Format | Example |
|--------|--------|---------|
| `provider` | Provider name (lowercase) | `anthropic` |
| `model` | Model ID as returned by the API | `claude-sonnet-4-6` |
| `input_per_1m` | Cost in USD per 1 million input tokens | `3.00` |
| `output_per_1m` | Cost in USD per 1 million output tokens | `15.00` |

After import, MarkFlow uses these rates for all future cost calculations.
Existing historical records are not retroactively updated.

#### Alert Thresholds

| Setting | What It Does |
|---------|--------------|
| Monthly spend alert | Send a notification when month-to-date spend crosses this dollar amount |
| Billing cycle start day | Day-of-month (1–28) when your provider's invoice cycle starts. Match your actual invoice date for an accurate running total. |

> Set **Billing cycle start day** to match when your provider closes its
> bill. For example, if your Anthropic invoice closes on the 15th, set this
> to 15. Capped at 28 to avoid February edge cases.

#### Per-Provider Rate Tables

Below the chart, each provider has an expandable table showing the current
model pricing that MarkFlow is using. This reflects either the built-in
defaults or your most recent CSV import.

---

## Auth & Security

**URL:** `/settings/auth`  **Admin only**

Security and access controls for the MarkFlow instance.

### JWT Settings

| Setting | What It Does |
|---------|--------------|
| JWT secret | The signing key for session tokens. Rotating this invalidates all active sessions. |
| Token expiry | How long a login session lasts before requiring re-authentication |
| Refresh token expiry | How long a "remember me" session lasts |

> **Warning:** After rotating the JWT secret, all users are logged out
> immediately. Plan for a low-traffic window.

### API Keys

| Setting | What It Does |
|---------|--------------|
| API keys | List of active API keys for machine-to-machine access. Create, rotate, or revoke keys here. |
| Key role | The role assigned to each key (Viewer, Operator, Admin) |
| Key expiry | Optional expiry date for a key |

### Session Config

| Setting | Default | What It Does |
|---------|---------|--------------|
| Max concurrent sessions per user | 5 | How many devices a single user can be signed in on at once |
| DEV_BYPASS_AUTH | false | Bypass authentication entirely (development only — must be false in production) |

---

## Notifications

**URL:** `/settings/notifications`

Configure where MarkFlow sends alerts and what triggers them.

### Alert Channels

| Setting | What It Does |
|---------|--------------|
| Email | SMTP settings for sending alert emails |
| Webhook | URL that receives a POST request on each alert event |
| Slack | Slack incoming webhook URL |

### Threshold Rules

| Setting | What It Does |
|---------|--------------|
| Rules list | Each rule specifies: trigger event, condition, channel(s) to notify |
| Common triggers | Bulk job failed, auto-conversion abort, LLM spend threshold crossed, OCR failure rate spike |

---

## DB Health

**URL:** `/settings/db-health`  **Admin only**

Database maintenance tools. Run these during low-traffic periods.

### Compact

SQLite's `VACUUM` command — reclaims space from deleted rows. Safe to run
at any time, but locks the database for several seconds on large databases.

### Integrity Check

Verifies the database file has no corruption. Returns "ok" or a list of
errors. Run this if you suspect storage issues or after an unexpected
container crash.

### Backup

| Setting | What It Does |
|---------|--------------|
| Download backup | Create a point-in-time snapshot of the database and download it as a file |
| Backup path | Optional — write the backup to a path inside the container instead of downloading |

### Restore

Upload a previously downloaded backup file. MarkFlow will stop the
pipeline, swap in the backup, run a quick integrity check, then restart.
Active jobs are aborted before restore begins.

> **Caution:** Restore is irreversible. Make sure you have a current backup
> of the database you're replacing before proceeding.

---

## Log Management

**URL:** `/settings/log-management`  **Admin only**

Control how verbose MarkFlow's logs are and how long they're kept.

### Log Levels

| Level | What Gets Logged |
|-------|-----------------|
| Normal | Warnings and errors only (recommended for production) |
| Elevated | Operational info — job starts/stops, file counts, scheduler events |
| Developer | Everything, including per-file debug traces and frontend click tracking |

> Turn Developer mode off when you're not actively debugging. It generates
> high log volume and enables frontend action tracking for every user.

### Retention

| Setting | Default | What It Does |
|---------|---------|--------------|
| Log retention days | 30 | Log files older than this are automatically deleted |

### Live Viewer

A link to the live log stream in your browser. Useful for watching what
MarkFlow is doing right now without SSH access.

### Export

Download a bundled ZIP of all current log files. Handy for sending to
support or archiving before a major change.

---

## Other Settings

Several settings live on section pages alongside related options. They don't
have their own top-level cards but are important to know about.

### OCR Confidence Thresholds
**Location:** Pipeline → Auto-Conversion sub-section

| Setting | Default | What It Does |
|---------|---------|--------------|
| Confidence threshold | 60 | Pages below this score are flagged for review |
| Unattended mode | Off | Auto-accepts all OCR output without flagging |
| OCR preprocessing | On | Deskew, contrast adjustment, noise reduction |
| Handwriting confidence threshold | 40 | Below this, the page image is sent to the vision provider for handwriting transcription |
| Force OCR by default | Off | New bulk jobs re-OCR every PDF page even if a text layer exists. Per-job override available on the Bulk page. |

### Password Recovery
**Location:** Storage → Password Recovery sub-section

| Setting | Default | What It Does |
|---------|---------|--------------|
| Dictionary attack | On | Try common passwords from the built-in wordlist |
| Brute-force | Off | Try all character combinations (can be slow for long passwords) |
| Brute-force max length | 6 | Longest password to attempt |
| Brute-force charset | Alphanumeric | Numeric, alpha, alphanumeric, or all printable characters |
| Recovery timeout | 300s | Maximum seconds per file before giving up |
| Reuse found passwords | On | Try passwords that worked on other files in the same batch |
| Use hashcat | On | GPU-accelerated cracking when available |
| Hashcat workload | 3 (High) | GPU intensity: 1 = Low, 2 = Default, 3 = High, 4 = Maximum |

### File Flagging
**Location:** Storage → File Flagging sub-section

| Setting | Default | What It Does |
|---------|---------|--------------|
| Flag webhook URL | (empty) | Optional webhook fired on every flag or unflag event |
| Default expiry days | 30 | How long a flag stays active before auto-expiring |

### Cloud Prefetch
**Location:** Pipeline → Cloud Prefetch sub-section

Background prefetch for cloud-synced source directories (OneDrive, Google
Drive, Dropbox, iCloud, tiered NAS with stubs).

| Setting | Default | What It Does |
|---------|---------|--------------|
| Cloud prefetch enabled | Off | Enable background prefetch of cloud placeholder files |
| Concurrency | 4 | How many prefetch workers run in parallel |
| Rate limit | 10/sec | Maximum files prefetched per second |
| Timeout | 120s | Maximum seconds to wait per file |
| Min size bytes | 0 | Skip files smaller than this size |

### Search Preview Hover
**Location:** Visible to all users via the Search page settings gear

| Setting | Default | What It Does |
|---------|---------|--------------|
| Hover preview | On | Show or hide the document preview popup on hover |
| Preview size | Medium | Small (320×240), Medium (480×360), or Large (640×480) |
| Hover delay | 400ms | How long to hover before the preview appears (100–2000 ms) |

> These are per-browser preferences, not global settings. Each user can
> configure their own hover behavior from the Search page.

### Fidelity Tiers
**Location:** Pipeline → Conversion sub-section

| Tier | What It Does |
|------|--------------|
| Tier 1 — Structure | Core content guaranteed (headings, paragraphs, tables, lists) |
| Tier 2 — Styles | Formatting preserved in a sidecar JSON file alongside the Markdown |
| Tier 3 — Original patch | Original file embedded or linked for full fidelity |

The active fidelity tier controls how much metadata is preserved during
conversion. Higher tiers produce larger output but preserve more of the
original document's appearance.

### Path Safety
**Location:** Pipeline → Conversion sub-section

| Setting | Default | What It Does |
|---------|---------|--------------|
| Max path length | 240 | Output paths longer than this are skipped with a `skip_reason` note |
| Collision strategy | rename | What to do when two files would produce the same output name: `rename`, `overwrite`, or `skip` |

### Advanced / Export & Import
**Location:** Any settings detail page → Advanced sub-section

| Setting | What It Does |
|---------|--------------|
| Reset to defaults | Restore all settings in this section to factory defaults (irreversible) |
| Export settings | Download a JSON snapshot of the current configuration |
| Import settings | Upload a previously exported JSON snapshot |

---

## Common Questions

**Where did my settings go? I used to see them all on one page.**

In v0.36.0 the single long settings page was split into dedicated pages
per section. Every setting still exists — it's just on its own page now.
Use your browser's **Find** on this article to locate a specific setting,
then navigate to the page listed next to it.

**Why can't I see the AI Providers card (or Auth & Security, DB Health,
or Log Management)?**

Those cards are hidden if your account doesn't have the required role.
AI Providers, Pipeline, Storage, and Notifications require the **Operator**
role. Auth & Security, DB Health, and Log Management require the **Admin**
role. Contact your MarkFlow administrator to request a role change.

**I changed a setting but nothing happened.**

Make sure you clicked **Save** in the save bar at the bottom of the page.
Changes are not applied until you save. If the save bar isn't visible,
your changes may not have been detected — try making the change again.

**Where is the "Expand All / Collapse All" button?**

That button was part of the old accordion layout. The new sidebar layout
doesn't need it — click any sidebar item to jump directly to that
sub-section.

**Where do I set the billing cycle start day?**

Go to **AI Providers → Cost** (click the Cost item in the AI Providers
sidebar). The billing cycle start day is in the Alert Thresholds section
of that page.

**How do I update LLM pricing rates?**

Go to **AI Providers → Cost** and use the CSV Rate Import tool to drag in
your rate table. The CSV needs four columns: `provider`, `model`,
`input_per_1m`, and `output_per_1m`.

---

## Related

- [What's New](/help.html#whats-new)
- [Getting Started](/help.html#getting-started)
- [Bulk Repository Conversion](/help.html#bulk-conversion)
- [Auto-Conversion](/help.html#auto-conversion)
- [LLM Provider Setup](/help.html#llm-providers)
- [Password-Protected Documents](/help.html#password-recovery)
- [Search](/help.html#search)
- [File Lifecycle](/help.html#file-lifecycle)
