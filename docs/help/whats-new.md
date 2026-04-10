# What's New

Running changelog of user-visible MarkFlow changes. Most recent
versions on top. For internal engineering detail see
[`docs/version-history.md`](../version-history.md) in the repo.

---

## v0.23.5 — Search shortcuts + startup crash fix

**Ten new keyboard shortcuts on the Search page** for faster batch
work and mouse-free navigation:

- `/` — jump focus to the search box from anywhere
- `Alt + Shift + A` — toggle **AI Assist**
- `Alt + A` — select every visible result for batch download
- `Alt + C` — clear the batch selection
- `Alt + Shift + D` — download the selection as a ZIP
- `Alt + B` — trigger **Browse All**
- `Alt + R` — re-run the current search
- `Esc` — contextual close (preview → AI drawer → modal → selection → blur)
- `Alt + Click` on a result — download the original source file directly
- `Shift + Click` on a checkbox — range-select rows

The fastest "grab everything" workflow is now three combos:
`Alt+A`, `Alt+Shift+D`. See [Keyboard
Shortcuts](/help#keyboard-shortcuts) and [Search](/help#search) for
the full writeup.

**Startup crash fix.** Fixed a pair of coupled bugs that caused
startup crash loops after upgrading from earlier releases: migration
27 (bulk_files rebuild) was running with foreign-key enforcement
on, rejecting historical orphan rows, and the MCP container was
racing the main container on migrations. Migrations now disable FK
enforcement (standard SQLite practice) and MCP no longer runs
migrations at all — it polls for DB readiness and then starts.

---

## v0.23.4 — Settings page reorganization

The Settings page is now grouped into logical clusters instead of a
flat list of 21 sections.

- **Files and Locations** now groups: Password Recovery, File Flagging,
  Info, Storage Connections
- **Conversion Options** now groups: OCR, Path Safety
- **AI Options** now groups: Vision & Frame Description, Claude
  Integration (MCP), Transcription, AI-Assisted Search

Section names: *Locations* became *Files and Locations*, *Conversion*
became *Conversion Options*, *AI Enhancement* became *AI Options*.

See the updated [Settings Reference](/help#settings-guide) for the
new layout.

---

## v0.23.3 — Faster heavy actions, bulk restore, extension exclude

**UX responsiveness.** Empty-trash, search-index rebuild, DB
compaction, integrity check, and stale-data check now show live
progress instead of freezing the page. Empty-trash batches deletes in
chunks of 200 so it returns immediately and shows "Purging X / Y..."
until finished.

**Bulk restore.** A new **Restore All** button on the Trash page
restores every trashed file in one action with a progress counter.

**Extension exclude list.** New **Settings → Conversion Options →
Skip file extensions** preference. Enter a list of extensions (without
dots) to exclude from scanning. Example: `tmp`, `bak`, `log`.

---

## v0.23.2 — Critical bug fixes

Background fixes to bulk upsert, the scheduler, and vision MIME
detection. No user-facing changes; listed here for completeness.

---

## v0.23.1 — Database file handler

MarkFlow now extracts and summarizes common **database files** as
Markdown, including schema, sample rows, foreign keys, and indexes.

Supported:

- **SQLite** — `.sqlite`, `.db`, `.sqlite3`, `.s3db`
- **Microsoft Access** — `.mdb`, `.accdb`
- **dBase / FoxPro** — `.dbf`
- **QuickBooks** — `.qbb`, `.qbw` (best-effort; open in QuickBooks
  Desktop and export to IIF / CSV for full extraction)

Tunable via **Settings → Conversion Options → Database sample rows
per table** (default 25, max 1000). See the
[Database Files](/help#database-files) article for full details.

---

## v0.23.0 — Audit remediation: pool, pipeline hardening, vision fix

Internal hardening pass: dedicated DB connection pool, pipeline
stability improvements, and a vision MIME-detection fix. No
user-visible feature changes.

---

## v0.22.19 — Scan-time junk-file filter

The scanner now skips common junk files at scan time (e.g. `.DS_Store`,
`Thumbs.db`, editor backups). They no longer clutter Pipeline Files
or consume conversion slots.

---

## v0.22.18 — Production readiness sweep

Lifecycle / vision / Qdrant / LibreOffice hardening. Background work;
nothing new visible in the UI.

---

## v0.22.17 — Overnight rebuild self-healing

New overnight rebuild script that restarts unhealthy services,
recovers from stuck scans, and leaves the container in a clean state
by morning. Useful for unattended overnight bulk jobs.

---

## v0.22.13 — Active Connections widget

The Resources page shows a live count of active connections
(SSE streams, WebSockets, AI Assist streams) so you can see at a
glance how many browsers are currently streaming from MarkFlow.

---

## v0.22.11 — Per-provider "Use for AI Assist" opt-in

You can now choose a **specific provider** for AI Assist independent
of the image-scanner provider. On **Settings → Providers**, tick
**Use for AI Assist** on any Anthropic provider you want AI Assist to
use. If nothing is ticked, AI Assist falls back to whichever provider
is currently active for the image scanner.

Today AI Assist only supports **Anthropic** providers — if your opted-in
or active provider is OpenAI / Gemini / Ollama you'll see a clear
error on the search page telling you to opt in an Anthropic provider.

---

## v0.22.2 — Toggle switch redesign

All on/off toggles across the Settings and Admin pages were redesigned
for clearer state: dimmed grey track + dot when off, lit accent track
+ dot when on, "Enabled/Disabled" label next to the switch. No
functional change — just visibly easier to read.

---

## v0.22.0 — Hybrid Vector Search ⭐

**Biggest change in this cycle.** Search now blends traditional
keyword matching (Meilisearch) with **semantic / vector search**
(Qdrant) using Reciprocal Rank Fusion.

What this means in practice:

- You can search for **concepts**, not just exact words. Searching
  "budget overrun" also finds documents that talk about "cost
  exceeded plan" or "went over the estimate."
- **Natural-language questions** work. "What is the latest safety
  policy?" is automatically normalized — the question prefix is
  stripped, temporal intent ("latest") is detected and boosts recent
  documents.
- Exact-keyword search still works the same. If you type a filename
  or a specific phrase, keyword match stays dominant.
- When vector search is down or disabled, search silently falls back
  to keyword-only — you don't see an error.

See the updated [Search](/help#search) article for examples and
guidance on crafting good queries.

---

## v0.21.0 — AI-Assisted Search

New **AI Assist** toggle button next to the search bar. When enabled,
every search opens a side drawer that streams a Claude-generated
answer synthesizing the top results, with inline citations `[1]`,
`[2]`, `[3]` linking back to the source documents.

- Requires an Anthropic provider (see v0.22.11 above)
- Only the top 8 search results are fed to Claude as context
- Answers are grounded in your documents — no fabricated content
- Click any citation to jump directly to the source document
- **Document Expand** — on any individual result, ask Claude for a
  deeper analysis of that single document in the context of your
  original query

See [Search](/help#search) for worked examples.

---

## v0.20.3 — Handwriting recognition via LLM vision

When Tesseract OCR returns very low confidence on a page (garbage
words, low word score), MarkFlow now falls back to the active
**LLM vision provider** (Claude, GPT-4V, Gemini, Ollama) to transcribe
the page directly from the image.

- Configurable threshold: **Settings → OCR → handwriting confidence
  threshold** (default 40%)
- In unattended mode, the LLM transcription automatically replaces
  Tesseract's garbled output
- In review mode, both outputs are shown side by side so you can
  accept either
- Requires an active LLM vision provider — without one, handwritten
  pages are flagged for manual review as before

---

## v0.20.2 — Binary handler expansion (30+ file types)

The binary-file handler now recognizes 30+ additional formats for
cataloging purposes (font files, CAD files, compiled binaries, etc.).
They appear in the Unrecognized Files catalog with MIME detection
instead of being ignored. Also fixes a bulk-scan gap where HEIC/HEIF
images weren't being discovered.

---

## v0.20.1 — 20 new file format handlers

MarkFlow added full conversion support for 20 additional file formats
in one release. Notable additions:

- **Rich Text**: `.rtf`
- **OpenDocument**: `.odt`, `.ods`, `.odp`
- **Web & Data**: `.html`, `.htm`, `.xml`, `.epub`
- **Data & Config**: `.json`, `.yaml`, `.yml`, `.ini`, `.cfg`, `.conf`, `.properties`
- **Email**: `.eml`, `.msg` (with recursive attachment conversion)
- **Archives**: `.zip`, `.tar`, `.tar.gz`, `.7z`, `.rar`, `.cab`, `.iso`
- **Legacy Office**: `.doc`, `.docm`, `.wpd`, `.xls`, `.ppt`

See the format table on the Convert page for the full list.

---

## v0.20.0 — NFS mount support

You can now add and manage **NFS mounts** directly from the
Settings page without editing `docker-compose.yml`. Go to
**Settings → Files and Locations → Storage Connections** and add a
new mount with the server address, export path, and local mount
point. MarkFlow handles `mount` and persistence on container restart.

---

## Related

- [Getting Started](/help#getting-started)
- [Search](/help#search)
- [Settings Reference](/help#settings-guide)
